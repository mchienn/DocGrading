"""Pure-function / mock-based tests for T-008 services and API logic.

Tests cover:
- Rubric publish blocked when total_weight != 100
- Edit published rubric blocked (409)
- Ownership deny (teacher B can't touch teacher A's course)
- Student can't see DRAFT assignments
- Assignment publish/close lifecycle
- Role checks

Follows project convention: sync test functions wrapping asyncio.run().
"""

from __future__ import annotations

import asyncio
import uuid
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException

from app.api.deps import (
    check_course_ownership,
    check_roles,
    visible_assignment_statuses,
)
from app.models.assignment import Assignment
from app.models.course import Course, Membership
from app.models.enums import (
    AssignmentStatus,
    RubricStatus,
    UserRole,
    UserStatus,
)
from app.models.identity import User
from app.models.rubric import CriterionVersion, RubricVersion
from app.services.rubric import _check_rubric_ownership

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_user(
    role: UserRole = UserRole.TEACHER,
    user_id: uuid.UUID | None = None,
) -> User:
    uid = user_id or uuid.uuid4()
    return User(
        id=uid,
        email=f"{uid.hex[:8]}@test.local",
        display_name="Test User",
        password_hash="$argon2id$placeholder",
        roles=[role],
        status=UserStatus.ACTIVE,
    )


def _make_course(owner_id: uuid.UUID) -> Course:
    return Course(
        id=uuid.uuid4(),
        code=f"CS{uuid.uuid4().hex[:4]}",
        name="Test Course",
        term="2026A",
        owner_teacher_id=owner_id,
    )


def _make_rubric_version(
    *,
    status: RubricStatus = RubricStatus.DRAFT,
    owner_user_id: uuid.UUID | None = None,
) -> RubricVersion:
    uid = owner_user_id or uuid.uuid4()
    return RubricVersion(
        id=uuid.uuid4(),
        rubric_id=uuid.uuid4(),
        version_number=1,
        name="Test Rubric",
        status=status,
        calculation_method="WEIGHTED_SUM",
        total_weight=Decimal("0.00"),
        owner_user_id=uid,
        created_by_user_id=uid,
        revision=1,
    )


def _make_criterion_version(
    rubric_version_id: uuid.UUID,
    *,
    weight: Decimal = Decimal("50.00"),
    is_enabled: bool = True,
    position: int = 1,
    code: str = "C1",
) -> CriterionVersion:
    return CriterionVersion(
        id=uuid.uuid4(),
        criterion_id=uuid.uuid4(),
        rubric_version_id=rubric_version_id,
        code=code,
        title="Test Criterion",
        description="Test description",
        weight=weight,
        position=position,
        is_enabled=is_enabled,
        evaluation_method="AI",
        levels=[],
        evaluator_config={},
        evidence_requirements={},
        revision=1,
    )


def _make_assignment(
    course_id: uuid.UUID,
    rubric_version_id: uuid.UUID,
    teacher_id: uuid.UUID,
    *,
    status: AssignmentStatus = AssignmentStatus.DRAFT,
) -> Assignment:
    from datetime import UTC, datetime, timedelta

    return Assignment(
        id=uuid.uuid4(),
        course_id=course_id,
        created_by_teacher_id=teacher_id,
        rubric_version_id=rubric_version_id,
        title="Test Assignment",
        due_at=datetime.now(UTC) + timedelta(days=7),
        max_submissions=3,
        status=status,
        revision=1,
    )


def _mock_db(**overrides: object) -> AsyncMock:
    db = AsyncMock()
    db.flush = AsyncMock()
    db.add = MagicMock()
    for k, v in overrides.items():
        setattr(db, k, v)
    return db


# ---------------------------------------------------------------------------
# SC-4: Rubric publish blocks when total_weight != 100
# ---------------------------------------------------------------------------


