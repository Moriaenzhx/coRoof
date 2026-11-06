"""Offline protocol acceptance: real Authlib PKCE and signed ID-token validation."""

import base64
import hashlib
import time
from datetime import timedelta
from urllib.parse import parse_qs, urlparse

import httpx2 as httpx
import pytest
from authlib.integrations.httpx_client import AsyncOAuth2Client
from authlib.integrations.starlette_client.apps import StarletteOAuth2App
from fastapi.testclient import TestClient
from joserfc import jwt
from joserfc.jwk import RSAKey
from sqlalchemy import func, select
from test_invitations import smtp as smtp

from app.core.config import settings
from app.infrastructure.db import session_factory
from app.infrastructure.models import AuthSession, Identity, now
from app.main import app
from app.modules.identity.limits import limiter
from app.modules.identity.models import LoginAttempt

ISSUER = "https://identity.example.test"
ORIGIN = "https://coroof.example.test"


@pytest.fixture
def provider(monkeypatch):
    for key, value in {
        "AUTH_MODE": "oidc",
        "OIDC_ISSUER": ISSUER,
        "OIDC_CLIENT_ID": "coroof-fixture",
        "OIDC_CLIENT_SECRET": "fixture-client-secret",
        "OIDC_SESSION_SECRET": "fixture-cookie-secret-with-enough-length",
        "WEB_ORIGIN": ORIGIN,
        "COOKIE_SECURE": "true",
        "RATE_LIMIT_URL": "memory://",
        "AUTH_RATE_LIMIT": "1000/minute",
    }.items():
        monkeypatch.setenv("COROOF_" + key, value)
    settings.cache_clear()
    limiter.cache_clear()
    key = RSAKey.generate_key(2048, private=True)
    calls = []
    control = {
        "claims": {},
        "metadata": {},
        "nonce": "",
        "challenge": "",
        "email": "verified@example.com",
        "subject": "subject-fixture",
    }

    def handle(request):
        calls.append(request)
        if request.url.path.endswith("/.well-known/openid-configuration"):
            return httpx.Response(
                200,
                json={
                    "issuer": ISSUER,
                    "authorization_endpoint": ISSUER + "/authorize",
                    "token_endpoint": ISSUER + "/token",
                    "jwks_uri": ISSUER + "/jwks",
                    "id_token_signing_alg_values_supported": ["RS256"],
                    "response_types_supported": ["code"],
                    "subject_types_supported": ["public"],
                    **control["metadata"],
                },
            )
        if request.url.path == "/jwks":
            return httpx.Response(200, json={"keys": [key.as_dict(private=False)]})
        if request.url.path == "/token":
            form = parse_qs(request.content.decode())
            verifier = form["code_verifier"][0]
            challenge = (
                base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest())
                .rstrip(b"=")
                .decode()
            )
            assert challenge == control["challenge"]
            assert form["redirect_uri"] == [ORIGIN + "/api/v1/auth/oidc/callback"]
            claims = {
                "iss": ISSUER,
                "sub": control["subject"],
                "aud": "coroof-fixture",
                "iat": int(time.time()),
                "exp": int(time.time()) + 300,
                "nonce": control["nonce"],
                "email": control["email"],
                "email_verified": True,
                "name": "已验证用户",
                "roles": ["owner"],
                **control["claims"],
            }
            signer = RSAKey.generate_key(2048, private=True) if control.get("wrong_key") else key
            signed = jwt.encode({"alg": "RS256"}, claims, signer)
            return httpx.Response(
                200,
                json={
                    "access_token": "fixture-access-token",
                    "token_type": "Bearer",
                    "id_token": signed,
                },
            )
        raise AssertionError("Unexpected identity endpoint")

    class Client(AsyncOAuth2Client):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, transport=httpx.MockTransport(handle), **kwargs)

    monkeypatch.setattr(StarletteOAuth2App, "client_cls", Client)
    client = TestClient(
        app, base_url=ORIGIN, follow_redirects=False, headers={"X-CoRoof-Request": "1"}
    )
    yield client, control, calls
    client.close()
    limiter.cache_clear()


def start(provider, **body):
    client, control, _ = provider
    response = client.post("/api/v1/auth/oidc/start", json=body)
    assert response.status_code == 200, response.text
    params = parse_qs(urlparse(response.json()["authorization_url"]).query)
    assert params["code_challenge_method"] == ["S256"]
    control["nonce"], control["challenge"] = params["nonce"][0], params["code_challenge"][0]
    return params["state"][0]


