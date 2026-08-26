import asyncio
import contextlib
import json
import os
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import create_async_engine

from app.core.config import get_settings

pytestmark = pytest.mark.skipif(
    os.environ.get("RUN_DATABASE_TESTS") != "1",
    reason="Database integration tests require RUN_DATABASE_TESTS=1",
)


async def _run_domain_invariants_test() -> None:
    settings = get_settings()
    engine = create_async_engine(settings.database_url)

    try:
        async with engine.connect() as conn:
            trans = await conn.begin()
            try:
                # 1. Unique identifiers for isolated test execution
                teacher_id = uuid.uuid4()
                student_id = uuid.uuid4()
                unenrolled_student_id = uuid.uuid4()
                course_id = uuid.uuid4()
                membership_id = uuid.uuid4()
                rubric_id = uuid.uuid4()
                rubric_version_1_id = uuid.uuid4()
                rubric_version_2_id = uuid.uuid4()
                criterion_id = uuid.uuid4()
                criterion_version_1_id = uuid.uuid4()
                assignment_id = uuid.uuid4()
                submission_id = uuid.uuid4()
                audit_event_id = uuid.uuid4()

                now = datetime.now(UTC)
                due_date = now + timedelta(days=7)

                # Insert valid TEACHER user
                await conn.execute(
                    text("""
                        INSERT INTO users (
                            id, email, display_name, password_hash,
                            roles, status, revision
                        )
                        VALUES (
                            :id, :email, :display_name, :password_hash,
                            ARRAY['TEACHER']::user_role[], 'ACTIVE'::user_status, 1
                        )
                    """),
                    {
                        "id": teacher_id,
                        "email": f"teacher_{uuid.uuid4().hex[:8]}@example.com",
                        "display_name": "Teacher User",
                        "password_hash": "hash_teacher_secret",
                    },
                )

                # Insert valid STUDENT user (enrolled)
                await conn.execute(
                    text("""
                        INSERT INTO users (
                            id, email, display_name, password_hash,
                            roles, status, revision
                        )
                        VALUES (
                            :id, :email, :display_name, :password_hash,
                            ARRAY['STUDENT']::user_role[], 'ACTIVE'::user_status, 1
                        )
                    """),
                    {
                        "id": student_id,
                        "email": f"student_{uuid.uuid4().hex[:8]}@example.com",
                        "display_name": "Student User",
                        "password_hash": "hash_student_secret",
                    },
                )

                # Insert second STUDENT user (unenrolled)
                await conn.execute(
                    text("""
                        INSERT INTO users (
                            id, email, display_name, password_hash,
                            roles, status, revision
                        )
                        VALUES (
                            :id, :email, :display_name, :password_hash,
                            ARRAY['STUDENT']::user_role[], 'ACTIVE'::user_status, 1
                        )
                    """),
                    {
                        "id": unenrolled_student_id,
                        "email": f"unenrolled_{uuid.uuid4().hex[:8]}@example.com",
                        "display_name": "Unenrolled Student User",
                        "password_hash": "hash_unenrolled_secret",
                    },
                )

                # 2. Reject Course owned by non-Teacher
                with pytest.raises(
                    DBAPIError,
                    match=r"course owner must have TEACHER role",
                ):
                    async with conn.begin_nested():
                        await conn.execute(
                            text("""
                                INSERT INTO courses (
                                    id, code, name, term, owner_teacher_id, revision
                                )
                                VALUES (
                                    :id, :code, :name, :term, :owner_teacher_id, 1
                                )
                            """),
                            {
                                "id": uuid.uuid4(),
                                "code": f"INVALID_COURSE_{uuid.uuid4().hex[:8]}",
                                "name": "Invalid Course",
                                "term": "Fall 2026",
                                "owner_teacher_id": student_id,
                            },
                        )

                # Insert valid Course owned by Teacher
                await conn.execute(
                    text("""
                        INSERT INTO courses (
                            id, code, name, term, owner_teacher_id, revision
                        )
                        VALUES (
                            :id, :code, :name, :term, :owner_teacher_id, 1
                        )
                    """),
                    {
                        "id": course_id,
                        "code": f"CS_{uuid.uuid4().hex[:8]}",
                        "name": "Introduction to Computer Science",
                        "term": "Fall 2026",
                        "owner_teacher_id": teacher_id,
                    },
                )

                # 3. Reject Membership whose role is absent from User.roles
                with pytest.raises(
                    DBAPIError,
                    match=r"membership role must be present in user roles",
                ):
                    async with conn.begin_nested():
                        await conn.execute(
                            text("""
                                INSERT INTO memberships (
                                    id, course_id, user_id, role, status
                                )
                                VALUES (
                                    :id, :course_id, :user_id,
                                    'TEACHER'::membership_role,
                                    'ACTIVE'::membership_status
                                )
                            """),
                            {
                                "id": uuid.uuid4(),
                                "course_id": course_id,
                                "user_id": student_id,
                            },
                        )

                # Insert valid active Student Membership
                await conn.execute(
                    text("""
                        INSERT INTO memberships (
                            id, course_id, user_id, role, status
                        )
                        VALUES (
                            :id, :course_id, :user_id,
                            'STUDENT'::membership_role,
                            'ACTIVE'::membership_status
                        )
                    """),
                    {
                        "id": membership_id,
                        "course_id": course_id,
                        "user_id": student_id,
                    },
                )

                # 4. Reject removal of a User role still used by Course ownership
                # or Membership
                with pytest.raises(
                    DBAPIError,
                    match=r"cannot remove role used by course or membership",
                ):
                    async with conn.begin_nested():
                        await conn.execute(
                            text("""
                                UPDATE users
                                SET roles = ARRAY['STUDENT']::user_role[]
                                WHERE id = :id
                            """),
                            {"id": teacher_id},
                        )

                with pytest.raises(
                    DBAPIError,
                    match=r"cannot remove role used by course or membership",
                ):
                    async with conn.begin_nested():
                        await conn.execute(
                            text("""
                                UPDATE users
                                SET roles = ARRAY['TEACHER']::user_role[]
                                WHERE id = :id
                            """),
                            {"id": student_id},
                        )

                # Insert RubricVersion 1 (PUBLISHED)
                await conn.execute(
                    text("""
                        INSERT INTO rubric_versions (
                            id, rubric_id, version_number, name, description,
                            status, calculation_method, total_weight,
                            owner_user_id, created_by_user_id, published_at,
                            revision
                        )
                        VALUES (
                            :id, :rubric_id, :version_number, :name, :description,
                            'PUBLISHED'::rubric_status, :calculation_method,
                            :total_weight, :owner_user_id, :created_by_user_id,
                            :published_at, 1
                        )
                    """),
                    {
                        "id": rubric_version_1_id,
                        "rubric_id": rubric_id,
                        "version_number": 1,
                        "name": "Standard Coding Rubric v1",
                        "description": "Initial rubric version",
                        "calculation_method": "WEIGHTED_SUM",
                        "total_weight": 100.0,
                        "owner_user_id": teacher_id,
                        "created_by_user_id": teacher_id,
                        "published_at": now,
                    },
                )

                # Insert RubricVersion 2 (PUBLISHED)
                await conn.execute(
                    text("""
                        INSERT INTO rubric_versions (
                            id, rubric_id, version_number, name, description,
                            status, calculation_method, total_weight,
                            owner_user_id, created_by_user_id, published_at,
                            revision
                        )
                        VALUES (
                            :id, :rubric_id, :version_number, :name, :description,
                            'PUBLISHED'::rubric_status, :calculation_method,
                            :total_weight, :owner_user_id, :created_by_user_id,
                            :published_at, 1
                        )
                    """),
                    {
                        "id": rubric_version_2_id,
                        "rubric_id": rubric_id,
                        "version_number": 2,
                        "name": "Standard Coding Rubric v2",
                        "description": "Second rubric version",
                        "calculation_method": "WEIGHTED_SUM",
                        "total_weight": 100.0,
                        "owner_user_id": teacher_id,
                        "created_by_user_id": teacher_id,
                        "published_at": now,
                    },
                )

                # Insert CriterionVersion on rubric 1
                await conn.execute(
                    text("""
                        INSERT INTO criterion_versions (
                            id, criterion_id, rubric_version_id, code, title,
                            description, scope, weight, position, is_enabled,
                            evaluation_method, levels, evaluator_config,
                            evidence_requirements, revision
                        )
                        VALUES (
                            :id, :criterion_id, :rubric_version_id, :code, :title,
                            :description, :scope, :weight, :position, :is_enabled,
                            :evaluation_method, CAST(:levels AS jsonb),
                            CAST(:evaluator_config AS jsonb),
                            CAST(:evidence_requirements AS jsonb), 1
                        )
                    """),
                    {
                        "id": criterion_version_1_id,
                        "criterion_id": criterion_id,
                        "rubric_version_id": rubric_version_1_id,
                        "code": "CRIT_CODE_QUALITY",
                        "title": "Code Quality and Design",
                        "description": (
                            "Evaluates clarity, architecture, and maintainability"
                        ),
                        "scope": "SECTION",
                        "weight": 100.0,
                        "position": 1,
                        "is_enabled": True,
                        "evaluation_method": "AI_ASSISTED",
                        "levels": json.dumps([{"name": "Proficient", "score": 100}]),
                        "evaluator_config": json.dumps({"model": "gpt-4o"}),
                        "evidence_requirements": json.dumps({"required_lines": True}),
                    },
                )

                # Insert OPEN Assignment on rubric 1
                await conn.execute(
                    text("""
                        INSERT INTO assignments (
                            id, course_id, created_by_teacher_id, rubric_version_id,
                            title, description, due_at, max_submissions, status,
                            published_at, closed_at, revision
                        )
                        VALUES (
                            :id, :course_id, :created_by_teacher_id,
                            :rubric_version_id, :title, :description, :due_at, 3,
                            'OPEN'::assignment_status, :published_at, NULL, 1
                        )
                    """),
                    {
                        "id": assignment_id,
                        "course_id": course_id,
                        "created_by_teacher_id": teacher_id,
                        "rubric_version_id": rubric_version_1_id,
                        "title": "Final Project Assignment",
                        "description": "Complete the final software project",
                        "due_at": due_date,
                        "published_at": now,
                    },
                )

                # 5. Reject Submission by Student without ACTIVE Student
                # Membership in Assignment's Course
                with pytest.raises(
                    DBAPIError,
                    match=r"student must have active course membership",
                ):
                    async with conn.begin_nested():
                        await conn.execute(
                            text("""
                                INSERT INTO submissions (id, assignment_id, student_id)
                                VALUES (:id, :assignment_id, :student_id)
                            """),
                            {
                                "id": uuid.uuid4(),
                                "assignment_id": assignment_id,
                                "student_id": unenrolled_student_id,
                            },
                        )

                # Insert valid Submission by the enrolled Student
                await conn.execute(
                    text("""
                        INSERT INTO submissions (id, assignment_id, student_id)
                        VALUES (:id, :assignment_id, :student_id)
                    """),
                    {
                        "id": submission_id,
                        "assignment_id": assignment_id,
                        "student_id": student_id,
                    },
                )

                # 6. After valid Submission, reject UPDATE/DELETE of rubric
                # version and criterion, and assignment rubric change
                with pytest.raises(
                    DBAPIError,
                    match=r"rubric version is immutable after first submission",
                ):
                    async with conn.begin_nested():
                        await conn.execute(
                            text("""
                                UPDATE rubric_versions
                                SET name = 'Modified Rubric Name'
                                WHERE id = :id
                            """),
                            {"id": rubric_version_1_id},
                        )

                with pytest.raises(
                    DBAPIError,
                    match=r"rubric version is immutable after first submission",
                ):
                    async with conn.begin_nested():
                        await conn.execute(
                            text("""
                                DELETE FROM rubric_versions
                                WHERE id = :id
                            """),
                            {"id": rubric_version_1_id},
                        )

                with pytest.raises(
                    DBAPIError,
                    match=r"criterion version is immutable after first submission",
                ):
                    async with conn.begin_nested():
                        await conn.execute(
                            text("""
                                UPDATE criterion_versions
                                SET title = 'Modified Criterion Title'
                                WHERE id = :id
                            """),
                            {"id": criterion_version_1_id},
                        )

                with pytest.raises(
                    DBAPIError,
                    match=r"criterion version is immutable after first submission",
                ):
                    async with conn.begin_nested():
                        await conn.execute(
                            text("""
                                DELETE FROM criterion_versions
                                WHERE id = :id
                            """),
                            {"id": criterion_version_1_id},
                        )

                with pytest.raises(
                    DBAPIError,
                    match=r"assignment rubric is immutable after first submission",
                ):
                    async with conn.begin_nested():
                        await conn.execute(
                            text("""
                                UPDATE assignments
                                SET rubric_version_id = :new_rubric_version_id
                                WHERE id = :id
                            """),
                            {
                                "id": assignment_id,
                                "new_rubric_version_id": rubric_version_2_id,
                            },
                        )

                # 7. Audit actor constraint rejects USER/null actor and
                # SYSTEM/non-null actor
                with pytest.raises(DBAPIError, match=r"ck_audit_events_actor"):
                    async with conn.begin_nested():
                        await conn.execute(
                            text("""
                                INSERT INTO audit_events (
                                    id, resource_type, resource_id, action,
                                    actor_type, actor_user_id, before, after,
                                    reason
                                )
                                VALUES (
                                    :id, 'COURSE', :resource_id, 'UPDATE',
                                    'USER'::audit_actor_type, NULL,
                                    '{"name": "Old"}'::jsonb,
                                    '{"name": "New"}'::jsonb, 'Update course'
                                )
                            """),
                            {
                                "id": uuid.uuid4(),
                                "resource_id": course_id,
                            },
                        )

                with pytest.raises(DBAPIError, match=r"ck_audit_events_actor"):
                    async with conn.begin_nested():
                        await conn.execute(
                            text("""
                                INSERT INTO audit_events (
                                    id, resource_type, resource_id, action,
                                    actor_type, actor_user_id, before, after,
                                    reason
                                )
                                VALUES (
                                    :id, 'COURSE', :resource_id, 'UPDATE',
                                    'SYSTEM'::audit_actor_type, :actor_user_id,
                                    '{"name": "Old"}'::jsonb,
                                    '{"name": "New"}'::jsonb,
                                    'System auto-update'
                                )
                            """),
                            {
                                "id": uuid.uuid4(),
                                "resource_id": course_id,
                                "actor_user_id": teacher_id,
                            },
                        )

                # 8. Insert valid SYSTEM AuditEvent with before/after object
                # and nonblank reason
                await conn.execute(
                    text("""
                        INSERT INTO audit_events (
                            id, resource_type, resource_id, action, actor_type,
                            actor_user_id, before, after, reason
                        )
                        VALUES (
                            :id, 'ASSIGNMENT', :resource_id, 'PUBLISH',
                            'SYSTEM'::audit_actor_type, NULL,
                            '{"status": "DRAFT"}'::jsonb,
                            '{"status": "OPEN"}'::jsonb,
                            'Automated scheduler publish'
                        )
                    """),
                    {
                        "id": audit_event_id,
                        "resource_id": assignment_id,
                    },
                )

                # Reject UPDATE and DELETE on audit events (append-only)
                with pytest.raises(
                    DBAPIError,
                    match=r"audit events are append-only",
                ):
                    async with conn.begin_nested():
                        await conn.execute(
                            text("""
                                UPDATE audit_events
                                SET reason = 'Tampered reason'
                                WHERE id = :id
                            """),
                            {"id": audit_event_id},
                        )

                with pytest.raises(
                    DBAPIError,
                    match=r"audit events are append-only",
                ):
                    async with conn.begin_nested():
                        await conn.execute(
                            text("""
                                DELETE FROM audit_events
                                WHERE id = :id
                            """),
                            {"id": audit_event_id},
                        )

            finally:
                await trans.rollback()
    finally:
        await engine.dispose()


