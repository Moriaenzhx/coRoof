"""Model invocation audit and tenant admission budgets; preserve existing analysis records."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0003_model_gateway"
down_revision = "0002_slice02"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("analysis_runs", sa.Column("failure_code", sa.String(40), nullable=True))
    op.create_table(
        "model_invocations",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "organization_id", sa.String(36), sa.ForeignKey("organizations.id"), nullable=False
        ),
        sa.Column("actor_id", sa.String(36), nullable=False),
        sa.Column("analysis_run_id", sa.String(36), nullable=False),
        sa.Column("request_id", sa.String(36), nullable=False),
        sa.Column("request_hash", sa.String(64), nullable=False),
        sa.Column("task", sa.String(60), nullable=False),
        sa.Column("provider", sa.String(50), nullable=False),
        sa.Column("model", sa.String(100), nullable=False),
        sa.Column("returned_model", sa.String(100)),
        sa.Column("profile_id", sa.String(60), nullable=False),
        sa.Column("adapter_version", sa.String(30), nullable=False),
        sa.Column("prompt_version", sa.String(30), nullable=False),
        sa.Column("schema_version", sa.String(30), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("error_code", sa.String(40)),
        sa.Column("provider_request_id", sa.String(150)),
        sa.Column("usage", sa.JSON().with_variant(postgresql.JSONB(), "postgresql")),
        sa.Column("charged_tokens", sa.Integer(), nullable=False),
        sa.Column("request_sent", sa.Boolean(), nullable=True),
        sa.Column("latency_ms", sa.Integer()),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
        sa.UniqueConstraint("organization_id", "id"),
        sa.UniqueConstraint("organization_id", "actor_id", "request_id"),
        sa.ForeignKeyConstraint(
            ["organization_id", "actor_id"], ["memberships.organization_id", "memberships.id"]
        ),
        sa.ForeignKeyConstraint(
            ["organization_id", "analysis_run_id"],
            ["analysis_runs.organization_id", "analysis_runs.id"],
        ),
        sa.CheckConstraint("status IN ('pending', 'succeeded', 'failed', 'unknown')"),
        sa.CheckConstraint("charged_tokens >= 0"),
    )
    op.create_index(
        "ix_model_invocations_organization_id", "model_invocations", ["organization_id"]
    )
    op.create_index(
        "ix_model_invocations_tenant_time", "model_invocations", ["organization_id", "started_at"]
    )


def downgrade() -> None:
    # Development rollback only; deployed audit history must be preserved by restoring a backup.
    op.drop_table("model_invocations")
    with op.batch_alter_table("analysis_runs") as batch:
        batch.drop_column("failure_code")
