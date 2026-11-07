"""Bounded background steps over the existing LangGraph read loop; no autonomous business writes."""

from datetime import timedelta
from uuid import NAMESPACE_URL, UUID, uuid5

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import Settings, settings
from app.core.errors import fail
from app.infrastructure.models import AgentRun, Membership, Organization, WorkItem, now
from app.modules.agent import runtime
from app.modules.agent.invalidation import clear_runs
from app.modules.agent.schemas import AdvanceInput, RunInput
from app.modules.ai_admin.service import effective_config
from app.modules.intelligence.signals import categories
from app.modules.model_gateway.contracts import ModelFailure
from app.modules.watch import attention, scheduler, service
from app.modules.watch.models import WatchPolicy, WatchRun
from app.modules.watch.sources import context_hash, source_stamp


def load(db: Session, organization_id: str, identifier: str, version: int) -> WatchRun | None:
    db.scalar(
        select(Organization)
        .where(Organization.id == organization_id)
        .with_for_update(key_share=True)
    )
    row = db.scalar(
        select(WatchRun)
        .where(WatchRun.organization_id == organization_id, WatchRun.id == identifier)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if row is None or row.state != "running" or row.version != version:
        db.rollback()
        return None
    return row


def config(db: Session, actor: Membership, development: Settings | None) -> Settings:
    if development is not None:
        if settings().environment != "test" or development.environment != "test":
            fail("scope_forbidden", "开发验收配置只可用于隔离测试", 403)
        return development
    return effective_config(db, actor)


def finish(db: Session, row: WatchRun, outcome: str, *, state: str = "completed") -> None:
    row.state, row.outcome_code, row.finished_at, row.lease_until = state, outcome, now(), None
    row.version += 1
    db.commit()


def gather(
    db: Session, organization_id: str, identifier: str, version: int, development: Settings | None
) -> None:
    row = load(db, organization_id, identifier, version)
    if row is None:
        return
    policy = db.get(WatchPolicy, row.policy_id)
    actor = db.get(Membership, policy.actor_id) if policy else None
    if actor is None:
        finish(db, row, "authorization_changed", state="cancelled")
        return
    try:
        service.authorize(db, actor, row.grant_id)
    except HTTPException:
        finish(db, row, "authorization_changed", state="cancelled")
        return
    assert policy is not None
    all_work = service.scope(policy, actor)
    row.coverage_count = db.scalar(select(func.count()).select_from(all_work.subquery())) or 0
    batch = all_work.where(WorkItem.id > policy.scan_after_id) if policy.scan_after_id else all_work
    works = list(db.scalars(batch.order_by(WorkItem.id).limit(100).with_for_update()))
    if not works and policy.scan_after_id:
        works = list(db.scalars(all_work.order_by(WorkItem.id).limit(100).with_for_update()))
    policy.scan_after_id = works[-1].id if works else None
    policy.last_checked_at = now()
    row.considered_count = len(works)
    attention.reconcile(db, actor, row, works)
    if not works:
        finish(db, row, "no_data")
        return
    try:
        cfg = config(db, actor, development)
    except ModelFailure:
        finish(db, row, "model_unavailable")
        return
    candidates = []
    for work in works:
        issue, _ = source_stamp(db, work)
        if issue:
            row.source_warning_count += 1
            continue
        if work.lifecycle_status in {"done", "cancelled"}:
            continue
        digest = context_hash(db, actor, policy, work, cfg)
        previous = db.scalar(
            select(WatchRun.id)
            .where(
                WatchRun.organization_id == organization_id,
                WatchRun.policy_id == row.policy_id,
                WatchRun.work_item_id == work.id,
                WatchRun.context_hash == digest,
                WatchRun.id != row.id,
                (WatchRun.analysis_started_at.is_not(None))
                | (WatchRun.outcome_code == "rules_only"),
            )
            .limit(1)
        )
        if previous:
            continue
        active = categories(work, now())
        priority = (
            0 if "deadline_blocked" in active else 1 if "support" in active else 2 if active else 3
        )
        candidates.append((priority, work.id, digest))
    if not candidates:
        finish(db, row, "source_unavailable" if row.source_warning_count else "no_change")
        return
    _, selected, digest = sorted(candidates)[0]
    row.work_item_id, row.context_hash = selected, digest
    if cfg.ai_provider == "rules":
        finish(db, row, "rules_only")
        return
    reserved = (
        db.scalar(
            select(func.count())
            .select_from(WatchRun)
            .where(
                WatchRun.organization_id == organization_id,
                WatchRun.policy_id == policy.id,
                WatchRun.analysis_started_at >= now() - timedelta(hours=24),
            )
        )
        or 0
    )
    if reserved >= policy.daily_analysis_limit:
        finish(db, row, "analysis_budget_exceeded")
        return
    row.analysis_started_at = now()
    question = (
        "持续关注目标（不是事实）："
        + policy.goal
        + "\n核对指定事项的确认记录及最近决策，提出供老板审阅的下一步。"
        "缺少资源、依赖或结果时保持未知，不代人确认。"
    )
    child = runtime.create(
        db,
        actor,
        RunInput(
            question=question,
            work_item_id=UUID(selected),
            idempotency_key=uuid5(NAMESPACE_URL, "watch:" + row.id),
        ),
        "",
        watch_grant_id=row.grant_id,
        commit=False,
    )
    row.agent_run_id, row.phase, row.state, row.lease_until = child.id, "analyze", "queued", None
    row.version += 1
    scheduler.enqueue(db, row)
    db.commit()


def analyze(
    db: Session, organization_id: str, identifier: str, version: int, development: Settings | None
) -> None:
    row = load(db, organization_id, identifier, version)
    if row is None:
        return
    policy = db.get(WatchPolicy, row.policy_id)
    actor = db.get(Membership, policy.actor_id) if policy else None
    child_id = row.agent_run_id
    if actor is None or child_id is None or row.work_item_id is None:
        finish(db, row, "missing_context", state="failed")
        return
    error = None
    try:
        service.authorize(db, actor, row.grant_id, row.work_item_id)
        work = db.get(WorkItem, row.work_item_id)
        if (
            policy is None
            or work is None
            or context_hash(db, actor, policy, work, config(db, actor, development))
            != row.context_hash
        ):
            raise ValueError("source_or_model_changed")
        child = runtime.read(db, actor, child_id)
        db.commit()  # Release watcher/organization locks before model I/O.
        if child.state == "ready":
            child = runtime.advance(
                db,
                actor,
                child.id,
                AdvanceInput(
                    expected_version=child.version,
                    idempotency_key=uuid5(NAMESPACE_URL, f"watch:{identifier}:{version}"),
                ),
                development_config=development,
            )
    except (HTTPException, ModelFailure, ValueError):
        db.rollback()
        error = "authorization_or_context_changed"
    db.expire_all()
    row = load(db, organization_id, identifier, version)
    if row is None:
        return
    policy = db.get(WatchPolicy, row.policy_id)
    actor = db.get(Membership, policy.actor_id) if policy else None
    try:
        if actor is None or policy is None:
            raise ValueError("missing_policy")
        service.authorize(db, actor, row.grant_id, row.work_item_id)
        work = db.get(WorkItem, row.work_item_id)
        if (
            work is None
            or context_hash(db, actor, policy, work, config(db, actor, development))
            != row.context_hash
        ):
            raise ValueError("source_changed")
    except (HTTPException, ModelFailure, ValueError):
        error = "authorization_or_context_changed"
    if error:
        clear_runs(
            db,
            organization_id,
            select(AgentRun.id).where(
                AgentRun.organization_id == organization_id, AgentRun.id == child_id
            ),
        )
        finish(db, row, error, state="cancelled")
        return
    child_row = db.get(AgentRun, child_id, populate_existing=True)
    assert child_row is not None
    if child_row.state == "ready":
        row.state, row.lease_until = "queued", None
        row.version += 1
        scheduler.enqueue(db, row)
        db.commit()
    elif child_row.state == "completed":
        assert actor is not None
        attention.plan(db, actor, row)
        finish(db, row, "analyzed")
    elif child_row.state in {"running", "interrupted"}:
        finish(db, row, "model_unknown", state="unknown")
    else:
        row.error_code = child_row.error_code
        finish(db, row, "model_failed", state="failed")


def process(
    db: Session,
    organization_id: str,
    identifier: str,
    version: int,
    *,
    development_config: Settings | None = None,
) -> None:
    if development_config is not None and settings().environment != "test":
        fail("scope_forbidden", "验收配置只允许隔离测试", 403)
    row = scheduler.claim(db, organization_id, identifier, version)
    if row is None:
        return
    if row.phase == "gather":
        gather(db, organization_id, identifier, row.version, development_config)
    else:
        analyze(db, organization_id, identifier, row.version, development_config)
