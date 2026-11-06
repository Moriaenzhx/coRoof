import hashlib
from datetime import timedelta
from typing import Literal

from fastapi import APIRouter, HTTPException, Request
from pydantic import Field
from sqlalchemy import func, select

from app.core.access import require_owner, tenant_get
from app.core.auth import Actor, Db, token_hash
from app.core.config import settings
from app.core.errors import fail
from app.infrastructure.models import (
    AIConfigEvent,
    AIConnection,
    AISettings,
    AnalysisRun,
    AuthSession,
    Identity,
    Membership,
    now,
    uid,
    utc,
)
from app.modules.ai_admin.schemas import (
    ConfigEventOut,
    ConnectionAction,
    ConnectionInput,
    ConnectionOut,
    PolicyInput,
    PolicyOut,
    ProviderOut,
)
from app.modules.ai_admin.service import (
    CODING_PLAN_BASE_URL,
    connection_config,
    connection_out,
    development_identity_allowed,
    development_only,
    development_test_allowed,
    lock_tenant,
    policy,
    policy_out,
    record,
    seal,
    validated_config,
)
from app.modules.intelligence import invocations
from app.modules.model_gateway.catalog import PROVIDERS
from app.modules.model_gateway.contracts import (
    Message,
    ModelFailure,
    ModelRequest,
    StrictModel,
    TokenUsage,
)
from app.modules.model_gateway.gateway import ModelGateway
from app.modules.model_gateway.profiles import resolve_profile

router = APIRouter(prefix="/ai", tags=["ai-management"])


class Probe(StrictModel):
    status: Literal["coroof_connection_ok"]
    checks: list[Literal["schema"]] = Field(min_length=1, max_length=1)


@router.get("/providers", response_model=list[ProviderOut])
def providers(actor: Actor) -> list[ProviderOut]:
    return [ProviderOut.model_validate(vars(p)) for p in PROVIDERS.values()]


@router.get("/settings", response_model=PolicyOut)
def read_settings(db: Db, actor: Actor) -> PolicyOut:
    require_owner(actor)
    return policy_out(db, actor)


@router.put("/settings", response_model=PolicyOut)
def save_settings(payload: PolicyInput, db: Db, actor: Actor) -> PolicyOut:
    lock_tenant(db, actor)
    row = policy(db, actor)
    if payload.expected_version != (row.version if row else 0):
        fail("version_conflict", "设置已更新，请刷新后再保存", 409)
    if payload.mode == "byok":
        connection = tenant_get(db, AIConnection, payload.connection_id or "", actor)
        if development_only(connection) and not (
            development_test_allowed(connection) and development_identity_allowed(db, actor)
        ):
            fail(
                "development_only", "该凭据已保存，但仅限开发用途；企业应用请配置通用 API Key", 409
            )
        if connection.state != "tested":
            fail("connection_not_tested", "请先完成该连接的测试", 409)
        try:
            resolve_profile(connection_config(connection, allow_development_test=True))
        except ModelFailure:
            fail("connection_unavailable", "连接配置不可用，请重新测试", 409)
    elif payload.connection_id is not None:
        fail("invalid_connection", "此服务模式不使用企业连接", 422)
    if payload.mode == "platform":
        if row and row.mode != "platform" and not policy_out(db, actor).platform_ready:
            fail("platform_unavailable", "平台模型尚未配置，请联系部署管理员", 409)
        for field in (
            "daily_call_limit",
            "daily_token_limit",
            "monthly_token_limit",
            "concurrency_limit",
        ):
            if getattr(payload, field) > getattr(settings(), f"ai_{field}"):
                fail("platform_limit", "平台服务额度不能超过部署方上限，请联系部署管理员", 422)
    if row is None:
        row = AISettings(organization_id=actor.organization_id, version=0)
        db.add(row)
    for field, value in payload.model_dump(exclude={"expected_version"}).items():
        setattr(row, field, value)
    row.version += 1
    mode_label = {"byok": "企业自带凭据", "platform": "平台服务", "disabled": "已暂停模型"}[
        row.mode
    ]
    record(
        db,
        actor,
        "settings.saved",
        row.version,
        f"{mode_label}；"
        f"24 小时 {row.daily_call_limit} 次 / {row.daily_token_limit} Token；"
        f"月度 {row.monthly_token_limit} Token；"
        f"并发 {row.concurrency_limit}；预警 {row.alert_percent}%",
        row.connection_id,
    )
    db.commit()
    return policy_out(db, actor)


@router.get("/connections", response_model=list[ConnectionOut])
def list_connections(db: Db, actor: Actor) -> list[ConnectionOut]:
    require_owner(actor)
    rows = db.scalars(
        select(AIConnection)
        .where(AIConnection.organization_id == actor.organization_id)
        .order_by(AIConnection.created_at.desc())
        .limit(100)
    ).all()
    return [connection_out(row) for row in rows]


