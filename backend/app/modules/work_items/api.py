from datetime import timedelta
from time import perf_counter

from fastapi import APIRouter
from sqlalchemy import select

from app.core.access import (
    audit,
    check_assignment,
    get_work,
    initiative_scope,
    page_rows,
    require_manager,
    tenant_get,
    work_scope,
)
from app.core.auth import Actor, Db
from app.core.errors import fail
from app.core.schemas import (
    AssignmentInput,
    ConfirmInput,
    DraftEdit,
    DraftInput,
    DraftOut,
    EventOut,
    Page,
    ProposedFields,
    QuickUpdate,
    WorkInput,
    WorkOut,
)
from app.infrastructure.models import (
    AgentRun,
    AnalysisRun,
    Department,
    Initiative,
    UpdateDraft,
    WorkEvent,
    WorkItem,
    now,
    utc,
)
from app.modules.decisions.arrangements import confirmed_arrangement
from app.modules.intelligence.provider import get_provider
from app.modules.intelligence.signals import refresh_work
from app.modules.organizations.api import Limit, Offset
from app.modules.work_items.service import append_update, ensure_version, replay, request_hash

router = APIRouter(tags=["work"])


@router.post("/work-items", response_model=WorkOut, status_code=201)
def create_work(payload: WorkInput, db: Db, actor: Actor) -> WorkOut:
    require_manager(actor, payload.department_id)
    tenant_get(db, Department, payload.department_id, actor)
    check_assignment(db, actor, payload.owner_id, payload.department_id)
    if payload.initiative_id:
        initiative = db.scalar(
            initiative_scope(actor).where(Initiative.id == payload.initiative_id)
        )
        if initiative is None:
            fail("not_found", "未找到获授权的项目", 404)
        assert initiative is not None
        if initiative.department_id and initiative.department_id != payload.department_id:
            fail("project_scope_mismatch", "事项部门须与项目所属部门一致")
    work = WorkItem(organization_id=actor.organization_id, **payload.model_dump())
    db.add(work)
    db.flush()
    db.add(
        WorkEvent(
            organization_id=actor.organization_id,
            work_item_id=work.id,
            actor_id=actor.id,
            event_type="work.created",
            event_payload=payload.model_dump(mode="json"),
            source_ref="native:creation",
            idempotency_key=f"create:{work.id}",
            request_hash=request_hash(payload.model_dump(mode="json")),
        )
    )
    db.flush()
    refresh_work(db, work)
    audit(db, actor, "work.created", work.id)
    db.commit()
    return WorkOut.model_validate(work)


@router.get("/work-items", response_model=Page[WorkOut])
def list_work(
    db: Db,
    actor: Actor,
    offset: Offset = 0,
    limit: Limit = 50,
    mine: bool = False,
) -> Page[WorkOut]:
    stmt = work_scope(actor)
    if mine:
        stmt = stmt.where(WorkItem.owner_id == actor.id)
    rows, total = page_rows(
        db, stmt.order_by(WorkItem.updated_at.desc(), WorkItem.id), offset, limit
    )
    return Page(
        items=[WorkOut.model_validate(r) for r in rows], total=total, offset=offset, limit=limit
    )


@router.get("/work-items/{work_id}", response_model=WorkOut)
def read_work(work_id: str, db: Db, actor: Actor) -> WorkOut:
    return WorkOut.model_validate(get_work(db, actor, work_id))


@router.patch("/work-items/{work_id}/assignment", response_model=EventOut)
def assign(work_id: str, payload: AssignmentInput, db: Db, actor: Actor) -> EventOut:
    work = get_work(db, actor, work_id, lock=True)
    require_manager(actor, work.department_id)
    body = {"work_id": work_id, "assignment": payload.model_dump()}
    existing = replay(db, actor, payload.idempotency_key, body)
    if existing:
        return EventOut.model_validate(existing)
    ensure_version(work, payload.expected_version)
    check_assignment(db, actor, payload.owner_id, work.department_id)
    old_owner = work.owner_id
    work.owner_id = payload.owner_id
    work.updated_at = now()
    event = WorkEvent(
        organization_id=actor.organization_id,
        work_item_id=work.id,
        actor_id=actor.id,
        event_type="work.assigned",
        event_payload={"previous_owner": old_owner, "owner_id": payload.owner_id},
        source_ref="native:assignment",
        idempotency_key=payload.idempotency_key,
        request_hash=request_hash(body),
    )
    db.add(event)
    db.flush()
    refresh_work(db, work)
    audit(db, actor, "work.assigned", event.id)
    db.commit()
    return EventOut.model_validate(event)


