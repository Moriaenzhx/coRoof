"""Offline SMTP acceptance and durable invitation delivery, with isolated tenant fixtures."""

import socket
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from email import policy
from email.parser import BytesParser
from threading import Event
from uuid import uuid4

import pytest
from aiosmtpd.controller import Controller
from conftest import API
from cryptography.fernet import Fernet
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from app.core.config import settings
from app.infrastructure.db import session_factory
from app.infrastructure.models import Invitation, Membership, now
from app.modules.identity import mail
from app.modules.identity.limits import limiter
from app.modules.identity.models import InvitationDelivery


@pytest.fixture
def smtp(monkeypatch):
    messages = []
    control = {"data": "250 Accepted", "quit": "221 Bye"}

    class Receiver:
        async def handle_DATA(self, server, session, envelope):
            messages.append(BytesParser(policy=policy.default).parsebytes(envelope.content))
            return control["data"]

        async def handle_QUIT(self, server, session, envelope):
            return control["quit"]

    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    server = Controller(Receiver(), hostname="127.0.0.1", port=port)
    server.start()
    for key, value in {
        "DELIVERY_MODE": "smtp",
        "SMTP_HOST": "127.0.0.1",
        "SMTP_PORT": str(port),
        "SMTP_TLS": "local",
        "SMTP_FROM": "invites@example.com",
        "MAIL_SECRET_KEY": Fernet.generate_key().decode(),
        "RATE_LIMIT_URL": "memory://",
        "INVITE_RATE_LIMIT": "1000/hour",
    }.items():
        monkeypatch.setenv("COROOF_" + key, value)
    settings.cache_clear()
    limiter.cache_clear()
    yield messages, control
    server.stop()
    limiter.cache_clear()


def create(boss, dept, email="recipient@example.com", key=None):
    return boss.post(
        "/members/invitations",
        {
            "department_id": dept["id"],
            "email": email,
            "idempotency_key": key or str(uuid4()),
        },
        201,
    )


def deliver(invitation, transport=None):
    with session_factory()() as db:
        row = db.scalar(
            select(InvitationDelivery).where(InvitationDelivery.invitation_id == invitation["id"])
        )
        args = row.organization_id, row.id, row.version
        db.rollback()
        if transport:
            mail.process(db, *args, transport=transport)
        else:
            mail.process(db, *args)
        return args


def record(invitation):
    with session_factory()() as db:
        row = db.scalar(
            select(InvitationDelivery).where(InvitationDelivery.invitation_id == invitation["id"])
        )
        db.expunge(row)
        return row


def test_smtp_transaction_encryption_idempotency_and_actual_protocol(smtp):
    boss = API()
    boss.org()
    dept = boss.department()
    key = str(uuid4())
    invitation = create(boss, dept, key=key)
    assert invitation["delivery"]["state"] == "queued"
    assert "token" not in str(invitation) and "#invite" not in str(invitation)
    row = record(invitation)
    assert "recipient@example.com" not in row.payload and "invite=" not in row.payload
    duplicate = create(boss, dept, key=key)
    assert duplicate["id"] == invitation["id"]
    assert (
        boss.request(
            "POST",
            "/members/invitations",
            {
                "email": "changed@example.com",
                "department_id": dept["id"],
                "idempotency_key": key,
            },
        ).status_code
        == 409
    )
    tasks = []
    with session_factory()() as db:
        assert mail.dispatch(db, lambda *args: tasks.append(args)) == 1
        assert mail.dispatch(db, lambda *args: tasks.append(args)) == 0
        mail.process(db, *tasks[0])
        mail.process(db, *tasks[0])
    assert len(smtp[0]) == 1
    assert record(invitation).state == "accepted" and record(invitation).payload is None
    message = smtp[0][0]
    assert message["To"] == "recipient@example.com"
    assert message["Message-ID"] == f"<{row.id}@example.com>"
    token = message.get_content().split("#invite=")[1].split()[0]
    employee = API("recipient@example.com")
    member = employee.post("/members/invitations/accept", {"token": token})
    assert member["roles"] == ["member"]
    assert employee.post("/members/invitations/accept", {"token": token}) == member
    with session_factory()() as db:
        assert db.scalar(select(func.count()).select_from(Invitation)) == 1


def test_smtp_quit_failure_does_not_retry_accepted_data(smtp):
    boss = API()
    boss.org()
    dept = boss.department()
    smtp[1]["quit"] = "450 QUIT unavailable"
    invitation = create(boss, dept)
    deliver(invitation)
    assert record(invitation).state == "accepted" and len(smtp[0]) == 1


@pytest.mark.parametrize(
    "code,expected", [("450 Try later", "retry_wait"), ("550 Rejected", "failed")]
)
def test_smtp_response_classifies_known_failures(smtp, code, expected):
    boss = API()
    boss.org()
    dept = boss.department()
    smtp[1]["data"] = code
    invitation = create(boss, dept)
    deliver(invitation)
    assert record(invitation).state == expected


def test_unknown_outcome_requires_versioned_explicit_retry(smtp):
    boss = API()
    boss.org()
    dept = boss.department()
    invitation = create(boss, dept)

    def unknown(*_):
        raise OSError("must not expose server or credential text")

    args = deliver(invitation, unknown)
    row = record(invitation)
    assert row.state == "unknown" and row.last_error == "delivery_unknown"
    with session_factory()() as db:
        assert mail.dispatch(db, lambda *_: pytest.fail("must not retry unknown")) == 0
        mail.process(db, *args, transport=lambda *_: pytest.fail("must not duplicate"))
    path = f"/members/invitations/{invitation['id']}/retry"
    body = {"expected_version": row.version, "confirm": True, "idempotency_key": str(uuid4())}
    assert (
        boss.post(path, {**body, "expected_version": 1}, 409)["error"]["code"] == "version_conflict"
    )
    first = boss.post(path, body)
    assert first["state"] == "queued" and boss.post(path, body) == first
    deliver(invitation)
    assert record(invitation).state == "accepted" and len(smtp[0]) == 1


