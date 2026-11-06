import asyncio
import importlib.util
import json
import os
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import timedelta
from pathlib import Path
from threading import Barrier
from uuid import uuid4

import httpx
import pytest
from alembic import command
from conftest import API
from pydantic import SecretStr
from sqlalchemy import func, select, text
from sqlalchemy.exc import IntegrityError

from app.core.config import Settings, settings
from app.infrastructure.db import session_factory
from app.infrastructure.models import (
    AnalysisRun,
    AuthSession,
    Membership,
    ModelInvocation,
    Organization,
    WorkItem,
    now,
)
from app.modules.intelligence import invocations
from app.modules.intelligence.schemas import ModelAnswer
from app.modules.model_gateway import adapter
from app.modules.model_gateway.contracts import Message, ModelFailure, ModelRequest, TokenUsage
from app.modules.model_gateway.gateway import ModelGateway, validate_schema


def config(**overrides):
    return Settings(
        _env_file=None,
        **{
            "ai_provider": "bailian",
            "ai_base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
            "ai_model": "qwen3.7-plus",
            "ai_api_key": SecretStr("fixture-not-real"),
            "ai_model_verified": True,
            **overrides,
        },
    )


def request():
    return ModelRequest(
        prompt_version="test-v1", messages=(Message(role="user", content="返回 JSON"),)
    )


def test_compact_schema_preserves_named_title_property_and_constraints():
    from pydantic import Field

    from app.modules.model_gateway.contracts import StrictModel

    class Entry(StrictModel):
        title: str = Field(min_length=1, max_length=40, description="User supplied heading")

    class Envelope(StrictModel):
        entry: Entry

    original = Envelope.model_json_schema()
    call = ModelGateway(config()).prepare(request(), Envelope)
    compact = call.body["schema"]
    assert compact["title"] == original["title"]
    nested = compact["$defs"]["Entry"]
    assert "title" not in nested
    assert nested["required"] == ["title"] and nested["additionalProperties"] is False
    assert nested["properties"]["title"] == {
        "type": "string",
        "minLength": 1,
        "maxLength": 40,
        "description": "User supplied heading",
    }
    assert Envelope.model_json_schema() == original


def mock_transport(monkeypatch, handler):
    client = httpx.AsyncClient
    monkeypatch.setattr(
        adapter,
        "http_client",
        lambda **kw: client(transport=httpx.MockTransport(handler), **kw),
    )


def response(content=None, **extra):
    return httpx.Response(
        200,
        json={
            "model": "qwen3.7-plus",
            "id": "request-fixture",
            "choices": [
                {
                    "finish_reason": "stop",
                    "message": {
                        "role": "assistant",
                        "content": json.dumps(
                            content if content is not None else {"assessments": []}
                        ),
                        "reasoning_content": "hidden-reasoning-not-to-persist",
                    },
                }
            ],
            **extra,
        },
    )


def setup_model(monkeypatch, **overrides):
    for name, value in {
        "PROVIDER": "bailian",
        "BASE_URL": "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "MODEL": "qwen3.7-plus",
        "API_KEY": "fixture-not-real",
        "MODEL_VERIFIED": "true",
        **overrides,
    }.items():
        monkeypatch.setenv("COROOF_AI_" + name, str(value))
    settings.cache_clear()


def ask(api, work):
    return api.request(
        "POST", "/ai/ask", {"question": "请根据依据判断", "work_item_id": work["id"]}
    )


