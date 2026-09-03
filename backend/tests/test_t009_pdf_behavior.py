import asyncio
import uuid
from datetime import UTC, datetime, timedelta
from io import BytesIO
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException
from pypdf import PdfWriter

from app.api.schemas_submission import PresignRequest, PresignResponse
from app.models.enums import (
    AnalysisJobStatus,
    AssignmentStatus,
    DocumentStatus,
    UserRole,
)
from app.services import analysis_job as job_service
from app.services.pdf_validation import PDFValidationError, validate_pdf
from app.services.storage import ObjectHead, S3Storage
from app.services.submission import _reused_response, complete_upload, initiate_upload


def _blank_pdf(*, active: bool = False, attachment: bool = False) -> bytes:
    writer = PdfWriter()
    writer.add_blank_page(width=72, height=72)
    if active:
        writer.add_js("app.alert('untrusted')")
    if attachment:
        writer.add_attachment("payload.txt", b"secret")
    stream = BytesIO()
    writer.write(stream)
    return stream.getvalue()


def test_invalid_magic_and_oversize_have_stable_errors() -> None:
    with pytest.raises(PDFValidationError, match="NOT_A_PDF") as magic:
        validate_pdf(b"not-pdf")
    assert magic.value.code == "NOT_A_PDF"
    with pytest.raises(PDFValidationError) as size:
        validate_pdf(b"%PDF-1.7", max_size_bytes=4)
    assert size.value.code == "PDF_TOO_LARGE"


def test_scan_only_pdf_has_stable_error() -> None:
    with pytest.raises(PDFValidationError) as error:
        validate_pdf(_blank_pdf())
    assert error.value.code == "PDF_SCAN_ONLY"


def test_malformed_encrypted_and_page_limit_errors_are_stable() -> None:
    with pytest.raises(PDFValidationError) as malformed:
        validate_pdf(b"%PDF-1.7\nnot a complete object")
    assert malformed.value.code == "PDF_MALFORMED"
    with pytest.raises(PDFValidationError) as limited:
        validate_pdf(_blank_pdf(), max_page_count=0)
    assert limited.value.code == "PDF_PAGE_LIMIT"
    writer = PdfWriter()
    writer.add_blank_page(width=72, height=72)
    writer.encrypt("password")
    encrypted = BytesIO()
    writer.write(encrypted)
    with pytest.raises(PDFValidationError) as locked:
        validate_pdf(encrypted.getvalue())
    assert locked.value.code == "PDF_ENCRYPTED"


def test_presign_requires_valid_sha256() -> None:
    request = {
        "filename": "paper.pdf",
        "content_type": "application/pdf",
        "size_bytes": 128,
    }
    with pytest.raises(ValueError):
        PresignRequest.model_validate(request)
    with pytest.raises(ValueError):
        PresignRequest.model_validate({**request, "sha256": "z" * 64})
    parsed = PresignRequest.model_validate({**request, "sha256": "A" * 64})
    assert parsed.sha256 == "A" * 64


def test_presign_uses_five_minute_expiry_and_exact_object_key() -> None:
    calls: list[dict[str, object]] = []

    class PublicClient:
        def generate_presigned_post(self, **kwargs: object) -> dict[str, object]:
            calls.append(kwargs)
            return {"url": "http://localhost:9000/docgrading", "fields": {}}

    storage = object.__new__(S3Storage)
    storage.bucket = "docgrading"
    storage.expiry_seconds = 300
    storage._public = PublicClient()

    storage.create_presigned_post("uploads/random.pdf", 1024)

    assert calls == [
        {
            "Bucket": "docgrading",
            "Key": "uploads/random.pdf",
            "Fields": {"Content-Type": "application/pdf"},
            "Conditions": [
                {"key": "uploads/random.pdf"},
                {"Content-Type": "application/pdf"},
                ["content-length-range", 1, 1024],
            ],
            "ExpiresIn": 300,
        }
    ]