def test_postgresql_domain_invariants() -> None:
    asyncio.run(_run_domain_invariants_test())


def _constraint_name(error: DBAPIError, expected: str) -> str | None:
    original = error.orig
    diagnostic = getattr(original, "diag", None)
    actual = getattr(diagnostic, "constraint_name", None) or getattr(
        original, "constraint_name", None
    )
    if actual is not None:
        return actual
    return expected if expected in str(error) else None


async def _cleanup_domain_rows(
    engine,
    *,
    submission_ids=(),
    assignment_ids=(),
    criterion_version_ids=(),
    rubric_version_ids=(),
    membership_ids=(),
    course_ids=(),
    audit_event_ids=(),
    user_ids=(),
) -> None:
    async with engine.connect() as conn:
        trans = await conn.begin()
        try:
            for row_id in submission_ids:
                await conn.execute(
                    text("DELETE FROM submissions WHERE id = :id"),
                    {"id": row_id},
                )
            for row_id in assignment_ids:
                await conn.execute(
                    text("DELETE FROM assignments WHERE id = :id"),
                    {"id": row_id},
                )
            for row_id in criterion_version_ids:
                await conn.execute(
                    text("DELETE FROM criterion_versions WHERE id = :id"),
                    {"id": row_id},
                )
            for row_id in rubric_version_ids:
                await conn.execute(
                    text("DELETE FROM rubric_versions WHERE id = :id"),
                    {"id": row_id},
                )
            for row_id in membership_ids:
                await conn.execute(
                    text("DELETE FROM memberships WHERE id = :id"),
                    {"id": row_id},
                )
            for row_id in course_ids:
                await conn.execute(
                    text("DELETE FROM courses WHERE id = :id"),
                    {"id": row_id},
                )
            for row_id in audit_event_ids:
                await conn.execute(
                    text("DELETE FROM audit_events WHERE id = :id"),
                    {"id": row_id},
                )
            for row_id in user_ids:
                await conn.execute(
                    text("DELETE FROM users WHERE id = :id"),
                    {"id": row_id},
                )
            await trans.commit()
        except Exception:
            await trans.rollback()
            raise


