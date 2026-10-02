from __future__ import annotations

import math
import uuid
from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator

from app.models.enums import AnalysisJobStatus, ReviewDecisionType, ReviewRequestStatus


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


class DocumentDownloadResponse(BaseModel):
    url: str = Field(min_length=1)
    expires_in: int = Field(ge=1, le=300)


class AnalysisJobResponse(BaseModel):
    id: uuid.UUID
    document_version_id: uuid.UUID
    rubric_version_id: uuid.UUID
    status: AnalysisJobStatus
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


class VersionProcessingStatus(StrEnum):
    QUEUED = "QUEUED"
    PROCESSING = "PROCESSING"
    AWAITING_REVIEW = "AWAITING_REVIEW"
    ERROR = "ERROR"


class VersionPublicationStatus(StrEnum):
    PUBLISHED = "PUBLISHED"
    UNPUBLISHED = "UNPUBLISHED"


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


class ValidationDiagnosticResponse(BaseModel):
    code: str = Field(min_length=1, max_length=64)
    category: str = Field(min_length=1, max_length=32)
    disposition: Literal["BLOCK", "WARN", "REVIEW", "RETRY"]
    scope: Literal["DOCUMENT", "PAGE", "REGION"]
    page_number: int | None = Field(default=None, gt=0)
    bbox: BBox | None = None
    metrics: dict[str, int | float] = Field(default_factory=dict)
    message_key: str = Field(min_length=1, max_length=128)
    action_key: str | None = Field(default=None, max_length=128)

    @model_validator(mode="after")
    def validate_location(self) -> ValidationDiagnosticResponse:
        if self.scope == "DOCUMENT" and (
            self.page_number is not None or self.bbox is not None
        ):
            raise ValueError("Document diagnostics cannot have page coordinates")
        if self.scope in {"PAGE", "REGION"} and self.page_number is None:
            raise ValueError("Page and region diagnostics require a page number")
        if self.scope == "REGION" and self.bbox is None:
            raise ValueError("Region diagnostics require a bounding box")
        return self


class ValidationReportResponse(BaseModel):
    document_version_id: uuid.UUID
    schema_version: int = Field(gt=0)
    outcome: Literal[
        "NOT_RUN",
        "ACCEPTED",
        "ACCEPTED_WITH_WARNINGS",
        "REJECTED",
        "PROCESSING_FAILED",
    ]
    diagnostics: list[ValidationDiagnosticResponse] = Field(max_length=25)


class CitationCountsResponse(BaseModel):
    references: int = Field(ge=0)
    mentions: int = Field(ge=0)
    linked: int = Field(ge=0)
    linkage_rate: float = Field(ge=0, le=1)
    orphan_mentions: int = Field(ge=0)
    ambiguous: int = Field(ge=0)
    ambiguous_mapping: int = Field(default=0, ge=0)
    uncited_references: int = Field(ge=0)
    verified: int = Field(ge=0)
    verified_rate: float = Field(ge=0, le=1)
    metadata_mismatch: int = Field(ge=0)
    unresolved: int = Field(ge=0)
    parser_uncertain: int = Field(default=0, ge=0)
    fragmented_references: int = Field(default=0, ge=0)
    bibliography_not_found: int = Field(default=0, ge=0)
    duplicates: int = Field(ge=0)


class CitationIdentityResponse(BaseModel):
    id: str
    status: Literal["VERIFIED", "METADATA_MISMATCH", "UNRESOLVED", "PARSER_UNCERTAIN"]
    mismatch_fields: list[str] = Field(default_factory=list)
    doi: str | None = None
    arxiv_id: str | None = None
    provider: dict[str, str] | None = None


class CitationAnchorResponse(BaseModel):
    element_id: str
    page_number: int = Field(gt=0)
    line_start: int | None = Field(default=None, ge=0)
    line_end: int | None = Field(default=None, ge=0)


class CitationIssueResponse(BaseModel):
    id: str
    status: str
    element_id: str
    page_number: int = Field(gt=0)
    snippet: str = Field(max_length=240)
    anchors: list[CitationAnchorResponse] = Field(default_factory=list)


class CitationReportResponse(BaseModel):
    schema_version: int = Field(gt=0)
    parser_status: Literal["PARSED", "PARSER_UNCERTAIN"] = "PARSED"
    bibliography_status: Literal[
        "PARSED", "PARSER_UNCERTAIN", "BIBLIOGRAPHY_NOT_FOUND"
    ] = "BIBLIOGRAPHY_NOT_FOUND"
    parser_warnings: list[str] = Field(default_factory=list)
    counts: CitationCountsResponse
    duplicate_reference_ids: list[str] = Field(default_factory=list)
    identity: list[CitationIdentityResponse] = Field(default_factory=list)
    issues: list[CitationIssueResponse] = Field(default_factory=list)


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
    citation: CitationReportResponse | None = None


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


class SubmissionVersionResponse(BaseModel):
    document_version_id: uuid.UUID
    version_number: int
    created_at: datetime
    processing_status: VersionProcessingStatus
    publication_status: VersionPublicationStatus | None = None
    published_result_id: uuid.UUID | None = None
    published_at: datetime | None = None


class SubmissionVersionListResponse(BaseModel):
    items: list[SubmissionVersionResponse]
    page: int
    page_size: int
    total: int


class VersionComparisonFindingResponse(BaseModel):
    criterion_version_id: uuid.UUID
    finding_id: uuid.UUID
    score: Decimal | None
    decision: ReviewDecisionType | None
    evidence_count: int = Field(ge=0)


class VersionComparisonSideResponse(BaseModel):
    document_version_id: uuid.UUID
    version_number: int
    comment: str
    findings: list[VersionComparisonFindingResponse]


class VersionComparisonResponse(BaseModel):
    submission_id: uuid.UUID
    left: VersionComparisonSideResponse
    right: VersionComparisonSideResponse


class ReviewRequestCreate(BaseModel):
    submission_id: uuid.UUID
    criterion_id: uuid.UUID | None = None
    finding_id: uuid.UUID | None = None
    reason: str = Field(min_length=1, max_length=4_000)

    model_config = {"extra": "forbid"}

    @model_validator(mode="after")
    def validate_target_and_reason(self) -> ReviewRequestCreate:
        if (self.criterion_id is None) == (self.finding_id is None):
            raise ValueError("Exactly one of criterion_id or finding_id is required")
        if not self.reason.strip():
            raise ValueError("Reason must not be blank")
        return self


class ReviewRequestResponse(BaseModel):
    id: uuid.UUID
    published_result_id: uuid.UUID
    submission_id: uuid.UUID
    student_id: uuid.UUID
    criterion_id: uuid.UUID | None = None
    finding_id: uuid.UUID | None = None
    status: ReviewRequestStatus
    reason: str
    response: str | None = None
    responded_by_user_id: uuid.UUID | None = None
    responded_at: datetime | None = None
    created_at: datetime
    updated_at: datetime

    model_config = {"extra": "forbid", "from_attributes": True}


class ReviewRequestListResponse(BaseModel):
    items: list[ReviewRequestResponse]
    page: int
    page_size: int
    total: int

    model_config = {"extra": "forbid"}


class ReviewRequestUpdate(BaseModel):
    status: Literal[ReviewRequestStatus.RESOLVED, ReviewRequestStatus.REJECTED]
    response: str = Field(min_length=1, max_length=4_000)

    model_config = {"extra": "forbid"}

    @field_validator("response")
    @classmethod
    def validate_response(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Response must not be blank")
        return value
