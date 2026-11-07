from datetime import timedelta

from fastapi import APIRouter
from sqlalchemy import and_, func, or_, select

from app.core.access import audit, get_work, page_rows, require_owner, tenant_get, work_scope
from app.core.auth import Actor, Db
from app.core.errors import fail
from app.core.schemas import Page
from app.infrastructure.models import (
    AgentRun,
    AgentStep,
    AnalysisRun,
    Decision,
    DecisionOutcome,
    EvidenceSnapshot,
    Signal,
    UpdateDraft,
    WorkEvent,
    WorkItem,
    now,
    utc,
)
from app.modules.decisions.arrangements import (
    confirmed_arrangement,
    feedback_out,
    feedback_query,
    list_arrangements,
)
from app.modules.decisions.schemas import (
    ArrangementFeedbackOut,
    DecisionConfirm,
    DecisionInput,
    DecisionListOut,
    DecisionOut,
    DecisionView,
    OutcomeInput,
    OutcomeOut,
    WorkArrangementOut,
)
from app.modules.intelligence.schemas import AnswerOut
from app.modules.intelligence.signals import refresh_work
from app.modules.organizations.api import Limit, Offset
from app.modules.work_items.service import request_hash

router = APIRouter(tags=["decisions"])


@router.get("/work-arrangements", response_model=Page[WorkArrangementOut])
def arrangements(
    db: Db, actor: Actor, mine: bool = False, offset: Offset = 0, limit: Limit = 50
) -> Page[WorkArrangementOut]:
    return list_arrangements(db, actor, mine=mine, offset=offset, limit=limit)


@router.get("/work-items/{work_id}/arrangements", response_model=Page[WorkArrangementOut])
def work_arrangements(
    work_id: str,
    db: Db,
    actor: Actor,
    decision_id: str | None = None,
    offset: Offset = 0,
    limit: Limit = 20,
) -> Page[WorkArrangementOut]:
    return list_arrangements(
        db, actor, work_id=work_id, decision_id=decision_id, offset=offset, limit=limit
    )


@router.get(
    "/work-items/{work_id}/arrangements/{decision_id}/feedback",
    response_model=Page[ArrangementFeedbackOut],
)
def arrangement_feedback(
    work_id: str,
    decision_id: str,
    db: Db,
    actor: Actor,
    offset: Offset = 0,
    limit: Limit = 20,
) -> Page[ArrangementFeedbackOut]:
    confirmed_arrangement(db, actor, work_id, decision_id)
    stmt = feedback_query(actor).where(UpdateDraft.decision_id == decision_id)
    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    rows = db.execute(
        stmt.order_by(WorkEvent.recorded_at.desc(), WorkEvent.id).offset(offset).limit(limit)
    )
    return Page(
        items=[feedback_out(event, target) for event, target in rows],
        total=total,
        offset=offset,
        limit=limit,
    )


def confirmation_hash(payload: DecisionConfirm) -> str:
    # Preserve receipts created before optional, explicit follow-up scheduling existed.
    return request_hash(
        payload.model_dump(
            mode="json", exclude={"follow_up_at"} if payload.follow_up_at is None else None
        )
    )


def source_run(db: Db, actor: Actor, analysis_id: str) -> AgentRun | None:
    return db.scalar(
        select(AgentRun)
        .join(
            AgentStep,
            (AgentStep.organization_id == AgentRun.organization_id)
            & (AgentStep.run_id == AgentRun.id),
        )
        .where(
            AgentRun.organization_id == actor.organization_id,
            AgentRun.actor_id == actor.id,
            AgentStep.analysis_id == analysis_id,
        )
    )


def decision_event(
    db: Db, actor: Actor, decision: Decision, kind: str, key: str, summary: str
) -> None:
    db.add(
        WorkEvent(
            organization_id=actor.organization_id,
            work_item_id=decision.work_item_id,
            actor_id=actor.id,
            event_type=kind,
            event_payload={"decision_id": decision.id, "confirmed": {"summary": summary}},
            source_ref=f"decision:{decision.id}",
            idempotency_key=key,
            request_hash=request_hash({"summary": summary}),
        )
    )
    audit(db, actor, kind, decision.id)


