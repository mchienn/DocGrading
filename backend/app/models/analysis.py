from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Any

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.enums import AnalysisJobStatus, pg_enum
from app.models.mixins import TimestampMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from app.models.rubric import RubricVersion
    from app.models.submission import DocumentVersion


class AnalysisJob(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "analysis_jobs"
    __table_args__ = (
        sa.CheckConstraint(
            "max_attempts > 0 AND attempt_count >= 0 AND attempt_count <= max_attempts",
            name="ck_analysis_jobs_attempts",
        ),
        sa.CheckConstraint(
            "jsonb_typeof(snapshot) = 'object'",
            name="ck_analysis_jobs_snapshot_object",
        ),
        sa.UniqueConstraint(
            "document_version_id",
            "rubric_version_id",
            name="uq_analysis_jobs_document_rubric",
        ),
    )

    document_version_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        sa.ForeignKey(
            "document_versions.id",
            ondelete="RESTRICT",
            name="fk_analysis_jobs_document_version_id_document_versions",
        ),
        nullable=False,
    )
    rubric_version_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        sa.ForeignKey(
            "rubric_versions.id",
            ondelete="RESTRICT",
            name="fk_analysis_jobs_rubric_version_id_rubric_versions",
        ),
        nullable=False,
    )
    status: Mapped[AnalysisJobStatus] = mapped_column(
        pg_enum(AnalysisJobStatus, name="analysis_job_status"),
        default=AnalysisJobStatus.QUEUED,
        nullable=False,
    )
    attempt_count: Mapped[int] = mapped_column(
        sa.Integer,
        default=0,
        server_default=sa.text("0"),
        nullable=False,
    )
    max_attempts: Mapped[int] = mapped_column(
        sa.Integer,
        default=3,
        server_default=sa.text("3"),
        nullable=False,
    )
    snapshot: Mapped[dict[str, Any]] = mapped_column(
        JSONB,
        default=dict,
        server_default=sa.text("'{}'::jsonb"),
        nullable=False,
    )
    queued_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True),
        server_default=sa.func.now(),
        nullable=False,
    )
    started_at: Mapped[datetime | None] = mapped_column(
        sa.DateTime(timezone=True),
        nullable=True,
    )
    finished_at: Mapped[datetime | None] = mapped_column(
        sa.DateTime(timezone=True),
        nullable=True,
    )
    error_code: Mapped[str | None] = mapped_column(
        sa.String(64),
        nullable=True,
    )
    error_detail: Mapped[str | None] = mapped_column(
        sa.Text,
        nullable=True,
    )

    document_version: Mapped[DocumentVersion] = relationship(
        "DocumentVersion",
        back_populates="analysis_jobs",
        foreign_keys=[document_version_id],
    )
    rubric_version: Mapped[RubricVersion] = relationship(
        "RubricVersion",
        back_populates="analysis_jobs",
        foreign_keys=[rubric_version_id],
    )
