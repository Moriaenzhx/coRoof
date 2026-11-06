"""Explicit local connection permission never grants unattended or production access."""

import json
from uuid import uuid4

import httpx
import pytest
from conftest import API
from sqlalchemy import func, select
from test_agent_read import advance, create, finish, read_proposal
from test_ai_management import action, admin_ready, connection_body, enable
from test_model_gateway import config, mock_transport, response
from test_watch_agent import background, step
from test_watch_controls import action as watch_action
from test_watch_controls import body as watch_body
from test_watch_controls import create as create_watch
from test_watch_runner import drain, due

from app.core.config import settings
from app.core.deployment import issues
from app.infrastructure.db import session_factory
from app.infrastructure.models import (
    AgentRun,
    AIConnection,
    Identity,
    Membership,
    ModelInvocation,
    WorkEvent,
)
from app.modules.agent.capabilities import CATALOG, execute
from app.modules.agent.runtime import PROMPT_VERSION, model_history, read_system
from app.modules.agent.schemas import Proposal
from app.modules.ai_admin.service import connection_config, effective_config
from app.modules.model_gateway.contracts import Message, ModelFailure, ModelRequest
from app.modules.model_gateway.gateway import ModelGateway
from app.modules.model_gateway.profiles import (
    CODING_PLAN_BASE_URL,
    development_connection_allowed,
    resolve_profile,
)


def saved(boss, monkeypatch, **fields):
    admin_ready(monkeypatch)
    return boss.post(
        "/ai/connections",
        connection_body(
            provider="bailian",
            model="qwen3.7-plus",
            base_url=CODING_PLAN_BASE_URL,
            api_key="sk-sp-fixture-not-real",
            **fields,
        ),
        201,
    )


def allow(monkeypatch, *identifiers):
    monkeypatch.setenv("COROOF_AI_DEVELOPMENT_TEST_CONNECTION_IDS", json.dumps(identifiers))
    settings.cache_clear()


def transport(monkeypatch, hook=None, failed=False):
    calls = []

    def handle(req):
        assert str(req.url) == CODING_PLAN_BASE_URL + "/chat/completions"
        body = json.loads(req.content)
        assert body["model"] == "qwen3.7-plus"
        assert body["enable_thinking"] is False
        calls.append(body)
        if hook:
            hook()
        if failed:
            return httpx.Response(403, json={"error": {"message": "fixture refusal"}})
        if body["response_format"]["json_schema"]["name"] == "Probe":
            output = {"status": "coroof_connection_ok", "checks": ["schema"]}
        else:
            context = json.loads(
                next(m["content"] for m in body["messages"] if m["role"] == "user")
            )
            output = read_proposal() if not context["completed_reads"] else finish(context)
        return response(output, usage={"prompt_tokens": 10, "completion_tokens": 5})

    mock_transport(monkeypatch, handle)
    return calls


def probe_connection(boss, row):
    command = action(row)
    result = boss.post(f"/ai/connections/{row['id']}/test", command)
    assert result["state"] == "tested"
    assert boss.post(f"/ai/connections/{row['id']}/test", command) == result
    return result


