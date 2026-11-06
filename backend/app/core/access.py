from typing import Any

from sqlalchemy import ColumnElement, Select, or_, select
from sqlalchemy.orm import Session

from app.core.errors import fail
from app.infrastructure.models import (
    AuditEntry,
    Department,
    Initiative,
    Membership,
    TenantEntity,
    WorkItem,
)
from app.modules.connectors.models import Connector, SourceLink


def owner(actor: Membership) -> bool:
    return "owner" in actor.roles


def manager(actor: Membership) -> bool:
    return "manager" in actor.roles and actor.department_id is not None


def require_owner(actor: Membership) -> None:
    if not owner(actor):
        fail("owner_required", "仅企业所有者可执行此操作", 403)


def require_manager(actor: Membership, department_id: str | None) -> None:
    if not owner(actor) and not (manager(actor) and actor.department_id == department_id):
        fail("scope_forbidden", "无权管理此部门", 403)


def tenant_get[T: TenantEntity](
    db: Session,
    model: type[T],
    entity_id: str,
    actor: Membership,
    lock: bool = False,
) -> T:
    stmt = select(model).where(
        model.id == entity_id,
        model.organization_id == actor.organization_id,
    )
    row = db.scalar(
        stmt.with_for_update().execution_options(populate_existing=True) if lock else stmt
    )
    if row is None:
        fail("not_found", "未找到此记录", 404)
    assert row is not None
    return row


def work_scope(actor: Membership) -> Select[tuple[WorkItem]]:
    published = (
        select(SourceLink.work_item_id)
        .join(
            Connector,
            (Connector.organization_id == SourceLink.organization_id)
            & (Connector.id == SourceLink.connector_id),
        )
        .where(
            SourceLink.organization_id == actor.organization_id,
            SourceLink.state == "linked",
            Connector.state == "active",
        )
    )
    stmt = select(WorkItem).where(
        WorkItem.organization_id == actor.organization_id,
        or_(WorkItem.source_authority == "native", WorkItem.id.in_(published)),
    )
    if owner(actor):
        return stmt
    if manager(actor):
        return stmt.where(
            or_(
                WorkItem.department_id == actor.department_id,
                WorkItem.owner_id == actor.id,
            )
        )
    return stmt.where(WorkItem.owner_id == actor.id)


def get_work(db: Session, actor: Membership, work_id: str, lock: bool = False) -> WorkItem:
    stmt = work_scope(actor).where(WorkItem.id == work_id)
    if lock:
        stmt = stmt.with_for_update()
    row = db.scalar(stmt)
    if row is None:
        fail("not_found", "未找到此事项", 404)
    assert row is not None
    return row


def department_scope(actor: Membership) -> Select[tuple[Department]]:
    stmt = select(Department).where(Department.organization_id == actor.organization_id)
    if not owner(actor):
        stmt = stmt.where(Department.id == actor.department_id)
    return stmt


def member_scope(actor: Membership) -> Select[tuple[Membership]]:
    stmt = select(Membership).where(
        Membership.organization_id == actor.organization_id,
        Membership.status == "active",
    )
    if not owner(actor):
        stmt = stmt.where(
            or_(Membership.department_id == actor.department_id, Membership.id == actor.id)
            if manager(actor)
            else Membership.id == actor.id
        )
    return stmt


def initiative_scope(actor: Membership) -> Select[tuple[Initiative]]:
    stmt = select(Initiative).where(Initiative.organization_id == actor.organization_id)
    if owner(actor):
        return stmt
    related = work_scope(actor).with_only_columns(WorkItem.initiative_id)
    condition: ColumnElement[bool] = Initiative.id.in_(related)
    if manager(actor):
        condition = or_(condition, Initiative.department_id == actor.department_id)
    return stmt.where(condition)


def check_assignment(
    db: Session,
    actor: Membership,
    owner_id: str | None,
    department_id: str | None,
) -> None:
    if owner_id:
        member = tenant_get(db, Membership, owner_id, actor)
        if member.status != "active" or member.department_id != department_id:
            fail("invalid_assignee", "负责人须为该部门的有效成员")


def audit(db: Session, actor: Membership, action: str, entity_id: str) -> None:
    db.add(
        AuditEntry(
            organization_id=actor.organization_id,
            actor_user_id=actor.user_id,
            action=action,
            entity_id=entity_id,
        )
    )


def page_rows(
    db: Session,
    stmt: Select[Any],
    offset: int,
    limit: int,
) -> tuple[list[Any], int]:
    from sqlalchemy import func

    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    return list(db.scalars(stmt.offset(offset).limit(limit)).all()), total