class TestRubricPublishValidation:
    """Tests for rubric service publish validation."""

    def test_publish_blocked_when_weight_not_100(self) -> None:
        """Publish should fail when enabled criteria don't sum to 100."""

        async def _run() -> None:
            from app.services.rubric import publish_rubric_version

            rv = _make_rubric_version()
            cv = _make_criterion_version(rv.id, weight=Decimal("60.00"))

            mock_result = MagicMock()
            mock_result.scalars.return_value.all.return_value = [cv]
            db = _mock_db(execute=AsyncMock(return_value=mock_result))

            with pytest.raises(HTTPException) as exc_info:
                await publish_rubric_version(db, rv, actor_user_id=uuid.uuid4())
            assert exc_info.value.status_code == 422
            assert "100.00" in exc_info.value.detail

        asyncio.run(_run())

    def test_publish_succeeds_when_weight_is_100(self) -> None:
        """Publish should succeed when enabled criteria sum to 100."""

        async def _run() -> None:
            from app.services.rubric import publish_rubric_version

            rv = _make_rubric_version()
            cv1 = _make_criterion_version(
                rv.id, weight=Decimal("60.00"), position=1, code="C1"
            )
            cv2 = _make_criterion_version(
                rv.id, weight=Decimal("40.00"), position=2, code="C2"
            )

            mock_result = MagicMock()
            mock_result.scalars.return_value.all.return_value = [cv1, cv2]
            db = _mock_db(execute=AsyncMock(return_value=mock_result))

            result = await publish_rubric_version(db, rv, actor_user_id=uuid.uuid4())
            assert result.status == RubricStatus.PUBLISHED
            assert result.published_at is not None
            assert result.total_weight == Decimal("100.00")

        asyncio.run(_run())

    def test_publish_already_published_blocked(self) -> None:
        """Can't publish an already-published rubric."""

        async def _run() -> None:
            from app.services.rubric import publish_rubric_version

            rv = _make_rubric_version(status=RubricStatus.PUBLISHED)
            db = _mock_db()

            with pytest.raises(HTTPException) as exc_info:
                await publish_rubric_version(db, rv, actor_user_id=uuid.uuid4())
            assert exc_info.value.status_code == 409

        asyncio.run(_run())


# ---------------------------------------------------------------------------
# Edit published rubric is blocked (409)
# ---------------------------------------------------------------------------


class TestRubricImmutability:
    """Published rubrics cannot be edited."""

    def test_update_published_rubric_blocked(self) -> None:
        """Updating a PUBLISHED rubric version must raise 409."""

        async def _run() -> None:
            from app.services.rubric import update_rubric_version

            rv = _make_rubric_version(status=RubricStatus.PUBLISHED)
            db = _mock_db()

            with pytest.raises(HTTPException) as exc_info:
                await update_rubric_version(
                    db, rv, actor_user_id=uuid.uuid4(), name="New Name"
                )
            assert exc_info.value.status_code == 409
            assert "immutable" in exc_info.value.detail.lower()

        asyncio.run(_run())

    def test_add_criterion_to_published_rubric_blocked(self) -> None:
        """Adding a criterion to a PUBLISHED rubric version must raise 409."""

        async def _run() -> None:
            from app.services.rubric import add_criterion

            rv = _make_rubric_version(status=RubricStatus.PUBLISHED)
            db = _mock_db()

            with pytest.raises(HTTPException) as exc_info:
                await add_criterion(
                    db,
                    rv,
                    actor_user_id=uuid.uuid4(),
                    code="C1",
                    title="Title",
                    description="Desc",
                    weight=Decimal("50.00"),
                    position=1,
                )
            assert exc_info.value.status_code == 409

        asyncio.run(_run())

    def test_update_criterion_on_published_rubric_blocked(self) -> None:
        """Updating a criterion on a PUBLISHED rubric must raise 409."""

        async def _run() -> None:
            from app.services.rubric import update_criterion

            rv = _make_rubric_version(status=RubricStatus.PUBLISHED)
            cv = _make_criterion_version(rv.id)
            db = _mock_db()

            with pytest.raises(HTTPException) as exc_info:
                await update_criterion(
                    db, rv, cv, actor_user_id=uuid.uuid4(), title="New"
                )
            assert exc_info.value.status_code == 409

        asyncio.run(_run())

    def test_delete_criterion_on_published_rubric_blocked(self) -> None:
        """Deleting a criterion from a PUBLISHED rubric must raise 409."""

        async def _run() -> None:
            from app.services.rubric import delete_criterion

            rv = _make_rubric_version(status=RubricStatus.PUBLISHED)
            cv = _make_criterion_version(rv.id)
            db = _mock_db()

            with pytest.raises(HTTPException) as exc_info:
                await delete_criterion(db, rv, cv, actor_user_id=uuid.uuid4())
            assert exc_info.value.status_code == 409

        asyncio.run(_run())


