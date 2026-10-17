"""Rubric CRUD and criteria management."""

from __future__ import annotations

import uuid
from decimal import Decimal

import sqlalchemy as sa
from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.analysis import AnalysisJob
from app.models.assignment import Assignment
from app.models.enums import RubricStatus
from app.models.rubric import CriterionVersion, RubricVersion
from app.services.audit import record_audit

# ---------------------------------------------------------------------------
# RubricVersion CRUD
# ---------------------------------------------------------------------------


async def create_rubric_version(
    db: AsyncSession,
    *,
    owner_user_id: uuid.UUID,
    created_by_user_id: uuid.UUID,
    name: str,
    description: str | None = None,
    calculation_method: str = "WEIGHTED_SUM",
    rubric_id: uuid.UUID | None = None,
    version_number: int = 1,
    source_version_id: uuid.UUID | None = None,
) -> RubricVersion:
    """Create a new rubric version in DRAFT status."""
    rv = RubricVersion(
        id=uuid.uuid4(),
        rubric_id=rubric_id or uuid.uuid4(),
        version_number=version_number,
        name=name,
        description=description,
        status=RubricStatus.DRAFT,
        calculation_method=calculation_method,
        total_weight=Decimal("0.00"),
        owner_user_id=owner_user_id,
        created_by_user_id=created_by_user_id,
        source_version_id=source_version_id,
    )
    db.add(rv)
    await db.flush()
    await record_audit(
        db,
        actor_user_id=created_by_user_id,
        resource_type="RubricVersion",
        resource_id=rv.id,
        action="CREATE",
        after={
            "name": name,
            "calculation_method": calculation_method,
        },
        reason="Rubric version created",
    )
    await db.flush()
    return rv


async def get_rubric_version(
    db: AsyncSession,
    rubric_version_id: uuid.UUID,
    *,
    load_criteria: bool = False,
) -> RubricVersion | None:
    """Load a single rubric version, optionally with criteria eagerly loaded."""
    if load_criteria:
        stmt = (
            select(RubricVersion)
            .where(RubricVersion.id == rubric_version_id)
            .options(
                selectinload(RubricVersion.criteria),
            )
        )
        result = await db.execute(stmt)
        return result.scalar_one_or_none()
    return await db.get(RubricVersion, rubric_version_id)


async def list_rubric_versions(
    db: AsyncSession,
    *,
    owner_user_id: uuid.UUID | None = None,
    rubric_id: uuid.UUID | None = None,
) -> list[RubricVersion]:
    """List rubric versions, optionally filtered."""
    stmt = select(RubricVersion).order_by(RubricVersion.created_at.desc())
    if owner_user_id is not None:
        stmt = stmt.where(RubricVersion.owner_user_id == owner_user_id)
    if rubric_id is not None:
        stmt = stmt.where(RubricVersion.rubric_id == rubric_id)
    result = await db.execute(stmt)
    return list(result.scalars().all())


def _rubric_mutation_conflict(exc: IntegrityError) -> HTTPException | None:
    if "after first submission" not in str(exc.orig):
        return None
    return HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail="Rubric is immutable after first assignment submission",
    )


async def _flush_rubric_mutation(db: AsyncSession) -> None:
    try:
        await db.flush()
    except IntegrityError as exc:
        conflict = _rubric_mutation_conflict(exc)
        if conflict is None:
            raise
        raise conflict from exc


async def _assert_rubric_mutable(db: AsyncSession, rv: RubricVersion) -> None:
    """Reject rubric changes after any assignment receives a submission."""
    try:
        await db.execute(
            sa.text("SELECT public.fn_assert_criterion_parent_mutable(:parent_id)"),
            {"parent_id": rv.id},
        )
    except IntegrityError as exc:
        conflict = _rubric_mutation_conflict(exc)
        if conflict is None:
            raise
        raise conflict from exc
    stmt = (
        select(Assignment.id)
        .where(
            Assignment.rubric_version_id == rv.id,
            Assignment.first_submission_at.is_not(None),
        )
        .order_by(Assignment.id)
        .limit(1)
    )
    result = await db.execute(stmt)
    if result.scalar_one_or_none() is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Rubric is immutable after first assignment submission",
        )


