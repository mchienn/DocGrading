"""T-011 review authorization, persistence, audit, and lock concurrency."""

from __future__ import annotations

import asyncio
import os
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncConnection,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import NullPool

from app.api.schemas_submission import QueueStatus, ReviewDraftRequest
from app.core.config import get_settings
from app.models.enums import UserRole, UserStatus
from app.models.identity import User
from app.services.review import (
    acquire_review_lock,
    get_evidence,
    get_review_draft,
    heartbeat_review_lock,
    list_submission_queue,
    release_review_lock,
    save_review_draft,
)

pytestmark = pytest.mark.skipif(
    os.environ.get("RUN_DATABASE_TESTS") != "1",
    reason="Database integration tests require RUN_DATABASE_TESTS=1",
)


def _ids() -> dict[str, uuid.UUID]:
    names = (
        "teacher",
        "admin",
        "other_teacher",
        "student_1",
        "student_2",
        "student_3",
        "course",
        "rubric",
        "criterion",
        "assignment",
        "submission_1",
        "submission_2",
        "submission_3",
        "document_1",
        "document_2",
        "document_3",
        "document_4",
        "job",
        "document_ir",
        "finding",
        "anchor",
    )
    return {name: uuid.uuid4() for name in names}


def _actor(user_id: uuid.UUID, display_name: str, *roles: UserRole) -> User:
    return User(
        id=user_id,
        email=f"{user_id}@test.local",
        display_name=display_name,
        password_hash="test-hash",
        roles=list(roles),
        status=UserStatus.ACTIVE,
        revision=1,
    )


