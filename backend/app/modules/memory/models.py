"""Confirmed lessons and personal owner preferences, distinct from business facts."""

from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.infrastructure.models import Base, TenantEntity, now


class MemoryEntry(TenantEntity, Base):
    __tablename__ = "memory_entries"
    __table_args__ = (
        UniqueConstraint("organization_id", "id"),
        UniqueConstraint("organization_id", "actor_id", "request_key"),
        ForeignKeyConstraint(
            ["organization_id", "actor_id"], ["memberships.organization_id", "memberships.id"]
        ),
        ForeignKeyConstraint(
            ["organization_id", "decision_id", "outcome_id"],
            [
                "decision_outcomes.organization_id",
                "decision_outcomes.decision_id",
                "decision_outcomes.id",
            ],
        ),
        CheckConstraint("kind IN ('experience', 'preference')", name="ck_memory_kind"),
        CheckConstraint(
            "state IN ('proposed', 'confirmed', 'revoked', 'deleted')", name="ck_memory_state"
        ),
        Index(
            "uq_memory_active_preference",
            "organization_id",
            "actor_id",
            "preference_key",
            unique=True,
            postgresql_where=text("kind = 'preference' AND state = 'confirmed'"),
            sqlite_where=text("kind = 'preference' AND state = 'confirmed'"),
        ),
        CheckConstraint(
            "(kind = 'experience' AND decision_id IS NOT NULL AND outcome_id IS NOT NULL "
            "AND source_version IS NOT NULL AND preference_key IS NULL) OR "
            "(kind = 'preference' AND decision_id IS NULL AND outcome_id IS NULL "
            "AND preference_key IS NOT NULL AND "
            "preference_key IN ('focus', 'communication', 'decision_rule', 'planning_goal'))",
            name="ck_memory_source",
        ),
    )
    kind: Mapped[str] = mapped_column(String(20))
    actor_id: Mapped[str] = mapped_column(String(36))
    decision_id: Mapped[str | None] = mapped_column(String(36))
    outcome_id: Mapped[str | None] = mapped_column(String(36))
    preference_key: Mapped[str | None] = mapped_column(String(30))
    source_text: Mapped[str] = mapped_column(Text, default="")
    source_hash: Mapped[str] = mapped_column(String(64))
    source_version: Mapped[int | None] = mapped_column(Integer)
    title: Mapped[str] = mapped_column(String(200))
    content: Mapped[str] = mapped_column(Text, default="")
    applicability: Mapped[str] = mapped_column(Text, default="")
    source_quote: Mapped[str] = mapped_column(String(500), default="")
    search_text: Mapped[str] = mapped_column(Text, default="")
    state: Mapped[str] = mapped_column(String(20), default="proposed")
    version: Mapped[int] = mapped_column(Integer, default=1)
    request_key: Mapped[str] = mapped_column(String(36))
    request_hash: Mapped[str] = mapped_column(String(64))
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    __mapper_args__ = {"version_id_col": version}


class MemoryUse(TenantEntity, Base):
    __tablename__ = "memory_uses"
    __table_args__ = (
        UniqueConstraint("organization_id", "id"),
        UniqueConstraint("organization_id", "entry_id", "run_id"),
        ForeignKeyConstraint(
            ["organization_id", "entry_id"], ["memory_entries.organization_id", "memory_entries.id"]
        ),
        ForeignKeyConstraint(
            ["organization_id", "run_id"], ["agent_runs.organization_id", "agent_runs.id"]
        ),
    )
    entry_id: Mapped[str] = mapped_column(String(36))
    run_id: Mapped[str] = mapped_column(String(36))
