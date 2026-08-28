import asyncio
import uuid
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from app.api.schemas_submission import PresignRequest
from app.models.enums import (
    AnalysisJobStatus,
    AssignmentStatus,
    DocumentStatus,
    UserRole,
)
from app.services.storage import ObjectHead, StorageObjectNotFound
from app.services.submission import complete_upload


def test_presign_rejects_whitespace_only_filename() -> None:
    valid_payload = {
        "content_type": "application/pdf",
        "size_bytes": 1024,
        "sha256": "a" * 64,
    }
    with pytest.raises(ValidationError):
        PresignRequest.model_validate({**valid_payload, "filename": "   "})

    with pytest.raises(ValidationError):
        PresignRequest.model_validate({**valid_payload, "filename": " \t \n \r "})

    with pytest.raises(ValidationError):
        PresignRequest.model_validate({**valid_payload, "filename": ""})

    # Valid filename with whitespace padding is preserved
    req = PresignRequest.model_validate(
        {**valid_payload, "filename": "  my_paper.pdf  "}
    )
    assert req.filename == "  my_paper.pdf  "

    # Standard valid filename is accepted
    req2 = PresignRequest.model_validate({**valid_payload, "filename": "report.pdf"})
    assert req2.filename == "report.pdf"


def test_complete_upload_lock_query_semantics() -> None:
    executed_statements = []
    version_id = uuid.uuid4()
    user_id = uuid.uuid4()
    now = datetime.now(UTC)

    version = SimpleNamespace(
        id=version_id,
        submission_id=uuid.uuid4(),
        storage_key="uploads/test.pdf",
        status=DocumentStatus.UPLOADING,
        upload_expires_at=now + timedelta(minutes=5),
        size_bytes=100,
        content_type="application/pdf",
    )
    submission = SimpleNamespace(
        id=version.submission_id,
        assignment_id=uuid.uuid4(),
        student_id=user_id,
    )
    assignment = SimpleNamespace(
        id=submission.assignment_id,
        status=AssignmentStatus.OPEN,
        due_at=now + timedelta(hours=1),
        rubric_version_id=uuid.uuid4(),
    )

    class Result:
        def one_or_none(self):
            return (version, submission, assignment)

        def first(self):
            return (version, submission, assignment)

    class DB:
        async def execute(self, statement):
            executed_statements.append(statement)
            return Result()

        flush = AsyncMock()
        commit = AsyncMock()

    storage = SimpleNamespace(
        head=lambda _key: ObjectHead(
            content_type="application/pdf",
            content_length=100,
        )
    )

    user = SimpleNamespace(id=user_id, roles={UserRole.STUDENT})

    created_job = SimpleNamespace(id=uuid.uuid4(), status=AnalysisJobStatus.QUEUED)

    async def run_test():
        # Monkeypatch create_or_get_job to observe rubric_version_id used
        import app.services.submission as sub_module

        original_create_job = sub_module.create_or_get_job
        passed_rubric_id = None

        async def mock_create_job(_db, *, document_version_id, rubric_version_id):
            nonlocal passed_rubric_id
            passed_rubric_id = rubric_version_id
            return created_job

        sub_module.create_or_get_job = mock_create_job
        try:
            v, job = await complete_upload(
                DB(),
                version_id=version_id,
                user=user,
                storage=storage,
            )
            assert v is version
            assert job is created_job
            assert passed_rubric_id == assignment.rubric_version_id
        finally:
            sub_module.create_or_get_job = original_create_job

    asyncio.run(run_test())

    assert len(executed_statements) >= 1
    select_stmt = executed_statements[0]
    compiled = str(select_stmt)
    assert "document_versions" in compiled
    assert "submissions" in compiled
    assert "assignments" in compiled
    assert select_stmt._for_update_arg is not None


