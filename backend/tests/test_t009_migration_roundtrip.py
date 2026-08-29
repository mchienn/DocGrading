from __future__ import annotations

# SQL fixtures are intentionally readable as complete statements.
# ruff: noqa: E501
import asyncio
import contextlib
import os
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.core.config import get_settings
from app.models.enums import AnalysisJobStatus, UserRole
from app.models.identity import User
from app.services import analysis_job as job_service


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
    assert hasattr(migration_0006, "LEGACY_CANCELLED_MARKER_KEY")
    assert hasattr(migration_0006, "LEGACY_CANCELLED_SENTINEL")
    assert (
        migration_0006.LEGACY_CANCELLED_MARKER_KEY
        == "_alembic_20260828_0006_legacy_cancelled"
    )
    assert migration_0006.LEGACY_CANCELLED_SENTINEL == "CANCELLED"
    assert (
        job_service.LEGACY_CANCELLED_MARKER_KEY
        == "_alembic_20260828_0006_legacy_cancelled"
    )


def test_retry_removes_legacy_cancelled_sentinel_unit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    job = type(
        "Job",
        (),
        {
            "id": uuid.uuid4(),
            "document_version_id": uuid.uuid4(),
            "status": AnalysisJobStatus.ERROR,
            "attempt_count": 1,
            "max_attempts": 3,
            "error_code": "MIGRATED_CANCELLED",
            "error_detail": "Migrated",
            "snapshot": {
                "_alembic_20260828_0006_legacy_cancelled": "CANCELLED",
                "custom_data": {"test": 123},
                "num": 42,
            },
            "finished_at": object(),
            "started_at": object(),
            "queued_at": None,
        },
    )()
    document = type("Doc", (), {"status": None})()

    class Result:
        def scalar_one(self):
            return job

    class DB:
        async def execute(self, _statement):
            return Result()

        async def get(self, _model, _key):
            return document

        flush = AsyncMock()

    async def allow(*_args, **_kwargs):
        pass

    async def audit(*_args, **_kwargs):
        pass

    monkeypatch.setattr(job_service, "authorize_job", allow)
    monkeypatch.setattr(job_service, "record_audit", audit)

    user = User(
        id=uuid.uuid4(),
        email="test@local",
        display_name="Teacher",
        password_hash="h",
        roles=[UserRole.TEACHER],
    )
    result = asyncio.run(job_service.retry_job(DB(), job, user))

    assert result is job
    assert result.status is AnalysisJobStatus.QUEUED
    assert "_alembic_20260828_0006_legacy_cancelled" not in result.snapshot
    assert result.snapshot["custom_data"] == {"test": 123}
    assert result.snapshot["num"] == 42


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
        for i, doc_name in enumerate(
            ["doc1", "doc2", "doc3", "doc4", "doc_retried", "doc_collision"],
            start=1,
        ):
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

        # Insert legacy jobs in 0005: CANCELLED (untouched and to-be-retried), FAILED, SUCCEEDED
        await conn.execute(
            text("""
                INSERT INTO public.analysis_jobs (id, document_version_id, rubric_version_id, status, snapshot)
                VALUES (:j_canc, :doc1, :rubric, 'CANCELLED'::public.analysis_job_status, '{\"custom_key\": \"hello\", \"nested\": {\"a\": 1, \"b\": [2, 3]}, \"num\": 42}'::jsonb),
                       (:j_canc_retried, :doc_retried, :rubric, 'CANCELLED'::public.analysis_job_status, '{\"retried_meta\": \"keep_me\", \"version\": 1}'::jsonb),
                       (:j_fail, :doc2, :rubric, 'FAILED'::public.analysis_job_status, '{\"failed_key\": 123, \"reasons\": [\"bad pdf\"]}'::jsonb),
                       (:j_succ, :doc3, :rubric, 'SUCCEEDED'::public.analysis_job_status, '{\"succ_key\": 456, \"metrics\": {\"pages\": 5}}'::jsonb)
            """),
            {
                "j_canc": ids["job_cancelled"],
                "j_canc_retried": ids["job_cancelled_retried"],
                "j_fail": ids["job_failed"],
                "j_succ": ids["job_succeeded"],
                "doc1": ids["doc1"],
                "doc_retried": ids["doc_retried"],
                "doc2": ids["doc2"],
                "doc3": ids["doc3"],
                "rubric": ids["rubric"],
            },
        )


