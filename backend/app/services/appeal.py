from __future__ import annotations

import uuid
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from typing import Any

import sqlalchemy as sa
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api.schemas_submission import (
    ReviewRequestCreate,
    ReviewRequestListResponse,
    ReviewRequestResponse,
    ReviewRequestUpdate,
)
from app.models.analysis import AnalysisJob
from app.models.assignment import Assignment
from app.models.course import Course
from app.models.enums import (
    AssignmentStatus,
    CourseStatus,
    DocumentStatus,
    ReviewRequestStatus,
    UserRole,
)
from app.models.identity import User
from app.models.review import Finding, PublishedResultVersion, ReviewRequest
from app.models.rubric import CriterionVersion
from app.models.submission import DocumentVersion, Submission
from app.services.audit import record_audit

_WINDOW = timedelta(days=7)


def _now() -> datetime:
    return datetime.now(UTC)


def _response(request: ReviewRequest) -> ReviewRequestResponse:
    return ReviewRequestResponse(
        id=request.id,
        published_result_id=request.published_result_id,
        submission_id=request.submission_id,
        student_id=request.student_id,
        criterion_id=(
            request.criterion_version.criterion_id
            if request.finding_id is None
            else None
        ),
        finding_id=request.finding_id,
        status=request.status,
        reason=request.reason,
        response=request.response,
        responded_by_user_id=request.responded_by_user_id,
        responded_at=request.responded_at,
        created_at=request.created_at,
        updated_at=request.updated_at,
    )


def _state_snapshot(
    request: ReviewRequest, *, status: object | None = None
) -> dict[str, Any]:
    current = request.status.value if status is None else status
    return {
        "status": current,
        "response": request.response,
        "responded_by_user_id": (
            str(request.responded_by_user_id)
            if request.responded_by_user_id is not None
            else None
        ),
        "responded_at": (
            request.responded_at.isoformat()
            if request.responded_at is not None
            else None
        ),
    }


def _require_pure_student(user: User) -> None:
    if set(user.roles) != {UserRole.STUDENT}:
        raise HTTPException(
            status_code=403, detail="Only students may open review requests"
        )


def _authorize_course_actor(user: User, course: Course) -> None:
    if UserRole.ADMIN in user.roles:
        return
    if UserRole.TEACHER in user.roles:
        if course.owner_teacher_id != user.id:
            raise HTTPException(status_code=404, detail="Course not found")
        return
    raise HTTPException(status_code=403, detail="Review request access denied")


async def _load_request_context(
    db: AsyncSession,
    published_result_id: uuid.UUID,
    submission_id: uuid.UUID,
    student_id: uuid.UUID,
) -> tuple[PublishedResultVersion, DocumentVersion, Submission, Assignment, Course]:
    row = (
        await db.execute(
            sa.select(
                PublishedResultVersion,
                DocumentVersion,
                Submission,
                Assignment,
                Course,
            )
            .join(
                DocumentVersion,
                DocumentVersion.id == PublishedResultVersion.document_version_id,
            )
            .join(Submission, Submission.id == DocumentVersion.submission_id)
            .join(Assignment, Assignment.id == Submission.assignment_id)
            .join(Course, Course.id == Assignment.course_id)
            .where(
                PublishedResultVersion.id == published_result_id,
                Submission.id == submission_id,
                Submission.student_id == student_id,
            )
        )
    ).one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="Published result not found")
    result, version, submission, assignment, course = row

    course = (
        await db.execute(
            sa.select(Course)
            .where(Course.id == course.id)
            .with_for_update(read=True)
            .execution_options(populate_existing=True)
        )
    ).scalar_one()
    assignment = (
        await db.execute(
            sa.select(Assignment)
            .where(
                Assignment.id == assignment.id,
                Assignment.course_id == course.id,
            )
            .with_for_update(read=True)
            .execution_options(populate_existing=True)
        )
    ).scalar_one()
    submission = (
        await db.execute(
            sa.select(Submission)
            .where(
                Submission.id == submission_id,
                Submission.assignment_id == assignment.id,
                Submission.student_id == student_id,
            )
            .with_for_update()
            .execution_options(populate_existing=True)
        )
    ).scalar_one()
    version = (
        await db.execute(
            sa.select(DocumentVersion)
            .where(
                DocumentVersion.id == version.id,
                DocumentVersion.submission_id == submission.id,
            )
            .with_for_update()
            .execution_options(populate_existing=True)
        )
    ).scalar_one()
    result = (
        await db.execute(
            sa.select(PublishedResultVersion)
            .where(
                PublishedResultVersion.id == published_result_id,
                PublishedResultVersion.document_version_id == version.id,
            )
            .with_for_update()
            .execution_options(populate_existing=True)
        )
    ).scalar_one()
    return result, version, submission, assignment, course