def callback(provider, state):
    return provider[0].get(
        "/api/v1/auth/oidc/callback", params={"code": "fixture-code", "state": state}
    )


def test_oidc_validates_protocol_and_creates_identity_without_tenant_roles(provider):
    client, _, calls = provider
    state = start(provider)
    assert "HttpOnly" in str(client.cookies) or client.cookies.get("coroof_oidc")
    response = callback(provider, state)
    assert response.status_code == 303 and response.headers["location"] == ORIGIN + "/"
    cookie = response.headers.get_list("set-cookie")[0]
    assert "HttpOnly" in cookie and "Secure" in cookie and "SameSite=strict" in cookie
    user = client.get("/api/v1/auth/me").json()
    assert user["mode"] == "oidc" and user["memberships"] == []
    assert "token" not in str(user) and "oidc_subject" not in user
    assert (
        client.get(
            "/api/v1/dashboard", headers={"X-Organization-Id": "any", "X-Role": "owner"}
        ).status_code
        == 403
    )
    assert len(calls) == 4
    with session_factory()() as db:
        identity = db.get(Identity, user["id"])
        assert identity.oidc_subject == "subject-fixture" and identity.oidc_issuer == ISSUER
        assert db.scalar(select(func.count()).select_from(AuthSession)) == 1


@pytest.mark.parametrize(
    "claims",
    [
        {"iss": "https://wrong.example"},
        {"aud": "other-client"},
        {"nonce": "wrong"},
        {"exp": 1},
        {"email_verified": False},
        {"email_verified": "true"},
        {"email": "not-an-email"},
    ],
)
def test_oidc_rejects_invalid_or_unverified_claims(provider, claims):
    provider[1]["claims"] = claims
    response = callback(provider, start(provider))
    assert response.headers["location"] == ORIGIN + "/?auth_error=1"
    assert provider[0].get("/api/v1/auth/me").status_code == 401
    with session_factory()() as db:
        assert db.scalar(select(func.count()).select_from(Identity)) == 0


def test_oidc_state_is_browser_bound_one_use_and_configuration_bound(provider, monkeypatch):
    client, _, calls = provider
    state = start(provider)
    copied = client.cookies.get("coroof_oidc")
    stranger = TestClient(app, base_url=ORIGIN, follow_redirects=False)
    assert (
        stranger.get("/api/v1/auth/oidc/callback", params={"code": "fixture-code", "state": state})
        .headers["location"]
        .endswith("auth_error=1")
    )
    assert len(calls) == 1
    assert callback(provider, state).headers["location"] == ORIGIN + "/"
    client.cookies.set("coroof_oidc", copied, domain="coroof.example.test", path="/")
    count = len(calls)
    assert callback(provider, state).headers["location"].endswith("auth_error=1")
    assert len(calls) == count
    state = start(provider)
    monkeypatch.setenv("COROOF_OIDC_CLIENT_ID", "changed-client")
    settings.cache_clear()
    assert callback(provider, state).headers["location"].endswith("auth_error=1")
    assert len(calls) == count + 1
    stranger.close()


def test_oidc_expired_attempt_and_untrusted_discovery_never_reach_token_endpoint(provider):
    state = start(provider)
    with session_factory()() as db:
        db.scalar(select(LoginAttempt)).expires_at = now() - timedelta(seconds=1)
        db.commit()
    assert callback(provider, state).headers["location"].endswith("auth_error=1")
    provider[1]["metadata"] = {"token_endpoint": "https://evil.example/token"}
    assert provider[0].post("/api/v1/auth/oidc/start", json={}).status_code == 503
    assert all(request.url.path.endswith("openid-configuration") for request in provider[2])


def test_oidc_will_not_promote_existing_mock_account(provider):
    with session_factory()() as db:
        db.add(Identity(verified_identity="verified@example.com", name="开发用户"))
        db.commit()
    assert callback(provider, start(provider)).headers["location"].endswith("auth_error=1")
    with session_factory()() as db:
        assert db.scalar(select(Identity)).identity_provider == "mock"
        assert db.scalar(select(func.count()).select_from(AuthSession)) == 0


