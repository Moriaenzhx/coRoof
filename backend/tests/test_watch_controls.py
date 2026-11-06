"""Stage 8.1: explicit bounded grants, current tenant authority and command concurrency."""

from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from uuid import uuid4

import pytest
from conftest import API
from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from app.core.config import settings
from app.infrastructure.db import session_factory
from app.infrastructure.models import AuthSession, Membership, WorkEvent, now
from app.modules.watch import service
from app.modules.watch.models import WatchGrant, WatchPolicy


def body(**changes):
    return {
        "name": "交付关注",
        "goal": "根据已确认记录核实交付阻碍，准备协调方案，不推测实际交付。",
        "scope_kind": "organization",
        "interval_minutes": 60,
        "daily_analysis_limit": 4,
        "expires_at": (now() + timedelta(days=7)).isoformat(),
        "confirm": True,
        "idempotency_key": str(uuid4()),
        **changes,
    }


def create(boss, **changes):
    return boss.post("/watch/policies", body(**changes), 201)


def actor_grant(db, identifier):
    policy = db.get(WatchPolicy, identifier)
    return db.get(Membership, policy.actor_id), service.current_grant(db, policy)


def action(policy, kind, **changes):
    return {
        "action": kind,
        "expected_version": policy["version"],
        "confirm": True,
        "idempotency_key": str(uuid4()),
        **changes,
    }


def test_policy_requires_owner_confirmation_and_does_not_invent_facts(loop):
    boss, member, _, _, _, _ = loop
    with session_factory()() as db:
        count = db.scalar(select(func.count()).select_from(WorkEvent))
    payload = body()
    assert member.request("POST", "/watch/policies", payload).status_code == 403
    assert boss.request("POST", "/watch/policies", {**payload, "confirm": False}).status_code == 422
    policy = boss.post("/watch/policies", payload, 201)
    assert policy["effective_state"] == "active" and "session" not in str(policy)
    assert boss.post("/watch/policies", payload, 201)["id"] == policy["id"]
    assert (
        boss.request("POST", "/watch/policies", {**payload, "goal": "changed"}).status_code == 409
    )
    with session_factory()() as db:
        assert db.scalar(select(func.count()).select_from(WorkEvent)) == count
        assert db.scalar(select(func.count()).select_from(WatchGrant)) == 1
    assert member.request("GET", "/watch/policies").status_code == 403


def test_grants_survive_logout_but_not_pause_reconfigure_or_expiry(loop, monkeypatch):
    boss, _, _, depts, _, work = loop
    policy = create(boss, scope_kind="department", department_id=depts[0]["id"])
    with session_factory()() as db:
        actor, grant = actor_grant(db, policy["id"])
        original = grant.id
        service.authorize(db, actor, original, work["id"])
    pause = action(policy, "pause")
    path = f"/watch/policies/{policy['id']}/actions"
    paused = boss.post(path, pause)
    assert paused["effective_state"] == "paused"
    assert boss.post(path, pause) == paused
    with session_factory()() as db:
        actor, _ = actor_grant(db, policy["id"])
        with pytest.raises(HTTPException):
            service.authorize(db, actor, original, work["id"])
    resumed = boss.post(path, action(paused, "resume"))
    with session_factory()() as db:
        actor, grant = actor_grant(db, policy["id"])
        renewed = grant.id
        assert renewed != original
    edited = boss.post(
        f"/watch/policies/{policy['id']}/edit",
        body(
            expected_version=resumed["version"],
            scope_kind="department",
            department_id=depts[1]["id"],
        ),
    )
    with session_factory()() as db:
        actor, grant = actor_grant(db, policy["id"])
        with pytest.raises(HTTPException):
            service.authorize(db, actor, renewed)
        with pytest.raises(HTTPException):
            service.authorize(db, actor, grant.id, work["id"])
        grant_id = grant.id
    assert boss.request("POST", "/auth/logout-all").status_code == 204
    with session_factory()() as db:
        actor, grant = actor_grant(db, policy["id"])
        assert (
            db.scalar(
                select(func.count())
                .select_from(AuthSession)
                .where(AuthSession.user_id == actor.user_id)
            )
            == 0
        )
        assert service.authorize(db, actor, grant_id).id == policy["id"]
        grant.expires_at = now() - timedelta(seconds=1)
        db.commit()
        with pytest.raises(HTTPException):
            service.authorize(db, actor, grant_id)
    assert edited["version"] > resumed["version"]


