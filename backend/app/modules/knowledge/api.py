from typing import Annotated
from urllib.parse import quote

from fastapi import APIRouter, Query
from fastapi.responses import Response
from sqlalchemy import select

from app.core.access import page_rows
from app.core.auth import Actor, Db
from app.core.errors import fail
from app.core.schemas import Page
from app.modules.knowledge import access, importer, service
from app.modules.knowledge.index import search
from app.modules.knowledge.models import KnowledgeDocument, KnowledgeRevision
from app.modules.knowledge.schemas import (
    AccessChange,
    DocumentAction,
    DocumentEdit,
    DocumentInput,
    DocumentOut,
    DocumentPublish,
    DocumentView,
    ImportInput,
    ImportPreviewOut,
    RevisionOut,
    SearchOut,
    Visibility,
)
from app.modules.organizations.api import Limit, Offset

router = APIRouter(prefix="/knowledge", tags=["knowledge"])


@router.get("/documents", response_model=Page[DocumentOut])
def documents(
    db: Db,
    actor: Actor,
    offset: Offset = 0,
    limit: Limit = 50,
    view: DocumentView = "all",
    visibility: Visibility | None = None,
    q: Annotated[str | None, Query(max_length=200)] = None,
) -> Page[DocumentOut]:
    stmt = access.scope(actor, published=view == "published")
    if view in ("mine", "my_withdrawn"):
        stmt = stmt.where(KnowledgeDocument.author_id == actor.id)
    if view == "my_withdrawn":
        stmt = stmt.where(KnowledgeDocument.state == "withdrawn")
    if view == "my_drafts":
        drafts = select(KnowledgeRevision.id).where(
            KnowledgeRevision.organization_id == actor.organization_id,
            KnowledgeRevision.author_id == actor.id,
            KnowledgeRevision.published_at.is_(None),
        )
        if q and q.strip():
            drafts = drafts.where(KnowledgeRevision.title.icontains(q.strip(), autoescape=True))
        stmt = stmt.where(KnowledgeDocument.draft_id.in_(drafts))
    if visibility is not None:
        stmt = stmt.where(KnowledgeDocument.visibility == visibility)
    if view != "my_drafts" and q and q.strip():
        stmt = stmt.where(KnowledgeDocument.title.icontains(q.strip(), autoescape=True))
    rows, total = page_rows(
        db,
        stmt.order_by(KnowledgeDocument.updated_at.desc(), KnowledgeDocument.id),
        offset,
        limit,
    )
    items = [service.view(db, actor, row) for row in rows]
    if view == "my_drafts":
        draft_titles = {
            identifier: title
            for identifier, title in db.execute(
                select(KnowledgeRevision.id, KnowledgeRevision.title).where(
                    KnowledgeRevision.organization_id == actor.organization_id,
                    KnowledgeRevision.author_id == actor.id,
                    KnowledgeRevision.id.in_([row.draft_id for row in rows if row.draft_id]),
                )
            )
        }
        items = [
            item.model_copy(update={"title": draft_titles.get(item.draft_id or "", item.title)})
            for item in items
        ]
    return Page(
        items=items,
        total=total,
        offset=offset,
        limit=limit,
    )


@router.post("/documents", response_model=DocumentOut, status_code=201)
def create(payload: DocumentInput, db: Db, actor: Actor) -> DocumentOut:
    return service.create(db, actor, payload)