async def _verify_0006_and_process_jobs(
    engine: AsyncEngine, ids: dict[str, uuid.UUID]
) -> None:
    marker_key = "_alembic_20260828_0006_legacy_cancelled"
    marker_val = "CANCELLED"
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    async with session_factory() as db:
        res = await db.execute(
            text(
                "SELECT id, status::text, snapshot FROM public.analysis_jobs WHERE id IN (:j1, :j2, :j3, :j_ret)"
            ),
            {
                "j1": ids["job_cancelled"],
                "j2": ids["job_failed"],
                "j3": ids["job_succeeded"],
                "j_ret": ids["job_cancelled_retried"],
            },
        )
        rows: dict[uuid.UUID, tuple[str, dict[str, Any]]] = {
            row[0]: (row[1], row[2]) for row in res.fetchall()
        }

        # Untouched CANCELLED must map to ERROR, have exact sentinel marker, and preserve all snapshot keys
        assert rows[ids["job_cancelled"]][0] == "ERROR"
        assert rows[ids["job_cancelled"]][1].get(marker_key) == marker_val
        assert rows[ids["job_cancelled"]][1].get("custom_key") == "hello"
        assert rows[ids["job_cancelled"]][1].get("nested") == {"a": 1, "b": [2, 3]}
        assert rows[ids["job_cancelled"]][1].get("num") == 42

        # Retried CANCELLED initially maps to ERROR with marker in 0006
        assert rows[ids["job_cancelled_retried"]][0] == "ERROR"
        assert rows[ids["job_cancelled_retried"]][1].get(marker_key) == marker_val
        assert rows[ids["job_cancelled_retried"]][1].get("retried_meta") == "keep_me"

        # FAILED must map to ERROR, not have marker, and preserve all snapshot keys
        assert rows[ids["job_failed"]][0] == "ERROR"
        assert marker_key not in rows[ids["job_failed"]][1]
        assert rows[ids["job_failed"]][1].get("failed_key") == 123
        assert rows[ids["job_failed"]][1].get("reasons") == ["bad pdf"]

        # SUCCEEDED must map to DONE, not have marker, and preserve all snapshot keys
        assert rows[ids["job_succeeded"]][0] == "DONE"
        assert rows[ids["job_succeeded"]][1].get("succ_key") == 456
        assert rows[ids["job_succeeded"]][1].get("metrics") == {"pages": 5}

        # Verify heartbeat_at column exists in 0006
        heartbeat_col_check = await db.execute(text("""
                SELECT column_name, data_type, is_nullable
                FROM information_schema.columns
                WHERE table_name = 'analysis_jobs' AND column_name = 'heartbeat_at'
            """))
        hb_row = heartbeat_col_check.fetchone()
        assert hb_row is not None
        assert "timestamp" in hb_row[1]

        # Insert an ordinary ERROR job in 0006 with heartbeat_at
        await db.execute(
            text("""
                INSERT INTO public.analysis_jobs (id, document_version_id, rubric_version_id, status, snapshot, heartbeat_at)
                VALUES (:id, :doc4, :rubric, 'ERROR'::public.analysis_job_status, '{\"ordinary\": true, \"details\": \"some error\"}'::jsonb, now())
            """),
            {
                "id": ids["job_ordinary_err"],
                "doc4": ids["doc4"],
                "rubric": ids["rubric"],
            },
        )
        await db.commit()

        # Now perform retry_job on job_cancelled_retried
        job_retried = await job_service.get_job(db, ids["job_cancelled_retried"])
        assert job_retried is not None
        teacher = User(
            id=ids["teacher"],
            email=f"{ids['teacher']}@x",
            display_name="T",
            password_hash="h",
            roles=[UserRole.TEACHER],
        )
        retried_res = await job_service.retry_job(db, job_retried, teacher)
        await db.commit()

        assert retried_res.status is AnalysisJobStatus.QUEUED
        assert marker_key not in retried_res.snapshot
        assert retried_res.snapshot.get("retried_meta") == "keep_me"

        # Now simulate failure of that retried job (e.g. mark_error in worker)
        await job_service.mark_error(
            db, retried_res, "SIMULATED_FAIL", "failed during worker execution"
        )
        await db.commit()

        # Verify job_cancelled_retried is now in ERROR but does NOT have the sentinel marker
        res_after = await db.execute(
            text(
                "SELECT status::text, snapshot FROM public.analysis_jobs WHERE id = :id"
            ),
            {"id": ids["job_cancelled_retried"]},
        )
        row_after = res_after.fetchone()
        assert row_after is not None
        assert row_after[0] == "ERROR"
        assert marker_key not in row_after[1]
        assert row_after[1].get("retried_meta") == "keep_me"


