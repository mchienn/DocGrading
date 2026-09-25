"""Retrieval-augmented answers over student documents.

Retrieval is hybrid: pgvector cosine distance and Postgres full-text search
each produce a ranked list of chunk ids, merged with Reciprocal Rank Fusion.
Callers must pass an already-authorized list of document version ids — this
module never widens scope on its own and never scans the whole table.
"""

from __future__ import annotations

import logging
import re
import unicodedata
import uuid
from collections.abc import Hashable, Sequence
from dataclasses import dataclass

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.chunk import DocumentChunk
from app.services.embeddings import EmbeddingNotConfiguredError, EmbeddingProvider

logger = logging.getLogger(__name__)

RRF_K = 60
VECTOR_TOP_K = 8
KEYWORD_TOP_K = 8
FINAL_TOP_K = 6
EXCERPT_CHARS = 320

# Words that carry no topic on their own; dropped before building the OR query
# so "của"/"và" do not match every chunk.
_STOPWORDS = frozenset(
    {
        "va", "la", "cua", "cac", "nhung", "mot", "cho", "voi", "trong", "ve",
        "de", "duoc", "co", "khong", "nay", "do", "the", "nao", "gi", "o",
        "a", "an", "of", "and", "to", "in", "is", "for", "on",
    }
)  # fmt: skip

_WORD_RE = re.compile(r"\w+", re.UNICODE)


@dataclass(frozen=True)
class RetrievedChunk:
    id: uuid.UUID
    document_version_id: uuid.UUID
    chunk_index: int
    page_start: int
    page_end: int
    section_path: str | None
    text: str
    score: float


def rrf_merge[K: Hashable](
    ranked_lists: Sequence[Sequence[K]], *, k: int = RRF_K, limit: int = FINAL_TOP_K
) -> list[tuple[K, float]]:
    """Reciprocal Rank Fusion: score(d) = sum over lists of 1 / (k + rank).

    ``rank`` is 1-based. Ties keep the order in which ids were first seen, so
    the result is deterministic.
    """
    scores: dict[K, float] = {}
    for ranked in ranked_lists:
        for rank, item in enumerate(ranked, start=1):
            scores[item] = scores.get(item, 0.0) + 1.0 / (k + rank)
    ordered = sorted(scores.items(), key=lambda pair: pair[1], reverse=True)
    return ordered[:limit]


def _fold(text: str) -> str:
    decomposed = unicodedata.normalize("NFD", text.lower())
    stripped = "".join(ch for ch in decomposed if unicodedata.category(ch) != "Mn")
    return stripped.replace("đ", "d")


def query_terms(query: str) -> list[str]:
    """Lower-cased NFC words of *query*, minus stopwords, in original order."""
    words = _WORD_RE.findall(unicodedata.normalize("NFC", query.lower()))
    terms = [w for w in words if len(w) > 1 and _fold(w) not in _STOPWORDS]
    return list(dict.fromkeys(terms))


def strip_section_prefix(text: str) -> str:
    """Drop the ``[section path]`` header that chunking prepends to chunk text."""
    if text.startswith("[") and "]\n" in text:
        return text.split("]\n", 1)[1]
    return text


def make_excerpt(text: str, query: str, width: int = EXCERPT_CHARS) -> str:
    """A ~*width*-char window of *text* centred on the first query-term hit."""
    body = " ".join(strip_section_prefix(text).split())
    if len(body) <= width:
        return body
    folded = _fold(body)
    hit = -1
    for term in query_terms(query):
        position = folded.find(_fold(term))
        if position != -1 and (hit == -1 or position < hit):
            hit = position
    start = 0 if hit == -1 else max(0, hit - width // 3)
    end = min(len(body), start + width)
    start = max(0, end - width)
    excerpt = body[start:end].strip()
    return ("…" if start > 0 else "") + excerpt + ("…" if end < len(body) else "")


def _tsvector() -> sa.ColumnElement:
    return sa.func.to_tsvector(
        sa.literal_column("'simple'::regconfig"), DocumentChunk.text
    )


async def _keyword_ranked(
    db: AsyncSession, version_ids: Sequence[uuid.UUID], query: str
) -> list[uuid.UUID]:
    terms = query_terms(query)
    if not terms:
        return []
    simple = sa.literal_column("'simple'::regconfig")
    # All terms first (precise); fall back to any term when nothing matches all.
    candidates = [
        sa.func.plainto_tsquery(simple, " ".join(terms)),
        sa.func.to_tsquery(simple, " | ".join(terms)),
    ]
    for tsquery in candidates:
        stmt = (
            sa.select(DocumentChunk.id)
            .where(
                DocumentChunk.document_version_id.in_(version_ids),
                _tsvector().op("@@")(tsquery),
            )
            .order_by(
                sa.func.ts_rank(_tsvector(), tsquery).desc(), DocumentChunk.chunk_index
            )
            .limit(KEYWORD_TOP_K)
        )
        ids = list((await db.execute(stmt)).scalars().all())
        if ids:
            return ids
    return []


async def _vector_ranked(
    db: AsyncSession,
    version_ids: Sequence[uuid.UUID],
    query: str,
    provider: EmbeddingProvider | None,
) -> list[uuid.UUID]:
    if provider is None:
        return []
    try:
        [query_vector] = await provider.embed([query])
    except EmbeddingNotConfiguredError as exc:
        logger.info("Vector retrieval skipped: %s", exc)
        return []
    stmt = (
        sa.select(DocumentChunk.id)
        .where(
            DocumentChunk.document_version_id.in_(version_ids),
            DocumentChunk.embedding.is_not(None),
        )
        .order_by(DocumentChunk.embedding.cosine_distance(query_vector))
        .limit(VECTOR_TOP_K)
    )
    return list((await db.execute(stmt)).scalars().all())


async def retrieve_chunks(
    db: AsyncSession,
    scoped_version_ids: Sequence[uuid.UUID],
    query: str,
    *,
    provider: EmbeddingProvider | None = None,
    limit: int = FINAL_TOP_K,
) -> list[RetrievedChunk]:
    """Hybrid search restricted to *scoped_version_ids* (already authorized)."""
    version_ids = list(dict.fromkeys(scoped_version_ids))
    if not version_ids or not query.strip():
        return []
    vector_ids = await _vector_ranked(db, version_ids, query, provider)
    keyword_ids = await _keyword_ranked(db, version_ids, query)
    merged = rrf_merge([vector_ids, keyword_ids], limit=limit)
    if not merged:
        return []
    rows = {
        chunk.id: chunk
        for chunk in (
            await db.execute(
                sa.select(DocumentChunk).where(
                    DocumentChunk.id.in_([chunk_id for chunk_id, _ in merged])
                )
            )
        )
        .scalars()
        .all()
    }
    return [
        RetrievedChunk(
            id=chunk.id,
            document_version_id=chunk.document_version_id,
            chunk_index=chunk.chunk_index,
            page_start=chunk.page_start,
            page_end=chunk.page_end,
            section_path=chunk.section_path,
            text=chunk.text,
            score=score,
        )
        for chunk_id, score in merged
        if (chunk := rows.get(chunk_id)) is not None
    ]
