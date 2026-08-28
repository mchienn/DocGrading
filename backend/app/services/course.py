"""Course service: CRUD operations for courses."""

from __future__ import annotations

import uuid

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.course import Course
from app.models.enums import CourseStatus
from app.services.audit import record_audit


async def create_course(
    db: AsyncSession,
    *,
    code: str,
    name: str,
    term: str,
    owner_teacher_id: uuid.UUID,
) -> Course:
    """Create a new course owned by a teacher."""
    course = Course(
        id=uuid.uuid4(),
        code=code,
        name=name,
        term=term,
        owner_teacher_id=owner_teacher_id,
        status=CourseStatus.ACTIVE,
    )
    db.add(course)
    await db.flush()

    await record_audit(
        db,
        actor_user_id=owner_teacher_id,
        resource_type="Course",
        resource_id=course.id,
        action="CREATE",
        after={"code": code, "name": name, "term": term},
        reason="Course created",
    )
    await db.flush()
    return course


async def get_course(db: AsyncSession, course_id: uuid.UUID) -> Course | None:
    """Load a single course by ID."""
    return await db.get(Course, course_id)


async def list_courses(
    db: AsyncSession,
    *,
    owner_teacher_id: uuid.UUID | None = None,
) -> list[Course]:
    """List courses, optionally filtered by owner."""
    stmt = select(Course).order_by(Course.created_at.desc())
    if owner_teacher_id is not None:
        stmt = stmt.where(Course.owner_teacher_id == owner_teacher_id)
    result = await db.execute(stmt)
    return list(result.scalars().all())


async def update_course(
    db: AsyncSession,
    course: Course,
    *,
    actor_user_id: uuid.UUID,
    name: str | None = None,
    term: str | None = None,
) -> Course:
    """Update mutable fields on a course. Records audit."""
    if course.status == CourseStatus.ARCHIVED:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Archived courses are read-only",
        )

    before: dict[str, str] = {}
    after: dict[str, str] = {}

    if name is not None and name != course.name:
        before["name"] = course.name
        course.name = name
        after["name"] = name

    if term is not None and term != course.term:
        before["term"] = course.term
        course.term = term
        after["term"] = term

    if after:
        course.revision += 1
        await record_audit(
            db,
            actor_user_id=actor_user_id,
            resource_type="Course",
            resource_id=course.id,
            action="UPDATE",
            before=before,
            after=after,
            reason="Course updated",
        )
        await db.flush()

    return course


async def delete_course(
    db: AsyncSession,
    course: Course,
    *,
    actor_user_id: uuid.UUID,
) -> None:
    """Delete a course. Records audit."""
    if course.status == CourseStatus.ARCHIVED:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Archived courses cannot be deleted",
        )

    await record_audit(
        db,
        actor_user_id=actor_user_id,
        resource_type="Course",
        resource_id=course.id,
        action="DELETE",
        before={"code": course.code, "name": course.name, "term": course.term},
        reason="Course deleted",
    )
    await db.delete(course)
    await db.flush()


async def archive_course(
    db: AsyncSession,
    course: Course,
    *,
    actor_user_id: uuid.UUID,
) -> Course:
    """Archive an ACTIVE course while preserving its read history."""
    if course.status == CourseStatus.ARCHIVED:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Course is already archived",
        )

    course.status = CourseStatus.ARCHIVED
    course.revision += 1
    await record_audit(
        db,
        actor_user_id=actor_user_id,
        resource_type="Course",
        resource_id=course.id,
        action="ARCHIVE",
        before={"status": CourseStatus.ACTIVE.value},
        after={"status": CourseStatus.ARCHIVED.value},
        reason="Course archived",
    )
    await db.flush()
    return course
