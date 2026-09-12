from __future__ import annotations

import asyncio
import os
import uuid
from datetime import UTC, datetime

import pytest
from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.pool import NullPool

from app.api.schemas_submission import ReviewRequestCreate, ReviewRequestUpdate
from app.core.config import get_settings
from app.models.enums import ReviewRequestStatus, UserRole
from app.services.appeal import (
    create_review_request,
    get_review_request,
    list_review_requests,
    respond_review_request,
)
from tests.test_t011_review_workspace import _actor, _ids, _seed_graph

pytestmark = pytest.mark.skipif(
    os.environ.get("RUN_DATABASE_TESTS") != "1",
    reason="Database integration tests require RUN_DATABASE_TESTS=1",
)


async def _publish_seed(connection, ids: dict[str, uuid.UUID]) -> uuid.UUID:
    result_id = uuid.uuid4()
    await connection.execute(
        text(
            "INSERT INTO public.published_result_versions "
            "(id, document_version_id, version_number, approved_by_user_id, "
            "published_by_user_id, approved_at, published_at, snapshot) "
            "VALUES (:id, :document, 1, :teacher, :teacher, :now, :now, "
            "CAST(:snapshot AS jsonb))"
        ),
        {
            "id": result_id,
            "document": ids["document_1"],
            "teacher": ids["teacher"],
            "now": datetime.now(UTC),
            "snapshot": (
                '{"comment":"public", "findings":[{"criterion_version_id":"'
                f'{ids["criterion"]}'
                '","finding_id":"'
                f'{ids["finding"]}'
                '"}]}'
            ),
        },
    )
    return result_id


