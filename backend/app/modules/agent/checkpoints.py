"""Use LangGraph's official savers on Alembic-managed tables."""

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

import psycopg
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.checkpoint.postgres import PostgresSaver
from langgraph.checkpoint.sqlite import SqliteSaver
from sqlalchemy.engine import make_url

from app.core.config import settings


@contextmanager
def saver() -> Iterator[BaseCheckpointSaver[Any]]:
    url = make_url(settings().database_url)
    if url.get_backend_name() == "sqlite":
        with sqlite3.connect(str(url.database), check_same_thread=False) as connection:
            connection.execute("PRAGMA foreign_keys=ON")
            store = SqliteSaver(connection)
            store.is_setup = True  # Tables must already exist through Alembic.
            yield store
        connection.close()
    else:
        # Preserve Unix socket and isolated test-schema connection options.
        args: dict[str, Any] = dict(url.query)
        if url.database:
            args["dbname"] = url.database
        for key, value in (
            ("host", url.host),
            ("port", url.port),
            ("user", url.username),
            ("password", url.password),
        ):
            if value is not None:
                args[key] = value
        with psycopg.connect(**args, autocommit=True, prepare_threshold=0) as pg_connection:
            yield PostgresSaver(pg_connection)
