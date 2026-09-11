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

pytestmark = pytest.mark.skipif(
    os.environ.get("RUN_DATABASE_TESTS") != "1",
    reason="Database integration tests require RUN_DATABASE_TESTS=1",
)

T011_TABLES = {
    "findings",
    "evidence_anchors",
    "review_locks",
    "review_drafts",
    "review_decisions",
}


async def _public_tables(engine: AsyncEngine) -> set[str]:
    async with engine.connect() as connection:
        rows = await connection.execute(text("""
                SELECT table_name
                FROM information_schema.tables
                WHERE table_schema = 'public'
            """))
        return {row.table_name for row in rows}


async def _enum_exists(engine: AsyncEngine) -> bool:
    async with engine.connect() as connection:
        return bool(await connection.scalar(text("""
                    SELECT EXISTS (
                        SELECT 1
                        FROM pg_type type
                        JOIN pg_namespace namespace
                          ON namespace.oid = type.typnamespace
                        WHERE namespace.nspname = 'public'
                          AND type.typname = 'review_decision_type'
                    )
                """)))


async def _draft_version_column_exists(engine: AsyncEngine) -> bool:
    async with engine.connect() as connection:
        return bool(await connection.scalar(text("""
            SELECT EXISTS (
                SELECT 1
                FROM information_schema.columns
                WHERE table_schema = 'public'
                  AND table_name = 'review_drafts'
                  AND column_name = 'document_version_id'
            )
        """)))


async def _assert_audit_truncate_rejected(engine: AsyncEngine) -> None:
    async with engine.connect() as connection:
        transaction = await connection.begin()
        try:
            with pytest.raises(exc.DBAPIError, match="append-only"):
                async with connection.begin_nested():
                    await connection.execute(text("TRUNCATE TABLE public.audit_events"))
            assert await connection.scalar(text("SELECT 1")) == 1
        finally:
            await transaction.rollback()


def test_migration_0009_real_postgresql_roundtrip() -> None:
    backend_dir = Path(__file__).resolve().parents[1]
    config = Config(str(backend_dir / "alembic.ini"))
    config.set_main_option("script_location", str(backend_dir / "alembic"))
    engine = create_async_engine(
        get_settings().database_url,
        poolclass=NullPool,
    )

    try:
        command.upgrade(config, "head")
        assert asyncio.run(_public_tables(engine)) >= T011_TABLES
        assert asyncio.run(_enum_exists(engine)) is True
        assert asyncio.run(_draft_version_column_exists(engine)) is True
        asyncio.run(_assert_audit_truncate_rejected(engine))

        command.downgrade(config, "20260902_0008")
        assert T011_TABLES.isdisjoint(asyncio.run(_public_tables(engine)))
        assert asyncio.run(_enum_exists(engine)) is False
        asyncio.run(_assert_audit_truncate_rejected(engine))

        command.upgrade(config, "head")
        assert asyncio.run(_public_tables(engine)) >= T011_TABLES
        assert asyncio.run(_enum_exists(engine)) is True
        assert asyncio.run(_draft_version_column_exists(engine)) is True
        asyncio.run(_assert_audit_truncate_rejected(engine))
    finally:
        with contextlib.suppress(Exception):
            command.upgrade(config, "head")
        asyncio.run(engine.dispose())


def test_migration_0009_refuses_nonempty_finding_downgrade() -> None:
    from tests.test_t011_review_workspace import _cleanup_graph, _ids, _seed_graph

    backend_dir = Path(__file__).resolve().parents[1]
    config = Config(str(backend_dir / "alembic.ini"))
    config.set_main_option("script_location", str(backend_dir / "alembic"))
    engine = create_async_engine(
        get_settings().database_url,
        poolclass=NullPool,
    )
    ids = _ids()

    async def exercise_guard() -> None:
        async with engine.begin() as connection:
            await _seed_graph(connection, ids)
            await connection.execute(
                text("DELETE FROM public.evidence_anchors WHERE id = :anchor"),
                {"anchor": ids["anchor"]},
            )
        try:
            with pytest.raises(RuntimeError, match="public.findings is not empty"):
                await asyncio.to_thread(
                    command.downgrade,
                    config,
                    "20260902_0008",
                )
            assert "findings" in await _public_tables(engine)
        finally:
            async with engine.begin() as connection:
                await _cleanup_graph(connection, ids)

    try:
        command.upgrade(config, "head")
        asyncio.run(exercise_guard())
    finally:
        with contextlib.suppress(Exception):
            command.upgrade(config, "head")
        asyncio.run(engine.dispose())