def test_complete_upload_rejects_first_completion_when_assignment_closed() -> None:
    version_id = uuid.uuid4()
    user_id = uuid.uuid4()
    now = datetime.now(UTC)

    version = SimpleNamespace(
        id=version_id,
        submission_id=uuid.uuid4(),
        storage_key="uploads/test.pdf",
        status=DocumentStatus.UPLOADING,
        upload_expires_at=now + timedelta(minutes=5),
        size_bytes=100,
    )
    submission = SimpleNamespace(
        id=version.submission_id,
        assignment_id=uuid.uuid4(),
        student_id=user_id,
    )
    assignment = SimpleNamespace(
        id=submission.assignment_id,
        status=AssignmentStatus.CLOSED,
        due_at=now + timedelta(hours=1),
        rubric_version_id=uuid.uuid4(),
    )

    class Result:
        def one_or_none(self):
            return (version, submission, assignment)

        def first(self):
            return (version, submission, assignment)

    class DB:
        async def execute(self, _statement):
            return Result()

    with pytest.raises(HTTPException) as exc:
        asyncio.run(
            complete_upload(
                DB(),
                version_id=version_id,
                user=SimpleNamespace(id=user_id, roles={UserRole.STUDENT}),
                storage=SimpleNamespace(),
            )
        )
    assert exc.value.status_code == 409
    assert exc.value.detail == "Assignment is not accepting submissions"


def test_complete_upload_rejects_first_completion_when_assignment_past_due() -> None:
    version_id = uuid.uuid4()
    user_id = uuid.uuid4()
    now = datetime.now(UTC)

    version = SimpleNamespace(
        id=version_id,
        submission_id=uuid.uuid4(),
        storage_key="uploads/test.pdf",
        status=DocumentStatus.UPLOADING,
        upload_expires_at=now + timedelta(minutes=5),
        size_bytes=100,
    )
    submission = SimpleNamespace(
        id=version.submission_id,
        assignment_id=uuid.uuid4(),
        student_id=user_id,
    )
    assignment = SimpleNamespace(
        id=submission.assignment_id,
        status=AssignmentStatus.OPEN,
        due_at=now - timedelta(seconds=1),
        rubric_version_id=uuid.uuid4(),
    )

    class Result:
        def one_or_none(self):
            return (version, submission, assignment)

        def first(self):
            return (version, submission, assignment)

    class DB:
        async def execute(self, _statement):
            return Result()

    with pytest.raises(HTTPException) as exc:
        asyncio.run(
            complete_upload(
                DB(),
                version_id=version_id,
                user=SimpleNamespace(id=user_id, roles={UserRole.STUDENT}),
                storage=SimpleNamespace(),
            )
        )
    assert exc.value.status_code == 409
    assert exc.value.detail == "Assignment is not accepting submissions"


def test_complete_upload_rejects_first_completion_on_exact_deadline() -> None:
    version_id = uuid.uuid4()
    user_id = uuid.uuid4()
    now = datetime.now(UTC)

    version = SimpleNamespace(
        id=version_id,
        submission_id=uuid.uuid4(),
        storage_key="uploads/test.pdf",
        status=DocumentStatus.UPLOADING,
        upload_expires_at=now + timedelta(minutes=5),
        size_bytes=100,
    )
    submission = SimpleNamespace(
        id=version.submission_id,
        assignment_id=uuid.uuid4(),
        student_id=user_id,
    )
    # due_at equals current time exactly
    assignment = SimpleNamespace(
        id=submission.assignment_id,
        status=AssignmentStatus.OPEN,
        due_at=now,
        rubric_version_id=uuid.uuid4(),
    )

    class Result:
        def one_or_none(self):
            return (version, submission, assignment)

        def first(self):
            return (version, submission, assignment)

    class DB:
        async def execute(self, _statement):
            return Result()

    with pytest.raises(HTTPException) as exc:
        asyncio.run(
            complete_upload(
                DB(),
                version_id=version_id,
                user=SimpleNamespace(id=user_id, roles={UserRole.STUDENT}),
                storage=SimpleNamespace(),
            )
        )
    assert exc.value.status_code == 409
    assert exc.value.detail == "Assignment is not accepting submissions"


