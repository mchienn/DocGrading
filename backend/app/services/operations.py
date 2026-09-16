from __future__ import annotations

import asyncio
import re
import uuid
from datetime import UTC, datetime
from typing import Any

import sqlalchemy as sa
from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.schemas_operations import (
    AdminAnalysisJobDetailResponse,
    AdminAnalysisJobListItem,
    AdminAnalysisJobListResponse,
    AdminAuditEventListResponse,
    AdminAuditEventResponse,
    AdminDashboardResponse,
    AdminUserCreateRequest,
    AdminUserListResponse,
    AdminUserResponse,
    AdminUserUpdateRequest,
    CourseSubmissionCount,
)
from app.models.analysis import AnalysisJob
from app.models.assignment import Assignment
from app.models.audit import AuditEvent
from app.models.course import Course
from app.models.enums import (
    AnalysisJobStatus,
    ReviewRequestStatus,
    UserRole,
    UserStatus,
)
from app.models.identity import User
from app.models.review import ReviewRequest
from app.models.submission import DocumentVersion, Submission
from app.services.audit import record_audit
from app.services.auth import hash_password

_SENSITIVE_KEY_PARTS = (
    "password",
    "secret",
    "credential",
    "token",
    "cookie",
    "storage_key",
    "object_key",
    "session_id",
    "api_key",
    "access_key",
    "authorization",
    "upload_url",
    "private_key",
    "connection_string",
    "dsn",
    "url",
    "uri",
    "provider",
    "config",
    "snapshot",
    "pdf",
    "raw",
)
_SENSITIVE_KEYS = {"fields"}
_SENSITIVE_ASSIGNMENT = re.compile(
    r"(?i)(?:"
    r"(?P<quote>[\"'])(?P<quoted_key>[a-z][a-z0-9_. -]{0,127})(?P=quote)|"
    r"(?P<key>(?:[a-z]+[ \t]+){1,3}[a-z]+|[a-z][a-z0-9_.-]{0,127})"
    r")(?P<separator>\s*[:=]\s*)"
    r"(?P<value>\"(?:\\.|[^\"\\])*\"|'(?:\\.|[^'\\])*'|"
    r"(?:(?:bearer|basic)\s+)?[^\s,;}\]\"']+)"
)
_STORAGE_PATH = re.compile(r"(?i)\buploads/[^\s'\",;}]+")
_CAMEL_CASE_BOUNDARY = re.compile(r"(?<=[a-z0-9])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z])")
_KEY_SEPARATOR = re.compile(r"[-\s]+")
_USER_ADMIN_MUTATION_LOCK_ID = 0x544F_3138
_AUDIT_SAFE_FIELDS: dict[str, frozenset[str]] = {
    "AnalysisJob": frozenset({"status", "attempt_count", "error_code"}),
    "Assignment": frozenset(
        {
            "title",
            "description",
            "course_id",
            "rubric_version_id",
            "due_at",
            "max_submissions",
            "status",
            "published_at",
            "closed_at",
        }
    ),
    "Course": frozenset({"code", "name", "term", "status"}),
    "CourseInvite": frozenset({"course_id", "status"}),
    "Membership": frozenset(
        {"course_id", "user_id", "status", "joined_via", "joined_at"}
    ),
    "CriterionVersion": frozenset(
        {
            "code",
            "title",
            "description",
            "scope",
            "weight",
            "position",
            "is_enabled",
            "evaluation_method",
            "rubric_version_id",
        }
    ),
    "DocumentVersion": frozenset(
        {
            "status",
            "failure_code",
            "approved_at",
            "approved_by_user_id",
            "published_result_id",
            "published_at",
            "version_number",
        }
    ),
    "Finding": frozenset({"decision", "score", "analysis_job_id"}),
    "ReviewLock": frozenset(
        {
            "submission_id",
            "reviewer_user_id",
            "acquired_at",
            "expires_at",
            "released",
        }
    ),
    "ReviewRequest": frozenset(
        {"status", "response", "responded_by_user_id", "responded_at"}
    ),
    "RubricVersion": frozenset(
        {
            "name",
            "description",
            "calculation_method",
            "status",
            "published_at",
            "total_weight",
            "source_version_id",
            "id",
            "version_number",
            "criteria_count",
        }
    ),
    "Session": frozenset(),
    "User": frozenset({"roles", "status"}),
}


