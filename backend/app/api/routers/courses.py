"""Course CRUD endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_owned_course, require_roles
from app.api.schemas_course import CourseCreate, CourseResponse, CourseUpdate
from app.db.session import get_db_session
from app.models.course import Course
from app.models.enums import UserRole
from app.models.identity import User
from app.services import course as course_svc

router = APIRouter(prefix="/courses", tags=["courses"])


@router.post("", response_model=CourseResponse, status_code=201)
async def create_course(
    body: CourseCreate,
    user: User = Depends(require_roles(UserRole.ADMIN, UserRole.TEACHER)),
    db: AsyncSession = Depends(get_db_session),
) -> CourseResponse:
    """Create a new course (Teacher/Admin only)."""
    course = await course_svc.create_course(
        db,
        code=body.code,
        name=body.name,
        term=body.term,
        owner_teacher_id=user.id,
    )
    await db.commit()
    return CourseResponse.model_validate(course)


@router.get("", response_model=list[CourseResponse])
async def list_courses(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> list[CourseResponse]:
    """List courses. Admin sees all; Teacher sees own."""
    owner_id = None if UserRole.ADMIN in user.roles else user.id
    courses = await course_svc.list_courses(db, owner_teacher_id=owner_id)
    return [CourseResponse.model_validate(c) for c in courses]


@router.get("/{course_id}", response_model=CourseResponse)
async def get_course(
    course: Course = Depends(get_owned_course),
) -> CourseResponse:
    """Get a single course (owner or Admin)."""
    return CourseResponse.model_validate(course)


@router.put("/{course_id}", response_model=CourseResponse)
async def update_course(
    body: CourseUpdate,
    course: Course = Depends(get_owned_course),
    user: User = Depends(require_roles(UserRole.ADMIN, UserRole.TEACHER)),
    db: AsyncSession = Depends(get_db_session),
) -> CourseResponse:
    """Update a course (owner or Admin)."""
    course = await course_svc.update_course(
        db,
        course,
        actor_user_id=user.id,
        name=body.name,
        term=body.term,
    )
    await db.commit()
    return CourseResponse.model_validate(course)


@router.delete("/{course_id}", status_code=204)
async def delete_course(
    course: Course = Depends(get_owned_course),
    user: User = Depends(require_roles(UserRole.ADMIN, UserRole.TEACHER)),
    db: AsyncSession = Depends(get_db_session),
) -> None:
    """Delete a course (owner or Admin)."""
    await course_svc.delete_course(db, course, actor_user_id=user.id)
    await db.commit()