async def _insert_durable_freeze_graph(conn, ids) -> None:
    now = datetime.now(UTC)
    due_date = now + timedelta(days=7)
    await conn.execute(
        text("""
            INSERT INTO users (
                id, email, display_name, password_hash, roles, status, revision
            )
            VALUES
                (
                    :teacher_id, :teacher_email, 'Durable Freeze Teacher',
                    'hash_durable_teacher', ARRAY['TEACHER']::user_role[],
                    'ACTIVE'::user_status, 1
                ),
                (
                    :student_id, :student_email, 'Durable Freeze Student',
                    'hash_durable_student', ARRAY['STUDENT']::user_role[],
                    'ACTIVE'::user_status, 1
                )
        """),
        {
            "teacher_id": ids["teacher_id"],
            "teacher_email": f"durable_teacher_{uuid.uuid4().hex}@example.com",
            "student_id": ids["student_id"],
            "student_email": f"durable_student_{uuid.uuid4().hex}@example.com",
        },
    )
    await conn.execute(
        text("""
            INSERT INTO courses (
                id, code, name, term, owner_teacher_id, revision
            )
            VALUES (
                :id, :code, 'Durable Freeze Course', 'Fall 2026',
                :owner_teacher_id, 1
            )
        """),
        {
            "id": ids["course_id"],
            "code": f"DURABLE_{uuid.uuid4().hex}",
            "owner_teacher_id": ids["teacher_id"],
        },
    )
    await conn.execute(
        text("""
            INSERT INTO memberships (
                id, course_id, user_id, role, status
            )
            VALUES (
                :id, :course_id, :user_id,
                'STUDENT'::membership_role, 'ACTIVE'::membership_status
            )
        """),
        {
            "id": ids["membership_id"],
            "course_id": ids["course_id"],
            "user_id": ids["student_id"],
        },
    )
    for version_id, version_number, name in (
        (ids["rubric_version_1_id"], 1, "Durable Rubric One"),
        (ids["rubric_version_2_id"], 2, "Durable Rubric Two"),
    ):
        await conn.execute(
            text("""
                INSERT INTO rubric_versions (
                    id, rubric_id, version_number, name, description,
                    status, calculation_method, total_weight,
                    owner_user_id, created_by_user_id, published_at, revision
                )
                VALUES (
                    :id, :rubric_id, :version_number, :name,
                    'Durable freeze rubric', 'PUBLISHED'::rubric_status,
                    'WEIGHTED_SUM', 100.0, :owner_user_id,
                    :created_by_user_id, :published_at, 1
                )
            """),
            {
                "id": version_id,
                "rubric_id": ids["rubric_id"],
                "version_number": version_number,
                "name": name,
                "owner_user_id": ids["teacher_id"],
                "created_by_user_id": ids["teacher_id"],
                "published_at": now,
            },
        )
    for criterion_id, criterion_version_id, rubric_version_id, code in (
        (
            ids["criterion_1_id"],
            ids["criterion_version_1_id"],
            ids["rubric_version_1_id"],
            "DURABLE_CRITERION_ONE",
        ),
        (
            ids["criterion_2_id"],
            ids["criterion_version_2_id"],
            ids["rubric_version_2_id"],
            "DURABLE_CRITERION_TWO",
        ),
    ):
        await conn.execute(
            text("""
                INSERT INTO criterion_versions (
                    id, criterion_id, rubric_version_id, code, title,
                    description, scope, weight, position, is_enabled,
                    evaluation_method, levels, evaluator_config,
                    evidence_requirements, revision
                )
                VALUES (
                    :id, :criterion_id, :rubric_version_id, :code,
                    'Durable Criterion', 'Criterion before first submission',
                    'SECTION', 100.0, 1, true, 'AI_ASSISTED',
                    CAST(:levels AS jsonb), CAST(:evaluator_config AS jsonb),
                    CAST(:evidence_requirements AS jsonb), 1
                )
            """),
            {
                "id": criterion_version_id,
                "criterion_id": criterion_id,
                "rubric_version_id": rubric_version_id,
                "code": code,
                "levels": json.dumps([{"name": "Proficient", "score": 100}]),
                "evaluator_config": json.dumps({"model": "durable-model"}),
                "evidence_requirements": json.dumps({"required_lines": True}),
            },
        )
    for assignment_id, rubric_version_id, title in (
        (
            ids["assignment_1_id"],
            ids["rubric_version_1_id"],
            "Durable Assignment One",
        ),
        (
            ids["assignment_2_id"],
            ids["rubric_version_2_id"],
            "Durable Assignment Two",
        ),
    ):
        await conn.execute(
            text("""
                INSERT INTO assignments (
                    id, course_id, created_by_teacher_id, rubric_version_id,
                    title, description, due_at, max_submissions, status,
                    published_at, closed_at, revision
                )
                VALUES (
                    :id, :course_id, :created_by_teacher_id,
                    :rubric_version_id, :title, 'Durable freeze assignment',
                    :due_at, 3, 'OPEN'::assignment_status,
                    :published_at, NULL, 1
                )
            """),
            {
                "id": assignment_id,
                "course_id": ids["course_id"],
                "created_by_teacher_id": ids["teacher_id"],
                "rubric_version_id": rubric_version_id,
                "title": title,
                "due_at": due_date,
                "published_at": now,
            },
        )


