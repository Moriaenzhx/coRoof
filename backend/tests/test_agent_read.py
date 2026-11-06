import json
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from threading import Event
from uuid import uuid4

import pytest
from alembic import command
from conftest import API
from sqlalchemy import func, select, text
from sqlalchemy.exc import IntegrityError
from test_model_gateway import mock_transport, response, setup_model

from app.core.auth import token_hash
from app.infrastructure.db import session_factory
from app.infrastructure.models import (
    AgentRun,
    AgentStep,
    AISettings,
    AuthSession,
    Membership,
    ModelInvocation,
    WorkEvent,
    WorkItem,
    now,
)


def create(api, work=None, **extra):
    return api.post(
        "/agent/runs",
        {
            "question": "有哪些事项需要核实？",
            "work_item_id": work["id"] if work else None,
            "idempotency_key": str(uuid4()),
            **extra,
        },
        201,
    )


def action(row):
    return {"expected_version": row["version"], "idempotency_key": str(uuid4())}


def advance(api, row, body=None, status=200):
    return api.post(f"/agent/runs/{row['id']}/advance", body or action(row), status)


def read_proposal(capability="company.overview", work_id=None):
    return {
        "kind": "read",
        "capability": capability,
        "work_item_id": work_id,
        "answer": None,
        "outcome": None,
    }


def finish(context):
    evidence = [e for result in context["completed_reads"] for e in result["evidence"]]
    return {
        "kind": "finish",
        "capability": None,
        "work_item_id": None,
        "answer": {
            "assessments": [
                {
                    "evidence_id": evidence[0]["id"],
                    "quote": evidence[0]["excerpt"],
                    "interpretation": "建议核实当前记录及支持安排。",
                    "action_keys": ["verify"],
                }
            ]
            if evidence
            else []
        },
        "outcome": "answer" if evidence else "insufficient_data",
    }


def model(monkeypatch, choose=None):
    setup_model(monkeypatch)
    calls = []

    def handle(request):
        context = json.loads(json.loads(request.content)["messages"][1]["content"])
        calls.append(context)
        proposal = (
            choose(context)
            if choose
            else (read_proposal() if not context["completed_reads"] else finish(context))
        )
        return response(proposal, usage={"prompt_tokens": 10, "completion_tokens": 5})

    mock_transport(monkeypatch, handle)
    return calls


def test_failed_model_call_preserves_safe_provider_request_id_without_retry(loop, monkeypatch):
    from app.modules.model_gateway.contracts import ModelFailure
    from app.modules.model_gateway.gateway import ModelGateway

    boss, *_ = loop
    setup_model(monkeypatch)
    attempts = []

    def unavailable(*args):
        attempts.append(True)
        raise ModelFailure("unavailable", sent=True, provider_request_id="safe-request-fixture")

    monkeypatch.setattr(ModelGateway, "generate", unavailable)
    initial = create(boss, question="今天有哪些事需要我处理？")
    command = action(initial)
    row = advance(boss, initial, command)
    assert row["state"] == "failed" and row["error_code"] == "unavailable"
    assert row["answer"] is None and row["steps"][0]["capability"] is None
    assert advance(boss, initial, command) == row and attempts == [True]
    with session_factory()() as db:
        invocation = db.scalars(select(ModelInvocation)).one()
        assert invocation.provider_request_id == "safe-request-fixture"
        assert invocation.request_sent and invocation.charged_tokens > 0
        assert invocation.error_code == "unavailable"


