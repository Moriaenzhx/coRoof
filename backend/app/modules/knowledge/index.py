"""Framework splitting and database-native search, after tenant and ACL filtering."""

import logging
import re
from typing import Literal

import jieba
import jieba.analyse
from langchain_text_splitters import RecursiveCharacterTextSplitter
from sqlalchemy import func, literal_column, select, text
from sqlalchemy.orm import Session, load_only

from app.infrastructure.models import Membership, utc
from app.modules.knowledge.access import scope
from app.modules.knowledge.models import KnowledgeChunk as Chunk
from app.modules.knowledge.models import KnowledgeDocument as Document
from app.modules.knowledge.models import KnowledgeRevision as Revision
from app.modules.knowledge.retrieval import RERANK_LIMIT, rerank
from app.modules.knowledge.schemas import (
    Citation,
    KnowledgeInventoryItem,
    KnowledgeInventoryOut,
    SearchOut,
    Visibility,
)

jieba.setLogLevel(logging.WARNING)
SPLITTER = RecursiveCharacterTextSplitter(
    chunk_size=600,
    chunk_overlap=60,
    add_start_index=True,
    separators=["\n\n", "\n", "。", "；", "，", " ", ""],
)


def tokens(value: str) -> str:
    return " ".join(word.lower() for word in jieba.cut_for_search(value) if re.search(r"\w", word))


def keywords(query: str) -> list[str]:
    words = jieba.analyse.extract_tags(query, topK=20)
    return list(dict.fromkeys(w.lower() for w in words if re.fullmatch(r"\w+", w)))


def publish_index(db: Session, row: Revision) -> None:
    for ordinal, part in enumerate(SPLITTER.create_documents([row.content or ""])):
        start = int(part.metadata["start_index"])
        db.add(
            Chunk(
                organization_id=row.organization_id,
                document_id=row.document_id,
                revision_id=row.id,
                ordinal=ordinal,
                content=part.page_content,
                start_offset=start,
                end_offset=start + len(part.page_content),
                search_text=tokens(row.title + " " + part.page_content),
            )
        )
    db.flush()


def citation(chunk: Chunk, revision: Revision) -> Citation:
    assert revision.published_at is not None
    return Citation(
        id=chunk.id,
        document_id=revision.document_id,
        revision_id=revision.id,
        revision_number=revision.number,
        title=revision.title,
        excerpt=chunk.content,
        start_offset=chunk.start_offset,
        end_offset=chunk.end_offset,
        source_at=utc(revision.published_at),
        file_name=revision.file_name,
    )


def inventory(db: Session, actor: Membership) -> KnowledgeInventoryOut:
    """List published metadata after the same ACL as search; never expose draft titles."""
    authorized = scope(actor, published=True).with_only_columns(Document.id)
    total = db.scalar(select(func.count()).select_from(authorized.subquery())) or 0
    rows = db.scalars(
        select(Revision)
        .join(
            Document,
            (Document.organization_id == Revision.organization_id)
            & (Document.id == Revision.document_id)
            & (Document.published_id == Revision.id),
        )
        .where(Revision.organization_id == actor.organization_id, Document.id.in_(authorized))
        .order_by(Revision.published_at.desc(), Document.id)
        .limit(20)
    )
    items = []
    for revision in rows:
        assert revision.published_at is not None
        items.append(
            KnowledgeInventoryItem(
                document_id=revision.document_id,
                revision_id=revision.id,
                revision_number=revision.number,
                title=revision.title,
                source_at=utc(revision.published_at),
            )
        )
    return KnowledgeInventoryOut(
        items=items,
        total=total,
        limit=20,
        truncated=total > len(items),
        notice="仅列出当前权限内的已发布文档，按发布时间排序，最多展示 20 篇；"
        "目录不是正文解读，也不代表文档要求已经执行。",
    )


def search(
    db: Session,
    actor: Membership,
    query: str,
    offset: int = 0,
    limit: int = 10,
    *,
    ranking: Literal["database", "bm25"] = "bm25",
    visibility: Visibility | None = None,
) -> SearchOut:
    authorized_scope = scope(actor, published=True)
    if visibility is not None:
        authorized_scope = authorized_scope.where(Document.visibility == visibility)
    authorized = authorized_scope.with_only_columns(Document.published_id)
    count = db.scalar(select(func.count()).select_from(authorized.subquery())) or 0
    words = keywords(query)
    if not words:
        return SearchOut(items=[], total=0, offset=offset, limit=limit, authorized_documents=count)
    stmt = (
        select(Chunk, Revision)
        .options(
            load_only(
                Revision.id,
                Revision.document_id,
                Revision.number,
                Revision.title,
                Revision.published_at,
                Revision.file_name,
                raiseload=True,
            )
        )
        .join(
            Revision,
            (Revision.organization_id == Chunk.organization_id)
            & (Revision.id == Chunk.revision_id),
        )
        .where(Chunk.organization_id == actor.organization_id, Chunk.revision_id.in_(authorized))
    )
    if db.get_bind().dialect.name == "postgresql":
        vector = func.to_tsvector(literal_column("'simple'::regconfig"), Chunk.search_text)
        tsquery = func.websearch_to_tsquery(
            literal_column("'simple'::regconfig"), " OR ".join(words)
        )
        stmt = stmt.where(vector.op("@@")(tsquery))
        rank = func.ts_rank_cd(vector, tsquery).desc()
    else:
        # Query terms are quoted and parameterized; no raw FTS operators from documents/users.
        match = " OR ".join('"' + word + '"' for word in words)
        hits = text(
            "SELECT chunk_id FROM knowledge_fts WHERE knowledge_fts MATCH :match"
        ).bindparams(match=match)
        stmt = stmt.where(Chunk.id.in_(hits))
        rank = Chunk.ordinal.asc()
    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    ordered = stmt.order_by(rank, Chunk.id)
    if ranking == "database":
        rows = [
            (chunk, revision) for chunk, revision in db.execute(ordered.offset(offset).limit(limit))
        ]
    else:
        # The head is independent of offset/limit. Reranking a different candidate set
        # on each page would duplicate or lose results. The untouched tail remains
        # pageable and total still counts every authorized matching chunk.
        rows = []
        if offset < RERANK_LIMIT:
            candidates = [
                (chunk, revision) for chunk, revision in db.execute(ordered.limit(RERANK_LIMIT))
            ]
            rows = rerank(words, candidates)[offset : offset + limit]
        tail_offset = max(offset, RERANK_LIMIT)
        tail_limit = offset + limit - tail_offset
        if tail_limit > 0:
            rows.extend(
                (chunk, revision)
                for chunk, revision in db.execute(ordered.offset(tail_offset).limit(tail_limit))
            )
    result = SearchOut(
        items=[citation(chunk, revision) for chunk, revision in rows],
        total=total,
        offset=offset,
        limit=limit,
        authorized_documents=count,
    )
    if ranking == "bm25" and total > RERANK_LIMIT:
        result.notice += "匹配较多，前 500 个片段按词项相关性重排，其余结果保留原顺序。"
    return result
