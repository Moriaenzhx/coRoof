"""confirmed decision experience and owner preferences"""

from contextlib import contextmanager

import sqlalchemy as sa
from alembic import op

revision = "0010_memory"
down_revision = "0009_knowledge"
branch_labels = None
depends_on = None


@contextmanager
def alter(table_name):
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
                raise RuntimeError("memory_migration_foreign_key_violation")


def upgrade() -> None:
    with alter("decision_outcomes") as batch_op:
        batch_op.create_unique_constraint(
            "uq_outcome_source", ["organization_id", "decision_id", "id"]
        )
    op.create_table(
        "memory_entries",
        sa.Column("kind", sa.String(length=20), nullable=False),
        sa.Column("actor_id", sa.String(length=36), nullable=False),
        sa.Column("decision_id", sa.String(length=36), nullable=True),
        sa.Column("outcome_id", sa.String(length=36), nullable=True),
        sa.Column("preference_key", sa.String(length=30), nullable=True),
        sa.Column("source_text", sa.Text(), nullable=False),
        sa.Column("source_hash", sa.String(length=64), nullable=False),
        sa.Column("source_version", sa.Integer(), nullable=True),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("applicability", sa.Text(), nullable=False),
        sa.Column("source_quote", sa.String(length=500), nullable=False),
        sa.Column("search_text", sa.Text(), nullable=False),
        sa.Column("state", sa.String(length=20), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("request_key", sa.String(length=36), nullable=False),
        sa.Column("request_hash", sa.String(length=64), nullable=False),
        sa.Column("confirmed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("organization_id", sa.String(length=36), nullable=False),
        sa.CheckConstraint(
            "(kind = 'experience' AND decision_id IS NOT NULL AND outcome_id IS NOT NULL "
            "AND source_version IS NOT NULL AND preference_key IS NULL) OR (kind = "
            "'preference' AND decision_id IS NULL AND outcome_id IS NULL AND "
            "preference_key IS NOT NULL AND preference_key IN ('focus', 'communication', "
            "'decision_rule', 'planning_goal'))",
            name="ck_memory_source",
        ),
        sa.CheckConstraint("kind IN ('experience', 'preference')", name="ck_memory_kind"),
        sa.CheckConstraint(
            "state IN ('proposed', 'confirmed', 'revoked', 'deleted')", name="ck_memory_state"
        ),
        sa.ForeignKeyConstraint(
            ["organization_id", "actor_id"],
            ["memberships.organization_id", "memberships.id"],
        ),
        sa.ForeignKeyConstraint(
            ["organization_id", "decision_id", "outcome_id"],
            [
                "decision_outcomes.organization_id",
                "decision_outcomes.decision_id",
                "decision_outcomes.id",
            ],
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("organization_id", "actor_id", "request_key"),
        sa.UniqueConstraint("organization_id", "id"),
    )
    with op.batch_alter_table("memory_entries", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_memory_entries_organization_id"), ["organization_id"], unique=False
        )
        batch_op.create_index(
            "uq_memory_active_preference",
            ["organization_id", "actor_id", "preference_key"],
            unique=True,
            postgresql_where=sa.text("kind = 'preference' AND state = 'confirmed'"),
            sqlite_where=sa.text("kind = 'preference' AND state = 'confirmed'"),
        )

    op.create_table(
        "memory_uses",
        sa.Column("entry_id", sa.String(length=36), nullable=False),
        sa.Column("run_id", sa.String(length=36), nullable=False),
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("organization_id", sa.String(length=36), nullable=False),
        sa.ForeignKeyConstraint(
            ["organization_id", "entry_id"],
            ["memory_entries.organization_id", "memory_entries.id"],
        ),
        sa.ForeignKeyConstraint(
            ["organization_id", "run_id"],
            ["agent_runs.organization_id", "agent_runs.id"],
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("organization_id", "entry_id", "run_id"),
        sa.UniqueConstraint("organization_id", "id"),
    )
    with op.batch_alter_table("memory_uses", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_memory_uses_organization_id"), ["organization_id"], unique=False
        )

    with alter("agent_runs") as batch_op:
        batch_op.add_column(sa.Column("memory_entry_id", sa.String(length=36), nullable=True))
        batch_op.add_column(sa.Column("memory_base_version", sa.Integer(), nullable=True))
        batch_op.create_foreign_key(
            "fk_agent_memory",
            "memory_entries",
            ["organization_id", "memory_entry_id"],
            ["organization_id", "id"],
        )
        batch_op.drop_constraint("ck_agent_task", type_="check")
        batch_op.create_check_constraint(
            "ck_agent_task", "task IN ('read', 'update_draft', 'memory_draft')"
        )
        batch_op.create_check_constraint(
            "ck_agent_memory_target",
            "(task != 'memory_draft' AND memory_entry_id IS NULL AND memory_base_version "
            "IS NULL) OR (task = 'memory_draft' AND memory_entry_id IS NOT NULL AND "
            "memory_base_version IS NOT NULL AND memory_base_version > 0)",
        )

    with alter("work_events") as batch_op:
        batch_op.add_column(sa.Column("memory_entry_id", sa.String(length=36), nullable=True))
        batch_op.create_foreign_key(
            "fk_work_event_memory",
            "memory_entries",
            ["organization_id", "memory_entry_id"],
            ["organization_id", "id"],
        )
        batch_op.drop_constraint("ck_work_event_target", type_="check")
        batch_op.create_check_constraint(
            "ck_work_event_target",
            "(CASE WHEN work_item_id IS NULL THEN 0 ELSE 1 END + CASE WHEN document_id "
            "IS NULL THEN 0 ELSE 1 END + CASE WHEN memory_entry_id IS NULL THEN 0 ELSE 1 "
            "END) = 1",
        )

    if op.get_bind().dialect.name == "postgresql":
        op.execute(
            "CREATE INDEX ix_memory_search ON memory_entries USING gin "
            "(to_tsvector('simple', search_text))"
        )
    else:
        op.execute("CREATE VIRTUAL TABLE memory_fts USING fts5(entry_id UNINDEXED, search_text)")
        op.execute(
            "CREATE TRIGGER memory_search_insert AFTER INSERT ON memory_entries BEGIN "
            "INSERT INTO memory_fts(entry_id, search_text) VALUES (new.id, "
            "new.search_text); END"
        )
        op.execute(
            "CREATE TRIGGER memory_search_delete AFTER DELETE ON memory_entries BEGIN "
            "DELETE FROM memory_fts WHERE entry_id = old.id; END"
        )
        op.execute(
            "CREATE TRIGGER memory_search_update AFTER UPDATE OF search_text ON "
            "memory_entries BEGIN DELETE FROM memory_fts WHERE entry_id = old.id; INSERT "
            "INTO memory_fts(entry_id, search_text) VALUES (new.id, new.search_text); "
            "END"
        )


def downgrade() -> None:
    if op.get_bind().execute(sa.text("SELECT 1 FROM memory_entries LIMIT 1")).first():
        raise RuntimeError("memory_downgrade_requires_explicit_data_migration")
    if op.get_bind().dialect.name == "sqlite":
        for name in ["memory_search_insert", "memory_search_delete", "memory_search_update"]:
            op.execute("DROP TRIGGER " + name)
        op.execute("DROP TABLE memory_fts")
    with alter("work_events") as batch_op:
        batch_op.drop_constraint("ck_work_event_target", type_="check")
        batch_op.drop_constraint("fk_work_event_memory", type_="foreignkey")
        batch_op.drop_column("memory_entry_id")
        batch_op.create_check_constraint(
            "ck_work_event_target", "(work_item_id IS NULL) != (document_id IS NULL)"
        )

    with alter("agent_runs") as batch_op:
        batch_op.drop_constraint("ck_agent_memory_target", type_="check")
        batch_op.drop_constraint("ck_agent_task", type_="check")
        batch_op.create_check_constraint("ck_agent_task", "task IN ('read', 'update_draft')")
        batch_op.drop_constraint("fk_agent_memory", type_="foreignkey")
        batch_op.drop_column("memory_base_version")
        batch_op.drop_column("memory_entry_id")

    with op.batch_alter_table("memory_uses", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_memory_uses_organization_id"))

    op.drop_table("memory_uses")
    with op.batch_alter_table("memory_entries", schema=None) as batch_op:
        batch_op.drop_index(
            "uq_memory_active_preference",
            postgresql_where=sa.text("kind = 'preference' AND state = 'confirmed'"),
            sqlite_where=sa.text("kind = 'preference' AND state = 'confirmed'"),
        )
        batch_op.drop_index(batch_op.f("ix_memory_entries_organization_id"))

    op.drop_table("memory_entries")
    with alter("decision_outcomes") as batch_op:
        batch_op.drop_constraint("uq_outcome_source", type_="unique")