def test_authorized_read_loop_uses_real_tool_results_and_persists_cited_answer(loop, monkeypatch):
    boss, _, org, _, _, work = loop
    calls = model(monkeypatch)
    foreign = API("foreign-agent@example.com")
    foreign.org()
    secret = foreign.work(foreign.department(), title="别的企业敏感事项")
    with session_factory()() as db:
        before = db.scalar(
            select(func.count())
            .select_from(WorkEvent)
            .where(WorkEvent.organization_id == org["id"])
        )
    row = create(boss)
    first = action(row)
    row = advance(boss, row, first)
    assert row["state"] == "ready" and row["step_count"] == 1
    assert advance(boss, row, first) == row and len(calls) == 1
    row = advance(boss, row)
    assert row["state"] == "completed" and len(calls) == 2
    assert row["answer"]["mode"] == "model"
    assert row["answer"]["evidence"][0]["work_item_id"] == work["id"]
    assert row["answer"]["suggestions"][0]["evidence_id"] == row["answer"]["evidence"][0]["id"]
    assert secret["id"] not in json.dumps(calls, ensure_ascii=False)
    assert org["id"] not in json.dumps(calls)
    assert "organization_id" not in json.dumps(calls)
    assert "别的企业敏感事项" not in json.dumps(calls, ensure_ascii=False)
    assert boss.get(f"/agent/runs/{row['id']}") == row
    with session_factory()() as db:
        assert (
            db.scalar(
                select(func.count())
                .select_from(WorkEvent)
                .where(WorkEvent.organization_id == org["id"])
            )
            == before
        )
        assert (
            len(
                db.scalars(
                    select(ModelInvocation).where(ModelInvocation.organization_id == org["id"])
                ).all()
            )
            == 2
        )
        assert "hidden-reasoning-not-to-persist" not in json.dumps(
            db.get(AgentRun, row["id"]).answer
        )


@pytest.mark.parametrize(
    "capability", ["attention.explain", "work.investigate", "coverage.explain"]
)
def test_registered_capabilities_return_authorized_results(loop, monkeypatch, capability):
    boss, _, _, _, _, work = loop
    boss.confirm(boss.draft(work))
    calls = model(
        monkeypatch,
        lambda c: (
            read_proposal(capability, work["id"] if capability == "work.investigate" else None)
            if not c["completed_reads"]
            else finish(c)
        ),
    )
    row = advance(boss, create(boss, work))
    row = advance(boss, row)
    assert row["state"] == "completed"
    result = calls[1]["completed_reads"][0]
    assert result["authorized_work_count"] == 1
    if capability == "work.investigate":
        assert result["timeline"] and result["evidence"]
    if capability == "attention.explain":
        assert result["signals"]
    if capability == "coverage.explain":
        assert result["evidence"] == [] and "尚未接入" in result["notice"]


def test_creation_idempotency_and_scope_forgery(loop):
    boss, employee, _, departments, _, work = loop
    key = str(uuid4())
    row = create(employee, work, idempotency_key=key)
    assert create(employee, work, idempotency_key=key)["id"] == row["id"]
    assert boss.request("GET", f"/agent/runs/{row['id']}").status_code == 404
    hidden = boss.work(departments[1])
    assert (
        employee.request(
            "POST",
            "/agent/runs",
            {"question": "读秘密", "work_item_id": hidden["id"], "idempotency_key": str(uuid4())},
        ).status_code
        == 404
    )
    assert (
        employee.request(
            "POST",
            "/agent/runs",
            {"question": "换问题", "work_item_id": work["id"], "idempotency_key": key},
        ).status_code
        == 409
    )
    assert (
        employee.request(
            "POST",
            "/agent/runs",
            {"question": "提权", "role": "owner", "idempotency_key": str(uuid4())},
        ).status_code
        == 422
    )


@pytest.mark.parametrize(
    "change", ["unknown_capability", "organization", "approved", "tool_url", "script"]
)
def test_untrusted_proposals_never_execute(loop, monkeypatch, change):
    boss, _, _, _, _, _ = loop

    def proposal(_):
        value = read_proposal()
        if change == "unknown_capability":
            value["capability"] = "work.delete"
        else:
            value[change] = "untrusted"
        return value

    model(monkeypatch, proposal)
    row = advance(boss, create(boss))
    assert row["state"] == "failed" and row["error_code"] == "invalid_output"
    with session_factory()() as db:
        step = db.scalar(select(AgentStep).where(AgentStep.run_id == row["id"]))
        assert step.result is None and step.capability is None


