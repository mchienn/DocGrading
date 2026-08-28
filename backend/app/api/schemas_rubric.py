"""Pydantic schemas for Rubric API."""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, Field

# ---------------------------------------------------------------------------
# RubricVersion
# ---------------------------------------------------------------------------


class RubricVersionCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    description: str | None = None
    calculation_method: str = Field(default="WEIGHTED_SUM", min_length=1, max_length=64)


class RubricVersionUpdate(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=255)
    description: str | None = None
    calculation_method: str | None = Field(None, min_length=1, max_length=64)


class RubricVersionResponse(BaseModel):
    id: uuid.UUID
    rubric_id: uuid.UUID
    version_number: int
    name: str
    description: str | None
    status: str
    calculation_method: str
    total_weight: Decimal
    owner_user_id: uuid.UUID
    created_by_user_id: uuid.UUID
    source_version_id: uuid.UUID | None
    published_at: datetime | None
    revision: int

    model_config = {"from_attributes": True}


# ---------------------------------------------------------------------------
# CriterionVersion
# ---------------------------------------------------------------------------


class CriterionCreate(BaseModel):
    code: str = Field(min_length=1, max_length=64)
    title: str = Field(min_length=1, max_length=255)
    description: str = Field(min_length=1)
    weight: Decimal = Field(ge=0, le=100)
    position: int = Field(ge=1)
    evaluation_method: str = Field(default="AI", min_length=1, max_length=64)
    scope: str | None = None
    is_enabled: bool = True
    levels: list[dict[str, Any]] = Field(default_factory=list)
    evaluator_config: dict[str, Any] = Field(default_factory=dict)
    evidence_requirements: dict[str, Any] = Field(default_factory=dict)


class CriterionUpdate(BaseModel):
    title: str | None = Field(None, min_length=1, max_length=255)
    description: str | None = Field(None, min_length=1)
    weight: Decimal | None = Field(None, ge=0, le=100)
    position: int | None = Field(None, ge=1)
    evaluation_method: str | None = Field(None, min_length=1, max_length=64)
    scope: str | None = None
    is_enabled: bool | None = None
    levels: list[dict[str, Any]] | None = None
    evaluator_config: dict[str, Any] | None = None
    evidence_requirements: dict[str, Any] | None = None


class CriterionResponse(BaseModel):
    id: uuid.UUID
    criterion_id: uuid.UUID
    rubric_version_id: uuid.UUID
    code: str
    title: str
    description: str
    scope: str | None
    weight: Decimal
    position: int
    is_enabled: bool
    evaluation_method: str
    levels: list[dict[str, Any]]
    evaluator_config: dict[str, Any]
    evidence_requirements: dict[str, Any]
    revision: int

    model_config = {"from_attributes": True}
