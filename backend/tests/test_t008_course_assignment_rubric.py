"""Pure-function / mock-based tests for T-008 services and API logic.

Tests cover direct rubric CRUD and assignment readiness validation.
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
    MembershipRole,
    MembershipStatus,
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
        levels=[{"level": level} for level in range(5)],
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
    result = MagicMock()
    result.scalar_one_or_none.return_value = None
    result.scalars.return_value.all.return_value = []
    db.execute = AsyncMock(return_value=result)
    for k, v in overrides.items():
        setattr(db, k, v)
    return db


# ---------------------------------------------------------------------------
# Direct rubric editing and assignment readiness
# ---------------------------------------------------------------------------


def _result(*, scalar: object = None, rows: list[object] | None = None) -> MagicMock:
    result = MagicMock()
    result.scalar_one_or_none.return_value = scalar
    result.scalars.return_value.all.return_value = rows or []
    return result


class TestRubricDirectEditing:
    def test_published_legacy_rubric_editable_before_submission(self) -> None:
        async def _run() -> None:
            from app.services.rubric import (
                add_criterion,
                delete_criterion,
                update_criterion,
                update_rubric_version,
            )

            rv = _make_rubric_version(status=RubricStatus.PUBLISHED)
            db = _mock_db()
            updated = await update_rubric_version(
                db, rv, actor_user_id=uuid.uuid4(), name="Edited"
            )
            assert updated.name == "Edited"
            rv.description = "Old description"
            updated = await update_rubric_version(
                db,
                rv,
                actor_user_id=uuid.uuid4(),
                description=None,
                description_set=True,
            )
            assert updated.description is None
            criterion = await add_criterion(
                db,
                rv,
                actor_user_id=uuid.uuid4(),
                code="C1",
                title="Title",
                description="Description",
                weight=Decimal("100.00"),
                position=1,
            )
            criterion.revision = 1
            edited = await update_criterion(
                db, rv, criterion, actor_user_id=uuid.uuid4(), title="Edited title"
            )
            assert edited.title == "Edited title"
            await delete_criterion(db, rv, criterion, actor_user_id=uuid.uuid4())

        asyncio.run(_run())

    def test_rubric_mutation_blocked_after_first_submission(self) -> None:
        async def _run() -> None:
            from app.services.rubric import update_rubric_version

            rv = _make_rubric_version(status=RubricStatus.PUBLISHED)
            db = _mock_db(execute=AsyncMock(return_value=_result(scalar=uuid.uuid4())))
            with pytest.raises(HTTPException) as exc_info:
                await update_rubric_version(
                    db, rv, actor_user_id=uuid.uuid4(), name="Blocked"
                )
            assert exc_info.value.status_code == 409
            assert "first assignment submission" in exc_info.value.detail

        asyncio.run(_run())

    def test_direct_delete_succeeds_without_references(self) -> None:
        async def _run() -> None:
            from app.services.rubric import delete_rubric_version

            rv = _make_rubric_version()
            db = _mock_db(execute=AsyncMock(side_effect=[_result() for _ in range(5)]))
            await delete_rubric_version(db, rv, actor_user_id=uuid.uuid4())
            db.delete.assert_awaited_once_with(rv)

        asyncio.run(_run())

    def test_delete_referenced_rubric_denied(self) -> None:
        async def _run() -> None:
            from app.services.rubric import delete_rubric_version

            rv = _make_rubric_version()
            db = _mock_db(execute=AsyncMock(return_value=_result(scalar=uuid.uuid4())))
            with pytest.raises(HTTPException) as exc_info:
                await delete_rubric_version(db, rv, actor_user_id=uuid.uuid4())
            assert exc_info.value.status_code == 409
            assert "referenced" in exc_info.value.detail

        asyncio.run(_run())


class TestAssignmentRubricReadiness:
    def test_publish_accepts_saved_draft_rubric_at_100(self) -> None:
        async def _run() -> None:
            from app.services.assignment import publish_assignment

            teacher = _make_user()
            rv = _make_rubric_version(owner_user_id=teacher.id)
            assignment = _make_assignment(uuid.uuid4(), rv.id, teacher.id)
            criteria = [
                _make_criterion_version(rv.id, weight=Decimal("60.00")),
                _make_criterion_version(
                    rv.id, weight=Decimal("40.00"), position=2, code="C2"
                ),
            ]
            db = _mock_db(execute=AsyncMock(return_value=_result(rows=criteria)))
            result = await publish_assignment(db, assignment, actor_user_id=teacher.id)
            assert result.status == AssignmentStatus.OPEN

        asyncio.run(_run())

    @pytest.mark.parametrize("criteria", [[], [_make_criterion_version(uuid.uuid4())]])
    def test_publish_rejects_empty_or_non_100_rubric(
        self, criteria: list[CriterionVersion]
    ) -> None:
        async def _run() -> None:
            from app.services.assignment import publish_assignment

            teacher = _make_user()
            rv = _make_rubric_version(owner_user_id=teacher.id)
            assignment = _make_assignment(uuid.uuid4(), rv.id, teacher.id)
            db = _mock_db(execute=AsyncMock(return_value=_result(rows=criteria)))
            with pytest.raises(HTTPException) as exc_info:
                await publish_assignment(db, assignment, actor_user_id=teacher.id)
            assert exc_info.value.status_code == 422
            assert "100.00" in exc_info.value.detail

        asyncio.run(_run())

    def test_publish_rejects_incomplete_score_scale(self) -> None:
        async def _run() -> None:
            from app.services.assignment import publish_assignment

            teacher = _make_user()
            rv = _make_rubric_version(owner_user_id=teacher.id)
            assignment = _make_assignment(uuid.uuid4(), rv.id, teacher.id)
            criterion = _make_criterion_version(rv.id, weight=Decimal("100.00"))
            criterion.levels = [{"level": level} for level in range(4)]
            db = _mock_db(execute=AsyncMock(return_value=_result(rows=[criterion])))
            with pytest.raises(HTTPException) as exc_info:
                await publish_assignment(db, assignment, actor_user_id=teacher.id)
            assert exc_info.value.status_code == 422
            assert "levels 0 through 4" in exc_info.value.detail

        asyncio.run(_run())


# ---------------------------------------------------------------------------
# Ownership deny
# ---------------------------------------------------------------------------


class TestOwnershipDeny:
    """Teacher B cannot manage Teacher A's course."""

    def test_other_teacher_course_is_masked_as_not_found(self) -> None:
        teacher_a = _make_user(UserRole.TEACHER)
        teacher_b = _make_user(UserRole.TEACHER)
        course = _make_course(teacher_a.id)

        with pytest.raises(HTTPException) as exc_info:
            check_course_ownership(teacher_b, course)
        assert exc_info.value.status_code == 404

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

    def test_edit_draft_assignment_can_clear_description(self) -> None:
        async def _run() -> None:
            from app.services.assignment import update_assignment

            teacher = _make_user(UserRole.TEACHER)
            assignment = _make_assignment(uuid.uuid4(), uuid.uuid4(), teacher.id)
            assignment.description = "Remove me"
            db = _mock_db()

            result = await update_assignment(
                db,
                assignment,
                actor_user_id=teacher.id,
                description=None,
                description_set=True,
            )

            assert result.description is None
            assert result.revision == 2

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


