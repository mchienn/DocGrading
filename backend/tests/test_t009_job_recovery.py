import asyncio
import uuid
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import sqlalchemy as sa

from app.models.analysis import AnalysisJob
from app.models.enums import AnalysisJobStatus, DocumentStatus
from app.services import analysis_job as job_service
from app.workers import tasks as worker_tasks


def test_analysis_job_has_nullable_timezone_heartbeat_at() -> None:
    column = AnalysisJob.__table__.c.heartbeat_at
    assert column.nullable is True
    assert isinstance(column.type, sa.DateTime)
    assert column.type.timezone is True


def test_claim_next_job_sets_running_and_processing_with_audits() -> None:
    doc_id = uuid.uuid4()
    job_id = uuid.uuid4()
    document = SimpleNamespace(
        id=doc_id,
        status=DocumentStatus.QUEUED,
        failure_code=None,
        failure_detail=None,
    )
    job = SimpleNamespace(
        id=job_id,
        document_version_id=doc_id,
        status=AnalysisJobStatus.QUEUED,
        attempt_count=0,
        max_attempts=3,
        started_at=None,
        heartbeat_at=None,
        finished_at=None,
        document_version=document,
    )

    class Result:
        def scalar_one_or_none(self):
            return job

    audits = []

    async def fake_system_audit(
        db, *, resource_type, resource_id, action, before=None, after=None, reason=""
    ):
        audits.append(
            {
                "resource_type": resource_type,
                "resource_id": resource_id,
                "action": action,
                "before": before,
                "after": after,
                "reason": reason,
            }
        )

    class DB:
        async def execute(self, _stmt):
            return Result()

        async def get(self, _model, _id):
            return document

        flush = AsyncMock()

    with patch.object(
        job_service, "record_system_audit", side_effect=fake_system_audit
    ):
        claimed = asyncio.run(job_service.claim_next_job(DB()))

    assert claimed is job
    assert job.status is AnalysisJobStatus.RUNNING
    assert job.attempt_count == 1
    assert job.started_at is not None
    assert job.heartbeat_at is not None
    assert document.status is DocumentStatus.PROCESSING

    # Assert both transitions audited in the same transaction
    job_audit = next(a for a in audits if a["resource_type"] == "AnalysisJob")
    assert job_audit["action"] == "RUNNING"
    assert job_audit["after"]["status"] == "RUNNING"
    assert job_audit["after"]["attempt_count"] == 1

    doc_audit = next(a for a in audits if a["resource_type"] == "DocumentVersion")
    assert doc_audit["action"] == "PROCESSING"
    assert doc_audit["before"]["status"] == "QUEUED"
    assert doc_audit["after"]["status"] == "PROCESSING"


def test_claim_job_by_id_sets_running_and_processing_with_audits() -> None:
    doc_id = uuid.uuid4()
    job_id = uuid.uuid4()
    document = SimpleNamespace(
        id=doc_id,
        status=DocumentStatus.QUEUED,
        failure_code=None,
        failure_detail=None,
    )
    job = SimpleNamespace(
        id=job_id,
        document_version_id=doc_id,
        status=AnalysisJobStatus.QUEUED,
        attempt_count=0,
        max_attempts=3,
        started_at=None,
        heartbeat_at=None,
        finished_at=None,
        document_version=document,
    )

    class Result:
        def scalar_one_or_none(self):
            return job

    audits = []

    async def fake_system_audit(
        db, *, resource_type, resource_id, action, before=None, after=None, reason=""
    ):
        audits.append(
            {
                "resource_type": resource_type,
                "resource_id": resource_id,
                "action": action,
                "before": before,
                "after": after,
                "reason": reason,
            }
        )

    class DB:
        async def execute(self, _stmt):
            return Result()

        async def get(self, _model, _id):
            return document

        flush = AsyncMock()

    with patch.object(
        job_service, "record_system_audit", side_effect=fake_system_audit
    ):
        claimed = asyncio.run(job_service.claim_job_by_id(DB(), job_id))

    assert claimed is job
    assert job.status is AnalysisJobStatus.RUNNING
    assert job.attempt_count == 1
    assert job.started_at is not None
    assert job.heartbeat_at is not None
    assert document.status is DocumentStatus.PROCESSING
    assert len(audits) == 2


