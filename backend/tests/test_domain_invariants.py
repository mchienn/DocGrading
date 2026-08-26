import asyncio
from datetime import datetime, timedelta, timezone
import json
import os
import uuid

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

                now = datetime.now(timezone.utc)
                due_date = now + timedelta(days=7)

                # Insert valid TEACHER user
                await conn.execute(
                    text("""
                        INSERT INTO users (id, email, display_name, password_hash, roles, status, revision)
                        VALUES (:id, :email, :display_name, :password_hash, ARRAY['TEACHER']::user_role[], 'ACTIVE'::user_status, 1)
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
                        INSERT INTO users (id, email, display_name, password_hash, roles, status, revision)
                        VALUES (:id, :email, :display_name, :password_hash, ARRAY['STUDENT']::user_role[], 'ACTIVE'::user_status, 1)
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
                        INSERT INTO users (id, email, display_name, password_hash, roles, status, revision)
                        VALUES (:id, :email, :display_name, :password_hash, ARRAY['STUDENT']::user_role[], 'ACTIVE'::user_status, 1)
                    """),
                    {
                        "id": unenrolled_student_id,
                        "email": f"unenrolled_{uuid.uuid4().hex[:8]}@example.com",
                        "display_name": "Unenrolled Student User",
                        "password_hash": "hash_unenrolled_secret",
                    },
                )

                # 2. Reject Course owned by non-Teacher
                with pytest.raises(DBAPIError, match=r"course owner must have TEACHER role"):
                    async with conn.begin_nested():
                        await conn.execute(
                            text("""
                                INSERT INTO courses (id, code, name, term, owner_teacher_id, revision)
                                VALUES (:id, :code, :name, :term, :owner_teacher_id, 1)
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
                        INSERT INTO courses (id, code, name, term, owner_teacher_id, revision)
                        VALUES (:id, :code, :name, :term, :owner_teacher_id, 1)
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
                with pytest.raises(DBAPIError, match=r"membership role must be present in user roles"):
                    async with conn.begin_nested():
                        await conn.execute(
                            text("""
                                INSERT INTO memberships (id, course_id, user_id, role, status)
                                VALUES (:id, :course_id, :user_id, 'TEACHER'::membership_role, 'ACTIVE'::membership_status)
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
                        INSERT INTO memberships (id, course_id, user_id, role, status)
                        VALUES (:id, :course_id, :user_id, 'STUDENT'::membership_role, 'ACTIVE'::membership_status)
                    """),
                    {
                        "id": membership_id,
                        "course_id": course_id,
                        "user_id": student_id,
                    },
                )

                # 4. Reject removal of a User role still used by Course ownership or Membership
                with pytest.raises(DBAPIError, match=r"cannot remove role used by course or membership"):
                    async with conn.begin_nested():
                        await conn.execute(
                            text("""
                                UPDATE users
                                SET roles = ARRAY['STUDENT']::user_role[]
                                WHERE id = :id
                            """),
                            {"id": teacher_id},
                        )

                with pytest.raises(DBAPIError, match=r"cannot remove role used by course or membership"):
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
                            id, rubric_id, version_number, name, description, status,
                            calculation_method, total_weight, owner_user_id, created_by_user_id,
                            published_at, revision
                        )
                        VALUES (
                            :id, :rubric_id, :version_number, :name, :description, 'PUBLISHED'::rubric_status,
                            :calculation_method, :total_weight, :owner_user_id, :created_by_user_id,
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
                            id, rubric_id, version_number, name, description, status,
                            calculation_method, total_weight, owner_user_id, created_by_user_id,
                            published_at, revision
                        )
                        VALUES (
                            :id, :rubric_id, :version_number, :name, :description, 'PUBLISHED'::rubric_status,
                            :calculation_method, :total_weight, :owner_user_id, :created_by_user_id,
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
                            id, criterion_id, rubric_version_id, code, title, description,
                            scope, weight, position, is_enabled, evaluation_method,
                            levels, evaluator_config, evidence_requirements, revision
                        )
                        VALUES (
                            :id, :criterion_id, :rubric_version_id, :code, :title, :description,
                            :scope, :weight, :position, :is_enabled, :evaluation_method,
                            CAST(:levels AS jsonb), CAST(:evaluator_config AS jsonb), CAST(:evidence_requirements AS jsonb), 1
                        )
                    """),
                    {
                        "id": criterion_version_1_id,
                        "criterion_id": criterion_id,
                        "rubric_version_id": rubric_version_1_id,
                        "code": "CRIT_CODE_QUALITY",
                        "title": "Code Quality and Design",
                        "description": "Evaluates clarity, architecture, and maintainability",
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
                            :id, :course_id, :created_by_teacher_id, :rubric_version_id,
                            :title, :description, :due_at, 3, 'OPEN'::assignment_status,
                            :published_at, NULL, 1
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

                # 5. Reject Submission by Student without ACTIVE Student Membership in Assignment's Course
                with pytest.raises(DBAPIError, match=r"student must have active course membership"):
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

                # 6. After valid Submission, reject UPDATE/DELETE of rubric version and criterion, and assignment rubric change
                with pytest.raises(DBAPIError, match=r"rubric version is immutable after first submission"):
                    async with conn.begin_nested():
                        await conn.execute(
                            text("""
                                UPDATE rubric_versions
                                SET name = 'Modified Rubric Name'
                                WHERE id = :id
                            """),
                            {"id": rubric_version_1_id},
                        )

                with pytest.raises(DBAPIError, match=r"rubric version is immutable after first submission"):
                    async with conn.begin_nested():
                        await conn.execute(
                            text("""
                                DELETE FROM rubric_versions
                                WHERE id = :id
                            """),
                            {"id": rubric_version_1_id},
                        )

                with pytest.raises(DBAPIError, match=r"criterion version is immutable after first submission"):
                    async with conn.begin_nested():
                        await conn.execute(
                            text("""
                                UPDATE criterion_versions
                                SET title = 'Modified Criterion Title'
                                WHERE id = :id
                            """),
                            {"id": criterion_version_1_id},
                        )

                with pytest.raises(DBAPIError, match=r"criterion version is immutable after first submission"):
                    async with conn.begin_nested():
                        await conn.execute(
                            text("""
                                DELETE FROM criterion_versions
                                WHERE id = :id
                            """),
                            {"id": criterion_version_1_id},
                        )

                with pytest.raises(DBAPIError, match=r"assignment rubric is immutable after first submission"):
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

                # 7. Audit actor constraint rejects USER/null actor and SYSTEM/non-null actor
                with pytest.raises(DBAPIError, match=r"ck_audit_events_actor"):
                    async with conn.begin_nested():
                        await conn.execute(
                            text("""
                                INSERT INTO audit_events (
                                    id, resource_type, resource_id, action, actor_type,
                                    actor_user_id, before, after, reason
                                )
                                VALUES (
                                    :id, 'COURSE', :resource_id, 'UPDATE', 'USER'::audit_actor_type,
                                    NULL, '{"name": "Old"}'::jsonb, '{"name": "New"}'::jsonb, 'Update course'
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
                                    id, resource_type, resource_id, action, actor_type,
                                    actor_user_id, before, after, reason
                                )
                                VALUES (
                                    :id, 'COURSE', :resource_id, 'UPDATE', 'SYSTEM'::audit_actor_type,
                                    :actor_user_id, '{"name": "Old"}'::jsonb, '{"name": "New"}'::jsonb, 'System auto-update'
                                )
                            """),
                            {
                                "id": uuid.uuid4(),
                                "resource_id": course_id,
                                "actor_user_id": teacher_id,
                            },
                        )

                # 8. Insert valid SYSTEM AuditEvent with before/after object and nonblank reason
                await conn.execute(
                    text("""
                        INSERT INTO audit_events (
                            id, resource_type, resource_id, action, actor_type,
                            actor_user_id, before, after, reason
                        )
                        VALUES (
                            :id, 'ASSIGNMENT', :resource_id, 'PUBLISH', 'SYSTEM'::audit_actor_type,
                            NULL, '{"status": "DRAFT"}'::jsonb, '{"status": "OPEN"}'::jsonb, 'Automated scheduler publish'
                        )
                    """),
                    {
                        "id": audit_event_id,
                        "resource_id": assignment_id,
                    },
                )

                # Reject UPDATE and DELETE on audit events (append-only)
                with pytest.raises(DBAPIError, match=r"audit events are append-only"):
                    async with conn.begin_nested():
                        await conn.execute(
                            text("""
                                UPDATE audit_events
                                SET reason = 'Tampered reason'
                                WHERE id = :id
                            """),
                            {"id": audit_event_id},
                        )

                with pytest.raises(DBAPIError, match=r"audit events are append-only"):
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
