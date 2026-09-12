from __future__ import annotations

import asyncio
import os
import uuid
from pathlib import Path

import pytest
from alembic.config import Config
from sqlalchemy import exc, text
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine
from sqlalchemy.pool import NullPool

from alembic import command
from app.core.config import get_settings
from tests.test_t011_review_workspace import _cleanup_graph, _ids, _seed_graph

pytestmark = pytest.mark.skipif(
    os.environ.get("RUN_DATABASE_TESTS") != "1",
    reason="Database integration tests require RUN_DATABASE_TESTS=1",
)


def _config() -> Config:
    backend_dir = Path(__file__).resolve().parents[1]
    config = Config(str(backend_dir / "alembic.ini"))
    config.set_main_option("script_location", str(backend_dir / "alembic"))
    return config


async def _tables(engine: AsyncEngine) -> set[str]:
    async with engine.connect() as connection:
        rows = await connection.execute(
            text(
                "SELECT table_name FROM information_schema.tables "
                "WHERE table_schema = 'public'"
            )
        )
        return {row.table_name for row in rows}


async def _append_only_guards(engine: AsyncEngine) -> None:
    ids = _ids()
    async with engine.connect() as connection:
        transaction = await connection.begin()
        try:
            await _seed_graph(connection, ids)
            await connection.execute(
                text(
                    "INSERT INTO public.published_result_versions "
                    "(id, document_version_id, version_number, approved_by_user_id, "
                    "published_by_user_id, approved_at, published_at, snapshot) "
                    "VALUES (:id, :document, 1, :teacher, :teacher, now(), now(), '{}')"
                ),
                {
                    "id": uuid.uuid4(),
                    "document": ids["document_1"],
                    "teacher": ids["teacher"],
                },
            )
            has_review_requests = await connection.scalar(
                text("SELECT to_regclass('public.review_requests') IS NOT NULL")
            )
            truncate_published = (
                "TRUNCATE TABLE public.review_requests, "
                "public.published_result_versions"
                if has_review_requests
                else "TRUNCATE TABLE public.published_result_versions"
            )
            for statement in (
                truncate_published,
                "TRUNCATE TABLE public.audit_events",
            ):
                with pytest.raises(exc.DBAPIError, match="append-only"):
                    async with connection.begin_nested():
                        await connection.execute(text(statement))
        finally:
            await transaction.rollback()


async def _lossy_downgrade_guard(engine: AsyncEngine, config: Config) -> None:
    ids = _ids()
    result_id = uuid.uuid4()
    async with engine.begin() as connection:
        await _seed_graph(connection, ids)
        await connection.execute(
            text(
                "INSERT INTO public.published_result_versions "
                "(id, document_version_id, version_number, approved_by_user_id, "
                "published_by_user_id, approved_at, published_at, snapshot) "
                "VALUES (:id, :document, 1, :teacher, :teacher, now(), now(), '{}')"
            ),
            {
                "id": result_id,
                "document": ids["document_1"],
                "teacher": ids["teacher"],
            },
        )
        await connection.execute(
            text(
                "INSERT INTO public.review_requests "
                "(id, published_result_id, submission_id, student_id, "
                "criterion_version_id, status, reason) VALUES "
                "(:id, :result, :submission, :student, :criterion, "
                "'OPEN'::public.review_request_status, 'guard')"
            ),
            {
                "id": uuid.uuid4(),
                "result": result_id,
                "submission": ids["submission_1"],
                "student": ids["student_1"],
                "criterion": ids["criterion"],
            },
        )
    try:
        with pytest.raises(RuntimeError, match="review_requests"):
            await asyncio.to_thread(command.downgrade, config, "20260911_0010")
    finally:
        async with engine.begin() as connection:
            await connection.execute(
                text("SET LOCAL session_replication_role = 'replica'")
            )
            await connection.execute(text("DELETE FROM public.review_requests"))
            await connection.execute(
                text("DELETE FROM public.published_result_versions WHERE id = :id"),
                {"id": result_id},
            )
            await _cleanup_graph(connection, ids)


def test_t016_migration_roundtrip_and_append_only_guards() -> None:
    config = _config()
    engine = create_async_engine(get_settings().database_url, poolclass=NullPool)
    try:
        command.upgrade(config, "head")
        tables = asyncio.run(_tables(engine))
        assert "review_requests" in tables
        asyncio.run(_append_only_guards(engine))
        asyncio.run(_lossy_downgrade_guard(engine, config))
        command.downgrade(config, "20260911_0010")
        assert "review_requests" not in asyncio.run(_tables(engine))
        asyncio.run(_append_only_guards(engine))
        command.upgrade(config, "head")
        tables = asyncio.run(_tables(engine))
        assert "review_requests" in tables
        asyncio.run(_append_only_guards(engine))
    finally:
        try:
            command.upgrade(config, "head")
        finally:
            asyncio.run(engine.dispose())
