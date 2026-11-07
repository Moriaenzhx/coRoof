from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from threading import Event
from uuid import uuid4

import pytest
from alembic import command
from conftest import API
from fastapi.testclient import TestClient
from sqlalchemy import MetaData, Table, event, func, inspect, select, text
from sqlalchemy.exc import IntegrityError
from test_slice02 import ask, confirm_body, prepare, supported

from app.core.config import settings
from app.infrastructure.db import session_factory
from app.infrastructure.models import (
    AgentRun,
    AnalysisRun,
    DecisionOutcome,
    EvidenceSnapshot,
    UpdateDraft,
    WorkItem,
    now,
)
from app.main import app
from app.modules.watch.models import WatchWake


def confirmed(loop):
    boss, employee, org, depts, member, work = supported(loop)
    pending = prepare(boss, ask(boss, work), work)
    body = {**confirm_body(pending), "follow_up_at": (now() + timedelta(days=1)).isoformat()}
    decision = boss.post(f"/decisions/{pending['id']}/confirm", body)
    return boss, employee, org, depts, member, work, decision


def feedback(employee, work, decision, text="已经完成资料核对，仍需要支持核实一处差异"):
    return employee.post(
        "/work-updates/drafts",
        {"work_item_id": work["id"], "decision_id": decision["id"], "raw_text": text},
        201,
    )


def test_arrangement_feedback_is_explicit_scoped_and_does_not_change_work_state(loop):
    boss, employee, org, depts, member, work, decision = confirmed(loop)
    employee.get(f"/decisions/{decision['id']}", 403)
    path = f"/work-items/{work['id']}/arrangements"
    row = employee.get(path)["items"][0]
    assert set(row) == {
        "id",
        "work_item_id",
        "selected_plan",
        "follow_up",
        "follow_up_at",
        "confirmed_at",
        "feedback_count",
        "latest_feedback",
    }
    assert row["selected_plan"] == decision["selected_plan"]
    assert row["follow_up_at"] == decision["follow_up_at"]
    assert row["feedback_count"] == 0 and row["latest_feedback"] is None
    before = employee.get(f"/work-items/{work['id']}")
    with session_factory()() as db:
        analyses = db.scalar(select(func.count()).select_from(AnalysisRun))
    draft = feedback(employee, work, decision)
    assert draft["decision_id"] == decision["id"] and draft["provider"] == "manual_feedback"
    assert draft["proposed_fields"] == {
        "summary": draft["raw_text"],
        "lifecycle_status": None,
        "needs_support": None,
    }
    assert employee.get(f"/work-items/{work['id']}") == before
    assert boss.get(path)["items"][0]["feedback_count"] == 0
    boss.confirm(draft, 404)
    event = employee.confirm(draft)
    assert event["id"] == employee.confirm(draft)["id"]
    assert event["event_type"] == "decision.feedback"
    assert event["event_payload"]["decision_id"] == decision["id"]
    after = boss.get(f"/work-items/{work['id']}")
    assert after["version"] == before["version"] + 1
    assert (after["lifecycle_status"], after["needs_support"]) == (
        before["lifecycle_status"],
        before["needs_support"],
    )
    shared = boss.get(path)["items"][0]
    assert shared["feedback_count"] == 1 and shared["latest_feedback"]["id"] == event["id"]
    assert employee.get(path + f"/{decision['id']}/feedback")["items"] == [
        shared["latest_feedback"]
    ]
    assert boss.get(f"/decisions/{decision['id']}/outcomes")["total"] == 0
    with session_factory()() as db:
        assert db.scalar(select(func.count()).select_from(AnalysisRun)) == analyses
        assert db.scalar(select(func.count()).select_from(DecisionOutcome)) == 0
        assert (
            db.scalar(
                select(func.count()).select_from(WatchWake).where(WatchWake.event_id == event["id"])
            )
            == 1
        )
        evidence = db.scalar(
            select(EvidenceSnapshot).where(
                EvidenceSnapshot.work_item_id == work["id"],
                EvidenceSnapshot.work_version == after["version"],
            )
        )
        assert evidence.event_id == event["id"] and evidence.excerpt == draft["raw_text"]


