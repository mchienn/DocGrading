from __future__ import annotations

import uuid
from typing import Any

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.mixins import TimestampMixin, UUIDPrimaryKeyMixin


class ChatSession(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A saved teacher chat ("tab" / history entry) with its selected scope."""

    __tablename__ = "chat_sessions"
    __table_args__ = (
        sa.CheckConstraint(
            "length(btrim(title)) > 0", name="ck_chat_sessions_title_not_blank"
        ),
        sa.CheckConstraint(
            "NOT (all_courses AND course_id IS NOT NULL)",
            name="ck_chat_sessions_all_courses_without_course",
        ),
        sa.Index(
            "ix_chat_sessions_owner_user_id_updated_at", "owner_user_id", "updated_at"
        ),
    )

    owner_user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        sa.ForeignKey(
            "users.id",
            ondelete="CASCADE",
            name="fk_chat_sessions_owner_user_id_users",
        ),
        nullable=False,
    )
    title: Mapped[str] = mapped_column(sa.Text, nullable=False)
    course_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        sa.ForeignKey(
            "courses.id",
            ondelete="SET NULL",
            name="fk_chat_sessions_course_id_courses",
        ),
        nullable=True,
    )
    all_courses: Mapped[bool] = mapped_column(
        sa.Boolean, default=False, server_default=sa.false(), nullable=False
    )
    submission_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        sa.ForeignKey(
            "submissions.id",
            ondelete="SET NULL",
            name="fk_chat_sessions_submission_id_submissions",
        ),
        nullable=True,
    )
    is_pinned: Mapped[bool] = mapped_column(
        sa.Boolean, default=False, server_default=sa.false(), nullable=False
    )


class ChatMessage(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """One turn in a ChatSession; ``payload`` keeps the structured response."""

    __tablename__ = "chat_messages"
    __table_args__ = (
        sa.CheckConstraint(
            "sender IN ('user', 'bot')", name="ck_chat_messages_sender_valid"
        ),
        sa.CheckConstraint(
            "jsonb_typeof(payload) = 'object'",
            name="ck_chat_messages_payload_object",
        ),
        sa.Index("ix_chat_messages_session_id_created_at", "session_id", "created_at"),
    )

    session_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        sa.ForeignKey(
            "chat_sessions.id",
            ondelete="CASCADE",
            name="fk_chat_messages_session_id_chat_sessions",
        ),
        nullable=False,
    )
    sender: Mapped[str] = mapped_column(sa.Text, nullable=False)
    content: Mapped[str] = mapped_column(sa.Text, nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(
        JSONB,
        default=dict,
        server_default=sa.text("'{}'::jsonb"),
        nullable=False,
    )