# ---------------------------------------------------------------------------
# Ownership deny
# ---------------------------------------------------------------------------


class TestOwnershipDeny:
    """Teacher B cannot manage Teacher A's course."""

    def test_other_teacher_denied_course_access(self) -> None:
        teacher_a = _make_user(UserRole.TEACHER)
        teacher_b = _make_user(UserRole.TEACHER)
        course = _make_course(teacher_a.id)

        with pytest.raises(HTTPException) as exc_info:
            check_course_ownership(teacher_b, course)
        assert exc_info.value.status_code == 403

    def test_admin_can_access_any_course(self) -> None:
        admin = _make_user(UserRole.ADMIN)
        teacher_a = _make_user(UserRole.TEACHER)
        course = _make_course(teacher_a.id)

        # Should not raise
        check_course_ownership(admin, course)

    def test_owner_teacher_can_access_own_course(self) -> None:
        teacher = _make_user(UserRole.TEACHER)
        course = _make_course(teacher.id)

        # Should not raise
        check_course_ownership(teacher, course)

    def test_rubric_ownership_check(self) -> None:
        """Non-owner teacher denied from rubric."""
        teacher_a = _make_user(UserRole.TEACHER)
        teacher_b = _make_user(UserRole.TEACHER)

        rv = _make_rubric_version(owner_user_id=teacher_a.id)

        with pytest.raises(HTTPException) as exc_info:
            _check_rubric_ownership(rv, teacher_b.id, [UserRole.TEACHER.value])
        assert exc_info.value.status_code == 403

    def test_admin_bypasses_rubric_ownership(self) -> None:
        """Admin can access any rubric."""
        teacher = _make_user(UserRole.TEACHER)

        rv = _make_rubric_version(owner_user_id=teacher.id)

        # Should not raise
        _check_rubric_ownership(rv, uuid.uuid4(), [UserRole.ADMIN.value])


# ---------------------------------------------------------------------------
# Student visibility: DRAFT assignments hidden
# ---------------------------------------------------------------------------


class TestStudentVisibility:
    """Students should not see DRAFT or ARCHIVED assignments."""

    def test_student_sees_only_open_and_closed(self) -> None:
        student = _make_user(UserRole.STUDENT)
        statuses = visible_assignment_statuses(student)
        assert statuses is not None
        assert AssignmentStatus.OPEN in statuses
        assert AssignmentStatus.CLOSED in statuses
        assert AssignmentStatus.DRAFT not in statuses
        assert AssignmentStatus.ARCHIVED not in statuses

    def test_teacher_sees_all(self) -> None:
        teacher = _make_user(UserRole.TEACHER)
        statuses = visible_assignment_statuses(teacher)
        assert statuses is None  # unrestricted

    def test_admin_sees_all(self) -> None:
        admin = _make_user(UserRole.ADMIN)
        statuses = visible_assignment_statuses(admin)
        assert statuses is None


# ---------------------------------------------------------------------------
# Assignment lifecycle
# ---------------------------------------------------------------------------


