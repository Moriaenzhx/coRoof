import hashlib
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.core.access import audit
from app.core.errors import fail
from app.core.schemas import DTO
from app.infrastructure.models import (
    Membership,
    Organization,
    WorkEvent,
    now,
    utc,
)
from app.modules.knowledge import access
from app.modules.knowledge.index import publish_index
from app.modules.knowledge.models import (
    KnowledgeChunk,
    KnowledgeDocument,
    KnowledgeReader,
    KnowledgeRevision,
    KnowledgeUse,
)
from app.modules.knowledge.schemas import (
    AccessChange,
    DocumentAction,
    DocumentCommand,
    DocumentEdit,
    DocumentInput,
    DocumentOut,
    DocumentPublish,
    RevisionOut,
)


def digest(value: str | bytes) -> str:
    return hashlib.sha256(value.encode() if isinstance(value, str) else value).hexdigest()


def fingerprint(payload: DTO, action: str, identifier: str = "") -> str:
    return digest(action + identifier + payload.model_dump_json(exclude={"idempotency_key"}))


def view(db: Session, actor: Membership, row: KnowledgeDocument) -> DocumentOut:
    can_edit = access.editable(actor, row) and row.state != "deleted"
    draft = db.get(KnowledgeRevision, row.draft_id) if row.draft_id and can_edit else None
    return DocumentOut(
        id=row.id,
        title=row.title,
        author_id=row.author_id,
        visibility=row.visibility,
        department_id=row.department_id,
        member_ids=list(
            db.scalars(
                select(KnowledgeReader.membership_id).where(
                    KnowledgeReader.organization_id == actor.organization_id,
                    KnowledgeReader.document_id == row.id,
                )
            )
        )
        if can_edit
        else [],
        state=row.state,
        version=row.version,
        published_id=row.published_id,
        draft_id=row.draft_id if can_edit else None,
        can_edit=can_edit,
        can_publish=draft is not None and draft.author_id == actor.id,
        updated_at=utc(row.updated_at),
        created_at=utc(row.created_at),
    )


def revision(
    db: Session, actor: Membership, identifier: str, revision_id: str
) -> tuple[KnowledgeDocument, KnowledgeRevision]:
    row = access.get(db, actor, identifier)
    item = db.scalar(
        select(KnowledgeRevision).where(
            KnowledgeRevision.organization_id == actor.organization_id,
            KnowledgeRevision.document_id == row.id,
            KnowledgeRevision.id == revision_id,
        )
    )
    if (
        item is None
        or item.content is None
        or (item.published_at is None and not access.editable(actor, row))
    ):
        fail("not_found", "未找到此版本", 404)
    assert item is not None
    return row, item


def revision_view(row: KnowledgeDocument, item: KnowledgeRevision) -> RevisionOut:
    return RevisionOut(
        id=item.id,
        document_id=row.id,
        author_id=item.author_id,
        number=item.number,
        title=item.title,
        content=item.content or "",
        content_hash=item.content_hash,
        file_name=item.file_name,
        file_hash=item.file_hash,
        edited_extraction=item.edited_extraction,
        published_at=utc(item.published_at) if item.published_at else None,
        created_at=utc(item.created_at),
        current=row.state == "published" and row.published_id == item.id,
    )


def event(
    db: Session,
    actor: Membership,
    row: KnowledgeDocument,
    key: str,
    request_hash: str,
    action: str,
    data: dict[str, Any],
) -> None:
    db.add(
        WorkEvent(
            organization_id=actor.organization_id,
            document_id=row.id,
            actor_id=actor.id,
            event_type="knowledge." + action,
            event_payload=data,
            source_ref="document:" + row.id,
            idempotency_key=key,
            request_hash=request_hash,
        )
    )
    audit(db, actor, "knowledge." + action, row.id)


def readers(db: Session, row: KnowledgeDocument, identifiers: list[str]) -> None:
    db.execute(
        delete(KnowledgeReader).where(
            KnowledgeReader.organization_id == row.organization_id,
            KnowledgeReader.document_id == row.id,
        )
    )
    for identifier in sorted(set(identifiers)):
        db.add(
            KnowledgeReader(
                organization_id=row.organization_id, document_id=row.id, membership_id=identifier
            )
        )


