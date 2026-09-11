from __future__ import annotations

import uuid
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

import sqlalchemy as sa
from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api.deps import check_course_ownership
from app.api.schemas_submission import (
    BBox,
    EvidenceResponse,
    EvidenceWorkspaceResponse,
    FindingResponse,
    QueueStatus,
    ReviewDecisionRequest,
    ReviewDecisionResponse,
    ReviewDraftRequest,
    ReviewDraftResponse,
    ReviewLockResponse,
    SubmissionQueueItem,
    SubmissionQueueResponse,
)
from app.models.analysis import AnalysisJob, DocumentIR
from app.models.assignment import Assignment
from app.models.course import Course
from app.models.enums import (
    CourseStatus,
    DocumentStatus,
    ReviewDecisionType,
    UserRole,
)
from app.models.identity import User
from app.models.review import (
    EvidenceAnchor,
    Finding,
    ReviewDecision,
    ReviewDraft,
    ReviewLock,
)
from app.models.submission import DocumentVersion, Submission
from app.services.audit import record_audit

LOCK_TTL = timedelta(minutes=10)
_REVIEWED_STATUSES = (DocumentStatus.APPROVED, DocumentStatus.PUBLISHED)
_ERROR_STATUSES = (DocumentStatus.INVALID, DocumentStatus.PROCESSING_FAILED)


def _now() -> datetime:
    return datetime.now(UTC)


def _authorize_course(user: User, course: Course) -> None:
    if UserRole.ADMIN in user.roles:
        return
    if UserRole.TEACHER not in user.roles:
        raise HTTPException(status_code=403, detail="Review access denied")
    check_course_ownership(user, course)


async def _submission_for_review(
    db: AsyncSession,
    submission_id: uuid.UUID,
    user: User,
    *,
    lock: bool = False,
    writable: bool = False,
) -> Submission:
    statement = (
        sa.select(Submission, Course)
        .join(Assignment, Assignment.id == Submission.assignment_id)
        .join(Course, Course.id == Assignment.course_id)
        .where(Submission.id == submission_id)
    )
    if lock:
        statement = statement.with_for_update(of=[Course, Submission])
    row = (await db.execute(statement)).one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="Submission not found")
    submission, course = row
    _authorize_course(user, course)
    if writable and course.status is CourseStatus.ARCHIVED:
        raise HTTPException(status_code=409, detail="Archived courses are read-only")
    return submission


def _queue_status(document_status: DocumentStatus | None) -> QueueStatus:
    if document_status in _REVIEWED_STATUSES:
        return QueueStatus.REVIEWED
    if document_status in _ERROR_STATUSES:
        return QueueStatus.ERROR
    return QueueStatus.UNREVIEWED


async def list_submission_queue(
    db: AsyncSession,
    *,
    course_id: uuid.UUID,
    user: User,
    status_filter: QueueStatus | None = None,
    sort: str = "desc",
    page: int = 1,
    page_size: int = 50,
) -> SubmissionQueueResponse:
    course = await db.get(Course, course_id)
    if course is None:
        raise HTTPException(status_code=404, detail="Course not found")
    _authorize_course(user, course)

    latest = (
        sa.select(
            DocumentVersion.submission_id,
            sa.func.max(DocumentVersion.version_number).label("version_number"),
        )
        .group_by(DocumentVersion.submission_id)
        .subquery()
    )
    now = _now()
    submitted_at = sa.func.coalesce(
        DocumentVersion.created_at, Submission.created_at
    ).label("submitted_at")
    statement = (
        sa.select(Submission, DocumentVersion, ReviewLock, User, submitted_at)
        .join(Assignment, Assignment.id == Submission.assignment_id)
        .outerjoin(latest, latest.c.submission_id == Submission.id)
        .outerjoin(
            DocumentVersion,
            sa.and_(
                DocumentVersion.submission_id == Submission.id,
                DocumentVersion.version_number == latest.c.version_number,
            ),
        )
        .outerjoin(
            ReviewLock,
            sa.and_(
                ReviewLock.submission_id == Submission.id,
                ReviewLock.expires_at > now,
            ),
        )
        .outerjoin(User, User.id == ReviewLock.reviewer_user_id)
        .where(Assignment.course_id == course_id)
    )
    if status_filter is QueueStatus.REVIEWED:
        statement = statement.where(DocumentVersion.status.in_(_REVIEWED_STATUSES))
    elif status_filter is QueueStatus.ERROR:
        statement = statement.where(DocumentVersion.status.in_(_ERROR_STATUSES))
    elif status_filter is QueueStatus.UNREVIEWED:
        statement = statement.where(
            sa.or_(
                DocumentVersion.id.is_(None),
                DocumentVersion.status.not_in(_REVIEWED_STATUSES + _ERROR_STATUSES),
            )
        )

    total = int(
        await db.scalar(sa.select(sa.func.count()).select_from(statement.subquery()))
        or 0
    )
    order = submitted_at.asc() if sort == "asc" else submitted_at.desc()
    statement = (
        statement.order_by(order, Submission.id)
        .limit(page_size)
        .offset((page - 1) * page_size)
    )
    items = [
        SubmissionQueueItem(
            submission_id=submission.id,
            document_version_id=document.id if document else None,
            student_id=submission.student_id,
            document_status=document.status.value if document else None,
            queue_status=_queue_status(document.status if document else None),
            submitted_at=row_submitted_at,
            review_lock=(
                {
                    "reviewer_user_id": review_lock.reviewer_user_id,
                    "reviewer_display_name": holder.display_name,
                    "expires_at": review_lock.expires_at,
                }
                if review_lock is not None and holder is not None
                else None
            ),
        )
        for submission, document, review_lock, holder, row_submitted_at in (
            await db.execute(statement)
        ).all()
    ]
    return SubmissionQueueResponse(
        items=items,
        page=page,
        page_size=page_size,
        total=total,
    )


