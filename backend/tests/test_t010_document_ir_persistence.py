from __future__ import annotations

import asyncio
import os
import threading
import uuid
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.core.config import get_settings
from app.models.analysis import DocumentIR
from app.models.assignment import Assignment
from app.models.course import Course, Membership
from app.models.enums import (
    AssignmentStatus,
    CourseStatus,
    DocumentStatus,
    MembershipRole,
    MembershipStatus,
    RubricStatus,
    UserRole,
    UserStatus,
)
from app.models.identity import User
from app.models.rubric import RubricVersion
from app.models.submission import DocumentVersion, Submission
from app.services import document_ir
from app.services.document_ir import (
    PARSER_VERSION,
    SCHEMA_VERSION,
    DocumentIRExtractionError,
    ParsedDocumentIR,
)
from app.services.pdf_validation import PDFValidationError, PDFValidationResult


@pytest.fixture
def worker_tasks(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("POSTGRES_DB", "docgrading_test")
    monkeypatch.setenv("POSTGRES_USER", "docgrading_test")
    monkeypatch.setenv("POSTGRES_PASSWORD", "test-only")
    get_settings.cache_clear()
    from app.workers import tasks

    return tasks


def _result(value):
    result = MagicMock()
    result.scalar_one.return_value = value
    result.scalar_one_or_none.return_value = value
    return result


def _parsed(sha256: str, content: dict) -> ParsedDocumentIR:
    return ParsedDocumentIR(
        validation=PDFValidationResult(
            sha256=sha256, size_bytes=3, page_count=1, has_text=True
        ),
        content=content,
    )


def _target(
    *,
    declared_sha256: str | None = None,
    sha256: str = "a" * 64,
) -> SimpleNamespace:
    return SimpleNamespace(
        id=uuid.uuid4(),
        submission_id=uuid.uuid4(),
        sha256=sha256,
        declared_sha256=declared_sha256,
    )


def _patch_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        document_ir,
        "get_settings",
        lambda: SimpleNamespace(
            pdf_max_size_bytes=50, pdf_max_page_count=100, pdf_ir_max_nodes=1000
        ),
    )


