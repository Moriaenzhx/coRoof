"""One bounded read per worker step; transactional intake/projection + outbox."""

from datetime import timedelta
from typing import Any

from fastapi import HTTPException
from sqlalchemy import or_, select
from sqlalchemy.orm import Session
from tenacity import RetryCallState, wait_exponential

from app.core.access import audit, check_assignment, require_owner, tenant_get
from app.core.errors import fail
from app.infrastructure.models import Membership, WorkEvent, WorkItem, now, utc
from app.modules.connectors import providers
from app.modules.connectors.models import (
    Connector,
    SourceLink,
    SourceMember,
    SourceRecord,
    SyncOutbox,
    SyncRun,
)
from app.modules.connectors.providers import Item, SourceConfig, SourceFailure
from app.modules.connectors.schemas import SyncInput
from app.modules.connectors.secrets import unseal
from app.modules.intelligence.signals import refresh_work
from app.modules.work_items.service import request_hash

ACTIVE = {"queued", "running", "retry_wait"}


def authorize(db: Session, actor: Membership) -> None:
    db.refresh(actor, with_for_update=True)
    if actor.status != "active":
        fail("organization_forbidden", "企业访问权限已失效", 403)
    require_owner(actor)


def enqueue(db: Session, run: SyncRun, delay: float = 0) -> None:
    db.add(
        SyncOutbox(
            organization_id=run.organization_id,
            run_id=run.id,
            run_version=run.version,
            available_at=now() + timedelta(seconds=delay),
        )
    )


def create_run(db: Session, actor: Membership, connector_id: str, payload: SyncInput) -> SyncRun:
    connector = tenant_get(db, Connector, connector_id, actor, lock=True)
    authorize(db, actor)
    fingerprint = request_hash({"connector_id": connector_id, **payload.model_dump(mode="json")})
    old = db.scalar(
        select(SyncRun).where(
            SyncRun.organization_id == actor.organization_id,
            SyncRun.actor_id == actor.id,
            SyncRun.request_key == str(payload.idempotency_key),
        )
    )
    if old:
        if old.request_hash != fingerprint:
            fail("idempotency_conflict", "同一请求不能提交不同同步内容", 409)
        return old
    if connector.version != payload.expected_version:
        fail("version_conflict", "连接已变化，请刷新", 409)
    if connector.state == "revoked" or not connector.credential:
        fail("connection_revoked", "请先更新连接凭据并测试", 409)
    if payload.mode != "verify" and connector.state != "active":
        fail("connection_inactive", "请先测试并明确启用连接", 409)
    if payload.mode == "incremental" and connector.watermark is None:
        fail("initial_sync_required", "请先完成一次全量同步", 409)
    running = db.scalar(
        select(SyncRun.id).where(
            SyncRun.organization_id == actor.organization_id,
            SyncRun.connector_id == connector.id,
            SyncRun.state.in_(ACTIVE),
        )
    )
    if running:
        fail("sync_busy", "此连接已有同步任务，请先查看任务状态", 409)
    run = SyncRun(
        organization_id=actor.organization_id,
        connector_id=connector.id,
        actor_id=actor.id,
        connector_version=connector.version,
        mode=payload.mode,
        request_key=str(payload.idempotency_key),
        request_hash=fingerprint,
        since=utc(connector.watermark) - timedelta(minutes=1)
        if payload.mode == "incremental" and connector.watermark
        else None,
    )
    db.add(run)
    db.flush()
    enqueue(db, run)
    audit(db, actor, "connector.sync_requested", run.id)
    db.commit()
    return run


def event(
    db: Session,
    actor: Membership,
    work: WorkItem,
    link: SourceLink,
    record: SourceRecord,
    kind: str,
    summary: str,
) -> None:
    digest = request_hash(
        {
            "link": link.id,
            "record": record.id,
            "kind": kind,
            "work_version": work.version,
            "projection": link.projection_hash,
        }
    )
    db.add(
        WorkEvent(
            organization_id=actor.organization_id,
            work_item_id=work.id,
            actor_id=actor.id,
            event_type=kind,
            event_payload={
                "confirmed": {"summary": summary},
                "source_record_id": record.id,
                "source_kind": "external",
                "source_at": utc(record.source_at).isoformat(),
            },
            source_ref=f"source:{record.id}",
            idempotency_key="source:" + digest,
            request_hash=digest,
            occurred_at=utc(record.source_at),
        )
    )
    work.updated_at = utc(record.source_at)
    work.version += 1
    db.flush()
    refresh_work(db, work)
    audit(db, actor, kind, link.id)


def withhold(db: Session, actor: Membership, link: SourceLink, reason: str, state: str) -> None:
    if link.state == "linked" and link.work_item_id:
        work = tenant_get(db, WorkItem, link.work_item_id, actor, lock=True)
        record = tenant_get(db, SourceRecord, link.record_id, actor)
        event(
            db, actor, work, link, record, "source.withheld", "来源不可用或映射待核对，已隐藏投影。"
        )
    link.state, link.mapping_issue = state, reason


