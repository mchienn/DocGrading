from __future__ import annotations

import math
import uuid
from datetime import datetime
from decimal import Decimal
from enum import StrEnum

from pydantic import BaseModel, Field, field_validator, model_validator

from app.models.enums import ReviewDecisionType


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


class QueueStatus(StrEnum):
    UNREVIEWED = "UNREVIEWED"
    REVIEWED = "REVIEWED"
    ERROR = "ERROR"


class QueueSort(StrEnum):
    ASC = "asc"
    DESC = "desc"


class BBox(BaseModel):
    x0: float
    top: float
    x1: float
    bottom: float

    @model_validator(mode="after")
    def validate_coordinates(self) -> BBox:
        coordinates = (self.x0, self.top, self.x1, self.bottom)
        if not all(math.isfinite(value) for value in coordinates):
            raise ValueError("Bounding box coordinates must be finite")
        if any(value < 0 for value in coordinates):
            raise ValueError("Bounding box coordinates must be nonnegative")
        if self.x0 > self.x1 or self.top > self.bottom:
            raise ValueError("Bounding box coordinates must be ordered")
        return self


class EvidenceResponse(BaseModel):
    document_ir_id: uuid.UUID
    element_id: str
    page_number: int = Field(gt=0)
    bbox: BBox


class FindingResponse(BaseModel):
    id: uuid.UUID
    criterion_version_id: uuid.UUID
    severity: str
    description: str
    suggestion: str | None
    proposed_score: Decimal | None
    evidence: list[EvidenceResponse]


class EvidenceWorkspaceResponse(BaseModel):
    submission_id: uuid.UUID
    document_version_id: uuid.UUID
    findings: list[FindingResponse]


class QueueLockResponse(BaseModel):
    reviewer_user_id: uuid.UUID
    reviewer_display_name: str
    expires_at: datetime


class SubmissionQueueItem(BaseModel):
    submission_id: uuid.UUID
    document_version_id: uuid.UUID | None
    student_id: uuid.UUID
    document_status: str | None
    queue_status: QueueStatus
    submitted_at: datetime
    review_lock: QueueLockResponse | None = None


class SubmissionQueueResponse(BaseModel):
    items: list[SubmissionQueueItem]
    page: int
    page_size: int
    total: int


class ReviewLockResponse(BaseModel):
    acquired: bool
    submission_id: uuid.UUID
    reviewer_user_id: uuid.UUID | None = None
    reviewer_display_name: str | None = None
    expires_at: datetime | None = None


class ReviewDecisionRequest(BaseModel):
    finding_id: uuid.UUID
    decision: ReviewDecisionType
    edited_description: str | None = Field(default=None, max_length=10_000)
    final_score: Decimal | None = Field(
        default=None,
        ge=0,
        le=100,
        max_digits=5,
        decimal_places=2,
    )
    reason: str | None = Field(default=None, max_length=2_000)

    @field_validator("edited_description", "reason")
    @classmethod
    def nonblank_text(cls, value: str | None) -> str | None:
        if value is not None and not value.strip():
            raise ValueError("Text must not be blank")
        return value

    @model_validator(mode="after")
    def validate_shape(self) -> ReviewDecisionRequest:
        if self.decision is ReviewDecisionType.ACCEPT and any(
            value is not None for value in (self.edited_description, self.final_score)
        ):
            raise ValueError("ACCEPT cannot include edit or score")
        if (
            self.decision is ReviewDecisionType.EDIT
            and self.edited_description is None
            and self.final_score is None
        ):
            raise ValueError("EDIT requires edited description or final score")
        if self.decision is ReviewDecisionType.REJECT and any(
            value is not None for value in (self.edited_description, self.final_score)
        ):
            raise ValueError("REJECT cannot include edit or score")
        return self


class ReviewDraftRequest(BaseModel):
    document_version_id: uuid.UUID
    revision: int = Field(ge=1)
    comment: str = Field(default="", max_length=10_000)
    decisions: list[ReviewDecisionRequest] = Field(default_factory=list)

    @field_validator("comment")
    @classmethod
    def normalize_comment(cls, value: str) -> str:
        return value if value.strip() else ""

    @model_validator(mode="after")
    def unique_findings(self) -> ReviewDraftRequest:
        finding_ids = [decision.finding_id for decision in self.decisions]
        if len(finding_ids) != len(set(finding_ids)):
            raise ValueError("Decision findings must be unique")
        return self


class ReviewDecisionResponse(BaseModel):
    finding_id: uuid.UUID
    decision: ReviewDecisionType
    edited_description: str | None
    final_score: Decimal | None
    reason: str | None


class ReviewDraftResponse(BaseModel):
    id: uuid.UUID | None
    submission_id: uuid.UUID
    document_version_id: uuid.UUID | None
    reviewer_user_id: uuid.UUID
    revision: int
    comment: str
    decisions: list[ReviewDecisionResponse]


class ApprovalResponse(BaseModel):
    document_version_id: uuid.UUID
    status: str
    approved_at: datetime


class BulkPublishRequest(BaseModel):
    version_ids: list[uuid.UUID] = Field(min_length=1, max_length=100)
    reason: str = Field(min_length=1, max_length=2_000)

    @field_validator("reason")
    @classmethod
    def nonblank_reason(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Reason must not be blank")
        return value

    @model_validator(mode="after")
    def unique_versions(self) -> BulkPublishRequest:
        if len(self.version_ids) != len(set(self.version_ids)):
            raise ValueError("version_ids must be unique")
        return self


class PublishRequest(BaseModel):
    reason: str = Field(min_length=1, max_length=2_000)

    @field_validator("reason")
    @classmethod
    def nonblank_reason(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Reason must not be blank")
        return value


class UnpublishRequest(PublishRequest):
    pass


class PublishedFindingResponse(BaseModel):
    criterion_version_id: uuid.UUID
    finding_id: uuid.UUID
    score: Decimal | None
    description: str
    suggestion: str | None
    evidence: list[EvidenceResponse]


class PublishedResultResponse(BaseModel):
    published_result_id: uuid.UUID
    submission_id: uuid.UUID
    document_version_id: uuid.UUID
    version_number: int
    published_at: datetime
    comment: str
    findings: list[PublishedFindingResponse]


class BulkPublishResponse(BaseModel):
    results: list[PublishedResultResponse]