class TestAssignmentLifecycle:
    """Assignment publish and close flow."""

    def test_publish_draft_assignment(self) -> None:
        """DRAFT assignment can be published when rubric is PUBLISHED."""

        async def _run() -> None:
            from app.services.assignment import publish_assignment

            teacher = _make_user(UserRole.TEACHER)
            rv = _make_rubric_version(
                status=RubricStatus.PUBLISHED, owner_user_id=teacher.id
            )
            assignment = _make_assignment(uuid.uuid4(), rv.id, teacher.id)

            db = _mock_db(get=AsyncMock(return_value=rv))

            result = await publish_assignment(db, assignment, actor_user_id=teacher.id)
            assert result.status == AssignmentStatus.OPEN
            assert result.published_at is not None

        asyncio.run(_run())

    def test_publish_fails_when_rubric_not_published(self) -> None:
        """Can't publish assignment if rubric is still DRAFT."""

        async def _run() -> None:
            from app.services.assignment import publish_assignment

            teacher = _make_user(UserRole.TEACHER)
            rv = _make_rubric_version(owner_user_id=teacher.id)
            assignment = _make_assignment(uuid.uuid4(), rv.id, teacher.id)

            db = _mock_db(get=AsyncMock(return_value=rv))

            with pytest.raises(HTTPException) as exc_info:
                await publish_assignment(db, assignment, actor_user_id=teacher.id)
            assert exc_info.value.status_code == 422

        asyncio.run(_run())

    def test_edit_non_draft_assignment_blocked(self) -> None:
        """Editing a non-DRAFT assignment must raise 409."""

        async def _run() -> None:
            from app.services.assignment import update_assignment

            teacher = _make_user(UserRole.TEACHER)
            rv = _make_rubric_version(
                status=RubricStatus.PUBLISHED, owner_user_id=teacher.id
            )
            assignment = _make_assignment(
                uuid.uuid4(), rv.id, teacher.id, status=AssignmentStatus.OPEN
            )

            db = _mock_db()

            with pytest.raises(HTTPException) as exc_info:
                await update_assignment(
                    db, assignment, actor_user_id=teacher.id, title="New"
                )
            assert exc_info.value.status_code == 409

        asyncio.run(_run())

    def test_close_open_assignment(self) -> None:
        """OPEN assignment can be closed."""

        async def _run() -> None:
            from app.services.assignment import close_assignment

            teacher = _make_user(UserRole.TEACHER)
            rv = _make_rubric_version(
                status=RubricStatus.PUBLISHED, owner_user_id=teacher.id
            )
            assignment = _make_assignment(
                uuid.uuid4(), rv.id, teacher.id, status=AssignmentStatus.OPEN
            )

            db = _mock_db()

            result = await close_assignment(db, assignment, actor_user_id=teacher.id)
            assert result.status == AssignmentStatus.CLOSED
            assert result.closed_at is not None

        asyncio.run(_run())

    def test_close_draft_assignment_blocked(self) -> None:
        """Can't close a DRAFT assignment."""

        async def _run() -> None:
            from app.services.assignment import close_assignment

            teacher = _make_user(UserRole.TEACHER)
            rv = _make_rubric_version(owner_user_id=teacher.id)
            assignment = _make_assignment(uuid.uuid4(), rv.id, teacher.id)

            db = _mock_db()

            with pytest.raises(HTTPException) as exc_info:
                await close_assignment(db, assignment, actor_user_id=teacher.id)
            assert exc_info.value.status_code == 409

        asyncio.run(_run())


# ---------------------------------------------------------------------------
# Role checks
# ---------------------------------------------------------------------------


class TestRoleChecks:
    """RBAC role validation."""

    def test_student_rejected_from_teacher_endpoint(self) -> None:
        student = _make_user(UserRole.STUDENT)
        with pytest.raises(HTTPException) as exc_info:
            check_roles(student, {UserRole.TEACHER, UserRole.ADMIN})
        assert exc_info.value.status_code == 403

    def test_teacher_accepted_for_teacher_endpoint(self) -> None:
        teacher = _make_user(UserRole.TEACHER)
        check_roles(teacher, {UserRole.TEACHER, UserRole.ADMIN})

    def test_admin_accepted_for_teacher_endpoint(self) -> None:
        admin = _make_user(UserRole.ADMIN)
        check_roles(admin, {UserRole.TEACHER, UserRole.ADMIN})


# ---------------------------------------------------------------------------
# ARCHIVED assignment status branches
# ---------------------------------------------------------------------------