@router.post("/connections", response_model=ConnectionOut, status_code=201)
def create_connection(payload: ConnectionInput, db: Db, actor: Actor) -> ConnectionOut:
    lock_tenant(db, actor)
    key = payload.api_key.get_secret_value()
    if any(char.isspace() or ord(char) < 33 or ord(char) > 126 for char in key):
        fail("invalid_credential", "凭据不能包含空格、换行或非 ASCII 字符", 422)
    raw = payload.model_dump_json(exclude={"api_key", "idempotency_key"}) + key
    fingerprint = hashlib.sha256(raw.encode()).hexdigest()
    previous = db.scalar(
        select(AIConnection).where(
            AIConnection.organization_id == actor.organization_id,
            AIConnection.actor_id == actor.id,
            AIConnection.request_key == str(payload.idempotency_key),
        )
    )
    if previous:
        if previous.request_hash != fingerprint:
            fail("idempotency_conflict", "同一请求不能提交不同配置", 409)
        return connection_out(previous)
    count = (
        db.scalar(
            select(func.count())
            .select_from(AIConnection)
            .where(
                AIConnection.organization_id == actor.organization_id,
                AIConnection.state != "revoked",
            )
        )
        or 0
    )
    if count >= 20:
        fail("connection_limit", "最多保留 20 个未撤销连接", 409)
    cfg = validated_config(
        {
            "ai_provider": payload.provider,
            "ai_model": payload.model,
            "ai_base_url": payload.base_url,
            "ai_api_key": payload.api_key,
            "ai_managed_connection": True,
            "ai_output_mode": payload.output_mode,
        }
    )
    if PROVIDERS[payload.provider].protocol != "chat" and payload.output_mode != "schema":
        fail("unsupported_mode", "该原生协议使用结构化输出模式", 422)
    restricted = (
        payload.provider == "bailian"
        and cfg.ai_base_url.rstrip("/") == CODING_PLAN_BASE_URL
        and key.startswith("sk-sp-")
    )
    try:
        # Registration is distinct from permission to call a model. A known developer
        # credential can be stored and managed without making any network request.
        if not restricted:
            resolve_profile(cfg, verification_probe=True)
        connection_id = uid()
        encrypted = seal(key, actor.organization_id, connection_id)
    except ModelFailure as exc:
        fail(exc.code, "端点未获部署方允许，或服务器尚未配置凭据加密", 422)
    row = AIConnection(
        id=connection_id,
        organization_id=actor.organization_id,
        actor_id=actor.id,
        request_key=str(payload.idempotency_key),
        request_hash=fingerprint,
        name=payload.name,
        provider=payload.provider,
        model=payload.model,
        base_url=cfg.ai_base_url.rstrip("/"),
        output_mode=payload.output_mode,
        credential=encrypted,
        key_suffix=key[-4:],
        state="draft",
        version=1,
    )
    db.add(row)
    db.flush()
    record(
        db,
        actor,
        "connection.created",
        row.version,
        "已保存 Coding Plan 凭据，仅登记管理，未启用业务"
        if restricted
        else "已保存连接，待测试并明确启用",
        row.id,
    )
    db.commit()
    return connection_out(row)


@router.post("/connections/{connection_id}/revoke", response_model=ConnectionOut)
def revoke(connection_id: str, payload: ConnectionAction, db: Db, actor: Actor) -> ConnectionOut:
    lock_tenant(db, actor)
    row = tenant_get(db, AIConnection, connection_id, actor, lock=True)
    if row.state == "revoked":
        return connection_out(row)
    if row.version != payload.expected_version:
        fail("version_conflict", "连接已变化，请刷新", 409)
    row.state, row.credential, row.key_suffix = "revoked", None, ""
    row.version += 1
    current = policy(db, actor)
    if current and current.connection_id == row.id:
        current.mode, current.connection_id = "disabled", None
        current.version += 1
    record(db, actor, "connection.revoked", row.version, "已撤销凭据；该连接不再接收新请求", row.id)
    db.commit()
    return connection_out(row)


