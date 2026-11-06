import json
from typing import Any

from cryptography.fernet import Fernet, InvalidToken
from pydantic import SecretStr, ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.access import require_owner, tenant_get
from app.core.config import Settings, settings
from app.core.errors import fail
from app.infrastructure.models import (
    AIConfigEvent,
    AIConnection,
    AISettings,
    Identity,
    Membership,
    Organization,
    utc,
)
from app.modules.ai_admin.schemas import ConnectionOut, PolicyOut
from app.modules.model_gateway.contracts import ModelFailure
from app.modules.model_gateway.profiles import CODING_PLAN_BASE_URL as CODING_PLAN_BASE_URL
from app.modules.model_gateway.profiles import development_connection_allowed, resolve_profile


def development_only(row: AIConnection) -> bool:
    # Connections are immutable. Scope is derived from the saved, validated endpoint,
    # never from a client-supplied permission flag or a successful developer probe.
    return row.base_url.rstrip("/") == CODING_PLAN_BASE_URL


def development_test_allowed(row: AIConnection, cfg: Settings | None = None) -> bool:
    return development_connection_allowed(
        cfg or settings(), row.id, row.provider, row.model, row.base_url
    )


def development_identity_allowed(db: Session, actor: Membership) -> bool:
    identity = db.get(Identity, actor.user_id, populate_existing=True)
    return identity is not None and identity.identity_provider == "mock"


def cipher() -> Fernet:
    try:
        return Fernet(settings().ai_secret_key.get_secret_value().encode())
    except (ValueError, TypeError):
        raise ModelFailure("not_configured") from None


def seal(secret: str, organization_id: str, connection_id: str) -> str:
    return cipher().encrypt(json.dumps([organization_id, connection_id, secret]).encode()).decode()


def unseal(row: AIConnection) -> SecretStr:
    try:
        org, connection, key = json.loads(cipher().decrypt((row.credential or "").encode()))
        if org != row.organization_id or connection != row.id:
            raise ValueError
        return SecretStr(key)
    except (InvalidToken, ValueError, TypeError):
        raise ModelFailure("not_configured") from None


def lock_tenant(db: Session, actor: Membership) -> None:
    db.scalar(
        select(Organization).where(Organization.id == actor.organization_id).with_for_update()
    )
    db.refresh(actor)
    if actor.status != "active":
        fail("organization_forbidden", "企业访问权限已失效", 403)
    require_owner(actor)


def policy(db: Session, actor: Membership) -> AISettings | None:
    return db.scalar(
        select(AISettings)
        .where(AISettings.organization_id == actor.organization_id)
        .execution_options(populate_existing=True)
    )


def connection_config(
    row: AIConnection, base: Settings | None = None, *, allow_development_test: bool = False
) -> Settings:
    cfg = base or settings()
    restricted = development_only(row)
    if restricted and not (allow_development_test and development_test_allowed(row, cfg)):
        raise ModelFailure("policy_denied")
    values = cfg.model_dump()
    values.update(
        ai_provider=row.provider,
        ai_model=row.model,
        ai_base_url=row.base_url,
        ai_api_key=unseal(row),
        ai_model_verified=row.state == "tested",
        ai_output_mode=row.output_mode,
        ai_managed_connection=True,
        ai_connection_id=row.id,
        ai_billing_mode="byok",
    )
    if restricted:
        values["ai_timeout_seconds"] = 60
        # Local multi-read test cases need room for the existing strict schema,
        # deduplicated evidence and timeline. Tenant quotas still reserve the
        # actual prepared input and output; ordinary connections are unchanged.
        values["ai_max_input_tokens"] = 32768
    selected = Settings(_env_file=None, **values)
    selected._local_test_connection_selected = restricted
    return selected


def effective_config(
    db: Session, actor: Membership, *, allow_development_test: bool = False
) -> Settings:
    cfg = settings().model_copy(deep=True)
    row = policy(db, actor)
    if row is None:
        return cfg
    for field, value in limits(row).items():
        setattr(cfg, f"ai_{field}", value)
    cfg.ai_config_revision = row.version
    if row.mode == "disabled":
        cfg.ai_provider = "rules"
    elif row.mode == "byok":
        connection = tenant_get(db, AIConnection, row.connection_id or "", actor)
        if connection.state != "tested":
            raise ModelFailure("not_verified")
        if development_only(connection) and not development_identity_allowed(db, actor):
            raise ModelFailure("policy_denied")
        cfg = connection_config(connection, cfg, allow_development_test=allow_development_test)
    return cfg


def limits(row: AISettings | None) -> dict[str, int]:
    cfg = settings()
    result = {}
    for field in (
        "daily_call_limit",
        "daily_token_limit",
        "monthly_token_limit",
        "concurrency_limit",
    ):
        ceiling = getattr(cfg, f"ai_{field}")
        value = getattr(row, field) if row else ceiling
        result[field] = min(value, ceiling) if row and row.mode == "platform" else value
    return result


def policy_out(db: Session, actor: Membership) -> PolicyOut:
    row, cfg = policy(db, actor), settings()
    try:
        cipher()
        storage_ready = True
    except ModelFailure:
        storage_ready = False
    try:
        resolve_profile(cfg)
        platform_ready = True
    except ModelFailure:
        platform_ready = False
    return PolicyOut(
        version=row.version if row else 0,
        mode=row.mode if row else "platform",
        connection_id=row.connection_id if row else None,
        **limits(row),
        alert_percent=row.alert_percent if row else 80,
        credential_storage_ready=storage_ready,
        platform_ready=platform_ready,
        platform_model=cfg.ai_model or None,
        platform_provider=cfg.ai_provider,
        allowed_custom_base_urls=cfg.ai_allowed_base_urls,
    )


def connection_out(row: AIConnection) -> ConnectionOut:
    restricted = development_only(row)
    local_test = restricted and development_test_allowed(row)
    return ConnectionOut(
        id=row.id,
        name=row.name,
        provider=row.provider,
        model=row.model,
        base_url=row.base_url,
        output_mode=row.output_mode,
        key_hint="••••" + row.key_suffix,
        state=row.state,
        version=row.version,
        tested_at=utc(row.tested_at) if row.tested_at else None,
        last_error=row.last_error,
        usage_scope="development_only" if restricted else "application",
        usage_notice=(
            "仅限本机开发测试与当前企业交互查询，不用于生产；后台持续关注不会调用此连接。"
            if local_test
            else "Coding Plan 凭据已保存，仅供查看与管理；未启用企业业务调用。"
            "企业应用请配置通用 API Key。"
        )
        if restricted
        else None,
        can_test=(not restricted or local_test) and row.state != "revoked",
        can_activate=(not restricted or local_test) and row.state == "tested",
    )


def record(
    db: Session,
    actor: Membership,
    action: str,
    revision: int,
    detail: str,
    connection_id: str | None = None,
    request_key: str | None = None,
) -> None:
    db.add(
        AIConfigEvent(
            organization_id=actor.organization_id,
            actor_id=actor.id,
            connection_id=connection_id,
            request_key=request_key,
            action=action,
            revision=revision,
            detail=detail,
        )
    )


def validated_config(values: dict[str, Any]) -> Settings:
    try:
        return Settings(_env_file=None, **{**settings().model_dump(), **values})
    except ValidationError:
        fail("invalid_connection", "模型或端点格式不正确", 422)
    raise AssertionError
