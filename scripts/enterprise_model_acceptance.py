"""Real development-model checks on the same synthetic 10-person company.

Explicit credentials only; isolated PostgreSQL schema; at most 19 model calls.
Nothing enables Coding Plan on the running application's business endpoints.
"""

# ruff: noqa: E402
import argparse
import json
import os
import sys
from pathlib import Path
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from alembic import command
from alembic.config import Config
from enterprise_scenario import EnterpriseScenario, ScenarioFailure, key
from fastapi.testclient import TestClient
from model_acceptance import explicit_config
from sqlalchemy import create_engine, func, select, text
from sqlalchemy.engine import make_url

from app.core.config import settings
from app.infrastructure.db import session_factory
from app.infrastructure.models import AgentRun, Membership, ModelInvocation, WorkEvent
from app.main import app
from app.modules.agent import runtime
from app.modules.agent.schemas import AdvanceInput
from app.modules.watch import runner, scheduler
from app.modules.watch.models import WatchRun


def tick():
    with session_factory()() as db:
        scheduler.merge_events(db)
        scheduler.schedule(db)
        queued = [
            (r.organization_id, r.id, r.version)
            for r in db.scalars(select(WatchRun).where(WatchRun.state == "queued"))
        ]
    for task in queued:
        with session_factory()() as db:
            runner.process(db, *task)