def test_duplicate_sha_reuses_active_upload_instead_of_inserting(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "app.services.submission.get_settings",
        lambda: SimpleNamespace(
            pdf_max_size_bytes=50_000_000,
            storage_presign_expiry_seconds=300,
        ),
    )
    assignment = SimpleNamespace(
        id=uuid.uuid4(),
        course_id=uuid.uuid4(),
        status=AssignmentStatus.OPEN,
        due_at=datetime.now(UTC) + timedelta(hours=1),
        max_submissions=3,
    )
    user = SimpleNamespace(id=uuid.uuid4(), roles={UserRole.STUDENT})
    submission = SimpleNamespace(
        id=uuid.uuid4(), assignment_id=assignment.id, student_id=user.id
    )
    version = SimpleNamespace(
        id=uuid.uuid4(),
        submission_id=submission.id,
        storage_key=f"uploads/{user.id}/{uuid.uuid4()}.pdf",
        status=DocumentStatus.UPLOADING,
        upload_expires_at=datetime.now(UTC),
    )
    sha256 = "a" * 64
    values = [assignment, uuid.uuid4(), submission, None]

    class Result:
        def __init__(self, value: object) -> None:
            self.value = value

        def scalar_one_or_none(self) -> object:
            return self.value

    class DB:
        async def execute(self, statement):
            if values:
                return Result(values.pop(0))
            if "document_versions.status !=" in str(statement):
                return Result(None)
            if "document_versions.sha256" in str(statement):
                return Result(version)
            raise AssertionError(
                "Duplicate SHA must return before inserting another row"
            )

        async def flush(self) -> None:
            raise AssertionError("Duplicate SHA must not flush a new row")

        def add(self, _value: object) -> None:
            raise AssertionError("Duplicate SHA must not add a new row")

    storage = SimpleNamespace(
        expiry_seconds=300,
        create_presigned_post=lambda key, _limit: {
            "url": "http://localhost:9000/docgrading",
            "fields": {"key": key},
        },
    )
    version_result, response = asyncio.run(
        initiate_upload(
            DB(),
            assignment_id=assignment.id,
            user=user,
            idempotency_key="retry-with-new-request-id",
            filename="same.pdf",
            content_type="application/pdf",
            size_bytes=128,
            sha256=sha256,
            storage=storage,
        )
    )

    assert version_result is version
    assert response["document_version_id"] == version.id
    assert response["object_key"] == version.storage_key
    assert response["reused"] is True
    assert response["upload_url"] == "http://localhost:9000/docgrading"


