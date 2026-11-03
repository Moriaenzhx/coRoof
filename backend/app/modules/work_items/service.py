import hashlib
import json
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.access import audit
from app.core.errors import fail
from app.core.schemas import ProposedFields
from app.infrastructure.models import Membership, WorkEvent, WorkItem, now


def request_hash(payload: dict[str, Any]) -> str:
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()


def replay(
    db: Session,
    actor: Membership,
    key: str,
    payload: dict[str, Any],
) -> WorkEvent | None:
    event = db.scalar(
        select(WorkEvent).where(
            WorkEvent.organization_id == actor.organization_id,
            WorkEvent.actor_id == actor.id,
            WorkEvent.idempotency_key == key,
        )
    )
    if event and event.request_hash != request_hash(payload):
        fail("idempotency_conflict", "同一提交标识不能用于不同内容", 409)
    return event


def ensure_version(work: WorkItem, expected: int) -> None:
    if work.source_authority != "native":
        fail("external_authority", "此事项由外部源维护，不能覆盖源状态", 409)
    if work.version != expected:
        fail("stale_work", "事项已发生变化，请刷新后重新确认", 409)


def append_update(
    db: Session,
    actor: Membership,
    work: WorkItem,
    proposed: ProposedFields,
    key: str,
    payload: dict[str, Any],
    event_type: str,
    draft_id: str | None = None,
    extra: dict[str, Any] | None = None,
) -> WorkEvent:
    if work.lifecycle_status in {"done", "cancelled"}:
        fail("terminal_work", "已结束事项不能继续更新", 409)
    previous = {"lifecycle_status": work.lifecycle_status, "needs_support": work.needs_support}
    if proposed.lifecycle_status:
        if work.lifecycle_status == "in_progress" and proposed.lifecycle_status == "planned":
            fail("invalid_transition", "进行中的事项不能退回未开始", 409)
        work.lifecycle_status = proposed.lifecycle_status
    if proposed.needs_support is not None:
        work.needs_support = proposed.needs_support
    if work.lifecycle_status in {"done", "cancelled"}:
        work.needs_support = False
    work.updated_at = now()
    event = WorkEvent(
        organization_id=actor.organization_id,
        work_item_id=work.id,
        actor_id=actor.id,
        draft_id=draft_id,
        event_type=event_type,
        event_payload={"previous": previous, "confirmed": proposed.model_dump(), **(extra or {})},
        source_ref=f"draft:{draft_id}" if draft_id else "native:explicit-action",
        idempotency_key=key,
        request_hash=request_hash(payload),
    )
    db.add(event)
    db.flush()
    audit(db, actor, event_type, event.id)
    return event
