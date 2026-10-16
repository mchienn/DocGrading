"""A DB session whose every write is rolled back when the block exits.

The session joins an outer transaction in ``create_savepoint`` mode, so the
``db.commit()`` calls inside product code (e.g. caching a summary) only
release a SAVEPOINT; the outer transaction is rolled back at the end and the
database is left exactly as it was. Every benchmark request runs inside one
of these, which makes runs repeatable (a run can't warm the summary cache
for the next one) and keeps the benchmark from writing to the database.
"""

from __future__ import annotations

import contextlib
from collections.abc import AsyncIterator

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import _engine


@contextlib.asynccontextmanager
async def rolled_back_session() -> AsyncIterator[AsyncSession]:
    async with _engine().connect() as connection:
        transaction = await connection.begin()
        session = AsyncSession(
            bind=connection,
            join_transaction_mode="create_savepoint",
            expire_on_commit=False,
        )
        try:
            yield session
        finally:
            await session.close()
            await transaction.rollback()
