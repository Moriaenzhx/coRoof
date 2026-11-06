from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.access import get_work, work_scope
from app.core.schemas import WorkOut
from app.infrastructure.models import (
    EvidenceSnapshot,
    Membership,
    Signal,
    WorkEvent,
    WorkItem,
    now,
    utc,
)
from app.modules.intelligence.schemas import Category, EvidenceOut, SignalOut

RULES: dict[Category, tuple[str, str, str]] = {
    "support": ("attention", "需要支持", "成员明确提出支持需求，尚未解除。"),
    "overdue": (
        "warning",
        "已过截止时间",
        "已到记录的截止时间，事项仍未结束；实际交付情况需确认。",
    ),
    "deadline_blocked": (
        "attention",
        "临近截止且需支持",
        "记录的截止时间在未来两天内，且仍有支持需求。",
    ),
    "stale": ("info", "记录待更新", "当前记录已超过七天未更新，仅表示信息可能陈旧。"),
}


def categories(work: WorkItem, at: datetime) -> list[Category]:
    if work.lifecycle_status in {"done", "cancelled"}:
        return []
    result: list[Category] = []
    if work.needs_support:
        result.append("support")
    if work.due_at and utc(work.due_at) < at:
        result.append("overdue")
    elif work.due_at and utc(work.due_at) <= at + timedelta(days=2) and work.needs_support:
        result.append("deadline_blocked")
    if utc(work.updated_at) < at - timedelta(days=7):
        result.append("stale")
    return result


def snapshot(db: Session, work: WorkItem) -> EvidenceSnapshot:
    evidence = db.scalar(
        select(EvidenceSnapshot).where(
            EvidenceSnapshot.organization_id == work.organization_id,
            EvidenceSnapshot.work_item_id == work.id,
            EvidenceSnapshot.work_version == work.version,
        )
    )
    if evidence:
        return evidence
    event = db.scalar(
        select(WorkEvent)
        .where(
            WorkEvent.organization_id == work.organization_id,
            WorkEvent.work_item_id == work.id,
            WorkEvent.event_type.in_(
                [
                    "work.created",
                    "work.assigned",
                    "work.updated",
                    "update.confirmed",
                    "decision.feedback",
                    "source.synced",
                ]
            ),
        )
        .order_by(WorkEvent.recorded_at.desc(), WorkEvent.id.desc())
    )
    excerpt = work.title
    if event:
        confirmed = event.event_payload.get("confirmed", {})
        excerpt = str(
            confirmed.get("summary") or event.event_payload.get("title") or "负责人分配已记录"
        )
    evidence = EvidenceSnapshot(
        organization_id=work.organization_id,
        work_item_id=work.id,
        work_version=work.version,
        event_id=event.id if event else None,
        facts=WorkOut.model_validate(work).model_dump(mode="json"),
        excerpt=excerpt,
        source_at=work.updated_at,
    )
    db.add(evidence)
    db.flush()
    return evidence


def refresh_work(db: Session, work: WorkItem, at: datetime | None = None) -> list[Signal]:
    """Caller holds the WorkItem row lock, serializing creation and projection updates."""
    at = at or now()
    active = categories(work, at)
    existing = list(
        db.scalars(
            select(Signal).where(
                Signal.organization_id == work.organization_id,
                Signal.work_item_id == work.id,
            )
        )
    )
    evidence = snapshot(db, work) if active else None
    for category in active:
        signal = next((s for s in existing if s.category == category), None)
        assert evidence is not None
        if signal is None:
            signal = Signal(
                organization_id=work.organization_id,
                work_item_id=work.id,
                category=category,
                severity=RULES[category][0],
                evidence_id=evidence.id,
            )
            db.add(signal)
            existing.append(signal)
        elif signal.state != "active" or signal.evidence_id != evidence.id:
            signal.state = "active"
            signal.evidence_id = evidence.id
            signal.evaluated_at = at
    for signal in existing:
        if signal.category not in active and signal.state == "active":
            signal.state = "resolved"
            signal.evaluated_at = at
    db.flush()
    return [s for s in existing if s.state == "active"]


def refresh_scope(db: Session, actor: Membership) -> tuple[list[WorkItem], list[Signal]]:
    works = list(db.scalars(work_scope(actor).order_by(WorkItem.id).with_for_update()))
    signals = [s for w in works for s in refresh_work(db, w)]
    return works, signals


def signal_out(signal: Signal, work: WorkItem) -> SignalOut:
    category: Category = signal.category  # type: ignore[assignment]
    return SignalOut(
        **{
            **{
                k: getattr(signal, k)
                for k in (
                    "id",
                    "work_item_id",
                    "evidence_id",
                    "category",
                    "severity",
                    "state",
                    "rule_version",
                    "detected_at",
                    "evaluated_at",
                    "version",
                )
            },
            "title": RULES[category][1],
            "explanation": RULES[category][2],
            "work_title": work.title,
        }
    )


def evidence_out(db: Session, actor: Membership, evidence: EvidenceSnapshot) -> EvidenceOut:
    work = get_work(db, actor, evidence.work_item_id)
    return EvidenceOut.model_validate(
        {
            **{
                k: getattr(evidence, k)
                for k in (
                    "id",
                    "work_item_id",
                    "work_version",
                    "event_id",
                    "facts",
                    "excerpt",
                    "source_at",
                    "captured_at",
                )
            },
            "outdated": work.version != evidence.work_version,
        }
    )