def _normalize_key(key: object) -> str:
    return _KEY_SEPARATOR.sub("_", _CAMEL_CASE_BOUNDARY.sub("_", str(key))).lower()


def _is_sensitive_key(key: object) -> bool:
    normalized = _normalize_key(key)
    collapsed = normalized.replace("_", "")
    return (
        normalized in _SENSITIVE_KEYS
        or "key" in normalized.split("_")
        or any(
            part in normalized or part.replace("_", "") in collapsed
            for part in _SENSITIVE_KEY_PARTS
        )
    )


def _redact_assignments(value: str) -> str:
    parts: list[str] = []
    cursor = 0
    search_from = 0
    while match := _SENSITIVE_ASSIGNMENT.search(value, search_from):
        key = match.group("quoted_key") or match.group("key")
        if not _is_sensitive_key(key):
            raw_value = match.group("value")
            search_from = match.start("value") + (1 if raw_value[0] in "\"'" else 0)
            continue

        parts.append(value[cursor : match.start()])
        key_quote = match.group("quote") or ""
        raw_value = match.group("value")
        value_quote = (
            raw_value[0]
            if raw_value[0] in "\"'" and raw_value[-1] == raw_value[0]
            else ""
        )
        parts.append(
            f"{key_quote}{key}{key_quote}{match.group('separator')}"
            f"{value_quote}[REDACTED]{value_quote}"
        )
        cursor = match.end()
        search_from = cursor

    parts.append(value[cursor:])
    return "".join(parts)


def _redact_text(value: str) -> str:
    value = _STORAGE_PATH.sub("[REDACTED]", value)
    return _redact_assignments(value)


def _redact_value(value: Any) -> Any:
    if isinstance(value, dict):
        result = {}
        for key, item in value.items():
            if _is_sensitive_key(key):
                result[key] = "[REDACTED]"
            else:
                result[key] = _redact_value(item)
        return result
    if isinstance(value, list):
        return [_redact_value(item) for item in value]
    if isinstance(value, str):
        return _redact_text(value)
    return value


def _redact_snapshot(
    resource_type: str, snapshot: dict[str, Any] | None
) -> dict[str, Any] | None:
    if snapshot is None:
        return None
    safe_fields = _AUDIT_SAFE_FIELDS.get(resource_type, frozenset())
    return {
        key: _redact_value(value) if key in safe_fields else "[REDACTED]"
        for key, value in snapshot.items()
    }


def _escape_like(value: str) -> str:
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


async def list_users(
    db: AsyncSession,
    *,
    role: UserRole | None,
    user_status: UserStatus | None,
    search: str | None,
    page: int,
    page_size: int,
) -> AdminUserListResponse:
    filters = []
    if role is not None:
        filters.append(User.roles.any(role))
    if user_status is not None:
        filters.append(User.status == user_status)
    if search is not None and (search := search.strip()):
        pattern = f"%{_escape_like(search)}%"
        filters.append(
            sa.or_(
                User.email.ilike(pattern, escape="\\"),
                User.display_name.ilike(pattern, escape="\\"),
            )
        )

    total = (
        await db.execute(sa.select(sa.func.count()).select_from(User).where(*filters))
    ).scalar_one()
    users = list(
        (
            await db.execute(
                sa.select(User)
                .where(*filters)
                .order_by(User.created_at.desc(), User.id)
                .offset((page - 1) * page_size)
                .limit(page_size)
            )
        ).scalars()
    )
    return AdminUserListResponse(
        items=[AdminUserResponse.model_validate(user) for user in users],
        page=page,
        page_size=page_size,
        total=total,
    )


async def get_user(db: AsyncSession, user_id: uuid.UUID) -> AdminUserResponse:
    user = await db.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")
    return AdminUserResponse.model_validate(user)


