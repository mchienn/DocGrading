"""Turn deadlines through ``handle_chat`` on a real (rolled-back) database.

    POSTGRES_DB=docgrading_test RUN_DATABASE_TESTS=1 uv run pytest \\
        tests/test_chat_deadlines_db.py

The ``measured_*`` tests use the production defaults (25 s turn, 8 s router,
90 s summary) against a provider that answers ``Retry-After: 120`` or never
answers, and print the wall-clock time of each turn. They take ~3 minutes and
run only with ``RUN_SLOW_DEADLINE_TESTS=1`` (add ``-s`` to see the numbers).
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import time
import uuid

import httpx
import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.models.enums import UserRole
from app.services import chat as chat_service
from app.services.chat import (
    ANSWER_FALLBACK_TEXT,
    ROUTER_SYSTEM_PROMPT,
    SUMMARY_UNAVAILABLE_TEXT,
    Intent,
    handle_chat,
)
from app.services.embeddings import OpenAIEmbeddingProvider
from app.services.rag import OpenAIChatClient
from app.workers.index_document_chunks import index_document_version
from tests.openai_mock import OpenAIMock, chat_completion, hang, retry_after
from tests.test_llm_failures import UNKNOWN_MESSAGE
from tests.test_rag_retrieval import _run
from tests.test_t011_review_workspace import _actor

pytestmark = pytest.mark.skipif(
    os.environ.get("RUN_DATABASE_TESTS") != "1",
    reason="Database integration tests require RUN_DATABASE_TESTS=1",
)
slow = pytest.mark.skipif(
    os.environ.get("RUN_SLOW_DEADLINE_TESTS") != "1",
    reason="Wall-clock deadline measurements require RUN_SLOW_DEADLINE_TESTS=1",
)

ASK = "Bài này có đề cập đến kiểm thử đơn vị không?"
SUMMARIZE = "Tóm tắt bài này"
SEARCH = "Tìm đoạn nói về kiểm thử"
GUARD_SECONDS = 150.0


def _install_product_providers(monkeypatch: pytest.MonkeyPatch, **settings) -> None:
    """Production clients and defaults (only *settings* overridden)."""
    config = Settings(**settings)
    monkeypatch.setattr(chat_service, "get_settings", lambda: config)
    monkeypatch.setattr(
        chat_service,
        "_rag_llm_client",
        lambda: OpenAIChatClient(
            "sk-test",
            "gpt-test",
            timeout_seconds=config.llm_timeout_seconds,
            max_retries=config.llm_max_retries,
        ),
    )
    monkeypatch.setattr(
        chat_service,
        "_rag_embedding_provider",
        lambda: OpenAIEmbeddingProvider(
            "sk-test",
            "emb-test",
            timeout_seconds=config.embedding_timeout_seconds,
            max_retries=config.embedding_max_retries,
            rate_limit_retries=0,  # as get_embedding_provider(interactive=True)
        ),
    )


async def _timed_turn(session: AsyncSession, ids: dict, message: str):
    teacher = _actor(ids["teacher"], "Teacher A", UserRole.TEACHER)
    started = time.perf_counter()
    response = await asyncio.wait_for(
        handle_chat(
            session,
            user=teacher,
            message=message,
            course_id=None,
            assignment_id=None,
            submission_id=ids["submission_2"],
        ),
        GUARD_SECONDS,
    )
    return response, time.perf_counter() - started


async def _summary_rows(session: AsyncSession, version: uuid.UUID) -> int:
    return await session.scalar(
        text(
            "SELECT count(*) FROM public.document_summaries "
            "WHERE document_version_id = :v"
        ),
        {"v": version},
    )


def test_short_deadline_cuts_every_path_through_handle_chat(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mock = OpenAIMock(retry_after(120)).install(monkeypatch)
    _install_product_providers(
        monkeypatch,
        chat_turn_deadline_seconds=0.6,
        llm_router_timeout_seconds=0.3,
        summary_deadline_seconds=0.6,
    )

    async def scenario(session: AsyncSession, ids: dict[str, uuid.UUID]) -> None:
        await index_document_version(session, ids["document_2"], None)

        answer, elapsed = await _timed_turn(session, ids, ASK)
        assert elapsed < 3.0
        assert answer.reply.splitlines()[0] == ANSWER_FALLBACK_TEXT
        assert answer.citations and answer.citations[0].page == 2
        assert answer.llm_unavailable is True

        search, elapsed = await _timed_turn(session, ids, SEARCH)
        assert elapsed < 3.0
        assert search.citations and search.citations[0].page == 2

        summary, elapsed = await _timed_turn(session, ids, SUMMARIZE)
        assert elapsed < 3.0
        assert summary.reply == SUMMARY_UNAVAILABLE_TEXT
        assert summary.llm_unavailable is True
        assert await _summary_rows(session, ids["document_2"]) == 0

        routed, elapsed = await _timed_turn(session, ids, UNKNOWN_MESSAGE)
        assert elapsed < 3.0
        assert routed.intent == Intent.UNKNOWN

    _run(scenario)
    assert mock.clients_closed == mock.clients_opened


# --- wall-clock measurements with the production defaults ----------------------


def _report(path: str, elapsed: float) -> None:
    print(f"\nMEASURED {path}: {elapsed:.2f}s")


@slow
def test_measured_ask_turn_with_retry_after_120(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    OpenAIMock(retry_after(120)).install(monkeypatch)
    _install_product_providers(monkeypatch)

    async def scenario(session: AsyncSession, ids: dict[str, uuid.UUID]) -> None:
        await index_document_version(session, ids["document_2"], None)
        answer, elapsed = await _timed_turn(session, ids, ASK)
        _report("ask (Retry-After 120 on embedding + answer)", elapsed)
        assert answer.llm_unavailable is True and answer.citations
        assert 24.0 <= elapsed <= 27.0

    _run(scenario)


@slow
def test_measured_search_turn_with_retry_after_120(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    OpenAIMock(retry_after(120)).install(monkeypatch)
    _install_product_providers(monkeypatch)

    async def scenario(session: AsyncSession, ids: dict[str, uuid.UUID]) -> None:
        await index_document_version(session, ids["document_2"], None)
        search, elapsed = await _timed_turn(session, ids, SEARCH)
        _report("search (Retry-After 120 on embedding)", elapsed)
        assert search.citations
        assert 5.5 <= elapsed <= 8.0, "cut at the 6 s query-embedding cap"

    _run(scenario)


@slow
def test_measured_router_turn_when_provider_never_answers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    OpenAIMock(hang).install(monkeypatch)
    _install_product_providers(monkeypatch)

    async def scenario(session: AsyncSession, ids: dict[str, uuid.UUID]) -> None:
        routed, elapsed = await _timed_turn(session, ids, UNKNOWN_MESSAGE)
        _report("router (provider never answers)", elapsed)
        assert routed.intent == Intent.UNKNOWN
        assert 7.5 <= elapsed <= 10.0

    _run(scenario)


@slow
def test_measured_slow_router_then_ask_shares_the_turn_deadline(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content or b"{}")
        messages = body.get("messages") or [{}]
        if messages[0].get("content") == ROUTER_SYSTEM_PROMPT:
            await asyncio.sleep(7)  # slow but inside the 8 s router timeout
            route = {"intent": "ASK_ABOUT_REQUIREMENT", "question": ASK}
            return httpx.Response(200, json=chat_completion(json.dumps(route)))
        return retry_after(120)(request)

    OpenAIMock(handler).install(monkeypatch)
    _install_product_providers(monkeypatch)

    async def scenario(session: AsyncSession, ids: dict[str, uuid.UUID]) -> None:
        await index_document_version(session, ids["document_2"], None)
        answer, elapsed = await _timed_turn(session, ids, UNKNOWN_MESSAGE)
        _report("router 7 s -> ask (Retry-After 120)", elapsed)
        assert answer.intent == Intent.ASK_ABOUT_REQUIREMENT
        assert answer.llm_unavailable is True
        assert 24.0 <= elapsed <= 27.0, "router time counts toward the 25 s"

    _run(scenario)


@slow
def test_measured_summary_turn_with_retry_after_120(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    OpenAIMock(retry_after(120)).install(monkeypatch)
    _install_product_providers(monkeypatch)

    async def scenario(session: AsyncSession, ids: dict[str, uuid.UUID]) -> None:
        await index_document_version(session, ids["document_2"], None)
        summary, elapsed = await _timed_turn(session, ids, SUMMARIZE)
        _report("summary (Retry-After 120)", elapsed)
        assert summary.reply == SUMMARY_UNAVAILABLE_TEXT
        assert await _summary_rows(session, ids["document_2"]) == 0
        assert 89.0 <= elapsed <= 92.0

    _run(scenario)


@slow
def test_measured_ask_turn_embedding_hangs_llm_answers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/embeddings"):
            return await hang(request)
        cited = re.search(rb"\[chunk:([0-9a-f-]{36})\]", request.content)
        reply = f"Có, nhóm viết kiểm thử đơn vị [chunk:{cited.group(1).decode()}]."
        return httpx.Response(200, json=chat_completion(reply))

    OpenAIMock(handler).install(monkeypatch)
    _install_product_providers(monkeypatch)

    async def scenario(session: AsyncSession, ids: dict[str, uuid.UUID]) -> None:
        await index_document_version(session, ids["document_2"], None)
        answer, elapsed = await _timed_turn(session, ids, ASK)
        _report("ask (embedding never answers, LLM answers)", elapsed)
        assert answer.llm_unavailable is False
        assert answer.reply.startswith("Có, nhóm viết kiểm thử đơn vị")
        assert answer.citations and answer.citations[0].page == 2
        assert 5.5 <= elapsed <= 8.0

    _run(scenario)
