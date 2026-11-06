"""Offline HTTP contracts and actual tenant transactions; no remote credentials."""

import json
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from threading import Event
from uuid import uuid4

import httpx
import pytest
import requests
import responses
from alembic import command
from conftest import API
from cryptography.fernet import Fernet
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from app.core.config import settings
from app.infrastructure.db import session_factory
from app.infrastructure.models import Membership, WorkEvent, now, utc
from app.modules.connectors import providers, service
from app.modules.connectors.models import (
    Connector,
    SourceMember,
    SourceRecord,
    SyncOutbox,
    SyncRun,
)
from app.modules.connectors.providers import Batch, SourceConfig, SourceFailure
from app.modules.connectors.schemas import Credentials
from app.modules.connectors.secrets import unseal
from worker.connectors import dispatch

TOKEN = "synthetic-offline-token-1234"
AT = datetime(2026, 1, 1, tzinfo=UTC)
CFG = SourceConfig("gitlab", "https://gitlab.com", "7", "issue", None, Credentials(token=TOKEN))
ROOT = "https://gitlab.com/api/v4/projects/7"


def raw(i=1, **kw):
    return {
        "id": 100 + i,
        "iid": i,
        "project_id": 7,
        "title": f"合成事项 {i}",
        "state": "opened",
        "updated_at": AT.isoformat(),
        "assignees": [],
        "web_url": f"https://gitlab.com/demo/project/-/issues/{i}",
        **kw,
    }


def item(i=1, **kw):
    return providers.gitlab_item(raw(i, **kw), CFG)


@pytest.fixture
def prepared(loop, monkeypatch):
    monkeypatch.setenv("COROOF_AI_SECRET_KEY", Fernet.generate_key().decode())
    settings.cache_clear()
    boss, employee, org, depts, member, native = loop
    connection = boss.post(
        "/connectors",
        {
            "name": "离线 GitLab",
            "kind": "gitlab",
            "base_url": CFG.base_url,
            "project_key": "7",
            "department_id": depts[0]["id"],
            "credentials": {"token": TOKEN},
            "status_map": {"opened": "planned", "closed": "done"},
            "share_with_department": True,
        },
        201,
    )
    return boss, employee, org, member, native, connection


def latest(boss):
    return boss.get("/connectors")["items"][0]


def start(boss, connection, mode="full", key=None, status=202):
    return boss.post(
        f"/connectors/{connection['id']}/syncs",
        {
            "expected_version": connection["version"],
            "mode": mode,
            "idempotency_key": key or str(uuid4()),
        },
        status,
    )


def step(org, run):
    with session_factory()() as db:
        service.process(db, org["id"], run["id"], run["version"])
        db.expire_all()
        value = db.get(SyncRun, run["id"])
        return {
            "id": value.id,
            "version": value.version,
            "state": value.state,
            "phase": value.phase,
            "processed": value.processed,
            "error": value.error_code,
        }


def drain(org, run):
    for _ in range(10):
        if run["state"] not in service.ACTIVE:
            return run
        run = step(org, run)
    raise AssertionError("worker did not finish")


def enable(prepared, monkeypatch):
    boss, _, org, _, _, connection = prepared
    monkeypatch.setattr(providers, "fetch", lambda *a, **k: Batch([], False))
    assert drain(org, start(boss, connection, "verify"))["state"] == "succeeded"
    connection = latest(boss)
    return boss.post(
        f"/connectors/{connection['id']}/state",
        {"expected_version": connection["version"], "action": "activate"},
    )


def sync(prepared, monkeypatch, rows, mode="full"):
    boss, _, org, *_ = prepared
    monkeypatch.setattr(providers, "fetch", lambda *a, **k: Batch(rows, False))
    return drain(org, start(boss, latest(boss), mode))


