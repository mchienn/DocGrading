from __future__ import annotations

import asyncio
import os
import uuid
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path

import pytest
from alembic.config import Config
from fastapi import HTTPException
from sqlalchemy import exc, text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, create_async_engine
from sqlalchemy.pool import NullPool

from alembic import command
from app.api.schemas_submission import ReviewRequestCreate, ReviewRequestUpdate
from app.core.config import get_settings
from app.models.analysis import AnalysisJob
from app.models.enums import NotificationType, ReviewRequestStatus, UserRole
from app.services import notification as notification_svc
from app.services import review as review_svc
from app.services.analysis_job import mark_error
from app.services.appeal import create_review_request, respond_review_request
from app.services.review import publish_document_version
from tests.test_t011_review_workspace import _actor, _ids, _seed_graph

pytestmark = pytest.mark.skipif(
    os.environ.get("RUN_DATABASE_TESTS") != "1",
    reason="Database integration tests require RUN_DATABASE_TESTS=1",
)


def _config() -> Config:
    backend_dir = Path(__file__).resolve().parents[1]
    config = Config(str(backend_dir / "alembic.ini"))
    config.set_main_option("script_location", str(backend_dir / "alembic"))
    return config


async def _notification_rows(session: AsyncSession):  # noqa: ANN202
    return list(
        (
            await session.execute(
                text(
                    "SELECT id, recipient_id, type, payload, read_at, created_at "
                    "FROM public.notifications"
                )
            )
        ).mappings()
    )


