import json
from uuid import uuid4

import httpx
import pytest
from conftest import API
from cryptography.fernet import Fernet
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.core.config import Settings, settings
from app.infrastructure.db import session_factory
from app.infrastructure.models import AIConnection, AISettings, Membership, ModelInvocation
from app.modules.ai_admin.service import unseal
from app.modules.intelligence.schemas import ModelAnswer
from app.modules.model_gateway import adapter
from app.modules.model_gateway.catalog import PROVIDERS
from app.modules.model_gateway.contracts import Message, ModelFailure, ModelRequest
from app.modules.model_gateway.gateway import ModelGateway


def gateway(provider):
    preset = PROVIDERS[provider]
    return ModelGateway(
        Settings(
            _env_file=None,
            ai_provider=provider,
            ai_base_url=preset.base_url,
            ai_model="model-fixture",
            ai_api_key="fixture-not-real",
            ai_model_verified=True,
            ai_managed_connection=True,
            ai_output_mode=preset.output_mode,
        )
    )


def model_request():
    return ModelRequest(
        prompt_version="probe-v1", messages=(Message(role="user", content="返回 JSON"),)
    )


def native_response(provider):
    content = '{"assessments": []}'
    if provider == "openai":
        return {
            "id": "resp_fixture",
            "model": "model-fixture",
            "object": "response",
            "error": None,
            "status": "completed",
            "output": [
                {"id": "rs_fixture", "type": "reasoning", "summary": []},
                {
                    "id": "msg_fixture",
                    "status": "completed",
                    "type": "message",
                    "role": "assistant",
                    "content": [{"type": "output_text", "text": content, "annotations": []}],
                },
            ],
            "usage": {"input_tokens": 10, "output_tokens": 5, "total_tokens": 15},
        }
    if provider == "anthropic":
        return {
            "id": "msg_fixture",
            "model": "model-fixture",
            "type": "message",
            "role": "assistant",
            "stop_reason": "end_turn",
            "content": [
                {"type": "thinking", "thinking": "do-not-store", "signature": "fixture"},
                {"type": "text", "text": content},
            ],
            "usage": {
                "input_tokens": 7,
                "cache_read_input_tokens": 3,
                "cache_creation_input_tokens": 0,
                "output_tokens": 5,
            },
        }
    if provider == "gemini":
        return {
            "candidates": [
                {
                    "finishReason": "STOP",
                    "content": {
                        "parts": [{"text": "do-not-store", "thought": True}, {"text": content}]
                    },
                }
            ],
            "usageMetadata": {
                "promptTokenCount": 10,
                "candidatesTokenCount": 3,
                "thoughtsTokenCount": 2,
            },
        }
    return {
        "choices": [
            {"finish_reason": "stop", "message": {"role": "assistant", "content": content}}
        ],
        "usage": {"prompt_tokens": 10, "completion_tokens": 5},
    }


@pytest.mark.parametrize("provider", ["openai", "anthropic", "gemini", "deepseek", "bailian"])
def test_provider_protocols_and_normalized_usage(monkeypatch, provider):
    def handler(req):
        body = json.loads(req.content)
        assert "fixture-not-real" not in req.url.query.decode()
        if provider == "openai":
            assert req.url.path == "/v1/responses" and body["store"] is False
            assert body["text"]["format"]["strict"] is True
        elif provider == "anthropic":
            assert req.url.path == "/v1/messages" and req.headers["x-api-key"] == "fixture-not-real"
            assert body["output_config"]["format"]["type"] == "json_schema"
            schema = body["output_config"]["format"]["schema"]
            assert "maxItems" not in schema["properties"]["assessments"]
            assert "maxLength" not in schema["$defs"]["ModelAssessment"]["properties"]["quote"]
            assert (
                "maxLength"
                in schema["$defs"]["ModelAssessment"]["properties"]["quote"]["description"]
            )
            assert all(m["role"] != "system" for m in body["messages"])
        elif provider == "gemini":
            assert (
                req.url.path.endswith(":generateContent")
                and req.headers["x-goog-api-key"] == "fixture-not-real"
            )
            assert body["generationConfig"]["responseMimeType"] == "application/json"
        else:
            assert req.url.path.endswith("/chat/completions")
            assert ("max_tokens" in body) == (provider == "deepseek")
            assert body["response_format"]["type"] == (
                "json_object" if provider == "deepseek" else "json_schema"
            )
        return httpx.Response(200, json=native_response(provider))

    client = httpx.AsyncClient
    monkeypatch.setattr(
        adapter,
        "http_client",
        lambda **kw: client(transport=httpx.MockTransport(handler), **kw),
    )
    gw = gateway(provider)
    result = gw.generate(gw.prepare(model_request(), ModelAnswer), ModelAnswer)
    assert result.output.assessments == []
    assert result.usage.input_tokens == 10 and result.usage.output_tokens == 5
    assert "do-not-store" not in repr(result)


