"""Encrypted transactional invitation delivery, bounded retries and explicit unknown outcomes."""

import asyncio
import json
from collections.abc import Callable
from datetime import timedelta
from email.message import EmailMessage
from typing import Literal
from urllib.parse import quote, urlparse

import aiosmtplib
from cryptography.fernet import Fernet
from fastapi import HTTPException
from pydantic import EmailStr, TypeAdapter
from sqlalchemy import and_, or_, select
from sqlalchemy.orm import Session

from app.core.access import audit, require_manager, tenant_get
from app.core.config import Settings, settings
from app.core.errors import fail
from app.core.schemas import DeliveryRetry, DeliveryStatus
from app.infrastructure.models import Identity, Invitation, Membership, Organization, now, uid, utc
from app.modules.identity.models import InvitationDelivery
from app.modules.identity.sessions import digest


class DeliveryFailure(Exception):
    def __init__(self, code: str, outcome: Literal["retry", "failed", "unknown"]) -> None:
        self.code, self.outcome = code, outcome
        super().__init__(code)


def configured(cfg: Settings) -> Fernet:
    try:
        cipher = Fernet(cfg.mail_secret_key.get_secret_value().encode())
        TypeAdapter(EmailStr).validate_python(cfg.smtp_from)
        if (
            cfg.delivery_mode != "smtp"
            or not cfg.smtp_host
            or "\r" in cfg.smtp_host
            or "\n" in cfg.smtp_host
        ):
            raise ValueError("missing_smtp")
        if cfg.smtp_tls == "local" and not (
            cfg.environment == "test" and cfg.smtp_host in {"localhost", "127.0.0.1", "::1"}
        ):
            raise ValueError("insecure_smtp")
        origin = urlparse(cfg.web_origin)
        if (
            not origin.hostname
            or origin.username
            or origin.password
            or origin.query
            or origin.fragment
            or origin.path not in {"", "/"}
        ):
            raise ValueError("invalid_origin")
        if origin.scheme != "https" and not (
            cfg.environment == "test"
            and origin.hostname in {"localhost", "127.0.0.1", "testserver"}
        ):
            raise ValueError("insecure_invitation_url")
        return cipher
    except ValueError:
        fail("delivery_not_configured", "正式邀请投递尚未配置完成", 503)


def status(row: InvitationDelivery) -> DeliveryStatus:
    return DeliveryStatus(
        state=row.state,
        version=row.version,
        attempts=row.attempts,
        accepted_at=utc(row.accepted_at) if row.accepted_at else None,
        last_error=row.last_error,
    )


def lookup(db: Session, invitation: Invitation) -> InvitationDelivery | None:
    return db.scalar(
        select(InvitationDelivery).where(
            InvitationDelivery.organization_id == invitation.organization_id,
            InvitationDelivery.invitation_id == invitation.id,
        )
    )


def enqueue(db: Session, invitation: Invitation, token: str) -> InvitationDelivery:
    cipher = configured(settings())
    row = InvitationDelivery(
        id=uid(), organization_id=invitation.organization_id, invitation_id=invitation.id
    )
    org = db.get(Organization, invitation.organization_id)
    assert org is not None
    data = [
        row.organization_id,
        row.id,
        invitation.id,
        invitation.email,
        settings().web_origin.rstrip("/") + "/#invite=" + quote(token, safe=""),
        org.name,
    ]
    row.payload = cipher.encrypt(json.dumps(data).encode()).decode()
    db.add(row)
    db.flush()
    return row


def permitted(db: Session, invitation: Invitation) -> bool:
    if (
        invitation.revoked
        or invitation.accepted_at
        or utc(invitation.expires_at) <= now()
        or invitation.auth_mode != settings().auth_mode
    ):
        return False
    actor = db.get(Membership, invitation.invited_by, populate_existing=True)
    if (
        actor is None
        or actor.organization_id != invitation.organization_id
        or actor.status != "active"
    ):
        return False
    identity = db.get(Identity, actor.user_id)
    if (
        identity is None
        or identity.identity_provider != settings().auth_mode
        or (settings().auth_mode == "oidc" and identity.oidc_issuer != settings().oidc_issuer)
    ):
        return False
    try:
        require_manager(actor, invitation.department_id)
        if "owner" not in actor.roles and set(invitation.roles) != {"member"}:
            return False
    except HTTPException:
        return False
    return True


