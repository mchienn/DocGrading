from __future__ import annotations

import hashlib
import json
import uuid
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

import sqlalchemy as sa
from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased, selectinload

from app.api.deps import check_course_ownership
from app.api.schemas_submission import (
    ApprovalResponse,
    BBox,
    BulkPublishResponse,
    EvidenceResponse,
    EvidenceWorkspaceResponse,
    FindingResponse,
    PublishedResultResponse,
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
    PublishedResultVersion,
    ReviewCommand,
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
        statement = statement.with_for_update(read=True, of=Course)
    row = (await db.execute(statement)).one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="Submission not found")
    submission, course = row
    _authorize_course(user, course)
    if writable and course.status is CourseStatus.ARCHIVED:
        raise HTTPException(status_code=409, detail="Archived courses are read-only")
    if lock:
        submission = (
            await db.execute(
                sa.select(Submission)
                .where(Submission.id == submission_id)
                .with_for_update()
            )
        ).scalar_one()
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
        .join(Submission, Submission.id == DocumentVersion.submission_id)
        .join(Assignment, Assignment.id == Submission.assignment_id)
        .where(Assignment.course_id == course_id)
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


def _lock_holder_error() -> HTTPException:
    return HTTPException(status_code=500, detail="Review lock holder is missing")


def _anchor_index(
    content: Mapping[str, Any],
    required: set[tuple[str, int]],
) -> dict[tuple[str, int], BBox]:
    if not required:
        return {}

    page_numbers = {page_number for _, page_number in required}
    try:
        pages: dict[int, tuple[float, float]] = {}
        for page in content.get("pages", ()):
            if not isinstance(page, Mapping):
                continue
            try:
                page_number = int(page["number"])
            except (KeyError, TypeError, ValueError, OverflowError):
                continue
            if page_number in page_numbers:
                pages[page_number] = (
                    float(page["width"]),
                    float(page["height"]),
                )

        candidates: list[tuple[tuple[str, int], object]] = []
        for collection_name in ("sections", "paragraphs"):
            for element in content.get(collection_name, ()):
                if not isinstance(element, Mapping):
                    continue
                try:
                    key = (str(element["id"]), int(element["page_number"]))
                except (KeyError, TypeError, ValueError, OverflowError):
                    continue
                if key in required:
                    candidates.append((key, element["bbox"]))
        for table in content.get("tables", ()):
            if not isinstance(table, Mapping):
                continue
            try:
                table_id = str(table["id"])
            except (KeyError, TypeError, ValueError):
                continue
            for region in table.get("regions", ()):
                if not isinstance(region, Mapping):
                    continue
                try:
                    key = (table_id, int(region["page_number"]))
                except (KeyError, TypeError, ValueError, OverflowError):
                    continue
                if key in required:
                    candidates.append((key, region["bbox"]))
    except (KeyError, TypeError, ValueError, OverflowError) as exc:
        raise _evidence_error() from exc

    index: dict[tuple[str, int], BBox] = {}
    for key, raw_bbox in candidates:
        dimensions = pages.get(key[1])
        if dimensions is None:
            raise _evidence_error()
        try:
            bbox = BBox.model_validate(raw_bbox)
        except ValidationError as exc:
            raise _evidence_error() from exc
        page_width, page_height = dimensions
        if bbox.x1 > page_width or bbox.bottom > page_height or key in index:
            raise _evidence_error()
        index[key] = bbox
    if index.keys() != required:
        raise _evidence_error()
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
    rows = (await db.execute(statement)).all()
    anchors = _anchor_index(
        document_ir.content,
        {(anchor.element_id, anchor.page_number) for _, anchor in rows},
    )
    grouped: dict[uuid.UUID, FindingResponse] = {}
    for finding, anchor in rows:
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
            raise _lock_holder_error()
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

    now = _now()
    is_force_release = UserRole.ADMIN in user.roles and (
        review_lock.reviewer_user_id != user.id or review_lock.expires_at <= now
    )
    if not is_force_release:
        if review_lock.expires_at <= now:
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


def _command_fingerprint(payload: dict[str, Any]) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


