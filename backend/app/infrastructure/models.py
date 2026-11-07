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
    oidc_issuer: Mapped[str | None] = mapped_column(String(500))
    oidc_subject: Mapped[str | None] = mapped_column(String(255))
    __table_args__ = (
        UniqueConstraint("oidc_issuer", "oidc_subject", name="uq_identity_oidc"),
        CheckConstraint(
            "(oidc_issuer IS NULL AND oidc_subject IS NULL) OR "
            "(identity_provider = 'oidc' AND oidc_issuer IS NOT NULL "
            "AND oidc_subject IS NOT NULL)",
            name="ck_identity_binding",
        ),
    )
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
    auth_mode: Mapped[str] = mapped_column(String(20), default="mock", server_default="mock")
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
        UniqueConstraint("organization_id", "id", name="uq_invitation_tenant"),
        UniqueConstraint(
            "organization_id", "invited_by", "request_key", name="uq_invitation_request"
        ),
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
    auth_mode: Mapped[str] = mapped_column(String(20), default="mock", server_default="mock")
    request_key: Mapped[str | None] = mapped_column(String(36))
    request_hash: Mapped[str | None] = mapped_column(String(64))
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
        ForeignKeyConstraint(
            ["organization_id", "work_item_id", "decision_id"],
            ["decisions.organization_id", "decisions.work_item_id", "decisions.id"],
            name="fk_draft_arrangement",
            use_alter=True,
        ),
        Index("ix_draft_arrangement", "organization_id", "decision_id"),
        CheckConstraint("state IN ('pending', 'confirmed')"),
    )
    work_item_id: Mapped[str] = mapped_column(String(36))
    decision_id: Mapped[str | None] = mapped_column(String(36))
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
        ForeignKeyConstraint(
            ["organization_id", "document_id"],
            ["knowledge_documents.organization_id", "knowledge_documents.id"],
            name="fk_work_event_document",
        ),
        CheckConstraint(
            "(CASE WHEN work_item_id IS NULL THEN 0 ELSE 1 END + "
            "CASE WHEN document_id IS NULL THEN 0 ELSE 1 END + "
            "CASE WHEN memory_entry_id IS NULL THEN 0 ELSE 1 END) = 1",
            name="ck_work_event_target",
        ),
        ForeignKeyConstraint(
            ["organization_id", "memory_entry_id"],
            ["memory_entries.organization_id", "memory_entries.id"],
            name="fk_work_event_memory",
            use_alter=True,
        ),
        Index("ix_event_history", "organization_id", "work_item_id", "recorded_at"),
    )
    work_item_id: Mapped[str | None] = mapped_column(String(36))
    document_id: Mapped[str | None] = mapped_column(String(36))
    memory_entry_id: Mapped[str | None] = mapped_column(String(36))
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
        UniqueConstraint("organization_id", "id", name="uq_analysis_tenant_id"),
        ForeignKeyConstraint(
            ["organization_id", "actor_id"],
            ["memberships.organization_id", "memberships.id"],
            name="fk_analysis_actor",
        ),
        ForeignKeyConstraint(
            ["organization_id", "draft_id"], ["update_drafts.organization_id", "update_drafts.id"]
        ),
    )
    draft_id: Mapped[str | None] = mapped_column(String(36))
    actor_id: Mapped[str | None] = mapped_column(String(36))
    result: Mapped[dict[str, Any] | None] = mapped_column(json_type)
    purpose: Mapped[str] = mapped_column(String(60))
    provider: Mapped[str] = mapped_column(String(50))
    model: Mapped[str] = mapped_column(String(50))
    prompt_version: Mapped[str] = mapped_column(String(30))
    input_evidence_ids: Mapped[list[str]] = mapped_column(json_type)
    output_schema_version: Mapped[str] = mapped_column(String(30))
    latency_ms: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(30))
    failure_code: Mapped[str | None] = mapped_column(String(40))
    cost_estimate: Mapped[str] = mapped_column(String(30), default="0")
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class ModelInvocation(TenantEntity, Base):
    __tablename__ = "model_invocations"
    __table_args__ = (
        UniqueConstraint("organization_id", "id"),
        UniqueConstraint("organization_id", "actor_id", "request_id"),
        ForeignKeyConstraint(
            ["organization_id", "actor_id"], ["memberships.organization_id", "memberships.id"]
        ),
        ForeignKeyConstraint(
            ["organization_id", "analysis_run_id"],
            ["analysis_runs.organization_id", "analysis_runs.id"],
        ),
        ForeignKeyConstraint(
            ["organization_id", "connection_id"],
            ["ai_connections.organization_id", "ai_connections.id"],
            name="fk_invocation_ai_connection",
        ),
        CheckConstraint("status IN ('pending', 'succeeded', 'failed', 'unknown')"),
        CheckConstraint("charged_tokens >= 0"),
        Index("ix_model_invocations_tenant_time", "organization_id", "started_at"),
    )
    actor_id: Mapped[str] = mapped_column(String(36))
    analysis_run_id: Mapped[str] = mapped_column(String(36))
    request_id: Mapped[str] = mapped_column(String(36))
    request_hash: Mapped[str] = mapped_column(String(64))
    task: Mapped[str] = mapped_column(String(60))
    provider: Mapped[str] = mapped_column(String(50))
    model: Mapped[str] = mapped_column(String(100))
    returned_model: Mapped[str | None] = mapped_column(String(100))
    profile_id: Mapped[str] = mapped_column(String(60))
    adapter_version: Mapped[str] = mapped_column(String(30))
    prompt_version: Mapped[str] = mapped_column(String(30))
    schema_version: Mapped[str] = mapped_column(String(30))
    status: Mapped[str] = mapped_column(String(20), default="pending")
    error_code: Mapped[str | None] = mapped_column(String(40))
    provider_request_id: Mapped[str | None] = mapped_column(String(150))
    usage: Mapped[dict[str, Any] | None] = mapped_column(json_type)
    charged_tokens: Mapped[int] = mapped_column(Integer)
    request_sent: Mapped[bool | None] = mapped_column(Boolean)
    latency_ms: Mapped[int | None] = mapped_column(Integer)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    lease_expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    connection_id: Mapped[str | None] = mapped_column(String(36))
    billing_mode: Mapped[str] = mapped_column(
        String(20), default="platform", server_default="platform"
    )
    config_revision: Mapped[int] = mapped_column(Integer, default=0, server_default="0")