def project(
    db: Session,
    actor: Membership,
    connector: Connector,
    link: SourceLink,
    record: SourceRecord,
    item: Item,
) -> None:
    status = connector.status_map.get(item.state or "")
    owners = set()
    issue = None
    if item.deleted:
        withhold(db, actor, link, "source_removed", "withdrawn")
        return
    if not status:
        issue = "unknown_status"
    if item.assignees is None:
        issue = issue or "unknown_assignees"
    for external in item.assignees or []:
        member = db.scalar(
            select(SourceMember).where(
                SourceMember.organization_id == actor.organization_id,
                SourceMember.connector_id == connector.id,
                SourceMember.external_id == external,
            )
        )
        if member is None:
            member = SourceMember(
                organization_id=actor.organization_id,
                connector_id=connector.id,
                external_id=external,
            )
            db.add(member)
            db.flush()
        if member.membership_id is None:
            issue = issue or "unmapped_member"
        else:
            try:
                check_assignment(db, actor, member.membership_id, connector.department_id)
                owners.add(member.membership_id)
            except HTTPException:
                issue = issue or "invalid_member"
    if len(owners) > 1:
        issue = issue or "multiple_owners"
    if issue:
        withhold(db, actor, link, issue, "pending")
        return
    assert status is not None
    fields: dict[str, Any] = {
        "title": item.title,
        "description": item.description,
        "lifecycle_status": status,
        "owner_id": next(iter(owners), None),
        "department_id": connector.department_id,
        "source_authority": "external",
    }
    projection_hash = request_hash({**fields, "source_at": utc(item.source_at).isoformat()})
    if link.state == "linked" and link.projection_hash == projection_hash:
        return
    work = (
        tenant_get(db, WorkItem, link.work_item_id, actor, lock=True) if link.work_item_id else None
    )
    if work is None:
        work = WorkItem(organization_id=actor.organization_id, **fields)
        db.add(work)
        db.flush()
        link.work_item_id = work.id
    else:
        if work.source_authority != "external":
            raise SourceFailure("authority_conflict")
        for field, value in fields.items():
            setattr(work, field, value)
    link.state, link.mapping_issue, link.projection_hash = "linked", None, projection_hash
    event(db, actor, work, link, record, "source.synced", f"外部来源同步：{item.title}")


def intake(db: Session, actor: Membership, connector: Connector, run: SyncRun, item: Item) -> None:
    digest = request_hash(
        {"raw": item.raw, "normalized": item.model_dump(mode="json", exclude={"raw"})}
    )
    record = db.scalar(
        select(SourceRecord).where(
            SourceRecord.organization_id == actor.organization_id,
            SourceRecord.connector_id == connector.id,
            SourceRecord.external_id == item.external_id,
            SourceRecord.payload_hash == digest,
        )
    )
    if record is None:
        record = SourceRecord(
            organization_id=actor.organization_id,
            connector_id=connector.id,
            external_id=item.external_id,
            payload_hash=digest,
            raw_payload=item.raw,
            normalized=item.model_dump(mode="json", exclude={"raw"}),
            source_at=item.source_at,
        )
        db.add(record)
        db.flush()
    link = db.scalar(
        select(SourceLink).where(
            SourceLink.organization_id == actor.organization_id,
            SourceLink.connector_id == connector.id,
            SourceLink.external_id == item.external_id,
        )
    )
    if link is None:
        link = SourceLink(
            organization_id=actor.organization_id,
            connector_id=connector.id,
            external_id=item.external_id,
            record_id=record.id,
        )
        db.add(link)
        db.flush()
    else:
        current = tenant_get(db, SourceRecord, link.record_id, actor)
        if utc(current.source_at) > item.source_at:
            link.seen_run_id, link.checked_at = run.id, now()
            return  # A delayed snapshot never regresses a newer source fact.
    link.record_id, link.seen_run_id, link.checked_at = record.id, run.id, now()
    project(db, actor, connector, link, record, item)


def finish(run: SyncRun, state: str, error: str | None = None) -> None:
    run.state, run.error_code, run.lease_until = state, error, None
    run.finished_at = now()
    run.version += 1