@router.post("/connections/{connection_id}/test", response_model=ConnectionOut)
def test_connection(
    connection_id: str, payload: ConnectionAction, db: Db, actor: Actor, request: Request
) -> ConnectionOut:
    lock_tenant(db, actor)
    row = tenant_get(db, AIConnection, connection_id, actor, lock=True)
    if development_only(row) and not (
        development_test_allowed(row) and development_identity_allowed(db, actor)
    ):
        fail("development_only", "该凭据仅登记管理；企业连接测试请使用通用 API Key", 409)
    prior = db.scalar(
        select(AIConfigEvent).where(
            AIConfigEvent.organization_id == actor.organization_id,
            AIConfigEvent.actor_id == actor.id,
            AIConfigEvent.request_key == str(payload.idempotency_key),
        )
    )
    if prior:
        if prior.connection_id != row.id or prior.revision != payload.expected_version:
            fail("idempotency_conflict", "同一测试请求参数已变化", 409)
        return connection_out(row)
    if row.version != payload.expected_version or row.state == "revoked":
        fail("version_conflict", "连接已变化，请刷新", 409)
    if (
        row.state == "testing"
        and row.tested_at
        and utc(row.tested_at) > now() - timedelta(seconds=130)
    ):
        fail("test_in_progress", "连接测试仍在进行中", 409)
    try:
        cfg = connection_config(row, allow_development_test=True)
        limits = policy_out(db, actor)
        cfg.ai_daily_call_limit, cfg.ai_daily_token_limit = (
            limits.daily_call_limit,
            limits.daily_token_limit,
        )
        cfg.ai_monthly_token_limit, cfg.ai_concurrency_limit = (
            limits.monthly_token_limit,
            limits.concurrency_limit,
        )
        cfg.ai_config_revision = limits.version
        cfg.ai_max_output_tokens = 256
        gateway = ModelGateway(cfg)
        call = gateway.prepare(
            ModelRequest(
                task="connection_test",
                schema_version="connection-probe-v1",
                prompt_version="connection-probe-v1",
                messages=(
                    Message(
                        role="user",
                        content=(
                            "仅为合成连接测试。返回 JSON："
                            '{"status":"coroof_connection_ok","checks":["schema"]}'
                        ),
                    ),
                ),
            ),
            Probe,
            verification_probe=True,
        )
    except ModelFailure as exc:
        fail(exc.code, "连接不可用，请检查配置及服务端加密密钥", 422)
    row.state, row.tested_at, row.last_error = "testing", now(), None
    record(
        db,
        actor,
        "connection.test_started",
        row.version,
        "合成结构化输出测试；未发送企业资料",
        row.id,
        str(payload.idempotency_key),
    )
    run = AnalysisRun(
        organization_id=actor.organization_id,
        actor_id=actor.id,
        purpose="connection_test",
        provider=cfg.ai_provider,
        model=cfg.ai_model,
        prompt_version="connection-probe-v1",
        input_evidence_ids=[],
        output_schema_version="connection-probe-v1",
        latency_ms=0,
        status="pending",
        cost_estimate="unknown",
    )
    db.add(run)
    db.flush()
    failure, usage, invocation, result = None, TokenUsage(), None, None
    try:
        invocation = invocations.reserve(db, actor, run, call, cfg)
        result = gateway.generate(call, Probe)
        usage = result.usage
    except ModelFailure as exc:
        failure, usage = exc, exc.usage
    db.expire_all()
    auth_error = None
    try:
        lock_tenant(db, actor)
        session = db.get(AuthSession, token_hash(request.cookies.get("coroof_session", "")))
        if session is None or session.user_id != actor.user_id or utc(session.expires_at) <= now():
            fail("unauthenticated", "会话已失效", 401)
        db.refresh(row)
        if row.version != payload.expected_version or row.state != "testing":
            fail("version_conflict", "测试期间连接已撤销或变更", 409)
        if development_only(row) and not (
            development_test_allowed(row) and development_identity_allowed(db, actor)
        ):
            failure = ModelFailure("policy_denied", sent=invocation is not None, usage=usage)
    except HTTPException as exc:
        auth_error, failure = (
            exc,
            ModelFailure("access_revoked", sent=invocation is not None, usage=usage),
        )
    if invocation:
        invocations.finish(
            db,
            invocation,
            error=failure.code if failure else None,
            usage=usage,
            sent=failure.sent if failure else True,
            request_id=result.provider_request_id if result else None,
            returned_model=result.returned_model if result else None,
        )
    if row.version == payload.expected_version and row.state == "testing":
        row.state, row.last_error = ("failed", failure.code) if failure else ("tested", None)
        row.version += 1
        row.tested_at = now()
    run.status, run.failure_code = ("failed", failure.code) if failure else ("succeeded", None)
    record(
        db,
        actor,
        "connection.test_finished",
        row.version,
        failure.code if failure else "结构化连接测试通过；不代表业务质量或生产验收",
        row.id,
    )
    db.commit()
    if auth_error:
        raise auth_error
    return connection_out(row)


@router.get("/config-events", response_model=list[ConfigEventOut])
def events(db: Db, actor: Actor) -> list[ConfigEventOut]:
    require_owner(actor)
    return [
        ConfigEventOut(
            id=row.id,
            actor_name=name,
            action=row.action,
            revision=row.revision,
            detail=row.detail,
            recorded_at=utc(row.recorded_at),
        )
        for row, name in db.execute(
            select(AIConfigEvent, Identity.name)
            .join(
                Membership,
                (Membership.organization_id == AIConfigEvent.organization_id)
                & (Membership.id == AIConfigEvent.actor_id),
            )
            .join(Identity, Identity.id == Membership.user_id)
            .where(AIConfigEvent.organization_id == actor.organization_id)
            .order_by(AIConfigEvent.recorded_at.desc(), AIConfigEvent.id)
            .limit(50)
        )
    ]