async def _seed_graph(connection: AsyncConnection, ids: dict[str, uuid.UUID]) -> None:
    await connection.execute(
        text("""
            INSERT INTO public.users (
                id, email, display_name, password_hash, roles, status, revision
            ) VALUES
                (
                    :teacher, :teacher_email, 'Teacher A', 'hash',
                    ARRAY['TEACHER', 'STUDENT']::public.user_role[],
                    'ACTIVE'::public.user_status, 1
                ),
                (
                    :admin, :admin_email, 'Teacher Admin', 'hash',
                    ARRAY['ADMIN', 'TEACHER']::public.user_role[],
                    'ACTIVE'::public.user_status, 1
                ),
                (
                    :other_teacher, :other_teacher_email, 'Teacher B', 'hash',
                    ARRAY['TEACHER']::public.user_role[],
                    'ACTIVE'::public.user_status, 1
                ),
                (
                    :student_1, :student_1_email, 'Student 1', 'hash',
                    ARRAY['STUDENT']::public.user_role[],
                    'ACTIVE'::public.user_status, 1
                ),
                (
                    :student_2, :student_2_email, 'Student 2', 'hash',
                    ARRAY['STUDENT']::public.user_role[],
                    'ACTIVE'::public.user_status, 1
                ),
                (
                    :student_3, :student_3_email, 'Student 3', 'hash',
                    ARRAY['STUDENT']::public.user_role[],
                    'ACTIVE'::public.user_status, 1
                )
        """),
        {
            **{
                name: ids[name]
                for name in (
                    "teacher",
                    "admin",
                    "other_teacher",
                    "student_1",
                    "student_2",
                    "student_3",
                )
            },
            **{
                f"{name}_email": f"{ids[name]}@test.local"
                for name in (
                    "teacher",
                    "admin",
                    "other_teacher",
                    "student_1",
                    "student_2",
                    "student_3",
                )
            },
        },
    )
    await connection.execute(
        text("""
            INSERT INTO public.courses (
                id, code, name, term, owner_teacher_id, revision
            ) VALUES (:course, :code, 'Review Course', '2026A', :teacher, 1)
        """),
        {
            "course": ids["course"],
            "code": f"T011-{ids['course']}",
            "teacher": ids["teacher"],
        },
    )
    await connection.execute(
        text("""
            INSERT INTO public.memberships (
                id, course_id, user_id, role, status
            ) VALUES
                (
                    :membership_1, :course, :student_1,
                    'STUDENT'::public.membership_role,
                    'ACTIVE'::public.membership_status
                ),
                (
                    :membership_2, :course, :student_2,
                    'STUDENT'::public.membership_role,
                    'ACTIVE'::public.membership_status
                ),
                (
                    :membership_3, :course, :student_3,
                    'STUDENT'::public.membership_role,
                    'ACTIVE'::public.membership_status
                )
        """),
        {
            "membership_1": uuid.uuid4(),
            "membership_2": uuid.uuid4(),
            "membership_3": uuid.uuid4(),
            "course": ids["course"],
            "student_1": ids["student_1"],
            "student_2": ids["student_2"],
            "student_3": ids["student_3"],
        },
    )
    await connection.execute(
        text("""
            INSERT INTO public.rubric_versions (
                id, rubric_id, version_number, name, status,
                calculation_method, total_weight, owner_user_id,
                created_by_user_id, revision
            ) VALUES (
                :rubric, :rubric_id, 1, 'Review Rubric',
                'DRAFT'::public.rubric_status, 'WEIGHTED_SUM', 100,
                :teacher, :teacher, 1
            )
        """),
        {
            "rubric": ids["rubric"],
            "rubric_id": uuid.uuid4(),
            "teacher": ids["teacher"],
        },
    )
    await connection.execute(
        text("""
            INSERT INTO public.criterion_versions (
                id, criterion_id, rubric_version_id, code, title,
                description, weight, position, is_enabled,
                evaluation_method, levels, evaluator_config,
                evidence_requirements, revision
            ) VALUES (
                :criterion, :criterion_id, :rubric, 'C1', 'Criterion',
                'Description', 100, 1, true, 'AI', '[]'::jsonb,
                '{}'::jsonb, '{}'::jsonb, 1
            )
        """),
        {
            "criterion": ids["criterion"],
            "criterion_id": uuid.uuid4(),
            "rubric": ids["rubric"],
        },
    )
    now = datetime.now(UTC)
    await connection.execute(
        text("""
            INSERT INTO public.assignments (
                id, course_id, created_by_teacher_id, rubric_version_id,
                title, due_at, max_submissions, status, published_at, revision
            ) VALUES (
                :assignment, :course, :teacher, :rubric, 'Review Assignment',
                :due_at, 3, 'OPEN'::public.assignment_status, :published_at, 1
            )
        """),
        {
            "assignment": ids["assignment"],
            "course": ids["course"],
            "teacher": ids["teacher"],
            "rubric": ids["rubric"],
            "due_at": now + timedelta(days=1),
            "published_at": now,
        },
    )
    await connection.execute(
        text("""
            INSERT INTO public.submissions (id, assignment_id, student_id)
            VALUES
                (:submission_1, :assignment, :student_1),
                (:submission_2, :assignment, :student_2),
                (:submission_3, :assignment, :student_3)
        """),
        {
            "submission_1": ids["submission_1"],
            "submission_2": ids["submission_2"],
            "submission_3": ids["submission_3"],
            "assignment": ids["assignment"],
            "student_1": ids["student_1"],
            "student_2": ids["student_2"],
            "student_3": ids["student_3"],
        },
    )
    await connection.execute(
        text("""
            INSERT INTO public.document_versions (
                id, submission_id, version_number, storage_key,
                original_filename, content_type, size_bytes, sha256,
                status, created_at
            ) VALUES
                (
                    :document_1, :submission_1, 1, :key_1, 'one.pdf',
                    'application/pdf', 100, :sha_1,
                    'AWAITING_REVIEW'::public.document_status, :time_1
                ),
                (
                    :document_2, :submission_2, 1, :key_2, 'two.pdf',
                    'application/pdf', 100, :sha_2,
                    'APPROVED'::public.document_status, :time_2
                ),
                (
                    :document_3, :submission_3, 1, :key_3, 'three.pdf',
                    'application/pdf', 100, :sha_3,
                    'PROCESSING_FAILED'::public.document_status, :time_3
                )
        """),
        {
            "document_1": ids["document_1"],
            "document_2": ids["document_2"],
            "document_3": ids["document_3"],
            "submission_1": ids["submission_1"],
            "submission_2": ids["submission_2"],
            "submission_3": ids["submission_3"],
            "key_1": f"private/{ids['document_1']}",
            "key_2": f"private/{ids['document_2']}",
            "key_3": f"private/{ids['document_3']}",
            "sha_1": "1" * 64,
            "sha_2": "2" * 64,
            "sha_3": "3" * 64,
            "time_1": now - timedelta(minutes=3),
            "time_2": now - timedelta(minutes=2),
            "time_3": now - timedelta(minutes=1),
        },
    )
    await connection.execute(
        text("""
            INSERT INTO public.analysis_jobs (
                id, document_version_id, rubric_version_id, status,
                snapshot, queued_at, finished_at
            ) VALUES (
                :job, :document, :rubric, 'DONE'::public.analysis_job_status,
                '{}'::jsonb, :now, :now
            )
        """),
        {
            "job": ids["job"],
            "document": ids["document_1"],
            "rubric": ids["rubric"],
            "now": now,
        },
    )
    ir_content = """{
        "schema_version": 1,
        "source": {"sha256": "x", "size_bytes": 100, "page_count": 1},
        "pages": [{
            "number": 1, "width": 600, "height": 800,
            "text": "SENSITIVE PDF TEXT",
            "headings": [], "paragraphs": ["paragraph-1"], "tables": []
        }],
        "sections": [],
        "paragraphs": [
            {
                "id": "paragraph-1", "text": "SENSITIVE PDF TEXT",
                "section_id": null, "page_number": 1,
                "bbox": {"x0": 10, "top": 20, "x1": 100, "bottom": 40}
            },
            {"id": "unreferenced-malformed", "page_number": 1}
        ],
        "tables": []
    }"""
    await connection.execute(
        text("""
            INSERT INTO public.document_irs (
                id, document_version_id, schema_version, parser_version, content
            ) VALUES (:document_ir, :document, 1, 't011-test', CAST(:content AS jsonb))
        """),
        {
            "document_ir": ids["document_ir"],
            "document": ids["document_1"],
            "content": ir_content,
        },
    )
    await connection.execute(
        text("""
            INSERT INTO public.findings (
                id, analysis_job_id, criterion_version_id, severity,
                description, suggestion, proposed_score
            ) VALUES (
                :finding, :job, :criterion, 'MAJOR',
                'Missing required section', 'Add required section', 80
            )
        """),
        {
            "finding": ids["finding"],
            "job": ids["job"],
            "criterion": ids["criterion"],
        },
    )
    await connection.execute(
        text("""
            INSERT INTO public.evidence_anchors (
                id, finding_id, document_ir_id, element_id, page_number
            ) VALUES (
                :anchor, :finding, :document_ir, 'paragraph-1', 1
            )
        """),
        {
            "anchor": ids["anchor"],
            "finding": ids["finding"],
            "document_ir": ids["document_ir"],
        },
    )