@pytest.mark.parametrize(
    "provider,field,value",
    [
        ("openai", "status", "incomplete"),
        ("anthropic", "stop_reason", "max_tokens"),
    ],
)
def test_native_truncation_is_never_a_valid_answer(monkeypatch, provider, field, value):
    payload = native_response(provider)
    payload[field] = value
    with pytest.raises(ModelFailure, match="truncated"):
        from test_model_gateway import mock_transport

        mock_transport(monkeypatch, lambda req: httpx.Response(200, json=payload))
        gw = gateway(provider)
        gw.generate(gw.prepare(model_request(), ModelAnswer), ModelAnswer)


def test_native_tools_refusals_and_endpoint_allowlist(monkeypatch):
    from test_model_gateway import mock_transport

    payload = native_response("openai")
    payload["output"] = [{"type": "function_call", "name": "send_email"}]
    with pytest.raises(ModelFailure, match="invalid_output"):
        mock_transport(monkeypatch, lambda req: httpx.Response(200, json=payload))
        gw = gateway("openai")
        gw.generate(gw.prepare(model_request(), ModelAnswer), ModelAnswer)
    payload = native_response("anthropic")
    payload["stop_reason"] = "refusal"
    with pytest.raises(ModelFailure, match="refused"):
        mock_transport(monkeypatch, lambda req: httpx.Response(200, json=payload))
        gw = gateway("anthropic")
        gw.generate(gw.prepare(model_request(), ModelAnswer), ModelAnswer)
    gw = gateway("openai")
    gw.cfg.ai_base_url = "https://127.0.0.1/v1"
    with pytest.raises(ModelFailure, match="policy_denied"):
        gw.prepare(model_request(), ModelAnswer)


def test_anthropic_bounds_are_enforced_locally_after_grammar_translation(monkeypatch):
    from app.modules.ai_admin.api import Probe

    def handler(req):
        schema = json.loads(req.content)["output_config"]["format"]["schema"]
        assert "maxItems" not in schema["properties"]["checks"]
        return httpx.Response(
            200,
            json={
                "id": "msg_fixture",
                "model": "model-fixture",
                "type": "message",
                "role": "assistant",
                "stop_reason": "end_turn",
                "content": [
                    {
                        "type": "text",
                        "text": json.dumps(
                            {
                                "status": "coroof_connection_ok",
                                "checks": ["schema", "schema"],
                            }
                        ),
                    }
                ],
            },
        )

    client = httpx.AsyncClient
    monkeypatch.setattr(
        adapter,
        "http_client",
        lambda **kw: client(transport=httpx.MockTransport(handler), **kw),
    )
    gw = gateway("anthropic")
    original = Probe.model_json_schema()
    call = gw.prepare(model_request(), Probe)
    assert Probe.model_json_schema() == original
    with pytest.raises(ModelFailure, match="invalid_output"):
        gw.generate(call, Probe)


def admin_ready(monkeypatch):
    monkeypatch.setenv("COROOF_AI_SECRET_KEY", Fernet.generate_key().decode())
    settings.cache_clear()


def connection_body(**kw):
    return {
        "name": "测试连接",
        "provider": "openai",
        "model": "model-fixture",
        "base_url": "https://api.openai.com/v1",
        "api_key": "fixture-not-real",
        "output_mode": "schema",
        "idempotency_key": str(uuid4()),
        **kw,
    }


