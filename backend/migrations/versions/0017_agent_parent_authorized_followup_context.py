"""Tenant-bound immediate parent for interactive read follow-ups."""

from contextlib import contextmanager

import sqlalchemy as sa
from alembic import op

revision = "0017_agent_parent"
down_revision = "0016_attention"
branch_labels = None
depends_on = None


@contextmanager
def alter():
    sqlite = op.get_bind().dialect.name == "sqlite"
    table = sa.Table("agent_runs", sa.MetaData(), autoload_with=op.get_bind()) if sqlite else None
    if sqlite:
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
                raise RuntimeError("agent_parent_foreign_key_violation")


def upgrade() -> None:
    with alter() as batch:
        batch.add_column(sa.Column("parent_run_id", sa.String(length=36), nullable=True))
        batch.create_foreign_key(
            "fk_agent_parent_run",
            "agent_runs",
            ["organization_id", "parent_run_id"],
            ["organization_id", "id"],
        )
        batch.create_check_constraint(
            "ck_agent_parent_read_only",
            "parent_run_id IS NULL OR (parent_run_id != id AND task = 'read' "
            "AND watch_grant_id IS NULL)",
        )


def downgrade() -> None:
    if (
        op.get_bind()
        .execute(sa.text("SELECT 1 FROM agent_runs WHERE parent_run_id IS NOT NULL LIMIT 1"))
        .first()
    ):
        raise RuntimeError("agent_followup_data_exists")
    with alter() as batch:
        batch.drop_constraint("ck_agent_parent_read_only", type_="check")
        batch.drop_constraint("fk_agent_parent_run", type_="foreignkey")
        batch.drop_column("parent_run_id")