class TestArchivedAssignmentBranches:
    """ARCHIVED assignments are locked: no edit, publish, or close."""

    def test_edit_archived_assignment_blocked(self) -> None:
        """Editing an ARCHIVED assignment must raise 409."""

        async def _run() -> None:
            from app.services.assignment import update_assignment

            teacher = _make_user(UserRole.TEACHER)
            rv = _make_rubric_version(
                status=RubricStatus.PUBLISHED, owner_user_id=teacher.id
            )
            assignment = _make_assignment(
                uuid.uuid4(), rv.id, teacher.id, status=AssignmentStatus.ARCHIVED
            )
            db = _mock_db()

            with pytest.raises(HTTPException) as exc_info:
                await update_assignment(
                    db, assignment, actor_user_id=teacher.id, title="New"
                )
            assert exc_info.value.status_code == 409

        asyncio.run(_run())

    def test_publish_archived_assignment_blocked(self) -> None:
        """Publishing an ARCHIVED assignment must raise 409."""

        async def _run() -> None:
            from app.services.assignment import publish_assignment

            teacher = _make_user(UserRole.TEACHER)
            assignment = _make_assignment(
                uuid.uuid4(),
                uuid.uuid4(),
                teacher.id,
                status=AssignmentStatus.ARCHIVED,
            )
            db = _mock_db()

            with pytest.raises(HTTPException) as exc_info:
                await publish_assignment(db, assignment, actor_user_id=teacher.id)
            assert exc_info.value.status_code == 409

        asyncio.run(_run())

    def test_close_archived_assignment_blocked(self) -> None:
        """Closing an ARCHIVED assignment must raise 409."""

        async def _run() -> None:
            from app.services.assignment import close_assignment

            teacher = _make_user(UserRole.TEACHER)
            assignment = _make_assignment(
                uuid.uuid4(),
                uuid.uuid4(),
                teacher.id,
                status=AssignmentStatus.ARCHIVED,
            )
            db = _mock_db()

            with pytest.raises(HTTPException) as exc_info:
                await close_assignment(db, assignment, actor_user_id=teacher.id)
            assert exc_info.value.status_code == 409

        asyncio.run(_run())


# ---------------------------------------------------------------------------
# ARCHIVED rubric status branches
# ---------------------------------------------------------------------------


class TestArchivedRubricBranches:
    """ARCHIVED rubrics are locked for edits and publish."""

    def test_publish_archived_rubric_blocked(self) -> None:
        """Publishing an ARCHIVED rubric must raise 409."""

        async def _run() -> None:
            from app.services.rubric import publish_rubric_version

            rv = _make_rubric_version(status=RubricStatus.ARCHIVED)
            db = _mock_db()

            with pytest.raises(HTTPException) as exc_info:
                await publish_rubric_version(db, rv, actor_user_id=uuid.uuid4())
            assert exc_info.value.status_code == 409

        asyncio.run(_run())

    def test_update_archived_rubric_blocked(self) -> None:
        """Updating an ARCHIVED rubric must raise 409."""

        async def _run() -> None:
            from app.services.rubric import update_rubric_version

            rv = _make_rubric_version(status=RubricStatus.ARCHIVED)
            db = _mock_db()

            with pytest.raises(HTTPException) as exc_info:
                await update_rubric_version(
                    db, rv, actor_user_id=uuid.uuid4(), name="New"
                )
            assert exc_info.value.status_code == 409

        asyncio.run(_run())

    def test_add_criterion_to_archived_rubric_blocked(self) -> None:
        """Adding a criterion to an ARCHIVED rubric must raise 409."""

        async def _run() -> None:
            from app.services.rubric import add_criterion

            rv = _make_rubric_version(status=RubricStatus.ARCHIVED)
            db = _mock_db()

            with pytest.raises(HTTPException) as exc_info:
                await add_criterion(
                    db,
                    rv,
                    actor_user_id=uuid.uuid4(),
                    code="C1",
                    title="Title",
                    description="Desc",
                    weight=Decimal("50.00"),
                    position=1,
                )
            assert exc_info.value.status_code == 409

        asyncio.run(_run())

    def test_create_new_version_from_archived_allowed(self) -> None:
        """Creating a new version from an ARCHIVED rubric should succeed."""

        async def _run() -> None:
            from app.services.rubric import create_new_version_from

            owner = _make_user(UserRole.TEACHER)
            rv = _make_rubric_version(
                status=RubricStatus.ARCHIVED, owner_user_id=owner.id
            )

            # Mock DB: max version query + no criteria
            mock_version_result = MagicMock()
            mock_version_result.scalar_one_or_none.return_value = 1
            mock_criteria_result = MagicMock()
            mock_criteria_result.scalars.return_value.all.return_value = []

            call_count = 0

            async def _execute(stmt: object) -> object:
                nonlocal call_count
                call_count += 1
                if call_count == 1:
                    return mock_version_result
                return mock_criteria_result

            db = _mock_db(execute=AsyncMock(side_effect=_execute))

            new_rv = await create_new_version_from(db, rv, actor_user_id=owner.id)
            assert new_rv.status == RubricStatus.DRAFT
            assert new_rv.version_number == 2
            assert new_rv.source_version_id == rv.id

        asyncio.run(_run())


