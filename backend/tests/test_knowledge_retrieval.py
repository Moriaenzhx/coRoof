"""Real SQL candidate retrieval, bounded lexical ranking and fixed quality acceptance."""

import base64
import importlib.util
import io
from pathlib import Path
from uuid import uuid4

import pytest
from docx import Document
from sqlalchemy import inspect, select
from test_knowledge import ROOT, create, employee_access_cases, find, publish

from app.infrastructure.db import session_factory
from app.infrastructure.models import Membership
from app.modules.knowledge import index
from app.modules.knowledge.retrieval import RERANK_LIMIT
from app.modules.model_gateway.gateway import ModelGateway

spec = importlib.util.spec_from_file_location(
    "knowledge_evaluation", Path(__file__).resolve().parents[2] / "scripts/knowledge_evaluation.py"
)
evaluation = importlib.util.module_from_spec(spec)
spec.loader.exec_module(evaluation)


def test_reranker_never_receives_unpublished_private_or_other_tenant_chunks(loop, monkeypatch):
    employee, cases, _ = employee_access_cases(loop)
    expected = {row["id"] for _, row, visible in cases if visible}
    received = []
    original = index.rerank

    def inspect_candidates(words, candidates):
        received.append({chunk.document_id for chunk, _ in candidates})
        assert received[-1] == expected
        # Large complete documents and original file bytes are not loaded per candidate.
        assert all(
            {"content", "file_bytes"} <= inspect(revision).unloaded for _, revision in candidates
        )
        return original(words, candidates)

    monkeypatch.setattr(index, "rerank", inspect_candidates)
    first = find(employee, "合成文档")
    second = find(employee, "合成文档")
    assert first == second
    assert {item["document_id"] for item in first["items"]} == expected
    assert first["authorized_documents"] == len(expected)
    assert len(received) == 2


def test_reranked_head_and_database_tail_are_one_stable_complete_pagination(loop):
    boss, _, org, *_ = loop
    for group in range(3):
        content = "\n\n".join(
            f"boundarymatch group{group} entry{number} " + "regular " * (66 + number % 3)
            for number in range(180)
        )
        publish(boss, create(boss, content=content))
    with session_factory()() as db:
        actor = db.scalar(select(Membership).where(Membership.organization_id == org["id"]))
        baseline = index.search(db, actor, "boundarymatch", limit=1000, ranking="database")
        assert baseline.total > RERANK_LIMIT + 1
        expected_ids = [item.id for item in baseline.items]
        pages = [
            index.search(db, actor, "boundarymatch", offset=start, limit=20)
            for start in range(0, baseline.total, 20)
        ]
        actual_ids = [item.id for page in pages for item in page.items]
        assert len(actual_ids) == len(set(actual_ids)) == baseline.total
        assert set(actual_ids) == set(expected_ids)
        assert set(actual_ids[:RERANK_LIMIT]) == set(expected_ids[:RERANK_LIMIT])
        assert actual_ids[RERANK_LIMIT:] == expected_ids[RERANK_LIMIT:]
        assert all(page.total == baseline.total and "500" in page.notice for page in pages)
        for start in (0, 479, 499, 500, 501, baseline.total, baseline.total + 9):
            page = index.search(db, actor, "boundarymatch", offset=start, limit=3)
            assert [item.id for item in page.items] == actual_ids[start : start + 3]
            assert page.total == baseline.total


def test_bm25_ties_keep_database_order_and_empty_query_never_invokes_ranker(loop, monkeypatch):
    boss, _, org, *_ = loop
    for _ in range(3):
        publish(boss, create(boss, content="sameword 相同的合成原文。"))
    with session_factory()() as db:
        actor = db.scalar(select(Membership).where(Membership.organization_id == org["id"]))
        before = index.search(db, actor, "sameword", ranking="database")
        after = index.search(db, actor, "sameword")
        assert [item.id for item in before.items] == [item.id for item in after.items]
    monkeypatch.setattr(index, "rerank", lambda *_: pytest.fail("empty query must not rank"))
    assert find(boss, "！！！")["items"] == []


def test_docx_preserves_interleaved_paragraph_and_table_order_and_exact_sources(loop):
    boss, *_ = loop
    document = Document()
    document.add_paragraph("采购审批条件")
    table = document.add_table(rows=2, cols=2)
    table.cell(0, 0).text = "金额"
    table.cell(0, 1).text = "审批人"
    table.cell(1, 0).text = "五千元以上"
    table.cell(1, 1).text = "部门主管"
    document.add_paragraph("以上表格核对后方可付款。")
    table = document.add_table(rows=1, cols=2)
    table.cell(0, 0).text = "付款材料"
    table.cell(0, 1).text = "合同和发票"
    document.add_paragraph("最后登记付款日期。")
    data = io.BytesIO()
    document.save(data)
    row = boss.post(
        "/knowledge/import",
        {
            "title": "合成采购制度",
            "file_name": "采购制度.docx",
            "file_base64": base64.b64encode(data.getvalue()).decode(),
            "idempotency_key": str(uuid4()),
        },
        201,
    )
    revision = boss.get(f"{ROOT}/{row['id']}/revisions/{row['draft_id']}")
    assert revision["content"] == (
        "采购审批条件\n金额 | 审批人\n五千元以上 | 部门主管\n"
        "以上表格核对后方可付款。\n付款材料 | 合同和发票\n最后登记付款日期。"
    )
    assert find(boss, "采购")["items"] == []
    published = publish(boss, row)
    hit = find(boss, "采购")["items"][0]
    assert hit["revision_id"] == published["published_id"]
    assert revision["content"][hit["start_offset"] : hit["end_offset"]] == hit["excerpt"]
    response = boss.request("GET", f"{ROOT}/{row['id']}/revisions/{hit['revision_id']}/file")
    assert response.content == data.getvalue()


def test_fixed_business_questions_measure_both_rankings_without_models(monkeypatch):
    monkeypatch.setattr(ModelGateway, "generate", lambda *_: pytest.fail("model not allowed"))
    report = evaluation.evaluate()
    assert len(report["cases"]) == 23
    assert report["model_calls"] == 0
    assert all(value["exact_sources"] for value in report["summary"].values())
    old, new = report["summary"]["database"], report["summary"]["bm25"]
    assert new["false_match"] == old["false_match"] == 0
    assert new["recall@3"] >= old["recall@3"]
    assert new["mrr@3"] >= old["mrr@3"]
    # PostgreSQL is the production baseline; SQLite's ordinal fallback has no relevance rank.
    if report["database"] == "postgresql":
        assert new["recall@1"] > old["recall@1"]
        assert new["mrr@3"] > old["mrr@3"]
    difficult = [row for row in report["cases"] if row["category"] == "difficult_paraphrase"]
    assert len(difficult) == 2
    assert all(row["relevant"] and "recall@3" in row["results"]["bm25"] for row in difficult)


@pytest.mark.parametrize("url", ["sqlite:///test.db", "postgresql+psycopg:///coroof_dev"])
def test_evaluation_rejects_non_test_database_before_writing(url):
    with pytest.raises(ValueError, match="dedicated_postgresql_test_database_required"):
        evaluation.test_database_url(url)
