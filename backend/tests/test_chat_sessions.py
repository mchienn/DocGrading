from __future__ import annotations

import asyncio
import os
import uuid
from collections.abc import AsyncIterator

import pytest
from httpx2 import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.pool import NullPool

from app.api.deps import get_current_user
from app.api.schemas_chat import ChatResponse, ChatStats
from app.core.config import get_settings
from app.db.session import get_db_session
from app.main import create_app
from app.models.enums import UserRole
from app.services.auth import auth_cookie_names, csrf_token_for_session
from app.services.chat_session import (
    DEFAULT_TITLE,
    TITLE_MAX_CHARS,
    bot_payload,
    title_from_message,
)
from tests.test_t011_review_workspace import _actor, _ids, _seed_graph


def test_title_from_first_question_is_one_trimmed_line() -> None:
    assert (
        title_from_message("  Tình hình\n lớp  thế nào? ") == "Tình hình lớp thế nào?"
    )
    long_title = title_from_message("x " * 100)
    assert len(long_title) == TITLE_MAX_CHARS and long_title.endswith("…")
    assert title_from_message("   ") == DEFAULT_TITLE


def test_bot_payload_keeps_structure_but_not_the_text() -> None:
    response = ChatResponse(
        reply="text",
        intent="SUMMARY",
        stats=ChatStats(
            total_students=3, submitted=2, reviewed=1, pending_review=1, errors=0
        ),
        session_id=uuid.uuid4(),
    )
    payload = bot_payload(response)
    assert "reply" not in payload and "session_id" not in payload
    assert payload["intent"] == "SUMMARY"
    assert payload["stats"]["submitted"] == 2


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


def _client(session: AsyncSession, user_id: uuid.UUID) -> tuple[AsyncClient, dict]:
    application = create_app()

    async def db_override() -> AsyncIterator[AsyncSession]:
        yield session

    application.dependency_overrides[get_db_session] = db_override
    application.dependency_overrides[get_current_user] = lambda: _actor(
        user_id, "Teacher", UserRole.TEACHER
    )
    session_id = uuid.uuid4()
    token = csrf_token_for_session(session_id)
    session_cookie, csrf_cookie = auth_cookie_names(False)
    headers = {
        "Cookie": f"{session_cookie}={session_id}; {csrf_cookie}={token}",
        "X-CSRF-Token": token,
    }
    client = AsyncClient(
        transport=ASGITransport(app=application), base_url="http://test"
    )
    return client, headers


@requires_db
def test_chat_turns_are_saved_and_private_to_their_owner() -> None:
    async def scenario(session: AsyncSession, ids: dict[str, uuid.UUID]) -> None:
        owner, headers = _client(session, ids["teacher"])
        async with owner:
            created = await owner.post(
                "/api/v1/chat/sessions", json={}, headers=headers
            )
            assert created.status_code == 201, created.text
            chat_session = created.json()
            assert chat_session["title"] == DEFAULT_TITLE

            answer = await owner.post(
                "/api/v1/chat",
                json={
                    "message": "Tình hình báo cáo lớp thế nào?",
                    "course_id": str(ids["course"]),
                    "session_id": chat_session["id"],
                },
                headers=headers,
            )
            assert answer.status_code == 200, answer.text
            assert answer.json()["session_id"] == chat_session["id"]

            messages = (
                await owner.get(
                    f"/api/v1/chat/sessions/{chat_session['id']}/messages",
                    headers=headers,
                )
            ).json()
            assert [m["sender"] for m in messages] == ["user", "bot"]
            assert messages[0]["content"] == "Tình hình báo cáo lớp thế nào?"
            assert messages[1]["payload"]["intent"] == "SUMMARY"
            assert messages[1]["payload"]["stats"]["submitted"] == 3

            [listed] = (
                await owner.get("/api/v1/chat/sessions", headers=headers)
            ).json()
            assert listed["title"] == "Tình hình báo cáo lớp thế nào?"
            assert listed["course_id"] == str(ids["course"])

        outsider, other_headers = _client(session, ids["other_teacher"])
        async with outsider:
            url = f"/api/v1/chat/sessions/{chat_session['id']}"
            assert (
                await outsider.get(f"{url}/messages", headers=other_headers)
            ).status_code == 404
            assert (
                await outsider.patch(
                    url, json={"is_pinned": True}, headers=other_headers
                )
            ).status_code == 404
            assert (
                await outsider.delete(url, headers=other_headers)
            ).status_code == 404
            hijack = await outsider.post(
                "/api/v1/chat",
                json={"message": "Xin chào", "session_id": chat_session["id"]},
                headers=other_headers,
            )
            assert hijack.status_code == 404
            assert (
                await outsider.get("/api/v1/chat/sessions", headers=other_headers)
            ).json() == []

    _run(scenario)


@requires_db
def test_pinned_sessions_list_first_and_delete_removes_them() -> None:
    async def scenario(session: AsyncSession, ids: dict[str, uuid.UUID]) -> None:
        client, headers = _client(session, ids["teacher"])
        async with client:
            first = (
                await client.post(
                    "/api/v1/chat/sessions", json={"title": "A"}, headers=headers
                )
            ).json()
            second = (
                await client.post(
                    "/api/v1/chat/sessions",
                    json={"title": "B", "course_id": "all"},
                    headers=headers,
                )
            ).json()
            assert second["all_courses"] is True
            pinned = await client.patch(
                f"/api/v1/chat/sessions/{first['id']}",
                json={"is_pinned": True},
                headers=headers,
            )
            assert pinned.json()["is_pinned"] is True
            titles = [
                s["title"]
                for s in (
                    await client.get("/api/v1/chat/sessions", headers=headers)
                ).json()
            ]
            assert titles == ["A", "B"]

            deleted = await client.delete(
                f"/api/v1/chat/sessions/{first['id']}", headers=headers
            )
            assert deleted.status_code == 204
            gone = await client.get(
                f"/api/v1/chat/sessions/{first['id']}/messages", headers=headers
            )
            assert gone.status_code == 404

    _run(scenario)


@requires_db
def test_session_scope_is_authorized_when_set() -> None:
    async def scenario(session: AsyncSession, ids: dict[str, uuid.UUID]) -> None:
        outsider, headers = _client(session, ids["other_teacher"])
        async with outsider:
            response = await outsider.post(
                "/api/v1/chat/sessions",
                json={"course_id": str(ids["course"])},
                headers=headers,
            )
            assert response.status_code == 404
            response = await outsider.post(
                "/api/v1/chat/sessions",
                json={"submission_id": str(ids["submission_1"])},
                headers=headers,
            )
            assert response.status_code == 404

    _run(scenario)


@requires_db
def test_scope_picker_lists_course_submissions_for_owner_only() -> None:
    async def scenario(session: AsyncSession, ids: dict[str, uuid.UUID]) -> None:
        owner, headers = _client(session, ids["teacher"])
        async with owner:
            rows = (
                await owner.get(
                    f"/api/v1/chat/courses/{ids['course']}/submissions",
                    headers=headers,
                )
            ).json()
            assert [r["student_name"] for r in rows] == [
                "Student 1",
                "Student 2",
                "Student 3",
            ]
            assert rows[0]["file_name"] == "one.pdf"
        outsider, other_headers = _client(session, ids["other_teacher"])
        async with outsider:
            denied = await outsider.get(
                f"/api/v1/chat/courses/{ids['course']}/submissions",
                headers=other_headers,
            )
            assert denied.status_code == 404

    _run(scenario)
