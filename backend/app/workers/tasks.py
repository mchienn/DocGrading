from __future__ import annotations

import asyncio
import uuid

import sqlalchemy as sa

from app.core.config import get_settings
from app.db.session import _session_factory
from app.models.enums import DocumentStatus
from app.models.submission import DocumentVersion
from app.services.analysis_job import (
    claim_job_by_id,
    claim_next_job,
    mark_done,
    mark_error,
)
from app.services.pdf_validation import PDFValidationError, validate_pdf
from app.services.storage import S3Storage
from app.workers.celery_app import celery_app


@celery_app.task(name="app.workers.tasks.healthcheck")
def healthcheck() -> dict[str, str]:
    return {"status": "ok"}


async def _run_analysis_job(job_id: str | None = None) -> str | None:
    async with _session_factory()() as db:
        job = (
            await claim_next_job(db)
            if job_id is None
            else await claim_job_by_id(db, uuid.UUID(job_id))
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
            if (
                job.document_version.declared_sha256
                and job.document_version.declared_sha256 != result.sha256
            ):
                job.document_version.status = DocumentStatus.INVALID
                job.document_version.failure_code = "PDF_SHA256_MISMATCH"
                job.document_version.failure_detail = "PDF checksum does not match"
                await mark_error(
                    db,
                    job,
                    "PDF_SHA256_MISMATCH",
                    "PDF checksum does not match",
                )
                await db.commit()
                return str(job.id)
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
            job.document_version.status = DocumentStatus.PROCESSING_FAILED
            job.document_version.failure_code = "PDF_STORAGE_ERROR"
            job.document_version.failure_detail = "Object storage read failed"
            await mark_error(db, job, "PDF_STORAGE_ERROR", "Object storage read failed")
        await db.commit()
        return str(job.id)


@celery_app.task(name="app.workers.tasks.process_analysis_job")
def process_analysis_job(job_id: str | None = None) -> str | None:
    return asyncio.run(_run_analysis_job(job_id))
