from sqlalchemy import Select, func, select
from sqlalchemy.orm import Session

from app.core.access import get_work, page_rows, work_scope
from app.core.errors import fail
from app.core.schemas import Page
from app.infrastructure.models import Decision, Membership, UpdateDraft, WorkEvent, WorkItem, utc
from app.modules.decisions.schemas import ArrangementFeedbackOut, WorkArrangementOut


def confirmed_arrangement(
    db: Session, actor: Membership, work_id: str, decision_id: str
) -> Decision:
    get_work(db, actor, work_id)
    row = db.scalar(
        select(Decision).where(
            Decision.organization_id == actor.organization_id,
            Decision.work_item_id == work_id,
            Decision.id == decision_id,
            Decision.state == "confirmed",
        )
    )
    if row is None:
        fail("not_found", "未找到此事项的已确认安排", 404)
    assert row is not None
    return row


def feedback_query(actor: Membership) -> Select[tuple[WorkEvent, str | None]]:
    return (
        select(WorkEvent, UpdateDraft.decision_id)
        .join(
            UpdateDraft,
            (UpdateDraft.organization_id == WorkEvent.organization_id)
            & (UpdateDraft.id == WorkEvent.draft_id),
        )
        .where(
            WorkEvent.organization_id == actor.organization_id,
            WorkEvent.event_type == "decision.feedback",
            UpdateDraft.state == "confirmed",
        )
    )


def feedback_out(event: WorkEvent, decision_id: str) -> ArrangementFeedbackOut:
    return ArrangementFeedbackOut(
        id=event.id,
        decision_id=decision_id,
        actor_id=event.actor_id,
        summary=str(event.event_payload["confirmed"]["summary"]),
        recorded_at=utc(event.recorded_at),
    )


def list_arrangements(
    db: Session,
    actor: Membership,
    *,
    work_id: str | None = None,
    decision_id: str | None = None,
    mine: bool = False,
    offset: int = 0,
    limit: int = 50,
) -> Page[WorkArrangementOut]:
    scope = work_scope(actor)
    if mine:
        scope = scope.where(WorkItem.owner_id == actor.id)
    if work_id:
        get_work(db, actor, work_id)
        scope = scope.where(WorkItem.id == work_id)
    stmt = select(Decision).where(
        Decision.organization_id == actor.organization_id,
        Decision.work_item_id.in_(scope.with_only_columns(WorkItem.id)),
        Decision.state == "confirmed",
    )
    if decision_id:
        stmt = stmt.where(Decision.id == decision_id)
    rows, total = page_rows(
        db, stmt.order_by(Decision.confirmed_at.desc(), Decision.id), offset, limit
    )
    # One bounded summary query, regardless of how many work items are displayed.
    ranked = (
        feedback_query(actor)
        .with_only_columns(
            WorkEvent.id.label("event_id"),
            UpdateDraft.decision_id.label("decision_id"),
            func.count().over(partition_by=UpdateDraft.decision_id).label("total"),
            func.row_number()
            .over(
                partition_by=UpdateDraft.decision_id,
                order_by=(WorkEvent.recorded_at.desc(), WorkEvent.id),
            )
            .label("position"),
        )
        .where(UpdateDraft.decision_id.in_([r.id for r in rows]))
        .subquery()
    )
    latest = {
        decision_id: (count, feedback_out(event, decision_id))
        for event, decision_id, count in db.execute(
            select(WorkEvent, ranked.c.decision_id, ranked.c.total)
            .join(ranked, ranked.c.event_id == WorkEvent.id)
            .where(ranked.c.position == 1, WorkEvent.organization_id == actor.organization_id)
        )
    }
    items = []
    for row in rows:
        assert row.selected_plan is not None and row.follow_up is not None
        assert row.confirmed_at is not None
        count, feedback = latest.get(row.id, (0, None))
        items.append(
            WorkArrangementOut(
                id=row.id,
                work_item_id=row.work_item_id,
                selected_plan=row.selected_plan,
                follow_up=row.follow_up,
                follow_up_at=utc(row.follow_up_at) if row.follow_up_at else None,
                confirmed_at=utc(row.confirmed_at),
                feedback_count=count,
                latest_feedback=feedback,
            )
        )
    return Page(items=items, total=total, offset=offset, limit=limit)
