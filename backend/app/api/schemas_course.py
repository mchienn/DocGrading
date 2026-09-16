"""Pydantic schemas for Course API."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator, model_validator

from app.models.enums import (
    CourseJoinOutcome,
    CourseStatus,
    MembershipAddOutcome,
    MembershipJoinedVia,
    MembershipStatus,
)


class CourseCreate(BaseModel):
    code: str = Field(min_length=1, max_length=64)
    name: str = Field(min_length=1, max_length=255)
    term: str = Field(min_length=1, max_length=128)


class CourseUpdate(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=255)
    term: str | None = Field(None, min_length=1, max_length=128)


class CourseResponse(BaseModel):
    id: uuid.UUID
    code: str
    name: str
    term: str
    status: CourseStatus
    owner_teacher_id: uuid.UUID
    revision: int

    model_config = {"from_attributes": True}


class CourseMemberResponse(BaseModel):
    id: uuid.UUID
    user_id: uuid.UUID
    email: str
    display_name: str
    status: MembershipStatus
    joined_at: datetime
    joined_via: MembershipJoinedVia

    model_config = {"extra": "forbid", "from_attributes": True}


class CourseMemberListResponse(BaseModel):
    items: list[CourseMemberResponse]
    page: int
    page_size: int
    total: int

    model_config = {"extra": "forbid"}


class CourseMemberAddRequest(BaseModel):
    email: str = Field(min_length=3, max_length=320)
    reason: str | None = Field(default=None, max_length=1000)

    model_config = {"extra": "forbid"}

    @field_validator("email", mode="before")
    @classmethod
    def normalize_email(cls, value: Any) -> Any:
        if not isinstance(value, str):
            return value
        value = value.strip().lower()
        if (
            value.count("@") != 1
            or any(character.isspace() for character in value)
            or not all(value.split("@"))
        ):
            raise ValueError("email must contain one nonempty local and domain pair")
        return value

    @field_validator("reason", mode="before")
    @classmethod
    def trim_reason(cls, value: Any) -> Any:
        if value is None:
            return None
        if not isinstance(value, str):
            return value
        value = value.strip()
        return value or None


class CourseMemberRemoveRequest(BaseModel):
    reason: str | None = Field(default=None, max_length=1000)

    model_config = {"extra": "forbid"}

    @field_validator("reason", mode="before")
    @classmethod
    def trim_reason(cls, value: Any) -> Any:
        if value is None:
            return None
        if not isinstance(value, str):
            return value
        value = value.strip()
        return value or None


class CourseInviteResponse(BaseModel):
    id: uuid.UUID
    course_id: uuid.UUID
    email: str
    status: Literal["PENDING"]
    created_at: datetime

    model_config = {"extra": "forbid", "from_attributes": True}


class CourseMemberAddResponse(BaseModel):
    outcome: MembershipAddOutcome
    member: CourseMemberResponse | None = None
    invite: CourseInviteResponse | None = None

    model_config = {"extra": "forbid"}

    @model_validator(mode="after")
    def require_one_result(self) -> CourseMemberAddResponse:
        if (self.member is None) == (self.invite is None):
            raise ValueError("exactly one of member or invite is required")
        return self


class CourseJoinCodeCreateRequest(BaseModel):
    expires_at: datetime

    model_config = {"extra": "forbid"}


class CourseJoinCodeUpdateRequest(BaseModel):
    expires_at: datetime

    model_config = {"extra": "forbid"}


class CourseJoinCodeResponse(BaseModel):
    id: uuid.UUID
    course_id: uuid.UUID
    code: str
    expires_at: datetime
    revoked_at: datetime | None
    status: Literal["ACTIVE", "EXPIRED", "REVOKED"]
    join_url: str
    qr_url: str

    model_config = {"extra": "forbid"}


class CourseJoinRequest(BaseModel):
    code: str = Field(min_length=1, max_length=64)

    model_config = {"extra": "forbid"}


class CourseJoinResponse(BaseModel):
    outcome: CourseJoinOutcome
    membership_id: uuid.UUID
    course_code: str
    course_name: str

    model_config = {"extra": "forbid"}