async def _test_first_statement_locks_document_version_and_first_build_adds_one_ir(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target = _target()
    parsed = _parsed("a" * 64, {"new": True})
    db = AsyncMock()
    db.add = MagicMock()
    db.execute.side_effect = [
        _result(SimpleNamespace(id=target.submission_id)),
        _result(target),
        _result(None),
        _result(None),
    ]
    db.flush = AsyncMock()
    parser = MagicMock(return_value=parsed)
    monkeypatch.setattr(document_ir, "parse_document_ir", parser)
    monkeypatch.setattr(
        document_ir,
        "get_settings",
        lambda: SimpleNamespace(
            pdf_max_size_bytes=11, pdf_max_page_count=12, pdf_ir_max_nodes=13
        ),
    )

    ir = await document_ir.get_or_build_document_ir(db, target.id, b"pdf")

    assert isinstance(ir, DocumentIR)
    assert ir.document_version_id == target.id
    assert ir.schema_version == SCHEMA_VERSION
    assert ir.parser_version == PARSER_VERSION
    assert ir.content == parsed.content
    db.add.assert_called_once_with(ir)
    db.flush.assert_awaited_once()
    parser.assert_called_once_with(
        b"pdf", max_size_bytes=11, max_page_count=12, max_nodes=13
    )
    submission_statement = db.execute.call_args_list[0].args[0]
    statement = db.execute.call_args_list[1].args[0]
    assert "submissions" in str(
        submission_statement.compile(dialect=postgresql.dialect())
    )
    assert "FOR UPDATE" in str(
        submission_statement.compile(dialect=postgresql.dialect())
    )
    assert "FOR UPDATE" in str(statement.compile(dialect=postgresql.dialect()))
    assert db.execute.call_count == 4


def test_first_statement_locks_document_version_and_first_build_adds_one_ir(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    asyncio.run(
        _test_first_statement_locks_document_version_and_first_build_adds_one_ir(
            monkeypatch
        )
    )


async def _test_existing_ir_replay_does_not_parse(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target = _target()
    existing = SimpleNamespace(id=uuid.uuid4(), content={"old": True})
    db = AsyncMock()
    db.add = MagicMock()
    db.execute.side_effect = [
        _result(SimpleNamespace(id=target.submission_id)),
        _result(target),
        _result(existing),
    ]
    parser = MagicMock(side_effect=AssertionError("replay parsed PDF"))
    monkeypatch.setattr(document_ir, "parse_document_ir", parser)

    assert await document_ir.get_or_build_document_ir(db, target.id, b"pdf") is existing
    parser.assert_not_called()
    db.flush.assert_not_awaited()
    assert db.execute.await_count == 3


def test_existing_ir_replay_does_not_parse(monkeypatch: pytest.MonkeyPatch) -> None:
    asyncio.run(_test_existing_ir_replay_does_not_parse(monkeypatch))


async def _test_rebuild_replaces_payload_and_retains_ir_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target = _target(sha256="b" * 64)
    ir_id = uuid.uuid4()
    existing = SimpleNamespace(
        id=ir_id,
        document_version_id=target.id,
        schema_version=99,
        parser_version="old-parser",
        content={"stale": True, "shared": "old"},
    )
    parsed = _parsed("b" * 64, {"shared": "new"})
    db = AsyncMock()
    db.add = MagicMock()
    db.execute.side_effect = [
        _result(SimpleNamespace(id=target.submission_id)),
        _result(target),
        _result(existing),
        _result(None),
    ]
    _patch_settings(monkeypatch)
    db.flush = AsyncMock()
    parser = MagicMock(return_value=parsed)
    monkeypatch.setattr(document_ir, "parse_document_ir", parser)

    result = await document_ir.get_or_build_document_ir(
        db, target.id, b"pdf", rebuild=True
    )

    assert result is existing
    assert existing.id == ir_id
    assert existing.schema_version == SCHEMA_VERSION
    assert existing.parser_version == PARSER_VERSION
    assert existing.content == {"shared": "new"}
    db.add.assert_not_called()
    db.flush.assert_awaited_once()


def test_rebuild_replaces_payload_and_retains_ir_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    asyncio.run(_test_rebuild_replaces_payload_and_retains_ir_id(monkeypatch))


async def _test_declared_sha_mismatch_raises_before_ir_add(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target = _target(declared_sha256="c" * 64)
    db = AsyncMock()
    db.add = MagicMock()
    db.execute.side_effect = [
        _result(SimpleNamespace(id=target.submission_id)),
        _result(target),
        _result(None),
    ]
    _patch_settings(monkeypatch)
    monkeypatch.setattr(
        document_ir, "parse_document_ir", MagicMock(return_value=_parsed("d" * 64, {}))
    )

    with pytest.raises(PDFValidationError) as exc_info:
        await document_ir.get_or_build_document_ir(db, target.id, b"pdf")

    assert exc_info.value.code == "PDF_SHA256_MISMATCH"
    assert str(exc_info.value) == "PDF checksum does not match"
    db.add.assert_not_called()
    db.flush.assert_not_awaited()
    assert db.execute.await_count == 3


def test_declared_sha_mismatch_raises_before_ir_add(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    asyncio.run(_test_declared_sha_mismatch_raises_before_ir_add(monkeypatch))


async def _test_duplicate_sibling_sha_raises_before_ir_add(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target = _target(sha256="e" * 64)
    db = AsyncMock()
    db.add = MagicMock()
    db.execute.side_effect = [
        _result(SimpleNamespace(id=target.submission_id)),
        _result(target),
        _result(None),
        _result(uuid.uuid4()),
    ]
    _patch_settings(monkeypatch)
    monkeypatch.setattr(
        document_ir, "parse_document_ir", MagicMock(return_value=_parsed("e" * 64, {}))
    )

    with pytest.raises(PDFValidationError) as exc_info:
        await document_ir.get_or_build_document_ir(db, target.id, b"pdf")

    assert exc_info.value.code == "PDF_DUPLICATE"
    assert str(exc_info.value) == "Duplicate document version"
    db.add.assert_not_called()
    db.flush.assert_not_awaited()


def test_duplicate_sibling_sha_raises_before_ir_add(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    asyncio.run(_test_duplicate_sibling_sha_raises_before_ir_add(monkeypatch))


async def _test_stale_stored_sha_hint_is_not_authoritative(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target = _target(sha256="a" * 64)
    db = AsyncMock()
    db.add = MagicMock()
    db.execute.side_effect = [
        _result(SimpleNamespace(id=target.submission_id)),
        _result(target),
        _result(None),
        _result(None),
    ]
    _patch_settings(monkeypatch)
    db.flush = AsyncMock()
    monkeypatch.setattr(
        document_ir,
        "parse_document_ir",
        MagicMock(return_value=_parsed("b" * 64, {"new": True})),
    )

    result = await document_ir.get_or_build_document_ir(db, target.id, b"pdf")

    assert result.content == {"new": True}
    db.add.assert_called_once_with(result)
    db.flush.assert_awaited_once()


def test_stale_stored_sha_hint_is_not_authoritative(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    asyncio.run(_test_stale_stored_sha_hint_is_not_authoritative(monkeypatch))


async def _test_submission_lock_precedes_document_version_lock(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target = _target()
    submission = SimpleNamespace(id=target.submission_id)
    db = AsyncMock()
    db.add = MagicMock()
    db.execute.side_effect = [
        _result(submission),
        _result(target),
        _result(None),
        _result(None),
    ]
    _patch_settings(monkeypatch)
    monkeypatch.setattr(
        document_ir,
        "parse_document_ir",
        MagicMock(return_value=_parsed("a" * 64, {"new": True})),
    )

    await document_ir.get_or_build_document_ir(db, target.id, b"pdf")
    assert db.execute.await_count == 4
    submission_sql = str(
        db.execute.call_args_list[0].args[0].compile(dialect=postgresql.dialect())
    )
    document_sql = str(
        db.execute.call_args_list[1].args[0].compile(dialect=postgresql.dialect())
    )
    assert "submissions" in submission_sql
    assert "FOR UPDATE" in submission_sql
    assert "document_versions" in document_sql
    assert "FOR UPDATE" in document_sql


def test_submission_lock_precedes_document_version_lock(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    asyncio.run(_test_submission_lock_precedes_document_version_lock(monkeypatch))


async def _test_duplicate_check_excludes_target_and_uses_submission_sha(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target = _target(sha256="f" * 64)
    db = AsyncMock()
    db.add = MagicMock()
    db.execute.side_effect = [
        _result(SimpleNamespace(id=target.submission_id)),
        _result(target),
        _result(None),
        _result(None),
    ]
    _patch_settings(monkeypatch)
    db.flush = AsyncMock()
    monkeypatch.setattr(
        document_ir, "parse_document_ir", MagicMock(return_value=_parsed("f" * 64, {}))
    )

    await document_ir.get_or_build_document_ir(db, target.id, b"pdf")

    duplicate_stmt = db.execute.call_args_list[3].args[0]
    sql = str(duplicate_stmt.compile(dialect=postgresql.dialect()))
    assert "document_versions.submission_id" in sql
    assert "document_versions.sha256" in sql
    assert "document_versions.id" in sql


def test_duplicate_check_excludes_target_and_uses_submission_sha(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    asyncio.run(
        _test_duplicate_check_excludes_target_and_uses_submission_sha(monkeypatch)
    )


async def _run_postgresql_concurrency_test() -> None:
    settings = get_settings()
    engine = create_async_engine(settings.database_url, poolclass=NullPool)
    ids = {
        name: uuid.uuid4()
        for name in (
            "user",
            "course",
            "membership",
            "rubric",
            "assignment",
            "submission",
            "version",
        )
    }
    parser_entered = threading.Event()
    release_parser = threading.Event()
    parser_calls = 0
    parser_lock = threading.Lock()

    def gated_parser(data: bytes, **_: int) -> ParsedDocumentIR:
        nonlocal parser_calls
        with parser_lock:
            parser_calls += 1
        parser_entered.set()
        assert release_parser.wait(timeout=10)
        return _parsed("1" * 64, {"pages": []})

    original_parser = document_ir.parse_document_ir
    document_ir.parse_document_ir = gated_parser
    graph_committed = False
    try:
        async with engine.begin() as conn:
            await conn.run_sync(
                lambda sync_conn: sync_conn.execute(
                    User.__table__.insert().values(
                        id=ids["user"],
                        email=f"{ids['user']}@example.test",
                        display_name="Student",
                        password_hash="hash",
                        roles=[UserRole.TEACHER, UserRole.STUDENT],
                        status=UserStatus.ACTIVE,
                    )
                )
            )
            await conn.run_sync(
                lambda sync_conn: sync_conn.execute(
                    Course.__table__.insert().values(
                        id=ids["course"],
                        code=f"C-{ids['course']}",
                        name="Course",
                        term="2026",
                        owner_teacher_id=ids["user"],
                        status=CourseStatus.ACTIVE,
                    )
                )
            )
            await conn.run_sync(
                lambda sync_conn: sync_conn.execute(
                    Membership.__table__.insert().values(
                        id=ids["membership"],
                        course_id=ids["course"],
                        user_id=ids["user"],
                        role=MembershipRole.STUDENT,
                        status=MembershipStatus.ACTIVE,
                    )
                )
            )
            await conn.run_sync(
                lambda sync_conn: sync_conn.execute(
                    RubricVersion.__table__.insert().values(
                        id=ids["rubric"],
                        rubric_id=uuid.uuid4(),
                        version_number=1,
                        name="Rubric",
                        status=RubricStatus.DRAFT,
                        calculation_method="WEIGHTED_SUM",
                        total_weight=0,
                        owner_user_id=ids["user"],
                        created_by_user_id=ids["user"],
                    )
                )
            )
            await conn.run_sync(
                lambda sync_conn: sync_conn.execute(
                    Assignment.__table__.insert().values(
                        id=ids["assignment"],
                        course_id=ids["course"],
                        created_by_teacher_id=ids["user"],
                        rubric_version_id=ids["rubric"],
                        title="Assignment",
                        due_at=datetime.now(UTC),
                        status=AssignmentStatus.DRAFT,
                        max_submissions=3,
                    )
                )
            )
            await conn.run_sync(
                lambda sync_conn: sync_conn.execute(
                    Submission.__table__.insert().values(
                        id=ids["submission"],
                        assignment_id=ids["assignment"],
                        student_id=ids["user"],
                    )
                )
            )
            await conn.run_sync(
                lambda sync_conn: sync_conn.execute(
                    DocumentVersion.__table__.insert().values(
                        id=ids["version"],
                        submission_id=ids["submission"],
                        version_number=1,
                        storage_key=f"uploads/{ids['version']}.pdf",
                        original_filename="x.pdf",
                        content_type="application/pdf",
                        size_bytes=3,
                        sha256="1" * 64,
                        status=DocumentStatus.QUEUED,
                    )
                )
            )
        graph_committed = True

        sessions = async_sessionmaker(engine, expire_on_commit=False)
        async with sessions() as first, sessions() as second:
            first_task = asyncio.create_task(
                document_ir.get_or_build_document_ir(first, ids["version"], b"pdf")
            )
            assert await asyncio.to_thread(parser_entered.wait, 10)
            second_task = asyncio.create_task(
                document_ir.get_or_build_document_ir(second, ids["version"], b"pdf")
            )
            release_parser.set()
            first_ir = await first_task
            await first.commit()
            second_ir = await second_task
            await second.commit()
            assert first_ir.id == second_ir.id

        async with engine.connect() as conn:
            count = await conn.scalar(
                sa.select(sa.func.count())
                .select_from(DocumentIR)
                .where(DocumentIR.document_version_id == ids["version"])
            )
            assert count == 1
        assert parser_calls == 1
    finally:
        document_ir.parse_document_ir = original_parser
        if graph_committed:
            async with engine.begin() as conn:
                for table, key in (
                    (DocumentIR.__table__, "version"),
                    (DocumentVersion.__table__, "version"),
                    (Submission.__table__, "submission"),
                    (Assignment.__table__, "assignment"),
                    (RubricVersion.__table__, "rubric"),
                    (Membership.__table__, "membership"),
                    (Course.__table__, "course"),
                    (User.__table__, "user"),
                ):
                    id_column = table.c.id
                    await conn.execute(
                        id_column.table.delete().where(id_column == ids[key])
                    )
        await engine.dispose()


@pytest.mark.skipif(
    os.environ.get("RUN_DATABASE_TESTS") != "1",
    reason="Database integration tests require RUN_DATABASE_TESTS=1",
)
def test_postgresql_document_ir_concurrency() -> None:
    asyncio.run(_run_postgresql_concurrency_test())


async def _run_postgresql_duplicate_race_test() -> None:
    settings = get_settings()
    engine = create_async_engine(settings.database_url, poolclass=NullPool)
    ids = {
        name: uuid.uuid4()
        for name in (
            "user",
            "course",
            "membership",
            "rubric",
            "assignment",
            "submission",
            "version_a",
            "version_b",
        )
    }
    parser_entered = threading.Event()
    release_parser = threading.Event()
    parser_calls = 0
    parser_lock = threading.Lock()

    def gated_parser(data: bytes, **_: int) -> ParsedDocumentIR:
        nonlocal parser_calls
        with parser_lock:
            parser_calls += 1
            call_number = parser_calls
        if call_number == 1:
            parser_entered.set()
            assert release_parser.wait(timeout=10)
        return _parsed("f" * 64, {"pages": []})

    original_parser = document_ir.parse_document_ir
    document_ir.parse_document_ir = gated_parser
    graph_committed = False
    try:
        async with engine.begin() as conn:
            await conn.run_sync(
                lambda sync_conn: sync_conn.execute(
                    User.__table__.insert().values(
                        id=ids["user"],
                        email=f"{ids['user']}@example.test",
                        display_name="Student",
                        password_hash="hash",
                        roles=[UserRole.TEACHER, UserRole.STUDENT],
                        status=UserStatus.ACTIVE,
                    )
                )
            )
            await conn.run_sync(
                lambda sync_conn: sync_conn.execute(
                    Course.__table__.insert().values(
                        id=ids["course"],
                        code=f"C-{ids['course']}",
                        name="Course",
                        term="2026",
                        owner_teacher_id=ids["user"],
                        status=CourseStatus.ACTIVE,
                    )
                )
            )
            await conn.run_sync(
                lambda sync_conn: sync_conn.execute(
                    Membership.__table__.insert().values(
                        id=ids["membership"],
                        course_id=ids["course"],
                        user_id=ids["user"],
                        role=MembershipRole.STUDENT,
                        status=MembershipStatus.ACTIVE,
                    )
                )
            )
            await conn.run_sync(
                lambda sync_conn: sync_conn.execute(
                    RubricVersion.__table__.insert().values(
                        id=ids["rubric"],
                        rubric_id=uuid.uuid4(),
                        version_number=1,
                        name="Rubric",
                        status=RubricStatus.DRAFT,
                        calculation_method="WEIGHTED_SUM",
                        total_weight=0,
                        owner_user_id=ids["user"],
                        created_by_user_id=ids["user"],
                    )
                )
            )
            await conn.run_sync(
                lambda sync_conn: sync_conn.execute(
                    Assignment.__table__.insert().values(
                        id=ids["assignment"],
                        course_id=ids["course"],
                        created_by_teacher_id=ids["user"],
                        rubric_version_id=ids["rubric"],
                        title="Assignment",
                        due_at=datetime.now(UTC),
                        status=AssignmentStatus.DRAFT,
                        max_submissions=3,
                    )
                )
            )
            await conn.run_sync(
                lambda sync_conn: sync_conn.execute(
                    Submission.__table__.insert().values(
                        id=ids["submission"],
                        assignment_id=ids["assignment"],
                        student_id=ids["user"],
                    )
                )
            )
            first_initial_sha = "a" * 64
            second_initial_sha = "b" * 64
            assert first_initial_sha != second_initial_sha

            def insert_version(
                sync_conn: Any,
                version_id: uuid.UUID,
                submission_id: uuid.UUID,
                version_number: int,
                key: str,
                sha256: str,
            ) -> None:
                sync_conn.execute(
                    DocumentVersion.__table__.insert().values(
                        id=version_id,
                        submission_id=submission_id,
                        version_number=version_number,
                        storage_key=f"uploads/{key}.pdf",
                        original_filename=f"{key}.pdf",
                        content_type="application/pdf",
                        size_bytes=3,
                        sha256=sha256,
                        status=DocumentStatus.QUEUED,
                    )
                )

            for key, version_number, sha256 in (
                ("version_a", 1, first_initial_sha),
                ("version_b", 2, second_initial_sha),
            ):
                await conn.run_sync(
                    insert_version,
                    ids[key],
                    ids["submission"],
                    version_number,
                    key,
                    sha256,
                )
        graph_committed = True
        sessions = async_sessionmaker(engine, expire_on_commit=False)
        tasks: list[asyncio.Task] = []
        async with sessions() as first, sessions() as second:
            try:
                async with engine.connect() as monitor:
                    second_pid = await second.scalar(sa.text("SELECT pg_backend_pid()"))
                    assert isinstance(second_pid, int)
                    first_task = asyncio.create_task(
                        document_ir.get_or_build_document_ir(
                            first, ids["version_a"], b"pdf"
                        )
                    )
                    tasks.append(first_task)
                    assert await asyncio.to_thread(parser_entered.wait, 10)
                    second_task = asyncio.create_task(
                        document_ir.get_or_build_document_ir(
                            second, ids["version_b"], b"pdf"
                        )
                    )
                    tasks.append(second_task)
                    await asyncio.sleep(0)
                    monitor_query = sa.text("""
                        SELECT wait_event_type, wait_event, state, query
                        FROM pg_stat_activity
                        WHERE pid = :pid
                        """)
                    deadline = asyncio.get_running_loop().time() + 10
                    blocked = False
                    while asyncio.get_running_loop().time() < deadline:
                        activity = (
                            (await monitor.execute(monitor_query, {"pid": second_pid}))
                            .mappings()
                            .first()
                        )
                        active_query = (
                            str(activity["query"] or "").lower() if activity else ""
                        )
                        if (
                            activity
                            and activity["wait_event_type"] == "Lock"
                            and "submissions" in active_query
                            and "for update" in active_query
                        ):
                            blocked = True
                            break
                        await asyncio.sleep(0)
                    assert blocked, "second session never waited on Submission lock"
                    release_parser.set()
                    await first_task
                    initial_versions = (
                        await first.scalars(
                            sa.select(DocumentVersion).where(
                                DocumentVersion.id.in_(
                                    (ids["version_a"], ids["version_b"])
                                )
                            )
                        )
                    ).all()
                    assert {
                        version.id: version.sha256 for version in initial_versions
                    } == {
                        ids["version_a"]: first_initial_sha,
                        ids["version_b"]: second_initial_sha,
                    }
                    first_document = next(
                        version
                        for version in initial_versions
                        if version.id == ids["version_a"]
                    )
                    first_document.sha256 = "f" * 64
                    assert first_document.sha256 != first_initial_sha
                    await first.commit()
                    with pytest.raises(PDFValidationError) as exc_info:
                        await second_task
                    assert exc_info.value.code == "PDF_DUPLICATE"
                    assert str(exc_info.value) == "Duplicate document version"
                    await second.rollback()
                    assert (
                        await second.scalar(
                            sa.select(sa.func.count())
                            .select_from(DocumentIR)
                            .where(
                                DocumentIR.document_version_id.in_(
                                    (ids["version_a"], ids["version_b"])
                                )
                            )
                        )
                        == 1
                    )
                assert parser_calls == 2
            finally:
                release_parser.set()
                for task in tasks:
                    if not task.done():
                        task.cancel()
                await asyncio.gather(*tasks, return_exceptions=True)
    finally:
        document_ir.parse_document_ir = original_parser
        if graph_committed:
            async with engine.begin() as conn:
                await conn.execute(
                    DocumentIR.__table__.delete().where(
                        DocumentIR.document_version_id.in_(
                            (ids["version_a"], ids["version_b"])
                        )
                    )
                )
                await conn.execute(
                    DocumentVersion.__table__.delete().where(
                        DocumentVersion.id.in_((ids["version_a"], ids["version_b"]))
                    )
                )
                for table, key in (
                    (Submission.__table__, "submission"),
                    (Assignment.__table__, "assignment"),
                    (RubricVersion.__table__, "rubric"),
                    (Membership.__table__, "membership"),
                    (Course.__table__, "course"),
                    (User.__table__, "user"),
                ):
                    await conn.execute(table.delete().where(table.c.id == ids[key]))
        await engine.dispose()


@pytest.mark.skipif(
    os.environ.get("RUN_DATABASE_TESTS") != "1",
    reason="Database integration tests require RUN_DATABASE_TESTS=1",
)
def test_postgresql_duplicate_race_is_safe() -> None:
    asyncio.run(_run_postgresql_duplicate_race_test())


class _WorkerSessionContext:
    def __init__(self, db: object) -> None:
        self.db = db

    async def __aenter__(self) -> object:
        return self.db

    async def __aexit__(self, *_args: object) -> None:
        return None


def _worker_job() -> tuple[SimpleNamespace, SimpleNamespace]:
    document = SimpleNamespace(
        id=uuid.uuid4(),
        storage_key="uploads/document.pdf",
        declared_sha256=None,
        submission_id=uuid.uuid4(),
        status=DocumentStatus.PROCESSING,
        sha256=None,
        size_bytes=None,
        page_count=None,
        failure_code=None,
        failure_detail=None,
    )
    job = SimpleNamespace(
        id=uuid.uuid4(),
        document_version_id=document.id,
        attempt_count=2,
        document_version=document,
    )
    return job, document


def _patch_worker(
    monkeypatch: pytest.MonkeyPatch,
    db: object,
    job: SimpleNamespace,
    worker_tasks: object,
) -> None:
    monkeypatch.setattr(
        worker_tasks,
        "_session_factory",
        lambda: lambda: _WorkerSessionContext(db),
    )
    monkeypatch.setattr(worker_tasks, "claim_next_job", AsyncMock(return_value=job))
    monkeypatch.setattr(
        worker_tasks,
        "get_settings",
        lambda: SimpleNamespace(
            analysis_job_heartbeat_seconds=60,
            pdf_max_size_bytes=50,
        ),
    )
    monkeypatch.setattr(
        worker_tasks,
        "S3Storage",
        lambda: SimpleNamespace(get_bounded=lambda _key, _limit: b"bounded-pdf"),
    )
    monkeypatch.setattr(worker_tasks, "update_heartbeat", AsyncMock(return_value=True))


def test_worker_builds_ir_and_copies_source_metadata(
    monkeypatch: pytest.MonkeyPatch,
    worker_tasks: object,
) -> None:
    job, document = _worker_job()
    db = SimpleNamespace(commit=AsyncMock(), rollback=AsyncMock())
    ir = SimpleNamespace(
        content={
            "source": {
                "sha256": "a" * 64,
                "size_bytes": 123,
                "page_count": 4,
            }
        }
    )
    _patch_worker(monkeypatch, db, job, worker_tasks)
    build_ir = AsyncMock(return_value=ir)
    monkeypatch.setattr(
        worker_tasks, "get_or_build_document_ir", build_ir, raising=False
    )
    validate = MagicMock(side_effect=AssertionError("validate_pdf called"))
    monkeypatch.setattr(worker_tasks, "validate_pdf", validate, raising=False)
    mark_done = AsyncMock(return_value=True)
    monkeypatch.setattr(worker_tasks, "mark_done", mark_done)

    result = asyncio.run(worker_tasks._run_analysis_job(None))

    assert result == str(job.id)
    build_ir.assert_awaited_once_with(db, document.id, b"bounded-pdf")
    validate.assert_not_called()
    assert document.sha256 == "a" * 64
    assert document.size_bytes == 123
    mark_done.assert_awaited_once_with(db, job, attempt_count=2)
    assert db.commit.await_count == 2


@pytest.mark.parametrize(
    ("error", "code", "detail"),
    [
        (
            PDFValidationError("PDF_STRUCTURE_LIMIT", "PDF structure exceeds limits"),
            "PDF_STRUCTURE_LIMIT",
            "PDF structure exceeds limits",
        ),
        (
            PDFValidationError("PDF_SHA256_MISMATCH", "PDF checksum does not match"),
            "PDF_SHA256_MISMATCH",
            "PDF checksum does not match",
        ),
        (
            PDFValidationError("PDF_DUPLICATE", "Duplicate document version"),
            "PDF_DUPLICATE",
            "Duplicate document version",
        ),
    ],
)
def test_worker_persists_pdf_validation_errors(
    monkeypatch: pytest.MonkeyPatch,
    worker_tasks: object,
    error: PDFValidationError,
    code: str,
    detail: str,
) -> None:
    job, document = _worker_job()
    db = SimpleNamespace(commit=AsyncMock(), rollback=AsyncMock())
    _patch_worker(monkeypatch, db, job, worker_tasks)
    monkeypatch.setattr(
        worker_tasks,
        "get_or_build_document_ir",
        AsyncMock(side_effect=error),
        raising=False,
    )
    mark_error = AsyncMock(return_value=True)
    monkeypatch.setattr(worker_tasks, "mark_error", mark_error)

    result = asyncio.run(worker_tasks._run_analysis_job(None))

    assert result == str(job.id)
    assert document.status is DocumentStatus.INVALID
    assert document.failure_code == code
    assert document.failure_detail == detail
    mark_error.assert_awaited_once_with(db, job, code, detail, attempt_count=2)
    assert db.commit.await_count == 2


def test_worker_sanitizes_ir_extraction_failure(
    monkeypatch: pytest.MonkeyPatch,
    worker_tasks: object,
) -> None:
    job, document = _worker_job()
    db = SimpleNamespace(commit=AsyncMock(), rollback=AsyncMock())
    _patch_worker(monkeypatch, db, job, worker_tasks)
    monkeypatch.setattr(
        worker_tasks,
        "get_or_build_document_ir",
        AsyncMock(side_effect=DocumentIRExtractionError("secret parser detail")),
        raising=False,
    )
    mark_error = AsyncMock(return_value=True)
    monkeypatch.setattr(worker_tasks, "mark_error", mark_error)

    result = asyncio.run(worker_tasks._run_analysis_job(None))

    assert result == str(job.id)
    assert document.status is DocumentStatus.PROCESSING_FAILED
    assert document.failure_code == "PDF_IR_EXTRACTION_FAILED"
    assert document.failure_detail == "Document structure extraction failed"
    mark_error.assert_awaited_once_with(
        db,
        job,
        "PDF_IR_EXTRACTION_FAILED",
        "Document structure extraction failed",
        attempt_count=2,
    )
    assert "secret" not in document.failure_detail


def test_worker_marks_storage_failure_with_sanitized_detail(
    monkeypatch: pytest.MonkeyPatch,
    worker_tasks: object,
) -> None:
    job, document = _worker_job()
    db = SimpleNamespace(commit=AsyncMock(), rollback=AsyncMock())
    _patch_worker(monkeypatch, db, job, worker_tasks)
    monkeypatch.setattr(
        worker_tasks,
        "get_or_build_document_ir",
        AsyncMock(side_effect=RuntimeError("signed URL secret")),
        raising=False,
    )
    mark_error = AsyncMock(return_value=True)
    monkeypatch.setattr(worker_tasks, "mark_error", mark_error)

    result = asyncio.run(worker_tasks._run_analysis_job(None))

    assert result == str(job.id)
    assert document.status is DocumentStatus.PROCESSING_FAILED
    assert document.failure_code == "PDF_STORAGE_ERROR"
    assert document.failure_detail == "Object storage read failed"
    mark_error.assert_awaited_once_with(
        db,
        job,
        "PDF_STORAGE_ERROR",
        "Object storage read failed",
        attempt_count=2,
    )
    assert "signed URL" not in document.failure_detail


def test_worker_rolls_back_ir_when_done_is_fenced_out(
    monkeypatch: pytest.MonkeyPatch,
    worker_tasks: object,
) -> None:
    job, document = _worker_job()
    db = SimpleNamespace(commit=AsyncMock(), rollback=AsyncMock())
    _patch_worker(monkeypatch, db, job, worker_tasks)
    ir = SimpleNamespace(
        content={
            "source": {
                "sha256": "b" * 64,
                "size_bytes": 9,
                "page_count": 1,
            }
        }
    )
    monkeypatch.setattr(
        worker_tasks,
        "get_or_build_document_ir",
        AsyncMock(return_value=ir),
        raising=False,
    )
    mark_done = AsyncMock(return_value=False)
    monkeypatch.setattr(worker_tasks, "mark_done", mark_done)

    result = asyncio.run(worker_tasks._run_analysis_job(None))
    assert result is None
    mark_done.assert_awaited_once_with(db, job, attempt_count=2)
    db.rollback.assert_awaited_once()
    assert db.commit.await_count == 1
