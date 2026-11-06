"""Source-bound candidates; only an explicit author command makes them effective."""

import hashlib
from typing import Any

from sqlalchemy import Select, and_, false, func, or_, select
from sqlalchemy.orm import Session

from app.core.access import audit, get_work, owner, require_owner, tenant_get, work_scope
from app.core.errors import fail
from app.infrastructure.models import (
    AgentRun,
    Decision,
    DecisionOutcome,
    Membership,
    Organization,
    WorkEvent,
    WorkItem,
    now,
    utc,
)
from app.modules.agent.invalidation import clear_runs, read_barrier
from app.modules.knowledge.index import tokens
from app.modules.knowledge.service import fingerprint
from app.modules.memory.models import MemoryEntry, MemoryUse
from app.modules.memory.schemas import (
    MemoryAction,
    MemoryCommand,
    MemoryEdit,
    MemoryInput,
    MemoryOut,
    MemoryProposal,
    MemorySource,
)


def digest(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def authorize(db: Session, actor: Membership) -> None:
    db.refresh(actor)
    if actor.status != "active":
        fail("access_revoked", "企业权限已失效", 403)
    require_owner(actor)


def command_lock(db: Session, actor: Membership) -> None:
    db.scalar(
        select(Organization)
        .where(Organization.id == actor.organization_id)
        .with_for_update(key_share=True)
    )
    authorize(db, actor)


def scope(
    actor: Membership, *, effective: bool = False, work_item_id: str | None = None
) -> Select[tuple[MemoryEntry]]:
    decisions = select(Decision.id).where(
        Decision.organization_id == actor.organization_id,
        Decision.state == "confirmed",
        Decision.work_item_id.in_(work_scope(actor).with_only_columns(WorkItem.id)),
    )
    if work_item_id:
        decisions = decisions.where(Decision.work_item_id == work_item_id)
    stmt = select(MemoryEntry).where(
        MemoryEntry.organization_id == actor.organization_id,
        MemoryEntry.state != "deleted",
        or_(
            and_(MemoryEntry.kind == "preference", MemoryEntry.actor_id == actor.id),
            and_(
                MemoryEntry.kind == "experience",
                MemoryEntry.decision_id.in_(decisions),
                or_(MemoryEntry.actor_id == actor.id, MemoryEntry.state == "confirmed"),
            ),
        ),
    )
    if not owner(actor):
        stmt = stmt.where(false())
    if effective:
        current_source = select(Decision.id).where(
            Decision.organization_id == actor.organization_id,
            Decision.version == MemoryEntry.source_version,
        )
        stmt = stmt.where(
            MemoryEntry.state == "confirmed",
            or_(MemoryEntry.kind == "preference", MemoryEntry.decision_id.in_(current_source)),
        )
    return stmt


def get(db: Session, actor: Membership, identifier: str, *, edit: bool = False) -> MemoryEntry:
    require_owner(actor)
    stmt = scope(actor).where(MemoryEntry.id == identifier)
    row = db.scalar(
        stmt.with_for_update(key_share=True).execution_options(populate_existing=True)
        if edit
        else stmt
    )
    if row is None or (edit and row.actor_id != actor.id):
        fail("not_found", "未找到本人可管理的条目", 404)
    assert row is not None
    return row


def source(db: Session, actor: Membership, row: MemoryEntry) -> MemorySource:
    if row.kind == "preference":
        if row.actor_id != actor.id:
            fail("not_found", "未找到本人的偏好", 404)
        return MemorySource(
            work_item_id=None,
            decision_id=None,
            outcome_id=None,
            selected_plan=None,
            observed_result=None,
            owner_statement=row.source_text,
            other_outcomes=[],
            outcome_count=0,
            source_hash=digest(row.source_text),
            source_at=utc(row.created_at),
        )
    decision = tenant_get(db, Decision, row.decision_id or "", actor)
    get_work(db, actor, decision.work_item_id)
    if decision.state != "confirmed":
        fail("decision_pending", "经验必须来自已确认决策", 409)
    outcome = db.scalar(
        select(DecisionOutcome).where(
            DecisionOutcome.organization_id == actor.organization_id,
            DecisionOutcome.decision_id == decision.id,
            DecisionOutcome.id == row.outcome_id,
        )
    )
    if outcome is None:
        fail("actual_outcome_required", "请先记录实际结果，再整理经验", 409)
    assert outcome is not None
    count = (
        db.scalar(
            select(func.count())
            .select_from(DecisionOutcome)
            .where(
                DecisionOutcome.organization_id == actor.organization_id,
                DecisionOutcome.decision_id == decision.id,
            )
        )
        or 0
    )
    others = list(
        db.scalars(
            select(DecisionOutcome.observed_result)
            .where(
                DecisionOutcome.organization_id == actor.organization_id,
                DecisionOutcome.decision_id == decision.id,
                DecisionOutcome.id != outcome.id,
            )
            .order_by(DecisionOutcome.recorded_at.desc(), DecisionOutcome.id)
            .limit(8)
        )
    )
    return MemorySource(
        work_item_id=decision.work_item_id,
        decision_id=decision.id,
        outcome_id=outcome.id,
        selected_plan=decision.selected_plan,
        observed_result=outcome.observed_result,
        owner_statement=None,
        other_outcomes=others,
        outcome_count=count,
        source_hash=digest(f"{decision.id}:{decision.version}:{outcome.id}:{outcome.request_hash}"),
        source_at=utc(outcome.recorded_at),
    )


def view(db: Session, actor: Membership, row: MemoryEntry) -> MemoryOut:
    context = source(db, actor, row) if row.state != "deleted" else None
    return MemoryOut(
        id=row.id,
        kind=row.kind,
        actor_id=row.actor_id,
        preference_key=row.preference_key,
        title=row.title,
        content=row.content,
        applicability=row.applicability,
        source_quote=row.source_quote,
        state=row.state,
        version=row.version,
        source=context,
        outdated=bool(context and context.source_hash != row.source_hash),
        can_edit=row.actor_id == actor.id and row.state != "deleted",
        confirmed_at=utc(row.confirmed_at) if row.confirmed_at else None,
        created_at=utc(row.created_at),
        updated_at=utc(row.updated_at),
    )


def event(
    db: Session,
    actor: Membership,
    row: MemoryEntry,
    key: str,
    request_hash: str,
    action: str,
    context: MemorySource | None,
) -> None:
    # Source references and content digests only: deleting a candidate can erase its prose.
    work_id = context.work_item_id if context and row.kind == "experience" else None
    db.add(
        WorkEvent(
            organization_id=actor.organization_id,
            actor_id=actor.id,
            work_item_id=work_id,
            memory_entry_id=None if work_id else row.id,
            event_type="memory." + action,
            event_payload={
                "entry_id": row.id,
                "kind": row.kind,
                "version": row.version,
                "state": row.state,
                "source_hash": row.source_hash,
                "content_hash": digest(row.content + row.applicability),
            },
            source_ref="memory:" + row.id,
            idempotency_key=key,
            request_hash=request_hash,
        )
    )
    audit(db, actor, "memory." + action, row.id)


def create(db: Session, actor: Membership, payload: MemoryInput) -> MemoryOut:
    command_lock(db, actor)
    request_hash = fingerprint(payload, "memory.create")
    old = db.scalar(
        select(WorkEvent).where(
            WorkEvent.organization_id == actor.organization_id,
            WorkEvent.actor_id == actor.id,
            WorkEvent.idempotency_key == str(payload.idempotency_key),
        )
    )
    if old:
        if old.request_hash != request_hash:
            fail("idempotency_conflict", "同一请求不能提交不同来源", 409)
        identifier = str(old.event_payload.get("entry_id", ""))
        return view(db, actor, get(db, actor, identifier))
    row = MemoryEntry(
        organization_id=actor.organization_id,
        kind=payload.kind,
        actor_id=actor.id,
        decision_id=str(payload.decision_id) if payload.decision_id else None,
        outcome_id=str(payload.outcome_id) if payload.outcome_id else None,
        preference_key=payload.preference_key,
        source_text=payload.source_text,
        source_hash="",
        title="待整理的经验" if payload.kind == "experience" else "待整理的偏好",
        created_at=now(),
        request_key=str(payload.idempotency_key),
        request_hash=request_hash,
    )
    context = source(db, actor, row)
    row.source_hash = context.source_hash
    if row.decision_id:
        decision = tenant_get(db, Decision, row.decision_id, actor)
        row.source_version, row.title = decision.version, decision.title
    db.add(row)
    db.flush()
    event(db, actor, row, str(payload.idempotency_key), request_hash, "created", context)
    db.commit()
    return view(db, actor, row)


def bind(db: Session, row: MemoryEntry, run: AgentRun) -> None:
    if not db.scalar(
        select(MemoryUse.id).where(
            MemoryUse.organization_id == row.organization_id,
            MemoryUse.entry_id == row.id,
            MemoryUse.run_id == run.id,
        )
    ):
        db.add(MemoryUse(organization_id=row.organization_id, entry_id=row.id, run_id=run.id))


def invalidate(
    db: Session, organization_id: str, entries: Select[tuple[str]], *, except_run: str = ""
) -> None:
    read_barrier(db, organization_id, except_run)
    run_ids = select(MemoryUse.run_id).where(
        MemoryUse.organization_id == organization_id, MemoryUse.entry_id.in_(entries)
    )
    clear_runs(db, organization_id, run_ids, except_run)


def command(
    db: Session, actor: Membership, identifier: str, payload: MemoryCommand, action: str
) -> tuple[MemoryEntry, str, bool]:
    command_lock(db, actor)
    row = tenant_get(db, MemoryEntry, identifier, actor)
    if row.actor_id != actor.id:
        fail("not_found", "只能管理本人的条目", 404)
    request_hash = fingerprint(payload, "memory." + action, identifier)
    old = db.scalar(
        select(WorkEvent).where(
            WorkEvent.organization_id == actor.organization_id,
            WorkEvent.actor_id == actor.id,
            WorkEvent.idempotency_key == str(payload.idempotency_key),
        )
    )
    if row.state == "deleted":
        if not old or old.event_type != "memory.delete" or old.request_hash != request_hash:
            fail("not_found", "条目已删除", 404)
    else:
        row = get(db, actor, identifier, edit=True)
    if old:
        if old.request_hash != request_hash:
            fail("idempotency_conflict", "同一请求不能提交不同内容", 409)
        return row, request_hash, True
    if row.version != payload.expected_version:
        fail("version_conflict", "条目已变化，请刷新后核对", 409)
    return row, request_hash, False


def validate_proposal(proposal: MemoryProposal, context: MemorySource) -> None:
    original = context.observed_result or context.owner_statement or ""
    if not proposal.source_quote.strip() or proposal.source_quote not in original:
        raise ValueError("unverified_quote")
    if not all(
        value.strip() and "\x00" not in value
        for value in (proposal.title, proposal.content, proposal.applicability)
    ):
        raise ValueError("invalid_output")


def edit(
    db: Session,
    actor: Membership,
    identifier: str,
    payload: MemoryEdit,
    *,
    except_run: str = "",
    commit: bool = True,
) -> MemoryOut:
    row, request_hash, replay = command(db, actor, identifier, payload, "edit")
    if replay:
        return view(db, actor, row)
    context = source(db, actor, row)
    if context.source_hash != payload.expected_source_hash:
        fail("source_changed", "实际结果已变化，请先核对最新来源", 409)
    proposal = MemoryProposal.model_validate(
        payload.model_dump(include={"title", "content", "applicability", "source_quote"})
    )
    try:
        validate_proposal(proposal, context)
    except ValueError:
        fail("unverified_quote", "引用必须逐字来自实际结果或本人原始输入", 422)
    invalidate(
        db,
        actor.organization_id,
        select(MemoryEntry.id).where(
            MemoryEntry.organization_id == actor.organization_id, MemoryEntry.id == row.id
        ),
        except_run=except_run,
    )
    for key, value in proposal.model_dump().items():
        setattr(row, key, value)
    row.source_hash = context.source_hash
    row.source_version = (
        tenant_get(db, Decision, row.decision_id, actor).version if row.decision_id else None
    )
    row.state, row.confirmed_at, row.updated_at, row.version = (
        "proposed",
        None,
        now(),
        row.version + 1,
    )
    row.search_text = ""  # Candidate prose is never indexed as effective memory.
    event(db, actor, row, str(payload.idempotency_key), request_hash, "edit", context)
    if commit:
        db.commit()
    else:
        db.flush()
    return view(db, actor, row)


def action(db: Session, actor: Membership, identifier: str, payload: MemoryAction) -> MemoryOut:
    row, request_hash, replay = command(db, actor, identifier, payload, payload.action)
    if replay:
        return view(db, actor, row)
    context = source(db, actor, row)
    if payload.action == "confirm":
        if (
            row.state != "proposed"
            or context.source_hash != row.source_hash
            or payload.expected_source_hash != row.source_hash
        ):
            fail("source_changed", "请先编辑并核对当前候选及最新实际结果", 409)
        try:
            validate_proposal(
                MemoryProposal(
                    title=row.title,
                    content=row.content,
                    applicability=row.applicability,
                    source_quote=row.source_quote,
                ),
                context,
            )
        except ValueError:
            fail("candidate_incomplete", "请先整理结论、适用条件和来源引文", 409)
        if row.kind == "preference" and db.scalar(
            select(MemoryEntry.id).where(
                MemoryEntry.organization_id == actor.organization_id,
                MemoryEntry.actor_id == actor.id,
                MemoryEntry.preference_key == row.preference_key,
                MemoryEntry.state == "confirmed",
                MemoryEntry.id != row.id,
            )
        ):
            fail("preference_conflict", "同类偏好已生效，请先修订或撤销原偏好", 409)
    invalidate(
        db,
        actor.organization_id,
        select(MemoryEntry.id).where(
            MemoryEntry.organization_id == actor.organization_id, MemoryEntry.id == row.id
        ),
    )
    row.state = {"confirm": "confirmed", "revoke": "revoked", "delete": "deleted"}[payload.action]
    row.confirmed_at = now() if payload.action == "confirm" else None
    row.updated_at, row.version = now(), row.version + 1
    row.search_text = (
        tokens(
            " ".join(
                (
                    row.title,
                    row.content,
                    row.applicability,
                    context.selected_plan or "",
                    context.observed_result or "",
                )
            )
        )
        if payload.action == "confirm"
        else ""
    )
    if payload.action == "delete":
        row.title, row.content, row.applicability, row.source_quote, row.source_text = (
            "已删除条目",
            "",
            "",
            "",
            "",
        )
    event(db, actor, row, str(payload.idempotency_key), request_hash, payload.action, context)
    db.commit()
    return view(db, actor, row)


def model_context(db: Session, actor: Membership, row: MemoryEntry) -> dict[str, Any]:
    context = source(db, actor, row)
    return {
        "kind": row.kind,
        "preference_key": row.preference_key,
        "source_text": (context.observed_result or context.owner_statement or "")[:1600],
        "selected_plan": (context.selected_plan or "")[:600],
        "other_outcomes": [value[:200] for value in context.other_outcomes[:3]],
        "outcome_count": context.outcome_count,
        "notice": "来源为有界片段；其他结果可能未完全覆盖，不得概括为普遍成功规律。"
        "确认页提供完整原文。",
    }
