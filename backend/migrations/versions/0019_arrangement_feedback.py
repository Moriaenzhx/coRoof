"""Bind explicitly confirmed member feedback to a confirmed work arrangement."""

from contextlib import contextmanager

import sqlalchemy as sa
from alembic import op

revision = "0019_arrangement_feedback"
down_revision = "0018_agent_execution"
branch_labels = None
depends_on = None


@contextmanager
def alter(table_name):
    # SQLite recreates these tables, both of which already have incoming FKs.
    # Reflect explicitly to retain the existing anonymous state CHECK constraints.
    sqlite = op.get_bind().dialect.name == "sqlite"
    table = sa.Table(table_name, sa.MetaData(), autoload_with=op.get_bind()) if sqlite else None
    if sqlite:
        with op.get_context().autocommit_block():
            op.execute("PRAGMA foreign_keys=OFF")
    try:
        with op.batch_alter_table(table_name, copy_from=table) as batch:
            yield batch
    finally:
        if sqlite:
            with op.get_context().autocommit_block():
                op.execute("PRAGMA foreign_keys=ON")
            if op.get_bind().exec_driver_sql("PRAGMA foreign_key_check").first():
                raise RuntimeError("arrangement_migration_foreign_key_violation")


def upgrade() -> None:
    with alter("decisions") as batch:
        batch.create_unique_constraint(
            "uq_decision_work", ["organization_id", "work_item_id", "id"]
        )
    with alter("update_drafts") as batch:
        batch.add_column(sa.Column("decision_id", sa.String(36), nullable=True))
        batch.create_foreign_key(
            "fk_draft_arrangement",
            "decisions",
            ["organization_id", "work_item_id", "decision_id"],
            ["organization_id", "work_item_id", "id"],
        )
        batch.create_index("ix_draft_arrangement", ["organization_id", "decision_id"])


def downgrade() -> None:
    if (
        op.get_bind()
        .execute(sa.text("SELECT 1 FROM update_drafts WHERE decision_id IS NOT NULL LIMIT 1"))
        .first()
    ):
        raise RuntimeError("arrangement_feedback_data_exists")
    with alter("update_drafts") as batch:
        batch.drop_index("ix_draft_arrangement")
        batch.drop_constraint("fk_draft_arrangement", type_="foreignkey")
        batch.drop_column("decision_id")
    with alter("decisions") as batch:
        batch.drop_constraint("uq_decision_work", type_="unique")
