import hashlib
import secrets
from datetime import timedelta
from typing import Annotated

from fastapi import APIRouter, Cookie, Depends, Header, Request, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.errors import fail
from app.core.schemas import LoginInput, MemberOut, MeOut, MockDelivery, OrgOut, TokenInput
from app.infrastructure.db import get_db
from app.infrastructure.models import (
    AuthSession,
    Identity,
    LoginChallenge,
    Membership,
    Organization,
    now,
    utc,
)

Db = Annotated[Session, Depends(get_db)]
router = APIRouter(prefix="/auth", tags=["identity"])


def token_hash(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def current_user(
    db: Db,
    request: Request,
    coroof_session: Annotated[str | None, Cookie()] = None,
) -> Identity:
    if request.method not in {"GET", "HEAD", "OPTIONS"}:
        if request.headers.get("X-CoRoof-Request") != "1":
            fail("csrf_required", "缺少请求校验头", 403)
    session = db.get(AuthSession, token_hash(coroof_session or ""))
    if session is None or utc(session.expires_at) <= now():
        fail("unauthenticated", "请先验证身份", 401)
    assert session is not None
    user = db.get(Identity, session.user_id)
    assert user is not None
    return user


User = Annotated[Identity, Depends(current_user)]


def current_member(
    db: Db,
    user: User,
    x_organization_id: Annotated[str, Header()],
) -> Membership:
    member = db.scalar(
        select(Membership).where(
            Membership.organization_id == x_organization_id,
            Membership.user_id == user.id,
            Membership.status == "active",
        )
    )
    if member is None:
        fail("organization_forbidden", "无权访问此企业", 403)
    assert member is not None
    return member


Actor = Annotated[Membership, Depends(current_member)]


def member_out(db: Session, member: Membership) -> MemberOut:
    user = db.get(Identity, member.user_id)
    assert user is not None
    return MemberOut(
        id=member.id,
        organization_id=member.organization_id,
        user_id=member.user_id,
        name=user.name,
        roles=member.roles,
        department_id=member.department_id,
        status=member.status,
    )


@router.post("/request-link", response_model=MockDelivery)
def request_link(payload: LoginInput, db: Db) -> MockDelivery:
    token = secrets.token_urlsafe(32)
    expires_at = now() + timedelta(minutes=10)
    db.add(
        LoginChallenge(
            email=payload.email.lower(),
            name=payload.name,
            token_hash=token_hash(token),
            expires_at=expires_at,
        )
    )
    db.commit()
    return MockDelivery(token=token, expires_at=expires_at)


@router.post("/verify", response_model=MeOut)
def verify(payload: TokenInput, db: Db, response: Response) -> MeOut:
    challenge = db.scalar(
        select(LoginChallenge)
        .where(
            LoginChallenge.token_hash == token_hash(payload.token),
        )
        .with_for_update()
    )
    if challenge is None or challenge.used or utc(challenge.expires_at) <= now():
        fail("invalid_verification", "验证链接无效或已过期", 400)
    assert challenge is not None
    challenge.used = True
    user = db.scalar(select(Identity).where(Identity.verified_identity == challenge.email))
    if user is None:
        user = Identity(verified_identity=challenge.email, name=challenge.name)
        db.add(user)
        db.flush()
    token = secrets.token_urlsafe(32)
    db.add(
        AuthSession(
            token_hash=token_hash(token),
            user_id=user.id,
            expires_at=now() + timedelta(hours=24),
        )
    )
    db.commit()
    response.set_cookie(
        "coroof_session",
        token,
        httponly=True,
        secure=settings().cookie_secure,
        samesite="strict",
        max_age=86400,
        path="/",
    )
    return me(db, user)


@router.get("/me", response_model=MeOut)
def me(db: Db, user: User) -> MeOut:
    memberships = db.scalars(
        select(Membership).where(
            Membership.user_id == user.id,
            Membership.status == "active",
        )
    ).all()
    return MeOut(
        id=user.id,
        name=user.name,
        email=user.verified_identity,
        memberships=[
            {
                "membership": member_out(db, m),
                "organization": OrgOut.model_validate(db.get(Organization, m.organization_id)),
            }
            for m in memberships
        ],
    )


@router.post("/logout", status_code=204)
def logout(db: Db, user: User, request: Request, response: Response) -> None:
    session = db.get(AuthSession, token_hash(request.cookies.get("coroof_session", "")))
    if session:
        db.delete(session)
        db.commit()
    response.delete_cookie("coroof_session", path="/")