class AIConnection(TenantEntity, Base):
    __tablename__ = "ai_connections"
    __table_args__ = (
        UniqueConstraint("organization_id", "id"),
        UniqueConstraint("organization_id", "actor_id", "request_key"),
        ForeignKeyConstraint(
            ["organization_id", "actor_id"], ["memberships.organization_id", "memberships.id"]
        ),
        CheckConstraint("state IN ('draft', 'testing', 'tested', 'failed', 'revoked')"),
    )
    actor_id: Mapped[str] = mapped_column(String(36))
    request_key: Mapped[str] = mapped_column(String(36))
    request_hash: Mapped[str] = mapped_column(String(64))
    name: Mapped[str] = mapped_column(String(80))
    provider: Mapped[str] = mapped_column(String(40))
    model: Mapped[str] = mapped_column(String(100))
    base_url: Mapped[str] = mapped_column(String(500))
    output_mode: Mapped[str] = mapped_column(String(20))
    credential: Mapped[str | None] = mapped_column(Text)
    key_suffix: Mapped[str] = mapped_column(String(4))
    state: Mapped[str] = mapped_column(String(20), default="draft")
    version: Mapped[int] = mapped_column(Integer, default=1)
    tested_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[str | None] = mapped_column(String(40))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class AISettings(TenantEntity, Base):
    __tablename__ = "ai_settings"
    __table_args__ = (
        UniqueConstraint("organization_id"),
        UniqueConstraint("organization_id", "id"),
        ForeignKeyConstraint(
            ["organization_id", "connection_id"],
            ["ai_connections.organization_id", "ai_connections.id"],
        ),
        CheckConstraint("mode IN ('platform', 'byok', 'disabled')"),
    )
    mode: Mapped[str] = mapped_column(String(20), default="platform")
    connection_id: Mapped[str | None] = mapped_column(String(36))
    version: Mapped[int] = mapped_column(Integer, default=1)
    daily_call_limit: Mapped[int] = mapped_column(Integer)
    daily_token_limit: Mapped[int] = mapped_column(Integer)
    monthly_token_limit: Mapped[int] = mapped_column(Integer)
    concurrency_limit: Mapped[int] = mapped_column(Integer)
    alert_percent: Mapped[int] = mapped_column(Integer, default=80)