@router.post("/import/preview", response_model=ImportPreviewOut)
def preview_import(payload: ImportInput, db: Db, actor: Actor) -> ImportPreviewOut:
    access.validate_access(db, actor, payload)
    db.commit()
    data, content = importer.parse(payload)
    # Reauthorize after the isolated parser; preview never creates a draft or event.
    access.authorize(db, actor)
    access.validate_access(db, actor, payload)
    file_hash = service.digest(data)
    # Only the author's current source is eligible. Hidden or superseded revisions
    # must not disclose another person's files through a duplicate-file oracle.
    duplicate = db.execute(
        access.scope(actor)
        .join(
            KnowledgeRevision,
            (KnowledgeRevision.organization_id == KnowledgeDocument.organization_id)
            & (KnowledgeRevision.document_id == KnowledgeDocument.id)
            & (KnowledgeRevision.id == KnowledgeDocument.published_id),
        )
        .where(
            KnowledgeDocument.author_id == actor.id,
            KnowledgeRevision.file_hash == file_hash,
            KnowledgeRevision.edited_extraction.is_(False),
        )
        .order_by(KnowledgeDocument.updated_at.desc(), KnowledgeDocument.id)
        .limit(1)
    ).scalar_one_or_none()
    if duplicate is None:
        duplicate = db.execute(
            access.scope(actor)
            .join(
                KnowledgeRevision,
                (KnowledgeRevision.organization_id == KnowledgeDocument.organization_id)
                & (KnowledgeRevision.document_id == KnowledgeDocument.id)
                & (KnowledgeRevision.id == KnowledgeDocument.draft_id),
            )
            .where(
                KnowledgeDocument.author_id == actor.id,
                KnowledgeRevision.author_id == actor.id,
                KnowledgeRevision.file_hash == file_hash,
                KnowledgeRevision.edited_extraction.is_(False),
            )
            .order_by(KnowledgeDocument.updated_at.desc(), KnowledgeDocument.id)
            .limit(1)
        ).scalar_one_or_none()
    return ImportPreviewOut(
        file_name=payload.file_name,
        file_hash=file_hash,
        content=content,
        duplicate_document_id=duplicate.id if duplicate else None,
        duplicate_title=duplicate.title if duplicate else None,
    )


@router.post("/import", response_model=DocumentOut, status_code=201)
def import_file(payload: ImportInput, db: Db, actor: Actor) -> DocumentOut:
    access.validate_access(db, actor, payload)
    db.commit()  # No transaction/connection held while the isolated parser works.
    data, content = importer.parse(payload)
    return service.create(
        db,
        actor,
        DocumentInput(
            title=payload.title,
            content=content,
            visibility=payload.visibility,
            department_id=payload.department_id,
            member_ids=payload.member_ids,
            idempotency_key=payload.idempotency_key,
        ),
        payload.file_name,
        data,
    )


@router.get("/search", response_model=SearchOut)
def search_documents(
    db: Db,
    actor: Actor,
    q: Annotated[str, Query(min_length=1, max_length=2000)],
    offset: Offset = 0,
    limit: Annotated[int, Query(ge=1, le=20)] = 10,
    visibility: Visibility | None = None,
) -> SearchOut:
    return search(db, actor, q, offset, limit, visibility=visibility)


@router.get("/documents/{identifier}", response_model=DocumentOut)
def document(identifier: str, db: Db, actor: Actor) -> DocumentOut:
    return service.view(db, actor, access.get(db, actor, identifier))


@router.get("/documents/{identifier}/revisions/{revision_id}", response_model=RevisionOut)
def get_revision(identifier: str, revision_id: str, db: Db, actor: Actor) -> RevisionOut:
    row, item = service.revision(db, actor, identifier, revision_id)
    return service.revision_view(row, item)


@router.get("/documents/{identifier}/revisions/{revision_id}/file")
def original_file(identifier: str, revision_id: str, db: Db, actor: Actor) -> Response:
    _, item = service.revision(db, actor, identifier, revision_id)
    if item.file_bytes is None:
        fail("not_found", "此版本没有原始文件", 404)
    return Response(
        content=item.file_bytes,
        media_type="application/octet-stream",
        headers={
            "Content-Disposition": "attachment; filename*=UTF-8''"
            + quote(item.file_name or "document", safe=""),
            "Content-Security-Policy": "sandbox",
        },
    )


@router.post("/documents/{identifier}/edit", response_model=DocumentOut)
def edit(identifier: str, payload: DocumentEdit, db: Db, actor: Actor) -> DocumentOut:
    return service.edit(db, actor, identifier, payload)


@router.post("/documents/{identifier}/publish", response_model=DocumentOut)
def publish(identifier: str, payload: DocumentPublish, db: Db, actor: Actor) -> DocumentOut:
    return service.publish(db, actor, identifier, payload)


@router.post("/documents/{identifier}/access", response_model=DocumentOut)
def change_access(identifier: str, payload: AccessChange, db: Db, actor: Actor) -> DocumentOut:
    return service.change_access(db, actor, identifier, payload)


@router.post("/documents/{identifier}/action", response_model=DocumentOut)
def action(identifier: str, payload: DocumentAction, db: Db, actor: Actor) -> DocumentOut:
    return service.action(db, actor, identifier, payload)
