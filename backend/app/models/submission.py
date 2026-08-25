from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.enums import DocumentStatus, pg_enum
from app.models.mixins import TimestampMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from app.models.analysis import AnalysisJob
    from app.models.assignment import Assignment
    from app.models.identity import User


class Submission(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "submissions"
    __table_args__ = (
        sa.UniqueConstraint(
            "assignment_id",
            "student_id",
            name="uq_submissions_assignment_student",
        ),
    )

    assignment_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        sa.ForeignKey(
            "assignments.id",
            ondelete="RESTRICT",
            name="fk_submissions_assignment_id_assignments",
        ),
        nullable=False,
    )
    student_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        sa.ForeignKey(
            "users.id",
            ondelete="RESTRICT",
            name="fk_submissions_student_id_users",
        ),
        nullable=False,
    )

    assignment: Mapped[Assignment] = relationship(
        "Assignment",
        back_populates="submissions",
        foreign_keys=[assignment_id],
    )
    student: Mapped[User] = relationship(
        "User",
        back_populates="submissions",
        foreign_keys=[student_id],
    )
    document_versions: Mapped[list[DocumentVersion]] = relationship(
        "DocumentVersion",
        back_populates="submission",
        foreign_keys="DocumentVersion.submission_id",
        passive_deletes="all",
    )


class DocumentVersion(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "document_versions"
    __table_args__ = (
        sa.UniqueConstraint(
            "submission_id",
            "version_number",
            name="uq_document_versions_submission_version",
        ),
        sa.UniqueConstraint(
            "submission_id",
            "sha256",
            name="uq_document_versions_submission_sha256",
        ),
        sa.CheckConstraint(
            "version_number > 0",
            name="ck_document_versions_version_number_positive",
        ),
        sa.CheckConstraint(
            "size_bytes > 0",
            name="ck_document_versions_size_bytes_positive",
        ),
        sa.CheckConstraint(
            "page_count IS NULL OR page_count > 0",
            name="ck_document_versions_page_count_positive",
        ),
        sa.CheckConstraint(
            "sha256 ~ '^[0-9a-f]{64}$'",
            name="ck_document_versions_sha256_format",
        ),
    )

    submission_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        sa.ForeignKey(
            "submissions.id",
            ondelete="RESTRICT",
            name="fk_document_versions_submission_id_submissions",
        ),
        nullable=False,
    )
    version_number: Mapped[int] = mapped_column(sa.Integer, nullable=False)
    previous_version_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        sa.ForeignKey(
            "document_versions.id",
            ondelete="RESTRICT",
            name="fk_document_versions_previous_version_id_document_versions",
        ),
        nullable=True,
    )
    storage_key: Mapped[str] = mapped_column(sa.String(1024), nullable=False)
    original_filename: Mapped[str] = mapped_column(sa.String(255), nullable=False)
    content_type: Mapped[str] = mapped_column(sa.String(128), nullable=False)
    size_bytes: Mapped[int] = mapped_column(sa.BigInteger, nullable=False)
    page_count: Mapped[int | None] = mapped_column(sa.Integer, nullable=True)
    sha256: Mapped[str] = mapped_column(sa.String(64), nullable=False)
    status: Mapped[DocumentStatus] = mapped_column(
        pg_enum(DocumentStatus, name="document_status"),
        default=DocumentStatus.UPLOADING,
        nullable=False,
    )
    failure_code: Mapped[str | None] = mapped_column(sa.String(64), nullable=True)
    failure_detail: Mapped[str | None] = mapped_column(sa.Text, nullable=True)

    submission: Mapped[Submission] = relationship(
        "Submission",
        back_populates="document_versions",
        foreign_keys=[submission_id],
    )
    previous_version: Mapped[DocumentVersion | None] = relationship(
        "DocumentVersion",
        back_populates="subsequent_versions",
        remote_side="DocumentVersion.id",
        foreign_keys=[previous_version_id],
    )
    subsequent_versions: Mapped[list[DocumentVersion]] = relationship(
        "DocumentVersion",
        back_populates="previous_version",
        foreign_keys="DocumentVersion.previous_version_id",
        passive_deletes="all",
    )
    analysis_jobs: Mapped[list[AnalysisJob]] = relationship(
        "AnalysisJob",
        back_populates="document_version",
        foreign_keys="AnalysisJob.document_version_id",
        passive_deletes="all",
    )
