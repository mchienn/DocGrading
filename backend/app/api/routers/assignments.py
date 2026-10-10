"""Assignment CRUD and lifecycle endpoints."""

from __future__ import annotations

import uuid

import sqlalchemy as sa
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import (
    get_accessible_course,
    get_active_owned_course,
    get_current_user,
    get_owned_course,
    get_visible_assignments,
    require_roles,
)
from app.api.schemas_assignment import (
    AssignmentCreate,
    AssignmentResponse,
    AssignmentUpdate,
)
from app.db.session import get_db_session
from app.models.assignment import Assignment
from app.models.course import Course
from app.models.enums import UserRole
from app.models.identity import User
from app.models.submission import DocumentVersion, Submission
from app.services import assignment as assignment_svc

router = APIRouter(prefix="/courses/{course_id}/assignments", tags=["assignments"])


def _student_only(user: User) -> bool:
    return (
        UserRole.STUDENT in user.roles
        and UserRole.ADMIN not in user.roles
        and UserRole.TEACHER not in user.roles
    )


async def _assignment_responses(
    assignments: list[Assignment],
    *,
    user: User,
    db: AsyncSession,
) -> list[AssignmentResponse]:
    attempts: dict[uuid.UUID, tuple[uuid.UUID, int]] = {}
    if assignments and _student_only(user):
        rows = await db.execute(
            sa.select(
                Submission.assignment_id,
                Submission.id,
                sa.func.count(DocumentVersion.id),
            )
            .outerjoin(
                DocumentVersion,
                DocumentVersion.submission_id == Submission.id,
            )
            .where(
                Submission.student_id == user.id,
                Submission.assignment_id.in_(
                    [assignment.id for assignment in assignments]
                ),
            )
            .group_by(Submission.assignment_id, Submission.id)
        )
        attempts = {
            assignment_id: (submission_id, int(count))
            for assignment_id, submission_id, count in rows
        }
    return [
        (
            AssignmentResponse.model_validate(assignment).model_copy(
                update={
                    "student_submission_id": attempts.get(assignment.id, (None, 0))[0],
                    "student_attempts_used": attempts.get(assignment.id, (None, 0))[1],
                }
            )
            if _student_only(user)
            else AssignmentResponse.model_validate(assignment)
        )
        for assignment in assignments
    ]


@router.post("", response_model=AssignmentResponse, status_code=201)
async def create_assignment(
    course_id: uuid.UUID,
    body: AssignmentCreate,
    course: Course = Depends(get_owned_course),
    user: User = Depends(require_roles(UserRole.ADMIN, UserRole.TEACHER)),
    db: AsyncSession = Depends(get_db_session),
) -> AssignmentResponse:
    """Create a new assignment in a course (owner/Admin)."""
    assignment = await assignment_svc.create_assignment(
        db,
        course_id=course.id,
        created_by_teacher_id=user.id,
        rubric_version_id=body.rubric_version_id,
        title=body.title,
        description=body.description,
        due_at=body.due_at,
        max_submissions=body.max_submissions,
        actor_roles=[r.value for r in user.roles],
    )
    await db.commit()
    return AssignmentResponse.model_validate(assignment)


@router.get("", response_model=list[AssignmentResponse])
async def list_assignments(
    assignments: list[Assignment] = Depends(get_visible_assignments),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> list[AssignmentResponse]:
    """List assignments visible to the current user."""
    return await _assignment_responses(assignments, user=user, db=db)


async def _get_assignment_with_ownership(
    course_id: uuid.UUID,
    assignment_id: uuid.UUID,
    course: Course = Depends(get_active_owned_course),
    db: AsyncSession = Depends(get_db_session),
) -> Assignment:
    """Load an assignment and verify it belongs to the owned course."""
    assignment = await assignment_svc.get_assignment(db, assignment_id)
    if assignment is None or assignment.course_id != course.id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Assignment not found",
        )
    return assignment


@router.get("/{assignment_id}", response_model=AssignmentResponse)
async def get_assignment(
    assignment_id: uuid.UUID,
    course: Course = Depends(get_accessible_course),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> AssignmentResponse:
    """Get a single assignment (respects student visibility)."""
    assignment = await assignment_svc.get_assignment(db, assignment_id)
    if assignment is None or assignment.course_id != course.id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Assignment not found",
        )
    # Students can only see OPEN/CLOSED
    from app.api.deps import visible_assignment_statuses

    allowed = visible_assignment_statuses(user)
    if allowed is not None and assignment.status not in allowed:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Assignment not found",
        )
    return (await _assignment_responses([assignment], user=user, db=db))[0]


@router.put("/{assignment_id}", response_model=AssignmentResponse)
async def update_assignment(
    body: AssignmentUpdate,
    assignment: Assignment = Depends(_get_assignment_with_ownership),
    user: User = Depends(require_roles(UserRole.ADMIN, UserRole.TEACHER)),
    db: AsyncSession = Depends(get_db_session),
) -> AssignmentResponse:
    """Update a DRAFT assignment (owner/Admin)."""
    assignment = await assignment_svc.update_assignment(
        db,
        assignment,
        actor_user_id=user.id,
        actor_roles=[r.value for r in user.roles],
        title=body.title,
        description=body.description,
        description_set="description" in body.model_fields_set,
        due_at=body.due_at,
        max_submissions=body.max_submissions,
        rubric_version_id=body.rubric_version_id,
    )
    await db.commit()
    return AssignmentResponse.model_validate(assignment)


@router.post(
    "/{assignment_id}/publish",
    response_model=AssignmentResponse,
)
async def publish_assignment(
    assignment: Assignment = Depends(_get_assignment_with_ownership),
    user: User = Depends(require_roles(UserRole.ADMIN, UserRole.TEACHER)),
    db: AsyncSession = Depends(get_db_session),
) -> AssignmentResponse:
    """Publish a DRAFT assignment (DRAFT → OPEN)."""
    assignment = await assignment_svc.publish_assignment(
        db, assignment, actor_user_id=user.id
    )
    await db.commit()
    return AssignmentResponse.model_validate(assignment)


@router.post(
    "/{assignment_id}/close",
    response_model=AssignmentResponse,
)
async def close_assignment(
    assignment: Assignment = Depends(_get_assignment_with_ownership),
    user: User = Depends(require_roles(UserRole.ADMIN, UserRole.TEACHER)),
    db: AsyncSession = Depends(get_db_session),
) -> AssignmentResponse:
    """Close an OPEN assignment (OPEN → CLOSED)."""
    assignment = await assignment_svc.close_assignment(
        db, assignment, actor_user_id=user.id
    )
    await db.commit()
    return AssignmentResponse.model_validate(assignment)