def send(cfg: Settings, message: EmailMessage) -> None:
    async def exchange() -> dict[str, aiosmtplib.response.SMTPResponse]:
        smtp = aiosmtplib.SMTP(
            hostname=cfg.smtp_host,
            port=cfg.smtp_port,
            username=cfg.smtp_username or None,
            password=cfg.smtp_password.get_secret_value() or None,
            use_tls=cfg.smtp_tls == "tls",
            start_tls=cfg.smtp_tls == "starttls",
            validate_certs=True,
            timeout=10,
        )
        await smtp.connect()
        try:
            refused, _ = await smtp.send_message(message)
            return refused
        finally:
            # QUIT errors cannot turn a known DATA acceptance into a retry.
            try:
                await smtp.quit()
            except Exception:
                smtp.close()

    try:
        refused = asyncio.run(exchange())
        if refused:
            raise DeliveryFailure("recipient_rejected", "failed")
    except (aiosmtplib.SMTPConnectError, aiosmtplib.SMTPConnectTimeoutError):
        raise DeliveryFailure("connection_failed", "retry") from None
    except aiosmtplib.SMTPAuthenticationError:
        raise DeliveryFailure("authentication_failed", "failed") from None
    except aiosmtplib.SMTPRecipientsRefused as exc:
        temporary = all(400 <= recipient.code < 500 for recipient in exc.recipients)
        raise DeliveryFailure("recipient_rejected", "retry" if temporary else "failed") from None
    except aiosmtplib.SMTPResponseException as exc:
        raise DeliveryFailure(
            "smtp_rejected", "retry" if 400 <= exc.code < 500 else "failed"
        ) from None
    except DeliveryFailure:
        raise
    except Exception:
        # Connection loss after DATA may have sent the message. Never silently resend.
        raise DeliveryFailure("delivery_unknown", "unknown") from None


def process(
    db: Session,
    organization_id: str,
    identifier: str,
    version: int,
    *,
    transport: Callable[[Settings, EmailMessage], None] = send,
) -> None:
    row = db.scalar(
        select(InvitationDelivery)
        .where(
            InvitationDelivery.organization_id == organization_id,
            InvitationDelivery.id == identifier,
        )
        .with_for_update()
    )
    if (
        row is None
        or row.version != version
        or row.state not in {"queued", "retry_wait"}
        or utc(row.available_at) > now()
    ):
        db.rollback()
        return
    invitation = db.scalar(
        select(Invitation).where(
            Invitation.organization_id == organization_id, Invitation.id == row.invitation_id
        )
    )
    if invitation is None or not permitted(db, invitation):
        row.state, row.payload = "cancelled", None
        row.last_error = "invitation_unavailable"
        row.version += 1
        db.commit()
        return
    try:
        cfg = settings()
        cipher = configured(cfg)
        org, delivery, invitation_id, recipient, link, company = json.loads(
            cipher.decrypt((row.payload or "").encode())
        )
        if [org, delivery, invitation_id, recipient] != [
            organization_id,
            row.id,
            invitation.id,
            invitation.email,
        ]:
            raise ValueError("delivery_binding_mismatch")
        message = EmailMessage()
        message["From"], message["To"], message["Subject"] = (
            cfg.smtp_from,
            recipient,
            "加入 coRoof 企业工作空间",
        )
        message["Message-ID"] = "<" + row.id + "@" + cfg.smtp_from.split("@")[-1] + ">"
        message.set_content(
            f"你收到 {company} 的加入邀请。\n"
            "请先使用受邀邮箱完成身份验证，再明确确认加入。\n"
            f"邀请链接：{link}\n本邀请有效期为 24 小时；若不是你的请求，请忽略。"
        )
    except Exception:
        row.state, row.last_error = "failed", "delivery_not_configured"
        row.version += 1
        db.commit()
        return
    row.state = "sending"
    row.attempts += 1
    row.version += 1
    claimed = row.version
    row.lease_until = now() + timedelta(seconds=90)
    db.commit()  # No transaction lock is held while talking to SMTP.
    error = None
    try:
        transport(cfg, message)
    except DeliveryFailure as exc:
        error = exc
    except Exception:
        error = DeliveryFailure("delivery_unknown", "unknown")
    db.expire_all()
    row = db.scalar(
        select(InvitationDelivery)
        .where(
            InvitationDelivery.organization_id == organization_id,
            InvitationDelivery.id == identifier,
        )
        .with_for_update()
    )
    if row is None or row.version != claimed or row.state != "sending":
        db.rollback()
        return
    row.version += 1
    row.lease_until = None
    row.dispatched_at = None
    if error is None:
        row.state, row.accepted_at, row.payload, row.last_error = "accepted", now(), None, None
    elif error.outcome == "retry" and row.attempts < 3:
        row.state = "retry_wait"
        row.available_at = now() + timedelta(seconds=30 * row.attempts)
        row.last_error = error.code
    else:
        row.state = "unknown" if error.outcome == "unknown" else "failed"
        row.last_error = error.code
    db.commit()