def _new_durable_freeze_ids() -> dict[str, uuid.UUID]:
    return {
        "teacher_id": uuid.uuid4(),
        "student_id": uuid.uuid4(),
        "course_id": uuid.uuid4(),
        "membership_id": uuid.uuid4(),
        "rubric_id": uuid.uuid4(),
        "rubric_version_1_id": uuid.uuid4(),
        "rubric_version_2_id": uuid.uuid4(),
        "criterion_1_id": uuid.uuid4(),
        "criterion_2_id": uuid.uuid4(),
        "criterion_version_1_id": uuid.uuid4(),
        "criterion_version_2_id": uuid.uuid4(),
        "assignment_1_id": uuid.uuid4(),
        "assignment_2_id": uuid.uuid4(),
        "submission_id": uuid.uuid4(),
    }


async def _run_durable_freeze_case(operation) -> None:
    settings = get_settings()
    engine = create_async_engine(settings.database_url)
    try:
        async with engine.connect() as conn:
            trans = await conn.begin()
            try:
                ids = _new_durable_freeze_ids()
                await _insert_durable_freeze_graph(conn, ids)
                await operation(conn, ids)
            finally:
                await trans.rollback()
    finally:
        await engine.dispose()


async def _insert_durable_submission(conn, ids) -> None:
    await conn.execute(
        text("""
            INSERT INTO submissions (id, assignment_id, student_id)
            VALUES (:id, :assignment_id, :student_id)
        """),
        {
            "id": ids["submission_id"],
            "assignment_id": ids["assignment_1_id"],
            "student_id": ids["student_id"],
        },
    )


async def _run_first_submission_marker_case(conn, ids) -> None:
    initial_markers = await conn.execute(
        text("""
            SELECT first_submission_at
            FROM assignments
            WHERE id IN (:assignment_1_id, :assignment_2_id)
        """),
        {
            "assignment_1_id": ids["assignment_1_id"],
            "assignment_2_id": ids["assignment_2_id"],
        },
    )
    assert all(row[0] is None for row in initial_markers)

    await _insert_durable_submission(conn, ids)
    marker_1 = await conn.scalar(
        text("SELECT first_submission_at FROM assignments WHERE id = :id"),
        {"id": ids["assignment_1_id"]},
    )
    assert marker_1 is not None

    await conn.execute(
        text("""
            UPDATE submissions
            SET assignment_id = :assignment_id
            WHERE id = :id
        """),
        {
            "id": ids["submission_id"],
            "assignment_id": ids["assignment_2_id"],
        },
    )
    marker_2 = await conn.scalar(
        text("SELECT first_submission_at FROM assignments WHERE id = :id"),
        {"id": ids["assignment_2_id"]},
    )
    assert marker_2 is not None

    await conn.execute(
        text("DELETE FROM submissions WHERE id = :id"),
        {"id": ids["submission_id"]},
    )
    assignment_1_after_delete = await conn.scalar(
        text("SELECT first_submission_at FROM assignments WHERE id = :id"),
        {"id": ids["assignment_1_id"]},
    )
    assignment_2_after_delete = await conn.scalar(
        text("SELECT first_submission_at FROM assignments WHERE id = :id"),
        {"id": ids["assignment_2_id"]},
    )
    assert assignment_1_after_delete == marker_1
    assert assignment_2_after_delete == marker_2


async def _run_direct_marker_mutation_case(conn, ids) -> None:
    await _insert_durable_submission(conn, ids)
    for value in (None, datetime.now(UTC)):
        with pytest.raises(
            DBAPIError,
            match=r"assignment submission freeze is immutable",
        ):
            async with conn.begin_nested():
                await conn.execute(
                    text("""
                        UPDATE assignments
                        SET first_submission_at = :value
                        WHERE id = :id
                    """),
                    {"id": ids["assignment_1_id"], "value": value},
                )


async def _run_rubric_freeze_after_delete_case(conn, ids) -> None:
    await _insert_durable_submission(conn, ids)
    await conn.execute(
        text("DELETE FROM submissions WHERE id = :id"),
        {"id": ids["submission_id"]},
    )
    for statement in (
        """
            UPDATE rubric_versions
            SET name = 'Changed after delete'
            WHERE id = :id
        """,
        """
            DELETE FROM rubric_versions
            WHERE id = :id
        """,
    ):
        with pytest.raises(
            DBAPIError,
            match=r"rubric version is immutable after first submission",
        ):
            async with conn.begin_nested():
                await conn.execute(
                    text(statement),
                    {"id": ids["rubric_version_1_id"]},
                )


async def _run_criterion_freeze_after_delete_case(conn, ids) -> None:
    await _insert_durable_submission(conn, ids)
    await conn.execute(
        text("DELETE FROM submissions WHERE id = :id"),
        {"id": ids["submission_id"]},
    )
    for statement in (
        """
            UPDATE criterion_versions
            SET title = 'Changed after delete'
            WHERE id = :id
        """,
        """
            DELETE FROM criterion_versions
            WHERE id = :id
        """,
    ):
        with pytest.raises(
            DBAPIError,
            match=r"criterion version is immutable after first submission",
        ):
            async with conn.begin_nested():
                await conn.execute(
                    text(statement),
                    {"id": ids["criterion_version_1_id"]},
                )




async def _run_criterion_insert_into_frozen_case(conn, ids) -> None:
    await _insert_durable_submission(conn, ids)
    await conn.execute(
        text("DELETE FROM submissions WHERE id = :id"),
        {"id": ids["submission_id"]},
    )
    with pytest.raises(
        DBAPIError,
        match=r"criterion version is immutable after first submission",
    ):
        async with conn.begin_nested():
            await conn.execute(
                text("""
                    INSERT INTO criterion_versions (
                        id, criterion_id, rubric_version_id, code, title,
                        description, scope, weight, position, is_enabled,
                        evaluation_method, levels, evaluator_config,
                        evidence_requirements, revision
                    )
                    VALUES (
                        :id, :criterion_id, :rubric_version_id,
                        'DURABLE_INSERTED_CRITERION', 'Inserted Criterion',
                        'All required criterion fields', 'SECTION', 100.0,
                        2, true, 'AI_ASSISTED',
                        CAST(:levels AS jsonb), CAST(:evaluator_config AS jsonb),
                        CAST(:evidence_requirements AS jsonb), 1
                    )
                """),
                {
                    "id": uuid.uuid4(),
                    "criterion_id": uuid.uuid4(),
                    "rubric_version_id": ids["rubric_version_1_id"],
                    "levels": json.dumps([{"name": "Proficient", "score": 100}]),
                    "evaluator_config": json.dumps({"model": "durable-model"}),
                    "evidence_requirements": json.dumps({"required_lines": True}),
                },
            )


