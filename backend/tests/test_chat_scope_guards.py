"""Chat must never 500 when the UI sends no / "all" / blank / bad course_id."""

from __future__ import annotations

import asyncio
import os
import uuid
from collections.abc import AsyncIterator

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from httpx2 import ASGITransport, AsyncClient
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.pool import NullPool

from app.api.deps import get_current_user
from app.api.schemas_chat import ChatRequest, ChatResponse
from app.core.config import get_settings
from app.db.session import get_db_session
from app.main import create_app
from app.models.enums import UserRole
from app.services.auth import auth_cookie_names, csrf_token_for_session
from app.services.chat import handle_chat, normalize_course_id
from tests.test_t011_review_workspace import _actor, _ids, _seed_graph

EVERY_INTENT_MESSAGE = [
    "Tình hình báo cáo lớp thế nào?",
    "Còn bao nhiêu bài chưa duyệt?",
    "Những bài nào đang lỗi?",
    "Bao nhiêu sinh viên chưa nộp?",
    "Hôm nay có yêu cầu xem lại nào mới không?",
    "Tìm đoạn nói về kiểm thử",
    "Bài này có đề cập đến kiểm thử không?",
    "Tóm tắt bài này",
    "Xin chào",
    "thời tiết thế nào",
]


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (None, None),
        ("", None),
        ("   ", None),
        ("all", "all"),
        ("ALL", "all"),
    ],
)
def test_normalize_course_id(raw: str | None, expected: str | None) -> None:
    assert normalize_course_id(raw) == expected


def test_normalize_course_id_parses_uuid_strings() -> None:
    value = uuid.uuid4()
    assert normalize_course_id(str(value)) == value
    assert normalize_course_id(value) == value


def test_normalize_course_id_rejects_garbage_with_422() -> None:
    with pytest.raises(HTTPException) as error:
        normalize_course_id("not-a-course")
    assert error.value.status_code == 422


def test_chat_request_blank_ids_mean_unset() -> None:
    request = ChatRequest(
        message="hi", course_id="", assignment_id="", submission_id=" "
    )
    assert (request.course_id, request.assignment_id, request.submission_id) == (
        None,
        None,
        None,
    )
    assert ChatRequest(message="hi", course_id="all").course_id == "all"


def test_chat_request_rejects_arbitrary_course_strings() -> None:
    with pytest.raises(ValidationError):
        ChatRequest(message="hi", course_id="abc")


def _client_as_teacher(monkeypatch: pytest.MonkeyPatch, db_override) -> tuple:
    monkeypatch.setenv("POSTGRES_DB", os.environ.get("POSTGRES_DB", "docgrading_test"))
    get_settings.cache_clear()
    application = create_app()
    teacher_id = uuid.uuid4()
    application.dependency_overrides[get_current_user] = lambda: _actor(
        teacher_id, "Teacher", UserRole.TEACHER
    )
    application.dependency_overrides[get_db_session] = db_override
    session_id = uuid.uuid4()
    token = csrf_token_for_session(session_id)
    session_cookie, csrf_cookie = auth_cookie_names(False)
    headers = {
        "Cookie": f"{session_cookie}={session_id}; {csrf_cookie}={token}",
        "X-CSRF-Token": token,
    }
    return application, headers


def test_endpoint_rejects_bad_course_id_with_422(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    application, headers = _client_as_teacher(monkeypatch, lambda: object())
    try:
        response = TestClient(application).post(
            "/api/v1/chat",
            json={"message": "Hôm nay có yêu cầu xem lại nào mới không?",
                  "course_id": "abc"},  # fmt: skip
            headers=headers,
        )
        assert response.status_code == 422
    finally:
        application.dependency_overrides.clear()
        get_settings.cache_clear()


requires_db = pytest.mark.skipif(
    os.environ.get("RUN_DATABASE_TESTS") != "1",
    reason="Database integration tests require RUN_DATABASE_TESTS=1",
)


async def _in_rolled_back_session(scenario) -> None:
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


@requires_db
@pytest.mark.parametrize("course_id", [None, "", "all"])
def test_every_intent_answers_without_a_specific_course(course_id: str | None) -> None:
    async def scenario(session: AsyncSession, ids: dict[str, uuid.UUID]) -> None:
        teacher = _actor(ids["teacher"], "Teacher A", UserRole.TEACHER)
        for message in EVERY_INTENT_MESSAGE:
            response = await handle_chat(
                session,
                user=teacher,
                message=message,
                course_id=course_id,
                assignment_id=None,
            )
            assert isinstance(response, ChatResponse), message
            assert response.reply.strip(), message

    asyncio.run(_in_rolled_back_session(scenario))


@requires_db
def test_all_courses_review_requests_endpoint_returns_200(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The exact bug report: "Tất cả lớp" + "yêu cầu xem lại mới" was a 500."""

    async def scenario(session: AsyncSession, ids: dict[str, uuid.UUID]) -> None:
        async def db_override() -> AsyncIterator[AsyncSession]:
            yield session

        application, headers = _client_as_teacher(monkeypatch, db_override)
        application.dependency_overrides[get_current_user] = lambda: _actor(
            ids["teacher"], "Teacher A", UserRole.TEACHER
        )
        try:
            # Same event loop as the test's DB connection (TestClient would not be).
            async with AsyncClient(
                transport=ASGITransport(app=application), base_url="http://test"
            ) as client:
                response = await client.post(
                    "/api/v1/chat",
                    json={
                        "message": "Hôm nay có yêu cầu xem lại nào mới không?",
                        "course_id": "all",
                    },
                    headers=headers,
                )
        finally:
            application.dependency_overrides.clear()
        assert response.status_code == 200, response.text
        assert response.json()["intent"] == "NEW_REVIEW_REQUESTS"

    asyncio.run(_in_rolled_back_session(scenario))
