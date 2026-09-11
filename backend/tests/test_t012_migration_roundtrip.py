from __future__ import annotations

import asyncio
import contextlib
import os
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
                    "id": ids["document_4"],
                    "document": ids["document_1"],
                    "teacher": ids["teacher"],
                },
            )
            for statement in (
                "UPDATE public.published_result_versions SET version_number = 2",
                "DELETE FROM public.published_result_versions",
                "TRUNCATE TABLE public.published_result_versions",
            ):
                with pytest.raises(exc.DBAPIError, match="append-only"):
                    async with connection.begin_nested():
                        await connection.execute(text(statement))
            with pytest.raises(exc.DBAPIError, match="append-only"):
                async with connection.begin_nested():
                    await connection.execute(text("TRUNCATE TABLE public.audit_events"))
        finally:
            await transaction.rollback()


async def _downgrade_guards(engine: AsyncEngine, config: Config) -> None:
    ids = _ids()
    async with engine.begin() as connection:
        await _seed_graph(connection, ids)
        await connection.execute(
            text(
                "INSERT INTO public.review_commands "
                "(id, actor_user_id, action, idempotency_key, "
                "request_fingerprint, response) "
                "VALUES (:id, :actor, 'APPROVE', 'guard', repeat('a', 64), '{}')"
            ),
            {"id": ids["document_4"], "actor": ids["teacher"]},
        )
    with pytest.raises(RuntimeError, match="review_commands"):
        await asyncio.to_thread(command.downgrade, config, "20260910_0009")
    async with engine.begin() as connection:
        await connection.execute(text("SET LOCAL session_replication_role = 'replica'"))
        await connection.execute(
            text("DELETE FROM public.review_commands WHERE id = :id"),
            {"id": ids["document_4"]},
        )
        await _cleanup_graph(connection, ids)

    async with engine.begin() as connection:
        await _seed_graph(connection, ids)
        await connection.execute(
            text(
                "UPDATE public.document_versions SET approved_at = now(), "
                "approved_by_user_id = :teacher, approved_snapshot = '{}'::jsonb "
                "WHERE id = :document"
            ),
            {"teacher": ids["teacher"], "document": ids["document_1"]},
        )
    with pytest.raises(RuntimeError, match="document_versions approval data"):
        await asyncio.to_thread(command.downgrade, config, "20260910_0009")
    async with engine.begin() as connection:
        await connection.execute(text("SET LOCAL session_replication_role = 'replica'"))
        await _cleanup_graph(connection, ids)


async def _seed_at_0009(engine: AsyncEngine, ids: dict[str, object]) -> None:
    async with engine.begin() as connection:
        await _seed_graph(connection, ids)


async def _cleanup_at_0009(engine: AsyncEngine, ids: dict[str, object]) -> None:
    async with engine.begin() as connection:
        await _cleanup_graph(connection, ids)


def test_t012_migration_real_postgresql_roundtrip_and_guards() -> None:
    config = _config()
    engine = create_async_engine(get_settings().database_url, poolclass=NullPool)
    try:
        command.upgrade(config, "head")
        tables = asyncio.run(_tables(engine))
        assert {"published_result_versions", "review_commands"} <= tables
        asyncio.run(_append_only_guards(engine))
        asyncio.run(_downgrade_guards(engine, config))
        command.downgrade(config, "20260910_0009")
        tables = asyncio.run(_tables(engine))
        assert "published_result_versions" not in tables
        assert "review_commands" not in tables
        legacy_ids = _ids()
        asyncio.run(_seed_at_0009(engine, legacy_ids))
        with pytest.raises(RuntimeError, match="approval snapshot backfill"):
            command.upgrade(config, "head")
        asyncio.run(_cleanup_at_0009(engine, legacy_ids))
        command.upgrade(config, "head")
        tables = asyncio.run(_tables(engine))
        assert {"published_result_versions", "review_commands"} <= tables
    finally:
        with contextlib.suppress(Exception):
            command.upgrade(config, "head")
        asyncio.run(engine.dispose())