# ---------------------------------------------------------------------------
# Student rubric visibility denial
# ---------------------------------------------------------------------------


class TestStudentRubricVisibility:
    """Students cannot access rubric endpoints."""

    def test_student_denied_from_rubric_list(self) -> None:
        """list_rubrics requires Teacher/Admin — Student is rejected."""
        student = _make_user(UserRole.STUDENT)
        with pytest.raises(HTTPException) as exc_info:
            check_roles(student, {UserRole.TEACHER, UserRole.ADMIN})
        assert exc_info.value.status_code == 403

    def test_student_denied_from_rubric_detail(self) -> None:
        """get_rubric requires Teacher/Admin — Student is rejected."""
        student = _make_user(UserRole.STUDENT)
        with pytest.raises(HTTPException) as exc_info:
            check_roles(student, {UserRole.TEACHER, UserRole.ADMIN})
        assert exc_info.value.status_code == 403


# ---------------------------------------------------------------------------
# Assignment CREATE audit record
# ---------------------------------------------------------------------------


class TestAssignmentCreateAudit:
    """Assignment creation records an audit event."""

    def test_create_assignment_records_audit(self) -> None:
        """create_assignment should call record_audit with action=CREATE."""

        async def _run() -> None:
            from unittest.mock import patch

            from app.services.assignment import create_assignment

            teacher = _make_user(UserRole.TEACHER)
            rv = _make_rubric_version(
                status=RubricStatus.DRAFT, owner_user_id=teacher.id
            )

            db = _mock_db(get=AsyncMock(return_value=rv))

            with patch(
                "app.services.assignment.record_audit", new_callable=AsyncMock
            ) as mock_audit:
                await create_assignment(
                    db,
                    course_id=uuid.uuid4(),
                    created_by_teacher_id=teacher.id,
                    rubric_version_id=rv.id,
                    title="Test",
                    due_at=__import__("datetime").datetime.now(
                        __import__("datetime").UTC
                    ),
                    actor_roles=[UserRole.TEACHER.value],
                )
                mock_audit.assert_called_once()
                call_kwargs = mock_audit.call_args
                assert call_kwargs[1]["action"] == "CREATE"
                assert call_kwargs[1]["resource_type"] == "Assignment"

        asyncio.run(_run())


# ---------------------------------------------------------------------------
# Course archive lifecycle
# ---------------------------------------------------------------------------


