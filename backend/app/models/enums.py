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
    REMOVED = "REMOVED"


class MembershipJoinedVia(StrEnum):
    MANUAL = "MANUAL"
    CODE = "CODE"


class MembershipAddOutcome(StrEnum):
    ADDED = "ADDED"
    REACTIVATED = "REACTIVATED"
    INVITED = "INVITED"


class CourseJoinOutcome(StrEnum):
    JOINED = "JOINED"
    REACTIVATED = "REACTIVATED"
    ALREADY_MEMBER = "ALREADY_MEMBER"


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


class LLMProvider(StrEnum):
    OPENAI = "OPENAI"
    ANTHROPIC = "ANTHROPIC"
    GEMINI = "GEMINI"
    DEEPSEEK = "DEEPSEEK"
    OPENCODE_ZEN = "OPENCODE_ZEN"
    BEDROCK = "BEDROCK"


class LLMCredentialSource(StrEnum):
    NONE = "NONE"
    ENVIRONMENT = "ENVIRONMENT"
    STORED = "STORED"


class LLMCatalogStatus(StrEnum):
    UNTESTED = "UNTESTED"
    CATALOG_VERIFIED = "CATALOG_VERIFIED"
    INVALID_CREDENTIAL = "INVALID_CREDENTIAL"
    RATE_LIMITED = "RATE_LIMITED"
    UNAVAILABLE = "UNAVAILABLE"
    TIMEOUT = "TIMEOUT"
    INVALID_RESPONSE = "INVALID_RESPONSE"


class LLMProtocol(StrEnum):
    OPENAI_CHAT = "OPENAI_CHAT"
    OPENAI_RESPONSES = "OPENAI_RESPONSES"
    ANTHROPIC_MESSAGES = "ANTHROPIC_MESSAGES"
    GEMINI_GENERATE_CONTENT = "GEMINI_GENERATE_CONTENT"
    BEDROCK_CONVERSE = "BEDROCK_CONVERSE"


class LLMTask(StrEnum):
    CITATION_SEMANTIC = "CITATION_SEMANTIC"


class LLMRouteState(StrEnum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    DISABLED = "DISABLED"


def llm_provider_protocols(provider: LLMProvider) -> tuple[LLMProtocol, ...]:
    if provider is LLMProvider.OPENCODE_ZEN:
        return (
            LLMProtocol.OPENAI_CHAT,
            LLMProtocol.OPENAI_RESPONSES,
            LLMProtocol.ANTHROPIC_MESSAGES,
            LLMProtocol.GEMINI_GENERATE_CONTENT,
        )
    return {
        LLMProvider.OPENAI: (LLMProtocol.OPENAI_CHAT, LLMProtocol.OPENAI_RESPONSES),
        LLMProvider.ANTHROPIC: (LLMProtocol.ANTHROPIC_MESSAGES,),
        LLMProvider.GEMINI: (LLMProtocol.GEMINI_GENERATE_CONTENT,),
        LLMProvider.DEEPSEEK: (LLMProtocol.OPENAI_CHAT,),
        LLMProvider.BEDROCK: (LLMProtocol.BEDROCK_CONVERSE,),
    }[provider]


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
