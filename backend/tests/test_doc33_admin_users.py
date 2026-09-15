from __future__ import annotations

import asyncio
import json
import os
import uuid
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool

from app.api.deps import get_current_user
from app.core.config import get_settings
from app.db.session import get_db_session
from app.main import create_app
from app.models.enums import UserRole
from app.services import operations as operations_svc
from app.services.auth import (
    auth_cookie_names,
    csrf_token_for_session,
    verify_password,
)
from tests.test_t011_review_workspace import _actor, _ids, _seed_graph
from tests.test_t019_security_adversarial import _authenticated_client


@pytest.mark.parametrize(
    "change",
    [
        {"password": "short-secret"[:11]},
        {"password": "x" * 513},
        {"email": "@domain"},
        {"email": "local@"},
        {"email": "a@@domain"},
        {"email": "a b@domain"},
        {"email": "a@do\tmain"},
        {"display_name": "   "},
        {"roles": []},
        {"roles": ["ADMIN", "ADMIN"]},
        {"roles": ["UNKNOWN"]},
        {"status": "LOCKED"},
    ],
)
def test_create_validation_never_echoes_password(
    change: dict, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("POSTGRES_DB", "docgrading_test")
    monkeypatch.setenv("POSTGRES_USER", "docgrading_test")
    monkeypatch.setenv("POSTGRES_PASSWORD", "test-only")
    get_settings.cache_clear()
    application = create_app()
    application.dependency_overrides[get_current_user] = lambda: _actor(
        uuid.uuid4(), "Admin", UserRole.ADMIN
    )
    application.dependency_overrides[get_db_session] = lambda: object()
    session_id = uuid.uuid4()
    token = csrf_token_for_session(session_id)
    session_cookie, csrf_cookie = auth_cookie_names(False)
    body = {
        "email": "created@test.local",
        "display_name": "Created User",
        "password": "private-password-123",
        "roles": ["STUDENT"],
        **change,
    }
    try:
        response = TestClient(application).post(
            "/api/v1/users",
            json=body,
            headers={
                "Cookie": f"{session_cookie}={session_id}; {csrf_cookie}={token}",
                "X-CSRF-Token": token,
            },
        )
        assert response.status_code == 422
        assert body["password"] not in response.text
        assert all("input" not in error for error in response.json()["detail"])
    finally:
        application.dependency_overrides.clear()
        get_settings.cache_clear()


@pytest.mark.skipif(
    os.environ.get("RUN_DATABASE_TESTS") != "1",
    reason="Database integration tests require RUN_DATABASE_TESTS=1",
)
def test_admin_create_account_persistence_audit_rbac_and_duplicate_race(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def scenario() -> None:
        ids = _ids()
        engine = create_async_engine(get_settings().database_url, poolclass=NullPool)
        async with engine.connect() as connection:
            transaction = await connection.begin()
            try:
                await _seed_graph(connection, ids)
                email = f"doc33-{uuid.uuid4()}@test.local"
                password = "exactly12abc"
                body = {
                    "email": f"  {email.upper()}  ",
                    "display_name": "  Created User  ",
                    "password": password,
                    "roles": ["STUDENT", "TEACHER"],
                }
                for actor in ("teacher", "student_1"):
                    async with _authenticated_client(connection, ids[actor]) as client:
                        denied = await client.post("/api/v1/users", json=body)
                        assert denied.status_code == 403
                async with _authenticated_client(connection, ids["admin"]) as client:
                    no_csrf = await client.post(
                        "/api/v1/users", json=body, headers={"X-CSRF-Token": "invalid"}
                    )
                    assert no_csrf.status_code == 403
                    created = await client.post("/api/v1/users", json=body)
                    assert created.status_code == 201, created.text
                    user = created.json()
                    assert user["email"] == email
                    assert user["display_name"] == "Created User"
                    assert user["status"] == "ACTIVE"
                    assert set(user["roles"]) == {"TEACHER", "STUDENT"}
                    assert password not in created.text
                    assert "password_hash" not in user
                    stored_hash = await connection.scalar(
                        text("SELECT password_hash FROM public.users WHERE id = :id"),
                        {"id": uuid.UUID(user["id"])},
                    )
                    assert stored_hash.startswith("$argon2id$")
                    assert verify_password(password, stored_hash)
                    persisted = await client.get(f"/api/v1/users/{user['id']}")
                    assert persisted.json() == user
                    audit = (
                        (
                            await connection.execute(
                                text(
                                    "SELECT action, actor_user_id, before, "
                                    "after, reason "
                                    "FROM public.audit_events "
                                    "WHERE resource_type = 'User' AND resource_id = :id"
                                ),
                                {"id": uuid.UUID(user["id"])},
                            )
                        )
                        .mappings()
                        .one()
                    )
                    assert audit["action"] == "CREATE"
                    assert audit["actor_user_id"] == ids["admin"]
                    assert audit["before"] is None
                    assert audit["after"] == {
                        "roles": user["roles"],
                        "status": "ACTIVE",
                    }
                    assert audit["reason"] == "Administrator created account"
                    serialized = json.dumps(dict(audit), default=str)
                    assert password not in serialized and stored_hash not in serialized
                    assert "password" not in serialized
                    duplicate = await client.post(
                        "/api/v1/users", json={**body, "email": email}
                    )
                    assert duplicate.status_code == 409

                    # Simulate a writer outside the advisory lock winning after lookup.
                    original_create = operations_svc.create_user

                    async def skip_duplicate_lookup(db, **kwargs):
                        original_scalar = db.scalar
                        db.scalar = AsyncMock(return_value=False)
                        try:
                            return await original_create(db, **kwargs)
                        finally:
                            db.scalar = original_scalar

                    with monkeypatch.context() as patch:
                        patch.setattr(
                            operations_svc, "create_user", skip_duplicate_lookup
                        )
                        raced = await client.post("/api/v1/users", json=body)
                        assert raced.status_code == 409
                        assert (
                            stored_hash not in raced.text and password not in raced.text
                        )

                    # Failure to write the audit must roll back the newly inserted user.
                    failed_email = f"rollback-{email}"
                    with monkeypatch.context() as patch:
                        patch.setattr(
                            operations_svc,
                            "record_audit",
                            AsyncMock(side_effect=RuntimeError("audit unavailable")),
                        )
                        with pytest.raises(RuntimeError, match="audit unavailable"):
                            await client.post(
                                "/api/v1/users", json={**body, "email": failed_email}
                            )
                    assert (
                        await connection.scalar(
                            text(
                                "SELECT count(*) FROM public.users WHERE email = :email"
                            ),
                            {"email": failed_email},
                        )
                        == 0
                    )
                    assert (
                        await connection.scalar(
                            text(
                                "SELECT count(*) FROM public.audit_events "
                                "WHERE resource_type = 'User' AND resource_id = :id"
                            ),
                            {"id": uuid.UUID(user["id"])},
                        )
                        == 1
                    )
            finally:
                await transaction.rollback()
        await engine.dispose()

    asyncio.run(scenario())
