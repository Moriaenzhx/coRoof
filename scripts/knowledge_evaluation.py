# ruff: noqa: E402
"""Compare lexical retrieval on fixed synthetic material in an isolated test schema.

No model, embedding, OCR service, real company data or application credentials are used.
This is a small regression benchmark, not evidence of general semantic understanding.
"""

import argparse
import hashlib
import json
import os
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from unittest.mock import patch
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select, text
from sqlalchemy.engine import make_url

from app.core.config import settings
from app.infrastructure.db import session_factory
from app.infrastructure.models import Membership, ModelInvocation
from app.main import app
from app.modules.knowledge.index import search
from app.modules.knowledge.models import KnowledgeRevision
from app.modules.model_gateway.gateway import ModelGateway

FIXTURE = ROOT / "scripts/fixtures/knowledge-retrieval-v1.json"


def metrics(ranked: list[str], relevant: list[str]) -> dict[str, float]:
    """Document-level recall and reciprocal rank; duplicate chunks earn no extra credit."""
    expected = set(relevant)
    result = {
        f"recall@{k}": len(set(ranked[:k]) & expected) / len(expected) for k in (1, 3) if expected
    }
    if expected:
        rank = next((i for i, item in enumerate(ranked[:3], 1) if item in expected), None)
        result["mrr@3"] = 1 / rank if rank else 0.0
    else:
        result["false_match"] = float(bool(ranked))
    return result


def evaluate(*, baseline_only: bool = False) -> dict[str, Any]:
    if settings().environment != "test" or settings().auth_mode != "mock":
        raise ValueError("isolated_test_environment_required")
    raw = FIXTURE.read_bytes()
    fixture = json.loads(raw)
    references: dict[str, str] = {}
    rows: list[dict[str, Any]] = []
    with TestClient(app) as client:
        client.headers["X-CoRoof-Request"] = "1"

        def post(path: str, body: dict[str, Any]) -> dict[str, Any]:
            response = client.post("/api/v1" + path, json=body)
            if response.status_code >= 400:
                raise ValueError("synthetic_fixture_setup_failed")
            return dict(response.json())

        login = post(
            "/auth/request-link",
            {"email": "retrieval-eval@synthetic.example", "name": "合成检索验收身份"},
        )
        post("/auth/verify", {"token": login["token"]})
        org = post("/organizations", {"name": "合成检索质量验收 · 非客户资料"})
        client.headers["X-Organization-Id"] = org["id"]
        for document in fixture["documents"]:
            saved = post(
                "/knowledge/documents",
                {
                    "title": document["title"],
                    "content": document["content"],
                    "visibility": "organization",
                    "idempotency_key": str(uuid4()),
                },
            )
            post(
                f"/knowledge/documents/{saved['id']}/publish",
                {
                    "expected_version": saved["version"],
                    "revision_id": saved["draft_id"],
                    "confirm": True,
                    "idempotency_key": str(uuid4()),
                },
            )
            references[saved["id"]] = document["id"]
        with session_factory()() as db:
            actor = db.scalar(select(Membership).where(Membership.organization_id == org["id"]))
            assert actor is not None
            for case in fixture["cases"]:
                row = {**case, "results": {}}
                modes = ("database",) if baseline_only else ("database", "bm25")
                for mode in modes:
                    result = search(db, actor, case["query"], limit=3, ranking=mode)
                    ranked = [references[item.document_id] for item in result.items]
                    exact = True
                    for item in result.items:
                        revision = db.get(KnowledgeRevision, item.revision_id)
                        exact = exact and bool(
                            revision
                            and revision.content is not None
                            and revision.content[item.start_offset : item.end_offset]
                            == item.excerpt
                        )
                    row["results"][mode] = {
                        "ranked_documents": ranked,
                        "matched_chunks": result.total,
                        "exact_sources": exact,
                        **metrics(ranked, case["relevant"]),
                    }
                rows.append(row)
            calls = db.scalar(
                select(func.count())
                .select_from(ModelInvocation)
                .where(ModelInvocation.organization_id == org["id"])
            )
    summaries = {}
    for mode in rows[0]["results"]:
        scores = [row["results"][mode] for row in rows]
        summaries[mode] = {
            metric: sum(item[metric] for item in scores if metric in item)
            / sum(metric in item for item in scores)
            for metric in ("recall@1", "recall@3", "mrr@3", "false_match")
        }
        summaries[mode]["exact_sources"] = all(item["exact_sources"] for item in scores)
    changes = []
    gates = {
        "no_model_calls": calls == 0,
        "exact_sources": all(value["exact_sources"] for value in summaries.values()),
    }
    if not baseline_only:
        before_summary, after_summary = summaries["database"], summaries["bm25"]
        gates.update(
            recall_not_regressed=after_summary["recall@3"] >= before_summary["recall@3"],
            reciprocal_rank_improved=after_summary["mrr@3"] > before_summary["mrr@3"],
            false_matches_not_increased=after_summary["false_match"]
            <= before_summary["false_match"],
        )
        for row in rows:
            before, after = row["results"]["database"], row["results"]["bm25"]
            if before["ranked_documents"] != after["ranked_documents"]:
                changes.append(
                    {
                        "case": row["id"],
                        "before": before["ranked_documents"],
                        "after": after["ranked_documents"],
                        "recall@3_delta": after.get("recall@3", 0) - before.get("recall@3", 0),
                        "mrr@3_delta": after.get("mrr@3", 0) - before.get("mrr@3", 0),
                    }
                )
    return {
        "benchmark": fixture["version"],
        "fixture_sha256": hashlib.sha256(raw).hexdigest(),
        "synthetic_data": True,
        "database": session_factory().kw["bind"].dialect.name,
        "checked_at": datetime.now(UTC).isoformat(),
        "model_calls": calls,
        "summary": summaries,
        "cases": rows,
        "ranking_changes": changes,
        "metric_regressions": [
            item for item in changes if item["recall@3_delta"] < 0 or item["mrr@3_delta"] < 0
        ],
        "unmatched_relevant_cases": {
            mode: [
                row["id"]
                for row in rows
                if row["relevant"] and not row["results"][mode]["ranked_documents"]
            ]
            for mode in summaries
        },
        "quality_gates": gates,
        "passed": all(gates.values()),
        "limits": [
            "词项检索与 BM25 排序不等于语义检索；同义转述可能无命中。",
            "BM25 仅重排数据库前 500 个获授权候选；其余结果按原顺序接续。",
            "Embedding 与模型 Rerank 未配置，未调用或验收；OCR 仍不支持。",
            "未来语义模型需独立配置、预算和调用验收，继续在当前租户/ACL/发布版本内读取。",
            "该固定小型合成集不代表真实企业规模、答案生成质量或生产验收。",
        ],
    }


