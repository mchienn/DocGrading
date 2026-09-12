from __future__ import annotations

import asyncio
import os
import uuid
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.pool import NullPool

from app.api.deps import get_current_user
from app.api.routers import operations as operations_router
from app.api.routers import submissions as submissions_router
from app.api.schemas_operations import (
    AdminAnalysisJobDetailResponse,
    AdminAnalysisJobListItem,
    AdminAuditEventResponse,
    AdminUserResponse,
    AdminUserUpdateRequest,
)
from app.core.config import get_settings
from app.db.session import get_db_session
from app.main import app, create_app
from app.models.analysis import AnalysisJob
from app.models.enums import AnalysisJobStatus, UserRole, UserStatus
from app.models.identity import User
from app.services import analysis_job as job_svc
from app.services import operations as operations_svc
from app.services.auth import auth_cookie_names, csrf_token_for_session
from tests.test_t011_review_workspace import _actor, _cleanup_graph, _ids, _seed_graph
from tests.test_t016_workflow import _publish_seed

requires_database = pytest.mark.skipif(
    os.environ.get("RUN_DATABASE_TESTS") != "1",
    reason="Database integration tests require RUN_DATABASE_TESTS=1",
)


def test_admin_operation_contracts_are_explicit_and_admin_only() -> None:
    schema = app.openapi()
    methods = {"delete", "get", "head", "options", "patch", "post", "put", "trace"}
    expected = {
        "/api/v1/users": {"get"},
        "/api/v1/users/{user_id}": {"get", "patch"},
        "/api/v1/operations/analysis-jobs": {"get"},
        "/api/v1/operations/analysis-jobs/{job_id}": {"get"},
        "/api/v1/operations/analysis-jobs/{job_id}/retry": {"post"},
        "/api/v1/operations/audit-events": {"get"},
        "/api/v1/operations/dashboard": {"get"},
    }
    for path, allowed in expected.items():
        assert set(schema["paths"][path]) & methods == allowed

    assert set(AdminUserResponse.model_fields) == {
        "id",
        "email",
        "display_name",
        "roles",
        "status",
        "revision",
        "created_at",
        "updated_at",
    }
    assert "password_hash" not in AdminUserResponse.model_fields
    assert "snapshot" not in AdminAnalysisJobListItem.model_fields
    assert "error_detail" not in AdminAnalysisJobListItem.model_fields
    assert set(AdminAnalysisJobDetailResponse.model_fields) == {
        *AdminAnalysisJobListItem.model_fields,
        "error_detail",
    }
    assert set(AdminAuditEventResponse.model_fields) == {
        "id",
        "resource_type",
        "resource_id",
        "action",
        "actor_type",
        "actor_user_id",
        "before",
        "after",
        "reason",
        "occurred_at",
    }