async def create_user(
    db: AsyncSession,
    *,
    body: AdminUserCreateRequest,
    actor_user_id: uuid.UUID,
) -> AdminUserResponse:
    await db.execute(
        sa.select(sa.func.pg_advisory_xact_lock(_USER_ADMIN_MUTATION_LOCK_ID))
    )
    if await db.scalar(
        sa.select(sa.exists().where(sa.func.lower(User.email) == body.email))
    ):
        raise HTTPException(status_code=409, detail="Email is already registered")
    user = User(
        email=body.email,
        display_name=body.display_name,
        password_hash=await asyncio.to_thread(hash_password, body.password),
        roles=[role for role in UserRole if role in body.roles],
        status=UserStatus.ACTIVE,
    )
    db.add(user)
    await db.flush()
    await record_audit(
        db,
        actor_user_id=actor_user_id,
        resource_type="User",
        resource_id=user.id,
        action="CREATE",
        before=None,
        after={
            "roles": [role.value for role in user.roles],
            "status": user.status.value,
        },
        reason="Administrator created account",
    )
    await db.flush()
    await db.refresh(user)
    return AdminUserResponse.model_validate(user)


async def update_user(
    db: AsyncSession,
    *,
    user_id: uuid.UUID,
    body: AdminUserUpdateRequest,
    actor_user_id: uuid.UUID,
    expected_revision: int | None = None,
) -> AdminUserResponse:
    # ponytail: one advisory lock serializes rare Admin account writes; shard if needed.
    await db.execute(
        sa.select(sa.func.pg_advisory_xact_lock(_USER_ADMIN_MUTATION_LOCK_ID))
    )
    user = (
        await db.execute(
            sa.select(User)
            .where(User.id == user_id)
            .execution_options(populate_existing=True)
            .with_for_update()
        )
    ).scalar_one_or_none()
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")
    if expected_revision is not None and user.revision != expected_revision:
        raise HTTPException(
            status_code=status.HTTP_412_PRECONDITION_FAILED,
            detail="User revision conflict",
        )

    requested_roles = set(body.roles) if body.roles is not None else set(user.roles)
    canonical_roles = [role for role in UserRole if role in requested_roles]
    requested_status = body.status if body.status is not None else user.status

    if user.id == actor_user_id and (
        (body.roles is not None and UserRole.ADMIN not in requested_roles)
        or body.status is UserStatus.LOCKED
    ):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "Administrators cannot remove their own ADMIN role "
                "or lock their own account"
            ),
        )

    was_active_admin = UserRole.ADMIN in user.roles and user.status is UserStatus.ACTIVE
    will_be_active_admin = (
        UserRole.ADMIN in requested_roles and requested_status is UserStatus.ACTIVE
    )
    if was_active_admin and not will_be_active_admin:
        has_other_active_admin = await db.scalar(
            sa.select(
                sa.exists().where(
                    User.id != user.id,
                    User.status == UserStatus.ACTIVE,
                    User.roles.any(UserRole.ADMIN),
                )
            )
        )
        if not has_other_active_admin:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="At least one active administrator must remain",
            )

    role_change: tuple[list[UserRole], list[UserRole]] | None = None
    if set(user.roles) != requested_roles:
        role_change = (list(user.roles), canonical_roles)
        user.roles = canonical_roles

    status_change: tuple[UserStatus, UserStatus] | None = None
    if user.status is not requested_status:
        status_change = (user.status, requested_status)
        user.status = requested_status

    if role_change is None and status_change is None:
        return AdminUserResponse.model_validate(user)

    user.revision += 1
    if role_change is not None:
        before_roles, after_roles = role_change
        await record_audit(
            db,
            actor_user_id=actor_user_id,
            resource_type="User",
            resource_id=user.id,
            action="ROLE_CHANGE",
            before={"roles": [role.value for role in before_roles]},
            after={"roles": [role.value for role in after_roles]},
            reason=body.reason,
        )
    if status_change is not None:
        before_status, after_status = status_change
        await record_audit(
            db,
            actor_user_id=actor_user_id,
            resource_type="User",
            resource_id=user.id,
            action="LOCK" if after_status is UserStatus.LOCKED else "UNLOCK",
            before={"status": before_status.value},
            after={"status": after_status.value},
            reason=body.reason,
        )
    await db.flush()
    await db.refresh(user)
    return AdminUserResponse.model_validate(user)


