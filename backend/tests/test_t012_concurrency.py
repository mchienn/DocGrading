from __future__ import annotations

import asyncio
import os
import uuid

import pytest
from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.core.config import get_settings
from app.models.enums import UserRole
from app.services import review as review_service
from tests.test_t011_review_workspace import _actor, _cleanup_graph, _ids, _seed_graph

pytestmark = pytest.mark.skipif(
    os.environ.get("RUN_DATABASE_TESTS") != "1",
    reason="Database integration tests require RUN_DATABASE_TESTS=1",
)


async def _race_scenario(monkeypatch: pytest.MonkeyPatch) -> None:
    ids = _ids()
    engine = create_async_engine(get_settings().database_url, poolclass=NullPool)
    try:
        async with engine.begin() as connection:
            await _seed_graph(connection, ids)
            draft_id = uuid.uuid4()
            await connection.execute(
                text(
                    "INSERT INTO public.review_drafts "
                    "(id, submission_id, document_version_id, reviewer_user_id, "
                    "revision, comment) VALUES "
                    "(:id, :submission, :document, :user, 2, '')"
                ),
                {
                    "id": draft_id,
                    "submission": ids["submission_1"],
                    "document": ids["document_1"],
                    "user": ids["teacher"],
                },
            )
            await connection.execute(
                text(
                    "INSERT INTO public.review_decisions "
                    "(id, review_draft_id, finding_id, decision) "
                    "VALUES (:id, :draft, :finding, "
                    "'ACCEPT'::public.review_decision_type)"
                ),
                {
                    "id": uuid.uuid4(),
                    "draft": draft_id,
                    "finding": ids["finding"],
                },
            )

        factory = async_sessionmaker(engine, expire_on_commit=False)
        teacher = _actor(ids["teacher"], "Teacher A", UserRole.TEACHER)
        admin = _actor(ids["admin"], "Admin", UserRole.ADMIN, UserRole.TEACHER)
        lock_barrier = asyncio.Barrier(2)
        original_locked_document_context = review_service._locked_document_context

        async def synchronized_document_lock(db, version_id, user):
            await lock_barrier.wait()
            return await original_locked_document_context(db, version_id, user)

        monkeypatch.setattr(
            review_service,
            "_locked_document_context",
            synchronized_document_lock,
        )

        async def approve_race(actor, key: str) -> tuple[str, int | None]:
            async with factory() as session:
                try:
                    await review_service.approve_document_version(
                        session,
                        version_id=ids["document_1"],
                        user=actor,
                        idempotency_key=key,
                    )
                    await session.commit()
                    return "ok", None
                except HTTPException as error:
                    await session.rollback()
                    return "error", error.status_code

        outcomes = await asyncio.gather(
            approve_race(teacher, "approve-teacher"),
            approve_race(admin, "approve-admin"),
        )
        assert sorted(outcomes) == [("error", 409), ("ok", None)]

        async with engine.connect() as connection:
            assert (
                await connection.scalar(
                    text(
                        "SELECT count(*) FROM public.audit_events "
                        "WHERE resource_id = :resource AND action = 'APPROVE'"
                    ),
                    {"resource": ids["document_1"]},
                )
                == 1
            )
            assert (
                await connection.scalar(
                    text(
                        "SELECT count(*) FROM public.review_commands "
                        "WHERE action = 'APPROVE'"
                    )
                )
                == 1
            )

        async def publish_race(actor, key: str) -> tuple[str, int | None]:
            async with factory() as session:
                try:
                    await review_service.publish_document_version(
                        session,
                        version_id=ids["document_1"],
                        user=actor,
                        idempotency_key=key,
                        reason="Concurrent publish",
                    )
                    await session.commit()
                    return "ok", None
                except HTTPException as error:
                    await session.rollback()
                    return "error", error.status_code

        publish_outcomes = await asyncio.gather(
            publish_race(teacher, "publish-teacher"),
            publish_race(admin, "publish-admin"),
        )
        assert sorted(publish_outcomes) == [("error", 409), ("ok", None)]
        async with engine.connect() as connection:
            assert (
                await connection.scalar(
                    text(
                        "SELECT count(*) FROM public.published_result_versions "
                        "WHERE document_version_id = :document"
                    ),
                    {"document": ids["document_1"]},
                )
                == 1
            )
            assert (
                await connection.scalar(
                    text(
                        "SELECT count(*) FROM public.audit_events "
                        "WHERE resource_id = :resource AND action = 'PUBLISH'"
                    ),
                    {"resource": ids["document_1"]},
                )
                == 1
            )

        async with engine.begin() as connection:
            await connection.execute(
                text(
                    "UPDATE public.document_versions SET approved_at = now(), "
                    "approved_by_user_id = :teacher, approved_snapshot = '{}'::jsonb "
                    "WHERE id = :document"
                ),
                {"teacher": ids["teacher"], "document": ids["document_2"]},
            )
        blocker = await engine.connect()
        blocker_transaction = await blocker.begin()
        try:
            await blocker.execute(
                text(
                    "SELECT id FROM public.submissions WHERE id = :submission "
                    "FOR UPDATE"
                ),
                {"submission": ids["submission_3"]},
            )
            async with factory() as session:
                await session.execute(text("SET LOCAL lock_timeout = '250ms'"))
                bulk = await review_service.bulk_publish_document_versions(
                    session,
                    assignment_id=ids["assignment"],
                    version_ids=[ids["document_2"]],
                    user=teacher,
                    idempotency_key="bulk-lock-scope",
                    reason="Publish requested submission",
                )
                await session.commit()
            assert len(bulk.results) == 1
        finally:
            await blocker_transaction.rollback()
            await blocker.close()
    finally:
        async with engine.begin() as connection:
            await connection.execute(
                text("SET LOCAL session_replication_role = 'replica'")
            )
            await connection.execute(
                text(
                    "DELETE FROM public.notifications "
                    "WHERE recipient_id IN (:student_1, :student_2)"
                ),
                ids,
            )
            await connection.execute(
                text(
                    "DELETE FROM public.published_result_versions "
                    "WHERE document_version_id IN (:one, :two)"
                ),
                {"one": ids["document_1"], "two": ids["document_2"]},
            )
            await connection.execute(
                text(
                    "DELETE FROM public.review_commands "
                    "WHERE actor_user_id IN (:teacher, :admin)"
                ),
                ids,
            )
            await connection.execute(
                text(
                    "DELETE FROM public.audit_events "
                    "WHERE resource_id IN (:one, :two, :finding)"
                ),
                {
                    "one": ids["document_1"],
                    "two": ids["document_2"],
                    "finding": ids["finding"],
                },
            )
            await _cleanup_graph(connection, ids)
        await engine.dispose()


def test_t012_concurrent_transitions_and_bulk_lock_scope(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    asyncio.run(_race_scenario(monkeypatch))
