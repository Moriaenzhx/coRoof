"""Stage 8.4: grounded, deduplicated owner review with explicit business confirmation."""

from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from uuid import uuid4

import pytest
from conftest import API
from sqlalchemy import func, select
from test_agent_actions import event_count, selection
from test_agent_read import model
from test_connectors import enable, item, prepared, sync  # noqa: F401
from test_watch_controls import action, create
from test_watch_runner import drain, due

from app.infrastructure.db import session_factory
from app.infrastructure.models import Decision, WorkItem, now
from app.modules.connectors.models import Connector
from app.modules.watch.models import AttentionItem, AttentionReview, WatchRun


def inbox(boss, history=False):
    return boss.get("/watch/attention" + ("?include_closed=true" if history else ""))


def review(item, action="dismiss", **extra):
    return {
        "action": action,
        "expected_version": item["version"],
        "idempotency_key": str(uuid4()),
        **extra,
    }


def prepare_background(loop, monkeypatch):
    boss, _, _, _, _, work = loop
    model(monkeypatch)
    policy = create(boss)
    identifier = due(policy)
    assert drain(identifier)[1] == "analyzed"
    attention = inbox(boss)[0]
    child = boss.get(f"/agent/runs/{attention['agent_run_id']}")
    decision = boss.post(
        "/decisions",
        {
            "analysis_id": child["answer"]["id"],
            "work_item_id": work["id"],
            "idempotency_key": str(uuid4()),
        },
        201,
    )
    return policy, attention, decision


def test_rules_are_grounded_deduplicated_and_dismissal_is_not_business_progress(loop):
    boss, _, _, _, _, work = loop
    boss.confirm(boss.draft(work))
    policy = create(boss)
    before = event_count()
    drain(due(policy))
    row = inbox(boss)[0]
    assert row["category"] == "support" and row["evidence"]["work_item_id"] == work["id"]
    assert row["agent_run_id"] is None
    path = f"/watch/attention/{row['id']}/actions"
    command = review(row)
    dismissed = boss.post(path, command)
    assert dismissed["state"] == "dismissed"
    assert boss.post(path, command) == dismissed
    drain(due(policy))
    assert inbox(boss) == []
    assert len(inbox(boss, True)) == 1
    assert event_count() == before
    with session_factory()() as db:
        assert db.get(WorkItem, work["id"]).needs_support is True
        assert db.scalar(select(func.count()).select_from(AttentionReview)) == 1


def test_new_fact_reopens_same_item_and_disappearing_basis_is_not_resolution(loop):
    boss, _, _, _, _, work = loop
    boss.confirm(boss.draft(work))
    policy = create(boss)
    drain(due(policy))
    original = inbox(boss)[0]
    boss.post(f"/watch/attention/{original['id']}/actions", review(original))
    boss.confirm(boss.draft(work, raw="仍需要支持，已补充客户资料清单"))
    drain(due(policy))
    changed = inbox(boss)[0]
    assert changed["id"] == original["id"] and changed["state"] == "open"
    assert changed["version"] > original["version"]
    # The immediate read is safe even before the next background scan.
    with session_factory()() as db:
        db.get(WorkItem, work["id"]).needs_support = False
        db.commit()
    invalidated = inbox(boss)[0]
    assert invalidated["state"] == "invalidated" and invalidated["evidence"] is None
    assert "不能据此认定问题已解决" in invalidated["explanation"]
    assert (
        boss.request(
            "POST", f"/watch/attention/{changed['id']}/actions", review(changed)
        ).status_code
        == 409
    )


def test_snooze_and_correction_are_review_records_and_do_not_modify_facts(loop):
    boss, _, _, _, _, work = loop
    boss.confirm(boss.draft(work))
    policy = create(boss)
    drain(due(policy))
    row = inbox(boss)[0]
    path = f"/watch/attention/{row['id']}/actions"
    before = event_count()
    row = boss.post(
        path, review(row, "snooze", snoozed_until=(now() + timedelta(days=1)).isoformat())
    )
    assert row["state"] == "snoozed"
    drain(due(policy))
    assert inbox(boss)[0]["state"] == "snoozed"
    with session_factory()() as db:
        db.get(AttentionItem, row["id"]).snoozed_until = now() - timedelta(seconds=1)
        db.commit()
    row = inbox(boss)[0]
    assert row["state"] == "open"
    assert boss.request("POST", path, review(row, "correct")).status_code == 422
    row = boss.post(path, review(row, "correct", note="请核实支持需求是否仍然存在"))
    assert row["state"] == "dismissed" and row["review_note"]
    assert event_count() == before


