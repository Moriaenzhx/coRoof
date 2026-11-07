import secrets
from datetime import timedelta

from fastapi import APIRouter, Request
from sqlalchemy import select

from app.core.access import (
    audit,
    member_scope,
    owner,
    page_rows,
    require_manager,
    tenant_get,
)
from app.core.auth import Actor, Db, User, member_out, token_hash
from app.core.config import settings
from app.core.errors import fail
from app.core.schemas import (
    DeliveryRetry,
    DeliveryStatus,
    InviteDelivery,
    InviteInput,
    InviteOut,
    MemberOut,
    MockDelivery,
    Page,
    TokenInput,
)
from app.infrastructure.models import AuditEntry, Department, Invitation, Membership, now, utc
from app.modules.identity import mail
from app.modules.identity.limits import enforce
from app.modules.identity.models import InvitationDelivery
from app.modules.organizations.api import Limit, Offset

router = APIRouter(prefix="/members", tags=["members"])


@router.get("", response_model=Page[MemberOut])
def list_members(db: Db, actor: Actor, offset: Offset = 0, limit: Limit = 50) -> Page[MemberOut]:
    rows, total = page_rows(db, member_scope(actor).order_by(Membership.id), offset, limit)
    return Page(items=[member_out(db, r) for r in rows], total=total, offset=offset, limit=limit)


@router.post("/invitations", response_model=InviteDelivery, status_code=201)
def invite(payload: InviteInput, request: Request, db: Db, actor: Actor) -> InviteDelivery:
    # Serialize the actor's idempotency receipt and re-read current authority.
    actor = tenant_get(db, Membership, actor.id, actor, lock=True)
    if actor.status != "active":
        fail("organization_forbidden", "无权访问此企业", 403)
    require_manager(actor, payload.department_id)
    tenant_get(db, Department, payload.department_id, actor)
    if not owner(actor) and set(payload.roles) != {"member"}:
        fail("role_forbidden", "负责人只能邀请本部门员工", 403)
    cfg = settings()
    if cfg.auth_mode == "oidc" and cfg.delivery_mode != "smtp":
        fail("delivery_not_configured", "正式邀请投递尚未配置完成", 503)
    fingerprint = token_hash(payload.model_dump_json())
    if payload.idempotency_key:
        previous = db.scalar(
            select(Invitation).where(
                Invitation.organization_id == actor.organization_id,
                Invitation.invited_by == actor.id,
                Invitation.request_key == str(payload.idempotency_key),
            )
        )
        if previous:
            if previous.request_hash != fingerprint:
                fail("idempotency_conflict", "同一请求不能更改邀请内容", 409)
            result = invitation_out(db, previous)
            return InviteDelivery(**result.model_dump(), delivery=result.delivery_status)
    elif cfg.delivery_mode == "smtp":
        fail("idempotency_required", "正式邀请需要请求标识", 422)
    enforce(request, "invite", actor.organization_id + ":" + actor.id)
    token = secrets.token_urlsafe(32)
    invitation = Invitation(
        organization_id=actor.organization_id,
        email=payload.email.lower(),
        roles=sorted(set(payload.roles)),
        department_id=payload.department_id,
        invited_by=actor.id,
        auth_mode=cfg.auth_mode,
        request_key=str(payload.idempotency_key) if payload.idempotency_key else None,
        request_hash=fingerprint if payload.idempotency_key else None,
        token_hash=token_hash(token),
        expires_at=now() + timedelta(hours=24),
    )
    db.add(invitation)
    db.flush()
    delivery = mail.enqueue(db, invitation, token) if cfg.delivery_mode == "smtp" else None
    audit(db, actor, "invitation.created", invitation.id)
    db.commit()
    return InviteDelivery(
        **invitation_out(db, invitation).model_dump(),
        delivery=mail.status(delivery)
        if delivery
        else MockDelivery(token=token, expires_at=invitation.expires_at),
    )


def invitation_out(db: Db, invitation: Invitation) -> InviteOut:
    result = InviteOut.model_validate(invitation)
    delivery = mail.lookup(db, invitation)
    if delivery:
        result.delivery_status = mail.status(delivery)
    return result


