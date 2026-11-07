import hashlib
import secrets
from datetime import timedelta

from fastapi import Response
from sqlalchemy import delete
from sqlalchemy.orm import Session

from app.core.config import settings
from app.infrastructure.models import AuthSession, Identity, now, utc


def digest(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def valid_session(db: Session, identifier: str, user_id: str | None = None) -> AuthSession | None:
    session = db.get(AuthSession, identifier, populate_existing=True)
    if (
        session is None
        or utc(session.expires_at) <= now()
        or session.auth_mode != settings().auth_mode
        or (user_id is not None and session.user_id != user_id)
    ):
        return None
    user = db.get(Identity, session.user_id)
    if user is None or user.identity_provider != settings().auth_mode:
        return None
    if settings().auth_mode == "oidc" and user.oidc_issuer != settings().oidc_issuer:
        return None
    return session


def issue(
    db: Session, user: Identity, response: Response, previous_hash: str | None = None
) -> None:
    if previous_hash:
        db.execute(delete(AuthSession).where(AuthSession.token_hash == previous_hash))
    token = secrets.token_urlsafe(32)
    seconds = settings().auth_session_hours * 3600
    db.add(
        AuthSession(
            token_hash=digest(token),
            user_id=user.id,
            auth_mode=user.identity_provider,
            expires_at=now() + timedelta(seconds=seconds),
        )
    )
    db.commit()
    response.set_cookie(
        "coroof_session",
        token,
        httponly=True,
        secure=settings().cookie_secure,
        samesite="strict",
        max_age=seconds,
        path="/",
    )
