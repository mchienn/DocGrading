"""Assignment CRUD and lifecycle endpoints."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import (
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
from app.services import assignment as assignment_svc

router = APIRouter(prefix="/courses/{course_id}/assignments", tags=["assignments"])


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
    )
    await db.commit()
    return AssignmentResponse.model_validate(assignment)


@router.get("", response_model=list[AssignmentResponse])
async def list_assignments(
    assignments: list[Assignment] = Depends(get_visible_assignments),
) -> list[AssignmentResponse]:
    """List assignments visible to the current user."""
    return [AssignmentResponse.model_validate(a) for a in assignments]


async def _get_assignment_with_ownership(
    course_id: uuid.UUID,
    assignment_id: uuid.UUID,
    course: Course = Depends(get_owned_course),
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
    assignment: Assignment = Depends(_get_assignment_with_ownership),
) -> AssignmentResponse:
    """Get a single assignment (owner/Admin)."""
    return AssignmentResponse.model_validate(assignment)


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
        title=body.title,
        description=body.description,
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
