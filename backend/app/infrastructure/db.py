from collections.abc import Generator
from functools import lru_cache

from sqlalchemy import Engine, create_engine, event
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import settings


def make_engine(url: str) -> Engine:
    # API, Worker and command-line entry points share the same metadata registry.
    # Composite references must resolve even when an entry point imports only a
    # subset of the business services. This registers models, never creates tables.
    from app.modules.agent import models as agent_models  # noqa: F401
    from app.modules.connectors import models as connector_models  # noqa: F401
    from app.modules.identity import models as identity_models  # noqa: F401
    from app.modules.knowledge import models as knowledge_models  # noqa: F401
    from app.modules.memory import models as memory_models  # noqa: F401
    from app.modules.watch import models as watch_models  # noqa: F401

    engine = create_engine(url, pool_pre_ping=True)
    if url.startswith("sqlite"):

        @event.listens_for(engine, "connect")
        def enable_foreign_keys(connection: object, _: object) -> None:
            connection.execute("PRAGMA foreign_keys=ON")  # type: ignore[attr-defined]

    return engine


@lru_cache
def session_factory() -> sessionmaker[Session]:
    return sessionmaker(make_engine(settings().database_url), expire_on_commit=False)


def get_db() -> Generator[Session, None, None]:
    with session_factory()() as session:
        yield session
