"""Background graphs reuse the existing read loop under revocable, scoped server grants."""

from concurrent.futures import ThreadPoolExecutor
from threading import Event
from uuid import UUID, uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from test_agent_read import model, read_proposal
from test_watch_controls import action, actor_grant, create

from app.infrastructure.db import session_factory
from app.infrastructure.models import AgentRun, AnalysisRun, Membership, WorkEvent
from app.modules.agent import runtime
from app.modules.agent.schemas import AdvanceInput, RunInput


def background(db, policy, work, **fields):
    actor, grant = actor_grant(db, policy["id"])
    payload = RunInput(
        question="依据确认的交付目标核实此事项，提出需老板审阅的推进建议。",
        work_item_id=UUID(work["id"]),
        idempotency_key=uuid4(),
        **fields,
    )
    return actor, runtime.create(db, actor, payload, "", watch_grant_id=grant.id)


def step(db, actor, run):
    return runtime.advance(
        db, actor, run.id, AdvanceInput(expected_version=run.version, idempotency_key=uuid4())
    )


def test_background_graph_survives_browser_logout_and_uses_existing_read_loop(loop, monkeypatch):
    boss, _, _, depts, _, work = loop
    policy = create(boss, scope_kind="department", department_id=depts[0]["id"])
    calls = model(monkeypatch)
    with session_factory()() as db:
        actor, run = background(db, policy, work)
        before = db.scalar(select(func.count()).select_from(WorkEvent))
        db.rollback()
        assert boss.request("POST", "/auth/logout-all").status_code == 204
        run = step(db, actor, run)
        run = step(db, actor, run)
        assert run.state == "completed" and run.answer.suggestions[0].work_item_id == work["id"]
        assert len(calls) == 2
        stored = db.get(AgentRun, run.id)
        assert stored.watch_grant_id and stored.session_hash == ""
        assert db.scalar(select(func.count()).select_from(WorkEvent)) == before


def test_background_cannot_create_drafts_or_investigate_outside_granted_scope(loop, monkeypatch):
    boss, _, _, depts, _, work = loop
    other_work = boss.work(depts[1], title="范围外记录")
    policy = create(boss, scope_kind="department", department_id=depts[0]["id"])
    model(monkeypatch, lambda _: read_proposal("work.investigate", other_work["id"]))
    with session_factory()() as db:
        with pytest.raises(HTTPException):
            background(db, policy, work, task="update_draft")
        db.rollback()
        with pytest.raises(HTTPException):
            background(db, policy, other_work)
        db.rollback()
        actor, run = background(db, policy, work)
        with pytest.raises(HTTPException):
            step(db, actor, run)
        db.rollback()
        assert db.get(AgentRun, run.id).answer is None
    assert (
        boss.request(
            "POST",
            "/agent/runs",
            {
                "question": "forged grant",
                "work_item_id": work["id"],
                "idempotency_key": str(uuid4()),
                "watch_grant_id": str(uuid4()),
            },
        ).status_code
        == 422
    )


def test_revoking_watch_erases_completed_derived_answer(loop, monkeypatch):
    boss, _, _, _, _, work = loop
    policy = create(boss)
    model(monkeypatch)
    with session_factory()() as db:
        actor, run = background(db, policy, work)
        run = step(db, actor, run)
        run = step(db, actor, run)
        analysis_id = run.answer.id
        db.rollback()
    boss.post(f"/watch/policies/{policy['id']}/actions", action(policy, "pause"))
    with session_factory()() as db:
        stored = db.get(AgentRun, run.id)
        assert stored.state == "cancelled" and stored.answer is None
        assert db.get(AnalysisRun, analysis_id).result is None
        with pytest.raises(HTTPException):
            runtime.read(db, db.get(Membership, stored.actor_id), run.id)


def test_background_read_only_boundary_is_enforced_by_database(loop):
    policy = create(loop[0])
    with session_factory()() as db:
        _, run = background(db, policy, loop[-1])
        stored = db.get(AgentRun, run.id)
        stored.task = "update_draft"
        with pytest.raises(IntegrityError):
            db.commit()
        db.rollback()


def test_pg_revocation_during_model_io_rejects_late_output(loop, monkeypatch):
    if session_factory().kw["bind"].dialect.name != "postgresql":
        pytest.skip("PostgreSQL revoke during model I/O")
    boss = loop[0]
    policy = create(boss)
    started, release = Event(), Event()

    def choose(_):
        started.set()
        assert release.wait(5)
        return read_proposal()

    model(monkeypatch, choose)
    with session_factory()() as db:
        actor, run = background(db, policy, loop[-1])
        actor_id = actor.id

    def execute():
        with session_factory()() as db:
            with pytest.raises(HTTPException):
                step(db, db.get(Membership, actor_id), run)

    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(execute)
        assert started.wait(5)
        try:
            boss.post(f"/watch/policies/{policy['id']}/actions", action(policy, "pause"))
        finally:
            release.set()
        future.result(timeout=10)
    with session_factory()() as db:
        assert db.get(AgentRun, run.id).answer is None
