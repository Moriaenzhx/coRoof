"""Stage 3 acceptance exercises actual graphs, savers and domain transactions."""

from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from uuid import uuid4

import pytest
from conftest import API
from sqlalchemy import func, select, text
from sqlalchemy.exc import IntegrityError
from test_agent_read import action, advance, create, model

from app.infrastructure.db import session_factory
from app.infrastructure.models import AgentRun, Membership, UpdateDraft, WorkEvent, now
from app.modules.agent.approvals import thread_id
from app.modules.agent.checkpoints import saver


def draft_run(monkeypatch, api, work):
    model(
        monkeypatch,
        lambda _: {
            "summary": "资料已整理，需要交付协调",
            "lifecycle_status": "in_progress",
            "needs_support": True,
        },
    )
    row = create(api, work, task="update_draft", question="资料已整理，需要交付协调")
    return advance(api, row)


def event_count():
    with session_factory()() as db:
        return db.scalar(select(func.count()).select_from(WorkEvent))


def checkpoint(row, kind, target, revision):
    with session_factory()() as db:
        run = db.get(AgentRun, row["id"])
        tid = thread_id(run, kind, target, revision)
    with saver() as store:
        saved = store.get_tuple({"configurable": {"thread_id": tid}})
        assert saved is not None
        return saved


def decision_run(monkeypatch, api, work):
    model(monkeypatch)
    row = advance(api, create(api, work))
    row = advance(api, row)
    assert row["state"] == "completed"
    body = {
        "analysis_id": row["answer"]["id"],
        "work_item_id": work["id"],
        "idempotency_key": str(uuid4()),
    }
    decision = api.post("/decisions", body, 201)
    assert api.post("/decisions", body, 201)["id"] == decision["id"]
    return row, decision


def selection(decision):
    return {
        "expected_version": decision["version"],
        "selected_option": decision["options"][0]["id"],
        "selected_plan": "先与负责人核实资料",
        "follow_up": "沟通后补充结果",
    }


def test_model_draft_pauses_without_effect_then_author_edits_and_confirms_once(loop, monkeypatch):
    boss, employee, _, _, _, work = loop
    count = event_count()
    row = draft_run(monkeypatch, employee, work)
    draft = row["draft"]
    assert row["state"] == "completed" and row["answer"] is None
    assert draft["provider"] != "rules" and draft["state"] == "pending"
    assert event_count() == count
    assert any(
        write[1] == "__interrupt__"
        for write in checkpoint(row, "draft", draft["id"], 1).pending_writes
    )
    # Refresh from a fresh connection sees the draft, never re-calls the model.
    assert employee.get(f"/agent/runs/{row['id']}")["draft"]["id"] == draft["id"]
    boss.confirm(draft, 404)
    changed = employee.request(
        "PATCH",
        f"/work-updates/drafts/{draft['id']}",
        {
            "expected_revision": 1,
            "proposed_fields": {
                "summary": "本人核对后：资料正在整理",
                "lifecycle_status": "in_progress",
                "needs_support": False,
            },
        },
    ).json()
    assert changed["revision"] == 2
    employee.confirm(draft, 409)
    receipt = employee.confirm(changed)
    assert employee.confirm(changed)["id"] == receipt["id"]
    assert event_count() == count + 1
    current = employee.get(f"/work-items/{work['id']}")
    assert current["lifecycle_status"] == "in_progress" and not current["needs_support"]
    assert checkpoint(row, "draft", draft["id"], 2).checkpoint["channel_values"]["committed"]


def test_draft_preparation_and_step_are_idempotent(loop, monkeypatch):
    boss, _, _, _, _, work = loop
    calls = model(
        monkeypatch,
        lambda _: {"summary": "资料已整理", "lifecycle_status": None, "needs_support": None},
    )
    body = {
        "task": "update_draft",
        "work_item_id": work["id"],
        "question": "资料已整理",
        "idempotency_key": str(uuid4()),
    }
    row = boss.post("/agent/runs", body, 201)
    assert boss.post("/agent/runs", body, 201)["id"] == row["id"]
    step = action(row)
    row = advance(boss, row, step)
    assert advance(boss, row, step)["draft"]["id"] == row["draft"]["id"]
    assert len(calls) == 1


