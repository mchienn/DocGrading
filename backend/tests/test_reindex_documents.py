"""scripts/reindex_documents.py on a rolled-back database.

The PDF is built by tests/test_document_ir_word_spacing.py (no student data);
the seeded document version's sha256 is set to that PDF's hash.
"""

from __future__ import annotations

import asyncio
import hashlib
import os
import uuid
from pathlib import Path

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.document_ir import PARSER_VERSION
from app.services.embeddings import FakeEmbeddingProvider
from app.services.rag import FakeLLMClient
from app.workers.index_document_chunks import index_document_version
from scripts import reindex_documents as reindex
from tests.test_document_ir_word_spacing import (
    TIGHT_GAP,
    VI,
    _Font,
    _pdf,
    _positioned_words,
)
from tests.test_rag_retrieval import _run

pytestmark = pytest.mark.skipif(
    os.environ.get("RUN_DATABASE_TESTS") != "1",
    reason="Database integration tests require RUN_DATABASE_TESTS=1",
)


def _fixture_pdf() -> bytes:
    font = _Font(VI)
    return _pdf(font, _positioned_words(font, VI, y=700, gap=TIGHT_GAP))


async def _prepare(session: AsyncSession, version: uuid.UUID, data: bytes) -> list[str]:
    """Old state: chunks built from the seeded (old-parser) IR, sha = PDF's."""
    await session.execute(
        text("UPDATE public.document_versions SET sha256 = :s WHERE id = :v"),
        {"s": hashlib.sha256(data).hexdigest(), "v": version},
    )
    await index_document_version(session, version, None)
    return await _chunk_texts(session, version)


async def _chunk_texts(session: AsyncSession, version: uuid.UUID) -> list[str]:
    rows = await session.execute(
        text(
            "SELECT text FROM public.document_chunks "
            "WHERE document_version_id = :v ORDER BY chunk_index"
        ),
        {"v": version},
    )
    return [r[0] for r in rows]


async def _parser_version(session: AsyncSession, version: uuid.UUID) -> str:
    return await session.scalar(
        text(
            "SELECT parser_version FROM public.document_irs "
            "WHERE document_version_id = :v"
        ),
        {"v": version},
    )


def _pdf_dir(tmp_path: Path, data: bytes) -> reindex.PdfIndex:
    (tmp_path / "nested").mkdir()
    (tmp_path / "nested" / "report.pdf").write_bytes(data)
    (tmp_path / "other.pdf").write_bytes(b"%PDF-1.4 not this one")
    return reindex.PdfIndex.from_directory(tmp_path)


def test_pdf_index_finds_files_by_sha256(tmp_path: Path) -> None:
    data = _fixture_pdf()
    index = _pdf_dir(tmp_path, data)
    assert index.get(hashlib.sha256(data).hexdigest()) == data
    assert index.get("0" * 64) is None


def test_dry_run_changes_nothing(tmp_path: Path) -> None:
    data = _fixture_pdf()
    index = _pdf_dir(tmp_path, data)

    async def scenario(session: AsyncSession, ids: dict[str, uuid.UUID]) -> None:
        version = ids["document_2"]
        before = await _prepare(session, version, data)
        result = await reindex.reindex_version(
            session, version, index, FakeEmbeddingProvider(), dry_run=True
        )
        assert result.outcome == "would_reindex"
        assert await _chunk_texts(session, version) == before
        assert await _parser_version(session, version) == "test-parser"

    _run(scenario)


def test_reindex_rebuilds_ir_chunks_and_embeddings_then_is_up_to_date(
    tmp_path: Path,
) -> None:
    data = _fixture_pdf()
    index = _pdf_dir(tmp_path, data)

    async def scenario(session: AsyncSession, ids: dict[str, uuid.UUID]) -> None:
        version = ids["document_2"]
        before = await _prepare(session, version, data)
        result = await reindex.reindex_version(
            session, version, index, FakeEmbeddingProvider(), dry_run=False
        )
        assert result.outcome == "reindexed"
        assert result.chunks_before == len(before)
        assert await _parser_version(session, version) == PARSER_VERSION
        after = await _chunk_texts(session, version)
        assert after != before
        assert any(VI in t for t in after), "spaced text from the new parser"
        embedded = await session.scalar(
            text(
                "SELECT count(*) FROM public.document_chunks "
                "WHERE document_version_id = :v AND embedding IS NOT NULL"
            ),
            {"v": version},
        )
        assert embedded == len(after) == result.chunks_after

        again = await reindex.reindex_version(
            session, version, index, FakeEmbeddingProvider(), dry_run=False
        )
        assert again.outcome == "up_to_date"
        assert await _chunk_texts(session, version) == after

    _run(scenario)


def test_missing_pdf_keeps_the_old_data(tmp_path: Path) -> None:
    data = _fixture_pdf()
    empty = reindex.PdfIndex.from_directory(tmp_path)

    async def scenario(session: AsyncSession, ids: dict[str, uuid.UUID]) -> None:
        version = ids["document_2"]
        before = await _prepare(session, version, data)
        result = await reindex.reindex_version(
            session, version, empty, FakeEmbeddingProvider(), dry_run=False
        )
        assert result.outcome == "pdf_missing"
        assert await _chunk_texts(session, version) == before
        assert await _parser_version(session, version) == "test-parser"

    _run(scenario)


def test_summaries_are_stored_with_a_real_source_hash(tmp_path: Path) -> None:
    data = _fixture_pdf()
    index = _pdf_dir(tmp_path, data)

    async def scenario(session: AsyncSession, ids: dict[str, uuid.UUID]) -> None:
        version = ids["document_2"]
        await _prepare(session, version, data)
        await reindex.reindex_version(
            session, version, index, FakeEmbeddingProvider(), dry_run=False
        )
        client = FakeLLMClient("Tóm tắt mới")
        outcome = await reindex.refresh_summary(session, version, client)
        assert outcome == "regenerated"
        stored = await session.scalar(
            text(
                "SELECT source_hash FROM public.document_summaries "
                "WHERE document_version_id = :v"
            ),
            {"v": version},
        )
        assert stored is not None and len(stored) == 64
        assert await reindex.refresh_summary(session, version, client) == "cached"
        assert len(client.calls) == 1

    _run(scenario)


def test_refuses_to_write_without_explicit_database_name() -> None:
    with pytest.raises(SystemExit):
        asyncio.run(
            reindex.main(
                dry_run=False,
                pdf_dir=None,
                use_storage=False,
                summaries=False,
                expect_db="some_other_db",
                report=None,
            )
        )
