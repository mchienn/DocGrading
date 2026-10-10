from __future__ import annotations

import asyncio
import uuid
from collections.abc import Iterator

import pytest
from sqlalchemy import text
from sqlalchemy.engine import URL, make_url
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool

from app.core.config import get_settings


async def _run_admin_sql(admin_url: URL, statement: str) -> None:
    engine = create_async_engine(
        admin_url,
        isolation_level="AUTOCOMMIT",
        poolclass=NullPool,
    )
    try:
        async with engine.connect() as connection:
            await connection.execute(text(statement))
    finally:
        await engine.dispose()


@pytest.fixture
def isolated_postgres_database(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Run destructive PostgreSQL tests against a disposable database."""
    admin_url = make_url(get_settings().database_url).set(database="postgres")
    database_name = f"pytest_{uuid.uuid4().hex}"
    asyncio.run(_run_admin_sql(admin_url, f'CREATE DATABASE "{database_name}"'))
    monkeypatch.setenv("POSTGRES_DB", database_name)
    get_settings.cache_clear()
    try:
        yield
    finally:
        get_settings.cache_clear()
        asyncio.run(
            _run_admin_sql(
                admin_url,
                f'DROP DATABASE IF EXISTS "{database_name}" WITH (FORCE)',
            )
        )
