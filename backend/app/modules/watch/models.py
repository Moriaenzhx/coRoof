from datetime import datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKeyConstraint,
    Integer,
    String,
    Text,
    UniqueConstraint,
    false,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.infrastructure.models import Base, TenantEntity, now


class WatchPolicy(TenantEntity, Base):
    __tablename__ = "watch_policies"
    __table_args__ = (
        UniqueConstraint("organization_id", "id"),
        UniqueConstraint("organization_id", "actor_id", "request_key"),
        ForeignKeyConstraint(
            ["organization_id", "actor_id"], ["memberships.organization_id", "memberships.id"]
        ),
        ForeignKeyConstraint(
            ["organization_id", "department_id"], ["departments.organization_id", "departments.id"]
        ),
        ForeignKeyConstraint(
            ["organization_id", "initiative_id"], ["initiatives.organization_id", "initiatives.id"]
        ),
        CheckConstraint("state IN ('active', 'paused', 'revoked')", name="ck_watch_policy_state"),
        CheckConstraint(
            "(scope_kind = 'organization' AND department_id IS NULL AND initiative_id IS NULL) OR "
            "(scope_kind = 'department' AND department_id IS NOT NULL "
            "AND initiative_id IS NULL) OR "
            "(scope_kind = 'initiative' AND department_id IS NULL AND initiative_id IS NOT NULL)",
            name="ck_watch_policy_scope",
        ),
        CheckConstraint(
            "interval_minutes >= 15 AND interval_minutes <= 1440", name="ck_watch_interval"
        ),
        CheckConstraint(
            "daily_analysis_limit >= 1 AND daily_analysis_limit <= 24", name="ck_watch_budget"
        ),
    )
    actor_id: Mapped[str] = mapped_column(String(36))
    name: Mapped[str] = mapped_column(String(100))
    goal: Mapped[str] = mapped_column(String(1500))
    scope_kind: Mapped[str] = mapped_column(String(20))
    department_id: Mapped[str | None] = mapped_column(String(36))
    initiative_id: Mapped[str | None] = mapped_column(String(36))
    interval_minutes: Mapped[int] = mapped_column(Integer)
    daily_analysis_limit: Mapped[int] = mapped_column(Integer)
    state: Mapped[str] = mapped_column(String(20), default="active")
    version: Mapped[int] = mapped_column(Integer, default=1)
    request_key: Mapped[str] = mapped_column(String(36))
    request_hash: Mapped[str] = mapped_column(String(64))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    next_due_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, index=True)
    scan_after_id: Mapped[str | None] = mapped_column(String(36))
    event_pending: Mapped[bool] = mapped_column(Boolean, default=False, server_default=false())
    last_checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    # Schedule progress is not a change in granted authority. Commands increment explicitly.
    __mapper_args__ = {"version_id_col": version, "version_id_generator": False}


class WatchGrant(TenantEntity, Base):
    __tablename__ = "watch_grants"
    __table_args__ = (
        UniqueConstraint("organization_id", "id"),
        UniqueConstraint("organization_id", "policy_id", "policy_version"),
        ForeignKeyConstraint(
            ["organization_id", "policy_id"],
            ["watch_policies.organization_id", "watch_policies.id"],
        ),
        ForeignKeyConstraint(
            ["organization_id", "actor_id"], ["memberships.organization_id", "memberships.id"]
        ),
    )
    policy_id: Mapped[str] = mapped_column(String(36))
    policy_version: Mapped[int] = mapped_column(Integer)
    actor_id: Mapped[str] = mapped_column(String(36))
    identity_binding: Mapped[str] = mapped_column(String(64))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class WatchCommand(TenantEntity, Base):
    __tablename__ = "watch_commands"
    __table_args__ = (
        UniqueConstraint("organization_id", "id"),
        UniqueConstraint("organization_id", "actor_id", "request_key"),
        ForeignKeyConstraint(
            ["organization_id", "policy_id"],
            ["watch_policies.organization_id", "watch_policies.id"],
        ),
        ForeignKeyConstraint(
            ["organization_id", "actor_id"], ["memberships.organization_id", "memberships.id"]
        ),
    )
    policy_id: Mapped[str] = mapped_column(String(36))
    actor_id: Mapped[str] = mapped_column(String(36))
    action: Mapped[str] = mapped_column(String(20))
    request_key: Mapped[str] = mapped_column(String(36))
    request_hash: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class WatchWake(TenantEntity, Base):
    """One transactional wake per confirmed event, coalesced before scheduling."""

    __tablename__ = "watch_wakes"
    __table_args__ = (
        UniqueConstraint("organization_id", "id"),
        UniqueConstraint("organization_id", "event_id"),
        ForeignKeyConstraint(
            ["organization_id", "event_id"], ["work_events.organization_id", "work_events.id"]
        ),
    )
    event_id: Mapped[str] = mapped_column(String(36))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, index=True)
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class WatchRun(TenantEntity, Base):
    __tablename__ = "watch_runs"
    __table_args__ = (
        UniqueConstraint("organization_id", "id"),
        UniqueConstraint("organization_id", "policy_id", "trigger_key"),
        ForeignKeyConstraint(
            ["organization_id", "policy_id"],
            ["watch_policies.organization_id", "watch_policies.id"],
        ),
        ForeignKeyConstraint(
            ["organization_id", "grant_id"], ["watch_grants.organization_id", "watch_grants.id"]
        ),
        ForeignKeyConstraint(
            ["organization_id", "work_item_id"],
            ["work_items.organization_id", "work_items.id"],
            name="fk_watch_run_work",
        ),
        ForeignKeyConstraint(
            ["organization_id", "grant_id", "agent_run_id"],
            ["agent_runs.organization_id", "agent_runs.watch_grant_id", "agent_runs.id"],
            name="fk_watch_run_agent",
        ),
        CheckConstraint(
            "state IN ('queued', 'running', 'completed', 'failed', 'cancelled', 'unknown')",
            name="ck_watch_run_state",
        ),
        CheckConstraint("phase IN ('gather', 'analyze')", name="ck_watch_run_phase"),
        CheckConstraint(
            "trigger_kind IN ('scheduled', 'event', 'manual')", name="ck_watch_run_trigger"
        ),
    )
    policy_id: Mapped[str] = mapped_column(String(36))
    grant_id: Mapped[str] = mapped_column(String(36))
    policy_version: Mapped[int] = mapped_column(Integer)
    work_item_id: Mapped[str | None] = mapped_column(String(36))
    agent_run_id: Mapped[str | None] = mapped_column(String(36))
    context_hash: Mapped[str | None] = mapped_column(String(64))
    analysis_started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    coverage_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    considered_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    source_warning_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    outcome_code: Mapped[str | None] = mapped_column(String(40))
    trigger_key: Mapped[str] = mapped_column(String(64))
    trigger_kind: Mapped[str] = mapped_column(String(20))
    state: Mapped[str] = mapped_column(String(20), default="queued")
    phase: Mapped[str] = mapped_column(String(20), default="gather")
    version: Mapped[int] = mapped_column(Integer, default=1)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    lease_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error_code: Mapped[str | None] = mapped_column(String(40))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    __mapper_args__ = {"version_id_col": version}


