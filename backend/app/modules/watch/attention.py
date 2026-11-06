"""Grounded review items. No generated text is promoted into business facts."""

from datetime import timedelta

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.access import audit, tenant_get
from app.core.errors import fail
from app.infrastructure.models import (
    Decision,
    DecisionOutcome,
    EvidenceSnapshot,
    Membership,
    WorkItem,
    now,
    utc,
)
from app.modules.agent import runtime
from app.modules.intelligence.signals import RULES, categories, evidence_out, snapshot
from app.modules.watch import service
from app.modules.watch.models import AttentionItem, AttentionReview, WatchRun
from app.modules.watch.schemas import AttentionAction, AttentionOut
from app.modules.watch.sources import source_stamp


def category(work: WorkItem) -> str | None:
    active = categories(work, now())
    return next(
        (key for key in ("deadline_blocked", "overdue", "support", "stale") if key in active), None
    )


def basis(work: WorkItem, key: str) -> str:
    return service.fingerprint({"work": work.id, "version": work.version, "category": key})


def upsert(
    db: Session,
    run: WatchRun,
    kind: str,
    key: str,
    digest: str,
    *,
    work: WorkItem | None = None,
    decision: Decision | None = None,
    evidence: EvidenceSnapshot | None = None,
) -> AttentionItem:
    dedup = service.fingerprint(
        {
            "kind": kind,
            "work": work.id if work else None,
            "decision": decision.id if decision else None,
        }
    )
    row = db.scalar(
        select(AttentionItem)
        .where(
            AttentionItem.organization_id == run.organization_id,
            AttentionItem.policy_id == run.policy_id,
            AttentionItem.dedup_key == dedup,
        )
        .with_for_update()
    )
    if row is None:
        row = AttentionItem(
            organization_id=run.organization_id,
            policy_id=run.policy_id,
            grant_id=run.grant_id,
            run_id=run.id,
            kind=kind,
            category=key,
            basis_hash=digest,
            dedup_key=dedup,
            work_item_id=work.id if work else None,
            decision_id=decision.id if decision else None,
        )
        db.add(row)
    elif row.basis_hash != digest or row.grant_id != run.grant_id or row.state == "invalidated":
        row.state, row.snoozed_until, row.review_note = "open", None, None
        row.changed_at, row.basis_hash, row.category, row.grant_id = (
            now(),
            digest,
            key,
            run.grant_id,
        )
        row.run_id = run.id
    elif row.state == "snoozed" and row.snoozed_until and utc(row.snoozed_until) <= now():
        row.state, row.snoozed_until = "open", None
    row.evidence_id = evidence.id if evidence else None
    db.flush()
    return row


def outcomes_exist(db: Session, decision: Decision) -> bool:
    return (
        db.scalar(
            select(DecisionOutcome.id)
            .where(
                DecisionOutcome.organization_id == decision.organization_id,
                DecisionOutcome.decision_id == decision.id,
            )
            .limit(1)
        )
        is not None
    )


def reconcile(db: Session, actor: Membership, run: WatchRun, works: list[WorkItem]) -> None:
    """Runs under the scheduler's organization lock, independent of model availability."""
    if run.coverage_count == 0:
        upsert(db, run, "coverage", "no_data", "empty")
    else:
        for item in db.scalars(
            select(AttentionItem).where(
                AttentionItem.organization_id == run.organization_id,
                AttentionItem.policy_id == run.policy_id,
                AttentionItem.kind == "coverage",
                AttentionItem.state != "invalidated",
            )
        ):
            item.state, item.changed_at = "invalidated", now()
    for work in works:
        issue, _ = source_stamp(db, work)
        key = issue or category(work)
        if key:
            upsert(
                db,
                run,
                "work",
                key,
                basis(work, key),
                work=work,
                evidence=snapshot(db, work) if not issue else None,
            )
        else:
            for item in db.scalars(
                select(AttentionItem).where(
                    AttentionItem.organization_id == run.organization_id,
                    AttentionItem.policy_id == run.policy_id,
                    AttentionItem.kind == "work",
                    AttentionItem.work_item_id == work.id,
                    AttentionItem.state != "invalidated",
                )
            ):
                if item.category != "plan" or item.basis_hash != basis(work, "plan"):
                    item.state, item.changed_at = "invalidated", now()
        if issue:
            continue
        for decision in db.scalars(
            select(Decision)
            .where(
                Decision.organization_id == run.organization_id,
                Decision.work_item_id == work.id,
                Decision.confirmed_by == actor.id,
                Decision.state == "confirmed",
                Decision.follow_up_at <= now(),
            )
            .order_by(Decision.follow_up_at)
            .limit(100)
        ):
            if outcomes_exist(db, decision):
                for item in db.scalars(
                    select(AttentionItem).where(
                        AttentionItem.organization_id == run.organization_id,
                        AttentionItem.policy_id == run.policy_id,
                        AttentionItem.decision_id == decision.id,
                        AttentionItem.state != "result_recorded",
                    )
                ):
                    item.state, item.changed_at = "result_recorded", now()
                continue
            upsert(
                db,
                run,
                "follow_up",
                "follow_up_due",
                service.fingerprint({"decision": decision.id, "version": decision.version}),
                work=work,
                decision=decision,
            )


def plan(db: Session, actor: Membership, run: WatchRun) -> None:
    if not run.agent_run_id or not run.work_item_id:
        return
    child = runtime.read(db, actor, run.agent_run_id)
    if child.state != "completed" or child.answer is None or not child.answer.suggestions:
        return
    work = db.get(WorkItem, run.work_item_id)
    if work is None:
        return
    key = category(work) or "plan"
    row = upsert(db, run, "work", key, basis(work, key), work=work, evidence=snapshot(db, work))
    # Attach an actual, validated graph; do not duplicate its answers in another model.
    row.run_id = run.id


