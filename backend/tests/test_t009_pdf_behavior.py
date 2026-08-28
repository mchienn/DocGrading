import asyncio
import hashlib
import uuid
from io import BytesIO
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException
from pypdf import PdfWriter

from app.api.schemas_submission import PresignResponse
from app.models.enums import AnalysisJobStatus, DocumentStatus, UserRole
from app.services import analysis_job as job_service
from app.services.pdf_validation import PDFValidationError, validate_pdf
from app.services.submission import _reused_response, complete_upload


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


def test_declared_sha_hint_is_compared_by_validation_contract() -> None:
    payload = _blank_pdf()
    expected = hashlib.sha256(payload).hexdigest()
    assert expected != "0" * 64


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

    class Result:
        def scalar_one_or_none(self):
            return version

    class DB:
        async def execute(self, _statement):
            return Result()

        async def get(self, model, _key):
            from app.models.submission import Submission

            return submission if model is Submission else None

        flush = AsyncMock()

    class BrokenStorage:
        def head(self, _key):
            raise RuntimeError("secret provider request metadata")

    with pytest.raises(HTTPException) as error:
        asyncio.run(
            complete_upload(
                DB(),
                version_id=version_id,
                user=SimpleNamespace(id=user_id),
                storage=BrokenStorage(),
            )
        )
    assert error.value.status_code == 503
    assert error.value.detail == "Object storage is temporarily unavailable"
    assert version.status is DocumentStatus.PROCESSING_FAILED
    assert version.failure_code == "STORAGE_UNAVAILABLE"
    assert "secret" not in version.failure_detail


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
            DB(),
            job,
            SimpleNamespace(id=teacher_id, roles={UserRole.TEACHER, UserRole.STUDENT}),
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

    class Result:
        def scalar_one(self):
            return job

    class DB:
        async def execute(self, _statement):
            return Result()

        async def get(self, _model, _key):
            return document

        def add(self, _event):
            pass

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
