from collections.abc import Generator
from functools import lru_cache

from sqlalchemy import Engine, create_engine, event
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import settings


def make_engine(url: str) -> Engine:
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