async def _cleanup_graph(
    connection: AsyncConnection, ids: dict[str, uuid.UUID]
) -> None:
    for statement, parameters in (
        (
            "DELETE FROM public.review_decisions WHERE finding_id = :finding",
            {"finding": ids["finding"]},
        ),
        (
            "DELETE FROM public.review_drafts WHERE submission_id IN "
            "(:submission_1, :submission_2, :submission_3)",
            ids,
        ),
        (
            "DELETE FROM public.review_locks WHERE submission_id IN "
            "(:submission_1, :submission_2, :submission_3)",
            ids,
        ),
        (
            "DELETE FROM public.evidence_anchors WHERE id = :anchor",
            {"anchor": ids["anchor"]},
        ),
        (
            "DELETE FROM public.findings WHERE id = :finding",
            {"finding": ids["finding"]},
        ),
        (
            "DELETE FROM public.document_irs WHERE id = :document_ir",
            {"document_ir": ids["document_ir"]},
        ),
        (
            "DELETE FROM public.analysis_jobs WHERE id = :job",
            {"job": ids["job"]},
        ),
        (
            "DELETE FROM public.document_versions WHERE id IN "
            "(:document_1, :document_2, :document_3)",
            ids,
        ),
        (
            "DELETE FROM public.submissions WHERE id IN "
            "(:submission_1, :submission_2, :submission_3)",
            ids,
        ),
        (
            "DELETE FROM public.assignments WHERE id = :assignment",
            {"assignment": ids["assignment"]},
        ),
        (
            "DELETE FROM public.criterion_versions WHERE id = :criterion",
            {"criterion": ids["criterion"]},
        ),
        (
            "DELETE FROM public.rubric_versions WHERE id = :rubric",
            {"rubric": ids["rubric"]},
        ),
        (
            "DELETE FROM public.memberships WHERE course_id = :course",
            {"course": ids["course"]},
        ),
        (
            "DELETE FROM public.courses WHERE id = :course",
            {"course": ids["course"]},
        ),
        (
            "DELETE FROM public.users WHERE id IN "
            "(:teacher, :admin, :other_teacher, "
            ":student_1, :student_2, :student_3)",
            ids,
        ),
    ):
        await connection.execute(text(statement), parameters)


