from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING, Any

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.enums import RubricStatus, pg_enum
from app.models.mixins import (
    NestedMutableDict,
    NestedMutableList,
    RevisionMixin,
    TimestampMixin,
    UUIDPrimaryKeyMixin,
)

if TYPE_CHECKING:
    from app.models.analysis import AnalysisJob
    from app.models.assignment import Assignment, AssignmentRequirement
    from app.models.identity import User


class RubricVersion(UUIDPrimaryKeyMixin, TimestampMixin, RevisionMixin, Base):
    __tablename__ = "rubric_versions"
    __table_args__ = (
        sa.UniqueConstraint(
            "rubric_id",
            "version_number",
            name="uq_rubric_versions_rubric_version",
        ),
        sa.CheckConstraint(
            "version_number > 0",
            name="ck_rubric_versions_version_number_positive",
        ),
        sa.CheckConstraint(
            "total_weight >= 0.00 AND total_weight <= 100.00",
            name="ck_rubric_versions_total_weight_range",
        ),
        sa.CheckConstraint(
            "(status = 'DRAFT' AND published_at IS NULL) "
            "OR (status IN ('PUBLISHED', 'ARCHIVED') "
            "AND published_at IS NOT NULL)",
            name="ck_rubric_versions_publication_state",
        ),
        sa.CheckConstraint("revision > 0", name="ck_rubric_versions_revision_positive"),
    )

    rubric_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        default=uuid.uuid4,
        nullable=False,
    )
    version_number: Mapped[int] = mapped_column(sa.Integer, nullable=False)
    name: Mapped[str] = mapped_column(sa.String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    status: Mapped[RubricStatus] = mapped_column(
        pg_enum(RubricStatus, name="rubric_status"),
        default=RubricStatus.DRAFT,
        nullable=False,
    )
    calculation_method: Mapped[str] = mapped_column(
        sa.String(64),
        default="WEIGHTED_SUM",
        server_default=sa.text("'WEIGHTED_SUM'"),
        nullable=False,
    )
    total_weight: Mapped[Decimal] = mapped_column(
        sa.Numeric(6, 2),
        default=Decimal("0.00"),
        server_default=sa.text("0.00"),
        nullable=False,
    )
    owner_user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        sa.ForeignKey(
            "users.id",
            ondelete="RESTRICT",
            name="fk_rubric_versions_owner_user_id_users",
        ),
        nullable=False,
    )
    created_by_user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        sa.ForeignKey(
            "users.id",
            ondelete="RESTRICT",
            name="fk_rubric_versions_created_by_user_id_users",
        ),
        nullable=False,
    )
    source_version_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        sa.ForeignKey(
            "rubric_versions.id",
            ondelete="RESTRICT",
            name="fk_rubric_versions_source_version_id_rubric_versions",
        ),
        nullable=True,
    )
    published_at: Mapped[datetime | None] = mapped_column(
        sa.DateTime(timezone=True),
        nullable=True,
    )

    owner: Mapped[User] = relationship(
        "User",
        back_populates="owned_rubric_versions",
        foreign_keys=[owner_user_id],
    )
    created_by_user: Mapped[User] = relationship(
        "User",
        back_populates="created_rubric_versions",
        foreign_keys=[created_by_user_id],
    )
    source_version: Mapped[RubricVersion | None] = relationship(
        "RubricVersion",
        back_populates="derived_versions",
        remote_side="RubricVersion.id",
        foreign_keys=[source_version_id],
    )
    derived_versions: Mapped[list[RubricVersion]] = relationship(
        "RubricVersion",
        back_populates="source_version",
        foreign_keys="RubricVersion.source_version_id",
        passive_deletes="all",
    )
    criteria: Mapped[list[CriterionVersion]] = relationship(
        "CriterionVersion",
        back_populates="rubric_version",
        cascade="all, delete-orphan",
        foreign_keys="CriterionVersion.rubric_version_id",
    )
    assignments: Mapped[list[Assignment]] = relationship(
        "Assignment",
        back_populates="rubric_version",
        foreign_keys="Assignment.rubric_version_id",
    )
    analysis_jobs: Mapped[list[AnalysisJob]] = relationship(
        "AnalysisJob",
        back_populates="rubric_version",
        foreign_keys="AnalysisJob.rubric_version_id",
        passive_deletes="all",
    )


