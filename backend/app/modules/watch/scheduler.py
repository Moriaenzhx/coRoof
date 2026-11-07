"""Transactional event coalescing and bounded scheduling over Celery transport."""

from collections.abc import Callable
from datetime import timedelta

from fastapi import HTTPException
from sqlalchemy import exists, func, select
from sqlalchemy.orm import Session

from app.infrastructure.models import (
    AgentRun,
    Membership,
    Organization,
    WorkEvent,
    WorkItem,
    now,
    utc,
)
from app.modules.watch import service
from app.modules.watch.models import WatchOutbox, WatchPolicy, WatchRun, WatchWake

ACTIVE = ("queued", "running")


def enqueue(db: Session, run: WatchRun) -> None:
    db.add(WatchOutbox(organization_id=run.organization_id, run_id=run.id, run_version=run.version))


def create_run(db: Session, policy: WatchPolicy, trigger: str, key: str) -> WatchRun:
    actor = db.get(Membership, policy.actor_id)
    grant = service.current_grant(db, policy)
    if actor is None or grant is None:
        raise ValueError("missing_watch_grant")
    service.authorize(db, actor, grant.id)
    run = WatchRun(
        organization_id=policy.organization_id,
        policy_id=policy.id,
        grant_id=grant.id,
        policy_version=policy.version,
        trigger_kind=trigger,
        trigger_key=key,
    )
    db.add(run)
    db.flush()
    enqueue(db, run)
    policy.next_due_at = now() + timedelta(minutes=policy.interval_minutes)
    policy.event_pending = False
    return run


def merge_events(db: Session) -> int:
    # One bounded batch per tenant prevents a busy tenant monopolizing this tick.
    organizations = list(
        db.scalars(
            select(WatchWake.organization_id)
            .where(
                WatchWake.processed_at.is_(None),
            )
            .group_by(WatchWake.organization_id)
            .order_by(func.min(WatchWake.created_at))
            .limit(20)
        )
    )
    merged = 0
    for organization_id in organizations:
        root = db.scalar(
            select(Organization)
            .where(Organization.id == organization_id)
            .with_for_update(key_share=True, skip_locked=True)
        )
        if root is None:
            db.rollback()
            continue
        wakes = list(
            db.scalars(
                select(WatchWake)
                .where(
                    WatchWake.organization_id == organization_id,
                    WatchWake.processed_at.is_(None),
                )
                .order_by(WatchWake.created_at, WatchWake.id)
                .limit(50)
                .with_for_update(skip_locked=True)
            )
        )
        events = list(
            db.scalars(
                select(WorkEvent).where(
                    WorkEvent.organization_id == organization_id,
                    WorkEvent.id.in_([wake.event_id for wake in wakes]),
                )
            )
        )
        work_ids = {event.work_item_id for event in events if event.work_item_id}
        works = list(
            db.scalars(
                select(WorkItem).where(
                    WorkItem.organization_id == organization_id,
                    WorkItem.id.in_(work_ids),
                )
            )
        )
        for policy in db.scalars(
            select(WatchPolicy)
            .where(
                WatchPolicy.organization_id == organization_id,
                WatchPolicy.state == "active",
                WatchPolicy.expires_at > now(),
            )
            .with_for_update()
        ):
            # Memory/document updates can change authorized context. They wake a
            # check but are never directly converted into a work/risk assertion.
            relevant = any(event.work_item_id is None for event in events) or any(
                policy.scope_kind == "organization"
                or (
                    policy.scope_kind == "department" and policy.department_id == work.department_id
                )
                or (
                    policy.scope_kind == "initiative" and policy.initiative_id == work.initiative_id
                )
                for work in works
            )
            if relevant:
                policy.next_due_at, policy.event_pending = now(), True
        for wake in wakes:
            wake.processed_at = now()
        merged += len(wakes)
        db.commit()
    return merged


