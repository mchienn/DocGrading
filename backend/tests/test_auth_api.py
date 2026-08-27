"""Auth API integration tests and password hashing unit tests.

The integration tests that touch the database are gated behind
``RUN_DATABASE_TESTS=1``.  Password hashing tests run unconditionally.
"""

from __future__ import annotations

import asyncio
import os
import uuid
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.api.routers import auth as auth_router
from app.api.schemas import LoginRequest
from app.core.config import Settings, get_settings
from app.models.enums import UserRole, UserStatus
from app.models.identity import User
from app.services.auth import (
    create_session,
    get_valid_session,
    hash_password,
    needs_rehash,
    verify_password,
)

# ---------------------------------------------------------------------------
# Unit tests — password hashing (no DB)
# ---------------------------------------------------------------------------


class TestArgon2id:
    def test_hash_and_verify_round_trip(self) -> None:
        pw = "Str0ng!Pass"
        h = hash_password(pw)
        assert h.startswith("$argon2id$")
        assert verify_password(pw, h) is True

    def test_wrong_password_fails(self) -> None:
        h = hash_password("correct")
        assert verify_password("wrong", h) is False

    def test_needs_rehash_returns_false_for_fresh_hash(self) -> None:
        h = hash_password("test")
        assert needs_rehash(h) is False


class TestSessionCookieSecurity:
    @pytest.mark.parametrize(
        ("app_env", "expected"),
        [
            ("development", False),
            ("production", True),
        ],
    )
    def test_secure_cookie_matches_deployment_environment(
        self,
        app_env: str,
        expected: bool,
    ) -> None:
        settings = Settings(
            app_env=app_env,
            postgres_db="test",
            postgres_user="test",
            postgres_password="test",
        )
        assert settings.session_cookie_secure is expected

    @pytest.mark.parametrize("secure", [False, True])
    def test_login_uses_configured_cookie_security(
        self,
        monkeypatch: pytest.MonkeyPatch,
        secure: bool,
    ) -> None:
        now = datetime.now(UTC)
        user = User(
            id=uuid.uuid4(),
            email="cookie@test.local",
            display_name="Cookie User",
            password_hash=hash_password("TestPassword!123"),
            roles=[UserRole.TEACHER],
            status=UserStatus.ACTIVE,
        )

        class FakeDb:
            async def commit(self) -> None:
                pass

        async def fake_authenticate_user(*_args: object) -> User:
            return user

        async def fake_create_session(*_args: object) -> SimpleNamespace:
            return SimpleNamespace(
                id=uuid.uuid4(),
                created_at=now,
                expires_at=now + timedelta(hours=24),
            )

        async def fake_record_audit(*_args: object, **_kwargs: object) -> None:
            pass

        monkeypatch.setattr(auth_router, "authenticate_user", fake_authenticate_user)
        monkeypatch.setattr(auth_router, "create_session", fake_create_session)
        monkeypatch.setattr(auth_router, "record_audit", fake_record_audit)
        monkeypatch.setattr(
            auth_router,
            "get_settings",
            lambda: SimpleNamespace(session_cookie_secure=secure),
        )

        response = asyncio.run(
            auth_router.login(
                LoginRequest(email=user.email, password="TestPassword!123"),
                FakeDb(),
            )
        )

        directives = {
            directive.strip().lower()
            for directive in response.headers["set-cookie"].split(";")
        }
        assert ("secure" in directives) is secure


# ---------------------------------------------------------------------------
# Integration tests — auth flow on real DB
# ---------------------------------------------------------------------------

pytestmark_db = pytest.mark.skipif(
    os.environ.get("RUN_DATABASE_TESTS") != "1",
    reason="Database integration tests require RUN_DATABASE_TESTS=1",
)