class TestRubricCreateAudit:
    def test_create_rubric_version_records_audit(self) -> None:
        async def _run() -> None:
            from unittest.mock import patch

            from app.services.rubric import create_rubric_version

            teacher_id = uuid.uuid4()
            database = _mock_db()
            with patch(
                "app.services.rubric.record_audit", new_callable=AsyncMock
            ) as mock_audit:
                rubric = await create_rubric_version(
                    database,
                    owner_user_id=teacher_id,
                    created_by_user_id=teacher_id,
                    name="Audited rubric",
                )

            mock_audit.assert_awaited_once_with(
                database,
                actor_user_id=teacher_id,
                resource_type="RubricVersion",
                resource_id=rubric.id,
                action="CREATE",
                after={
                    "name": "Audited rubric",
                    "calculation_method": "WEIGHTED_SUM",
                },
                reason="Rubric version created",
            )

        asyncio.run(_run())


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
                archived = await archive_course(
                    db,
                    course,
                    actor_user_id=teacher.id,
                    expected_revision=1,
                )

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
            result = MagicMock()
            result.scalar_one_or_none.return_value = course
            db = _mock_db(execute=AsyncMock(return_value=result))

            with pytest.raises(HTTPException) as exc_info:
                await archive_course(
                    db,
                    course,
                    actor_user_id=teacher.id,
                    expected_revision=1,
                )
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
            result = MagicMock()
            result.scalar_one_or_none.return_value = course
            db = _mock_db(execute=AsyncMock(return_value=result))

            with pytest.raises(HTTPException) as exc_info:
                await update_course(
                    db,
                    course,
                    actor_user_id=teacher.id,
                    expected_revision=1,
                    name="Changed",
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
            result = MagicMock()
            result.scalar_one_or_none.return_value = course
            db = _mock_db(execute=AsyncMock(return_value=result))

            with pytest.raises(HTTPException) as exc_info:
                await delete_course(
                    db,
                    course,
                    actor_user_id=teacher.id,
                    expected_revision=1,
                )
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
            course_result = MagicMock()
            course_result.scalar_one_or_none.return_value = course
            membership_result = MagicMock()
            membership_result.scalar_one_or_none.return_value = membership
            execute = AsyncMock(side_effect=[course_result, membership_result])
            db = _mock_db(execute=execute)

            assert await get_accessible_course(course.id, student, db) is course
            assert execute.await_count == 2

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
            course_result = MagicMock()
            course_result.scalar_one_or_none.return_value = course
            membership_result = MagicMock()
            membership_result.scalar_one_or_none.return_value = None
            execute = AsyncMock(side_effect=[course_result, membership_result])
            db = _mock_db(execute=execute)

            with pytest.raises(HTTPException) as exc_info:
                await get_accessible_course(course.id, student, db)
            assert exc_info.value.status_code == 404
            assert execute.await_count == 2

        asyncio.run(_run())

    def test_non_owner_teacher_is_masked_from_assignment_read_scope(self) -> None:
        """Teacher ownership remains enforced without disclosing the Course."""

        async def _run() -> None:
            from app.api import deps

            get_accessible_course = getattr(deps, "get_accessible_course", None)
            assert callable(
                get_accessible_course
            ), "Assignment read-scope dependency is required"

            owner = _make_user(UserRole.TEACHER)
            other_teacher = _make_user(UserRole.TEACHER)
            course = _make_course(owner.id)
            course_result = MagicMock()
            course_result.scalar_one_or_none.return_value = course
            execute = AsyncMock(return_value=course_result)
            db = _mock_db(execute=execute)

            with pytest.raises(HTTPException) as exc_info:
                await get_accessible_course(course.id, other_teacher, db)
            assert exc_info.value.status_code == 404
            assert execute.await_count == 1

        asyncio.run(_run())

    def test_dual_role_non_owner_cannot_fall_back_to_student_scope(self) -> None:
        """Strongest-role precedence prevents Teacher-to-Student fallback."""

        async def _run() -> None:
            from app.api.deps import get_accessible_course

            owner = _make_user(UserRole.TEACHER)
            dual_role_user = _make_user(UserRole.TEACHER)
            dual_role_user.roles.append(UserRole.STUDENT)
            course = _make_course(owner.id)
            course_result = MagicMock()
            course_result.scalar_one_or_none.return_value = course
            execute = AsyncMock(return_value=course_result)
            db = _mock_db(execute=execute)

            with pytest.raises(HTTPException) as exc_info:
                await get_accessible_course(course.id, dual_role_user, db)
            assert exc_info.value.status_code == 404
            assert execute.await_count == 1

        asyncio.run(_run())

    def test_dual_role_course_owner_does_not_require_membership(self) -> None:
        """Course ownership takes precedence over the Student membership scope."""

        async def _run() -> None:
            from app.api.deps import get_accessible_course

            owner = _make_user(UserRole.TEACHER)
            owner.roles.append(UserRole.STUDENT)
            course = _make_course(owner.id)
            course_result = MagicMock()
            course_result.scalar_one_or_none.return_value = course
            execute = AsyncMock(return_value=course_result)
            db = _mock_db(execute=execute)

            assert await get_accessible_course(course.id, owner, db) is course
            assert execute.await_count == 1

        asyncio.run(_run())


class TestStudentCourseDiscovery:
    def test_student_course_list_is_membership_scoped(self) -> None:
        async def _run() -> None:
            from app.services.course import list_courses

            student = _make_user(UserRole.STUDENT)
            result = MagicMock()
            result.scalars.return_value.all.return_value = []
            db = _mock_db(execute=AsyncMock(return_value=result))

            assert await list_courses(db, member_user_id=student.id) == []

            statement = db.execute.await_args.args[0]
            sql = str(statement)
            params = statement.compile().params.values()
            assert "JOIN memberships" in sql
            assert student.id in params
            assert MembershipRole.STUDENT in params
            assert MembershipStatus.ACTIVE in params

        asyncio.run(_run())
