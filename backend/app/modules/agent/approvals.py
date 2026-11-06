"""LangGraph owns waiting/recovery; existing domain commands own all effects."""

from collections.abc import Callable, Iterator
from contextlib import contextmanager
from threading import RLock
from typing import Any, TypedDict

import psycopg
from langchain_core.runnables import RunnableConfig, RunnableLambda
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.checkpoint.postgres import PostgresSaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command, interrupt
from langsmith import tracing_context
from psycopg.rows import tuple_row

from app.core.errors import fail
from app.infrastructure.models import AgentRun
from app.modules.agent.checkpoints import saver

_sqlite_lock = RLock()  # Auxiliary tests only; concurrency acceptance uses PostgreSQL.


class ReviewState(TypedDict, total=False):
    target: str
    revision: int
    confirmation_hash: str
    committed: bool


def thread_id(run: AgentRun, kind: str, target: str, revision: int) -> str:
    return f"{run.organization_id}:{run.id}:review:{kind}:{target}:{revision}"


@contextmanager
def locked_saver(thread: str) -> Iterator[BaseCheckpointSaver[Any]]:
    # Serialize the graph checkpoint as well as the command across API processes.
    # This session lock survives the domain transaction's commit and dies on crash.
    with saver() as store:
        if isinstance(store, PostgresSaver):
            assert isinstance(store.conn, psycopg.Connection)
            with store.conn.cursor(row_factory=tuple_row) as cursor:
                cursor.execute("SELECT pg_try_advisory_lock(hashtextextended(%s, 0))", (thread,))
                acquired = cursor.fetchone()
                if not acquired or not acquired[0]:
                    fail("confirmation_busy", "正在处理确认，请刷新后重试", 409)
            try:
                yield store
            finally:
                with store.conn.cursor(row_factory=tuple_row) as cursor:
                    cursor.execute("SELECT pg_advisory_unlock(hashtextextended(%s, 0))", (thread,))
        else:
            with _sqlite_lock:
                yield store


def review[T](
    run: AgentRun,
    kind: str,
    target: str,
    revision: int,
    *,
    fingerprint: str | None = None,
    apply: Callable[[], T] | None = None,
) -> T | None:
    """Only authenticated, explicit confirmation endpoints supply apply/fingerprint.

    Never replay an LLM call here. On a crash after the business commit, the existing
    idempotent command returns its original receipt when the user retries confirmation.
    """
    receipt: list[T] = []

    def await_author(state: ReviewState) -> ReviewState:
        approved_hash = interrupt({"target": state["target"], "revision": state["revision"]})
        if fingerprint is None or approved_hash != fingerprint:
            fail("confirmation_conflict", "确认内容已变化，请重新核对", 409)
        assert fingerprint is not None
        return {"confirmation_hash": fingerprint}

    def commit(state: ReviewState) -> ReviewState:
        if apply is None or state.get("confirmation_hash") != fingerprint:
            fail("confirmation_required", "需要作者明确确认", 409)
        assert apply is not None
        receipt.append(apply())  # Rechecks authority/version and commits event + projection.
        return {"committed": True}

    builder = StateGraph(ReviewState)
    builder.add_node("await_author", RunnableLambda(await_author))
    builder.add_node("commit", RunnableLambda(commit))
    builder.add_edge(START, "await_author")
    builder.add_edge("await_author", "commit")
    builder.add_edge("commit", END)
    thread = thread_id(run, kind, target, revision)
    config: RunnableConfig = {"configurable": {"thread_id": thread}, "recursion_limit": 4}
    with tracing_context(enabled=False), locked_saver(thread) as store:
        graph = builder.compile(checkpointer=store)
        state = graph.get_state(config)
        if not state.values:
            graph.invoke({"target": target, "revision": revision}, config, durability="sync")
            state = graph.get_state(config)
        if fingerprint is None:
            return None
        if state.values.get("confirmation_hash") not in {None, fingerprint}:
            fail("confirmation_conflict", "确认内容已变化，请重新核对", 409)
        if state.values.get("committed"):
            # Domain replay still verifies the current caller and exact request.
            assert apply is not None
            return apply()
        if state.next == ("commit",):
            graph.invoke(None, config, durability="sync")
        else:
            graph.invoke(Command(resume=fingerprint), config, durability="sync")
    if not receipt:
        fail("confirmation_incomplete", "确认结果尚未取得，请刷新后核对", 409)
    return receipt[0]


def wait_for_review(run: AgentRun, kind: str, target: str, revision: int) -> None:
    review(run, kind, target, revision)