def test_pending_and_other_work_or_tenant_arrangements_are_not_exposed(loop):
    boss, employee, org, depts, member, work = supported(loop)
    pending = prepare(boss, ask(boss, work), work)
    assert employee.get("/work-arrangements?mine=true")["total"] == 0
    employee.post(
        "/work-updates/drafts",
        {"work_item_id": work["id"], "decision_id": pending["id"], "raw_text": "实际情况"},
        404,
    )
    decision = boss.post(f"/decisions/{pending['id']}/confirm", confirm_body(pending))
    other_work = boss.work(depts[0], member)
    employee.post(
        "/work-updates/drafts",
        {"work_item_id": other_work["id"], "decision_id": decision["id"], "raw_text": "实际情况"},
        404,
    )
    stranger = API("stranger@example.com")
    stranger.join(boss.invite(depts[1], "stranger@example.com"), org["id"])
    assert stranger.get("/work-arrangements")["total"] == 0
    stranger.get(f"/work-items/{work['id']}/arrangements", 404)
    stranger.get(f"/work-items/{work['id']}/arrangements/{decision['id']}/feedback", 404)
    foreign = API("foreign@example.com")
    foreign.org()
    assert foreign.get("/work-arrangements")["total"] == 0
    foreign.get(f"/work-items/{work['id']}/arrangements", 404)
    assert boss.get("/work-arrangements?mine=true")["total"] == 0
    assert employee.get("/work-arrangements?mine=true")["total"] == 1


def test_feedback_rejects_status_edits_and_stale_confirmation(loop):
    boss, employee, org, depts, member, work, decision = confirmed(loop)
    draft = feedback(employee, work, decision)
    path = f"/work-updates/drafts/{draft['id']}"
    for field, value in [("lifecycle_status", "done"), ("needs_support", False)]:
        response = employee.request(
            "PATCH",
            path,
            {
                "expected_revision": draft["revision"],
                "proposed_fields": {**draft["proposed_fields"], field: value},
            },
        )
        assert response.status_code == 422
        assert response.json()["error"]["code"] == "feedback_state_change"
    changed = employee.request(
        "PATCH",
        path,
        {
            "expected_revision": draft["revision"],
            "proposed_fields": {**draft["proposed_fields"], "summary": "核实后仍有一处差异"},
        },
    )
    assert changed.status_code == 200
    employee.confirm(draft, 409)
    current = changed.json()
    employee.confirm(employee.draft(work, "补充普通进展"))
    assert employee.confirm(current, 409)["error"]["code"] == "stale_work"
    assert boss.get(f"/work-items/{work['id']}/arrangements")["items"][0]["feedback_count"] == 0


def test_handover_revokes_old_author_drafts_reads_and_replay(loop):
    boss, employee, org, depts, member, work, decision = confirmed(loop)
    original = feedback(employee, work, decision)
    employee.confirm(original)
    pending = feedback(employee, work, decision, "待确认的补充反馈")
    successor = API("successor@example.com")
    next_member = successor.join(boss.invite(depts[0], "successor@example.com"), org["id"])
    current = boss.get(f"/work-items/{work['id']}")
    response = boss.request(
        "PATCH",
        f"/work-items/{work['id']}/assignment",
        {
            "owner_id": next_member["id"],
            "expected_version": current["version"],
            "idempotency_key": str(uuid4()),
        },
    )
    assert response.status_code == 200
    for draft in (pending, original):
        employee.get(f"/work-updates/drafts/{draft['id']}", 404)
        employee.confirm(draft, 404)
    assert employee.get("/work-arrangements?mine=true")["items"] == []
    employee.get(f"/work-items/{work['id']}/arrangements", 404)
    assert successor.get("/work-arrangements?mine=true")["items"][0]["feedback_count"] == 1
    successor.confirm(pending, 404)  # The new owner cannot confirm somebody else's text.
    next_draft = feedback(successor, work, decision, "接手后已核对原安排")
    successor.confirm(next_draft)
    assert boss.get(f"/work-items/{work['id']}/arrangements")["items"][0]["feedback_count"] == 2


def test_feedback_pagination_and_outcomes_remain_separate(loop):
    boss, employee, org, depts, member, work, decision = confirmed(loop)
    for feedback_text in ["已核对第一部分", "已核对第二部分", "仍有内容待补充"]:
        employee.confirm(feedback(employee, work, decision, feedback_text))
    path = f"/work-items/{work['id']}/arrangements/{decision['id']}/feedback"
    first = boss.get(path + "?limit=2")
    last = boss.get(path + "?limit=2&offset=2")
    assert first["total"] == last["total"] == 3
    assert len({row["id"] for row in first["items"] + last["items"]}) == 3
    assert first["items"][0]["summary"] == "仍有内容待补充"
    employee.post(
        f"/decisions/{decision['id']}/outcomes",
        {"observed_result": "冒充老板结果", "idempotency_key": str(uuid4())},
        403,
    )
    draft = feedback(employee, work, decision, "老板记录结果期间仍可继续反馈")
    boss.post(
        f"/decisions/{decision['id']}/outcomes",
        {"observed_result": "阶段性核实，继续跟进", "idempotency_key": str(uuid4())},
        201,
    )
    employee.confirm(draft)
    assert boss.get(f"/decisions/{decision['id']}/outcomes")["total"] == 1


