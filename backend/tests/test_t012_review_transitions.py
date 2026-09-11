from __future__ import annotations

import asyncio
import os
import uuid
from datetime import UTC, datetime
from decimal import Decimal

import pytest
from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.pool import NullPool

from app.api.schemas_submission import PublishedResultResponse
from app.core.config import get_settings
from app.models.enums import UserRole
from app.services.review import (
    approve_document_version,
    bulk_publish_document_versions,
    get_student_published_result,
    publish_document_version,
    unpublish_result,
)
from tests.test_t011_review_workspace import _actor, _ids, _seed_graph

pytestmark = pytest.mark.skipif(
    os.environ.get("RUN_DATABASE_TESTS") != "1",
    reason="Database integration tests require RUN_DATABASE_TESTS=1",
)


async def _transition_scenario() -> None:
    ids = _ids()
    engine = create_async_engine(get_settings().database_url, poolclass=NullPool)
    connection = await engine.connect()
    transaction = await connection.begin()
    session = AsyncSession(bind=connection, expire_on_commit=False)
    try:
        await _seed_graph(connection, ids)
        owner = _actor(ids["teacher"], "Teacher A", UserRole.TEACHER)
        student = _actor(ids["student_1"], "Student 1", UserRole.STUDENT)
        other_student = _actor(ids["student_2"], "Student 2", UserRole.STUDENT)
        admin = _actor(ids["admin"], "Teacher Admin", UserRole.ADMIN, UserRole.TEACHER)

        with pytest.raises(HTTPException) as missing:
            await get_student_published_result(
                session, submission_id=ids["submission_1"], user=student
            )
        assert missing.value.status_code == 404

        with pytest.raises(HTTPException) as direct_publish:
            await publish_document_version(
                session,
                version_id=ids["document_1"],
                user=owner,
                idempotency_key="publish-before-approval",
                reason="too early",
            )
        assert direct_publish.value.status_code == 409

        now = datetime.now(UTC)
        rejected_finding_id = uuid.uuid4()
        await connection.execute(
            text(
                "INSERT INTO public.findings "
                "(id, analysis_job_id, criterion_version_id, severity, "
                "description, suggestion, proposed_score) "
                "VALUES (:id, :job, :criterion, 'MINOR', "
                "'Internal rejected finding', 'Do not expose', 10)"
            ),
            {
                "id": rejected_finding_id,
                "job": ids["job"],
                "criterion": ids["criterion"],
            },
        )
        await connection.execute(
            text(
                "INSERT INTO public.review_drafts "
                "(id, submission_id, document_version_id, reviewer_user_id, "
                "revision, comment) VALUES "
                "(:id, :submission, :document, :user, 2, :comment)"
            ),
            {
                "id": uuid.uuid4(),
                "submission": ids["submission_1"],
                "document": ids["document_1"],
                "user": ids["teacher"],
                "comment": "Public teacher comment",
            },
        )
        draft_id = (
            await connection.execute(
                text(
                    "SELECT id FROM public.review_drafts "
                    "WHERE document_version_id = :document"
                ),
                {"document": ids["document_1"]},
            )
        ).scalar_one()
        await connection.execute(
            text(
                "INSERT INTO public.review_decisions "
                "(id, review_draft_id, finding_id, decision) "
                "VALUES (:id, :draft, :finding, 'ACCEPT'::public.review_decision_type)"
            ),
            {"id": uuid.uuid4(), "draft": draft_id, "finding": ids["finding"]},
        )
        await connection.execute(
            text(
                "INSERT INTO public.review_decisions "
                "(id, review_draft_id, finding_id, decision, reason) "
                "VALUES (:id, :draft, :finding, "
                "'REJECT'::public.review_decision_type, :reason)"
            ),
            {
                "id": uuid.uuid4(),
                "draft": draft_id,
                "finding": rejected_finding_id,
                "reason": "Internal rejection reason",
            },
        )

        approved = await approve_document_version(
            session,
            version_id=ids["document_1"],
            user=owner,
            idempotency_key="approve-one",
        )
        assert approved.status == "APPROVED"
        approve_audit = (
            await connection.execute(
                text(
                    "SELECT actor_user_id, reason, before, after "
                    "FROM public.audit_events "
                    "WHERE resource_id = :document AND action = 'APPROVE'"
                ),
                {"document": ids["document_1"]},
            )
        ).one()
        assert approve_audit.actor_user_id == ids["teacher"]
        assert approve_audit.reason == "Teacher approved review snapshot"
        assert approve_audit.before == {"status": "AWAITING_REVIEW"}
        assert approve_audit.after["status"] == "APPROVED"
        with pytest.raises(HTTPException) as still_hidden:
            await get_student_published_result(
                session, submission_id=ids["submission_1"], user=student
            )
        assert still_hidden.value.status_code == 404

        published = await publish_document_version(
            session,
            version_id=ids["document_1"],
            user=owner,
            idempotency_key="publish-one",
            reason="Ready for students",
        )
        assert isinstance(published, PublishedResultResponse)
        visible = await get_student_published_result(
            session, submission_id=ids["submission_1"], user=student
        )
        assert set(visible.model_dump()) == {
            "published_result_id",
            "submission_id",
            "document_version_id",
            "version_number",
            "published_at",
            "comment",
            "findings",
        }
        assert visible.findings[0].score == Decimal("80.00")
        assert visible.findings[0].description == "Missing required section"
        assert visible.findings[0].suggestion == "Add required section"
        assert visible.findings[0].evidence[0].model_dump() == {
            "document_ir_id": ids["document_ir"],
            "element_id": "paragraph-1",
            "page_number": 1,
            "bbox": {"x0": 10.0, "top": 20.0, "x1": 100.0, "bottom": 40.0},
        }
        assert visible.comment == "Public teacher comment"
        assert visible.findings[0].finding_id == ids["finding"]
        assert set(visible.findings[0].model_dump()) == {
            "criterion_version_id",
            "finding_id",
            "score",
            "description",
            "suggestion",
            "evidence",
        }
        assert set(visible.findings[0].evidence[0].model_dump()) == {
            "document_ir_id",
            "element_id",
            "page_number",
            "bbox",
        }
        payload_text = str(visible.model_dump())
        assert str(rejected_finding_id) not in payload_text
        assert "Internal rejection reason" not in payload_text
        assert "SENSITIVE PDF TEXT" not in payload_text
        assert f"private/{ids['document_1']}" not in payload_text
        with pytest.raises(HTTPException) as wrong_owner:
            await get_student_published_result(
                session,
                submission_id=ids["submission_1"],
                user=other_student,
            )
        assert wrong_owner.value.status_code == 404
        publish_audit = (
            await connection.execute(
                text(
                    "SELECT actor_user_id, reason, before, after "
                    "FROM public.audit_events "
                    "WHERE resource_id = :document AND action = 'PUBLISH' "
                    "ORDER BY occurred_at LIMIT 1"
                ),
                {"document": ids["document_1"]},
            )
        ).one()
        assert publish_audit.actor_user_id == ids["teacher"]
        assert publish_audit.reason == "Ready for students"
        assert publish_audit.before == {"status": "APPROVED"}
        assert publish_audit.after["status"] == "PUBLISHED"
        assert publish_audit.after["published_result_id"] == str(
            published.published_result_id
        )

        replay = await publish_document_version(
            session,
            version_id=ids["document_1"],
            user=owner,
            idempotency_key="publish-one",
            reason="Ready for students",
        )
        assert replay.published_result_id == published.published_result_id
        with pytest.raises(HTTPException) as conflict:
            await publish_document_version(
                session,
                version_id=ids["document_1"],
                user=owner,
                idempotency_key="publish-one",
                reason="Changed reason",
            )
        assert conflict.value.status_code == 409
        published_row_before = (
            await connection.execute(
                text(
                    "SELECT snapshot, published_at "
                    "FROM public.published_result_versions WHERE id = :id"
                ),
                {"id": published.published_result_id},
            )
        ).one()

        unpublished = await unpublish_result(
            session,
            published_result_id=published.published_result_id,
            user=admin,
            idempotency_key="unpublish-one",
            reason="Fix teacher comment",
        )
        assert unpublished.status == "APPROVED"
        published_row_after = (
            await connection.execute(
                text(
                    "SELECT snapshot, published_at "
                    "FROM public.published_result_versions WHERE id = :id"
                ),
                {"id": published.published_result_id},
            )
        ).one()
        assert published_row_after == published_row_before
        unpublish_audit = (
            await connection.execute(
                text(
                    "SELECT actor_user_id, reason, before, after "
                    "FROM public.audit_events "
                    "WHERE resource_id = :document AND action = 'UNPUBLISH'"
                ),
                {"document": ids["document_1"]},
            )
        ).one()
        assert unpublish_audit.actor_user_id == ids["admin"]
        assert unpublish_audit.reason == "Fix teacher comment"
        assert unpublish_audit.before["published_result_id"] == str(
            published.published_result_id
        )
        assert unpublish_audit.after == {
            "published_result_id": str(published.published_result_id),
            "status": "APPROVED",
            "version_number": 1,
        }
        with pytest.raises(HTTPException) as reverted:
            await get_student_published_result(
                session, submission_id=ids["submission_1"], user=student
            )
        assert reverted.value.status_code == 404

        await connection.execute(
            text(
                "UPDATE public.document_versions SET approved_at = :at, "
                "approved_by_user_id = :user, approved_snapshot = '{}'::jsonb "
                "WHERE id = :document"
            ),
            {"at": now, "user": ids["teacher"], "document": ids["document_2"]},
        )
        bulk = await bulk_publish_document_versions(
            session,
            assignment_id=ids["assignment"],
            version_ids=[ids["document_1"], ids["document_2"]],
            user=owner,
            idempotency_key="bulk-one",
            reason="Publish approved set",
        )
        assert len(bulk.results) == 2
        before_failed_bulk = (
            await connection.scalar(
                text(
                    "SELECT count(*) FROM public.published_result_versions "
                    "WHERE document_version_id IN (:one, :three)"
                ),
                {"one": ids["document_1"], "three": ids["document_3"]},
            ),
            await connection.scalar(
                text(
                    "SELECT count(*) FROM public.audit_events "
                    "WHERE resource_id IN (:one, :three) AND action = 'PUBLISH'"
                ),
                {"one": ids["document_1"], "three": ids["document_3"]},
            ),
            await connection.scalar(
                text(
                    "SELECT count(*) FROM public.review_commands "
                    "WHERE idempotency_key = 'bulk-invalid'"
                )
            ),
        )
        with pytest.raises(HTTPException) as rollback:
            async with session.begin_nested():
                await bulk_publish_document_versions(
                    session,
                    assignment_id=ids["assignment"],
                    version_ids=[ids["document_1"], ids["document_3"]],
                    user=owner,
                    idempotency_key="bulk-invalid",
                    reason="Must rollback",
                )
        assert rollback.value.status_code == 409
        status_after = (
            await connection.execute(
                text(
                    "SELECT status::text FROM public.document_versions "
                    "WHERE id = :id"
                ),
                {"id": ids["document_3"]},
            )
        ).scalar_one()
        assert status_after == "PROCESSING_FAILED"
        after_failed_bulk = (
            await connection.scalar(
                text(
                    "SELECT count(*) FROM public.published_result_versions "
                    "WHERE document_version_id IN (:one, :three)"
                ),
                {"one": ids["document_1"], "three": ids["document_3"]},
            ),
            await connection.scalar(
                text(
                    "SELECT count(*) FROM public.audit_events "
                    "WHERE resource_id IN (:one, :three) AND action = 'PUBLISH'"
                ),
                {"one": ids["document_1"], "three": ids["document_3"]},
            ),
            await connection.scalar(
                text(
                    "SELECT count(*) FROM public.review_commands "
                    "WHERE idempotency_key = 'bulk-invalid'"
                )
            ),
        )
        assert after_failed_bulk == before_failed_bulk

        await connection.execute(
            text(
                "INSERT INTO public.document_versions ("
                "id, submission_id, version_number, previous_version_id, "
                "storage_key, original_filename, content_type, size_bytes, "
                "sha256, status, approved_at, approved_by_user_id, approved_snapshot"
                ") SELECT :id, submission_id, 2, id, :storage_key, 'new.pdf', "
                "'application/pdf', 100, :sha256, "
                "'APPROVED'::public.document_status, approved_at, "
                "approved_by_user_id, approved_snapshot "
                "FROM public.document_versions WHERE id = :previous"
            ),
            {
                "id": ids["document_4"],
                "storage_key": f"private/{ids['document_4']}",
                "sha256": "4" * 64,
                "previous": ids["document_1"],
            },
        )
        latest = await publish_document_version(
            session,
            version_id=ids["document_4"],
            user=owner,
            idempotency_key="publish-latest-document",
            reason="Publish latest document",
        )
        assert (
            await get_student_published_result(
                session,
                submission_id=ids["submission_1"],
                user=student,
            )
        ).document_version_id == ids["document_4"]
        await unpublish_result(
            session,
            published_result_id=latest.published_result_id,
            user=admin,
            idempotency_key="unpublish-latest-document",
            reason="Withdraw latest result",
        )
        with pytest.raises(HTTPException) as no_old_fallback:
            await get_student_published_result(
                session,
                submission_id=ids["submission_1"],
                user=student,
            )
        assert no_old_fallback.value.status_code == 404
    finally:
        await transaction.rollback()
        await session.close()
        await connection.close()
        await engine.dispose()


def test_t012_transition_publication_and_rollback_contracts() -> None:
    asyncio.run(_transition_scenario())
