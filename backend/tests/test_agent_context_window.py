"""Three independently authorized turns share one bounded context, without extra calls."""

import json
from datetime import timedelta

import pytest
from sqlalchemy import func, select
from test_agent_followup import completed, payload
from test_agent_read import advance, model, read_proposal
from test_agent_read import create as run
from test_knowledge import create as document
from test_knowledge import publish

from app.infrastructure.db import session_factory
from app.infrastructure.models import AgentRun, ModelInvocation, now
from app.modules.agent.runtime import parent_turn


def chain(boss, count=3, **fields):
    rows = []
    for index in range(count):
        rows.append(
            completed(
                boss,
                question=f"第{index + 1}轮独有问题：哪些事项需要核实？",
                **({"parent_run_id": rows[-1]["id"]} if rows else {}),
                **fields,
            )
        )
    return rows


def test_context_contains_only_three_own_turns_and_rereads_current_facts(loop, monkeypatch):
    boss = loop[0]
    calls = model(monkeypatch)
    rows = chain(boss, 4)
    # The excluded fourth ancestor no longer contributes context or authority.
    with session_factory()() as db:
        db.get(AgentRun, rows[0]["id"]).created_at = now() - timedelta(hours=25)
        db.commit()
    child = boss.post("/agent/runs", payload(rows[-1], question="现在讨论下一步安排"), 201)
    advance(boss, child)
    context = calls[-1]
    previous = context["previous_turn"]
    assert context["question"] == "现在讨论下一步安排"
    assert context["completed_reads"] == []
    assert previous["question"] == rows[-1]["question"]
    assert [turn["question"] for turn in previous["earlier_turns"]] == [
        rows[2]["question"],
        rows[1]["question"],
    ]
    assert rows[0]["question"] not in json.dumps(previous, ensure_ascii=False)
    assert all(set(turn) == {"question", "summary"} for turn in previous["earlier_turns"])
    assert len(json.dumps(previous, ensure_ascii=False, separators=(",", ":")).encode()) <= 1800
    assert len(calls) == 9


@pytest.mark.parametrize("index", [0, 1])
@pytest.mark.parametrize(
    "change", ["expired", "other_actor", "different_session", "answer_removed"]
)
def test_each_included_ancestor_is_reauthorized_on_create_read_and_advance(
    loop, monkeypatch, index, change
):
    boss, employee, *_ = loop
    calls = model(monkeypatch)
    rows = chain(boss)
    child = boss.post("/agent/runs", payload(rows[-1]), 201)
    with session_factory()() as db:
        ancestor = db.get(AgentRun, rows[index]["id"])
        if change == "expired":
            ancestor.created_at = now() - timedelta(hours=25)
        elif change == "other_actor":
            ancestor.actor_id = employee.get("/members")["items"][0]["id"]
        elif change == "different_session":
            ancestor.session_hash = "revoked-session-fixture"
        else:
            ancestor.answer = None
        before = db.scalar(select(func.count()).select_from(ModelInvocation))
        db.commit()
    for result in (
        boss.post("/agent/runs", payload(rows[-1]), 409),
        boss.get(f"/agent/runs/{child['id']}", 409),
        advance(boss, child, status=409),
    ):
        assert result["error"]["code"] == "parent_context_unavailable"
        assert "独有问题" not in json.dumps(result, ensure_ascii=False)
    assert len(calls) == 6
    with session_factory()() as db:
        assert db.scalar(select(func.count()).select_from(ModelInvocation)) == before


def test_third_turn_expiring_during_model_call_discards_output(loop, monkeypatch):
    boss = loop[0]
    model(monkeypatch)
    rows = chain(boss)
    child = boss.post("/agent/runs", payload(rows[-1]), 201)

    def expired_during_call(context):
        with session_factory()() as db:
            db.get(AgentRun, rows[0]["id"]).created_at = now() - timedelta(hours=25)
            db.commit()
        return read_proposal()

    calls = model(monkeypatch, expired_during_call)
    result = advance(boss, child, status=409)
    assert result["error"]["code"] == "parent_context_unavailable" and len(calls) == 1
    with session_factory()() as db:
        stored = db.get(AgentRun, child["id"])
        assert stored.answer is None and stored.state == "failed"
        invocation = db.scalars(
            select(ModelInvocation).order_by(ModelInvocation.started_at.desc())
        ).first()
        assert invocation.error_code == "access_revoked" and invocation.request_sent