@pytest.mark.parametrize("change", ["work", "expiry", "reassignment", "session"])
def test_pending_draft_rechecks_freshness_and_authority(loop, monkeypatch, change):
    boss, employee, _, _, _, work = loop
    row = draft_run(monkeypatch, employee, work)
    draft = row["draft"]
    if change == "work":
        boss.post(
            f"/work-items/{work['id']}/updates",
            {
                "action": "progress",
                "expected_version": work["version"],
                "idempotency_key": str(uuid4()),
            },
        )
    elif change == "expiry":
        with session_factory()() as db:
            db.get(UpdateDraft, draft["id"]).expires_at = now() - timedelta(seconds=1)
            db.commit()
    elif change == "reassignment":
        assert (
            boss.request(
                "PATCH",
                f"/work-items/{work['id']}/assignment",
                {
                    "owner_id": None,
                    "expected_version": work["version"],
                    "idempotency_key": str(uuid4()),
                },
            ).status_code
            == 200
        )
    else:
        assert employee.request("POST", "/auth/logout").status_code == 204
    count = event_count()
    status = 401 if change == "session" else 404 if change == "reassignment" else 409
    employee.confirm(draft, status)
    assert event_count() == count


def test_checkpoint_recovery_after_business_commit_does_not_repeat_effect(loop, monkeypatch):
    from app.modules.work_items import api as commands

    _, employee, _, _, _, work = loop
    row = draft_run(monkeypatch, employee, work)
    count = event_count()
    original = commands.confirm_domain
    crashed = False

    def crash(*args):
        nonlocal crashed
        result = original(*args)
        if not crashed:
            crashed = True
            raise RuntimeError("synthetic_crash_after_business_commit")
        return result

    monkeypatch.setattr(commands, "confirm_domain", crash)
    with pytest.raises(RuntimeError, match="synthetic_crash"):
        employee.confirm(row["draft"])
    assert event_count() == count + 1
    assert employee.confirm(row["draft"])["draft_id"] == row["draft"]["id"]
    assert event_count() == count + 1


def test_agent_decision_uses_cited_analysis_author_confirmation_and_result(loop, monkeypatch):
    boss, employee, org, _, member, work = loop
    count = event_count()
    row, decision = decision_run(monkeypatch, boss, work)
    assert event_count() == count
    assert any(
        write[1] == "__interrupt__"
        for write in checkpoint(row, "decision", decision["id"], 1).pending_writes
    )
    with session_factory()() as db:
        db.get(Membership, member["id"]).roles = ["owner", "member"]
        db.commit()
    employee.post(f"/decisions/{decision['id']}/confirm", selection(decision), 404)
    assert (
        boss.post(f"/decisions/{decision['id']}/confirm", selection(decision))["state"]
        == "confirmed"
    )
    boss.post(f"/decisions/{decision['id']}/confirm", selection(decision))
    changed = {**selection(decision), "selected_plan": "改写历史"}
    boss.post(f"/decisions/{decision['id']}/confirm", changed, 409)
    result = {
        "observed_result": "已和负责人核实，尚缺补充资料",
        "idempotency_key": str(uuid4()),
        "evidence_refs": [decision["context_snapshot"]["evidence"]["id"]],
    }
    outcome = boss.post(f"/decisions/{decision['id']}/outcomes", result, 201)
    assert boss.post(f"/decisions/{decision['id']}/outcomes", result, 201)["id"] == outcome["id"]
    assert event_count() == count + 2
    assert boss.get(f"/work-items/{work['id']}")["version"] == work["version"]