def test_model_selected_foreign_work_is_rejected_before_tool_output(loop, monkeypatch):
    boss, employee, _, departments, _, work = loop
    hidden = boss.work(departments[1])
    model(monkeypatch, lambda _: read_proposal("work.investigate", hidden["id"]))
    row = create(employee)
    response = employee.request("POST", f"/agent/runs/{row['id']}/advance", action(row))
    assert response.status_code == 404
    with session_factory()() as db:
        assert db.get(AgentRun, row["id"]).state == "failed"
        assert db.scalar(select(AgentStep).where(AgentStep.run_id == row["id"])).result is None


def test_repeated_read_stops_without_reexecuting(loop, monkeypatch):
    boss, *_ = loop
    calls = model(monkeypatch, lambda _: read_proposal())
    row = advance(boss, create(boss))
    row = advance(boss, row)
    assert row["state"] == "failed" and row["error_code"] == "no_progress" and len(calls) == 2


def test_empty_coverage_cannot_be_used_as_invented_evidence(loop, monkeypatch):
    boss, *_ = loop

    def choose(context):
        if not context["completed_reads"]:
            return read_proposal("coverage.explain")
        return {
            "kind": "finish",
            "capability": None,
            "work_item_id": None,
            "outcome": "insufficient_data",
            "answer": {
                "assessments": [
                    {
                        "evidence_id": "invented-coverage",
                        "quote": "不存在的来源",
                        "interpretation": "资料需要核实。",
                        "action_keys": ["verify"],
                    }
                ]
            },
        }

    model(monkeypatch, choose)
    row = advance(boss, advance(boss, create(boss)))
    assert row["state"] == "failed" and row["error_code"] == "invalid_evidence"
    assert row["steps"][-1]["error_code"] == "invalid_citation"
    assert row["answer"] is None


def test_cited_partial_answer_cannot_claim_empty_insufficient_data_outcome(loop, monkeypatch):
    boss, *_ = loop

    def choose(context):
        if not context["completed_reads"]:
            return read_proposal()
        proposal = finish(context)
        proposal["outcome"] = "insufficient_data"
        return proposal

    model(monkeypatch, choose)
    row = advance(boss, advance(boss, create(boss)))
    assert row["state"] == "failed" and row["error_code"] == "invalid_evidence"
    assert row["steps"][-1]["error_code"] == "outcome_mismatch"
    assert row["answer"] is None


def test_scope_change_hides_old_context_including_aggregate(loop, monkeypatch):
    boss, employee, _, _, _, work = loop
    calls = model(monkeypatch)
    row = advance(employee, create(employee))
    with session_factory()() as db:
        db.get(WorkItem, work["id"]).owner_id = None
        db.commit()
    assert employee.request("GET", f"/agent/runs/{row['id']}").status_code == 409
    assert (
        employee.request("POST", f"/agent/runs/{row['id']}/advance", action(row)).status_code == 409
    )
    assert len(calls) == 1


@pytest.mark.parametrize("change", ["membership", "session", "work"])
def test_revocation_during_model_call_blocks_tool_and_result(loop, monkeypatch, change):
    _, employee, _, _, member, work = loop

    def revoke(_):
        with session_factory()() as db:
            if change == "membership":
                db.get(Membership, member["id"]).status = "inactive"
            elif change == "session":
                db.delete(
                    db.get(AuthSession, token_hash(employee.client.cookies.get("coroof_session")))
                )
            else:
                db.get(WorkItem, work["id"]).owner_id = None
            db.commit()
        return read_proposal()

    model(monkeypatch, revoke)
    row = create(employee)
    result = employee.request("POST", f"/agent/runs/{row['id']}/advance", action(row))
    assert result.status_code in {401, 403, 409}
    with session_factory()() as db:
        assert db.get(AgentRun, row["id"]).answer is None
        step = db.scalar(select(AgentStep).where(AgentStep.run_id == row["id"]))
        assert step.result is None
        call = db.scalar(
            select(ModelInvocation).where(ModelInvocation.analysis_run_id == step.analysis_id)
        )
        assert call.error_code == "access_revoked" and call.charged_tokens == 15


