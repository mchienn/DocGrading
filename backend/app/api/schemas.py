"""Pydantic schemas for authentication requests and responses."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field, field_validator


def _trim_nonblank(value: Any) -> Any:
    if not isinstance(value, str):
        return value
    value = value.strip()
    if not value:
        raise ValueError("must not be blank")
    return value


class LoginRequest(BaseModel):
    email: str = Field(max_length=320)
    password: str = Field(min_length=1, max_length=512, repr=False)


class ProfileUpdateRequest(BaseModel):
    display_name: str = Field(min_length=1, max_length=255)

    model_config = {"extra": "forbid"}

    @field_validator("display_name", mode="before")
    @classmethod
    def trim_display_name(cls, value: Any) -> Any:
        return _trim_nonblank(value)


class ChangePasswordRequest(BaseModel):
    current_password: str = Field(min_length=1, max_length=512, repr=False)
    new_password: str = Field(min_length=12, max_length=512, repr=False)

    model_config = {"extra": "forbid"}


class UserResponse(BaseModel):
    id: uuid.UUID
    email: str
    display_name: str
    roles: list[str]
    status: str
    created_at: datetime
    revision: int

    model_config = {"from_attributes": True}
