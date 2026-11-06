"""Explicit content reads use authorized retrieval without asking a model to choose a route."""

from concurrent.futures import ThreadPoolExecutor
from threading import Event

import pytest
from sqlalchemy import func, select
from test_agent_read import action, advance, model, read_proposal
from test_agent_read import create as run
from test_knowledge import TEXT, create, publish
from test_knowledge_agent import choose

from app.infrastructure.db import session_factory
from app.infrastructure.models import AnalysisRun, ModelInvocation, WorkEvent
from app.modules.agent.runtime import knowledge_content_followup, knowledge_inventory_request
from app.modules.model_gateway.gateway import ModelGateway


@pytest.mark.parametrize(
    "question,expected",
    [
        ("里面写了什么？", True),
        ("其中具体规定是什么？", True),
        ("内容呢？", True),
        ("原文是什么？", True),
        ("再列一下知识库目录", False),
        ("现在有哪些文档？", False),
        ("客户项目现在进展如何？", False),
        ("订单备注写了什么？", False),
    ],
)
def test_content_route_requires_knowledge_parent_and_prioritizes_current_question(
    question, expected
):
    previous = {"knowledge_documents": [{"document_id": "fixture", "title": "制度"}]}
    assert knowledge_content_followup(question, previous) is expected
    assert not knowledge_content_followup(question, None)
    assert not knowledge_content_followup(question, {"knowledge_documents": []})


@pytest.mark.parametrize("model_disabled", [False, True])
def test_content_followup_retrieves_without_model_and_preserves_audit_idempotency(
    loop, monkeypatch, model_disabled
):
    boss, *_ = loop
    publish(boss, create(boss, title="差旅报销制度"))
    calls = model(monkeypatch, lambda _: read_proposal("knowledge.list"))
    parent = advance(boss, run(boss, question="现在企业有哪些知识库"))
    if model_disabled:
        policy = boss.get("/ai/settings")
        body = {
            key: policy[key]
            for key in (
                "daily_call_limit",
                "daily_token_limit",
                "monthly_token_limit",
                "concurrency_limit",
                "alert_percent",
            )
        }
        body.update(expected_version=policy["version"], mode="disabled", connection_id=None)
        assert boss.request("PUT", "/ai/settings", body).status_code == 200

    def forbidden(*args):
        raise AssertionError("An explicit original-text read must not invoke the model gateway")

    monkeypatch.setattr(ModelGateway, "prepare", forbidden)
    monkeypatch.setattr(ModelGateway, "generate", forbidden)
    with session_factory()() as db:
        before_events = db.scalar(select(func.count()).select_from(WorkEvent))
        before_calls = db.scalar(select(func.count()).select_from(ModelInvocation))
    initial = run(boss, question="里面写了什么？", parent_run_id=parent["id"])
    command = action(initial)
    child = advance(boss, initial, command)
    assert child["state"] == "completed" and child["steps"][0]["capability"] == "knowledge.search"
    assert (
        child["answer"]["mode"] == "retrieval"
        and child["answer"]["provider"] == "knowledge_retrieval"
    )
    assert child["answer"]["model"] == "none" and "未调用模型" in child["answer"]["notice"]
    assert child["answer"]["knowledge_inventory"] is None
    assert child["answer"]["document_answers"][0]["quote"] == TEXT
    assert advance(boss, initial, command) == child and calls == []
    with session_factory()() as db:
        assert db.scalar(select(func.count()).select_from(ModelInvocation)) == before_calls
        assert db.scalar(select(func.count()).select_from(WorkEvent)) == before_events
        analysis = db.get(AnalysisRun, child["answer"]["id"])
        assert analysis.status == "succeeded" and analysis.cost_estimate == "0"


def test_explicit_new_directory_question_can_still_list_with_a_parent(loop, monkeypatch):
    boss, *_ = loop
    publish(boss, create(boss))
    calls = model(monkeypatch, lambda _: read_proposal("knowledge.list"))
    parent = advance(boss, run(boss, question="现在有哪些知识库？"))
    child = advance(boss, run(boss, question="请重新列出文档目录", parent_run_id=parent["id"]))
    assert child["state"] == "completed" and child["answer"]["knowledge_inventory"]["total"] == 1
    assert child["answer"]["mode"] == "retrieval" and calls == []