async def _queue_evidence_scenario() -> None:
    ids = _ids()
    engine = create_async_engine(get_settings().database_url, poolclass=NullPool)
    connection = await engine.connect()
    transaction = await connection.begin()
    session = AsyncSession(bind=connection, expire_on_commit=False)
    try:
        await _seed_graph(connection, ids)
        owner = _actor(ids["teacher"], "Teacher A", UserRole.TEACHER, UserRole.STUDENT)
        admin = _actor(ids["admin"], "Teacher Admin", UserRole.ADMIN, UserRole.TEACHER)
        other = _actor(ids["other_teacher"], "Teacher B", UserRole.TEACHER)
        student = _actor(ids["student_1"], "Student 1", UserRole.STUDENT)

        queue = await list_submission_queue(
            session,
            course_id=ids["course"],
            user=owner,
            sort="asc",
        )
        assert queue.page == 1
        assert queue.page_size == 50
        assert queue.total == 3
        assert [item.document_version_id for item in queue.items] == [
            ids["document_1"],
            ids["document_2"],
            ids["document_3"],
        ]
        assert [item.queue_status for item in queue.items] == [
            QueueStatus.UNREVIEWED,
            QueueStatus.REVIEWED,
            QueueStatus.ERROR,
        ]
        errors = await list_submission_queue(
            session,
            course_id=ids["course"],
            user=admin,
            status_filter=QueueStatus.ERROR,
        )
        assert errors.total == 1
        assert [item.document_version_id for item in errors.items] == [
            ids["document_3"]
        ]

        for denied_user in (other, student):
            with pytest.raises(HTTPException) as error:
                await list_submission_queue(
                    session,
                    course_id=ids["course"],
                    user=denied_user,
                )
            assert error.value.status_code == 403

        evidence = await get_evidence(
            session, submission_id=ids["submission_1"], user=owner
        )
        admin_evidence = await get_evidence(
            session, submission_id=ids["submission_1"], user=admin
        )
        assert evidence == admin_evidence
        payload = evidence.model_dump()
        assert set(payload) == {"submission_id", "document_version_id", "findings"}
        assert set(payload["findings"][0]) == {
            "id",
            "criterion_version_id",
            "severity",
            "description",
            "suggestion",
            "proposed_score",
            "evidence",
        }
        assert set(payload["findings"][0]["evidence"][0]) == {
            "document_ir_id",
            "element_id",
            "page_number",
            "bbox",
        }
        assert evidence.findings[0].evidence[0].model_dump() == {
            "document_ir_id": ids["document_ir"],
            "element_id": "paragraph-1",
            "page_number": 1,
            "bbox": {"x0": 10.0, "top": 20.0, "x1": 100.0, "bottom": 40.0},
        }
        assert "SENSITIVE PDF TEXT" not in str(evidence.model_dump())
        assert f"private/{ids['document_1']}" not in str(evidence.model_dump())
        with pytest.raises(HTTPException) as error:
            await get_evidence(session, submission_id=ids["submission_1"], user=other)
        assert error.value.status_code == 403
    finally:
        await session.close()
        await transaction.rollback()
        await connection.close()
        await engine.dispose()


