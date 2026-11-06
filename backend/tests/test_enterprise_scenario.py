"""A whole-company rehearsal using the same API script as the running local stack."""

import importlib.util
import json
from pathlib import Path
from uuid import uuid4

import httpx
import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy import select
from test_agent_read import finish, read_proposal
from test_model_gateway import config, mock_transport, response

from app.infrastructure.db import session_factory
from app.main import app
from app.modules.model_gateway.gateway import ModelGateway
from app.modules.watch import runner, scheduler
from app.modules.watch.models import WatchRun

spec = importlib.util.spec_from_file_location(
    "enterprise_scenario", Path(__file__).resolve().parents[2] / "scripts/enterprise_scenario.py"
)
scenario_module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(scenario_module)


def tick():
    with session_factory()() as db:
        scheduler.merge_events(db)
        scheduler.schedule(db)
        queued = [
            (row.organization_id, row.id, row.version)
            for row in db.scalars(select(WatchRun).where(WatchRun.state == "queued"))
        ]
    for task in queued:
        with session_factory()() as db:
            runner.process(db, *task)


def test_multi_role_company_full_business_rehearsal(monkeypatch):
    def unexpected_call(*args, **kwargs):
        raise AssertionError("The rules-only rehearsal must not call a paid model")

    monkeypatch.setattr(ModelGateway, "generate", unexpected_call)
    scenario = scenario_module.EnterpriseScenario(
        lambda: TestClient(app), "test-" + uuid4().hex[:8], tick=tick
    )
    try:
        report = scenario.run()
        assert report["passed"] and len(report["checks"]) >= 50
        assert len(report["accounts"]) == 11
        assert all(check["passed"] for check in report["checks"])
    finally:
        scenario.close()


@pytest.mark.parametrize(
    "environment,auth_mode,pause_models,reason",
    [
        ("production", "oidc", True, "development_mock"),
        ("development", "mock", False, "isolated_test_environment"),
    ],
)
def test_company_rehearsal_refuses_unsafe_mode_before_any_write(
    environment, auth_mode, pause_models, reason
):
    requests = []

    def respond(request):
        requests.append((request.method, request.url.path))
        return httpx.Response(200, json={"environment": environment, "auth_mode": auth_mode})

    scenario = scenario_module.EnterpriseScenario(
        lambda: httpx.Client(base_url="http://testserver", transport=httpx.MockTransport(respond)),
        "guard-test",
        pause_models=pause_models,
    )
    try:
        with pytest.raises(scenario_module.ScenarioFailure, match=reason):
            scenario.run()
        assert requests == [("GET", "/api/v1/runtime")]
    finally:
        scenario.close()


def test_realistic_decisions_and_knowledge_fit_default_model_budget(monkeypatch):
    scripts = Path(__file__).resolve().parents[2] / "scripts"
    monkeypatch.syspath_prepend(str(scripts))
    import enterprise_model_acceptance

    scenario = scenario_module.EnterpriseScenario(
        lambda: TestClient(app), "budget-" + uuid4().hex[:8], tick=tick, pause_models=False
    )
    contexts = []

    def respond(request):
        context = json.loads(json.loads(request.content)["messages"][-1]["content"])
        contexts.append(context)
        reads = context.get("completed_reads", [])
        if "raw_text" in context:
            proposal = {
                "summary": context["raw_text"],
                "lifecycle_status": "in_progress",
                "needs_support": True,
            }
        elif "验收制度" in context["question"]:
            if not reads:
                proposal = read_proposal("knowledge.search")
            else:
                document = next(item for result in reads for item in result["documents"])
                proposal = {
                    "kind": "finish",
                    "capability": None,
                    "work_item_id": None,
                    "outcome": "answer",
                    "answer": {
                        "assessments": [],
                        "document_answers": [
                            {"citation_id": document["id"], "quote": document["excerpt"]}
                        ],
                        "memory_answers": [],
                    },
                }
        elif "最近决策" in context["question"]:
            plan = [
                "work.investigate",
                "preference.read",
                "experience.reference",
                "coverage.explain",
                "attention.explain",
            ]
            if len(reads) < len(plan):
                capability = plan[len(reads)]
                proposal = read_proposal(
                    capability,
                    context["work_item_id"] if capability == "work.investigate" else None,
                )
            else:
                proposal = finish(context)
        elif not any(result["evidence"] for result in reads):
            proposal = read_proposal("work.investigate", context["work_item_id"])
        else:
            proposal = finish(context)
        return response(proposal, usage={"prompt_tokens": 100, "completion_tokens": 50})

    try:
        scenario.run()
        mock_transport(monkeypatch, respond)
        cfg = config(
            environment="test",
            ai_base_url="https://coding.dashscope.aliyuncs.com/v1",
            ai_api_key=SecretStr("sk-sp-fixture-not-real"),
            ai_model_verified=False,
        )
        report = {"cases": [], "runs": [], "answers": []}
        try:
            enterprise_model_acceptance.model_checks(scenario, cfg, report)
        except enterprise_model_acceptance.ScenarioFailure:
            pytest.fail(str(report["runs"]))
        assert report["passed"] and len(contexts) == 11
        owner_context = contexts[5]
        assert owner_context["capabilities"] == {}
        summaries = [
            event["summary"]
            for read in owner_context["completed_reads"]
            for event in read["timeline"]
        ]
        assert any("图片已收到" in summary for summary in summaries)
        assert any("销售负责人核实" in summary for summary in summaries)
    finally:
        scenario.close()
