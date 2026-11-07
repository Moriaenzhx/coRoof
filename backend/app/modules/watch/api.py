from fastapi import APIRouter
from sqlalchemy import select

from app.core.auth import Actor, Db
from app.infrastructure.models import utc
from app.modules.watch import attention, service
from app.modules.watch.models import AttentionItem, WatchPolicy, WatchRun
from app.modules.watch.schemas import (
    AttentionAction,
    AttentionOut,
    PolicyAction,
    PolicyCreate,
    PolicyEdit,
    WatchPolicyOut,
    WatchRunOut,
)

router = APIRouter(prefix="/watch", tags=["continuous-agent"])


@router.get("/policies", response_model=list[WatchPolicyOut])
def policies(db: Db, actor: Actor) -> list[WatchPolicyOut]:
    service.owner(db, actor)
    return [
        service.view(db, actor, policy)
        for policy in db.scalars(
            select(WatchPolicy)
            .where(
                WatchPolicy.organization_id == actor.organization_id,
                WatchPolicy.actor_id == actor.id,
            )
            .order_by(WatchPolicy.created_at.desc(), WatchPolicy.id)
            .limit(100)
        )
    ]


@router.post("/policies", response_model=WatchPolicyOut, status_code=201)
def create(payload: PolicyCreate, db: Db, actor: Actor) -> WatchPolicyOut:
    return service.create(db, actor, payload)


@router.post("/policies/{policy_id}/edit", response_model=WatchPolicyOut)
def edit(policy_id: str, payload: PolicyEdit, db: Db, actor: Actor) -> WatchPolicyOut:
    return service.change(db, actor, policy_id, payload)


@router.post("/policies/{policy_id}/actions", response_model=WatchPolicyOut)
def action(policy_id: str, payload: PolicyAction, db: Db, actor: Actor) -> WatchPolicyOut:
    return service.change(db, actor, policy_id, payload)


@router.get("/attention", response_model=list[AttentionOut])
def inbox(db: Db, actor: Actor, include_closed: bool = False) -> list[AttentionOut]:
    service.command_lock(db, actor)
    owned = select(WatchPolicy.id).where(
        WatchPolicy.organization_id == actor.organization_id, WatchPolicy.actor_id == actor.id
    )
    query = select(AttentionItem).where(
        AttentionItem.organization_id == actor.organization_id, AttentionItem.policy_id.in_(owned)
    )
    if not include_closed:
        query = query.where(AttentionItem.state.in_(["open", "snoozed"]))
    rows = list(
        db.scalars(query.order_by(AttentionItem.changed_at.desc(), AttentionItem.id).limit(100))
    )
    result = [value for row in rows if (value := attention.view(db, actor, row)) is not None]
    db.commit()
    return result


@router.post("/attention/{item_id}/actions", response_model=AttentionOut)
def review(item_id: str, payload: AttentionAction, db: Db, actor: Actor) -> AttentionOut:
    return attention.review(db, actor, item_id, payload)


@router.get("/policies/{policy_id}/runs", response_model=list[WatchRunOut])
def runs(policy_id: str, db: Db, actor: Actor) -> list[WatchRunOut]:
    policy = service.get(db, actor, policy_id)
    effective = service.view(db, actor, policy).effective_state == "active"
    result = []
    for row in db.scalars(
        select(WatchRun)
        .where(WatchRun.organization_id == actor.organization_id, WatchRun.policy_id == policy.id)
        .order_by(WatchRun.created_at.desc(), WatchRun.id)
        .limit(20)
    ):
        data = {field: getattr(row, field) for field in WatchRunOut.model_fields}
        data["created_at"] = utc(row.created_at)
        data["finished_at"] = utc(row.finished_at) if row.finished_at else None
        # Execution history is operational metadata; content is exposed only via checked items.
        data["agent_run_id"] = None
        if not effective or row.policy_version != policy.version:
            data["work_item_id"] = None
        result.append(WatchRunOut.model_validate(data))
    return result
