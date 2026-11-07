"""Stage 8.3: bounded unattended analysis, stable evidence, cost and failure fences."""

from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from threading import Event

import pytest
from conftest import API
from sqlalchemy import func, select
from test_agent_read import model, read_proposal
from test_connectors import enable, item, prepared, sync  # noqa: F401
from test_watch_controls import create

from app.core.config import settings
from app.infrastructure.db import session_factory
from app.infrastructure.models import AgentRun, ModelInvocation, WorkEvent, WorkItem, now
from app.modules.connectors.models import Connector
from app.modules.watch import runner, scheduler
from app.modules.watch.models import WatchPolicy, WatchRun
from worker.app import celery
from worker.watch import dispatch, process_step


def due(policy):
    with session_factory()() as db:
        row = db.get(WatchPolicy, policy["id"])
        row.next_due_at = now()
        db.commit()
        assert scheduler.schedule(db) == 1
        run = db.scalar(select(WatchRun).order_by(WatchRun.created_at.desc()))
        return run.id


def drain(identifier, development_config=None):
    for _ in range(10):
        with session_factory()() as db:
            row = db.get(WatchRun, identifier)
            if row.state != "queued":
                assert row.state != "running"
                return row.state, row.outcome_code
            task = row.organization_id, row.id, row.version
            db.rollback()
            runner.process(db, *task, development_config=development_config)
    raise AssertionError("background graph exceeded its bounded steps")


def test_background_finishes_without_browser_and_unchanged_context_is_free(loop, monkeypatch):
    boss, _, _, _, _, work = loop
    calls = model(monkeypatch)
    policy = create(boss)
    identifier = due(policy)
    with session_factory()() as db:
        before = db.scalar(select(func.count()).select_from(WorkEvent))
    assert boss.request("POST", "/auth/logout-all").status_code == 204
    assert drain(identifier) == ("completed", "analyzed")
    assert len(calls) == 2
    assert drain(due(policy)) == ("completed", "no_change")
    assert len(calls) == 2
    with session_factory()() as db:
        run = db.get(WatchRun, identifier)
        assert run.work_item_id == work["id"] and run.coverage_count == 1
        assert db.get(AgentRun, run.agent_run_id).answer
        assert db.scalar(select(func.count()).select_from(WorkEvent)) == before


def test_new_confirmed_fact_can_be_analyzed_but_draft_cannot(loop, monkeypatch):
    boss, _, _, _, _, work = loop
    calls = model(monkeypatch)
    policy = create(boss)
    assert drain(due(policy))[1] == "analyzed"
    draft = boss.draft(work)
    assert drain(due(policy))[1] == "no_change"
    assert len(calls) == 2
    boss.confirm(draft)
    assert drain(due(policy))[1] == "analyzed"
    assert len(calls) == 4


def test_empty_scope_and_rules_fallback_never_call_model(loop):
    boss = API("empty-watch@example.com")
    boss.org()
    policy = create(boss)
    assert drain(due(policy)) == ("completed", "no_data")
    native = create(loop[0])
    assert drain(due(native)) == ("completed", "rules_only")
    assert drain(due(native)) == ("completed", "no_change")
    with session_factory()() as db:
        assert db.scalar(select(func.count()).select_from(ModelInvocation)) == 0
        assert db.scalar(select(func.count()).select_from(AgentRun)) == 0


def test_analysis_limit_is_reserved_and_new_day_releases_capacity(loop, monkeypatch):
    boss, _, _, _, _, work = loop
    calls = model(monkeypatch)
    policy = create(boss, daily_analysis_limit=1)
    first = due(policy)
    assert drain(first)[1] == "analyzed"
    boss.confirm(boss.draft(work))
    assert drain(due(policy))[1] == "analysis_budget_exceeded"
    assert len(calls) == 2
    with session_factory()() as db:
        db.get(WatchRun, first).analysis_started_at = now() - timedelta(hours=25)
        db.commit()
    assert drain(due(policy))[1] == "analyzed"
    assert len(calls) == 4


def test_failed_analysis_is_not_blindly_rebilled(loop, monkeypatch):
    calls = model(monkeypatch, lambda _: {"kind": "invented_tool"})
    policy = create(loop[0])
    assert drain(due(policy)) == ("failed", "model_failed")
    assert drain(due(policy))[1] == "no_change"
    assert len(calls) == 1


