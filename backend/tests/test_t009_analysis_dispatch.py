from __future__ import annotations

import asyncio
import importlib.util
import os
import time
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
import sqlalchemy as sa
from sqlalchemy import text
from sqlalchemy.dialects import postgresql
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

import app.models  # noqa: F401
from app.core.config import get_settings
from app.db.base import Base
from app.models.analysis import AnalysisJob, AnalysisJobDispatch
from app.models.enums import AnalysisJobStatus
from app.services import analysis_dispatch
from app.services.analysis_job import create_or_get_job


def test_analysis_job_dispatch_model_contract() -> None:
    table = Base.metadata.tables.get("analysis_job_dispatches")

    assert table is not None
    assert set(table.columns.keys()) == {
        "id",
        "analysis_job_id",
        "attempt_count",
        "next_attempt_at",
        "created_at",
        "updated_at",
    }
    assert table.c.analysis_job_id.unique is True
    assert table.c.analysis_job_id.foreign_keys
    assert {index.name for index in table.indexes} == {"ix_analysis_job_dispatches_due"}
    assert any(
        constraint.name == "ck_analysis_job_dispatches_attempt_count_nonnegative"
        for constraint in table.constraints
        if isinstance(constraint, sa.CheckConstraint)
    )


def test_analysis_job_dispatch_migration_contract() -> None:
    migration_path = (
        Path(__file__).resolve().parents[1]
        / "alembic"
        / "versions"
        / "20260829_0007_analysis_job_dispatch_outbox.py"
    )

    assert migration_path.exists()
    spec = importlib.util.spec_from_file_location(
        "migration_0007",
        migration_path,
    )
    assert spec is not None and spec.loader is not None
    migration_0007 = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration_0007)

    assert migration_0007.revision == "20260829_0007"
    assert migration_0007.down_revision == "20260828_0006"
    assert callable(migration_0007.upgrade)
    assert callable(migration_0007.downgrade)


def test_create_or_get_queued_job_enqueues_dispatch_in_same_session() -> None:
    job = SimpleNamespace(
        id=uuid.uuid4(),
        status=AnalysisJobStatus.QUEUED,
    )
    statements: list[object] = []

    class Result:
        def scalar_one_or_none(self):
            return job

    class DB:
        async def execute(self, statement):
            statements.append(statement)
            return Result()

    result = asyncio.run(
        create_or_get_job(
            DB(),
            document_version_id=uuid.uuid4(),
            rubric_version_id=uuid.uuid4(),
        )
    )

    assert result is job
    assert len(statements) == 2
    dispatch_sql = str(statements[1].compile(dialect=postgresql.dialect()))
    assert "INSERT INTO analysis_job_dispatches" in dispatch_sql
    assert "ON CONFLICT (analysis_job_id) DO NOTHING" in dispatch_sql


def test_retry_dispatch_updates_existing_schedule() -> None:
    statements: list[object] = []

    class DB:
        async def execute(self, statement):
            statements.append(statement)

    retry_at = datetime.now(UTC) + timedelta(seconds=30)
    asyncio.run(
        analysis_dispatch.enqueue_analysis_job_dispatch(
            DB(),
            uuid.uuid4(),
            next_attempt_at=retry_at,
        )
    )

    sql = str(statements[0].compile(dialect=postgresql.dialect()))
    assert "ON CONFLICT (analysis_job_id) DO UPDATE SET" in sql
    assert "next_attempt_at" in sql


def test_immediate_dispatch_does_not_wait_for_busy_poller_gate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def exercise() -> tuple[bool, float]:
        await analysis_dispatch._dispatch_gate.acquire()
        try:
            started = time.perf_counter()
            result = await asyncio.wait_for(
                analysis_dispatch.dispatch_analysis_job_now(uuid.uuid4()),
                timeout=0.1,
            )
            return result, time.perf_counter() - started
        finally:
            analysis_dispatch._dispatch_gate.release()

    monkeypatch.setattr(analysis_dispatch, "_PUBLISH_TIMEOUT_SECONDS", 0.01)
    result, elapsed = asyncio.run(exercise())

    assert result is False
    assert elapsed < 0.1