def test_cancel_during_model_call_is_persistent_and_prevents_read(loop, monkeypatch):
    boss, *_ = loop
    target = {}

    def cancel(_):
        current = boss.get(f"/agent/runs/{target['id']}")
        boss.post(f"/agent/runs/{target['id']}/cancel", {"expected_version": current["version"]})
        return read_proposal()

    model(monkeypatch, cancel)
    row = create(boss)
    target["id"] = row["id"]
    row = advance(boss, row)
    assert row["state"] == "cancelled" and row["answer"] is None
    with session_factory()() as db:
        assert db.scalar(select(AgentStep).where(AgentStep.run_id == row["id"])).result is None


def test_budget_deadline_and_missing_model_do_not_make_network_calls(loop, monkeypatch):
    boss, *_ = loop
    row = advance(boss, create(boss))
    assert row["state"] == "failed" and row["error_code"] == "not_configured"
    calls = model(monkeypatch)
    row = create(boss)
    with session_factory()() as db:
        db.get(AgentRun, row["id"]).deadline = now() - timedelta(seconds=1)
        db.commit()
    row = advance(boss, row)
    assert row["error_code"] == "budget_exceeded" and calls == []
    setup_model(monkeypatch, DAILY_CALL_LIMIT=1)
    row = advance(boss, create(boss))
    row = advance(boss, row)
    assert row["error_code"] == "budget_exceeded" and len(calls) == 1


@pytest.mark.parametrize(
    "policy_mode,expected",
    [(None, "not_configured"), ("platform", "not_configured"), ("disabled", "model_disabled")],
)
def test_model_preflight_distinguishes_disabled_from_missing_config(
    loop, monkeypatch, policy_mode, expected
):
    boss, _, org, *_ = loop
    calls = model(monkeypatch)
    if policy_mode != "disabled":
        setup_model(monkeypatch, PROVIDER="rules", API_KEY="", MODEL="")
    with session_factory()() as db:
        if policy_mode:
            db.add(
                AISettings(
                    organization_id=org["id"],
                    mode=policy_mode,
                    version=7,
                    daily_call_limit=100,
                    daily_token_limit=200000,
                    monthly_token_limit=6000000,
                    concurrency_limit=2,
                )
            )
            db.commit()
    row = advance(boss, create(boss))
    assert row["state"] == "failed" and row["error_code"] == expected
    assert row["answer"] is None and row["step_count"] == 0 and calls == []
    with session_factory()() as db:
        assert (
            db.scalar(
                select(func.count())
                .select_from(ModelInvocation)
                .where(ModelInvocation.organization_id == org["id"])
            )
            == 0
        )
        assert (
            db.scalar(
                select(func.count()).select_from(AgentStep).where(AgentStep.run_id == row["id"])
            )
            == 0
        )
        stored_policy = db.scalar(select(AISettings).where(AISettings.organization_id == org["id"]))
        if policy_mode:
            assert stored_policy.mode == policy_mode and stored_policy.version == 7
        else:
            assert stored_policy is None


