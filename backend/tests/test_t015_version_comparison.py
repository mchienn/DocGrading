from __future__ import annotations

import asyncio
import os
import uuid
from datetime import UTC, datetime, timedelta

import pytest
import sqlalchemy as sa
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.api.schemas_submission import (
    SubmissionVersionListResponse,
    SubmissionVersionResponse,
    VersionComparisonResponse,
)
from app.core.config import get_settings
from app.main import app
from app.models.analysis import AnalysisJob
from app.models.assignment import Assignment
from app.models.enums import (
    AssignmentStatus,
    DocumentStatus,
    ReviewDecisionType,
    UserRole,
)
from app.models.review import PublishedResultVersion
from app.models.submission import DocumentVersion
from app.services.review import compare_submission_versions, list_submission_versions
from app.services.submission import initiate_upload
from tests.test_t011_review_workspace import _actor, _cleanup_graph, _ids, _seed_graph

requires_database = pytest.mark.skipif(
    os.environ.get("RUN_DATABASE_TESTS") != "1",
    reason="Database integration tests require RUN_DATABASE_TESTS=1",
)


class _Storage:
    expiry_seconds = 300

    @staticmethod
    def create_presigned_post(key: str, _limit: int) -> dict[str, object]:
        return {
            "url": "http://localhost:9000/docgrading",
            "fields": {"key": key},
        }


def _snapshot(
    ids: dict[str, uuid.UUID],
    *,
    finding_id: uuid.UUID,
    comment: str,
    score: str,
) -> dict[str, object]:
    return {
        "comment": comment,
        "findings": [
            {
                "criterion_version_id": str(ids["criterion"]),
                "finding_id": str(finding_id),
                "score": score,
                "description": "Published finding",
                "suggestion": "Published suggestion",
                "decision": "ACCEPT",
                "evidence_count": 1,
                "evidence": [
                    {
                        "document_ir_id": str(ids["document_ir"]),
                        "element_id": "paragraph-1",
                        "page_number": 1,
                        "bbox": {
                            "x0": 10,
                            "top": 20,
                            "x1": 100,
                            "bottom": 40,
                        },
                    }
                ],
            }
        ],
    }


def test_t015_routes_and_response_contract() -> None:
    schema = app.openapi()
    versions = schema["paths"]["/api/v1/submissions/{submission_id}/versions"]["get"]
    version_parameters = {
        parameter["name"]: parameter for parameter in versions["parameters"]
    }
    assert version_parameters["page"]["schema"]["default"] == 1
    assert version_parameters["page_size"]["schema"] == {
        "type": "integer",
        "maximum": 100,
        "minimum": 1,
        "default": 50,
        "title": "Page Size",
    }
    assert versions["responses"]["200"]["content"]["application/json"]["schema"] == {
        "$ref": "#/components/schemas/SubmissionVersionListResponse"
    }
    compare = schema["paths"]["/api/v1/submissions/{submission_id}/versions/compare"][
        "get"
    ]
    parameters = {parameter["name"]: parameter for parameter in compare["parameters"]}
    assert parameters["left_version_id"]["required"] is True
    assert parameters["right_version_id"]["required"] is True
    assert set(SubmissionVersionResponse.model_fields) == {
        "document_version_id",
        "version_number",
        "created_at",
        "processing_status",
        "publication_status",
        "published_result_id",
        "published_at",
    }
    assert set(SubmissionVersionListResponse.model_fields) == {
        "items",
        "page",
        "page_size",
        "total",
    }
    assert set(VersionComparisonResponse.model_fields) == {
        "submission_id",
        "left",
        "right",
    }


