from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.enums import AssignmentStatus, pg_enum
from app.models.mixins import RevisionMixin, TimestampMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from app.models.course import Course
    from app.models.identity import User
    from app.models.rubric import RubricVersion, TemplateVersion
    from app.models.submission import Submission


class Assignment(UUIDPrimaryKeyMixin, TimestampMixin, RevisionMixin, Base):
    __tablename__ = "assignments"
    __table_args__ = (
        sa.CheckConstraint(
            "max_submissions >= 1 AND max_submissions <= 5",
            name="ck_assignments_max_submissions",
        ),
        sa.CheckConstraint(
            "(status = 'DRAFT' AND published_at IS NULL AND closed_at IS NULL) "
            "OR (status = 'OPEN' AND published_at IS NOT NULL AND closed_at IS NULL) "
            "OR (status IN ('CLOSED', 'ARCHIVED') "
            "AND published_at IS NOT NULL AND closed_at IS NOT NULL)",
            name="ck_assignments_publication_state",
        ),
        sa.CheckConstraint("revision > 0", name="ck_assignments_revision_positive"),
        sa.CheckConstraint(
            "length(btrim(title)) > 0 AND title !~ '^[[:space:]]*$'",
            name="ck_assignments_title_not_blank",
        ),
    )

    course_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        sa.ForeignKey(
            "courses.id",
            ondelete="RESTRICT",
            name="fk_assignments_course_id_courses",
        ),
        nullable=False,
    )
    created_by_teacher_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        sa.ForeignKey(
            "users.id",
            ondelete="RESTRICT",
            name="fk_assignments_created_by_teacher_id_users",
        ),
        nullable=False,
    )
    rubric_version_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        sa.ForeignKey(
            "rubric_versions.id",
            ondelete="RESTRICT",
            name="fk_assignments_rubric_version_id_rubric_versions",
        ),
        nullable=False,
    )
    title: Mapped[str] = mapped_column(sa.String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    due_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True),
        nullable=False,
    )
    first_submission_at: Mapped[datetime | None] = mapped_column(
        sa.DateTime(timezone=True),
        nullable=True,
    )
    max_submissions: Mapped[int] = mapped_column(
        sa.Integer,
        default=3,
        server_default=sa.text("3"),
        nullable=False,
    )
    status: Mapped[AssignmentStatus] = mapped_column(
        pg_enum(AssignmentStatus, name="assignment_status"),
        default=AssignmentStatus.DRAFT,
        nullable=False,
    )
    published_at: Mapped[datetime | None] = mapped_column(
        sa.DateTime(timezone=True),
        nullable=True,
    )
    closed_at: Mapped[datetime | None] = mapped_column(
        sa.DateTime(timezone=True),
        nullable=True,
    )

    course: Mapped[Course] = relationship(
        "Course",
        back_populates="assignments",
        foreign_keys=[course_id],
    )
    created_by_teacher: Mapped[User] = relationship(
        "User",
        back_populates="created_assignments",
        foreign_keys=[created_by_teacher_id],
    )
    rubric_version: Mapped[RubricVersion] = relationship(
        "RubricVersion",
        back_populates="assignments",
        foreign_keys=[rubric_version_id],
    )
    requirements: Mapped[list[AssignmentRequirement]] = relationship(
        "AssignmentRequirement",
        back_populates="assignment",
        cascade="all, delete-orphan",
        foreign_keys="AssignmentRequirement.assignment_id",
    )
    submissions: Mapped[list[Submission]] = relationship(
        "Submission",
        back_populates="assignment",
        foreign_keys="Submission.assignment_id",
        passive_deletes="all",
    )


class AssignmentRequirement(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "assignment_requirements"
    __table_args__ = (
        sa.UniqueConstraint(
            "assignment_id",
            "position",
            name="uq_assignment_requirements_position",
        ),
        sa.CheckConstraint(
            "position > 0",
            name="ck_assignment_requirements_position_positive",
        ),
        sa.CheckConstraint(
            "max_file_size_bytes IS NULL OR max_file_size_bytes > 0",
            name="ck_assignment_requirements_max_file_size_bytes_positive",
        ),
        sa.CheckConstraint(
            "max_page_count IS NULL OR max_page_count > 0",
            name="ck_assignment_requirements_max_page_count_positive",
        ),
        sa.CheckConstraint(
            "length(btrim(kind)) > 0 AND kind !~ '^[[:space:]]*$'",
            name="ck_assignment_requirements_kind_not_blank",
        ),
        sa.CheckConstraint(
            "length(btrim(label)) > 0 AND label !~ '^[[:space:]]*$'",
            name="ck_assignment_requirements_label_not_blank",
        ),

    )
    assignment_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        sa.ForeignKey(
            "assignments.id",
            ondelete="CASCADE",
            name="fk_assignment_requirements_assignment_id_assignments",
        ),
        nullable=False,
    )
    kind: Mapped[str] = mapped_column(sa.String(32), nullable=False)
    label: Mapped[str] = mapped_column(sa.String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    is_required: Mapped[bool] = mapped_column(
        sa.Boolean,
        default=True,
        server_default=sa.text("true"),
        nullable=False,
    )
    position: Mapped[int] = mapped_column(sa.Integer, nullable=False)
    max_file_size_bytes: Mapped[int | None] = mapped_column(
        sa.BigInteger,
        nullable=True,
    )
    max_page_count: Mapped[int | None] = mapped_column(
        sa.Integer,
        nullable=True,
    )
    text_layer_required: Mapped[bool] = mapped_column(
        sa.Boolean,
        default=True,
        server_default=sa.text("true"),
        nullable=False,
    )
    template_version_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        sa.ForeignKey(
            "template_versions.id",
            ondelete="RESTRICT",
            name="fk_assignment_requirements_template_version_template_versions",
        ),
        nullable=True,
    )

    assignment: Mapped[Assignment] = relationship(
        "Assignment",
        back_populates="requirements",
        foreign_keys=[assignment_id],
    )
    template_version: Mapped[TemplateVersion | None] = relationship(
        "TemplateVersion",
        back_populates="assignment_requirements",
        foreign_keys=[template_version_id],
    )
