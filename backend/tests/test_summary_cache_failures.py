"""A failed summary must never be cached as if it were a real one.

``summarize_document`` keys its cache on ``source_hash``; if the failure
placeholder were stored under the current hash, every later request would
serve it as a cache hit until the chunks changed. These tests use a minimal
fake session (the DB variant lives in ``test_rag_retrieval.py``).
"""

from __future__ import annotations

import asyncio
import uuid
from typing import Any

import pytest

from app.models.chunk import DocumentSummary
from app.services.rag import (
    SUMMARY_FAILED_TEXT,
    FakeLLMClient,
    SummaryChunk,
    summarize_document,
    summary_source_hash,
)

_PARSER = "parser-test"
_ROWS = [
    ("1. Giới thiệu", "[1. Giới thiệu]\nHệ thống quản lý thư viện.", 12),
    ("2. Kiểm thử", "[2. Kiểm thử]\nKiểm thử đơn vị bằng pytest.", 10),
]


def _current_hash() -> str:
    return summary_source_hash(_PARSER, [SummaryChunk(*row) for row in _ROWS])


class _Result:
    def __init__(self, rows: list[tuple[Any, ...]]) -> None:
        self._rows = rows

    def all(self) -> list[tuple[Any, ...]]:
        return self._rows


class _FakeSession:
    """Answers summarize_document's queries in the order it issues them:
    chunks (execute), parser version (scalar), cached row (scalar)."""

    def __init__(self, existing: DocumentSummary | None) -> None:
        self._scalars: list[Any] = [_PARSER, existing]
        self.added: list[object] = []
        self.commits = 0

    async def execute(self, _stmt: object) -> _Result:
        return _Result(list(_ROWS))

    async def scalar(self, _stmt: object) -> Any:
        return self._scalars.pop(0)

    def add(self, obj: object) -> None:
        self.added.append(obj)

    async def commit(self) -> None:
        self.commits += 1

    async def rollback(self) -> None:
        return None


def _row(summary: str, source_hash: str | None) -> DocumentSummary:
    return DocumentSummary(
        id=uuid.uuid4(),
        document_version_id=uuid.uuid4(),
        summary=summary,
        model_version="old-model",
        source_hash=source_hash,
    )


def _summarize(session: _FakeSession, client: FakeLLMClient):
    return asyncio.run(summarize_document(session, uuid.uuid4(), client))  # type: ignore[arg-type]


@pytest.mark.parametrize("llm_output", ["", "   \n  "])
def test_empty_llm_output_is_not_stored(llm_output: str) -> None:
    session = _FakeSession(existing=None)
    result = _summarize(session, FakeLLMClient(llm_output))

    assert result is not None
    assert result.text == SUMMARY_FAILED_TEXT
    assert not result.cached
    assert session.added == [], "the failure placeholder must not be inserted"
    assert session.commits == 0


def test_empty_llm_output_leaves_an_existing_stale_row_untouched() -> None:
    stale = _row("Tóm tắt cũ", "0" * 64)
    session = _FakeSession(existing=stale)
    result = _summarize(session, FakeLLMClient(""))

    assert result is not None and result.text == SUMMARY_FAILED_TEXT
    assert not result.cached
    assert stale.summary == "Tóm tắt cũ"
    assert stale.source_hash == "0" * 64, "hash must not be stamped on failure"
    assert session.commits == 0


def test_llm_error_propagates_and_nothing_is_stored() -> None:
    def broken(_system: str, _prompt: str) -> str:
        raise TimeoutError("provider timed out")

    session = _FakeSession(existing=None)
    with pytest.raises(TimeoutError):
        _summarize(session, FakeLLMClient(broken))
    assert session.added == [] and session.commits == 0


def test_placeholder_row_left_by_older_code_is_regenerated() -> None:
    # Rows written before this fix hold the placeholder under a matching hash.
    poisoned = _row(SUMMARY_FAILED_TEXT, _current_hash())
    session = _FakeSession(existing=poisoned)
    client = FakeLLMClient("Tóm tắt thật")
    result = _summarize(session, client)

    assert result is not None and result.text == "Tóm tắt thật"
    assert not result.cached
    assert len(client.calls) == 1
    assert poisoned.summary == "Tóm tắt thật"
    assert session.commits == 1


def test_matching_real_summary_is_still_a_cache_hit() -> None:
    cached = _row("Tóm tắt thật", _current_hash())
    session = _FakeSession(existing=cached)
    client = FakeLLMClient("không được gọi")
    result = _summarize(session, client)

    assert result is not None and result.cached and result.text == "Tóm tắt thật"
    assert client.calls == []
