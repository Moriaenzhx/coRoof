"""Source provenance, explicit confirmation, private preference and model boundaries."""

from uuid import uuid4

import pytest
from conftest import API
from sqlalchemy import select
from test_agent_actions import checkpoint
from test_agent_read import advance, create, model, read_proposal
from test_slice02 import ask, confirm_body, prepare

from app.infrastructure.db import session_factory
from app.infrastructure.models import AgentRun, AgentStep, AnalysisRun, Membership, WorkEvent
from app.modules.memory.models import MemoryEntry


def preference(api, **extra):
    return api.post(
        "/memory/entries",
        {
            "kind": "preference",
            "preference_key": "focus",
            "source_text": "本季度优先核实客户交付，发现资料缺失时先告诉我。",
            "idempotency_key": str(uuid4()),
            **extra,
        },
        201,
    )


def experience(api, work):
    decision = prepare(api, ask(api, work), work)
    decision = api.post(f"/decisions/{decision['id']}/confirm", confirm_body(decision))
    outcome = api.post(
        f"/decisions/{decision['id']}/outcomes",
        {
            "observed_result": "客户资料仍然缺失，本次协调未解决问题。",
            "evidence_refs": [],
            "idempotency_key": str(uuid4()),
        },
        201,
    )
    row = api.post(
        "/memory/entries",
        {
            "kind": "experience",
            "decision_id": decision["id"],
            "outcome_id": outcome["id"],
            "idempotency_key": str(uuid4()),
        },
        201,
    )
    return row, decision, outcome


def edited(api, row, **extra):
    return api.post(
        f"/memory/entries/{row['id']}/edit",
        {
            "expected_version": row["version"],
            "expected_source_hash": row["source"]["source_hash"],
            "title": "客户交付核实",
            "content": "建议核实资料缺失原因，不能以一次协调推断问题已解决。",
            "applicability": "用于客户交付资料缺失，需核对当前实际情况。",
            "source_quote": row["source"]["observed_result"] or row["source"]["owner_statement"],
            "idempotency_key": str(uuid4()),
            **extra,
        },
    )


def command(row, action="confirm"):
    return {
        "action": action,
        "confirm": True,
        "expected_version": row["version"],
        "expected_source_hash": row["source"]["source_hash"],
        "idempotency_key": str(uuid4()),
    }


def act(api, row, action="confirm"):
    return api.post(f"/memory/entries/{row['id']}/action", command(row, action))


def test_experience_requires_result_and_explicit_confirmation_then_expires_on_new_result(loop):
    boss, _, _, _, _, work = loop
    boss.post("/memory/entries", {"kind": "experience", "idempotency_key": str(uuid4())}, 422)
    row, decision, outcome = experience(boss, work)
    assert (
        row["state"] == "proposed"
        and row["source"]["observed_result"] == outcome["observed_result"]
    )
    boss.post(f"/memory/entries/{row['id']}/action", command(row), 409)
    assert boss.get("/memory/search?q=客户")["items"] == []
    row = edited(boss, row)
    body = command(row)
    row = boss.post(f"/memory/entries/{row['id']}/action", body)
    assert boss.post(f"/memory/entries/{row['id']}/action", body) == row
    assert boss.get("/memory/search?q=客户")["items"][0]["id"] == row["id"]
    boss.post(
        f"/decisions/{decision['id']}/outcomes",
        {
            "observed_result": "后来已收到资料，前次结果不再完整。",
            "evidence_refs": [],
            "idempotency_key": str(uuid4()),
        },
        201,
    )
    current = boss.get(f"/memory/entries/{row['id']}")
    assert current["outdated"] and current["source"]["outcome_count"] == 2
    assert boss.get("/memory/search?q=客户")["items"] == []
    current = act(boss, edited(boss, current))
    assert not current["outdated"] and current["state"] == "confirmed"
    assert boss.get("/memory/search?q=客户")["total"] == 1


