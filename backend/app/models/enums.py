from enum import StrEnum
from typing import Any

import sqlalchemy as sa


class UserRole(StrEnum):
    ADMIN = "ADMIN"
    TEACHER = "TEACHER"
    STUDENT = "STUDENT"


class UserStatus(StrEnum):
    ACTIVE = "ACTIVE"
    LOCKED = "LOCKED"


class MembershipRole(StrEnum):
    TEACHER = "TEACHER"
    STUDENT = "STUDENT"


class MembershipStatus(StrEnum):
    ACTIVE = "ACTIVE"
    INACTIVE = "INACTIVE"


class CourseStatus(StrEnum):
    ACTIVE = "ACTIVE"
    ARCHIVED = "ARCHIVED"


class AssignmentStatus(StrEnum):
    DRAFT = "DRAFT"
    OPEN = "OPEN"
    CLOSED = "CLOSED"
    ARCHIVED = "ARCHIVED"


class RubricStatus(StrEnum):
    DRAFT = "DRAFT"
    PUBLISHED = "PUBLISHED"
    ARCHIVED = "ARCHIVED"


class DocumentStatus(StrEnum):
    UPLOADING = "UPLOADING"
    VALIDATING = "VALIDATING"
    INVALID = "INVALID"
    QUEUED = "QUEUED"
    PROCESSING = "PROCESSING"
    AWAITING_REVIEW = "AWAITING_REVIEW"
    APPROVED = "APPROVED"
    PUBLISHED = "PUBLISHED"
    PROCESSING_FAILED = "PROCESSING_FAILED"


class AnalysisJobStatus(StrEnum):
    QUEUED = "QUEUED"
    RUNNING = "RUNNING"
    DONE = "DONE"
    ERROR = "ERROR"


class AuditActorType(StrEnum):
    USER = "USER"
    SYSTEM = "SYSTEM"


class ReviewDecisionType(StrEnum):
    ACCEPT = "ACCEPT"
    EDIT = "EDIT"
    REJECT = "REJECT"


class ReviewRequestStatus(StrEnum):
    OPEN = "OPEN"
    RESOLVED = "RESOLVED"
    REJECTED = "REJECTED"


class NotificationType(StrEnum):
    ANALYSIS_JOB_ERROR = "ANALYSIS_JOB_ERROR"
    RESULT_PUBLISHED = "RESULT_PUBLISHED"
    REVIEW_REQUEST_CREATED = "REVIEW_REQUEST_CREATED"
    REVIEW_REQUEST_RESOLVED = "REVIEW_REQUEST_RESOLVED"
    REVIEW_REQUEST_REJECTED = "REVIEW_REQUEST_REJECTED"


NOTIFICATION_PAYLOAD_KEYS: dict[NotificationType, frozenset[str]] = {
    NotificationType.ANALYSIS_JOB_ERROR: frozenset({"analysis_job_id"}),
    NotificationType.RESULT_PUBLISHED: frozenset(
        {"published_result_version_id", "submission_id"}
    ),
    NotificationType.REVIEW_REQUEST_CREATED: frozenset({"review_request_id"}),
    NotificationType.REVIEW_REQUEST_RESOLVED: frozenset({"review_request_id"}),
    NotificationType.REVIEW_REQUEST_REJECTED: frozenset({"review_request_id"}),
}


def pg_enum(
    enum_cls: type[StrEnum],
    name: str,
    *,
    native_enum: bool = True,
    **kwargs: Any,
) -> sa.Enum:
    """Helper creating named native SQLAlchemy Enum values via values_callable and
    validate_strings.
    """
    return sa.Enum(
        enum_cls,
        name=name,
        native_enum=native_enum,
        values_callable=lambda enum: [member.value for member in enum],
        validate_strings=True,
        **kwargs,
    )
