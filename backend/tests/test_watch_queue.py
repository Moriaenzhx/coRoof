"""Stage 8.2: transaction rollback, event coalescing, fair admission and delivery recovery."""

from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from uuid import uuid4

import pytest
from conftest import API
from sqlalchemy import func, select
from test_watch_controls import action, create

from app.infrastructure.db import session_factory
from app.infrastructure.models import WorkEvent, now, utc
from app.modules.watch import scheduler
from app.modules.watch.models import WatchOutbox, WatchPolicy, WatchRun, WatchWake


def test_event_wake_shares_commit_and_drafts_never_wake(loop):
    boss, _, org, _, _, work = loop
    with session_factory()() as db:
        initial = db.scalar(select(func.count()).select_from(WatchWake))
        source = db.scalar(select(WorkEvent))
        db.add(
            WorkEvent(
                organization_id=org["id"],
                work_item_id=work["id"],
                actor_id=source.actor_id,
                event_type="work.updated",
                event_payload={"confirmed": {"summary": "rollback"}},
                source_ref="fixture",
                idempotency_key=str(uuid4()),
                request_hash="x" * 64,
                occurred_at=now(),
            )
        )
        db.flush()
        assert db.scalar(select(func.count()).select_from(WatchWake)) == initial + 1
        db.rollback()
        assert db.scalar(select(func.count()).select_from(WatchWake)) == initial
    draft = boss.draft(work)
    with session_factory()() as db:
        assert db.scalar(select(func.count()).select_from(WatchWake)) == initial
    boss.confirm(draft)
    with session_factory()() as db:
        assert db.scalar(select(func.count()).select_from(WatchWake)) == initial + 1


def test_coalesced_event_and_clock_admission_have_no_duplicate_active_runs(loop):
    boss = loop[0]
    policy = create(boss)
    with session_factory()() as db:
        assert scheduler.merge_events(db) >= 1
        assert scheduler.merge_events(db) == 0
        assert scheduler.schedule(db) == 1
        assert scheduler.schedule(db) == 0
        run = db.scalar(select(WatchRun))
        assert run.trigger_kind == "event"
        assert db.scalar(select(func.count()).select_from(WatchOutbox)) == 1
        assert utc(db.get(WatchPolicy, policy["id"]).next_due_at) > now()
    draft = boss.draft(loop[-1])
    boss.confirm(draft)
    with session_factory()() as db:
        scheduler.merge_events(db)
        assert scheduler.schedule(db) == 0
        run = db.scalar(select(WatchRun))
        run.state = "completed"
        db.commit()
        assert scheduler.schedule(db) == 1
        assert db.scalar(select(func.count()).select_from(WatchRun)) == 2


def test_broker_ambiguity_duplicate_messages_and_missing_receipts_are_safe(loop):
    create(loop[0])
    tasks = []
    with session_factory()() as db:
        assert scheduler.schedule(db) == 1

        def ambiguous(*args):
            tasks.append(args)
            raise OSError("broker response lost")

        assert scheduler.publish(db, ambiguous) == 0
        assert db.scalar(select(WatchOutbox)).published_at is None
        assert scheduler.publish(db, lambda *args: tasks.append(args)) == 1
        assert tasks[0] == tasks[1]
        row = scheduler.claim(db, *tasks[0])
        assert row is not None
        assert scheduler.claim(db, *tasks[1]) is None
        assert scheduler.claim(db, str(uuid4()), row.id, row.version) is None
        assert db.scalar(select(func.count()).select_from(WatchRun)) == 1


def test_safe_gather_recovery_and_unknown_model_step_stop(loop):
    create(loop[0])
    tasks = []
    with session_factory()() as db:
        scheduler.schedule(db)
        scheduler.publish(db, lambda *args: tasks.append(args))
        row = scheduler.claim(db, *tasks[0])
        identifier = row.id
        row.lease_until = now() - timedelta(seconds=1)
        db.commit()
        assert scheduler.recover(db) == 1
        assert db.get(WatchRun, identifier).state == "queued"
        scheduler.publish(db, lambda *args: tasks.append(args))
        row = scheduler.claim(db, *tasks[-1])
        row.phase = "analyze"
        row.lease_until = now() - timedelta(seconds=1)
        db.commit()
        assert scheduler.recover(db) == 1
        assert db.get(WatchRun, identifier).state == "unknown"
        assert (
            scheduler.publish(db, lambda *_: pytest.fail("unknown model step must not retry")) == 0
        )


def test_published_but_unclaimed_outbox_is_recoverable(loop):
    create(loop[0])
    tasks = []
    with session_factory()() as db:
        scheduler.schedule(db)
        scheduler.publish(db, lambda *args: tasks.append(args))
        box = db.scalar(select(WatchOutbox))
        box.published_at = now() - timedelta(minutes=5)
        db.commit()
        scheduler.recover(db)
        assert scheduler.publish(db, lambda *args: tasks.append(args)) == 1
        assert tasks[0] == tasks[1]
        assert scheduler.claim(db, *tasks[1]) is not None
        assert scheduler.claim(db, *tasks[0]) is None


def test_pause_fences_pending_run_and_scheduler_rotates_tenants(loop):
    boss = loop[0]
    policy = create(boss)
    create(boss, name="第二项")
    other = API("watch-owner@example.com")
    other.org("另一企业")
    other_policy = create(other)
    with session_factory()() as db:
        assert scheduler.schedule(db) == 2
        runs = list(db.scalars(select(WatchRun)))
        assert len({row.organization_id for row in runs}) == 2
        assert any(row.policy_id == other_policy["id"] for row in runs)
        task = next(
            (r.organization_id, r.id, r.version) for r in runs if r.policy_id == policy["id"]
        )
    boss.post(f"/watch/policies/{policy['id']}/actions", action(policy, "pause"))
    with session_factory()() as db:
        assert scheduler.claim(db, *task) is None
        assert db.get(WatchRun, task[1]).state == "cancelled"


def test_pg_concurrent_schedule_and_claim_are_once(loop):
    if session_factory().kw["bind"].dialect.name != "postgresql":
        pytest.skip("PostgreSQL scheduling and lease acceptance")
    create(loop[0])

    def schedule():
        with session_factory()() as db:
            return scheduler.schedule(db)

    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sum(pool.map(lambda _: schedule(), range(2))) == 1
    with session_factory()() as db:
        row = db.scalar(select(WatchRun))
        task = row.organization_id, row.id, row.version

    def claim():
        with session_factory()() as db:
            return scheduler.claim(db, *task) is not None

    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sum(pool.map(lambda _: claim(), range(2))) == 1
