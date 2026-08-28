"""FastAPI dependencies for authentication, RBAC, and ownership checks."""

from __future__ import annotations

import uuid

from fastapi import Cookie, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db_session
from app.models.assignment import Assignment
from app.models.course import Course, Membership
from app.models.enums import (
    AssignmentStatus,
    CourseStatus,
    MembershipRole,
    MembershipStatus,
    UserRole,
)
from app.models.identity import User
from app.services.auth import get_valid_session

# ---------------------------------------------------------------------------
# Pure-function checks (testable without FastAPI/DB)
# ---------------------------------------------------------------------------


def check_roles(user: User, required: set[UserRole]) -> None:
    """Raise 403 if *user* holds none of the *required* roles."""
    if not required.intersection(user.roles):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Insufficient permissions",
        )


def check_course_ownership(user: User, course: Course) -> None:
    """Raise 403 unless *user* is Admin or owns *course*."""
    if UserRole.ADMIN in user.roles:
        return
    if course.owner_teacher_id != user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not the course owner",
        )


def visible_assignment_statuses(user: User) -> list[AssignmentStatus] | None:
    """Return statuses a *user* may see, or ``None`` for unrestricted."""
    if UserRole.ADMIN in user.roles or UserRole.TEACHER in user.roles:
        return None
    return [AssignmentStatus.OPEN, AssignmentStatus.CLOSED]


# ---------------------------------------------------------------------------
# FastAPI dependencies
# ---------------------------------------------------------------------------


async def get_current_user(
    session_id: str | None = Cookie(None),
    db: AsyncSession = Depends(get_db_session),
) -> User:
    """Resolve the session cookie to an active ``User``.

    Raises 401 when the cookie is missing, invalid, expired, or revoked.
    """
    if session_id is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
        )
    try:
        sid = uuid.UUID(session_id)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid session",
        ) from exc
    session = await get_valid_session(db, sid)
    if session is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Session expired or invalid",
        )
    return session.user


def require_roles(*roles: UserRole):  # noqa: ANN201
    """Dependency factory — returns a FastAPI dependency that enforces roles.

    Usage::

        @router.get("/admin")
        async def admin_endpoint(
            user: User = Depends(require_roles(UserRole.ADMIN)),
        ):
            ...
    """
    role_set = set(roles)

    async def _dependency(
        user: User = Depends(get_current_user),
    ) -> User:
        check_roles(user, role_set)
        return user

    return _dependency


async def get_owned_course(
    course_id: uuid.UUID,
    user: User = Depends(
        require_roles(UserRole.ADMIN, UserRole.TEACHER),
    ),
    db: AsyncSession = Depends(get_db_session),
) -> Course:
    """Load a course and verify that *user* is its owner (or Admin)."""
    course = await db.get(Course, course_id)
    if course is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Course not found",
        )
    check_course_ownership(user, course)
    return course


async def get_active_owned_course(
    course: Course = Depends(get_owned_course),
) -> Course:
    """Load an owned course and reject mutations after it is archived."""
    if course.status == CourseStatus.ARCHIVED:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Archived courses are read-only",
        )
    return course


async def get_accessible_course(
    course_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> Course:
    """Load a Course readable by its owner/Admin or an active Student member."""
    course = await db.get(Course, course_id)
    if course is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Course not found",
        )
    if UserRole.ADMIN in user.roles:
        return course

    if UserRole.TEACHER in user.roles and course.owner_teacher_id == user.id:
        return course

    if UserRole.STUDENT in user.roles:
        stmt = select(Membership.id).where(
            Membership.course_id == course.id,
            Membership.user_id == user.id,
            Membership.role == MembershipRole.STUDENT,
            Membership.status == MembershipStatus.ACTIVE,
        )
        result = await db.execute(stmt)
        if result.scalar_one_or_none() is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Course not found",
            )
        return course

    check_roles(user, {UserRole.TEACHER})
    check_course_ownership(user, course)
    return course


async def get_visible_assignments(
    course: Course = Depends(get_accessible_course),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> list[Assignment]:
    """Return assignments in an authorized Course filtered by visibility."""
    stmt = select(Assignment).where(Assignment.course_id == course.id)
    statuses = visible_assignment_statuses(user)
    if statuses is not None:
        stmt = stmt.where(Assignment.status.in_(statuses))
    result = await db.execute(stmt)
    return list(result.scalars().all())