def test_complete_upload_idempotent_for_completed_when_closed_or_late() -> None:
    version_id = uuid.uuid4()
    user_id = uuid.uuid4()
    now = datetime.now(UTC)

    version = SimpleNamespace(
        id=version_id,
        submission_id=uuid.uuid4(),
        storage_key="uploads/test.pdf",
        status=DocumentStatus.QUEUED,
        upload_expires_at=now - timedelta(hours=10),
        size_bytes=100,
    )
    submission = SimpleNamespace(
        id=version.submission_id,
        assignment_id=uuid.uuid4(),
        student_id=user_id,
    )
    # Assignment is closed AND past due
    assignment = SimpleNamespace(
        id=submission.assignment_id,
        status=AssignmentStatus.CLOSED,
        due_at=now - timedelta(hours=10),
        rubric_version_id=uuid.uuid4(),
    )
    existing_job = SimpleNamespace(
        id=uuid.uuid4(),
        document_version_id=version_id,
        status=AnalysisJobStatus.RUNNING,
    )

    class LockResult:
        def one_or_none(self):
            return (version, submission, assignment)

        def first(self):
            return (version, submission, assignment)

    class JobResult:
        def scalar_one_or_none(self):
            return existing_job

    class DB:
        async def execute(self, statement):
            if "analysis_jobs" in str(statement):
                return JobResult()
            return LockResult()

    v, job = asyncio.run(
        complete_upload(
            DB(),
            version_id=version_id,
            user=SimpleNamespace(id=user_id, roles={UserRole.STUDENT}),
            storage=SimpleNamespace(),
        )
    )
    assert v is version
    assert job is existing_job


def test_complete_upload_commits_processing_failed_on_generic_storage_error() -> None:
    version_id = uuid.uuid4()
    user_id = uuid.uuid4()
    now = datetime.now(UTC)

    version = SimpleNamespace(
        id=version_id,
        submission_id=uuid.uuid4(),
        storage_key="uploads/test.pdf",
        status=DocumentStatus.UPLOADING,
        upload_expires_at=now + timedelta(minutes=5),
        size_bytes=100,
        failure_code=None,
        failure_detail=None,
    )
    submission = SimpleNamespace(
        id=version.submission_id,
        assignment_id=uuid.uuid4(),
        student_id=user_id,
    )
    assignment = SimpleNamespace(
        id=submission.assignment_id,
        status=AssignmentStatus.OPEN,
        due_at=now + timedelta(hours=1),
        rubric_version_id=uuid.uuid4(),
    )

    class Result:
        def one_or_none(self):
            return (version, submission, assignment)

        def first(self):
            return (version, submission, assignment)

    db_commit_mock = AsyncMock()

    class DB:
        async def execute(self, _statement):
            return Result()

        commit = db_commit_mock
        flush = AsyncMock()

    class BrokenStorage:
        def head(self, _key):
            raise RuntimeError("secret internal s3 credentials error")

    with pytest.raises(HTTPException) as exc:
        asyncio.run(
            complete_upload(
                DB(),
                version_id=version_id,
                user=SimpleNamespace(id=user_id, roles={UserRole.STUDENT}),
                storage=BrokenStorage(),
            )
        )

    assert exc.value.status_code == 503
    assert exc.value.detail == "Object storage is temporarily unavailable"
    assert version.status == DocumentStatus.PROCESSING_FAILED
    assert version.failure_code == "STORAGE_UNAVAILABLE"
    assert version.failure_detail == "Object storage is temporarily unavailable"
    # Verify commit was awaited
    db_commit_mock.assert_awaited_once()


def test_complete_upload_storage_not_found_raises_409_without_commit() -> None:
    version_id = uuid.uuid4()
    user_id = uuid.uuid4()
    now = datetime.now(UTC)

    version = SimpleNamespace(
        id=version_id,
        submission_id=uuid.uuid4(),
        storage_key="uploads/test.pdf",
        status=DocumentStatus.UPLOADING,
        upload_expires_at=now + timedelta(minutes=5),
        size_bytes=100,
    )
    submission = SimpleNamespace(
        id=version.submission_id,
        assignment_id=uuid.uuid4(),
        student_id=user_id,
    )
    assignment = SimpleNamespace(
        id=submission.assignment_id,
        status=AssignmentStatus.OPEN,
        due_at=now + timedelta(hours=1),
        rubric_version_id=uuid.uuid4(),
    )

    class Result:
        def one_or_none(self):
            return (version, submission, assignment)

        def first(self):
            return (version, submission, assignment)

    db_commit_mock = AsyncMock()

    class DB:
        async def execute(self, _statement):
            return Result()

        commit = db_commit_mock
        flush = AsyncMock()

    class NotFoundStorage:
        def head(self, _key):
            raise StorageObjectNotFound("Not found")

    with pytest.raises(HTTPException) as exc:
        asyncio.run(
            complete_upload(
                DB(),
                version_id=version_id,
                user=SimpleNamespace(id=user_id, roles={UserRole.STUDENT}),
                storage=NotFoundStorage(),
            )
        )

    assert exc.value.status_code == 409
    assert exc.value.detail == "Uploaded object not found"
    db_commit_mock.assert_not_called()
