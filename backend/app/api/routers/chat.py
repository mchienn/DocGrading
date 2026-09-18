from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_roles
from app.api.schemas_chat import ChatRequest, ChatResponse
from app.db.session import get_db_session
from app.models.enums import UserRole
from app.models.identity import User
from app.services.chat import handle_chat

router = APIRouter(prefix="/chat", tags=["chat"])


@router.post("", response_model=ChatResponse)
async def chat(
    body: ChatRequest,
    user: User = Depends(require_roles(UserRole.ADMIN, UserRole.TEACHER)),
    db: AsyncSession = Depends(get_db_session),
) -> ChatResponse:
    """Answer a teacher's free-text question about their own course's grading status."""
    return await handle_chat(
        db,
        user=user,
        message=body.message,
        course_id=body.course_id,
        assignment_id=body.assignment_id,
    )