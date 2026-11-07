from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKeyConstraint,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.infrastructure.models import Base, TenantEntity, now, uid


class LoginAttempt(Base):
    """One-use, browser-bound OIDC receipt; no provider token or authorization code."""

    __tablename__ = "login_attempts"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    state_hash: Mapped[str] = mapped_column(String(64), unique=True)
    config_hash: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class InvitationDelivery(TenantEntity, Base):
    __tablename__ = "invitation_deliveries"
    __table_args__ = (
        UniqueConstraint("organization_id", "id"),
        UniqueConstraint("organization_id", "invitation_id"),
        ForeignKeyConstraint(
            ["organization_id", "invitation_id"], ["invitations.organization_id", "invitations.id"]
        ),
        CheckConstraint(
            "state IN ('queued', 'sending', 'retry_wait', 'accepted', "
            "'unknown', 'failed', 'cancelled')",
            name="ck_delivery_state",
        ),
    )
    invitation_id: Mapped[str] = mapped_column(String(36))
    payload: Mapped[str | None] = mapped_column(Text)
    state: Mapped[str] = mapped_column(String(20), default="queued")
    version: Mapped[int] = mapped_column(Integer, default=1)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    available_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    dispatched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    lease_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    accepted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[str | None] = mapped_column(String(40))
    retry_key: Mapped[str | None] = mapped_column(String(36))
    retry_hash: Mapped[str | None] = mapped_column(String(64))
    __mapper_args__ = {"version_id_col": version}
