"""Real PostgreSQL concurrency contract for the durable job pickup."""

# SQL fixtures are intentionally readable as complete statements.
# ruff: noqa: E501

from __future__ import annotations

import asyncio
import os
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.core.config import get_settings
from app.services.analysis_job import (
    claim_job_by_id,
    claim_next_job,
    mark_done,
    mark_error,
    update_heartbeat,
)

pytestmark = pytest.mark.skipif(
    os.environ.get("RUN_DATABASE_TESTS") != "1",
    reason="Database integration tests require RUN_DATABASE_TESTS=1",
)


async def _run_two_session_claim() -> None:
    settings = get_settings()
    engine = create_async_engine(settings.database_url, poolclass=NullPool)
    ids = {
        name: uuid.uuid4()
        for name in (
            "teacher",
            "student",
            "course",
            "member",
            "rubric",
            "assignment",
            "submission",
            "document",
            "job",
        )
    }
    setup_complete = False
    try:
        async with engine.begin() as conn:
            await conn.execute(
                text("""
                    INSERT INTO public.users (id, email, display_name, password_hash, roles, status, revision)
                    VALUES (:teacher, :teacher_email, 'T', 'hash', ARRAY['TEACHER']::public.user_role[], 'ACTIVE'::public.user_status, 1),
                           (:student, :student_email, 'S', 'hash', ARRAY['STUDENT']::public.user_role[], 'ACTIVE'::public.user_status, 1)
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
                INSERT INTO public.courses (id, code, name, term, owner_teacher_id, revision)
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
                INSERT INTO public.memberships (id, course_id, user_id, role, status)
                VALUES (:id, :course, :student, 'STUDENT'::public.membership_role, 'ACTIVE'::public.membership_status)
            """),
                {
                    "id": ids["member"],
                    "course": ids["course"],
                    "student": ids["student"],
                },
            )
            await conn.execute(
                text("""
                INSERT INTO public.rubric_versions (id, rubric_id, version_number, name, status, calculation_method, total_weight, owner_user_id, created_by_user_id, revision)
                VALUES (:id, :rid, 1, 'R', 'DRAFT'::public.rubric_status, 'WEIGHTED_SUM', 0, :teacher, :teacher, 1)
            """),
                {"id": ids["rubric"], "rid": uuid.uuid4(), "teacher": ids["teacher"]},
            )
            now = datetime.now(UTC)
            await conn.execute(
                text("""
                INSERT INTO public.assignments (id, course_id, created_by_teacher_id, rubric_version_id, title, due_at, max_submissions, status, published_at, revision)
                VALUES (:id, :course, :teacher, :rubric, 'A', :due, 3, 'OPEN'::public.assignment_status, :published, 1)
            """),
                {
                    "id": ids["assignment"],
                    "course": ids["course"],
                    "teacher": ids["teacher"],
                    "rubric": ids["rubric"],
                    "due": now + timedelta(days=1),
                    "published": now,
                },
            )
            await conn.execute(
                text("""
                INSERT INTO public.submissions (id, assignment_id, student_id) VALUES (:id, :assignment, :student)
            """),
                {
                    "id": ids["submission"],
                    "assignment": ids["assignment"],
                    "student": ids["student"],
                },
            )
            await conn.execute(
                text("""
                INSERT INTO public.document_versions (id, submission_id, version_number, storage_key, original_filename, content_type, size_bytes, sha256, status)
                VALUES (:id, :submission, 1, :key, 'a.pdf', 'application/pdf', 5, :sha, 'QUEUED'::public.document_status)
            """),
                {
                    "id": ids["document"],
                    "submission": ids["submission"],
                    "key": f"x/{ids['document']}",
                    "sha": uuid.uuid4().hex + uuid.uuid4().hex,
                },
            )
            await conn.execute(
                text("""
                INSERT INTO public.analysis_jobs (id, document_version_id, rubric_version_id, status, snapshot)
                VALUES (:id, :document, :rubric, 'QUEUED'::public.analysis_job_status, '{}'::jsonb)
            """),
                {
                    "id": ids["job"],
                    "document": ids["document"],
                    "rubric": ids["rubric"],
                },
            )

        setup_complete = True
        sessions = async_sessionmaker(engine, expire_on_commit=False)
        async with sessions() as first, sessions() as second:
            winner = await claim_next_job(first)
            assert winner is not None and winner.id == ids["job"]
            assert (await claim_next_job(second)) is None
            await first.rollback()
            await second.rollback()
    finally:
        if setup_complete:
            async with engine.begin() as conn:
                await conn.execute(
                    text("DELETE FROM public.analysis_jobs WHERE id = :id"),
                    {"id": ids["job"]},
                )
                await conn.execute(
                    text("DELETE FROM public.document_versions WHERE id = :id"),
                    {"id": ids["document"]},
                )
                await conn.execute(
                    text("DELETE FROM public.submissions WHERE id = :id"),
                    {"id": ids["submission"]},
                )
                await conn.execute(
                    text("DELETE FROM public.assignments WHERE id = :id"),
                    {"id": ids["assignment"]},
                )
                await conn.execute(
                    text("DELETE FROM public.rubric_versions WHERE id = :id"),
                    {"id": ids["rubric"]},
                )
                await conn.execute(
                    text("DELETE FROM public.memberships WHERE id = :id"),
                    {"id": ids["member"]},
                )
                await conn.execute(
                    text("DELETE FROM public.courses WHERE id = :id"),
                    {"id": ids["course"]},
                )
                await conn.execute(
                    text("DELETE FROM public.users WHERE id IN (:teacher, :student)"),
                    {"teacher": ids["teacher"], "student": ids["student"]},
                )
        await engine.dispose()