async def _command_start(
    db: AsyncSession,
    *,
    actor_user_id: uuid.UUID,
    action: str,
    idempotency_key: str,
    payload: dict[str, Any],
) -> tuple[dict[str, Any] | None, str]:
    if not idempotency_key or not idempotency_key.strip() or len(idempotency_key) > 128:
        raise HTTPException(status_code=400, detail="Idempotency-Key is required")
    fingerprint = _command_fingerprint(payload)
    lock_key = f"{actor_user_id}:{action}:{idempotency_key}"
    await db.execute(
        sa.text(
            "SELECT pg_catalog.pg_advisory_xact_lock("
            "pg_catalog.hashtextextended(:lock_key, 0))"
        ),
        {"lock_key": lock_key},
    )
    command = (
        await db.execute(
            sa.select(ReviewCommand)
            .where(
                ReviewCommand.actor_user_id == actor_user_id,
                ReviewCommand.action == action,
                ReviewCommand.idempotency_key == idempotency_key,
            )
            .with_for_update()
        )
    ).scalar_one_or_none()
    if command is not None:
        if command.request_fingerprint != fingerprint:
            raise HTTPException(
                status_code=409, detail="Idempotency-Key payload conflict"
            )
        return command.response, fingerprint
    return None, fingerprint


async def _command_finish(
    db: AsyncSession,
    *,
    actor_user_id: uuid.UUID,
    action: str,
    idempotency_key: str,
    fingerprint: str,
    response: dict[str, Any],
) -> None:
    db.add(
        ReviewCommand(
            id=uuid.uuid4(),
            actor_user_id=actor_user_id,
            action=action,
            idempotency_key=idempotency_key,
            request_fingerprint=fingerprint,
            response=response,
        )
    )
    await db.flush()


async def _locked_document_context(
    db: AsyncSession, version_id: uuid.UUID, user: User
) -> tuple[Course, Submission, DocumentVersion]:
    course = (
        await db.execute(
            sa.select(Course)
            .join(Assignment, Assignment.course_id == Course.id)
            .join(Submission, Submission.assignment_id == Assignment.id)
            .join(DocumentVersion, DocumentVersion.submission_id == Submission.id)
            .where(DocumentVersion.id == version_id)
            .with_for_update(read=True, of=Course)
        )
    ).scalar_one_or_none()
    if course is None:
        raise HTTPException(status_code=404, detail="Document version not found")
    _authorize_course(user, course)
    if course.status is CourseStatus.ARCHIVED:
        raise HTTPException(status_code=409, detail="Archived courses are read-only")
    submission = (
        await db.execute(
            sa.select(Submission)
            .join(DocumentVersion, DocumentVersion.submission_id == Submission.id)
            .where(DocumentVersion.id == version_id)
            .with_for_update(of=Submission)
        )
    ).scalar_one()
    version = (
        await db.execute(
            sa.select(DocumentVersion)
            .where(DocumentVersion.id == version_id)
            .with_for_update(of=DocumentVersion)
            .execution_options(populate_existing=True)
        )
    ).scalar_one()
    return course, submission, version


async def _approval_snapshot(
    db: AsyncSession,
    *,
    version: DocumentVersion,
    submission: Submission,
) -> dict[str, Any]:
    draft = (
        await db.execute(
            sa.select(ReviewDraft)
            .where(
                ReviewDraft.submission_id == submission.id,
                ReviewDraft.document_version_id == version.id,
            )
            .order_by(ReviewDraft.updated_at.desc(), ReviewDraft.id.desc())
            .limit(1)
            .with_for_update()
        )
    ).scalar_one_or_none()
    if draft is None:
        raise HTTPException(
            status_code=422,
            detail="Current review draft is required before approval",
        )
    decisions: dict[uuid.UUID, ReviewDecision] = {}
    if draft is not None:
        decisions = {
            decision.finding_id: decision
            for decision in (
                await db.execute(
                    sa.select(ReviewDecision)
                    .where(ReviewDecision.review_draft_id == draft.id)
                    .with_for_update()
                )
            ).scalars()
        }

    findings = list(
        (
            await db.execute(
                sa.select(Finding)
                .join(AnalysisJob, AnalysisJob.id == Finding.analysis_job_id)
                .where(AnalysisJob.document_version_id == version.id)
                .order_by(Finding.id)
            )
        ).scalars()
    )
    missing = [finding.id for finding in findings if finding.id not in decisions]
    if missing:
        raise HTTPException(
            status_code=422,
            detail="Every finding requires a review decision before approval",
        )

    finding_ids = {
        finding.id
        for finding in findings
        if decisions[finding.id].decision is not ReviewDecisionType.REJECT
    }
    all_anchors = list(
        (
            await db.execute(
                sa.select(EvidenceAnchor)
                .where(EvidenceAnchor.finding_id.in_(finding_ids))
                .order_by(
                    EvidenceAnchor.finding_id,
                    EvidenceAnchor.page_number,
                    EvidenceAnchor.element_id,
                )
            )
        ).scalars()
    )
    document_ir = (
        await db.execute(
            sa.select(DocumentIR).where(DocumentIR.document_version_id == version.id)
        )
    ).scalar_one_or_none()
    if all_anchors and document_ir is None:
        raise HTTPException(status_code=409, detail="Document IR is not available")
    anchors = (
        [anchor for anchor in all_anchors if anchor.document_ir_id == document_ir.id]
        if document_ir is not None
        else []
    )
    if len(anchors) != len(all_anchors):
        raise _evidence_error()
    anchor_by_finding: dict[uuid.UUID, list[EvidenceAnchor]] = {}
    for anchor in anchors:
        anchor_by_finding.setdefault(anchor.finding_id, []).append(anchor)
    required = {(anchor.element_id, anchor.page_number) for anchor in anchors}
    geometry = _anchor_index(document_ir.content, required) if document_ir else {}

    output_findings: list[dict[str, Any]] = []
    for finding in findings:
        decision = decisions[finding.id]
        if decision.decision is ReviewDecisionType.REJECT:
            continue
        description = (
            decision.edited_description
            if decision.decision is ReviewDecisionType.EDIT
            and decision.edited_description is not None
            else finding.description
        )
        score = (
            decision.final_score
            if decision.decision is ReviewDecisionType.EDIT
            and decision.final_score is not None
            else finding.proposed_score
        )
        evidence = []
        for anchor in anchor_by_finding.get(finding.id, []):
            bbox = geometry[(anchor.element_id, anchor.page_number)]
            evidence.append(
                {
                    "document_ir_id": str(anchor.document_ir_id),
                    "element_id": anchor.element_id,
                    "page_number": anchor.page_number,
                    "bbox": bbox.model_dump(),
                }
            )
        output_findings.append(
            {
                "criterion_version_id": str(finding.criterion_version_id),
                "finding_id": str(finding.id),
                "score": format(score, "f") if score is not None else None,
                "description": description,
                "suggestion": finding.suggestion,
                "evidence": evidence,
            }
        )
    return {
        "comment": draft.comment if draft is not None else "",
        "findings": output_findings,
    }


