"""Bind generated update drafts to their authorized agent run."""

from contextlib import contextmanager

import sqlalchemy as sa
from alembic import op

revision = "0007_agent_drafts"
down_revision = "0006_langgraph"
branch_labels = None
depends_on = None


@contextmanager
def alter_run():
    # SQLite requires a table copy for a composite FK. Preserve its existing checks
    # and child rows; PostgreSQL performs ordinary transactional ALTER TABLE.
    sqlite = op.get_bind().dialect.name == "sqlite"
    table = None
    if sqlite:
        table = sa.Table("agent_runs", sa.MetaData(), autoload_with=op.get_bind())
        for constraint in table.constraints:
            if isinstance(constraint, sa.CheckConstraint) and constraint.name is None:
                constraint.name = (
                    "ck_agent_run_steps"
                    if "step_count" in str(constraint.sqltext)
                    else "ck_agent_run_state"
                )
        with op.get_context().autocommit_block():
            op.execute("PRAGMA foreign_keys=OFF")
    try:
        with op.batch_alter_table("agent_runs", copy_from=table) as batch:
            yield batch
    finally:
        if sqlite:
            with op.get_context().autocommit_block():
                op.execute("PRAGMA foreign_keys=ON")
            if op.get_bind().exec_driver_sql("PRAGMA foreign_key_check").first():
                raise RuntimeError("agent_draft_migration_foreign_key_violation")


def upgrade() -> None:
    with alter_run() as batch:
        batch.add_column(sa.Column("task", sa.String(20), nullable=False, server_default="read"))
        batch.add_column(sa.Column("draft_id", sa.String(36), nullable=True))
        batch.create_foreign_key(
            "fk_agent_run_draft",
            "update_drafts",
            ["organization_id", "draft_id"],
            ["organization_id", "id"],
        )
        batch.create_check_constraint("ck_agent_task", "task IN ('read', 'update_draft')")


def downgrade() -> None:
    with alter_run() as batch:
        batch.drop_constraint("ck_agent_task", type_="check")
        batch.drop_constraint("fk_agent_run_draft", type_="foreignkey")
        batch.drop_column("draft_id")
        batch.drop_column("task")