def test_feedback_draft_database_fk_enforces_same_tenant_and_work(loop):
    boss, employee, org, depts, member, work, decision = confirmed(loop)
    other = boss.work(depts[0], member)
    draft = employee.draft(other)
    with session_factory()() as db:
        row = db.get(UpdateDraft, draft["id"])
        row.decision_id = decision["id"]
        with pytest.raises(IntegrityError):
            db.commit()
    with session_factory()() as db:
        for table in ["decisions", "update_drafts"]:
            assert any(
                "state" in c["sqltext"] for c in inspect(db.bind).get_check_constraints(table)
            )


def test_concurrent_feedback_confirmation_has_one_event_and_projection(loop):
    if not settings().database_url.startswith("postgresql"):
        pytest.skip("Row locks require PostgreSQL")
    boss, employee, org, depts, member, work, decision = confirmed(loop)
    draft = feedback(employee, work, decision)
    cookies = dict(employee.client.cookies)

    def submit(_):
        with TestClient(
            app, cookies=cookies, headers={"X-CoRoof-Request": "1", "X-Organization-Id": org["id"]}
        ) as client:
            return client.post(
                f"/api/v1/work-updates/drafts/{draft['id']}/confirm",
                json={"expected_revision": draft["revision"]},
            )

    with ThreadPoolExecutor(max_workers=4) as pool:
        responses = list(pool.map(submit, range(4)))
    assert all(r.status_code == 200 for r in responses), [r.text for r in responses]
    assert len({r.json()["id"] for r in responses}) == 1
    assert boss.get(f"/work-items/{work['id']}")["version"] == work["version"] + 1
    assert boss.get(f"/work-items/{work['id']}/arrangements")["items"][0]["feedback_count"] == 1


def test_assignment_committed_while_feedback_waits_for_work_lock_revokes_confirmation(loop):
    if not settings().database_url.startswith("postgresql"):
        pytest.skip("Authorization under row-lock contention requires PostgreSQL")
    boss, employee, org, depts, member, work, decision = confirmed(loop)
    successor = API("new-owner@example.com")
    new_member = successor.join(boss.invite(depts[0], "new-owner@example.com"), org["id"])
    draft = feedback(employee, work, decision)
    waiting = Event()
    engine = session_factory().kw["bind"]
    cookies = dict(employee.client.cookies)

    def before_execute(conn, cursor, statement, parameters, context, executemany):
        if "work_items" in statement and "FOR UPDATE" in statement:
            waiting.set()

    def submit():
        with TestClient(
            app, cookies=cookies, headers={"X-CoRoof-Request": "1", "X-Organization-Id": org["id"]}
        ) as client:
            return client.post(
                f"/api/v1/work-updates/drafts/{draft['id']}/confirm",
                json={"expected_revision": draft["revision"]},
            )

    with session_factory()() as db, ThreadPoolExecutor(max_workers=1) as pool:
        row = db.scalar(select(WorkItem).where(WorkItem.id == work["id"]).with_for_update())
        event.listen(engine, "before_cursor_execute", before_execute)
        try:
            future = pool.submit(submit)
            assert waiting.wait(5), "feedback did not reach the locked work authorization read"
            row.owner_id = new_member["id"]
            db.commit()
            response = future.result(timeout=5)
            assert response.status_code == 404, response.text
        finally:
            db.rollback()
            event.remove(engine, "before_cursor_execute", before_execute)
    assert boss.get(f"/work-items/{work['id']}/arrangements")["items"][0]["feedback_count"] == 0
    assert successor.get("/work-arrangements?mine=true")["total"] == 1


