"""Opt-in real broker/worker restart acceptance, isolated schema and queue only."""

import os
import subprocess
import sys
import time
from pathlib import Path
from uuid import uuid4

import pytest
from celery import Celery
from sqlalchemy import func, select
from test_agent_actions import event_count
from test_watch_controls import create

from app.infrastructure.db import session_factory
from app.modules.watch.models import AttentionItem, WatchRun
from worker.watch import dispatch


def test_worker_stopped_during_delivery_recovers_without_duplicate_effect(loop, tmp_path):
    broker_url = os.environ.get("COROOF_TEST_REDIS_URL")
    if not broker_url or session_factory().kw["bind"].dialect.name != "postgresql":
        pytest.skip("Explicit local Redis plus PostgreSQL required for real process acceptance")
    boss = loop[0]
    boss.confirm(boss.draft(loop[-1]))
    create(boss)
    before = event_count()
    queue = "watch_test_" + uuid4().hex
    producer = Celery("watch_test_producer", broker=broker_url)
    tasks = []
    process = None
    log = (tmp_path / "worker.log").open("w")

    def publish(*args):
        tasks.append(args)
        for _ in range(2):  # Duplicate delivery after an ambiguous broker receipt.
            producer.send_task("coroof.watch.process", args=args, queue=queue, ignore_result=True)

    def start():
        env = {**os.environ, "COROOF_REDIS_URL": broker_url}
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
                row = db.get(WatchRun, identifier)
                if row.state == "completed":
                    assert row.outcome_code == "rules_only"
                    return
            assert process.poll() is None, "isolated worker exited"
            time.sleep(0.1)
        raise AssertionError("isolated worker did not finish the queued check")

    try:
        with session_factory()() as db:
            assert dispatch(db, publish) == 1
        # Task was queued while there was no consumer. Starting it must recover the task.
        process = start()
        wait_completed(tasks[-1][1])
        process.terminate()
        process.wait(timeout=10)
        boss.confirm(boss.draft(loop[-1], raw="合成恢复验收：资料清单已补充，仍需支持"))
        with session_factory()() as db:
            assert dispatch(db, publish) == 1
        process = start()
        wait_completed(tasks[-1][1])
        assert event_count() == before + 1
        with session_factory()() as db:
            assert db.scalar(select(func.count()).select_from(WatchRun)) == 2
            assert db.scalar(select(func.count()).select_from(AttentionItem)) == 1
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