@pytest.mark.parametrize("role", [UserRole.TEACHER, UserRole.STUDENT])
def test_non_admin_is_rejected_from_every_admin_endpoint(
    role: UserRole, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("POSTGRES_DB", "docgrading_test")
    monkeypatch.setenv("POSTGRES_USER", "docgrading_test")
    monkeypatch.setenv("POSTGRES_PASSWORD", "test-only")
    get_settings.cache_clear()
    application = create_app()
    actor = _actor(uuid.uuid4(), role.value.title(), role)
    application.dependency_overrides[get_current_user] = lambda: actor
    application.dependency_overrides[get_db_session] = lambda: object()
    session_id = uuid.uuid4()
    token = csrf_token_for_session(session_id)
    session_cookie, csrf_cookie = auth_cookie_names(
        get_settings().session_cookie_secure
    )
    headers = {
        "Cookie": f"{session_cookie}={session_id}; {csrf_cookie}={token}",
        "X-CSRF-Token": token,
    }
    resource_id = uuid.uuid4()
    requests = (
        ("GET", "/api/v1/users", None),
        ("GET", f"/api/v1/users/{resource_id}", None),
        (
            "PATCH",
            f"/api/v1/users/{resource_id}",
            {"status": "LOCKED", "reason": "policy"},
        ),
        ("GET", "/api/v1/operations/analysis-jobs", None),
        ("GET", f"/api/v1/operations/analysis-jobs/{resource_id}", None),
        (
            "POST",
            f"/api/v1/operations/analysis-jobs/{resource_id}/retry",
            None,
        ),
        ("GET", "/api/v1/operations/audit-events", None),
        ("GET", "/api/v1/operations/dashboard", None),
    )
    try:
        client = TestClient(application)
        for method, path, body in requests:
            response = client.request(method, path, json=body, headers=headers)
            assert response.status_code == 403, (method, path, response.text)
    finally:
        application.dependency_overrides.clear()
        get_settings.cache_clear()


def test_user_update_requires_a_unique_nonempty_change_and_reason() -> None:
    with pytest.raises(ValidationError):
        AdminUserUpdateRequest(reason="missing change")
    with pytest.raises(ValidationError):
        AdminUserUpdateRequest(roles=[], reason="empty roles")
    with pytest.raises(ValidationError):
        AdminUserUpdateRequest(
            roles=[UserRole.ADMIN, UserRole.ADMIN], reason="duplicate roles"
        )
    with pytest.raises(ValidationError):
        AdminUserUpdateRequest(status=UserStatus.LOCKED, reason="   ")


async def _seed_second_course(
    connection, ids: dict[str, uuid.UUID], extra: dict[str, uuid.UUID]
) -> None:
    now = datetime.now(UTC)
    await connection.execute(
        text("""
            INSERT INTO public.courses (
                id, code, name, term, owner_teacher_id, revision
            ) VALUES (
                :course, :code, 'Other Course', '2026B', :teacher, 1
            )
        """),
        {
            "course": extra["course"],
            "code": f"T018-{extra['course']}",
            "teacher": ids["other_teacher"],
        },
    )
    await connection.execute(
        text("""
            INSERT INTO public.memberships (id, course_id, user_id, role, status)
            VALUES (
                :id, :course, :student,
                'STUDENT'::public.membership_role,
                'ACTIVE'::public.membership_status
            )
        """),
        {
            "id": extra["membership"],
            "course": extra["course"],
            "student": ids["student_1"],
        },
    )
    await connection.execute(
        text("""
            INSERT INTO public.rubric_versions (
                id, rubric_id, version_number, name, status,
                calculation_method, total_weight, owner_user_id,
                created_by_user_id, revision
            ) VALUES (
                :id, :rubric_id, 1, 'Other Rubric',
                'DRAFT'::public.rubric_status, 'WEIGHTED_SUM', 100,
                :teacher, :teacher, 1
            )
        """),
        {
            "id": extra["rubric"],
            "rubric_id": uuid.uuid4(),
            "teacher": ids["other_teacher"],
        },
    )
    await connection.execute(
        text("""
            INSERT INTO public.assignments (
                id, course_id, created_by_teacher_id, rubric_version_id,
                title, due_at, max_submissions, status, published_at, revision
            ) VALUES (
                :id, :course, :teacher, :rubric, 'Other Assignment',
                :due_at, 3, 'OPEN'::public.assignment_status, :now, 1
            )
        """),
        {
            "id": extra["assignment"],
            "course": extra["course"],
            "teacher": ids["other_teacher"],
            "rubric": extra["rubric"],
            "due_at": now + timedelta(days=1),
            "now": now,
        },
    )
    await connection.execute(
        text(
            "INSERT INTO public.submissions (id, assignment_id, student_id) "
            "VALUES (:id, :assignment, :student)"
        ),
        {
            "id": extra["submission"],
            "assignment": extra["assignment"],
            "student": ids["student_1"],
        },
    )
    await connection.execute(
        text("""
            INSERT INTO public.document_versions (
                id, submission_id, version_number, storage_key,
                original_filename, content_type, size_bytes, sha256,
                status, failure_code, failure_detail
            ) VALUES (
                :id, :submission, 1, :storage_key, 'other.pdf',
                'application/pdf', 100, :sha,
                'PROCESSING_FAILED'::public.document_status,
                'PRIVATE_ERROR', 'private document failure'
            )
        """),
        {
            "id": extra["document"],
            "submission": extra["submission"],
            "storage_key": f"uploads/{extra['document']}.pdf",
            "sha": "4" * 64,
        },
    )
    await connection.execute(
        text("""
            INSERT INTO public.analysis_jobs (
                id, document_version_id, rubric_version_id, status,
                attempt_count, max_attempts, snapshot, queued_at,
                finished_at, error_code, error_detail
            ) VALUES (
                :id, :document, :rubric,
                'ERROR'::public.analysis_job_status, 1, 3,
                CAST(:snapshot AS jsonb), :now, :now,
                'PRIVATE_ERROR', :detail
            )
        """),
        {
            "id": extra["job"],
            "document": extra["document"],
            "rubric": extra["rubric"],
            "snapshot": '{"storage_key":"uploads/private.pdf","credential":"secret"}',
            "now": now,
            "detail": (
                "storage_key=uploads/private.pdf credential=top-secret "
                "apiKey=camel-secret APIKey=acronym-secret "
                "'api key'=space-secret "
                '"access key":"space-access-secret" '
                '"private key":"spaced-private-secret" '
                '"client secret":"spaced-client-secret" '
                '"connection string":"postgres://user:connection-secret@db" '
                "APIKEY=uppercase-api-secret PRIVATEKEY=uppercase-private-secret "
                "AWSACCESSKEYID=uppercase-access-secret "
                "context=authorization=Bearer nested-secret "
                'message="token=quoted-nested-secret" '
                "authorization=Bearer bearer-secret "
                "password_hash=hash-secret refreshToken=refresh-secret "
                "clientSecret=client-secret aws_access_key_id=AKIA-secret "
                'privateKey="private-secret" '
                '{"authorization":"Bearer json-secret"} '
                "{'apiKey':'single-quoted-secret'}"
            ),
        },
    )


@requires_database
def test_admin_operations_workflow_and_existing_teacher_scope(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def scenario() -> None:
        ids = _ids()
        extra = {
            name: uuid.uuid4()
            for name in (
                "course",
                "membership",
                "rubric",
                "assignment",
                "submission",
                "document",
                "job",
                "review_request",
                "audit_event",
            )
        }
        engine = create_async_engine(get_settings().database_url, poolclass=NullPool)
        connection = await engine.connect()
        transaction = await connection.begin()
        session = AsyncSession(bind=connection, expire_on_commit=False)
        baseline_dashboard = await operations_svc.get_dashboard(session)
        try:
            await _seed_graph(connection, ids)
            await _seed_second_course(connection, ids, extra)
            published_id = await _publish_seed(
                connection,
                ids,
                document_id=ids["document_1"],
                published_at=datetime.now(UTC),
            )
            await connection.execute(
                text("""
                    INSERT INTO public.review_requests (
                        id, published_result_id, submission_id, student_id,
                        criterion_version_id, status, reason
                    ) VALUES (
                        :id, :published, :submission, :student, :criterion,
                        'OPEN'::public.review_request_status, 'Please review'
                    )
                """),
                {
                    "id": extra["review_request"],
                    "published": published_id,
                    "submission": ids["submission_1"],
                    "student": ids["student_1"],
                    "criterion": ids["criterion"],
                },
            )
            await connection.execute(
                text("""
                    INSERT INTO public.audit_events (
                        id, resource_type, resource_id, action,
                        actor_type, actor_user_id, before, after, reason
                    ) VALUES (
                        :id, 'CriterionVersion', :resource_id, 'UPDATE',
                        'USER'::public.audit_actor_type, :actor,
                        CAST(:before AS jsonb), CAST(:after AS jsonb), :reason
                    )
                """),
                {
                    "id": extra["audit_event"],
                    "resource_id": extra["audit_event"],
                    "actor": ids["admin"],
                    "before": (
                        '{"sessionId":"session-secret","nested":'
                        '{"storageKey":"uploads/private.pdf","safe":"visible"},'
                        '"title":"Before"}'
                    ),
                    "after": (
                        '{"title":"After","evaluator_config":{"apiKey":"secret"},'
                        '"storageKey":"uploads/private.pdf",'
                        '"jobSnapshot":{"pdfData":"raw"},'
                        '"fields":{"secret":"x"}}'
                    ),
                    "reason": (
                        "token=reason-secret apiKey=audit-secret "
                        "authorization=Bearer audit-bearer "
                        '{"token":"json-audit-secret"} '
                        "refresh_token=refresh-audit-secret "
                        "client_secret=client-audit-secret"
                    ),
                },
            )

            admin = _actor(ids["admin"], "Admin", UserRole.ADMIN)
            teacher = _actor(ids["teacher"], "Teacher A", UserRole.TEACHER)
            other_teacher = _actor(ids["other_teacher"], "Teacher B", UserRole.TEACHER)
            cached_admin = await session.get(User, admin.id)
            assert cached_admin is not None
            assert UserRole.STUDENT not in cached_admin.roles
            await connection.execute(
                text(
                    "UPDATE public.users "
                    "SET roles = ARRAY['ADMIN', 'TEACHER', 'STUDENT']"
                    "::public.user_role[], revision = 2 WHERE id = :id"
                ),
                {"id": admin.id},
            )
            concurrent_replay = await operations_svc.update_user(
                session,
                user_id=admin.id,
                body=AdminUserUpdateRequest(
                    roles=[UserRole.ADMIN, UserRole.TEACHER, UserRole.STUDENT],
                    reason="Concurrent exact replay",
                ),
                actor_user_id=admin.id,
            )
            assert concurrent_replay.revision == 2
            assert (
                await connection.scalar(
                    text(
                        "SELECT count(*) FROM public.audit_events "
                        "WHERE resource_type = 'User' AND resource_id = :id"
                    ),
                    {"id": admin.id},
                )
                == 0
            )

            users = await operations_svc.list_users(
                session,
                role=UserRole.STUDENT,
                user_status=UserStatus.ACTIVE,
                search=str(ids["student_3"]),
                page=1,
                page_size=10,
            )
            assert users.total == 1 and users.items[0].id == ids["student_3"]
            assert "password_hash" not in users.items[0].model_dump()

            changed = await operations_svc.update_user(
                session,
                user_id=ids["student_3"],
                body=AdminUserUpdateRequest(
                    roles=[UserRole.STUDENT, UserRole.TEACHER],
                    status=UserStatus.LOCKED,
                    reason="Administrative policy",
                ),
                actor_user_id=admin.id,
            )
            assert changed.roles == [UserRole.TEACHER, UserRole.STUDENT]
            assert changed.status is UserStatus.LOCKED
            assert changed.revision == 2
            unlocked = await operations_svc.update_user(
                session,
                user_id=ids["student_3"],
                body=AdminUserUpdateRequest(
                    status=UserStatus.ACTIVE,
                    reason="Administrative policy cleared",
                ),
                actor_user_id=admin.id,
            )
            assert unlocked.status is UserStatus.ACTIVE and unlocked.revision == 3
            unchanged = await operations_svc.update_user(
                session,
                user_id=ids["student_3"],
                body=AdminUserUpdateRequest(
                    status=UserStatus.ACTIVE,
                    reason="Exact replay",
                ),
                actor_user_id=admin.id,
            )
            assert unchanged.revision == 3
            user_audits = (
                (
                    await connection.execute(
                        text(
                            "SELECT action, before, after, reason "
                            "FROM public.audit_events "
                            "WHERE resource_type = 'User' AND resource_id = :id "
                            "ORDER BY occurred_at, id"
                        ),
                        {"id": ids["student_3"]},
                    )
                )
                .mappings()
                .all()
            )
            assert len(user_audits) == 3
            by_action = {event["action"]: event for event in user_audits}
            assert by_action["ROLE_CHANGE"]["before"] == {"roles": ["STUDENT"]}
            assert by_action["ROLE_CHANGE"]["after"] == {
                "roles": ["TEACHER", "STUDENT"]
            }
            assert by_action["LOCK"]["before"] == {"status": "ACTIVE"}
            assert by_action["LOCK"]["after"] == {"status": "LOCKED"}
            assert by_action["UNLOCK"]["before"] == {"status": "LOCKED"}
            assert by_action["UNLOCK"]["after"] == {"status": "ACTIVE"}

            all_jobs = await operations_svc.list_analysis_jobs(
                session,
                job_status=None,
                course_id=None,
                page=1,
                page_size=100,
            )
            assert all_jobs.total >= 2
            assert {ids["job"], extra["job"]} <= {item.id for item in all_jobs.items}
            assert all(
                "error_detail" not in item.model_dump() for item in all_jobs.items
            )
            errors = await operations_svc.list_analysis_jobs(
                session,
                job_status=AnalysisJobStatus.ERROR,
                course_id=extra["course"],
                page=1,
                page_size=10,
            )
            assert errors.total == 1 and errors.items[0].id == extra["job"]
            detail = await operations_svc.get_analysis_job(session, extra["job"])
            assert detail.error_detail is not None
            assert "private.pdf" not in detail.error_detail
            assert "top-secret" not in detail.error_detail
            assert "camel-secret" not in detail.error_detail
            assert "bearer-secret" not in detail.error_detail
            assert "hash-secret" not in detail.error_detail
            assert "refresh-secret" not in detail.error_detail
            assert "client-secret" not in detail.error_detail
            assert "AKIA-secret" not in detail.error_detail
            assert "json-secret" not in detail.error_detail
            assert "single-quoted-secret" not in detail.error_detail
            assert "acronym-secret" not in detail.error_detail
            assert "space-secret" not in detail.error_detail
            assert "space-access-secret" not in detail.error_detail
            assert "private-secret" not in detail.error_detail
            assert "spaced-private-secret" not in detail.error_detail
            assert "spaced-client-secret" not in detail.error_detail
            assert "connection-secret" not in detail.error_detail
            assert "uppercase-api-secret" not in detail.error_detail
            assert "uppercase-private-secret" not in detail.error_detail
            assert "uppercase-access-secret" not in detail.error_detail
            assert "nested-secret" not in detail.error_detail
            assert "quoted-nested-secret" not in detail.error_detail
            assert "snapshot" not in detail.model_dump()

            owned_job = await session.get(AnalysisJob, ids["job"])
            foreign_job = await session.get(AnalysisJob, extra["job"])
            assert owned_job is not None and foreign_job is not None
            await job_svc.authorize_job(session, owned_job, teacher)
            with pytest.raises(HTTPException) as foreign_teacher:
                await job_svc.authorize_job(session, foreign_job, teacher)
            assert foreign_teacher.value.status_code == 404
            await job_svc.authorize_job(session, foreign_job, other_teacher)
            await job_svc.authorize_job(session, foreign_job, admin)

            dashboard = await operations_svc.get_dashboard(session)
            expected_job_counts = dict(baseline_dashboard.jobs_by_status)
            expected_job_counts[AnalysisJobStatus.DONE] += 1
            expected_job_counts[AnalysisJobStatus.ERROR] += 1
            assert dashboard.jobs_by_status == expected_job_counts
            course_counts = {
                item.course_id: item.submission_count
                for item in dashboard.submissions_by_course
            }
            assert course_counts[ids["course"]] == 3
            assert course_counts[extra["course"]] == 1
            assert (
                dashboard.open_review_requests
                == baseline_dashboard.open_review_requests + 1
            )

            audit_page = await operations_svc.list_audit_events(
                session,
                actor_user_id=admin.id,
                resource_type="CriterionVersion",
                from_time=datetime.now(UTC) - timedelta(minutes=1),
                to_time=datetime.now(UTC) + timedelta(minutes=1),
                page=1,
                page_size=1,
            )
            assert audit_page.total == 1
            audit = audit_page.items[0]
            assert audit.before == {
                "sessionId": "[REDACTED]",
                "nested": "[REDACTED]",
                "title": "Before",
            }
            assert audit.after == {
                "title": "After",
                "evaluator_config": "[REDACTED]",
                "storageKey": "[REDACTED]",
                "jobSnapshot": "[REDACTED]",
                "fields": "[REDACTED]",
            }
            assert audit.reason == (
                "token=[REDACTED] apiKey=[REDACTED] authorization=[REDACTED] "
                '{"token":"[REDACTED]"} refresh_token=[REDACTED] '
                "client_secret=[REDACTED]"
            )
            user_audit_page = await operations_svc.list_audit_events(
                session,
                actor_user_id=admin.id,
                resource_type="User",
                from_time=None,
                to_time=None,
                page=1,
                page_size=2,
            )
            assert user_audit_page.total == 3
            assert len(user_audit_page.items) == 2
            with pytest.raises(HTTPException) as invalid_time:
                await operations_svc.list_audit_events(
                    session,
                    actor_user_id=None,
                    resource_type=None,
                    from_time=datetime.now(UTC),
                    to_time=datetime.now(UTC) - timedelta(seconds=1),
                    page=1,
                    page_size=50,
                )
            assert invalid_time.value.status_code == 422
            with pytest.raises(HTTPException) as naive_time:
                await operations_svc.list_audit_events(
                    session,
                    actor_user_id=None,
                    resource_type=None,
                    from_time=datetime.now(),
                    to_time=None,
                    page=1,
                    page_size=50,
                )
            assert naive_time.value.status_code == 422

            await connection.execute(
                text("""
                    UPDATE public.analysis_jobs
                    SET status = 'ERROR'::public.analysis_job_status,
                        attempt_count = 1, error_code = 'RETRY_ME',
                        error_detail = 'retry detail', finished_at = now()
                    WHERE id = :id
                """),
                {"id": ids["job"]},
            )
            await connection.execute(
                text("""
                    UPDATE public.document_versions
                    SET status = 'PROCESSING_FAILED'::public.document_status,
                        failure_code = 'RETRY_ME', failure_detail = 'retry detail'
                    WHERE id = :id
                """),
                {"id": ids["document_1"]},
            )
            session.expire_all()
            original_dispatch = AsyncMock(return_value=True)
            admin_dispatch = AsyncMock(return_value=True)
            monkeypatch.setattr(
                submissions_router, "dispatch_analysis_job_now", original_dispatch
            )
            monkeypatch.setattr(
                operations_router, "dispatch_analysis_job_now", admin_dispatch
            )
            original_response = await submissions_router.retry_analysis_job(
                ids["job"], teacher, session
            )
            admin_response = await operations_router.retry_analysis_job(
                extra["job"], admin, session
            )
            assert original_response.status == AnalysisJobStatus.QUEUED
            assert admin_response.status is AnalysisJobStatus.QUEUED
            original_dispatch.assert_awaited_once_with(ids["job"])
            admin_dispatch.assert_awaited_once_with(extra["job"])

            retried = (
                (
                    await connection.execute(
                        text(
                            "SELECT id, status, error_code, error_detail "
                            "FROM public.analysis_jobs WHERE id IN (:first, :second)"
                        ),
                        {"first": ids["job"], "second": extra["job"]},
                    )
                )
                .mappings()
                .all()
            )
            assert len(retried) == 2
            assert all(
                row["status"] == AnalysisJobStatus.QUEUED.value
                and row["error_code"] is None
                and row["error_detail"] is None
                for row in retried
            )
            assert (
                await connection.scalar(
                    text(
                        "SELECT count(*) FROM public.analysis_jobs "
                        "WHERE id IN (:first, :second)"
                    ),
                    {"first": ids["job"], "second": extra["job"]},
                )
                == 2
            )
            assert (
                await connection.scalar(
                    text(
                        "SELECT count(*) FROM public.analysis_job_dispatches "
                        "WHERE analysis_job_id IN (:first, :second)"
                    ),
                    {"first": ids["job"], "second": extra["job"]},
                )
                == 2
            )
            assert (
                await connection.scalar(
                    text(
                        "SELECT count(*) FROM public.audit_events "
                        "WHERE resource_type = 'AnalysisJob' AND action = 'QUEUED' "
                        "AND resource_id IN (:first, :second)"
                    ),
                    {"first": ids["job"], "second": extra["job"]},
                )
                == 2
            )
            document_states = (
                (
                    await connection.execute(
                        text(
                            "SELECT status FROM public.document_versions "
                            "WHERE id IN (:first, :second)"
                        ),
                        {
                            "first": ids["document_1"],
                            "second": extra["document"],
                        },
                    )
                )
                .scalars()
                .all()
            )
            assert document_states == [
                AnalysisJobStatus.QUEUED.value,
                AnalysisJobStatus.QUEUED.value,
            ]
        finally:
            await session.close()
            if transaction.is_active:
                await transaction.rollback()
            await connection.close()
            await engine.dispose()

    asyncio.run(scenario())


@requires_database
def test_retry_refreshes_locked_state_after_concurrent_change() -> None:
    async def scenario() -> None:
        ids = _ids()
        engine = create_async_engine(get_settings().database_url, poolclass=NullPool)
        try:
            async with engine.begin() as connection:
                await _seed_graph(connection, ids)
                await connection.execute(
                    text(
                        "UPDATE public.analysis_jobs "
                        "SET status = 'ERROR'::public.analysis_job_status, "
                        "attempt_count = 1, error_code = 'RETRY_ME' "
                        "WHERE id = :id"
                    ),
                    {"id": ids["job"]},
                )

            admin = _actor(ids["admin"], "Admin", UserRole.ADMIN)
            async with AsyncSession(engine, expire_on_commit=False) as session:
                stale_job = await session.get(AnalysisJob, ids["job"])
                assert stale_job is not None
                assert stale_job.status is AnalysisJobStatus.ERROR

                async with engine.begin() as connection:
                    await connection.execute(
                        text(
                            "UPDATE public.analysis_jobs "
                            "SET status = 'RUNNING'::public.analysis_job_status, "
                            "attempt_count = 2 WHERE id = :id"
                        ),
                        {"id": ids["job"]},
                    )

                with pytest.raises(HTTPException) as conflict:
                    await job_svc.retry_job(session, stale_job, admin)
                assert conflict.value.status_code == 409
                await session.rollback()
        finally:
            async with engine.begin() as connection:
                await _cleanup_graph(connection, ids)
            await engine.dispose()

    asyncio.run(scenario())