def test_empty_scope_is_a_single_coverage_gap_never_a_risk():
    boss = API()
    boss.org()
    policy = create(boss)
    before = event_count()
    drain(due(policy))
    drain(due(policy))
    rows = inbox(boss)
    assert len(rows) == 1 and rows[0]["kind"] == "coverage"
    assert rows[0]["evidence"] is None and rows[0]["work_item_id"] is None
    assert event_count() == before


def test_background_plan_reuses_explicit_graph_confirmation_and_follow_up(loop, monkeypatch):
    boss = loop[0]
    before = event_count()
    policy, attention, decision = prepare_background(loop, monkeypatch)
    assert attention["category"] == "plan"
    assert event_count() == before
    command = {**selection(decision), "follow_up_at": (now() + timedelta(days=1)).isoformat()}
    path = f"/decisions/{decision['id']}/confirm"
    confirmed = boss.post(path, command)
    assert confirmed["follow_up_at"] and boss.post(path, command) == confirmed
    assert event_count() == before + 1
    with session_factory()() as db:
        db.get(Decision, decision["id"]).follow_up_at = now() - timedelta(seconds=1)
        db.commit()
    drain(due(policy))
    follow = next(r for r in inbox(boss) if r["kind"] == "follow_up")
    assert follow["decision_id"] == decision["id"] and follow["state"] == "open"
    boss.post(
        f"/decisions/{decision['id']}/outcomes",
        {
            "observed_result": "核实后仍缺资料，问题未解决",
            "idempotency_key": str(uuid4()),
        },
        201,
    )
    follow = next(r for r in inbox(boss) if r["kind"] == "follow_up")
    assert follow["state"] == "result_recorded"
    assert "不代表问题一定已解决" in follow["explanation"]


def test_revocation_hides_items_and_prevents_pending_confirmation(loop, monkeypatch):
    boss, member, *_ = loop
    policy, attention, decision = prepare_background(loop, monkeypatch)
    assert member.request("GET", "/watch/attention").status_code == 403
    other = API("foreign-review@example.com")
    other.org()
    assert (
        other.request(
            "POST", f"/watch/attention/{attention['id']}/actions", review(attention)
        ).status_code
        == 404
    )
    before = event_count()
    boss.post(f"/watch/policies/{policy['id']}/actions", action(policy, "pause"))
    assert inbox(boss, True) == []
    assert (
        boss.request(
            "POST", f"/decisions/{decision['id']}/confirm", selection(decision)
        ).status_code
        == 403
    )
    assert event_count() == before


def test_failed_source_supersedes_old_claims_without_inventing_business_risk(
    prepared,  # noqa: F811 - imported pytest fixture
    monkeypatch,
):
    boss, _, _, _, native, connection = prepared
    enable(prepared, monkeypatch)
    sync(prepared, monkeypatch, [item()])
    with session_factory()() as db:
        db.get(WorkItem, native["id"]).lifecycle_status = "done"
        db.commit()
    model(monkeypatch)
    policy = create(boss)
    drain(due(policy))
    old = inbox(boss)[0]
    with session_factory()() as db:
        db.get(Connector, connection["id"]).last_error = "source_unavailable"
        db.commit()
    assert inbox(boss)[0]["state"] == "invalidated"
    drain(due(policy))
    current = inbox(boss)[0]
    assert current["id"] == old["id"] and current["category"] == "source_unavailable"
    assert current["evidence"] is None and current["agent_run_id"] is None


def test_pg_concurrent_review_has_one_receipt(loop):
    if session_factory().kw["bind"].dialect.name != "postgresql":
        pytest.skip("PostgreSQL owner review concurrency")
    boss = loop[0]
    boss.confirm(boss.draft(loop[-1]))
    policy = create(boss)
    drain(due(policy))
    row = inbox(boss)[0]
    path, command = f"/watch/attention/{row['id']}/actions", review(row)
    with ThreadPoolExecutor(max_workers=2) as pool:
        rows = list(pool.map(lambda _: boss.post(path, command), range(2)))
    assert rows[0] == rows[1]
    with session_factory()() as db:
        assert db.scalar(select(func.count()).select_from(AttentionReview)) == 1
        assert db.scalar(select(func.count()).select_from(WatchRun)) == 1