def test_owner_admin_multirole_queue_and_evidence_privacy() -> None:
    asyncio.run(_queue_evidence_scenario())


async def _lock_contention_scenario() -> None:
    ids = _ids()
    engine = create_async_engine(get_settings().database_url, poolclass=NullPool)
    setup_complete = False
    try:
        async with engine.begin() as connection:
            await _seed_graph(connection, ids)
        setup_complete = True
        owner = _actor(ids["teacher"], "Teacher A", UserRole.TEACHER, UserRole.STUDENT)
        admin = _actor(ids["admin"], "Teacher Admin", UserRole.ADMIN, UserRole.TEACHER)
        sessions = async_sessionmaker(engine, expire_on_commit=False)
        start = asyncio.Event()

        async def contend(actor: User):
            async with sessions() as session:
                await start.wait()
                response = await acquire_review_lock(
                    session,
                    submission_id=ids["submission_1"],
                    user=actor,
                )
                await session.commit()
                return actor, response

        tasks = [asyncio.create_task(contend(actor)) for actor in (owner, admin)]
        start.set()
        results = await asyncio.gather(*tasks)
        assert sorted(result.acquired for _actor_value, result in results) == [
            False,
            True,
        ]
        winner = next(actor for actor, result in results if result.acquired)
        loser = next(actor for actor, result in results if not result.acquired)

        async with engine.begin() as connection:
            count = await connection.scalar(
                text(
                    "SELECT count(*) FROM public.review_locks "
                    "WHERE submission_id = :submission"
                ),
                {"submission": ids["submission_1"]},
            )
            assert count == 1
            await connection.execute(
                text("""
                    UPDATE public.review_locks
                    SET acquired_at = CURRENT_TIMESTAMP - INTERVAL '11 minutes',
                        expires_at = CURRENT_TIMESTAMP - INTERVAL '1 minute'
                    WHERE submission_id = :submission
                """),
                {"submission": ids["submission_1"]},
            )

        async with sessions() as session:
            takeover = await acquire_review_lock(
                session,
                submission_id=ids["submission_1"],
                user=loser,
            )
            await session.commit()
            assert takeover.acquired is True
            assert takeover.reviewer_user_id == loser.id

        async with sessions() as session:
            with pytest.raises(HTTPException) as error:
                await heartbeat_review_lock(
                    session,
                    submission_id=ids["submission_1"],
                    user=winner,
                )
            assert error.value.status_code == 409
            await session.rollback()

        async with sessions() as archive_session:
            await archive_session.execute(
                text("""
                    UPDATE public.courses
                    SET status = 'ARCHIVED'::public.course_status
                    WHERE id = :course
                """),
                {"course": ids["course"]},
            )

            waiter_pid = asyncio.get_running_loop().create_future()

            async def acquire_after_archive() -> HTTPException:
                async with sessions() as review_session:
                    pid = await review_session.scalar(text("SELECT pg_backend_pid()"))
                    assert pid is not None
                    waiter_pid.set_result(pid)
                    with pytest.raises(HTTPException) as archived_error:
                        await acquire_review_lock(
                            review_session,
                            submission_id=ids["submission_1"],
                            user=owner,
                        )
                    await review_session.rollback()
                    return archived_error.value

            blocked = asyncio.create_task(acquire_after_archive())
            pid = await waiter_pid
            waiting = False
            for _ in range(500):
                waiting = bool(
                    await archive_session.scalar(
                        text("""
                            SELECT EXISTS (
                                SELECT 1
                                FROM pg_locks
                                WHERE pid = :pid
                                  AND NOT granted
                            )
                        """),
                        {"pid": pid},
                    )
                )
                if waiting:
                    break
                await asyncio.sleep(0.01)
            assert waiting
            assert not blocked.done()
            await archive_session.commit()
            archived_error = await asyncio.wait_for(blocked, timeout=1)
            assert archived_error.status_code == 409
            assert archived_error.detail == "Archived courses are read-only"
    finally:
        if setup_complete:
            async with engine.begin() as connection:
                await _cleanup_graph(connection, ids)
        await engine.dispose()