def test_t017_source_events_create_private_reference_notifications() -> None:
    async def scenario() -> None:
        ids = _ids()
        engine = create_async_engine(get_settings().database_url, poolclass=NullPool)
        connection = await engine.connect()
        transaction = await connection.begin()
        session = AsyncSession(bind=connection, expire_on_commit=False)
        try:
            await _seed_graph(connection, ids)
            await connection.execute(
                text(
                    "UPDATE public.analysis_jobs "
                    "SET status = 'RUNNING', attempt_count = 1 WHERE id = :job"
                ),
                {"job": ids["job"]},
            )
            job = await session.get(AnalysisJob, ids["job"])
            assert job is not None
            assert await mark_error(
                session,
                job,
                "PRIVATE_ERROR",
                "sensitive detail",
                attempt_count=1,
            )
            assert not await mark_error(
                session,
                job,
                "SECOND_ERROR",
                "must not notify twice",
                attempt_count=1,
            )
            await connection.execute(
                text(
                    "UPDATE public.analysis_jobs "
                    "SET status = 'RUNNING', attempt_count = 2 WHERE id = :job"
                ),
                {"job": ids["job"]},
            )
            await session.refresh(job)
            assert await mark_error(
                session,
                job,
                "PRIVATE_ERROR",
                "failed after retry",
                attempt_count=2,
            )

            await connection.execute(
                text(
                    "UPDATE public.document_versions "
                    "SET status = 'APPROVED', approved_at = now(), "
                    "approved_by_user_id = :teacher, "
                    "approved_snapshot = '{}'::jsonb WHERE id = :document"
                ),
                {"teacher": ids["teacher"], "document": ids["document_2"]},
            )
            teacher = _actor(ids["teacher"], "Teacher A", UserRole.TEACHER)
            idempotency_key = f"publish-{ids['document_2']}"
            published = await publish_document_version(
                session,
                version_id=ids["document_2"],
                user=teacher,
                idempotency_key=idempotency_key,
                reason="publish",
            )
            replay = await publish_document_version(
                session,
                version_id=ids["document_2"],
                user=teacher,
                idempotency_key=idempotency_key,
                reason="publish",
            )
            assert replay.published_result_id == published.published_result_id

            criterion_id = (
                await session.execute(
                    text(
                        "SELECT criterion_id FROM public.criterion_versions "
                        "WHERE id = :id"
                    ),
                    {"id": ids["criterion"]},
                )
            ).scalar_one()
            student = _actor(ids["student_2"], "Student 2", UserRole.STUDENT)
            resolved_request = await create_review_request(
                session,
                published_result_id=published.published_result_id,
                payload=ReviewRequestCreate(
                    submission_id=ids["submission_2"],
                    criterion_id=criterion_id,
                    reason="request",
                ),
                user=student,
            )
            await respond_review_request(
                session,
                request_id=resolved_request.id,
                payload=ReviewRequestUpdate(
                    status=ReviewRequestStatus.RESOLVED,
                    response="resolved",
                ),
                user=teacher,
            )
            with pytest.raises(HTTPException) as terminal_replay:
                await respond_review_request(
                    session,
                    request_id=resolved_request.id,
                    payload=ReviewRequestUpdate(
                        status=ReviewRequestStatus.REJECTED,
                        response="must not notify twice",
                    ),
                    user=teacher,
                )
            assert terminal_replay.value.status_code == 409

            rejected_request = await create_review_request(
                session,
                published_result_id=published.published_result_id,
                payload=ReviewRequestCreate(
                    submission_id=ids["submission_2"],
                    criterion_id=criterion_id,
                    reason="request again",
                ),
                user=student,
            )
            await respond_review_request(
                session,
                request_id=rejected_request.id,
                payload=ReviewRequestUpdate(
                    status=ReviewRequestStatus.REJECTED,
                    response="rejected",
                ),
                user=teacher,
            )

            rows = await _notification_rows(session)
            counts = Counter(row["type"] for row in rows)
            assert counts == {
                NotificationType.ANALYSIS_JOB_ERROR.value: 2,
                NotificationType.RESULT_PUBLISHED.value: 1,
                NotificationType.REVIEW_REQUEST_CREATED.value: 2,
                NotificationType.REVIEW_REQUEST_RESOLVED.value: 1,
                NotificationType.REVIEW_REQUEST_REJECTED.value: 1,
            }
            error_rows = [
                row
                for row in rows
                if row["type"] == NotificationType.ANALYSIS_JOB_ERROR.value
            ]
            assert len(error_rows) == 2
            assert all(
                row["recipient_id"] == ids["student_1"]
                and row["payload"] == {"analysis_job_id": str(ids["job"])}
                for row in error_rows
            )
            by_type = {
                row["type"]: row
                for row in rows
                if row["type"]
                not in (
                    NotificationType.ANALYSIS_JOB_ERROR.value,
                    NotificationType.REVIEW_REQUEST_CREATED.value,
                )
            }
            assert (
                by_type[NotificationType.RESULT_PUBLISHED.value]["recipient_id"]
                == ids["student_2"]
            )
            assert by_type[NotificationType.RESULT_PUBLISHED.value]["payload"] == {
                "published_result_version_id": str(published.published_result_id),
                "submission_id": str(ids["submission_2"]),
            }
            created = [
                row
                for row in rows
                if row["type"] == NotificationType.REVIEW_REQUEST_CREATED.value
            ]
            assert {row["recipient_id"] for row in created} == {ids["teacher"]}
            assert {row["payload"]["review_request_id"] for row in created} == {
                str(resolved_request.id),
                str(rejected_request.id),
            }
            assert (
                by_type[NotificationType.REVIEW_REQUEST_RESOLVED.value]["recipient_id"]
                == ids["student_2"]
            )
            assert by_type[NotificationType.REVIEW_REQUEST_RESOLVED.value][
                "payload"
            ] == {"review_request_id": str(resolved_request.id)}
            assert (
                by_type[NotificationType.REVIEW_REQUEST_REJECTED.value]["recipient_id"]
                == ids["student_2"]
            )
            assert by_type[NotificationType.REVIEW_REQUEST_REJECTED.value][
                "payload"
            ] == {"review_request_id": str(rejected_request.id)}

            other_teacher = _actor(ids["other_teacher"], "Teacher B", UserRole.TEACHER)
            foreign_course_notifications = await notification_svc.list_notifications(
                session,
                user=other_teacher,
                unread=None,
                page=1,
                page_size=50,
            )
            assert foreign_course_notifications.total == 0
            assert foreign_course_notifications.items == []
        finally:
            await session.close()
            await transaction.rollback()
            await connection.close()
            await engine.dispose()

    asyncio.run(scenario())