def test_changed_source_between_graph_steps_invalidates_answer(loop, monkeypatch):
    boss, _, _, _, _, work = loop
    calls = model(monkeypatch)
    identifier = due(create(boss))
    with session_factory()() as db:
        row = db.get(WatchRun, identifier)
        runner.process(db, row.organization_id, row.id, row.version)
        row = db.get(WatchRun, identifier)
        runner.process(db, row.organization_id, row.id, row.version)
    assert len(calls) == 1
    boss.confirm(boss.draft(work))
    assert drain(identifier) == ("cancelled", "authorization_or_context_changed")
    assert len(calls) == 1
    with session_factory()() as db:
        row = db.get(WatchRun, identifier)
        assert db.get(AgentRun, row.agent_run_id).answer is None


def test_model_config_change_before_execution_does_not_spend_old_reservation(loop, monkeypatch):
    calls = model(monkeypatch)
    identifier = due(create(loop[0]))
    with session_factory()() as db:
        row = db.get(WatchRun, identifier)
        runner.process(db, row.organization_id, row.id, row.version)
    monkeypatch.setenv("COROOF_AI_MODEL", "changed-model")
    settings.cache_clear()
    assert drain(identifier) == ("cancelled", "authorization_or_context_changed")
    assert not calls


def test_celery_registered_dispatch_and_process_complete_an_offline_round(loop):
    create(loop[0])
    assert "worker.watch" in celery.conf.imports
    assert celery.conf.beat_schedule["continuous-agent"]["task"] == "coroof.watch.dispatch"
    tasks = []
    with session_factory()() as db:
        assert dispatch(db, lambda *args: tasks.append(args)) == 1
    assert process_step.run(*tasks[0]) is None
    assert process_step.run(*tasks[0]) is None
    with session_factory()() as db:
        row = db.get(WatchRun, tasks[0][1])
        assert row.state == "completed" and row.outcome_code == "rules_only"
        assert dispatch(db, lambda *args: tasks.append(args)) == 0


def test_unchanged_sync_does_not_rebill_and_stale_or_failed_source_is_unknown(
    prepared,  # noqa: F811 - imported pytest fixture
    monkeypatch,
):
    boss, _, _, _, native, connection = prepared
    enable(prepared, monkeypatch)
    sync(prepared, monkeypatch, [item()])
    with session_factory()() as db:
        db.get(WorkItem, native["id"]).lifecycle_status = "done"
        db.commit()
    calls = model(monkeypatch)
    policy = create(boss)
    assert drain(due(policy))[1] == "analyzed"
    sync(prepared, monkeypatch, [item()])
    assert drain(due(policy))[1] == "no_change"
    assert len(calls) == 2
    with session_factory()() as db:
        source = db.get(Connector, connection["id"])
        source.last_error = "source_unavailable"
        db.commit()
    assert drain(due(policy))[1] == "source_unavailable"
    with session_factory()() as db:
        source = db.get(Connector, connection["id"])
        source.last_error = None
        source.synced_at = now() - timedelta(hours=25)
        db.commit()
    assert drain(due(policy))[1] == "source_unavailable"
    assert len(calls) == 2


def test_duplicate_delivery_while_model_runs_has_one_effect(loop, monkeypatch):
    if session_factory().kw["bind"].dialect.name != "postgresql":
        pytest.skip("PostgreSQL model execution and duplicate delivery")
    entered, release = Event(), Event()

    def wait(_):
        entered.set()
        assert release.wait(10)
        return read_proposal()

    calls = model(monkeypatch, wait)
    identifier = due(create(loop[0]))
    with session_factory()() as db:
        row = db.get(WatchRun, identifier)
        runner.process(db, row.organization_id, row.id, row.version)
        row = db.get(WatchRun, identifier)
        task = row.organization_id, row.id, row.version

    def process():
        with session_factory()() as db:
            runner.process(db, *task)

    with ThreadPoolExecutor(max_workers=2) as pool:
        future = pool.submit(process)
        assert entered.wait(10)
        try:
            pool.submit(process).result(timeout=5)
        finally:
            release.set()
        future.result(timeout=10)
    assert len(calls) == 1
    with session_factory()() as db:
        assert db.get(WatchRun, identifier).state == "queued"
        assert db.scalar(select(func.count()).select_from(ModelInvocation)) == 1