def dispatch(db: Session, publish: Callable[[str, str, int], None]) -> int:
    # Remove expired/revoked encrypted bearer links even after failed delivery.
    invalid = select(Invitation.id).where(
        or_(
            Invitation.revoked.is_(True),
            Invitation.accepted_at.is_not(None),
            Invitation.expires_at <= now(),
            Invitation.auth_mode != settings().auth_mode,
        )
    )
    for expired in db.scalars(
        select(InvitationDelivery)
        .where(
            InvitationDelivery.invitation_id.in_(invalid),
            InvitationDelivery.payload.is_not(None),
            InvitationDelivery.state != "sending",
        )
        .with_for_update(skip_locked=True)
        .limit(100)
    ):
        expired.state, expired.payload = "cancelled", None
        expired.version += 1
    db.commit()
    # Interrupted SMTP is unknown. Only unclaimed broker deliveries may be requeued.
    for stale in db.scalars(
        select(InvitationDelivery)
        .where(
            or_(
                and_(
                    InvitationDelivery.state == "sending", InvitationDelivery.lease_until <= now()
                ),
                and_(
                    InvitationDelivery.state.in_(["queued", "retry_wait"]),
                    InvitationDelivery.dispatched_at < now() - timedelta(seconds=120),
                ),
            )
        )
        .order_by(InvitationDelivery.available_at, InvitationDelivery.id)
        .with_for_update(skip_locked=True)
        .limit(100)
    ):
        if stale.state == "sending" and stale.lease_until and utc(stale.lease_until) <= now():
            stale.state, stale.last_error, stale.lease_until = "unknown", "worker_interrupted", None
            stale.version += 1
        elif (
            stale.state != "sending"
            and stale.dispatched_at
            and utc(stale.dispatched_at) < now() - timedelta(seconds=120)
        ):
            stale.dispatched_at = None
            stale.version += 1
    db.commit()
    count = 0
    for _ in range(50):
        row = db.scalar(
            select(InvitationDelivery)
            .where(
                InvitationDelivery.state.in_(["queued", "retry_wait"]),
                InvitationDelivery.dispatched_at.is_(None),
                InvitationDelivery.available_at <= now(),
            )
            .order_by(InvitationDelivery.available_at, InvitationDelivery.id)
            .with_for_update(skip_locked=True)
            .limit(1)
        )
        if row is None:
            db.rollback()
            break
        row.version += 1
        try:
            publish(row.organization_id, row.id, row.version)
        except Exception:
            db.rollback()
            break
        row.dispatched_at = now()
        db.commit()
        count += 1
    return count


def retry(
    db: Session, actor: Membership, invitation: Invitation, payload: DeliveryRetry
) -> DeliveryStatus:
    require_manager(actor, invitation.department_id)
    row = lookup(db, invitation)
    if row is None:
        fail("not_found", "未找到邮件投递记录", 404)
    row = tenant_get(db, InvitationDelivery, row.id, actor, lock=True)
    fingerprint = digest(payload.model_dump_json())
    if row.retry_key == str(payload.idempotency_key):
        if row.retry_hash != fingerprint:
            fail("idempotency_conflict", "同一请求不能更改内容", 409)
        return status(row)
    if row.version != payload.expected_version or row.state not in {"failed", "unknown"}:
        fail("version_conflict", "投递状态已变化，请刷新核对", 409)
    if not permitted(db, invitation) or not row.payload:
        fail("invitation_unavailable", "邀请已不可用，请重新发起邀请", 409)
    configured(settings())
    row.state, row.last_error, row.available_at, row.dispatched_at = "queued", None, now(), None
    row.version += 1
    row.attempts = 0
    row.retry_key = str(payload.idempotency_key)
    row.retry_hash = fingerprint
    audit(db, actor, "invitation.delivery_retry", invitation.id)
    db.commit()
    return status(row)
