"""Cut a DocumentIR into chunks, embed them and store them in document_chunks.

Runs once per document version: if chunks already exist the version is not
re-chunked. When no embedding provider is configured (e.g. no API key yet)
chunks are still stored with ``embedding = NULL`` so keyword retrieval works;
a later run fills in the missing vectors once a key is available.
"""

from __future__ import annotations

import asyncio
import logging
import uuid

import sqlalchemy as sa
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import _engine, _session_factory
from app.models.analysis import DocumentIR
from app.models.chunk import DocumentChunk
from app.services.chunking import build_chunks
from app.services.embeddings import (
    EmbeddingNotConfiguredError,
    EmbeddingProvider,
    get_embedding_provider,
)
from app.workers.celery_app import celery_app

logger = logging.getLogger(__name__)

EMBED_BATCH_SIZE = 100


async def _embed_in_batches(
    provider: EmbeddingProvider, texts: list[str]
) -> list[list[float]]:
    vectors: list[list[float]] = []
    for start in range(0, len(texts), EMBED_BATCH_SIZE):
        vectors.extend(await provider.embed(texts[start : start + EMBED_BATCH_SIZE]))
    return vectors


async def _try_embed(
    provider: EmbeddingProvider | None, texts: list[str]
) -> list[list[float]] | None:
    if provider is None:
        return None
    try:
        return await _embed_in_batches(provider, texts)
    except EmbeddingNotConfiguredError as exc:
        logger.warning("Storing chunks without embeddings: %s", exc)
        return None


async def _fill_missing_embeddings(
    db: AsyncSession, version_id: uuid.UUID, provider: EmbeddingProvider | None
) -> str:
    missing = list(
        (
            await db.execute(
                sa.select(DocumentChunk)
                .where(
                    DocumentChunk.document_version_id == version_id,
                    DocumentChunk.embedding.is_(None),
                )
                .order_by(DocumentChunk.chunk_index)
            )
        )
        .scalars()
        .all()
    )
    if not missing:
        return "already_indexed"
    vectors = await _try_embed(provider, [chunk.text for chunk in missing])
    if vectors is None:
        return "already_indexed_without_embeddings"
    for chunk, vector in zip(missing, vectors, strict=True):
        chunk.embedding = vector
    await db.commit()
    return "embeddings_filled"


async def index_document_version(
    db: AsyncSession,
    version_id: uuid.UUID,
    provider: EmbeddingProvider | None,
) -> str:
    """Index one version; returns a short outcome label (for logs/tests)."""
    existing = await db.scalar(
        sa.select(sa.func.count())
        .select_from(DocumentChunk)
        .where(DocumentChunk.document_version_id == version_id)
    )
    if existing:
        return await _fill_missing_embeddings(db, version_id, provider)

    ir = (
        await db.execute(
            sa.select(DocumentIR).where(DocumentIR.document_version_id == version_id)
        )
    ).scalar_one_or_none()
    if ir is None:
        return "no_document_ir"

    drafts = build_chunks(ir.content)
    if not drafts:
        return "no_chunks"

    vectors = await _try_embed(provider, [draft.text for draft in drafts])
    for position, draft in enumerate(drafts):
        db.add(
            DocumentChunk(
                id=uuid.uuid4(),
                document_version_id=version_id,
                chunk_index=draft.chunk_index,
                section_path=draft.section_path,
                page_start=draft.page_start,
                page_end=draft.page_end,
                paragraph_ids=draft.paragraph_ids,
                text=draft.text,
                token_count=draft.token_count,
                embedding=vectors[position] if vectors is not None else None,
            )
        )
    try:
        await db.commit()
    except IntegrityError:
        # A concurrent run indexed the same version first — keep its rows.
        await db.rollback()
        return "already_indexed"
    return "indexed" if vectors is not None else "indexed_without_embeddings"


def _default_provider() -> EmbeddingProvider | None:
    try:
        return get_embedding_provider()
    except EmbeddingNotConfiguredError as exc:
        logger.warning("Embedding provider unavailable: %s", exc)
        return None


async def _run_index(document_version_id: str) -> str:
    try:
        async with _session_factory()() as db:
            return await index_document_version(
                db, uuid.UUID(document_version_id), _default_provider()
            )
    finally:
        # asyncio.run creates a loop per Celery task. Drain asyncpg pool on that loop.
        await _engine().dispose()


@celery_app.task(name="app.workers.index_document_chunks.index_document_chunks")
def index_document_chunks(document_version_id: str) -> str:
    return asyncio.run(_run_index(document_version_id))


def enqueue_chunk_indexing(document_version_id: uuid.UUID) -> bool:
    """Best-effort publish; indexing failures must never fail the analysis job.

    Anything missed here is picked up by scripts/backfill_chunks.py.
    """
    try:
        index_document_chunks.apply_async(args=(str(document_version_id),), retry=False)
    except Exception:
        logger.warning("Could not enqueue chunk indexing for %s", document_version_id)
        return False
    return True