async def create_review_request(
    db: AsyncSession,
    *,
    published_result_id: uuid.UUID,
    payload: ReviewRequestCreate,
    user: User,
) -> ReviewRequestResponse:
    _require_pure_student(user)
    result, version, submission, assignment, course = await _load_request_context(
        db,
        published_result_id,
        payload.submission_id,
        user.id,
    )
    if version.status is not DocumentStatus.PUBLISHED:
        raise HTTPException(status_code=409, detail="Document is not published")
    if course.status is CourseStatus.ARCHIVED:
        raise HTTPException(status_code=409, detail="Archived courses are read-only")
    if assignment.status is AssignmentStatus.ARCHIVED:
        raise HTTPException(
            status_code=409, detail="Archived assignments are read-only"
        )
    latest_document_id = (
        await db.execute(
            sa.select(DocumentVersion.id)
            .where(DocumentVersion.submission_id == submission.id)
            .order_by(DocumentVersion.version_number.desc())
            .limit(1)
        )
    ).scalar_one()
    if latest_document_id != version.id:
        raise HTTPException(
            status_code=409, detail="Only latest document result may be reviewed"
        )
    latest_result_id = (
        await db.execute(
            sa.select(PublishedResultVersion.id)
            .where(PublishedResultVersion.document_version_id == version.id)
            .order_by(PublishedResultVersion.version_number.desc())
            .limit(1)
        )
    ).scalar_one()
    if latest_result_id != result.id:
        raise HTTPException(
            status_code=409, detail="Only latest published result may be reviewed"
        )
    now = _now()
    if result.published_at < now - _WINDOW or result.published_at > now:
        raise HTTPException(status_code=409, detail="Review request window has expired")

    criterion_version: CriterionVersion | None = None
    finding_id: uuid.UUID | None = None
    if payload.criterion_id is not None:
        criterion_version = (
            await db.execute(
                sa.select(CriterionVersion).where(
                    CriterionVersion.rubric_version_id == assignment.rubric_version_id,
                    CriterionVersion.criterion_id == payload.criterion_id,
                )
            )
        ).scalar_one_or_none()
        if criterion_version is None:
            raise HTTPException(
                status_code=409, detail="Criterion is not in assignment rubric"
            )
    else:
        finding_id = payload.finding_id
        criterion_version_id: uuid.UUID | None = None
        findings = result.snapshot.get("findings", [])
        if isinstance(findings, list):
            for raw in findings:
                if not isinstance(raw, Mapping):
                    continue
                try:
                    candidate = uuid.UUID(str(raw["finding_id"]))
                    candidate_criterion = uuid.UUID(str(raw["criterion_version_id"]))
                except (KeyError, TypeError, ValueError):
                    continue
                if candidate == finding_id:
                    criterion_version_id = candidate_criterion
                    break
        if criterion_version_id is None:
            raise HTTPException(
                status_code=409, detail="Finding is not in published result"
            )
        criterion_version = (
            await db.execute(
                sa.select(CriterionVersion).where(
                    CriterionVersion.id == criterion_version_id,
                    CriterionVersion.rubric_version_id == assignment.rubric_version_id,
                )
            )
        ).scalar_one_or_none()
        if criterion_version is None:
            raise HTTPException(status_code=409, detail="Finding criterion not found")
        finding_exists = (
            await db.execute(
                sa.select(Finding.id)
                .join(AnalysisJob, AnalysisJob.id == Finding.analysis_job_id)
                .where(
                    Finding.id == finding_id,
                    Finding.criterion_version_id == criterion_version.id,
                    AnalysisJob.document_version_id == version.id,
                )
            )
        ).scalar_one_or_none()
        if finding_exists is None:
            raise HTTPException(
                status_code=409, detail="Finding does not belong to document"
            )

    duplicate = (
        await db.execute(
            sa.select(ReviewRequest.id).where(
                ReviewRequest.published_result_id == result.id,
                ReviewRequest.student_id == user.id,
                ReviewRequest.criterion_version_id == criterion_version.id,
                ReviewRequest.status == ReviewRequestStatus.OPEN,
            )
        )
    ).scalar_one_or_none()
    if duplicate is not None:
        raise HTTPException(
            status_code=409, detail="Open review request already exists"
        )

    request = ReviewRequest(
        id=uuid.uuid4(),
        published_result_id=result.id,
        submission_id=submission.id,
        student_id=user.id,
        criterion_version_id=criterion_version.id,
        criterion_version=criterion_version,
        finding_id=finding_id,
        status=ReviewRequestStatus.OPEN,
        reason=payload.reason,
    )
    db.add(request)
    await db.flush()
    await record_audit(
        db,
        actor_user_id=user.id,
        resource_type="ReviewRequest",
        resource_id=request.id,
        action="OPEN",
        before={"status": None},
        after=_state_snapshot(request),
        reason=request.reason,
    )
    return _response(request)


async def _get_request_with_course(
    db: AsyncSession,
    request_id: uuid.UUID,
    *,
    owner_teacher_id: uuid.UUID | None = None,
    lock_course: bool = False,
) -> tuple[ReviewRequest, Assignment, Course]:
    statement = (
        sa.select(ReviewRequest, Assignment, Course)
        .options(selectinload(ReviewRequest.criterion_version))
        .join(Submission, Submission.id == ReviewRequest.submission_id)
        .join(Assignment, Assignment.id == Submission.assignment_id)
        .join(Course, Course.id == Assignment.course_id)
        .where(ReviewRequest.id == request_id)
    )
    if owner_teacher_id is not None:
        statement = statement.where(Course.owner_teacher_id == owner_teacher_id)
    if lock_course:
        statement = statement.with_for_update(read=True, of=Course)
    row = (await db.execute(statement)).one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="Review request not found")
    return row