@pytest.mark.parametrize("revision,expected", [(0, "not_verified"), (7, None)])
def test_explicit_acceptance_keeps_config_revision_checks_with_disabled_policy(
    loop, monkeypatch, revision, expected
):
    from test_model_gateway import config

    from app.modules.agent.runtime import advance as internal_advance
    from app.modules.agent.schemas import AdvanceInput

    boss, _, org, *_ = loop
    calls = model(monkeypatch)
    with session_factory()() as db:
        db.add(
            AISettings(
                organization_id=org["id"],
                mode="disabled",
                version=7,
                daily_call_limit=100,
                daily_token_limit=200000,
                monthly_token_limit=6000000,
                concurrency_limit=2,
            )
        )
        db.commit()
    row = create(boss)
    with session_factory()() as db:
        stored = db.get(AgentRun, row["id"])
        actor = db.get(Membership, stored.actor_id)
        result = internal_advance(
            db,
            actor,
            stored.id,
            AdvanceInput.model_validate(action(row)),
            development_config=config(environment="test", ai_config_revision=revision),
        )
        assert result.error_code == expected
        assert result.state == ("failed" if expected else "ready")
        assert len(calls) == (0 if expected else 1)
        current = db.scalar(select(AISettings).where(AISettings.organization_id == org["id"]))
        assert current.mode == "disabled" and current.version == 7


def test_step_limit_blocks_seventh_model_call(loop, monkeypatch):
    # Isolate the step ceiling from the independently tested byte/token ceiling.
    monkeypatch.setenv("COROOF_AI_MAX_INPUT_TOKENS", "64000")
    monkeypatch.setenv("COROOF_AI_DAILY_TOKEN_LIMIT", "1000000")
    boss, _, _, departments, _, _ = loop
    targets = [boss.work(departments[0], title=f"合成步骤额度事项 {n}")["id"] for n in range(6)]
    index = 0

    def choose(_):
        nonlocal index
        result = read_proposal("work.investigate", targets[index])
        index += 1
        return result

    calls = model(monkeypatch, choose)
    row = create(boss)
    for _ in range(7):
        row = advance(boss, row)
    assert row["state"] == "failed" and row["error_code"] == "budget_exceeded"
    assert row["step_count"] == 6 and len(calls) == 6


def test_developer_profile_is_only_allowed_in_explicit_test_runtime(loop, monkeypatch):
    from test_model_gateway import config

    from app.core.config import settings
    from app.modules.agent.runtime import advance as internal_advance
    from app.modules.agent.schemas import AdvanceInput

    boss, *_ = loop
    calls = model(monkeypatch)
    row = create(boss)
    monkeypatch.setenv("COROOF_ENVIRONMENT", "development")
    settings.cache_clear()
    with session_factory()() as db:
        stored = db.get(AgentRun, row["id"])
        actor = db.get(Membership, stored.actor_id)
        result = internal_advance(
            db,
            actor,
            stored.id,
            AdvanceInput.model_validate(action(row)),
            development_config=config(environment="test"),
        )
        assert result.state == "failed" and result.error_code == "policy_denied"
    assert calls == []


def test_expired_lease_requires_explicit_resume_and_never_replays_unknown_step(loop, monkeypatch):
    boss, *_ = loop
    calls = model(monkeypatch)
    row = create(boss)
    with session_factory()() as db:
        stored = db.get(AgentRun, row["id"])
        stored.state, stored.step_count = "running", 1
        stored.lease_expires_at = now() - timedelta(seconds=1)
        db.add(
            AgentStep(
                organization_id=stored.organization_id,
                run_id=stored.id,
                request_key=str(uuid4()),
                expected_version=1,
                ordinal=1,
            )
        )
        db.commit()
    row = boss.get(f"/agent/runs/{row['id']}")
    assert row["state"] == "interrupted" and row["steps"][0]["state"] == "unknown"
    assert calls == []
    row = boss.post(f"/agent/runs/{row['id']}/resume", {"expected_version": row["version"]})
    row = advance(boss, row)
    assert row["step_count"] == 2 and row["steps"][0]["state"] == "unknown" and len(calls) == 1