class CriterionVersion(UUIDPrimaryKeyMixin, TimestampMixin, RevisionMixin, Base):
    __tablename__ = "criterion_versions"
    __table_args__ = (
        sa.UniqueConstraint(
            "rubric_version_id",
            "criterion_id",
            name="uq_criterion_versions_rubric_version_criterion",
        ),
        sa.UniqueConstraint(
            "rubric_version_id",
            "code",
            name="uq_criterion_versions_rubric_version_code",
        ),
        sa.UniqueConstraint(
            "rubric_version_id",
            "position",
            name="uq_criterion_versions_rubric_version_position",
        ),
        sa.CheckConstraint(
            "weight >= 0.00 AND weight <= 100.00",
            name="ck_criterion_versions_weight_range",
        ),
        sa.CheckConstraint(
            "position > 0",
            name="ck_criterion_versions_position_positive",
        ),
        sa.CheckConstraint(
            "revision > 0",
            name="ck_criterion_versions_revision_positive",
        ),
        sa.CheckConstraint(
            "jsonb_typeof(levels) = 'array'",
            name="ck_criterion_versions_levels_is_array",
        ),
        sa.CheckConstraint(
            "jsonb_typeof(evaluator_config) = 'object'",
            name="ck_criterion_versions_evaluator_config_is_object",
        ),
        sa.CheckConstraint(
            "jsonb_typeof(evidence_requirements) = 'object'",
            name="ck_criterion_versions_evidence_requirements_is_object",
        ),
    )

    criterion_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        default=uuid.uuid4,
        nullable=False,
    )
    rubric_version_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        sa.ForeignKey(
            "rubric_versions.id",
            ondelete="CASCADE",
            name="fk_criterion_versions_rubric_version_id_rubric_versions",
        ),
        nullable=False,
    )
    code: Mapped[str] = mapped_column(sa.String(64), nullable=False)
    title: Mapped[str] = mapped_column(sa.String(255), nullable=False)
    description: Mapped[str] = mapped_column(sa.Text, nullable=False)
    scope: Mapped[str | None] = mapped_column(sa.String(255), nullable=True)
    weight: Mapped[Decimal] = mapped_column(sa.Numeric(6, 2), nullable=False)
    position: Mapped[int] = mapped_column(sa.Integer, nullable=False)
    is_enabled: Mapped[bool] = mapped_column(
        sa.Boolean,
        default=True,
        server_default=sa.text("true"),
        nullable=False,
    )
    evaluation_method: Mapped[str] = mapped_column(sa.String(64), nullable=False)
    levels: Mapped[list[dict[str, Any]]] = mapped_column(
        NestedMutableList.as_mutable(JSONB),
        default=list,
        server_default=sa.text("'[]'::jsonb"),
        nullable=False,
    )
    evaluator_config: Mapped[dict[str, Any]] = mapped_column(
        NestedMutableDict.as_mutable(JSONB),
        default=dict,
        server_default=sa.text("'{}'::jsonb"),
        nullable=False,
    )
    evidence_requirements: Mapped[dict[str, Any]] = mapped_column(
        NestedMutableDict.as_mutable(JSONB),
        default=dict,
        server_default=sa.text("'{}'::jsonb"),
        nullable=False,
    )

    rubric_version: Mapped[RubricVersion] = relationship(
        "RubricVersion",
        back_populates="criteria",
        foreign_keys=[rubric_version_id],
    )


class TemplateVersion(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "template_versions"
    __table_args__ = (
        sa.UniqueConstraint(
            "template_id",
            "version_number",
            name="uq_template_versions_template_version",
        ),
        sa.CheckConstraint(
            "version_number > 0",
            name="ck_template_versions_version_number_positive",
        ),
        sa.CheckConstraint(
            "jsonb_typeof(structure) = 'object'",
            name="ck_template_versions_structure_is_object",
        ),
        sa.CheckConstraint(
            "sha256 IS NULL OR sha256 ~ '^[0-9a-f]{64}$'",
            name="ck_template_versions_sha256_format",
        ),
    )

    template_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        default=uuid.uuid4,
        nullable=False,
    )
    version_number: Mapped[int] = mapped_column(sa.Integer, nullable=False)
    name: Mapped[str] = mapped_column(sa.String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    owner_user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        sa.ForeignKey(
            "users.id",
            ondelete="RESTRICT",
            name="fk_template_versions_owner_user_id_users",
        ),
        nullable=False,
    )
    created_by_user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        sa.ForeignKey(
            "users.id",
            ondelete="RESTRICT",
            name="fk_template_versions_created_by_user_id_users",
        ),
        nullable=False,
    )
    structure: Mapped[dict[str, Any]] = mapped_column(
        NestedMutableDict.as_mutable(JSONB),
        default=dict,
        server_default=sa.text("'{}'::jsonb"),
        nullable=False,
    )
    storage_key: Mapped[str | None] = mapped_column(
        sa.String(1024),
        nullable=True,
    )
    sha256: Mapped[str | None] = mapped_column(
        sa.String(64),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True),
        server_default=sa.func.now(),
        nullable=False,
    )

    owner: Mapped[User] = relationship(
        "User",
        back_populates="owned_template_versions",
        foreign_keys=[owner_user_id],
    )
    created_by_user: Mapped[User] = relationship(
        "User",
        back_populates="created_template_versions",
        foreign_keys=[created_by_user_id],
    )
    assignment_requirements: Mapped[list[AssignmentRequirement]] = relationship(
        "AssignmentRequirement",
        back_populates="template_version",
        foreign_keys="AssignmentRequirement.template_version_id",
        passive_deletes="all",
    )