def test_retries_are_bounded_and_stale_broker_receipts_are_fenced(smtp):
    boss = API()
    boss.org()
    dept = boss.department()
    invitation = create(boss, dept)

    def temporary(*_):
        raise mail.DeliveryFailure("connection_failed", "retry")

    with session_factory()() as db:
        assert mail.dispatch(db, lambda *_: (_ for _ in ()).throw(OSError())) == 0
    assert record(invitation).dispatched_at is None
    for _attempt in range(3):
        with session_factory()() as db:
            row = db.get(InvitationDelivery, record(invitation).id)
            row.available_at = now() - timedelta(seconds=1)
            db.commit()
        deliver(invitation, temporary)
    assert record(invitation).state == "failed" and record(invitation).attempts == 3


def test_broker_recovery_and_worker_interruption_do_not_repeat_smtp(smtp):
    boss = API()
    boss.org()
    dept = boss.department()
    invitation = create(boss, dept)
    tasks = []
    with session_factory()() as db:
        mail.dispatch(db, lambda *args: tasks.append(args))
        row = db.get(InvitationDelivery, record(invitation).id)
        row.dispatched_at = now() - timedelta(minutes=3)
        db.commit()
        mail.dispatch(db, lambda *args: tasks.append(args))
        assert len(tasks) == 2 and tasks[0][2] != tasks[1][2]
        mail.process(db, *tasks[0], transport=lambda *_: pytest.fail("stale receipt"))
        mail.process(db, *tasks[1])
    assert len(smtp[0]) == 1
    other = create(boss, dept, email="other@example.com")
    with session_factory()() as db:
        row = db.get(InvitationDelivery, record(other).id)
        row.state = "sending"
        row.lease_until = now() - timedelta(seconds=1)
        db.commit()
        assert mail.dispatch(db, lambda *_: pytest.fail("interrupted SMTP")) == 0
    assert record(other).state == "unknown"


@pytest.mark.parametrize("change", ["revoked", "expired", "inactive", "role", "mode"])
def test_revoked_expired_or_unauthorized_invites_cannot_send(smtp, change):
    boss = API()
    boss.org()
    dept = boss.department()
    invitation = create(boss, dept)
    with session_factory()() as db:
        row = db.get(Invitation, invitation["id"])
        actor = db.get(Membership, row.invited_by)
        if change == "revoked":
            row.revoked = True
        elif change == "expired":
            row.expires_at = now() - timedelta(seconds=1)
        elif change == "inactive":
            actor.status = "inactive"
        elif change == "role":
            actor.roles = ["member"]
        else:
            row.auth_mode = "oidc"
        db.commit()
    deliver(invitation, lambda *_: pytest.fail("unauthorized SMTP"))
    assert record(invitation).state == "cancelled" and record(invitation).payload is None


def test_invitation_delivery_tenant_binding_and_configuration_failure(smtp, monkeypatch):
    boss = API()
    boss.org()
    dept = boss.department()
    invitation = create(boss, dept)
    other = boss.org("另一个企业")
    second_dept = boss.department()
    other_invite = create(boss, second_dept)
    with session_factory()() as db:
        row = db.get(InvitationDelivery, record(invitation).id)
        row.payload = record(other_invite).payload
        db.commit()
    deliver(invitation, lambda *_: pytest.fail("envelope scope mismatch"))
    assert record(invitation).state == "failed"
    assert (
        boss.request(
            "POST",
            f"/members/invitations/{invitation['id']}/retry",
            {
                "expected_version": record(invitation).version,
                "confirm": True,
                "idempotency_key": str(uuid4()),
            },
        ).status_code
        == 404
    )
    with session_factory()() as db:
        db.add(InvitationDelivery(organization_id=other["id"], invitation_id=invitation["id"]))
        with pytest.raises(IntegrityError):
            db.commit()
        db.rollback()
    monkeypatch.setenv("COROOF_MAIL_SECRET_KEY", "")
    settings.cache_clear()
    with session_factory()() as db:
        count = db.scalar(select(func.count()).select_from(Invitation))
    response = boss.request(
        "POST",
        "/members/invitations",
        {
            "department_id": second_dept["id"],
            "email": "fail@example.com",
            "idempotency_key": str(uuid4()),
        },
    )
    assert response.status_code == 503
    with session_factory()() as db:
        assert db.scalar(select(func.count()).select_from(Invitation)) == count


def test_pg_concurrent_claim_and_invitation_creation_are_once(smtp):
    if session_factory().kw["bind"].dialect.name != "postgresql":
        pytest.skip("PostgreSQL row-lock acceptance")
    boss = API()
    boss.org()
    dept = boss.department()
    key = str(uuid4())
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: create(boss, dept, key=key), range(2)))
    assert results[0]["id"] == results[1]["id"]
    row = record(results[0])
    started, release = Event(), Event()
    calls = []

    def transport(*_):
        calls.append(True)
        started.set()
        assert release.wait(5)

    def run():
        with session_factory()() as db:
            mail.process(db, row.organization_id, row.id, row.version, transport=transport)

    with ThreadPoolExecutor(max_workers=2) as pool:
        one = pool.submit(run)
        assert started.wait(5)
        two = pool.submit(run)
        two.result(timeout=5)
        release.set()
        one.result(timeout=5)
    assert len(calls) == 1 and record(results[0]).state == "accepted"
