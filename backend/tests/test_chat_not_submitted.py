from __future__ import annotations

import asyncio
import os
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.pool import NullPool

from app.core.config import get_settings
from app.models.enums import UserRole
from app.services.chat import (
    NOT_SUBMITTED_NAME_LIMIT,
    Intent,
    MissingSubmissions,
    format_not_submitted,
    handle_chat,
)
from tests.test_t011_review_workspace import _actor, _ids, _seed_graph


def test_format_lists_missing_students_per_assignment() -> None:
    reply = format_not_submitted(
        "CNPM",
        3,
        [
            MissingSubmissions("SRS", False, ["An (an@x)", "Bình (binh@x)"]),
            MissingSubmissions("Khởi động", True, []),
        ],
    )
    assert reply.splitlines() == [
        'Lớp "CNPM" (3 sinh viên đang hoạt động):',
        '• Bài tập "SRS": 2/3 sinh viên chưa nộp:',
        "   - An (an@x)",
        "   - Bình (binh@x)",
        '• Bài tập "Khởi động" (đã đóng): tất cả sinh viên đã nộp.',
    ]


def test_format_truncates_long_rosters() -> None:
    names = [f"SV {i}" for i in range(NOT_SUBMITTED_NAME_LIMIT + 5)]
    reply = format_not_submitted(
        "L", len(names), [MissingSubmissions("A", False, names)]
    )
    assert f"   - SV {NOT_SUBMITTED_NAME_LIMIT - 1}" in reply
    assert f"   - SV {NOT_SUBMITTED_NAME_LIMIT}" not in reply
    assert reply.endswith("… và 5 sinh viên khác.")


def test_format_without_assignments() -> None:
    assert format_not_submitted("L", 10, []) == 'Lớp "L" chưa có bài tập nào được giao.'


@pytest.mark.skipif(
    os.environ.get("RUN_DATABASE_TESTS") != "1",
    reason="Database integration tests require RUN_DATABASE_TESTS=1",
)
def test_not_submitted_lists_students_without_choosing_assignment() -> None:
    async def scenario() -> None:
        engine = create_async_engine(get_settings().database_url, poolclass=NullPool)
        connection = await engine.connect()
        transaction = await connection.begin()
        session = AsyncSession(bind=connection, expire_on_commit=False)
        try:
            ids = _ids()
            await _seed_graph(connection, ids)
            late_student = uuid.uuid4()
            await connection.execute(
                text("""
                    INSERT INTO public.users (
                        id, email, display_name, password_hash, roles, status, revision
                    ) VALUES (
                        :id, :email, 'Late Student', 'hash',
                        ARRAY['STUDENT']::public.user_role[],
                        'ACTIVE'::public.user_status, 1
                    )
                """),
                {"id": late_student, "email": f"{late_student}@test.local"},
            )
            await connection.execute(
                text("""
                    INSERT INTO public.memberships (
                        id, course_id, user_id, role, status
                    )
                    VALUES (
                        :id, :course, :user, 'STUDENT'::public.membership_role,
                        'ACTIVE'::public.membership_status
                    )
                """),
                {"id": uuid.uuid4(), "course": ids["course"], "user": late_student},
            )
            # Drafts are not visible to students, so they must not be listed.
            await connection.execute(
                text("""
                    INSERT INTO public.assignments (
                        id, course_id, created_by_teacher_id, rubric_version_id,
                        title, due_at, max_submissions, status, revision
                    ) VALUES (
                        :id, :course, :teacher, :rubric, 'Draft Assignment',
                        :due_at, 3, 'DRAFT'::public.assignment_status, 1
                    )
                """),
                {
                    "id": uuid.uuid4(),
                    "course": ids["course"],
                    "teacher": ids["teacher"],
                    "rubric": ids["rubric"],
                    "due_at": datetime.now(UTC) + timedelta(days=3),
                },
            )

            teacher = _actor(ids["teacher"], "Teacher A", UserRole.TEACHER)
            response = await handle_chat(
                session,
                user=teacher,
                message="Còn bao nhiêu sinh viên chưa nộp?",
                course_id=ids["course"],
                assignment_id=None,
            )
            assert response.intent == Intent.NOT_SUBMITTED
            assert response.needs_clarification is None
            assert '• Bài tập "Review Assignment": 1/4 sinh viên chưa nộp:' in (
                response.reply
            )
            assert f"   - Late Student ({late_student}@test.local)" in response.reply
            assert "Draft Assignment" not in response.reply
            assert "Student 1" not in response.reply
        finally:
            await session.close()
            await transaction.rollback()
            await connection.close()
            await engine.dispose()

    asyncio.run(scenario())
