from __future__ import annotations

import asyncio
import json
import os
import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime

import pytest
from httpx2 import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.pool import NullPool

from app.api.deps import get_current_user
from app.api.schemas_chat import ChatScopeSubmission
from app.core.config import get_settings
from app.db.session import get_db_session
from app.main import create_app
from app.models.enums import UserRole
from app.services import chat as chat_service
from app.services.auth import auth_cookie_names, csrf_token_for_session
from app.services.chat import (
    ROUTER_HISTORY_TURNS,
    ROUTER_SYSTEM_PROMPT,
    Intent,
    RoutedQuestion,
    build_router_prompt,
    classify_intent,
    extract_submission_reference,
    find_submissions_by_reference,
    handle_chat,
    parse_route,
    route_with_llm,
)
from app.services.rag import FakeLLMClient
from app.workers.index_document_chunks import index_document_version
from tests.test_rag_retrieval import _insert_ir, _report_ir
from tests.test_t011_review_workspace import _actor, _ids, _seed_graph

# --- keyword intent + reference extraction -----------------------------------


@pytest.mark.parametrize(
    ("message", "expected"),
    [
        ("tôi muốn xem bài báo cáo OPRO", Intent.OPEN_SUBMISSION),
        ("Mở file của An", Intent.OPEN_SUBMISSION),
        ("xem bao cao LightRAG", Intent.OPEN_SUBMISSION),
        # Existing intents keep their meaning.
        ("Tìm đoạn nói về xem bài", Intent.SEARCH_CONTENT),
        ("Tóm tắt bài của An", Intent.SUMMARIZE_SUBMISSION),
        ("Hôm nay có yêu cầu xem lại nào mới không?", Intent.NEW_REVIEW_REQUESTS),
    ],
)
def test_open_submission_keywords(message: str, expected: Intent) -> None:
    assert classify_intent(message) is expected


@pytest.mark.parametrize(
    ("message", "reference"),
    [
        ("tôi muốn xem bài báo cáo OPRO", "OPRO"),
        ("Mở file của sinh viên Nguyễn Văn An", "Nguyễn Văn An"),
        ("xem bài nộp này", ""),
    ],
)
def test_extract_submission_reference(message: str, reference: str) -> None:
    assert extract_submission_reference(message) == reference


def _candidate(name: str, file_name: str) -> ChatScopeSubmission:
    return ChatScopeSubmission(
        submission_id=uuid.uuid4(),
        document_version_id=uuid.uuid4(),
        student_name=name,
        student_email="x@y",
        assignment_title="SRS",
        file_name=file_name,
        submitted_at=datetime(2026, 9, 25, tzinfo=UTC),
    )


OPRO = _candidate("[N8] - OPRO", "[N8] - OPRO.pdf")
EVOPROMPT = _candidate("[N14] - EvoPrompt", "[N14] - EvoPrompt.pdf")
LIGHTRAG = _candidate("[N3] - LightRAG", "[N3] - LightRAG.pdf")
CONG = _candidate("côngtrầnvăn", "cong_[Nhóm13] [LoFTR].pdf")


def test_whole_word_match_beats_substring() -> None:
    # "opro" is also a substring of "EvoPrompt"; the exact word must win.
    assert find_submissions_by_reference("OPRO", [EVOPROMPT, OPRO]) == [OPRO]
    assert find_submissions_by_reference("prompt", [EVOPROMPT, OPRO]) == [EVOPROMPT]


def test_reference_matches_file_or_student_name_without_diacritics() -> None:
    candidates = [OPRO, LIGHTRAG, CONG]
    assert find_submissions_by_reference("opro", candidates) == [OPRO]
    assert find_submissions_by_reference("congtranvan", candidates) == [CONG]
    assert find_submissions_by_reference("LoFTR", candidates) == [CONG]
    assert find_submissions_by_reference("RAG", candidates) == [LIGHTRAG]
    assert find_submissions_by_reference("N", candidates) == []
    assert find_submissions_by_reference("khongcobainay", candidates) == []


# --- LLM router output parsing -------------------------------------------------


def test_parse_route_accepts_valid_json_even_with_surrounding_text() -> None:
    raw = 'Kết quả: {"intent": "open_submission", "question": "Xem bài  OPRO"} xong'
    assert parse_route(raw) == RoutedQuestion(Intent.OPEN_SUBMISSION, "Xem bài OPRO")


def test_parse_route_keeps_target_as_plain_text() -> None:
    raw = '{"intent": "ASK_ABOUT_REQUIREMENT", "question": "q", "target": " OPRO "}'
    assert parse_route(raw).target == "OPRO"
    no_target = '{"intent": "SUMMARY", "question": "q", "target": 42}'
    assert parse_route(no_target).target == ""


