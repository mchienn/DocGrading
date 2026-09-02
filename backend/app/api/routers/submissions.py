from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Header, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.api.schemas_submission import (
    AnalysisJobResponse,
    CompletionResponse,
    PresignRequest,
    PresignResponse,
)
from app.db.session import get_db_session
from app.models.enums import AnalysisJobStatus
from app.models.identity import User
from app.services import analysis_job as job_svc
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
