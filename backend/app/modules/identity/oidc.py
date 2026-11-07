"""Authlib owns OIDC. Domain identity never trusts provider roles or email-only linking."""

import json
import secrets
from datetime import timedelta
from typing import Any
from urllib.parse import parse_qs, quote, urlparse

from authlib.integrations.starlette_client import OAuth
from fastapi import APIRouter, Request
from fastapi.responses import RedirectResponse
from pydantic import EmailStr, TypeAdapter
from sqlalchemy import select
from starlette.concurrency import run_in_threadpool
from starlette.middleware.sessions import SessionMiddleware
from starlette.types import ASGIApp, Receive, Scope, Send

from app.core.auth import Db
from app.core.config import Settings, settings
from app.core.errors import fail
from app.infrastructure.models import Identity, now, utc
from app.modules.identity.limits import enforce
from app.modules.identity.models import LoginAttempt
from app.modules.identity.schemas import OIDCStart, OIDCStartOut
from app.modules.identity.sessions import digest, issue

router = APIRouter(prefix="/auth/oidc", tags=["identity"])
_dev_signing_key = secrets.token_urlsafe(48)


class OIDCSessionMiddleware:
    """Use framework cookies; runtime settings also permit isolated test app instances."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        cfg = settings()
        middleware = SessionMiddleware(
            self.app,
            secret_key=cfg.oidc_session_secret.get_secret_value() or _dev_signing_key,
            session_cookie="coroof_oidc",
            max_age=600,
            same_site="lax",
            https_only=cfg.cookie_secure,
        )
        await middleware(scope, receive, send)


def configured(cfg: Settings) -> None:
    if cfg.auth_mode != "oidc":
        fail("oidc_disabled", "当前未启用正式登录", 404)
    if (
        not cfg.oidc_issuer
        or not cfg.oidc_client_id
        or not cfg.oidc_client_secret.get_secret_value()
        or len(cfg.oidc_session_secret.get_secret_value()) < 32
    ):
        fail("identity_not_configured", "正式登录尚未配置完成", 503)


def config_hash(cfg: Settings) -> str:
    return digest(
        json.dumps(
            [
                cfg.oidc_issuer,
                cfg.oidc_client_id,
                cfg.oidc_client_secret.get_secret_value(),
                cfg.oidc_allowed_hosts,
                cfg.web_origin,
                cfg.oidc_token_auth_method,
            ]
        )
    )


def endpoint(value: str, cfg: Settings) -> None:
    parsed = urlparse(value)
    trusted = {urlparse(cfg.oidc_issuer).netloc, *cfg.oidc_allowed_hosts}
    if (
        not parsed.hostname
        or parsed.netloc not in trusted
        or parsed.username
        or parsed.password
        or parsed.fragment
        or (
            parsed.scheme != "https"
            and not (
                cfg.environment == "test"
                and parsed.scheme == "http"
                and parsed.hostname in {"localhost", "127.0.0.1", "::1"}
            )
        )
    ):
        raise ValueError("untrusted_identity_endpoint")


async def client(cfg: Settings) -> Any:
    endpoint(cfg.oidc_issuer, cfg)
    if urlparse(cfg.oidc_issuer).query:
        raise ValueError("invalid_identity_issuer")
    remote = OAuth().register(
        "identity",
        client_id=cfg.oidc_client_id,
        client_secret=cfg.oidc_client_secret.get_secret_value(),
        server_metadata_url=cfg.oidc_issuer.rstrip("/") + "/.well-known/openid-configuration",
        client_kwargs={
            "scope": "openid profile email",
            "code_challenge_method": "S256",
            "token_endpoint_auth_method": cfg.oidc_token_auth_method,
            "timeout": 10,
            "trust_env": False,
            "follow_redirects": False,
        },
    )
    metadata = await remote.load_server_metadata()
    if metadata.get("issuer") != cfg.oidc_issuer:
        raise ValueError("issuer_mismatch")
    for key in ("authorization_endpoint", "token_endpoint", "jwks_uri"):
        endpoint(metadata[key], cfg)
    algorithms = [
        value
        for value in metadata.get("id_token_signing_alg_values_supported", ["RS256"])
        if value
        in {"RS256", "ES256", "PS256", "RS384", "RS512", "ES384", "ES512", "PS384", "PS512"}
    ]
    if not algorithms:
        raise ValueError("unsigned_identity_not_allowed")
    remote.server_metadata["id_token_signing_alg_values_supported"] = algorithms
    return remote


@router.post("/start", response_model=OIDCStartOut)
async def start(payload: OIDCStart, request: Request, db: Db) -> OIDCStartOut:
    cfg = settings()
    configured(cfg)
    if request.headers.get("X-CoRoof-Request") != "1":
        fail("csrf_required", "缺少请求校验头", 403)
    await run_in_threadpool(enforce, request, "login")
    request.session.clear()
    try:
        remote = await client(cfg)
        response = await remote.authorize_redirect(
            request, cfg.web_origin + "/api/v1/auth/oidc/callback"
        )
        location = response.headers["location"]
        state = parse_qs(urlparse(location).query)["state"][0]
    except Exception:
        request.session.clear()
        fail("identity_unavailable", "登录服务暂不可用，请稍后再试", 503)
    attempt = LoginAttempt(
        state_hash=digest(state),
        config_hash=config_hash(cfg),
        expires_at=now() + timedelta(minutes=10),
    )
    db.add(attempt)
    db.commit()
    request.session["attempt_id"] = attempt.id
    request.session["previous_session_hash"] = digest(request.cookies.get("coroof_session", ""))
    if payload.invite_token:
        request.session["invite"] = payload.invite_token
    return OIDCStartOut(authorization_url=location)


@router.get("/callback")
async def callback(request: Request, db: Db) -> RedirectResponse:
    cfg = settings()
    configured(cfg)
    await run_in_threadpool(enforce, request, "callback")
    attempt_id = request.session.get("attempt_id")
    state = request.query_params.get("state", "")
    attempt = (
        db.scalar(select(LoginAttempt).where(LoginAttempt.id == attempt_id).with_for_update())
        if attempt_id
        else None
    )
    # The ID comes from the framework's signed browser cookie; state and the
    # current provider configuration must match the one-use database receipt.
    if (
        not attempt
        or attempt.used_at is not None
        or utc(attempt.expires_at) <= now()
        or attempt.state_hash != digest(state)
        or attempt.config_hash != config_hash(cfg)
    ):
        request.session.clear()
        db.rollback()
        return RedirectResponse(cfg.web_origin + "/?auth_error=1", status_code=303)
    attempt.used_at = now()
    db.commit()  # Release all database locks before HTTP.
    invitation = request.session.get("invite")
    previous = request.session.get("previous_session_hash")
    try:
        remote = await client(cfg)
        token = await remote.authorize_access_token(
            request,
            claims_options={
                "iss": {"essential": True, "value": cfg.oidc_issuer},
                "email": {"essential": True},
                "email_verified": {"essential": True},
            },
            leeway=30,
        )
        info = token["userinfo"]
        if (
            info.get("email_verified") is not True
            or not isinstance(info.get("sub"), str)
            or not (0 < len(info["sub"]) <= 255)
        ):
            raise ValueError("unverified_identity")
        email = str(TypeAdapter(EmailStr).validate_python(info["email"])).lower()
        user = db.scalar(
            select(Identity)
            .where(Identity.oidc_issuer == cfg.oidc_issuer, Identity.oidc_subject == info["sub"])
            .with_for_update()
        )
        if user:
            if user.identity_provider != "oidc" or user.verified_identity != email:
                raise ValueError("identity_changed_requires_review")
        else:
            if db.scalar(select(Identity.id).where(Identity.verified_identity == email)):
                raise ValueError("identity_link_requires_review")
            name = info.get("name")
            user = Identity(
                verified_identity=email,
                name=(
                    name.strip()[:100] if isinstance(name, str) and name.strip() else email[:100]
                ),
                identity_provider="oidc",
                oidc_issuer=cfg.oidc_issuer,
                oidc_subject=info["sub"],
            )
            db.add(user)
            db.flush()
        destination = (
            cfg.web_origin
            + "/"
            + ("#invite=" + quote(invitation, safe="") if isinstance(invitation, str) else "")
        )
        response = RedirectResponse(destination, status_code=303)
        issue(db, user, response, previous_hash=previous if isinstance(previous, str) else None)
    except Exception:
        db.rollback()
        response = RedirectResponse(cfg.web_origin + "/?auth_error=1", status_code=303)
    finally:
        request.session.clear()
    return response