@router.get("/invitations", response_model=Page[InviteOut])
def invitations(db: Db, actor: Actor, offset: Offset = 0, limit: Limit = 50) -> Page[InviteOut]:
    require_manager(actor, actor.department_id)
    stmt = select(Invitation).where(Invitation.organization_id == actor.organization_id)
    if not owner(actor):
        stmt = stmt.where(Invitation.department_id == actor.department_id)
    rows, total = page_rows(db, stmt.order_by(Invitation.id), offset, limit)
    return Page(
        items=[invitation_out(db, r) for r in rows], total=total, offset=offset, limit=limit
    )


@router.post("/invitations/{invitation_id}/revoke", response_model=InviteOut)
def revoke(invitation_id: str, db: Db, actor: Actor) -> InviteOut:
    invitation = tenant_get(db, Invitation, invitation_id, actor, lock=True)
    require_manager(actor, invitation.department_id)
    if invitation.accepted_at:
        fail("already_accepted", "邀请已使用，无法撤销成员资格", 409)
    invitation.revoked = True
    delivery = mail.lookup(db, invitation)
    if delivery:
        delivery = tenant_get(db, InvitationDelivery, delivery.id, actor, lock=True)
        if delivery.state != "accepted":
            delivery.state, delivery.payload = "cancelled", None
            delivery.version += 1
    audit(db, actor, "invitation.revoked", invitation.id)
    db.commit()
    return invitation_out(db, invitation)


@router.post("/invitations/{invitation_id}/retry", response_model=DeliveryStatus)
def retry_delivery(
    invitation_id: str, payload: DeliveryRetry, request: Request, db: Db, actor: Actor
) -> DeliveryStatus:
    invitation = tenant_get(db, Invitation, invitation_id, actor, lock=True)
    require_manager(actor, invitation.department_id)
    enforce(request, "invite", actor.organization_id + ":" + actor.id)
    return mail.retry(db, actor, invitation, payload)


@router.post("/invitations/accept", response_model=MemberOut)
def accept(payload: TokenInput, db: Db, user: User) -> MemberOut:
    invitation = db.scalar(
        select(Invitation)
        .where(
            Invitation.token_hash == token_hash(payload.token),
        )
        .with_for_update()
    )
    if (
        invitation is None
        or invitation.revoked
        or utc(invitation.expires_at) <= now()
        or invitation.auth_mode != settings().auth_mode
    ):
        fail("invalid_invitation", "邀请无效、已撤销或已过期")
    assert invitation is not None
    if invitation.email != user.verified_identity:
        fail("identity_mismatch", "请用受邀邮箱验证身份后加入", 403)
    member = db.scalar(
        select(Membership).where(
            Membership.organization_id == invitation.organization_id,
            Membership.user_id == user.id,
        )
    )
    if invitation.accepted_at and member:
        if member.status != "active":
            fail("organization_forbidden", "该成员资格已停用", 403)
        return member_out(db, member)
    if not mail.permitted(db, invitation):
        fail("invalid_invitation", "邀请人已无权授予此成员资格", 403)
    if member:
        fail("already_member", "该身份已加入企业；邀请不能修改已有权限", 409)
    member = Membership(
        organization_id=invitation.organization_id,
        user_id=user.id,
        department_id=invitation.department_id,
        roles=invitation.roles,
    )
    db.add(member)
    invitation.accepted_at = now()
    db.flush()
    db.add(
        AuditEntry(
            organization_id=member.organization_id,
            actor_user_id=user.id,
            action="invitation.accepted",
            entity_id=invitation.id,
        )
    )
    db.commit()
    return member_out(db, member)


@router.get("/{member_id}", response_model=MemberOut)
def get_member(member_id: str, db: Db, actor: Actor) -> MemberOut:
    member = db.scalar(member_scope(actor).where(Membership.id == member_id))
    if member is None:
        fail("not_found", "未找到此成员", 404)
    assert member is not None
    return member_out(db, member)