def test_closed_work_and_expired_feedback_cannot_be_confirmed(loop):
    boss, employee, org, depts, member, work, decision = confirmed(loop)
    draft = feedback(employee, work, decision)
    with session_factory()() as db:
        db.get(UpdateDraft, draft["id"]).expires_at = now() - timedelta(seconds=1)
        db.commit()
    assert employee.confirm(draft, 409)["error"]["code"] == "draft_closed"
    current = employee.get(f"/work-items/{work['id']}")
    employee.post(
        f"/work-items/{work['id']}/updates",
        {"action": "done", "expected_version": current["version"], "idempotency_key": str(uuid4())},
    )
    employee.post(
        "/work-updates/drafts",
        {"work_item_id": work["id"], "decision_id": decision["id"], "raw_text": "已结束后的反馈"},
        409,
    )
    assert employee.get(f"/work-items/{work['id']}/arrangements")["total"] == 1
    assert boss.get(f"/decisions/{decision['id']}/outcomes")["total"] == 0


def test_nonempty_0018_upgrade_preserves_confirmed_history_and_incoming_foreign_keys(
    database, loop
):
    boss, employee, org, depts, member, work, decision = confirmed(loop)
    outcome = boss.post(
        f"/decisions/{decision['id']}/outcomes",
        {
            "observed_result": "历史已确认结果：资料仍需补充",
            "idempotency_key": str(uuid4()),
        },
        201,
    )
    with session_factory()() as db:
        historical_draft = db.scalar(
            select(UpdateDraft).where(UpdateDraft.work_item_id == work["id"])
        )
        assert historical_draft.state == "confirmed" and historical_draft.decision_id is None
        db.add(
            AgentRun(
                organization_id=org["id"],
                actor_id=member["id"],
                session_hash="0" * 64,
                work_item_id=work["id"],
                task="update_draft",
                draft_id=historical_draft.id,
                question="迁移验收的合成历史草稿",
                request_key=str(uuid4()),
                request_hash="1" * 64,
                scope_hash="2" * 64,
                state="completed",
                deadline=now() + timedelta(minutes=10),
            )
        )
        db.commit()

    tables = [
        "work_items",
        "update_drafts",
        "work_events",
        "analysis_runs",
        "decisions",
        "decision_outcomes",
        "agent_runs",
        "watch_wakes",
        "evidence_snapshots",
        "signals",
    ]

    def snapshot():
        with session_factory()() as db:
            rows = {}
            for name in tables:
                table = Table(name, MetaData(), autoload_with=db.connection())
                columns = [
                    column
                    for column in table.c
                    if not (name == "update_drafts" and column.name == "decision_id")
                ]
                rows[name] = [
                    dict(row)
                    for row in db.execute(select(*columns).order_by(table.c.id)).mappings()
                ]
            return rows

    before = snapshot()
    # Incoming WorkEvent, AnalysisRun and AgentRun references remain present in 0018.
    command.downgrade(database, "0018_agent_execution")
    assert snapshot() == before
    with session_factory()() as db:
        assert "decision_id" not in {
            c["name"] for c in inspect(db.bind).get_columns("update_drafts")
        }
        assert db.scalar(text("SELECT version_num FROM alembic_version")) == "0018_agent_execution"
    command.upgrade(database, "0019_arrangement_feedback")
    command.check(database)
    assert snapshot() == before
    assert boss.get(f"/decisions/{decision['id']}/outcomes")["items"][0]["id"] == outcome["id"]
    with session_factory()() as db:
        assert db.scalar(select(UpdateDraft.decision_id)) is None
        if db.bind.dialect.name == "sqlite":
            assert db.scalar(text("PRAGMA foreign_keys")) == 1
            assert db.execute(text("PRAGMA foreign_key_check")).all() == []
        for name in ["update_drafts", "decisions"]:
            assert any(
                "state" in check["sqltext"]
                for check in inspect(db.bind).get_check_constraints(name)
            )


def test_arrangement_migration_refuses_to_drop_bound_feedback(database, loop):
    boss, employee, org, depts, member, work, decision = confirmed(loop)
    draft = feedback(employee, work, decision)
    employee.confirm(draft)
    with pytest.raises(RuntimeError, match="arrangement_feedback_data_exists"):
        command.downgrade(database, "0018_agent_execution")
    with session_factory()() as db:
        assert (
            db.scalar(text("SELECT version_num FROM alembic_version"))
            == "0019_arrangement_feedback"
        )
        assert db.get(UpdateDraft, draft["id"]).decision_id == decision["id"]
        if db.bind.dialect.name == "sqlite":
            assert db.scalar(text("PRAGMA foreign_keys")) == 1
            assert db.execute(text("PRAGMA foreign_key_check")).all() == []