async def _run_criterion_reparent_into_frozen_case(conn, ids) -> None:
    await _insert_durable_submission(conn, ids)
    await conn.execute(
        text("DELETE FROM submissions WHERE id = :id"),
        {"id": ids["submission_id"]},
    )
    for criterion_id, new_rubric_version_id in (
        (ids["criterion_version_2_id"], ids["rubric_version_1_id"]),
        (ids["criterion_version_1_id"], ids["rubric_version_2_id"]),
    ):
        with pytest.raises(
            DBAPIError,
            match=r"criterion version is immutable after first submission",
        ):
            async with conn.begin_nested():
                await conn.execute(
                    text("""
                        UPDATE criterion_versions
                        SET rubric_version_id = :new_rubric_version_id
                        WHERE id = :id
                    """),
                    {
                        "id": criterion_id,
                        "new_rubric_version_id": new_rubric_version_id,
                    },
                )


async def _run_reassignment_freezes_both_assignments_case(conn, ids) -> None:
    await _insert_durable_submission(conn, ids)
    await conn.execute(
        text("""
            UPDATE submissions
            SET assignment_id = :assignment_id
            WHERE id = :id
        """),
        {
            "id": ids["submission_id"],
            "assignment_id": ids["assignment_2_id"],
        },
    )
    await conn.execute(
        text("DELETE FROM submissions WHERE id = :id"),
        {"id": ids["submission_id"]},
    )

    for assignment_id, rubric_version_id in (
        (ids["assignment_1_id"], ids["rubric_version_2_id"]),
        (ids["assignment_2_id"], ids["rubric_version_1_id"]),
    ):
        with pytest.raises(
            DBAPIError,
            match=r"assignment rubric is immutable after first submission",
        ):
            async with conn.begin_nested():
                await conn.execute(
                    text("""
                        UPDATE assignments
                        SET rubric_version_id = :rubric_version_id
                        WHERE id = :assignment_id
                    """),
                    {
                        "assignment_id": assignment_id,
                        "rubric_version_id": rubric_version_id,
                    },
                )


def test_postgresql_sets_durable_submission_markers() -> None:
    asyncio.run(_run_durable_freeze_case(_run_first_submission_marker_case))


def test_postgresql_rejects_direct_assignment_submission_freeze_mutation() -> None:
    asyncio.run(_run_durable_freeze_case(_run_direct_marker_mutation_case))


def test_postgresql_preserves_rubric_freeze_after_submission_delete() -> None:
    asyncio.run(_run_durable_freeze_case(_run_rubric_freeze_after_delete_case))



def test_postgresql_preserves_criterion_freeze_after_submission_delete() -> None:
    asyncio.run(_run_durable_freeze_case(_run_criterion_freeze_after_delete_case))

def test_postgresql_rejects_criterion_insert_into_frozen_rubric() -> None:
    asyncio.run(_run_durable_freeze_case(_run_criterion_insert_into_frozen_case))


def test_postgresql_rejects_criterion_reparent_into_frozen_rubric() -> None:
    asyncio.run(_run_durable_freeze_case(_run_criterion_reparent_into_frozen_case))


def test_postgresql_reassignment_freezes_both_assignments_durably() -> None:
    asyncio.run(_run_durable_freeze_case(_run_reassignment_freezes_both_assignments_case))


async def _wait_for_advisory_wait(
    observer_conn,
    worker_pid,
    task,
    operation: str,
) -> None:
    async def poll() -> None:
        while True:
            if task.done():
                try:
                    task.result()
                except Exception as error:
                    pytest.fail(f"{operation} completed before advisory wait: {error}")
                pytest.fail(f"{operation} completed before advisory wait")

            waiting = await observer_conn.scalar(
                text("""
                    SELECT EXISTS (
                        SELECT 1
                        FROM pg_locks
                        WHERE pid = :pid
                          AND locktype = 'advisory'
                          AND granted = false
                    )
                """),
                {"pid": worker_pid},
            )
            if waiting:
                return
            await asyncio.sleep(0.02)

    try:
        await asyncio.wait_for(poll(), timeout=2.0)
    except TimeoutError:
        pytest.fail(f"timed out waiting for {operation} advisory lock wait")


async def _run_null_role_constraint_test() -> None:
    settings = get_settings()
    engine = create_async_engine(settings.database_url)
    user_id = uuid.uuid4()

    try:
        async with engine.connect() as conn:
            trans = await conn.begin()
            try:
                with pytest.raises(DBAPIError) as error_info:
                    async with conn.begin_nested():
                        await conn.execute(
                            text("""
                                INSERT INTO users (
                                    id, email, display_name, password_hash,
                                    roles, status, revision
                                )
                                VALUES (
                                    :id, :email, 'Null Role User',
                                    'hash_null_role',
                                    ARRAY[NULL]::user_role[],
                                    'ACTIVE'::user_status, 1
                                )
                            """),
                            {
                                "id": user_id,
                                "email": f"null_role_{uuid.uuid4().hex}@example.com",
                            },
                        )
                assert (
                    _constraint_name(
                        error_info.value,
                        "ck_users_roles_not_empty",
                    )
                    == "ck_users_roles_not_empty"
                )
            finally:
                await trans.rollback()
    finally:
        try:
            await _cleanup_domain_rows(engine, user_ids=(user_id,))
        finally:
            await engine.dispose()


def test_postgresql_rejects_null_role_array_member() -> None:
    asyncio.run(_run_null_role_constraint_test())


async def _run_whitespace_reason_constraint_test() -> None:
    settings = get_settings()
    engine = create_async_engine(settings.database_url)
    audit_event_id = uuid.uuid4()

    try:
        async with engine.connect() as conn:
            trans = await conn.begin()
            try:
                with pytest.raises(DBAPIError) as error_info:
                    async with conn.begin_nested():
                        await conn.execute(
                            text("""
                                INSERT INTO audit_events (
                                    id, resource_type, resource_id, action,
                                    actor_type, actor_user_id, before, after,
                                    reason
                                )
                                VALUES (
                                    :id, 'COURSE', :resource_id, 'UPDATE',
                                    'SYSTEM'::audit_actor_type, NULL,
                                    '{"name": "Old"}'::jsonb,
                                    '{"name": "New"}'::jsonb, :reason
                                )
                            """),
                            {
                                "id": audit_event_id,
                                "resource_id": uuid.uuid4(),
                                "reason": "\t\n",
                            },
                        )
                assert (
                    _constraint_name(
                        error_info.value,
                        "ck_audit_events_reason_not_blank",
                    )
                    == "ck_audit_events_reason_not_blank"
                )
            finally:
                await trans.rollback()
    finally:
        try:
            await _cleanup_domain_rows(engine, audit_event_ids=(audit_event_id,))
        finally:
            await engine.dispose()


def test_postgresql_rejects_whitespace_only_audit_reason() -> None:
    asyncio.run(_run_whitespace_reason_constraint_test())