def test_dispatch_due_jobs_publishes_and_deletes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    dispatch = SimpleNamespace(
        analysis_job_id=uuid.uuid4(),
        attempt_count=0,
        next_attempt_at=datetime.now(UTC),
    )
    statement_holder: list[object] = []

    class ScalarResult:
        def all(self):
            return [dispatch]

    class Result:
        def scalars(self):
            return ScalarResult()

    class DB:
        delete = AsyncMock()
        flush = AsyncMock()

        async def execute(self, statement):
            statement_holder.append(statement)
            return Result()

    assert hasattr(analysis_dispatch, "_publish_analysis_job")
    assert hasattr(analysis_dispatch, "dispatch_due_analysis_jobs")

    publish = AsyncMock()
    monkeypatch.setattr(analysis_dispatch, "_publish_analysis_job", publish)

    sent = asyncio.run(analysis_dispatch.dispatch_due_analysis_jobs(DB(), limit=10))

    assert sent == 1
    publish.assert_awaited_once_with(dispatch.analysis_job_id)
    DB.delete.assert_awaited_once_with(dispatch)
    DB.flush.assert_awaited_once()
    sql = str(statement_holder[0].compile(dialect=postgresql.dialect()))
    assert "FOR UPDATE SKIP LOCKED" in sql


