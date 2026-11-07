"""read_only_connectors"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0008_connectors"
down_revision = "0007_agent_drafts"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "connectors",
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("kind", sa.String(length=20), nullable=False),
        sa.Column("base_url", sa.String(length=200), nullable=False),
        sa.Column("project_key", sa.String(length=100), nullable=False),
        sa.Column("item_type", sa.String(length=100), nullable=False),
        sa.Column("department_id", sa.String(length=36), nullable=False),
        sa.Column("owner_field", sa.String(length=100), nullable=True),
        sa.Column(
            "status_map",
            sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql"),
            nullable=False,
        ),
        sa.Column("credential", sa.Text(), nullable=True),
        sa.Column("key_suffix", sa.String(length=4), nullable=False),
        sa.Column("state", sa.String(length=20), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("tested_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("synced_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("watermark", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.String(length=40), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("organization_id", sa.String(length=36), nullable=False),
        sa.CheckConstraint("kind IN ('gitlab', 'feishu_project')"),
        sa.CheckConstraint(
            "state IN ('saved', 'tested', 'active', 'paused', 'revoked', 'permission_lost')"
        ),
        sa.ForeignKeyConstraint(
            ["organization_id", "department_id"],
            ["departments.organization_id", "departments.id"],
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("organization_id", "id"),
        sa.UniqueConstraint("organization_id", "kind", "base_url", "project_key", "item_type"),
    )
    with op.batch_alter_table("connectors", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_connectors_organization_id"), ["organization_id"], unique=False
        )

    op.create_table(
        "source_members",
        sa.Column("connector_id", sa.String(length=36), nullable=False),
        sa.Column("external_id", sa.String(length=100), nullable=False),
        sa.Column("membership_id", sa.String(length=36), nullable=True),
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("organization_id", sa.String(length=36), nullable=False),
        sa.ForeignKeyConstraint(
            ["organization_id", "connector_id"],
            ["connectors.organization_id", "connectors.id"],
        ),
        sa.ForeignKeyConstraint(
            ["organization_id", "membership_id"],
            ["memberships.organization_id", "memberships.id"],
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("organization_id", "connector_id", "external_id"),
        sa.UniqueConstraint("organization_id", "id"),
    )
    with op.batch_alter_table("source_members", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_source_members_organization_id"), ["organization_id"], unique=False
        )

    op.create_table(
        "source_records",
        sa.Column("connector_id", sa.String(length=36), nullable=False),
        sa.Column("external_id", sa.String(length=100), nullable=False),
        sa.Column("payload_hash", sa.String(length=64), nullable=False),
        sa.Column(
            "raw_payload",
            sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql"),
            nullable=False,
        ),
        sa.Column(
            "normalized",
            sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql"),
            nullable=False,
        ),
        sa.Column("source_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("organization_id", sa.String(length=36), nullable=False),
        sa.ForeignKeyConstraint(
            ["organization_id", "connector_id"],
            ["connectors.organization_id", "connectors.id"],
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("organization_id", "connector_id", "external_id", "payload_hash"),
        sa.UniqueConstraint("organization_id", "connector_id", "id"),
        sa.UniqueConstraint("organization_id", "id"),
    )
    with op.batch_alter_table("source_records", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_source_records_organization_id"), ["organization_id"], unique=False
        )

    op.create_table(
        "sync_runs",
        sa.Column("connector_id", sa.String(length=36), nullable=False),
        sa.Column("actor_id", sa.String(length=36), nullable=False),
        sa.Column("connector_version", sa.Integer(), nullable=False),
        sa.Column("request_key", sa.String(length=36), nullable=False),
        sa.Column("request_hash", sa.String(length=64), nullable=False),
        sa.Column("mode", sa.String(length=20), nullable=False),
        sa.Column("state", sa.String(length=20), nullable=False),
        sa.Column("phase", sa.String(length=20), nullable=False),
        sa.Column("page", sa.Integer(), nullable=False),
        sa.Column("cursor", sa.String(length=200), nullable=True),
        sa.Column("since", sa.DateTime(timezone=True), nullable=True),
        sa.Column("until", sa.DateTime(timezone=True), nullable=False),
        sa.Column("processed", sa.Integer(), nullable=False),
        sa.Column("failures", sa.Integer(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("error_code", sa.String(length=40), nullable=True),
        sa.Column("lease_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("organization_id", sa.String(length=36), nullable=False),
        sa.CheckConstraint("mode IN ('verify', 'full', 'incremental')"),
        sa.CheckConstraint(
            "state IN ('queued', 'running', 'retry_wait', 'succeeded', 'failed', 'cancelled')"
        ),
        sa.ForeignKeyConstraint(
            ["organization_id", "actor_id"],
            ["memberships.organization_id", "memberships.id"],
        ),
        sa.ForeignKeyConstraint(
            ["organization_id", "connector_id"],
            ["connectors.organization_id", "connectors.id"],
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("organization_id", "actor_id", "request_key"),
        sa.UniqueConstraint("organization_id", "id"),
    )
    with op.batch_alter_table("sync_runs", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_sync_runs_organization_id"), ["organization_id"], unique=False
        )

    op.create_table(
        "sync_outbox",
        sa.Column("run_id", sa.String(length=36), nullable=False),
        sa.Column("run_version", sa.Integer(), nullable=False),
        sa.Column("available_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("organization_id", sa.String(length=36), nullable=False),
        sa.ForeignKeyConstraint(
            ["organization_id", "run_id"],
            ["sync_runs.organization_id", "sync_runs.id"],
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("organization_id", "id"),
        sa.UniqueConstraint("organization_id", "run_id", "run_version"),
    )
    with op.batch_alter_table("sync_outbox", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_sync_outbox_available_at"), ["available_at"], unique=False
        )
        batch_op.create_index(
            batch_op.f("ix_sync_outbox_organization_id"), ["organization_id"], unique=False
        )

    op.create_table(
        "source_links",
        sa.Column("connector_id", sa.String(length=36), nullable=False),
        sa.Column("external_id", sa.String(length=100), nullable=False),
        sa.Column("record_id", sa.String(length=36), nullable=False),
        sa.Column("work_item_id", sa.String(length=36), nullable=True),
        sa.Column("state", sa.String(length=20), nullable=False),
        sa.Column("mapping_issue", sa.String(length=40), nullable=True),
        sa.Column("projection_hash", sa.String(length=64), nullable=True),
        sa.Column("seen_run_id", sa.String(length=36), nullable=True),
        sa.Column("checked_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("organization_id", sa.String(length=36), nullable=False),
        sa.CheckConstraint("state IN ('pending', 'linked', 'withdrawn')"),
        sa.ForeignKeyConstraint(
            ["organization_id", "connector_id", "record_id"],
            ["source_records.organization_id", "source_records.connector_id", "source_records.id"],
        ),
        sa.ForeignKeyConstraint(
            ["organization_id", "connector_id"],
            ["connectors.organization_id", "connectors.id"],
        ),
        sa.ForeignKeyConstraint(
            ["organization_id", "seen_run_id"],
            ["sync_runs.organization_id", "sync_runs.id"],
        ),
        sa.ForeignKeyConstraint(
            ["organization_id", "work_item_id"],
            ["work_items.organization_id", "work_items.id"],
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("organization_id", "connector_id", "external_id"),
        sa.UniqueConstraint("organization_id", "id"),
        sa.UniqueConstraint("organization_id", "work_item_id"),
    )
    with op.batch_alter_table("source_links", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_source_links_organization_id"), ["organization_id"], unique=False
        )


def downgrade() -> None:
    with op.batch_alter_table("source_links", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_source_links_organization_id"))

    op.drop_table("source_links")
    with op.batch_alter_table("sync_outbox", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_sync_outbox_organization_id"))
        batch_op.drop_index(batch_op.f("ix_sync_outbox_available_at"))

    op.drop_table("sync_outbox")
    with op.batch_alter_table("sync_runs", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_sync_runs_organization_id"))

    op.drop_table("sync_runs")
    with op.batch_alter_table("source_records", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_source_records_organization_id"))

    op.drop_table("source_records")
    with op.batch_alter_table("source_members", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_source_members_organization_id"))

    op.drop_table("source_members")
    with op.batch_alter_table("connectors", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_connectors_organization_id"))

    op.drop_table("connectors")
