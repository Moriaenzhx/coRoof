"""Deterministic release preflight; never treats local protocol tests as live acceptance."""

from typing import TYPE_CHECKING
from urllib.parse import urlparse

from cryptography.fernet import Fernet
from limits import parse
from sqlalchemy.engine import make_url

if TYPE_CHECKING:
    from app.core.config import Settings


def issues(cfg: "Settings") -> list[str]:
    missing = []
    if cfg.ai_development_test_connection_ids:
        missing.append("development_model_connections")
    if not cfg.production_release_verified:
        missing.append("external_release_acceptance")
    if cfg.auth_mode != "oidc" or not cfg.oidc_client_id:
        missing.append("verified_identity")
    if (
        len(cfg.oidc_client_secret.get_secret_value()) < 16
        or len(cfg.oidc_session_secret.get_secret_value()) < 32
    ):
        missing.append("identity_secrets")
    for name, value in (("web_origin", cfg.web_origin), ("identity_issuer", cfg.oidc_issuer)):
        url = urlparse(value)
        if (
            url.scheme != "https"
            or not url.hostname
            or url.username
            or url.password
            or url.query
            or url.fragment
            or (name == "web_origin" and url.path not in {"", "/"})
        ):
            missing.append(name)
    if not cfg.cookie_secure:
        missing.append("secure_cookies")
    if (
        cfg.delivery_mode != "smtp"
        or not cfg.smtp_host
        or not cfg.smtp_from
        or cfg.smtp_tls not in {"starttls", "tls"}
        or not cfg.smtp_username
        or not cfg.smtp_password.get_secret_value()
    ):
        missing.append("verified_delivery")
    for name, secret in (
        ("mail_encryption", cfg.mail_secret_key),
        ("ai_encryption", cfg.ai_secret_key),
    ):
        try:
            Fernet(secret.get_secret_value().encode())
        except ValueError:
            missing.append(name)
    try:
        database = make_url(cfg.database_url)
        if (
            database.get_backend_name() != "postgresql"
            or not database.host
            or len(database.password or "") < 16
        ):
            missing.append("postgres_credentials")
    except Exception:
        missing.append("postgres_credentials")
    for name, value in (
        ("redis_credentials", cfg.redis_url),
        ("shared_rate_limit", cfg.rate_limit_url or cfg.redis_url),
    ):
        url = urlparse(value)
        if (
            url.scheme not in {"redis", "rediss"}
            or not url.hostname
            or len(url.password or "") < 16
        ):
            missing.append(name)
    try:
        parse(cfg.auth_rate_limit)
        parse(cfg.invite_rate_limit)
    except ValueError:
        missing.append("rate_limit_policy")
    return missing
