from alembic import context

from app.core.config import settings
from app.infrastructure.db import make_engine
from app.infrastructure.models import Base

if context.is_offline_mode():
    context.configure(
        url=settings().database_url,
        target_metadata=Base.metadata,
        literal_binds=True,
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()
else:
    engine = make_engine(settings().database_url)
    with engine.connect() as connection:
        context.configure(connection=connection, target_metadata=Base.metadata, compare_type=True)
        with context.begin_transaction():
            context.run_migrations()