def test_recovery_reuses_completed_child_without_repeating_paid_step(loop, monkeypatch):
    from uuid import uuid4

    from app.infrastructure.models import Membership
    from app.modules.agent import runtime
    from app.modules.agent.schemas import AdvanceInput

    calls = model(monkeypatch)
    identifier = due(create(loop[0]))
    with session_factory()() as db:
        row = db.get(WatchRun, identifier)
        runner.process(db, row.organization_id, row.id, row.version)
        row = db.get(WatchRun, identifier)
        runner.process(db, row.organization_id, row.id, row.version)
        row = db.get(WatchRun, identifier)
        row = scheduler.claim(db, row.organization_id, row.id, row.version)
        child = db.get(AgentRun, row.agent_run_id)
        actor = db.get(Membership, child.actor_id)
        completed = runtime.advance(
            db,
            actor,
            child.id,
            AdvanceInput(expected_version=child.version, idempotency_key=uuid4()),
        )
        assert completed.state == "completed"
        # Model step committed; process stopped before writing the outer watch result.
        row.lease_until = now() - timedelta(seconds=1)
        db.commit()
        assert scheduler.recover(db) == 1
    assert drain(identifier) == ("completed", "analyzed")
    assert len(calls) == 2


def test_background_history_includes_new_decisions_even_without_work_version_change(
    loop, monkeypatch
):
    from test_agent_actions import selection
    from test_watch_attention import prepare_background

    boss, _, _, _, _, work = loop
    policy, _, decision = prepare_background(loop, monkeypatch)
    with session_factory()() as db:
        version = db.get(WorkItem, work["id"]).version
    boss.post(f"/decisions/{decision['id']}/confirm", selection(decision))
    calls = model(monkeypatch)
    assert drain(due(policy))[1] == "analyzed"
    timeline = calls[1]["completed_reads"][0]["timeline"]
    assert any(event["event_type"] == "decision.confirmed" for event in timeline)
    with session_factory()() as db:
        assert db.get(WorkItem, work["id"]).version == version


def test_large_scope_reports_bounded_batch_and_rotates_coverage(loop):
    _, _, org, departments, _, _ = loop
    with session_factory()() as db:
        db.add_all(
            [
                WorkItem(
                    organization_id=org["id"],
                    department_id=departments[0]["id"],
                    title=f"合成覆盖 {i}",
                )
                for i in range(104)
            ]
        )
        db.commit()
    policy = create(loop[0])
    first = due(policy)
    drain(first)
    second = due(policy)
    drain(second)
    with session_factory()() as db:
        a, b = db.get(WatchRun, first), db.get(WatchRun, second)
        assert a.coverage_count == b.coverage_count == 105
        assert a.considered_count == 100 and b.considered_count == 5
        assert a.work_item_id != b.work_item_id


def test_coding_plan_history_and_decision_fit_default_input_limit(loop, monkeypatch):
    import json

    from pydantic import SecretStr
    from test_agent_actions import selection
    from test_agent_read import finish
    from test_model_gateway import config, mock_transport, response
    from test_watch_attention import prepare_background

    boss, _, _, _, _, work = loop
    policy, _, decision = prepare_background(loop, monkeypatch)
    boss.post(f"/decisions/{decision['id']}/confirm", selection(decision))
    calls = []

    def handle(request):
        context = json.loads(json.loads(request.content)["messages"][-1]["content"])
        calls.append(context)
        proposal = (
            read_proposal("work.investigate", work["id"])
            if len(calls) == 1
            else read_proposal("attention.explain")
            if len(calls) == 2
            else read_proposal("preference.read")
            if len(calls) == 3
            else finish(context)
        )
        return response(proposal, usage={"prompt_tokens": 10, "completion_tokens": 5})

    mock_transport(monkeypatch, handle)
    cfg = config(
        environment="test",
        ai_base_url="https://coding.dashscope.aliyuncs.com/v1",
        ai_api_key=SecretStr("sk-sp-fixture-not-real"),
        ai_model_verified=False,
    )
    assert drain(due(policy), cfg)[1] == "analyzed"
    assert len(calls) == 4
    assert sum(len(read["timeline"]) for read in calls[-1]["completed_reads"]) == 2