@pytest.mark.parametrize(
    "question,expected",
    [
        ("现在企业有哪些知识库", True),
        ("公司有哪些资料？", True),
        ("请重新列出文档目录", True),
        ("目前公司的资料清单", True),
        ("列出知识目录", True),
        ("企业知识库有哪些资料？", True),
        ("知识库里有哪些文档？", True),
        ("知识库中有哪些资料？", True),
        ("我们的知识库里面都有哪些制度？", True),
        ("请问企业知识库有哪些资料？", True),
        ("当前公司的知识库内有哪些已发布文档？", True),
        ("哪些制度有风险？", False),
        ("有哪些待确认的制度？", False),
        ("制度有哪些具体要求？", False),
        ("知识库里的制度有哪些具体要求？", False),
        ("知识库中有哪些待确认制度？", False),
        ("企业知识库有哪些资料需要审批？", False),
        ("知识库里有哪些未发布资料？", False),
        ("知识库里哪些资料有风险？", False),
        ("公司制度执行情况如何？", False),
        ("今天有哪些事需要我处理？", False),
    ],
)
def test_inventory_route_only_matches_explicit_directory_questions(question, expected):
    assert knowledge_inventory_request(question) is expected


@pytest.mark.parametrize(
    "question",
    ["企业知识库有哪些资料？", "知识库里有哪些文档？", "知识库中有哪些资料？"],
)
def test_repository_inventory_phrasing_reads_current_acl_with_zero_model_calls(
    loop, monkeypatch, question
):
    boss, employee, *_ = loop
    visible = publish(boss, create(boss, title="共享制度", visibility="organization"))
    publish(boss, create(boss, title="不应暴露的私人资料"))

    def forbidden(*args):
        raise AssertionError("Explicit inventory must not prepare or call a model")

    monkeypatch.setattr(ModelGateway, "prepare", forbidden)
    monkeypatch.setattr(ModelGateway, "generate", forbidden)
    child = advance(employee, run(employee, question=question))
    assert child["state"] == "completed" and child["step_count"] == 1
    assert child["steps"][0]["capability"] == "knowledge.list"
    assert child["answer"]["mode"] == "retrieval"
    listing = child["answer"]["knowledge_inventory"]
    assert listing["total"] == 1
    assert [item["document_id"] for item in listing["items"]] == [visible["id"]]
    with session_factory()() as db:
        assert db.scalar(select(func.count()).select_from(ModelInvocation)) == 0


def test_directory_retrieval_concurrent_advance_has_one_audited_effect(loop, monkeypatch):
    from app.modules.agent import runtime

    with session_factory()() as db:
        if db.get_bind().dialect.name != "postgresql":
            pytest.skip("PostgreSQL row locks required")
    boss, *_ = loop
    publish(boss, create(boss))
    calls = model(monkeypatch)
    entered, release = Event(), Event()
    execute = runtime.execute

    def paused(*args):
        entered.set()
        assert release.wait(10)
        return execute(*args)

    monkeypatch.setattr(runtime, "execute", paused)
    initial = run(boss, question="现在企业有哪些知识库？")
    command = action(initial)
    path = f"/agent/runs/{initial['id']}/advance"
    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(boss.post, path, command)
        assert entered.wait(10)
        second = pool.submit(boss.post, path, command)
        release.set()
        one, duplicate = first.result(timeout=10), second.result(timeout=10)
    assert one == duplicate and one["state"] == "completed"
    assert one["step_count"] == 1 and calls == []
    with session_factory()() as db:
        assert db.scalar(select(func.count()).select_from(ModelInvocation)) == 0
        assert db.scalar(select(func.count()).select_from(AnalysisRun)) == 1


def test_new_knowledge_topic_does_not_inherit_previous_directory_search_terms(loop, monkeypatch):
    from app.modules.agent import capabilities

    boss, *_ = loop
    publish(boss, create(boss, title="差旅报销制度"))
    publish(boss, create(boss, title="安全培训", content="安全培训需要完成消防演练。"))
    queries = []
    search = capabilities.search

    def recorded_search(db, actor, query, **kwargs):
        queries.append(query)
        return search(db, actor, query, **kwargs)

    def respond(context):
        if not context.get("previous_turn"):
            return read_proposal("knowledge.list")
        return choose(context)

    monkeypatch.setattr(capabilities, "search", recorded_search)
    model(monkeypatch, respond)
    parent = advance(boss, run(boss, question="有哪些文档？"))
    question = "安全培训有什么要求？"
    child = advance(boss, run(boss, question=question, parent_run_id=parent["id"]))
    child = advance(boss, child)
    assert child["state"] == "completed"
    assert queries == [question]
    assert child["answer"]["document_answers"][0]["quote"] == "安全培训需要完成消防演练。"
