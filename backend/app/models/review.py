from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.enums import ReviewDecisionType, pg_enum
from app.models.mixins import RevisionMixin, TimestampMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from app.models.analysis import AnalysisJob, DocumentIR
    from app.models.identity import User
    from app.models.rubric import CriterionVersion
    from app.models.submission import DocumentVersion, Submission


def _not_blank(column: str, name: str) -> sa.CheckConstraint:
    return sa.CheckConstraint(
        f"length(btrim({column})) > 0 AND {column} !~ '^[[:space:]]*$'",
        name=name,
    )


class Finding(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "findings"
    __table_args__ = (
        _not_blank("severity", "ck_findings_severity_not_blank"),
        _not_blank("description", "ck_findings_description_not_blank"),
        sa.CheckConstraint(
            "proposed_score IS NULL "
            "OR (proposed_score >= 0 AND proposed_score <= 100)",
            name="ck_findings_proposed_score_range",
        ),
        sa.ForeignKeyConstraint(
            ["analysis_job_id"],
            ["analysis_jobs.id"],
            name="fk_findings_analysis_job_id_analysis_jobs",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["criterion_version_id"],
            ["criterion_versions.id"],
            name="fk_findings_criterion_version_id_criterion_versions",
            ondelete="RESTRICT",
        ),
        sa.Index("ix_findings_analysis_job", "analysis_job_id"),
        sa.Index("ix_findings_criterion", "criterion_version_id"),
    )

    analysis_job_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False
    )
    criterion_version_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False
    )
    severity: Mapped[str] = mapped_column(sa.String(32), nullable=False)
    description: Mapped[str] = mapped_column(sa.Text, nullable=False)
    suggestion: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    proposed_score: Mapped[Decimal | None] = mapped_column(
        sa.Numeric(5, 2), nullable=True
    )

    analysis_job: Mapped[AnalysisJob] = relationship(
        "AnalysisJob", foreign_keys=[analysis_job_id]
    )
    criterion_version: Mapped[CriterionVersion] = relationship(
        "CriterionVersion", foreign_keys=[criterion_version_id]
    )
    evidence_anchors: Mapped[list[EvidenceAnchor]] = relationship(
        "EvidenceAnchor",
        back_populates="finding",
        cascade="all, delete-orphan",
        foreign_keys="EvidenceAnchor.finding_id",
    )


class EvidenceAnchor(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "evidence_anchors"
    __table_args__ = (
        sa.UniqueConstraint(
            "finding_id",
            "document_ir_id",
            "element_id",
            "page_number",
            name="uq_evidence_anchors_finding_element_page",
        ),
        sa.CheckConstraint("page_number > 0", name="ck_evidence_anchors_page_positive"),
        _not_blank("element_id", "ck_evidence_anchors_element_id_not_blank"),
        sa.ForeignKeyConstraint(
            ["finding_id"],
            ["findings.id"],
            name="fk_evidence_anchors_finding_id_findings",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["document_ir_id"],
            ["document_irs.id"],
            name="fk_evidence_anchors_document_ir_id_document_irs",
            ondelete="RESTRICT",
        ),
        sa.Index("ix_evidence_anchors_finding", "finding_id"),
    )

    finding_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    document_ir_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False
    )
    element_id: Mapped[str] = mapped_column(sa.String(64), nullable=False)
    page_number: Mapped[int] = mapped_column(sa.Integer, nullable=False)

    finding: Mapped[Finding] = relationship(
        "Finding", back_populates="evidence_anchors", foreign_keys=[finding_id]
    )
    document_ir: Mapped[DocumentIR] = relationship(
        "DocumentIR", foreign_keys=[document_ir_id]
    )