@pytest.mark.parametrize(
    "raw",
    [
        "không phải json",
        '{"intent": "DROP_TABLES", "question": "x"}',
        '{"intent": "GREETING", "question": "Xin chào"}',  # not routable
        '{"intent": "SUMMARY"}',
        '{"intent": "SUMMARY", "question": "   "}',
        '["SUMMARY"]',
    ],
)
def test_parse_route_rejects_anything_unexpected(raw: str) -> None:
    assert parse_route(raw) is None


def test_router_prompt_keeps_only_recent_teacher_questions() -> None:
    history = [f"câu {i}" for i in range(10)]
    prompt = build_router_prompt("bài đó thì sao?", history)
    assert "câu 3" not in prompt
    assert all(f"câu {i}" in prompt for i in range(10 - ROUTER_HISTORY_TURNS, 10))
    assert prompt.rstrip().endswith("Câu hỏi hiện tại: bài đó thì sao?")


def test_route_with_llm_uses_router_prompt_and_history() -> None:
    client = FakeLLMClient(
        json.dumps({"intent": "ASK_ABOUT_REQUIREMENT",
                    "question": "Bài OPRO có đề cập đến kiểm thử không?"})
    )  # fmt: skip
    routed = asyncio.run(
        route_with_llm("bài đó có kiểm thử không", ["Xem bài OPRO"], client)
    )
    assert routed == RoutedQuestion(
        Intent.ASK_ABOUT_REQUIREMENT, "Bài OPRO có đề cập đến kiểm thử không?"
    )
    [call] = client.calls
    assert call["system"] == ROUTER_SYSTEM_PROMPT
    assert "Xem bài OPRO" in call["prompt"]


def test_unknown_question_without_llm_key_still_gets_help() -> None:
    # conftest forces an unconfigured LLM client: routing is skipped quietly.
    response = asyncio.run(
        handle_chat(
            None,  # type: ignore[arg-type]  # UNKNOWN never touches the DB
            user=_actor(uuid.uuid4(), "T", UserRole.TEACHER),
            message="thời tiết hôm nay thế nào",
            course_id=None,
            assignment_id=None,
        )
    )
    assert response.intent == Intent.UNKNOWN
    assert "chưa hiểu" in response.reply


# --- DB integration --------------------------------------------------------------

requires_db = pytest.mark.skipif(
    os.environ.get("RUN_DATABASE_TESTS") != "1",
    reason="Database integration tests require RUN_DATABASE_TESTS=1",
)


def _run(scenario) -> None:
    async def wrapper() -> None:
        engine = create_async_engine(get_settings().database_url, poolclass=NullPool)
        connection = await engine.connect()
        transaction = await connection.begin()
        session = AsyncSession(
            bind=connection,
            expire_on_commit=False,
            join_transaction_mode="create_savepoint",
        )
        try:
            ids = _ids()
            await _seed_graph(connection, ids)
            await scenario(session, ids)
        finally:
            await session.close()
            await transaction.rollback()
            await connection.close()
            await engine.dispose()

    asyncio.run(wrapper())


async def _ask(session, ids, message, **scope):
    scope.setdefault("course_id", ids["course"])
    scope.setdefault("assignment_id", None)
    teacher = _actor(ids["teacher"], "Teacher A", UserRole.TEACHER)
    return await handle_chat(session, user=teacher, message=message, **scope)


@requires_db
def test_open_submission_by_file_name_opens_exactly_that_one() -> None:
    async def scenario(session: AsyncSession, ids: dict[str, uuid.UUID]) -> None:
        response = await _ask(session, ids, "Tôi muốn xem bài two")
        assert response.intent == Intent.OPEN_SUBMISSION
        assert response.needs_clarification is None
        assert response.open_document.submission_id == ids["submission_2"]
        assert response.open_document.document_version_id == ids["document_2"]

        missing = await _ask(session, ids, "xem bài OPRO")
        assert missing.open_document is None
        assert 'khớp với "OPRO"' in missing.reply

    _run(scenario)


@requires_db
def test_open_submission_ambiguous_or_unnamed_asks_which() -> None:
    async def scenario(session: AsyncSession, ids: dict[str, uuid.UUID]) -> None:
        ambiguous = await _ask(session, ids, "xem bài Student")
        assert ambiguous.needs_clarification == "submission"
        assert len(ambiguous.clarification_options) == 3
        # The picked option is re-sent with its submission_id and opens it.
        picked = await _ask(
            session,
            ids,
            ambiguous.pending_message,
            submission_id=ambiguous.clarification_options[0].id,
        )
        assert picked.open_document.submission_id == (
            ambiguous.clarification_options[0].id
        )

        no_course = await _ask(session, ids, "xem bài two", course_id=None)
        assert no_course.needs_clarification == "course"

    _run(scenario)