def test_stale_agent_analysis_cannot_prepare_decision(loop, monkeypatch):
    boss, _, _, _, _, work = loop
    model(monkeypatch)
    row = advance(boss, create(boss, work))
    row = advance(boss, row)
    boss.post(
        f"/work-items/{work['id']}/updates",
        {
            "action": "progress",
            "expected_version": work["version"],
            "idempotency_key": str(uuid4()),
        },
    )
    boss.post(
        "/decisions",
        {
            "analysis_id": row["answer"]["id"],
            "work_item_id": work["id"],
            "idempotency_key": str(uuid4()),
        },
        409,
    )


def test_draft_references_enforce_tenant_and_model_cannot_self_approve(loop, monkeypatch):
    boss, _, org, _, _, work = loop
    row = draft_run(monkeypatch, boss, work)
    other = API("foreign-draft@example.com")
    other.org()
    foreign = other.draft(other.work(other.department()))
    other.get(f"/agent/runs/{row['id']}", 404)
    other.confirm(row["draft"], 404)
    with session_factory()() as db:
        with pytest.raises(IntegrityError):
            db.execute(
                text("UPDATE agent_runs SET draft_id=:draft WHERE id=:run"),
                {"draft": foreign["id"], "run": row["id"]},
            )
            db.flush()
        db.rollback()
    count = event_count()
    model(
        monkeypatch,
        lambda _: {
            "summary": "已批准",
            "lifecycle_status": "done",
            "needs_support": False,
            "approved": True,
        },
    )
    rejected = advance(boss, create(boss, work, task="update_draft"))
    assert rejected["state"] == "failed" and rejected["draft"] is None
    assert event_count() == count


def test_postgres_concurrent_confirmation_has_one_business_effect(loop, monkeypatch):
    with session_factory()() as db:
        if db.get_bind().dialect.name != "postgresql":
            pytest.skip("PostgreSQL concurrency acceptance required")
    _, employee, _, _, _, work = loop
    row = draft_run(monkeypatch, employee, work)
    count = event_count()

    def confirm(_):
        return employee.request(
            "POST",
            f"/work-updates/drafts/{row['draft']['id']}/confirm",
            {"expected_revision": row["draft"]["revision"]},
        )

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(confirm, range(2)))
    assert sorted(r.status_code for r in results) in ([200, 200], [200, 409])
    assert employee.confirm(row["draft"])["draft_id"] == row["draft"]["id"]
    assert event_count() == count + 1


def test_agent_decision_stale_work_and_correctable_choice(loop, monkeypatch):
    boss, _, _, _, _, work = loop
    _, decision = decision_run(monkeypatch, boss, work)
    boss.post(
        f"/decisions/{decision['id']}/confirm",
        {**selection(decision), "selected_option": "fake"},
        400,
    )
    boss.post(
        f"/work-items/{work['id']}/updates",
        {
            "action": "progress",
            "expected_version": work["version"],
            "idempotency_key": str(uuid4()),
        },
    )
    count = event_count()
    boss.post(f"/decisions/{decision['id']}/confirm", selection(decision), 409)
    assert event_count() == count


def test_migration_preserves_existing_read_graph_and_constraints(database, loop, monkeypatch):
    from alembic import command

    boss, _, _, _, _, work = loop
    model(monkeypatch)
    row = advance(boss, create(boss, work))
    with session_factory()() as db:
        checkpoint_count = db.scalar(text("SELECT count(*) FROM checkpoints"))
    command.downgrade(database, "0006_langgraph")
    command.upgrade(database, "head")
    command.check(database)
    assert boss.get(f"/agent/runs/{row['id']}")["step_count"] == 1
    with session_factory()() as db:
        assert db.scalar(text("SELECT count(*) FROM checkpoints")) == checkpoint_count
        with pytest.raises(IntegrityError):
            db.execute(
                text("UPDATE agent_runs SET step_count = 99 WHERE id = :id"), {"id": row["id"]}
            )
            db.flush()
        db.rollback()