async def update_rubric_version(
    db: AsyncSession,
    rv: RubricVersion,
    *,
    actor_user_id: uuid.UUID,
    name: str | None = None,
    description: str | None = None,
    description_set: bool = False,
    calculation_method: str | None = None,
) -> RubricVersion:
    """Update a rubric version before assignment submission freeze."""
    await _assert_rubric_mutable(db, rv)

    before: dict[str, object] = {}
    after: dict[str, object] = {}

    if name is not None and name != rv.name:
        before["name"] = rv.name
        rv.name = name
        after["name"] = name

    if description_set and description != rv.description:
        before["description"] = rv.description
        rv.description = description
        after["description"] = description

    if calculation_method is not None and calculation_method != rv.calculation_method:
        before["calculation_method"] = rv.calculation_method
        rv.calculation_method = calculation_method
        after["calculation_method"] = calculation_method

    if after:
        rv.revision += 1
        await record_audit(
            db,
            actor_user_id=actor_user_id,
            resource_type="RubricVersion",
            resource_id=rv.id,
            action="UPDATE",
            before=before,
            after=after,
            reason="Rubric version updated",
        )
        await _flush_rubric_mutation(db)

    return rv


async def delete_rubric_version(
    db: AsyncSession,
    rv: RubricVersion,
    *,
    actor_user_id: uuid.UUID,
) -> None:
    """Delete a rubric version with no references or derived versions."""

    references = (
        (
            select(Assignment.id)
            .where(Assignment.rubric_version_id == rv.id)
            .order_by(Assignment.id)
            .limit(1),
            "assignment",
        ),
        (
            select(AnalysisJob.id)
            .where(AnalysisJob.rubric_version_id == rv.id)
            .order_by(AnalysisJob.id)
            .limit(1),
            "analysis job",
        ),
        (
            select(RubricVersion.id)
            .where(RubricVersion.source_version_id == rv.id)
            .order_by(RubricVersion.id)
            .limit(1),
            "derived rubric version",
        ),
    )
    for stmt, reference_name in references:
        result = await db.execute(stmt)
        if result.scalar_one_or_none() is not None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Cannot delete rubric referenced by {reference_name}",
            )
    await _assert_rubric_mutable(db, rv)

    await record_audit(
        db,
        actor_user_id=actor_user_id,
        resource_type="RubricVersion",
        resource_id=rv.id,
        action="DELETE",
        before={"name": rv.name, "rubric_id": str(rv.rubric_id)},
        reason="Rubric version deleted",
    )
    await db.delete(rv)
    await _flush_rubric_mutation(db)


def _check_rubric_ownership(
    rv: RubricVersion, user_id: uuid.UUID, user_roles: list[str]
) -> None:
    """Raise 403 if user is not Admin and doesn't own the rubric."""
    if "ADMIN" in user_roles:
        return
    if rv.owner_user_id != user_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You do not own this rubric",
        )


# ---------------------------------------------------------------------------
# CriterionVersion CRUD
# ---------------------------------------------------------------------------


async def add_criterion(
    db: AsyncSession,
    rv: RubricVersion,
    *,
    actor_user_id: uuid.UUID,
    code: str,
    title: str,
    description: str,
    weight: Decimal,
    position: int,
    evaluation_method: str = "AI",
    scope: str | None = None,
    is_enabled: bool = True,
    levels: list[dict] | None = None,
    evaluator_config: dict | None = None,
    evidence_requirements: dict | None = None,
) -> CriterionVersion:
    """Add a criterion before assignment submission freeze."""
    await _assert_rubric_mutable(db, rv)

    cv = CriterionVersion(
        id=uuid.uuid4(),
        criterion_id=uuid.uuid4(),
        rubric_version_id=rv.id,
        code=code,
        title=title,
        description=description,
        scope=scope,
        weight=weight,
        position=position,
        is_enabled=is_enabled,
        evaluation_method=evaluation_method,
        levels=levels or [],
        evaluator_config=evaluator_config or {},
        evidence_requirements=evidence_requirements or {},
    )
    db.add(cv)

    # Update rubric total_weight
    rv.total_weight += weight if is_enabled else Decimal("0.00")
    rv.revision += 1

    await record_audit(
        db,
        actor_user_id=actor_user_id,
        resource_type="CriterionVersion",
        resource_id=cv.id,
        action="CREATE",
        after={
            "code": code,
            "title": title,
            "weight": str(weight),
            "rubric_version_id": str(rv.id),
        },
        reason="Criterion added to rubric",
    )
    await _flush_rubric_mutation(db)
    return cv


