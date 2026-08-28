"""Upload initiation/completion with server-authoritative object checks."""

from __future__ import annotations

import asyncio
import hashlib
import json
import uuid
from datetime import UTC, datetime, timedelta

import sqlalchemy as sa
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.models.analysis import AnalysisJob
from app.models.assignment import Assignment
from app.models.course import Membership
from app.models.enums import (
    AssignmentStatus,
    DocumentStatus,
    MembershipRole,
    MembershipStatus,
    UserRole,
)
from app.models.identity import User
from app.models.submission import DocumentVersion, Submission
from app.services.analysis_job import create_or_get_job
from app.services.storage import S3Storage, StorageObjectNotFound


def _fingerprint(
    *, filename: str, content_type: str, size_bytes: int, sha256: str
) -> str:
    payload = json.dumps(
        {
            "filename": filename,
            "content_type": content_type,
            "size_bytes": size_bytes,
            "sha256": sha256,
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    return hashlib.sha256(payload).hexdigest()


def _require_student_upload_actor(user: User) -> None:
    if (
        UserRole.STUDENT not in user.roles
        or UserRole.ADMIN in user.roles
        or UserRole.TEACHER in user.roles
    ):
        raise HTTPException(
            status_code=403, detail="Only students may upload submissions"
        )


async def initiate_upload(
    db: AsyncSession,
    *,
    assignment_id: uuid.UUID,
    user: User,
    idempotency_key: str,
    filename: str,
    content_type: str,
    size_bytes: int,
    sha256: str,
    storage: S3Storage | None = None,
) -> tuple[DocumentVersion, dict[str, object]]:
    _require_student_upload_actor(user)
    assignment = (
        await db.execute(
            sa.select(Assignment)
            .where(Assignment.id == assignment_id)
            .with_for_update()
        )
    ).scalar_one_or_none()
    if assignment is None:
        raise HTTPException(status_code=404, detail="Assignment not found")
    now = datetime.now(UTC)
    sha256 = sha256.lower()
    if len(sha256) != 64 or any(char not in "0123456789abcdef" for char in sha256):
        raise HTTPException(status_code=422, detail="SHA-256 hint is invalid")
    if content_type.lower().strip() != "application/pdf":
        raise HTTPException(status_code=422, detail="Only application/pdf is accepted")
    if size_bytes > get_settings().pdf_max_size_bytes:
        raise HTTPException(status_code=413, detail="PDF exceeds maximum size")
    if assignment.status != AssignmentStatus.OPEN or assignment.due_at <= now:
        raise HTTPException(
            status_code=409, detail="Assignment is not accepting submissions"
        )
    member = (
        await db.execute(
            sa.select(Membership.id).where(
                Membership.course_id == assignment.course_id,
                Membership.user_id == user.id,
                Membership.role == MembershipRole.STUDENT,
                Membership.status == MembershipStatus.ACTIVE,
            )
        )
    ).scalar_one_or_none()
    if member is None:
        raise HTTPException(status_code=404, detail="Assignment not found")
    submission = (
        await db.execute(
            sa.select(Submission)
            .where(
                Submission.assignment_id == assignment.id,
                Submission.student_id == user.id,
            )
            .with_for_update()
        )
    ).scalar_one_or_none()
    if submission is None:
        submission = Submission(
            id=uuid.uuid4(), assignment_id=assignment.id, student_id=user.id
        )
        db.add(submission)
        await db.flush()
    fingerprint = _fingerprint(
        filename=filename,
        content_type=content_type,
        size_bytes=size_bytes,
        sha256=sha256,
    )
    existing = (
        await db.execute(
            sa.select(DocumentVersion).where(
                DocumentVersion.submission_id == submission.id,
                DocumentVersion.idempotency_key == idempotency_key,
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        if existing.idempotency_fingerprint != fingerprint:
            raise HTTPException(
                status_code=409, detail="Idempotency key payload conflict"
            )
        if existing.status != DocumentStatus.UPLOADING:
            return existing, await _reused_response(db, existing)
        existing.upload_expires_at = now + timedelta(
            seconds=get_settings().storage_presign_expiry_seconds
        )
        return existing, _presign_response(existing, storage=storage, reused=True)
    duplicate = (
        await db.execute(
            sa.select(DocumentVersion).where(
                DocumentVersion.submission_id == submission.id,
                DocumentVersion.sha256 == sha256,
            )
        )
    ).scalar_one_or_none()
    if duplicate is not None:
        if duplicate.status == DocumentStatus.UPLOADING:
            duplicate.upload_expires_at = now + timedelta(
                seconds=get_settings().storage_presign_expiry_seconds
            )
            return duplicate, _presign_response(duplicate, storage=storage, reused=True)
        return duplicate, await _reused_response(db, duplicate)
    version_count = (
        await db.execute(
            sa.select(sa.func.count(DocumentVersion.id)).where(
                DocumentVersion.submission_id == submission.id
            )
        )
    ).scalar_one()
    if version_count >= assignment.max_submissions:
        raise HTTPException(status_code=409, detail="Submission attempt limit reached")
    previous = (
        await db.execute(
            sa.select(DocumentVersion.id)
            .where(DocumentVersion.submission_id == submission.id)
            .order_by(DocumentVersion.version_number.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    # The client digest enables duplicate lookup, but the worker always replaces it
    # with a digest computed from the bytes fetched from object storage.
    version_id = uuid.uuid4()
    version = DocumentVersion(
        id=version_id,
        submission_id=submission.id,
        version_number=int(version_count) + 1,
        previous_version_id=previous,
        storage_key=f"uploads/{user.id}/{uuid.uuid4()}.pdf",
        original_filename=filename,
        content_type="application/pdf",
        size_bytes=size_bytes,
        sha256=sha256,
        declared_sha256=sha256,
        status=DocumentStatus.UPLOADING,
        idempotency_key=idempotency_key,
        idempotency_fingerprint=fingerprint,
        upload_expires_at=now
        + timedelta(seconds=get_settings().storage_presign_expiry_seconds),
    )
    db.add(version)
    await db.flush()
    return version, _presign_response(version, storage=storage)


def _presign_response(
    version: DocumentVersion,
    *,
    storage: S3Storage | None,
    reused: bool = False,
) -> dict[str, object]:
    storage = storage or S3Storage()
    signed = storage.create_presigned_post(
        version.storage_key, get_settings().pdf_max_size_bytes
    )
    return {
        "submission_id": version.submission_id,
        "document_version_id": version.id,
        "object_key": version.storage_key,
        "upload_url": signed["url"],
        "fields": signed["fields"],
        "expires_in": storage.expiry_seconds,
        "status": version.status.value,
        "reused": reused,
    }


async def _reused_response(
    db: AsyncSession, version: DocumentVersion
) -> dict[str, object]:
    job = (
        await db.execute(
            sa.select(AnalysisJob).where(AnalysisJob.document_version_id == version.id)
        )
    ).scalar_one_or_none()
    return {
        "submission_id": version.submission_id,
        "document_version_id": version.id,
        "object_key": version.storage_key,
        "status": job.status.value if job else version.status.value,
        "reused": True,
        "analysis_job_id": job.id if job else None,
    }


async def complete_upload(
    db: AsyncSession,
    *,
    version_id: uuid.UUID,
    user: User,
    storage: S3Storage | None = None,
) -> tuple[DocumentVersion, object]:
    _require_student_upload_actor(user)
    version = (
        await db.execute(
            sa.select(DocumentVersion)
            .where(DocumentVersion.id == version_id)
            .with_for_update()
        )
    ).scalar_one_or_none()
    if version is None:
        raise HTTPException(status_code=404, detail="Document version not found")
    submission = await db.get(Submission, version.submission_id)
    if submission is None or submission.student_id != user.id:
        raise HTTPException(status_code=404, detail="Document version not found")
    if version.status in {
        DocumentStatus.QUEUED,
        DocumentStatus.PROCESSING,
        DocumentStatus.AWAITING_REVIEW,
        DocumentStatus.APPROVED,
        DocumentStatus.PUBLISHED,
    }:
        job = (
            await db.execute(
                sa.select(AnalysisJob).where(
                    AnalysisJob.document_version_id == version.id
                )
            )
        ).scalar_one_or_none()
        if job is None:
            raise HTTPException(
                status_code=409, detail="Document completion is inconsistent"
            )
        return version, job
    if version.status == DocumentStatus.INVALID:
        raise HTTPException(status_code=409, detail="Document upload is invalid")
    if version.upload_expires_at and version.upload_expires_at < datetime.now(UTC):
        raise HTTPException(status_code=409, detail="Upload has expired")
    storage = storage or S3Storage()
    try:
        head = await asyncio.to_thread(storage.head, version.storage_key)
    except StorageObjectNotFound as exc:
        raise HTTPException(
            status_code=409, detail="Uploaded object not found"
        ) from exc
    except Exception as exc:
        version.status = DocumentStatus.PROCESSING_FAILED
        version.failure_code = "STORAGE_UNAVAILABLE"
        version.failure_detail = "Object storage is temporarily unavailable"
        await db.flush()
        raise HTTPException(
            status_code=503, detail="Object storage is temporarily unavailable"
        ) from exc
    if head.content_type.lower().strip() != "application/pdf":
        raise HTTPException(
            status_code=422, detail="Uploaded object content type is invalid"
        )
    if (
        head.content_length <= 0
        or head.content_length > get_settings().pdf_max_size_bytes
    ):
        raise HTTPException(status_code=422, detail="Uploaded object size is invalid")
    if head.content_length != version.size_bytes:
        raise HTTPException(
            status_code=422, detail="Uploaded object size does not match"
        )
    version.content_type = head.content_type
    version.size_bytes = head.content_length
    version.status = DocumentStatus.QUEUED
    job = await create_or_get_job(
        db,
        document_version_id=version.id,
        rubric_version_id=(
            await db.get(Assignment, submission.assignment_id)
        ).rubric_version_id,
    )
    await db.flush()
    return version, job
