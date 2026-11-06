"""Tenant-owned connector configuration, immutable intake and delivery receipts."""

from datetime import datetime
from typing import Any

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

from app.infrastructure.models import Base, TenantEntity, json_type, now


class Connector(TenantEntity, Base):
    __tablename__ = "connectors"
    __table_args__ = (
        UniqueConstraint("organization_id", "id"),
        UniqueConstraint("organization_id", "kind", "base_url", "project_key", "item_type"),
        ForeignKeyConstraint(
            ["organization_id", "department_id"], ["departments.organization_id", "departments.id"]
        ),
        CheckConstraint("kind IN ('gitlab', 'feishu_project')"),
        CheckConstraint(
            "state IN ('saved', 'tested', 'active', 'paused', 'revoked', 'permission_lost')"
        ),
    )
    name: Mapped[str] = mapped_column(String(100))
    kind: Mapped[str] = mapped_column(String(20))
    base_url: Mapped[str] = mapped_column(String(200))
    project_key: Mapped[str] = mapped_column(String(100))
    item_type: Mapped[str] = mapped_column(String(100), default="issue")
    department_id: Mapped[str] = mapped_column(String(36))
    owner_field: Mapped[str | None] = mapped_column(String(100))
    status_map: Mapped[dict[str, str]] = mapped_column(json_type, default=dict)
    credential: Mapped[str | None] = mapped_column(Text)
    key_suffix: Mapped[str] = mapped_column(String(4))
    state: Mapped[str] = mapped_column(String(20), default="saved")
    version: Mapped[int] = mapped_column(Integer, default=1)
    tested_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    watermark: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[str | None] = mapped_column(String(40))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    __mapper_args__ = {"version_id_col": version}


class SyncRun(TenantEntity, Base):
    __tablename__ = "sync_runs"
    __table_args__ = (
        UniqueConstraint("organization_id", "id"),
        UniqueConstraint("organization_id", "actor_id", "request_key"),
        ForeignKeyConstraint(
            ["organization_id", "connector_id"], ["connectors.organization_id", "connectors.id"]
        ),
        ForeignKeyConstraint(
            ["organization_id", "actor_id"], ["memberships.organization_id", "memberships.id"]
        ),
        CheckConstraint("mode IN ('verify', 'full', 'incremental')"),
        CheckConstraint(
            "state IN ('queued', 'running', 'retry_wait', 'succeeded', 'failed', 'cancelled')"
        ),
    )
    connector_id: Mapped[str] = mapped_column(String(36))
    actor_id: Mapped[str] = mapped_column(String(36))
    connector_version: Mapped[int] = mapped_column(Integer)
    request_key: Mapped[str] = mapped_column(String(36))
    request_hash: Mapped[str] = mapped_column(String(64))
    mode: Mapped[str] = mapped_column(String(20))
    state: Mapped[str] = mapped_column(String(20), default="queued")
    phase: Mapped[str] = mapped_column(String(20), default="pages")
    page: Mapped[int] = mapped_column(Integer, default=1)
    cursor: Mapped[str | None] = mapped_column(String(200))
    since: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    until: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    processed: Mapped[int] = mapped_column(Integer, default=0)
    failures: Mapped[int] = mapped_column(Integer, default=0)
    version: Mapped[int] = mapped_column(Integer, default=1)
    error_code: Mapped[str | None] = mapped_column(String(40))
    lease_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class SourceRecord(TenantEntity, Base):
    __tablename__ = "source_records"
    __table_args__ = (
        UniqueConstraint("organization_id", "id"),
        UniqueConstraint("organization_id", "connector_id", "id"),
        UniqueConstraint("organization_id", "connector_id", "external_id", "payload_hash"),
        ForeignKeyConstraint(
            ["organization_id", "connector_id"], ["connectors.organization_id", "connectors.id"]
        ),
    )
    connector_id: Mapped[str] = mapped_column(String(36))
    external_id: Mapped[str] = mapped_column(String(100))
    payload_hash: Mapped[str] = mapped_column(String(64))
    raw_payload: Mapped[dict[str, Any]] = mapped_column(json_type)
    normalized: Mapped[dict[str, Any]] = mapped_column(json_type)
    source_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class SourceLink(TenantEntity, Base):
    __tablename__ = "source_links"
    __table_args__ = (
        UniqueConstraint("organization_id", "id"),
        UniqueConstraint("organization_id", "connector_id", "external_id"),
        UniqueConstraint("organization_id", "work_item_id"),
        ForeignKeyConstraint(
            ["organization_id", "connector_id"], ["connectors.organization_id", "connectors.id"]
        ),
        ForeignKeyConstraint(
            ["organization_id", "connector_id", "record_id"],
            ["source_records.organization_id", "source_records.connector_id", "source_records.id"],
        ),
        ForeignKeyConstraint(
            ["organization_id", "work_item_id"], ["work_items.organization_id", "work_items.id"]
        ),
        ForeignKeyConstraint(
            ["organization_id", "seen_run_id"], ["sync_runs.organization_id", "sync_runs.id"]
        ),
        CheckConstraint("state IN ('pending', 'linked', 'withdrawn')"),
    )
    connector_id: Mapped[str] = mapped_column(String(36))
    external_id: Mapped[str] = mapped_column(String(100))
    record_id: Mapped[str] = mapped_column(String(36))
    work_item_id: Mapped[str | None] = mapped_column(String(36))
    state: Mapped[str] = mapped_column(String(20), default="pending")
    mapping_issue: Mapped[str | None] = mapped_column(String(40))
    projection_hash: Mapped[str | None] = mapped_column(String(64))
    seen_run_id: Mapped[str | None] = mapped_column(String(36))
    checked_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class SourceMember(TenantEntity, Base):
    __tablename__ = "source_members"
    __table_args__ = (
        UniqueConstraint("organization_id", "id"),
        UniqueConstraint("organization_id", "connector_id", "external_id"),
        ForeignKeyConstraint(
            ["organization_id", "connector_id"], ["connectors.organization_id", "connectors.id"]
        ),
        ForeignKeyConstraint(
            ["organization_id", "membership_id"], ["memberships.organization_id", "memberships.id"]
        ),
    )
    connector_id: Mapped[str] = mapped_column(String(36))
    external_id: Mapped[str] = mapped_column(String(100))
    membership_id: Mapped[str | None] = mapped_column(String(36))


class SyncOutbox(TenantEntity, Base):
    __tablename__ = "sync_outbox"
    __table_args__ = (
        UniqueConstraint("organization_id", "id"),
        UniqueConstraint("organization_id", "run_id", "run_version"),
        ForeignKeyConstraint(
            ["organization_id", "run_id"], ["sync_runs.organization_id", "sync_runs.id"]
        ),
    )
    run_id: Mapped[str] = mapped_column(String(36))
    run_version: Mapped[int] = mapped_column(Integer)
    available_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, index=True)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
