"""Assignment service: CRUD and lifecycle (draft → publish → close)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from decimal import Decimal

import sqlalchemy as sa
from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.assignment import Assignment
from app.models.course import Course
from app.models.enums import AssignmentStatus, CourseStatus
from app.models.rubric import CriterionVersion, RubricVersion
from app.models.submission import Submission
from app.services.audit import record_audit


def _has_complete_level_scale(criterion: CriterionVersion) -> bool:
    levels = {
        item.get("level")
        for item in criterion.levels
        if isinstance(item, dict) and type(item.get("level")) is int
    }
    return levels == {0, 1, 2, 3, 4}


async def create_assignment(
    db: AsyncSession,
    *,
    course_id: uuid.UUID,
    created_by_teacher_id: uuid.UUID,
    rubric_version_id: uuid.UUID,
    title: str,
    description: str | None = None,
    due_at: datetime,
    max_submissions: int = 3,
    actor_roles: list[str] | None = None,
) -> Assignment:
    """Create a new assignment in DRAFT status."""
    course = await db.get(Course, course_id)
    if course is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Course not found",
        )
    if course.status == CourseStatus.ARCHIVED:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Cannot create assignments in an archived course",
        )

    # Validate rubric exists and caller owns it
    rv = await db.get(RubricVersion, rubric_version_id)
    if rv is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Rubric not found",
        )
    from app.services.rubric import _check_rubric_ownership

    _check_rubric_ownership(rv, created_by_teacher_id, actor_roles or [])

    assignment = Assignment(
        id=uuid.uuid4(),
        course_id=course_id,
        created_by_teacher_id=created_by_teacher_id,
        rubric_version_id=rubric_version_id,
        title=title,
        description=description,
        due_at=due_at,
        max_submissions=max_submissions,
        status=AssignmentStatus.DRAFT,
    )
    db.add(assignment)
    await db.flush()

    await record_audit(
        db,
        actor_user_id=created_by_teacher_id,
        resource_type="Assignment",
        resource_id=assignment.id,
        action="CREATE",
        after={
            "title": title,
            "course_id": str(course_id),
            "rubric_version_id": str(rubric_version_id),
        },
        reason="Assignment created",
    )
    await db.flush()
    return assignment


async def get_assignment(
    db: AsyncSession, assignment_id: uuid.UUID
) -> Assignment | None:
    """Load a single assignment by ID."""
    return await db.get(Assignment, assignment_id)


async def update_assignment(
    db: AsyncSession,
    assignment: Assignment,
    *,
    actor_user_id: uuid.UUID,
    actor_roles: list[str] | None = None,
    title: str | None = None,
    description: str | None = None,
    description_set: bool = False,
    due_at: datetime | None = None,
    max_submissions: int | None = None,
    rubric_version_id: uuid.UUID | None = None,
) -> Assignment:
    """Update mutable fields on a DRAFT assignment."""
    if assignment.status != AssignmentStatus.DRAFT:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Only DRAFT assignments can be edited",
        )

    before: dict[str, object] = {}
    after: dict[str, object] = {}

    if title is not None and title != assignment.title:
        before["title"] = assignment.title
        assignment.title = title
        after["title"] = title

    if description_set and description != assignment.description:
        before["description"] = assignment.description
        assignment.description = description
        after["description"] = description

    if due_at is not None and due_at != assignment.due_at:
        before["due_at"] = assignment.due_at.isoformat()
        assignment.due_at = due_at
        after["due_at"] = due_at.isoformat()

    if max_submissions is not None and max_submissions != assignment.max_submissions:
        before["max_submissions"] = assignment.max_submissions
        assignment.max_submissions = max_submissions
        after["max_submissions"] = max_submissions

    if (
        rubric_version_id is not None
        and rubric_version_id != assignment.rubric_version_id
    ):
        # Validate new rubric exists and caller owns it
        rv = await db.get(RubricVersion, rubric_version_id)
        if rv is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Rubric not found",
            )
        from app.services.rubric import _check_rubric_ownership

        _check_rubric_ownership(rv, actor_user_id, actor_roles or [])
        before["rubric_version_id"] = str(assignment.rubric_version_id)
        assignment.rubric_version_id = rubric_version_id
        after["rubric_version_id"] = str(rubric_version_id)

    if after:
        assignment.revision += 1
        await record_audit(
            db,
            actor_user_id=actor_user_id,
            resource_type="Assignment",
            resource_id=assignment.id,
            action="UPDATE",
            before=before,
            after=after,
            reason="Assignment updated",
        )
        await db.flush()

    return assignment


async def delete_assignment(
    db: AsyncSession,
    assignment: Assignment,
    *,
    actor_user_id: uuid.UUID,
) -> None:
    if assignment.status != AssignmentStatus.DRAFT:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Only DRAFT assignments can be deleted",
        )
    has_submission = await db.scalar(
        select(sa.exists().where(Submission.assignment_id == assignment.id))
    )
    if has_submission:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Assignments with submissions cannot be deleted",
        )
    await record_audit(
        db,
        actor_user_id=actor_user_id,
        resource_type="Assignment",
        resource_id=assignment.id,
        action="DELETE",
        before={"course_id": str(assignment.course_id), "title": assignment.title},
        reason="Assignment deleted",
    )
    await db.delete(assignment)
    await db.flush()


async def publish_assignment(
    db: AsyncSession,
    assignment: Assignment,
    *,
    actor_user_id: uuid.UUID,
) -> Assignment:
    """Publish a DRAFT assignment (DRAFT → OPEN).

    Requires at least one enabled criterion with an exact total weight of 100.00.
    """
    if assignment.status != AssignmentStatus.DRAFT:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Only DRAFT assignments can be published",
        )

    stmt = select(CriterionVersion).where(
        CriterionVersion.rubric_version_id == assignment.rubric_version_id,
        CriterionVersion.is_enabled.is_(True),
    )
    result = await db.execute(stmt)
    criteria = list(result.scalars().all())
    total_weight = sum((criterion.weight for criterion in criteria), Decimal("0.00"))
    if not criteria or total_weight != Decimal("100.00"):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=(
                "Assignment's rubric must have at least one enabled criterion "
                f"totaling 100.00, got {total_weight}"
            ),
        )
    incomplete_scale = next(
        (
            criterion.code
            for criterion in criteria
            if not _has_complete_level_scale(criterion)
        ),
        None,
    )
    if incomplete_scale is not None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=f"Criterion {incomplete_scale} must define score levels 0 through 4",
        )

    now = datetime.now(UTC)
    before_status = assignment.status.value
    assignment.status = AssignmentStatus.OPEN
    assignment.published_at = now
    assignment.revision += 1

    await record_audit(
        db,
        actor_user_id=actor_user_id,
        resource_type="Assignment",
        resource_id=assignment.id,
        action="PUBLISH",
        before={"status": before_status},
        after={"status": AssignmentStatus.OPEN.value, "published_at": now.isoformat()},
        reason="Assignment published",
    )
    await db.flush()
    return assignment


async def close_assignment(
    db: AsyncSession,
    assignment: Assignment,
    *,
    actor_user_id: uuid.UUID,
) -> Assignment:
    """Close an OPEN assignment (OPEN → CLOSED)."""
    if assignment.status != AssignmentStatus.OPEN:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Only OPEN assignments can be closed",
        )

    now = datetime.now(UTC)
    before_status = assignment.status.value
    assignment.status = AssignmentStatus.CLOSED
    assignment.closed_at = now
    assignment.revision += 1

    await record_audit(
        db,
        actor_user_id=actor_user_id,
        resource_type="Assignment",
        resource_id=assignment.id,
        action="CLOSE",
        before={"status": before_status},
        after={"status": AssignmentStatus.CLOSED.value, "closed_at": now.isoformat()},
        reason="Assignment closed",
    )
    await db.flush()
    return assignment