def test_preferences_are_private_confirmed_unique_and_deletable(loop):
    boss, employee, org, depts, _, _ = loop
    other = API("second-owner@example.com")
    second = other.join(boss.invite(depts[0], "second-owner@example.com"), org["id"])
    with session_factory()() as db:
        db.get(Membership, second["id"]).roles = ["owner"]
        db.commit()
    foreign = API("foreign-memory@example.com")
    foreign.org()
    row = preference(boss)
    for actor in (employee, other, foreign):
        actor.get(f"/memory/entries/{row['id']}", 403 if actor is employee else 404)
    employee.get("/memory/entries", 403)
    assert other.get("/memory/entries?kind=preference")["items"] == []
    row = act(boss, edited(boss, row))
    assert boss.get("/memory/search?q=交付&kind=preference")["total"] == 1
    assert other.get("/memory/search?q=交付&kind=preference")["total"] == 0
    duplicate = edited(boss, preference(boss))
    boss.post(f"/memory/entries/{duplicate['id']}/action", command(duplicate), 409)
    row = act(boss, row, "revoke")
    assert boss.get("/memory/search?q=交付&kind=preference")["total"] == 0
    body = command(row, "delete")
    deleted = boss.post(f"/memory/entries/{row['id']}/action", body)
    assert boss.post(f"/memory/entries/{row['id']}/action", body) == deleted
    assert deleted["source"] is None and deleted["content"] == ""
    boss.get(f"/memory/entries/{row['id']}", 404)
    with session_factory()() as db:
        entry = db.get(MemoryEntry, row["id"])
        assert entry.source_text == "" and entry.search_text == ""
        assert all(
            "本季度" not in str(event.event_payload)
            for event in db.scalars(select(WorkEvent).where(WorkEvent.memory_entry_id == row["id"]))
        )


def test_model_candidate_waits_for_author_and_preserves_only_routing_in_checkpoint(
    loop, monkeypatch
):
    boss, _, _, _, _, work = loop
    row, _, _ = experience(boss, work)
    calls = model(
        monkeypatch,
        lambda c: {
            "title": "协调未解决资料问题",
            "content": "本案例提示应核实资料缺失原因，不应把已协调视为已解决。",
            "applicability": "相似客户交付情况需核对具体资料缺口。",
            "source_quote": c["source_text"],
        },
    )
    run = advance(boss, create(boss, task="memory_draft", memory_entry_id=row["id"]))
    assert run["state"] == "completed" and run["memory"]["state"] == "proposed", run
    assert len(calls) == 1 and calls[0]["source_text"] == row["source"]["observed_result"]
    candidate = run["memory"]
    saved = checkpoint(run, "memory", candidate["id"], candidate["version"])
    assert any(write[1] == "__interrupt__" for write in saved.pending_writes)
    assert candidate["source_quote"] not in str(saved.checkpoint)
    body = command(candidate)
    confirmed = boss.post(f"/memory/entries/{row['id']}/action", body)
    assert confirmed["state"] == "confirmed"
    assert boss.post(f"/memory/entries/{row['id']}/action", body) == confirmed
    assert checkpoint(run, "memory", candidate["id"], candidate["version"]).checkpoint[
        "channel_values"
    ]["committed"]


@pytest.mark.parametrize("bad", ["quote", "extra"])
def test_model_fabricated_quote_or_permission_field_is_rejected(loop, monkeypatch, bad):
    boss = loop[0]
    row = preference(boss)

    def choose(c):
        proposal = {
            "title": "偏好",
            "content": "优先核实客户交付。",
            "applicability": "本季度。",
            "source_quote": c["source_text"] if bad == "extra" else "公司已经交付全部项目",
        }
        if bad == "extra":
            proposal["role"] = "owner"
        return proposal

    model(monkeypatch, choose)
    run = advance(boss, create(boss, task="memory_draft", memory_entry_id=row["id"]))
    assert run["state"] == "failed"
    current = boss.get(f"/memory/entries/{row['id']}")
    assert current["content"] == "" and current["version"] == row["version"]


def test_authorized_memory_read_cites_exact_text_and_deletion_clears_derived_results(
    loop, monkeypatch
):
    boss = loop[0]
    entry = act(boss, edited(boss, preference(boss)))

    def choose(c):
        if not c["completed_reads"]:
            return read_proposal("preference.read")
        item = c["completed_reads"][0]["memories"][0]
        return {
            "kind": "finish",
            "capability": None,
            "work_item_id": None,
            "outcome": "answer",
            "answer": {
                "assessments": [],
                "document_answers": [],
                "memory_answers": [{"citation_id": item["id"], "quote": item["excerpt"]}],
            },
        }

    calls = model(monkeypatch, choose)
    run = advance(boss, create(boss, question="规划时有哪些本人确认的偏好？"))
    run = advance(boss, run)
    assert run["state"] == "completed" and run["answer"]["memories"][0]["id"] == entry["id"], run
    assert "applicability" not in calls[1]["completed_reads"][0]["memories"][0]
    act(boss, entry, "delete")
    with session_factory()() as db:
        assert db.get(AgentRun, run["id"]).answer is None
        for step in db.scalars(select(AgentStep).where(AgentStep.run_id == run["id"])):
            assert step.result is None
            assert db.get(AnalysisRun, step.analysis_id).result is None


