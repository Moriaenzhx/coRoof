"""Durable execution intent for explicitly submitted, session-bound read tasks."""

from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.infrastructure.models import Base, TenantEntity, now


class AgentExecution(TenantEntity, Base):
    __tablename__ = "agent_executions"
    __table_args__ = (
        UniqueConstraint("organization_id", "id"),
        UniqueConstraint("organization_id", "run_id"),
        ForeignKeyConstraint(
            ["organization_id", "run_id"], ["agent_runs.organization_id", "agent_runs.id"]
        ),
        CheckConstraint(
            "state IN ('queued', 'running', 'stopped')", name="ck_agent_execution_state"
        ),
        CheckConstraint("generation >= 1", name="ck_agent_execution_generation"),
        CheckConstraint(
            "(state = 'running' AND lease_token IS NOT NULL AND lease_until IS NOT NULL) "
            "OR (state != 'running' AND lease_token IS NULL AND lease_until IS NULL)",
            name="ck_agent_execution_lease",
        ),
        Index("ix_agent_execution_dispatch", "state", "available_at"),
        Index("ix_agent_execution_recovery", "state", "lease_until"),
    )
    run_id: Mapped[str] = mapped_column(String(36))
    state: Mapped[str] = mapped_column(String(20), default="queued")
    generation: Mapped[int] = mapped_column(Integer, default=1)
    lease_token: Mapped[str | None] = mapped_column(String(36))
    lease_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    available_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
