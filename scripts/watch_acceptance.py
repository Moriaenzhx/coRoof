# ruff: noqa: E402
"""Explicit Coding Plan development acceptance in an isolated synthetic PostgreSQL schema.

At most two background graphs / twelve model calls, no automatic retry. Credentials
come only from --config-file, never application environment or tenant connections.
"""

import argparse
import json
import os
import sys
from datetime import timedelta
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(root / "backend"))
sys.path.insert(0, str(root / "scripts"))

from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from model_acceptance import explicit_config
from sqlalchemy import create_engine, func, select, text
from sqlalchemy.engine import make_url

from app.core.config import settings
from app.infrastructure.db import session_factory
from app.infrastructure.models import AgentRun, ModelInvocation, WorkEvent, now
from app.main import app
from app.modules.model_gateway.gateway import ModelGateway
from app.modules.watch import runner, scheduler
from app.modules.watch.models import WatchPolicy, WatchRun


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config-file", required=True, type=Path)
    parser.add_argument("--database-url", required=True)
    parser.add_argument("--report", type=Path, default=root / ".local/watch-live-acceptance.json")
    args = parser.parse_args()
    report = {
        "stage": 8,
        "synthetic_data": True,
        "application_backend_verified": False,
        "passed": False,
        "cases": [],
        "model_call_ceiling": 12,
    }
    schema = "test_watch_live_" + uuid4().hex
    engine, created = None, False
    clients = []
    try:
        cfg = explicit_config(args.config_file)
        url = make_url(args.database_url)
        if url.get_backend_name() != "postgresql" or "test" not in (url.database or ""):
            raise ValueError("dedicated_test_database_required")
        engine = create_engine(url)
        with engine.begin() as connection:
            connection.execute(text(f'CREATE SCHEMA "{schema}"'))
        created = True
        os.environ.update(
            COROOF_DATABASE_URL=url.update_query_dict(
                {"options": f"-csearch_path={schema}"}
            ).render_as_string(hide_password=False),
            COROOF_ENVIRONMENT="test",
            COROOF_AUTH_MODE="mock",
            COROOF_AI_PROVIDER="rules",
            COROOF_AI_API_KEY="",
        )
        settings.cache_clear()
        session_factory.cache_clear()
        command.upgrade(Config(str(root / "backend/alembic.ini")), "head")

        def post(client, path, body):
            result = client.post("/api/v1" + path, json=body)
            if result.status_code >= 400:
                raise ValueError("synthetic_request_failed")
            return result.json()

        def login(email):
            client = TestClient(app)
            clients.append(client)
            client.headers["X-CoRoof-Request"] = "1"
            delivery = post(client, "/auth/request-link", {"name": "合成后台验收", "email": email})
            post(client, "/auth/verify", {"token": delivery["token"]})
            return client

        def policy(client):
            return post(
                client,
                "/watch/policies",
                {
                    "name": "合成验收 · 交付资料核实",
                    "goal": (
                        "核实已确认的交付资料缺口及最近决策，准备需老板审阅的下一步。"
                        "没有实际结果就保持未知。"
                    ),
                    "scope_kind": "organization",
                    "interval_minutes": 60,
                    "daily_analysis_limit": 2,
                    "expires_at": (now() + timedelta(days=1)).isoformat(),
                    "confirm": True,
                    "idempotency_key": str(uuid4()),
                },
            )

        def execute(p):
            with session_factory()() as db:
                row = db.get(WatchPolicy, p["id"])
                row.next_due_at = now()
                db.commit()
                scheduler.schedule(db)
                identifier = db.scalar(
                    select(WatchRun.id)
                    .where(WatchRun.policy_id == p["id"])
                    .order_by(WatchRun.created_at.desc())
                )
            for _ in range(8):
                with session_factory()() as db:
                    run = db.get(WatchRun, identifier)
                    if run.state != "queued":
                        child = db.get(AgentRun, run.agent_run_id) if run.agent_run_id else None
                        report.setdefault("runs", []).append(
                            {
                                "outcome": run.outcome_code,
                                "error_code": run.error_code,
                                "child_error": child.error_code if child else None,
                            }
                        )
                        return (
                            run.outcome_code,
                            child.answer if child else None,
                            run.agent_run_id,
                        )
                    task = run.organization_id, run.id, run.version
                    db.rollback()
                    original = ModelGateway.generate

                    def inspect(gateway, call, schema, original=original):
                        value = original(gateway, call, schema)
                        report.setdefault("synthetic_proposals", []).append(
                            value.output.model_dump(mode="json")
                        )
                        return value

                    with patch.object(ModelGateway, "generate", inspect):
                        runner.process(db, *task, development_config=cfg)
            raise ValueError("bounded_graph_did_not_finish")

        def count(model=False):
            with session_factory()() as db:
                return db.scalar(
                    select(func.count()).select_from(ModelInvocation if model else WorkEvent)
                )

        def record(name, passed):
            report["cases"].append({"case": name, "passed": bool(passed)})
            print(json.dumps({"case": name, "passed": bool(passed)}), flush=True)
            if not passed:
                raise ValueError("acceptance_case_failed")

        boss = login("watch-owner@synthetic.example")
        org = post(boss, "/organizations", {"name": "合成验收 · 持续关注"})
        boss.headers["X-Organization-Id"] = org["id"]
        dept = post(boss, "/departments", {"name": "合成交付"})
        work = post(
            boss,
            "/work-items",
            {"title": "合成资料交付待核实", "department_id": dept["id"]},
        )
        draft = post(
            boss,
            "/work-updates/drafts",
            {
                "work_item_id": work["id"],
                "raw_text": "合成验收：客户资料尚未到位，需要支持。实际交付结果未知。",
            },
        )
        post(
            boss,
            f"/work-updates/drafts/{draft['id']}/confirm",
            {"expected_revision": draft["revision"]},
        )
        p = policy(boss)
        before = count()
        assert boss.post("/api/v1/auth/logout-all").status_code == 204
        outcome, answer, child_id = execute(p)
        record(
            "unattended_grounded_graph",
            outcome == "analyzed" and answer and answer["suggestions"] and answer["evidence"],
        )
        record("no_autonomous_business_writes", count() == before)
        used = count(True)
        record(
            "unchanged_facts_no_rebilling",
            execute(p)[0] == "no_change" and count(True) == used,
        )
        boss = login("watch-owner@synthetic.example")
        boss.headers["X-Organization-Id"] = org["id"]
        decision = post(
            boss,
            "/decisions",
            {
                "analysis_id": answer["id"],
                "work_item_id": work["id"],
                "idempotency_key": str(uuid4()),
            },
        )
        choice = {
            "expected_version": decision["version"],
            "selected_option": decision["options"][0]["id"],
            "selected_plan": "合成确认：先与负责人核实资料缺口",
            "follow_up": "合成确认：核实后补充实际结果",
            "follow_up_at": (now() + timedelta(days=1)).isoformat(),
        }
        confirmed = post(boss, f"/decisions/{decision['id']}/confirm", choice)
        replay = post(boss, f"/decisions/{decision['id']}/confirm", choice)
        record("human_confirm_once", confirmed == replay and count() == before + 1)
        outcome, _, _ = execute(p)
        record("confirmed_decision_is_new_planning_context", outcome == "analyzed")
        empty = login("watch-empty@synthetic.example")
        empty_org = post(empty, "/organizations", {"name": "合成验收 · 无资料"})
        empty.headers["X-Organization-Id"] = empty_org["id"]
        used = count(True)
        record(
            "empty_scope_no_invention_or_call",
            execute(policy(empty))[0] == "no_data" and count(True) == used,
        )
        post(
            boss,
            f"/watch/policies/{p['id']}/actions",
            {
                "action": "pause",
                "confirm": True,
                "expected_version": p["version"],
                "idempotency_key": str(uuid4()),
            },
        )
        record(
            "pause_revokes_derived_answer",
            boss.get(f"/api/v1/agent/runs/{child_id}").status_code == 403,
        )
        report["passed"] = len(report["cases"]) == 7
        report["profile_kind"] = (
            "coding_plan_development"
            if cfg.ai_base_url.startswith("https://coding.")
            else "general_api_development"
        )
    except Exception as error:  # noqa: BLE001 - redact all operational diagnostics before cleanup
        report["error"] = type(
            error
        ).__name__  # No credential, SQL or response body in diagnostics.
    finally:
        for client in clients:
            client.close()
        if created:
            with session_factory()() as db:
                invocations = list(db.scalars(select(ModelInvocation)))
                report["model_calls"] = len(invocations)
                report["usage"] = [row.usage for row in invocations]
                report["model_status"] = [row.status for row in invocations]
                report["model_errors"] = [row.error_code for row in invocations]
            session_factory().kw["bind"].dispose()
            session_factory.cache_clear()
            with engine.begin() as connection:
                connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        if engine:
            engine.dispose()
        args.report.parent.mkdir(parents=True, exist_ok=True)
        with args.report.open("w") as output:
            args.report.chmod(0o600)
            json.dump(report, output, ensure_ascii=False, indent=2)
    print(json.dumps({"passed": report["passed"], "report": str(args.report.resolve())}))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