@pytest.fixture
def worker_tasks(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("POSTGRES_DB", "docgrading_test")
    monkeypatch.setenv("POSTGRES_USER", "docgrading_test")
    monkeypatch.setenv("POSTGRES_PASSWORD", "test-only")
    from app.core.config import get_settings

    get_settings.cache_clear()
    from app.workers import tasks

    yield tasks
    get_settings.cache_clear()


class _WorkerSessionContext:
    def __init__(self, db: object) -> None:
        self.db = db

    async def __aenter__(self) -> object:
        return self.db

    async def __aexit__(self, *_args: object) -> None:
        return None


def _patch_worker_session(
    monkeypatch: pytest.MonkeyPatch, worker_tasks_mod: object, db: object, job: object
) -> None:
    monkeypatch.setattr(
        worker_tasks_mod,
        "_session_factory",
        lambda: lambda: _WorkerSessionContext(db),
    )
    monkeypatch.setattr(
        worker_tasks_mod, "claim_job_by_id", AsyncMock(return_value=job)
    )


def test_worker_rejects_server_computed_sha_mismatch(
    monkeypatch: pytest.MonkeyPatch,
    worker_tasks: object,
) -> None:
    document = SimpleNamespace(
        id=uuid.uuid4(),
        storage_key="private/object.pdf",
        declared_sha256="0" * 64,
        submission_id=uuid.uuid4(),
        status=DocumentStatus.QUEUED,
        failure_code=None,
        failure_detail=None,
    )
    job = SimpleNamespace(id=uuid.uuid4(), attempt_count=1, document_version=document)
    db = SimpleNamespace(commit=AsyncMock(), rollback=AsyncMock())
    _patch_worker_session(monkeypatch, worker_tasks, db, job)
    monkeypatch.setattr(
        worker_tasks,
        "S3Storage",
        lambda: SimpleNamespace(get_bounded=lambda *_args: b"%PDF-1.7"),
    )
    build_ir = AsyncMock(
        side_effect=PDFValidationError(
            "PDF_SHA256_MISMATCH", "PDF checksum does not match"
        )
    )
    monkeypatch.setattr(worker_tasks, "get_or_build_document_ir", build_ir)
    monkeypatch.setattr(
        worker_tasks, "update_heartbeat", AsyncMock(return_value=True)
    )
    mark_error = AsyncMock(return_value=True)
    monkeypatch.setattr(worker_tasks, "mark_error", mark_error)
    result = asyncio.run(worker_tasks._run_analysis_job(str(job.id)))
    build_ir.assert_awaited_once()

    assert result == str(job.id)
    assert document.status is DocumentStatus.INVALID
    assert document.failure_code == "PDF_SHA256_MISMATCH"
    assert "checksum" in document.failure_detail
    mark_error.assert_awaited_once_with(
        db,
        job,
        "PDF_SHA256_MISMATCH",
        "PDF checksum does not match",
        attempt_count=1,
    )


def test_worker_storage_failure_marks_document_failed_without_secret(
    monkeypatch: pytest.MonkeyPatch,
    worker_tasks: object,
) -> None:
    document = SimpleNamespace(
        storage_key="private/object.pdf",
        declared_sha256="0" * 64,
        status=DocumentStatus.QUEUED,
        failure_code=None,
        failure_detail=None,
    )
    job = SimpleNamespace(id=uuid.uuid4(), attempt_count=1, document_version=document)
    db = SimpleNamespace(commit=AsyncMock(), rollback=AsyncMock())
    _patch_worker_session(monkeypatch, worker_tasks, db, job)

    class BrokenStorage:
        def get_bounded(self, *_args: object) -> bytes:
            raise RuntimeError("secret signed URL and provider metadata")

    monkeypatch.setattr(worker_tasks, "S3Storage", BrokenStorage)
    mark_error = AsyncMock(return_value=True)
    monkeypatch.setattr(worker_tasks, "mark_error", mark_error)

    result = asyncio.run(worker_tasks._run_analysis_job(str(job.id)))

    assert result == str(job.id)
    assert document.status is DocumentStatus.PROCESSING_FAILED
    assert document.failure_code == "PDF_STORAGE_ERROR"
    assert document.failure_detail == "Object storage read failed"
    mark_error.assert_awaited_once_with(
        db,
        job,
        "PDF_STORAGE_ERROR",
        "Object storage read failed",
        attempt_count=1,
    )


@pytest.mark.parametrize("kwargs", [{"active": True}, {"attachment": True}])
def test_indirect_active_content_and_attachment_are_rejected(
    kwargs: dict[str, bool],
) -> None:
    with pytest.raises(PDFValidationError) as error:
        validate_pdf(_blank_pdf(**kwargs))
    assert error.value.code == "PDF_ACTIVE_CONTENT"


def test_reused_completed_upload_has_no_overwrite_credentials() -> None:
    version = SimpleNamespace(
        submission_id=uuid.uuid4(),
        id=uuid.uuid4(),
        storage_key="private/existing.pdf",
        status=DocumentStatus.QUEUED,
    )
    job_id = uuid.uuid4()
    result = SimpleNamespace(
        scalar_one_or_none=lambda: SimpleNamespace(
            id=job_id, status=AnalysisJobStatus.DONE
        )
    )
    db = SimpleNamespace(execute=AsyncMock(return_value=result))
    response = PresignResponse.model_validate(
        asyncio.run(_reused_response(db, version))
    )
    assert response.reused is True
    assert response.upload_url is None
    assert response.fields is None
    assert response.analysis_job_id == job_id


def test_completion_sanitizes_generic_storage_failure_and_marks_failed() -> None:
    version_id = "version"
    user_id = "student"
    version = SimpleNamespace(
        id=version_id,
        submission_id="submission",
        storage_key="private/object.pdf",
        status=DocumentStatus.UPLOADING,
        upload_expires_at=None,
    )
    submission = SimpleNamespace(student_id=user_id, assignment_id="assignment")
    assignment = SimpleNamespace(
        id="assignment",
        status=AssignmentStatus.OPEN,
        due_at=None,
        rubric_version_id="rubric",
    )

    class Result:
        def one_or_none(self):
            return (version, submission, assignment)

        def first(self):
            return (version, submission, assignment)

    class DB:
        async def execute(self, _statement):
            return Result()

        commit = AsyncMock()
        flush = AsyncMock()

    class BrokenStorage:
        def head(self, _key):
            raise RuntimeError("secret provider request metadata")

    with pytest.raises(HTTPException) as error:
        asyncio.run(
            complete_upload(
                DB(),
                version_id=version_id,
                user=SimpleNamespace(id=user_id, roles={UserRole.STUDENT}),
                storage=BrokenStorage(),
            )
        )
    assert error.value.status_code == 503
    assert error.value.detail == "Object storage is temporarily unavailable"
    assert version.status is DocumentStatus.PROCESSING_FAILED
    assert version.failure_code == "STORAGE_UNAVAILABLE"
    assert "secret" not in version.failure_detail


@pytest.mark.parametrize(
    ("head", "detail"),
    [
        (ObjectHead(content_type="text/plain", content_length=128), "content type"),
        (
            ObjectHead(content_type="application/pdf", content_length=129),
            "does not match",
        ),
    ],
)
def test_completion_uses_server_observed_metadata(
    monkeypatch: pytest.MonkeyPatch, head: ObjectHead, detail: str
) -> None:
    monkeypatch.setattr(
        "app.services.submission.get_settings",
        lambda: SimpleNamespace(
            pdf_max_size_bytes=50_000_000,
            storage_presign_expiry_seconds=300,
        ),
    )
    version_id = "version"
    user_id = "student"
    version = SimpleNamespace(
        id=version_id,
        submission_id="submission",
        storage_key="private/object.pdf",
        status=DocumentStatus.UPLOADING,
        upload_expires_at=None,
        size_bytes=128,
    )
    submission = SimpleNamespace(student_id=user_id, assignment_id="assignment")
    assignment = SimpleNamespace(
        id="assignment",
        status=AssignmentStatus.OPEN,
        due_at=None,
        rubric_version_id="rubric",
    )

    class Result:
        def one_or_none(self):
            return (version, submission, assignment)

        def first(self):
            return (version, submission, assignment)

    class DB:
        async def execute(self, _statement):
            return Result()

        commit = AsyncMock()
        flush = AsyncMock()

    storage = SimpleNamespace(head=lambda _key: head)
    with pytest.raises(HTTPException) as error:
        asyncio.run(
            complete_upload(
                DB(),
                version_id=version_id,
                user=SimpleNamespace(id=user_id, roles={UserRole.STUDENT}),
                storage=storage,
            )
        )
    assert error.value.status_code == 422
    assert detail in error.value.detail
    assert version.status is DocumentStatus.UPLOADING


def test_multirole_cannot_complete_as_student() -> None:
    class NeverQueriedDB:
        async def execute(self, _statement):
            raise AssertionError("Stronger role must be checked before object lookup")

    with pytest.raises(HTTPException) as error:
        asyncio.run(
            complete_upload(
                NeverQueriedDB(),
                version_id=uuid.uuid4(),
                user=SimpleNamespace(
                    id=uuid.uuid4(), roles={UserRole.ADMIN, UserRole.STUDENT}
                ),
                storage=SimpleNamespace(),
            )
        )
    assert error.value.status_code == 403


def test_other_user_denied_but_teacher_student_multirole_uses_teacher_branch() -> None:
    job = SimpleNamespace(document_version_id=uuid.uuid4())
    teacher_id = uuid.uuid4()
    student_id = uuid.uuid4()

    class Result:
        def one_or_none(self):
            return (student_id, uuid.uuid4(), teacher_id)

    class DB:
        async def execute(self, _statement):
            return Result()

    with pytest.raises(HTTPException) as denied:
        asyncio.run(
            job_service.authorize_job(
                DB(), job, SimpleNamespace(id=uuid.uuid4(), roles={UserRole.STUDENT})
            )
        )
    assert denied.value.status_code == 404
    asyncio.run(
        job_service.authorize_job(
            DB(), job, SimpleNamespace(id=student_id, roles={UserRole.STUDENT})
        )
    )
    asyncio.run(
        job_service.authorize_job(
            DB(),
            job,
            SimpleNamespace(id=teacher_id, roles={UserRole.TEACHER, UserRole.STUDENT}),
        )
    )
    asyncio.run(
        job_service.authorize_job(
            DB(),
            job,
            SimpleNamespace(id=teacher_id, roles={UserRole.TEACHER, UserRole.STUDENT}),
            retry=True,
        )
    )

    class NeverQueriedDB:
        async def execute(self, _statement):
            raise AssertionError("Admin authorization must not use Student ownership")

    asyncio.run(
        job_service.authorize_job(
            NeverQueriedDB(),
            job,
            SimpleNamespace(id=uuid.uuid4(), roles={UserRole.ADMIN, UserRole.STUDENT}),
            retry=True,
        )
    )


def test_retry_reuses_same_job_row_and_preserves_attempt_count(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    job = SimpleNamespace(
        id=uuid.uuid4(),
        document_version_id=uuid.uuid4(),
        status=AnalysisJobStatus.ERROR,
        attempt_count=2,
        max_attempts=3,
        error_code="PDF_MALFORMED",
        error_detail="bad",
        finished_at=object(),
        started_at=object(),
        queued_at=None,
    )
    document = SimpleNamespace(status=DocumentStatus.INVALID)
    added: list[object] = []

    class Result:
        def scalar_one(self):
            return job

    class DB:
        async def execute(self, _statement):
            return Result()

        async def get(self, _model, _key):
            return document

        def add(self, event):
            added.append(event)

        flush = AsyncMock()

    async def allow(*_args, **_kwargs):
        pass

    async def audit(*_args, **_kwargs):
        pass

    monkeypatch.setattr(job_service, "authorize_job", allow)
    monkeypatch.setattr(job_service, "record_audit", audit)
    result = asyncio.run(
        job_service.retry_job(DB(), job, SimpleNamespace(id=uuid.uuid4()))
    )
    assert result is job
    assert result.status is AnalysisJobStatus.QUEUED
    assert result.attempt_count == 2
    assert result.error_code is None
    assert document.status is DocumentStatus.QUEUED
    assert added == []
