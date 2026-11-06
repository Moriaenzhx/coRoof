"""Durable interactive reads, real domain execution with offline model transport."""

from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from threading import Event
from uuid import uuid4

import pytest
from alembic import command
from conftest import API
from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from test_agent_read import action, create, model, read_proposal
from test_knowledge import TEXT, cmd, publish
from test_knowledge import create as document

from app.core.auth import token_hash
from app.infrastructure.db import session_factory
from app.infrastructure.models import (
    AgentRun,
    AgentStep,
    AuthSession,
    Membership,
    ModelInvocation,
    WorkEvent,
    WorkItem,
    now,
)
from app.modules.agent import execution, runtime
from app.modules.agent.models import AgentExecution
from app.modules.agent.schemas import AdvanceInput
from app.modules.model_gateway.gateway import ModelGateway


def submit(api, **fields):
    return api.post(
        "/agent/runs/submit",
        {
            "question": "有哪些事项需要核实？",
            "idempotency_key": str(uuid4()),
            **fields,
        },
        202,
    )


def deliver():
    messages = []
    with session_factory()() as db:
        execution.dispatch(db, lambda *args: messages.append(args))
    for args in messages:
        with session_factory()() as db:
            execution.process(db, *args)
    return messages


def expire_execution(identifier, *, model_lease=False):
    with session_factory()() as db:
        row = db.get(AgentRun, identifier)
        job = execution.get(db, row)
        job.lease_until = now() - timedelta(seconds=1)
        if model_lease:
            row.lease_expires_at = now() - timedelta(seconds=1)
        db.commit()


def test_submit_is_atomic_idempotent_and_refresh_does_not_advance(loop, monkeypatch):
    boss, employee, org, *_ = loop
    calls = model(monkeypatch)
    with session_factory()() as db:
        before = db.scalar(select(func.count()).select_from(WorkEvent))
    key = str(uuid4())
    row = submit(boss, idempotency_key=key)
    assert row["state"] == "ready" and row["execution"]["state"] == "queued"
    assert submit(boss, idempotency_key=key) == row and calls == []
    assert boss.get("/agent/runs/active") == [row]
    assert employee.get("/agent/runs/active") == []
    assert (
        boss.post(f"/agent/runs/{row['id']}/advance", action(row), 409)["error"]["code"]
        == "execution_managed"
    )
    foreign = API("foreign-execution@example.com")
    foreign.org()
    assert foreign.get("/agent/runs/active") == []
    foreign.get(f"/agent/runs/{row['id']}", 404)
    first = deliver()
    refreshed = boss.get(f"/agent/runs/{row['id']}")
    assert refreshed["state"] == "ready" and refreshed["step_count"] == 1 and len(calls) == 1
    assert refreshed["execution"]["state"] == "queued"
    for args in first:
        with session_factory()() as db:
            execution.process(db, *args)
    assert len(calls) == 1
    deliver()
    completed = boss.get(f"/agent/runs/{row['id']}")
    assert completed["state"] == "completed" and completed["step_count"] == 2
    assert completed["execution"]["state"] == "stopped" and len(calls) == 2
    assert submit(boss, idempotency_key=key) == completed
    assert boss.get("/agent/runs/active") == []
    with session_factory()() as db:
        assert db.scalar(select(func.count()).select_from(AgentExecution)) == 1
        assert db.scalar(select(func.count()).select_from(ModelInvocation)) == 2
        assert db.scalar(select(func.count()).select_from(WorkEvent)) == before
        assert db.scalars(select(AgentExecution)).one().organization_id == org["id"]


def test_failed_intent_commit_does_not_leave_an_unmanaged_run(loop, monkeypatch):
    boss = loop[0]
    original = Session.flush

    def reject_intent(db, *args, **kwargs):
        if any(isinstance(row, AgentExecution) for row in db.new):
            raise RuntimeError("synthetic execution commit failure")
        return original(db, *args, **kwargs)

    monkeypatch.setattr(Session, "flush", reject_intent)
    with pytest.raises(RuntimeError, match="synthetic execution"):
        submit(boss)
    with session_factory()() as db:
        assert db.scalar(select(func.count()).select_from(AgentRun)) == 0


def test_broker_failure_and_ambiguous_delivery_reuse_same_generation(loop, monkeypatch):
    boss = loop[0]
    calls = model(monkeypatch)
    row = submit(boss)
    messages = []

    def unavailable(*args):
        messages.append(args)
        raise ConnectionError("synthetic broker failure after delivery")

    with session_factory()() as db:
        assert execution.dispatch(db, unavailable) == 0
        job = execution.get(db, db.get(AgentRun, row["id"]))
        assert job.state == "queued"
        job.available_at = now() - timedelta(seconds=1)
        db.commit()
        assert execution.dispatch(db, lambda *args: messages.append(args)) == 1
    assert messages[0] == messages[1]
    for args in messages:
        with session_factory()() as db:
            execution.process(db, *args)
    assert len(calls) == 1
    assert boss.get(f"/agent/runs/{row['id']}")["step_count"] == 1


