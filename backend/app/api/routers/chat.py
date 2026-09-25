from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_roles
from app.api.schemas_chat import (
    ChatMessageResponse,
    ChatRequest,
    ChatResponse,
    ChatScopeSubmission,
    ChatSessionCreate,
    ChatSessionResponse,
    ChatSessionUpdate,
)
from app.db.session import get_db_session
from app.models.course import Course
from app.models.enums import UserRole
from app.models.identity import User
from app.services import chat_session as session_svc
from app.services.chat import _authorize, handle_chat, submission_candidates

router = APIRouter(prefix="/chat", tags=["chat"])

_chat_user = require_roles(UserRole.ADMIN, UserRole.TEACHER)


@router.post("", response_model=ChatResponse)
async def chat(
    body: ChatRequest,
    user: User = Depends(_chat_user),
    db: AsyncSession = Depends(get_db_session),
) -> ChatResponse:
    """Answer a teacher's free-text question about their own course's grading status."""
    session = (
        await session_svc.get_owned_session(db, user, body.session_id)
        if body.session_id is not None
        else None
    )
    response = await handle_chat(
        db,
        user=user,
        message=body.message,
        course_id=body.course_id,
        assignment_id=body.assignment_id,
        submission_id=body.submission_id,
    )
    if session is not None:
        await session_svc.record_turn(db, session, body, response)
        await db.commit()
        response.session_id = session.id
    return response


@router.get(
    "/courses/{course_id}/submissions", response_model=list[ChatScopeSubmission]
)
async def chat_scope_submissions(
    course_id: uuid.UUID,
    user: User = Depends(_chat_user),
    db: AsyncSession = Depends(get_db_session),
) -> list[ChatScopeSubmission]:
    """Submissions of an owned course, for the "Phạm vi" picker."""
    course = _authorize(user, await db.get(Course, course_id))
    return await submission_candidates(db, course.id)


@router.get("/sessions", response_model=list[ChatSessionResponse])
async def list_chat_sessions(
    user: User = Depends(_chat_user),
    db: AsyncSession = Depends(get_db_session),
) -> list[ChatSessionResponse]:
    sessions = await session_svc.list_sessions(db, user)
    return [ChatSessionResponse.model_validate(s) for s in sessions]


@router.post(
    "/sessions",
    response_model=ChatSessionResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_chat_session(
    body: ChatSessionCreate,
    user: User = Depends(_chat_user),
    db: AsyncSession = Depends(get_db_session),
) -> ChatSessionResponse:
    session = await session_svc.create_session(db, user, body)
    await db.commit()
    return ChatSessionResponse.model_validate(session)


@router.patch("/sessions/{session_id}", response_model=ChatSessionResponse)
async def update_chat_session(
    session_id: uuid.UUID,
    body: ChatSessionUpdate,
    user: User = Depends(_chat_user),
    db: AsyncSession = Depends(get_db_session),
) -> ChatSessionResponse:
    session = await session_svc.update_session(db, user, session_id, body)
    await db.commit()
    return ChatSessionResponse.model_validate(session)


@router.delete("/sessions/{session_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_chat_session(
    session_id: uuid.UUID,
    user: User = Depends(_chat_user),
    db: AsyncSession = Depends(get_db_session),
) -> Response:
    await session_svc.delete_session(db, user, session_id)
    await db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/sessions/{session_id}/messages", response_model=list[ChatMessageResponse])
async def list_chat_messages(
    session_id: uuid.UUID,
    user: User = Depends(_chat_user),
    db: AsyncSession = Depends(get_db_session),
) -> list[ChatMessageResponse]:
    messages = await session_svc.list_messages(db, user, session_id)
    return [ChatMessageResponse.model_validate(m) for m in messages]
