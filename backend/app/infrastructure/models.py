"""Persistent facts. All organization-owned references use composite tenant foreign keys."""

from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def now() -> datetime:
    return datetime.now(UTC)


def uid() -> str:
    return str(uuid4())


def utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


json_type = JSON().with_variant(JSONB(), "postgresql")


class Base(DeclarativeBase):
    pass


class Identity(Base):
    __tablename__ = "users"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    verified_identity: Mapped[str] = mapped_column(String(320), unique=True)
    name: Mapped[str] = mapped_column(String(100))
    identity_provider: Mapped[str] = mapped_column(String(30), default="mock")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class LoginChallenge(Base):
    __tablename__ = "login_challenges"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    email: Mapped[str] = mapped_column(String(320))
    name: Mapped[str] = mapped_column(String(100))
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    used: Mapped[bool] = mapped_column(Boolean, default=False)


class AuthSession(Base):
    __tablename__ = "auth_sessions"
    token_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class Organization(Base):
    __tablename__ = "organizations"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    name: Mapped[str] = mapped_column(String(100))
    timezone: Mapped[str] = mapped_column(String(80), default="Asia/Shanghai")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class TenantEntity:
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    organization_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"), index=True)


class Department(TenantEntity, Base):
    __tablename__ = "departments"
    __table_args__ = (
        UniqueConstraint("organization_id", "id"),
        UniqueConstraint("organization_id", "name"),
    )
    name: Mapped[str] = mapped_column(String(100))


class Membership(TenantEntity, Base):
    __tablename__ = "memberships"
    __table_args__ = (
        UniqueConstraint("organization_id", "id"),
        UniqueConstraint("organization_id", "user_id"),
        ForeignKeyConstraint(
            ["organization_id", "department_id"], ["departments.organization_id", "departments.id"]
        ),
        CheckConstraint("status IN ('active', 'inactive')"),
    )
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    department_id: Mapped[str | None] = mapped_column(String(36))
    roles: Mapped[list[str]] = mapped_column(json_type)
    status: Mapped[str] = mapped_column(String(20), default="active")


class Invitation(TenantEntity, Base):
    __tablename__ = "invitations"
    __table_args__ = (
        ForeignKeyConstraint(
            ["organization_id", "department_id"], ["departments.organization_id", "departments.id"]
        ),
        ForeignKeyConstraint(
            ["organization_id", "invited_by"], ["memberships.organization_id", "memberships.id"]
        ),
    )
    email: Mapped[str] = mapped_column(String(320))
    roles: Mapped[list[str]] = mapped_column(json_type)
    department_id: Mapped[str] = mapped_column(String(36))
    invited_by: Mapped[str] = mapped_column(String(36))
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    revoked: Mapped[bool] = mapped_column(Boolean, default=False)
    accepted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Initiative(TenantEntity, Base):
    __tablename__ = "initiatives"
    __table_args__ = (
        UniqueConstraint("organization_id", "id"),
        ForeignKeyConstraint(
            ["organization_id", "department_id"], ["departments.organization_id", "departments.id"]
        ),
        ForeignKeyConstraint(
            ["organization_id", "owner_id"], ["memberships.organization_id", "memberships.id"]
        ),
        CheckConstraint("status IN ('planned', 'in_progress', 'done', 'cancelled')"),
    )
    title: Mapped[str] = mapped_column(String(200))
    goal: Mapped[str | None] = mapped_column(Text)
    owner_id: Mapped[str | None] = mapped_column(String(36))
    department_id: Mapped[str | None] = mapped_column(String(36))
    due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(20), default="planned")