def test_queued_cancel_prevents_delivery_and_submission_cannot_restart(loop, monkeypatch):
    boss = loop[0]
    calls = model(monkeypatch)
    key = str(uuid4())
    row = submit(boss, idempotency_key=key)
    cancelled = boss.post(f"/agent/runs/{row['id']}/cancel", {"expected_version": row["version"]})
    assert cancelled["execution"]["state"] == "stopped"
    assert submit(boss, idempotency_key=key)["state"] == "cancelled"
    assert deliver() == [] and calls == []
    with session_factory()() as db:
        execution.process(db, loop[2]["id"], row["id"], 1)
    assert calls == []


@pytest.mark.parametrize("change", ["membership", "session", "work"])
def test_worker_revalidates_authority_before_call_and_active_hides_invalid_context(
    loop, monkeypatch, change
):
    boss, employee, org, _, member, work = loop
    calls = model(monkeypatch)
    row = submit(employee)
    with session_factory()() as db:
        if change == "membership":
            db.get(Membership, member["id"]).status = "inactive"
        elif change == "session":
            db.delete(
                db.get(AuthSession, token_hash(employee.client.cookies.get("coroof_session")))
            )
        else:
            db.get(WorkItem, work["id"]).owner_id = None
        db.commit()
    if change == "work":
        assert employee.get("/agent/runs/active") == []
    else:
        assert employee.request("GET", "/agent/runs/active").status_code in {401, 403}
    deliver()
    with session_factory()() as db:
        stored = db.get(AgentRun, row["id"])
        assert stored.state == "cancelled" and stored.answer is None
        assert execution.get(db, stored).state == "stopped"
        assert db.scalar(select(func.count()).select_from(ModelInvocation)) == 0
    assert calls == []
    assert boss.get("/agent/runs/active") == []


def test_source_revocation_between_background_rounds_stops_without_new_model(loop, monkeypatch):
    boss, employee, *_ = loop
    source = publish(boss, document(boss, visibility="organization"))
    calls = model(monkeypatch, lambda _: read_proposal("knowledge.search"))
    row = submit(employee, question="报销规定")
    deliver()
    assert len(calls) == 1
    boss.post(f"/knowledge/documents/{source['id']}/access", cmd(source, visibility="private"))
    assert employee.get("/agent/runs/active") == []
    deliver()
    with session_factory()() as db:
        stored = db.get(AgentRun, row["id"])
        assert stored.answer is None and stored.state == "cancelled"
        assert execution.get(db, stored).state == "stopped"
        assert db.scalars(select(AgentStep)).one().result is None
    assert len(calls) == 1


def test_retrieval_directory_and_parent_content_finish_without_model(loop, monkeypatch):
    boss = loop[0]
    publish(boss, document(boss, title="差旅报销制度"))

    def forbidden(*args):
        raise AssertionError("explicit source retrieval must never call a model")

    monkeypatch.setattr(ModelGateway, "generate", forbidden)
    parent = submit(boss, question="现在企业有哪些知识库？")
    deliver()
    parent = boss.get(f"/agent/runs/{parent['id']}")
    assert parent["answer"]["mode"] == "retrieval"
    child = submit(boss, question="里面写了什么？", parent_run_id=parent["id"])
    deliver()
    child = boss.get(f"/agent/runs/{child['id']}")
    assert child["answer"]["document_answers"][0]["quote"] == TEXT
    assert child["execution"]["state"] == "stopped"
    with session_factory()() as db:
        assert db.scalar(select(func.count()).select_from(ModelInvocation)) == 0


def test_worker_death_before_step_admission_can_recover_without_replaying_a_call(loop, monkeypatch):
    boss, _, org, *_ = loop
    calls = model(monkeypatch)
    row = submit(boss)
    with session_factory()() as db:
        old_token = execution.claim(db, org["id"], row["id"], 1)
    expire_execution(row["id"])
    with session_factory()() as db:
        assert execution.recover(db) == 1
        actor = db.get(Membership, db.get(AgentRun, row["id"]).actor_id)
        with pytest.raises(HTTPException) as stale:
            runtime.advance(
                db, actor, row["id"], AdvanceInput(**action(row)), execution_token=old_token
            )
        assert stale.value.detail["code"] == "execution_stale"
    deliver()
    assert len(calls) == 1


