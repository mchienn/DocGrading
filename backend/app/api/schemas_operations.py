from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field, field_validator, model_validator

from app.models.enums import (
    AnalysisJobStatus,
    AuditActorType,
    UserRole,
    UserStatus,
)


class AdminUserResponse(BaseModel):
    id: uuid.UUID
    email: str
    display_name: str
    roles: list[UserRole]
    status: UserStatus
    revision: int
    created_at: datetime
    updated_at: datetime

    model_config = {"extra": "forbid", "from_attributes": True}


class AdminUserListResponse(BaseModel):
    items: list[AdminUserResponse]
    page: int
    page_size: int
    total: int

    model_config = {"extra": "forbid"}


class AdminUserUpdateRequest(BaseModel):
    roles: list[UserRole] | None = Field(default=None, min_length=1, max_length=3)
    status: UserStatus | None = None
    reason: str = Field(min_length=1, max_length=1000)

    model_config = {"extra": "forbid"}

    @field_validator("roles")
    @classmethod
    def require_unique_roles(
        cls, value: list[UserRole] | None
    ) -> list[UserRole] | None:
        if value is not None and len(set(value)) != len(value):
            raise ValueError("roles must be unique")
        return value

    @field_validator("reason")
    @classmethod
    def require_nonblank_reason(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("reason must not be blank")
        return value

    @model_validator(mode="after")
    def require_change(self) -> AdminUserUpdateRequest:
        if self.roles is None and self.status is None:
            raise ValueError("roles or status is required")
        return self


class AdminAnalysisJobListItem(BaseModel):
    id: uuid.UUID
    course_id: uuid.UUID
    course_code: str
    course_name: str
    assignment_id: uuid.UUID
    submission_id: uuid.UUID
    document_version_id: uuid.UUID
    rubric_version_id: uuid.UUID
    status: AnalysisJobStatus
    attempt_count: int
    max_attempts: int
    error_code: str | None
    queued_at: datetime
    started_at: datetime | None
    finished_at: datetime | None
    created_at: datetime
    updated_at: datetime

    model_config = {"extra": "forbid"}


class AdminAnalysisJobDetailResponse(AdminAnalysisJobListItem):
    error_detail: str | None


class AdminAnalysisJobListResponse(BaseModel):
    items: list[AdminAnalysisJobListItem]
    page: int
    page_size: int
    total: int

    model_config = {"extra": "forbid"}


class AdminAuditEventResponse(BaseModel):
    id: uuid.UUID
    resource_type: str
    resource_id: uuid.UUID
    action: str
    actor_type: AuditActorType
    actor_user_id: uuid.UUID | None
    before: dict[str, Any] | None
    after: dict[str, Any] | None
    reason: str
    occurred_at: datetime

    model_config = {"extra": "forbid"}


class AdminAuditEventListResponse(BaseModel):
    items: list[AdminAuditEventResponse]
    page: int
    page_size: int
    total: int

    model_config = {"extra": "forbid"}


class CourseSubmissionCount(BaseModel):
    course_id: uuid.UUID
    course_code: str
    course_name: str
    submission_count: int

    model_config = {"extra": "forbid"}


class AdminDashboardResponse(BaseModel):
    jobs_by_status: dict[AnalysisJobStatus, int]
    submissions_by_course: list[CourseSubmissionCount]
    open_review_requests: int

    model_config = {"extra": "forbid"}