def _analysis_job_select(*, include_error_detail: bool = False):  # noqa: ANN202
    columns = [
        AnalysisJob.id.label("id"),
        Course.id.label("course_id"),
        Course.code.label("course_code"),
        Course.name.label("course_name"),
        Assignment.id.label("assignment_id"),
        Submission.id.label("submission_id"),
        AnalysisJob.document_version_id.label("document_version_id"),
        AnalysisJob.rubric_version_id.label("rubric_version_id"),
        AnalysisJob.status.label("status"),
        AnalysisJob.attempt_count.label("attempt_count"),
        AnalysisJob.max_attempts.label("max_attempts"),
        AnalysisJob.error_code.label("error_code"),
        AnalysisJob.queued_at.label("queued_at"),
        AnalysisJob.started_at.label("started_at"),
        AnalysisJob.finished_at.label("finished_at"),
        AnalysisJob.created_at.label("created_at"),
        AnalysisJob.updated_at.label("updated_at"),
    ]
    if include_error_detail:
        columns.append(AnalysisJob.error_detail.label("error_detail"))
    return (
        sa.select(*columns)
        .select_from(AnalysisJob)
        .join(
            DocumentVersion,
            DocumentVersion.id == AnalysisJob.document_version_id,
        )
        .join(Submission, Submission.id == DocumentVersion.submission_id)
        .join(Assignment, Assignment.id == Submission.assignment_id)
        .join(Course, Course.id == Assignment.course_id)
    )


async def list_analysis_jobs(
    db: AsyncSession,
    *,
    job_status: AnalysisJobStatus | None,
    course_id: uuid.UUID | None,
    page: int,
    page_size: int,
) -> AdminAnalysisJobListResponse:
    filters = []
    if job_status is not None:
        filters.append(AnalysisJob.status == job_status)
    if course_id is not None:
        filters.append(Course.id == course_id)

    total = (
        await db.execute(
            sa.select(sa.func.count())
            .select_from(AnalysisJob)
            .join(
                DocumentVersion,
                DocumentVersion.id == AnalysisJob.document_version_id,
            )
            .join(Submission, Submission.id == DocumentVersion.submission_id)
            .join(Assignment, Assignment.id == Submission.assignment_id)
            .join(Course, Course.id == Assignment.course_id)
            .where(*filters)
        )
    ).scalar_one()
    rows = (
        await db.execute(
            _analysis_job_select()
            .where(*filters)
            .order_by(AnalysisJob.queued_at.desc(), AnalysisJob.id)
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
    ).mappings()
    return AdminAnalysisJobListResponse(
        items=[AdminAnalysisJobListItem.model_validate(row) for row in rows],
        page=page,
        page_size=page_size,
        total=total,
    )


async def get_analysis_job(
    db: AsyncSession, job_id: uuid.UUID
) -> AdminAnalysisJobDetailResponse:
    row = (
        (
            await db.execute(
                _analysis_job_select(include_error_detail=True).where(
                    AnalysisJob.id == job_id
                )
            )
        )
        .mappings()
        .one_or_none()
    )
    if row is None:
        raise HTTPException(status_code=404, detail="Analysis job not found")
    values = dict(row)
    if values["error_detail"] is not None:
        values["error_detail"] = _redact_text(values["error_detail"])
    return AdminAnalysisJobDetailResponse.model_validate(values)


async def list_audit_events(
    db: AsyncSession,
    *,
    actor_user_id: uuid.UUID | None,
    resource_type: str | None,
    from_time: datetime | None,
    to_time: datetime | None,
    page: int,
    page_size: int,
) -> AdminAuditEventListResponse:
    for name, value in (("from_time", from_time), ("to_time", to_time)):
        if value is not None and (value.tzinfo is None or value.utcoffset() is None):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail=f"{name} must include a timezone",
            )
    from_time = from_time.astimezone(UTC) if from_time is not None else None
    to_time = to_time.astimezone(UTC) if to_time is not None else None
    if from_time is not None and to_time is not None and from_time > to_time:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="from_time must not be after to_time",
        )
    filters = []
    if actor_user_id is not None:
        filters.append(AuditEvent.actor_user_id == actor_user_id)
    if resource_type is not None:
        resource_type = resource_type.strip()
        if not resource_type:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="resource_type must not be blank",
            )
        filters.append(AuditEvent.resource_type == resource_type)
    if from_time is not None:
        filters.append(AuditEvent.occurred_at >= from_time)
    if to_time is not None:
        filters.append(AuditEvent.occurred_at <= to_time)

    total = (
        await db.execute(
            sa.select(sa.func.count()).select_from(AuditEvent).where(*filters)
        )
    ).scalar_one()
    events = list(
        (
            await db.execute(
                sa.select(AuditEvent)
                .where(*filters)
                .order_by(AuditEvent.occurred_at.desc(), AuditEvent.id)
                .offset((page - 1) * page_size)
                .limit(page_size)
            )
        ).scalars()
    )
    return AdminAuditEventListResponse(
        items=[
            AdminAuditEventResponse(
                id=event.id,
                resource_type=event.resource_type,
                resource_id=event.resource_id,
                action=event.action,
                actor_type=event.actor_type,
                actor_user_id=event.actor_user_id,
                before=_redact_snapshot(event.resource_type, event.before),
                after=_redact_snapshot(event.resource_type, event.after),
                reason=_redact_text(event.reason),
                occurred_at=event.occurred_at,
            )
            for event in events
        ],
        page=page,
        page_size=page_size,
        total=total,
    )