def test_local_saved_connection_requires_test_and_explicit_activation(loop, monkeypatch):
    boss, employee, _, _, _, work = loop
    row = saved(boss, monkeypatch)
    unrelated = boss.post("/ai/connections", connection_body(), 201)
    allow(monkeypatch, row["id"])
    calls = transport(monkeypatch)
    visible = next(r for r in boss.get("/ai/connections") if r["id"] == row["id"])
    assert visible["usage_scope"] == "development_only" and visible["can_test"]
    assert not visible["can_activate"] and "后台持续关注不会调用" in visible["usage_notice"]
    assert enable(boss, row).json()["error"]["code"] == "connection_not_tested"
    assert calls == []
    employee.post(f"/ai/connections/{row['id']}/test", action(row), 403)
    foreign = API("other-local-test@example.com")
    foreign.org()
    foreign.post(f"/ai/connections/{row['id']}/test", action(row), 404)
    assert enable(foreign, row).status_code == 404
    verified = probe_connection(boss, row)
    assert verified["can_activate"] and len(calls) == 1
    assert boss.get("/ai/settings")["mode"] == "platform"
    assert enable(boss, verified).status_code == 200
    with session_factory()() as db:
        before = db.scalar(select(func.count()).select_from(WorkEvent))
        stored = db.get(AIConnection, row["id"])
        with pytest.raises(ModelFailure, match="policy_denied"):
            connection_config(stored)
        cfg = connection_config(stored, allow_development_test=True)
        assert cfg.ai_timeout_seconds == 60 and cfg.ai_model_verified
        assert db.get(AIConnection, unrelated["id"]).state == "draft"
    run = create(boss, work)
    run = advance(boss, run)
    run = advance(boss, run)
    assert run["state"] == "completed" and len(calls) == 3
    assert run["answer"]["mode"] == "model"
    assert run["answer"]["evidence"][0]["work_item_id"] == work["id"]
    usage = boss.get("/ai/usage")
    assert usage["calls"] == 3 and usage["test_calls"] == 1
    with session_factory()() as db:
        assert db.scalar(select(func.count()).select_from(WorkEvent)) == before
        invocations = list(db.scalars(select(ModelInvocation)))
        assert len(invocations) == 3
        assert all(c.connection_id == row["id"] and c.billing_mode == "byok" for c in invocations)
    assert {e["action"] for e in boss.get("/ai/config-events")} >= {
        "connection.test_started",
        "connection.test_finished",
        "settings.saved",
    }
    # Legacy non-Agent queries do not opt in to this local permission.
    answer = boss.post("/ai/ask", {"question": "当前情况", "work_item_id": work["id"]})
    assert answer["mode"] == "rules" and len(calls) == 3


@pytest.mark.parametrize(
    "changes",
    [
        {"environment": "production"},
        {"auth_mode": "oidc"},
        {"web_origin": "https://workspace.example.com"},
        {"web_origin": "http://localhost.evil.example"},
        {"web_origin": "http://user@localhost"},
        {"web_origin": "http://localhost/path"},
        {"web_origin": "http://localhost:bad"},
        {"ai_development_test_connection_ids": []},
        {"ai_connection_id": str(uuid4())},
        {"ai_provider": "openai_compatible"},
        {"ai_base_url": "https://coding-intl.dashscope.aliyuncs.com/v1"},
        {"ai_model": "qwen3.7-plus-other"},
        {"ai_managed_connection": False},
    ],
)
def test_local_profile_is_fail_closed(changes):
    identifier = str(uuid4())
    cfg = config(
        environment="development",
        auth_mode="mock",
        web_origin="http://localhost:3000",
        ai_managed_connection=True,
        ai_connection_id=identifier,
        ai_development_test_connection_ids=[identifier],
        ai_base_url=CODING_PLAN_BASE_URL,
        ai_api_key="sk-sp-fixture-not-real",
    )
    cfg._local_test_connection_selected = True
    assert resolve_profile(cfg).provider == "bailian_coding_plan_test"
    with pytest.raises(ModelFailure, match="policy_denied"):
        resolve_profile(cfg.model_copy(update=changes))
    if changes.get("environment") == "production":
        assert "development_model_connections" in issues(cfg.model_copy(update=changes))


@pytest.mark.parametrize(
    "origin", ["http://localhost:3000", "https://127.0.0.1", "http://[::1]:3000"]
)
def test_only_verified_exact_local_connection_gets_profile(origin):
    identifier = str(uuid4())
    cfg = config(
        environment="development",
        auth_mode="mock",
        web_origin=origin,
        ai_managed_connection=True,
        ai_connection_id=identifier,
        ai_development_test_connection_ids=[identifier],
        ai_base_url=CODING_PLAN_BASE_URL,
        ai_api_key="sk-sp-fixture-not-real",
        ai_model_verified=False,
    )
    cfg._local_test_connection_selected = True
    assert development_connection_allowed(
        cfg, identifier, cfg.ai_provider, cfg.ai_model, cfg.ai_base_url
    )
    with pytest.raises(ModelFailure, match="not_verified"):
        resolve_profile(cfg)
    assert resolve_profile(cfg, verification_probe=True).capability_status == "documented"


