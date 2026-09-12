from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.enums import NotificationType, pg_enum
from app.models.mixins import UUIDPrimaryKeyMixin


class Notification(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "notifications"
    __table_args__ = (
        sa.CheckConstraint(
            "jsonb_typeof(payload) = 'object'",
            name="ck_notifications_payload_object",
        ),
        sa.ForeignKeyConstraint(
            ["recipient_id"],
            ["users.id"],
            name="fk_notifications_recipient_id_users",
            ondelete="RESTRICT",
        ),
        sa.Index(
            "ix_notifications_recipient_created_at",
            "recipient_id",
            "created_at",
        ),
        sa.Index(
            "ix_notifications_recipient_unread",
            "recipient_id",
            postgresql_where=sa.text("read_at IS NULL"),
        ),
    )

    recipient_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    type: Mapped[NotificationType] = mapped_column(
        pg_enum(NotificationType, name="notification_type"), nullable=False
    )
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    read_at: Mapped[datetime | None] = mapped_column(
        sa.DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
    )