async def _run_whitespace_course_name_constraint_test() -> None:
    settings = get_settings()
    engine = create_async_engine(settings.database_url)
    teacher_id = uuid.uuid4()
    course_id = uuid.uuid4()
    try:
        async with engine.connect() as conn:
            trans = await conn.begin()
            try:
                await conn.execute(
                    text("""
                        INSERT INTO users (
                            id, email, display_name, password_hash,
                            roles, status, revision
                        )
                        VALUES (
                            :id, :email, 'Blank Course Teacher',
                            'hash_blank_course_teacher',
                            ARRAY['TEACHER']::user_role[],
                            'ACTIVE'::user_status, 1
                        )
                    """),
                    {
                        "id": teacher_id,
                        "email": f"blank_course_{uuid.uuid4().hex}@example.com",
                    },
                )
                with pytest.raises(DBAPIError) as error_info:
                    async with conn.begin_nested():
                        await conn.execute(
                            text("""
                                INSERT INTO courses (
                                    id, code, name, term, owner_teacher_id, revision
                                )
                                VALUES (
                                    :id, :code, :name, 'Fall 2026',
                                    :owner_teacher_id, 1
                                )
                            """),
                            {
                                "id": course_id,
                                "code": f"BLANK_{uuid.uuid4().hex}",
                                "name": " \t\n ",
                                "owner_teacher_id": teacher_id,
                            },
                        )
                assert (
                    _constraint_name(
                        error_info.value,
                        "ck_courses_name_not_blank",
                    )
                    == "ck_courses_name_not_blank"
                )
            finally:
                await trans.rollback()
    finally:
        try:
            await _cleanup_domain_rows(
                engine,
                course_ids=(course_id,),
                user_ids=(teacher_id,),
            )
        finally:
            await engine.dispose()


async def _run_whitespace_user_display_name_constraint_test() -> None:
    settings = get_settings()
    engine = create_async_engine(settings.database_url)
    user_id = uuid.uuid4()
    try:
        async with engine.connect() as conn:
            trans = await conn.begin()
            try:
                with pytest.raises(DBAPIError) as error_info:
                    async with conn.begin_nested():
                        await conn.execute(
                            text("""
                                INSERT INTO users (
                                    id, email, display_name, password_hash,
                                    roles, status, revision
                                )
                                VALUES (
                                    :id, :email, :display_name,
                                    'hash_blank_display_name',
                                    ARRAY['STUDENT']::user_role[],
                                    'ACTIVE'::user_status, 1
                                )
                            """),
                            {
                                "id": user_id,
                                "email": f"blank_display_{uuid.uuid4().hex}@example.com",
                                "display_name": "\t\n",
                            },
                        )
                assert (
                    _constraint_name(
                        error_info.value,
                        "ck_users_display_name_not_blank",
                    )
                    == "ck_users_display_name_not_blank"
                )
            finally:
                await trans.rollback()
    finally:
        try:
            await _cleanup_domain_rows(engine, user_ids=(user_id,))
        finally:
            await engine.dispose()


def test_postgresql_rejects_whitespace_only_course_name() -> None:
    asyncio.run(_run_whitespace_course_name_constraint_test())


def test_postgresql_rejects_whitespace_only_user_display_name() -> None:
    asyncio.run(_run_whitespace_user_display_name_constraint_test())


async def _run_role_removal_course_insert_race_test() -> None:
    settings = get_settings()
    engine = create_async_engine(settings.database_url)
    teacher_id = uuid.uuid4()
    course_id = uuid.uuid4()
    conn_a = None
    conn_b = None
    observer_conn = None
    trans_a = None
    trans_b = None
    insert_task = None
    worker_pid_a = None
    worker_pid_b = None

    try:
        async with engine.connect() as setup_conn:
            setup_trans = await setup_conn.begin()
            await setup_conn.execute(
                text("""
                    INSERT INTO users (
                        id, email, display_name, password_hash,
                        roles, status, revision
                    )
                    VALUES (
                        :id, :email, 'Race Teacher', 'hash_race_teacher',
                        ARRAY['TEACHER']::user_role[],
                        'ACTIVE'::user_status, 1
                    )
                """),
                {
                    "id": teacher_id,
                    "email": f"race_teacher_{uuid.uuid4().hex}@example.com",
                },
            )
            await setup_trans.commit()

        conn_a = await engine.connect()
        trans_a = await conn_a.begin()
        worker_pid_a = await conn_a.scalar(text("SELECT pg_backend_pid()"))
        await conn_a.execute(
            text("""
                UPDATE users
                SET roles = ARRAY['STUDENT']::user_role[]
                WHERE id = :id
            """),
            {"id": teacher_id},
        )

        conn_b = await engine.connect()
        trans_b = await conn_b.begin()
        worker_pid_b = await conn_b.scalar(text("SELECT pg_backend_pid()"))
        await conn_b.execute(text("SET LOCAL lock_timeout = '5000ms'"))
        observer_conn = await engine.connect()
        assert worker_pid_a != worker_pid_b

        insert_task = asyncio.create_task(
            conn_b.execute(
                text("""
                    INSERT INTO courses (
                        id, code, name, term, owner_teacher_id, revision
                    )
                    VALUES (
                        :id, :code, 'Concurrent Course', 'Fall 2026',
                        :owner_teacher_id, 1
                    )
                """),
                {
                    "id": course_id,
                    "code": f"RACE_{uuid.uuid4().hex}",
                    "owner_teacher_id": teacher_id,
                },
            )
        )

        await _wait_for_advisory_wait(
            observer_conn,
            worker_pid_b,
            insert_task,
            "course insert",
        )

        await trans_a.commit()
        trans_a = None

        with pytest.raises(
            DBAPIError,
            match=r"course owner must have TEACHER role",
        ):
            await asyncio.wait_for(insert_task, timeout=2.0)
        await trans_b.rollback()
        trans_b = None

        async with engine.connect() as verify_conn:
            course_count = await verify_conn.scalar(
                text("SELECT count(*) FROM courses WHERE id = :id"),
                {"id": course_id},
            )
        assert course_count == 0
    finally:
        try:
            if insert_task is not None and not insert_task.done():
                insert_task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await insert_task
            if trans_a is not None:
                await trans_a.rollback()
            if trans_b is not None:
                await trans_b.rollback()
            if conn_a is not None:
                await conn_a.close()
            if conn_b is not None:
                await conn_b.close()
            if observer_conn is not None:
                await observer_conn.close()
            await _cleanup_domain_rows(
                engine,
                course_ids=(course_id,),
                user_ids=(teacher_id,),
            )
        finally:
            await engine.dispose()


def test_postgresql_serializes_role_removal_and_course_insert() -> None:
    asyncio.run(_run_role_removal_course_insert_race_test())