async def _jobs_by_status(
    db: AsyncSession,
) -> dict[AnalysisJobStatus, int]:
    job_rows = (
        await db.execute(
            sa.select(AnalysisJob.status, sa.func.count(AnalysisJob.id)).group_by(
                AnalysisJob.status
            )
        )
    ).all()
    counts = {job_status: 0 for job_status in AnalysisJobStatus}
    counts.update(dict(job_rows))
    return counts


async def get_metrics(db: AsyncSession) -> str:
    jobs_by_status = await _jobs_by_status(db)
    average_active_age = (
        await db.execute(
            sa.select(
                sa.func.coalesce(
                    sa.func.avg(
                        sa.extract(
                            "epoch",
                            sa.func.now() - AnalysisJob.queued_at,
                        )
                    ),
                    0,
                )
            ).where(
                AnalysisJob.status.in_(
                    (AnalysisJobStatus.QUEUED, AnalysisJobStatus.RUNNING)
                )
            )
        )
    ).scalar_one()
    lines = [
        "# HELP docgrading_analysis_jobs Current analysis jobs by status.",
        "# TYPE docgrading_analysis_jobs gauge",
        *[
            f'docgrading_analysis_jobs{{status="{job_status.value}"}} '
            f"{jobs_by_status[job_status]}"
            for job_status in AnalysisJobStatus
        ],
        "# HELP docgrading_analysis_queue_depth Current queued analysis jobs.",
        "# TYPE docgrading_analysis_queue_depth gauge",
        f"docgrading_analysis_queue_depth "
        f"{jobs_by_status[AnalysisJobStatus.QUEUED]}",
        "# HELP docgrading_analysis_job_age_seconds_avg "
        "Average age of queued and running jobs.",
        "# TYPE docgrading_analysis_job_age_seconds_avg gauge",
        f"docgrading_analysis_job_age_seconds_avg {float(average_active_age):.6f}",
    ]
    return "\n".join(lines) + "\n"


async def get_dashboard(db: AsyncSession) -> AdminDashboardResponse:
    jobs_by_status = await _jobs_by_status(db)

    course_rows = (
        await db.execute(
            sa.select(
                Course.id,
                Course.code,
                Course.name,
                sa.func.count(Submission.id),
            )
            .select_from(Course)
            .outerjoin(Assignment, Assignment.course_id == Course.id)
            .outerjoin(Submission, Submission.assignment_id == Assignment.id)
            .group_by(Course.id, Course.code, Course.name)
            .order_by(Course.code, Course.id)
        )
    ).all()
    open_review_requests = (
        await db.execute(
            sa.select(sa.func.count())
            .select_from(ReviewRequest)
            .where(ReviewRequest.status == ReviewRequestStatus.OPEN)
        )
    ).scalar_one()
    return AdminDashboardResponse(
        jobs_by_status=jobs_by_status,
        submissions_by_course=[
            CourseSubmissionCount(
                course_id=course_id,
                course_code=course_code,
                course_name=course_name,
                submission_count=submission_count,
            )
            for course_id, course_code, course_name, submission_count in course_rows
        ],
        open_review_requests=open_review_requests,
    )