def test_database_url(value: str) -> Any:
    url = make_url(value)
    if url.get_backend_name() != "postgresql" or "test" not in (url.database or ""):
        raise ValueError("dedicated_postgresql_test_database_required")
    return url


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database-url", required=True)
    parser.add_argument("--baseline-only", action="store_true")
    parser.add_argument(
        "--report", type=Path, default=ROOT / ".local/knowledge-retrieval-quality.json"
    )
    args = parser.parse_args()
    url = test_database_url(args.database_url)
    schema = "test_knowledge_eval_" + uuid4().hex
    admin = create_engine(url)
    with admin.begin() as connection:
        connection.execute(text(f'CREATE SCHEMA "{schema}"'))
    try:
        scoped = url.update_query_dict({"options": f"-csearch_path={schema}"})
        os.environ.update(
            COROOF_DATABASE_URL=scoped.render_as_string(hide_password=False),
            COROOF_ENVIRONMENT="test",
            COROOF_AUTH_MODE="mock",
            COROOF_AI_PROVIDER="rules",
            COROOF_AI_API_KEY="",
            COROOF_AI_MODEL_VERIFIED="false",
            COROOF_AI_DEVELOPMENT_TEST_CONNECTION_IDS="[]",
            LANGSMITH_TRACING="false",
        )
        settings.cache_clear()
        session_factory.cache_clear()
        command.upgrade(Config(str(ROOT / "backend/alembic.ini")), "head")
        with patch.object(
            ModelGateway, "generate", side_effect=AssertionError("model_not_allowed")
        ):
            report = evaluate(baseline_only=args.baseline_only)
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
        print(json.dumps({"summary": report["summary"], "model_calls": report["model_calls"]}))
        return 0 if report["passed"] else 1
    finally:
        session_factory().kw["bind"].dispose()
        session_factory.cache_clear()
        settings.cache_clear()
        with admin.begin() as connection:
            connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        admin.dispose()


if __name__ == "__main__":
    raise SystemExit(main())