async def _insert_submission_graph(conn, ids) -> None:
    now = datetime.now(UTC)
    due_date = now + timedelta(days=7)
    await conn.execute(
        text("""
            INSERT INTO users (
                id, email, display_name, password_hash,
                roles, status, revision
            )
            VALUES
                (
                    :teacher_id, :teacher_email, 'Graph Teacher',
                    'hash_graph_teacher',
                    ARRAY['TEACHER']::user_role[],
                    'ACTIVE'::user_status, 1
                ),
                (
                    :student_id, :student_email, 'Graph Student',
                    'hash_graph_student',
                    ARRAY['STUDENT']::user_role[],
                    'ACTIVE'::user_status, 1
                )
        """),
        {
            "teacher_id": ids["teacher_id"],
            "teacher_email": f"graph_teacher_{uuid.uuid4().hex}@example.com",
            "student_id": ids["student_id"],
            "student_email": f"graph_student_{uuid.uuid4().hex}@example.com",
        },
    )
    await conn.execute(
        text("""
            INSERT INTO courses (
                id, code, name, term, owner_teacher_id, revision
            )
            VALUES (
                :id, :code, 'Graph Course', 'Fall 2026',
                :owner_teacher_id, 1
            )
        """),
        {
            "id": ids["course_id"],
            "code": f"GRAPH_{uuid.uuid4().hex}",
            "owner_teacher_id": ids["teacher_id"],
        },
    )
    await conn.execute(
        text("""
            INSERT INTO memberships (
                id, course_id, user_id, role, status
            )
            VALUES (
                :id, :course_id, :user_id,
                'STUDENT'::membership_role,
                'ACTIVE'::membership_status
            )
        """),
        {
            "id": ids["membership_id"],
            "course_id": ids["course_id"],
            "user_id": ids["student_id"],
        },
    )
    await conn.execute(
        text("""
            INSERT INTO rubric_versions (
                id, rubric_id, version_number, name, description,
                status, calculation_method, total_weight,
                owner_user_id, created_by_user_id, published_at, revision
            )
            VALUES (
                :id, :rubric_id, 1, 'Race Rubric', 'Initial race rubric',
                'PUBLISHED'::rubric_status, 'WEIGHTED_SUM', 100.0,
                :owner_user_id, :created_by_user_id, :published_at, 1
            )
        """),
        {
            "id": ids["rubric_version_id"],
            "rubric_id": ids["rubric_id"],
            "owner_user_id": ids["teacher_id"],
            "created_by_user_id": ids["teacher_id"],
            "published_at": now,
        },
    )
    await conn.execute(
        text("""
            INSERT INTO criterion_versions (
                id, criterion_id, rubric_version_id, code, title,
                description, scope, weight, position, is_enabled,
                evaluation_method, levels, evaluator_config,
                evidence_requirements, revision
            )
            VALUES (
                :id, :criterion_id, :rubric_version_id, 'RACE_CRITERION',
                'Race Criterion', 'Criterion for race test', 'SECTION',
                100.0, 1, true, 'AI_ASSISTED',
                CAST(:levels AS jsonb), CAST(:evaluator_config AS jsonb),
                CAST(:evidence_requirements AS jsonb), 1
            )
        """),
        {
            "id": ids["criterion_version_id"],
            "criterion_id": ids["criterion_id"],
            "rubric_version_id": ids["rubric_version_id"],
            "levels": json.dumps([{"name": "Proficient", "score": 100}]),
            "evaluator_config": json.dumps({"model": "race-model"}),
            "evidence_requirements": json.dumps({"required_lines": True}),
        },
    )
    await conn.execute(
        text("""
            INSERT INTO assignments (
                id, course_id, created_by_teacher_id, rubric_version_id,
                title, description, due_at, max_submissions, status,
                published_at, closed_at, revision
            )
            VALUES (
                :id, :course_id, :created_by_teacher_id, :rubric_version_id,
                'Race Assignment', 'Assignment for race test', :due_at, 3,
                'OPEN'::assignment_status, :published_at, NULL, 1
            )
        """),
        {
            "id": ids["assignment_id"],
            "course_id": ids["course_id"],
            "created_by_teacher_id": ids["teacher_id"],
            "rubric_version_id": ids["rubric_version_id"],
            "due_at": due_date,
            "published_at": now,
        },
    )


async def _run_first_submission_rubric_update_race_test() -> None:
    settings = get_settings()
    engine = create_async_engine(settings.database_url)
    ids = {
        "teacher_id": uuid.uuid4(),
        "student_id": uuid.uuid4(),
        "course_id": uuid.uuid4(),
        "membership_id": uuid.uuid4(),
        "rubric_id": uuid.uuid4(),
        "rubric_version_id": uuid.uuid4(),
        "criterion_id": uuid.uuid4(),
        "criterion_version_id": uuid.uuid4(),
        "assignment_id": uuid.uuid4(),
        "submission_id": uuid.uuid4(),
    }
    conn_a = None
    conn_b = None
    observer_conn = None
    trans_a = None
    trans_b = None
    update_task = None
    worker_pid_a = None
    worker_pid_b = None

    try:
        async with engine.connect() as setup_conn:
            setup_trans = await setup_conn.begin()
            await _insert_submission_graph(setup_conn, ids)
            await setup_trans.commit()

        conn_a = await engine.connect()
        trans_a = await conn_a.begin()
        worker_pid_a = await conn_a.scalar(text("SELECT pg_backend_pid()"))
        await conn_a.execute(
            text("""
                INSERT INTO submissions (id, assignment_id, student_id)
                VALUES (:id, :assignment_id, :student_id)
            """),
            {
                "id": ids["submission_id"],
                "assignment_id": ids["assignment_id"],
                "student_id": ids["student_id"],
            },
        )

        conn_b = await engine.connect()
        trans_b = await conn_b.begin()
        worker_pid_b = await conn_b.scalar(text("SELECT pg_backend_pid()"))
        await conn_b.execute(text("SET LOCAL lock_timeout = '5000ms'"))
        observer_conn = await engine.connect()
        assert worker_pid_a != worker_pid_b

        update_task = asyncio.create_task(
            conn_b.execute(
                text("""
                    UPDATE rubric_versions
                    SET name = 'Updated During Race'
                    WHERE id = :id
                """),
                {"id": ids["rubric_version_id"]},
            )
        )

        await _wait_for_advisory_wait(
            observer_conn,
            worker_pid_b,
            update_task,
            "rubric update",
        )

        await trans_a.commit()
        trans_a = None

        with pytest.raises(
            DBAPIError,
            match=r"rubric version is immutable after first submission",
        ):
            await asyncio.wait_for(update_task, timeout=2.0)
        await trans_b.rollback()
        trans_b = None

        async with engine.connect() as verify_conn:
            rubric_name = await verify_conn.scalar(
                text("SELECT name FROM rubric_versions WHERE id = :id"),
                {"id": ids["rubric_version_id"]},
            )
        assert rubric_name == "Race Rubric"
    finally:
        try:
            if update_task is not None and not update_task.done():
                update_task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await update_task
            if trans_a is not None:
                await trans_a.rollback()
            if trans_b is not None:
                await trans_b.rollback()
            if conn_a is not None:
                await conn_a.close()
            if conn_b is not None:
                await conn_b.close()
            if observer_conn is not None:
                await observer_conn.close()
            await _cleanup_domain_rows(
                engine,
                submission_ids=(ids["submission_id"],),
                assignment_ids=(ids["assignment_id"],),
                criterion_version_ids=(ids["criterion_version_id"],),
                rubric_version_ids=(ids["rubric_version_id"],),
                membership_ids=(ids["membership_id"],),
                course_ids=(ids["course_id"],),
                user_ids=(ids["teacher_id"], ids["student_id"]),
            )
        finally:
            await engine.dispose()


def test_postgresql_serializes_first_submission_and_rubric_update() -> None:
    asyncio.run(_run_first_submission_rubric_update_race_test())