class WorkItem(TenantEntity, Base):
    __tablename__ = "work_items"
    __table_args__ = (
        UniqueConstraint("organization_id", "id"),
        ForeignKeyConstraint(
            ["organization_id", "department_id"], ["departments.organization_id", "departments.id"]
        ),
        ForeignKeyConstraint(
            ["organization_id", "initiative_id"], ["initiatives.organization_id", "initiatives.id"]
        ),
        ForeignKeyConstraint(
            ["organization_id", "owner_id"], ["memberships.organization_id", "memberships.id"]
        ),
        CheckConstraint("lifecycle_status IN ('planned', 'in_progress', 'done', 'cancelled')"),
        CheckConstraint("source_authority IN ('native', 'external')"),
        Index("ix_work_scope", "organization_id", "department_id", "owner_id"),
    )
    title: Mapped[str] = mapped_column(String(200))
    description: Mapped[str | None] = mapped_column(Text)
    department_id: Mapped[str] = mapped_column(String(36))
    initiative_id: Mapped[str | None] = mapped_column(String(36))
    owner_id: Mapped[str | None] = mapped_column(String(36))
    due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    lifecycle_status: Mapped[str] = mapped_column(String(20), default="planned")
    needs_support: Mapped[bool] = mapped_column(Boolean, default=False)
    source_authority: Mapped[str] = mapped_column(String(20), default="native")
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    version: Mapped[int] = mapped_column(Integer, default=1)
    __mapper_args__ = {"version_id_col": version}


class UpdateDraft(TenantEntity, Base):
    __tablename__ = "update_drafts"
    __table_args__ = (
        UniqueConstraint("organization_id", "id"),
        ForeignKeyConstraint(
            ["organization_id", "work_item_id"], ["work_items.organization_id", "work_items.id"]
        ),
        ForeignKeyConstraint(
            ["organization_id", "actor_id"], ["memberships.organization_id", "memberships.id"]
        ),
        CheckConstraint("state IN ('pending', 'confirmed')"),
    )
    work_item_id: Mapped[str] = mapped_column(String(36))
    actor_id: Mapped[str] = mapped_column(String(36))
    raw_text: Mapped[str] = mapped_column(Text)
    proposed_fields: Mapped[dict[str, Any]] = mapped_column(json_type)
    state: Mapped[str] = mapped_column(String(20), default="pending")
    base_version: Mapped[int] = mapped_column(Integer)
    revision: Mapped[int] = mapped_column(Integer, default=1)
    provider: Mapped[str] = mapped_column(String(40), default="rules")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    __mapper_args__ = {"version_id_col": revision}


class WorkEvent(TenantEntity, Base):
    __tablename__ = "work_events"
    __table_args__ = (
        UniqueConstraint("organization_id", "id"),
        UniqueConstraint("organization_id", "actor_id", "idempotency_key"),
        UniqueConstraint("organization_id", "draft_id"),
        ForeignKeyConstraint(
            ["organization_id", "work_item_id"], ["work_items.organization_id", "work_items.id"]
        ),
        ForeignKeyConstraint(
            ["organization_id", "actor_id"], ["memberships.organization_id", "memberships.id"]
        ),
        ForeignKeyConstraint(
            ["organization_id", "draft_id"], ["update_drafts.organization_id", "update_drafts.id"]
        ),
        Index("ix_event_history", "organization_id", "work_item_id", "recorded_at"),
    )
    work_item_id: Mapped[str] = mapped_column(String(36))
    actor_id: Mapped[str] = mapped_column(String(36))
    draft_id: Mapped[str | None] = mapped_column(String(36))
    event_type: Mapped[str] = mapped_column(String(40))
    event_payload: Mapped[dict[str, Any]] = mapped_column(json_type)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    source_ref: Mapped[str] = mapped_column(String(100))
    idempotency_key: Mapped[str] = mapped_column(String(100))
    request_hash: Mapped[str] = mapped_column(String(64))


class AuditEntry(TenantEntity, Base):
    __tablename__ = "audit_entries"
    actor_user_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    action: Mapped[str] = mapped_column(String(60))
    entity_id: Mapped[str] = mapped_column(String(36))
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class AnalysisRun(TenantEntity, Base):
    __tablename__ = "analysis_runs"
    __table_args__ = (
        ForeignKeyConstraint(
            ["organization_id", "draft_id"], ["update_drafts.organization_id", "update_drafts.id"]
        ),
    )
    draft_id: Mapped[str] = mapped_column(String(36))
    purpose: Mapped[str] = mapped_column(String(60))
    provider: Mapped[str] = mapped_column(String(50))
    model: Mapped[str] = mapped_column(String(50))
    prompt_version: Mapped[str] = mapped_column(String(30))
    input_evidence_ids: Mapped[list[str]] = mapped_column(json_type)
    output_schema_version: Mapped[str] = mapped_column(String(30))
    latency_ms: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(30))
    cost_estimate: Mapped[str] = mapped_column(String(30), default="0")
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
