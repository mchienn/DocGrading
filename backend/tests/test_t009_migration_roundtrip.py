from __future__ import annotations

# SQL fixtures are intentionally readable as complete statements.
# ruff: noqa: E501
import asyncio
import os
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine
from sqlalchemy.pool import NullPool

from app.core.config import get_settings


def test_migration_0006_contract_definitions() -> None:
    import importlib.util
    from pathlib import Path

    migration_path = (
        Path(__file__).resolve().parents[1]
        / "alembic"
        / "versions"
        / "20260828_0006_pdf_upload_job_lifecycle.py"
    )
    spec = importlib.util.spec_from_file_location("migration_0006", migration_path)
    assert spec is not None and spec.loader is not None
    migration_0006 = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration_0006)

    assert migration_0006.revision == "20260828_0006"
    assert migration_0006.down_revision == "20260828_0005"
    assert hasattr(migration_0006, "upgrade")
    assert hasattr(migration_0006, "downgrade")


async def _seed_0005(engine: AsyncEngine, ids: dict[str, uuid.UUID]) -> None:
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
        for i, doc_name in enumerate(["doc1", "doc2", "doc3", "doc4"], start=1):
            await conn.execute(
                text("""
                    INSERT INTO public.document_versions (id, submission_id, version_number, storage_key, original_filename, content_type, size_bytes, sha256, status)
                    VALUES (:id, :submission, :ver, :key, 'a.pdf', 'application/pdf', 5, :sha, 'QUEUED'::public.document_status)
                """),
                {
                    "id": ids[doc_name],
                    "submission": ids["submission"],
                    "ver": i,
                    "key": f"x/{ids[doc_name]}",
                    "sha": uuid.uuid4().hex + uuid.uuid4().hex,
                },
            )

        # Insert legacy jobs in 0005: CANCELLED, FAILED, SUCCEEDED
        await conn.execute(
            text("""
                INSERT INTO public.analysis_jobs (id, document_version_id, rubric_version_id, status, snapshot)
                VALUES (:j_canc, :doc1, :rubric, 'CANCELLED'::public.analysis_job_status, '{\"custom_key\": \"hello\"}'::jsonb),
                       (:j_fail, :doc2, :rubric, 'FAILED'::public.analysis_job_status, '{\"failed_key\": 123}'::jsonb),
                       (:j_succ, :doc3, :rubric, 'SUCCEEDED'::public.analysis_job_status, '{\"succ_key\": 456}'::jsonb)
            """),
            {
                "j_canc": ids["job_cancelled"],
                "j_fail": ids["job_failed"],
                "j_succ": ids["job_succeeded"],
                "doc1": ids["doc1"],
                "doc2": ids["doc2"],
                "doc3": ids["doc3"],
                "rubric": ids["rubric"],
            },
        )


async def _verify_0006_and_insert_error_job(
    engine: AsyncEngine, ids: dict[str, uuid.UUID]
) -> None:
    async with engine.begin() as conn:
        res = await conn.execute(
            text(
                "SELECT id, status::text, snapshot FROM public.analysis_jobs WHERE id IN (:j1, :j2, :j3)"
            ),
            {
                "j1": ids["job_cancelled"],
                "j2": ids["job_failed"],
                "j3": ids["job_succeeded"],
            },
        )
        rows: dict[uuid.UUID, tuple[str, dict[str, Any]]] = {
            row[0]: (row[1], row[2]) for row in res.fetchall()
        }

        assert rows[ids["job_cancelled"]][0] == "ERROR"
        assert rows[ids["job_cancelled"]][1].get("_legacy_cancelled") is True
        assert rows[ids["job_cancelled"]][1].get("custom_key") == "hello"

        assert rows[ids["job_failed"]][0] == "ERROR"
        assert "_legacy_cancelled" not in rows[ids["job_failed"]][1]
        assert rows[ids["job_failed"]][1].get("failed_key") == 123

        assert rows[ids["job_succeeded"]][0] == "DONE"
        assert rows[ids["job_succeeded"]][1].get("succ_key") == 456

        # Verify heartbeat_at column exists in 0006
        heartbeat_col_check = await conn.execute(text("""
                SELECT column_name, data_type, is_nullable
                FROM information_schema.columns
                WHERE table_name = 'analysis_jobs' AND column_name = 'heartbeat_at'
            """))
        hb_row = heartbeat_col_check.fetchone()
        assert hb_row is not None
        assert "timestamp" in hb_row[1]

        # Insert an ordinary ERROR job in 0006 with heartbeat_at
        await conn.execute(
            text("""
                INSERT INTO public.analysis_jobs (id, document_version_id, rubric_version_id, status, snapshot, heartbeat_at)
                VALUES (:id, :doc4, :rubric, 'ERROR'::public.analysis_job_status, '{\"ordinary\": true}'::jsonb, now())
            """),
            {
                "id": ids["job_ordinary_err"],
                "doc4": ids["doc4"],
                "rubric": ids["rubric"],
            },
        )