@responses.activate
def test_gitlab_sdk_pagination_incremental_and_read_scope(monkeypatch):
    monkeypatch.setattr(providers, "PAGE_SIZE", 2)
    responses.get(ROOT, json={"id": 7})
    responses.get(ROOT + "/issues", json=[raw(1), raw(2)])
    batch = providers.fetch(CFG, 3, AT, AT + timedelta(days=1))
    assert batch.more and [x.external_id for x in batch.items] == ["1", "2"]
    request = responses.calls[-1].request
    assert request.headers["PRIVATE-TOKEN"] == TOKEN
    query = httpx.URL(request.url).params
    assert query["page"] == "3" and query["per_page"] == "2"
    assert query["updated_after"] == AT.isoformat()
    assert query["scope"] == "all" and query["state"] == "all"
    assert batch.items[0].assignees == []
    for method, url in [
        ("POST", ROOT + "/issues"),
        ("GET", "https://evil.invalid/a"),
        ("GET", "https://gitlab.com/api/v4/projects/8/issues"),
    ]:
        with providers.ReadSession(CFG.base_url, CFG.project_key) as session:
            with pytest.raises(SourceFailure, match="endpoint_denied"):
                session.send(requests.Request(method, url).prepare())


@pytest.mark.parametrize(
    "status,code,retry",
    [
        (401, "source_denied", False),
        (403, "source_denied", False),
        (404, "source_denied", False),
        (429, "source_unavailable", True),
        (503, "source_unavailable", True),
        (302, "invalid_response", False),
    ],
)
@responses.activate
def test_gitlab_http_failure_redaction(status, code, retry):
    responses.get(ROOT, status=status, body=TOKEN, headers={"Location": "https://evil.invalid"})
    with pytest.raises(SourceFailure) as error:
        providers.fetch(CFG, 1, None, now())
    assert error.value.code == code and error.value.retryable == retry
    assert TOKEN not in str(error.value) and len(responses.calls) == 1


@responses.activate
def test_gitlab_item_removal_is_not_credential_revocation():
    responses.get(ROOT, json={"id": 7})
    responses.get(ROOT + "/issues/1", status=404)
    assert not providers.fetch(CFG, 1, None, now(), external_id="1").items
    responses.replace(responses.GET, ROOT + "/issues/1", status=401)
    with pytest.raises(SourceFailure, match="source_denied"):
        providers.fetch(CFG, 1, None, now(), external_id="1")


@responses.activate
def test_gitlab_malformed_and_wrong_scope_are_not_facts():
    responses.get(ROOT, json={"id": 7})
    responses.get(ROOT + "/issues", json=[raw(project_id=8)])
    with pytest.raises(SourceFailure, match="scope_mismatch"):
        providers.fetch(CFG, 1, None, now())
    responses.replace(responses.GET, ROOT + "/issues", body="not json")
    with pytest.raises(SourceFailure, match="invalid_response"):
        providers.fetch(CFG, 1, None, now())
    responses.replace(responses.GET, ROOT + "/issues", body="x" * (providers.MAX_BODY + 1))
    with pytest.raises(SourceFailure, match="response_too_large"):
        providers.fetch(CFG, 1, None, now())


def test_feishu_project_contract_and_ambiguous_members(monkeypatch):
    calls = []

    def transport(req):
        body = json.loads(req.content)
        calls.append((str(req.url), body))
        if req.url.path.endswith("plugin_token"):
            assert body == {"plugin_id": "plugin", "plugin_secret": "synthetic", "type": 0}
            return httpx.Response(200, json={"data": {"token": "temporary", "expire_time": 3600}})
        assert req.headers["X-Plugin-Token"] == "temporary"
        assert req.headers["X-User-Key"] == "user"
        assert body["work_item_type_keys"] == ["story"]
        assert body["updated_at"]["start"] == int(AT.timestamp() * 1000)
        return httpx.Response(
            200,
            json={
                "err_code": 0,
                "data": [
                    {
                        "id": 23,
                        "project_key": "space",
                        "work_item_type_key": "story",
                        "name": "合成飞书事项",
                        "updated_at": int(AT.timestamp() * 1000),
                        "work_item_status": {"state_key": "started"},
                        "fields": [{"field_key": "owner", "field_value": ["user-a"]}],
                    }
                ],
                "pagination": {"page_num": 2, "page_size": 50, "total": 51},
            },
        )

    client = httpx.Client
    monkeypatch.setattr(
        httpx, "Client", lambda **kw: client(transport=httpx.MockTransport(transport), **kw)
    )
    cfg = SourceConfig(
        "feishu_project",
        "https://project.feishu.cn",
        "space",
        "story",
        "owner",
        Credentials(plugin_id="plugin", plugin_secret="synthetic", user_key="user"),
    )
    batch = providers.fetch(cfg, 2, AT, now())
    assert not batch.more and batch.items[0].assignees == ["user-a"]
    assert batch.items[0].source_url is None and batch.items[0].state == "started"
    unknown = providers.feishu_item({**batch.items[0].raw, "fields": []}, cfg)
    assert unknown.assignees is None
    assert len(calls) == 2