async def _verify_0005_downgrade(
    engine: AsyncEngine, ids: dict[str, uuid.UUID]
) -> None:
    marker_key = "_alembic_20260828_0006_legacy_cancelled"
    async with engine.begin() as conn:
        res = await conn.execute(
            text(
                "SELECT id, status::text, snapshot FROM public.analysis_jobs WHERE id IN (:j1, :j2, :j3, :j4, :j_ret)"
            ),
            {
                "j1": ids["job_cancelled"],
                "j2": ids["job_failed"],
                "j3": ids["job_succeeded"],
                "j4": ids["job_ordinary_err"],
                "j_ret": ids["job_cancelled_retried"],
            },
        )
        rows: dict[uuid.UUID, tuple[str, dict[str, Any]]] = {
            row[0]: (row[1], row[2]) for row in res.fetchall()
        }

        # Untouched legacy cancelled row must be restored to CANCELLED and only marker stripped
        assert rows[ids["job_cancelled"]][0] == "CANCELLED"
        assert marker_key not in rows[ids["job_cancelled"]][1]
        assert rows[ids["job_cancelled"]][1].get("custom_key") == "hello"
        assert rows[ids["job_cancelled"]][1].get("nested") == {"a": 1, "b": [2, 3]}
        assert rows[ids["job_cancelled"]][1].get("num") == 42

        # Retried migrated job (which failed after retry) must downgrade to FAILED (not CANCELLED!)
        assert rows[ids["job_cancelled_retried"]][0] == "FAILED"
        assert marker_key not in rows[ids["job_cancelled_retried"]][1]
        assert rows[ids["job_cancelled_retried"]][1].get("retried_meta") == "keep_me"

        # Legacy failed row must be FAILED and preserve all snapshot keys
        assert rows[ids["job_failed"]][0] == "FAILED"
        assert rows[ids["job_failed"]][1].get("failed_key") == 123
        assert rows[ids["job_failed"]][1].get("reasons") == ["bad pdf"]

        # Legacy succeeded row must be SUCCEEDED and preserve all snapshot keys
        assert rows[ids["job_succeeded"]][0] == "SUCCEEDED"
        assert rows[ids["job_succeeded"]][1].get("succ_key") == 456
        assert rows[ids["job_succeeded"]][1].get("metrics") == {"pages": 5}

        # Ordinary ERROR created in 0006 must downgrade to FAILED
        assert rows[ids["job_ordinary_err"]][0] == "FAILED"
        assert rows[ids["job_ordinary_err"]][1].get("ordinary") is True
        assert rows[ids["job_ordinary_err"]][1].get("details") == "some error"

        # Verify heartbeat_at column was dropped
        heartbeat_col_check = await conn.execute(text("""
                SELECT column_name
                FROM information_schema.columns
                WHERE table_name = 'analysis_jobs' AND column_name = 'heartbeat_at'
            """))
        assert heartbeat_col_check.fetchone() is None


async def _cleanup(engine: AsyncEngine, ids: dict[str, uuid.UUID]) -> None:
    async with engine.begin() as conn:
        job_ids = [ids[k] for k in ids if k.startswith("job")]
        doc_ids = [ids[k] for k in ids if k.startswith("doc")]
        if job_ids:
            await conn.execute(
                text("DELETE FROM public.analysis_jobs WHERE id = ANY(:jids)"),
                {"jids": job_ids},
            )
        if doc_ids:
            await conn.execute(
                text("DELETE FROM public.document_versions WHERE id = ANY(:dids)"),
                {"dids": doc_ids},
            )
        if "submission" in ids:
            await conn.execute(
                text("DELETE FROM public.submissions WHERE id = :id"),
                {"id": ids["submission"]},
            )
        if "assignment" in ids:
            await conn.execute(
                text("DELETE FROM public.assignments WHERE id = :id"),
                {"id": ids["assignment"]},
            )
        if "rubric" in ids:
            await conn.execute(
                text("DELETE FROM public.rubric_versions WHERE id = :id"),
                {"id": ids["rubric"]},
            )
        if "member" in ids:
            await conn.execute(
                text("DELETE FROM public.memberships WHERE id = :id"),
                {"id": ids["member"]},
            )
        if "course" in ids:
            await conn.execute(
                text("DELETE FROM public.courses WHERE id = :id"),
                {"id": ids["course"]},
            )
        if "teacher" in ids and "student" in ids:
            with contextlib.suppress(Exception):
                await conn.execute(
                    text("DELETE FROM public.users WHERE id IN (:teacher, :student)"),
                    {"teacher": ids["teacher"], "student": ids["student"]},
                )