def create(
    db: Session,
    actor: Membership,
    payload: DocumentInput,
    file_name: str | None = None,
    file_bytes: bytes | None = None,
) -> DocumentOut:
    db.scalar(
        select(Organization).where(Organization.id == actor.organization_id).with_for_update()
    )
    access.authorize(db, actor)
    access.validate_access(db, actor, payload)
    request_hash = fingerprint(payload, "create")
    if file_bytes is not None:
        request_hash = digest(request_hash + (file_name or "") + digest(file_bytes))
    old = db.scalar(
        select(WorkEvent).where(
            WorkEvent.organization_id == actor.organization_id,
            WorkEvent.actor_id == actor.id,
            WorkEvent.idempotency_key == str(payload.idempotency_key),
        )
    )
    if old:
        if old.request_hash != request_hash or old.document_id is None:
            fail("idempotency_conflict", "同一请求不能提交不同内容", 409)
        return view(db, actor, access.get(db, actor, old.document_id))
    row = KnowledgeDocument(
        organization_id=actor.organization_id,
        author_id=actor.id,
        title=payload.title,
        visibility=payload.visibility,
        department_id=str(payload.department_id) if payload.department_id else None,
        request_key=str(payload.idempotency_key),
        request_hash=request_hash,
    )
    db.add(row)
    db.flush()
    item = KnowledgeRevision(
        organization_id=actor.organization_id,
        document_id=row.id,
        author_id=actor.id,
        number=1,
        title=payload.title,
        content=payload.content,
        content_hash=digest(payload.content),
        file_name=file_name,
        file_bytes=file_bytes,
        file_hash=digest(file_bytes) if file_bytes else None,
    )
    db.add(item)
    db.flush()
    row.draft_id = item.id
    readers(db, row, [str(i) for i in payload.member_ids])
    event(
        db,
        actor,
        row,
        str(payload.idempotency_key),
        request_hash,
        "created",
        {"revision_id": item.id, "content_hash": item.content_hash},
    )
    db.commit()
    return view(db, actor, row)


def command(
    db: Session, actor: Membership, identifier: str, payload: DocumentCommand, action: str
) -> tuple[KnowledgeDocument, str, bool]:
    # Same ordering as Agent creation: no new run may capture the previous scope
    # while revocation is waiting for an already executing read to finish.
    db.scalar(
        select(Organization)
        .where(Organization.id == actor.organization_id)
        .with_for_update(key_share=True)
    )
    # Lock the document before re-reading authority and the event replay boundary.
    row = db.scalar(
        select(KnowledgeDocument)
        .where(
            KnowledgeDocument.organization_id == actor.organization_id,
            KnowledgeDocument.id == identifier,
        )
        .with_for_update(key_share=True)
        .execution_options(populate_existing=True)
    )
    access.authorize(db, actor)
    if row is None:
        fail("not_found", "未找到此文档", 404)
    assert row is not None
    request_hash = fingerprint(payload, action, identifier)
    old = db.scalar(
        select(WorkEvent).where(
            WorkEvent.organization_id == actor.organization_id,
            WorkEvent.actor_id == actor.id,
            WorkEvent.idempotency_key == str(payload.idempotency_key),
        )
    )
    if row.state != "deleted":
        access.get(db, actor, row.id)
        if not access.editable(actor, row):
            fail("author_required", "仅作者或有访问权限的企业所有者可管理文档", 403)
    elif old is None or old.document_id != row.id or old.event_type != "knowledge.delete":
        fail("not_found", "未找到此文档", 404)
    if old:
        if old.request_hash != request_hash:
            fail("idempotency_conflict", "同一请求不能提交不同内容", 409)
        return row, request_hash, True
    if row.version != payload.expected_version:
        fail("version_conflict", "文档已变化，请刷新后重试", 409)
    return row, request_hash, False


def invalidate(db: Session, row: KnowledgeDocument) -> None:
    from app.modules.agent.invalidation import clear_runs, read_barrier

    read_barrier(db, row.organization_id)
    run_ids = select(KnowledgeUse.run_id).where(
        KnowledgeUse.organization_id == row.organization_id, KnowledgeUse.document_id == row.id
    )
    clear_runs(db, row.organization_id, run_ids)
    row.access_version += 1


