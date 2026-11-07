"""Durable, at-least-once delivery of bounded interactive read steps.

The existing AgentRun owns authorization, model admission and its result. This
table is only execution intent and transport fencing, never a new authority.
All mutations lock AgentRun before AgentExecution, including cancellation.
"""

from collections.abc import Callable
from datetime import timedelta
from uuid import NAMESPACE_URL, uuid5

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import fail
from app.infrastructure.models import AgentRun, Membership, now, uid, utc
from app.modules.agent.models import AgentExecution
from app.modules.agent.schemas import AdvanceInput, ExecutionOut, RunInput, RunOut

LEASE_SECONDS = 180
DELIVERY_RETRY_SECONDS = 30


def get(db: Session, run: AgentRun, *, lock: bool = False) -> AgentExecution | None:
    stmt = select(AgentExecution).where(
        AgentExecution.organization_id == run.organization_id,
        AgentExecution.run_id == run.id,
    )
    if lock:
        stmt = stmt.with_for_update().execution_options(populate_existing=True)
    return db.scalar(stmt)


def output(db: Session, run: AgentRun) -> ExecutionOut | None:
    execution = get(db, run)
    if execution is None:
        return None
    return ExecutionOut(
        state=execution.state if run.state in {"ready", "running"} else "stopped",
        updated_at=execution.updated_at,
    )


def stop(execution: AgentExecution) -> None:
    execution.state, execution.lease_token, execution.lease_until = "stopped", None, None
    execution.updated_at = now()


def requeue(db: Session, run: AgentRun) -> None:
    execution = get(db, run, lock=True)
    if execution is not None:
        execution.state, execution.lease_token, execution.lease_until = "queued", None, None
        execution.generation += 1
        execution.available_at = execution.updated_at = now()


def stop_run(db: Session, run: AgentRun) -> None:
    execution = get(db, run, lock=True)
    if execution is not None:
        stop(execution)


def authorize_executor(db: Session, run: AgentRun, token: str | None) -> None:
    execution = get(db, run, lock=True)
    if execution is None and token is None:
        return
    if execution is not None and token is None:
        fail("execution_managed", "此任务由服务器执行，请读取进度或明确取消", 409)
    if (
        execution is None
        or execution.state != "running"
        or execution.lease_token != token
        or execution.lease_until is None
        or utc(execution.lease_until) <= now()
    ):
        fail("execution_stale", "任务执行权已变化", 409)


def submit(db: Session, actor: Membership, payload: RunInput, session_hash: str) -> RunOut:
    from app.modules.agent import runtime

    if payload.task != "read":
        fail("scope_forbidden", "持久任务仅支持本人显式提交的只读查询", 403)
    result = runtime.create(db, actor, payload, session_hash, commit=False)
    row = runtime.load(db, actor, result.id)
    if get(db, row, lock=True) is None and row.state == "ready":
        db.add(AgentExecution(organization_id=row.organization_id, run_id=row.id))
    db.commit()
    return runtime.output(db, row)


def pair(
    db: Session, organization_id: str, run_id: str, *, skip_locked: bool = False
) -> tuple[AgentRun, AgentExecution] | None:
    row = db.scalar(
        select(AgentRun)
        .where(AgentRun.organization_id == organization_id, AgentRun.id == run_id)
        .with_for_update(skip_locked=skip_locked)
        .execution_options(populate_existing=True)
    )
    if row is None:
        db.rollback()
        return None
    execution = get(db, row, lock=True)
    if execution is None:
        db.rollback()
        return None
    return row, execution


def claim(db: Session, organization_id: str, run_id: str, generation: int) -> str | None:
    current = pair(db, organization_id, run_id)
    if current is None:
        return None
    row, execution = current
    if execution.state != "queued" or execution.generation != generation:
        db.rollback()
        return None
    if row.state != "ready" or row.task != "read" or row.watch_grant_id is not None:
        stop(execution)
        db.commit()
        return None
    token = uid()
    execution.state, execution.lease_token = "running", token
    execution.lease_until = now() + timedelta(seconds=LEASE_SECONDS)
    execution.updated_at = now()
    db.commit()
    return token


