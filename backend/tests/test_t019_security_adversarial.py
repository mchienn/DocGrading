from __future__ import annotations

import asyncio
import os
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from fastapi import HTTPException
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.api.routers import auth as auth_router
from app.api.schemas import LoginRequest
from app.core.config import get_settings
from app.models.enums import UserRole, UserStatus
from app.models.identity import User
from app.services.auth import authenticate_user, hash_password

pytestmark = pytest.mark.skipif(
    os.environ.get("RUN_DATABASE_TESTS") != "1",
    reason="Database integration tests require RUN_DATABASE_TESTS=1",
)


async def _run_brute_force_lockout() -> None:
    settings = get_settings()
    engine = create_async_engine(settings.database_url, poolclass=NullPool)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    user_id = uuid.uuid4()
    email = f"t019-lockout-{user_id}@test.local"
    password = "TestPassword!123"

    try:
        async with sessions() as db:
            user = User(
                id=user_id,
                email=email,
                display_name="T019 Lockout",
                password_hash=hash_password(password),
                roles=[UserRole.TEACHER],
                status=UserStatus.ACTIVE,
            )
            db.add(user)
            await db.commit()

            for _ in range(settings.login_max_failed_attempts):
                with pytest.raises(HTTPException) as rejected:
                    await auth_router.login(
                        LoginRequest(email=email, password="wrong-password"), db
                    )
                assert rejected.value.status_code == 401

            await db.refresh(user)
            assert user.failed_login_attempts == settings.login_max_failed_attempts
            assert user.login_locked_until is not None
            assert user.login_locked_until > datetime.now(UTC)

            with pytest.raises(HTTPException) as locked:
                await auth_router.login(
                    LoginRequest(email=email, password=password), db
                )
            assert locked.value.status_code == 401

            user.login_locked_until = datetime.now(UTC) - timedelta(seconds=1)
            await db.commit()
            authenticated = await authenticate_user(db, email, password)
            assert authenticated is not None and authenticated.id == user_id
            await db.commit()
            await db.refresh(user)
            assert user.failed_login_attempts == 0
            assert user.failed_login_window_started_at is None
            assert user.login_locked_until is None
    finally:
        async with engine.begin() as connection:
            await connection.execute(delete(User).where(User.id == user_id))
        await engine.dispose()


def test_repeated_login_failures_lock_then_expire_on_postgresql() -> None:
    asyncio.run(_run_brute_force_lockout())
