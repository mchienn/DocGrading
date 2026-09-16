"""Course service: CRUD operations for courses."""

import uuid
from datetime import UTC, datetime

import sqlalchemy as sa
from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.elements import ColumnElement

from app.models.course import Course, CourseInvite, Membership
from app.models.enums import (
    CourseStatus,
    MembershipAddOutcome,
    MembershipJoinedVia,
    MembershipRole,
    MembershipStatus,
    UserRole,
)
from app.models.identity import User
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


def active_student_membership_exists(
    *,
    course_id: uuid.UUID | ColumnElement[uuid.UUID],
    user_id: uuid.UUID,
) -> ColumnElement[bool]:
    """Match an active Student membership for an authorization query."""
    return sa.exists().where(
        Membership.course_id == course_id,
        Membership.user_id == user_id,
        Membership.role == MembershipRole.STUDENT,
        Membership.status == MembershipStatus.ACTIVE,
    )


async def list_courses(
    db: AsyncSession,
    *,
    owner_teacher_id: uuid.UUID | None = None,
    member_user_id: uuid.UUID | None = None,
) -> list[Course]:
    """List courses visible to an Admin, owning Teacher, or active Student member."""
    stmt = select(Course).order_by(Course.created_at.desc())
    if owner_teacher_id is not None:
        stmt = stmt.where(Course.owner_teacher_id == owner_teacher_id)
    elif member_user_id is not None:
        stmt = stmt.join(Membership, Membership.course_id == Course.id).where(
            Membership.user_id == member_user_id,
            Membership.role == MembershipRole.STUDENT,
            Membership.status == MembershipStatus.ACTIVE,
        )
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

    result = await db.execute(
        select(Course)
        .where(Course.id == course.id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    course = result.scalar_one_or_none()
    if course is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Course not found",
        )
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


def _member_snapshot(
    membership: Membership,
) -> dict[str, str]:
    return {
        "course_id": str(membership.course_id),
        "user_id": str(membership.user_id),
        "status": membership.status.value,
        "joined_via": membership.joined_via.value,
        "joined_at": membership.joined_at.isoformat(),
    }


async def list_members(
    db: AsyncSession,
    *,
    course_id: uuid.UUID,
    member_status: MembershipStatus | None,
    page: int,
    page_size: int,
) -> tuple[list[tuple[Membership, User]], int]:
    filters = [
        Membership.course_id == course_id,
        Membership.role == MembershipRole.STUDENT,
    ]
    if member_status is not None:
        filters.append(Membership.status == member_status)

    total = int(
        (
            await db.execute(
                select(sa.func.count())
                .select_from(Membership)
                .join(User, User.id == Membership.user_id)
                .where(*filters)
            )
        ).scalar_one()
    )
    rows = list(
        (
            await db.execute(
                select(Membership, User)
                .join(User, User.id == Membership.user_id)
                .where(*filters)
                .order_by(sa.func.lower(User.email), User.id)
                .offset((page - 1) * page_size)
                .limit(page_size)
            )
        ).all()
    )
    return rows, total


async def _lock_active_course(db: AsyncSession, course_id: uuid.UUID) -> Course:
    result = await db.execute(
        select(Course)
        .where(Course.id == course_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    course = result.scalar_one_or_none()
    if course is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Course not found",
        )
    if course.status == CourseStatus.ARCHIVED:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Archived courses are read-only",
        )
    return course


async def add_member(
    db: AsyncSession,
    *,
    course_id: uuid.UUID,
    email: str,
    actor_user_id: uuid.UUID,
    reason: str | None,
) -> tuple[MembershipAddOutcome, Membership | None, CourseInvite | None]:
    await _lock_active_course(db, course_id)
    email = email.strip().lower()
    now = datetime.now(UTC)
    reason = reason.strip() if reason else None
    user = (
        await db.execute(select(User).where(sa.func.lower(User.email) == email))
    ).scalar_one_or_none()

    if user is None:
        invite = (
            await db.execute(
                select(CourseInvite).where(
                    CourseInvite.course_id == course_id,
                    sa.func.lower(CourseInvite.email) == email,
                )
            )
        ).scalar_one_or_none()
        if invite is not None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Pending invite already exists",
            )
        invite = CourseInvite(
            id=uuid.uuid4(),
            course_id=course_id,
            email=email,
            created_by_user_id=actor_user_id,
        )
        db.add(invite)
        await db.flush()
        await record_audit(
            db,
            actor_user_id=actor_user_id,
            resource_type="CourseInvite",
            resource_id=invite.id,
            action="CREATE_INVITE",
            reason=reason or "Invite created",
            after={"course_id": str(course_id), "status": "PENDING"},
        )
        return MembershipAddOutcome.INVITED, None, invite

    if UserRole.STUDENT not in user.roles:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="User does not have STUDENT role",
        )

    membership = (
        await db.execute(
            select(Membership).where(
                Membership.course_id == course_id,
                Membership.user_id == user.id,
                Membership.role == MembershipRole.STUDENT,
            )
        )
    ).scalar_one_or_none()

    if membership is not None and membership.status == MembershipStatus.ACTIVE:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="User is already an active member",
        )

    stale_invite = (
        await db.execute(
            select(CourseInvite).where(
                CourseInvite.course_id == course_id,
                sa.func.lower(CourseInvite.email) == email,
            )
        )
    ).scalar_one_or_none()
    if stale_invite is not None:
        await db.delete(stale_invite)

    if membership is None:
        membership = Membership(
            id=uuid.uuid4(),
            course_id=course_id,
            user_id=user.id,
            role=MembershipRole.STUDENT,
            status=MembershipStatus.ACTIVE,
            joined_via=MembershipJoinedVia.MANUAL,
            joined_at=now,
        )
        db.add(membership)
        outcome = MembershipAddOutcome.ADDED
        action = "ADD_MEMBER"
        default_reason = "Member added"
        before = None
    else:
        before = _member_snapshot(membership)
        membership.status = MembershipStatus.ACTIVE
        membership.joined_via = MembershipJoinedVia.MANUAL
        membership.joined_at = now
        outcome = MembershipAddOutcome.REACTIVATED
        action = "REACTIVATE_MEMBER"
        default_reason = "Member reactivated"

    await db.flush()
    await record_audit(
        db,
        actor_user_id=actor_user_id,
        resource_type="Membership",
        resource_id=membership.id,
        action=action,
        before=before,
        after=_member_snapshot(membership),
        reason=reason or default_reason,
    )
    return outcome, membership, None


async def remove_member(
    db: AsyncSession,
    *,
    course_id: uuid.UUID,
    user_id: uuid.UUID,
    actor_user_id: uuid.UUID,
    reason: str | None,
) -> None:
    await _lock_active_course(db, course_id)
    membership = (
        await db.execute(
            select(Membership).where(
                Membership.course_id == course_id,
                Membership.user_id == user_id,
                Membership.role == MembershipRole.STUDENT,
            )
        )
    ).scalar_one_or_none()
    if membership is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Student membership not found",
        )
    if membership.status == MembershipStatus.REMOVED:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Student membership is already removed",
        )

    before = _member_snapshot(membership)
    membership.status = MembershipStatus.REMOVED
    await db.flush()
    await record_audit(
        db,
        actor_user_id=actor_user_id,
        resource_type="Membership",
        resource_id=membership.id,
        action="REMOVE_MEMBER",
        before=before,
        after=_member_snapshot(membership),
        reason=reason or "Member removed",
    )
