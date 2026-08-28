"""Pydantic schemas for Course API."""

from __future__ import annotations

import uuid

from pydantic import BaseModel, Field

from app.models.enums import CourseStatus


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
