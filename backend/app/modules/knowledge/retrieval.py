"""Bounded lexical reranking; callers supply already-authorized published chunks only."""

from collections.abc import Sequence

from rank_bm25 import BM25Plus

from app.modules.knowledge.models import KnowledgeChunk, KnowledgeRevision

RERANK_LIMIT = 500
Candidate = tuple[KnowledgeChunk, KnowledgeRevision]


def rerank(words: list[str], candidates: Sequence[Candidate]) -> list[Candidate]:
    if len(candidates) < 2 or not words:
        return list(candidates)
    # Use the same persisted tokens as the SQL candidate query. No global corpus/cache:
    # even corpus statistics must not incorporate another user's private documents.
    corpus = [chunk.search_text.split() for chunk, _ in candidates]
    # BM25+ uses a positive IDF for common terms, including a tiny authorized corpus.
    # The mature library owns the scoring formula; no embedding or remote model is used.
    scores = BM25Plus(corpus).get_scores(words)
    order = sorted(range(len(candidates)), key=lambda index: (-float(scores[index]), index))
    return [candidates[index] for index in order]
