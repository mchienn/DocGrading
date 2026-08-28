from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, Field, field_validator


class PresignRequest(BaseModel):
    filename: str = Field(min_length=1, max_length=255)
    content_type: str = Field(min_length=1, max_length=128)
    size_bytes: int = Field(gt=0)
    sha256: str = Field(min_length=64, max_length=64, pattern=r"^[0-9a-fA-F]{64}$")

    @field_validator("filename")
    @classmethod
    def validate_filename_not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Filename must not be whitespace-only")
        return value


class PresignResponse(BaseModel):
    submission_id: uuid.UUID
    document_version_id: uuid.UUID
    object_key: str
    upload_url: str | None = None
    fields: dict[str, str] | None = None
    expires_in: int | None = None
    status: str
    reused: bool = False
    analysis_job_id: uuid.UUID | None = None


class CompletionResponse(BaseModel):
    submission_id: uuid.UUID
    document_version_id: uuid.UUID
    analysis_job_id: uuid.UUID
    status: str


class AnalysisJobResponse(BaseModel):
    id: uuid.UUID
    document_version_id: uuid.UUID
    rubric_version_id: uuid.UUID
    status: str
    attempt_count: int
    max_attempts: int
    error_code: str | None
    error_detail: str | None
    queued_at: datetime
    started_at: datetime | None
    finished_at: datetime | None

    model_config = {"from_attributes": True}
