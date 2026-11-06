from uuid import uuid4

from fastapi import APIRouter
from pydantic import ValidationError
from sqlalchemy import func, select

from app.core.access import audit, check_assignment, get_work, page_rows, require_owner, tenant_get
from app.core.auth import Actor, Db
from app.core.errors import fail
from app.core.schemas import Page
from app.infrastructure.models import Department, utc
from app.modules.connectors import service
from app.modules.connectors.models import Connector, SourceLink, SourceMember, SourceRecord, SyncRun
from app.modules.connectors.providers import SourceFailure, endpoint
from app.modules.connectors.schemas import (
    ConnectorAction,
    ConnectorInput,
    ConnectorOut,
    ConnectorVersion,
    MappingInput,
    MemberMapOut,
    RotateInput,
    SourceDetail,
    SourceOut,
    SyncInput,
    SyncOut,
)
from app.modules.connectors.secrets import seal
from app.modules.organizations.api import Limit, Offset

router = APIRouter(tags=["connectors"])


def view(db: Db, row: Connector) -> ConnectorOut:
    counts = {
        state: count
        for state, count in db.execute(
            select(SourceLink.state, func.count())
            .where(
                SourceLink.organization_id == row.organization_id, SourceLink.connector_id == row.id
            )
            .group_by(SourceLink.state)
        ).all()
    }
    return ConnectorOut(
        id=row.id,
        name=row.name,
        kind=row.kind,
        base_url=row.base_url,
        project_key=row.project_key,
        item_type=row.item_type,
        department_id=row.department_id,
        owner_field=row.owner_field,
        status_map=row.status_map,
        key_hint="••••" + row.key_suffix,
        state=row.state,
        version=row.version,
        tested_at=utc(row.tested_at) if row.tested_at else None,
        synced_at=utc(row.synced_at) if row.synced_at else None,
        last_error=row.last_error,
        source_count=sum(counts.values()),
        pending_count=counts.get("pending", 0),
    )


def locked(db: Db, actor: Actor, identifier: str, version: int) -> Connector:
    row = tenant_get(db, Connector, identifier, actor, lock=True)
    service.authorize(db, actor)
    if row.version != version:
        fail("version_conflict", "连接已变化，请刷新后重试", 409)
    return row


@router.get("/connectors", response_model=Page[ConnectorOut])
def connections(db: Db, actor: Actor, offset: Offset = 0, limit: Limit = 50) -> Page[ConnectorOut]:
    require_owner(actor)
    rows, total = page_rows(
        db,
        select(Connector)
        .where(Connector.organization_id == actor.organization_id)
        .order_by(Connector.created_at.desc(), Connector.id),
        offset,
        limit,
    )
    return Page(items=[view(db, row) for row in rows], total=total, offset=offset, limit=limit)


@router.post("/connectors", response_model=ConnectorOut, status_code=201)
def create(payload: ConnectorInput, db: Db, actor: Actor) -> ConnectorOut:
    service.authorize(db, actor)
    tenant_get(db, Department, str(payload.department_id), actor)
    identifier = str(uuid4())
    try:
        base = endpoint(payload.base_url, payload.kind)
        credential = seal(payload.credentials, actor.organization_id, identifier)
    except SourceFailure as exc:
        fail(exc.code, "端点未获部署允许或凭据加密未就绪，请核对服务器配置", 409)
    row = Connector(
        id=identifier,
        organization_id=actor.organization_id,
        name=payload.name,
        kind=payload.kind,
        base_url=base,
        project_key=payload.project_key,
        item_type=payload.item_type,
        department_id=str(payload.department_id),
        owner_field=payload.owner_field,
        status_map=payload.status_map,
        credential=credential,
        key_suffix=(
            payload.credentials.token.get_secret_value()
            if payload.kind == "gitlab"
            else payload.credentials.plugin_secret.get_secret_value()
        )[-4:],
    )
    db.add(row)
    db.flush()
    audit(db, actor, "connector.created", row.id)
    db.commit()
    return view(db, row)