@pytest.mark.skipif(
    os.environ.get("RUN_DATABASE_TESTS") != "1",
    reason="Database integration tests require RUN_DATABASE_TESTS=1",
)
def test_migration_0006_marker_collision_aborts_postgres() -> None:
    """Prove that existing marker in snapshot causes upgrade 0006 to abort and protect data."""
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
            "doc_retried",
            "doc_collision",
            "job_cancelled",
            "job_cancelled_retried",
            "job_failed",
            "job_succeeded",
            "job_ordinary_err",
            "job_collision",
        )
    }

    try:
        # Step 1: Ensure at 0005
        try:
            alembic.command.downgrade(alembic_cfg, "20260828_0005")
        except Exception:
            alembic.command.upgrade(alembic_cfg, "20260828_0005")

        # Step 2: Seed base 0005 data
        asyncio.run(_seed_0005(engine, ids))

        # Insert a job with collision marker key in snapshot in 0005
        async def _insert_colliding_job() -> None:
            async with engine.begin() as conn:
                await conn.execute(
                    text("""
                        INSERT INTO public.analysis_jobs (id, document_version_id, rubric_version_id, status, snapshot)
                        VALUES (:j_coll, :doc_coll, :rubric, 'QUEUED'::public.analysis_job_status,
                                '{\"_alembic_20260828_0006_legacy_cancelled\": \"user_data\", \"preserve_me\": 999}'::jsonb)
                    """),
                    {
                        "j_coll": ids["job_collision"],
                        "doc_coll": ids["doc_collision"],
                        "rubric": ids["rubric"],
                    },
                )

        asyncio.run(_insert_colliding_job())

        # Step 3: Upgrade to 0006 MUST fail and abort
        with pytest.raises(Exception, match="_alembic_20260828_0006_legacy_cancelled"):
            alembic.command.upgrade(alembic_cfg, "20260828_0006")

        # Step 4: Verify that data was uncorrupted and job remains with its original data
        async def _verify_colliding_job_preserved() -> None:
            async with engine.begin() as conn:
                res = await conn.execute(
                    text(
                        "SELECT status::text, snapshot FROM public.analysis_jobs WHERE id = :id"
                    ),
                    {"id": ids["job_collision"]},
                )
                row = res.fetchone()
                assert row is not None
                assert row[0] == "QUEUED"
                assert row[1] == {
                    "_alembic_20260828_0006_legacy_cancelled": "user_data",
                    "preserve_me": 999,
                }

        asyncio.run(_verify_colliding_job_preserved())

    finally:
        try:
            asyncio.run(_cleanup(engine, ids))
        finally:
            alembic.command.upgrade(alembic_cfg, "head")
            asyncio.run(engine.dispose())


@pytest.mark.skipif(
    os.environ.get("RUN_DATABASE_TESTS") != "1",
    reason="Database integration tests require RUN_DATABASE_TESTS=1",
)
def test_migration_0006_cancelled_reversible_roundtrip_postgres() -> None:
    """Real PostgreSQL roundtrip verifying CANCELLED -> ERROR -> CANCELLED, retry sentinel removal, and heartbeat_at."""
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
            "doc_retried",
            "doc_collision",
            "job_cancelled",
            "job_cancelled_retried",
            "job_failed",
            "job_succeeded",
            "job_ordinary_err",
            "job_collision",
        )
    }

    try:
        # Step 1: Ensure at 0005
        try:
            alembic.command.downgrade(alembic_cfg, "20260828_0005")
        except Exception:
            alembic.command.upgrade(alembic_cfg, "20260828_0005")

        # Step 2: Seed data in 0005 schema
        asyncio.run(_seed_0005(engine, ids))

        # Step 3: Upgrade to 0006
        alembic.command.upgrade(alembic_cfg, "20260828_0006")

        # Step 4: Verify 0006 status/snapshot, retry one migrated job, and add ordinary ERROR job
        asyncio.run(_verify_0006_and_process_jobs(engine, ids))

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