def _evidence_error() -> HTTPException:
    return HTTPException(status_code=500, detail="Persisted evidence anchor is invalid")


def _anchor_index(content: Mapping[str, Any]) -> dict[tuple[str, int], BBox]:
    try:
        pages = {
            int(page["number"]): (float(page["width"]), float(page["height"]))
            for page in content["pages"]
        }
        candidates: list[tuple[str, int, object]] = []
        for collection_name in ("sections", "paragraphs"):
            for element in content[collection_name]:
                candidates.append(
                    (str(element["id"]), int(element["page_number"]), element["bbox"])
                )
        for table in content["tables"]:
            for region in table["regions"]:
                candidates.append(
                    (str(table["id"]), int(region["page_number"]), region["bbox"])
                )
    except (KeyError, TypeError, ValueError, OverflowError) as exc:
        raise _evidence_error() from exc

    index: dict[tuple[str, int], BBox] = {}
    for element_id, page_number, raw_bbox in candidates:
        dimensions = pages.get(page_number)
        if dimensions is None:
            raise _evidence_error()
        try:
            bbox = BBox.model_validate(raw_bbox)
        except ValidationError as exc:
            raise _evidence_error() from exc
        page_width, page_height = dimensions
        if bbox.x1 > page_width or bbox.bottom > page_height:
            raise _evidence_error()
        key = (element_id, page_number)
        if key in index:
            raise _evidence_error()
        index[key] = bbox
    return index


