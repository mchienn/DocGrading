from __future__ import annotations

import asyncio

import sqlalchemy as sa

from app.core.config import get_settings
from app.db.session import _session_factory
from app.models.enums import DocumentStatus
from app.models.submission import DocumentVersion
from app.services.analysis_job import claim_next_job, mark_done, mark_error
from app.services.audit import record_system_audit
from app.services.pdf_validation import PDFValidationError, validate_pdf
from app.services.storage import S3Storage
from app.workers.celery_app import celery_app


@celery_app.task(name="app.workers.tasks.healthcheck")
def healthcheck() -> dict[str, str]:
    return {"status": "ok"}


async def _run_analysis_job(job_id: str | None = None) -> str | None:
    async with _session_factory()() as db:
        job = (
            await claim_next_job(db) if job_id is None else await _claim_job(db, job_id)
        )
        if job is None:
            await db.rollback()
            return None
        await db.commit()
        try:
            storage = S3Storage()
            data = storage.get_bounded(
                job.document_version.storage_key, get_settings().pdf_max_size_bytes
            )
            result = validate_pdf(
                data,
                max_size_bytes=get_settings().pdf_max_size_bytes,
                max_page_count=get_settings().pdf_max_page_count,
            )
            duplicate = (
                await db.execute(
                    sa.select(DocumentVersion.id).where(
                        DocumentVersion.submission_id
                        == job.document_version.submission_id,
                        DocumentVersion.sha256 == result.sha256,
                        DocumentVersion.id != job.document_version.id,
                    )
                )
            ).scalar_one_or_none()
            if duplicate is not None:
                job.document_version.status = DocumentStatus.INVALID
                job.document_version.failure_code = "PDF_DUPLICATE"
                job.document_version.failure_detail = "Duplicate document version"
                await mark_error(db, job, "PDF_DUPLICATE", "Duplicate document version")
                await db.commit()
                return str(job.id)
            job.document_version.sha256 = result.sha256
            job.document_version.size_bytes = result.size_bytes
            job.document_version.page_count = result.page_count
            await mark_done(db, job)
        except PDFValidationError as exc:
            job.document_version.status = DocumentStatus.INVALID
            job.document_version.failure_code = exc.code
            job.document_version.failure_detail = exc.detail
            await mark_error(db, job, exc.code, exc.detail)
        except Exception:
            # Keep provider exceptions (which may include URLs/request metadata)
            # out of logs and persisted student-visible detail.
            await mark_error(db, job, "PDF_STORAGE_ERROR", "Object storage read failed")
        await db.commit()
        return str(job.id)


async def _claim_job(db, job_id: str):  # noqa: ANN001
    import uuid

    import sqlalchemy as sa
    from sqlalchemy.orm import selectinload

    from app.models.analysis import AnalysisJob
    from app.models.enums import AnalysisJobStatus

    job = (
        await db.execute(
            sa.select(AnalysisJob)
            .where(
                AnalysisJob.id == uuid.UUID(job_id),
                AnalysisJob.status == AnalysisJobStatus.QUEUED,
            )
            .options(selectinload(AnalysisJob.document_version))
            .with_for_update(skip_locked=True)
        )
    ).scalar_one_or_none()
    if job is None:
        return None
    if job.status is not AnalysisJobStatus.QUEUED:
        return None
    # Reuse the common transition/audit implementation after the locked read.
    job.status = AnalysisJobStatus.RUNNING
    before = AnalysisJobStatus.QUEUED.value
    job.attempt_count += 1
    from datetime import UTC, datetime

    job.started_at = datetime.now(UTC)
    await record_system_audit(
        db,
        resource_type="AnalysisJob",
        resource_id=job.id,
        action="RUNNING",
        before={"status": before},
        after={"status": job.status.value, "attempt_count": job.attempt_count},
        reason="Analysis job claimed",
    )
    await db.flush()
    return job


@celery_app.task(name="app.workers.tasks.process_analysis_job")
def process_analysis_job(job_id: str | None = None) -> str | None:
    return asyncio.run(_run_analysis_job(job_id))
