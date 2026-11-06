from sqlalchemy import func, literal_column, select, text
from sqlalchemy.orm import Session

from app.core.access import require_owner
from app.infrastructure.models import Membership, utc
from app.modules.knowledge.index import keywords
from app.modules.memory import service
from app.modules.memory.models import MemoryEntry
from app.modules.memory.schemas import MemoryCitation, MemoryKind, MemorySearchOut


def citation(row: MemoryEntry) -> MemoryCitation:
    assert row.confirmed_at is not None
    excerpt = (
        "本人确认的偏好：" + row.content[:260] + "\n适用条件：" + row.applicability[:100]
        if row.kind == "preference"
        else "经确认的经验解释："
        + row.content[:200]
        + "\n适用条件："
        + row.applicability[:100]
        + "\n所据实际结果原文："
        + row.source_quote[:250]
    )
    return MemoryCitation(
        id=row.id,
        kind=row.kind,
        title=row.title,
        excerpt=excerpt,
        applicability=row.applicability,
        version=row.version,
        source_at=utc(row.confirmed_at),
        decision_id=row.decision_id,
        outcome_id=row.outcome_id,
    )


def search(
    db: Session,
    actor: Membership,
    query: str,
    *,
    kind: MemoryKind = "experience",
    work_item_id: str | None = None,
    offset: int = 0,
    limit: int = 10,
) -> MemorySearchOut:
    require_owner(actor)
    stmt = service.scope(actor, effective=True, work_item_id=work_item_id).where(
        MemoryEntry.kind == kind
    )
    if kind == "experience":
        words = keywords(query)
        if not words:
            return MemorySearchOut(items=[], total=0, offset=offset, limit=limit)
        if db.get_bind().dialect.name == "postgresql":
            vector = func.to_tsvector(
                literal_column("'simple'::regconfig"), MemoryEntry.search_text
            )
            tsquery = func.websearch_to_tsquery(
                literal_column("'simple'::regconfig"), " OR ".join(words)
            )
            stmt = stmt.where(vector.op("@@")(tsquery)).order_by(
                func.ts_rank_cd(vector, tsquery).desc()
            )
        else:
            hits = text("SELECT entry_id FROM memory_fts WHERE memory_fts MATCH :match").bindparams(
                match=" OR ".join('"' + word + '"' for word in words)
            )
            stmt = stmt.where(MemoryEntry.id.in_(hits))
    total = db.scalar(select(func.count()).select_from(stmt.order_by(None).subquery())) or 0
    rows = list(
        db.scalars(
            stmt.order_by(MemoryEntry.updated_at.desc(), MemoryEntry.id).offset(offset).limit(limit)
        )
    )
    return MemorySearchOut(
        items=[citation(row) for row in rows], total=total, offset=offset, limit=limit
    )
