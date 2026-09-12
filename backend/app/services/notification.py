from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

import sqlalchemy as sa
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.schemas_notification import (
    NotificationBulkReadResponse,
    NotificationListResponse,
    NotificationResponse,
)
from app.models.enums import NOTIFICATION_PAYLOAD_KEYS, NotificationType
from app.models.identity import User
from app.models.notification import Notification


def _reference_payload(
    notification_type: NotificationType, payload: dict[str, Any]
) -> dict[str, str]:
    if set(payload) != NOTIFICATION_PAYLOAD_KEYS[notification_type]:
        raise ValueError("Notification payload contains invalid references")
    try:
        return {key: str(uuid.UUID(str(value))) for key, value in payload.items()}
    except (AttributeError, TypeError, ValueError) as exc:
        raise ValueError("Notification payload contains invalid references") from exc


async def add_notification(
    db: AsyncSession,
    *,
    recipient_id: uuid.UUID,
    notification_type: NotificationType,
    payload: dict[str, Any],
) -> Notification:
    notification = Notification(
        id=uuid.uuid4(),
        recipient_id=recipient_id,
        type=notification_type,
        payload=_reference_payload(notification_type, payload),
    )
    db.add(notification)
    await db.flush()
    return notification


async def list_notifications(
    db: AsyncSession,
    *,
    user: User,
    unread: bool | None,
    page: int,
    page_size: int,
) -> NotificationListResponse:
    filters = [Notification.recipient_id == user.id]
    if unread is True:
        filters.append(Notification.read_at.is_(None))
    elif unread is False:
        filters.append(Notification.read_at.is_not(None))

    total = (
        await db.execute(
            sa.select(sa.func.count()).select_from(Notification).where(*filters)
        )
    ).scalar_one()
    notifications = list(
        (
            await db.execute(
                sa.select(Notification)
                .where(*filters)
                .order_by(Notification.created_at.desc(), Notification.id)
                .offset((page - 1) * page_size)
                .limit(page_size)
            )
        ).scalars()
    )
    return NotificationListResponse(
        items=[NotificationResponse.model_validate(item) for item in notifications],
        page=page,
        page_size=page_size,
        total=total,
    )


async def mark_notification_read(
    db: AsyncSession, *, notification_id: uuid.UUID, user: User
) -> NotificationResponse:
    notification = (
        await db.execute(
            sa.select(Notification)
            .where(
                Notification.id == notification_id,
                Notification.recipient_id == user.id,
            )
            .with_for_update()
        )
    ).scalar_one_or_none()
    if notification is None:
        raise HTTPException(status_code=404, detail="Notification not found")
    if notification.read_at is None:
        notification.read_at = datetime.now(UTC)
        await db.flush()
    return NotificationResponse.model_validate(notification)


async def mark_notifications_read(
    db: AsyncSession, *, notification_ids: list[uuid.UUID], user: User
) -> NotificationBulkReadResponse:
    notifications = list(
        (
            await db.execute(
                sa.select(Notification)
                .where(
                    Notification.id.in_(notification_ids),
                    Notification.recipient_id == user.id,
                )
                .with_for_update()
            )
        ).scalars()
    )
    if len(notifications) != len(notification_ids):
        raise HTTPException(status_code=404, detail="Notification not found")
    notifications_by_id = {
        notification.id: notification for notification in notifications
    }
    now = datetime.now(UTC)
    for notification in notifications:
        if notification.read_at is None:
            notification.read_at = now
    await db.flush()
    return NotificationBulkReadResponse(
        items=[
            NotificationResponse.model_validate(notifications_by_id[notification_id])
            for notification_id in notification_ids
        ]
    )
