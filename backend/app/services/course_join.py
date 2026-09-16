"""Course join-code lifecycle, rate limiting, and atomic student joins."""

from __future__ import annotations

import hashlib
import io
import math
import secrets
import uuid
from datetime import UTC, datetime, timedelta
from urllib.parse import quote

import qrcode
import sqlalchemy as sa
from fastapi import HTTPException, Request, status
from qrcode.image.svg import SvgPathImage
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.models.course import Course, CourseJoinCode, JoinRateLimit, Membership
from app.models.enums import (
    CourseJoinOutcome,
    CourseStatus,
    MembershipJoinedVia,
    MembershipRole,
    MembershipStatus,
    UserRole,
)
from app.models.identity import User
from app.services.audit import record_audit

CODE_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ023456789"
CODE_LENGTH = 20
_JOIN_MUTATION_LOCK_ID = 0x544F_3237


def normalize_join_code(value: str) -> str:
    """Normalize user-entered code; invalid shape remains service error."""
    return value.strip().upper()


def generate_join_code() -> str:
    return "".join(secrets.choice(CODE_ALPHABET) for _ in range(CODE_LENGTH))


def _error(code: str, message: str, http_status: int) -> HTTPException:
    return HTTPException(
        status_code=http_status,
        detail={"code": code, "message": message},
    )


async def _raise_after_commit(db: AsyncSession, error: HTTPException) -> None:
    await db.commit()
    raise error


def _state(code: CourseJoinCode, now: datetime | None = None) -> str:
    now = now or datetime.now(UTC)
    if code.revoked_at is not None:
        return "REVOKED"
    if code.expires_at <= now:
        return "EXPIRED"
    return "ACTIVE"


def join_url(code: str) -> str:
    origin = get_settings().frontend_origin.rstrip("/")
    return f"{origin}/student/join?code={quote(code, safe='')}"


def qr_url(course_id: uuid.UUID) -> str:
    return f"/api/v1/courses/{course_id}/join-code/qr"


def _snapshot(
    code: CourseJoinCode, now: datetime | None = None
) -> dict[str, str | None]:
    return {
        "course_id": str(code.course_id),
        "expires_at": code.expires_at.isoformat(),
        "revoked_at": code.revoked_at.isoformat() if code.revoked_at else None,
        "status": _state(code, now),
    }