def test_qwen_request_and_usage(monkeypatch):
    def handle(req):
        body = json.loads(req.content)
        assert req.url.path == "/compatible-mode/v1/chat/completions"
        assert body["enable_thinking"] is False
        assert body["max_completion_tokens"] == 2500 and body["stream"] is False
        assert body["response_format"]["json_schema"]["strict"] is True
        assert not {"store", "extra_body", "tools", "temperature", "top_p"}.intersection(body)
        assert req.headers["accept-encoding"] == "identity"
        return response(
            usage={
                "prompt_tokens": 20,
                "completion_tokens": 10,
                "completion_tokens_details": {"reasoning_tokens": 0},
            }
        )

    mock_transport(monkeypatch, handle)
    gateway = ModelGateway(config())
    result = gateway.generate(gateway.prepare(request(), ModelAnswer), ModelAnswer)
    assert result.usage == TokenUsage(input_tokens=20, output_tokens=10, reasoning_tokens=0)
    assert result.output.assessments == [] and result.provider_request_id == "request-fixture"
    assert "hidden-reasoning" not in repr(result)


@pytest.mark.parametrize(
    "status,code",
    [
        (401, "authentication"),
        (403, "permission"),
        (429, "rate_limited"),
        (400, "invalid_request"),
        (302, "invalid_request"),
        (503, "unavailable"),
    ],
)
def test_http_errors_are_redacted_and_never_retried(monkeypatch, status, code):
    calls = []

    def handle(req):
        calls.append(req)
        return httpx.Response(
            status,
            text="Authorization fixture-not-real",
            headers={"Location": "https://other.example/steal"},
        )

    mock_transport(monkeypatch, handle)
    gateway = ModelGateway(config())
    with pytest.raises(ModelFailure) as error:
        gateway.generate(gateway.prepare(request(), ModelAnswer), ModelAnswer)
    assert str(error.value) == code and error.value.sent and len(calls) == 1
    assert "fixture-not-real" not in repr(error.value)


@pytest.mark.parametrize(
    "payload,expected",
    [
        (
            {
                "choices": [
                    {"finish_reason": "length", "message": {"role": "assistant", "content": "{}"}}
                ]
            },
            "truncated",
        ),
        (
            {
                "choices": [
                    {
                        "finish_reason": "stop",
                        "message": {"role": "assistant", "refusal": "refused"},
                    }
                ]
            },
            "refused",
        ),
        (
            {
                "choices": [
                    {
                        "finish_reason": "tool_calls",
                        "message": {"role": "assistant", "tool_calls": [{}]},
                    }
                ]
            },
            "invalid_output",
        ),
        (
            {
                "choices": [
                    {
                        "finish_reason": "stop",
                        "message": {"role": "assistant", "content": "not json"},
                    }
                ]
            },
            "invalid_output",
        ),
        ({"choices": []}, "invalid_output"),
        (
            {
                "choices": [
                    {
                        "finish_reason": "stop",
                        "message": {
                            "role": "assistant",
                            "content": '{"assessments": [], "approved": true}',
                        },
                    }
                ]
            },
            "invalid_output",
        ),
        (
            {
                "choices": [
                    {
                        "finish_reason": "stop",
                        "message": {"role": "assistant", "content": "fixture-not-real"},
                    }
                ]
            },
            "invalid_output",
        ),
    ],
)
def test_rejects_unsafe_or_incomplete_output(monkeypatch, payload, expected):
    mock_transport(monkeypatch, lambda req: httpx.Response(200, json=payload))
    gateway = ModelGateway(config())
    with pytest.raises(ModelFailure, match=expected):
        gateway.generate(gateway.prepare(request(), ModelAnswer), ModelAnswer)


def test_total_deadline_stops_slow_stream(monkeypatch):
    closed = []

    class SlowStream(httpx.AsyncByteStream):
        async def __aiter__(self):
            while True:
                await asyncio.sleep(0.01)
                yield b" "

        async def aclose(self):
            closed.append(True)

    mock_transport(monkeypatch, lambda req: httpx.Response(200, stream=SlowStream()))
    gateway = ModelGateway(config(ai_timeout_seconds=0.05))
    with pytest.raises(ModelFailure, match="timeout"):
        gateway.generate(gateway.prepare(request(), ModelAnswer), ModelAnswer)
    assert closed