@router.get("/work-items/{work_id}/events", response_model=Page[EventOut])
def events(
    work_id: str,
    db: Db,
    actor: Actor,
    offset: Offset = 0,
    limit: Limit = 50,
) -> Page[EventOut]:
    get_work(db, actor, work_id)
    rows, total = page_rows(
        db,
        select(WorkEvent)
        .where(
            WorkEvent.organization_id == actor.organization_id,
            WorkEvent.work_item_id == work_id,
        )
        .order_by(WorkEvent.recorded_at.desc(), WorkEvent.id),
        offset,
        limit,
    )
    return Page(
        items=[EventOut.model_validate(r) for r in rows], total=total, offset=offset, limit=limit
    )


@router.post("/work-items/{work_id}/updates", response_model=EventOut)
def quick_update(work_id: str, payload: QuickUpdate, db: Db, actor: Actor) -> EventOut:
    work = get_work(db, actor, work_id, lock=True)
    body = {"work_id": work_id, **payload.model_dump()}
    existing = replay(db, actor, payload.idempotency_key, body)
    if existing:
        return EventOut.model_validate(existing)
    ensure_version(work, payload.expected_version)
    fields = ProposedFields(
        summary=payload.summary
        or {
            "progress": "有进展",
            "done": "已完成",
            "support": "需要支持",
            "resolve_support": "阻塞已解除",
        }[payload.action],
        lifecycle_status={"progress": "in_progress", "done": "done"}.get(payload.action),
        needs_support={"support": True, "resolve_support": False}.get(payload.action),
    )
    event = append_update(db, actor, work, fields, payload.idempotency_key, body, "work.updated")
    db.commit()
    return EventOut.model_validate(event)


@router.post("/work-updates/drafts", response_model=DraftOut, status_code=201)
def create_draft(payload: DraftInput, db: Db, actor: Actor) -> DraftOut:
    work = get_work(db, actor, payload.work_item_id)
    ensure_version(work, work.version)
    if work.lifecycle_status in {"done", "cancelled"}:
        fail("terminal_work", "已结束事项不能继续更新", 409)
    if payload.decision_id:
        confirmed_arrangement(db, actor, work.id, payload.decision_id)
        if not payload.raw_text.strip():
            fail("empty_feedback", "请写下实际反馈")
    provider = get_provider()
    started = perf_counter()
    proposed = (
        ProposedFields(summary=payload.raw_text.strip())
        if payload.decision_id
        else ProposedFields.model_validate(provider.propose(payload.raw_text))
    )
    latency = int((perf_counter() - started) * 1000)
    draft = UpdateDraft(
        organization_id=actor.organization_id,
        work_item_id=work.id,
        decision_id=payload.decision_id,
        actor_id=actor.id,
        raw_text=payload.raw_text,
        proposed_fields=proposed.model_dump(),
        base_version=work.version,
        provider="manual_feedback" if payload.decision_id else provider.name,
        expires_at=now() + timedelta(hours=24),
    )
    db.add(draft)
    db.flush()
    if not payload.decision_id:
        db.add(
            AnalysisRun(
                organization_id=actor.organization_id,
                draft_id=draft.id,
                purpose="update_draft",
                provider=provider.name,
                model=provider.model,
                prompt_version=provider.prompt_version,
                input_evidence_ids=[f"draft:{draft.id}", f"work:{work.id}:v{work.version}"],
                output_schema_version="proposed-fields-v1",
                latency_ms=latency,
                status="rules_fallback",
            )
        )
    db.commit()
    return DraftOut.model_validate(draft)


def owned_draft(db: Db, actor: Actor, draft_id: str) -> UpdateDraft:
    draft = db.scalar(
        select(UpdateDraft)
        .where(
            UpdateDraft.id == draft_id,
            UpdateDraft.organization_id == actor.organization_id,
            UpdateDraft.actor_id == actor.id,
        )
        .with_for_update()
    )
    if draft is None:
        fail("not_found", "未找到此草稿", 404)
    assert draft is not None
    get_work(db, actor, draft.work_item_id)
    if draft.decision_id:
        confirmed_arrangement(db, actor, draft.work_item_id, draft.decision_id)
    return draft