def test_two_teachers_contend_for_one_ttl_lock() -> None:
    asyncio.run(_lock_contention_scenario())


async def _autosave_override_scenario() -> None:
    ids = _ids()
    engine = create_async_engine(get_settings().database_url, poolclass=NullPool)
    connection = await engine.connect()
    transaction = await connection.begin()
    session = AsyncSession(bind=connection, expire_on_commit=False)
    try:
        await _seed_graph(connection, ids)
        owner = _actor(ids["teacher"], "Teacher A", UserRole.TEACHER, UserRole.STUDENT)
        admin = _actor(ids["admin"], "Teacher Admin", UserRole.ADMIN, UserRole.TEACHER)
        acquired = await acquire_review_lock(
            session,
            submission_id=ids["submission_1"],
            user=owner,
        )
        assert acquired.acquired is True

        body = ReviewDraftRequest(
            document_version_id=ids["document_1"],
            revision=1,
            comment="Teacher comment",
            decisions=[
                {
                    "finding_id": ids["finding"],
                    "decision": "EDIT",
                    "edited_description": "Corrected description",
                    "final_score": 75,
                    "reason": "Evidence supports a lower score",
                }
            ],
        )
        saved = await save_review_draft(
            session,
            submission_id=ids["submission_1"],
            user=owner,
            body=body,
        )
        assert saved.document_version_id == ids["document_1"]
        assert saved.revision == 2
        assert saved.comment == "Teacher comment"
        assert saved.decisions[0].final_score == 75

        reloaded = await get_review_draft(
            session,
            submission_id=ids["submission_1"],
            user=owner,
        )
        assert reloaded == saved
        replayed = await save_review_draft(
            session,
            submission_id=ids["submission_1"],
            user=owner,
            body=body,
        )
        assert replayed == saved

        audits = (
            await session.execute(
                text("""
                    SELECT before, after, reason, actor_user_id
                    FROM public.audit_events
                    WHERE resource_type = 'Finding'
                      AND resource_id = :finding
                      AND action = 'FINDING_OVERRIDE'
                    ORDER BY occurred_at
                """),
                {"finding": ids["finding"]},
            )
        ).all()
        assert len(audits) == 1
        before, after, reason, actor_user_id = audits[0]
        assert before == {
            "decision": "PROPOSED",
            "score": "80.00",
            "analysis_job_id": str(ids["job"]),
        }
        assert after == {
            "decision": "EDIT",
            "score": "75.00",
            "analysis_job_id": str(ids["job"]),
        }
        assert reason == "Evidence supports a lower score"
        assert actor_user_id == ids["teacher"]

        stale = body.model_copy(update={"comment": "Must not overwrite"})
        with pytest.raises(HTTPException) as error:
            await save_review_draft(
                session,
                submission_id=ids["submission_1"],
                user=owner,
                body=stale,
            )
        assert error.value.status_code == 409
        assert (
            await get_review_draft(
                session,
                submission_id=ids["submission_1"],
                user=owner,
            )
        ).comment == "Teacher comment"
        await session.execute(
            text("""
                INSERT INTO public.document_versions (
                    id, submission_id, version_number, previous_version_id,
                    storage_key, original_filename, content_type, size_bytes,
                    sha256, status
                ) VALUES (
                    :document, :submission, 2, :previous, :storage_key,
                    'four.pdf', 'application/pdf', 100, :sha256,
                    'UPLOADING'::public.document_status
                )
            """),
            {
                "document": ids["document_4"],
                "submission": ids["submission_1"],
                "previous": ids["document_1"],
                "storage_key": f"private/{ids['document_4']}",
                "sha256": "4" * 64,
            },
        )
        rolled_over = await get_review_draft(
            session,
            submission_id=ids["submission_1"],
            user=owner,
        )
        assert rolled_over.document_version_id == ids["document_4"]
        assert rolled_over.revision == saved.revision
        assert rolled_over.comment == ""
        assert rolled_over.decisions == []
        with pytest.raises(HTTPException) as error:
            await save_review_draft(
                session,
                submission_id=ids["submission_1"],
                user=owner,
                body=body.model_copy(
                    update={
                        "revision": rolled_over.revision,
                        "comment": "Stale previous-version comment",
                        "decisions": [],
                    }
                ),
            )
        assert error.value.status_code == 409
        assert error.value.detail == "Document version changed"
        reset = await save_review_draft(
            session,
            submission_id=ids["submission_1"],
            user=owner,
            body=ReviewDraftRequest(
                document_version_id=ids["document_4"],
                revision=rolled_over.revision,
                comment="Reviewing latest version",
            ),
        )
        assert reset.document_version_id == ids["document_4"]
        assert reset.revision == saved.revision + 1
        assert reset.decisions == []

        with pytest.raises(HTTPException) as error:
            await save_review_draft(
                session,
                submission_id=ids["submission_1"],
                user=admin,
                body=ReviewDraftRequest(
                    document_version_id=ids["document_4"],
                    revision=1,
                    comment="Admin write",
                ),
            )
        assert error.value.status_code == 409
        await release_review_lock(
            session,
            submission_id=ids["submission_1"],
            user=admin,
        )
        release_audit = (
            await session.execute(
                text("""
                    SELECT before, after, reason, actor_user_id
                    FROM public.audit_events
                    WHERE resource_type = 'ReviewLock'
                      AND action = 'ADMIN_RELEASE'
                      AND actor_user_id = :admin
                """),
                {"admin": ids["admin"]},
            )
        ).one()
        assert release_audit.before["submission_id"] == str(ids["submission_1"])
        assert release_audit.before["reviewer_user_id"] == str(ids["teacher"])
        assert release_audit.after == {"released": True}
        assert release_audit.reason == "Admin released review lock"
        admin_lock = await acquire_review_lock(
            session,
            submission_id=ids["submission_1"],
            user=admin,
        )
        assert admin_lock.acquired is True
        await release_review_lock(
            session,
            submission_id=ids["submission_1"],
            user=admin,
        )
        force_release_count = await session.scalar(
            text("""
                SELECT count(*)
                FROM public.audit_events
                WHERE resource_type = 'ReviewLock'
                  AND action = 'ADMIN_RELEASE'
                  AND actor_user_id = :admin
            """),
            {"admin": ids["admin"]},
        )
        assert force_release_count == 1
    finally:
        await session.close()
        await transaction.rollback()
        await connection.close()
        await engine.dispose()


def test_autosave_retry_reload_lock_owner_and_override_audit() -> None:
    asyncio.run(_autosave_override_scenario())