def test_response_limit_stops_reading(monkeypatch):
    read = []

    class HugeStream(httpx.AsyncByteStream):
        async def __aiter__(self):
            for _ in range(1000):
                read.append(1)
                yield b"x" * 4096

    mock_transport(monkeypatch, lambda req: httpx.Response(200, stream=HugeStream()))
    gateway = ModelGateway(config())
    with pytest.raises(ModelFailure, match="response_too_large"):
        gateway.generate(gateway.prepare(request(), ModelAnswer), ModelAnswer)
    assert len(read) < 40


@pytest.mark.parametrize(
    "overrides,expected",
    [
        ({"ai_api_key": SecretStr("")}, "not_configured"),
        ({"ai_api_key": SecretStr("sk-sp-fixture")}, "policy_denied"),
        ({"ai_base_url": "https://coding.dashscope.aliyuncs.com/v1"}, "policy_denied"),
        ({"ai_base_url": "https://evil.example/compatible-mode/v1"}, "policy_denied"),
        ({"ai_model": "qwen-unknown"}, "unsupported_capability"),
        ({"ai_model_verified": False}, "not_verified"),
    ],
)
def test_invalid_configuration_fails_before_network(overrides, expected):
    with pytest.raises(ModelFailure, match=expected):
        ModelGateway(config(**overrides)).prepare(request(), ModelAnswer)


def test_unknown_usage_is_not_zero_and_unsupported_schema_rejected():
    assert adapter.token_usage(None).output_tokens is None
    assert adapter.token_usage({"output_tokens": -2}).output_tokens is None
    assert adapter.token_usage({"output_tokens": "12"}).output_tokens is None
    assert adapter.token_usage({"output_tokens": 10**30}).output_tokens is None
    with pytest.raises(ModelFailure, match="unsupported_capability"):
        validate_schema(
            {
                "type": "object",
                "additionalProperties": False,
                "properties": {"amount": {"type": "number", "multipleOf": 5}},
            }
        )


def test_invocation_audit_budget_and_rules_source(loop, monkeypatch):
    boss, _, org, _, _, work = loop
    setup_model(monkeypatch, DAILY_CALL_LIMIT=1)
    calls = []

    def handle(req):
        calls.append(req)
        return response()

    mock_transport(monkeypatch, handle)
    first = ask(boss, work).json()
    second = ask(boss, work).json()
    assert first["mode"] == "model"
    assert second["mode"] == "rules" and second["provider"] == "rules"
    assert second["model"] == "deterministic-no-llm" and len(calls) == 1
    with session_factory()() as db:
        row = db.scalar(select(ModelInvocation))
        assert row.organization_id == org["id"] and row.status == "succeeded"
        assert row.usage["output_tokens"] is None and row.charged_tokens > 0
        assert db.get(AnalysisRun, first["id"]).cost_estimate == "unknown"
        assert db.get(AnalysisRun, second["id"]).failure_code == "budget_exceeded"
        assert "fixture-not-real" not in str(row.__dict__)
        assert "hidden-reasoning" not in str(row.__dict__)


@pytest.mark.parametrize(
    "change,status", [("membership", 403), ("assignment", 404), ("session", 401)]
)
def test_permission_revoked_during_model_call_never_returns_evidence(
    loop, monkeypatch, change, status
):
    _, employee, _, _, member, work = loop
    setup_model(monkeypatch)

    def handle(req):
        with session_factory()() as db:
            actor = db.get(Membership, member["id"])
            if change == "membership":
                actor.status = "inactive"
            elif change == "assignment":
                db.get(WorkItem, work["id"]).owner_id = None
            else:
                for session in db.scalars(
                    select(AuthSession).where(AuthSession.user_id == actor.user_id)
                ):
                    db.delete(session)
            db.commit()
        return response()

    mock_transport(monkeypatch, handle)
    result = ask(employee, work)
    assert result.status_code == status and "evidence" not in result.json()
    with session_factory()() as db:
        run = db.scalar(select(AnalysisRun).where(AnalysisRun.purpose == "evidence_qa"))
        assert run.status == "access_revoked" and run.result is None
        assert db.scalar(select(ModelInvocation)).error_code == "access_revoked"