def test_t017_polling_is_actor_scoped_and_mark_read_idempotent() -> None:
    async def scenario() -> None:
        ids = _ids()
        engine = create_async_engine(get_settings().database_url, poolclass=NullPool)
        connection = await engine.connect()
        transaction = await connection.begin()
        session = AsyncSession(bind=connection, expire_on_commit=False)
        try:
            await _seed_graph(connection, ids)
            own_first = await notification_svc.add_notification(
                session,
                recipient_id=ids["student_1"],
                notification_type=NotificationType.REVIEW_REQUEST_CREATED,
                payload={"review_request_id": uuid.uuid4()},
            )
            own_second = await notification_svc.add_notification(
                session,
                recipient_id=ids["student_1"],
                notification_type=NotificationType.REVIEW_REQUEST_RESOLVED,
                payload={"review_request_id": uuid.uuid4()},
            )
            foreign = await notification_svc.add_notification(
                session,
                recipient_id=ids["student_2"],
                notification_type=NotificationType.REVIEW_REQUEST_CREATED,
                payload={"review_request_id": uuid.uuid4()},
            )
            own_first.created_at = datetime(2026, 1, 1, tzinfo=UTC)
            own_second.created_at = datetime(2026, 1, 2, tzinfo=UTC)
            await session.flush()
            student = _actor(ids["student_1"], "Student 1", UserRole.STUDENT)
            first_page = await notification_svc.list_notifications(
                session, user=student, unread=None, page=1, page_size=1
            )
            second_page = await notification_svc.list_notifications(
                session, user=student, unread=None, page=2, page_size=1
            )
            assert first_page.total == second_page.total == 2
            assert first_page.items[0].id == own_second.id
            assert second_page.items[0].id == own_first.id
            assert (
                await notification_svc.list_notifications(
                    session, user=student, unread=True, page=1, page_size=50
                )
            ).total == 2
            assert (
                await notification_svc.list_notifications(
                    session, user=student, unread=False, page=1, page_size=50
                )
            ).total == 0

            with pytest.raises(HTTPException) as foreign_single:
                await notification_svc.mark_notification_read(
                    session, notification_id=foreign.id, user=student
                )
            assert foreign_single.value.status_code == 404
            with pytest.raises(HTTPException) as mixed_bulk:
                await notification_svc.mark_notifications_read(
                    session,
                    notification_ids=[own_first.id, foreign.id],
                    user=student,
                )
            assert mixed_bulk.value.status_code == 404
            assert own_first.read_at is None

            first_read = await notification_svc.mark_notification_read(
                session, notification_id=own_first.id, user=student
            )
            original_first_read_at = first_read.read_at
            replayed_read = await notification_svc.mark_notification_read(
                session, notification_id=own_first.id, user=student
            )
            assert replayed_read.read_at == original_first_read_at

            first_bulk = await notification_svc.mark_notifications_read(
                session,
                notification_ids=[own_second.id, own_first.id],
                user=student,
            )
            first_bulk_times = [item.read_at for item in first_bulk.items]
            replayed_bulk = await notification_svc.mark_notifications_read(
                session,
                notification_ids=[own_second.id, own_first.id],
                user=student,
            )
            assert [item.read_at for item in replayed_bulk.items] == first_bulk_times
            assert first_bulk.items[1].read_at == original_first_read_at
            assert (
                await notification_svc.list_notifications(
                    session, user=student, unread=True, page=1, page_size=50
                )
            ).total == 0
            assert (
                await notification_svc.list_notifications(
                    session, user=student, unread=False, page=1, page_size=50
                )
            ).total == 2

            other_student = _actor(ids["student_2"], "Student 2", UserRole.STUDENT)
            other_list = await notification_svc.list_notifications(
                session,
                user=other_student,
                unread=None,
                page=1,
                page_size=50,
            )
            assert other_list.total == 1
            assert other_list.items[0].id == foreign.id
        finally:
            await session.close()
            await transaction.rollback()
            await connection.close()
            await engine.dispose()

    asyncio.run(scenario())


