"""Conversation context is bounded, authorized and never a factual shortcut."""

import json
from datetime import timedelta
from uuid import uuid4

import pytest
from alembic import command
from conftest import API
from sqlalchemy import func, inspect, select
from sqlalchemy.exc import IntegrityError
from test_agent_read import advance, create, finish, model, read_proposal

from app.infrastructure.db import session_factory
from app.infrastructure.models import AgentRun, ModelInvocation, now


def completed(api, **fields):
    row = create(api, **fields)
    row = advance(api, row)
    return advance(api, row)


def payload(parent, **fields):
    return {
        "question": "其中哪一项应该先核实？",
        "parent_run_id": parent["id"],
        "idempotency_key": str(uuid4()),
        **fields,
    }


def test_followup_prioritizes_direct_parent_and_rereads_facts(loop, monkeypatch):
    boss = loop[0]
    calls = model(monkeypatch)
    parent = completed(boss, question="祖代独有问题：有什么事项需要核实？")
    body = payload(parent)
    child = boss.post("/agent/runs", body, 201)
    assert child["parent_run_id"] == parent["id"]
    assert boss.post("/agent/runs", body, 201)["id"] == child["id"]
    assert len(calls) == 2
    child = advance(boss, child)
    assert calls[-1]["completed_reads"] == []
    assert calls[-1]["previous_turn"]["question"] == parent["question"]
    assert "必须重新读取" in calls[-1]["previous_turn"]["notice"]
    child = advance(boss, child)
    assert child["state"] == "completed" and len(calls) == 4
    grandchild = boss.post("/agent/runs", payload(child, question="这一步具体怎么核实？"), 201)
    advance(boss, grandchild)
    previous = calls[-1]["previous_turn"]
    assert previous["question"] == child["question"]
    assert previous["earlier_turns"][0]["question"] == parent["question"]
    assert len(json.dumps(previous, ensure_ascii=False, separators=(",", ":")).encode()) <= 1800
    assert "previous_turn" not in previous
    assert (
        boss.post("/agent/runs", {**body, "parent_run_id": child["id"]}, 409)["error"]["code"]
        == "idempotency_conflict"
    )


@pytest.mark.parametrize(
    "case", ["other_member", "other_tenant", "new_session", "not_completed", "missing", "expired"]
)
def test_invalid_parent_is_rejected_without_model_call_or_disclosing_context(
    loop, monkeypatch, case
):
    boss, employee, org, *_ = loop
    calls = model(monkeypatch)
    parent = completed(boss, question="只在本次父任务中的问题")
    caller = boss
    if case == "other_member":
        caller = employee
    elif case == "other_tenant":
        caller = API("foreign-followup@example.com")
        caller.org()
    elif case == "new_session":
        caller = API("owner@example.com")
        caller.client.headers["X-Organization-Id"] = org["id"]
    elif case == "not_completed":
        parent = create(boss)
    elif case == "missing":
        parent = {"id": str(uuid4())}
    elif case == "expired":
        with session_factory()() as db:
            db.get(AgentRun, parent["id"]).created_at = now() - timedelta(hours=25)
            db.commit()
    result = caller.post("/agent/runs", payload(parent), 409)
    assert result["error"]["code"] == "parent_context_unavailable"
    assert "只在本次父任务中的问题" not in json.dumps(result, ensure_ascii=False)
    assert len(calls) == 2


def test_parent_expiring_after_create_prevents_advance_and_history_read(loop, monkeypatch):
    boss = loop[0]
    calls = model(monkeypatch)
    parent = completed(boss)
    child = boss.post("/agent/runs", payload(parent), 201)
    with session_factory()() as db:
        db.get(AgentRun, parent["id"]).created_at = now() - timedelta(hours=25)
        before = db.scalar(select(func.count()).select_from(ModelInvocation))
        db.commit()
    assert advance(boss, child, status=409)["error"]["code"] == "parent_context_unavailable"
    assert (
        boss.get(f"/agent/runs/{child['id']}", 409)["error"]["code"] == "parent_context_unavailable"
    )
    assert len(calls) == 2
    with session_factory()() as db:
        assert db.scalar(select(func.count()).select_from(ModelInvocation)) == before


def test_parent_source_changes_fail_closed_and_drafts_cannot_inherit_context(loop, monkeypatch):
    boss, _, _, _, _, work = loop
    calls = model(monkeypatch)
    parent = completed(boss)
    # A work-bound query must not borrow a broader previous context.
    assert (
        boss.post("/agent/runs", payload(parent, work_item_id=work["id"]), 409)["error"]["code"]
        == "parent_context_unavailable"
    )
    boss.post("/agent/runs", payload(parent, task="update_draft", work_item_id=work["id"]), 422)
    boss.confirm(boss.draft(work))
    assert (
        boss.post("/agent/runs", payload(parent), 409)["error"]["code"]
        == "parent_context_unavailable"
    )
    assert len(calls) == 2


def test_followup_context_is_bounded_without_reusing_prior_citations_as_current_reads(
    loop, monkeypatch
):
    boss = loop[0]

    def verbose(context):
        if not context["completed_reads"]:
            return read_proposal()
        answer = finish(context)
        for assessment in answer["answer"]["assessments"]:
            assessment["interpretation"] = "根据当前记录逐项核实，并由负责人确认后继续。" * 20
        return answer

    calls = model(monkeypatch, verbose)
    parent = completed(boss, question="请核实当前事项的支持需求。" * 40)
    row = boss.post("/agent/runs", payload(parent), 201)
    advance(boss, row)
    current = calls[-1]
    assert current["completed_reads"] == []
    assert (
        len(
            json.dumps(current["previous_turn"], ensure_ascii=False, separators=(",", ":")).encode()
        )
        <= 1800
    )
    assert "evidence" not in current["previous_turn"]


def test_parent_migration_preserves_existing_runs_and_enforces_tenant_reference(
    loop, monkeypatch, database
):
    boss, *_ = loop
    model(monkeypatch)
    parent = completed(boss)
    command.downgrade(database, "0016_attention")
    with session_factory()() as db:
        assert "parent_run_id" not in {
            column["name"] for column in inspect(db.get_bind()).get_columns("agent_runs")
        }
    command.upgrade(database, "head")
    assert boss.get(f"/agent/runs/{parent['id']}")["state"] == "completed"
    foreign = API("cross-tenant-parent@example.com")
    foreign.org()
    other = create(foreign)
    with session_factory()() as db:
        db.get(AgentRun, other["id"]).parent_run_id = parent["id"]
        with pytest.raises(IntegrityError):
            db.commit()
        db.rollback()
        db.get(AgentRun, parent["id"]).parent_run_id = parent["id"]
        with pytest.raises(IntegrityError):
            db.commit()
        db.rollback()