async def _version_history_scenario() -> None:
    ids = _ids()
    engine = create_async_engine(get_settings().database_url, poolclass=NullPool)
    connection = await engine.connect()
    transaction = await connection.begin()
    session = AsyncSession(bind=connection, expire_on_commit=False)
    try:
        await _seed_graph(connection, ids)
        now = datetime.now(UTC)
        student = _actor(ids["student_1"], "Student 1", UserRole.STUDENT)
        other_student = _actor(ids["student_2"], "Student 2", UserRole.STUDENT)
        owner = _actor(ids["teacher"], "Teacher A", UserRole.TEACHER)
        other_teacher = _actor(ids["other_teacher"], "Teacher B", UserRole.TEACHER)
        admin = _actor(ids["admin"], "Admin", UserRole.ADMIN, UserRole.TEACHER)
        owner_with_teacher_role = _actor(
            ids["student_1"], "Student 1", UserRole.TEACHER, UserRole.STUDENT
        )

        assignment = await session.get(Assignment, ids["assignment"])
        first = await session.get(DocumentVersion, ids["document_1"])
        assert assignment is not None
        assert first is not None
        first.status = DocumentStatus.PUBLISHED
        first.approved_at = now
        first.approved_by_user_id = ids["teacher"]
        first_snapshot = _snapshot(
            ids,
            finding_id=ids["finding"],
            comment="Version one comment",
            score="80.00",
        )
        first_finding = first_snapshot["findings"][0]
        assert isinstance(first_finding, dict)
        first_finding.pop("decision")
        first_finding.pop("evidence_count")
        first.approved_snapshot = first_snapshot
        first_result = PublishedResultVersion(
            id=uuid.uuid4(),
            document_version_id=first.id,
            version_number=1,
            approved_by_user_id=ids["teacher"],
            published_by_user_id=ids["teacher"],
            approved_at=now,
            published_at=now,
            snapshot=first_snapshot,
        )
        session.add(first_result)
        await session.flush()

        upload = {
            "assignment_id": assignment.id,
            "user": student,
            "filename": "second.pdf",
            "content_type": "application/pdf",
            "size_bytes": 200,
            "sha256": "a" * 64,
            "storage": _Storage(),
        }
        assignment.due_at = now - timedelta(seconds=1)
        await session.flush()
        with pytest.raises(HTTPException) as late:
            await initiate_upload(session, idempotency_key="late", **upload)
        assert late.value.status_code == 409

        assignment.due_at = now + timedelta(days=1)
        assignment.status = AssignmentStatus.CLOSED
        assignment.closed_at = now
        await session.flush()
        with pytest.raises(HTTPException) as closed:
            await initiate_upload(session, idempotency_key="closed", **upload)
        assert closed.value.status_code == 409
        assert (
            await session.scalar(
                sa.select(sa.func.count(DocumentVersion.id)).where(
                    DocumentVersion.submission_id == ids["submission_1"]
                )
            )
            == 1
        )

        assignment.status = AssignmentStatus.OPEN
        assignment.closed_at = None
        second, _ = await initiate_upload(
            session,
            idempotency_key="second-version",
            **upload,
        )
        assert second.version_number == 2
        assert second.previous_version_id == first.id
        await session.flush()

        stored_first = (
            await session.execute(
                sa.select(
                    DocumentVersion.status,
                    PublishedResultVersion.snapshot,
                    PublishedResultVersion.published_at,
                )
                .join(
                    PublishedResultVersion,
                    PublishedResultVersion.document_version_id == DocumentVersion.id,
                )
                .where(DocumentVersion.id == first.id)
            )
        ).one()
        assert stored_first.status is DocumentStatus.PUBLISHED
        assert stored_first.snapshot == first_snapshot
        assert stored_first.published_at == now
        assert (
            await session.scalar(
                sa.select(sa.func.count(AnalysisJob.id)).where(
                    AnalysisJob.document_version_id == first.id
                )
            )
            == 1
        )

        second_snapshot = _snapshot(
            ids,
            finding_id=uuid.uuid4(),
            comment="Version two comment",
            score="90.00",
        )
        rejected_finding_id = uuid.uuid4()
        second_snapshot["rejected_findings"] = [
            {
                "criterion_version_id": str(ids["criterion"]),
                "finding_id": str(rejected_finding_id),
                "score": None,
                "decision": "REJECT",
                "evidence_count": 0,
                "evidence": [],
            }
        ]
        second.status = DocumentStatus.PUBLISHED
        second.approved_at = now + timedelta(seconds=1)
        second.approved_by_user_id = ids["teacher"]
        second.approved_snapshot = second_snapshot
        second_result = PublishedResultVersion(
            id=uuid.uuid4(),
            document_version_id=second.id,
            version_number=1,
            approved_by_user_id=ids["teacher"],
            published_by_user_id=ids["teacher"],
            approved_at=second.approved_at,
            published_at=now + timedelta(seconds=1),
            snapshot=second_snapshot,
        )
        failed = DocumentVersion(
            id=uuid.uuid4(),
            submission_id=ids["submission_1"],
            version_number=3,
            previous_version_id=second.id,
            storage_key=f"private/{uuid.uuid4()}",
            original_filename="failed.pdf",
            content_type="application/pdf",
            size_bytes=200,
            sha256="b" * 64,
            status=DocumentStatus.PROCESSING_FAILED,
            failure_code="INTERNAL_FAILURE",
            failure_detail="secret internal detail",
        )
        session.add_all([second_result, failed])
        await session.flush()

        student_versions = await list_submission_versions(
            session, submission_id=ids["submission_1"], user=student
        )
        assert student_versions.model_dump(exclude={"items"}) == {
            "page": 1,
            "page_size": 50,
            "total": 3,
        }
        assert [item.version_number for item in student_versions.items] == [1, 2, 3]
        assert [item.processing_status for item in student_versions.items] == [
            "AWAITING_REVIEW",
            "AWAITING_REVIEW",
            "ERROR",
        ]
        assert [item.publication_status for item in student_versions.items] == [
            "PUBLISHED",
            "PUBLISHED",
            None,
        ]
        assert "secret internal detail" not in str(
            [item.model_dump() for item in student_versions.items]
        )
        second_page = await list_submission_versions(
            session,
            submission_id=ids["submission_1"],
            user=student,
            page=2,
            page_size=2,
        )
        assert second_page.total == 3
        assert [item.version_number for item in second_page.items] == [3]

        comparison = await compare_submission_versions(
            session,
            submission_id=ids["submission_1"],
            left_version_id=first.id,
            right_version_id=second.id,
            user=student,
        )
        assert comparison.submission_id == ids["submission_1"]
        assert comparison.left.comment == "Version one comment"
        assert comparison.left.findings[0].score == 80
        assert comparison.left.findings[0].decision is None
        assert comparison.left.findings[0].evidence_count == 1
        assert comparison.right.comment == "Version two comment"
        assert comparison.right.findings[0].score == 90
        assert [finding.finding_id for finding in comparison.right.findings] == [
            uuid.UUID(str(second_snapshot["findings"][0]["finding_id"]))
        ]
        payload = str(comparison.model_dump())
        assert "secret internal detail" not in payload
        assert "private/" not in payload
        assert "SENSITIVE PDF TEXT" not in payload

        for privileged in (owner, admin):
            privileged_comparison = await compare_submission_versions(
                session,
                submission_id=ids["submission_1"],
                left_version_id=first.id,
                right_version_id=second.id,
                user=privileged,
            )
            assert privileged_comparison.left == comparison.left
            assert len(privileged_comparison.right.findings) == 2
            rejected = next(
                finding
                for finding in privileged_comparison.right.findings
                if finding.finding_id == rejected_finding_id
            )
            assert rejected.decision is ReviewDecisionType.REJECT
            assert rejected.score is None
            assert rejected.evidence_count == 0

        for denied in (other_student, other_teacher, owner_with_teacher_role):
            with pytest.raises(HTTPException) as denied_error:
                await compare_submission_versions(
                    session,
                    submission_id=ids["submission_1"],
                    left_version_id=first.id,
                    right_version_id=second.id,
                    user=denied,
                )
            assert denied_error.value.status_code == 404

        with pytest.raises(HTTPException) as hidden_error:
            await compare_submission_versions(
                session,
                submission_id=ids["submission_1"],
                left_version_id=second.id,
                right_version_id=failed.id,
                user=student,
            )
        assert hidden_error.value.status_code == 404

        malformed_version = DocumentVersion(
            id=uuid.uuid4(),
            submission_id=ids["submission_1"],
            version_number=4,
            previous_version_id=failed.id,
            storage_key=f"private/{uuid.uuid4()}",
            original_filename="malformed.pdf",
            content_type="application/pdf",
            size_bytes=200,
            sha256="e" * 64,
            status=DocumentStatus.PUBLISHED,
            approved_at=now,
            approved_by_user_id=ids["teacher"],
            approved_snapshot={},
        )
        malformed_snapshot = {
            "comment": "Malformed score comment",
            "findings": [
                {
                    **first_result.snapshot["findings"][0],
                    "score": {"malformed": True},
                },
                {
                    "criterion_version_id": str(ids["criterion"]),
                    "finding_id": str(uuid.uuid4()),
                    "decision": "ACCEPT",
                    "evidence_count": 0,
                },
            ],
        }
        session.add_all(
            [
                malformed_version,
                PublishedResultVersion(
                    id=uuid.uuid4(),
                    document_version_id=malformed_version.id,
                    version_number=1,
                    approved_by_user_id=ids["teacher"],
                    published_by_user_id=ids["teacher"],
                    approved_at=now,
                    published_at=now,
                    snapshot=malformed_snapshot,
                ),
            ]
        )
        await session.flush()
        malformed_scores = await compare_submission_versions(
            session,
            submission_id=ids["submission_1"],
            left_version_id=first.id,
            right_version_id=malformed_version.id,
            user=student,
        )
        assert [finding.score for finding in malformed_scores.right.findings] == [
            None,
            None,
        ]
    finally:
        await session.close()
        await transaction.rollback()
        await connection.close()
        await engine.dispose()