def pending(db, actor):
    row = AnalysisRun(
        organization_id=actor.organization_id,
        actor_id=actor.id,
        purpose="evidence_qa",
        provider="rules",
        model="deterministic-no-llm",
        prompt_version="test-v1",
        input_evidence_ids=[],
        output_schema_version="answer-v1",
        latency_ms=0,
        status="pending",
    )
    db.add(row)
    db.commit()
    return row


def test_postgres_concurrent_admission_and_no_duplicate_retry(loop):
    _, _, _, _, member, _ = loop
    factory = session_factory()
    if factory.kw["bind"].dialect.name != "postgresql":
        pytest.skip("PostgreSQL required for admission row locks")
    cfg = config(ai_concurrency_limit=1)
    call = ModelGateway(cfg).prepare(request(), ModelAnswer)
    with factory() as db:
        actor = db.get(Membership, member["id"])
        ids = [pending(db, actor).id for _ in range(2)]
    barrier = Barrier(2)

    def attempt(run_id):
        with factory() as db:
            actor = db.get(Membership, member["id"])
            run = db.get(AnalysisRun, run_id)
            barrier.wait(timeout=5)
            try:
                return invocations.reserve(db, actor, run, call, cfg).status
            except ModelFailure as exc:
                db.commit()
                return exc.code

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(attempt, ids))
    assert sorted(results) == ["budget_exceeded", "pending"]
    with factory() as db:
        row = db.scalar(select(ModelInvocation))
        row.lease_expires_at = now() - timedelta(seconds=1)
        db.commit()
        with pytest.raises(ModelFailure, match="policy_denied"):
            invocations.reserve(
                db,
                db.get(Membership, member["id"]),
                db.get(AnalysisRun, row.analysis_run_id),
                call,
                cfg,
            )
        db.commit()
        assert row.status == "unknown" and row.charged_tokens > 0
        assert db.scalar(select(func.count()).select_from(ModelInvocation)) == 1


def test_model_invocation_composite_tenant_foreign_key(loop):
    _, _, _, _, member, _ = loop
    outsider = API("model-other@example.com")
    foreign_org = outsider.org()
    with session_factory()() as db:
        actor = db.get(Membership, member["id"])
        run = pending(db, actor)
        cfg = config()
        row = invocations.reserve(
            db, actor, run, ModelGateway(cfg).prepare(request(), ModelAnswer), cfg
        )
        row.organization_id = foreign_org["id"]
        with pytest.raises(IntegrityError):
            db.commit()
        db.rollback()


def test_input_is_trimmed_by_whole_evidence_and_coverage_is_truthful(loop, monkeypatch):
    boss, _, _, departments, _, work = loop
    for i in range(10):
        boss.work(departments[0], title=f"合成测试 {i} " + "长标题" * 60)
    setup_model(monkeypatch, MAX_INPUT_TOKENS=10000)
    included = []

    def handle(req):
        data = json.loads(req.content)
        context = json.loads(data["messages"][1]["content"])
        included.extend(e["id"] for e in context["evidence"])
        assert len(json.dumps(data, ensure_ascii=False, sort_keys=True).encode()) + 512 <= 10000
        return response()

    mock_transport(monkeypatch, handle)
    result = boss.post("/ai/ask", {"question": "哪些事项需要关注？"})
    assert result["mode"] == "model" and 0 < len(included) < 11
    assert result["considered_work_count"] == len(result["evidence"]) == len(included)
    assert result["authorized_work_count"] == 11


def test_tenant_budgets_are_independent(loop, monkeypatch):
    boss, _, _, _, _, work = loop
    other = API("independent-budget@example.com")
    other.org()
    other_work = other.work(other.department())
    setup_model(monkeypatch, DAILY_CALL_LIMIT=1)
    mock_transport(monkeypatch, lambda req: response())
    assert ask(boss, work).json()["mode"] == "model"
    assert ask(boss, work).json()["mode"] == "rules"
    assert ask(other, other_work).json()["mode"] == "model"


