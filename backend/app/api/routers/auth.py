"""Authentication endpoints: login, logout, session info."""

import asyncio
import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, Header, HTTPException, Request, Response, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.routing import APIRoute
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.api.schemas import (
    ChangePasswordRequest,
    LoginRequest,
    ProfileUpdateRequest,
    UserResponse,
)
from app.core.config import get_settings
from app.db.session import get_db_session
from app.models.enums import UserStatus
from app.models.identity import User
from app.models.session import Session
from app.services.audit import record_audit
from app.services.auth import (
    auth_cookie_names,
    authenticate_user,
    create_session,
    csrf_token_for_session,
    hash_password,
    password_check_slot,
    revoke_session,
    verify_password,
)

router = APIRouter(prefix="/auth", tags=["auth"])


class _PasswordRoute(APIRoute):
    def get_route_handler(self):  # noqa: ANN202
        handler = super().get_route_handler()

        async def safe_handler(request):  # noqa: ANN001, ANN202
            try:
                return await handler(request)
            except RequestValidationError as exc:
                raise HTTPException(
                    status_code=422,
                    detail=[
                        {key: error[key] for key in ("loc", "msg", "type")}
                        for error in exc.errors()
                    ],
                ) from None

        return safe_handler


def _request_session_id(request: Request) -> uuid.UUID:
    session_cookie_name, _ = auth_cookie_names(get_settings().session_cookie_secure)
    raw_session_id = request.cookies.get(session_cookie_name)
    try:
        return uuid.UUID(raw_session_id or "")
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid session",
        ) from exc


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
    request: Request,
    db: AsyncSession = Depends(get_db_session),
) -> JSONResponse:
    """Authenticate with email + password, receive a session cookie."""
    user = await authenticate_user(
        db,
        body.email,
        body.password,
        client_ip=request.client.host if request.client else "unknown",
    )
    if user is None:
        await db.commit()
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


@router.patch("/me", response_model=UserResponse)
async def update_me(
    body: ProfileUpdateRequest,
    if_match: str = Header(alias="If-Match", pattern=r'^"rev-[1-9]\d*"$'),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> UserResponse:
    expected_revision = int(if_match[5:-1])
    fresh_user = (
        await db.execute(select(User).where(User.id == user.id).with_for_update())
    ).scalar_one_or_none()
    if fresh_user is None:
        raise HTTPException(status_code=401, detail="Not authenticated")
    if fresh_user.revision != expected_revision:
        raise HTTPException(status_code=412, detail="Profile revision is stale")
    previous_revision = fresh_user.revision
    fresh_user.display_name = body.display_name
    fresh_user.revision += 1
    await db.flush()
    await record_audit(
        db,
        actor_user_id=fresh_user.id,
        resource_type="User",
        resource_id=fresh_user.id,
        action="PROFILE_UPDATED",
        before={"revision": previous_revision},
        after={"revision": fresh_user.revision},
        reason="User profile updated",
    )
    await db.commit()
    return UserResponse.model_validate(fresh_user)


async def change_password(
    body: ChangePasswordRequest,
    request: Request,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> UserResponse:
    current_session_id = _request_session_id(request)
    async with password_check_slot():
        fresh_user = (
            await db.execute(select(User).where(User.id == user.id).with_for_update())
        ).scalar_one_or_none()
        if fresh_user is None or fresh_user.status is not UserStatus.ACTIVE:
            raise HTTPException(status_code=401, detail="Not authenticated")
        if not await asyncio.to_thread(
            verify_password, body.current_password, fresh_user.password_hash
        ):
            raise HTTPException(status_code=400, detail="Current password is incorrect")
        if await asyncio.to_thread(
            verify_password, body.new_password, fresh_user.password_hash
        ):
            raise HTTPException(status_code=400, detail="New password must differ")
        fresh_user.password_hash = await asyncio.to_thread(
            hash_password, body.new_password
        )
    previous_revision = fresh_user.revision
    fresh_user.revision += 1
    now = datetime.now(UTC)
    await db.execute(
        update(Session)
        .where(
            Session.user_id == fresh_user.id,
            Session.id != current_session_id,
            Session.revoked_at.is_(None),
            Session.expires_at > now,
        )
        .values(revoked_at=now)
    )
    await db.flush()
    await record_audit(
        db,
        actor_user_id=fresh_user.id,
        resource_type="User",
        resource_id=fresh_user.id,
        action="PASSWORD_CHANGED",
        before={"revision": previous_revision},
        after={"revision": fresh_user.revision},
        reason="User password changed",
    )
    await db.commit()
    return UserResponse.model_validate(fresh_user)


router.add_api_route(
    "/change-password",
    change_password,
    methods=["POST"],
    response_model=UserResponse,
    route_class_override=_PasswordRoute,
)