def test_oidc_rotates_local_session_and_logout_all_revokes_other_browsers(provider):
    client, _, _ = provider
    callback(provider, start(provider))
    old = client.cookies.get("coroof_session")
    callback(provider, start(provider))
    new = client.cookies.get("coroof_session")
    assert old and new and old != new
    with session_factory()() as db:
        assert db.scalar(select(func.count()).select_from(AuthSession)) == 1
    other = TestClient(
        app, base_url=ORIGIN, headers={"X-CoRoof-Request": "1"}, follow_redirects=False
    )
    other.cookies.update(client.cookies)
    assert client.post("/api/v1/auth/logout-all").status_code == 204
    assert other.get("/api/v1/auth/me").status_code == 401
    other.close()


def test_real_mode_disables_development_login_and_session(loop, provider):
    boss = loop[0]
    assert boss.request("GET", "/auth/me").status_code == 401
    assert (
        provider[0]
        .post("/api/v1/auth/request-link", json={"email": "real@example.com", "name": "A"})
        .status_code
        == 404
    )
    assert provider[0].post("/api/v1/auth/verify", json={"token": "x" * 32}).status_code == 404


def test_oidc_limits_requests_without_trusting_forwarded_ip(provider, monkeypatch):
    monkeypatch.setenv("COROOF_AUTH_RATE_LIMIT", "1/minute")
    settings.cache_clear()
    start(provider)
    result = provider[0].post(
        "/api/v1/auth/oidc/start", json={}, headers={"X-Forwarded-For": "another-ip"}
    )
    assert result.status_code == 429


def test_oidc_invitation_flow_uses_verified_email_and_current_membership(provider, smtp):
    client, control, _ = provider
    assert callback(provider, start(provider)).headers["location"] == ORIGIN + "/"
    org = client.post("/api/v1/organizations", json={"name": "离线身份验收企业"}).json()
    client.headers["X-Organization-Id"] = org["id"]
    dept = client.post("/api/v1/departments", json={"name": "交付"}).json()
    from uuid import uuid4

    from test_invitations import deliver

    invitation = client.post(
        "/api/v1/members/invitations",
        json={
            "email": "colleague@example.com",
            "department_id": dept["id"],
            "idempotency_key": str(uuid4()),
        },
    )
    assert invitation.status_code == 201, invitation.text
    deliver(invitation.json())
    token = smtp[0][0].get_content().split("#invite=")[1].split()[0]
    # Being an owner does not make an invitation for another email acceptable.
    assert (
        client.post("/api/v1/members/invitations/accept", json={"token": token}).status_code == 403
    )
    control.update(email="colleague@example.com", subject="colleague-subject")
    response = callback(provider, start(provider, invite_token=token))
    assert response.headers["location"] == ORIGIN + "/#invite=" + token
    assert client.get("/api/v1/auth/me").json()["memberships"] == []
    joined = client.post("/api/v1/members/invitations/accept", json={"token": token})
    assert joined.status_code == 200 and joined.json()["roles"] == ["member"]
    assert client.get("/api/v1/auth/me").json()["memberships"][0]["organization"]["id"] == org["id"]
    assert client.post("/api/v1/departments", json={"name": "禁止"}).status_code == 403


def test_existing_oidc_session_is_invalid_after_issuer_change(provider, monkeypatch):
    client, _, _ = provider
    callback(provider, start(provider))
    assert client.get("/api/v1/auth/me").status_code == 200
    monkeypatch.setenv("COROOF_OIDC_ISSUER", "https://replacement.example.com")
    settings.cache_clear()
    assert client.get("/api/v1/auth/me").status_code == 401


def test_oidc_rejects_untrusted_signature(provider):
    provider[1]["wrong_key"] = True
    assert callback(provider, start(provider)).headers["location"].endswith("auth_error=1")
    assert provider[0].get("/api/v1/auth/me").status_code == 401


def test_oidc_rejects_missing_csrf_and_rate_limit_outage_before_provider(provider, monkeypatch):
    client, _, calls = provider
    client.headers.pop("X-CoRoof-Request")
    assert client.post("/api/v1/auth/oidc/start", json={}).status_code == 403
    client.headers["X-CoRoof-Request"] = "1"

    def unavailable(_):
        raise ConnectionError("private-storage-address")

    monkeypatch.setattr("app.modules.identity.limits.limiter", unavailable)
    result = client.post("/api/v1/auth/oidc/start", json={})
    assert result.status_code == 503 and result.json()["error"]["code"] == "rate_limit_unavailable"
    assert not calls and "private-storage" not in result.text
