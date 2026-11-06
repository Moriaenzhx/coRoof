"""Official LangGraph checkpoint layouts with tenant/run foreign keys.

Pinned to postgres saver 3.2 / sqlite saver 3.1. Alembic owns setup;
runtime never calls saver.setup(). No application records are rewritten.
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "0006_langgraph"
down_revision = "0005_agent_read"
branch_labels = None
depends_on = None


def tenant_columns() -> list[sa.Column]:  # type: ignore[type-arg]
    return [
        sa.Column(
            "organization_id",
            sa.String(36),
            sa.Computed("substr(thread_id, 1, 36)", persisted=True),
        ),
        sa.Column(
            "run_id", sa.String(36), sa.Computed("substr(thread_id, 38, 36)", persisted=True)
        ),
    ]


def run_fk() -> sa.ForeignKeyConstraint:
    return sa.ForeignKeyConstraint(
        ["organization_id", "run_id"],
        ["agent_runs.organization_id", "agent_runs.id"],
        ondelete="CASCADE",
    )


def upgrade() -> None:
    postgres = op.get_bind().dialect.name == "postgresql"
    op.create_table(
        "checkpoints",
        sa.Column("thread_id", sa.Text(), primary_key=True),
        sa.Column("checkpoint_ns", sa.Text(), primary_key=True, server_default=""),
        sa.Column("checkpoint_id", sa.Text(), primary_key=True),
        sa.Column("parent_checkpoint_id", sa.Text()),
        sa.Column("type", sa.Text()),
        sa.Column("checkpoint", JSONB() if postgres else sa.LargeBinary(), nullable=False),
        sa.Column("metadata", JSONB() if postgres else sa.LargeBinary(), nullable=False),
        *tenant_columns(),
        run_fk(),
    )
    writes = "checkpoint_writes" if postgres else "writes"
    op.create_table(
        writes,
        sa.Column("thread_id", sa.Text(), primary_key=True),
        sa.Column("checkpoint_ns", sa.Text(), primary_key=True, server_default=""),
        sa.Column("checkpoint_id", sa.Text(), primary_key=True),
        sa.Column("task_id", sa.Text(), primary_key=True),
        sa.Column("idx", sa.Integer(), primary_key=True),
        sa.Column("task_path", sa.Text(), nullable=False, server_default=""),
        sa.Column("channel", sa.Text(), nullable=False),
        sa.Column("type", sa.Text()),
        sa.Column("blob" if postgres else "value", sa.LargeBinary(), nullable=False),
        *tenant_columns(),
        run_fk(),
    )
    tables = ["checkpoints", writes]
    if postgres:
        op.create_table(
            "checkpoint_blobs",
            sa.Column("thread_id", sa.Text(), primary_key=True),
            sa.Column("checkpoint_ns", sa.Text(), primary_key=True, server_default=""),
            sa.Column("channel", sa.Text(), primary_key=True),
            sa.Column("version", sa.Text(), primary_key=True),
            sa.Column("type", sa.Text(), nullable=False),
            sa.Column("blob", sa.LargeBinary()),
            *tenant_columns(),
            run_fk(),
        )
        tables.append("checkpoint_blobs")
    for table in tables:
        op.create_index(f"{table}_thread_id_idx", table, ["thread_id"])


def downgrade() -> None:
    if op.get_bind().dialect.name == "postgresql":
        op.drop_table("checkpoint_blobs")
        op.drop_table("checkpoint_writes")
    else:
        op.drop_table("writes")
    op.drop_table("checkpoints")