def test_parent_cycle_is_rejected_without_recursion_or_model_call(loop, monkeypatch):
    boss = loop[0]
    calls = model(monkeypatch)
    rows = chain(boss)
    with session_factory()() as db:
        db.get(AgentRun, rows[0]["id"]).parent_run_id = rows[-1]["id"]
        db.commit()
    result = boss.post("/agent/runs", payload(rows[-1]), 409)
    assert result["error"]["code"] == "parent_context_unavailable" and len(calls) == 6


@pytest.mark.parametrize("text", ["中文原文与表情🙂" * 200, "\u0001" * 1200])
def test_three_turns_share_utf8_and_json_escape_budget(loop, monkeypatch, text):
    boss = loop[0]
    model(monkeypatch)
    rows = chain(boss)
    # Exercise serialization directly without depending on the public question
    # validator's whitespace normalization or a provider's context limit.
    with session_factory()() as db:
        for row in rows:
            db.get(AgentRun, row["id"]).question = text
        db.flush()
        current = db.get(AgentRun, rows[-1]["id"])
        from app.modules.agent.runtime import run_actor

        value = parent_turn(db, run_actor(db, current), current.id, current.session_hash, None)
        encoded = json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode()
        assert len(encoded) <= 1800 and len(value["earlier_turns"]) == 2
        assert "�" not in encoded.decode()


def test_old_document_antecedent_does_not_override_direct_parent_or_new_topic(loop, monkeypatch):
    from app.modules.agent import capabilities

    boss = loop[0]
    publish(boss, document(boss, title="差旅报销制度"))
    calls = model(monkeypatch)
    directory = advance(boss, run(boss, question="现在有哪些知识库？"))
    current = completed(boss, question="交付事项有哪些需要核实？", parent_run_id=directory["id"])
    followup = run(boss, question="其中写了什么？", parent_run_id=current["id"])
    result = advance(boss, followup)
    assert result["steps"][0]["capability"] == "company.overview"
    previous = calls[-1]["previous_turn"]
    assert previous["knowledge_documents"] == [] and len(previous["earlier_turns"]) == 1

    queries = []
    search = capabilities.search

    def recorded(db, actor, query, **kwargs):
        queries.append(query)
        return search(db, actor, query, **kwargs)

    monkeypatch.setattr(capabilities, "search", recorded)
    model(monkeypatch, lambda context: read_proposal("knowledge.search"))
    fresh = run(boss, question="安全培训有哪些要求？", parent_run_id=current["id"])
    advance(boss, fresh)
    assert queries == ["安全培训有哪些要求？"]


def test_ancestor_summary_is_not_current_citation_authority(loop, monkeypatch):
    boss = loop[0]
    model(monkeypatch)
    rows = chain(boss)

    def no_read(context):
        assert not context["completed_reads"] and context["previous_turn"]["earlier_turns"]
        old = rows[0]["answer"]["evidence"][0]
        return {
            "kind": "finish",
            "capability": None,
            "work_item_id": None,
            "outcome": "answer",
            "answer": {
                "assessments": [
                    {
                        "evidence_id": old["id"],
                        "quote": old["excerpt"],
                        "interpretation": "请核实当前记录。",
                        "action_keys": ["verify"],
                    }
                ]
            },
        }

    calls = model(monkeypatch, no_read)
    row = advance(boss, boss.post("/agent/runs", payload(rows[-1]), 201))
    assert row["state"] == "failed" and len(calls) == 1
    assert row["error_code"] == "invalid_evidence" and row["answer"] is None