@router.get("/work-updates/drafts/{draft_id}", response_model=DraftOut)
def read_draft(draft_id: str, db: Db, actor: Actor) -> DraftOut:
    return DraftOut.model_validate(owned_draft(db, actor, draft_id))


@router.patch("/work-updates/drafts/{draft_id}", response_model=DraftOut)
def edit_draft(draft_id: str, payload: DraftEdit, db: Db, actor: Actor) -> DraftOut:
    draft = owned_draft(db, actor, draft_id)
    if draft.state != "pending" or utc(draft.expires_at) <= now():
        fail("draft_closed", "草稿已确认或已过期", 409)
    if draft.revision != payload.expected_revision:
        fail("stale_draft", "草稿已变化，请重新查看", 409)
    if draft.decision_id:
        feedback_fields(payload.proposed_fields)
    draft.proposed_fields = payload.proposed_fields.model_dump()
    # SQLAlchemy detects real changes; identical edits safely preserve the revision.
    db.commit()
    run = db.scalar(
        select(AgentRun).where(
            AgentRun.organization_id == actor.organization_id,
            AgentRun.draft_id == draft.id,
            AgentRun.actor_id == actor.id,
        )
    )
    if run:
        from app.modules.agent.approvals import wait_for_review

        db.commit()
        wait_for_review(run, "draft", draft.id, draft.revision)
    return DraftOut.model_validate(draft)


@router.post("/work-updates/drafts/{draft_id}/confirm", response_model=EventOut)
def confirm(draft_id: str, payload: ConfirmInput, db: Db, actor: Actor) -> EventOut:
    run = db.scalar(
        select(AgentRun).where(
            AgentRun.organization_id == actor.organization_id,
            AgentRun.draft_id == draft_id,
            AgentRun.actor_id == actor.id,
        )
    )
    if run is None:
        return confirm_domain(draft_id, payload, db, actor)
    from app.modules.agent.approvals import review
    from app.modules.agent.runtime import authorize

    authorize(db, actor, run.session_hash)
    owned_draft(db, actor, draft_id)
    db.commit()  # Do not hold domain row locks while the checkpoint store writes.

    def apply() -> EventOut:
        authorize(db, actor, run.session_hash)
        return confirm_domain(draft_id, payload, db, actor)

    result = review(
        run,
        "draft",
        draft_id,
        payload.expected_revision,
        fingerprint=request_hash(payload.model_dump()),
        apply=apply,
    )
    assert result is not None
    return result


def confirm_domain(draft_id: str, payload: ConfirmInput, db: Db, actor: Actor) -> EventOut:
    draft = owned_draft(db, actor, draft_id)
    body = {"draft_id": draft_id, **payload.model_dump()}
    existing = replay(db, actor, f"draft:{draft_id}", body)
    if existing:
        return EventOut.model_validate(existing)
    if draft.state != "pending" or utc(draft.expires_at) <= now():
        fail("draft_closed", "草稿已确认或已过期", 409)
    if draft.revision != payload.expected_revision:
        fail("stale_draft", "草稿已变化，请重新查看", 409)
    work = get_work(db, actor, draft.work_item_id, lock=True)
    db.refresh(work)
    ensure_version(work, draft.base_version)
    fields = ProposedFields.model_validate(draft.proposed_fields)
    if draft.decision_id:
        confirmed_arrangement(db, actor, work.id, draft.decision_id)
        feedback_fields(fields)
    event = append_update(
        db,
        actor,
        work,
        fields,
        f"draft:{draft_id}",
        body,
        "decision.feedback" if draft.decision_id else "update.confirmed",
        draft_id,
        {
            "raw_text": draft.raw_text,
            "provider": draft.provider,
            "draft_revision": draft.revision,
            **({"decision_id": draft.decision_id} if draft.decision_id else {}),
        },
    )
    draft.state = "confirmed"
    db.commit()
    return EventOut.model_validate(event)


def feedback_fields(fields: ProposedFields) -> None:
    if fields.lifecycle_status is not None or fields.needs_support is not None:
        fail("feedback_state_change", "安排反馈只记录实际情况；如需变更状态，请单独更新工作", 422)
    if not fields.summary.strip():
        fail("empty_feedback", "请写下实际反馈")
