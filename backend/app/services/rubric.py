"""Rubric service: CRUD, publish validation, and version management."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from decimal import Decimal

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

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


async def update_rubric_version(
    db: AsyncSession,
    rv: RubricVersion,
    *,
    actor_user_id: uuid.UUID,
    name: str | None = None,
    description: str | None = None,
    calculation_method: str | None = None,
) -> RubricVersion:
    """Update mutable fields on a DRAFT rubric version."""
    if rv.status != RubricStatus.DRAFT:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Published rubric is immutable; create a new version to edit",
        )

    before: dict[str, object] = {}
    after: dict[str, object] = {}

    if name is not None and name != rv.name:
        before["name"] = rv.name
        rv.name = name
        after["name"] = name

    if description is not None and description != rv.description:
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
        await db.flush()

    return rv


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


async def publish_rubric_version(
    db: AsyncSession,
    rv: RubricVersion,
    *,
    actor_user_id: uuid.UUID,
) -> RubricVersion:
    """Publish a DRAFT rubric version.

    Validates that the sum of weights of enabled criteria equals 100.
    """
    if rv.status != RubricStatus.DRAFT:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Only DRAFT rubric versions can be published",
        )

    # Load criteria to validate weights
    stmt = select(CriterionVersion).where(
        CriterionVersion.rubric_version_id == rv.id,
        CriterionVersion.is_enabled.is_(True),
    )
    result = await db.execute(stmt)
    criteria = list(result.scalars().all())

    total_weight = sum(c.weight for c in criteria)
    if total_weight != Decimal("100.00"):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=(
                f"Total weight of enabled criteria must be 100.00, "
                f"got {total_weight}"
            ),
        )

    now = datetime.now(UTC)
    before_status = rv.status.value
    rv.status = RubricStatus.PUBLISHED
    rv.published_at = now
    rv.total_weight = total_weight
    rv.revision += 1

    await record_audit(
        db,
        actor_user_id=actor_user_id,
        resource_type="RubricVersion",
        resource_id=rv.id,
        action="PUBLISH",
        before={"status": before_status},
        after={
            "status": RubricStatus.PUBLISHED.value,
            "published_at": now.isoformat(),
            "total_weight": str(total_weight),
        },
        reason="Rubric version published",
    )
    await db.flush()
    return rv


async def create_new_version_from(
    db: AsyncSession,
    source_rv: RubricVersion,
    *,
    actor_user_id: uuid.UUID,
) -> RubricVersion:
    """Create a new DRAFT version by cloning a published rubric version.

    Copies all criteria from the source version.
    """
    if source_rv.status == RubricStatus.DRAFT:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Source rubric is still DRAFT; edit it directly",
        )

    # Find the next version number
    stmt = (
        select(RubricVersion.version_number)
        .where(RubricVersion.rubric_id == source_rv.rubric_id)
        .order_by(RubricVersion.version_number.desc())
        .limit(1)
    )
    result = await db.execute(stmt)
    max_version = result.scalar_one_or_none() or 0
    new_version_number = max_version + 1

    new_rv = RubricVersion(
        id=uuid.uuid4(),
        rubric_id=source_rv.rubric_id,
        version_number=new_version_number,
        name=source_rv.name,
        description=source_rv.description,
        status=RubricStatus.DRAFT,
        calculation_method=source_rv.calculation_method,
        total_weight=Decimal("0.00"),
        owner_user_id=source_rv.owner_user_id,
        created_by_user_id=actor_user_id,
        source_version_id=source_rv.id,
    )
    db.add(new_rv)
    await db.flush()

    # Clone criteria
    stmt = select(CriterionVersion).where(
        CriterionVersion.rubric_version_id == source_rv.id,
    )
    result = await db.execute(stmt)
    source_criteria = list(result.scalars().all())

    for sc in source_criteria:
        new_cv = CriterionVersion(
            id=uuid.uuid4(),
            criterion_id=sc.criterion_id,
            rubric_version_id=new_rv.id,
            code=sc.code,
            title=sc.title,
            description=sc.description,
            scope=sc.scope,
            weight=sc.weight,
            position=sc.position,
            is_enabled=sc.is_enabled,
            evaluation_method=sc.evaluation_method,
            levels=sc.levels,
            evaluator_config=sc.evaluator_config,
            evidence_requirements=sc.evidence_requirements,
        )
        db.add(new_cv)

    await db.flush()

    await record_audit(
        db,
        actor_user_id=actor_user_id,
        resource_type="RubricVersion",
        resource_id=new_rv.id,
        action="CREATE_VERSION",
        before={"source_version_id": str(source_rv.id)},
        after={
            "id": str(new_rv.id),
            "version_number": new_version_number,
            "criteria_count": len(source_criteria),
        },
        reason=f"New version created from v{source_rv.version_number}",
    )
    await db.flush()

    return new_rv


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
    """Add a criterion to a DRAFT rubric version."""
    if rv.status != RubricStatus.DRAFT:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Cannot add criteria to a published rubric; create a new version",
        )

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
    await db.flush()
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
    """Update a criterion on a DRAFT rubric version."""
    if rv.status != RubricStatus.DRAFT:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Cannot edit criteria of a published rubric; create a new version",
        )

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
        await db.flush()

    return cv


async def delete_criterion(
    db: AsyncSession,
    rv: RubricVersion,
    cv: CriterionVersion,
    *,
    actor_user_id: uuid.UUID,
) -> None:
    """Delete a criterion from a DRAFT rubric version."""
    if rv.status != RubricStatus.DRAFT:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Cannot delete criteria of a published rubric; create a new version",
        )

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
    await db.flush()


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
