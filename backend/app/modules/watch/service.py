"""Server-owned, expiring read grants; no browser token is kept for background execution."""

import hashlib
import json
from datetime import timedelta
from typing import Any

from fastapi import HTTPException
from sqlalchemy import Select, func, select
from sqlalchemy.orm import Session

from app.core.access import audit, require_owner, tenant_get, work_scope
from app.core.config import settings
from app.core.errors import fail
from app.infrastructure.models import (
    AgentRun,
    AIConnection,
    Department,
    Identity,
    Initiative,
    Membership,
    Organization,
    WorkItem,
    now,
    utc,
)
from app.modules.ai_admin.service import development_only
from app.modules.ai_admin.service import policy as ai_policy
from app.modules.watch.models import WatchCommand, WatchGrant, WatchPolicy, WatchRun
from app.modules.watch.schemas import (
    PolicyAction,
    PolicyCreate,
    PolicyEdit,
    PolicyFields,
    WatchPolicyOut,
)


def fingerprint(data: dict[str, Any]) -> str:
    return hashlib.sha256(json.dumps(data, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def identity_binding(db: Session, actor: Membership) -> str:
    identity = db.get(Identity, actor.user_id, populate_existing=True)
    cfg = settings()
    if (
        identity is None
        or identity.identity_provider != cfg.auth_mode
        or (cfg.auth_mode == "oidc" and identity.oidc_issuer != cfg.oidc_issuer)
    ):
        fail("watch_authorization_lost", "持续关注的身份授权已失效", 403)
    return fingerprint(
        {
            "user": actor.user_id,
            "mode": identity.identity_provider,
            "issuer": identity.oidc_issuer,
            "subject": identity.oidc_subject,
        }
    )


def owner(db: Session, actor: Membership) -> None:
    db.refresh(actor)
    if actor.status != "active":
        fail("organization_forbidden", "企业访问权限已失效", 403)
    require_owner(actor)
    identity_binding(db, actor)


def command_lock(db: Session, actor: Membership) -> None:
    db.scalar(
        select(Organization)
        .where(Organization.id == actor.organization_id)
        .with_for_update(key_share=True)
    )
    owner(db, actor)


def scope(policy: WatchPolicy, actor: Membership) -> Select[tuple[WorkItem]]:
    statement = work_scope(actor)
    if policy.scope_kind == "department":
        statement = statement.where(WorkItem.department_id == policy.department_id)
    elif policy.scope_kind == "initiative":
        statement = statement.where(WorkItem.initiative_id == policy.initiative_id)
    return statement


def current_grant(db: Session, policy: WatchPolicy) -> WatchGrant | None:
    return db.scalar(
        select(WatchGrant)
        .where(
            WatchGrant.organization_id == policy.organization_id,
            WatchGrant.policy_id == policy.id,
            WatchGrant.policy_version == policy.version,
        )
        .execution_options(populate_existing=True)
    )


def authorize(
    db: Session, actor: Membership, grant_id: str, work_id: str | None = None
) -> WatchPolicy:
    owner(db, actor)
    grant = tenant_get(db, WatchGrant, grant_id, actor)
    db.refresh(grant)
    policy = tenant_get(db, WatchPolicy, grant.policy_id, actor)
    db.refresh(policy)
    if (
        grant.actor_id != actor.id
        or policy.actor_id != actor.id
        or grant.revoked_at is not None
        or policy.state != "active"
        or policy.version != grant.policy_version
        or utc(grant.expires_at) <= now()
        or utc(policy.expires_at) <= now()
        or grant.identity_binding != identity_binding(db, actor)
    ):
        fail("watch_authorization_lost", "持续关注已暂停、到期或授权发生变化", 403)
    if work_id and not db.scalar(scope(policy, actor).where(WorkItem.id == work_id)):
        fail("scope_forbidden", "事项不在持续关注授权范围内", 403)
    if work_id:
        from app.modules.watch.sources import source_stamp

        work = db.get(WorkItem, work_id)
        if work is None or source_stamp(db, work)[0]:
            fail("source_unavailable", "来源更新失败或已失效，暂不据此生成推进判断", 409)
    return policy


def get(db: Session, actor: Membership, identifier: str, *, lock: bool = False) -> WatchPolicy:
    owner(db, actor)
    policy = tenant_get(db, WatchPolicy, identifier, actor, lock=lock)
    if policy.actor_id != actor.id:
        fail("not_found", "未找到此关注策略", 404)
    return policy


def view(db: Session, actor: Membership, policy: WatchPolicy) -> WatchPolicyOut:
    effective = policy.state
    if effective == "active":
        if utc(policy.expires_at) <= now():
            effective = "expired"
        else:
            grant = current_grant(db, policy)
            try:
                if not grant:
                    raise ValueError("missing_grant")
                authorize(db, actor, grant.id)
            except (HTTPException, ValueError):
                effective = "unauthorized"
    return WatchPolicyOut.model_validate(
        {
            **{key: getattr(policy, key) for key in PolicyFields.model_fields},
            "id": policy.id,
            "actor_id": policy.actor_id,
            "state": policy.state,
            "effective_state": effective,
            "version": policy.version,
            "created_at": utc(policy.created_at),
            "next_due_at": utc(policy.next_due_at),
            "expires_at": utc(policy.expires_at),
            "last_checked_at": utc(policy.last_checked_at) if policy.last_checked_at else None,
        }
    )


def validate_fields(db: Session, actor: Membership, data: PolicyFields) -> None:
    if not now() + timedelta(minutes=5) < data.expires_at <= now() + timedelta(days=90):
        fail("invalid_grant_expiry", "授权期限须在五分钟后至九十天内", 422)
    if data.department_id:
        tenant_get(db, Department, str(data.department_id), actor)
    if data.initiative_id:
        tenant_get(db, Initiative, str(data.initiative_id), actor)


def grant(db: Session, actor: Membership, policy: WatchPolicy) -> None:
    selected = ai_policy(db, actor)
    if selected and selected.mode == "byok":
        connection = tenant_get(db, AIConnection, selected.connection_id or "", actor)
        if development_only(connection):
            fail("development_only", "本机开发测试连接不能用于后台持续关注，请使用通用 API", 409)
    db.add(
        WatchGrant(
            organization_id=actor.organization_id,
            policy_id=policy.id,
            policy_version=policy.version,
            actor_id=actor.id,
            identity_binding=identity_binding(db, actor),
            expires_at=policy.expires_at,
        )
    )
    db.flush()


def revoke_grants(db: Session, policy: WatchPolicy) -> None:
    from app.modules.agent.invalidation import clear_runs, read_barrier

    read_barrier(db, policy.organization_id)
    grant_ids = select(WatchGrant.id).where(
        WatchGrant.organization_id == policy.organization_id,
        WatchGrant.policy_id == policy.id,
    )
    run_ids = select(AgentRun.id).where(
        AgentRun.organization_id == policy.organization_id,
        AgentRun.watch_grant_id.in_(grant_ids),
    )
    clear_runs(db, policy.organization_id, run_ids)
    for item in db.scalars(
        select(WatchGrant)
        .where(
            WatchGrant.organization_id == policy.organization_id,
            WatchGrant.policy_id == policy.id,
            WatchGrant.revoked_at.is_(None),
        )
        .with_for_update()
    ):
        item.revoked_at = now()

    for run in db.scalars(
        select(WatchRun)
        .where(
            WatchRun.organization_id == policy.organization_id,
            WatchRun.policy_id == policy.id,
            WatchRun.state.in_(["queued", "running"]),
        )
        .order_by(WatchRun.id)
        .with_for_update()
    ):
        run.state, run.error_code, run.finished_at = "cancelled", "authorization_changed", now()
        run.version += 1


def create(db: Session, actor: Membership, payload: PolicyCreate) -> WatchPolicyOut:
    command_lock(db, actor)
    digest = fingerprint(payload.model_dump(mode="json", exclude={"idempotency_key"}))
    previous = db.scalar(
        select(WatchPolicy).where(
            WatchPolicy.organization_id == actor.organization_id,
            WatchPolicy.actor_id == actor.id,
            WatchPolicy.request_key == str(payload.idempotency_key),
        )
    )
    if previous:
        if previous.request_hash != digest:
            fail("idempotency_conflict", "同一请求不能改变授权内容", 409)
        return view(db, actor, previous)
    validate_fields(db, actor, payload)
    count = (
        db.scalar(
            select(func.count())
            .select_from(WatchPolicy)
            .where(
                WatchPolicy.organization_id == actor.organization_id,
                WatchPolicy.actor_id == actor.id,
                WatchPolicy.state != "revoked",
            )
        )
        or 0
    )
    if count >= 10:
        fail("policy_limit", "最多保留十项未撤销的关注策略", 409)
    data = payload.model_dump(mode="json", include=set(PolicyFields.model_fields))
    data["expires_at"] = payload.expires_at
    policy = WatchPolicy(
        organization_id=actor.organization_id,
        actor_id=actor.id,
        request_key=str(payload.idempotency_key),
        request_hash=digest,
        **data,
    )
    db.add(policy)
    db.flush()
    grant(db, actor, policy)
    audit(db, actor, "watch.granted", policy.id)
    db.commit()
    return view(db, actor, policy)


def change(
    db: Session, actor: Membership, identifier: str, payload: PolicyEdit | PolicyAction
) -> WatchPolicyOut:
    command_lock(db, actor)
    policy = get(db, actor, identifier, lock=True)
    digest = fingerprint({"policy": identifier, **payload.model_dump(mode="json")})
    previous = db.scalar(
        select(WatchCommand).where(
            WatchCommand.organization_id == actor.organization_id,
            WatchCommand.actor_id == actor.id,
            WatchCommand.request_key == str(payload.idempotency_key),
        )
    )
    if previous:
        if previous.request_hash != digest:
            fail("idempotency_conflict", "同一请求不能改变授权内容", 409)
        return view(db, actor, policy)
    if policy.version != payload.expected_version:
        fail("version_conflict", "关注策略已变化，请刷新后核对", 409)
    if policy.state == "revoked":
        fail("policy_revoked", "已撤销的策略不能重新启用，请重新授权", 409)
    action = "edit" if isinstance(payload, PolicyEdit) else payload.action
    if isinstance(payload, PolicyEdit):
        validate_fields(db, actor, payload)
        for key, value in payload.model_dump(include=set(PolicyFields.model_fields)).items():
            setattr(
                policy,
                key,
                str(value) if key in {"department_id", "initiative_id"} and value else value,
            )
    elif action == "resume" and utc(policy.expires_at) <= now():
        fail("grant_expired", "授权已到期，请核对目标并更新授权期限", 409)
    revoke_grants(db, policy)
    policy.state = "paused" if action == "pause" else "revoked" if action == "revoke" else "active"
    policy.version += 1
    policy.next_due_at = now()
    if policy.state == "active":
        grant(db, actor, policy)
    db.add(
        WatchCommand(
            organization_id=actor.organization_id,
            policy_id=policy.id,
            actor_id=actor.id,
            action=action,
            request_key=str(payload.idempotency_key),
            request_hash=digest,
        )
    )
    audit(db, actor, "watch." + action, policy.id)
    db.commit()
    return view(db, actor, policy)