async def get_evidence(
    db: AsyncSession, *, submission_id: uuid.UUID, user: User
) -> EvidenceWorkspaceResponse:
    submission = await _submission_for_review(db, submission_id, user)
    document = (
        await db.execute(
            sa.select(DocumentVersion)
            .where(DocumentVersion.submission_id == submission.id)
            .order_by(DocumentVersion.version_number.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    if document is None:
        raise HTTPException(status_code=404, detail="Document version not found")
    document_ir = (
        await db.execute(
            sa.select(DocumentIR).where(DocumentIR.document_version_id == document.id)
        )
    ).scalar_one_or_none()
    if document_ir is None:
        raise HTTPException(status_code=409, detail="Document IR is not available")

    anchors = _anchor_index(document_ir.content)
    statement = (
        sa.select(Finding, EvidenceAnchor)
        .join(AnalysisJob, AnalysisJob.id == Finding.analysis_job_id)
        .join(EvidenceAnchor, EvidenceAnchor.finding_id == Finding.id)
        .where(
            AnalysisJob.document_version_id == document.id,
            EvidenceAnchor.document_ir_id == document_ir.id,
        )
        .order_by(
            Finding.created_at,
            Finding.id,
            EvidenceAnchor.page_number,
            EvidenceAnchor.element_id,
        )
    )
    grouped: dict[uuid.UUID, FindingResponse] = {}
    for finding, anchor in (await db.execute(statement)).all():
        bbox = anchors.get((anchor.element_id, anchor.page_number))
        if bbox is None:
            raise _evidence_error()
        response = grouped.get(finding.id)
        if response is None:
            response = FindingResponse(
                id=finding.id,
                criterion_version_id=finding.criterion_version_id,
                severity=finding.severity,
                description=finding.description,
                suggestion=finding.suggestion,
                proposed_score=finding.proposed_score,
                evidence=[],
            )
            grouped[finding.id] = response
        response.evidence.append(
            EvidenceResponse(
                document_ir_id=document_ir.id,
                element_id=anchor.element_id,
                page_number=anchor.page_number,
                bbox=bbox,
            )
        )
    return EvidenceWorkspaceResponse(
        submission_id=submission.id,
        document_version_id=document.id,
        findings=list(grouped.values()),
    )


def _lock_response(
    review_lock: ReviewLock,
    holder: User,
    *,
    acquired: bool,
) -> ReviewLockResponse:
    return ReviewLockResponse(
        acquired=acquired,
        submission_id=review_lock.submission_id,
        reviewer_user_id=review_lock.reviewer_user_id,
        reviewer_display_name=holder.display_name,
        expires_at=review_lock.expires_at,
    )


async def _locked_review_lock(
    db: AsyncSession, submission_id: uuid.UUID
) -> ReviewLock | None:
    return (
        await db.execute(
            sa.select(ReviewLock)
            .where(ReviewLock.submission_id == submission_id)
            .with_for_update()
        )
    ).scalar_one_or_none()


async def acquire_review_lock(
    db: AsyncSession, *, submission_id: uuid.UUID, user: User
) -> ReviewLockResponse:
    await _submission_for_review(db, submission_id, user, lock=True, writable=True)
    review_lock = await _locked_review_lock(db, submission_id)
    now = _now()
    if (
        review_lock is not None
        and review_lock.expires_at > now
        and review_lock.reviewer_user_id != user.id
    ):
        holder = await db.get(User, review_lock.reviewer_user_id)
        if holder is None:
            raise _evidence_error()
        return _lock_response(review_lock, holder, acquired=False)

    if review_lock is None:
        review_lock = ReviewLock(
            id=uuid.uuid4(),
            submission_id=submission_id,
            reviewer_user_id=user.id,
            acquired_at=now,
            expires_at=now + LOCK_TTL,
        )
        db.add(review_lock)
    else:
        if review_lock.reviewer_user_id != user.id or review_lock.expires_at <= now:
            review_lock.acquired_at = now
        review_lock.reviewer_user_id = user.id
        review_lock.expires_at = now + LOCK_TTL
    await db.flush()
    return _lock_response(review_lock, user, acquired=True)


async def _require_review_lock(
    db: AsyncSession, submission_id: uuid.UUID, user: User
) -> ReviewLock:
    await _submission_for_review(db, submission_id, user, lock=True, writable=True)
    review_lock = await _locked_review_lock(db, submission_id)
    now = _now()
    if review_lock is None or review_lock.expires_at <= now:
        raise HTTPException(status_code=409, detail="Review lock is not held")
    if review_lock.reviewer_user_id != user.id:
        raise HTTPException(
            status_code=409, detail="Review lock is held by another reviewer"
        )
    return review_lock


async def heartbeat_review_lock(
    db: AsyncSession, *, submission_id: uuid.UUID, user: User
) -> ReviewLockResponse:
    review_lock = await _require_review_lock(db, submission_id, user)
    review_lock.expires_at = _now() + LOCK_TTL
    await db.flush()
    return _lock_response(review_lock, user, acquired=True)


async def release_review_lock(
    db: AsyncSession, *, submission_id: uuid.UUID, user: User
) -> None:
    await _submission_for_review(db, submission_id, user, lock=True)
    review_lock = await _locked_review_lock(db, submission_id)
    if review_lock is None:
        raise HTTPException(status_code=409, detail="Review lock is not held")

    is_admin = UserRole.ADMIN in user.roles
    if not is_admin:
        if review_lock.expires_at <= _now():
            raise HTTPException(status_code=409, detail="Review lock is not held")
        if review_lock.reviewer_user_id != user.id:
            raise HTTPException(
                status_code=409, detail="Review lock is held by another reviewer"
            )
    else:
        await record_audit(
            db,
            actor_user_id=user.id,
            resource_type="ReviewLock",
            resource_id=review_lock.id,
            action="ADMIN_RELEASE",
            before={
                "submission_id": str(review_lock.submission_id),
                "reviewer_user_id": str(review_lock.reviewer_user_id),
                "acquired_at": review_lock.acquired_at.isoformat(),
                "expires_at": review_lock.expires_at.isoformat(),
            },
            after={"released": True},
            reason="Admin released review lock",
        )
    await db.delete(review_lock)
    await db.flush()


async def _review_draft(
    db: AsyncSession,
    submission_id: uuid.UUID,
    user_id: uuid.UUID,
    *,
    lock: bool = False,
) -> ReviewDraft | None:
    statement = (
        sa.select(ReviewDraft)
        .where(
            ReviewDraft.submission_id == submission_id,
            ReviewDraft.reviewer_user_id == user_id,
        )
        .options(selectinload(ReviewDraft.decisions))
    )
    if lock:
        statement = statement.with_for_update()
    return (await db.execute(statement)).scalar_one_or_none()


def _draft_response(
    draft: ReviewDraft | None,
    submission_id: uuid.UUID,
    reviewer_user_id: uuid.UUID,
    document_version_id: uuid.UUID | None,
) -> ReviewDraftResponse:
    is_current = draft is not None and draft.document_version_id == document_version_id
    decisions = sorted(
        draft.decisions if is_current else [],
        key=lambda decision: decision.finding_id,
    )
    return ReviewDraftResponse(
        id=draft.id if draft else None,
        submission_id=submission_id,
        document_version_id=document_version_id,
        reviewer_user_id=reviewer_user_id,
        revision=draft.revision if draft else 1,
        comment=draft.comment if is_current else "",
        decisions=[
            ReviewDecisionResponse(
                finding_id=decision.finding_id,
                decision=decision.decision,
                edited_description=decision.edited_description,
                final_score=decision.final_score,
                reason=decision.reason,
            )
            for decision in decisions
        ],
    )


def _same_payload(draft: ReviewDraft, body: ReviewDraftRequest) -> bool:
    incoming = {
        (
            item.finding_id,
            item.decision,
            item.edited_description,
            item.final_score,
            item.reason,
        )
        for item in body.decisions
    }
    existing = {
        (
            item.finding_id,
            item.decision,
            item.edited_description,
            item.final_score,
            item.reason,
        )
        for item in draft.decisions
    }
    return draft.comment == body.comment and incoming == existing


async def get_review_draft(
    db: AsyncSession, *, submission_id: uuid.UUID, user: User
) -> ReviewDraftResponse:
    await _submission_for_review(db, submission_id, user)
    document_version_id = await _latest_document_id(db, submission_id)
    draft = await _review_draft(db, submission_id, user.id)
    return _draft_response(
        draft,
        submission_id,
        user.id,
        document_version_id,
    )


async def _latest_document_id(
    db: AsyncSession, submission_id: uuid.UUID
) -> uuid.UUID | None:
    return (
        await db.execute(
            sa.select(DocumentVersion.id)
            .where(DocumentVersion.submission_id == submission_id)
            .order_by(DocumentVersion.version_number.desc())
            .limit(1)
        )
    ).scalar_one_or_none()


async def _findings_for_draft(
    db: AsyncSession,
    document_version_id: uuid.UUID | None,
    finding_ids: set[uuid.UUID],
) -> dict[uuid.UUID, tuple[Finding, AnalysisJob]]:
    if not finding_ids:
        return {}
    if document_version_id is None:
        raise HTTPException(status_code=422, detail="Submission has no document")
    rows = (
        await db.execute(
            sa.select(Finding, AnalysisJob)
            .join(AnalysisJob, AnalysisJob.id == Finding.analysis_job_id)
            .where(
                Finding.id.in_(finding_ids),
                AnalysisJob.document_version_id == document_version_id,
            )
        )
    ).all()
    findings = {finding.id: (finding, job) for finding, job in rows}
    if findings.keys() != finding_ids:
        raise HTTPException(
            status_code=422, detail="Decision finding is not in latest document"
        )
    return findings


def _effective_score(
    finding: Finding,
    decision: ReviewDecision | ReviewDecisionRequest | None,
) -> Decimal | None:
    if decision is None or decision.decision is ReviewDecisionType.ACCEPT:
        return finding.proposed_score
    if decision.decision is ReviewDecisionType.REJECT:
        return None
    return (
        decision.final_score
        if decision.final_score is not None
        else finding.proposed_score
    )


def _audit_snapshot(
    decision: ReviewDecision | ReviewDecisionRequest | None,
    score: Decimal | None,
    analysis_job_id: uuid.UUID,
) -> dict[str, str | None]:
    return {
        "decision": decision.decision.value if decision else "PROPOSED",
        "score": (
            format(Decimal(0) if score == 0 else score, ".2f")
            if score is not None
            else None
        ),
        "analysis_job_id": str(analysis_job_id),
    }


async def save_review_draft(
    db: AsyncSession,
    *,
    submission_id: uuid.UUID,
    user: User,
    body: ReviewDraftRequest,
) -> ReviewDraftResponse:
    review_lock = await _require_review_lock(db, submission_id, user)
    document_version_id = await _latest_document_id(db, submission_id)
    if document_version_id is None:
        raise HTTPException(status_code=422, detail="Submission has no document")

    if body.document_version_id != document_version_id:
        raise HTTPException(status_code=409, detail="Document version changed")
    draft = await _review_draft(db, submission_id, user.id, lock=True)
    is_current = draft is not None and draft.document_version_id == document_version_id
    if is_current and draft is not None and _same_payload(draft, body):
        review_lock.expires_at = _now() + LOCK_TTL
        await db.flush()
        return _draft_response(
            draft,
            submission_id,
            user.id,
            document_version_id,
        )
    if draft is None:
        if body.revision != 1:
            raise HTTPException(
                status_code=409, detail="Review draft revision conflict"
            )
    elif body.revision != draft.revision:
        raise HTTPException(status_code=409, detail="Review draft revision conflict")

    stored_decisions = list(draft.decisions if draft else [])
    old_decisions = (
        {decision.finding_id: decision for decision in stored_decisions}
        if is_current
        else {}
    )
    new_decisions = {decision.finding_id: decision for decision in body.decisions}
    finding_ids = old_decisions.keys() | new_decisions.keys()
    findings = await _findings_for_draft(
        db,
        document_version_id,
        set(finding_ids),
    )

    for finding_id in finding_ids:
        finding, job = findings[finding_id]
        before_decision = old_decisions.get(finding_id)
        after_decision = new_decisions.get(finding_id)
        before_score = _effective_score(finding, before_decision)
        after_score = _effective_score(finding, after_decision)
        if before_score == after_score:
            continue
        if after_decision is None:
            raise HTTPException(
                status_code=422,
                detail="Use ACCEPT with a reason to restore a scored proposal",
            )
        if after_decision.reason is None:
            raise HTTPException(status_code=422, detail="Override reason is required")
        await record_audit(
            db,
            actor_user_id=user.id,
            resource_type="Finding",
            resource_id=finding.id,
            action="FINDING_OVERRIDE",
            before=_audit_snapshot(before_decision, before_score, job.id),
            after=_audit_snapshot(after_decision, after_score, job.id),
            reason=after_decision.reason,
        )

    if draft is None:
        draft = ReviewDraft(
            id=uuid.uuid4(),
            submission_id=submission_id,
            document_version_id=document_version_id,
            reviewer_user_id=user.id,
            revision=2,
            comment=body.comment,
        )
        db.add(draft)
        await db.flush()
    else:
        if not is_current:
            for decision in stored_decisions:
                await db.delete(decision)
            draft.document_version_id = document_version_id
        draft.comment = body.comment
        draft.revision += 1

    for finding_id, old_decision in old_decisions.items():
        if finding_id not in new_decisions:
            await db.delete(old_decision)
    for finding_id, request in new_decisions.items():
        decision = old_decisions.get(finding_id)
        if decision is None:
            decision = ReviewDecision(
                id=uuid.uuid4(),
                review_draft_id=draft.id,
                finding_id=finding_id,
                decision=request.decision,
            )
            db.add(decision)
        decision.decision = request.decision
        decision.edited_description = request.edited_description
        decision.final_score = request.final_score
        decision.reason = request.reason

    review_lock.expires_at = _now() + LOCK_TTL
    await db.flush()
    await db.refresh(draft, attribute_names=["decisions"])
    return _draft_response(
        draft,
        submission_id,
        user.id,
        document_version_id,
    )