@router.post("/connectors/{connector_id}/state", response_model=ConnectorOut)
def change_state(connector_id: str, payload: ConnectorAction, db: Db, actor: Actor) -> ConnectorOut:
    row = locked(db, actor, connector_id, payload.expected_version)
    if payload.action == "activate":
        if row.state not in {"tested", "paused"} or not row.credential or not row.tested_at:
            fail("connection_not_tested", "请先测试连接", 409)
        row.state = "active"
    else:
        if payload.action == "pause" and row.state not in {"active", "paused"}:
            fail("connection_inactive", "仅已启用的连接可暂停；失效授权需重新测试", 409)
        row.state = "paused" if payload.action == "pause" and row.credential else "revoked"
        if payload.action == "revoke":
            row.state, row.credential = "revoked", None
        for run in db.scalars(
            select(SyncRun)
            .where(
                SyncRun.organization_id == actor.organization_id,
                SyncRun.connector_id == row.id,
                SyncRun.state.in_(service.ACTIVE),
            )
            .with_for_update()
        ):
            service.finish(run, "cancelled", "configuration_changed")
    audit(db, actor, "connector." + payload.action, row.id)
    db.commit()
    return view(db, row)


@router.post("/connectors/{connector_id}/credentials", response_model=ConnectorOut)
def rotate(connector_id: str, payload: RotateInput, db: Db, actor: Actor) -> ConnectorOut:
    row = locked(db, actor, connector_id, payload.expected_version)
    # Reuse the creation schema to validate the provider's complete credential shape.
    try:
        valid = ConnectorInput(
            name=row.name,
            kind=row.kind,
            base_url=row.base_url,
            project_key=row.project_key,
            item_type=row.item_type,
            department_id=row.department_id,
            credentials=payload.credentials,
            share_with_department=True,
        )
        row.credential = seal(valid.credentials, actor.organization_id, row.id)
    except ValidationError:
        fail("invalid_credentials", "请完整填写该平台所需的凭据", 422)
    except SourceFailure as exc:
        fail(exc.code, "凭据加密未就绪", 409)
    row.key_suffix = (
        valid.credentials.token.get_secret_value()
        if row.kind == "gitlab"
        else valid.credentials.plugin_secret.get_secret_value()
    )[-4:]
    row.state, row.tested_at, row.last_error = "saved", None, None
    audit(db, actor, "connector.credentials_rotated", row.id)
    db.commit()
    return view(db, row)


@router.put("/connectors/{connector_id}/mapping", response_model=ConnectorOut)
def mapping(connector_id: str, payload: MappingInput, db: Db, actor: Actor) -> ConnectorOut:
    row = locked(db, actor, connector_id, payload.expected_version)
    if row.state != "active":
        fail("connection_inactive", "请先测试并启用连接", 409)
    for external, membership in payload.members.items():
        target = str(membership) if membership else None
        check_assignment(db, actor, target, row.department_id)
        member = db.scalar(
            select(SourceMember).where(
                SourceMember.organization_id == actor.organization_id,
                SourceMember.connector_id == row.id,
                SourceMember.external_id == external,
            )
        )
        if member is None:
            fail("unknown_external_member", "请先同步并核对来源中的成员标识", 409)
        assert member is not None
        member.membership_id = target
    row.status_map = dict(payload.status_map)
    if row.kind == "feishu_project" and "owner_field" in payload.model_fields_set:
        row.owner_field = payload.owner_field
    row.version += 1
    # Do not expose an earlier projection under newly edited mapping semantics.
    for link in db.scalars(
        select(SourceLink).where(
            SourceLink.organization_id == actor.organization_id,
            SourceLink.connector_id == row.id,
            SourceLink.state == "linked",
        )
    ):
        service.withhold(db, actor, link, "mapping_changed", "pending")
    audit(db, actor, "connector.mapping_changed", row.id)
    db.commit()
    return view(db, row)


@router.post("/connectors/{connector_id}/syncs", response_model=SyncOut, status_code=202)
def start(connector_id: str, payload: SyncInput, db: Db, actor: Actor) -> SyncOut:
    require_owner(actor)
    return SyncOut.model_validate(service.create_run(db, actor, connector_id, payload))


