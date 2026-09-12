from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.api.schemas_notification import (
    NotificationBulkReadRequest,
    NotificationBulkReadResponse,
    NotificationListResponse,
    NotificationResponse,
)
from app.db.session import get_db_session
from app.models.identity import User
from app.services import notification as notification_svc

router = APIRouter(prefix="/notifications", tags=["notifications"])


@router.get("", response_model=NotificationListResponse)
async def list_notifications(
    unread: bool | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=100),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> NotificationListResponse:
    return await notification_svc.list_notifications(
        db,
        user=user,
        unread=unread,
        page=page,
        page_size=page_size,
    )


@router.patch("/read", response_model=NotificationBulkReadResponse)
async def mark_notifications_read(
    body: NotificationBulkReadRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> NotificationBulkReadResponse:
    response = await notification_svc.mark_notifications_read(
        db, notification_ids=body.notification_ids, user=user
    )
    await db.commit()
    return response


@router.patch("/{notification_id}/read", response_model=NotificationResponse)
async def mark_notification_read(
    notification_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> NotificationResponse:
    response = await notification_svc.mark_notification_read(
        db, notification_id=notification_id, user=user
    )
    await db.commit()
    return response
