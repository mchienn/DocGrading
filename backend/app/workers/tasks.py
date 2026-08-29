from __future__ import annotations

import asyncio
import contextlib
import uuid

import sqlalchemy as sa
from celery import Task

from app.core.config import get_settings
from app.db.session import _session_factory
from app.models.enums import DocumentStatus
from app.models.submission import DocumentVersion
from app.services.analysis_job import (
    active_lease_retry_delay,
    claim_job_by_id,
    claim_next_job,
    mark_done,
    mark_error,
    update_heartbeat,
)
from app.services.pdf_validation import PDFValidationError, validate_pdf
from app.services.storage import S3Storage
from app.workers.celery_app import celery_app


@celery_app.task(name="app.workers.tasks.healthcheck")
def healthcheck() -> dict[str, str]:
    return {"status": "ok"}


class _ActiveLease(Exception):
    def __init__(self, retry_after: int) -> None:
        super().__init__("Analysis job lease is still active")
        self.retry_after = retry_after


async def _heartbeat_loop(
    job_id: uuid.UUID, attempt_count: int, interval_seconds: float
) -> None:
    try:
        while True:
            await asyncio.sleep(interval_seconds)
            async with _session_factory()() as hb_db:
                alive = await update_heartbeat(
                    hb_db, job_id, attempt_count=attempt_count
                )
                await hb_db.commit()
                if not alive:
                    break
    except asyncio.CancelledError:
        pass


async def _run_analysis_job(job_id: str | None = None) -> str | None:
    async with _session_factory()() as db:
        target_job_id = uuid.UUID(job_id) if job_id is not None else None
        job = (
            await claim_next_job(db)
            if target_job_id is None
            else await claim_job_by_id(db, target_job_id)
        )
        if job is None:
            retry_after = (
                await active_lease_retry_delay(db, target_job_id)
                if target_job_id is not None
                else None
            )
            await db.commit()
            if retry_after is not None:
                raise _ActiveLease(retry_after)
            return None
        await db.commit()

        claimed_attempt = job.attempt_count
        heartbeat_interval = get_settings().analysis_job_heartbeat_seconds
        heartbeat_task = asyncio.create_task(
            _heartbeat_loop(job.id, claimed_attempt, heartbeat_interval)
        )
        try:
            try:
                storage = S3Storage()
                data = await asyncio.to_thread(
                    storage.get_bounded,
                    job.document_version.storage_key,
                    get_settings().pdf_max_size_bytes,
                )
                result = await asyncio.to_thread(
                    validate_pdf,
                    data,
                    max_size_bytes=get_settings().pdf_max_size_bytes,
                    max_page_count=get_settings().pdf_max_page_count,
                )
                if (
                    job.document_version.declared_sha256
                    and job.document_version.declared_sha256 != result.sha256
                ):
                    job_outcome = ("sha_mismatch", None)
                else:
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
                        job_outcome = ("duplicate", None)
                    else:
                        job_outcome = ("success", result)
            except PDFValidationError as exc:
                job_outcome = ("validation_error", exc)
            except Exception:
                # Keep provider exceptions (which may include URLs/request metadata)
                # out of logs and persisted student-visible detail.
                job_outcome = ("storage_error", None)
        finally:
            heartbeat_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await heartbeat_task

        if job_outcome[0] == "sha_mismatch":
            job.document_version.status = DocumentStatus.INVALID
            job.document_version.failure_code = "PDF_SHA256_MISMATCH"
            job.document_version.failure_detail = "PDF checksum does not match"
            success = await mark_error(
                db,
                job,
                "PDF_SHA256_MISMATCH",
                "PDF checksum does not match",
                attempt_count=claimed_attempt,
            )
            if not success:
                await db.rollback()
                return None
        elif job_outcome[0] == "duplicate":
            job.document_version.status = DocumentStatus.INVALID
            job.document_version.failure_code = "PDF_DUPLICATE"
            job.document_version.failure_detail = "Duplicate document version"
            success = await mark_error(
                db,
                job,
                "PDF_DUPLICATE",
                "Duplicate document version",
                attempt_count=claimed_attempt,
            )
            if not success:
                await db.rollback()
                return None
        elif job_outcome[0] == "validation_error":
            exc = job_outcome[1]
            job.document_version.status = DocumentStatus.INVALID
            job.document_version.failure_code = exc.code
            job.document_version.failure_detail = exc.detail
            success = await mark_error(
                db,
                job,
                exc.code,
                exc.detail,
                attempt_count=claimed_attempt,
            )
            if not success:
                await db.rollback()
                return None
        elif job_outcome[0] == "storage_error":
            job.document_version.status = DocumentStatus.PROCESSING_FAILED
            job.document_version.failure_code = "PDF_STORAGE_ERROR"
            job.document_version.failure_detail = "Object storage read failed"
            success = await mark_error(
                db,
                job,
                "PDF_STORAGE_ERROR",
                "Object storage read failed",
                attempt_count=claimed_attempt,
            )
            if not success:
                await db.rollback()
                return None
        elif job_outcome[0] == "success":
            result = job_outcome[1]
            job.document_version.sha256 = result.sha256
            job.document_version.size_bytes = result.size_bytes
            job.document_version.page_count = result.page_count
            success = await mark_done(db, job, attempt_count=claimed_attempt)
            if not success:
                await db.rollback()
                return None

        await db.commit()
        return str(job.id)


@celery_app.task(
    bind=True,
    max_retries=None,
    name="app.workers.tasks.process_analysis_job",
)
def process_analysis_job(task: Task, job_id: str | None = None) -> str | None:
    try:
        return asyncio.run(_run_analysis_job(job_id))
    except _ActiveLease as exc:
        raise task.retry(countdown=exc.retry_after) from exc
