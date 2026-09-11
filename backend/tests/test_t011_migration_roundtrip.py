from __future__ import annotations

import asyncio
import contextlib
import os
from pathlib import Path

import pytest
from sqlalchemy import exc, text
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine
from sqlalchemy.pool import NullPool

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
    import alembic.command
    import alembic.config

    backend_dir = Path(__file__).resolve().parents[1]
    config = alembic.config.Config(str(backend_dir / "alembic.ini"))
    config.set_main_option("script_location", str(backend_dir / "alembic"))
    engine = create_async_engine(
        get_settings().database_url,
        poolclass=NullPool,
    )

    try:
        alembic.command.upgrade(config, "head")
        assert asyncio.run(_public_tables(engine)) >= T011_TABLES
        assert asyncio.run(_enum_exists(engine)) is True
        assert asyncio.run(_draft_version_column_exists(engine)) is True
        asyncio.run(_assert_audit_truncate_rejected(engine))

        alembic.command.downgrade(config, "20260902_0008")
        assert T011_TABLES.isdisjoint(asyncio.run(_public_tables(engine)))
        assert asyncio.run(_enum_exists(engine)) is False
        asyncio.run(_assert_audit_truncate_rejected(engine))

        alembic.command.upgrade(config, "head")
        assert asyncio.run(_public_tables(engine)) >= T011_TABLES
        assert asyncio.run(_enum_exists(engine)) is True
        assert asyncio.run(_draft_version_column_exists(engine)) is True
        asyncio.run(_assert_audit_truncate_rejected(engine))
    finally:
        with contextlib.suppress(Exception):
            alembic.command.upgrade(config, "head")
        asyncio.run(engine.dispose())