def _published_response(
    result: PublishedResultVersion, submission_id: uuid.UUID
) -> dict[str, Any]:
    snapshot = result.snapshot
    return {
        "published_result_id": str(result.id),
        "submission_id": str(submission_id),
        "document_version_id": str(result.document_version_id),
        "version_number": result.version_number,
        "published_at": result.published_at.isoformat(),
        "comment": snapshot.get("comment", ""),
        "findings": snapshot.get("findings", []),
    }


async def approve_document_version(
    db: AsyncSession,
    *,
    version_id: uuid.UUID,
    user: User,
    idempotency_key: str,
) -> ApprovalResponse:
    payload = {"document_version_id": str(version_id)}
    replay, fingerprint = await _command_start(
        db,
        actor_user_id=user.id,
        action="APPROVE",
        idempotency_key=idempotency_key,
        payload=payload,
    )
    if replay is not None:
        return ApprovalResponse.model_validate(replay)
    _, submission, version = await _locked_document_context(db, version_id, user)
    if version.status is not DocumentStatus.AWAITING_REVIEW:
        raise HTTPException(status_code=409, detail="Document is not awaiting review")
    snapshot = await _approval_snapshot(db, version=version, submission=submission)
    now = _now()
    before = {"status": version.status.value}
    version.status = DocumentStatus.APPROVED
    version.approved_at = now
    version.approved_by_user_id = user.id
    version.approved_snapshot = snapshot
    await record_audit(
        db,
        actor_user_id=user.id,
        resource_type="DocumentVersion",
        resource_id=version.id,
        action="APPROVE",
        before=before,
        after={
            "status": version.status.value,
            "approved_at": now.isoformat(),
            "approved_by_user_id": str(user.id),
        },
        reason="Teacher approved review snapshot",
    )
    response = {
        "document_version_id": str(version.id),
        "status": version.status.value,
        "approved_at": now.isoformat(),
    }
    await _command_finish(
        db,
        actor_user_id=user.id,
        action="APPROVE",
        idempotency_key=idempotency_key,
        fingerprint=fingerprint,
        response=response,
    )
    return ApprovalResponse.model_validate(response)


