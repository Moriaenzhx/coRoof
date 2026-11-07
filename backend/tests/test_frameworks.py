"""Acceptance of maintained integrations and tenant-bound official checkpointers."""

import json
from uuid import uuid4

import httpx
import pytest
from langchain_core.messages import AIMessage
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from test_agent_read import advance, create, model
from test_ai_management import gateway, model_request, native_response
from test_model_gateway import mock_transport

from app.infrastructure.db import session_factory
from app.modules.agent.checkpoints import saver
from app.modules.intelligence.schemas import ModelAnswer
from app.modules.model_gateway.adapter import parse_message
from app.modules.model_gateway.contracts import ModelFailure


def test_official_checkpoints_survive_new_connection_and_reject_foreign_run(loop, monkeypatch):
    boss, _, org, _, _, _ = loop
    calls = model(monkeypatch)
    row = advance(boss, create(boss))
    step = row["steps"][0]
    thread_id = f"{org['id']}:{row['id']}:{step['id']}"
    with saver() as store:
        checkpoint = store.get_tuple({"configurable": {"thread_id": thread_id}})
        assert checkpoint and checkpoint.checkpoint["channel_values"]["committed"]
        encoded = json.dumps(checkpoint.checkpoint, default=str)
        assert "fixture-not-real" not in encoded and "hidden-reasoning" not in encoded
    # Replay does not run the framework/model a second time.
    assert boss.get(f"/agent/runs/{row['id']}")["state"] == "ready" and len(calls) == 1
    with session_factory()() as db:
        assert db.execute(
            text("SELECT organization_id, run_id FROM checkpoints LIMIT 1")
        ).first() == (org["id"], row["id"])
        with pytest.raises(IntegrityError):
            db.execute(
                text("UPDATE checkpoints SET thread_id = :value"),
                {"value": f"{uuid4()}:{row['id']}:{step['id']}"},
            )
            db.flush()
        db.rollback()


@pytest.mark.parametrize("provider", ["openai", "anthropic", "gemini", "deepseek", "bailian"])
def test_framework_does_not_retry_or_send_to_inherited_tracing_destination(monkeypatch, provider):
    monkeypatch.setenv("LANGSMITH_TRACING", "true")
    monkeypatch.setenv("LANGCHAIN_TRACING_V2", "true")
    monkeypatch.setenv("LANGSMITH_API_KEY", "synthetic-trace-secret")
    calls = []

    def handle(req):
        calls.append(req)
        return httpx.Response(429, text="fixture-not-real must never surface")

    mock_transport(monkeypatch, handle)
    gw = gateway(provider)
    with pytest.raises(ModelFailure, match="rate_limited") as exc:
        gw.generate(gw.prepare(model_request(), ModelAnswer), ModelAnswer)
    assert len(calls) == 1 and exc.value.sent
    assert "fixture-not-real" not in str(exc.value)


@pytest.mark.parametrize("finish,expected", [("MAX_TOKENS", "truncated"), ("SAFETY", "refused")])
def test_gemini_finish_policy_uses_langchain_metadata(monkeypatch, finish, expected):
    body = native_response("gemini")
    body["candidates"][0]["finishReason"] = finish
    mock_transport(monkeypatch, lambda req: httpx.Response(200, json=body))
    gw = gateway("gemini")
    with pytest.raises(ModelFailure, match=expected):
        gw.generate(gw.prepare(model_request(), ModelAnswer), ModelAnswer)


def test_framework_generated_message_id_is_not_a_provider_request_id():
    result = parse_message(
        AIMessage(content="{}", id="lc_run-fixture", response_metadata={"finish_reason": "stop"}),
        "fixture-key",
        None,
    )
    assert result.provider_request_id is None and result.usage.input_tokens is None
