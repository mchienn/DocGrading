"""Pure-function tests for RBAC role checks and ownership enforcement.

These tests run without a database — they exercise the logic in
``app.api.deps`` that decides permission/ownership, using plain
SQLAlchemy model instances.
"""

from __future__ import annotations

import uuid

import pytest
from fastapi import HTTPException

from app.api.deps import (
    check_course_ownership,
    check_roles,
    visible_assignment_statuses,
)
from app.models.course import Course
from app.models.enums import AssignmentStatus, UserRole, UserStatus
from app.models.identity import User

# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _make_user(
    *roles: UserRole,
    user_id: uuid.UUID | None = None,
) -> User:
    uid = user_id or uuid.uuid4()
    return User(
        id=uid,
        email=f"{uid.hex[:8]}@test.local",
        display_name="Test User",
        password_hash="$argon2id$placeholder",
        roles=list(roles),
        status=UserStatus.ACTIVE,
    )


def _make_course(owner_id: uuid.UUID) -> Course:
    return Course(
        id=uuid.uuid4(),
        code="CS101",
        name="Test Course",
        term="2026A",
        owner_teacher_id=owner_id,
    )


# ---------------------------------------------------------------------------
# Role checks
# ---------------------------------------------------------------------------


class TestCheckRoles:
    def test_rejects_student_from_admin_only(self) -> None:
        user = _make_user(UserRole.STUDENT)
        with pytest.raises(HTTPException) as exc_info:
            check_roles(user, {UserRole.ADMIN})
        assert exc_info.value.status_code == 403

    def test_rejects_teacher_from_admin_only(self) -> None:
        user = _make_user(UserRole.TEACHER)
        with pytest.raises(HTTPException) as exc_info:
            check_roles(user, {UserRole.ADMIN})
        assert exc_info.value.status_code == 403

    def test_accepts_admin(self) -> None:
        user = _make_user(UserRole.ADMIN)
        check_roles(user, {UserRole.ADMIN})  # no exception

    def test_accepts_teacher_when_teacher_or_admin_required(self) -> None:
        user = _make_user(UserRole.TEACHER)
        check_roles(user, {UserRole.ADMIN, UserRole.TEACHER})

    def test_accepts_multi_role_user(self) -> None:
        user = _make_user(UserRole.TEACHER, UserRole.STUDENT)
        check_roles(user, {UserRole.TEACHER})

    def test_rejects_when_no_role_overlap(self) -> None:
        user = _make_user(UserRole.STUDENT)
        with pytest.raises(HTTPException) as exc_info:
            check_roles(user, {UserRole.ADMIN, UserRole.TEACHER})
        assert exc_info.value.status_code == 403


# ---------------------------------------------------------------------------
# Ownership checks
# ---------------------------------------------------------------------------


class TestCheckCourseOwnership:
    def test_owner_teacher_is_allowed(self) -> None:
        teacher_id = uuid.uuid4()
        user = _make_user(UserRole.TEACHER, user_id=teacher_id)
        course = _make_course(owner_id=teacher_id)
        check_course_ownership(user, course)  # no exception

    def test_non_owner_teacher_is_denied(self) -> None:
        user = _make_user(UserRole.TEACHER)
        course = _make_course(owner_id=uuid.uuid4())
        with pytest.raises(HTTPException) as exc_info:
            check_course_ownership(user, course)
        assert exc_info.value.status_code == 403

    def test_admin_bypasses_ownership(self) -> None:
        user = _make_user(UserRole.ADMIN)
        course = _make_course(owner_id=uuid.uuid4())
        check_course_ownership(user, course)  # no exception

    def test_student_is_denied(self) -> None:
        user = _make_user(UserRole.STUDENT)
        course = _make_course(owner_id=uuid.uuid4())
        with pytest.raises(HTTPException) as exc_info:
            check_course_ownership(user, course)
        assert exc_info.value.status_code == 403


# ---------------------------------------------------------------------------
# Student visibility filter
# ---------------------------------------------------------------------------


class TestVisibleAssignmentStatuses:
    def test_student_sees_only_open_and_closed(self) -> None:
        user = _make_user(UserRole.STUDENT)
        statuses = visible_assignment_statuses(user)
        assert statuses is not None
        assert set(statuses) == {
            AssignmentStatus.OPEN,
            AssignmentStatus.CLOSED,
        }

    def test_teacher_sees_all(self) -> None:
        user = _make_user(UserRole.TEACHER)
        assert visible_assignment_statuses(user) is None

    def test_admin_sees_all(self) -> None:
        user = _make_user(UserRole.ADMIN)
        assert visible_assignment_statuses(user) is None

    def test_student_cannot_see_draft(self) -> None:
        user = _make_user(UserRole.STUDENT)
        statuses = visible_assignment_statuses(user)
        assert statuses is not None
        assert AssignmentStatus.DRAFT not in statuses
        assert AssignmentStatus.ARCHIVED not in statuses