def test_credentials_saved_only_tenant_bound_and_owner_only(prepared, monkeypatch):
    boss, employee, org, _, _, connection = prepared
    assert connection["state"] == "saved" and connection["key_hint"] == "••••1234"
    assert TOKEN not in json.dumps(connection)
    employee.get("/connectors", 403)
    start(boss, connection, status=409)
    with session_factory()() as db:
        row = db.get(Connector, connection["id"])
        assert TOKEN not in row.credential and unseal(row).token.get_secret_value() == TOKEN
        row.organization_id = str(uuid4())
        with pytest.raises(SourceFailure, match="credential_unavailable"):
            unseal(row)
    other = API("other@example.com")
    other.org("合成企业乙")
    other.get(f"/connectors/{connection['id']}/syncs", 404)
    bad = boss.post(
        f"/connectors/{connection['id']}/credentials",
        {"expected_version": connection["version"], "credentials": {}},
        422,
    )
    assert TOKEN not in json.dumps(bad)


def test_sync_mapping_idempotency_source_truth_and_incremental(prepared, monkeypatch):
    boss, employee, org, member, _, connection = prepared
    connection = enable(prepared, monkeypatch)
    rows = [item(assignees=[{"id": 9}])]
    assert sync(prepared, monkeypatch, rows)["state"] == "succeeded"
    path = f"/connectors/{connection['id']}"
    pending = boss.get(path + "/sources")["items"][0]
    assert pending["mapping_issue"] == "unmapped_member" and pending["work_item_id"] is None
    connection = latest(boss)
    result = boss.request(
        "PUT",
        path + "/mapping",
        {
            "expected_version": connection["version"],
            "status_map": connection["status_map"],
            "members": {"9": member["id"]},
        },
    )
    assert result.status_code == 200, result.text
    assert sync(prepared, monkeypatch, rows)["state"] == "succeeded"
    source = boss.get(path + "/sources")["items"][0]
    work = boss.get(f"/work-items/{source['work_item_id']}")
    assert work["owner_id"] == member["id"] and work["source_authority"] == "external"
    assert datetime.fromisoformat(work["updated_at"].replace("Z", "+00:00")) == AT
    employee.get(f"/work-items/{work['id']}")
    boss.post("/work-updates/drafts", {"work_item_id": work["id"], "raw_text": "更新内容"}, 409)
    proof = boss.get(f"/work-items/{work['id']}/source")
    assert proof["external_id"] == "1" and "未同步" in proof["notice"]
    events = boss.get(f"/work-items/{work['id']}/events")["total"]
    connection = latest(boss)
    key = str(uuid4())
    run = start(boss, connection, "incremental", key)
    assert start(boss, connection, "incremental", key)["id"] == run["id"]
    assert drain(org, run)["state"] == "succeeded"
    assert boss.get(f"/work-items/{work['id']}/events")["total"] == events
    with session_factory()() as db:
        assert db.scalar(select(func.count()).select_from(SourceRecord)) == 1
        persisted = db.get(SyncRun, run["id"])
        assert persisted.since and utc(persisted.since) < utc(persisted.until)
    # Retesting an active connection must not withdraw its published records.
    assert drain(org, start(boss, latest(boss), "verify"))["state"] == "succeeded"
    assert latest(boss)["state"] == "active"


