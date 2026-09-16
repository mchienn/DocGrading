from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.enums import (
    CourseStatus,
    MembershipJoinedVia,
    MembershipRole,
    MembershipStatus,
    pg_enum,
)
from app.models.mixins import RevisionMixin, TimestampMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from app.models.assignment import Assignment
    from app.models.identity import User


class Course(UUIDPrimaryKeyMixin, TimestampMixin, RevisionMixin, Base):
    __tablename__ = "courses"
    __table_args__ = (
        sa.UniqueConstraint("code", name="uq_courses_code"),
        sa.CheckConstraint(
            "length(btrim(code)) > 0 AND code !~ '^[[:space:]]*$'",
            name="ck_courses_code_not_blank",
        ),
        sa.CheckConstraint(
            "length(btrim(name)) > 0 AND name !~ '^[[:space:]]*$'",
            name="ck_courses_name_not_blank",
        ),
        sa.CheckConstraint(
            "length(btrim(term)) > 0 AND term !~ '^[[:space:]]*$'",
            name="ck_courses_term_not_blank",
        ),
        sa.CheckConstraint("revision > 0", name="ck_courses_revision_positive"),
    )

    code: Mapped[str] = mapped_column(sa.String(64), nullable=False)
    name: Mapped[str] = mapped_column(sa.String(255), nullable=False)
    term: Mapped[str] = mapped_column(sa.String(128), nullable=False)
    status: Mapped[CourseStatus] = mapped_column(
        pg_enum(CourseStatus, name="course_status"),
        default=CourseStatus.ACTIVE,
        nullable=False,
    )
    owner_teacher_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        sa.ForeignKey(
            "users.id",
            ondelete="RESTRICT",
            name="fk_courses_owner_teacher_id_users",
        ),
        nullable=False,
    )

    owner: Mapped[User] = relationship(
        "User",
        back_populates="owned_courses",
        foreign_keys=[owner_teacher_id],
    )
    memberships: Mapped[list[Membership]] = relationship(
        "Membership",
        back_populates="course",
        cascade="all, delete-orphan",
        foreign_keys="Membership.course_id",
    )
    invites: Mapped[list[CourseInvite]] = relationship(
        "CourseInvite",
        back_populates="course",
        cascade="all, delete-orphan",
        foreign_keys="CourseInvite.course_id",
    )
    assignments: Mapped[list[Assignment]] = relationship(
        "Assignment",
        back_populates="course",
        foreign_keys="Assignment.course_id",
    )
    join_codes: Mapped[list[CourseJoinCode]] = relationship(
        "CourseJoinCode",
        back_populates="course",
        cascade="all, delete-orphan",
        foreign_keys="CourseJoinCode.course_id",
    )


class CourseJoinCode(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "course_join_codes"
    __table_args__ = (
        sa.UniqueConstraint("code", name="uq_course_join_codes_code"),
        sa.Index(
            "uq_course_join_codes_course_active",
            "course_id",
            unique=True,
            postgresql_where=sa.text("revoked_at IS NULL"),
        ),
        sa.CheckConstraint(
            "length(code) = 20 AND code ~ '^[ABCDEFGHJKMNPQRSTUVWXYZ23456789]{20}$'",
            name="ck_course_join_codes_code_shape",
        ),
        sa.CheckConstraint(
            "expires_at > created_at",
            name="ck_course_join_codes_expiry_after_creation",
        ),
    )

    course_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        sa.ForeignKey(
            "courses.id",
            ondelete="CASCADE",
            name="fk_course_join_codes_course_id_courses",
        ),
        nullable=False,
    )
    code: Mapped[str] = mapped_column(sa.String(20), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), nullable=False
    )
    revoked_at: Mapped[datetime | None] = mapped_column(
        sa.DateTime(timezone=True), nullable=True
    )
    course: Mapped[Course] = relationship(
        "Course",
        back_populates="join_codes",
        foreign_keys=[course_id],
    )


class JoinRateLimit(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "join_rate_limits"
    subject_hash: Mapped[str] = mapped_column(
        sa.String(64), nullable=False, unique=True
    )
    window_started_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), nullable=False
    )
    request_count: Mapped[int] = mapped_column(
        sa.Integer, nullable=False, server_default=sa.text("0")
    )


class Membership(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "memberships"
    __table_args__ = (
        sa.UniqueConstraint(
            "course_id",
            "user_id",
            "role",
            name="uq_memberships_course_user_role",
        ),
    )

    course_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        sa.ForeignKey(
            "courses.id",
            ondelete="CASCADE",
            name="fk_memberships_course_id_courses",
        ),
        nullable=False,
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        sa.ForeignKey(
            "users.id",
            ondelete="RESTRICT",
            name="fk_memberships_user_id_users",
        ),
        nullable=False,
    )
    role: Mapped[MembershipRole] = mapped_column(
        pg_enum(MembershipRole, name="membership_role"),
        nullable=False,
    )
    status: Mapped[MembershipStatus] = mapped_column(
        pg_enum(MembershipStatus, name="membership_status"),
        default=MembershipStatus.ACTIVE,
        nullable=False,
    )
    joined_via: Mapped[MembershipJoinedVia] = mapped_column(
        pg_enum(MembershipJoinedVia, name="membership_joined_via"),
        default=MembershipJoinedVia.MANUAL,
        server_default=sa.text("'MANUAL'::membership_joined_via"),
        nullable=False,
    )
    joined_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        server_default=sa.func.now(),
        nullable=False,
    )
    course: Mapped[Course] = relationship(
        "Course",
        back_populates="memberships",
        foreign_keys=[course_id],
    )
    user: Mapped[User] = relationship(
        "User",
        back_populates="memberships",
        foreign_keys=[user_id],
    )


class CourseInvite(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "course_invites"
    __table_args__ = (
        sa.Index(
            "uq_course_invites_course_email_lower",
            "course_id",
            sa.func.lower(sa.column("email")),
            unique=True,
        ),
        sa.CheckConstraint(
            "length(btrim(email)) > 0 AND email !~ '^[[:space:]]*$'",
            name="ck_course_invites_email_not_blank",
        ),
    )

    course_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        sa.ForeignKey(
            "courses.id",
            ondelete="CASCADE",
            name="fk_course_invites_course_id_courses",
        ),
        nullable=False,
    )
    email: Mapped[str] = mapped_column(sa.String(320), nullable=False)
    created_by_user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        sa.ForeignKey(
            "users.id",
            ondelete="RESTRICT",
            name="fk_course_invites_created_by_user_id_users",
        ),
        nullable=False,
    )

    course: Mapped[Course] = relationship(
        "Course",
        back_populates="invites",
        foreign_keys=[course_id],
    )
    created_by_user: Mapped[User] = relationship(
        "User",
        back_populates="created_course_invites",
        foreign_keys=[created_by_user_id],
    )
