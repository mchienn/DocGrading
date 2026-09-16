from __future__ import annotations

import asyncio
import os
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from io import BytesIO
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from httpx2 import ASGITransport, AsyncClient
from pypdf import PdfReader, PdfWriter
from pypdf.generic import ArrayObject, DictionaryObject, NameObject
from sqlalchemy import delete, exc, text
from sqlalchemy.ext.asyncio import (
    AsyncConnection,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import NullPool

from app.api.routers import auth as auth_router
from app.api.schemas import LoginRequest
from app.core.config import get_settings
from app.db.session import get_db_session
from app.main import create_app
from app.models.enums import UserRole, UserStatus
from app.models.identity import User
from app.services import auth as auth_service
from app.services.auth import (
    auth_cookie_names,
    authenticate_user,
    csrf_token_for_session,
    hash_password,
)
from app.services.document_ir import parse_document_ir
from app.services.pdf_validation import (
    PDFValidationError,
    _preflight_page_tree,
    validate_pdf,
)
from tests.test_t009_job_concurrency import _run_two_session_claim
from tests.test_t009_pdf_decoded_limit import _make_pdf_with_stream
from tests.test_t010_document_ir_parser import _make_active_pdf
from tests.test_t011_review_workspace import _ids, _seed_graph
from tests.test_t016_workflow import _publish_seed

pytestmark = pytest.mark.skipif(
    os.environ.get("RUN_DATABASE_TESTS") != "1",
    reason="Database integration tests require RUN_DATABASE_TESTS=1",
)


async def _run_brute_force_lockout(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = get_settings()
    engine = create_async_engine(settings.database_url, poolclass=NullPool)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    user_ids = [uuid.uuid4() for _ in range(4)]
    email = f"t019-lockout-{user_ids[0]}@test.local"
    locked_email = f"t019-admin-locked-{user_ids[1]}@test.local"
    temporary_email = f"t019-temporary-lock-{user_ids[2]}@test.local"
    wrong_email = f"t019-wrong-password-{user_ids[3]}@test.local"
    password = "TestPassword!123"
    original_verify_password = auth_service.verify_password
    verify_calls = 0

    def counted_verify_password(candidate: str, password_hash: str) -> bool:
        nonlocal verify_calls
        verify_calls += 1
        return original_verify_password(candidate, password_hash)

    async def assert_one_rejection(
        database: AsyncSession, candidate_email: str, candidate_password: str
    ) -> None:
        before = verify_calls
        with pytest.raises(HTTPException) as rejected:
            await auth_router.login(
                LoginRequest(email=candidate_email, password=candidate_password),
                database,
            )
        assert rejected.value.status_code == 401
        assert rejected.value.detail == "Invalid email or password"
        assert verify_calls == before + 1

    monkeypatch.setattr(auth_service, "verify_password", counted_verify_password)
    try:
        async with sessions() as db:
            users = [
                User(
                    id=user_ids[0],
                    email=email,
                    display_name="T019 Lockout",
                    password_hash=hash_password(password),
                    roles=[UserRole.TEACHER],
                    status=UserStatus.ACTIVE,
                ),
                User(
                    id=user_ids[1],
                    email=locked_email,
                    display_name="T019 Admin Locked",
                    password_hash=hash_password(password),
                    roles=[UserRole.TEACHER],
                    status=UserStatus.LOCKED,
                ),
                User(
                    id=user_ids[2],
                    email=temporary_email,
                    display_name="T019 Temporary Lock",
                    password_hash=hash_password(password),
                    roles=[UserRole.TEACHER],
                    status=UserStatus.ACTIVE,
                    login_locked_until=datetime(2100, 1, 1, tzinfo=UTC),
                ),
                User(
                    id=user_ids[3],
                    email=wrong_email,
                    display_name="T019 Wrong Password",
                    password_hash=hash_password(password),
                    roles=[UserRole.TEACHER],
                    status=UserStatus.ACTIVE,
                ),
            ]
            db.add_all(users)
            await db.commit()

            await assert_one_rejection(
                db, f"t019-unknown-{uuid.uuid4()}@test.local", password
            )
            await assert_one_rejection(db, locked_email, password)
            await assert_one_rejection(db, temporary_email, password)
            await assert_one_rejection(db, wrong_email, "wrong-password")

            for _ in range(settings.login_max_failed_attempts):
                await assert_one_rejection(db, email, "wrong-password")

            user = users[0]
            await db.refresh(user)
            assert user.failed_login_attempts == settings.login_max_failed_attempts
            assert user.login_locked_until is not None

            await assert_one_rejection(db, email, password)

            user.login_locked_until = datetime(2000, 1, 1, tzinfo=UTC)
            await db.commit()
            authenticated = await authenticate_user(db, email, password)
            assert authenticated is not None and authenticated.id == user_ids[0]
            await db.commit()
            await db.refresh(user)
            assert user.failed_login_attempts == 0
            assert user.failed_login_window_started_at is None
            assert user.login_locked_until is None
    finally:
        async with engine.begin() as connection:
            await connection.execute(delete(User).where(User.id.in_(user_ids)))
        await engine.dispose()


async def _run_expired_failure_window() -> None:
    settings = get_settings()
    engine = create_async_engine(settings.database_url, poolclass=NullPool)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    user_id = uuid.uuid4()
    email = f"t019-expired-window-{user_id}@test.local"
    expired_start = datetime(2000, 1, 1, tzinfo=UTC)
    try:
        async with sessions() as db:
            user = User(
                id=user_id,
                email=email,
                display_name="T019 Expired Window",
                password_hash=hash_password("TestPassword!123"),
                roles=[UserRole.TEACHER],
                status=UserStatus.ACTIVE,
                failed_login_attempts=settings.login_max_failed_attempts - 1,
                failed_login_window_started_at=expired_start,
            )
            db.add(user)
            await db.commit()

            with pytest.raises(HTTPException) as rejected:
                await auth_router.login(
                    LoginRequest(email=email, password="wrong-password"), db
                )
            assert rejected.value.status_code == 401
            await db.refresh(user)
            assert user.failed_login_attempts == 1
            assert user.failed_login_window_started_at is not None
            assert user.failed_login_window_started_at > expired_start + timedelta(
                seconds=settings.login_failure_window_seconds
            )
            assert user.login_locked_until is None
    finally:
        async with engine.begin() as connection:
            await connection.execute(delete(User).where(User.id == user_id))
        await engine.dispose()


async def _run_concurrent_lockout_threshold() -> None:
    settings = get_settings()
    engine = create_async_engine(settings.database_url, poolclass=NullPool)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    user_id = uuid.uuid4()
    email = f"t019-concurrent-lockout-{user_id}@test.local"
    initial_attempts = max(0, settings.login_max_failed_attempts - 2)
    try:
        async with sessions() as db:
            user = User(
                id=user_id,
                email=email,
                display_name="T019 Concurrent Lockout",
                password_hash=hash_password("TestPassword!123"),
                roles=[UserRole.TEACHER],
                status=UserStatus.ACTIVE,
                failed_login_attempts=initial_attempts,
                failed_login_window_started_at=datetime.now(UTC),
            )
            db.add(user)
            await db.commit()

        barrier = asyncio.Barrier(2)

        async def reject_wrong_password() -> None:
            async with sessions() as db:
                await barrier.wait()
                with pytest.raises(HTTPException) as rejected:
                    await auth_router.login(
                        LoginRequest(email=email, password="wrong-password"), db
                    )
                assert rejected.value.status_code == 401

        await asyncio.gather(reject_wrong_password(), reject_wrong_password())

        async with sessions() as db:
            user = await db.get(User, user_id)
            assert user is not None
            assert user.failed_login_attempts == settings.login_max_failed_attempts
            assert user.login_locked_until is not None
    finally:
        async with engine.begin() as connection:
            await connection.execute(delete(User).where(User.id == user_id))
        await engine.dispose()


async def _insert_session(connection: AsyncConnection, user_id: uuid.UUID) -> uuid.UUID:
    session_id = uuid.uuid4()
    await connection.execute(
        text(
            "INSERT INTO public.sessions (id, user_id, created_at, expires_at) "
            "VALUES (:id, :user_id, now(), now() + interval '1 hour')"
        ),
        {"id": session_id, "user_id": user_id},
    )
    return session_id


@asynccontextmanager
async def _authenticated_client(
    connection: AsyncConnection, user_id: uuid.UUID
) -> AsyncIterator[AsyncClient]:
    sessions = async_sessionmaker(
        bind=connection,
        expire_on_commit=False,
        join_transaction_mode="create_savepoint",
    )

    async def override_database() -> AsyncIterator[AsyncSession]:
        async with sessions() as database:
            yield database

    application = create_app()
    application.dependency_overrides[get_db_session] = override_database
    session_id = await _insert_session(connection, user_id)
    session_cookie, csrf_cookie = auth_cookie_names(
        get_settings().session_cookie_secure
    )
    csrf_token = csrf_token_for_session(session_id)
    try:
        async with AsyncClient(
            transport=ASGITransport(app=application),
            base_url="https://testserver",
            cookies={
                session_cookie: str(session_id),
                csrf_cookie: csrf_token,
            },
            headers={
                "X-CSRF-Token": csrf_token,
                "Idempotency-Key": "t019-idor",
            },
        ) as client:
            yield client
    finally:
        application.dependency_overrides.clear()


async def _run_secure_cookie_login() -> None:
    settings = get_settings()
    engine = create_async_engine(settings.database_url, poolclass=NullPool)
    connection = await engine.connect()
    transaction = await connection.begin()
    user_id = uuid.uuid4()
    email = f"t019-cookie-{user_id}@test.local"
    password = "TestPassword!123"
    sessions = async_sessionmaker(
        bind=connection,
        expire_on_commit=False,
        join_transaction_mode="create_savepoint",
    )

    async def override_database() -> AsyncIterator[AsyncSession]:
        async with sessions() as database:
            yield database

    application = create_app()
    application.dependency_overrides[get_db_session] = override_database
    try:
        await connection.execute(
            text(
                "INSERT INTO public.users "
                "(id, email, display_name, password_hash, roles, status, revision) "
                "VALUES (:id, :email, 'T019 Cookie', :password_hash, "
                "ARRAY['TEACHER']::public.user_role[], "
                "'ACTIVE'::public.user_status, 1)"
            ),
            {
                "id": user_id,
                "email": email,
                "password_hash": hash_password(password),
            },
        )
        async with AsyncClient(
            transport=ASGITransport(app=application),
            base_url="https://testserver",
        ) as client:
            response = await client.post(
                "/api/v1/auth/login",
                json={"email": email, "password": password},
            )
        assert response.status_code == 200
        cookies = response.headers.get_list("set-cookie")
        assert len(cookies) == 2
        assert all("Secure" in cookie for cookie in cookies)
        assert any(cookie.startswith("__Host-session_id=") for cookie in cookies)
        assert any(cookie.startswith("__Host-csrf_token=") for cookie in cookies)
    finally:
        application.dependency_overrides.clear()
        await transaction.rollback()
        await connection.close()
        await engine.dispose()


def test_login_cookies_are_secure_outside_development(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("STORAGE_ACCESS_KEY_ID", "t019-production-key")
    monkeypatch.setenv("STORAGE_SECRET_ACCESS_KEY", "t019-production-secret")
    monkeypatch.setenv(
        "JOIN_RATE_LIMIT_HASH_SECRET", "test-rate-limit-hash-secret-32-bytes"
    )
    get_settings.cache_clear()
    try:
        asyncio.run(_run_secure_cookie_login())
    finally:
        get_settings.cache_clear()


async def _run_locked_user_session_rejection() -> None:
    engine = create_async_engine(get_settings().database_url, poolclass=NullPool)
    connection = await engine.connect()
    transaction = await connection.begin()
    user_id = uuid.uuid4()
    try:
        await connection.execute(
            text(
                "INSERT INTO public.users "
                "(id, email, display_name, password_hash, roles, status, revision) "
                "VALUES (:id, :email, 'T019 Session', 'hash', "
                "ARRAY['TEACHER']::public.user_role[], "
                "'ACTIVE'::public.user_status, 1)"
            ),
            {"id": user_id, "email": f"t019-session-{user_id}@test.local"},
        )
        async with _authenticated_client(connection, user_id) as client:
            assert (await client.get("/api/v1/auth/me")).status_code == 200
            await connection.execute(
                text(
                    "UPDATE public.users SET status = 'LOCKED'::public.user_status "
                    "WHERE id = :id"
                ),
                {"id": user_id},
            )
            rejected = await client.get("/api/v1/auth/me")
            assert rejected.status_code == 401
            assert rejected.json() == {"detail": "Session expired or invalid"}
    finally:
        await transaction.rollback()
        await connection.close()
        await engine.dispose()


def test_existing_session_is_rejected_after_account_deactivation() -> None:
    asyncio.run(_run_locked_user_session_rejection())


async def _seed_idor_targets(
    connection: AsyncConnection, ids: dict[str, uuid.UUID]
) -> tuple[uuid.UUID, uuid.UUID]:
    now = datetime.now(UTC)
    await connection.execute(
        text(
            "UPDATE public.users "
            "SET roles = ARRAY['TEACHER', 'STUDENT']::public.user_role[] "
            "WHERE id = :id"
        ),
        {"id": ids["other_teacher"]},
    )
    await connection.execute(
        text(
            "INSERT INTO public.document_versions "
            "(id, submission_id, version_number, storage_key, original_filename, "
            "content_type, size_bytes, sha256, status, approved_at, "
            "approved_by_user_id, approved_snapshot, created_at) "
            "VALUES (:id, :submission, 2, :storage_key, 'four.pdf', "
            "'application/pdf', 100, :sha256, "
            "'PUBLISHED'::public.document_status, :now, :teacher, "
            '\'{"comment":"public","findings":[]}\'::jsonb, :now)'
        ),
        {
            "id": ids["document_4"],
            "submission": ids["submission_1"],
            "storage_key": f"private/{ids['document_4']}",
            "sha256": "4" * 64,
            "now": now,
            "teacher": ids["teacher"],
        },
    )
    result_id = await _publish_seed(
        connection,
        ids,
        document_id=ids["document_4"],
        published_at=now,
    )
    request_id = uuid.uuid4()
    await connection.execute(
        text(
            "INSERT INTO public.review_requests "
            "(id, published_result_id, submission_id, student_id, "
            "criterion_version_id, status, reason) "
            "VALUES (:id, :result, :submission, :student, :criterion, "
            "'OPEN'::public.review_request_status, 'T019 ownership target')"
        ),
        {
            "id": request_id,
            "result": result_id,
            "submission": ids["submission_1"],
            "student": ids["student_1"],
            "criterion": ids["criterion"],
        },
    )
    await connection.execute(
        text(
            "INSERT INTO public.review_locks "
            "(id, submission_id, reviewer_user_id, acquired_at, expires_at) "
            "VALUES (:id, :submission, :reviewer, :now, :expires)"
        ),
        {
            "id": uuid.uuid4(),
            "submission": ids["submission_1"],
            "reviewer": ids["other_teacher"],
            "now": now,
            "expires": now + timedelta(minutes=10),
        },
    )
    return result_id, request_id


async def _run_teacher_idor_matrix() -> None:
    ids = _ids()
    engine = create_async_engine(get_settings().database_url, poolclass=NullPool)
    connection = await engine.connect()
    transaction = await connection.begin()
    try:
        await _seed_graph(connection, ids)
        result_id, request_id = await _seed_idor_targets(connection, ids)

        async with _authenticated_client(connection, ids["teacher"]) as owner:
            assert (
                await owner.get(f"/api/v1/courses/{ids['course']}")
            ).status_code == 200
            assert (
                await owner.get(f"/api/v1/analysis-jobs/{ids['job']}")
            ).status_code == 200
            assert (
                await owner.get(f"/api/v1/review-requests/{request_id}")
            ).status_code == 200
            compared = await owner.get(
                f"/api/v1/submissions/{ids['submission_1']}/versions/compare",
                params={
                    "left_version_id": ids["document_1"],
                    "right_version_id": ids["document_4"],
                },
            )
            assert compared.status_code == 200

        async with _authenticated_client(connection, ids["admin"]) as admin:
            assert (
                await admin.get(f"/api/v1/courses/{ids['course']}")
            ).status_code == 200

        async with _authenticated_client(connection, ids["other_teacher"]) as attacker:
            listed = await attacker.get("/api/v1/courses")
            assert listed.status_code == 200
            assert str(ids["course"]) not in listed.text

            due_at = (datetime.now(UTC) + timedelta(days=1)).isoformat()
            requests = [
                ("GET", f"/api/v1/courses/{ids['course']}", None),
                (
                    "PUT",
                    f"/api/v1/courses/{ids['course']}",
                    {"name": "IDOR"},
                ),
                ("DELETE", f"/api/v1/courses/{ids['course']}", None),
                ("POST", f"/api/v1/courses/{ids['course']}/archive", None),
                ("GET", f"/api/v1/courses/{ids['course']}/assignments", None),
                (
                    "POST",
                    f"/api/v1/courses/{ids['course']}/assignments",
                    {
                        "rubric_version_id": str(ids["rubric"]),
                        "title": "IDOR",
                        "due_at": due_at,
                    },
                ),
                (
                    "GET",
                    f"/api/v1/courses/{ids['course']}/assignments/"
                    f"{ids['assignment']}",
                    None,
                ),
                (
                    "PUT",
                    f"/api/v1/courses/{ids['course']}/assignments/"
                    f"{ids['assignment']}",
                    {"title": "IDOR"},
                ),
                (
                    "POST",
                    f"/api/v1/courses/{ids['course']}/assignments/"
                    f"{ids['assignment']}/publish",
                    None,
                ),
                (
                    "POST",
                    f"/api/v1/courses/{ids['course']}/assignments/"
                    f"{ids['assignment']}/close",
                    None,
                ),
                ("GET", f"/api/v1/analysis-jobs/{ids['job']}", None),
                ("POST", f"/api/v1/analysis-jobs/{ids['job']}/retry", None),
                (
                    "GET",
                    f"/api/v1/courses/{ids['course']}/submission-queue",
                    None,
                ),
                (
                    "GET",
                    f"/api/v1/submissions/{ids['submission_1']}/evidence",
                    None,
                ),
                (
                    "POST",
                    f"/api/v1/submissions/{ids['submission_1']}/review-lock",
                    None,
                ),
                (
                    "PUT",
                    f"/api/v1/submissions/{ids['submission_1']}/"
                    "review-lock/heartbeat",
                    None,
                ),
                (
                    "GET",
                    f"/api/v1/submissions/{ids['submission_1']}/review-draft",
                    None,
                ),
                (
                    "PUT",
                    f"/api/v1/submissions/{ids['submission_1']}/review-draft",
                    {
                        "document_version_id": str(ids["document_4"]),
                        "revision": 1,
                        "comment": "IDOR",
                        "decisions": [],
                    },
                ),
                (
                    "DELETE",
                    f"/api/v1/submissions/{ids['submission_1']}/review-lock",
                    None,
                ),
                (
                    "POST",
                    f"/api/v1/document-versions/{ids['document_4']}/approve",
                    None,
                ),
                (
                    "POST",
                    f"/api/v1/document-versions/{ids['document_4']}/publish",
                    {"reason": "IDOR"},
                ),
                (
                    "POST",
                    f"/api/v1/assignments/{ids['assignment']}/"
                    "document-versions/bulk-publish",
                    {
                        "version_ids": [str(ids["document_4"])],
                        "reason": "IDOR",
                    },
                ),
                (
                    "POST",
                    f"/api/v1/published-results/{result_id}/unpublish",
                    {"reason": "IDOR"},
                ),
                (
                    "GET",
                    f"/api/v1/submissions/{ids['submission_1']}/versions",
                    None,
                ),
                (
                    "GET",
                    f"/api/v1/submissions/{ids['submission_1']}/versions/compare"
                    f"?left_version_id={ids['document_1']}"
                    f"&right_version_id={ids['document_4']}",
                    None,
                ),
                (
                    "GET",
                    f"/api/v1/submissions/{ids['submission_1']}/published-result",
                    None,
                ),
                (
                    "GET",
                    f"/api/v1/courses/{ids['course']}/review-requests",
                    None,
                ),
                ("GET", f"/api/v1/review-requests/{request_id}", None),
                (
                    "PATCH",
                    f"/api/v1/review-requests/{request_id}",
                    {"status": "REJECTED", "response": "IDOR"},
                ),
            ]
            for method, path, body in requests:
                response = await attacker.request(method, path, json=body)
                assert response.status_code == 404, (
                    method,
                    path,
                    response.status_code,
                    response.text,
                )

        async with _authenticated_client(connection, ids["student_2"]) as student:
            assert (await student.get("/api/v1/users")).status_code == 403
            assert (
                await student.get(f"/api/v1/courses/{ids['course']}")
            ).status_code == 403
        async with _authenticated_client(connection, ids["other_teacher"]) as teacher:
            assert (await teacher.get("/api/v1/users")).status_code == 403
    finally:
        await transaction.rollback()
        await connection.close()
        await engine.dispose()


def test_teacher_cannot_idor_foreign_course_submission_review_or_result() -> None:
    asyncio.run(_run_teacher_idor_matrix())


async def _run_notification_actor_isolation() -> None:
    ids = _ids()
    engine = create_async_engine(get_settings().database_url, poolclass=NullPool)
    connection = await engine.connect()
    transaction = await connection.begin()
    own_id, foreign_id = uuid.uuid4(), uuid.uuid4()
    try:
        await _seed_graph(connection, ids)
        await connection.execute(
            text(
                "INSERT INTO public.notifications (id, recipient_id, type, payload) "
                "VALUES "
                "(:own, :teacher, "
                "'REVIEW_REQUEST_CREATED'::public.notification_type, "
                "jsonb_build_object('review_request_id', "
                "CAST(:own_target AS text))), "
                "(:foreign, :student, "
                "'RESULT_PUBLISHED'::public.notification_type, "
                "jsonb_build_object('published_result_version_id', "
                "CAST(:foreign_target AS text)))"
            ),
            {
                "own": own_id,
                "teacher": ids["teacher"],
                "foreign": foreign_id,
                "student": ids["student_1"],
                "own_target": str(ids["criterion"]),
                "foreign_target": str(ids["document_1"]),
            },
        )
        async with _authenticated_client(connection, ids["teacher"]) as client:
            listed = await client.get("/api/v1/notifications")
            assert listed.status_code == 200
            assert [item["id"] for item in listed.json()["items"]] == [str(own_id)]

            foreign = await client.patch(f"/api/v1/notifications/{foreign_id}/read")
            assert foreign.status_code == 404
            mixed = await client.patch(
                "/api/v1/notifications/read",
                json={"notification_ids": [str(own_id), str(foreign_id)]},
            )
            assert mixed.status_code == 404

        unread = (
            await connection.execute(
                text(
                    "SELECT id FROM public.notifications "
                    "WHERE id IN (:own, :foreign) AND read_at IS NULL ORDER BY id"
                ),
                {"own": own_id, "foreign": foreign_id},
            )
        ).scalars()
        assert set(unread) == {own_id, foreign_id}
    finally:
        await transaction.rollback()
        await connection.close()
        await engine.dispose()


def test_notification_list_and_updates_are_actor_scoped() -> None:
    asyncio.run(_run_notification_actor_isolation())


def _pdf_with_form() -> bytes:
    writer = PdfWriter()
    writer.clone_document_from_reader(PdfReader(BytesIO(_make_active_pdf())))
    writer._root_object[NameObject("/AcroForm")] = DictionaryObject(
        {NameObject("/Fields"): ArrayObject()}
    )
    output = BytesIO()
    writer.write(output)
    return output.getvalue()


def test_declared_pdf_upload_with_non_pdf_bytes_is_rejected() -> None:
    with pytest.raises(PDFValidationError) as rejected:
        validate_pdf(b"report.pdf\\x00application/pdf\\x00not-a-pdf")
    assert rejected.value.code == "NOT_A_PDF"


@pytest.mark.parametrize(
    "payload",
    [
        _make_active_pdf(js=True),
        _make_active_pdf(launch=True),
        _make_active_pdf(attachment=True),
        _pdf_with_form(),
    ],
    ids=["javascript", "launch", "embedded", "form"],
)
def test_active_pdf_content_never_reaches_document_ir(payload: bytes) -> None:
    with pytest.raises(PDFValidationError) as rejected:
        parse_document_ir(payload)
    assert rejected.value.code == "PDF_ACTIVE_CONTENT"


def test_page_tree_cycle_and_bomb_fail_closed() -> None:
    cycle: dict[str, object] = {
        "/Type": "/Pages",
        "/Count": 1,
        "/Kids": [],
    }
    cycle["/Kids"] = [cycle]
    bomb = {
        "/Type": "/Pages",
        "/Count": 0,
        "/Kids": [{"/Type": "/Pages", "/Count": 0, "/Kids": []} for _ in range(10_001)],
    }
    for root in (cycle, bomb):
        with pytest.raises(PDFValidationError) as rejected:
            _preflight_page_tree(SimpleNamespace(root_object={"/Pages": root}), 100)
        assert rejected.value.code == "PDF_MALFORMED"


def test_compressed_pdf_cannot_bypass_decoded_content_limit() -> None:
    decoded = b"BT /F1 12 Tf 10 10 Td (" + b"A" * 2_500 + b") Tj ET"
    payload = _make_pdf_with_stream([decoded], compress=True)
    assert len(payload) < 1_500
    with pytest.raises(PDFValidationError) as rejected:
        validate_pdf(payload, max_size_bytes=1_500)
    assert rejected.value.code == "PDF_DECODED_TOO_LARGE"


def test_existing_two_worker_claim_regression_still_has_one_winner() -> None:
    asyncio.run(_run_two_session_claim())


async def _run_head_truncate_guards() -> None:
    engine = create_async_engine(get_settings().database_url, poolclass=NullPool)
    try:
        async with engine.connect() as connection:
            transaction = await connection.begin()
            try:
                revision = await connection.scalar(
                    text("SELECT version_num FROM public.alembic_version")
                )
                assert revision == "20260916_0015"
                for table in ("audit_events", "published_result_versions"):
                    with pytest.raises(exc.DBAPIError, match="append-only"):
                        async with connection.begin_nested():
                            await connection.execute(
                                text(f"TRUNCATE TABLE public.{table} CASCADE")
                            )
                    assert await connection.scalar(text("SELECT 1")) == 1
            finally:
                await transaction.rollback()
    finally:
        await engine.dispose()


def test_head_migrations_preserve_both_truncate_guards() -> None:
    asyncio.run(_run_head_truncate_guards())


def test_repeated_login_failures_lock_then_expire_on_postgresql(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    asyncio.run(_run_brute_force_lockout(monkeypatch))


def test_expired_failure_window_starts_a_fresh_counter() -> None:
    asyncio.run(_run_expired_failure_window())


def test_concurrent_failures_reach_lockout_threshold() -> None:
    asyncio.run(_run_concurrent_lockout_threshold())
