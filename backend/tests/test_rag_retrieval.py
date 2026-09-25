"""Integration tests for RAG indexing, hybrid retrieval and chat scoping.

Run against the dedicated test database, never the dev one (migration
roundtrip tests elsewhere downgrade whatever DB they point at):
    POSTGRES_DB=docgrading_test RUN_DATABASE_TESTS=1 uv run pytest tests/test_rag*.py
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import uuid
from collections.abc import Awaitable, Callable

import pytest
from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncSession, create_async_engine
from sqlalchemy.pool import NullPool

from app.core.config import get_settings
from app.models.enums import UserRole
from app.services import chat as chat_service
from app.services.chat import Intent, handle_chat
from app.services.embeddings import FakeEmbeddingProvider
from app.services.rag import FakeLLMClient, retrieve_chunks, summarize_document
from app.workers.index_document_chunks import index_document_version
from tests.test_t011_review_workspace import _actor, _ids, _seed_graph

pytestmark = pytest.mark.skipif(
    os.environ.get("RUN_DATABASE_TESTS") != "1",
    reason="Database integration tests require RUN_DATABASE_TESTS=1",
)


def _paragraph(pid: str, text_: str, section: str, page: int) -> dict:
    return {
        "id": pid,
        "text": text_,
        "section_id": section,
        "page_number": page,
        "bbox": {"x0": 0, "top": 0, "x1": 1, "bottom": 1},
    }


def _report_ir() -> dict:
    return {
        "schema_version": 1,
        "source": {"sha256": "b" * 64, "size_bytes": 100, "page_count": 3},
        "pages": [],
        "sections": [
            {"id": "s1", "text": "1. Giới thiệu", "level": 1, "parent_id": None,
             "page_number": 1, "bbox": {}},
            {"id": "s2", "text": "3. Kiểm thử", "level": 1, "parent_id": None,
             "page_number": 2, "bbox": {}},
            {"id": "s3", "text": "4. Kết luận", "level": 1, "parent_id": None,
             "page_number": 3, "bbox": {}},
        ],  # fmt: skip
        "paragraphs": [
            _paragraph("p1", "Hệ thống quản lý thư viện cho sinh viên.", "s1", 1),
            _paragraph(
                "p2",
                "Nhóm viết kiểm thử đơn vị bằng pytest cho module mượn sách.",
                "s2",
                2,
            ),
            _paragraph(
                "p3", "Nhóm đề xuất hướng phát triển giao diện di động.", "s3", 3
            ),
        ],
        "tables": [],
    }


async def _insert_ir(
    connection: AsyncConnection, version_id: uuid.UUID, content: dict
) -> None:
    await connection.execute(
        text("""
            INSERT INTO public.document_irs (
                id, document_version_id, schema_version, parser_version, content
            ) VALUES (:id, :version, 1, 'test-parser', CAST(:content AS jsonb))
        """),
        {"id": uuid.uuid4(), "version": version_id, "content": json.dumps(content)},
    )


def _run(
    scenario: Callable[[AsyncSession, dict[str, uuid.UUID]], Awaitable[None]],
) -> None:
    async def wrapper() -> None:
        engine = create_async_engine(get_settings().database_url, poolclass=NullPool)
        connection = await engine.connect()
        transaction = await connection.begin()
        # Service-level commits become savepoints; everything is rolled back.
        session = AsyncSession(
            bind=connection,
            expire_on_commit=False,
            join_transaction_mode="create_savepoint",
        )
        try:
            ids = _ids()
            await _seed_graph(connection, ids)
            await _insert_ir(connection, ids["document_2"], _report_ir())
            await scenario(session, ids)
        finally:
            await session.close()
            await transaction.rollback()
            await connection.close()
            await engine.dispose()

    asyncio.run(wrapper())


def test_index_is_idempotent_and_retrieval_finds_right_page() -> None:
    async def scenario(session: AsyncSession, ids: dict[str, uuid.UUID]) -> None:
        provider = FakeEmbeddingProvider()
        version = ids["document_2"]
        assert await index_document_version(session, version, provider) == "indexed"
        assert (
            await index_document_version(session, version, provider)
            == "already_indexed"
        )
        assert (
            await index_document_version(session, ids["document_3"], provider)
            == "no_document_ir"
        )

        chunks = await retrieve_chunks(
            session, [version], "kiểm thử đơn vị", provider=provider
        )
        assert chunks, "expected at least one hit"
        assert chunks[0].page_start == 2
        assert "kiểm thử đơn vị" in chunks[0].text
        assert chunks[0].section_path == "3. Kiểm thử"

    _run(scenario)


def test_retrieval_never_leaves_the_given_scope() -> None:
    async def scenario(session: AsyncSession, ids: dict[str, uuid.UUID]) -> None:
        provider = FakeEmbeddingProvider()
        await index_document_version(session, ids["document_2"], provider)
        await index_document_version(session, ids["document_1"], provider)
        hits = await retrieve_chunks(
            session, [ids["document_1"]], "kiểm thử đơn vị", provider=provider
        )
        assert all(hit.document_version_id == ids["document_1"] for hit in hits)
        assert await retrieve_chunks(session, [], "kiểm thử", provider=provider) == []

    _run(scenario)


def test_keyword_only_retrieval_without_embeddings() -> None:
    async def scenario(session: AsyncSession, ids: dict[str, uuid.UUID]) -> None:
        version = ids["document_2"]
        outcome = await index_document_version(session, version, None)
        assert outcome == "indexed_without_embeddings"
        chunks = await retrieve_chunks(session, [version], "pytest", provider=None)
        assert [chunk.page_start for chunk in chunks] == [2]
        # A later run with a provider fills the missing vectors in place.
        filled = await index_document_version(session, version, FakeEmbeddingProvider())
        assert filled == "embeddings_filled"

    _run(scenario)


def test_search_content_chat_returns_excerpt_page_and_citations() -> None:
    async def scenario(session: AsyncSession, ids: dict[str, uuid.UUID]) -> None:
        await index_document_version(session, ids["document_2"], None)
        teacher = _actor(ids["teacher"], "Teacher A", UserRole.TEACHER)
        response = await handle_chat(
            session,
            user=teacher,
            message="Tìm đoạn nói về kiểm thử đơn vị",
            course_id=None,
            assignment_id=None,
            submission_id=ids["submission_2"],
        )
        assert response.intent == Intent.SEARCH_CONTENT
        assert response.citations
        first = response.citations[0]
        assert first.page == 2
        assert first.section_path == "3. Kiểm thử"
        assert first.submission_id == ids["submission_2"]
        assert "kiểm thử đơn vị" in first.excerpt
        assert "Trang 2" in response.reply

        # Course scope searches every latest version in the course.
        course_wide = await handle_chat(
            session,
            user=teacher,
            message="Tìm đoạn nói về pytest",
            course_id=ids["course"],
            assignment_id=None,
        )
        assert course_wide.citations and course_wide.citations[0].page == 2
        assert "Student 2" in course_wide.reply

    _run(scenario)


def test_search_content_denies_other_teachers_submission() -> None:
    async def scenario(session: AsyncSession, ids: dict[str, uuid.UUID]) -> None:
        await index_document_version(session, ids["document_2"], None)
        outsider = _actor(ids["other_teacher"], "Teacher B", UserRole.TEACHER)
        with pytest.raises(HTTPException) as error:
            await handle_chat(
                session,
                user=outsider,
                message="Tìm đoạn nói về kiểm thử",
                course_id=None,
                assignment_id=None,
                submission_id=ids["submission_2"],
            )
        assert error.value.status_code == 404

        teacher = _actor(ids["teacher"], "Teacher A", UserRole.TEACHER)
        with pytest.raises(HTTPException) as mismatch:
            await handle_chat(
                session,
                user=teacher,
                message="Tìm đoạn nói về kiểm thử",
                course_id=uuid.uuid4(),
                assignment_id=None,
                submission_id=ids["submission_2"],
            )
        assert mismatch.value.status_code == 404

    _run(scenario)


def test_ask_about_requirement_keeps_only_verified_citations(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    forged = uuid.uuid4()

    def respond(_system: str, prompt: str) -> str:
        real_id = re.search(r"\[chunk:([0-9a-f-]{36})\]", prompt).group(1)
        return f"Có, nhóm dùng pytest [chunk:{real_id}] và Selenium [chunk:{forged}]."

    client = FakeLLMClient(respond)
    monkeypatch.setattr(chat_service, "_rag_llm_client", lambda: client)

    async def scenario(session: AsyncSession, ids: dict[str, uuid.UUID]) -> None:
        await index_document_version(session, ids["document_2"], None)
        teacher = _actor(ids["teacher"], "Teacher A", UserRole.TEACHER)
        response = await handle_chat(
            session,
            user=teacher,
            message="Bài này có đề cập đến kiểm thử đơn vị không?",
            course_id=None,
            assignment_id=None,
            submission_id=ids["submission_2"],
        )
        assert response.intent == Intent.ASK_ABOUT_REQUIREMENT
        assert response.reply == "Có, nhóm dùng pytest [1] và Selenium."
        assert [c.page for c in response.citations] == [2]
        assert str(forged) not in response.reply
        assert len(client.calls) == 1

    _run(scenario)


def test_ask_about_requirement_without_llm_key_returns_passages() -> None:
    async def scenario(session: AsyncSession, ids: dict[str, uuid.UUID]) -> None:
        await index_document_version(session, ids["document_2"], None)
        teacher = _actor(ids["teacher"], "Teacher A", UserRole.TEACHER)
        response = await handle_chat(
            session,
            user=teacher,
            message="Bài này có đề cập đến kiểm thử đơn vị không?",
            course_id=None,
            assignment_id=None,
            submission_id=ids["submission_2"],
        )
        assert response.intent == Intent.ASK_ABOUT_REQUIREMENT
        assert "LLM_API_KEY" in response.reply
        assert response.citations and response.citations[0].page == 2

    _run(scenario)


def test_keyword_retrieval_falls_back_to_substring_for_glued_words() -> None:
    async def scenario(session: AsyncSession, ids: dict[str, uuid.UUID]) -> None:
        await _insert_ir(
            session.bind,
            ids["document_3"],
            {
                **_report_ir(),
                "paragraphs": [
                    _paragraph("g1", "HệthốngdùngGraphRAGđểtruyxuất.", "s1", 1)
                ],
            },
        )
        await index_document_version(session, ids["document_3"], None)
        hits = await retrieve_chunks(session, [ids["document_3"]], "graphrag")
        assert [hit.page_start for hit in hits] == [1]

    _run(scenario)


def test_summarize_submission_is_cached_after_first_llm_call(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = FakeLLMClient("**Mục tiêu:** Quản lý thư viện.\n**Phạm vi:** ...")
    monkeypatch.setattr(chat_service, "_rag_llm_client", lambda: client)

    async def scenario(session: AsyncSession, ids: dict[str, uuid.UUID]) -> None:
        await index_document_version(session, ids["document_2"], None)
        teacher = _actor(ids["teacher"], "Teacher A", UserRole.TEACHER)

        async def ask() -> object:
            return await handle_chat(
                session,
                user=teacher,
                message="Tóm tắt bài này",
                course_id=None,
                assignment_id=None,
                submission_id=ids["submission_2"],
            )

        first = await ask()
        assert first.intent == Intent.SUMMARIZE_SUBMISSION
        assert first.reply.startswith("**Mục tiêu:**")
        assert len(client.calls) == 1
        # Whole document fits the direct budget -> sections sent in one prompt.
        assert "## 3. Kiểm thử" in client.calls[0]["prompt"]

        second = await ask()
        assert second.reply == first.reply
        assert len(client.calls) == 1, "second ask must come from the cache"

        stored = await session.scalar(
            text(
                "SELECT model_version FROM public.document_summaries "
                "WHERE document_version_id = :v"
            ),
            {"v": ids["document_2"]},
        )
        assert stored == "fake-llm"

    _run(scenario)


def test_summaries_are_per_document_version(monkeypatch: pytest.MonkeyPatch) -> None:
    client = FakeLLMClient(lambda _s, prompt: f"Tóm tắt dài {len(prompt)}")

    async def scenario(session: AsyncSession, ids: dict[str, uuid.UUID]) -> None:
        for version in (ids["document_1"], ids["document_2"]):
            await index_document_version(session, version, None)
        one = await summarize_document(session, ids["document_1"], client)
        two = await summarize_document(session, ids["document_2"], client)
        assert one and two and not one.cached and not two.cached
        assert one.text != two.text
        assert len(client.calls) == 2
        assert await summarize_document(session, ids["document_3"], client) is None

    _run(scenario)


def test_summarize_needs_submission_and_respects_ownership() -> None:
    async def scenario(session: AsyncSession, ids: dict[str, uuid.UUID]) -> None:
        teacher = _actor(ids["teacher"], "Teacher A", UserRole.TEACHER)
        response = await handle_chat(
            session,
            user=teacher,
            message="Tóm tắt bài này",
            course_id=ids["course"],
            assignment_id=None,
        )
        assert response.needs_submission is True
        assert response.intent == Intent.SUMMARIZE_SUBMISSION

        outsider = _actor(ids["other_teacher"], "Teacher B", UserRole.TEACHER)
        with pytest.raises(HTTPException) as error:
            await handle_chat(
                session,
                user=outsider,
                message="Tóm tắt bài này",
                course_id=None,
                assignment_id=None,
                submission_id=ids["submission_2"],
            )
        assert error.value.status_code == 404

    _run(scenario)
