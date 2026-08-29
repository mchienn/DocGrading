"""Durable, audited AnalysisJob lifecycle and authorization."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import sqlalchemy as sa
from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.config import get_settings
from app.models.analysis import AnalysisJob
from app.models.assignment import Assignment
from app.models.course import Course
from app.models.enums import AnalysisJobStatus, DocumentStatus, UserRole
from app.models.identity import User
from app.models.submission import DocumentVersion, Submission
from app.services.audit import record_audit, record_system_audit


async def get_job(db: AsyncSession, job_id: uuid.UUID) -> AnalysisJob | None:
    return await db.get(AnalysisJob, job_id)


async def authorize_job(
    db: AsyncSession, job: AnalysisJob, user: User, *, retry: bool = False
) -> None:
    """Authorize by strongest role branch; unauthorized jobs look absent."""
    if UserRole.ADMIN in user.roles:
        return
    query = (
        sa.select(Submission.student_id, Assignment.course_id, Course.owner_teacher_id)
        .join(DocumentVersion, DocumentVersion.submission_id == Submission.id)
        .join(Assignment, Assignment.id == Submission.assignment_id)
        .join(Course, Course.id == Assignment.course_id)
        .where(DocumentVersion.id == job.document_version_id)
    )
    row = (await db.execute(query)).one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="Analysis job not found")
    student_id, _course_id, owner_id = row
    if UserRole.TEACHER in user.roles:
        if owner_id != user.id:
            raise HTTPException(status_code=404, detail="Analysis job not found")
        return
    if UserRole.STUDENT in user.roles and student_id == user.id and not retry:
        return
    raise HTTPException(status_code=404, detail="Analysis job not found")


async def create_or_get_job(
    db: AsyncSession,
    *,
    document_version_id: uuid.UUID,
    rubric_version_id: uuid.UUID,
) -> AnalysisJob:
    stmt = (
        sa.select(AnalysisJob)
        .where(
            AnalysisJob.document_version_id == document_version_id,
            AnalysisJob.rubric_version_id == rubric_version_id,
        )
        .with_for_update()
    )
    job = (await db.execute(stmt)).scalar_one_or_none()
    if job is not None:
        return job
    job = AnalysisJob(
        id=uuid.uuid4(),
        document_version_id=document_version_id,
        rubric_version_id=rubric_version_id,
        status=AnalysisJobStatus.QUEUED,
        snapshot={"pipeline": "pdf-ingestion", "version": 1},
    )
    db.add(job)
    await db.flush()
    await record_system_audit(
        db,
        resource_type="AnalysisJob",
        resource_id=job.id,
        action="QUEUED",
        after={"status": AnalysisJobStatus.QUEUED.value},
        reason="Analysis job created",
    )
    return job


async def update_heartbeat(
    db: AsyncSession, job_id: uuid.UUID, *, attempt_count: int
) -> bool:
    """Periodically touch heartbeat_at for an active RUNNING job matching attempt."""
    stmt = (
        sa.update(AnalysisJob)
        .where(
            AnalysisJob.id == job_id,
            AnalysisJob.status == AnalysisJobStatus.RUNNING,
            AnalysisJob.attempt_count == attempt_count,
        )
        .values(heartbeat_at=datetime.now(UTC))
    )
    result = await db.execute(stmt)
    return getattr(result, "rowcount", 0) > 0


def _get_lease_seconds() -> int:
    return get_settings().analysis_job_lease_seconds


async def _mark_running(db: AsyncSession, job: AnalysisJob) -> None:
    now = datetime.now(UTC)
    before = job.status.value
    job.status = AnalysisJobStatus.RUNNING
    job.attempt_count += 1
    job.started_at = now
    job.heartbeat_at = now
    job.finished_at = None
    await record_system_audit(
        db,
        resource_type="AnalysisJob",
        resource_id=job.id,
        action="RUNNING",
        before={"status": before},
        after={"status": job.status.value, "attempt_count": job.attempt_count},
        reason="Analysis job claimed",
    )
    doc = job.document_version
    if doc is None:
        doc = await db.get(DocumentVersion, job.document_version_id)
    if doc is not None:
        doc_before = doc.status.value
        doc.status = DocumentStatus.PROCESSING
        doc.failure_code = None
        doc.failure_detail = None
        await record_system_audit(
            db,
            resource_type="DocumentVersion",
            resource_id=doc.id,
            action="PROCESSING",
            before={"status": doc_before},
            after={"status": doc.status.value},
            reason="Document processing started",
        )
    await db.flush()


async def _handle_locked_job(
    db: AsyncSession, job: AnalysisJob, cutoff: datetime
) -> AnalysisJob | None:
    if job.status is AnalysisJobStatus.QUEUED:
        await _mark_running(db, job)
        return job
    if job.status is AnalysisJobStatus.RUNNING:
        last_touch = job.heartbeat_at or job.started_at or job.queued_at
        if last_touch is not None and last_touch > cutoff:
            return None
        if job.attempt_count < job.max_attempts:
            before = job.status.value
            job.status = AnalysisJobStatus.QUEUED
            job.queued_at = datetime.now(UTC)
            await record_system_audit(
                db,
                resource_type="AnalysisJob",
                resource_id=job.id,
                action="QUEUED",
                before={"status": before},
                after={"status": job.status.value},
                reason="Analysis job lease expired, requeued",
            )
            await _mark_running(db, job)
            return job
        now = datetime.now(UTC)
        before = job.status.value
        job.status = AnalysisJobStatus.ERROR
        job.error_code = "LEASE_EXPIRED"
        job.error_detail = "Job lease expired and retry limit reached"
        job.finished_at = now
        await record_system_audit(
            db,
            resource_type="AnalysisJob",
            resource_id=job.id,
            action="ERROR",
            before={"status": before},
            after={"status": job.status.value, "error_code": "LEASE_EXPIRED"},
            reason="Analysis job lease expired and attempts exhausted",
        )
        doc = job.document_version
        if doc is None:
            doc = await db.get(DocumentVersion, job.document_version_id)
        if doc is not None:
            doc_before = doc.status.value
            doc.status = DocumentStatus.PROCESSING_FAILED
            doc.failure_code = "LEASE_EXPIRED"
            doc.failure_detail = "Job lease expired and retry limit reached"
            await record_system_audit(
                db,
                resource_type="DocumentVersion",
                resource_id=doc.id,
                action="PROCESSING_FAILED",
                before={"status": doc_before},
                after={
                    "status": doc.status.value,
                    "failure_code": "LEASE_EXPIRED",
                },
                reason="Analysis job lease expired and attempts exhausted",
            )
        await db.flush()
        return None
    return None


async def claim_next_job(db: AsyncSession) -> AnalysisJob | None:
    lease_seconds = _get_lease_seconds()
    cutoff = datetime.now(UTC) - timedelta(seconds=lease_seconds)
    is_queued = AnalysisJob.status == AnalysisJobStatus.QUEUED
    is_stale_running = (AnalysisJob.status == AnalysisJobStatus.RUNNING) & (
        sa.func.coalesce(
            AnalysisJob.heartbeat_at,
            AnalysisJob.started_at,
            AnalysisJob.queued_at,
        )
        <= cutoff
    )
    stmt = (
        sa.select(AnalysisJob)
        .where(sa.or_(is_queued, is_stale_running))
        .order_by(AnalysisJob.queued_at, AnalysisJob.id)
        .options(selectinload(AnalysisJob.document_version))
        .with_for_update(skip_locked=True)
        .limit(1)
    )
    job = (await db.execute(stmt)).scalar_one_or_none()
    if job is None:
        return None
    return await _handle_locked_job(db, job, cutoff)


async def claim_job_by_id(db: AsyncSession, job_id: uuid.UUID) -> AnalysisJob | None:
    """Claim a specific queued or stale job after a SKIP LOCKED check."""
    lease_seconds = _get_lease_seconds()
    cutoff = datetime.now(UTC) - timedelta(seconds=lease_seconds)
    is_queued = AnalysisJob.status == AnalysisJobStatus.QUEUED
    is_stale_running = (AnalysisJob.status == AnalysisJobStatus.RUNNING) & (
        sa.func.coalesce(
            AnalysisJob.heartbeat_at,
            AnalysisJob.started_at,
            AnalysisJob.queued_at,
        )
        <= cutoff
    )
    stmt = (
        sa.select(AnalysisJob)
        .where(
            AnalysisJob.id == job_id,
            sa.or_(is_queued, is_stale_running),
        )
        .options(selectinload(AnalysisJob.document_version))
        .with_for_update(skip_locked=True)
    )
    job = (await db.execute(stmt)).scalar_one_or_none()
    if job is None:
        return None
    return await _handle_locked_job(db, job, cutoff)


async def mark_done(db: AsyncSession, job: AnalysisJob, *, attempt_count: int) -> bool:
    now = datetime.now(UTC)
    stmt = (
        sa.update(AnalysisJob)
        .where(
            AnalysisJob.id == job.id,
            AnalysisJob.status == AnalysisJobStatus.RUNNING,
            AnalysisJob.attempt_count == attempt_count,
        )
        .values(
            status=AnalysisJobStatus.DONE,
            finished_at=now,
        )
    )
    result = await db.execute(stmt)
    if getattr(result, "rowcount", 0) == 0:
        return False

    job.status = AnalysisJobStatus.DONE
    job.finished_at = now
    await record_system_audit(
        db,
        resource_type="AnalysisJob",
        resource_id=job.id,
        action="DONE",
        before={"status": AnalysisJobStatus.RUNNING.value},
        after={"status": job.status.value},
        reason="PDF ingestion completed",
    )
    doc = job.document_version
    if doc is None:
        doc = await db.get(DocumentVersion, job.document_version_id)
    if doc is not None:
        doc_before = doc.status.value
        doc.status = DocumentStatus.AWAITING_REVIEW
        doc.failure_code = None
        doc.failure_detail = None
        await record_system_audit(
            db,
            resource_type="DocumentVersion",
            resource_id=doc.id,
            action="AWAITING_REVIEW",
            before={"status": doc_before},
            after={"status": doc.status.value},
            reason="Document processing completed",
        )
    await db.flush()
    return True


async def mark_error(
    db: AsyncSession,
    job: AnalysisJob,
    code: str,
    detail: str,
    *,
    attempt_count: int,
) -> bool:
    now = datetime.now(UTC)
    stmt = (
        sa.update(AnalysisJob)
        .where(
            AnalysisJob.id == job.id,
            AnalysisJob.status == AnalysisJobStatus.RUNNING,
            AnalysisJob.attempt_count == attempt_count,
        )
        .values(
            status=AnalysisJobStatus.ERROR,
            error_code=code,
            error_detail=detail[:1000],
            finished_at=now,
        )
    )
    result = await db.execute(stmt)
    if getattr(result, "rowcount", 0) == 0:
        return False

    job.status = AnalysisJobStatus.ERROR
    job.error_code = code
    job.error_detail = detail[:1000]
    job.finished_at = now
    await record_system_audit(
        db,
        resource_type="AnalysisJob",
        resource_id=job.id,
        action="ERROR",
        before={"status": AnalysisJobStatus.RUNNING.value},
        after={"status": job.status.value, "error_code": code},
        reason="PDF ingestion failed",
    )
    await db.flush()
    return True


LEGACY_CANCELLED_MARKER_KEY: str = "_alembic_20260828_0006_legacy_cancelled"


async def retry_job(db: AsyncSession, job: AnalysisJob, user: User) -> AnalysisJob:
    await authorize_job(db, job, user, retry=True)
    locked = (
        await db.execute(
            sa.select(AnalysisJob).where(AnalysisJob.id == job.id).with_for_update()
        )
    ).scalar_one()
    if locked.status is not AnalysisJobStatus.ERROR:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="Job is not in ERROR"
        )
    if locked.attempt_count >= locked.max_attempts:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="Retry limit reached"
        )
    document = await db.get(DocumentVersion, locked.document_version_id)
    if document is not None:
        document.status = DocumentStatus.QUEUED
    snapshot = getattr(locked, "snapshot", None)
    if snapshot and LEGACY_CANCELLED_MARKER_KEY in snapshot:
        updated_snapshot = dict(snapshot)
        updated_snapshot.pop(LEGACY_CANCELLED_MARKER_KEY, None)
        locked.snapshot = updated_snapshot
    before = locked.status.value
    locked.status = AnalysisJobStatus.QUEUED
    locked.error_code = None
    locked.error_detail = None
    locked.finished_at = None
    locked.started_at = None
    locked.heartbeat_at = None
    locked.queued_at = datetime.now(UTC)
    await record_audit(
        db,
        actor_user_id=user.id,
        resource_type="AnalysisJob",
        resource_id=locked.id,
        action="QUEUED",
        before={"status": before},
        after={"status": locked.status.value},
        reason="Analysis job retry requested",
    )
    await db.flush()
    return locked
