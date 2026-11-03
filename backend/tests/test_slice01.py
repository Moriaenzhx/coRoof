from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from uuid import uuid4

import pytest
from alembic import command
from conftest import API
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from app.core.config import Settings, settings
from app.infrastructure.db import session_factory
from app.infrastructure.models import (
    AnalysisRun,
    AuthSession,
    Invitation,
    UpdateDraft,
    WorkEvent,
    WorkItem,
    now,
)
from app.main import app
from worker.app import ping


def test_empty_database_health_migration_and_worker(database):
    with TestClient(app) as client:
        assert client.get("/healthz").json() == {"status": "ok"}
        assert client.get("/readyz").json() == {"status": "ready"}
        info = client.get("/api/v1/runtime").json()
        assert info["auth_mode"] == "mock"
        assert not info["production_ready"]
    command.check(database)
    command.downgrade(database, "base")
    command.upgrade(database, "head")
    assert ping.apply().get() == ping.apply().get() == "pong"


def test_acceptance_loop_confirm_once_and_evidence(loop):
    boss, employee, org, depts, member, work = loop
    assert employee.get("/work-items?mine=true")["items"][0]["id"] == work["id"]
    draft = employee.draft(work)
    assert draft["provider"] == "rules"
    assert employee.get(f"/work-items/{work['id']}")["needs_support"] is False
    assert len(boss.get(f"/work-items/{work['id']}/events")["items"]) == 1
    event = employee.confirm(draft)
    repeated = employee.confirm(draft)
    assert repeated["id"] == event["id"]
    projected = boss.get(f"/work-items/{work['id']}")
    assert projected["needs_support"]
    assert projected["lifecycle_status"] == "planned"
    assert projected["owner_id"] == member["id"]
    dashboard = boss.get("/dashboard")
    assert dashboard["support_work"] == 1
    assert dashboard["total_work"] == 1
    assert sum(d["coverage"] == "unknown" for d in dashboard["departments"]) == 2
    assert dashboard["external_data"] == "not_connected"
    assert event["source_ref"] == f"draft:{draft['id']}"
    assert event["event_payload"]["raw_text"] == "客户资料晚到两天，需要交付协调"
    assert len(boss.get(f"/work-items/{work['id']}/events")["items"]) == 2
    with session_factory()() as db:
        run = db.scalar(select(AnalysisRun))
        assert run.status == "rules_fallback"
        assert run.input_evidence_ids[0] == f"draft:{draft['id']}"
        assert db.scalar(select(func.count()).select_from(WorkEvent)) == 2


def test_cross_tenant_reads_writes_and_relations(loop):
    boss, employee, org, depts, member, work = loop
    outsider = API("other-owner@example.com", "另一老板")
    other_org = outsider.org("验收企业乙")
    other_dept = outsider.department("乙部门")
    other_work = outsider.work(other_dept)
    for path in (
        f"/work-items/{work['id']}",
        f"/work-items/{work['id']}/events",
        f"/members/{member['id']}",
    ):
        outsider.get(path, 404)
    outsider.client.headers["X-Organization-Id"] = org["id"]
    outsider.get("/dashboard", 403)
    outsider.client.headers["X-Organization-Id"] = other_org["id"]
    outsider.post("/work-items", {"title": "invalid", "department_id": depts[0]["id"]}, 404)
    boss.post(
        "/work-items",
        {"title": "invalid", "department_id": depts[0]["id"], "initiative_id": other_work["id"]},
        404,
    )
    employee.get(f"/work-items/{other_work['id']}", 404)
    assert outsider.get("/dashboard")["total_work"] == 1
    # Composite FK protects against an internal service accidentally crossing a tenant boundary.
    with session_factory()() as db:
        row = db.get(WorkItem, work["id"])
        row.department_id = other_dept["id"]
        with pytest.raises(IntegrityError):
            db.commit()


def test_member_cannot_list_peers_create_or_confirm_other_drafts(loop):
    boss, employee, org, depts, member, work = loop
    another = boss.work(depts[0])
    employee.get(f"/work-items/{another['id']}", 404)
    assert employee.get("/work-items")["total"] == 1
    assert employee.get("/members")["total"] == 1
    employee.post("/departments", {"name": "非法"}, 403)
    employee.post("/work-items", {"title": "非法", "department_id": depts[0]["id"]}, 403)
    employee.post(
        "/members/invitations", {"email": "third@example.com", "department_id": depts[0]["id"]}, 403
    )
    draft = boss.draft(work)
    employee.confirm(draft, 404)
    employee.post("/decisions/example/confirm", {}, 404)  # Slice 02 is deliberately unavailable.
    assert employee.get("/dashboard")["scope"] == "assigned"