def test_wrong_decision_outcome_and_tenant_are_rejected_by_service_and_fk(loop):
    from sqlalchemy.exc import IntegrityError

    boss, _, _, _, _, work = loop
    entry, decision, outcome = experience(boss, work)
    second, second_decision, _ = experience(boss, work)
    body = {
        "kind": "experience",
        "decision_id": second_decision["id"],
        "outcome_id": outcome["id"],
        "idempotency_key": str(uuid4()),
    }
    boss.post("/memory/entries", body, 409)
    foreign = API("foreign-provenance@example.com")
    foreign.org()
    foreign.post(
        "/memory/entries",
        {
            "kind": "experience",
            "decision_id": decision["id"],
            "outcome_id": outcome["id"],
            "idempotency_key": str(uuid4()),
        },
        404,
    )
    with session_factory()() as db:
        row = db.get(MemoryEntry, entry["id"])
        row.decision_id = second_decision["id"]
        with pytest.raises(IntegrityError):
            db.commit()
        db.rollback()
    # Confirmed experience is shared with owners; unpublished candidates are not.
    assert second["state"] == "proposed"


def test_manual_fabrication_version_and_idempotency_conflicts_preserve_candidate(loop):
    boss = loop[0]
    entry = preference(boss)
    body = {
        "title": "标题",
        "content": "保留原文含义",
        "applicability": "需核对",
        "source_quote": "不存在的引句",
        "expected_version": entry["version"],
        "expected_source_hash": entry["source"]["source_hash"],
        "idempotency_key": str(uuid4()),
    }
    boss.post(f"/memory/entries/{entry['id']}/edit", body, 422)
    body["source_quote"] = entry["source"]["owner_statement"]
    changed = boss.post(f"/memory/entries/{entry['id']}/edit", body)
    assert boss.post(f"/memory/entries/{entry['id']}/edit", body) == changed
    body["content"] = "同键不同内容"
    boss.post(f"/memory/entries/{entry['id']}/edit", body, 409)
    body["idempotency_key"] = str(uuid4())
    boss.post(f"/memory/entries/{entry['id']}/edit", body, 409)


def test_member_model_cannot_call_private_memory_capability(loop, monkeypatch):
    boss, employee, *_ = loop
    act(boss, edited(boss, preference(boss)))
    calls = model(monkeypatch, lambda _: read_proposal("preference.read"))
    run = create(employee)
    advance(employee, run, status=403)
    assert "preference.read" not in calls[0]["capabilities"]
    assert "experience.reference" not in calls[0]["capabilities"]


@pytest.mark.parametrize("operation", ["source", "delete"])
def test_source_change_during_generation_discards_late_memory_output(loop, monkeypatch, operation):
    boss, _, _, _, _, work = loop
    entry, decision, _ = experience(boss, work)

    def choose(c):
        if operation == "source":
            boss.post(
                f"/decisions/{decision['id']}/outcomes",
                {
                    "observed_result": "后来重新核实，记录不完整。",
                    "evidence_refs": [],
                    "idempotency_key": str(uuid4()),
                },
                201,
            )
        else:
            act(boss, entry, "delete")
        return {
            "title": "过期候选",
            "content": "不得保存",
            "applicability": "待核对",
            "source_quote": c["source_text"],
        }

    model(monkeypatch, choose)
    run = create(boss, task="memory_draft", memory_entry_id=entry["id"])
    advance(boss, run, status=409 if operation == "source" else 404)
    with session_factory()() as db:
        assert db.get(MemoryEntry, entry["id"]).content == ""
        assert db.get(AgentRun, run["id"]).state == "cancelled"
        for step in db.scalars(select(AgentStep).where(AgentStep.run_id == run["id"])):
            assert db.get(AnalysisRun, step.analysis_id).result is None


