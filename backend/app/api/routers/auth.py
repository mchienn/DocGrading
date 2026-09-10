"""Authentication endpoints: login, logout, session info."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.api.schemas import LoginRequest, UserResponse
from app.core.config import get_settings
from app.db.session import get_db_session
from app.models.identity import User
from app.services.audit import record_audit
from app.services.auth import (
    auth_cookie_names,
    authenticate_user,
    create_session,
    csrf_token_for_session,
    revoke_session,
)

router = APIRouter(prefix="/auth", tags=["auth"])


def _set_csrf_cookie(response: Response, session_id: uuid.UUID) -> None:
    settings = get_settings()
    _, csrf_cookie_name = auth_cookie_names(settings.session_cookie_secure)
    response.set_cookie(
        key=csrf_cookie_name,
        value=csrf_token_for_session(session_id),
        httponly=False,
        samesite="lax",
        path="/",
        secure=settings.session_cookie_secure,
        max_age=settings.session_lifetime_seconds,
    )


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
    settings = get_settings()
    session_cookie_name, _ = auth_cookie_names(settings.session_cookie_secure)
    response.set_cookie(
        key=session_cookie_name,
        value=str(session.id),
        httponly=True,
        samesite="lax",
        path="/",
        secure=settings.session_cookie_secure,
        max_age=int(
            (session.expires_at - session.created_at).total_seconds(),
        ),
    )
    _set_csrf_cookie(response, session.id)
    return response


@router.post("/logout", status_code=204)
async def logout(
    request: Request,
    response: Response,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> Response:
    """Revoke the current session and clear its host-bound cookies."""
    settings = get_settings()
    session_cookie_name, csrf_cookie_name = auth_cookie_names(
        settings.session_cookie_secure
    )
    session_id = request.cookies.get(session_cookie_name)
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
    response.delete_cookie(
        key=session_cookie_name,
        path="/",
        secure=settings.session_cookie_secure,
        samesite="lax",
    )
    response.delete_cookie(
        key=csrf_cookie_name,
        path="/",
        secure=settings.session_cookie_secure,
        samesite="lax",
    )
    response.status_code = status.HTTP_204_NO_CONTENT
    return response


@router.get("/me", response_model=UserResponse)
async def me(
    request: Request,
    response: Response,
    user: User = Depends(get_current_user),
) -> UserResponse:
    """Return the current user and ensure a session-bound CSRF cookie exists."""
    settings = get_settings()
    session_cookie_name, csrf_cookie_name = auth_cookie_names(
        settings.session_cookie_secure
    )
    session_id = request.cookies.get(session_cookie_name)
    if request.cookies.get(csrf_cookie_name) is None and session_id is not None:
        _set_csrf_cookie(response, uuid.UUID(session_id))
    return UserResponse.model_validate(user)
