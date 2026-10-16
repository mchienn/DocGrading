"""Chunk indexing when the embedding provider fails.

Existing design (see ``index_document_chunks``): without a usable provider,
chunks are stored with ``embedding = NULL`` so keyword retrieval works, and
``scripts/backfill_chunks --fill-embeddings`` fills the vectors later. A
provider *failure* must follow the same path, and one bad document must not
stop the backfill of the others.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import os
import uuid

import httpx
import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.chunk import EMBEDDING_DIMENSIONS
from app.services.embeddings import (
    EmbeddingUnavailableError,
    FakeEmbeddingProvider,
    OpenAIEmbeddingProvider,
)
from app.workers.index_document_chunks import index_document_version
from scripts import backfill_chunks
from tests.openai_mock import OpenAIMock
from tests.test_rag_retrieval import _insert_ir, _paragraph, _report_ir, _run

requires_db = pytest.mark.skipif(
    os.environ.get("RUN_DATABASE_TESTS") != "1",
    reason="Database integration tests require RUN_DATABASE_TESTS=1",
)

POISON = "MÃ-LỖI-NHÚNG"


class _FailsOnPoison:
    """Embeds like the fake provider, but fails for batches containing POISON."""

    model_name = "fails-on-poison"

    def __init__(self) -> None:
        self._inner = FakeEmbeddingProvider()

    async def embed(self, texts: list[str]) -> list[list[float]]:
        if any(POISON in t for t in texts):
            raise EmbeddingUnavailableError("Embedding provider request failed (X)")
        return await self._inner.embed(texts)


async def _embedded(session: AsyncSession, version: uuid.UUID) -> tuple[int, int]:
    row = (
        await session.execute(
            text(
                "SELECT count(*), count(embedding) FROM public.document_chunks "
                "WHERE document_version_id = :v"
            ),
            {"v": version},
        )
    ).one()
    return int(row[0]), int(row[1])


@requires_db
@pytest.mark.parametrize("status", [429, 503, 401])
def test_provider_failure_stores_chunks_without_embeddings(
    monkeypatch: pytest.MonkeyPatch, status: int
) -> None:
    OpenAIMock(
        lambda _r: httpx.Response(status, headers={"retry-after-ms": "1"})
    ).install(monkeypatch)

    async def no_wait(_seconds: float) -> None:
        return None

    provider = OpenAIEmbeddingProvider(
        "sk-test", "emb", timeout_seconds=5, max_retries=0, sleep=no_wait
    )

    async def scenario(session: AsyncSession, ids: dict[str, uuid.UUID]) -> None:
        version = ids["document_2"]
        outcome = await index_document_version(session, version, provider)
        assert outcome == "indexed_without_embeddings"
        total, with_vector = await _embedded(session, version)
        assert total > 0 and with_vector == 0, "keyword retrieval still works"

    _run(scenario)


@requires_db
def test_fill_embeddings_keeps_chunks_when_the_provider_fails() -> None:
    async def scenario(session: AsyncSession, ids: dict[str, uuid.UUID]) -> None:
        version = ids["document_2"]
        assert await index_document_version(session, version, None) == (
            "indexed_without_embeddings"
        )
        failing = _FailsOnPoison()
        await session.execute(
            text(
                "UPDATE public.document_chunks SET text = text || :p "
                "WHERE document_version_id = :v"
            ),
            {"p": f" {POISON}", "v": version},
        )
        outcome = await index_document_version(session, version, failing)
        assert outcome == "already_indexed_without_embeddings"
        total, with_vector = await _embedded(session, version)
        assert total > 0 and with_vector == 0

    _run(scenario)


@requires_db
def test_one_failing_document_does_not_affect_the_next() -> None:
    provider = _FailsOnPoison()

    async def scenario(session: AsyncSession, ids: dict[str, uuid.UUID]) -> None:
        poisoned_ir = _report_ir()
        poisoned_ir["paragraphs"] = [
            _paragraph("x1", f"Đoạn có {POISON} trong nội dung.", "s1", 1)
        ]
        await _insert_ir(session.bind, ids["document_3"], poisoned_ir)

        first = await index_document_version(session, ids["document_3"], provider)
        second = await index_document_version(session, ids["document_2"], provider)

        assert first == "indexed_without_embeddings"
        assert second == "indexed"
        assert (await _embedded(session, ids["document_3"]))[1] == 0
        total, with_vector = await _embedded(session, ids["document_2"])
        assert total > 0 and with_vector == total
        assert EMBEDDING_DIMENSIONS > 0

    _run(scenario)


def test_backfill_continues_after_an_unexpected_error(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    versions = [uuid.uuid4(), uuid.uuid4(), uuid.uuid4()]
    seen: list[uuid.UUID] = []

    async def pending(_fill: bool) -> list[uuid.UUID]:
        return versions

    async def index(_db: object, version: uuid.UUID, _provider: object) -> str:
        seen.append(version)
        if version == versions[1]:
            raise RuntimeError("database hiccup")
        return "indexed"

    class _Engine:
        async def dispose(self) -> None:
            return None

    @contextlib.asynccontextmanager
    async def session():
        yield object()

    monkeypatch.setattr(backfill_chunks, "_pending_version_ids", pending)
    monkeypatch.setattr(backfill_chunks, "index_document_version", index)
    monkeypatch.setattr(backfill_chunks, "_default_provider", lambda: None)
    monkeypatch.setattr(backfill_chunks, "_session_factory", lambda: session)
    monkeypatch.setattr(backfill_chunks, "_engine", lambda: _Engine())

    asyncio.run(backfill_chunks.main(fill_embeddings=False))

    assert seen == versions, "the third document is still processed"
    out = capsys.readouterr().out
    assert "'indexed': 2" in out and "'error': 1" in out
    assert "database hiccup" not in out, "details go to the log"


@requires_db
def test_fill_embeddings_mode_refills_versions_left_without_vectors(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """End to end on the real queries: a version indexed while the provider
    failed is found by ``--fill-embeddings`` and gets its vectors."""

    async def scenario(session: AsyncSession, ids: dict[str, uuid.UUID]) -> None:
        version = ids["document_3"]
        poisoned = _report_ir()
        poisoned["paragraphs"] = [_paragraph("p1", f"Có {POISON} ở đây.", "s1", 1)]
        await _insert_ir(session.bind, version, poisoned)
        outcome = await index_document_version(session, version, _FailsOnPoison())
        assert outcome == "indexed_without_embeddings"
        assert (await _embedded(session, version))[1] == 0

        real_pending = backfill_chunks._pending_version_ids

        @contextlib.asynccontextmanager
        async def same_session():
            yield session  # the test transaction; rolled back by _run

        class _Engine:
            async def dispose(self) -> None:
                return None

        monkeypatch.setattr(backfill_chunks, "_session_factory", lambda: same_session)
        monkeypatch.setattr(backfill_chunks, "_engine", lambda: _Engine())
        monkeypatch.setattr(
            backfill_chunks, "_default_provider", lambda: FakeEmbeddingProvider()
        )

        assert version not in await real_pending(False), "it has chunks already"
        assert version in await real_pending(True), "missing vectors are found"

        async def only_this_version(fill: bool) -> list[uuid.UUID]:
            return [v for v in await real_pending(fill) if v == version]

        monkeypatch.setattr(backfill_chunks, "_pending_version_ids", only_this_version)
        await backfill_chunks.main(fill_embeddings=True)

        total, with_vector = await _embedded(session, version)
        assert total > 0 and with_vector == total
        assert "embeddings_filled" in capsys.readouterr().out

    _run(scenario)


@requires_db
def test_worker_warns_how_to_fill_the_missing_embeddings(
    caplog: pytest.LogCaptureFixture,
) -> None:
    async def scenario(session: AsyncSession, ids: dict[str, uuid.UUID]) -> None:
        version = ids["document_3"]
        poisoned = _report_ir()
        poisoned["paragraphs"] = [_paragraph("x1", f"{POISON} trong bài.", "s1", 1)]
        await _insert_ir(session.bind, version, poisoned)
        with caplog.at_level(logging.WARNING, logger="app.workers"):
            outcome = await index_document_version(session, version, _FailsOnPoison())
        assert outcome == "indexed_without_embeddings"
        hints = [
            r.getMessage()
            for r in caplog.records
            if "--fill-embeddings" in r.getMessage()
        ]
        assert hints and str(version) in hints[0]

    _run(scenario)


@requires_db
def test_no_warning_when_indexing_without_a_provider_on_purpose(
    caplog: pytest.LogCaptureFixture,
) -> None:
    async def scenario(session: AsyncSession, ids: dict[str, uuid.UUID]) -> None:
        with caplog.at_level(logging.WARNING, logger="app.workers"):
            await index_document_version(session, ids["document_2"], None)
        assert not [r for r in caplog.records if "--fill-embeddings" in r.getMessage()]

    _run(scenario)