def test_model_wait_does_not_hold_work_locks_and_reports_updated_snapshot(loop, monkeypatch):
    boss, _, _, _, _, work = loop
    setup_model(monkeypatch)

    def handle(req):
        with session_factory()() as db:
            if db.bind.dialect.name == "postgresql":
                db.execute(text("SET LOCAL lock_timeout = '250ms'"))
            current = db.scalar(select(WorkItem).where(WorkItem.id == work["id"]).with_for_update())
            current.title = "已更新的合成事项"
            db.commit()
        return response()

    mock_transport(monkeypatch, handle)
    result = ask(boss, work).json()
    assert result["mode"] == "model" and result["evidence"][0]["outdated"]


def test_deeply_nested_response_is_rejected(monkeypatch):
    gateway = ModelGateway(config())
    call = gateway.prepare(request(), ModelAnswer)
    mock_transport(monkeypatch, lambda req: httpx.Response(200, content=b"[" * 5000 + b"]" * 5000))
    with pytest.raises(ModelFailure, match="invalid_output"):
        gateway.generate(call, ModelAnswer)


def test_admission_and_network_share_one_deadline(monkeypatch):
    gateway = ModelGateway(config())
    call = gateway.prepare(request(), ModelAnswer)
    expired = replace(call, prepared_at=call.prepared_at - call.timeout_seconds - 1)
    calls = []
    mock_transport(monkeypatch, lambda req: calls.append(req) or response())
    with pytest.raises(ModelFailure, match="timeout") as error:
        gateway.generate(expired, ModelAnswer)
    assert not calls and not error.value.sent


def test_postgres_admission_lock_wait_is_bounded(loop):
    _, _, org, _, member, _ = loop
    factory = session_factory()
    if factory.kw["bind"].dialect.name != "postgresql":
        pytest.skip("PostgreSQL required for admission lock timeout")
    cfg = config(ai_timeout_seconds=0.1)
    with factory() as db:
        actor = db.get(Membership, member["id"])
        run = pending(db, actor)
        with factory() as blocker:
            blocker.scalar(
                select(Organization).where(Organization.id == org["id"]).with_for_update()
            )
            call = ModelGateway(cfg).prepare(request(), ModelAnswer)
            with pytest.raises(ModelFailure, match="timeout"):
                invocations.reserve(db, actor, run, call, cfg)
        assert db.scalar(select(func.count()).select_from(ModelInvocation)) == 0