def model_checks(scenario, cfg, report):
    policy = scenario.get("owner", "/ai/settings")
    cfg = cfg.model_copy(
        update={
            "ai_config_revision": policy["version"],
            **{
                "ai_" + name: policy[name]
                for name in (
                    "daily_call_limit",
                    "daily_token_limit",
                    "monthly_token_limit",
                    "concurrency_limit",
                )
            },
        }
    )

    def graph(actor, question, work=None, task="read"):
        row = scenario.post(
            actor,
            "/agent/runs",
            {
                "question": question,
                "work_item_id": scenario.works[work]["id"] if work else None,
                "task": task,
                "idempotency_key": key(),
            },
        )
        for _ in range(6 if task == "read" else 1):
            if row["state"] != "ready":
                break
            with session_factory()() as db:
                count = db.scalar(select(func.count()).select_from(ModelInvocation))
                if count >= 19:
                    raise ScenarioFailure("model_call_ceiling")
                stored = db.get(AgentRun, row["id"])
                member = db.get(Membership, stored.actor_id)
                value = runtime.advance(
                    db,
                    member,
                    stored.id,
                    AdvanceInput(expected_version=row["version"], idempotency_key=uuid4()),
                    development_config=cfg,
                )
                row = value.model_dump(mode="json")
        report["runs"].append(
            {
                "actor": actor,
                "task": task,
                "state": row["state"],
                "error_code": row.get("error_code"),
                "steps": row["step_count"],
                "step_results": [
                    {name: step[name] for name in ("ordinal", "state", "capability", "error_code")}
                    for step in row["steps"]
                ],
            }
        )
        return row

    def check(name, condition):
        report["cases"].append({"case": name, "passed": bool(condition)})
        print(
            json.dumps({"case": name, "passed": bool(condition)}, ensure_ascii=False),
            flush=True,
        )
        if not condition:
            raise ScenarioFailure(name)

    def work_event_count():
        with session_factory()() as db:
            return db.scalar(select(func.count()).select_from(WorkEvent))

    before = work_event_count()
    owner = graph(
        "owner",
        "核实客户资料缺口与最近决策，提出有依据的下一步；没有实际结果不要声称问题解决。",
        "material",
    )
    answer = owner.get("answer") or {}
    check(
        "老板按真实经营记录得到有引用建议",
        owner["state"] == "completed"
        and answer.get("suggestions")
        and answer.get("mode") == "model"
        and all(e["work_item_id"] == scenario.works["material"]["id"] for e in answer["evidence"]),
    )
    report["answers"].append({"actor": "owner", "answer": answer})

    manager = graph(
        "dev-0",
        "请核实订单接口联调当前有哪些记录和支持需求；不猜测客户资料状态。",
        "api",
    )
    answer = manager.get("answer") or {}
    check(
        "研发主管模型读取不超出事项范围",
        manager["state"] == "completed"
        and answer.get("evidence")
        and all(e["work_item_id"] == scenario.works["api"]["id"] for e in answer["evidence"]),
    )
    report["answers"].append({"actor": "dev-0", "answer": answer})

    knowledge = graph(
        "owner",
        "请查找企业知识库中的验收制度，引用其原文。不要检索或推测私人报价底线。",
    )
    answer = knowledge.get("answer") or {}
    check(
        "老板知识问答引用已发布制度",
        knowledge["state"] == "completed"
        and answer.get("document_answers")
        and answer.get("mode") == "model",
    )
    check(
        "私有报价内容未进入老板答案",
        "紫杉报价底线" not in json.dumps(answer, ensure_ascii=False),
    )
    report["answers"].append({"actor": "owner_knowledge", "answer": answer})
    check("模型读取不生成业务进展", work_event_count() == before)

    row = graph(
        "delivery-1",
        "模拟汇报：培训讲义已整理，仍等待客户名单，需要负责人协调。培训尚未完成。",
        "training",
        "update_draft",
    )
    draft = row.get("draft")
    check(
        "员工模型草稿等待本人确认",
        row["state"] == "completed"
        and draft
        and draft["state"] == "pending"
        and draft["provider"] != "rules"
        and work_event_count() == before,
    )
    confirm = {"expected_revision": draft["revision"]}
    scenario.deny(
        "模型草稿仍拒绝老板代确认",
        "owner",
        "POST",
        f"/work-updates/drafts/{draft['id']}/confirm",
        confirm,
    )
    first = scenario.post("delivery-1", f"/work-updates/drafts/{draft['id']}/confirm", confirm)
    repeated = scenario.post("delivery-1", f"/work-updates/drafts/{draft['id']}/confirm", confirm)
    check(
        "模型草稿作者确认与重放一次效果",
        first["id"] == repeated["id"] and work_event_count() == before + 1,
    )
    report["passed"] = True


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config-file", type=Path, required=True)
    parser.add_argument("--database-url", required=True)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    if args.report.exists():
        parser.error("Choose a new report path")
    report = {
        "passed": False,
        "synthetic_data": True,
        "application_backend_verified": False,
        "model_call_ceiling": 19,
        "cases": [],
        "runs": [],
        "answers": [],
    }
    schema = "test_enterprise_" + uuid4().hex
    engine, scenario, created = None, None, False
    try:
        cfg = explicit_config(args.config_file)
        url = make_url(args.database_url)
        if url.get_backend_name() != "postgresql" or "test" not in (url.database or ""):
            raise ValueError("dedicated_test_database_required")
        engine = create_engine(url)
        with engine.begin() as db:
            db.execute(text(f'CREATE SCHEMA "{schema}"'))
        created = True
        os.environ.update(
            COROOF_DATABASE_URL=url.update_query_dict(
                {"options": f"-csearch_path={schema}"}
            ).render_as_string(hide_password=False),
            COROOF_ENVIRONMENT="test",
            COROOF_AUTH_MODE="mock",
            COROOF_DELIVERY_MODE="mock",
            COROOF_AI_PROVIDER="rules",
            COROOF_AI_API_KEY="",
        )
        settings.cache_clear()
        session_factory.cache_clear()
        command.upgrade(Config(str(ROOT / "backend/alembic.ini")), "head")
        scenario = EnterpriseScenario(
            lambda: TestClient(app),
            "model-" + uuid4().hex[:8],
            tick=tick,
            pause_models=False,
        )
        scenario.run()
        report["business_checks"] = len(scenario.report["checks"])
        model_checks(scenario, cfg, report)
    except Exception as error:
        report["failure"] = (
            str(error) if isinstance(error, ScenarioFailure) else type(error).__name__
        )
    finally:
        if scenario:
            scenario.close()
        if created:
            with session_factory()() as db:
                rows = list(db.scalars(select(ModelInvocation)))
                report["model_calls"] = len(rows)
                report["model_status"] = [
                    {"status": r.status, "error_code": r.error_code} for r in rows
                ]
            session_factory().kw["bind"].dispose()
            session_factory.cache_clear()
            with engine.begin() as db:
                db.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        if engine:
            engine.dispose()
        settings.cache_clear()
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    print(
        json.dumps(
            {
                "passed": report["passed"],
                "cases": len(report["cases"]),
                "failure": report.get("failure"),
                "model_calls": report.get("model_calls"),
                "report": str(args.report),
            },
            ensure_ascii=False,
        )
    )
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
