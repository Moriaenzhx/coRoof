"""Tenant-scoped documents, published revisions, ACLs and retrieval dependencies."""

from datetime import datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKeyConstraint,
    Integer,
    LargeBinary,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.infrastructure.models import Base, TenantEntity, now


class KnowledgeDocument(TenantEntity, Base):
    __tablename__ = "knowledge_documents"
    __table_args__ = (
        UniqueConstraint("organization_id", "id"),
        UniqueConstraint("organization_id", "author_id", "request_key"),
        ForeignKeyConstraint(
            ["organization_id", "author_id"], ["memberships.organization_id", "memberships.id"]
        ),
        ForeignKeyConstraint(
            ["organization_id", "department_id"], ["departments.organization_id", "departments.id"]
        ),
        ForeignKeyConstraint(
            ["organization_id", "id", "published_id"],
            [
                "knowledge_revisions.organization_id",
                "knowledge_revisions.document_id",
                "knowledge_revisions.id",
            ],
            name="fk_knowledge_published",
            use_alter=True,
        ),
        ForeignKeyConstraint(
            ["organization_id", "id", "draft_id"],
            [
                "knowledge_revisions.organization_id",
                "knowledge_revisions.document_id",
                "knowledge_revisions.id",
            ],
            name="fk_knowledge_draft",
            use_alter=True,
        ),
        CheckConstraint("state IN ('draft', 'published', 'withdrawn', 'deleted')"),
        CheckConstraint("visibility IN ('private', 'department', 'organization', 'members')"),
        CheckConstraint("visibility != 'department' OR department_id IS NOT NULL"),
    )
    title: Mapped[str] = mapped_column(String(200))
    author_id: Mapped[str] = mapped_column(String(36))
    visibility: Mapped[str] = mapped_column(String(20), default="private")
    department_id: Mapped[str | None] = mapped_column(String(36))
    state: Mapped[str] = mapped_column(String(20), default="draft")
    published_id: Mapped[str | None] = mapped_column(String(36))
    draft_id: Mapped[str | None] = mapped_column(String(36))
    revision_count: Mapped[int] = mapped_column(Integer, default=1)
    access_version: Mapped[int] = mapped_column(Integer, default=1)
    version: Mapped[int] = mapped_column(Integer, default=1)
    request_key: Mapped[str] = mapped_column(String(36))
    request_hash: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    __mapper_args__ = {"version_id_col": version}


class KnowledgeRevision(TenantEntity, Base):
    __tablename__ = "knowledge_revisions"
    __table_args__ = (
        UniqueConstraint("organization_id", "id"),
        UniqueConstraint("organization_id", "document_id", "id"),
        UniqueConstraint("organization_id", "document_id", "number"),
        ForeignKeyConstraint(
            ["organization_id", "document_id"],
            ["knowledge_documents.organization_id", "knowledge_documents.id"],
        ),
        ForeignKeyConstraint(
            ["organization_id", "author_id"], ["memberships.organization_id", "memberships.id"]
        ),
    )
    document_id: Mapped[str] = mapped_column(String(36))
    author_id: Mapped[str] = mapped_column(String(36))
    number: Mapped[int] = mapped_column(Integer)
    title: Mapped[str] = mapped_column(String(200))
    content: Mapped[str | None] = mapped_column(Text)
    content_hash: Mapped[str] = mapped_column(String(64))
    file_name: Mapped[str | None] = mapped_column(String(180))
    file_bytes: Mapped[bytes | None] = mapped_column(LargeBinary)
    file_hash: Mapped[str | None] = mapped_column(String(64))
    edited_extraction: Mapped[bool] = mapped_column(Boolean, default=False)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class KnowledgeReader(TenantEntity, Base):
    __tablename__ = "knowledge_readers"
    __table_args__ = (
        UniqueConstraint("organization_id", "id"),
        UniqueConstraint("organization_id", "document_id", "membership_id"),
        ForeignKeyConstraint(
            ["organization_id", "document_id"],
            ["knowledge_documents.organization_id", "knowledge_documents.id"],
        ),
        ForeignKeyConstraint(
            ["organization_id", "membership_id"], ["memberships.organization_id", "memberships.id"]
        ),
    )
    document_id: Mapped[str] = mapped_column(String(36))
    membership_id: Mapped[str] = mapped_column(String(36))


class KnowledgeChunk(TenantEntity, Base):
    __tablename__ = "knowledge_chunks"
    __table_args__ = (
        UniqueConstraint("organization_id", "id"),
        UniqueConstraint("organization_id", "revision_id", "ordinal"),
        ForeignKeyConstraint(
            ["organization_id", "document_id", "revision_id"],
            [
                "knowledge_revisions.organization_id",
                "knowledge_revisions.document_id",
                "knowledge_revisions.id",
            ],
        ),
    )
    document_id: Mapped[str] = mapped_column(String(36))
    revision_id: Mapped[str] = mapped_column(String(36))
    ordinal: Mapped[int] = mapped_column(Integer)
    content: Mapped[str] = mapped_column(Text)
    start_offset: Mapped[int] = mapped_column(Integer)
    end_offset: Mapped[int] = mapped_column(Integer)
    search_text: Mapped[str] = mapped_column(Text)


class KnowledgeUse(TenantEntity, Base):
    __tablename__ = "knowledge_uses"
    __table_args__ = (
        UniqueConstraint("organization_id", "id"),
        UniqueConstraint("organization_id", "document_id", "run_id"),
        ForeignKeyConstraint(
            ["organization_id", "document_id"],
            ["knowledge_documents.organization_id", "knowledge_documents.id"],
        ),
        ForeignKeyConstraint(
            ["organization_id", "run_id"], ["agent_runs.organization_id", "agent_runs.id"]
        ),
    )
    document_id: Mapped[str] = mapped_column(String(36))
    run_id: Mapped[str] = mapped_column(String(36))