def process(db: Session, organization_id: str, run_id: str, expected_version: int) -> None:
    initial = db.scalar(
        select(SyncRun).where(SyncRun.organization_id == organization_id, SyncRun.id == run_id)
    )
    if initial is None:
        return
    connector = db.scalar(
        select(Connector)
        .where(Connector.organization_id == organization_id, Connector.id == initial.connector_id)
        .with_for_update()
    )
    run = db.scalar(
        select(SyncRun)
        .where(SyncRun.organization_id == organization_id, SyncRun.id == run_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    assert connector is not None and run is not None
    if run.version != expected_version or run.state not in {"queued", "retry_wait"}:
        return
    actor = db.scalar(
        select(Membership).where(
            Membership.organization_id == organization_id, Membership.id == run.actor_id
        )
    )
    assert actor is not None
    try:
        authorize(db, actor)
        if (
            connector.version != run.connector_version
            or connector.state == "revoked"
            or (run.mode != "verify" and connector.state != "active")
        ):
            raise SourceFailure("configuration_changed")
        if run.page > 100 or utc(run.created_at) < now() - timedelta(minutes=30):
            raise SourceFailure("sync_limit")
        cfg = SourceConfig(
            connector.kind,
            connector.base_url,
            connector.project_key,
            connector.item_type,
            connector.owner_field,
            unseal(connector),
        )
    except (HTTPException, SourceFailure):
        finish(run, "cancelled", "configuration_changed")
        db.commit()
        return
    candidate = None
    if run.phase == "reconcile":
        candidate = db.scalar(
            select(SourceLink)
            .where(
                SourceLink.organization_id == organization_id,
                SourceLink.connector_id == connector.id,
                or_(SourceLink.seen_run_id != run.id, SourceLink.seen_run_id.is_(None)),
                SourceLink.external_id > (run.cursor or ""),
            )
            .order_by(SourceLink.external_id)
            .limit(1)
        )
        if candidate is None:
            connector.synced_at, connector.watermark, connector.last_error = now(), run.until, None
            finish(run, "succeeded")
            db.commit()
            return
    target = candidate.external_id if candidate else None
    run.state, run.lease_until = "running", now() + timedelta(seconds=90)
    run.version += 1
    claimed_version = run.version
    db.commit()
    failure = None
    batch = None
    try:
        batch = providers.fetch(
            cfg,
            run.page if target is None else 1,
            utc(run.since) if run.since else None,
            utc(run.until),
            external_id=target,
            verify=run.mode == "verify",
        )
    except SourceFailure as exc:
        failure = exc
    db.expire_all()
    connector = db.scalar(
        select(Connector)
        .where(Connector.organization_id == organization_id, Connector.id == initial.connector_id)
        .with_for_update()
    )
    run = db.scalar(
        select(SyncRun)
        .where(SyncRun.organization_id == organization_id, SyncRun.id == run_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    assert connector is not None and run is not None
    if run.version != claimed_version or run.state != "running":
        db.rollback()
        return
    try:
        authorize(db, actor)
        if connector.version != run.connector_version or (
            run.mode != "verify" and connector.state != "active"
        ):
            raise SourceFailure("configuration_changed")
    except (HTTPException, SourceFailure):
        finish(run, "cancelled", "configuration_changed")
        db.commit()
        return
    if failure:
        run.failures += 1
        run.error_code = failure.code
        connector.last_error = failure.code
        # Do not invalidate the captured configuration for a transient metadata update.
        if failure.code == "source_denied":
            connector.state = "permission_lost"
        if failure.retryable and run.failures < 5:
            run.state, run.lease_until = "retry_wait", None
            run.version += 1
            db.flush()
            run.connector_version = connector.version
            retry = RetryCallState(None, None, (), {})  # type: ignore[arg-type]
            retry.attempt_number = run.failures
            enqueue(db, run, wait_exponential(multiplier=2, min=2, max=60)(retry))
        else:
            finish(run, "failed", failure.code)
        db.commit()
        return
    assert batch is not None
    if run.mode == "verify":
        if connector.state != "active":
            connector.state = "tested"
        connector.tested_at, connector.last_error = now(), None
        run.processed = len(batch.items)
        finish(run, "succeeded")
    else:
        for item in batch.items:
            intake(db, actor, connector, run, item)
        run.processed += len(batch.items)
        run.failures, run.error_code, run.lease_until = 0, None, None
        if target:
            candidate = db.scalar(
                select(SourceLink).where(
                    SourceLink.organization_id == organization_id,
                    SourceLink.connector_id == connector.id,
                    SourceLink.external_id == target,
                )
            )
            assert candidate is not None
            if not batch.items:
                withhold(db, actor, candidate, "source_removed", "withdrawn")
                candidate.checked_at = now()
            run.cursor = target
        elif batch.more:
            run.page += 1
        elif run.mode == "full":
            run.phase, run.cursor = "reconcile", None
        else:
            connector.synced_at, connector.watermark, connector.last_error = now(), run.until, None
            finish(run, "succeeded")
        if run.state == "running":
            run.state = "queued"
            run.version += 1
            enqueue(db, run)
    db.commit()


def recover(db: Session) -> int:
    """Requeue expired read leases. Late workers are fenced by the run version."""
    count = 0
    candidates = list(
        db.scalars(
            select(SyncRun.id)
            .where(SyncRun.state == "running", SyncRun.lease_until < now())
            .limit(50)
        )
    )
    for run_id in candidates:
        initial = db.get(SyncRun, run_id)
        assert initial is not None
        db.scalar(
            select(Connector)
            .where(
                Connector.organization_id == initial.organization_id,
                Connector.id == initial.connector_id,
            )
            .with_for_update()
        )
        run = db.scalar(
            select(SyncRun)
            .where(SyncRun.id == run_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        assert run is not None
        if run.state == "running" and run.lease_until and utc(run.lease_until) < now():
            run.state, run.error_code, run.lease_until = "queued", "worker_interrupted", None
            run.version += 1
            enqueue(db, run)
            count += 1
        db.commit()
    return count