def test_t017_notification_failure_rolls_back_source_transaction(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def scenario() -> None:
        ids = _ids()
        engine = create_async_engine(get_settings().database_url, poolclass=NullPool)
        connection = await engine.connect()
        transaction = await connection.begin()
        session = AsyncSession(bind=connection, expire_on_commit=False)
        try:
            await _seed_graph(connection, ids)
            await connection.execute(
                text(
                    "UPDATE public.document_versions "
                    "SET approved_at = now(), approved_by_user_id = :teacher, "
                    "approved_snapshot = '{}'::jsonb WHERE id = :document"
                ),
                {"teacher": ids["teacher"], "document": ids["document_2"]},
            )
            original_add = review_svc.notification_svc.add_notification

            async def fail_after_notification(
                *args, **kwargs
            ):  # noqa: ANN002, ANN003, ANN202
                await original_add(*args, **kwargs)
                raise RuntimeError("notification write failed")

            monkeypatch.setattr(
                review_svc.notification_svc,
                "add_notification",
                fail_after_notification,
            )
            teacher = _actor(ids["teacher"], "Teacher A", UserRole.TEACHER)
            with pytest.raises(RuntimeError, match="notification write failed"):
                async with session.begin_nested():
                    await publish_document_version(
                        session,
                        version_id=ids["document_2"],
                        user=teacher,
                        idempotency_key="rollback-publish",
                        reason="publish",
                    )

            status = await session.scalar(
                text(
                    "SELECT status FROM public.document_versions WHERE id = :document"
                ),
                {"document": ids["document_2"]},
            )
            result_count = await session.scalar(
                text(
                    "SELECT count(*) FROM public.published_result_versions "
                    "WHERE document_version_id = :document"
                ),
                {"document": ids["document_2"]},
            )
            notification_count = await session.scalar(
                text(
                    "SELECT count(*) FROM public.notifications "
                    "WHERE recipient_id = :recipient"
                ),
                {"recipient": ids["student_2"]},
            )
            assert str(status) == "APPROVED"
            assert result_count == 0
            assert notification_count == 0
        finally:
            await session.close()
            await transaction.rollback()
            await connection.close()
            await engine.dispose()

    asyncio.run(scenario())


async def _table_exists(engine: AsyncEngine, table_name: str) -> bool:
    async with engine.connect() as connection:
        return bool(
            await connection.scalar(
                text("SELECT to_regclass(:name) IS NOT NULL"),
                {"name": f"public.{table_name}"},
            )
        )


async def _assert_append_only_guards(engine: AsyncEngine) -> None:
    async with engine.connect() as connection:
        transaction = await connection.begin()
        try:
            statements = (
                "TRUNCATE TABLE public.audit_events",
                "TRUNCATE TABLE public.review_requests, "
                "public.published_result_versions",
            )
            for statement in statements:
                with pytest.raises(exc.DBAPIError, match="append-only"):
                    async with connection.begin_nested():
                        await connection.execute(text(statement))
        finally:
            await transaction.rollback()


async def _insert_downgrade_guard_rows(
    engine: AsyncEngine,
    *,
    user_id: uuid.UUID,
    notification_id: uuid.UUID,
) -> None:
    async with engine.begin() as connection:
        await connection.execute(
            text(
                "INSERT INTO public.users "
                "(id, email, display_name, password_hash, roles, status, revision) "
                "VALUES (:id, :email, 'T017 Student', 'hash', "
                "ARRAY['STUDENT']::public.user_role[], "
                "'ACTIVE'::public.user_status, 1)"
            ),
            {"id": user_id, "email": f"{user_id}@test.local"},
        )
        await connection.execute(
            text(
                "INSERT INTO public.notifications "
                "(id, recipient_id, type, payload) VALUES "
                "(:id, :recipient, "
                "'REVIEW_REQUEST_CREATED'::public.notification_type, "
                "CAST(:payload AS jsonb))"
            ),
            {
                "id": notification_id,
                "recipient": user_id,
                "payload": f'{{"review_request_id":"{uuid.uuid4()}"}}',
            },
        )


async def _delete_downgrade_guard_rows(
    engine: AsyncEngine,
    *,
    user_id: uuid.UUID,
    notification_id: uuid.UUID,
) -> None:
    async with engine.begin() as connection:
        if await connection.scalar(
            text("SELECT to_regclass('public.notifications') IS NOT NULL")
        ):
            await connection.execute(
                text("DELETE FROM public.notifications WHERE id = :id"),
                {"id": notification_id},
            )
        await connection.execute(
            text("DELETE FROM public.users WHERE id = :id"),
            {"id": user_id},
        )


def test_t017_migration_roundtrip_lossy_guard_and_append_only_guards() -> None:
    config = _config()
    engine = create_async_engine(get_settings().database_url, poolclass=NullPool)
    user_id = uuid.uuid4()
    notification_id = uuid.uuid4()
    try:
        command.upgrade(config, "head")
        assert asyncio.run(_table_exists(engine, "notifications"))
        asyncio.run(_assert_append_only_guards(engine))
        asyncio.run(
            _insert_downgrade_guard_rows(
                engine,
                user_id=user_id,
                notification_id=notification_id,
            )
        )
        with pytest.raises(RuntimeError, match="public.notifications"):
            command.downgrade(config, "20260912_0011")
        asyncio.run(
            _delete_downgrade_guard_rows(
                engine,
                user_id=user_id,
                notification_id=notification_id,
            )
        )

        command.downgrade(config, "20260912_0011")
        assert not asyncio.run(_table_exists(engine, "notifications"))
        asyncio.run(_assert_append_only_guards(engine))
        command.upgrade(config, "head")
        assert asyncio.run(_table_exists(engine, "notifications"))
        asyncio.run(_assert_append_only_guards(engine))
    finally:
        command.upgrade(config, "head")
        asyncio.run(
            _delete_downgrade_guard_rows(
                engine,
                user_id=user_id,
                notification_id=notification_id,
            )
        )
        asyncio.run(engine.dispose())