def test_claim_recovers_stale_running_job_when_attempts_remain() -> None:
    doc_id = uuid.uuid4()
    job_id = uuid.uuid4()
    old_time = datetime.now(UTC) - timedelta(seconds=400)
    document = SimpleNamespace(
        id=doc_id,
        status=DocumentStatus.PROCESSING,
        failure_code=None,
        failure_detail=None,
    )
    job = SimpleNamespace(
        id=job_id,
        document_version_id=doc_id,
        status=AnalysisJobStatus.RUNNING,
        attempt_count=1,
        max_attempts=3,
        started_at=old_time,
        heartbeat_at=old_time,
        finished_at=None,
        document_version=document,
    )

    class Result:
        def scalar_one_or_none(self):
            return job

    audits = []

    async def fake_system_audit(
        db, *, resource_type, resource_id, action, before=None, after=None, reason=""
    ):
        audits.append(
            {
                "resource_type": resource_type,
                "resource_id": resource_id,
                "action": action,
                "before": before,
                "after": after,
                "reason": reason,
            }
        )

    class DB:
        async def execute(self, _stmt):
            return Result()

        async def get(self, _model, _id):
            return document

        flush = AsyncMock()

    with patch.object(
        job_service, "record_system_audit", side_effect=fake_system_audit
    ):
        claimed = asyncio.run(job_service.claim_next_job(DB()))

    assert claimed is job
    assert job.status is AnalysisJobStatus.RUNNING
    assert job.attempt_count == 2
    assert job.started_at > old_time
    assert job.heartbeat_at > old_time
    assert document.status is DocumentStatus.PROCESSING

    # Distinct RUNNING->QUEUED recovery event audited
    requeue_audit = next(
        a
        for a in audits
        if a["resource_type"] == "AnalysisJob" and a["action"] == "QUEUED"
    )
    assert requeue_audit["before"]["status"] == "RUNNING"
    assert requeue_audit["after"]["status"] == "QUEUED"

    # Distinct claim event audited
    claim_audit = next(
        a
        for a in audits
        if a["resource_type"] == "AnalysisJob" and a["action"] == "RUNNING"
    )
    assert claim_audit["after"]["attempt_count"] == 2


def test_claim_exhausts_stale_running_job_to_error_and_document_processing_failed() -> (
    None
):
    doc_id = uuid.uuid4()
    job_id = uuid.uuid4()
    old_time = datetime.now(UTC) - timedelta(seconds=400)
    document = SimpleNamespace(
        id=doc_id,
        status=DocumentStatus.PROCESSING,
        failure_code=None,
        failure_detail=None,
    )
    job = SimpleNamespace(
        id=job_id,
        document_version_id=doc_id,
        status=AnalysisJobStatus.RUNNING,
        attempt_count=3,
        max_attempts=3,
        started_at=old_time,
        heartbeat_at=old_time,
        finished_at=None,
        document_version=document,
    )

    class Result:
        def scalar_one_or_none(self):
            return job

    audits = []

    async def fake_system_audit(
        db, *, resource_type, resource_id, action, before=None, after=None, reason=""
    ):
        audits.append(
            {
                "resource_type": resource_type,
                "resource_id": resource_id,
                "action": action,
                "before": before,
                "after": after,
                "reason": reason,
            }
        )

    class DB:
        async def execute(self, _stmt):
            return Result()

        async def get(self, _model, _id):
            return document

        flush = AsyncMock()

    with patch.object(
        job_service, "record_system_audit", side_effect=fake_system_audit
    ):
        claimed = asyncio.run(job_service.claim_next_job(DB()))

    # Must NOT process exhausted job
    assert claimed is None
    assert job.status is AnalysisJobStatus.ERROR
    assert job.error_code == "LEASE_EXPIRED"
    assert job.finished_at is not None
    assert document.status is DocumentStatus.PROCESSING_FAILED
    assert document.failure_code == "LEASE_EXPIRED"

    # Distinct audits recorded
    job_error_audit = next(
        a
        for a in audits
        if a["resource_type"] == "AnalysisJob" and a["action"] == "ERROR"
    )
    assert job_error_audit["before"]["status"] == "RUNNING"
    assert job_error_audit["after"]["status"] == "ERROR"
    assert job_error_audit["after"]["error_code"] == "LEASE_EXPIRED"

    doc_fail_audit = next(
        a
        for a in audits
        if a["resource_type"] == "DocumentVersion"
        and a["action"] == "PROCESSING_FAILED"
    )
    assert doc_fail_audit["before"]["status"] == "PROCESSING"
    assert doc_fail_audit["after"]["status"] == "PROCESSING_FAILED"
    assert doc_fail_audit["after"]["failure_code"] == "LEASE_EXPIRED"


def test_claim_ignores_active_running_job_within_lease() -> None:
    doc_id = uuid.uuid4()
    job_id = uuid.uuid4()
    recent_time = datetime.now(UTC) - timedelta(seconds=10)
    document = SimpleNamespace(
        id=doc_id,
        status=DocumentStatus.PROCESSING,
    )
    job = SimpleNamespace(
        id=job_id,
        document_version_id=doc_id,
        status=AnalysisJobStatus.RUNNING,
        attempt_count=1,
        max_attempts=3,
        started_at=recent_time,
        heartbeat_at=recent_time,
        finished_at=None,
        document_version=document,
    )

    class Result:
        def scalar_one_or_none(self):
            return job

    class DB:
        async def execute(self, _stmt):
            return Result()

        flush = AsyncMock()

    claimed = asyncio.run(job_service.claim_next_job(DB()))
    assert claimed is None
    assert job.status is AnalysisJobStatus.RUNNING
    assert job.attempt_count == 1