def test_unknown_model_call_is_not_replayed_until_explicit_resume(loop, monkeypatch):
    boss = loop[0]
    calls = model(monkeypatch)
    original = ModelGateway.generate

    def crash(*args):
        raise RuntimeError("synthetic worker death after quota admission")

    monkeypatch.setattr(ModelGateway, "generate", crash)
    row = submit(boss)
    with pytest.raises(RuntimeError, match="worker death"):
        deliver()
    expire_execution(row["id"], model_lease=True)
    with session_factory()() as db:
        assert execution.recover(db) == 1
        invocation = db.scalars(select(ModelInvocation)).one()
        charged = invocation.charged_tokens
        assert invocation.status == "unknown" and charged > 0
    interrupted = boss.get(f"/agent/runs/{row['id']}")
    assert interrupted["state"] == "interrupted" and interrupted["execution"]["state"] == "stopped"
    assert boss.get("/agent/runs/active")[0]["id"] == row["id"]
    assert deliver() == [] and calls == []
    monkeypatch.setattr(ModelGateway, "generate", original)
    resumed = boss.post(
        f"/agent/runs/{row['id']}/resume", {"expected_version": interrupted["version"]}
    )
    assert resumed["execution"]["state"] == "queued"
    deliver()
    assert len(calls) == 1
    with session_factory()() as db:
        unknown = db.scalar(select(ModelInvocation).where(ModelInvocation.status == "unknown"))
        assert unknown.charged_tokens == charged
        assert db.get(AgentRun, row["id"]).step_count == 2


def test_known_step_committed_before_worker_death_resumes_from_next_step(loop, monkeypatch):
    boss = loop[0]
    calls = model(monkeypatch)
    row = submit(boss)
    original = execution.requeue

    def crash(*args):
        raise RuntimeError("synthetic worker death after result commit")

    monkeypatch.setattr(execution, "requeue", crash)
    with pytest.raises(RuntimeError, match="result commit"):
        deliver()
    assert len(calls) == 1
    monkeypatch.setattr(execution, "requeue", original)
    expire_execution(row["id"])
    with session_factory()() as db:
        assert execution.recover(db) == 1
    deliver()
    completed = boss.get(f"/agent/runs/{row['id']}")
    assert completed["state"] == "completed" and len(calls) == 2
    assert len(calls[-1]["completed_reads"]) == 1


def test_cancel_during_background_call_prevents_result_and_following_step(loop, monkeypatch):
    boss = loop[0]
    target = {}

    def cancel(_):
        current = boss.get(f"/agent/runs/{target['id']}")
        boss.post(f"/agent/runs/{target['id']}/cancel", {"expected_version": current["version"]})
        return read_proposal()

    calls = model(monkeypatch, cancel)
    row = submit(boss)
    target["id"] = row["id"]
    deliver()
    stopped = boss.get(f"/agent/runs/{row['id']}")
    assert stopped["state"] == "cancelled" and stopped["answer"] is None
    assert stopped["execution"]["state"] == "stopped"
    assert deliver() == [] and len(calls) == 1


def test_queue_preserves_task_step_and_deadline_limits(loop, monkeypatch):
    boss, _, _, _, _, work = loop
    calls = model(monkeypatch)
    assert (
        boss.request(
            "POST",
            "/agent/runs/submit",
            {
                "task": "update_draft",
                "question": "整理进展",
                "work_item_id": work["id"],
                "idempotency_key": str(uuid4()),
            },
        ).status_code
        == 403
    )
    expired = submit(boss)
    exhausted = submit(boss)
    with session_factory()() as db:
        db.get(AgentRun, expired["id"]).deadline = now() - timedelta(seconds=1)
        db.get(AgentRun, exhausted["id"]).step_count = 6
        db.commit()
    deliver()
    for row in [expired, exhausted]:
        result = boss.get(f"/agent/runs/{row['id']}")
        assert result["state"] == "failed" and result["error_code"] == "budget_exceeded"
        assert result["execution"]["state"] == "stopped"
    assert calls == []


def test_duplicate_workers_admit_one_model_step_on_postgres(loop, monkeypatch):
    with session_factory()() as db:
        if db.get_bind().dialect.name != "postgresql":
            pytest.skip("PostgreSQL row locking required")
    boss, _, org, *_ = loop
    entered, release = Event(), Event()

    def waiting(_):
        entered.set()
        assert release.wait(10)
        return read_proposal()

    calls = model(monkeypatch, waiting)
    row = submit(boss)

    def run_once():
        with session_factory()() as db:
            execution.process(db, org["id"], row["id"], 1)

    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(run_once)
        assert entered.wait(10)
        try:
            pool.submit(run_once).result(timeout=5)
        finally:
            release.set()
        first.result(timeout=10)
    assert len(calls) == 1


def test_execution_migration_preserves_old_manual_runs_and_enforces_tenant_fk(loop, database):
    boss, _, org, *_ = loop
    row = create(boss)
    command.downgrade(database, "0017_agent_parent")
    command.upgrade(database, "head")
    assert boss.get(f"/agent/runs/{row['id']}")["execution"] is None
    foreign = API("other-execution-schema@example.com")
    other_org = foreign.org()
    with session_factory()() as db:
        db.add(AgentExecution(organization_id=other_org["id"], run_id=row["id"]))
        with pytest.raises(IntegrityError):
            db.commit()
        db.rollback()
    submitted = submit(boss)
    with pytest.raises(RuntimeError, match="agent_execution_data_exists"):
        command.downgrade(database, "0017_agent_parent")
    assert boss.get(f"/agent/runs/{submitted['id']}")["execution"]["state"] == "queued"