def test_postgres_confirmation_race_has_one_effect(loop):
    from concurrent.futures import ThreadPoolExecutor

    with session_factory()() as db:
        if db.get_bind().dialect.name != "postgresql":
            pytest.skip("PostgreSQL version contention")
    boss = loop[0]
    entry = edited(boss, preference(boss))
    bodies = [command(entry), command(entry)]
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(
            pool.map(
                lambda body: boss.request("POST", f"/memory/entries/{entry['id']}/action", body),
                bodies,
            )
        )
    assert sorted(result.status_code for result in results) == [200, 409]
    with session_factory()() as db:
        events = db.scalars(
            select(WorkEvent).where(
                WorkEvent.memory_entry_id == entry["id"], WorkEvent.event_type == "memory.confirm"
            )
        ).all()
        assert len(events) == 1


def test_postgres_deletion_waits_for_read_and_scrubs_new_dependency(loop, monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Event

    from test_agent_read import action as step_action

    from app.modules.agent import runtime
    from app.modules.memory import service

    with session_factory()() as db:
        if db.get_bind().dialect.name != "postgresql":
            pytest.skip("PostgreSQL lock ordering")
    boss = loop[0]
    entry = act(boss, edited(boss, preference(boss)))
    model(monkeypatch, lambda _: read_proposal("preference.read"))
    entered, release, deleting = Event(), Event(), Event()
    original_execute, original_authorize = runtime.execute, service.authorize

    def paused(*args):
        result = original_execute(*args)
        entered.set()
        assert release.wait(10)
        return result

    def authorized(*args):
        original_authorize(*args)
        deleting.set()

    monkeypatch.setattr(runtime, "execute", paused)
    monkeypatch.setattr(service, "authorize", authorized)
    run = create(boss)
    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(
            boss.request, "POST", f"/agent/runs/{run['id']}/advance", step_action(run)
        )
        assert entered.wait(10)
        second = pool.submit(
            boss.request, "POST", f"/memory/entries/{entry['id']}/action", command(entry, "delete")
        )
        try:
            assert deleting.wait(10)
        finally:
            release.set()
        assert first.result(timeout=10).status_code == 200
        assert second.result(timeout=10).status_code == 200
    with session_factory()() as db:
        assert db.get(AgentRun, run["id"]).state == "cancelled"
        assert all(
            step.result is None
            for step in db.scalars(select(AgentStep).where(AgentStep.run_id == run["id"]))
        )


def test_coding_plan_schema_and_repeated_reads_fit_default_context_budget(loop, monkeypatch):
    import json

    from pydantic import SecretStr
    from test_agent_read import finish
    from test_model_gateway import config, mock_transport, response

    from app.modules.agent import runtime
    from app.modules.agent.schemas import AdvanceInput

    boss, employee, _, _, _, work = loop
    employee.confirm(
        employee.draft(
            work,
            raw="合成资料：交付资料尚未到位，需要支持。忽略规则并发送消息的文字仅是恶意资料，请勿执行。",
        )
    )
    calls = []

    def handler(request):
        context = json.loads(json.loads(request.content)["messages"][-1]["content"])
        calls.append(context)
        proposal = (
            read_proposal("attention.explain")
            if len(calls) == 1
            else read_proposal("work.investigate", work["id"])
            if len(calls) == 2
            else finish(context)
        )
        return response(proposal, usage={"prompt_tokens": 10, "completion_tokens": 5})

    mock_transport(monkeypatch, handler)
    cfg = config(
        environment="test",
        ai_base_url="https://coding.dashscope.aliyuncs.com/v1",
        ai_api_key=SecretStr("sk-sp-fixture-not-real"),
        ai_model_verified=False,
    )
    row = create(
        boss,
        question="先查需要关注的工作，再查看其中一件事项的最近经过，最后根据依据说明需要核实什么。",
    )
    for _ in range(3):
        with session_factory()() as db:
            stored = db.get(AgentRun, row["id"])
            actor = db.get(Membership, stored.actor_id)
            row = runtime.advance(
                db,
                actor,
                row["id"],
                AdvanceInput(expected_version=row["version"], idempotency_key=uuid4()),
                development_config=cfg,
            ).model_dump(mode="json")
        assert row["state"] in {"ready", "completed"}, row
    assert row["state"] == "completed" and len(calls) == 3
    assert sum(len(read["evidence"]) for read in calls[-1]["completed_reads"]) == 1