def test_deployment_fields_cannot_turn_allowlist_into_global_platform_permission():
    identifier = str(uuid4())
    cfg = config(
        environment="development",
        auth_mode="mock",
        web_origin="http://localhost:3000",
        ai_managed_connection=True,
        ai_connection_id=identifier,
        ai_development_test_connection_ids=[identifier],
        ai_base_url=CODING_PLAN_BASE_URL,
        ai_api_key="sk-sp-fixture-not-real",
        _local_test_connection_selected=True,
    )
    assert not cfg._local_test_connection_selected
    assert "_local_test_connection_selected" not in cfg.model_dump()
    with pytest.raises(ModelFailure, match="policy_denied"):
        resolve_profile(cfg)


def test_allowlist_removal_fences_inflight_agent_and_keeps_saved_policy(loop, monkeypatch):
    boss = loop[0]
    row = saved(boss, monkeypatch)
    allow(monkeypatch, row["id"])
    transport(monkeypatch)
    verified = probe_connection(boss, row)
    assert enable(boss, verified).status_code == 200
    calls = transport(monkeypatch, lambda: allow(monkeypatch))
    run = advance(boss, create(boss))
    assert run["state"] == "failed" and run["error_code"] == "policy_denied"
    assert run["answer"] is None and len(calls) == 1
    with session_factory()() as db:
        invocation = db.scalar(select(ModelInvocation).where(ModelInvocation.task == "agent_read"))
        assert invocation.request_sent and invocation.charged_tokens == 15
        assert invocation.usage == {
            "input_tokens": 10,
            "output_tokens": 5,
            "cached_tokens": None,
            "reasoning_tokens": None,
        }
    assert boss.get("/ai/settings")["connection_id"] == row["id"]
    visible = boss.get("/ai/connections")[0]
    assert not visible["can_test"] and not visible["can_activate"]
    run = advance(boss, create(boss))
    assert run["error_code"] == "policy_denied" and run["step_count"] == 0 and len(calls) == 1
    assert enable(boss, verified).json()["error"]["code"] == "development_only"


def test_failed_probe_or_revoked_permission_does_not_activate(loop, monkeypatch):
    boss = loop[0]
    row = saved(boss, monkeypatch)
    allow(monkeypatch, row["id"])
    calls = transport(monkeypatch, failed=True)
    failed = boss.post(f"/ai/connections/{row['id']}/test", action(row))
    assert failed["state"] == "failed" and failed["last_error"]
    assert not failed["can_activate"] and len(calls) == 1
    assert enable(boss, failed).status_code == 409
    assert boss.get("/ai/settings")["mode"] == "platform"
    calls = transport(monkeypatch, lambda: allow(monkeypatch))
    failed = boss.post(f"/ai/connections/{row['id']}/test", action(failed))
    assert failed["state"] == "failed" and failed["last_error"] == "policy_denied"
    assert not failed["can_activate"] and len(calls) == 1


def test_mock_deployment_does_not_accept_real_identity(loop, monkeypatch):
    boss = loop[0]
    row = saved(boss, monkeypatch)
    allow(monkeypatch, row["id"])
    calls = transport(monkeypatch)
    with session_factory()() as db:
        identity = db.get(Identity, boss.user["id"])
        identity.identity_provider = "oidc"
        db.commit()
    boss.post(f"/ai/connections/{row['id']}/test", action(row), 401)
    assert calls == []


def test_local_connection_obeys_existing_tenant_quota(loop, monkeypatch):
    boss = loop[0]
    row = saved(boss, monkeypatch)
    allow(monkeypatch, row["id"])
    calls = transport(monkeypatch)
    verified = probe_connection(boss, row)
    assert enable(boss, verified, daily_call_limit=1).status_code == 200
    run = advance(boss, create(boss))
    assert run["state"] == "failed" and run["error_code"] == "budget_exceeded"
    assert len(calls) == 1