async def _lock_active_course(db: AsyncSession, course_id: uuid.UUID) -> Course:
    course = (
        await db.execute(
            select(Course)
            .where(Course.id == course_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
    ).scalar_one_or_none()
    if course is None:
        raise _error("COURSE_NOT_FOUND", "Course not found", status.HTTP_404_NOT_FOUND)
    if course.status == CourseStatus.ARCHIVED:
        raise _error(
            "COURSE_ARCHIVED",
            "Archived courses are read-only",
            status.HTTP_409_CONFLICT,
        )
    return course


async def _lock_course_code(
    db: AsyncSession, course_id: uuid.UUID, *, latest: bool = True
) -> CourseJoinCode | None:
    statement = select(CourseJoinCode).where(CourseJoinCode.course_id == course_id)
    if latest:
        statement = statement.order_by(
            CourseJoinCode.revoked_at.is_(None).desc(),
            CourseJoinCode.revoked_at.desc(),
            CourseJoinCode.created_at.desc(),
            CourseJoinCode.id.desc(),
        ).limit(1)
    return (
        await db.execute(
            statement.with_for_update().execution_options(populate_existing=True)
        )
    ).scalar_one_or_none()


async def _create_code_row(
    db: AsyncSession, *, course_id: uuid.UUID, expires_at: datetime
) -> CourseJoinCode:
    await db.execute(select(sa.func.pg_advisory_xact_lock(_JOIN_MUTATION_LOCK_ID)))
    while True:
        code = generate_join_code()
        exists = await db.scalar(select(sa.exists().where(CourseJoinCode.code == code)))
        if not exists:
            break
    row = CourseJoinCode(
        id=uuid.uuid4(), course_id=course_id, code=code, expires_at=expires_at
    )
    db.add(row)
    await db.flush()
    return row


def _valid_expiry(expires_at: datetime) -> datetime:
    if expires_at.tzinfo is None:
        raise _error(
            "INVALID_EXPIRY",
            "expires_at must include timezone",
            status.HTTP_422_UNPROCESSABLE_ENTITY,
        )
    expires_at = expires_at.astimezone(UTC)
    if expires_at <= datetime.now(UTC):
        raise _error(
            "INVALID_EXPIRY",
            "expires_at must be in the future",
            status.HTTP_422_UNPROCESSABLE_ENTITY,
        )
    return expires_at


async def create_join_code(
    db: AsyncSession,
    *,
    course_id: uuid.UUID,
    expires_at: datetime,
    actor_user_id: uuid.UUID,
) -> CourseJoinCode:
    await db.execute(select(sa.func.pg_advisory_xact_lock(_JOIN_MUTATION_LOCK_ID)))
    await _lock_active_course(db, course_id)
    expires_at = _valid_expiry(expires_at)
    current = await db.scalar(
        select(CourseJoinCode.id).where(
            CourseJoinCode.course_id == course_id, CourseJoinCode.revoked_at.is_(None)
        )
    )
    if current is not None:
        raise _error(
            "JOIN_CODE_EXISTS",
            "Course already has an active join code",
            status.HTTP_409_CONFLICT,
        )
    row = await _create_code_row(db, course_id=course_id, expires_at=expires_at)
    await record_audit(
        db,
        actor_user_id=actor_user_id,
        resource_type="CourseJoinCode",
        resource_id=row.id,
        action="CREATE_JOIN_CODE",
        after=_snapshot(row),
        reason="Course join code created",
    )
    return row


async def get_join_code(db: AsyncSession, *, course_id: uuid.UUID) -> CourseJoinCode:
    row = await _lock_course_code(db, course_id)
    if row is None:
        raise _error(
            "JOIN_CODE_NOT_FOUND", "Join code not found", status.HTTP_404_NOT_FOUND
        )
    return row


async def update_join_code(
    db: AsyncSession,
    *,
    course_id: uuid.UUID,
    expires_at: datetime,
    actor_user_id: uuid.UUID,
) -> CourseJoinCode:
    await db.execute(select(sa.func.pg_advisory_xact_lock(_JOIN_MUTATION_LOCK_ID)))
    await _lock_active_course(db, course_id)
    row = await _lock_course_code(db, course_id)
    if row is None:
        raise _error(
            "JOIN_CODE_NOT_FOUND", "Join code not found", status.HTTP_404_NOT_FOUND
        )
    if row.revoked_at is not None:
        raise _error("JOIN_CODE_REVOKED", "Join code is revoked", status.HTTP_410_GONE)
    expires_at = _valid_expiry(expires_at)
    before = _snapshot(row)
    row.expires_at = expires_at
    await db.flush()
    await record_audit(
        db,
        actor_user_id=actor_user_id,
        resource_type="CourseJoinCode",
        resource_id=row.id,
        action="UPDATE_JOIN_CODE",
        before=before,
        after=_snapshot(row),
        reason="Course join code expiry updated",
    )
    return row


async def revoke_join_code(
    db: AsyncSession, *, course_id: uuid.UUID, actor_user_id: uuid.UUID
) -> CourseJoinCode:
    await db.execute(select(sa.func.pg_advisory_xact_lock(_JOIN_MUTATION_LOCK_ID)))
    await _lock_active_course(db, course_id)
    row = await _lock_course_code(db, course_id)
    if row is None:
        raise _error(
            "JOIN_CODE_NOT_FOUND", "Join code not found", status.HTTP_404_NOT_FOUND
        )
    if row.revoked_at is not None:
        raise _error(
            "JOIN_CODE_REVOKED", "Join code is already revoked", status.HTTP_410_GONE
        )
    before = _snapshot(row)
    row.revoked_at = datetime.now(UTC)
    await db.flush()
    await record_audit(
        db,
        actor_user_id=actor_user_id,
        resource_type="CourseJoinCode",
        resource_id=row.id,
        action="REVOKE_JOIN_CODE",
        before=before,
        after=_snapshot(row),
        reason="Course join code revoked",
    )
    return row


async def regenerate_join_code(
    db: AsyncSession,
    *,
    course_id: uuid.UUID,
    expires_at: datetime,
    actor_user_id: uuid.UUID,
) -> CourseJoinCode:
    await db.execute(select(sa.func.pg_advisory_xact_lock(_JOIN_MUTATION_LOCK_ID)))
    course = await _lock_active_course(db, course_id)
    expires_at = _valid_expiry(expires_at)
    old = await _lock_course_code(db, course.id)
    before = _snapshot(old) if old is not None else None
    if old is not None and old.revoked_at is None:
        old.revoked_at = datetime.now(UTC)
        await db.flush()
    row = await _create_code_row(db, course_id=course.id, expires_at=expires_at)
    await record_audit(
        db,
        actor_user_id=actor_user_id,
        resource_type="CourseJoinCode",
        resource_id=row.id,
        action="REGENERATE_JOIN_CODE",
        before=before,
        after=_snapshot(row),
        reason="Course join code regenerated",
    )
    return row


async def enforce_join_rate_limit(
    db: AsyncSession, *, user_id: uuid.UUID, request: Request
) -> None:
    settings = get_settings()
    ip = request.client.host if request.client else "unknown"
    subjects = (f"account:{user_id}", f"ip:{ip}")
    now = datetime.now(UTC)
    retry_after = 0
    for subject in subjects:
        digest = hashlib.sha256(subject.encode()).hexdigest()
        lock_id = int.from_bytes(
            hashlib.sha256(digest.encode()).digest()[:8], "big", signed=True
        )
        await db.execute(select(sa.func.pg_advisory_xact_lock(lock_id)))
        row = await db.scalar(
            select(JoinRateLimit)
            .where(JoinRateLimit.subject_hash == digest)
            .with_for_update()
        )
        if row is None or now - row.window_started_at >= timedelta(
            seconds=settings.join_rate_limit_window_seconds
        ):
            if row is None:
                row = JoinRateLimit(
                    id=uuid.uuid4(),
                    subject_hash=digest,
                    window_started_at=now,
                    request_count=1,
                )
                db.add(row)
            else:
                row.window_started_at = now
                row.request_count = 1
        else:
            row.request_count += 1
            retry_after = max(
                retry_after,
                math.ceil(
                    settings.join_rate_limit_window_seconds
                    - (now - row.window_started_at).total_seconds()
                ),
            )
        if row.request_count > settings.join_rate_limit_max_requests:
            await db.flush()
            await db.commit()
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail={
                    "code": "JOIN_RATE_LIMITED",
                    "message": "Too many join attempts",
                },
                headers={"Retry-After": str(max(1, retry_after))},
            )
    await db.flush()


async def join_course(
    db: AsyncSession,
    *,
    code: str,
    user: User,
    request: Request,
) -> tuple[CourseJoinOutcome, Membership, Course]:
    if UserRole.STUDENT not in user.roles:
        raise HTTPException(status_code=403, detail="Insufficient permissions")
    await enforce_join_rate_limit(db, user_id=user.id, request=request)
    normalized = normalize_join_code(code)
    if len(normalized) != CODE_LENGTH or any(
        c not in CODE_ALPHABET for c in normalized
    ):
        await _raise_after_commit(
            db,
            _error(
                "JOIN_CODE_INVALID", "Join code is invalid", status.HTTP_404_NOT_FOUND
            ),
        )
    locator = (
        await db.execute(
            select(CourseJoinCode.id, CourseJoinCode.course_id).where(
                CourseJoinCode.code == normalized
            )
        )
    ).one_or_none()
    if locator is None:
        await _raise_after_commit(
            db,
            _error(
                "JOIN_CODE_INVALID", "Join code is invalid", status.HTTP_404_NOT_FOUND
            ),
        )
    try:
        course = await _lock_active_course(db, locator.course_id)
    except HTTPException as error:
        await _raise_after_commit(db, error)
    row = await db.scalar(
        select(CourseJoinCode)
        .where(CourseJoinCode.id == locator.id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if row is None:
        await _raise_after_commit(
            db,
            _error(
                "JOIN_CODE_INVALID", "Join code is invalid", status.HTTP_404_NOT_FOUND
            ),
        )
    if row.revoked_at is not None:
        await _raise_after_commit(
            db,
            _error("JOIN_CODE_REVOKED", "Join code is revoked", status.HTTP_410_GONE),
        )
    if row.expires_at <= datetime.now(UTC):
        await _raise_after_commit(
            db,
            _error("JOIN_CODE_EXPIRED", "Join code is expired", status.HTTP_410_GONE),
        )
    membership = await db.scalar(
        select(Membership)
        .where(
            Membership.course_id == course.id,
            Membership.user_id == user.id,
            Membership.role == MembershipRole.STUDENT,
        )
        .with_for_update()
    )
    now = datetime.now(UTC)
    if membership is not None and membership.status == MembershipStatus.ACTIVE:
        return CourseJoinOutcome.ALREADY_MEMBER, membership, course
    if membership is None:
        membership = Membership(
            id=uuid.uuid4(),
            course_id=course.id,
            user_id=user.id,
            role=MembershipRole.STUDENT,
            status=MembershipStatus.ACTIVE,
            joined_via=MembershipJoinedVia.CODE,
            joined_at=now,
        )
        db.add(membership)
        outcome = CourseJoinOutcome.JOINED
        action = "JOIN_MEMBER"
        before = None
    else:
        before = {
            "course_id": str(membership.course_id),
            "user_id": str(membership.user_id),
            "status": membership.status.value,
            "joined_via": membership.joined_via.value,
            "joined_at": membership.joined_at.isoformat(),
        }
        membership.status = MembershipStatus.ACTIVE
        membership.joined_via = MembershipJoinedVia.CODE
        membership.joined_at = now
        outcome = CourseJoinOutcome.REACTIVATED
        action = "REACTIVATE_MEMBER"
    await db.flush()
    await record_audit(
        db,
        actor_user_id=user.id,
        resource_type="Membership",
        resource_id=membership.id,
        action=action,
        before=before,
        after={
            "course_id": str(membership.course_id),
            "user_id": str(membership.user_id),
            "status": membership.status.value,
            "joined_via": membership.joined_via.value,
            "joined_at": membership.joined_at.isoformat(),
        },
        reason="Course joined by code",
    )
    return outcome, membership, course


def render_qr_svg(code: str) -> str:
    image = qrcode.make(join_url(code), image_factory=SvgPathImage)
    output = io.BytesIO()
    image.save(output)
    return output.getvalue().decode("utf-8")
