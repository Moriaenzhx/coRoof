"""Code-owned, tenant-authorized read capabilities. No arbitrary tool dispatch."""

import hashlib
import json
from typing import Any

from sqlalchemy import Select, func, select
from sqlalchemy.orm import Session

from app.core.access import get_work, owner, work_scope
from app.core.errors import fail
from app.infrastructure.models import AgentRun, Membership, WorkEvent, WorkItem, now
from app.modules.agent.schemas import Capability, Proposal
from app.modules.intelligence.signals import (
    categories,
    evidence_out,
    refresh_work,
    signal_out,
    snapshot,
)
from app.modules.knowledge.access import scope as knowledge_scope
from app.modules.knowledge.index import inventory, search
from app.modules.knowledge.models import KnowledgeDocument, KnowledgeUse
from app.modules.memory import retrieval as memory_retrieval
from app.modules.memory import service as memory_service
from app.modules.memory.models import MemoryEntry

CATALOG: dict[Capability, str] = {
    "experience.reference": "检索已确认且来源有效的经验，须核对适用条件。",
    "preference.read": "读取老板已确认的私人偏好；规划前先查。",
    "company.overview": "读取授权工作概况与有限依据。",
    "attention.explain": "读取支持、逾期、受阻或陈旧事项及依据。",
    "work.investigate": "读取指定授权事项事实与近期事件，须给 work_item_id。",
    "coverage.explain": "读取信息覆盖和缺口；不判断健康。",
    "knowledge.search": "按问题检索授权已发布文档；制度不是执行事实。",
    "knowledge.list": "盘点当前有哪些知识、知识库或文档，列出有权查看的已发布目录。",
}


def scoped(run: AgentRun, actor: Membership) -> Select[tuple[WorkItem]]:
    stmt = work_scope(actor)
    return stmt.where(WorkItem.id == run.work_item_id) if run.work_item_id else stmt


def scope_hash(
    db: Session, actor: Membership, work_item_id: str | None, *, include_events: bool = False
) -> str:
    # Includes the whole authorized scope, so an old aggregate cannot survive a move
    # out of scope even when the moved work was outside the bounded evidence sample.
    digest = hashlib.sha256(json.dumps([sorted(actor.roles), actor.department_id]).encode())
    stmt = work_scope(actor).order_by(WorkItem.id)
    if work_item_id:
        get_work(db, actor, work_item_id)
        stmt = stmt.where(WorkItem.id == work_item_id)
    clock = now()
    for work in db.scalars(stmt.execution_options(yield_per=100, populate_existing=True)):
        digest.update(json.dumps([work.id, work.version, categories(work, clock)]).encode())
    if include_events and work_item_id:
        # Confirmed decisions/results append events without changing WorkItem.version.
        # Background planning must notice them and reject conclusions from an older history.
        event_ids = list(
            db.scalars(
                select(WorkEvent.id)
                .where(
                    WorkEvent.organization_id == actor.organization_id,
                    WorkEvent.work_item_id == work_item_id,
                )
                .order_by(WorkEvent.recorded_at.desc(), WorkEvent.id.desc())
                .limit(12)
            )
        )
        digest.update(json.dumps(event_ids).encode())
    if not work_item_id:
        for document in db.scalars(
            knowledge_scope(actor, published=True)
            .order_by(KnowledgeDocument.id)
            .execution_options(yield_per=100, populate_existing=True)
        ):
            digest.update(json.dumps([document.id, document.access_version]).encode())
    if owner(actor):
        for entry in db.scalars(
            memory_service.scope(actor, effective=True, work_item_id=work_item_id).order_by(
                MemoryEntry.id
            )
        ):
            digest.update(json.dumps([entry.id, entry.version]).encode())
    return digest.hexdigest()


