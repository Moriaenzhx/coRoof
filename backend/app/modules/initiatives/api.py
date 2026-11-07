from fastapi import APIRouter

from app.core.access import (
    audit,
    check_assignment,
    initiative_scope,
    page_rows,
    require_manager,
    tenant_get,
)
from app.core.auth import Actor, Db
from app.core.schemas import InitiativeInput, InitiativeOut, Page
from app.infrastructure.models import Department, Initiative
from app.modules.organizations.api import Limit, Offset

router = APIRouter(prefix="/initiatives", tags=["initiatives"])


@router.post("", response_model=InitiativeOut, status_code=201)
def create(payload: InitiativeInput, db: Db, actor: Actor) -> InitiativeOut:
    require_manager(actor, payload.department_id)
    if payload.department_id:
        tenant_get(db, Department, payload.department_id, actor)
    check_assignment(db, actor, payload.owner_id, payload.department_id)
    initiative = Initiative(organization_id=actor.organization_id, **payload.model_dump())
    db.add(initiative)
    db.flush()
    audit(db, actor, "initiative.created", initiative.id)
    db.commit()
    return InitiativeOut.model_validate(initiative)


@router.get("", response_model=Page[InitiativeOut])
def list_initiatives(
    db: Db,
    actor: Actor,
    offset: Offset = 0,
    limit: Limit = 50,
) -> Page[InitiativeOut]:
    rows, total = page_rows(db, initiative_scope(actor).order_by(Initiative.id), offset, limit)
    return Page(
        items=[InitiativeOut.model_validate(r) for r in rows],
        total=total,
        offset=offset,
        limit=limit,
    )