class AIConfigEvent(TenantEntity, Base):
    __tablename__ = "ai_config_events"
    __table_args__ = (
        UniqueConstraint("organization_id", "id"),
        UniqueConstraint("organization_id", "actor_id", "request_key"),
        ForeignKeyConstraint(
            ["organization_id", "actor_id"], ["memberships.organization_id", "memberships.id"]
        ),
        ForeignKeyConstraint(
            ["organization_id", "connection_id"],
            ["ai_connections.organization_id", "ai_connections.id"],
        ),
    )
    actor_id: Mapped[str] = mapped_column(String(36))
    connection_id: Mapped[str | None] = mapped_column(String(36))
    request_key: Mapped[str | None] = mapped_column(String(36))
    action: Mapped[str] = mapped_column(String(40))
    revision: Mapped[int] = mapped_column(Integer)
    detail: Mapped[str] = mapped_column(String(250))
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class EvidenceSnapshot(TenantEntity, Base):
    __tablename__ = "evidence_snapshots"
    __table_args__ = (
        UniqueConstraint("organization_id", "id"),
        UniqueConstraint("organization_id", "work_item_id", "work_version"),
        ForeignKeyConstraint(
            ["organization_id", "work_item_id"], ["work_items.organization_id", "work_items.id"]
        ),
        ForeignKeyConstraint(
            ["organization_id", "event_id"], ["work_events.organization_id", "work_events.id"]
        ),
    )
    work_item_id: Mapped[str] = mapped_column(String(36))
    work_version: Mapped[int] = mapped_column(Integer)
    event_id: Mapped[str | None] = mapped_column(String(36))
    facts: Mapped[dict[str, Any]] = mapped_column(json_type)
    excerpt: Mapped[str] = mapped_column(Text)
    source_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    captured_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class Signal(TenantEntity, Base):
    __tablename__ = "signals"
    __table_args__ = (
        UniqueConstraint("organization_id", "id"),
        UniqueConstraint("organization_id", "work_item_id", "category"),
        ForeignKeyConstraint(
            ["organization_id", "work_item_id"], ["work_items.organization_id", "work_items.id"]
        ),
        ForeignKeyConstraint(
            ["organization_id", "evidence_id"],
            ["evidence_snapshots.organization_id", "evidence_snapshots.id"],
        ),
        CheckConstraint("state IN ('active', 'resolved')"),
        CheckConstraint("category IN ('support', 'overdue', 'deadline_blocked', 'stale')"),
        CheckConstraint("severity IN ('attention', 'warning', 'info')"),
    )
    work_item_id: Mapped[str] = mapped_column(String(36))
    evidence_id: Mapped[str] = mapped_column(String(36))
    category: Mapped[str] = mapped_column(String(30))
    severity: Mapped[str] = mapped_column(String(20))
    state: Mapped[str] = mapped_column(String(20), default="active")
    rule_version: Mapped[str] = mapped_column(String(30), default="signals-v1")
    detected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    evaluated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    version: Mapped[int] = mapped_column(Integer, default=1)
    __mapper_args__ = {"version_id_col": version}


