"""Pydantic schemas for authentication requests and responses."""

from __future__ import annotations

import uuid

from pydantic import BaseModel, Field


class LoginRequest(BaseModel):
    email: str = Field(max_length=320)
    password: str = Field(min_length=1, max_length=512)


class UserResponse(BaseModel):
    id: uuid.UUID
    email: str
    display_name: str
    roles: list[str]
    status: str

    model_config = {"from_attributes": True}
