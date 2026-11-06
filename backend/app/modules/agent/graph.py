"""Read-agent graph. Business authorization stays inside each domain node."""

from collections.abc import Callable
from typing import Any, TypedDict

from langchain_core.runnables import RunnableConfig, RunnableLambda
from langgraph.graph import END, START, StateGraph
from langsmith import tracing_context

from app.modules.agent.checkpoints import saver
from app.modules.model_gateway.contracts import ErrorCode


class RoundState(TypedDict, total=False):
    run_id: str
    proposal: dict[str, Any] | None
    failure: ErrorCode | None
    sent: bool
    usage: dict[str, Any]
    provider_request_id: str | None
    returned_model: str | None
    latency_ms: int
    committed: bool


def execute_round(
    organization_id: str,
    run_id: str,
    step_id: str,
    generate: Callable[[RoundState], RoundState],
    apply: Callable[[RoundState], RoundState],
) -> None:
    builder = StateGraph(RoundState)
    builder.add_node("model", RunnableLambda(generate))
    builder.add_node("authorized_read", RunnableLambda(apply))
    builder.add_node("validated_answer", RunnableLambda(apply))
    builder.add_node("prepare_draft", RunnableLambda(apply))
    builder.add_node("prepare_memory", RunnableLambda(apply))
    builder.add_node("record_failure", RunnableLambda(apply))
    builder.add_edge(START, "model")

    def route(state: RoundState) -> str:
        if state.get("failure"):
            return "record_failure"
        if "memory" in (state.get("proposal") or {}):
            return "prepare_memory"
        if "summary" in (state.get("proposal") or {}):
            return "prepare_draft"
        return (
            "authorized_read"
            if (state.get("proposal") or {}).get("kind") == "read"
            else "validated_answer"
        )

    builder.add_conditional_edges(
        "model",
        route,
        [
            "authorized_read",
            "validated_answer",
            "prepare_draft",
            "prepare_memory",
            "record_failure",
        ],
    )
    for node in (
        "authorized_read",
        "validated_answer",
        "prepare_draft",
        "prepare_memory",
        "record_failure",
    ):
        builder.add_edge(node, END)
    # A round's identity is server generated. Late responses cannot write a newer round.
    config: RunnableConfig = {
        "configurable": {"thread_id": f"{organization_id}:{run_id}:{step_id}"},
        "recursion_limit": 6,
    }
    with tracing_context(enabled=False), saver() as store:
        graph = builder.compile(checkpointer=store)
        graph.invoke({"run_id": run_id}, config=config, durability="sync")