@requires_database
def test_t015_resubmit_history_comparison_and_privacy() -> None:
    asyncio.run(_version_history_scenario())


async def _concurrent_resubmit_scenario() -> None:
    ids = _ids()
    engine = create_async_engine(get_settings().database_url, poolclass=NullPool)
    setup_complete = False
    try:
        async with engine.begin() as connection:
            await _seed_graph(connection, ids)
        setup_complete = True
        sessions = async_sessionmaker(engine, expire_on_commit=False)
        student = _actor(ids["student_1"], "Student 1", UserRole.STUDENT)
        start = asyncio.Event()

        async def submit(key: str) -> uuid.UUID:
            async with sessions() as session:
                await start.wait()
                version, _ = await initiate_upload(
                    session,
                    assignment_id=ids["assignment"],
                    user=student,
                    idempotency_key=key,
                    filename="same-resubmit.pdf",
                    content_type="application/pdf",
                    size_bytes=200,
                    sha256="c" * 64,
                    storage=_Storage(),
                )
                await session.commit()
                return version.id

        tasks = [
            asyncio.create_task(submit("resubmit-one")),
            asyncio.create_task(submit("resubmit-two")),
        ]
        start.set()
        version_ids = await asyncio.gather(*tasks)
        assert version_ids[0] == version_ids[1]

        async with engine.connect() as connection:
            versions = (
                await connection.execute(
                    sa.text(
                        "SELECT id, version_number, previous_version_id "
                        "FROM public.document_versions "
                        "WHERE submission_id = :submission "
                        "ORDER BY version_number"
                    ),
                    {"submission": ids["submission_1"]},
                )
            ).all()
            assert [
                (row.version_number, row.previous_version_id) for row in versions
            ] == [
                (1, None),
                (2, ids["document_1"]),
            ]
    finally:
        if setup_complete:
            async with engine.begin() as connection:
                await connection.execute(
                    sa.text("SET LOCAL session_replication_role = 'replica'")
                )
                await connection.execute(
                    sa.text(
                        "DELETE FROM public.document_versions "
                        "WHERE submission_id = :submission AND id != :first"
                    ),
                    {
                        "submission": ids["submission_1"],
                        "first": ids["document_1"],
                    },
                )
                await _cleanup_graph(connection, ids)
        await engine.dispose()