def process(db: Session, organization_id: str, run_id: str, generation: int) -> None:
    from app.modules.agent import runtime

    token = claim(db, organization_id, run_id, generation)
    if token is None:
        return
    row = db.get(AgentRun, run_id)
    assert row is not None and row.organization_id == organization_id
    actor = db.get(Membership, row.actor_id)
    error = None
    try:
        if actor is None or actor.organization_id != organization_id:
            fail("organization_forbidden", "任务成员已失效", 403)
        runtime.advance(
            db,
            actor,
            run_id,
            AdvanceInput(
                expected_version=row.version,
                idempotency_key=uuid5(
                    NAMESPACE_URL, f"agent-execution:{organization_id}:{run_id}:{generation}"
                ),
            ),
            execution_token=token,
        )
    except HTTPException as exc:
        # Persist a safe code only. A source/session failure never falls back or retries.
        error = (
            str(exc.detail.get("code", "access_revoked"))
            if isinstance(exc.detail, dict)
            else "access_revoked"
        )
        db.rollback()
    # Unexpected crashes leave their lease intact. Recovery distinguishes a known
    # committed result from an unknown in-flight model call; Celery must not replay it.
    current = pair(db, organization_id, run_id)
    if current is None:
        return
    row, execution = current
    if execution.state != "running" or execution.lease_token != token:
        db.rollback()
        return
    if error is not None and row.state in {"ready", "running"}:
        row.state, row.error_code, row.answer = "cancelled", error, None
        row.version += 1
    if row.state == "ready":
        requeue(db, row)
    else:
        stop(execution)
    db.commit()


def recover(db: Session) -> int:
    from app.modules.agent import runtime

    candidates = list(
        db.execute(
            select(AgentExecution.organization_id, AgentExecution.run_id)
            .where(AgentExecution.state == "running", AgentExecution.lease_until <= now())
            .order_by(AgentExecution.lease_until, AgentExecution.id)
            .limit(50)
        )
    )
    db.rollback()
    count = 0
    for organization_id, run_id in candidates:
        current = pair(db, organization_id, run_id, skip_locked=True)
        if current is None:
            continue
        row, execution = current
        if (
            execution.state != "running"
            or execution.lease_until is None
            or utc(execution.lease_until) > now()
        ):
            db.rollback()
            continue
        runtime.recover_expired(db, row, commit=False)
        if row.state == "ready":
            # No step was admitted, or its known result committed before a crash.
            requeue(db, row)
        elif row.state == "running":
            # The model lease still owns this call; never steal its execution.
            execution.lease_until = max(
                utc(row.lease_expires_at or now()), now() + timedelta(seconds=15)
            )
        else:
            stop(execution)
        count += 1
        db.commit()
    return count


def dispatch(db: Session, publish: Callable[[str, str, int], None]) -> int:
    recover(db)
    candidates = list(
        db.execute(
            select(AgentExecution.organization_id, AgentExecution.run_id)
            .where(AgentExecution.state == "queued", AgentExecution.available_at <= now())
            .order_by(AgentExecution.available_at, AgentExecution.id)
            .limit(50)
        )
    )
    db.rollback()
    count = 0
    for organization_id, run_id in candidates:
        current = pair(db, organization_id, run_id, skip_locked=True)
        if current is None:
            continue
        row, execution = current
        if execution.state != "queued" or utc(execution.available_at) > now():
            db.rollback()
            continue
        if row.state != "ready":
            stop(execution)
        elif utc(row.deadline) <= now():
            row.state, row.error_code = "failed", "budget_exceeded"
            row.version += 1
            stop(execution)
        else:
            # The row remains queued until claimed. Ambiguous or lost broker
            # delivery is retried with the same generation, never a new model step.
            try:
                publish(organization_id, run_id, execution.generation)
            except Exception:
                execution.available_at = now() + timedelta(seconds=10)
            else:
                execution.available_at = now() + timedelta(seconds=DELIVERY_RETRY_SECONDS)
                count += 1
        db.commit()
    return count