def test_postgresql_two_workers_have_one_skip_locked_winner() -> None:
    asyncio.run(_run_two_session_claim())


async def _run_stale_job_recovery() -> None:
    settings = get_settings()
    engine = create_async_engine(settings.database_url, poolclass=NullPool)
    ids = {
        name: uuid.uuid4()
        for name in (
            "teacher",
            "student",
            "course",
            "member",
            "rubric",
            "assignment",
            "submission",
            "document",
            "job",
        )
    }
    setup_complete = False
    try:
        async with engine.begin() as conn:
            await conn.execute(
                text("""
                    INSERT INTO public.users (id, email, display_name, password_hash, roles, status, revision)
                    VALUES (:teacher, :teacher_email, 'T', 'hash', ARRAY['TEACHER']::public.user_role[], 'ACTIVE'::public.user_status, 1),
                           (:student, :student_email, 'S', 'hash', ARRAY['STUDENT']::public.user_role[], 'ACTIVE'::public.user_status, 1)
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
                INSERT INTO public.courses (id, code, name, term, owner_teacher_id, revision)
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
                INSERT INTO public.memberships (id, course_id, user_id, role, status)
                VALUES (:id, :course, :student, 'STUDENT'::public.membership_role, 'ACTIVE'::public.membership_status)
            """),
                {
                    "id": ids["member"],
                    "course": ids["course"],
                    "student": ids["student"],
                },
            )
            await conn.execute(
                text("""
                INSERT INTO public.rubric_versions (id, rubric_id, version_number, name, status, calculation_method, total_weight, owner_user_id, created_by_user_id, revision)
                VALUES (:id, :rid, 1, 'R', 'DRAFT'::public.rubric_status, 'WEIGHTED_SUM', 0, :teacher, :teacher, 1)
            """),
                {"id": ids["rubric"], "rid": uuid.uuid4(), "teacher": ids["teacher"]},
            )
            now = datetime.now(UTC)
            await conn.execute(
                text("""
                INSERT INTO public.assignments (id, course_id, created_by_teacher_id, rubric_version_id, title, due_at, max_submissions, status, published_at, revision)
                VALUES (:id, :course, :teacher, :rubric, 'A', :due, 3, 'OPEN'::public.assignment_status, :published, 1)
            """),
                {
                    "id": ids["assignment"],
                    "course": ids["course"],
                    "teacher": ids["teacher"],
                    "rubric": ids["rubric"],
                    "due": now + timedelta(days=1),
                    "published": now,
                },
            )
            await conn.execute(
                text("""
                INSERT INTO public.submissions (id, assignment_id, student_id) VALUES (:id, :assignment, :student)
            """),
                {
                    "id": ids["submission"],
                    "assignment": ids["assignment"],
                    "student": ids["student"],
                },
            )
            await conn.execute(
                text("""
                INSERT INTO public.document_versions (id, submission_id, version_number, storage_key, original_filename, content_type, size_bytes, sha256, status, failure_code, failure_detail)
                VALUES (:id, :submission, 1, :key, 'a.pdf', 'application/pdf', 5, :sha, 'QUEUED'::public.document_status, 'STALE_ERR', 'stale detail')
            """),
                {
                    "id": ids["document"],
                    "submission": ids["submission"],
                    "key": f"x/{ids['document']}",
                    "sha": uuid.uuid4().hex + uuid.uuid4().hex,
                },
            )
            await conn.execute(
                text("""
                INSERT INTO public.analysis_jobs (id, document_version_id, rubric_version_id, status, snapshot, attempt_count, max_attempts)
                VALUES (:id, :document, :rubric, 'QUEUED'::public.analysis_job_status, '{}'::jsonb, 0, 3)
            """),
                {
                    "id": ids["job"],
                    "document": ids["document"],
                    "rubric": ids["rubric"],
                },
            )

        setup_complete = True
        sessions = async_sessionmaker(engine, expire_on_commit=False)

        # 1. Session A claims queued job and commits RUNNING
        async with sessions() as session_a:
            job_a = await claim_next_job(session_a)
            assert job_a is not None and job_a.id == ids["job"]
            assert job_a.status.value == "RUNNING"
            assert job_a.attempt_count == 1
            await session_a.commit()

        # 2. Simulate worker loss by making heartbeat stale
        stale_time = datetime.now(UTC) - timedelta(seconds=400)
        async with engine.begin() as conn:
            await conn.execute(
                text(
                    "UPDATE public.analysis_jobs "
                    "SET heartbeat_at = :stale, started_at = :stale "
                    "WHERE id = :id"
                ),
                {"stale": stale_time, "id": ids["job"]},
            )

        # 3. Session B redelivers claim_job_by_id, commits recovery
        async with sessions() as session_b:
            job_b = await claim_job_by_id(session_b, ids["job"])
            assert job_b is not None and job_b.id == ids["job"]
            assert job_b.status.value == "RUNNING"
            assert job_b.attempt_count == 2
            await session_b.commit()

        # 4. Prove same row in DB is RUNNING attempt 2, document is PROCESSING, and audits exist
        async with engine.begin() as conn:
            job_row = (
                await conn.execute(
                    text(
                        "SELECT status::text, attempt_count, heartbeat_at "
                        "FROM public.analysis_jobs WHERE id = :id"
                    ),
                    {"id": ids["job"]},
                )
            ).one()
            assert job_row[0] == "RUNNING"
            assert job_row[1] == 2
            assert job_row[2] > stale_time

            doc_row = (
                await conn.execute(
                    text(
                        "SELECT status::text, failure_code, failure_detail "
                        "FROM public.document_versions WHERE id = :id"
                    ),
                    {"id": ids["document"]},
                )
            ).one()
            assert doc_row[0] == "PROCESSING"
            assert doc_row[1] is None  # Stale failure cleared
            assert doc_row[2] is None

            job_audits = (
                await conn.execute(
                    text(
                        "SELECT action, before, after FROM public.audit_events "
                        "WHERE resource_id = :id ORDER BY created_at ASC"
                    ),
                    {"id": ids["job"]},
                )
            ).all()
            actions = [row[0] for row in job_audits]
            assert "QUEUED" in actions  # Lease requeue event
            assert "RUNNING" in actions  # Claim events
    finally:
        if setup_complete:
            async with engine.begin() as conn:
                await conn.execute(
                    text(
                        "DELETE FROM public.audit_events "
                        "WHERE resource_id IN (:job, :document)"
                    ),
                    {"job": ids["job"], "document": ids["document"]},
                )
                await conn.execute(
                    text("DELETE FROM public.analysis_jobs WHERE id = :id"),
                    {"id": ids["job"]},
                )
                await conn.execute(
                    text("DELETE FROM public.document_versions WHERE id = :id"),
                    {"id": ids["document"]},
                )
                await conn.execute(
                    text("DELETE FROM public.submissions WHERE id = :id"),
                    {"id": ids["submission"]},
                )
                await conn.execute(
                    text("DELETE FROM public.assignments WHERE id = :id"),
                    {"id": ids["assignment"]},
                )
                await conn.execute(
                    text("DELETE FROM public.rubric_versions WHERE id = :id"),
                    {"id": ids["rubric"]},
                )
                await conn.execute(
                    text("DELETE FROM public.memberships WHERE id = :id"),
                    {"id": ids["member"]},
                )
                await conn.execute(
                    text("DELETE FROM public.courses WHERE id = :id"),
                    {"id": ids["course"]},
                )
                await conn.execute(
                    text("DELETE FROM public.users WHERE id IN (:teacher, :student)"),
                    {"teacher": ids["teacher"], "student": ids["student"]},
                )
        await engine.dispose()