@requires_db
def test_follow_up_question_is_routed_with_context(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def respond(system: str, prompt: str) -> str:
        if system == ROUTER_SYSTEM_PROMPT:
            assert "Tôi muốn xem bài two" in prompt  # previous teacher question
            return json.dumps(
                {"intent": "ASK_ABOUT_REQUIREMENT",
                 "question": "Bài này có đề cập đến pytest không?"}
            )  # fmt: skip
        chunk_id = prompt.split("[chunk:", 1)[1].split("]", 1)[0]
        return f"Có, nhóm dùng pytest [chunk:{chunk_id}]."

    client = FakeLLMClient(respond)
    monkeypatch.setattr(chat_service, "_rag_llm_client", lambda: client)

    async def scenario(session: AsyncSession, ids: dict[str, uuid.UUID]) -> None:
        await _insert_ir(session.bind, ids["document_3"], _report_ir())
        await index_document_version(session, ids["document_3"], None)
        response = await _ask(
            session,
            ids,
            "thế nhóm đó test bằng gì",  # no keyword matches this
            submission_id=ids["submission_3"],
            history=["Tôi muốn xem bài two", "Tôi muốn xem bài three"],
        )
        assert response.intent == Intent.ASK_ABOUT_REQUIREMENT
        assert response.reply == "Có, nhóm dùng pytest [1]."
        assert [c.page for c in response.citations] == [2]
        assert [call["system"] == ROUTER_SYSTEM_PROMPT for call in client.calls] == [
            True,
            False,
        ]

    _run(scenario)


@requires_db
def test_session_remembers_opened_document_and_feeds_history(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    prompts: list[str] = []

    def respond(system: str, prompt: str) -> str:
        prompts.append(prompt)
        return json.dumps({"intent": "UNKNOWN", "question": "ngoài lề"})

    monkeypatch.setattr(chat_service, "_rag_llm_client", lambda: FakeLLMClient(respond))

    async def scenario(session: AsyncSession, ids: dict[str, uuid.UUID]) -> None:
        application = create_app()

        async def db_override() -> AsyncIterator[AsyncSession]:
            yield session

        application.dependency_overrides[get_db_session] = db_override
        application.dependency_overrides[get_current_user] = lambda: _actor(
            ids["teacher"], "Teacher A", UserRole.TEACHER
        )
        sid = uuid.uuid4()
        token = csrf_token_for_session(sid)
        session_cookie, csrf_cookie = auth_cookie_names(False)
        headers = {
            "Cookie": f"{session_cookie}={sid}; {csrf_cookie}={token}",
            "X-CSRF-Token": token,
        }
        async with AsyncClient(
            transport=ASGITransport(app=application), base_url="http://test"
        ) as client:
            chat_session = (
                await client.post("/api/v1/chat/sessions", json={}, headers=headers)
            ).json()
            opened = await client.post(
                "/api/v1/chat",
                json={
                    "message": "Tôi muốn xem bài two",
                    "course_id": str(ids["course"]),
                    "session_id": chat_session["id"],
                },
                headers=headers,
            )
            assert opened.json()["open_document"]["submission_id"] == str(
                ids["submission_2"]
            )
            [saved] = (
                await client.get("/api/v1/chat/sessions", headers=headers)
            ).json()
            assert saved["submission_id"] == str(ids["submission_2"])

            await client.post(
                "/api/v1/chat",
                json={
                    "message": "thời tiết hôm nay thế nào",
                    "course_id": str(ids["course"]),
                    "session_id": chat_session["id"],
                },
                headers=headers,
            )
        [router_prompt] = prompts
        assert "Tôi muốn xem bài two" in router_prompt
        stored = await session.scalar(
            text(
                "SELECT count(*) FROM public.chat_messages "
                "WHERE session_id = CAST(:s AS uuid)"
            ),
            {"s": chat_session["id"]},
        )
        assert stored == 4

    _run(scenario)


@requires_db
def test_routed_target_narrows_scope_to_that_submission(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def respond(system: str, prompt: str) -> str:
        if system == ROUTER_SYSTEM_PROMPT:
            return json.dumps(
                {"intent": "ASK_ABOUT_REQUIREMENT",
                 "question": "Bài three kiểm thử bằng gì?", "target": "three"}
            )  # fmt: skip
        assert "Nhóm viết kiểm thử" in prompt  # only document_3's chunks
        chunk_id = prompt.split("[chunk:", 1)[1].split("]", 1)[0]
        return f"Dùng pytest [chunk:{chunk_id}]."

    monkeypatch.setattr(chat_service, "_rag_llm_client", lambda: FakeLLMClient(respond))

    async def scenario(session: AsyncSession, ids: dict[str, uuid.UUID]) -> None:
        await _insert_ir(session.bind, ids["document_3"], _report_ir())
        for version in ("document_1", "document_3"):
            await index_document_version(session, ids[version], None)
        response = await _ask(session, ids, "thế nhóm đó test bằng gì")
        assert response.intent == Intent.ASK_ABOUT_REQUIREMENT
        assert {c.submission_id for c in response.citations} == {ids["submission_3"]}

    _run(scenario)