def action(row):
    return {"expected_version": row["version"], "idempotency_key": str(uuid4())}


def enable(boss, row, **kw):
    policy = boss.get("/ai/settings")
    body = {
        k: policy[k]
        for k in (
            "daily_call_limit",
            "daily_token_limit",
            "monthly_token_limit",
            "concurrency_limit",
            "alert_percent",
        )
    }
    body.update(expected_version=policy["version"], mode="byok", connection_id=row["id"], **kw)
    return boss.request("PUT", "/ai/settings", body)


def provider_mock(monkeypatch, hook=None, unknown_usage=False):
    calls = []

    def handler(req):
        calls.append(req)
        if hook:
            hook()
        data = native_response("openai")
        format_ = json.loads(req.content)["text"]["format"]
        if format_["name"] == "Probe":
            data["output"][1]["content"][0]["text"] = (
                '{"status":"coroof_connection_ok","checks":["schema"]}'
            )
        if unknown_usage:
            data.pop("usage")
        return httpx.Response(200, json=data)

    client = httpx.AsyncClient
    monkeypatch.setattr(
        adapter,
        "http_client",
        lambda **kw: client(transport=httpx.MockTransport(handler), **kw),
    )
    return calls


def test_connection_lifecycle_routes_business_and_scopes_usage(loop, monkeypatch):
    boss, employee, org, _, _, work = loop
    admin_ready(monkeypatch)
    calls = provider_mock(monkeypatch)
    body = connection_body()
    row = boss.post("/ai/connections", body, 201)
    assert row["usage_scope"] == "application" and row["can_test"]
    assert row["can_activate"] is False
    assert boss.post("/ai/connections", body, 201)["id"] == row["id"]
    assert "fixture-not-real" not in json.dumps(row)
    assert enable(boss, row).status_code == 409
    employee.get("/ai/settings", 403)
    employee.get("/ai/connections", 403)
    employee.post(f"/ai/connections/{row['id']}/test", action(row), 403)
    command = action(row)
    tested = boss.post(f"/ai/connections/{row['id']}/test", command)
    assert tested["state"] == "tested"
    assert tested["can_activate"] is True
    assert boss.post(f"/ai/connections/{row['id']}/test", command) == tested
    assert len(calls) == 1
    assert enable(boss, tested).status_code == 200
    answer = boss.post("/ai/ask", {"question": "根据事实说明", "work_item_id": work["id"]})
    assert answer["mode"] == "model" and answer["provider"] == "openai"
    usage = boss.get("/ai/usage")
    assert usage["calls"] == 2 and usage["test_calls"] == 1 and usage["business_tasks"] == 1
    assert usage["input_tokens"] == 20 and usage["cost"] is None
    assert employee.get("/ai/usage")["calls"] == 0
    assert employee.get("/ai/usage")["monthly_token_limit"] is None
    assert len(boss.get("/ai/config-events")) == 4
    with session_factory()() as db:
        stored = db.get(AIConnection, row["id"])
        assert stored.credential and "fixture-not-real" not in stored.credential
        assert unseal(stored).get_secret_value() == "fixture-not-real"
        assert all(
            c.billing_mode == "byok" and c.connection_id == row["id"]
            for c in db.scalars(select(ModelInvocation))
        )
    revoked = boss.post(f"/ai/connections/{row['id']}/revoke", action(tested))
    assert revoked["state"] == "revoked"
    assert boss.get("/ai/settings")["mode"] == "disabled"
    assert (
        boss.post("/ai/ask", {"question": "情况如何", "work_item_id": work["id"]})["mode"]
        == "rules"
    )
    assert len(calls) == 2