@router.get("/connectors/{connector_id}/syncs", response_model=Page[SyncOut])
def runs(
    connector_id: str, db: Db, actor: Actor, offset: Offset = 0, limit: Limit = 50
) -> Page[SyncOut]:
    require_owner(actor)
    tenant_get(db, Connector, connector_id, actor)
    rows, total = page_rows(
        db,
        select(SyncRun)
        .where(
            SyncRun.organization_id == actor.organization_id, SyncRun.connector_id == connector_id
        )
        .order_by(SyncRun.created_at.desc(), SyncRun.id),
        offset,
        limit,
    )
    return Page(
        items=[SyncOut.model_validate(row) for row in rows], total=total, offset=offset, limit=limit
    )


@router.post("/connectors/{connector_id}/syncs/{run_id}/cancel", response_model=SyncOut)
def cancel(
    connector_id: str, run_id: str, payload: ConnectorVersion, db: Db, actor: Actor
) -> SyncOut:
    tenant_get(db, Connector, connector_id, actor, lock=True)
    service.authorize(db, actor)
    run = tenant_get(db, SyncRun, run_id, actor, lock=True)
    if run.connector_id != connector_id:
        fail("not_found", "未找到此同步任务", 404)
    if run.version != payload.expected_version:
        fail("version_conflict", "任务已变化，请刷新", 409)
    if run.state in service.ACTIVE:
        service.finish(run, "cancelled", "cancelled")
        audit(db, actor, "connector.sync_cancelled", run.id)
        db.commit()
    return SyncOut.model_validate(run)


def active_source(db: Db, actor: Actor, connector_id: str) -> Connector:
    require_owner(actor)
    row = tenant_get(db, Connector, connector_id, actor)
    if row.state != "active":
        fail("connection_inactive", "来源未启用或已失去授权，缓存内容不再展示", 409)
    return row


@router.get("/connectors/{connector_id}/sources", response_model=Page[SourceOut])
def sources(
    connector_id: str, db: Db, actor: Actor, offset: Offset = 0, limit: Limit = 50
) -> Page[SourceOut]:
    active_source(db, actor, connector_id)
    rows, total = page_rows(
        db,
        select(SourceLink)
        .where(
            SourceLink.organization_id == actor.organization_id,
            SourceLink.connector_id == connector_id,
            SourceLink.state != "withdrawn",
        )
        .order_by(SourceLink.external_id),
        offset,
        limit,
    )
    result = []
    for link in rows:
        record = tenant_get(db, SourceRecord, link.record_id, actor)
        result.append(
            SourceOut(
                id=link.id,
                external_id=link.external_id,
                title=record.normalized["title"],
                external_state=record.normalized["state"],
                assignees=record.normalized["assignees"] or [],
                work_item_id=link.work_item_id,
                state=link.state,
                mapping_issue=link.mapping_issue,
                source_at=utc(record.source_at),
                checked_at=utc(link.checked_at),
            )
        )
    return Page(items=result, total=total, offset=offset, limit=limit)


@router.get("/connectors/{connector_id}/members", response_model=Page[MemberMapOut])
def members(
    connector_id: str, db: Db, actor: Actor, offset: Offset = 0, limit: Limit = 50
) -> Page[MemberMapOut]:
    active_source(db, actor, connector_id)
    rows, total = page_rows(
        db,
        select(SourceMember)
        .where(
            SourceMember.organization_id == actor.organization_id,
            SourceMember.connector_id == connector_id,
        )
        .order_by(SourceMember.external_id),
        offset,
        limit,
    )
    return Page(
        items=[MemberMapOut.model_validate(row) for row in rows],
        total=total,
        offset=offset,
        limit=limit,
    )


@router.get("/work-items/{work_id}/source", response_model=SourceDetail)
def provenance(work_id: str, db: Db, actor: Actor) -> SourceDetail:
    get_work(db, actor, work_id)
    link = db.scalar(
        select(SourceLink).where(
            SourceLink.organization_id == actor.organization_id,
            SourceLink.work_item_id == work_id,
            SourceLink.state == "linked",
        )
    )
    if link is None:
        fail("not_found", "此事项没有外部来源", 404)
    assert link is not None
    connector = tenant_get(db, Connector, link.connector_id, actor)
    record = tenant_get(db, SourceRecord, link.record_id, actor)
    return SourceDetail(
        connector_name=connector.name,
        kind=connector.kind,
        external_id=link.external_id,
        source_url=record.normalized.get("source_url"),
        source_at=utc(record.source_at),
        observed_at=utc(link.checked_at),
        last_error=connector.last_error,
    )
