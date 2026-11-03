from typing import Annotated

from fastapi import APIRouter, Query

from app.core.access import audit, department_scope, page_rows, require_owner
from app.core.auth import Actor, Db, User
from app.core.schemas import DepartmentInput, DepartmentOut, OrgInput, OrgOut, Page
from app.infrastructure.models import AuditEntry, Department, Membership, Organization

router = APIRouter(tags=["organizations"])
Offset = Annotated[int, Query(ge=0)]
Limit = Annotated[int, Query(ge=1, le=100)]


@router.post("/organizations", response_model=OrgOut, status_code=201)
def create_organization(payload: OrgInput, db: Db, user: User) -> OrgOut:
    org = Organization(**payload.model_dump())
    db.add(org)
    db.flush()
    db.add(Membership(organization_id=org.id, user_id=user.id, roles=["owner", "member"]))
    db.add(
        AuditEntry(
            organization_id=org.id,
            actor_user_id=user.id,
            action="organization.created",
            entity_id=org.id,
        )
    )
    db.commit()
    return OrgOut.model_validate(org)


@router.get("/organizations/current", response_model=OrgOut)
def current_organization(db: Db, actor: Actor) -> OrgOut:
    return OrgOut.model_validate(db.get(Organization, actor.organization_id))


@router.post("/departments", response_model=DepartmentOut, status_code=201)
def create_department(payload: DepartmentInput, db: Db, actor: Actor) -> DepartmentOut:
    require_owner(actor)
    department = Department(organization_id=actor.organization_id, name=payload.name)
    db.add(department)
    db.flush()
    audit(db, actor, "department.created", department.id)
    db.commit()
    return DepartmentOut.model_validate(department)


@router.get("/departments", response_model=Page[DepartmentOut])
def list_departments(
    db: Db, actor: Actor, offset: Offset = 0, limit: Limit = 50
) -> Page[DepartmentOut]:
    rows, total = page_rows(db, department_scope(actor).order_by(Department.id), offset, limit)
    return Page(
        items=[DepartmentOut.model_validate(r) for r in rows],
        total=total,
        offset=offset,
        limit=limit,
    )