async def _publish_locked(
    db: AsyncSession,
    *,
    version: DocumentVersion,
    submission: Submission,
    user: User,
    reason: str,
) -> PublishedResultVersion:
    if version.status is not DocumentStatus.APPROVED:
        raise HTTPException(status_code=409, detail="Document is not approved")
    if (
        version.approved_snapshot is None
        or version.approved_at is None
        or version.approved_by_user_id is None
    ):
        raise HTTPException(status_code=409, detail="Approved snapshot is missing")
    latest_number = (
        await db.execute(
            sa.select(PublishedResultVersion.version_number)
            .where(PublishedResultVersion.document_version_id == version.id)
            .order_by(PublishedResultVersion.version_number.desc())
            .limit(1)
            .with_for_update()
        )
    ).scalar_one_or_none()
    latest_number = latest_number or 0
    result = PublishedResultVersion(
        id=uuid.uuid4(),
        document_version_id=version.id,
        version_number=int(latest_number) + 1,
        approved_by_user_id=version.approved_by_user_id,
        published_by_user_id=user.id,
        approved_at=version.approved_at,
        published_at=_now(),
        snapshot=version.approved_snapshot,
    )
    db.add(result)
    before = {"status": version.status.value}
    version.status = DocumentStatus.PUBLISHED
    await record_audit(
        db,
        actor_user_id=user.id,
        resource_type="DocumentVersion",
        resource_id=version.id,
        action="PUBLISH",
        before=before,
        after={
            "status": version.status.value,
            "published_result_id": str(result.id),
            "version_number": result.version_number,
            "approved_at": result.approved_at.isoformat(),
            "approved_by_user_id": str(result.approved_by_user_id),
            "published_at": result.published_at.isoformat(),
        },
        reason=reason,
    )
    return result


async def publish_document_version(
    db: AsyncSession,
    *,
    version_id: uuid.UUID,
    user: User,
    idempotency_key: str,
    reason: str,
) -> PublishedResultResponse:
    payload = {"document_version_id": str(version_id), "reason": reason}
    replay, fingerprint = await _command_start(
        db,
        actor_user_id=user.id,
        action="PUBLISH",
        idempotency_key=idempotency_key,
        payload=payload,
    )
    if replay is not None:
        return PublishedResultResponse.model_validate(replay)
    if not reason.strip():
        raise HTTPException(status_code=422, detail="Reason must not be blank")
    _, submission, version = await _locked_document_context(db, version_id, user)
    result = await _publish_locked(
        db, version=version, submission=submission, user=user, reason=reason
    )
    response = _published_response(result, submission.id)
    await _command_finish(
        db,
        actor_user_id=user.id,
        action="PUBLISH",
        idempotency_key=idempotency_key,
        fingerprint=fingerprint,
        response=response,
    )
    return PublishedResultResponse.model_validate(response)


async def bulk_publish_document_versions(
    db: AsyncSession,
    *,
    assignment_id: uuid.UUID,
    version_ids: list[uuid.UUID],
    user: User,
    idempotency_key: str,
    reason: str,
) -> BulkPublishResponse:
    payload = {
        "assignment_id": str(assignment_id),
        "version_ids": [str(value) for value in version_ids],
        "reason": reason,
    }
    replay, fingerprint = await _command_start(
        db,
        actor_user_id=user.id,
        action="BULK_PUBLISH",
        idempotency_key=idempotency_key,
        payload=payload,
    )
    if replay is not None:
        return BulkPublishResponse.model_validate(replay)
    if not reason.strip():
        raise HTTPException(status_code=422, detail="Reason must not be blank")
    assignment = (
        await db.execute(sa.select(Assignment).where(Assignment.id == assignment_id))
    ).scalar_one_or_none()
    if assignment is None:
        raise HTTPException(status_code=404, detail="Assignment not found")
    course = (
        await db.execute(
            sa.select(Course)
            .where(Course.id == assignment.course_id)
            .with_for_update(read=True, of=Course)
        )
    ).scalar_one()
    _authorize_course(user, course)
    if course.status is CourseStatus.ARCHIVED:
        raise HTTPException(status_code=409, detail="Archived courses are read-only")
    submissions = list(
        (
            await db.execute(
                sa.select(Submission)
                .where(Submission.assignment_id == assignment_id)
                .order_by(Submission.id)
                .with_for_update()
            )
        ).scalars()
    )
    submission_by_id = {submission.id: submission for submission in submissions}
    versions = list(
        (
            await db.execute(
                sa.select(DocumentVersion)
                .where(DocumentVersion.id.in_(version_ids))
                .order_by(DocumentVersion.id)
                .with_for_update()
                .execution_options(populate_existing=True)
            )
        ).scalars()
    )
    if len(versions) != len(version_ids):
        raise HTTPException(
            status_code=409, detail="Bulk publish contains invalid version"
        )
    if any(
        version.submission_id not in submission_by_id
        or version.status is not DocumentStatus.APPROVED
        for version in versions
    ):
        raise HTTPException(
            status_code=409, detail="All versions must be approved in assignment"
        )
    results: list[PublishedResultResponse] = []
    for version in versions:
        result = await _publish_locked(
            db,
            version=version,
            submission=submission_by_id[version.submission_id],
            user=user,
            reason=reason,
        )
        results.append(
            PublishedResultResponse.model_validate(
                _published_response(result, version.submission_id)
            )
        )
    response = {"results": [result.model_dump(mode="json") for result in results]}
    await _command_finish(
        db,
        actor_user_id=user.id,
        action="BULK_PUBLISH",
        idempotency_key=idempotency_key,
        fingerprint=fingerprint,
        response=response,
    )
    return BulkPublishResponse.model_validate(response)