async def update_criterion(
    db: AsyncSession,
    rv: RubricVersion,
    cv: CriterionVersion,
    *,
    actor_user_id: uuid.UUID,
    title: str | None = None,
    description: str | None = None,
    weight: Decimal | None = None,
    position: int | None = None,
    is_enabled: bool | None = None,
    evaluation_method: str | None = None,
    scope: str | None = None,
    levels: list[dict] | None = None,
    evaluator_config: dict | None = None,
    evidence_requirements: dict | None = None,
) -> CriterionVersion:
    """Update a criterion before assignment submission freeze."""
    await _assert_rubric_mutable(db, rv)

    before: dict[str, object] = {}
    after: dict[str, object] = {}
    if title is not None and title != cv.title:
        before["title"] = cv.title
        cv.title = title
        after["title"] = title

    if description is not None and description != cv.description:
        before["description"] = cv.description
        cv.description = description
        after["description"] = description

    if weight is not None and weight != cv.weight:
        old_weight = cv.weight
        before["weight"] = str(old_weight)
        cv.weight = weight
        after["weight"] = str(weight)
        # Adjust rubric total_weight
        if cv.is_enabled:
            rv.total_weight += weight - old_weight

    if position is not None and position != cv.position:
        before["position"] = cv.position
        cv.position = position
        after["position"] = position

    if is_enabled is not None and is_enabled != cv.is_enabled:
        before["is_enabled"] = cv.is_enabled
        cv.is_enabled = is_enabled
        after["is_enabled"] = is_enabled
        # Adjust rubric total_weight
        if is_enabled:
            rv.total_weight += cv.weight
        else:
            rv.total_weight -= cv.weight

    if evaluation_method is not None and evaluation_method != cv.evaluation_method:
        before["evaluation_method"] = cv.evaluation_method
        cv.evaluation_method = evaluation_method
        after["evaluation_method"] = evaluation_method

    if scope is not None:
        before["scope"] = cv.scope
        cv.scope = scope
        after["scope"] = scope

    if levels is not None:
        cv.levels = levels
        after["levels"] = levels

    if evaluator_config is not None:
        cv.evaluator_config = evaluator_config
        after["evaluator_config"] = evaluator_config

    if evidence_requirements is not None:
        cv.evidence_requirements = evidence_requirements
        after["evidence_requirements"] = evidence_requirements

    if after:
        cv.revision += 1
        rv.revision += 1
        await record_audit(
            db,
            actor_user_id=actor_user_id,
            resource_type="CriterionVersion",
            resource_id=cv.id,
            action="UPDATE",
            before=before,
            after=after,
            reason="Criterion updated",
        )
        await _flush_rubric_mutation(db)

    return cv


async def delete_criterion(
    db: AsyncSession,
    rv: RubricVersion,
    cv: CriterionVersion,
    *,
    actor_user_id: uuid.UUID,
) -> None:
    """Delete a criterion before assignment submission freeze."""
    await _assert_rubric_mutable(db, rv)

    if cv.is_enabled:
        rv.total_weight -= cv.weight
    rv.revision += 1

    await record_audit(
        db,
        actor_user_id=actor_user_id,
        resource_type="CriterionVersion",
        resource_id=cv.id,
        action="DELETE",
        before={
            "code": cv.code,
            "title": cv.title,
            "weight": str(cv.weight),
        },
        reason="Criterion deleted from rubric",
    )
    await db.delete(cv)
    await _flush_rubric_mutation(db)


async def list_criteria(
    db: AsyncSession,
    rubric_version_id: uuid.UUID,
) -> list[CriterionVersion]:
    """List criteria for a rubric version ordered by position."""
    stmt = (
        select(CriterionVersion)
        .where(CriterionVersion.rubric_version_id == rubric_version_id)
        .order_by(CriterionVersion.position)
    )
    result = await db.execute(stmt)
    return list(result.scalars().all())
