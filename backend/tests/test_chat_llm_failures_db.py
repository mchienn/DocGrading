"""``handle_chat`` and ``POST /api/v1/chat`` survive every OpenAI failure.

Run against the dedicated test database (each scenario is rolled back):
    POSTGRES_DB=docgrading_test RUN_DATABASE_TESTS=1 uv run pytest \\
        tests/test_chat_llm_failures_db.py
"""

from __future__ import annotations

import os
import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.enums import UserRole
from app.services import chat as chat_service
from app.services.chat import (
    ANSWER_FALLBACK_TEXT,
    SUMMARY_UNAVAILABLE_TEXT,
    Intent,
    handle_chat,
)
from app.services.embeddings import OpenAIEmbeddingProvider
from app.services.rag import OpenAIChatClient
from app.workers.index_document_chunks import index_document_version
from tests.test_chat_sessions import _client
from tests.test_llm_failures import (
    FAILURES,
    UNKNOWN_MESSAGE,
    assert_no_leak,
    install_failing_openai,
)
from tests.test_rag_retrieval import _run
from tests.test_t011_review_workspace import _actor

pytestmark = pytest.mark.skipif(
    os.environ.get("RUN_DATABASE_TESTS") != "1",
    reason="Database integration tests require RUN_DATABASE_TESTS=1",
)

ASK = "Bài này có đề cập đến kiểm thử đơn vị không?"
SUMMARIZE = "Tóm tắt bài này"
SEARCH = "Tìm đoạn nói về kiểm thử"


def _install_failing_providers(
    monkeypatch: pytest.MonkeyPatch, kind: str
) -> list[object]:
    """LLM and embeddings both go through the real SDK and fail as *kind*."""
    seen = install_failing_openai(monkeypatch, kind)
    monkeypatch.setattr(
        chat_service,
        "_rag_llm_client",
        lambda: OpenAIChatClient(
            "sk-test", "gpt-test", timeout_seconds=5, max_retries=1
        ),
    )
    monkeypatch.setattr(
        chat_service,
        "_rag_embedding_provider",
        lambda: OpenAIEmbeddingProvider(
            "sk-test",
            "emb-test",
            timeout_seconds=5,
            max_retries=0,
            rate_limit_retries=0,
        ),
    )
    return seen


async def _summary_rows(session: AsyncSession, version: uuid.UUID) -> int:
    return await session.scalar(
        text(
            "SELECT count(*) FROM public.document_summaries "
            "WHERE document_version_id = :v"
        ),
        {"v": version},
    )


@pytest.mark.parametrize("kind", FAILURES)
def test_handle_chat_never_raises_on_provider_failure(
    monkeypatch: pytest.MonkeyPatch, kind: str
) -> None:
    seen = _install_failing_providers(monkeypatch, kind)

    async def scenario(session: AsyncSession, ids: dict[str, uuid.UUID]) -> None:
        await index_document_version(session, ids["document_2"], None)
        teacher = _actor(ids["teacher"], "Teacher A", UserRole.TEACHER)

        async def ask(message: str):
            return await handle_chat(
                session,
                user=teacher,
                message=message,
                course_id=None,
                assignment_id=None,
                submission_id=ids["submission_2"],
            )

        # Answer with citations: embedding fails -> keyword retrieval still
        # finds page 2; the LLM fails -> passages are returned verbatim.
        answer = await ask(ASK)
        assert answer.intent == Intent.ASK_ABOUT_REQUIREMENT
        assert answer.reply.splitlines()[0] == ANSWER_FALLBACK_TEXT
        assert answer.citations and answer.citations[0].page == 2
        assert answer.llm_unavailable is True
        assert_no_leak(answer.model_dump_json())

        summary = await ask(SUMMARIZE)
        assert summary.intent == Intent.SUMMARIZE_SUBMISSION
        assert summary.reply == SUMMARY_UNAVAILABLE_TEXT
        assert summary.llm_unavailable is True
        assert await _summary_rows(session, ids["document_2"]) == 0
        assert_no_leak(summary.model_dump_json())

        search = await ask(SEARCH)
        assert search.intent == Intent.SEARCH_CONTENT
        assert search.citations and search.citations[0].page == 2
        assert search.llm_unavailable is False, "no LLM on this path"
        assert_no_leak(search.model_dump_json())

        routed = await ask(UNKNOWN_MESSAGE)
        assert routed.intent == Intent.UNKNOWN
        assert routed.reply.startswith("Mình chưa hiểu câu hỏi này.")
        assert_no_leak(routed.model_dump_json())

    _run(scenario)
    assert seen, "the SDK was really called"


@pytest.mark.parametrize("kind", FAILURES)
def test_chat_endpoint_answers_200_when_the_provider_fails(
    monkeypatch: pytest.MonkeyPatch, kind: str
) -> None:
    _install_failing_providers(monkeypatch, kind)

    async def scenario(session: AsyncSession, ids: dict[str, uuid.UUID]) -> None:
        await index_document_version(session, ids["document_2"], None)
        client, headers = _client(session, ids["teacher"])
        async with client:
            for message in (ASK, SUMMARIZE, SEARCH, UNKNOWN_MESSAGE):
                response = await client.post(
                    "/api/v1/chat",
                    json={
                        "message": message,
                        "submission_id": str(ids["submission_2"]),
                    },
                    headers=headers,
                )
                assert response.status_code == 200, (message, response.text)
                assert_no_leak(response.text)
                body = response.json()
                expected_flag = message in (ASK, SUMMARIZE)
                assert body["llm_unavailable"] is expected_flag, message

    _run(scenario)
