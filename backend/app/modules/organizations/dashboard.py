from fastapi import APIRouter

from app.core.access import department_scope, manager, member_scope, owner, work_scope
from app.core.auth import Actor, Db
from app.core.schemas import DashboardOut, DepartmentOut, DepartmentSummary, OrgOut
from app.infrastructure.models import Organization, now

router = APIRouter(tags=["dashboard"])


@router.get("/dashboard", response_model=DashboardOut)
def dashboard(db: Db, actor: Actor) -> DashboardOut:
    departments = db.scalars(department_scope(actor)).all()
    works = db.scalars(work_scope(actor)).all()
    members = db.scalars(member_scope(actor)).all()
    summaries = []
    for department in departments:
        related = [w for w in works if w.department_id == department.id]
        summaries.append(
            DepartmentSummary(
                department=DepartmentOut.model_validate(department),
                member_count=sum(m.department_id == department.id for m in members),
                work_count=len(related),
                active_count=sum(w.lifecycle_status in {"planned", "in_progress"} for w in related),
                support_count=sum(w.needs_support for w in related),
                coverage="recorded" if related else "unknown",
                updated_at=max((w.updated_at for w in related), default=None),
            )
        )
    return DashboardOut(
        organization=OrgOut.model_validate(db.get(Organization, actor.organization_id)),
        departments=summaries,
        source="mixed" if any(w.source_authority == "external" for w in works) else "native",
        external_data="partial"
        if any(w.source_authority == "external" for w in works)
        else "not_connected",
        total_work=len(works),
        active_work=sum(w.lifecycle_status in {"planned", "in_progress"} for w in works),
        completed_work=sum(w.lifecycle_status == "done" for w in works),
        support_work=sum(w.needs_support for w in works),
        member_count=len(members),
        unscoped_members=sum(m.department_id is None for m in members),
        last_updated_at=max((w.updated_at for w in works), default=None),
        generated_at=now(),
        scope="organization" if owner(actor) else "department" if manager(actor) else "assigned",
    )