def test_postgresql_stale_job_redelivered_and_reclaimed_with_audits() -> None:
    asyncio.run(_run_stale_job_recovery())


async def _run_split_brain_fencing() -> None:
    settings = get_settings()
    engine = create_async_engine(settings.database_url, poolclass=NullPool)
    ids = {
        name: uuid.uuid4()
        for name in (
            "teacher",
            "student",
            "course",
            "member",
            "rubric",
            "assignment",
            "submission",
            "document",
            "job",
        )
    }
    setup_complete = False
    try:
        async with engine.begin() as conn:
            await conn.execute(
                text("""
                    INSERT INTO public.users (id, email, display_name, password_hash, roles, status, revision)
                    VALUES (:teacher, :teacher_email, 'T', 'hash', ARRAY['TEACHER']::public.user_role[], 'ACTIVE'::public.user_status, 1),
                           (:student, :student_email, 'S', 'hash', ARRAY['STUDENT']::public.user_role[], 'ACTIVE'::public.user_status, 1)
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
                INSERT INTO public.courses (id, code, name, term, owner_teacher_id, revision)
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
                INSERT INTO public.memberships (id, course_id, user_id, role, status)
                VALUES (:id, :course, :student, 'STUDENT'::public.membership_role, 'ACTIVE'::public.membership_status)
            """),
                {
                    "id": ids["member"],
                    "course": ids["course"],
                    "student": ids["student"],
                },
            )
            await conn.execute(
                text("""
                INSERT INTO public.rubric_versions (id, rubric_id, version_number, name, status, calculation_method, total_weight, owner_user_id, created_by_user_id, revision)
                VALUES (:id, :rid, 1, 'R', 'DRAFT'::public.rubric_status, 'WEIGHTED_SUM', 0, :teacher, :teacher, 1)
            """),
                {"id": ids["rubric"], "rid": uuid.uuid4(), "teacher": ids["teacher"]},
            )
            now = datetime.now(UTC)
            await conn.execute(
                text("""
                INSERT INTO public.assignments (id, course_id, created_by_teacher_id, rubric_version_id, title, due_at, max_submissions, status, published_at, revision)
                VALUES (:id, :course, :teacher, :rubric, 'A', :due, 3, 'OPEN'::public.assignment_status, :published, 1)
            """),
                {
                    "id": ids["assignment"],
                    "course": ids["course"],
                    "teacher": ids["teacher"],
                    "rubric": ids["rubric"],
                    "due": now + timedelta(days=1),
                    "published": now,
                },
            )
            await conn.execute(
                text("""
                INSERT INTO public.submissions (id, assignment_id, student_id) VALUES (:id, :assignment, :student)
            """),
                {
                    "id": ids["submission"],
                    "assignment": ids["assignment"],
                    "student": ids["student"],
                },
            )
            await conn.execute(
                text("""
                INSERT INTO public.document_versions (id, submission_id, version_number, storage_key, original_filename, content_type, size_bytes, sha256, status)
                VALUES (:id, :submission, 1, :key, 'a.pdf', 'application/pdf', 5, :sha, 'QUEUED'::public.document_status)
            """),
                {
                    "id": ids["document"],
                    "submission": ids["submission"],
                    "key": f"x/{ids['document']}",
                    "sha": uuid.uuid4().hex + uuid.uuid4().hex,
                },
            )
            await conn.execute(
                text("""
                INSERT INTO public.analysis_jobs (id, document_version_id, rubric_version_id, status, snapshot, attempt_count, max_attempts)
                VALUES (:id, :document, :rubric, 'QUEUED'::public.analysis_job_status, '{}'::jsonb, 0, 3)
            """),
                {
                    "id": ids["job"],
                    "document": ids["document"],
                    "rubric": ids["rubric"],
                },
            )

        setup_complete = True
        sessions = async_sessionmaker(engine, expire_on_commit=False)

        # 1. Session A claims queued job and commits RUNNING (attempt 1)
        async with sessions() as session_a:
            job_a = await claim_next_job(session_a)
            assert job_a is not None and job_a.id == ids["job"]
            assert job_a.status.value == "RUNNING"
            assert job_a.attempt_count == 1
            await session_a.commit()

        # 2. Simulate worker loss by making heartbeat and started_at stale
        stale_time = datetime.now(UTC) - timedelta(seconds=400)
        async with engine.begin() as conn:
            await conn.execute(
                text(
                    "UPDATE public.analysis_jobs "
                    "SET heartbeat_at = :stale, started_at = :stale "
                    "WHERE id = :id"
                ),
                {"stale": stale_time, "id": ids["job"]},
            )

        # 3. Session B redelivers claim_job_by_id, commits recovery as attempt 2
        async with sessions() as session_b:
            job_b = await claim_job_by_id(session_b, ids["job"])
            assert job_b is not None and job_b.id == ids["job"]
            assert job_b.status.value == "RUNNING"
            assert job_b.attempt_count == 2
            await session_b.commit()

        # 4. Worker A resumes and attempts operations with attempt_count 1
        async with sessions() as session_a_resumed:
            # Heartbeat attempt with attempt 1 must return False
            hb_success = await update_heartbeat(
                session_a_resumed, ids["job"], attempt_count=1
            )
            assert hb_success is False

            # Mark done with attempt 1 must return False without mutating DB
            done_success = await mark_done(session_a_resumed, job_a, attempt_count=1)
            assert done_success is False

            # Mark error with attempt 1 must return False without mutating DB
            err_success = await mark_error(
                session_a_resumed,
                job_a,
                "ERR_STALE",
                "stale attempt error",
                attempt_count=1,
            )
            assert err_success is False

            await session_a_resumed.rollback()

        # 5. Worker B (attempt 2) successfully updates heartbeat and marks done
        async with sessions() as session_b_final:
            hb_b = await update_heartbeat(session_b_final, ids["job"], attempt_count=2)
            assert hb_b is True

            done_b = await mark_done(session_b_final, job_b, attempt_count=2)
            assert done_b is True
            await session_b_final.commit()

        # 6. Prove final database state is DONE for attempt 2 and document is AWAITING_REVIEW
        async with engine.begin() as conn:
            job_row = (
                await conn.execute(
                    text(
                        "SELECT status::text, attempt_count "
                        "FROM public.analysis_jobs WHERE id = :id"
                    ),
                    {"id": ids["job"]},
                )
            ).one()
            assert job_row[0] == "DONE"
            assert job_row[1] == 2

            doc_row = (
                await conn.execute(
                    text(
                        "SELECT status::text, failure_code FROM public.document_versions WHERE id = :id"
                    ),
                    {"id": ids["document"]},
                )
            ).one()
            assert doc_row[0] == "AWAITING_REVIEW"
            assert doc_row[1] is None

            job_audits = (
                await conn.execute(
                    text(
                        "SELECT action, before, after FROM public.audit_events "
                        "WHERE resource_id = :id ORDER BY created_at ASC"
                    ),
                    {"id": ids["job"]},
                )
            ).all()
            actions = [row[0] for row in job_audits]
            assert "QUEUED" in actions  # Lease requeue event
            assert actions.count("RUNNING") == 2  # Attempt 1 and Attempt 2
            assert actions.count("DONE") == 1  # Only Attempt 2 DONE
    finally:
        if setup_complete:
            async with engine.begin() as conn:
                await conn.execute(
                    text(
                        "DELETE FROM public.audit_events "
                        "WHERE resource_id IN (:job, :document)"
                    ),
                    {"job": ids["job"], "document": ids["document"]},
                )
                await conn.execute(
                    text("DELETE FROM public.analysis_jobs WHERE id = :id"),
                    {"id": ids["job"]},
                )
                await conn.execute(
                    text("DELETE FROM public.document_versions WHERE id = :id"),
                    {"id": ids["document"]},
                )
                await conn.execute(
                    text("DELETE FROM public.submissions WHERE id = :id"),
                    {"id": ids["submission"]},
                )
                await conn.execute(
                    text("DELETE FROM public.assignments WHERE id = :id"),
                    {"id": ids["assignment"]},
                )
                await conn.execute(
                    text("DELETE FROM public.rubric_versions WHERE id = :id"),
                    {"id": ids["rubric"]},
                )
                await conn.execute(
                    text("DELETE FROM public.memberships WHERE id = :id"),
                    {"id": ids["member"]},
                )
                await conn.execute(
                    text("DELETE FROM public.courses WHERE id = :id"),
                    {"id": ids["course"]},
                )
                await conn.execute(
                    text("DELETE FROM public.users WHERE id IN (:teacher, :student)"),
                    {"teacher": ids["teacher"], "student": ids["student"]},
                )
        await engine.dispose()


def test_postgresql_split_brain_stale_attempt_fenced_out_and_attempt_2_settles() -> (
    None
):
    asyncio.run(_run_split_brain_fencing())