def test_owner_can_register_developer_credentials_without_enabling_business(loop, monkeypatch):
    from app.modules.ai_admin.service import CODING_PLAN_BASE_URL, connection_config

    boss, employee, _, _, _, _ = loop
    admin_ready(monkeypatch)
    calls = provider_mock(monkeypatch)
    body = connection_body(
        provider="bailian",
        model="qwen3.7-plus",
        base_url=CODING_PLAN_BASE_URL,
        api_key="sk-sp-fixture-not-real",
    )
    row = boss.post("/ai/connections", body, 201)
    assert row["usage_scope"] == "development_only" and row["key_hint"] == "••••real"
    assert not row["can_test"] and not row["can_activate"]
    assert boss.get("/ai/connections")[0]["id"] == row["id"]
    assert "sk-sp-fixture" not in json.dumps(row)
    assert enable(boss, row).json()["error"]["code"] == "development_only"
    boss.post(f"/ai/connections/{row['id']}/test", action(row), 409)
    employee.get("/ai/connections", 403)
    other = API("other-developer@example.com")
    other.org("其他企业")
    assert other.get("/ai/connections") == []
    assert enable(other, row).status_code == 404
    with session_factory()() as db:
        saved = db.get(AIConnection, row["id"])
        assert "sk-sp-fixture" not in saved.credential
        saved.state = "tested"  # Even a legacy probe success must not grant activation.
        db.commit()
        with pytest.raises(ModelFailure, match="policy_denied"):
            connection_config(saved)
    assert not boss.get("/ai/connections")[0]["can_activate"]
    assert enable(boss, row).status_code == 409
    revoked = boss.post(f"/ai/connections/{row['id']}/revoke", action(row))
    assert revoked["state"] == "revoked" and revoked["key_hint"] == "••••"
    assert calls == [] and boss.get("/ai/usage")["calls"] == 0


def test_saved_profile_import_is_idempotent_tenant_scoped_and_does_not_select_it(loop, monkeypatch):
    from fastapi import HTTPException

    from app.infrastructure.models import AIConfigEvent
    from app.modules.ai_admin.imports import import_saved_connection
    from app.modules.ai_admin.service import CODING_PLAN_BASE_URL

    boss, _, org, _, _, _ = loop
    admin_ready(monkeypatch)
    calls = provider_mock(monkeypatch)
    config = {
        "provider": "bailian_coding_plan",
        "model": "qwen3.7-plus",
        "base_url": CODING_PLAN_BASE_URL,
        "api_key": "sk-sp-fixture-import",
    }
    with session_factory()() as db:
        members = db.scalars(
            select(Membership).where(Membership.organization_id == org["id"])
        ).all()
        actor = next(m for m in members if "owner" in m.roles)
        employee = next(m for m in members if "owner" not in m.roles)
        first = import_saved_connection(db, actor, config, "已有百炼配置")
        again = import_saved_connection(db, actor, config, "已有百炼配置")
        assert first.id == again.id
        assert (
            len(
                db.scalars(
                    select(AIConfigEvent).where(AIConfigEvent.action == "connection.imported")
                ).all()
            )
            == 1
        )
        with pytest.raises(HTTPException) as exc:
            import_saved_connection(db, employee, config, "越权导入")
        assert exc.value.status_code == 403
    assert boss.get("/ai/settings")["connection_id"] is None
    assert len(boss.get("/ai/connections")) == 1 and calls == []


def test_configuration_isolation_secret_binding_and_endpoint_policy(loop, monkeypatch):
    boss, _, org, _, _, _ = loop
    admin_ready(monkeypatch)
    row = boss.post("/ai/connections", connection_body(), 201)
    other = API("other@example.com")
    other_org = other.org("另一企业")
    assert other.get("/ai/connections") == []
    other.post(f"/ai/connections/{row['id']}/test", action(row), 404)
    assert enable(other, row).status_code == 404
    boss.post("/ai/connections", connection_body(base_url="https://127.0.0.1/v1"), 422)
    boss.post(
        "/ai/connections", connection_body(base_url="https://api.openai.com.evil.example/v1"), 422
    )
    with session_factory()() as db:
        original = db.get(AIConnection, row["id"])
        fake = AIConnection(
            id=original.id, organization_id=other_org["id"], credential=original.credential
        )
        with pytest.raises(ModelFailure, match="not_configured"):
            unseal(fake)
        db.add(
            AISettings(
                organization_id=other_org["id"],
                mode="byok",
                connection_id=row["id"],
                daily_call_limit=10,
                daily_token_limit=10000,
                monthly_token_limit=10000,
                concurrency_limit=1,
            )
        )
        with pytest.raises(IntegrityError):
            db.flush()
        db.rollback()