def test_policy_scope_and_grant_foreign_keys_are_tenant_bound(loop):
    boss, _, _, depts, _, work = loop
    other = API("other-owner@example.com")
    other_org = other.org("另一企业")
    foreign_dept = other.department()
    assert (
        boss.request(
            "POST",
            "/watch/policies",
            body(scope_kind="department", department_id=foreign_dept["id"]),
        ).status_code
        == 404
    )
    assert (
        boss.request("POST", "/watch/policies", body(department_id=depts[0]["id"])).status_code
        == 422
    )
    policy = create(boss, scope_kind="initiative", initiative_id=work["initiative_id"])
    with session_factory()() as db:
        actor, grant = actor_grant(db, policy["id"])
        assert service.authorize(db, actor, grant.id, work["id"]).id == policy["id"]
        other_actor = db.scalar(
            select(Membership).where(Membership.organization_id == other_org["id"])
        )
        db.add(
            WatchGrant(
                organization_id=other_org["id"],
                policy_id=policy["id"],
                policy_version=2,
                actor_id=other_actor.id,
                identity_binding="x" * 64,
                expires_at=now() + timedelta(days=1),
            )
        )
        with pytest.raises(IntegrityError):
            db.commit()
        db.rollback()
    assert (
        other.request(
            "POST", f"/watch/policies/{policy['id']}/actions", action(policy, "revoke")
        ).status_code
        == 404
    )


def test_owner_authority_and_identity_changes_invalidate_background_grants(loop, monkeypatch):
    boss = loop[0]
    policy = create(boss)
    with session_factory()() as db:
        actor, grant = actor_grant(db, policy["id"])
        actor.roles = ["member"]
        db.commit()
        with pytest.raises(HTTPException):
            service.authorize(db, actor, grant.id)
        actor.roles = ["owner"]
        actor.status = "inactive"
        db.commit()
        with pytest.raises(HTTPException):
            service.authorize(db, actor, grant.id)
        actor.status = "active"
        db.commit()
        monkeypatch.setenv("COROOF_AUTH_MODE", "oidc")
        settings.cache_clear()
        with pytest.raises(HTTPException):
            service.authorize(db, actor, grant.id)


def test_revoke_is_permanent_and_expiry_must_be_explicit(loop):
    boss = loop[0]
    assert (
        boss.request(
            "POST", "/watch/policies", body(expires_at=(now() + timedelta(days=91)).isoformat())
        ).status_code
        == 422
    )
    policy = create(boss)
    path = f"/watch/policies/{policy['id']}/actions"
    revoked = boss.post(path, action(policy, "revoke"))
    assert revoked["state"] == "revoked"
    assert boss.request("POST", path, action(revoked, "resume")).status_code == 409


def test_pg_concurrent_policy_commands_have_once_effect(loop):
    if session_factory().kw["bind"].dialect.name != "postgresql":
        pytest.skip("PostgreSQL row-lock acceptance")
    boss = loop[0]
    payload = body()
    with ThreadPoolExecutor(max_workers=2) as pool:
        rows = list(pool.map(lambda _: boss.post("/watch/policies", payload, 201), range(2)))
    assert rows[0]["id"] == rows[1]["id"]
    policy = rows[0]
    path = f"/watch/policies/{policy['id']}/actions"
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(
            pool.map(
                lambda kind: boss.request("POST", path, action(policy, kind)), ["pause", "revoke"]
            )
        )
    assert sorted(result.status_code for result in results) == [200, 409]
    with session_factory()() as db:
        assert db.scalar(select(func.count()).select_from(WatchPolicy)) == 1
        assert db.scalar(select(func.count()).select_from(WatchGrant)) == 1