async def unpublish_result(
    db: AsyncSession,
    *,
    published_result_id: uuid.UUID,
    user: User,
    idempotency_key: str,
    reason: str,
) -> ApprovalResponse:
    payload = {"published_result_id": str(published_result_id), "reason": reason}
    replay, fingerprint = await _command_start(
        db,
        actor_user_id=user.id,
        action="UNPUBLISH",
        idempotency_key=idempotency_key,
        payload=payload,
    )
    if not reason.strip():
        raise HTTPException(status_code=422, detail="Reason must not be blank")
    if replay is not None:
        return ApprovalResponse.model_validate(replay)
    result = (
        await db.execute(
            sa.select(PublishedResultVersion).where(
                PublishedResultVersion.id == published_result_id
            )
        )
    ).scalar_one_or_none()
    if result is None:
        raise HTTPException(status_code=404, detail="Published result not found")
    _, submission, version = await _locked_document_context(
        db, result.document_version_id, user
    )
    result = (
        await db.execute(
            sa.select(PublishedResultVersion)
            .where(PublishedResultVersion.id == published_result_id)
            .with_for_update()
        )
    ).scalar_one()
    if version.status is not DocumentStatus.PUBLISHED:
        raise HTTPException(status_code=409, detail="Document is not published")
    latest_document_id = await _latest_document_id(db, submission.id)
    if latest_document_id != version.id:
        raise HTTPException(
            status_code=409,
            detail="Only latest document result can be unpublished",
        )
    latest_id = (
        await db.execute(
            sa.select(PublishedResultVersion.id)
            .where(PublishedResultVersion.document_version_id == version.id)
            .order_by(PublishedResultVersion.version_number.desc())
            .limit(1)
        )
    ).scalar_one()
    if latest_id != result.id:
        raise HTTPException(
            status_code=409, detail="Only latest published result can be unpublished"
        )
    before = {
        "status": version.status.value,
        "published_result_id": str(result.id),
        "version_number": result.version_number,
    }
    version.status = DocumentStatus.APPROVED
    await record_audit(
        db,
        actor_user_id=user.id,
        resource_type="DocumentVersion",
        resource_id=version.id,
        action="UNPUBLISH",
        before=before,
        after={
            "status": version.status.value,
            "published_result_id": str(result.id),
            "version_number": result.version_number,
        },
        reason=reason,
    )
    response = {
        "document_version_id": str(version.id),
        "status": version.status.value,
        "approved_at": version.approved_at.isoformat(),
    }
    await _command_finish(
        db,
        actor_user_id=user.id,
        action="UNPUBLISH",
        idempotency_key=idempotency_key,
        fingerprint=fingerprint,
        response=response,
    )
    return ApprovalResponse.model_validate(response)


async def get_student_published_result(
    db: AsyncSession, *, submission_id: uuid.UUID, user: User
) -> PublishedResultResponse:
    if UserRole.STUDENT not in user.roles:
        raise HTTPException(status_code=404, detail="Published result not found")
    latest_document = aliased(DocumentVersion)
    latest_version_number = (
        sa.select(sa.func.max(latest_document.version_number))
        .where(latest_document.submission_id == submission_id)
        .scalar_subquery()
    )
    row = (
        await db.execute(
            sa.select(PublishedResultVersion, Submission.id)
            .join(
                DocumentVersion,
                DocumentVersion.id == PublishedResultVersion.document_version_id,
            )
            .join(Submission, Submission.id == DocumentVersion.submission_id)
            .where(
                Submission.id == submission_id,
                Submission.student_id == user.id,
                DocumentVersion.status == DocumentStatus.PUBLISHED,
                DocumentVersion.version_number == latest_version_number,
            )
            .order_by(
                DocumentVersion.version_number.desc(),
                PublishedResultVersion.version_number.desc(),
            )
            .limit(1)
        )
    ).first()
    if row is None:
        raise HTTPException(status_code=404, detail="Published result not found")
    result, owner_submission_id = row
    return PublishedResultResponse.model_validate(
        _published_response(result, owner_submission_id)
    )
