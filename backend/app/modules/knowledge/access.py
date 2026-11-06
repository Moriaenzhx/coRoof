from sqlalchemy import Select, and_, or_, select
from sqlalchemy.orm import Session

from app.core.access import member_scope, owner, tenant_get
from app.core.errors import fail
from app.infrastructure.models import Department, Membership
from app.modules.knowledge.models import KnowledgeDocument as Document
from app.modules.knowledge.models import KnowledgeReader
from app.modules.knowledge.schemas import DocumentAccess


def authorize(db: Session, actor: Membership) -> None:
    db.refresh(actor)
    if actor.status != "active":
        fail("access_revoked", "企业权限已失效", 403)


def scope(actor: Membership, *, published: bool = False) -> Select[tuple[Document]]:
    readers = select(KnowledgeReader.document_id).where(
        KnowledgeReader.organization_id == actor.organization_id,
        KnowledgeReader.membership_id == actor.id,
    )
    shared = and_(
        Document.state == "published",
        or_(
            Document.visibility == "organization",
            and_(
                Document.visibility == "department",
                Document.department_id == actor.department_id,
                Document.department_id.is_not(None),
            ),
            and_(Document.visibility == "members", Document.id.in_(readers)),
        ),
    )
    stmt = select(Document).where(
        Document.organization_id == actor.organization_id,
        Document.state != "deleted",
        or_(Document.author_id == actor.id, shared),
    )
    return stmt.where(Document.state == "published") if published else stmt


def get(db: Session, actor: Membership, identifier: str, *, lock: bool = False) -> Document:
    stmt = scope(actor).where(Document.id == identifier)
    if lock:
        stmt = stmt.with_for_update().execution_options(populate_existing=True)
    row = db.scalar(stmt)
    if row is None:
        fail("not_found", "未找到此文档", 404)
    assert row is not None
    return row


def editable(actor: Membership, row: Document) -> bool:
    return row.author_id == actor.id or owner(actor)


def validate_access(db: Session, actor: Membership, payload: DocumentAccess) -> None:
    if payload.visibility == "organization" and not owner(actor):
        fail("owner_required", "企业共享需要企业所有者确认", 403)
    if payload.visibility == "department":
        if not payload.department_id:
            fail("department_required", "请选择部门")
        department = tenant_get(db, Department, str(payload.department_id), actor)
        if not owner(actor) and department.id != actor.department_id:
            fail("scope_forbidden", "只能分享给当前所属部门", 403)
    elif payload.department_id:
        fail("invalid_visibility", "此可见范围不使用部门")
    if payload.visibility == "members":
        if not payload.member_ids:
            fail("readers_required", "请选择可见成员")
        allowed = set(db.scalars(member_scope(actor).with_only_columns(Membership.id)))
        if any(str(identifier) not in allowed for identifier in payload.member_ids):
            fail("scope_forbidden", "所选成员不在当前可管理范围", 403)
    elif payload.member_ids:
        fail("invalid_visibility", "此可见范围不使用指定成员")