def edit(db: Session, actor: Membership, identifier: str, payload: DocumentEdit) -> DocumentOut:
    row, request_hash, replay = command(db, actor, identifier, payload, "edit")
    if replay:
        return view(db, actor, row)
    item = db.get(KnowledgeRevision, row.draft_id) if row.draft_id else None
    if item:
        if item.author_id != actor.id:
            fail("author_required", "待发布草稿仅可由其作者编辑", 403)
        item.title, item.content, item.content_hash = (
            payload.title,
            payload.content,
            digest(payload.content),
        )
        item.edited_extraction = item.file_bytes is not None
    else:
        row.revision_count += 1
        item = KnowledgeRevision(
            organization_id=actor.organization_id,
            document_id=row.id,
            author_id=actor.id,
            number=row.revision_count,
            title=payload.title,
            content=payload.content,
            content_hash=digest(payload.content),
        )
        db.add(item)
        db.flush()
        row.draft_id = item.id
    if row.state != "published":
        row.title = payload.title
    row.updated_at, row.version = now(), row.version + 1
    event(
        db,
        actor,
        row,
        str(payload.idempotency_key),
        request_hash,
        "edit",
        {"revision_id": item.id, "content_hash": item.content_hash},
    )
    db.commit()
    return view(db, actor, row)


def publish(
    db: Session, actor: Membership, identifier: str, payload: DocumentPublish
) -> DocumentOut:
    row, request_hash, replay = command(db, actor, identifier, payload, "publish")
    if replay:
        return view(db, actor, row)
    item = db.get(KnowledgeRevision, row.draft_id) if row.draft_id else None
    if item is None or item.id != str(payload.revision_id):
        fail("draft_changed", "待发布版本已变化", 409)
    if item.author_id != actor.id:
        fail("author_required", "发布须由草稿作者明确确认", 403)
    # Re-check sharing authority after role or department changes.
    from app.modules.knowledge.schemas import DocumentAccess

    access.validate_access(
        db,
        actor,
        DocumentAccess(
            visibility=row.visibility,
            department_id=row.department_id,
            member_ids=list(
                db.scalars(
                    select(KnowledgeReader.membership_id).where(
                        KnowledgeReader.organization_id == row.organization_id,
                        KnowledgeReader.document_id == row.id,
                    )
                )
            ),
        ),
    )
    item.published_at = now()
    publish_index(db, item)
    invalidate(db, row)
    row.title, row.published_id, row.draft_id, row.state = item.title, item.id, None, "published"
    row.updated_at, row.version = now(), row.version + 1
    event(
        db,
        actor,
        row,
        str(payload.idempotency_key),
        request_hash,
        "publish",
        {"revision_id": item.id, "number": item.number, "content_hash": item.content_hash},
    )
    db.commit()
    return view(db, actor, row)


def change_access(
    db: Session, actor: Membership, identifier: str, payload: AccessChange
) -> DocumentOut:
    row, request_hash, replay = command(db, actor, identifier, payload, "access")
    if replay:
        return view(db, actor, row)
    access.validate_access(db, actor, payload)
    invalidate(db, row)
    row.visibility = payload.visibility
    row.department_id = str(payload.department_id) if payload.department_id else None
    readers(db, row, [str(i) for i in payload.member_ids])
    row.updated_at, row.version = now(), row.version + 1
    event(
        db,
        actor,
        row,
        str(payload.idempotency_key),
        request_hash,
        "access",
        {"visibility": row.visibility, "department_id": row.department_id},
    )
    db.commit()
    return view(db, actor, row)


def action(db: Session, actor: Membership, identifier: str, payload: DocumentAction) -> DocumentOut:
    row, request_hash, replay = command(db, actor, identifier, payload, payload.action)
    if replay:
        return view(db, actor, row)
    invalidate(db, row)
    row.state = "withdrawn" if payload.action == "withdraw" else "deleted"
    if payload.action == "delete":
        row.title, row.draft_id, row.published_id = "已删除文档", None, None
        row.visibility, row.department_id = "private", None
        readers(db, row, [])
        db.execute(
            delete(KnowledgeChunk).where(
                KnowledgeChunk.organization_id == row.organization_id,
                KnowledgeChunk.document_id == row.id,
            )
        )
        for item in db.scalars(
            select(KnowledgeRevision).where(
                KnowledgeRevision.organization_id == row.organization_id,
                KnowledgeRevision.document_id == row.id,
            )
        ):
            item.content, item.file_bytes, item.file_name, item.title = (
                None,
                None,
                None,
                "已删除文档",
            )
    row.updated_at, row.version = now(), row.version + 1
    event(
        db,
        actor,
        row,
        str(payload.idempotency_key),
        request_hash,
        payload.action,
        {"state": row.state},
    )
    db.commit()
    return view(db, actor, row)
