from uuid import UUID

from fastapi import APIRouter, HTTPException, Request
from sqlalchemy import select

from app.core.auth import Actor, Db, token_hash
from app.infrastructure.models import AgentRun
from app.modules.agent import execution, runtime
from app.modules.agent.models import AgentExecution
from app.modules.agent.schemas import AdvanceInput, RunInput, RunOut, Task, VersionInput

router = APIRouter(prefix="/agent/runs", tags=["agent"])


@router.get("", response_model=list[RunOut])
def recent(
    db: Db,
    actor: Actor,
    work_item_id: UUID | None = None,
    task: Task = "read",
    memory_entry_id: UUID | None = None,
) -> list[RunOut]:
    query = select(AgentRun.id).where(
        AgentRun.organization_id == actor.organization_id,
        AgentRun.actor_id == actor.id,
        AgentRun.task == task,
        AgentRun.watch_grant_id.is_(None),
    )
    if work_item_id:
        query = query.where(AgentRun.work_item_id == str(work_item_id))
    if memory_entry_id:
        query = query.where(AgentRun.memory_entry_id == str(memory_entry_id))
    result = []
    for run_id in db.scalars(query.order_by(AgentRun.created_at.desc(), AgentRun.id).limit(5)):
        try:
            result.append(runtime.read(db, actor, run_id))
        except HTTPException:
            # Changed scope or expired originating sessions must not leak old context.
            continue
    return result


@router.post("", response_model=RunOut, status_code=201)
def create(payload: RunInput, db: Db, actor: Actor, request: Request) -> RunOut:
    return runtime.create(db, actor, payload, token_hash(request.cookies.get("coroof_session", "")))


@router.post("/submit", response_model=RunOut, status_code=202)
def submit(payload: RunInput, db: Db, actor: Actor, request: Request) -> RunOut:
    return execution.submit(
        db, actor, payload, token_hash(request.cookies.get("coroof_session", ""))
    )


@router.get("/active", response_model=list[RunOut])
def active(db: Db, actor: Actor) -> list[RunOut]:
    identifiers = list(
        db.scalars(
            select(AgentRun.id)
            .join(
                AgentExecution,
                (AgentExecution.organization_id == AgentRun.organization_id)
                & (AgentExecution.run_id == AgentRun.id),
            )
            .where(
                AgentRun.organization_id == actor.organization_id,
                AgentRun.actor_id == actor.id,
                AgentRun.task == "read",
                AgentRun.watch_grant_id.is_(None),
                AgentRun.state.in_(["ready", "running", "interrupted"]),
            )
            .order_by(AgentRun.created_at.desc(), AgentRun.id)
            .limit(5)
        )
    )
    result = []
    for identifier in identifiers:
        try:
            result.append(runtime.read(db, actor, identifier))
        except HTTPException:
            # Do not expose even the question when its source/session is invalid.
            db.rollback()
    return result


@router.get("/{run_id}", response_model=RunOut)
def read(run_id: str, db: Db, actor: Actor) -> RunOut:
    return runtime.read(db, actor, run_id)


@router.post("/{run_id}/advance", response_model=RunOut)
def advance(run_id: str, payload: AdvanceInput, db: Db, actor: Actor) -> RunOut:
    return runtime.advance(db, actor, run_id, payload)


@router.post("/{run_id}/cancel", response_model=RunOut)
def cancel(run_id: str, payload: VersionInput, db: Db, actor: Actor) -> RunOut:
    return runtime.cancel(db, actor, run_id, payload.expected_version)


@router.post("/{run_id}/resume", response_model=RunOut)
def resume(run_id: str, payload: VersionInput, db: Db, actor: Actor) -> RunOut:
    return runtime.resume(db, actor, run_id, payload.expected_version)