def test_full_scan_rechecks_missing_items_and_revoke_hides_everywhere(prepared, monkeypatch):
    boss, employee, org, _, _, connection = prepared
    enable(prepared, monkeypatch)
    sync(prepared, monkeypatch, [item()])
    source = boss.get(f"/connectors/{connection['id']}/sources")["items"][0]
    work_id = source["work_item_id"]
    calls = []

    def fetch(*a, **kw):
        calls.append(kw.get("external_id"))
        return (
            Batch([item(title="同步途中已更新")], False)
            if kw.get("external_id")
            else Batch([], False)
        )

    monkeypatch.setattr(providers, "fetch", fetch)
    assert drain(org, start(boss, latest(boss)))["state"] == "succeeded"
    assert calls == [None, "1"] and boss.get(f"/work-items/{work_id}")["title"] == "同步途中已更新"
    monkeypatch.setattr(providers, "fetch", lambda *a, **kw: Batch([], False))
    drain(org, start(boss, latest(boss)))
    boss.get(f"/work-items/{work_id}", 404)
    assert sync(prepared, monkeypatch, [item()])["state"] == "succeeded"
    boss.get(f"/work-items/{work_id}")
    connection = latest(boss)
    boss.post(
        f"/connectors/{connection['id']}/state",
        {"expected_version": connection["version"], "action": "revoke"},
    )
    boss.get(f"/work-items/{work_id}", 404)
    boss.get(f"/work-items/{work_id}/events", 404)
    boss.get(f"/work-items/{work_id}/source", 404)
    boss.get(f"/connectors/{connection['id']}/sources", 409)
    assert all(w["id"] != work_id for w in boss.get("/work-items")["items"])
    with session_factory()() as db:
        assert db.get(Connector, connection["id"]).credential is None
        assert db.scalar(select(func.count()).select_from(SourceRecord)) == 2


def test_retry_failure_and_outbox_delivery_recovery(prepared, monkeypatch):
    boss, _, org, *_ = prepared
    enable(prepared, monkeypatch)

    def fail(*a, **k):
        raise SourceFailure("source_unavailable", retryable=True)

    monkeypatch.setattr(providers, "fetch", fail)
    run = start(boss, latest(boss))
    run = step(org, run)
    assert run["state"] == "retry_wait"
    with session_factory()() as db:
        retry = db.scalar(
            select(SyncOutbox)
            .where(SyncOutbox.run_id == run["id"])
            .order_by(SyncOutbox.available_at.desc())
        )
        assert (
            utc(retry.available_at) > now()
            and db.get(Connector, latest(boss)["id"]).watermark is None
        )

        def broker_down(*args):
            raise ConnectionError("synthetic broker failure")

        assert dispatch(db, broker_down) == 0
        assert (
            db.scalar(
                select(func.count())
                .select_from(SyncOutbox)
                .where(SyncOutbox.published_at.is_(None))
            )
            > 0
        )
    for _ in range(4):
        run = step(org, run)
    assert run["state"] == "failed"
    # Next run with a revoked remote credential hides previously published work.
    sync(prepared, monkeypatch, [item()])

    def denied(*a, **k):
        raise SourceFailure("source_denied")

    monkeypatch.setattr(providers, "fetch", denied)
    assert drain(org, start(boss, latest(boss)))["state"] == "failed"
    assert latest(boss)["state"] == "permission_lost"
    assert all(w["source_authority"] == "native" for w in boss.get("/work-items")["items"])


def test_inflight_configuration_change_and_stale_worker_are_fenced(prepared, monkeypatch):
    boss, _, org, *_ = prepared
    connection = enable(prepared, monkeypatch)

    def fetch(*args, **kw):
        boss.post(
            f"/connectors/{connection['id']}/state",
            {"expected_version": connection["version"], "action": "revoke"},
        )
        return Batch([item()], False)

    monkeypatch.setattr(providers, "fetch", fetch)
    run = start(boss, connection)
    assert step(org, run)["state"] == "cancelled"
    assert step(org, run)["state"] == "cancelled"
    with session_factory()() as db:
        assert db.scalar(select(func.count()).select_from(SourceRecord)) == 0