async def _workflow() -> None:
    ids = _ids()
    engine = create_async_engine(get_settings().database_url, poolclass=NullPool)
    connection = await engine.connect()
    transaction = await connection.begin()
    session = AsyncSession(bind=connection, expire_on_commit=False)
    try:
        await _seed_graph(connection, ids)
        result_id = await _publish_seed(connection, ids)
        student = _actor(ids["student_1"], "Student 1", UserRole.STUDENT)
        other_student = _actor(ids["student_2"], "Student 2", UserRole.STUDENT)
        owner = _actor(ids["teacher"], "Teacher A", UserRole.TEACHER)
        other_teacher = _actor(ids["other_teacher"], "Teacher B", UserRole.TEACHER)
        admin = _actor(ids["admin"], "Admin", UserRole.ADMIN)
        criterion_id = (
            await connection.execute(
                text(
                    "SELECT criterion_id FROM public.criterion_versions WHERE id = :id"
                ),
                {"id": ids["criterion"]},
            )
        ).scalar_one()
        create = ReviewRequestCreate(
            submission_id=ids["submission_1"],
            criterion_id=criterion_id,
            reason="Explain score",
        )
        with pytest.raises(HTTPException) as unpublished:
            await create_review_request(
                session, published_result_id=result_id, payload=create, user=student
            )
        assert unpublished.value.status_code == 409
        await connection.execute(
            text(
                "UPDATE public.document_versions "
                "SET status = 'PUBLISHED'::public.document_status "
                "WHERE id = :id"
            ),
            {"id": ids["document_1"]},
        )
        document_before = (
            await connection.execute(
                text(
                    "SELECT status, approved_snapshot FROM public.document_versions "
                    "WHERE id = :id"
                ),
                {"id": ids["document_1"]},
            )
        ).one()
        finding_score_before = await connection.scalar(
            text("SELECT proposed_score FROM public.findings WHERE id = :id"),
            {"id": ids["finding"]},
        )
        decisions_before = await connection.scalar(
            text("SELECT count(*) FROM public.review_decisions")
        )
        result_snapshot_before = await connection.scalar(
            text(
                "SELECT snapshot FROM public.published_result_versions WHERE id = :id"
            ),
            {"id": result_id},
        )
        request = await create_review_request(
            session, published_result_id=result_id, payload=create, user=student
        )
        assert request.status is ReviewRequestStatus.OPEN
        assert request.published_result_id == result_id
        assert request.criterion_id == criterion_id and request.finding_id is None
        assert set(request.model_dump()) == set(ReviewRequestResponseFields)
        own_request = await get_review_request(
            session, request_id=request.id, user=student
        )
        assert own_request.model_dump() == request.model_dump()
        with pytest.raises(HTTPException) as foreign_student_read:
            await get_review_request(session, request_id=request.id, user=other_student)
        assert foreign_student_read.value.status_code == 404
        with pytest.raises(HTTPException) as invalid_finding:
            await create_review_request(
                session,
                published_result_id=result_id,
                payload=ReviewRequestCreate(
                    submission_id=ids["submission_1"],
                    finding_id=uuid.uuid4(),
                    reason="Unknown finding",
                ),
                user=student,
            )
        assert invalid_finding.value.status_code == 409
        with pytest.raises(HTTPException) as duplicate:
            await create_review_request(
                session, published_result_id=result_id, payload=create, user=student
            )
        assert duplicate.value.status_code == 409
        with pytest.raises(HTTPException) as foreign_create:
            await create_review_request(
                session,
                published_result_id=result_id,
                payload=ReviewRequestCreate(
                    submission_id=ids["submission_1"],
                    criterion_id=criterion_id,
                    reason="x",
                ),
                user=other_student,
            )
        assert foreign_create.value.status_code == 404

        audit = (
            await connection.execute(
                text(
                    "SELECT actor_user_id, action, reason, before, after "
                    "FROM public.audit_events "
                    "WHERE resource_id = :id AND action = 'OPEN'"
                ),
                {"id": request.id},
            )
        ).one()
        assert audit.actor_user_id == student.id
        assert audit.reason == "Explain score"
        assert audit.before == {"status": None}
        assert audit.after["status"] == "OPEN"

        resolved = await respond_review_request(
            session,
            request_id=request.id,
            payload=ReviewRequestUpdate(
                status=ReviewRequestStatus.RESOLVED, response="Reviewed"
            ),
            user=owner,
        )
        assert resolved.status is ReviewRequestStatus.RESOLVED
        student_view = await get_review_request(
            session, request_id=request.id, user=student
        )
        assert student_view.status is ReviewRequestStatus.RESOLVED
        assert student_view.response == "Reviewed"
        with pytest.raises(HTTPException) as replay:
            await respond_review_request(
                session,
                request_id=request.id,
                payload=ReviewRequestUpdate(
                    status=ReviewRequestStatus.REJECTED, response="Again"
                ),
                user=owner,
            )
        assert replay.value.status_code == 409

        finding_request = await create_review_request(
            session,
            published_result_id=result_id,
            payload=ReviewRequestCreate(
                submission_id=ids["submission_1"],
                finding_id=ids["finding"],
                reason="Finding",
            ),
            user=student,
        )
        assert finding_request.finding_id == ids["finding"]
        assert finding_request.published_result_id == result_id
        assert finding_request.criterion_id is None
        with pytest.raises(HTTPException) as foreign_list:
            await list_review_requests(
                session,
                course_id=ids["course"],
                user=other_teacher,
                status_filter=None,
                page=1,
                page_size=50,
            )
        assert foreign_list.value.status_code == 404
        with pytest.raises(HTTPException) as foreign_read:
            await get_review_request(
                session, request_id=finding_request.id, user=other_teacher
            )
        assert foreign_read.value.status_code == 404
        with pytest.raises(HTTPException) as foreign_response:
            await respond_review_request(
                session,
                request_id=finding_request.id,
                payload=ReviewRequestUpdate(
                    status=ReviewRequestStatus.REJECTED,
                    response="Foreign",
                ),
                user=other_teacher,
            )
        assert foreign_response.value.status_code == 404
        with pytest.raises(HTTPException) as student_response:
            await respond_review_request(
                session,
                request_id=finding_request.id,
                payload=ReviewRequestUpdate(
                    status=ReviewRequestStatus.REJECTED, response="No"
                ),
                user=student,
            )
        assert student_response.value.status_code == 403
        teacher_resolved = await list_review_requests(
            session,
            course_id=ids["course"],
            user=owner,
            status_filter=ReviewRequestStatus.RESOLVED,
            page=1,
            page_size=50,
        )
        assert teacher_resolved.total == 1
        with pytest.raises(HTTPException) as student_list:
            await list_review_requests(
                session,
                course_id=ids["course"],
                user=student,
                status_filter=None,
                page=1,
                page_size=50,
            )
        assert student_list.value.status_code == 403
        listed = await list_review_requests(
            session,
            course_id=ids["course"],
            user=admin,
            status_filter=ReviewRequestStatus.OPEN,
            page=1,
            page_size=50,
        )
        assert listed.total == 1
        rejected = await respond_review_request(
            session,
            request_id=finding_request.id,
            payload=ReviewRequestUpdate(
                status=ReviewRequestStatus.REJECTED, response="Rejected"
            ),
            user=admin,
        )
        assert rejected.status is ReviewRequestStatus.REJECTED
        document_after = (
            await connection.execute(
                text(
                    "SELECT status, approved_snapshot FROM public.document_versions "
                    "WHERE id = :id"
                ),
                {"id": ids["document_1"]},
            )
        ).one()
        result_snapshot_after = await connection.scalar(
            text(
                "SELECT snapshot FROM public.published_result_versions WHERE id = :id"
            ),
            {"id": result_id},
        )
        assert document_after == document_before
        assert result_snapshot_after == result_snapshot_before
        assert (
            await connection.scalar(
                text("SELECT proposed_score FROM public.findings WHERE id = :id"),
                {"id": ids["finding"]},
            )
            == finding_score_before
        )
        assert (
            await connection.scalar(
                text("SELECT count(*) FROM public.review_decisions")
            )
            == decisions_before
        )
        payload_text = str(
            [request.model_dump(), resolved.model_dump(), rejected.model_dump()]
        )
        assert "SENSITIVE PDF TEXT" not in payload_text
        assert f"private/{ids['document_1']}" not in payload_text

        resolve_audit = (
            await connection.execute(
                text(
                    "SELECT actor_user_id, reason, before, after "
                    "FROM public.audit_events "
                    "WHERE resource_id = :id AND action = 'RESOLVE'"
                ),
                {"id": request.id},
            )
        ).one()
        assert resolve_audit.actor_user_id == owner.id
        assert resolve_audit.reason == "Reviewed"
        assert resolve_audit.before["status"] == "OPEN"
        assert resolve_audit.after["status"] == "RESOLVED"
        assert resolve_audit.after["responded_by_user_id"] == str(owner.id)

        reject_audit = (
            await connection.execute(
                text(
                    "SELECT actor_user_id, reason, before, after "
                    "FROM public.audit_events "
                    "WHERE resource_id = :id AND action = 'REJECT'"
                ),
                {"id": finding_request.id},
            )
        ).one()
        assert reject_audit.actor_user_id == admin.id
        assert reject_audit.reason == "Rejected"
        assert reject_audit.before["status"] == "OPEN"
        assert reject_audit.after["status"] == "REJECTED"
        assert reject_audit.after["responded_by_user_id"] == str(admin.id)

        archive_open_request = await create_review_request(
            session,
            published_result_id=result_id,
            payload=create,
            user=student,
        )

        await connection.execute(
            text(
                "UPDATE public.assignments "
                "SET status = 'ARCHIVED'::public.assignment_status, closed_at = now() "
                "WHERE id = :id"
            ),
            {"id": ids["assignment"]},
        )
        with pytest.raises(HTTPException) as archived_assignment:
            await create_review_request(
                session,
                published_result_id=result_id,
                payload=create,
                user=student,
            )
        assert archived_assignment.value.status_code == 409
        with pytest.raises(HTTPException) as archived_assignment_response:
            await respond_review_request(
                session,
                request_id=archive_open_request.id,
                payload=ReviewRequestUpdate(
                    status=ReviewRequestStatus.RESOLVED,
                    response="Too late",
                ),
                user=owner,
            )
        assert archived_assignment_response.value.status_code == 409
        await connection.execute(
            text(
                "UPDATE public.assignments "
                "SET status = 'OPEN'::public.assignment_status, closed_at = NULL "
                "WHERE id = :id"
            ),
            {"id": ids["assignment"]},
        )
        await connection.execute(
            text(
                "UPDATE public.courses "
                "SET status = 'ARCHIVED'::public.course_status WHERE id = :id"
            ),
            {"id": ids["course"]},
        )
        with pytest.raises(HTTPException) as archived_course:
            await create_review_request(
                session,
                published_result_id=result_id,
                payload=create,
                user=student,
            )
        assert archived_course.value.status_code == 409
        with pytest.raises(HTTPException) as archived_course_response:
            await respond_review_request(
                session,
                request_id=archive_open_request.id,
                payload=ReviewRequestUpdate(
                    status=ReviewRequestStatus.REJECTED,
                    response="Too late",
                ),
                user=admin,
            )
        assert archived_course_response.value.status_code == 409
    finally:
        await transaction.rollback()
        await session.close()
        await connection.close()
        await engine.dispose()


ReviewRequestResponseFields = {
    "id",
    "published_result_id",
    "submission_id",
    "student_id",
    "criterion_id",
    "finding_id",
    "status",
    "reason",
    "response",
    "responded_by_user_id",
    "responded_at",
    "created_at",
    "updated_at",
}


def test_t016_real_postgresql_workflow_and_security() -> None:
    asyncio.run(_workflow())
