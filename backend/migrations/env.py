from alembic import context

from app.core.config import settings
from app.infrastructure.db import make_engine
from app.infrastructure.models import Base
from app.modules.agent import models as agent_models  # noqa: F401
from app.modules.connectors import models as connector_models  # noqa: F401
from app.modules.identity import models as identity_models  # noqa: F401
from app.modules.knowledge import models as knowledge_models  # noqa: F401
from app.modules.memory import models as memory_models  # noqa: F401
from app.modules.watch import models as watch_models  # noqa: F401


# Framework-owned schemas are versioned in Alembic, not ORM entities.
# Their tenant FKs and round trips are covered by integration tests.
def include_object(obj, name, type_, reflected, compare_to):
    if reflected and (
        (type_ == "table" and name.startswith(("knowledge_fts", "memory_fts")))
        or (type_ == "index" and name in {"ix_knowledge_search", "ix_memory_search"})
    ):
        return False
    return not (
        type_ == "table"
        and reflected
        and name in {"checkpoints", "checkpoint_blobs", "checkpoint_writes", "writes"}
    )


if context.is_offline_mode():
    context.configure(
        url=settings().database_url,
        target_metadata=Base.metadata,
        include_object=include_object,
        literal_binds=True,
        compare_type=True,
        render_as_batch=True,
    )
    with context.begin_transaction():
        context.run_migrations()
else:
    engine = make_engine(settings().database_url)
    with engine.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=Base.metadata,
            include_object=include_object,
            compare_type=True,
            render_as_batch=True,
        )
        with context.begin_transaction():
            context.run_migrations()
    engine.dispose()