def execute(db: Session, actor: Membership, run: AgentRun, proposal: Proposal) -> dict[str, Any]:
    capability = proposal.capability
    if capability not in CATALOG:
        fail("unsupported_capability", "此能力尚未接入", 422)
    if capability in {"experience.reference", "preference.read"}:
        result_memory = memory_retrieval.search(
            db,
            actor,
            run.question,
            kind="preference" if capability == "preference.read" else "experience",
            work_item_id=run.work_item_id,
            limit=4 if capability == "preference.read" else 2,
        )
        for item in result_memory.items:
            memory_service.bind(db, memory_service.get(db, actor, item.id), run)
        return {
            "capability": capability,
            "scope": "confirmed_memory",
            "authorized_work_count": 0,
            "considered_work_count": 0,
            "evidence": [],
            "signals": [],
            "timeline": [],
            "memories": [item.model_dump(mode="json") for item in result_memory.items],
            "notice": result_memory.notice,
        }
    if capability in {"knowledge.search", "knowledge.list"}:
        if run.work_item_id:
            fail("scope_forbidden", "事项专属任务尚未绑定文档范围，请从知识库发起查询", 403)
        query = run.question
        if capability == "knowledge.search" and run.parent_run_id:
            # Resolve a short follow-up against titles from only the authorized
            # immediate parent. Search still filters current published versions
            # and ACLs; these titles do not grant document access or become facts.
            from app.modules.agent.runtime import knowledge_content_followup, parent_turn

            previous = parent_turn(
                db, actor, run.parent_run_id, run.session_hash, run.work_item_id, run.id
            )
            if knowledge_content_followup(run.question, previous):
                titles = " ".join(item["title"] for item in previous["knowledge_documents"][:3])
                query = (run.question[:1400] + " " + titles[:600]).strip()
        result = search(db, actor, query, limit=3) if capability == "knowledge.search" else None
        listing = inventory(db, actor) if result is None or not result.items else None
        identifiers = {item.document_id for item in result.items} if result else set()
        if listing:
            identifiers.update(item.document_id for item in listing.items)
        for identifier in sorted(identifiers):
            if not db.scalar(
                select(KnowledgeUse.id).where(
                    KnowledgeUse.organization_id == actor.organization_id,
                    KnowledgeUse.document_id == identifier,
                    KnowledgeUse.run_id == run.id,
                )
            ):
                db.add(
                    KnowledgeUse(
                        organization_id=actor.organization_id, document_id=identifier, run_id=run.id
                    )
                )
        return {
            "capability": capability,
            "scope": "authorized_documents",
            "authorized_work_count": 0,
            "considered_work_count": 0,
            "evidence": [],
            "signals": [],
            "timeline": [],
            "documents": [item.model_dump(mode="json") for item in result.items] if result else [],
            "authorized_documents": result.authorized_documents
            if result
            else listing.total
            if listing
            else 0,
            "notice": (
                result.notice + " 本次最多返回 3 个相关片段，不代表已覆盖全部文档。"
                if result
                else listing.notice
                if listing
                else ""
            ),
            "knowledge_inventory": listing.model_dump(mode="json") if listing else None,
        }
    total = db.scalar(select(func.count()).select_from(scoped(run, actor).subquery())) or 0
    works: list[WorkItem] = []
    if capability == "work.investigate":
        if run.work_item_id and run.work_item_id != proposal.work_item_id:
            fail("scope_forbidden", "此任务仅能读取指定事项", 403)
        works = [get_work(db, actor, proposal.work_item_id or "", lock=True)]
    elif capability == "company.overview":
        works = list(
            db.scalars(
                scoped(run, actor)
                .order_by(WorkItem.updated_at.desc(), WorkItem.id)
                .limit(8)
                .with_for_update()
            )
        )
    elif capability == "attention.explain":
        # Check rules against current facts. Bounded returned evidence is separate
        # from coverage; missing records never imply healthy operation.
        candidates = [
            w.id
            for w in db.scalars(
                scoped(run, actor).order_by(WorkItem.updated_at.desc(), WorkItem.id)
            )
            if categories(w, now())
        ][:8]
        works = [get_work(db, actor, wid, lock=True) for wid in sorted(candidates)]
    signals = [signal_out(s, w).model_dump(mode="json") for w in works for s in refresh_work(db, w)]
    evidence = [evidence_out(db, actor, snapshot(db, w)).model_dump(mode="json") for w in works]
    timeline: list[dict[str, Any]] = []
    if works and (capability == "work.investigate" or run.watch_grant_id):
        for event in db.scalars(
            select(WorkEvent)
            .where(
                WorkEvent.organization_id == actor.organization_id,
                WorkEvent.work_item_id == works[0].id,
            )
            .order_by(WorkEvent.recorded_at.desc(), WorkEvent.id.desc())
            .limit(12)
        ):
            timeline.append(
                {
                    "event_id": event.id,
                    "event_type": event.event_type,
                    "recorded_at": event.recorded_at.isoformat(),
                    "summary": str(
                        event.event_payload.get("confirmed", {}).get("summary")
                        or event.event_payload.get("title")
                        or "已记录工作事件"
                    )[:1000],
                }
            )
    return {
        "capability": capability,
        "scope": "organization" if owner(actor) and not run.work_item_id else "authorized_work",
        "authorized_work_count": total,
        "considered_work_count": len(works),
        "evidence": evidence,
        "signals": signals,
        "timeline": timeline,
        "notice": (
            "仅含当前获授权且已记录的工作；外部来源可能部分同步，截止日期与支持需求未知。尚未接入的来源仍未知。"
            "数量不代表工时、绩效或健康。"
        ),
    }