def test_local_multiread_context_has_bounded_room_without_changing_tenant_quotas(loop, monkeypatch):
    boss, _, _, depts, _, work = loop
    summary = "已核对客户资料，仍待确认剩余交付日期，需要交付协调。"
    for index in range(7):
        boss.confirm(boss.draft(work, f"第 {index + 1} 次核对：" + summary * 2))
    for index in range(2):
        other = boss.work(depts[0], title=f"核对第 {index + 1} 项交付安排")
        boss.confirm(boss.draft(other, summary))
    row = saved(boss, monkeypatch)
    allow(monkeypatch, row["id"])
    calls = transport(monkeypatch)
    verified = probe_connection(boss, row)
    assert (
        enable(
            boss, verified, daily_token_limit=50000, monthly_token_limit=100000, concurrency_limit=2
        ).status_code
        == 200
    )
    ordinary = boss.post("/ai/connections", connection_body(), 201)
    run = create(boss)
    with session_factory()() as db:
        stored = db.get(AgentRun, run["id"])
        actor = db.get(Membership, stored.actor_id)
        history = [
            execute(db, actor, stored, Proposal.model_validate(read_proposal("attention.explain"))),
            execute(
                db,
                actor,
                stored,
                Proposal.model_validate(read_proposal("work.investigate", work["id"])),
            ),
        ]
        compact = model_history(history)
        assert len(compact[0]["evidence"]) == 3
        assert compact[1]["evidence"] == [] and len(compact[1]["timeline"]) == 8
        context = {
            "question": "目前哪些交付事项需要我协调，下一步应该核实什么？",
            "work_item_id": None,
            "capabilities": {
                key: value for key, value in CATALOG.items() if key != "attention.explain"
            },
            "completed_reads": compact,
            "completed_requests": [
                {"capability": "attention.explain", "work_item_id": None},
                {"capability": "work.investigate", "work_item_id": work["id"]},
            ],
            "steps_remaining": 4,
        }
        cfg = effective_config(db, actor, allow_development_test=True)
        assert cfg.ai_max_input_tokens == 32768
        assert (cfg.ai_daily_token_limit, cfg.ai_monthly_token_limit, cfg.ai_concurrency_limit) == (
            50000,
            100000,
            2,
        )
        assert settings().ai_max_input_tokens == 24000
        assert connection_config(db.get(AIConnection, ordinary["id"])).ai_max_input_tokens == 24000
        request = ModelRequest(
            task="agent_read",
            prompt_version=PROMPT_VERSION,
            schema_version="agent-proposal-v3",
            messages=(
                Message(role="system", content=read_system(stored)),
                Message(
                    role="user",
                    content=json.dumps(context, ensure_ascii=False, separators=(",", ":")),
                ),
            ),
        )
        prepared = ModelGateway(cfg).prepare(request, Proposal)
        assert 24000 < prepared.input_token_reserve <= 32768
        with pytest.raises(ModelFailure, match="budget_exceeded"):
            ModelGateway(cfg.model_copy(update={"ai_max_input_tokens": 24000})).prepare(
                request, Proposal
            )
        # An actual larger timeline still fails; the cap is not an unlimited escape.
        for event in compact[1]["timeline"]:
            event["summary"] += summary * 10
        oversized = request.model_copy(
            update={
                "messages": (
                    request.messages[0],
                    Message(
                        role="user",
                        content=json.dumps(context, ensure_ascii=False, separators=(",", ":")),
                    ),
                )
            }
        )
        with pytest.raises(ModelFailure, match="budget_exceeded"):
            ModelGateway(cfg).prepare(oversized, Proposal)
        db.rollback()
    assert len(calls) == 1  # Preparing both accepted and rejected inputs never calls the model.


def test_background_grants_and_existing_jobs_cannot_use_local_connection(loop, monkeypatch):
    boss, _, _, _, _, work = loop
    policy = create_watch(boss)
    with session_factory()() as db:
        actor, run = background(db, policy, work)
        actor_id = actor.id
    row = saved(boss, monkeypatch)
    allow(monkeypatch, row["id"])
    calls = transport(monkeypatch)
    verified = probe_connection(boss, row)
    assert enable(boss, verified).status_code == 200
    assert boss.post("/watch/policies", watch_body(), 409)["error"]["code"] == "development_only"
    assert drain(due(policy)) == ("completed", "model_unavailable")
    from app.infrastructure.models import Membership

    with session_factory()() as db:
        blocked = step(db, db.get(Membership, actor_id), run)
        assert blocked.state == "failed" and blocked.error_code == "policy_denied"
    paused = boss.post(f"/watch/policies/{policy['id']}/actions", watch_action(policy, "pause"))
    assert (
        boss.post(f"/watch/policies/{policy['id']}/actions", watch_action(paused, "resume"), 409)[
            "error"
        ]["code"]
        == "development_only"
    )
    assert len(calls) == 1
