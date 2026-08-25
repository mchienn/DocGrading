from __future__ import annotations

from typing import TYPE_CHECKING
import uuid
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.enums import MembershipRole, MembershipStatus, pg_enum
from app.models.mixins import RevisionMixin, TimestampMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from app.models.assignment import Assignment
    from app.models.identity import User


class Course(UUIDPrimaryKeyMixin, TimestampMixin, RevisionMixin, Base):
    __tablename__ = "courses"
    __table_args__ = (
        sa.UniqueConstraint("code", name="uq_courses_code"),
        sa.CheckConstraint("revision > 0", name="ck_courses_revision_positive"),
    )

    code: Mapped[str] = mapped_column(sa.String(64), nullable=False)
    name: Mapped[str] = mapped_column(sa.String(255), nullable=False)
    term: Mapped[str] = mapped_column(sa.String(128), nullable=False)
    owner_teacher_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        sa.ForeignKey("users.id", ondelete="RESTRICT", name="fk_courses_owner_teacher_id_users"),
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
    assignments: Mapped[list[Assignment]] = relationship(
        "Assignment",
        back_populates="course",
        foreign_keys="Assignment.course_id",
    )


class Membership(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "memberships"
    __table_args__ = (
        sa.UniqueConstraint("course_id", "user_id", "role", name="uq_memberships_course_user_role"),
    )

    course_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        sa.ForeignKey("courses.id", ondelete="CASCADE", name="fk_memberships_course_id_courses"),
        nullable=False,
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        sa.ForeignKey("users.id", ondelete="RESTRICT", name="fk_memberships_user_id_users"),
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
