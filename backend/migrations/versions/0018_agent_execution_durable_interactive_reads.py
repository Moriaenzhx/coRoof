"""Durable transport intent for interactive reads; existing tasks remain manual."""

import sqlalchemy as sa
from alembic import op

revision = "0018_agent_execution"
down_revision = "0017_agent_parent"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "agent_executions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "organization_id", sa.String(36), sa.ForeignKey("organizations.id"), nullable=False
        ),
        sa.Column("run_id", sa.String(36), nullable=False),
        sa.Column("state", sa.String(20), nullable=False),
        sa.Column("generation", sa.Integer(), nullable=False),
        sa.Column("lease_token", sa.String(36), nullable=True),
        sa.Column("lease_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("available_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("organization_id", "id"),
        sa.UniqueConstraint("organization_id", "run_id"),
        sa.ForeignKeyConstraint(
            ["organization_id", "run_id"], ["agent_runs.organization_id", "agent_runs.id"]
        ),
        sa.CheckConstraint(
            "state IN ('queued', 'running', 'stopped')", name="ck_agent_execution_state"
        ),
        sa.CheckConstraint("generation >= 1", name="ck_agent_execution_generation"),
        sa.CheckConstraint(
            "(state = 'running' AND lease_token IS NOT NULL AND lease_until IS NOT NULL) "
            "OR (state != 'running' AND lease_token IS NULL AND lease_until IS NULL)",
            name="ck_agent_execution_lease",
        ),
    )
    op.create_index("ix_agent_executions_organization_id", "agent_executions", ["organization_id"])
    op.create_index("ix_agent_execution_dispatch", "agent_executions", ["state", "available_at"])
    op.create_index("ix_agent_execution_recovery", "agent_executions", ["state", "lease_until"])


def downgrade() -> None:
    if op.get_bind().execute(sa.text("SELECT 1 FROM agent_executions LIMIT 1")).first():
        raise RuntimeError("agent_execution_data_exists")
    op.drop_table("agent_executions")