def test_expired_worker_lease_recovers_without_duplicate_projection(prepared, monkeypatch):
    boss, _, org, *_ = prepared
    enable(prepared, monkeypatch)
    run = start(boss, latest(boss))
    with session_factory()() as db:
        record = db.get(SyncRun, run["id"])
        record.state = "running"
        record.version += 1
        record.lease_until = now() - timedelta(seconds=1)
        db.commit()
        assert service.recover(db) == 1
        assert service.recover(db) == 0
    old = step(org, run)
    assert old["state"] == "queued"
    monkeypatch.setattr(providers, "fetch", lambda *a, **k: Batch([item()], False))
    assert drain(org, old)["state"] == "succeeded"
    with session_factory()() as db:
        assert (
            db.scalar(
                select(func.count())
                .select_from(WorkEvent)
                .where(WorkEvent.event_type == "source.synced")
            )
            == 1
        )


def test_member_revocation_unknown_status_and_older_record(prepared, monkeypatch):
    boss, _, _, member, *_ = prepared
    enable(prepared, monkeypatch)
    sync(prepared, monkeypatch, [item(state="unmapped", assignees=[{"id": 9}])])
    assert latest(boss)["pending_count"] == 1
    assert sync(prepared, monkeypatch, [item(state="opened")])["state"] == "succeeded"
    sync(
        prepared,
        monkeypatch,
        [item(state="closed", updated_at=(AT - timedelta(days=1)).isoformat())],
    )
    sources = boss.get(f"/connectors/{latest(boss)['id']}/sources")["items"]
    assert boss.get(f"/work-items/{sources[0]['work_item_id']}")["lifecycle_status"] == "planned"


def test_mapping_foreign_tenant_rejected_by_database(prepared):
    boss, _, org, member, _, connection = prepared
    other = API("foreign@example.com")
    foreign = other.org("异租户")
    with session_factory()() as db:
        foreign_member = db.scalar(
            select(Membership).where(Membership.organization_id == foreign["id"])
        )
        db.add(
            SourceMember(
                organization_id=org["id"],
                connector_id=connection["id"],
                external_id="9",
                membership_id=foreign_member.id,
            )
        )
        with pytest.raises(IntegrityError):
            db.commit()


def test_migration_preserves_existing_native_work(prepared, database):
    boss, _, _, _, native, _ = prepared
    command.downgrade(database, "0007_agent_drafts")
    command.upgrade(database, "head")
    assert boss.get(f"/work-items/{native['id']}")["title"] == native["title"]
    command.check(database)


def test_postgres_duplicate_workers_have_one_effect(prepared, monkeypatch):
    if session_factory().kw["bind"].dialect.name != "postgresql":
        pytest.skip("PostgreSQL row locks")
    boss, _, org, *_ = prepared
    enable(prepared, monkeypatch)
    entered, release = Event(), Event()

    def fetch(*a, **k):
        entered.set()
        assert release.wait(10)
        return Batch([item()], False)

    monkeypatch.setattr(providers, "fetch", fetch)
    run = start(boss, latest(boss))
    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(step, org, run)
        assert entered.wait(10)
        second = pool.submit(step, org, run)
        assert second.result(10)["state"] == "running"
        release.set()
        updated = first.result(10)
    assert drain(org, updated)["state"] == "succeeded"
    with session_factory()() as db:
        assert db.scalar(select(func.count()).select_from(SourceRecord)) == 1
        assert (
            db.scalar(
                select(func.count())
                .select_from(WorkEvent)
                .where(WorkEvent.event_type == "source.synced")
            )
            == 1
        )


