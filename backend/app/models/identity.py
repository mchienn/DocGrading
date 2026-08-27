from __future__ import annotations

from typing import TYPE_CHECKING

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.ext.mutable import MutableList
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.enums import UserRole, UserStatus, pg_enum
from app.models.mixins import RevisionMixin, TimestampMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from app.models.assignment import Assignment
    from app.models.audit import AuditEvent
    from app.models.course import Course, Membership
    from app.models.rubric import RubricVersion, TemplateVersion
    from app.models.submission import Submission


class User(UUIDPrimaryKeyMixin, TimestampMixin, RevisionMixin, Base):
    __tablename__ = "users"
    __table_args__ = (
        sa.CheckConstraint(
            "cardinality(roles) > 0 "
            "AND array_position(roles, NULL::user_role) IS NULL",
            name="ck_users_roles_not_empty",
        ),
        sa.CheckConstraint(
            "length(btrim(email)) > 0 AND email !~ '^[[:space:]]*$'",
            name="ck_users_email_not_blank",
        ),
        sa.CheckConstraint(
            "length(btrim(display_name)) > 0 " "AND display_name !~ '^[[:space:]]*$'",
            name="ck_users_display_name_not_blank",
        ),
        sa.CheckConstraint(
            "length(btrim(password_hash)) > 0 " "AND password_hash !~ '^[[:space:]]*$'",
            name="ck_users_password_hash_not_blank",
        ),
        sa.CheckConstraint("revision > 0", name="ck_users_revision_positive"),
        sa.Index(
            "uq_users_email_lower",
            sa.func.lower(sa.column("email")),
            unique=True,
        ),
    )

    email: Mapped[str] = mapped_column(sa.String(320), nullable=False)
    display_name: Mapped[str] = mapped_column(sa.String(255), nullable=False)
    password_hash: Mapped[str] = mapped_column(sa.String(255), nullable=False)
    roles: Mapped[list[UserRole]] = mapped_column(
        MutableList.as_mutable(ARRAY(pg_enum(UserRole, name="user_role"))),
        default=list,
        nullable=False,
    )
    status: Mapped[UserStatus] = mapped_column(
        pg_enum(UserStatus, name="user_status"),
        default=UserStatus.ACTIVE,
        nullable=False,
    )

    owned_courses: Mapped[list[Course]] = relationship(
        "Course",
        back_populates="owner",
        foreign_keys="Course.owner_teacher_id",
    )
    memberships: Mapped[list[Membership]] = relationship(
        "Membership",
        back_populates="user",
        foreign_keys="Membership.user_id",
    )
    created_assignments: Mapped[list[Assignment]] = relationship(
        "Assignment",
        back_populates="created_by_teacher",
        foreign_keys="Assignment.created_by_teacher_id",
    )
    owned_rubric_versions: Mapped[list[RubricVersion]] = relationship(
        "RubricVersion",
        back_populates="owner",
        foreign_keys="RubricVersion.owner_user_id",
    )
    created_rubric_versions: Mapped[list[RubricVersion]] = relationship(
        "RubricVersion",
        back_populates="created_by_user",
        foreign_keys="RubricVersion.created_by_user_id",
    )
    owned_template_versions: Mapped[list[TemplateVersion]] = relationship(
        "TemplateVersion",
        back_populates="owner",
        foreign_keys="TemplateVersion.owner_user_id",
    )
    created_template_versions: Mapped[list[TemplateVersion]] = relationship(
        "TemplateVersion",
        back_populates="created_by_user",
        foreign_keys="TemplateVersion.created_by_user_id",
    )
    submissions: Mapped[list[Submission]] = relationship(
        "Submission",
        back_populates="student",
        foreign_keys="Submission.student_id",
        passive_deletes="all",
    )
    audit_events: Mapped[list[AuditEvent]] = relationship(
        "AuditEvent",
        back_populates="actor_user",
        foreign_keys="AuditEvent.actor_user_id",
        passive_deletes="all",
    )