async def _insert_rubric_race_prerequisites(conn, ids) -> None:
    now = datetime.now(UTC)
    await conn.execute(
        text("""
            INSERT INTO users (
                id, email, display_name, password_hash,
                roles, status, revision
            )
            VALUES
                (
                    :teacher_id, :teacher_email, 'Scope Race Teacher',
                    'hash_scope_race_teacher',
                    ARRAY['TEACHER']::user_role[],
                    'ACTIVE'::user_status, 1
                ),
                (
                    :student_id, :student_email, 'Scope Race Student',
                    'hash_scope_race_student',
                    ARRAY['STUDENT']::user_role[],
                    'ACTIVE'::user_status, 1
                )
        """),
        {
            "teacher_id": ids["teacher_id"],
            "teacher_email": f"scope_teacher_{uuid.uuid4().hex}@example.com",
            "student_id": ids["student_id"],
            "student_email": f"scope_student_{uuid.uuid4().hex}@example.com",
        },
    )
    await conn.execute(
        text("""
            INSERT INTO courses (
                id, code, name, term, owner_teacher_id, revision
            )
            VALUES (
                :id, :code, 'Scope Race Course', 'Fall 2026',
                :owner_teacher_id, 1
            )
        """),
        {
            "id": ids["course_id"],
            "code": f"SCOPE_{uuid.uuid4().hex}",
            "owner_teacher_id": ids["teacher_id"],
        },
    )
    await conn.execute(
        text("""
            INSERT INTO memberships (
                id, course_id, user_id, role, status
            )
            VALUES (
                :id, :course_id, :user_id,
                'STUDENT'::membership_role,
                'ACTIVE'::membership_status
            )
        """),
        {
            "id": ids["membership_id"],
            "course_id": ids["course_id"],
            "user_id": ids["student_id"],
        },
    )
    await conn.execute(
        text("""
            INSERT INTO rubric_versions (
                id, rubric_id, version_number, name, description,
                status, calculation_method, total_weight,
                owner_user_id, created_by_user_id, published_at, revision
            )
            VALUES (
                :id, :rubric_id, 1, 'Scope Race Rubric',
                'Initial scope race rubric',
                'PUBLISHED'::rubric_status, 'WEIGHTED_SUM', 100.0,
                :owner_user_id, :created_by_user_id, :published_at, 1
            )
        """),
        {
            "id": ids["rubric_version_id"],
            "rubric_id": ids["rubric_id"],
            "owner_user_id": ids["teacher_id"],
            "created_by_user_id": ids["teacher_id"],
            "published_at": now,
        },
    )
    await conn.execute(
        text("""
            INSERT INTO criterion_versions (
                id, criterion_id, rubric_version_id, code, title,
                description, scope, weight, position, is_enabled,
                evaluation_method, levels, evaluator_config,
                evidence_requirements, revision
            )
            VALUES (
                :id, :criterion_id, :rubric_version_id, 'SCOPE_CRITERION',
                'Scope Race Criterion', 'Criterion for scope race test',
                'SECTION', 100.0, 1, true, 'AI_ASSISTED',
                CAST(:levels AS jsonb), CAST(:evaluator_config AS jsonb),
                CAST(:evidence_requirements AS jsonb), 1
            )
        """),
        {
            "id": ids["criterion_version_id"],
            "criterion_id": ids["criterion_id"],
            "rubric_version_id": ids["rubric_version_id"],
            "levels": json.dumps([{"name": "Proficient", "score": 100}]),
            "evaluator_config": json.dumps({"model": "scope-race-model"}),
            "evidence_requirements": json.dumps({"required_lines": True}),
        },
    )


async def _run_new_assignment_rubric_update_race_test() -> None:
    settings = get_settings()
    engine = create_async_engine(settings.database_url)
    ids = {
        "teacher_id": uuid.uuid4(),
        "student_id": uuid.uuid4(),
        "course_id": uuid.uuid4(),
        "membership_id": uuid.uuid4(),
        "rubric_id": uuid.uuid4(),
        "rubric_version_id": uuid.uuid4(),
        "criterion_id": uuid.uuid4(),
        "criterion_version_id": uuid.uuid4(),
        "assignment_id": uuid.uuid4(),
        "submission_id": uuid.uuid4(),
    }
    conn_a = None
    conn_b = None
    observer_conn = None
    trans_a = None
    trans_b = None
    update_task = None
    worker_pid_a = None
    worker_pid_b = None
    now = datetime.now(UTC)
    due_date = now + timedelta(days=7)

    try:
        async with engine.connect() as setup_conn:
            setup_trans = await setup_conn.begin()
            await _insert_rubric_race_prerequisites(setup_conn, ids)
            await setup_trans.commit()

        conn_a = await engine.connect()
        trans_a = await conn_a.begin()
        worker_pid_a = await conn_a.scalar(text("SELECT pg_backend_pid()"))
        await conn_a.execute(
            text("""
                INSERT INTO assignments (
                    id, course_id, created_by_teacher_id, rubric_version_id,
                    title, description, due_at, max_submissions, status,
                    published_at, closed_at, revision
                )
                VALUES (
                    :id, :course_id, :created_by_teacher_id,
                    :rubric_version_id, 'Scope Race Assignment',
                    'Assignment inserted during rubric race', :due_at, 3,
                    'OPEN'::assignment_status, :published_at, NULL, 1
                )
            """),
            {
                "id": ids["assignment_id"],
                "course_id": ids["course_id"],
                "created_by_teacher_id": ids["teacher_id"],
                "rubric_version_id": ids["rubric_version_id"],
                "due_at": due_date,
                "published_at": now,
            },
        )
        await conn_a.execute(
            text("""
                INSERT INTO submissions (id, assignment_id, student_id)
                VALUES (:id, :assignment_id, :student_id)
            """),
            {
                "id": ids["submission_id"],
                "assignment_id": ids["assignment_id"],
                "student_id": ids["student_id"],
            },
        )

        conn_b = await engine.connect()
        trans_b = await conn_b.begin()
        worker_pid_b = await conn_b.scalar(text("SELECT pg_backend_pid()"))
        await conn_b.execute(text("SET LOCAL lock_timeout = '5000ms'"))
        observer_conn = await engine.connect()
        assert worker_pid_a != worker_pid_b

        update_task = asyncio.create_task(
            conn_b.execute(
                text("""
                    UPDATE rubric_versions
                    SET name = 'Updated During New Assignment Race'
                    WHERE id = :id
                """),
                {"id": ids["rubric_version_id"]},
            )
        )

        await _wait_for_advisory_wait(
            observer_conn,
            worker_pid_b,
            update_task,
            "rubric update",
        )

        await trans_a.commit()
        trans_a = None

        with pytest.raises(
            DBAPIError,
            match=r"rubric version is immutable after first submission",
        ):
            await asyncio.wait_for(update_task, timeout=2.0)
        await trans_b.rollback()
        trans_b = None

        async with engine.connect() as verify_conn:
            rubric_name = await verify_conn.scalar(
                text("SELECT name FROM rubric_versions WHERE id = :id"),
                {"id": ids["rubric_version_id"]},
            )
        assert rubric_name == "Scope Race Rubric"
    finally:
        try:
            if update_task is not None and not update_task.done():
                update_task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await update_task
            if trans_a is not None:
                await trans_a.rollback()
            if trans_b is not None:
                await trans_b.rollback()
            if conn_a is not None:
                await conn_a.close()
            if conn_b is not None:
                await conn_b.close()
            if observer_conn is not None:
                await observer_conn.close()
            await _cleanup_domain_rows(
                engine,
                submission_ids=(ids["submission_id"],),
                assignment_ids=(ids["assignment_id"],),
                criterion_version_ids=(ids["criterion_version_id"],),
                rubric_version_ids=(ids["rubric_version_id"],),
                membership_ids=(ids["membership_id"],),
                course_ids=(ids["course_id"],),
                user_ids=(ids["teacher_id"], ids["student_id"]),
            )
        finally:
            await engine.dispose()


def test_postgresql_serializes_new_assignment_and_rubric_update() -> None:
    asyncio.run(_run_new_assignment_rubric_update_race_test())