def live_acceptance_module():
    path = Path(__file__).resolve().parents[2] / "scripts/model_acceptance.py"
    spec = importlib.util.spec_from_file_location("model_acceptance", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_live_acceptance_uses_synthetic_data_and_requires_all_cases(monkeypatch):
    module = live_acceptance_module()
    calls = []

    def handle(req):
        calls.append(req)
        context = json.loads(json.loads(req.content)["messages"][1]["content"])
        evidence = context["evidence"]
        assert all(e["id"] == "synthetic-evidence" for e in evidence)
        if not evidence or "另一家企业" in context["question"]:
            return response()
        return response(
            {
                "assessments": [
                    {
                        "evidence_id": evidence[0]["id"],
                        "quote": evidence[0]["excerpt"],
                        "interpretation": "建议核实当前记录及实际情况，再确认处理安排。",
                        "action_keys": ["verify"],
                    }
                ]
            }
        )

    mock_transport(monkeypatch, handle)
    report = module.run(config(ai_model_verified=False))
    assert report["passed"] and len(calls) == 6 and report["synthetic_data"]
    assert "fixture-not-real" not in json.dumps(report)


def test_live_acceptance_is_not_a_success_on_missing_config(tmp_path):
    script = Path(__file__).resolve().parents[2] / "scripts/model_acceptance.py"
    env = {**os.environ, "COROOF_AI_PROVIDER": "rules", "COROOF_AI_API_KEY": ""}
    result = subprocess.run(
        [
            sys.executable,
            str(script),
            "--env-file",
            str(tmp_path / "absent.env"),
            "--report",
            str(tmp_path / "report.json"),
        ],
        env=env,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 2 and json.loads(result.stdout)["error"] == "not_configured"
    assert not (tmp_path / "report.json").exists()


def test_explicit_developer_probe_ignores_environment_and_cannot_enable_backend(
    tmp_path, monkeypatch
):
    module = live_acceptance_module()
    monkeypatch.setenv("COROOF_AI_BASE_URL", "https://unrelated.example/v1")
    monkeypatch.setenv("COROOF_AI_API_KEY", "environment-secret-not-to-use")
    monkeypatch.setenv("COROOF_AI_MODEL_VERIFIED", "true")
    monkeypatch.setenv("COROOF_DATABASE_URL", "not-a-test-database")
    monkeypatch.setenv("COROOF_ENVIRONMENT", "production")
    path = tmp_path / "test-config.json"
    path.write_text(
        json.dumps(
            {
                "provider": "bailian_coding_plan",
                "model": "qwen3.7-plus",
                "base_url": "https://coding.dashscope.aliyuncs.com/v1",
                "api_key": "sk-sp-fixture",
            }
        )
    )
    cfg = module.explicit_config(path)
    assert cfg.environment == "test" and not cfg.ai_model_verified
    assert cfg.database_url != "not-a-test-database"
    calls = []

    def handle(req):
        calls.append(req)
        assert req.url.host == "coding.dashscope.aliyuncs.com"
        assert req.headers["Authorization"] == "Bearer sk-sp-fixture"
        schema_prompt = json.loads(req.content)["messages"][0]["content"]
        assert '"action_keys"' in schema_prompt and '"required"' in schema_prompt
        return response()

    mock_transport(monkeypatch, handle)
    gateway = ModelGateway(cfg)
    with pytest.raises(ModelFailure, match="policy_denied"):
        gateway.prepare(request(), ModelAnswer)
    call = gateway.prepare(request(), ModelAnswer, verification_probe=True)
    assert call.profile.id == "bailian-coding-plan-qwen37-test-v2"
    assert gateway.generate(call, ModelAnswer).output.assessments == []
    assert len(calls) == 1
    report = module.run(cfg)
    assert report["deployment_kind"] == "bailian_coding_plan_test"
    assert not report["application_backend_verified"]
    assert "sk-sp-fixture" not in json.dumps(report)
    for environment in ("development", "production"):
        with pytest.raises(ModelFailure, match="policy_denied"):
            ModelGateway(cfg.model_copy(update={"environment": environment})).prepare(
                request(), ModelAnswer, verification_probe=True
            )


def test_migration_matches_metadata_and_keeps_slice02_records(database, loop):
    _, _, org, _, member, work = loop
    command.downgrade(database, "0002_slice02")
    old_id = str(uuid4())
    with session_factory()() as db:
        # Insert using the old column set, before the new migration exists.
        db.execute(
            AnalysisRun.__table__.insert().values(
                id=old_id,
                organization_id=org["id"],
                actor_id=member["id"],
                purpose="evidence_qa",
                provider="rules",
                model="deterministic-no-llm",
                prompt_version="old-v1",
                input_evidence_ids=[],
                output_schema_version="answer-v1",
                latency_ms=0,
                status="rules_fallback",
                result={"historical": "synthetic fixture"},
            )
        )
        db.commit()
    command.upgrade(database, "head")
    command.check(database)
    with session_factory()() as db:
        assert db.get(WorkItem, work["id"])
        old = db.get(AnalysisRun, old_id)
        assert old.failure_code is None and old.result == {"historical": "synthetic fixture"}
        assert (
            db.scalar(text("SELECT version_num FROM alembic_version"))
            == "0019_arrangement_feedback"
        )