class Decision(TenantEntity, Base):
    __tablename__ = "decisions"
    __table_args__ = (
        UniqueConstraint("organization_id", "id"),
        UniqueConstraint("organization_id", "work_item_id", "id", name="uq_decision_work"),
        UniqueConstraint("organization_id", "actor_id", "idempotency_key"),
        ForeignKeyConstraint(
            ["organization_id", "work_item_id"], ["work_items.organization_id", "work_items.id"]
        ),
        ForeignKeyConstraint(
            ["organization_id", "signal_id"], ["signals.organization_id", "signals.id"]
        ),
        ForeignKeyConstraint(
            ["organization_id", "analysis_id"],
            ["analysis_runs.organization_id", "analysis_runs.id"],
        ),
        ForeignKeyConstraint(
            ["organization_id", "actor_id"], ["memberships.organization_id", "memberships.id"]
        ),
        ForeignKeyConstraint(
            ["organization_id", "confirmed_by"], ["memberships.organization_id", "memberships.id"]
        ),
        CheckConstraint("state IN ('pending', 'confirmed')"),
    )
    work_item_id: Mapped[str] = mapped_column(String(36))
    signal_id: Mapped[str | None] = mapped_column(String(36))
    signal_version: Mapped[int | None] = mapped_column(Integer)
    analysis_id: Mapped[str] = mapped_column(String(36))
    actor_id: Mapped[str] = mapped_column(String(36))
    title: Mapped[str] = mapped_column(String(200))
    work_version: Mapped[int] = mapped_column(Integer)
    context_snapshot: Mapped[dict[str, Any]] = mapped_column(json_type)
    options: Mapped[list[dict[str, Any]]] = mapped_column(json_type)
    state: Mapped[str] = mapped_column(String(20), default="pending")
    selected_option: Mapped[str | None] = mapped_column(String(40))
    selected_plan: Mapped[str | None] = mapped_column(Text)
    follow_up: Mapped[str | None] = mapped_column(Text)
    follow_up_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    confirmed_by: Mapped[str | None] = mapped_column(String(36))
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    idempotency_key: Mapped[str] = mapped_column(String(100))
    request_hash: Mapped[str] = mapped_column(String(64))
    confirmation_hash: Mapped[str | None] = mapped_column(String(64))
    version: Mapped[int] = mapped_column(Integer, default=1)
    __mapper_args__ = {"version_id_col": version}


class DecisionOutcome(TenantEntity, Base):
    __tablename__ = "decision_outcomes"
    __table_args__ = (
        UniqueConstraint("organization_id", "decision_id", "id", name="uq_outcome_source"),
        UniqueConstraint("organization_id", "decision_id", "idempotency_key"),
        ForeignKeyConstraint(
            ["organization_id", "decision_id"], ["decisions.organization_id", "decisions.id"]
        ),
        ForeignKeyConstraint(
            ["organization_id", "actor_id"], ["memberships.organization_id", "memberships.id"]
        ),
    )
    decision_id: Mapped[str] = mapped_column(String(36))
    actor_id: Mapped[str] = mapped_column(String(36))
    observed_result: Mapped[str] = mapped_column(Text)
    evidence_refs: Mapped[list[str]] = mapped_column(json_type)
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    idempotency_key: Mapped[str] = mapped_column(String(100))
    request_hash: Mapped[str] = mapped_column(String(64))