def test_revocation_removes_evidence_analysis_and_decisions(prepared, monkeypatch):
    from test_slice02 import ask, confirm_body, prepare

    boss, _, _, _, _, connection = prepared
    enable(prepared, monkeypatch)
    sync(prepared, monkeypatch, [item()])
    work_id = boss.get(f"/connectors/{connection['id']}/sources")["items"][0]["work_item_id"]
    work = boss.get(f"/work-items/{work_id}")
    answer = ask(boss, work)
    decision = prepare(boss, answer, work)
    boss.post(f"/decisions/{decision['id']}/confirm", confirm_body(decision))
    assert boss.get("/dashboard")["external_data"] == "partial"
    evidence_id = answer["evidence"][0]["id"]
    connection = latest(boss)
    boss.post(
        f"/connectors/{connection['id']}/state",
        {"expected_version": connection["version"], "action": "revoke"},
    )
    boss.get(f"/evidence/{evidence_id}", 404)
    boss.get(f"/decisions/{decision['id']}", 404)
    boss.get(f"/decisions/{decision['id']}/outcomes", 404)
    assert all(row["id"] != decision["id"] for row in boss.get("/decisions")["items"])


def test_worker_rechecks_owner_after_external_read(prepared, monkeypatch):
    boss, _, org, *_ = prepared
    connection = enable(prepared, monkeypatch)

    def fetch(*args, **kwargs):
        with session_factory()() as db:
            actor = next(
                m
                for m in db.scalars(
                    select(Membership).where(Membership.organization_id == org["id"])
                )
                if "owner" in m.roles
            )
            actor.roles = ["member"]
            db.commit()
        return Batch([item()], False)

    monkeypatch.setattr(providers, "fetch", fetch)
    run = start(boss, connection)
    assert step(org, run)["state"] == "cancelled"
    with session_factory()() as db:
        assert db.scalar(select(func.count()).select_from(SourceRecord)) == 0


def test_outbox_publish_ack_and_duplicate_delivery(prepared, monkeypatch):
    boss, _, org, *_ = prepared
    connection = enable(prepared, monkeypatch)
    monkeypatch.setattr(providers, "fetch", lambda *a, **k: Batch([item()], False))
    run = start(boss, connection)
    delivered = []
    with session_factory()() as db:
        assert dispatch(db, lambda *message: delivered.append(message)) > 0
        assert dispatch(db, lambda *message: delivered.append(message)) == 0
    for org_id, identifier, version in delivered * 2:
        with session_factory()() as db:
            service.process(db, org_id, identifier, version)
    with session_factory()() as db:
        current = db.get(SyncRun, run["id"])
        finish = {"id": current.id, "version": current.version, "state": current.state}
    assert drain(org, finish)["state"] == "succeeded"
    with session_factory()() as db:
        assert (
            db.scalar(
                select(func.count())
                .select_from(WorkEvent)
                .where(WorkEvent.event_type == "source.synced")
            )
            == 1
        )


def test_feishu_invalid_response_stops_cursor(monkeypatch):
    client = httpx.Client
    cfg = SourceConfig(
        "feishu_project",
        "https://project.feishu.cn",
        "space",
        "story",
        "owner",
        Credentials(plugin_id="plugin", plugin_secret="synthetic", user_key="user"),
    )

    def handle(request):
        return httpx.Response(
            200,
            json={"data": {"token": "temporary"}}
            if request.url.path.endswith("plugin_token")
            else {
                "err_code": 0,
                "data": [],
                "pagination": {"page_num": 1, "page_size": 50, "total": 51},
            },
        )

    monkeypatch.setattr(
        httpx, "Client", lambda **kw: client(transport=httpx.MockTransport(handle), **kw)
    )
    with pytest.raises(SourceFailure, match="invalid_response"):
        providers.fetch(cfg, 1, None, now())


def test_lost_permission_cannot_be_reactivated_through_pause(prepared, monkeypatch):
    boss, _, org, *_ = prepared
    enable(prepared, monkeypatch)

    def denied(*args, **kwargs):
        raise SourceFailure("source_denied")

    monkeypatch.setattr(providers, "fetch", denied)
    assert drain(org, start(boss, latest(boss)))["state"] == "failed"
    connection = latest(boss)
    for action in ("pause", "activate"):
        boss.post(
            f"/connectors/{connection['id']}/state",
            {"expected_version": connection["version"], "action": action},
            409,
        )
    assert latest(boss)["state"] == "permission_lost"
