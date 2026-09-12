from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Header, HTTPException, Query, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.api.schemas_submission import (
    AnalysisJobResponse,
    ApprovalResponse,
    BulkPublishRequest,
    BulkPublishResponse,
    CompletionResponse,
    EvidenceWorkspaceResponse,
    PresignRequest,
    PresignResponse,
    PublishedResultResponse,
    PublishRequest,
    QueueSort,
    QueueStatus,
    ReviewDraftRequest,
    ReviewDraftResponse,
    ReviewLockResponse,
    ReviewRequestCreate,
    ReviewRequestListResponse,
    ReviewRequestResponse,
    ReviewRequestUpdate,
    SubmissionQueueResponse,
    SubmissionVersionListResponse,
    UnpublishRequest,
    VersionComparisonResponse,
)
from app.db.session import get_db_session
from app.models.enums import AnalysisJobStatus, ReviewRequestStatus
from app.models.identity import User
from app.services import analysis_job as job_svc
from app.services import appeal as appeal_svc
from app.services import review as review_svc
from app.services import submission as submission_svc
from app.services.analysis_dispatch import dispatch_analysis_job_now

router = APIRouter(tags=["submissions"])


@router.post(
    "/assignments/{assignment_id}/uploads/presign",
    response_model=PresignResponse,
    status_code=status.HTTP_201_CREATED,
)
async def presign_upload(
    assignment_id: uuid.UUID,
    body: PresignRequest,
    idempotency_key: str | None = Header(None, alias="Idempotency-Key"),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> PresignResponse:
    if not idempotency_key or len(idempotency_key) > 128:
        raise HTTPException(status_code=400, detail="Idempotency-Key is required")
    version, response = await submission_svc.initiate_upload(
        db,
        assignment_id=assignment_id,
        user=user,
        idempotency_key=idempotency_key,
        filename=body.filename,
        content_type=body.content_type,
        size_bytes=body.size_bytes,
        sha256=body.sha256,
    )
    await db.commit()
    return PresignResponse.model_validate(response)


@router.post(
    "/document-versions/{version_id}/complete",
    response_model=CompletionResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def complete_upload(
    version_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> CompletionResponse:
    version, job = await submission_svc.complete_upload(
        db, version_id=version_id, user=user
    )
    await db.commit()
    if job.status is AnalysisJobStatus.QUEUED:
        await dispatch_analysis_job_now(job.id)
    return CompletionResponse(
        submission_id=version.submission_id,
        document_version_id=version.id,
        analysis_job_id=job.id,
        status=job.status.value,
    )


@router.get("/analysis-jobs/{job_id}", response_model=AnalysisJobResponse)
async def get_analysis_job(
    job_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> AnalysisJobResponse:
    job = await job_svc.get_job(db, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Analysis job not found")
    await job_svc.authorize_job(db, job, user)
    return AnalysisJobResponse.model_validate(job)


@router.post("/analysis-jobs/{job_id}/retry", response_model=AnalysisJobResponse)
async def retry_analysis_job(
    job_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> AnalysisJobResponse:
    job = await job_svc.get_job(db, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Analysis job not found")
    job = await job_svc.retry_job(db, job, user)
    await db.commit()
    await dispatch_analysis_job_now(job.id)
    return AnalysisJobResponse.model_validate(job)


@router.get(
    "/courses/{course_id}/submission-queue", response_model=SubmissionQueueResponse
)
async def submission_queue(
    course_id: uuid.UUID,
    queue_status: QueueStatus | None = Query(None, alias="status"),
    sort: QueueSort = Query(QueueSort.DESC),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=100),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> SubmissionQueueResponse:
    return await review_svc.list_submission_queue(
        db,
        course_id=course_id,
        user=user,
        status_filter=queue_status,
        sort=sort.value,
        page=page,
        page_size=page_size,
    )


@router.get(
    "/submissions/{submission_id}/evidence", response_model=EvidenceWorkspaceResponse
)
async def submission_evidence(
    submission_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> EvidenceWorkspaceResponse:
    return await review_svc.get_evidence(db, submission_id=submission_id, user=user)


@router.post(
    "/submissions/{submission_id}/review-lock", response_model=ReviewLockResponse
)
async def acquire_submission_review_lock(
    submission_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> ReviewLockResponse:
    response = await review_svc.acquire_review_lock(
        db, submission_id=submission_id, user=user
    )
    await db.commit()
    return response


@router.put(
    "/submissions/{submission_id}/review-lock/heartbeat",
    response_model=ReviewLockResponse,
)
async def heartbeat_submission_review_lock(
    submission_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> ReviewLockResponse:
    response = await review_svc.heartbeat_review_lock(
        db, submission_id=submission_id, user=user
    )
    await db.commit()
    return response


@router.delete(
    "/submissions/{submission_id}/review-lock", status_code=status.HTTP_204_NO_CONTENT
)
async def release_submission_review_lock(
    submission_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> None:
    await review_svc.release_review_lock(db, submission_id=submission_id, user=user)
    await db.commit()


@router.get(
    "/submissions/{submission_id}/review-draft", response_model=ReviewDraftResponse
)
async def get_submission_review_draft(
    submission_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> ReviewDraftResponse:
    return await review_svc.get_review_draft(db, submission_id=submission_id, user=user)


@router.put(
    "/submissions/{submission_id}/review-draft", response_model=ReviewDraftResponse
)
async def put_submission_review_draft(
    submission_id: uuid.UUID,
    body: ReviewDraftRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> ReviewDraftResponse:
    response = await review_svc.save_review_draft(
        db, submission_id=submission_id, user=user, body=body
    )
    await db.commit()
    return response


@router.post(
    "/document-versions/{version_id}/approve",
    response_model=ApprovalResponse,
)
async def approve_document_version(
    version_id: uuid.UUID,
    idempotency_key: str = Header(alias="Idempotency-Key"),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> ApprovalResponse:
    response = await review_svc.approve_document_version(
        db,
        version_id=version_id,
        user=user,
        idempotency_key=idempotency_key,
    )
    await db.commit()
    return response


@router.post(
    "/document-versions/{version_id}/publish",
    response_model=PublishedResultResponse,
)
async def publish_document_version(
    version_id: uuid.UUID,
    body: PublishRequest,
    idempotency_key: str = Header(alias="Idempotency-Key"),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> PublishedResultResponse:
    response = await review_svc.publish_document_version(
        db,
        version_id=version_id,
        user=user,
        idempotency_key=idempotency_key,
        reason=body.reason,
    )
    await db.commit()
    return response


@router.post(
    "/assignments/{assignment_id}/document-versions/bulk-publish",
    response_model=BulkPublishResponse,
)
async def bulk_publish_document_versions(
    assignment_id: uuid.UUID,
    body: BulkPublishRequest,
    idempotency_key: str = Header(alias="Idempotency-Key"),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> BulkPublishResponse:
    response = await review_svc.bulk_publish_document_versions(
        db,
        assignment_id=assignment_id,
        version_ids=body.version_ids,
        user=user,
        idempotency_key=idempotency_key,
        reason=body.reason,
    )
    await db.commit()
    return response


@router.post(
    "/published-results/{published_result_id}/unpublish",
    response_model=ApprovalResponse,
)
async def unpublish_published_result(
    published_result_id: uuid.UUID,
    body: UnpublishRequest,
    idempotency_key: str = Header(alias="Idempotency-Key"),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> ApprovalResponse:
    response = await review_svc.unpublish_result(
        db,
        published_result_id=published_result_id,
        user=user,
        idempotency_key=idempotency_key,
        reason=body.reason,
    )
    await db.commit()
    return response


@router.get(
    "/submissions/{submission_id}/versions",
    response_model=SubmissionVersionListResponse,
)
async def list_submission_versions(
    submission_id: uuid.UUID,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=100),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> SubmissionVersionListResponse:
    return await review_svc.list_submission_versions(
        db,
        submission_id=submission_id,
        user=user,
        page=page,
        page_size=page_size,
    )


@router.get(
    "/submissions/{submission_id}/versions/compare",
    response_model=VersionComparisonResponse,
)
async def compare_submission_versions(
    submission_id: uuid.UUID,
    left_version_id: uuid.UUID = Query(...),
    right_version_id: uuid.UUID = Query(...),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> VersionComparisonResponse:
    return await review_svc.compare_submission_versions(
        db,
        submission_id=submission_id,
        left_version_id=left_version_id,
        right_version_id=right_version_id,
        user=user,
    )


@router.get(
    "/submissions/{submission_id}/published-result",
    response_model=PublishedResultResponse,
)
async def get_submission_published_result(
    submission_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> PublishedResultResponse:
    return await review_svc.get_student_published_result(
        db, submission_id=submission_id, user=user
    )


@router.post(
    "/published-results/{published_result_id}/review-requests",
    response_model=ReviewRequestResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_review_request(
    published_result_id: uuid.UUID,
    payload: ReviewRequestCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> ReviewRequestResponse:
    try:
        response = await appeal_svc.create_review_request(
            db,
            published_result_id=published_result_id,
            payload=payload,
            user=user,
        )
    except IntegrityError as exc:
        original = exc.orig
        cause = getattr(original, "__cause__", None)
        constraint_name = (
            getattr(getattr(original, "diag", None), "constraint_name", None)
            or getattr(original, "constraint_name", None)
            or getattr(cause, "constraint_name", None)
        )
        if constraint_name != "uq_review_requests_open_target":
            raise
        await db.rollback()
        raise HTTPException(
            status_code=409, detail="Open review request already exists"
        ) from exc
    await db.commit()
    return response


@router.get(
    "/courses/{course_id}/review-requests",
    response_model=ReviewRequestListResponse,
)
async def list_review_requests(
    course_id: uuid.UUID,
    status_filter: ReviewRequestStatus | None = Query(default=None, alias="status"),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=100),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> ReviewRequestListResponse:
    return await appeal_svc.list_review_requests(
        db,
        course_id=course_id,
        user=user,
        status_filter=status_filter,
        page=page,
        page_size=page_size,
    )


@router.get(
    "/review-requests/{review_request_id}",
    response_model=ReviewRequestResponse,
)
async def get_review_request(
    review_request_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> ReviewRequestResponse:
    return await appeal_svc.get_review_request(
        db, request_id=review_request_id, user=user
    )


@router.patch(
    "/review-requests/{review_request_id}",
    response_model=ReviewRequestResponse,
)
async def respond_review_request(
    review_request_id: uuid.UUID,
    payload: ReviewRequestUpdate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> ReviewRequestResponse:
    response = await appeal_svc.respond_review_request(
        db,
        request_id=review_request_id,
        payload=payload,
        user=user,
    )
    await db.commit()
    return response
