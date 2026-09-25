"""Saved teacher chat sessions (tabs + "Lịch sử tra cứu").

A session belongs to exactly one user; any other user gets a 404, the same
way ``check_course_ownership`` hides courses. Scope ids stored on a session
are re-authorized every time they are set, and every chat turn is still
authorized again by ``handle_chat`` — the stored scope is only a UI default.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Literal

import sqlalchemy as sa
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.schemas_chat import (
    ALL_COURSES,
    ChatRequest,
    ChatResponse,
    ChatSessionCreate,
    ChatSessionUpdate,
)
from app.models.chat import ChatMessage, ChatSession
from app.models.course import Course
from app.models.identity import User
from app.services.chat import _authorize, _submission_scope

DEFAULT_TITLE = "Phiên tra cứu mới"
TITLE_MAX_CHARS = 60


def title_from_message(message: str) -> str:
    """First user question, trimmed to a one-line tab title."""
    title = " ".join(message.split())
    if len(title) > TITLE_MAX_CHARS:
        title = title[: TITLE_MAX_CHARS - 1].rstrip() + "…"
    return title or DEFAULT_TITLE


async def get_owned_session(
    db: AsyncSession, user: User, session_id: uuid.UUID
) -> ChatSession:
    session = await db.get(ChatSession, session_id)
    if session is None or session.owner_user_id != user.id:
        raise HTTPException(status_code=404, detail="Chat session not found")
    return session


async def _apply_scope(
    db: AsyncSession,
    user: User,
    session: ChatSession,
    course_id: uuid.UUID | Literal["all"] | None,
    submission_id: uuid.UUID | None,
) -> None:
    if course_id == ALL_COURSES:
        session.course_id, session.all_courses = None, True
    elif course_id is None:
        session.course_id, session.all_courses = None, False
    else:
        course = _authorize(user, await db.get(Course, course_id))
        session.course_id, session.all_courses = course.id, False
    if submission_id is not None:
        await _submission_scope(db, user, submission_id, session.course_id, None)
    session.submission_id = submission_id


async def list_sessions(db: AsyncSession, user: User) -> list[ChatSession]:
    stmt = (
        sa.select(ChatSession)
        .where(ChatSession.owner_user_id == user.id)
        .order_by(ChatSession.is_pinned.desc(), ChatSession.updated_at.desc())
    )
    return list((await db.execute(stmt)).scalars().all())


async def create_session(
    db: AsyncSession, user: User, body: ChatSessionCreate
) -> ChatSession:
    session = ChatSession(
        id=uuid.uuid4(),
        owner_user_id=user.id,
        title=(body.title or "").strip() or DEFAULT_TITLE,
    )
    await _apply_scope(db, user, session, body.course_id, body.submission_id)
    db.add(session)
    await db.flush()
    await db.refresh(session)
    return session


async def update_session(
    db: AsyncSession, user: User, session_id: uuid.UUID, body: ChatSessionUpdate
) -> ChatSession:
    session = await get_owned_session(db, user, session_id)
    changed = body.model_fields_set
    if "title" in changed and body.title is not None:
        title = body.title.strip()
        if not title:
            raise HTTPException(status_code=422, detail="Title must not be blank")
        session.title = title
    if "is_pinned" in changed and body.is_pinned is not None:
        session.is_pinned = body.is_pinned
    if "course_id" in changed or "submission_id" in changed:
        course_id = (
            body.course_id
            if "course_id" in changed
            else (ALL_COURSES if session.all_courses else session.course_id)
        )
        submission_id = (
            body.submission_id if "submission_id" in changed else session.submission_id
        )
        await _apply_scope(db, user, session, course_id, submission_id)
    session.updated_at = sa.func.now()
    await db.flush()
    await db.refresh(session)
    return session


async def delete_session(db: AsyncSession, user: User, session_id: uuid.UUID) -> None:
    session = await get_owned_session(db, user, session_id)
    await db.delete(session)
    await db.flush()


async def list_messages(
    db: AsyncSession, user: User, session_id: uuid.UUID
) -> list[ChatMessage]:
    await get_owned_session(db, user, session_id)
    stmt = (
        sa.select(ChatMessage)
        .where(ChatMessage.session_id == session_id)
        .order_by(ChatMessage.created_at)
    )
    return list((await db.execute(stmt)).scalars().all())


def bot_payload(response: ChatResponse) -> dict:
    """Everything the UI needs to re-render a bot turn, minus the text itself."""
    return response.model_dump(mode="json", exclude={"reply", "session_id"})


async def record_turn(
    db: AsyncSession,
    session: ChatSession,
    request: ChatRequest,
    response: ChatResponse,
) -> None:
    """Store the question + answer and remember the scope the turn used."""
    if session.title == DEFAULT_TITLE:
        session.title = title_from_message(request.message)
    session.all_courses = request.course_id == ALL_COURSES
    session.course_id = (
        request.course_id if isinstance(request.course_id, uuid.UUID) else None
    )
    session.submission_id = request.submission_id
    # Explicit times: now() is per transaction, so both rows would tie.
    asked_at = datetime.now(UTC)
    session.updated_at = asked_at
    db.add_all(
        [
            ChatMessage(
                id=uuid.uuid4(),
                session_id=session.id,
                sender="user",
                content=request.message,
                payload={},
                created_at=asked_at,
            ),
            ChatMessage(
                id=uuid.uuid4(),
                session_id=session.id,
                sender="bot",
                content=response.reply,
                payload=bot_payload(response),
                created_at=asked_at + timedelta(microseconds=1),
            ),
        ]
    )
    await db.flush()