def view(db: Session, actor: Membership, item: AttentionItem) -> AttentionOut | None:
    try:
        policy = service.authorize(db, actor, item.grant_id)
    except HTTPException:
        return None
    work = None
    state = item.state
    if item.work_item_id:
        work = db.scalar(service.scope(policy, actor).where(WorkItem.id == item.work_item_id))
        if work is None:
            return None
    evidence = None
    agent_id = None
    if item.kind == "work" and work:
        issue, _ = source_stamp(db, work)
        key = issue or category(work) or "plan"
        if key != item.category or item.basis_hash != basis(work, key):
            state = "invalidated"
        elif not issue:
            source = db.get(EvidenceSnapshot, item.evidence_id) if item.evidence_id else None
            evidence = evidence_out(db, actor, source) if source else None
            run = db.get(WatchRun, item.run_id)
            if run and run.agent_run_id:
                try:
                    child = runtime.read(db, actor, run.agent_run_id)
                    if child.state == "completed" and child.answer:
                        agent_id = child.id
                except HTTPException:
                    pass
            if item.category == "plan" and agent_id is None:
                state, evidence = "invalidated", None
    elif item.kind == "follow_up":
        decision = db.get(Decision, item.decision_id) if item.decision_id else None
        if decision is None or not decision.follow_up_at or utc(decision.follow_up_at) > now():
            state = "invalidated"
        elif work and source_stamp(db, work)[0]:
            state = "invalidated"
        elif outcomes_exist(db, decision):
            state = "result_recorded"
    elif db.scalar(service.scope(policy, actor).limit(1)):
        state = "invalidated"
    if state == "snoozed" and item.snoozed_until and utc(item.snoozed_until) <= now():
        state = "open"
    descriptions: dict[str, tuple[str, str]] = {
        **{key: (value[1], value[2]) for key, value in RULES.items()},
        "plan": ("推进建议待审阅", "依据当前已确认记录整理了候选下一步，尚未执行业务修改。"),
        "source_unavailable": ("来源更新失败", "来源暂不可核对；停止根据旧内容新增推进判断。"),
        "source_stale": ("来源待更新", "来源超过二十四小时未成功核对；实际进展仍未知。"),
        "no_data": (
            "关注范围尚无可读取的工作",
            "请补充已确认事项或接入授权来源；暂无依据判断项目状态。",
        ),
        "follow_up_due": (
            "到了确认的跟进时间",
            "已到你明确设置的跟进时间，尚未记录实际结果；不代表工作逾期。",
        ),
    }
    title, explanation = descriptions[item.category]
    if state == "invalidated":
        explanation, evidence, agent_id = (
            "依据或来源已变化，旧建议已失效；不能据此认定问题已解决。",
            None,
            None,
        )
    elif state == "result_recorded":
        explanation = "已有人工记录的实际结果，请查看决策；记录结果不代表问题一定已解决。"
    return AttentionOut.model_validate(
        dict(
            id=item.id,
            policy_id=policy.id,
            policy_name=policy.name,
            kind=item.kind,
            category=item.category,
            title=title,
            explanation=explanation,
            work_item_id=item.work_item_id,
            work_title=work.title if work else None,
            decision_id=item.decision_id,
            agent_run_id=agent_id,
            evidence=evidence,
            state=state,
            version=item.version,
            snoozed_until=utc(item.snoozed_until) if item.snoozed_until else None,
            review_note=item.review_note,
            created_at=utc(item.created_at),
            changed_at=utc(item.changed_at),
        )
    )


def review(
    db: Session, actor: Membership, identifier: str, payload: AttentionAction
) -> AttentionOut:
    service.command_lock(db, actor)
    item = tenant_get(db, AttentionItem, identifier, actor, lock=True)
    current = view(db, actor, item)
    if current is None:
        fail("not_found", "关注项已失效或不在当前授权范围", 404)
    assert current is not None
    digest = service.fingerprint({"item": identifier, **payload.model_dump(mode="json")})
    previous = db.scalar(
        select(AttentionReview).where(
            AttentionReview.organization_id == actor.organization_id,
            AttentionReview.actor_id == actor.id,
            AttentionReview.request_key == str(payload.idempotency_key),
        )
    )
    if previous:
        if previous.request_hash != digest:
            fail("idempotency_conflict", "同一请求不能改变处理内容", 409)
        return current
    if item.version != payload.expected_version or current.state in {
        "invalidated",
        "result_recorded",
    }:
        fail("context_changed", "关注项或依据已变化，请刷新后重新核对", 409)
    if payload.snoozed_until and not now() < payload.snoozed_until <= now() + timedelta(days=30):
        fail("invalid_snooze_time", "暂缓时间须在未来三十天内", 422)
    item.state = (
        "snoozed"
        if payload.action == "snooze"
        else "open"
        if payload.action == "reopen"
        else "dismissed"
    )
    item.snoozed_until, item.review_note = payload.snoozed_until, payload.note
    item.version += 1
    item.changed_at = now()
    db.add(
        AttentionReview(
            organization_id=actor.organization_id,
            item_id=item.id,
            actor_id=actor.id,
            action=payload.action,
            note=payload.note,
            request_key=str(payload.idempotency_key),
            request_hash=digest,
        )
    )
    audit(db, actor, "attention." + payload.action, item.id)
    db.commit()
    updated = view(db, actor, item)
    assert updated is not None
    return updated
