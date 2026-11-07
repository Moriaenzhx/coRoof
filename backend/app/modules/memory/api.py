from typing import Annotated

from fastapi import APIRouter, Query, Request
from sqlalchemy import select

from app.core.access import page_rows, require_owner
from app.core.auth import Actor, Db, token_hash
from app.core.schemas import Page
from app.infrastructure.models import AgentRun
from app.modules.memory import retrieval, service
from app.modules.memory.models import MemoryEntry
from app.modules.memory.schemas import (
    MemoryAction,
    MemoryEdit,
    MemoryInput,
    MemoryKind,
    MemoryOut,
    MemorySearchOut,
)
from app.modules.organizations.api import Limit, Offset

router = APIRouter(prefix="/memory", tags=["decision-memory"])


@router.get("/entries", response_model=Page[MemoryOut])
def entries(
    db: Db, actor: Actor, kind: MemoryKind = "experience", offset: Offset = 0, limit: Limit = 30
) -> Page[MemoryOut]:
    require_owner(actor)
    rows, total = page_rows(
        db,
        service.scope(actor)
        .where(MemoryEntry.kind == kind)
        .order_by(MemoryEntry.updated_at.desc(), MemoryEntry.id),
        offset,
        limit,
    )
    return Page(
        items=[service.view(db, actor, row) for row in rows],
        total=total,
        offset=offset,
        limit=limit,
    )


@router.post("/entries", response_model=MemoryOut, status_code=201)
def create(payload: MemoryInput, db: Db, actor: Actor) -> MemoryOut:
    return service.create(db, actor, payload)


@router.get("/search", response_model=MemorySearchOut)
def search(
    db: Db,
    actor: Actor,
    q: Annotated[str, Query(min_length=1, max_length=2000)],
    kind: MemoryKind = "experience",
    offset: Offset = 0,
    limit: Annotated[int, Query(ge=1, le=20)] = 10,
) -> MemorySearchOut:
    return retrieval.search(db, actor, q, kind=kind, offset=offset, limit=limit)


@router.get("/entries/{identifier}", response_model=MemoryOut)
def entry(identifier: str, db: Db, actor: Actor) -> MemoryOut:
    return service.view(db, actor, service.get(db, actor, identifier))


@router.post("/entries/{identifier}/edit", response_model=MemoryOut)
def edit(identifier: str, payload: MemoryEdit, db: Db, actor: Actor) -> MemoryOut:
    return service.edit(db, actor, identifier, payload)


@router.post("/entries/{identifier}/action", response_model=MemoryOut)
def action(
    identifier: str, payload: MemoryAction, db: Db, actor: Actor, request: Request
) -> MemoryOut:
    require_owner(actor)
    if payload.action != "confirm":
        return service.action(db, actor, identifier, payload)
    # Human-entered candidates use the same domain command. Model candidates
    # additionally resume the official LangGraph waiting/confirmation graph.
    row = service.get(db, actor, identifier)
    run = db.scalar(
        select(AgentRun)
        .where(
            AgentRun.organization_id == actor.organization_id,
            AgentRun.actor_id == actor.id,
            AgentRun.memory_entry_id == row.id,
            AgentRun.memory_base_version == payload.expected_version,
            AgentRun.state.in_(["completed", "cancelled"]),
        )
        .order_by(AgentRun.created_at.desc())
        .limit(1)
    )
    if run is None:
        return service.action(db, actor, identifier, payload)
    from app.modules.agent.approvals import review
    from app.modules.agent.runtime import authorize
    from app.modules.knowledge.service import fingerprint

    current_session = token_hash(request.cookies.get("coroof_session", ""))
    authorize(db, actor, current_session)
    db.commit()

    def apply() -> MemoryOut:
        authorize(db, actor, current_session)
        return service.action(db, actor, identifier, payload)

    result = review(
        run,
        "memory",
        identifier,
        payload.expected_version,
        fingerprint=fingerprint(payload, "memory.confirm", identifier),
        apply=apply,
    )
    assert result is not None
    return result