@router.post("/decisions", response_model=DecisionOut, status_code=201)
def prepare(payload: DecisionInput, db: Db, actor: Actor) -> DecisionOut:
    require_owner(actor)
    from app.modules.memory.service import command_lock

    command_lock(db, actor)
    work = get_work(db, actor, payload.work_item_id, lock=True)
    fingerprint = request_hash(payload.model_dump())
    old = db.scalar(
        select(Decision).where(
            Decision.organization_id == actor.organization_id,
            Decision.actor_id == actor.id,
            Decision.idempotency_key == payload.idempotency_key,
        )
    )
    if old:
        if old.request_hash != fingerprint:
            fail("idempotency_conflict", "同一提交标识不能用于不同内容", 409)
        return DecisionOut.model_validate(old)
    analysis = tenant_get(db, AnalysisRun, payload.analysis_id, actor)
    if (
        analysis.actor_id != actor.id
        or analysis.purpose not in {"evidence_qa", "agent_read"}
        or not analysis.result
    ):
        fail("not_found", "未找到本人的分析记录", 404)
    if utc(analysis.recorded_at) < now() - timedelta(minutes=30):
        fail("analysis_expired", "分析已超过三十分钟，请重新询问后再准备决策", 409)
    agent_run = source_run(db, actor, analysis.id)
    if analysis.purpose == "agent_read":
        if agent_run is None:
            fail("not_found", "未找到已完成的分析任务", 404)
        assert agent_run is not None
        from app.modules.agent.runtime import load

        load(db, actor, agent_run.id)
        if agent_run.state != "completed" or agent_run.answer != analysis.result:
            fail("analysis_incomplete", "分析任务尚未完成", 409)
    answer = AnswerOut.model_validate(analysis.result)
    suggestion = next((s for s in answer.suggestions if s.work_item_id == work.id), None)
    if suggestion is None:
        fail("no_suggestion", "此事项尚无可确认的建议", 409)
    assert suggestion is not None
    evidence = tenant_get(db, EvidenceSnapshot, suggestion.evidence_id, actor)
    if work.version != evidence.work_version:
        fail("stale_analysis", "工作记录已变化，请重新询问后再准备决策", 409)
    current_signals = refresh_work(db, work)
    expected_signals = {s.id: s.version for s in answer.signals if s.work_item_id == work.id}
    if {s.id: s.version for s in current_signals} != expected_signals:
        fail("stale_signal", "风险提示已变化，请重新询问", 409)
    if suggestion.signal_id:
        signal = tenant_get(db, Signal, suggestion.signal_id, actor)
        if signal.state != "active" or signal.version != suggestion.signal_version:
            fail("stale_signal", "风险提示已变化，请重新询问", 409)
    decision = Decision(
        organization_id=actor.organization_id,
        work_item_id=work.id,
        signal_id=suggestion.signal_id,
        signal_version=suggestion.signal_version,
        analysis_id=analysis.id,
        actor_id=actor.id,
        title=work.title,
        work_version=work.version,
        context_snapshot={
            "evidence": next(
                e.model_dump(mode="json") for e in answer.evidence if e.id == evidence.id
            ),
            "interpretation": suggestion.interpretation,
            "analysis_mode": answer.mode,
            "analysis_time": answer.generated_at.isoformat(),
            "signal_versions": expected_signals,
        },
        options=[o.model_dump() for o in suggestion.options],
        idempotency_key=payload.idempotency_key,
        request_hash=fingerprint,
    )
    db.add(decision)
    db.flush()
    audit(db, actor, "decision.prepared", decision.id)
    db.commit()
    if agent_run:
        from app.modules.agent.approvals import wait_for_review

        wait_for_review(agent_run, "decision", decision.id, decision.version)
    return DecisionOut.model_validate(decision)