def test_concurrent_advance_has_single_admission(loop, monkeypatch):
    with session_factory()() as db:
        if db.get_bind().dialect.name != "postgresql":
            pytest.skip("PostgreSQL row locks required")
    boss, *_ = loop
    entered, release = Event(), Event()

    def wait(_):
        entered.set()
        assert release.wait(10)
        return read_proposal()

    calls = model(monkeypatch, wait)
    row = create(boss)
    body = action(row)
    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(boss.request, "POST", f"/agent/runs/{row['id']}/advance", body)
        assert entered.wait(10)
        try:
            duplicate = boss.post(f"/agent/runs/{row['id']}/advance", body)
            assert duplicate["state"] == "running"
            assert (
                boss.request("POST", f"/agent/runs/{row['id']}/advance", action(row)).status_code
                == 409
            )
        finally:
            release.set()
        assert first.result(timeout=10).status_code == 200
    assert len(calls) == 1


def test_late_response_cannot_overwrite_explicitly_resumed_run(loop, monkeypatch):
    boss, *_ = loop
    target = {}

    def late(_):
        with session_factory()() as db:
            stored = db.get(AgentRun, target["id"])
            stored.lease_expires_at = now() - timedelta(seconds=1)
            db.commit()
        current = boss.get(f"/agent/runs/{target['id']}")
        assert current["state"] == "interrupted"
        boss.post(f"/agent/runs/{target['id']}/resume", {"expected_version": current["version"]})
        return read_proposal()

    model(monkeypatch, late)
    row = create(boss)
    target["id"] = row["id"]
    row = advance(boss, row)
    assert row["state"] == "ready" and row["steps"][0]["state"] == "unknown"
    with session_factory()() as db:
        assert db.scalar(select(AgentStep).where(AgentStep.run_id == row["id"])).result is None


def test_disabling_ai_during_model_call_prevents_following_query(loop, monkeypatch):
    boss, *_ = loop

    def disable(_):
        response = boss.request(
            "PUT",
            "/ai/settings",
            {
                "expected_version": 0,
                "mode": "disabled",
                "connection_id": None,
                "daily_call_limit": 100,
                "daily_token_limit": 200000,
                "monthly_token_limit": 6000000,
                "concurrency_limit": 2,
                "alert_percent": 80,
            },
        )
        assert response.status_code == 200
        return read_proposal()

    model(monkeypatch, disable)
    row = advance(boss, create(boss))
    assert row["state"] == "failed" and row["error_code"] == "not_verified"
    with session_factory()() as db:
        assert db.scalar(select(AgentStep).where(AgentStep.run_id == row["id"])).result is None


def test_manager_catalog_and_context_are_limited_to_authorized_department(loop, monkeypatch):
    boss, _, org, departments, _, _ = loop
    manager = API("agent-manager@example.com")
    manager.join(boss.invite(departments[1], "agent-manager@example.com", ["manager"]), org["id"])
    visible = boss.work(departments[1], title="负责人可见的合成工作")
    calls = model(monkeypatch)
    row = advance(manager, create(manager))
    row = advance(manager, row)
    assert row["state"] == "completed"
    assert row["answer"]["authorized_work_count"] == 1
    assert row["answer"]["evidence"][0]["work_item_id"] == visible["id"]
    assert calls[1]["completed_reads"][0]["scope"] == "authorized_work"


def test_agent_migration_preserves_prior_facts_and_rejects_foreign_references(database, loop):
    boss, _, org, _, member, work = loop
    command.downgrade(database, "0004_ai_management")
    command.upgrade(database, "head")
    command.check(database)
    other = API("migration-agent@example.com")
    foreign = other.org()
    row = create(boss)
    with session_factory()() as db:
        assert db.get(WorkItem, work["id"])
        with pytest.raises(IntegrityError):
            db.execute(
                text("UPDATE agent_runs SET organization_id = :org WHERE id = :id"),
                {"org": foreign["id"], "id": row["id"]},
            )
            db.flush()
        db.rollback()
        assert db.get(AgentRun, row["id"]).organization_id == org["id"]
