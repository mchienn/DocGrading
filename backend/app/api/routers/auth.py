"""Authentication endpoints: login, logout, session info."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Cookie, Depends, HTTPException, Response, status
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.api.schemas import LoginRequest, UserResponse
from app.db.session import get_db_session
from app.models.identity import User
from app.services.audit import record_audit
from app.services.auth import authenticate_user, create_session, revoke_session

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/login", response_model=UserResponse)
async def login(
    body: LoginRequest,
    db: AsyncSession = Depends(get_db_session),
) -> JSONResponse:
    """Authenticate with email + password, receive a session cookie."""
    user = await authenticate_user(db, body.email, body.password)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password",
        )
    session = await create_session(db, user.id)

    await record_audit(
        db,
        actor_user_id=user.id,
        resource_type="Session",
        resource_id=session.id,
        action="LOGIN",
        after={"session_id": str(session.id)},
        reason="User logged in",
    )

    await db.commit()

    data = UserResponse.model_validate(user).model_dump(mode="json")
    response = JSONResponse(content=data, status_code=200)
    response.set_cookie(
        key="session_id",
        value=str(session.id),
        httponly=True,
        samesite="lax",
        path="/api",
        max_age=int(
            (session.expires_at - session.created_at).total_seconds(),
        ),
    )
    return response


@router.post("/logout", status_code=204)
async def logout(
    response: Response,
    user: User = Depends(get_current_user),
    session_id: str | None = Cookie(None),
    db: AsyncSession = Depends(get_db_session),
) -> Response:
    """Revoke the current session and clear the cookie."""
    if session_id is not None:
        sid = uuid.UUID(session_id)
        await revoke_session(db, sid)
        await record_audit(
            db,
            actor_user_id=user.id,
            resource_type="Session",
            resource_id=sid,
            action="LOGOUT",
            before={"session_id": session_id},
            reason="User logged out",
        )
        await db.commit()
    response.delete_cookie(key="session_id", path="/api")
    return response


@router.get("/me", response_model=UserResponse)
async def me(
    user: User = Depends(get_current_user),
) -> UserResponse:
    """Return the currently authenticated user's profile."""
    return UserResponse.model_validate(user)