class TestCourseArchiveLifecycle:
    """Archived Courses retain history but reject writes."""

    def test_archive_active_course_records_audit(self) -> None:
        """An ACTIVE Course transitions to ARCHIVED through the service."""

        async def _run() -> None:
            from unittest.mock import patch

            from app.services import course as course_svc

            archive_course = getattr(course_svc, "archive_course", None)
            assert callable(archive_course), "Course archive service is required"

            teacher = _make_user(UserRole.TEACHER)
            course = _make_course(teacher.id)
            course.status = "ACTIVE"
            course.revision = 1
            result = MagicMock()
            result.scalar_one_or_none.return_value = course
            db = _mock_db(execute=AsyncMock(return_value=result))

            with patch(
                "app.services.course.record_audit", new_callable=AsyncMock
            ) as mock_audit:
                archived = await archive_course(db, course, actor_user_id=teacher.id)

            assert archived.status == "ARCHIVED"
            assert archived.revision == 2
            assert mock_audit.call_args.kwargs["action"] == "ARCHIVE"

        asyncio.run(_run())

    def test_archive_archived_course_is_blocked(self) -> None:
        """ARCHIVED Courses cannot transition through archive a second time."""

        async def _run() -> None:
            from app.services.course import archive_course

            teacher = _make_user(UserRole.TEACHER)
            course = _make_course(teacher.id)
            course.status = "ARCHIVED"
            course.revision = 1
            db = _mock_db()

            with pytest.raises(HTTPException) as exc_info:
                await archive_course(db, course, actor_user_id=teacher.id)
            assert exc_info.value.status_code == 409

        asyncio.run(_run())

    def test_update_archived_course_is_blocked(self) -> None:
        """Archived Courses are read-only and cannot be changed."""

        async def _run() -> None:
            from app.services.course import update_course

            teacher = _make_user(UserRole.TEACHER)
            course = _make_course(teacher.id)
            course.status = "ARCHIVED"
            course.revision = 1
            db = _mock_db()

            with pytest.raises(HTTPException) as exc_info:
                await update_course(
                    db, course, actor_user_id=teacher.id, name="Changed"
                )
            assert exc_info.value.status_code == 409

        asyncio.run(_run())

    def test_delete_archived_course_is_blocked(self) -> None:
        """Archived Courses retain history and cannot be deleted."""

        async def _run() -> None:
            from app.services.course import delete_course

            teacher = _make_user(UserRole.TEACHER)
            course = _make_course(teacher.id)
            course.status = "ARCHIVED"
            course.revision = 1
            db = _mock_db()

            with pytest.raises(HTTPException) as exc_info:
                await delete_course(db, course, actor_user_id=teacher.id)
            assert exc_info.value.status_code == 409

        asyncio.run(_run())

    def test_create_assignment_in_archived_course_is_blocked(self) -> None:
        """Archived Courses cannot receive another Assignment."""

        async def _run() -> None:
            from app.services.assignment import create_assignment

            teacher = _make_user(UserRole.TEACHER)
            course = _make_course(teacher.id)
            course.status = "ARCHIVED"
            rubric = _make_rubric_version(owner_user_id=teacher.id)

            async def _get(model: type[object], _: uuid.UUID) -> object | None:
                if model is Course:
                    return course
                if model is RubricVersion:
                    return rubric
                return None

            db = _mock_db(get=AsyncMock(side_effect=_get))

            with pytest.raises(HTTPException) as exc_info:
                await create_assignment(
                    db,
                    course_id=course.id,
                    created_by_teacher_id=teacher.id,
                    rubric_version_id=rubric.id,
                    title="Forbidden",
                    due_at=__import__("datetime").datetime.now(
                        __import__("datetime").UTC
                    ),
                    actor_roles=[UserRole.TEACHER.value],
                )
            assert exc_info.value.status_code == 409

        asyncio.run(_run())


# ---------------------------------------------------------------------------
# Student assignment Course scope
# ---------------------------------------------------------------------------