def test_mark_done_sets_job_done_and_document_awaiting_review() -> None:
    doc_id = uuid.uuid4()
    job_id = uuid.uuid4()
    document = SimpleNamespace(
        id=doc_id,
        status=DocumentStatus.PROCESSING,
    )
    job = SimpleNamespace(
        id=job_id,
        document_version_id=doc_id,
        status=AnalysisJobStatus.RUNNING,
        finished_at=None,
        document_version=document,
    )

    audits = []

    async def fake_system_audit(
        db, *, resource_type, resource_id, action, before=None, after=None, reason=""
    ):
        audits.append(
            {
                "resource_type": resource_type,
                "resource_id": resource_id,
                "action": action,
                "before": before,
                "after": after,
                "reason": reason,
            }
        )

    class DB:
        async def get(self, _model, _id):
            return document

        flush = AsyncMock()

    with patch.object(
        job_service, "record_system_audit", side_effect=fake_system_audit
    ):
        asyncio.run(job_service.mark_done(DB(), job))

    assert job.status is AnalysisJobStatus.DONE
    assert job.finished_at is not None
    assert document.status is DocumentStatus.AWAITING_REVIEW

    job_audit = next(a for a in audits if a["resource_type"] == "AnalysisJob")
    assert job_audit["action"] == "DONE"
    assert job_audit["after"]["status"] == "DONE"

    doc_audit = next(a for a in audits if a["resource_type"] == "DocumentVersion")
    assert doc_audit["action"] == "AWAITING_REVIEW"
    assert doc_audit["after"]["status"] == "AWAITING_REVIEW"


def test_update_heartbeat_updates_running_job() -> None:
    job_id = uuid.uuid4()

    class Result:
        rowcount = 1

    class DB:
        async def execute(self, stmt):
            assert "analysis_jobs" in str(stmt) or hasattr(stmt, "table")
            return Result()

    updated = asyncio.run(job_service.update_heartbeat(DB(), job_id))
    assert updated is True


def test_update_heartbeat_returns_false_when_no_rows_updated() -> None:
    job_id = uuid.uuid4()

    class Result:
        rowcount = 0

    class DB:
        async def execute(self, _stmt):
            return Result()

    updated = asyncio.run(job_service.update_heartbeat(DB(), job_id))
    assert updated is False


def test_worker_commits_when_no_job_claimed_or_exhausted_recovered() -> None:
    db = SimpleNamespace(
        commit=AsyncMock(),
        rollback=AsyncMock(),
    )

    class SessionContext:
        async def __aenter__(self):
            return db

        async def __aexit__(self, *args):
            return None

    with (
        patch.object(
            worker_tasks, "_session_factory", return_value=lambda: SessionContext()
        ),
        patch.object(worker_tasks, "claim_next_job", AsyncMock(return_value=None)),
    ):
        result = asyncio.run(worker_tasks._run_analysis_job(None))

    assert result is None
    db.commit.assert_awaited_once()
    db.rollback.assert_not_called()


def test_worker_task_runs_heartbeat_and_stops_before_terminal_done() -> None:
    doc_id = uuid.uuid4()
    job_id = uuid.uuid4()
    document = SimpleNamespace(
        id=doc_id,
        storage_key="test/document.pdf",
        declared_sha256=None,
        submission_id=uuid.uuid4(),
        status=DocumentStatus.PROCESSING,
        sha256=None,
        size_bytes=None,
        page_count=None,
    )
    job = SimpleNamespace(
        id=job_id,
        document_version_id=doc_id,
        status=AnalysisJobStatus.RUNNING,
        document_version=document,
    )

    class Result:
        def scalar_one_or_none(self):
            return None

    class DB:
        async def commit(self):
            pass

        async def execute(self, _stmt):
            return Result()

    class SessionContext:
        async def __aenter__(self):
            return DB()

        async def __aexit__(self, *args):
            return None

    heartbeat_calls = []

    async def fake_update_heartbeat(session, target_job_id):
        heartbeat_calls.append(target_job_id)
        return True

    class FakeStorage:
        def get_bounded(self, key, limit):
            return b"%PDF-1.7"

    def fake_validate_pdf(data, **kwargs):
        return SimpleNamespace(
            sha256="abcdef" * 10 + "1234",
            size_bytes=100,
            page_count=2,
        )

    with (
        patch.object(
            worker_tasks, "_session_factory", return_value=lambda: SessionContext()
        ),
        patch.object(worker_tasks, "claim_next_job", AsyncMock(return_value=job)),
        patch.object(worker_tasks, "S3Storage", FakeStorage),
        patch.object(worker_tasks, "validate_pdf", fake_validate_pdf),
        patch.object(
            worker_tasks,
            "update_heartbeat",
            side_effect=fake_update_heartbeat,
        ),
        patch.object(worker_tasks, "mark_done", AsyncMock()) as mock_mark_done,
    ):
        result = asyncio.run(worker_tasks._run_analysis_job(None))

    assert result == str(job_id)
    assert document.sha256 == "abcdef" * 10 + "1234"
    assert document.size_bytes == 100
    assert document.page_count == 2
    mock_mark_done.assert_awaited_once()