def test_manager_department_scope_and_role_escalation(loop):
    boss, employee, org, depts, member, work = loop
    manager = API("manager@example.com", "交付负责人")
    invitation = boss.invite(depts[0], "manager@example.com", ["manager", "member"])
    manager.join(invitation, org["id"])
    manager.work(depts[0], member)
    other = boss.work(depts[1])
    assert manager.get("/work-items")["total"] == 2
    assert manager.get("/dashboard")["scope"] == "department"
    manager.get(f"/work-items/{other['id']}", 404)
    manager.post("/work-items", {"title": "outside", "department_id": depts[1]["id"]}, 403)
    manager.post(
        "/members/invitations",
        {"email": "x@example.com", "department_id": depts[0]["id"], "roles": ["manager"]},
        403,
    )
    manager.post(
        "/members/invitations", {"email": "x@example.com", "department_id": depts[1]["id"]}, 403
    )
    manager.post(
        "/members/invitations",
        {"email": "x@example.com", "department_id": depts[0]["id"], "roles": ["owner"]},
        422,
    )


def test_edit_draft_requires_revision_and_confirmation(loop):
    boss, employee, org, depts, member, work = loop
    draft = employee.draft(work)
    response = employee.request(
        "PATCH",
        f"/work-updates/drafts/{draft['id']}",
        {
            "expected_revision": draft["revision"],
            "proposed_fields": {
                "summary": "已协调，等待资料",
                "lifecycle_status": "in_progress",
                "needs_support": False,
            },
        },
    )
    assert response.status_code == 200, response.text
    edited = response.json()
    employee.confirm(draft, 409)
    assert boss.get(f"/work-items/{work['id']}")["lifecycle_status"] == "planned"
    employee.confirm(edited)
    projected = boss.get(f"/work-items/{work['id']}")
    assert projected["lifecycle_status"] == "in_progress"
    assert not projected["needs_support"]
    assert (
        employee.request(
            "PATCH",
            f"/work-updates/drafts/{draft['id']}",
            {
                "expected_revision": edited["revision"],
                "proposed_fields": {"summary": "tamper"},
            },
        ).status_code
        == 409
    )


@pytest.mark.parametrize("action", ["progress", "support", "done", "resolve_support"])
def test_quick_actions_idempotency_and_payload_conflict(loop, action):
    boss, employee, org, depts, member, work = loop
    body = {"action": action, "expected_version": work["version"], "idempotency_key": str(uuid4())}
    path = f"/work-items/{work['id']}/updates"
    first = employee.post(path, body)
    assert employee.post(path, body)["id"] == first["id"]
    employee.post(path, {**body, "summary": "different"}, 409)
    assert boss.get(f"/work-items/{work['id']}/events")["total"] == 2


def test_stale_draft_and_terminal_state_are_rejected(loop):
    boss, employee, org, depts, member, work = loop
    draft = employee.draft(work)
    employee.post(
        f"/work-items/{work['id']}/updates",
        {
            "action": "done",
            "expected_version": work["version"],
            "idempotency_key": str(uuid4()),
        },
    )
    employee.confirm(draft, 409)
    current = employee.get(f"/work-items/{work['id']}")
    assert not current["needs_support"]
    employee.post(
        f"/work-items/{work['id']}/updates",
        {
            "action": "progress",
            "expected_version": current["version"],
            "idempotency_key": str(uuid4()),
        },
        409,
    )


def test_reassignment_removes_old_access(loop):
    boss, employee, org, depts, member, work = loop
    draft = employee.draft(work)
    response = boss.request(
        "PATCH",
        f"/work-items/{work['id']}/assignment",
        {
            "owner_id": None,
            "expected_version": work["version"],
            "idempotency_key": str(uuid4()),
        },
    )
    assert response.status_code == 200, response.text
    employee.get(f"/work-items/{work['id']}", 404)
    employee.confirm(draft, 404)


