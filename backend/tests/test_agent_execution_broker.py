"""Real isolated Redis/worker restart acceptance; source retrieval never calls a model."""

import os
import subprocess
import sys
import time
from pathlib import Path
from uuid import uuid4

import pytest
from celery import Celery
from sqlalchemy import func, select
from test_agent_execution import submit
from test_knowledge import TEXT, create, publish

from app.infrastructure.db import session_factory
from app.infrastructure.models import AgentRun, ModelInvocation, WorkEvent
from app.modules.agent import execution


def test_stopped_worker_restarts_directory_and_content_with_duplicate_delivery(loop, tmp_path):
    broker_url = os.environ.get("COROOF_TEST_REDIS_URL")
    if not broker_url or session_factory().kw["bind"].dialect.name != "postgresql":
        pytest.skip("Explicit local Redis and PostgreSQL required")
    boss = loop[0]
    publish(boss, create(boss, title="差旅报销制度"))
    with session_factory()() as db:
        before = db.scalar(select(func.count()).select_from(WorkEvent))
    queue = "agent_test_" + uuid4().hex
    producer = Celery("agent_test_producer", broker=broker_url)
    process = None
    log = (tmp_path / "worker.log").open("w")

    def send(*args):
        for _ in range(2):
            producer.send_task("coroof.agent.process", args=args, queue=queue, ignore_result=True)

    def start():
        env = {
            **os.environ,
            "COROOF_REDIS_URL": broker_url,
            "COROOF_AI_PROVIDER": "rules",
            "COROOF_AI_API_KEY": "",
        }
        return subprocess.Popen(
            [
                sys.executable,
                "-m",
                "celery",
                "-A",
                "worker.app",
                "worker",
                "--pool=solo",
                "--loglevel=WARNING",
                "--without-gossip",
                "--without-mingle",
                "--without-heartbeat",
                "--queues",
                queue,
                "--hostname",
                queue + "@%h",
            ],
            cwd=Path(__file__).parents[1],
            env=env,
            stdout=log,
            stderr=subprocess.STDOUT,
        )

    def wait_completed(identifier):
        deadline = time.monotonic() + 25
        while time.monotonic() < deadline:
            with session_factory()() as db:
                row = db.get(AgentRun, identifier)
                if row.state == "completed":
                    assert row.answer["mode"] == "retrieval" and row.step_count == 1
                    return
                assert row.state in {"ready", "running"}, row.error_code
            assert process.poll() is None, "isolated worker exited"
            time.sleep(0.1)
        raise AssertionError("isolated worker did not finish queued retrieval")

    try:
        parent = submit(boss, question="现在企业有哪些知识库？")
        with session_factory()() as db:
            assert execution.dispatch(db, send) == 1
        process = start()
        wait_completed(parent["id"])
        process.terminate()
        process.wait(timeout=10)
        child = submit(boss, question="里面写了什么？", parent_run_id=parent["id"])
        with session_factory()() as db:
            assert execution.dispatch(db, send) == 1
        process = start()
        wait_completed(child["id"])
        assert (
            boss.get(f"/agent/runs/{child['id']}")["answer"]["document_answers"][0]["quote"] == TEXT
        )
        with session_factory()() as db:
            assert db.scalar(select(func.count()).select_from(ModelInvocation)) == 0
            assert db.scalar(select(func.count()).select_from(WorkEvent)) == before
    finally:
        if process and process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)
        with producer.connection_for_write() as connection:
            channel = connection.channel()
            channel.queue_delete(queue=queue)
            channel.close()
        producer.close()
        log.close()