@router.get("/decisions", response_model=Page[DecisionListOut])
def list_decisions(
    db: Db,
    actor: Actor,
    offset: Offset = 0,
    limit: Limit = 50,
    mine: bool = False,
    initiative_id: str | None = None,
    view: DecisionView = "all",
) -> Page[DecisionListOut]:
    require_owner(actor)
    authorized_work = work_scope(actor)
    if initiative_id is not None:
        authorized_work = authorized_work.where(WorkItem.initiative_id == initiative_id)
    outcome_totals = (
        select(
            DecisionOutcome.organization_id,
            DecisionOutcome.decision_id,
            func.count(DecisionOutcome.id).label("outcome_count"),
        )
        .where(DecisionOutcome.organization_id == actor.organization_id)
        .group_by(DecisionOutcome.organization_id, DecisionOutcome.decision_id)
        .subquery()
    )
    outcome_count = func.coalesce(outcome_totals.c.outcome_count, 0)
    stmt = (
        select(Decision, outcome_count)
        .outerjoin(
            outcome_totals,
            and_(
                outcome_totals.c.organization_id == Decision.organization_id,
                outcome_totals.c.decision_id == Decision.id,
            ),
        )
        .where(
            Decision.organization_id == actor.organization_id,
            Decision.work_item_id.in_(authorized_work.with_only_columns(WorkItem.id)),
        )
    )
    if mine:
        stmt = stmt.where(Decision.actor_id == actor.id)
    pending = Decision.state == "pending"
    follow_up = and_(Decision.state == "confirmed", outcome_count == 0)
    if view == "pending":
        stmt = stmt.where(pending)
    elif view == "follow_up":
        stmt = stmt.where(follow_up)
    elif view == "recorded":
        stmt = stmt.where(Decision.state == "confirmed", outcome_count > 0)
    elif view == "action_required":
        stmt = stmt.where(or_(pending, follow_up))
    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    rows = db.execute(
        stmt.order_by(Decision.created_at.desc(), Decision.id).offset(offset).limit(limit)
    ).all()
    return Page(
        items=[
            DecisionListOut(
                **DecisionOut.model_validate(decision).model_dump(), outcome_count=count
            )
            for decision, count in rows
        ],
        total=total,
        offset=offset,
        limit=limit,
    )


@router.get("/decisions/{decision_id}", response_model=DecisionOut)
def read(decision_id: str, db: Db, actor: Actor) -> DecisionOut:
    require_owner(actor)
    decision = tenant_get(db, Decision, decision_id, actor)
    get_work(db, actor, decision.work_item_id)
    return DecisionOut.model_validate(decision)


@router.post("/decisions/{decision_id}/confirm", response_model=DecisionOut)
def confirm(decision_id: str, payload: DecisionConfirm, db: Db, actor: Actor) -> DecisionOut:
    require_owner(actor)
    decision = tenant_get(db, Decision, decision_id, actor)
    if decision.actor_id != actor.id:
        fail("not_found", "只能确认本人准备的方案", 404)
    if payload.selected_option not in {option["id"] for option in decision.options}:
        fail("invalid_option", "请选择本次建议中的方案")
    run = source_run(db, actor, decision.analysis_id)
    if run is None:
        return confirm_domain(decision_id, payload, db, actor)
    from app.modules.agent.approvals import review
    from app.modules.agent.runtime import load
    from app.modules.memory.service import command_lock

    command_lock(db, actor)
    load(db, actor, run.id, context=decision.state != "confirmed")
    db.commit()

    def apply() -> DecisionOut:
        command_lock(db, actor)
        load(db, actor, run.id, context=decision.state != "confirmed")
        return confirm_domain(decision_id, payload, db, actor)

    result = review(
        run,
        "decision",
        decision_id,
        payload.expected_version,
        fingerprint=confirmation_hash(payload),
        apply=apply,
    )
    assert result is not None
    return result