class TestStudentAssignmentScope:
    """Student reads require an ACTIVE Student Membership in the Course."""

    def test_active_student_membership_can_read_course(self) -> None:
        """The shared assignment-read dependency accepts active members."""

        async def _run() -> None:
            from app.api import deps

            get_accessible_course = getattr(deps, "get_accessible_course", None)
            assert callable(
                get_accessible_course
            ), "Assignment read-scope dependency is required"

            teacher = _make_user(UserRole.TEACHER)
            student = _make_user(UserRole.STUDENT)
            course = _make_course(teacher.id)
            membership = Membership(
                id=uuid.uuid4(),
                course_id=course.id,
                user_id=student.id,
                role="STUDENT",
                status="ACTIVE",
            )

            result = MagicMock()
            result.scalar_one_or_none.return_value = membership
            db = _mock_db(
                get=AsyncMock(return_value=course),
                execute=AsyncMock(return_value=result),
            )

            assert await get_accessible_course(course.id, student, db) is course

        asyncio.run(_run())

    def test_inactive_student_membership_is_masked_as_not_found(self) -> None:
        """An inactive member cannot discover or list Course assignments."""

        async def _run() -> None:
            from app.api import deps

            get_accessible_course = getattr(deps, "get_accessible_course", None)
            assert callable(
                get_accessible_course
            ), "Assignment read-scope dependency is required"

            teacher = _make_user(UserRole.TEACHER)
            student = _make_user(UserRole.STUDENT)
            course = _make_course(teacher.id)
            result = MagicMock()
            result.scalar_one_or_none.return_value = None
            db = _mock_db(
                get=AsyncMock(return_value=course),
                execute=AsyncMock(return_value=result),
            )

            with pytest.raises(HTTPException) as exc_info:
                await get_accessible_course(course.id, student, db)
            assert exc_info.value.status_code == 404

        asyncio.run(_run())

    def test_non_owner_teacher_is_denied_assignment_read_scope(self) -> None:
        """Teacher ownership remains enforced for assignment reads."""

        async def _run() -> None:
            from app.api import deps

            get_accessible_course = getattr(deps, "get_accessible_course", None)
            assert callable(
                get_accessible_course
            ), "Assignment read-scope dependency is required"

            owner = _make_user(UserRole.TEACHER)
            other_teacher = _make_user(UserRole.TEACHER)
            course = _make_course(owner.id)
            db = _mock_db(get=AsyncMock(return_value=course))

            with pytest.raises(HTTPException) as exc_info:
                await get_accessible_course(course.id, other_teacher, db)
            assert exc_info.value.status_code == 403

        asyncio.run(_run())

    def test_dual_role_student_member_can_read_course(self) -> None:
        """A Teacher+Student user may use the active Student membership scope."""

        async def _run() -> None:
            from app.api.deps import get_accessible_course

            owner = _make_user(UserRole.TEACHER)
            dual_role_user = _make_user(UserRole.TEACHER)
            dual_role_user.roles.append(UserRole.STUDENT)
            course = _make_course(owner.id)
            membership = Membership(
                id=uuid.uuid4(),
                course_id=course.id,
                user_id=dual_role_user.id,
                role="STUDENT",
                status="ACTIVE",
            )
            result = MagicMock()
            result.scalar_one_or_none.return_value = membership
            db = _mock_db(
                get=AsyncMock(return_value=course),
                execute=AsyncMock(return_value=result),
            )

            assert await get_accessible_course(course.id, dual_role_user, db) is course

        asyncio.run(_run())

    def test_dual_role_course_owner_does_not_require_membership(self) -> None:
        """Course ownership takes precedence over the Student membership scope."""

        async def _run() -> None:
            from app.api.deps import get_accessible_course

            owner = _make_user(UserRole.TEACHER)
            owner.roles.append(UserRole.STUDENT)
            course = _make_course(owner.id)
            execute = AsyncMock()
            db = _mock_db(
                get=AsyncMock(return_value=course),
                execute=execute,
            )

            assert await get_accessible_course(course.id, owner, db) is course
            execute.assert_not_awaited()

        asyncio.run(_run())


# ---------------------------------------------------------------------------
# Rubric supersession lineage
# ---------------------------------------------------------------------------


class TestRubricSupersession:
    """A new Draft version preserves an immutable Published source."""

    def test_superseded_source_creates_monotonic_draft_version(self) -> None:
        """Version lineage is explicit and source status is never mutated."""

        async def _run() -> None:
            from app.services.rubric import create_new_version_from

            owner = _make_user(UserRole.TEACHER)
            source = _make_rubric_version(
                status=RubricStatus.PUBLISHED, owner_user_id=owner.id
            )
            source.version_number = 2
            source.total_weight = Decimal("100.00")

            max_version_result = MagicMock()
            max_version_result.scalar_one_or_none.return_value = 2
            criteria_result = MagicMock()
            criteria_result.scalars.return_value.all.return_value = []
            db = _mock_db(
                execute=AsyncMock(side_effect=[max_version_result, criteria_result])
            )

            new_version = await create_new_version_from(
                db, source, actor_user_id=owner.id
            )

            assert new_version.version_number == 3
            assert new_version.source_version_id == source.id
            assert new_version.status == RubricStatus.DRAFT
            assert new_version.total_weight == Decimal("0.00")
            assert source.status == RubricStatus.PUBLISHED

        asyncio.run(_run())
