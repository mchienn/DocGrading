"""Pydantic schemas for Assignment API."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, Field


class AssignmentCreate(BaseModel):
    rubric_version_id: uuid.UUID
    title: str = Field(min_length=1, max_length=255)
    description: str | None = None
    due_at: datetime
    max_submissions: int = Field(default=3, ge=1, le=5)


class AssignmentUpdate(BaseModel):
    title: str | None = Field(None, min_length=1, max_length=255)
    description: str | None = None
    due_at: datetime | None = None
    max_submissions: int | None = Field(None, ge=1, le=5)
    rubric_version_id: uuid.UUID | None = None


class AssignmentResponse(BaseModel):
    id: uuid.UUID
    course_id: uuid.UUID
    created_by_teacher_id: uuid.UUID
    rubric_version_id: uuid.UUID
    title: str
    description: str | None
    due_at: datetime
    max_submissions: int
    status: str
    published_at: datetime | None
    closed_at: datetime | None
    revision: int

    model_config = {"from_attributes": True}