def test_dispatch_due_jobs_retains_failure_with_backoff(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    before = datetime.now(UTC)
    dispatch = SimpleNamespace(
        analysis_job_id=uuid.uuid4(),
        attempt_count=0,
        next_attempt_at=before,
    )

    class ScalarResult:
        def all(self):
            return [dispatch]

    class Result:
        def scalars(self):
            return ScalarResult()

    class DB:
        delete = AsyncMock()
        flush = AsyncMock()

        async def execute(self, _statement):
            return Result()

    assert hasattr(analysis_dispatch, "_publish_analysis_job")
    assert hasattr(analysis_dispatch, "dispatch_due_analysis_jobs")

    publish = AsyncMock(side_effect=RuntimeError("broker unavailable"))
    monkeypatch.setattr(analysis_dispatch, "_publish_analysis_job", publish)

    sent = asyncio.run(analysis_dispatch.dispatch_due_analysis_jobs(DB(), limit=10))

    assert sent == 0
    assert dispatch.attempt_count == 1
    assert dispatch.next_attempt_at > before
    DB.delete.assert_not_awaited()
    DB.flush.assert_awaited_once()


def test_celery_producer_publish_is_bounded(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.core.config import get_settings

    with monkeypatch.context() as scoped:
        scoped.setenv("POSTGRES_DB", "docgrading")
        scoped.setenv("POSTGRES_USER", "docgrading")
        scoped.setenv("POSTGRES_PASSWORD", "test-password")
        get_settings.cache_clear()
        from app.workers.celery_app import celery_app

        assert celery_app.conf.task_publish_retry is True
        assert celery_app.conf.broker_transport_options == {
            "socket_connect_timeout": 3,
            "socket_timeout": 3,
            "retry_on_timeout": False,
        }
    get_settings.cache_clear()


def test_publish_timeout_does_not_block_event_loop(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.core.config import get_settings

    with monkeypatch.context() as scoped:
        scoped.setenv("POSTGRES_DB", "docgrading")
        scoped.setenv("POSTGRES_USER", "docgrading")
        scoped.setenv("POSTGRES_PASSWORD", "test-password")
        get_settings.cache_clear()
        from app.workers import tasks

        publish_options: dict[str, object] = {}

        def blocking_publish(*_args, **kwargs):
            publish_options.update(kwargs)
            time.sleep(0.1)

        scoped.setattr(
            tasks.process_analysis_job,
            "apply_async",
            blocking_publish,
        )
        scoped.setattr(
            analysis_dispatch,
            "_PUBLISH_TIMEOUT_SECONDS",
            0.02,
        )
        heartbeat_observed = False

        async def exercise() -> None:
            nonlocal heartbeat_observed

            async def heartbeat() -> None:
                nonlocal heartbeat_observed
                await asyncio.sleep(0.005)
                heartbeat_observed = True

            heartbeat_task = asyncio.create_task(heartbeat())
            with pytest.raises(TimeoutError):
                await analysis_dispatch._publish_analysis_job(uuid.uuid4())
            await heartbeat_task

        asyncio.run(exercise())
        assert heartbeat_observed
        assert publish_options["retry"] is False
    get_settings.cache_clear()


def test_immediate_dispatch_owns_commit_and_swallows_database_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[str] = []

    class DB:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

        async def commit(self):
            events.append("commit")

    class Factory:
        def __call__(self):
            return DB()

    async def dispatch(_db, **_kwargs):
        events.append("dispatch")
        return 1

    monkeypatch.setattr(
        analysis_dispatch,
        "_session_factory",
        lambda: Factory(),
        raising=False,
    )
    monkeypatch.setattr(
        analysis_dispatch,
        "dispatch_due_analysis_jobs",
        dispatch,
    )

    assert asyncio.run(analysis_dispatch.dispatch_analysis_job_now(uuid.uuid4()))
    assert events == ["dispatch", "commit"]

    class BrokenFactory:
        def __call__(self):
            raise RuntimeError("database unavailable")

    monkeypatch.setattr(
        analysis_dispatch,
        "_session_factory",
        lambda: BrokenFactory(),
        raising=False,
    )
    assert not asyncio.run(analysis_dispatch.dispatch_analysis_job_now(uuid.uuid4()))


def test_dispatch_poller_recovers_with_fresh_session(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sessions_created = 0
    dispatch_calls = 0

    class DB:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

        commit = AsyncMock()
        rollback = AsyncMock()

    class Factory:
        def __call__(self):
            nonlocal sessions_created
            sessions_created += 1
            return DB()

    async def dispatch(_db, **_kwargs):
        nonlocal dispatch_calls
        dispatch_calls += 1
        if dispatch_calls == 1:
            raise RuntimeError("temporary database failure")
        raise asyncio.CancelledError

    sleep_calls = 0

    async def sleep(_seconds):
        nonlocal sleep_calls
        sleep_calls += 1

    monkeypatch.setattr(
        analysis_dispatch,
        "_session_factory",
        lambda: Factory(),
        raising=False,
    )
    monkeypatch.setattr(
        analysis_dispatch,
        "dispatch_due_analysis_jobs",
        dispatch,
    )
    monkeypatch.setattr(asyncio, "sleep", sleep)

    with pytest.raises(asyncio.CancelledError):
        asyncio.run(analysis_dispatch.run_analysis_dispatch_poller())

    assert sleep_calls >= 2
    assert sessions_created == 2


def test_fastapi_lifespan_cancels_dispatch_poller(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.core.config import get_settings

    with monkeypatch.context() as scoped:
        scoped.setenv("POSTGRES_DB", "docgrading")
        scoped.setenv("POSTGRES_USER", "docgrading")
        scoped.setenv("POSTGRES_PASSWORD", "test-password")
        get_settings.cache_clear()
        from app import main

        started = asyncio.Event()
        cancelled = asyncio.Event()

        async def poller():
            started.set()
            try:
                await asyncio.Event().wait()
            finally:
                cancelled.set()

        scoped.setattr(
            main,
            "run_analysis_dispatch_poller",
            poller,
            raising=False,
        )

        async def exercise():
            async with main.lifespan(main.app):
                await started.wait()
            assert cancelled.is_set()

        asyncio.run(exercise())
    get_settings.cache_clear()


def test_complete_route_commits_before_immediate_dispatch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.api.routers import submissions as router

    events: list[str] = []
    job_id = uuid.uuid4()
    version = SimpleNamespace(
        id=uuid.uuid4(),
        submission_id=uuid.uuid4(),
    )
    job = SimpleNamespace(
        id=job_id,
        status=AnalysisJobStatus.QUEUED,
    )

    async def complete(*_args, **_kwargs):
        return version, job

    async def dispatch(received_job_id):
        assert received_job_id == job_id
        events.append("dispatch")
        return False

    class DB:
        async def commit(self):
            events.append("commit")

    monkeypatch.setattr(router.submission_svc, "complete_upload", complete)
    monkeypatch.setattr(router, "dispatch_analysis_job_now", dispatch)

    response = asyncio.run(
        router.complete_upload(
            version.id,
            user=SimpleNamespace(),
            db=DB(),
        )
    )

    assert response.analysis_job_id == job_id
    assert events == ["commit", "dispatch"]


def test_retry_route_commits_before_failed_immediate_dispatch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.api.routers import submissions as router

    events: list[str] = []
    job_id = uuid.uuid4()
    now = datetime.now(UTC)
    job = SimpleNamespace(
        id=job_id,
        document_version_id=uuid.uuid4(),
        rubric_version_id=uuid.uuid4(),
        status=AnalysisJobStatus.QUEUED,
        attempt_count=1,
        max_attempts=3,
        error_code=None,
        error_detail=None,
        queued_at=now,
        started_at=None,
        finished_at=None,
    )

    async def get_job(_db, received_job_id):
        assert received_job_id == job_id
        return job

    async def retry(_db, received_job, _user):
        assert received_job is job
        return job

    async def dispatch(received_job_id):
        assert received_job_id == job_id
        events.append("dispatch")
        return False

    class DB:
        async def commit(self):
            events.append("commit")

    monkeypatch.setattr(router.job_svc, "get_job", get_job)
    monkeypatch.setattr(router.job_svc, "retry_job", retry)
    monkeypatch.setattr(router, "dispatch_analysis_job_now", dispatch)

    response = asyncio.run(
        router.retry_analysis_job(
            job_id,
            user=SimpleNamespace(),
            db=DB(),
        )
    )

    assert response.id == job_id
    assert events == ["commit", "dispatch"]


async def _seed_outbox_domain(engine, ids: dict[str, uuid.UUID]) -> None:
    async with engine.begin() as conn:
        await conn.execute(
            text("""
                INSERT INTO public.users
                    (id, email, display_name, password_hash, roles, status, revision)
                VALUES
                    (:teacher, :teacher_email, 'T', 'hash',
                     ARRAY['TEACHER']::public.user_role[],
                     'ACTIVE'::public.user_status, 1),
                    (:student, :student_email, 'S', 'hash',
                     ARRAY['STUDENT']::public.user_role[],
                     'ACTIVE'::public.user_status, 1)
            """),
            {
                "teacher": ids["teacher"],
                "student": ids["student"],
                "teacher_email": f"{ids['teacher']}@x",
                "student_email": f"{ids['student']}@x",
            },
        )
        await conn.execute(
            text("""
                INSERT INTO public.courses
                    (id, code, name, term, owner_teacher_id, revision)
                VALUES (:id, :code, 'C', 'T', :teacher, 1)
            """),
            {
                "id": ids["course"],
                "code": f"C-{ids['course']}",
                "teacher": ids["teacher"],
            },
        )
        await conn.execute(
            text("""
                INSERT INTO public.memberships
                    (id, course_id, user_id, role, status)
                VALUES
                    (
                        :id, :course, :student,
                        'STUDENT'::public.membership_role,
                        'ACTIVE'::public.membership_status
                    )
            """),
            {
                "id": ids["membership"],
                "course": ids["course"],
                "student": ids["student"],
            },
        )
        await conn.execute(
            text("""
                INSERT INTO public.rubric_versions
                    (
                        id, rubric_id, version_number, name, status,
                        calculation_method, total_weight, owner_user_id,
                        created_by_user_id, revision
                    )
                VALUES
                    (
                        :id, :rubric_id, 1, 'R',
                        'DRAFT'::public.rubric_status, 'WEIGHTED_SUM',
                        0, :teacher, :teacher, 1
                    )
            """),
            {
                "id": ids["rubric"],
                "rubric_id": uuid.uuid4(),
                "teacher": ids["teacher"],
            },
        )
        await conn.execute(
            text("""
                INSERT INTO public.assignments
                    (
                        id, course_id, created_by_teacher_id,
                        rubric_version_id, title, due_at,
                        max_submissions, status, published_at, revision
                    )
                VALUES
                    (
                        :id, :course, :teacher, :rubric, 'A', :due_at,
                        3, 'OPEN'::public.assignment_status, :published_at, 1
                    )
            """),
            {
                "id": ids["assignment"],
                "course": ids["course"],
                "teacher": ids["teacher"],
                "rubric": ids["rubric"],
                "due_at": datetime.now(UTC) + timedelta(days=1),
                "published_at": datetime.now(UTC),
            },
        )
        await conn.execute(
            text("""
                INSERT INTO public.submissions
                    (id, assignment_id, student_id)
                VALUES (:id, :assignment, :student)
            """),
            {
                "id": ids["submission"],
                "assignment": ids["assignment"],
                "student": ids["student"],
            },
        )
        for version, document_name in enumerate(
            ("document", "rolled_back_document"),
            start=1,
        ):
            await conn.execute(
                text("""
                    INSERT INTO public.document_versions
                        (
                            id, submission_id, version_number, storage_key,
                            original_filename, content_type, size_bytes,
                            sha256, status
                        )
                    VALUES
                        (
                            :id, :submission, :version, :key, 'a.pdf',
                            'application/pdf', 5, :sha,
                            'QUEUED'::public.document_status
                        )
                """),
                {
                    "id": ids[document_name],
                    "submission": ids["submission"],
                    "version": version,
                    "key": f"x/{ids[document_name]}",
                    "sha": uuid.uuid4().hex + uuid.uuid4().hex,
                },
            )


async def _cleanup_outbox_domain(
    engine,
    ids: dict[str, uuid.UUID],
) -> None:
    async with engine.begin() as conn:
        document_ids = [
            ids["document"],
            ids["rolled_back_document"],
        ]
        await conn.execute(
            text(
                "DELETE FROM public.analysis_jobs "
                "WHERE document_version_id = ANY(:document_ids)"
            ),
            {"document_ids": document_ids},
        )
        await conn.execute(
            text(
                "DELETE FROM public.document_versions " "WHERE id = ANY(:document_ids)"
            ),
            {"document_ids": document_ids},
        )
        for table, key in (
            ("submissions", "submission"),
            ("assignments", "assignment"),
            ("rubric_versions", "rubric"),
            ("memberships", "membership"),
            ("courses", "course"),
        ):
            await conn.execute(
                text(f"DELETE FROM public.{table} WHERE id = :id"),
                {"id": ids[key]},
            )
        await conn.execute(
            text("DELETE FROM public.users " "WHERE id IN (:teacher, :student)"),
            {
                "teacher": ids["teacher"],
                "student": ids["student"],
            },
        )


async def _run_atomic_outbox_contract() -> None:
    engine = create_async_engine(
        get_settings().database_url,
        poolclass=NullPool,
    )
    ids = {
        name: uuid.uuid4()
        for name in (
            "teacher",
            "student",
            "course",
            "membership",
            "rubric",
            "assignment",
            "submission",
            "document",
            "rolled_back_document",
        )
    }
    setup_complete = False
    try:
        await _seed_outbox_domain(engine, ids)
        setup_complete = True
        sessions = async_sessionmaker(engine, expire_on_commit=False)
        async with sessions() as db:
            job = await create_or_get_job(
                db,
                document_version_id=ids["document"],
                rubric_version_id=ids["rubric"],
            )
            await db.commit()
            same_job = await create_or_get_job(
                db,
                document_version_id=ids["document"],
                rubric_version_id=ids["rubric"],
            )
            await db.commit()
            assert same_job.id == job.id

        async with sessions() as check:
            dispatch_count = (
                await check.execute(
                    sa.select(sa.func.count())
                    .select_from(AnalysisJobDispatch)
                    .where(AnalysisJobDispatch.analysis_job_id == job.id)
                )
            ).scalar_one()
            assert dispatch_count == 1

        async with sessions() as rolled_back:
            await create_or_get_job(
                rolled_back,
                document_version_id=ids["rolled_back_document"],
                rubric_version_id=ids["rubric"],
            )
            await rolled_back.rollback()

        async with sessions() as check:
            rolled_back_jobs = (
                await check.execute(
                    sa.select(sa.func.count())
                    .select_from(AnalysisJob)
                    .where(
                        AnalysisJob.document_version_id == ids["rolled_back_document"]
                    )
                )
            ).scalar_one()
            assert rolled_back_jobs == 0
    finally:
        if setup_complete:
            await _cleanup_outbox_domain(engine, ids)
        await engine.dispose()


@pytest.mark.skipif(
    os.environ.get("RUN_DATABASE_TESTS") != "1",
    reason="Database integration tests require RUN_DATABASE_TESTS=1",
)
def test_queued_job_and_dispatch_are_atomic_postgres() -> None:
    asyncio.run(_run_atomic_outbox_contract())


async def _run_concurrent_dispatch_contract(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine = create_async_engine(
        get_settings().database_url,
        poolclass=NullPool,
    )
    ids = {
        name: uuid.uuid4()
        for name in (
            "teacher",
            "student",
            "course",
            "membership",
            "rubric",
            "assignment",
            "submission",
            "document",
            "rolled_back_document",
        )
    }
    setup_complete = False
    release_publish = asyncio.Event()
    publish_started = asyncio.Event()
    published_job_ids: list[uuid.UUID] = []

    async def publish(job_id: uuid.UUID) -> None:
        published_job_ids.append(job_id)
        publish_started.set()
        await release_publish.wait()

    try:
        await _seed_outbox_domain(engine, ids)
        setup_complete = True
        sessions = async_sessionmaker(engine, expire_on_commit=False)
        async with sessions() as setup:
            job = await create_or_get_job(
                setup,
                document_version_id=ids["document"],
                rubric_version_id=ids["rubric"],
            )
            await setup.commit()

        monkeypatch.setattr(
            analysis_dispatch,
            "_publish_analysis_job",
            publish,
        )
        async with sessions() as first, sessions() as second:
            first_task = asyncio.create_task(
                analysis_dispatch.dispatch_due_analysis_jobs(
                    first,
                    job_id=job.id,
                    limit=1,
                )
            )
            await publish_started.wait()
            second_sent = await analysis_dispatch.dispatch_due_analysis_jobs(
                second,
                job_id=job.id,
                limit=1,
            )
            await second.commit()
            assert second_sent == 0

            release_publish.set()
            assert await first_task == 1
            await first.commit()

        assert published_job_ids == [job.id]
    finally:
        release_publish.set()
        if setup_complete:
            await _cleanup_outbox_domain(engine, ids)
        await engine.dispose()


@pytest.mark.skipif(
    os.environ.get("RUN_DATABASE_TESTS") != "1",
    reason="Database integration tests require RUN_DATABASE_TESTS=1",
)
def test_concurrent_dispatchers_have_one_skip_locked_publisher(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    asyncio.run(_run_concurrent_dispatch_contract(monkeypatch))