class ReviewLock(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "review_locks"
    __table_args__ = (
        sa.UniqueConstraint("submission_id", name="uq_review_locks_submission_id"),
        sa.CheckConstraint(
            "expires_at > acquired_at",
            name="ck_review_locks_expiry_after_acquired",
        ),
        sa.ForeignKeyConstraint(
            ["submission_id"],
            ["submissions.id"],
            name="fk_review_locks_submission_id_submissions",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["reviewer_user_id"],
            ["users.id"],
            name="fk_review_locks_reviewer_user_id_users",
            ondelete="RESTRICT",
        ),
    )

    submission_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    reviewer_user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False
    )
    acquired_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
    )
    expires_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), nullable=False
    )

    reviewer: Mapped[User] = relationship("User", foreign_keys=[reviewer_user_id])
    submission: Mapped[Submission] = relationship(
        "Submission", foreign_keys=[submission_id]
    )


class ReviewDraft(UUIDPrimaryKeyMixin, TimestampMixin, RevisionMixin, Base):
    __tablename__ = "review_drafts"
    __table_args__ = (
        sa.UniqueConstraint(
            "submission_id",
            "reviewer_user_id",
            name="uq_review_drafts_submission_reviewer",
        ),
        sa.CheckConstraint("revision > 0", name="ck_review_drafts_revision_positive"),
        sa.ForeignKeyConstraint(
            ["submission_id"],
            ["submissions.id"],
            name="fk_review_drafts_submission_id_submissions",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["reviewer_user_id"],
            ["users.id"],
            name="fk_review_drafts_reviewer_user_id_users",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["document_version_id"],
            ["document_versions.id"],
            name="fk_review_drafts_document_version_id_document_versions",
            ondelete="CASCADE",
        ),
    )

    submission_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    document_version_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False
    )
    reviewer_user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False
    )
    comment: Mapped[str] = mapped_column(
        sa.Text, default="", server_default=sa.text("''"), nullable=False
    )

    reviewer: Mapped[User] = relationship("User", foreign_keys=[reviewer_user_id])
    submission: Mapped[Submission] = relationship(
        "Submission", foreign_keys=[submission_id]
    )
    document_version: Mapped[DocumentVersion] = relationship(
        "DocumentVersion", foreign_keys=[document_version_id]
    )
    decisions: Mapped[list[ReviewDecision]] = relationship(
        "ReviewDecision",
        back_populates="draft",
        cascade="all, delete-orphan",
        foreign_keys="ReviewDecision.review_draft_id",
    )


class ReviewDecision(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "review_decisions"
    __table_args__ = (
        sa.UniqueConstraint(
            "review_draft_id",
            "finding_id",
            name="uq_review_decisions_draft_finding",
        ),
        sa.CheckConstraint(
            "(decision = 'ACCEPT' "
            "AND edited_description IS NULL AND final_score IS NULL) "
            "OR (decision = 'EDIT' "
            "AND (edited_description IS NOT NULL OR final_score IS NOT NULL)) "
            "OR (decision = 'REJECT' "
            "AND edited_description IS NULL AND final_score IS NULL)",
            name="ck_review_decisions_payload",
        ),
        _not_blank("edited_description", "ck_review_decisions_description_not_blank"),
        _not_blank("reason", "ck_review_decisions_reason_not_blank"),
        sa.CheckConstraint(
            "final_score IS NULL OR (final_score >= 0 AND final_score <= 100)",
            name="ck_review_decisions_final_score_range",
        ),
        sa.ForeignKeyConstraint(
            ["review_draft_id"],
            ["review_drafts.id"],
            name="fk_review_decisions_review_draft_id_review_drafts",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["finding_id"],
            ["findings.id"],
            name="fk_review_decisions_finding_id_findings",
            ondelete="RESTRICT",
        ),
    )

    review_draft_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False
    )
    finding_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    decision: Mapped[ReviewDecisionType] = mapped_column(
        pg_enum(ReviewDecisionType, name="review_decision_type"), nullable=False
    )
    edited_description: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    final_score: Mapped[Decimal | None] = mapped_column(sa.Numeric(5, 2), nullable=True)
    reason: Mapped[str | None] = mapped_column(sa.Text, nullable=True)

    draft: Mapped[ReviewDraft] = relationship(
        "ReviewDraft", back_populates="decisions", foreign_keys=[review_draft_id]
    )
    finding: Mapped[Finding] = relationship("Finding", foreign_keys=[finding_id])