@pytest.mark.parametrize("change,status", [("revoke", 409), ("role", 403), ("session", 401)])
def test_test_call_cannot_restore_revoked_access(loop, monkeypatch, change, status):
    boss, _, _, _, _, _ = loop
    admin_ready(monkeypatch)
    row = boss.post("/ai/connections", connection_body(), 201)

    def hook():
        with session_factory()() as db:
            connection = db.get(AIConnection, row["id"])
            if change == "revoke":
                connection.state, connection.credential = "revoked", None
                connection.version += 1
            elif change == "role":
                db.get(Membership, connection.actor_id).roles = ["member"]
            else:
                from app.infrastructure.models import AuthSession

                for session in db.scalars(select(AuthSession)):
                    db.delete(session)
            db.commit()

    provider_mock(monkeypatch, hook)
    boss.post(f"/ai/connections/{row['id']}/test", action(row), status)
    with session_factory()() as db:
        assert db.get(AIConnection, row["id"]).state != "tested"
        assert db.scalar(select(ModelInvocation)).error_code == "access_revoked"


def test_unknown_usage_and_monthly_limit_are_not_reported_as_zero(loop, monkeypatch):
    boss, _, _, _, _, work = loop
    admin_ready(monkeypatch)
    calls = provider_mock(monkeypatch, unknown_usage=True)
    row = boss.post("/ai/connections", connection_body(), 201)
    row = boss.post(f"/ai/connections/{row['id']}/test", action(row))
    assert enable(boss, row, monthly_token_limit=1000).status_code == 200
    result = boss.post("/ai/ask", {"question": "请说明", "work_item_id": work["id"]})
    assert result["mode"] == "rules" and len(calls) == 1
    usage = boss.get("/ai/usage")
    assert usage["unknown_usage_calls"] == 1 and usage["quota_occupied_tokens"] > 1000
    assert usage["alert"] and usage["cost"] is None


def test_encryption_setup_required_and_stale_settings_rejected(loop, monkeypatch):
    boss, _, _, _, _, _ = loop
    monkeypatch.setenv("COROOF_AI_SECRET_KEY", "")
    settings.cache_clear()
    assert boss.get("/ai/settings")["credential_storage_ready"] is False
    boss.post("/ai/connections", connection_body(), 422)
    body = {
        "expected_version": 0,
        "mode": "disabled",
        "daily_call_limit": 100,
        "daily_token_limit": 200000,
        "monthly_token_limit": 6000000,
        "concurrency_limit": 2,
        "alert_percent": 80,
    }
    assert boss.request("PUT", "/ai/settings", body).status_code == 200
    assert boss.request("PUT", "/ai/settings", body).status_code == 409


def test_concurrent_settings_updates_have_one_winner(loop):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier

    boss, _, _, _, _, _ = loop
    with session_factory()() as db:
        if db.get_bind().dialect.name != "postgresql":
            pytest.skip("PostgreSQL row locks required")
    body = {
        "expected_version": 0,
        "mode": "disabled",
        "daily_call_limit": 100,
        "daily_token_limit": 200000,
        "monthly_token_limit": 6000000,
        "concurrency_limit": 2,
        "alert_percent": 80,
    }
    barrier = Barrier(2)

    def save(_):
        barrier.wait()
        return boss.request("PUT", "/ai/settings", body).status_code

    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(save, range(2))) == [200, 409]
    assert len(boss.get("/ai/config-events")) == 1