async def _verify_0005_downgrade(
    engine: AsyncEngine, ids: dict[str, uuid.UUID]
) -> None:
    async with engine.begin() as conn:
        res = await conn.execute(
            text(
                "SELECT id, status::text, snapshot FROM public.analysis_jobs WHERE id IN (:j1, :j2, :j3, :j4)"
            ),
            {
                "j1": ids["job_cancelled"],
                "j2": ids["job_failed"],
                "j3": ids["job_succeeded"],
                "j4": ids["job_ordinary_err"],
            },
        )
        rows: dict[uuid.UUID, tuple[str, dict[str, Any]]] = {
            row[0]: (row[1], row[2]) for row in res.fetchall()
        }

        # Legacy cancelled row must be restored to CANCELLED and marker stripped
        assert rows[ids["job_cancelled"]][0] == "CANCELLED"
        assert "_legacy_cancelled" not in rows[ids["job_cancelled"]][1]
        assert rows[ids["job_cancelled"]][1].get("custom_key") == "hello"

        # Legacy failed row must be FAILED
        assert rows[ids["job_failed"]][0] == "FAILED"
        assert rows[ids["job_failed"]][1].get("failed_key") == 123

        # Legacy succeeded row must be SUCCEEDED
        assert rows[ids["job_succeeded"]][0] == "SUCCEEDED"
        assert rows[ids["job_succeeded"]][1].get("succ_key") == 456

        # Ordinary ERROR created in 0006 must downgrade to FAILED
        assert rows[ids["job_ordinary_err"]][0] == "FAILED"
        assert rows[ids["job_ordinary_err"]][1].get("ordinary") is True

        # Verify heartbeat_at column was dropped
        heartbeat_col_check = await conn.execute(text("""
                SELECT column_name
                FROM information_schema.columns
                WHERE table_name = 'analysis_jobs' AND column_name = 'heartbeat_at'
            """))
        assert heartbeat_col_check.fetchone() is None


async def _cleanup(engine: AsyncEngine, ids: dict[str, uuid.UUID]) -> None:
    async with engine.begin() as conn:
        await conn.execute(
            text("DELETE FROM public.analysis_jobs WHERE id IN (:j1, :j2, :j3, :j4)"),
            {
                "j1": ids["job_cancelled"],
                "j2": ids["job_failed"],
                "j3": ids["job_succeeded"],
                "j4": ids["job_ordinary_err"],
            },
        )
        await conn.execute(
            text(
                "DELETE FROM public.document_versions WHERE id IN (:d1, :d2, :d3, :d4)"
            ),
            {
                "d1": ids["doc1"],
                "d2": ids["doc2"],
                "d3": ids["doc3"],
                "d4": ids["doc4"],
            },
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


@pytest.mark.skipif(
    os.environ.get("RUN_DATABASE_TESTS") != "1",
    reason="Database integration tests require RUN_DATABASE_TESTS=1",
)
def test_migration_0006_cancelled_reversible_roundtrip_postgres() -> None:
    """Real PostgreSQL roundtrip verifying CANCELLED -> ERROR -> CANCELLED and heartbeat_at."""
    import alembic.command
    import alembic.config

    backend_dir = os.path.dirname(os.path.dirname(__file__))
    alembic_ini_path = os.path.join(backend_dir, "alembic.ini")
    alembic_cfg = alembic.config.Config(alembic_ini_path)
    alembic_cfg.set_main_option("script_location", os.path.join(backend_dir, "alembic"))

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
            "doc1",
            "doc2",
            "doc3",
            "doc4",
            "job_cancelled",
            "job_failed",
            "job_succeeded",
            "job_ordinary_err",
        )
    }

    try:
        # Step 1: Ensure at 0005
        alembic.command.upgrade(alembic_cfg, "20260828_0005")
    except Exception:
        alembic.command.downgrade(alembic_cfg, "20260828_0005")

        # Step 2: Seed data in 0005 schema
        asyncio.run(_seed_0005(engine, ids))

        # Step 3: Upgrade to 0006
        alembic.command.upgrade(alembic_cfg, "20260828_0006")

        # Step 4: Verify 0006 status/snapshot and add ordinary ERROR job
        asyncio.run(_verify_0006_and_insert_error_job(engine, ids))

        # Step 5: Downgrade back to 0005
        alembic.command.downgrade(alembic_cfg, "20260828_0005")

        # Step 6: Verify 0005 downgrade behavior
        asyncio.run(_verify_0005_downgrade(engine, ids))

    finally:
        try:
            asyncio.run(_cleanup(engine, ids))
        finally:
            alembic.command.upgrade(alembic_cfg, "head")
            asyncio.run(engine.dispose())