def confirm_domain(decision_id: str, payload: DecisionConfirm, db: Db, actor: Actor) -> DecisionOut:
    require_owner(actor)
    initial = tenant_get(db, Decision, decision_id, actor)
    if initial.actor_id != actor.id:
        fail("not_found", "只能确认本人准备的方案", 404)
    work = get_work(db, actor, initial.work_item_id, lock=True)
    decision = tenant_get(db, Decision, decision_id, actor, lock=True)
    fingerprint = confirmation_hash(payload)
    if decision.state == "confirmed":
        if decision.confirmation_hash != fingerprint:
            fail("decision_closed", "该决策已确认，不能覆盖历史选择", 409)
        return DecisionOut.model_validate(decision)
    if decision.version != payload.expected_version or work.version != decision.work_version:
        fail("stale_decision", "工作或方案已变化，请重新询问并准备决策", 409)
    current_signals = refresh_work(db, work)
    if {s.id: s.version for s in current_signals} != decision.context_snapshot["signal_versions"]:
        fail("stale_signal", "风险提示已变化，请重新询问并准备决策", 409)
    if utc(decision.created_at) < now() - timedelta(minutes=30):
        fail("decision_expired", "方案已超过三十分钟，请重新核对记录后准备决策", 409)
    if decision.signal_id:
        signal = tenant_get(db, Signal, decision.signal_id, actor)
        if signal.state != "active" or signal.version != decision.signal_version:
            fail("stale_signal", "风险提示已变化，请重新询问并准备决策", 409)
    if payload.selected_option not in {o["id"] for o in decision.options}:
        fail("invalid_option", "请选择本次建议中的方案")
    if payload.follow_up_at and not now() < payload.follow_up_at <= now() + timedelta(days=365):
        fail("invalid_follow_up_time", "跟进时间须在未来一年内", 422)
    decision.state = "confirmed"
    decision.selected_option = payload.selected_option
    decision.selected_plan = payload.selected_plan
    decision.follow_up = payload.follow_up
    decision.follow_up_at = payload.follow_up_at
    decision.confirmed_by = actor.id
    decision.confirmed_at = now()
    decision.confirmation_hash = fingerprint
    decision_event(
        db, actor, decision, "decision.confirmed", f"decision:{decision.id}", payload.selected_plan
    )
    db.commit()
    return DecisionOut.model_validate(decision)


@router.get("/decisions/{decision_id}/outcomes", response_model=Page[OutcomeOut])
def outcomes(
    decision_id: str, db: Db, actor: Actor, offset: Offset = 0, limit: Limit = 50
) -> Page[OutcomeOut]:
    require_owner(actor)
    decision = tenant_get(db, Decision, decision_id, actor)
    get_work(db, actor, decision.work_item_id)
    rows, total = page_rows(
        db,
        select(DecisionOutcome)
        .where(
            DecisionOutcome.organization_id == actor.organization_id,
            DecisionOutcome.decision_id == decision_id,
        )
        .order_by(DecisionOutcome.recorded_at.desc(), DecisionOutcome.id),
        offset,
        limit,
    )
    return Page(
        items=[OutcomeOut.model_validate(r) for r in rows], total=total, offset=offset, limit=limit
    )


@router.post("/decisions/{decision_id}/outcomes", response_model=OutcomeOut, status_code=201)
def record_outcome(decision_id: str, payload: OutcomeInput, db: Db, actor: Actor) -> OutcomeOut:
    require_owner(actor)
    from app.modules.memory.models import MemoryEntry
    from app.modules.memory.service import command_lock, invalidate

    command_lock(db, actor)
    decision = tenant_get(db, Decision, decision_id, actor, lock=True)
    get_work(db, actor, decision.work_item_id)
    if decision.state != "confirmed":
        fail("decision_pending", "请先确认方案再记录结果", 409)
    fingerprint = request_hash(payload.model_dump())
    old = db.scalar(
        select(DecisionOutcome).where(
            DecisionOutcome.organization_id == actor.organization_id,
            DecisionOutcome.decision_id == decision.id,
            DecisionOutcome.idempotency_key == payload.idempotency_key,
        )
    )
    if old:
        if old.request_hash != fingerprint:
            fail("idempotency_conflict", "同一提交标识不能用于不同内容", 409)
        return OutcomeOut.model_validate(old)
    for ref in payload.evidence_refs:
        evidence = tenant_get(db, EvidenceSnapshot, ref, actor)
        if evidence.work_item_id != decision.work_item_id:
            fail("invalid_evidence", "结果依据必须属于该工作事项")
    outcome = DecisionOutcome(
        organization_id=actor.organization_id,
        decision_id=decision.id,
        actor_id=actor.id,
        observed_result=payload.observed_result,
        evidence_refs=payload.evidence_refs,
        idempotency_key=payload.idempotency_key,
        request_hash=fingerprint,
    )
    db.add(outcome)
    db.flush()
    decision.version += 1
    invalidate(
        db,
        actor.organization_id,
        select(MemoryEntry.id).where(
            MemoryEntry.organization_id == actor.organization_id,
            MemoryEntry.decision_id == decision.id,
        ),
    )
    decision_event(
        db, actor, decision, "decision.outcome", f"outcome:{outcome.id}", payload.observed_result
    )
    db.commit()
    return OutcomeOut.model_validate(outcome)
