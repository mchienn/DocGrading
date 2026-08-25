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
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class AuditActorType(StrEnum):
    USER = "USER"
    SYSTEM = "SYSTEM"


def pg_enum(
    enum_cls: type[StrEnum],
    name: str,
    *,
    native_enum: bool = True,
    create_type: bool = True,
    **kwargs: Any,
) -> sa.Enum:
    """Helper creating named native SQLAlchemy Enum values via values_callable and validate_strings."""
    return sa.Enum(
        enum_cls,
        name=name,
        native_enum=native_enum,
        create_type=create_type,
        values_callable=lambda enum: [member.value for member in enum],
        validate_strings=True,
        **kwargs,
    )