async def _run_auth_integration_test() -> None:
    settings = get_settings()
    engine = create_async_engine(settings.database_url, poolclass=NullPool)

    try:
        async with engine.connect() as conn:
            trans = await conn.begin()
            try:
                user_id = uuid.uuid4()
                pw = "TestPassword!123"
                pw_hash = hash_password(pw)

                # Create test user
                await conn.execute(
                    text("""
                        INSERT INTO public.users (
                            id, email, display_name, password_hash,
                            roles, status, revision
                        ) VALUES (
                            :id, :email, :display_name, :password_hash,
                            ARRAY['TEACHER']::user_role[], 'ACTIVE'::user_status, 1
                        )
                    """),
                    {
                        "id": user_id,
                        "email": f"auth_test_{uuid.uuid4().hex[:8]}@test.local",
                        "display_name": "Auth Test User",
                        "password_hash": pw_hash,
                    },
                )

                # Verify password works
                result = await conn.execute(
                    text("SELECT password_hash FROM public.users WHERE id = :id"),
                    {"id": user_id},
                )
                stored_hash = result.scalar_one()
                assert verify_password(pw, stored_hash) is True
                assert verify_password("WrongPass!", stored_hash) is False

                # Create a session
                session_id = uuid.uuid4()
                now = datetime.now(UTC)
                await conn.execute(
                    text("""
                        INSERT INTO public.sessions (
                            id, user_id, created_at, expires_at
                        ) VALUES (
                            :id, :user_id, :created_at, :expires_at
                        )
                    """),
                    {
                        "id": session_id,
                        "user_id": user_id,
                        "created_at": now,
                        "expires_at": now + timedelta(hours=24),
                    },
                )

                # Validate session exists
                result = await conn.execute(
                    text(
                        "SELECT user_id FROM public.sessions "
                        "WHERE id = :id AND revoked_at IS NULL "
                        "AND expires_at > now()"
                    ),
                    {"id": session_id},
                )
                assert result.scalar_one() == user_id

                # Revoke session
                await conn.execute(
                    text(
                        "UPDATE public.sessions "
                        "SET revoked_at = now() WHERE id = :id"
                    ),
                    {"id": session_id},
                )
                result = await conn.execute(
                    text(
                        "SELECT user_id FROM public.sessions "
                        "WHERE id = :id AND revoked_at IS NULL"
                    ),
                    {"id": session_id},
                )
                assert result.scalar_one_or_none() is None

                # SC-2: Verify TRUNCATE on audit_events is blocked
                audit_id = uuid.uuid4()
                await conn.execute(
                    text("""
                        INSERT INTO public.audit_events (
                            id, resource_type, resource_id, action,
                            actor_type, actor_user_id,
                            before, after, reason
                        ) VALUES (
                            :id, 'Session', :resource_id, 'LOGIN',
                            'USER', :actor_id,
                            NULL, '{"session": "test"}'::jsonb,
                            'Integration test login'
                        )
                    """),
                    {
                        "id": audit_id,
                        "resource_id": session_id,
                        "actor_id": user_id,
                    },
                )

                # TRUNCATE must fail due to trigger
                with pytest.raises(Exception, match="append-only"):
                    await conn.execute(text("TRUNCATE public.audit_events"))

            finally:
                await trans.rollback()
    finally:
        await engine.dispose()


async def _run_inactive_user_session_test() -> None:
    settings = get_settings()
    engine = create_async_engine(settings.database_url, poolclass=NullPool)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    try:
        async with session_factory() as db:
            trans = await db.begin()
            try:
                user_id = uuid.uuid4()
                user = User(
                    id=user_id,
                    email=f"locked_{user_id.hex[:8]}@test.local",
                    display_name="Locked User",
                    password_hash=hash_password("TestPassword!123"),
                    roles=[UserRole.TEACHER],
                    status=UserStatus.ACTIVE,
                )
                db.add(user)
                await db.flush()

                session = await create_session(db, user.id)
                user.status = UserStatus.LOCKED
                await db.flush()

                assert await get_valid_session(db, session.id) is None
            finally:
                await trans.rollback()
    finally:
        await engine.dispose()


@pytestmark_db
def test_session_is_rejected_after_user_is_locked() -> None:
    asyncio.run(_run_inactive_user_session_test())


@pytestmark_db
def test_auth_session_lifecycle_and_audit_truncate_guard() -> None:
    asyncio.run(_run_auth_integration_test())