class WatchOutbox(TenantEntity, Base):
    __tablename__ = "watch_outbox"
    __table_args__ = (
        UniqueConstraint("organization_id", "id"),
        UniqueConstraint("organization_id", "run_id", "run_version"),
        ForeignKeyConstraint(
            ["organization_id", "run_id"], ["watch_runs.organization_id", "watch_runs.id"]
        ),
    )
    run_id: Mapped[str] = mapped_column(String(36))
    run_version: Mapped[int] = mapped_column(Integer)
    available_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, index=True)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class AttentionItem(TenantEntity, Base):
    """An owner's review queue, never a projection of actual business progress."""

    __tablename__ = "attention_items"
    __table_args__ = (
        UniqueConstraint("organization_id", "id"),
        UniqueConstraint("organization_id", "policy_id", "dedup_key"),
        ForeignKeyConstraint(
            ["organization_id", "policy_id"],
            ["watch_policies.organization_id", "watch_policies.id"],
        ),
        ForeignKeyConstraint(
            ["organization_id", "grant_id"], ["watch_grants.organization_id", "watch_grants.id"]
        ),
        ForeignKeyConstraint(
            ["organization_id", "run_id"], ["watch_runs.organization_id", "watch_runs.id"]
        ),
        ForeignKeyConstraint(
            ["organization_id", "work_item_id"], ["work_items.organization_id", "work_items.id"]
        ),
        ForeignKeyConstraint(
            ["organization_id", "decision_id"], ["decisions.organization_id", "decisions.id"]
        ),
        ForeignKeyConstraint(
            ["organization_id", "evidence_id"],
            ["evidence_snapshots.organization_id", "evidence_snapshots.id"],
        ),
        CheckConstraint(
            "state IN ('open', 'snoozed', 'dismissed', 'invalidated', 'result_recorded')",
            name="ck_attention_state",
        ),
        CheckConstraint("kind IN ('work', 'follow_up', 'coverage')", name="ck_attention_kind"),
    )
    policy_id: Mapped[str] = mapped_column(String(36))
    grant_id: Mapped[str] = mapped_column(String(36))
    run_id: Mapped[str] = mapped_column(String(36))
    work_item_id: Mapped[str | None] = mapped_column(String(36))
    decision_id: Mapped[str | None] = mapped_column(String(36))
    evidence_id: Mapped[str | None] = mapped_column(String(36))
    dedup_key: Mapped[str] = mapped_column(String(64))
    basis_hash: Mapped[str] = mapped_column(String(64))
    kind: Mapped[str] = mapped_column(String(20))
    category: Mapped[str] = mapped_column(String(40))
    state: Mapped[str] = mapped_column(String(20), default="open")
    snoozed_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    review_note: Mapped[str | None] = mapped_column(Text)
    version: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    changed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    __mapper_args__ = {"version_id_col": version}


class AttentionReview(TenantEntity, Base):
    __tablename__ = "attention_reviews"
    __table_args__ = (
        UniqueConstraint("organization_id", "id"),
        UniqueConstraint("organization_id", "actor_id", "request_key"),
        ForeignKeyConstraint(
            ["organization_id", "item_id"],
            ["attention_items.organization_id", "attention_items.id"],
        ),
        ForeignKeyConstraint(
            ["organization_id", "actor_id"], ["memberships.organization_id", "memberships.id"]
        ),
    )
    item_id: Mapped[str] = mapped_column(String(36))
    actor_id: Mapped[str] = mapped_column(String(36))
    action: Mapped[str] = mapped_column(String(20))
    note: Mapped[str | None] = mapped_column(Text)
    request_key: Mapped[str] = mapped_column(String(36))
    request_hash: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
