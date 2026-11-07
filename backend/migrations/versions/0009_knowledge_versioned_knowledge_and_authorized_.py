"""versioned knowledge and authorized search"""

from contextlib import contextmanager

import sqlalchemy as sa
from alembic import op

revision = "0009_knowledge"
down_revision = "0008_connectors"
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
                raise RuntimeError("knowledge_migration_foreign_key_violation")


def upgrade() -> None:
    op.create_table(
        "knowledge_documents",
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("author_id", sa.String(length=36), nullable=False),
        sa.Column("visibility", sa.String(length=20), nullable=False),
        sa.Column("department_id", sa.String(length=36), nullable=True),
        sa.Column("state", sa.String(length=20), nullable=False),
        sa.Column("published_id", sa.String(length=36), nullable=True),
        sa.Column("draft_id", sa.String(length=36), nullable=True),
        sa.Column("revision_count", sa.Integer(), nullable=False),
        sa.Column("access_version", sa.Integer(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("request_key", sa.String(length=36), nullable=False),
        sa.Column("request_hash", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("organization_id", sa.String(length=36), nullable=False),
        sa.CheckConstraint(
            "state IN ('draft', 'published', 'withdrawn', 'deleted')", name="ck_knowledge_state"
        ),
        sa.CheckConstraint(
            "visibility != 'department' OR department_id IS NOT NULL",
            name="ck_knowledge_department",
        ),
        sa.CheckConstraint(
            "visibility IN ('private', 'department', 'organization', 'members')",
            name="ck_knowledge_visibility",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id", "author_id"],
            ["memberships.organization_id", "memberships.id"],
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
        sa.UniqueConstraint("organization_id", "author_id", "request_key"),
        sa.UniqueConstraint("organization_id", "id"),
    )
    with op.batch_alter_table("knowledge_documents", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_knowledge_documents_organization_id"), ["organization_id"], unique=False
        )

    op.create_table(
        "knowledge_readers",
        sa.Column("document_id", sa.String(length=36), nullable=False),
        sa.Column("membership_id", sa.String(length=36), nullable=False),
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("organization_id", sa.String(length=36), nullable=False),
        sa.ForeignKeyConstraint(
            ["organization_id", "document_id"],
            ["knowledge_documents.organization_id", "knowledge_documents.id"],
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
        sa.UniqueConstraint("organization_id", "document_id", "membership_id"),
        sa.UniqueConstraint("organization_id", "id"),
    )
    with op.batch_alter_table("knowledge_readers", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_knowledge_readers_organization_id"), ["organization_id"], unique=False
        )

    op.create_table(
        "knowledge_revisions",
        sa.Column("document_id", sa.String(length=36), nullable=False),
        sa.Column("author_id", sa.String(length=36), nullable=False),
        sa.Column("number", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("content", sa.Text(), nullable=True),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column("file_name", sa.String(length=180), nullable=True),
        sa.Column("file_bytes", sa.LargeBinary(), nullable=True),
        sa.Column("file_hash", sa.String(length=64), nullable=True),
        sa.Column("edited_extraction", sa.Boolean(), nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("organization_id", sa.String(length=36), nullable=False),
        sa.ForeignKeyConstraint(
            ["organization_id", "author_id"],
            ["memberships.organization_id", "memberships.id"],
        ),
        sa.ForeignKeyConstraint(
            ["organization_id", "document_id"],
            ["knowledge_documents.organization_id", "knowledge_documents.id"],
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("organization_id", "document_id", "id"),
        sa.UniqueConstraint("organization_id", "document_id", "number"),
        sa.UniqueConstraint("organization_id", "id"),
    )
    with op.batch_alter_table("knowledge_revisions", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_knowledge_revisions_organization_id"), ["organization_id"], unique=False
        )

    op.create_table(
        "knowledge_chunks",
        sa.Column("document_id", sa.String(length=36), nullable=False),
        sa.Column("revision_id", sa.String(length=36), nullable=False),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("start_offset", sa.Integer(), nullable=False),
        sa.Column("end_offset", sa.Integer(), nullable=False),
        sa.Column("search_text", sa.Text(), nullable=False),
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("organization_id", sa.String(length=36), nullable=False),
        sa.ForeignKeyConstraint(
            ["organization_id", "document_id", "revision_id"],
            [
                "knowledge_revisions.organization_id",
                "knowledge_revisions.document_id",
                "knowledge_revisions.id",
            ],
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("organization_id", "id"),
        sa.UniqueConstraint("organization_id", "revision_id", "ordinal"),
    )
    with op.batch_alter_table("knowledge_chunks", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_knowledge_chunks_organization_id"), ["organization_id"], unique=False
        )

    op.create_table(
        "knowledge_uses",
        sa.Column("document_id", sa.String(length=36), nullable=False),
        sa.Column("run_id", sa.String(length=36), nullable=False),
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("organization_id", sa.String(length=36), nullable=False),
        sa.ForeignKeyConstraint(
            ["organization_id", "document_id"],
            ["knowledge_documents.organization_id", "knowledge_documents.id"],
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
        sa.UniqueConstraint("organization_id", "document_id", "run_id"),
        sa.UniqueConstraint("organization_id", "id"),
    )
    with op.batch_alter_table("knowledge_uses", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_knowledge_uses_organization_id"), ["organization_id"], unique=False
        )

    with alter("knowledge_documents") as batch_op:
        for column, name in [
            ("published_id", "fk_knowledge_published"),
            ("draft_id", "fk_knowledge_draft"),
        ]:
            batch_op.create_foreign_key(
                name,
                "knowledge_revisions",
                ["organization_id", "id", column],
                ["organization_id", "document_id", "id"],
            )

    with alter("work_events") as batch_op:
        batch_op.add_column(sa.Column("document_id", sa.String(length=36), nullable=True))
        batch_op.alter_column("work_item_id", existing_type=sa.VARCHAR(length=36), nullable=True)
        batch_op.create_foreign_key(
            "fk_work_event_document",
            "knowledge_documents",
            ["organization_id", "document_id"],
            ["organization_id", "id"],
        )
        batch_op.create_check_constraint(
            "ck_work_event_target", "(work_item_id IS NULL) != (document_id IS NULL)"
        )

    if op.get_bind().dialect.name == "postgresql":
        op.execute(
            "CREATE INDEX ix_knowledge_search ON knowledge_chunks "
            "USING gin (to_tsvector('simple', search_text))"
        )
    else:
        op.execute("CREATE VIRTUAL TABLE knowledge_fts USING fts5(chunk_id UNINDEXED, search_text)")
        op.execute(
            "CREATE TRIGGER knowledge_search_insert AFTER INSERT ON knowledge_chunks BEGIN "
            "INSERT INTO knowledge_fts(chunk_id, search_text) VALUES (new.id, new.search_text); END"
        )
        op.execute(
            "CREATE TRIGGER knowledge_search_delete AFTER DELETE ON knowledge_chunks BEGIN "
            "DELETE FROM knowledge_fts WHERE chunk_id = old.id; END"
        )
        op.execute(
            "CREATE TRIGGER knowledge_search_update AFTER UPDATE OF search_text "
            "ON knowledge_chunks "
            "BEGIN DELETE FROM knowledge_fts WHERE chunk_id = old.id; "
            "INSERT INTO knowledge_fts(chunk_id, search_text) VALUES (new.id, new.search_text); END"
        )


def downgrade() -> None:
    if op.get_bind().execute(sa.text("SELECT 1 FROM knowledge_documents LIMIT 1")).first():
        raise RuntimeError("knowledge_downgrade_requires_explicit_data_migration")
    if op.get_bind().dialect.name == "sqlite":
        for name in [
            "knowledge_search_insert",
            "knowledge_search_delete",
            "knowledge_search_update",
        ]:
            op.execute("DROP TRIGGER " + name)
        op.execute("DROP TABLE knowledge_fts")
    with alter("work_events") as batch_op:
        batch_op.drop_constraint("ck_work_event_target", type_="check")
        batch_op.drop_constraint("fk_work_event_document", type_="foreignkey")
        batch_op.alter_column("work_item_id", existing_type=sa.VARCHAR(length=36), nullable=False)
        batch_op.drop_column("document_id")

    with alter("knowledge_documents") as batch_op:
        batch_op.drop_constraint("fk_knowledge_published", type_="foreignkey")
        batch_op.drop_constraint("fk_knowledge_draft", type_="foreignkey")

    with op.batch_alter_table("knowledge_uses", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_knowledge_uses_organization_id"))

    op.drop_table("knowledge_uses")
    with op.batch_alter_table("knowledge_chunks", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_knowledge_chunks_organization_id"))

    op.drop_table("knowledge_chunks")
    with op.batch_alter_table("knowledge_revisions", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_knowledge_revisions_organization_id"))

    op.drop_table("knowledge_revisions")
    with op.batch_alter_table("knowledge_readers", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_knowledge_readers_organization_id"))

    op.drop_table("knowledge_readers")
    with op.batch_alter_table("knowledge_documents", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_knowledge_documents_organization_id"))

    op.drop_table("knowledge_documents")