async def _locked_request(db: AsyncSession, request_id: uuid.UUID) -> ReviewRequest:
    request = (
        await db.execute(
            sa.select(ReviewRequest)
            .options(selectinload(ReviewRequest.criterion_version))
            .where(ReviewRequest.id == request_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
    ).scalar_one_or_none()
    if request is None:
        raise HTTPException(status_code=404, detail="Review request not found")
    return request


def _authorize_read(user: User, request: ReviewRequest, course: Course) -> None:
    if UserRole.ADMIN in user.roles:
        return
    if UserRole.TEACHER in user.roles:
        if course.owner_teacher_id != user.id:
            raise HTTPException(status_code=404, detail="Review request not found")
        return
    if UserRole.STUDENT in user.roles and request.student_id == user.id:
        return
    raise HTTPException(status_code=404, detail="Review request not found")


async def get_review_request(
    db: AsyncSession, *, request_id: uuid.UUID, user: User
) -> ReviewRequestResponse:
    request, _, course = await _get_request_with_course(db, request_id)
    _authorize_read(user, request, course)
    return _response(request)


async def list_review_requests(
    db: AsyncSession,
    *,
    course_id: uuid.UUID,
    user: User,
    status_filter: ReviewRequestStatus | None,
    page: int,
    page_size: int,
) -> ReviewRequestListResponse:
    course = await db.get(Course, course_id)
    if course is None:
        raise HTTPException(status_code=404, detail="Course not found")
    _authorize_course_actor(user, course)
    base = (
        sa.select(ReviewRequest)
        .options(selectinload(ReviewRequest.criterion_version))
        .join(Submission, Submission.id == ReviewRequest.submission_id)
        .join(Assignment, Assignment.id == Submission.assignment_id)
        .where(Assignment.course_id == course_id)
    )
    count_query = (
        sa.select(sa.func.count())
        .select_from(ReviewRequest)
        .join(Submission, Submission.id == ReviewRequest.submission_id)
        .join(Assignment, Assignment.id == Submission.assignment_id)
        .where(Assignment.course_id == course_id)
    )
    if status_filter is not None:
        base = base.where(ReviewRequest.status == status_filter)
        count_query = count_query.where(ReviewRequest.status == status_filter)
    total = (await db.execute(count_query)).scalar_one()
    requests = list(
        (
            await db.execute(
                base.order_by(ReviewRequest.created_at.desc(), ReviewRequest.id)
                .offset((page - 1) * page_size)
                .limit(page_size)
            )
        ).scalars()
    )
    return ReviewRequestListResponse(
        items=[_response(request) for request in requests],
        page=page,
        page_size=page_size,
        total=total,
    )


async def respond_review_request(
    db: AsyncSession,
    *,
    request_id: uuid.UUID,
    payload: ReviewRequestUpdate,
    user: User,
) -> ReviewRequestResponse:
    if UserRole.ADMIN in user.roles:
        owner_teacher_id = None
    elif UserRole.TEACHER in user.roles:
        owner_teacher_id = user.id
    else:
        raise HTTPException(status_code=403, detail="Review request access denied")
    request, assignment, course = await _get_request_with_course(
        db,
        request_id,
        owner_teacher_id=owner_teacher_id,
        lock_course=True,
    )
    if course.status is CourseStatus.ARCHIVED:
        raise HTTPException(status_code=409, detail="Archived courses are read-only")
    assignment = (
        await db.execute(
            sa.select(Assignment)
            .where(
                Assignment.id == assignment.id,
                Assignment.course_id == course.id,
            )
            .with_for_update(read=True)
            .execution_options(populate_existing=True)
        )
    ).scalar_one()
    if assignment.status is AssignmentStatus.ARCHIVED:
        raise HTTPException(
            status_code=409, detail="Archived assignments are read-only"
        )
    request = await _locked_request(db, request_id)
    if payload.status not in (
        ReviewRequestStatus.RESOLVED,
        ReviewRequestStatus.REJECTED,
    ):
        raise HTTPException(
            status_code=422, detail="Response status must be RESOLVED or REJECTED"
        )
    if request.status is not ReviewRequestStatus.OPEN:
        raise HTTPException(
            status_code=409, detail="Review request is already terminal"
        )
    before = _state_snapshot(request)
    request.status = payload.status
    request.response = payload.response
    request.responded_by_user_id = user.id
    request.responded_at = _now()
    await db.flush()
    await db.refresh(request, attribute_names=["updated_at"])
    await record_audit(
        db,
        actor_user_id=user.id,
        resource_type="ReviewRequest",
        resource_id=request.id,
        action=(
            "RESOLVE" if payload.status is ReviewRequestStatus.RESOLVED else "REJECT"
        ),
        before=before,
        after=_state_snapshot(request),
        reason=payload.response,
    )
    return _response(request)