def schedule(db: Session) -> int:
    busy = exists(
        select(WatchRun.id).where(
            WatchRun.organization_id == WatchPolicy.organization_id,
            WatchRun.policy_id == WatchPolicy.id,
            WatchRun.state.in_(ACTIVE),
        )
    )
    due = select(WatchPolicy).where(
        WatchPolicy.state == "active",
        WatchPolicy.expires_at > now(),
        WatchPolicy.next_due_at <= now(),
        ~busy,
    )
    organizations = list(
        db.scalars(
            due.with_only_columns(WatchPolicy.organization_id)
            .group_by(WatchPolicy.organization_id)
            .order_by(func.min(WatchPolicy.next_due_at))
            .limit(20)
        )
    )
    count = 0
    for organization_id in organizations:
        root = db.scalar(
            select(Organization)
            .where(Organization.id == organization_id)
            .with_for_update(key_share=True, skip_locked=True)
        )
        if root is None:
            db.rollback()
            continue
        policy = db.scalar(
            due.where(WatchPolicy.organization_id == organization_id)
            .order_by(WatchPolicy.next_due_at, WatchPolicy.id)
            .limit(1)
            .with_for_update(skip_locked=True)
            .execution_options(populate_existing=True)
        )
        if policy is None:
            db.rollback()
            continue
        try:
            create_run(
                db,
                policy,
                "event" if policy.event_pending else "scheduled",
                service.fingerprint(
                    {
                        "policy": policy.id,
                        "version": policy.version,
                        "due": utc(policy.next_due_at).isoformat(),
                    }
                ),
            )
        except (HTTPException, ValueError):
            policy.next_due_at = now() + timedelta(minutes=policy.interval_minutes)
            db.commit()
            continue
        db.commit()
        count += 1
    return count


def publish(db: Session, send: Callable[[str, str, int], None]) -> int:
    count = 0
    for _ in range(50):
        row = db.scalar(
            select(WatchOutbox)
            .where(
                WatchOutbox.published_at.is_(None),
                WatchOutbox.available_at <= now(),
            )
            .order_by(WatchOutbox.available_at, WatchOutbox.id)
            .limit(1)
            .with_for_update(skip_locked=True)
        )
        if row is None:
            db.rollback()
            break
        run = db.get(WatchRun, row.run_id)
        if (
            run
            and run.organization_id == row.organization_id
            and run.state == "queued"
            and run.version == row.run_version
        ):
            try:
                send(row.organization_id, row.run_id, row.run_version)
            except Exception:
                db.rollback()
                break
            count += 1
        row.published_at = now()
        db.commit()
    return count


def claim(db: Session, organization_id: str, identifier: str, version: int) -> WatchRun | None:
    run = db.scalar(
        select(WatchRun)
        .where(
            WatchRun.organization_id == organization_id,
            WatchRun.id == identifier,
        )
        .with_for_update()
    )
    if run is None or run.version != version or run.state != "queued":
        db.rollback()
        return None
    policy = db.get(WatchPolicy, run.policy_id)
    actor = db.get(Membership, policy.actor_id) if policy else None
    try:
        if actor is None:
            raise ValueError("missing_actor")
        service.authorize(db, actor, run.grant_id)
    except (HTTPException, ValueError):
        run.state, run.error_code, run.finished_at = "cancelled", "authorization_changed", now()
        run.version += 1
        db.commit()
        return None
    run.state = "running"
    run.version += 1
    run.attempts += 1
    run.lease_until = now() + timedelta(seconds=180)
    db.commit()
    return run


def recover(db: Session) -> int:
    count = 0
    runs = list(
        db.scalars(
            select(WatchRun)
            .where(
                WatchRun.state == "running",
                WatchRun.lease_until <= now(),
            )
            .order_by(WatchRun.lease_until, WatchRun.id)
            .limit(50)
            .with_for_update(skip_locked=True)
        )
    )
    for run in runs:
        run.version += 1
        run.lease_until = None
        if run.phase == "gather" and run.attempts < 3:
            run.state = "queued"
            enqueue(db, run)
        else:
            child = db.get(AgentRun, run.agent_run_id) if run.agent_run_id else None
            if child and child.state in {"ready", "completed"}:
                # A persisted, known step can be reconciled. Running/interrupted calls cannot.
                run.state = "queued"
                enqueue(db, run)
            else:
                run.state, run.error_code, run.finished_at = "unknown", "worker_interrupted", now()
        count += 1
    db.commit()
    for box in db.scalars(
        select(WatchOutbox)
        .where(
            WatchOutbox.published_at < now() - timedelta(seconds=240),
        )
        .join(
            WatchRun,
            (WatchRun.organization_id == WatchOutbox.organization_id)
            & (WatchRun.id == WatchOutbox.run_id),
        )
        .where(WatchRun.state == "queued", WatchRun.version == WatchOutbox.run_version)
        .order_by(WatchOutbox.published_at)
        .limit(50)
        .with_for_update(skip_locked=True)
    ):
        box.published_at = None
    db.commit()
    return count