class AgentRun(TenantEntity, Base):
    __tablename__ = "agent_runs"
    __table_args__ = (
        UniqueConstraint("organization_id", "id"),
        UniqueConstraint("organization_id", "actor_id", "request_key"),
        ForeignKeyConstraint(
            ["organization_id", "parent_run_id"],
            ["agent_runs.organization_id", "agent_runs.id"],
            name="fk_agent_parent_run",
        ),
        CheckConstraint(
            "parent_run_id IS NULL OR (parent_run_id != id AND task = 'read' "
            "AND watch_grant_id IS NULL)",
            name="ck_agent_parent_read_only",
        ),
        UniqueConstraint("organization_id", "watch_grant_id", "id", name="uq_agent_watch_grant"),
        ForeignKeyConstraint(
            ["organization_id", "watch_grant_id"],
            ["watch_grants.organization_id", "watch_grants.id"],
            name="fk_agent_watch_grant",
        ),
        CheckConstraint(
            "watch_grant_id IS NULL OR (task = 'read' AND work_item_id IS NOT NULL "
            "AND session_hash = '')",
            name="ck_agent_watch_read_only",
        ),
        ForeignKeyConstraint(
            ["organization_id", "actor_id"], ["memberships.organization_id", "memberships.id"]
        ),
        ForeignKeyConstraint(
            ["organization_id", "work_item_id"], ["work_items.organization_id", "work_items.id"]
        ),
        ForeignKeyConstraint(
            ["organization_id", "draft_id"],
            ["update_drafts.organization_id", "update_drafts.id"],
            name="fk_agent_run_draft",
        ),
        CheckConstraint("task IN ('read', 'update_draft', 'memory_draft')", name="ck_agent_task"),
        CheckConstraint(
            "(task != 'memory_draft' AND memory_entry_id IS NULL AND memory_base_version IS NULL) "
            "OR (task = 'memory_draft' AND memory_entry_id IS NOT NULL "
            "AND memory_base_version IS NOT NULL AND memory_base_version > 0)",
            name="ck_agent_memory_target",
        ),
        ForeignKeyConstraint(
            ["organization_id", "memory_entry_id"],
            ["memory_entries.organization_id", "memory_entries.id"],
            name="fk_agent_memory",
        ),
        CheckConstraint(
            "state IN ('ready', 'running', 'completed', 'failed', 'cancelled', 'interrupted')"
        ),
        CheckConstraint("step_count >= 0 AND step_count <= 6"),
    )
    actor_id: Mapped[str] = mapped_column(String(36))
    # Hash only. Logout may delete the originating session; no cascading deletion of audit.
    session_hash: Mapped[str] = mapped_column(String(64))
    watch_grant_id: Mapped[str | None] = mapped_column(String(36))
    parent_run_id: Mapped[str | None] = mapped_column(String(36))
    work_item_id: Mapped[str | None] = mapped_column(String(36))
    task: Mapped[str] = mapped_column(String(20), default="read", server_default="read")
    memory_entry_id: Mapped[str | None] = mapped_column(String(36))
    memory_base_version: Mapped[int | None] = mapped_column(Integer)
    draft_id: Mapped[str | None] = mapped_column(String(36))
    question: Mapped[str] = mapped_column(String(2000))
    request_key: Mapped[str] = mapped_column(String(36))
    request_hash: Mapped[str] = mapped_column(String(64))
    scope_hash: Mapped[str] = mapped_column(String(64))
    state: Mapped[str] = mapped_column(String(20), default="ready")
    error_code: Mapped[str | None] = mapped_column(String(40))
    step_count: Mapped[int] = mapped_column(Integer, default=0)
    version: Mapped[int] = mapped_column(Integer, default=1)
    answer: Mapped[dict[str, Any] | None] = mapped_column(json_type)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    deadline: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class AgentStep(TenantEntity, Base):
    __tablename__ = "agent_steps"
    __table_args__ = (
        UniqueConstraint("organization_id", "id"),
        UniqueConstraint("organization_id", "run_id", "ordinal"),
        UniqueConstraint("organization_id", "run_id", "request_key"),
        ForeignKeyConstraint(
            ["organization_id", "run_id"], ["agent_runs.organization_id", "agent_runs.id"]
        ),
        ForeignKeyConstraint(
            ["organization_id", "analysis_id"],
            ["analysis_runs.organization_id", "analysis_runs.id"],
        ),
        CheckConstraint("state IN ('pending', 'succeeded', 'failed', 'unknown')"),
        CheckConstraint("ordinal >= 1 AND ordinal <= 6"),
    )
    run_id: Mapped[str] = mapped_column(String(36))
    analysis_id: Mapped[str | None] = mapped_column(String(36))
    request_key: Mapped[str] = mapped_column(String(36))
    expected_version: Mapped[int] = mapped_column(Integer)
    ordinal: Mapped[int] = mapped_column(Integer)
    state: Mapped[str] = mapped_column(String(20), default="pending")
    capability: Mapped[str | None] = mapped_column(String(40))
    arguments: Mapped[dict[str, Any] | None] = mapped_column(json_type)
    result: Mapped[dict[str, Any] | None] = mapped_column(json_type)
    error_code: Mapped[str | None] = mapped_column(String(40))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
