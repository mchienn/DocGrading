from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Any

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.enums import AuditActorType, pg_enum
from app.models.mixins import UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from app.models.identity import User


class AuditEvent(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "audit_events"
    __table_args__ = (
        sa.CheckConstraint(
            "(actor_type = 'USER' AND actor_user_id IS NOT NULL) "
            "OR (actor_type = 'SYSTEM' AND actor_user_id IS NULL)",
            name="ck_audit_events_actor",
        ),
        sa.CheckConstraint(
            "before IS NOT NULL OR after IS NOT NULL",
            name="ck_audit_events_snapshots",
        ),
        sa.CheckConstraint(
            "before IS NULL OR jsonb_typeof(before) = 'object'",
            name="ck_audit_events_before_object",
        ),
        sa.CheckConstraint(
            "after IS NULL OR jsonb_typeof(after) = 'object'",
            name="ck_audit_events_after_object",
        ),
        sa.CheckConstraint(
            "reason !~ '^[[:space:]]*$'",
            name="ck_audit_events_reason_not_blank",
        ),
        sa.CheckConstraint(
            "length(btrim(resource_type)) > 0 "
            "AND resource_type !~ '^[[:space:]]*$'",
            name="ck_audit_events_resource_type_not_blank",
        ),
        sa.CheckConstraint(
            "length(btrim(action)) > 0 AND action !~ '^[[:space:]]*$'",
            name="ck_audit_events_action_not_blank",
        ),
        sa.Index("ix_audit_events_resource", "resource_type", "resource_id"),
        sa.Index("ix_audit_events_occurred_at", "occurred_at"),
    )

    resource_type: Mapped[str] = mapped_column(sa.String(128), nullable=False)
    resource_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        nullable=False,
    )
    action: Mapped[str] = mapped_column(sa.String(128), nullable=False)
    actor_type: Mapped[AuditActorType] = mapped_column(
        pg_enum(AuditActorType, name="audit_actor_type"),
        nullable=False,
    )
    actor_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        sa.ForeignKey(
            "users.id",
            ondelete="RESTRICT",
            name="fk_audit_events_actor_user_id_users",
        ),
        nullable=True,
    )
    before: Mapped[dict[str, Any] | None] = mapped_column(
        JSONB,
        nullable=True,
    )
    after: Mapped[dict[str, Any] | None] = mapped_column(
        JSONB,
        nullable=True,
    )
    reason: Mapped[str] = mapped_column(
        sa.Text,
        nullable=False,
    )
    occurred_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True),
        server_default=sa.func.now(),
        nullable=False,
    )

    actor_user: Mapped[User | None] = relationship(
        "User",
        back_populates="audit_events",
        foreign_keys=[actor_user_id],
    )
