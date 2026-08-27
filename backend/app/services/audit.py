"""Audit service: structured event recording for sensitive actions."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.audit import AuditEvent
from app.models.enums import AuditActorType


async def record_audit(
    db: AsyncSession,
    *,
    actor_user_id: uuid.UUID,
    resource_type: str,
    resource_id: uuid.UUID,
    action: str,
    before: dict[str, Any] | None = None,
    after: dict[str, Any] | None = None,
    reason: str,
) -> AuditEvent:
    """Create an ``AuditEvent`` in the current transaction.

    The caller is responsible for committing the enclosing transaction so
    the audit record is atomically persisted with the domain change.
    """
    event = AuditEvent(
        id=uuid.uuid4(),
        resource_type=resource_type,
        resource_id=resource_id,
        action=action,
        actor_type=AuditActorType.USER,
        actor_user_id=actor_user_id,
        before=before,
        after=after,
        reason=reason,
    )
    db.add(event)
    await db.flush()
    return event


async def record_system_audit(
    db: AsyncSession,
    *,
    resource_type: str,
    resource_id: uuid.UUID,
    action: str,
    before: dict[str, Any] | None = None,
    after: dict[str, Any] | None = None,
    reason: str,
) -> AuditEvent:
    """Create a ``SYSTEM``-actor ``AuditEvent``."""
    event = AuditEvent(
        id=uuid.uuid4(),
        resource_type=resource_type,
        resource_id=resource_id,
        action=action,
        actor_type=AuditActorType.SYSTEM,
        actor_user_id=None,
        before=before,
        after=after,
        reason=reason,
    )
    db.add(event)
    await db.flush()
    return event