@requires_database
def test_t015_concurrent_duplicate_resubmit_creates_one_next_version() -> None:
    asyncio.run(_concurrent_resubmit_scenario())


async def _student_unpublish_race_scenario() -> None:
    ids = _ids()
    engine = create_async_engine(get_settings().database_url, poolclass=NullPool)
    setup_complete = False
    second_version_id = uuid.uuid4()
    try:
        now = datetime.now(UTC)
        snapshot = _snapshot(
            ids,
            finding_id=ids["finding"],
            comment="Published comment",
            score="80.00",
        )
        async with engine.begin() as connection:
            await _seed_graph(connection, ids)
            await connection.execute(
                sa.update(DocumentVersion)
                .where(DocumentVersion.id == ids["document_1"])
                .values(
                    status=DocumentStatus.PUBLISHED,
                    approved_at=now,
                    approved_by_user_id=ids["teacher"],
                    approved_snapshot=snapshot,
                )
            )
            await connection.execute(
                sa.insert(PublishedResultVersion).values(
                    id=uuid.uuid4(),
                    document_version_id=ids["document_1"],
                    version_number=1,
                    approved_by_user_id=ids["teacher"],
                    published_by_user_id=ids["teacher"],
                    approved_at=now,
                    published_at=now,
                    snapshot=snapshot,
                )
            )
            await connection.execute(
                sa.insert(DocumentVersion).values(
                    id=second_version_id,
                    submission_id=ids["submission_1"],
                    version_number=2,
                    previous_version_id=ids["document_1"],
                    storage_key=f"private/{second_version_id}",
                    original_filename="second.pdf",
                    content_type="application/pdf",
                    size_bytes=200,
                    sha256="d" * 64,
                    status=DocumentStatus.PUBLISHED,
                    approved_at=now,
                    approved_by_user_id=ids["teacher"],
                    approved_snapshot=snapshot,
                )
            )
            await connection.execute(
                sa.insert(PublishedResultVersion).values(
                    id=uuid.uuid4(),
                    document_version_id=second_version_id,
                    version_number=1,
                    approved_by_user_id=ids["teacher"],
                    published_by_user_id=ids["teacher"],
                    approved_at=now,
                    published_at=now,
                    snapshot=snapshot,
                )
            )
        setup_complete = True
        normal_sessions = async_sessionmaker(engine, expire_on_commit=False)
        unpublish_committed = False

        class RaceSession(AsyncSession):
            async def execute(self, statement, *args, **kwargs):
                nonlocal unpublish_committed
                if not unpublish_committed and "published_result_versions" in str(
                    statement
                ):
                    async with normal_sessions() as other:
                        await other.execute(
                            sa.update(DocumentVersion)
                            .where(DocumentVersion.id == ids["document_1"])
                            .values(status=DocumentStatus.APPROVED)
                        )
                        await other.commit()
                    unpublish_committed = True
                return await super().execute(statement, *args, **kwargs)

        racing_sessions = async_sessionmaker(
            engine, class_=RaceSession, expire_on_commit=False
        )
        student = _actor(ids["student_1"], "Student 1", UserRole.STUDENT)
        async with racing_sessions() as session:
            with pytest.raises(HTTPException) as hidden:
                await compare_submission_versions(
                    session,
                    submission_id=ids["submission_1"],
                    left_version_id=ids["document_1"],
                    right_version_id=second_version_id,
                    user=student,
                )
            assert hidden.value.status_code == 404
        assert unpublish_committed is True
    finally:
        if setup_complete:
            async with engine.begin() as connection:
                await connection.execute(
                    sa.text("SET LOCAL session_replication_role = 'replica'")
                )
                await connection.execute(
                    sa.delete(PublishedResultVersion).where(
                        PublishedResultVersion.document_version_id.in_(
                            [ids["document_1"], second_version_id]
                        )
                    )
                )
                await connection.execute(
                    sa.delete(DocumentVersion).where(
                        DocumentVersion.id == second_version_id
                    )
                )
                await _cleanup_graph(connection, ids)
        await engine.dispose()


@requires_database
def test_t015_student_compare_cannot_race_unpublish() -> None:
    asyncio.run(_student_unpublish_race_scenario())