def test_platform_budgets_remain_bounded_by_operator_and_audit_has_actor(loop, monkeypatch):
    from app.modules.ai_admin.service import effective_config

    boss, _, org, _, _, _ = loop
    body = {
        "expected_version": 0,
        "mode": "platform",
        "daily_call_limit": 100,
        "daily_token_limit": 200000,
        "monthly_token_limit": 6000000,
        "concurrency_limit": 2,
        "alert_percent": 80,
    }
    assert boss.request("PUT", "/ai/settings", {**body, "daily_call_limit": 101}).status_code == 422
    assert boss.request("PUT", "/ai/settings", body).status_code == 200
    audit = boss.get("/ai/config-events")
    assert audit[0]["actor_name"] and "24 小时 100 次" in audit[0]["detail"]
    monkeypatch.setenv("COROOF_AI_DAILY_CALL_LIMIT", "50")
    settings.cache_clear()
    assert boss.get("/ai/settings")["daily_call_limit"] == 50
    with session_factory()() as db:
        actor = db.scalar(select(Membership).where(Membership.organization_id == org["id"]))
        assert effective_config(db, actor).ai_daily_call_limit == 50


def test_credentials_reject_header_control_characters_without_echo(loop, monkeypatch):
    boss, _, _, _, _, _ = loop
    admin_ready(monkeypatch)
    secret = "fixture-secret\r\nx-api-key: injected"
    response = boss.request("POST", "/ai/connections", connection_body(api_key=secret))
    assert response.status_code == 422 and "fixture-secret" not in response.text
    assert boss.get("/ai/connections") == []


def test_usage_groups_days_in_utc_independently_of_postgres_session_timezone(loop, monkeypatch):
    from datetime import UTC, datetime

    from sqlalchemy import text

    from app.modules.ai_admin import usage as usage_module

    boss, _, org, _, _, _ = loop
    admin_ready(monkeypatch)
    provider_mock(monkeypatch)
    row = boss.post("/ai/connections", connection_body(), 201)
    boss.post(f"/ai/connections/{row['id']}/test", action(row))
    monkeypatch.setattr(usage_module, "now", lambda: datetime(2026, 11, 3, tzinfo=UTC))
    with session_factory()() as db:
        if db.get_bind().dialect.name == "postgresql":
            db.execute(text("SET LOCAL TIME ZONE 'Pacific/Honolulu'"))
        call = db.scalar(
            select(ModelInvocation).where(ModelInvocation.organization_id == org["id"])
        )
        call.started_at = datetime(2026, 11, 1, 1, tzinfo=UTC)
        db.flush()
        actor = next(
            m
            for m in db.scalars(select(Membership).where(Membership.organization_id == org["id"]))
            if "owner" in m.roles
        )
        result = usage_module.usage(db, actor)
        assert result.calls == 1 and result.daily[0].label == "2026-11-01"


def test_ai_migration_preserves_invocations_and_checks(database, loop):
    from alembic import command
    from sqlalchemy import text

    from app.infrastructure.models import AnalysisRun, now

    _, _, org, _, member, _ = loop
    with session_factory()() as db:
        run = AnalysisRun(
            organization_id=org["id"],
            actor_id=member["id"],
            purpose="evidence_qa",
            provider="fixture",
            model="fixture",
            prompt_version="v1",
            input_evidence_ids=[],
            output_schema_version="v1",
            latency_ms=1,
            status="succeeded",
        )
        db.add(run)
        db.flush()
        call = ModelInvocation(
            organization_id=org["id"],
            actor_id=member["id"],
            analysis_run_id=run.id,
            request_id=str(uuid4()),
            request_hash="a" * 64,
            task="evidence_qa",
            provider="fixture",
            model="fixture",
            profile_id="v1",
            adapter_version="v1",
            prompt_version="v1",
            schema_version="v1",
            status="succeeded",
            charged_tokens=10,
            lease_expires_at=now(),
        )
        db.add(call)
        db.commit()
        call_id = call.id
    command.downgrade(database, "0003_model_gateway")
    command.upgrade(database, "head")
    command.check(database)
    with session_factory()() as db:
        restored = db.get(ModelInvocation, call_id)
        assert restored.charged_tokens == 10 and restored.billing_mode == "platform"
        assert restored.connection_id is None
        with pytest.raises(IntegrityError):
            db.execute(
                text("UPDATE model_invocations SET charged_tokens = -1 WHERE id = :id"),
                {"id": call_id},
            )
            db.flush()
        db.rollback()
