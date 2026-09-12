from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, Field, field_validator, model_validator

from app.models.enums import NOTIFICATION_PAYLOAD_KEYS, NotificationType


class NotificationResponse(BaseModel):
    id: uuid.UUID
    type: NotificationType
    payload: dict[str, uuid.UUID]
    read_at: datetime | None
    created_at: datetime

    model_config = {"extra": "forbid", "from_attributes": True}

    @model_validator(mode="after")
    def validate_payload_references(self) -> NotificationResponse:
        expected = NOTIFICATION_PAYLOAD_KEYS[self.type]
        if set(self.payload) != expected:
            raise ValueError("Notification payload contains invalid references")
        return self


class NotificationListResponse(BaseModel):
    items: list[NotificationResponse]
    page: int
    page_size: int
    total: int

    model_config = {"extra": "forbid"}


class NotificationBulkReadRequest(BaseModel):
    notification_ids: list[uuid.UUID] = Field(min_length=1, max_length=100)

    model_config = {"extra": "forbid"}

    @field_validator("notification_ids")
    @classmethod
    def require_unique_ids(cls, value: list[uuid.UUID]) -> list[uuid.UUID]:
        if len(set(value)) != len(value):
            raise ValueError("notification_ids must be unique")
        return value


class NotificationBulkReadResponse(BaseModel):
    items: list[NotificationResponse]

    model_config = {"extra": "forbid"}
