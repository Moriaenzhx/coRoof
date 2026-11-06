from fastapi import APIRouter, Request
from sqlalchemy import select

from app.core.access import get_work, page_rows, tenant_get, work_scope
from app.core.auth import Actor, Db, token_hash
from app.core.schemas import Page
from app.infrastructure.models import EvidenceSnapshot, Signal, WorkItem
from app.modules.intelligence.analysis import ask
from app.modules.intelligence.schemas import AnswerOut, AskInput, EvidenceOut, SignalOut
from app.modules.intelligence.signals import evidence_out, refresh_scope, signal_out
from app.modules.organizations.api import Limit, Offset

router = APIRouter(tags=["intelligence"])


@router.get("/signals", response_model=Page[SignalOut])
def list_signals(db: Db, actor: Actor, offset: Offset = 0, limit: Limit = 50) -> Page[SignalOut]:
    works, _ = refresh_scope(db, actor)
    db.commit()
    by_id = {w.id: w for w in works}
    rows, total = page_rows(
        db,
        select(Signal)
        .where(
            Signal.organization_id == actor.organization_id,
            Signal.state == "active",
            Signal.work_item_id.in_(by_id),
            Signal.work_item_id.in_(work_scope(actor).with_only_columns(WorkItem.id)),
        )
        .order_by(Signal.detected_at.desc(), Signal.id),
        offset,
        limit,
    )
    return Page(
        items=[signal_out(s, by_id[s.work_item_id]) for s in rows],
        total=total,
        offset=offset,
        limit=limit,
    )


@router.get("/signals/{signal_id}", response_model=SignalOut)
def read_signal(signal_id: str, db: Db, actor: Actor) -> SignalOut:
    signal = tenant_get(db, Signal, signal_id, actor)
    work = get_work(db, actor, signal.work_item_id)
    return signal_out(signal, work)


@router.get("/evidence/{evidence_id}", response_model=EvidenceOut)
def read_evidence(evidence_id: str, db: Db, actor: Actor) -> EvidenceOut:
    evidence = tenant_get(db, EvidenceSnapshot, evidence_id, actor)
    return evidence_out(db, actor, evidence)


@router.post("/ai/ask", response_model=AnswerOut)
def answer(payload: AskInput, db: Db, actor: Actor, request: Request) -> AnswerOut:
    return ask(
        db, actor, payload, session_hash=token_hash(request.cookies.get("coroof_session", ""))
    )
