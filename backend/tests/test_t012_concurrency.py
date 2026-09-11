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
from app.services.review import approve_document_version, publish_document_version
from tests.test_t011_review_workspace import _actor, _cleanup_graph, _ids, _seed_graph

pytestmark = pytest.mark.skipif(
    os.environ.get("RUN_DATABASE_TESTS") != "1",
    reason="Database integration tests require RUN_DATABASE_TESTS=1",
)


async def _race_scenario() -> None:
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

        async def approve_race(actor, key: str) -> tuple[str, int | None]:
            async with factory() as session:
                try:
                    await approve_document_version(
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
                    await publish_document_version(
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
    finally:
        async with engine.begin() as connection:
            await connection.execute(
                text("SET LOCAL session_replication_role = 'replica'")
            )
            await connection.execute(
                text(
                    "DELETE FROM public.published_result_versions "
                    "WHERE document_version_id = :document"
                ),
                {"document": ids["document_1"]},
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
                    "WHERE resource_id IN (:document, :finding)"
                ),
                {"document": ids["document_1"], "finding": ids["finding"]},
            )
            await _cleanup_graph(connection, ids)
        await engine.dispose()


def test_t012_concurrent_approve_and_publish_have_one_winner() -> None:
    asyncio.run(_race_scenario())