def test_invitation_identity_revocation_expiry_and_replay(loop):
    boss, employee, org, depts, member, work = loop
    invite = boss.invite(depts[1], "new@example.com")
    employee.post("/members/invitations/accept", {"token": invite["delivery"]["token"]}, 403)
    new = API("new@example.com")
    boss.post(f"/members/invitations/{invite['id']}/revoke")
    new.post("/members/invitations/accept", {"token": invite["delivery"]["token"]}, 400)
    invite = boss.invite(depts[1], "new@example.com")
    with session_factory()() as db:
        db.get(Invitation, invite["id"]).expires_at = now() - timedelta(seconds=1)
        db.commit()
    new.post("/members/invitations/accept", {"token": invite["delivery"]["token"]}, 400)
    invite = boss.invite(depts[1], "new@example.com")
    accepted = new.join(invite, org["id"])
    assert new.join(invite, org["id"])["id"] == accepted["id"]
    escalation = boss.invite(depts[0], "new@example.com", ["manager"])
    new.post("/members/invitations/accept", {"token": escalation["delivery"]["token"]}, 409)


def test_expired_draft_and_source_authority(loop):
    boss, employee, org, depts, member, work = loop
    draft = employee.draft(work)
    with session_factory()() as db:
        db.get(UpdateDraft, draft["id"]).expires_at = now() - timedelta(seconds=1)
        db.commit()
    employee.confirm(draft, 409)
    with session_factory()() as db:
        db.get(WorkItem, work["id"]).source_authority = "external"
        db.commit()
    employee.post("/work-updates/drafts", {"work_item_id": work["id"], "raw_text": "完成"}, 409)


def test_one_identity_multiple_organizations_no_implicit_access(loop):
    boss, employee, org, depts, member, work = loop
    second = boss.org("老板的第二家公司")
    assert len(boss.get("/auth/me")["memberships"]) == 2
    assert boss.get("/dashboard")["total_work"] == 0
    employee.client.headers["X-Organization-Id"] = second["id"]
    employee.get("/dashboard", 403)


def test_auth_csrf_token_expiry_and_no_role_headers(loop):
    boss, employee, org, depts, member, work = loop
    with TestClient(app) as client:
        assert (
            client.get(
                "/api/v1/dashboard", headers={"X-Organization-Id": org["id"], "X-Role": "owner"}
            ).status_code
            == 401
        )
        response = client.post(
            "/api/v1/auth/request-link", json={"name": "A", "email": "a@example.com"}
        )
        token = response.json()["token"]
        assert client.post("/api/v1/auth/verify", json={"token": token}).status_code == 200
        assert client.post("/api/v1/auth/verify", json={"token": token}).status_code == 400
        assert client.post("/api/v1/organizations", json={"name": "CSRF"}).status_code == 403
        assert (
            client.post(
                "/api/v1/auth/request-link",
                json={"name": "A", "email": "a@example.com"},
                headers={"Origin": "https://evil.example"},
            ).status_code
            == 403
        )
    with session_factory()() as db:
        for session in db.scalars(select(AuthSession)).all():
            session.expires_at = now() - timedelta(seconds=1)
        db.commit()
    employee.get("/auth/me", 401)


def test_mock_production_fails_closed():
    with pytest.raises(RuntimeError, match="Production is blocked"):
        Settings(environment="production").check_deployment()


def test_pagination_validation_and_unknown_route(loop):
    boss, employee, org, depts, member, work = loop
    page = boss.get("/departments?limit=1&offset=1")
    assert len(page["items"]) == 1 and page["total"] == 3
    boss.get("/departments?limit=10000", 422)
    boss.post("/organizations", {"name": "x", "timezone": "invalid/timezone"}, 422)
    response = boss.get("/not-existing", 404)
    assert response["error"]["code"] == "http_error"


def test_concurrent_confirmation_has_one_persistent_event(loop):
    if not settings().database_url.startswith("postgresql"):
        pytest.skip("Row-lock concurrency is verified against PostgreSQL")
    boss, employee, org, depts, member, work = loop
    draft = employee.draft(work)
    cookies = dict(employee.client.cookies)

    def submit(_):
        with TestClient(
            app, cookies=cookies, headers={"X-CoRoof-Request": "1", "X-Organization-Id": org["id"]}
        ) as client:
            return client.post(
                f"/api/v1/work-updates/drafts/{draft['id']}/confirm",
                json={"expected_revision": draft["revision"]},
            )

    with ThreadPoolExecutor(max_workers=4) as pool:
        responses = list(pool.map(submit, range(4)))
    assert all(r.status_code == 200 for r in responses), [r.text for r in responses]
    assert len({r.json()["id"] for r in responses}) == 1
    assert boss.get(f"/work-items/{work['id']}/events")["total"] == 2
