"""Rubric CRUD, publish, versioning, and criteria management endpoints."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, require_roles
from app.api.schemas_rubric import (
    CriterionCreate,
    CriterionResponse,
    CriterionUpdate,
    RubricVersionCreate,
    RubricVersionResponse,
    RubricVersionUpdate,
)
from app.db.session import get_db_session
from app.models.enums import UserRole
from app.models.identity import User
from app.models.rubric import CriterionVersion, RubricVersion
from app.services import rubric as rubric_svc
from app.services.rubric import _check_rubric_ownership

router = APIRouter(prefix="/rubrics", tags=["rubrics"])


# ---------------------------------------------------------------------------
# RubricVersion endpoints
# ---------------------------------------------------------------------------


@router.post("", response_model=RubricVersionResponse, status_code=201)
async def create_rubric(
    body: RubricVersionCreate,
    user: User = Depends(require_roles(UserRole.ADMIN, UserRole.TEACHER)),
    db: AsyncSession = Depends(get_db_session),
) -> RubricVersionResponse:
    """Create a new rubric version (Teacher/Admin)."""
    rv = await rubric_svc.create_rubric_version(
        db,
        owner_user_id=user.id,
        created_by_user_id=user.id,
        name=body.name,
        description=body.description,
        calculation_method=body.calculation_method,
    )
    await db.commit()
    return RubricVersionResponse.model_validate(rv)


@router.get("", response_model=list[RubricVersionResponse])
async def list_rubrics(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> list[RubricVersionResponse]:
    """List rubric versions. Admin sees all; others see own."""
    owner_id = None if UserRole.ADMIN in user.roles else user.id
    rubrics = await rubric_svc.list_rubric_versions(db, owner_user_id=owner_id)
    return [RubricVersionResponse.model_validate(r) for r in rubrics]


async def _get_owned_rubric(
    rubric_id: uuid.UUID,
    user: User = Depends(require_roles(UserRole.ADMIN, UserRole.TEACHER)),
    db: AsyncSession = Depends(get_db_session),
) -> RubricVersion:
    """Load rubric version and verify ownership."""
    rv = await rubric_svc.get_rubric_version(db, rubric_id)
    if rv is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Rubric version not found",
        )
    _check_rubric_ownership(rv, user.id, [r.value for r in user.roles])
    return rv


@router.get("/{rubric_id}", response_model=RubricVersionResponse)
async def get_rubric(
    rv: RubricVersion = Depends(_get_owned_rubric),
) -> RubricVersionResponse:
    """Get a single rubric version (owner/Admin)."""
    return RubricVersionResponse.model_validate(rv)


@router.put("/{rubric_id}", response_model=RubricVersionResponse)
async def update_rubric(
    body: RubricVersionUpdate,
    rv: RubricVersion = Depends(_get_owned_rubric),
    user: User = Depends(require_roles(UserRole.ADMIN, UserRole.TEACHER)),
    db: AsyncSession = Depends(get_db_session),
) -> RubricVersionResponse:
    """Update a DRAFT rubric version (owner/Admin)."""
    rv = await rubric_svc.update_rubric_version(
        db,
        rv,
        actor_user_id=user.id,
        name=body.name,
        description=body.description,
        calculation_method=body.calculation_method,
    )
    await db.commit()
    return RubricVersionResponse.model_validate(rv)


@router.post("/{rubric_id}/publish", response_model=RubricVersionResponse)
async def publish_rubric(
    rv: RubricVersion = Depends(_get_owned_rubric),
    user: User = Depends(require_roles(UserRole.ADMIN, UserRole.TEACHER)),
    db: AsyncSession = Depends(get_db_session),
) -> RubricVersionResponse:
    """Publish a DRAFT rubric version."""
    rv = await rubric_svc.publish_rubric_version(db, rv, actor_user_id=user.id)
    await db.commit()
    return RubricVersionResponse.model_validate(rv)


@router.post("/{rubric_id}/new-version", response_model=RubricVersionResponse)
async def create_new_version(
    rv: RubricVersion = Depends(_get_owned_rubric),
    user: User = Depends(require_roles(UserRole.ADMIN, UserRole.TEACHER)),
    db: AsyncSession = Depends(get_db_session),
) -> RubricVersionResponse:
    """Create a new DRAFT version from a published rubric."""
    new_rv = await rubric_svc.create_new_version_from(db, rv, actor_user_id=user.id)
    await db.commit()
    return RubricVersionResponse.model_validate(new_rv)


# ---------------------------------------------------------------------------
# CriterionVersion endpoints
# ---------------------------------------------------------------------------


@router.post(
    "/{rubric_id}/criteria",
    response_model=CriterionResponse,
    status_code=201,
)
async def add_criterion(
    body: CriterionCreate,
    rv: RubricVersion = Depends(_get_owned_rubric),
    user: User = Depends(require_roles(UserRole.ADMIN, UserRole.TEACHER)),
    db: AsyncSession = Depends(get_db_session),
) -> CriterionResponse:
    """Add a criterion to a DRAFT rubric version."""
    cv = await rubric_svc.add_criterion(
        db,
        rv,
        actor_user_id=user.id,
        code=body.code,
        title=body.title,
        description=body.description,
        weight=body.weight,
        position=body.position,
        evaluation_method=body.evaluation_method,
        scope=body.scope,
        is_enabled=body.is_enabled,
        levels=body.levels,
        evaluator_config=body.evaluator_config,
        evidence_requirements=body.evidence_requirements,
    )
    await db.commit()
    return CriterionResponse.model_validate(cv)


@router.get("/{rubric_id}/criteria", response_model=list[CriterionResponse])
async def list_criteria(
    rv: RubricVersion = Depends(_get_owned_rubric),
    db: AsyncSession = Depends(get_db_session),
) -> list[CriterionResponse]:
    """List criteria for a rubric version."""
    criteria = await rubric_svc.list_criteria(db, rv.id)
    return [CriterionResponse.model_validate(c) for c in criteria]


async def _get_criterion(
    criterion_id: uuid.UUID,
    rv: RubricVersion = Depends(_get_owned_rubric),
    db: AsyncSession = Depends(get_db_session),
) -> tuple[RubricVersion, CriterionVersion]:
    """Load criterion and verify it belongs to the rubric."""
    cv = await db.get(CriterionVersion, criterion_id)
    if cv is None or cv.rubric_version_id != rv.id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Criterion not found",
        )
    return rv, cv


@router.put(
    "/{rubric_id}/criteria/{criterion_id}",
    response_model=CriterionResponse,
)
async def update_criterion(
    body: CriterionUpdate,
    rv_cv: tuple[RubricVersion, CriterionVersion] = Depends(_get_criterion),
    user: User = Depends(require_roles(UserRole.ADMIN, UserRole.TEACHER)),
    db: AsyncSession = Depends(get_db_session),
) -> CriterionResponse:
    """Update a criterion on a DRAFT rubric version."""
    rv, cv = rv_cv
    cv = await rubric_svc.update_criterion(
        db,
        rv,
        cv,
        actor_user_id=user.id,
        title=body.title,
        description=body.description,
        weight=body.weight,
        position=body.position,
        is_enabled=body.is_enabled,
        evaluation_method=body.evaluation_method,
        scope=body.scope,
        levels=body.levels,
        evaluator_config=body.evaluator_config,
        evidence_requirements=body.evidence_requirements,
    )
    await db.commit()
    return CriterionResponse.model_validate(cv)


@router.delete("/{rubric_id}/criteria/{criterion_id}", status_code=204)
async def delete_criterion(
    rv_cv: tuple[RubricVersion, CriterionVersion] = Depends(_get_criterion),
    user: User = Depends(require_roles(UserRole.ADMIN, UserRole.TEACHER)),
    db: AsyncSession = Depends(get_db_session),
) -> None:
    """Delete a criterion from a DRAFT rubric version."""
    rv, cv = rv_cv
    await rubric_svc.delete_criterion(db, rv, cv, actor_user_id=user.id)
    await db.commit()
