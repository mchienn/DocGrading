from __future__ import annotations

import asyncio
import os
import uuid
from pathlib import Path

import pytest
from alembic.config import Config
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine
from sqlalchemy.pool import NullPool

from alembic import command
from app.core.config import get_settings
from app.services.course_join import generate_join_code
from tests.test_t016_migration_roundtrip import _append_only_guards

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


async def _constraints(engine: AsyncEngine) -> set[str]:
    async with engine.connect() as connection:
        rows = await connection.execute(
            text(
                "SELECT conname FROM pg_catalog.pg_constraint "
                "WHERE connamespace = 'public'::regnamespace "
                "AND conrelid IN "
                "('public.course_join_codes'::regclass, "
                "'public.join_rate_limits'::regclass)"
            )
        )
        return {row.conname for row in rows}


async def _prove_lossy_downgrade_guard(engine: AsyncEngine, config: Config) -> None:
    teacher_id = uuid.uuid4()
    course_id = uuid.uuid4()
    code_id = uuid.uuid4()
    code = generate_join_code()
    async with engine.begin() as connection:
        await connection.execute(
            text(
                "INSERT INTO public.users "
                "(id, email, display_name, password_hash, roles, status, revision) "
                "VALUES (:id, :email, 'T027 Migration', 'hash', "
                "ARRAY['TEACHER']::public.user_role[], "
                "'ACTIVE'::public.user_status, 1)"
            ),
            {"id": teacher_id, "email": f"{teacher_id}@test.local"},
        )
        await connection.execute(
            text(
                "INSERT INTO public.courses "
                "(id, code, name, term, owner_teacher_id, revision) "
                "VALUES (:id, :code, 'T027 Migration', '2026A', :teacher, 1)"
            ),
            {
                "id": course_id,
                "code": f"T027-{course_id}",
                "teacher": teacher_id,
            },
        )
        await connection.execute(
            text(
                "INSERT INTO public.course_join_codes "
                "(id, course_id, code, expires_at) "
                "VALUES (:id, :course, :code, now() + interval '1 day')"
            ),
            {"id": code_id, "course": course_id, "code": code},
        )
    try:
        with pytest.raises(RuntimeError, match="course_join_codes is not empty"):
            await asyncio.to_thread(command.downgrade, config, "20260916_0014")
    finally:
        async with engine.begin() as connection:
            await connection.execute(
                text("DELETE FROM public.course_join_codes WHERE id = :id"),
                {"id": code_id},
            )
            await connection.execute(
                text("DELETE FROM public.courses WHERE id = :id"),
                {"id": course_id},
            )
            await connection.execute(
                text("DELETE FROM public.users WHERE id = :id"),
                {"id": teacher_id},
            )


def test_t027_real_postgresql_roundtrip_and_append_only_guards() -> None:
    config = _config()
    engine = create_async_engine(get_settings().database_url, poolclass=NullPool)
    try:
        command.upgrade(config, "head")
        assert {"course_join_codes", "join_rate_limits"} <= asyncio.run(_tables(engine))
        assert {
            "pk_course_join_codes",
            "uq_course_join_codes_code",
            "ck_course_join_codes_code_shape",
            "ck_course_join_codes_expiry_after_creation",
            "fk_course_join_codes_course_id_courses",
            "pk_join_rate_limits",
            "uq_join_rate_limits_subject_hash",
            "ck_join_rate_limits_subject_hash",
            "ck_join_rate_limits_count_nonnegative",
        } <= asyncio.run(_constraints(engine))
        asyncio.run(_append_only_guards(engine))
        asyncio.run(_prove_lossy_downgrade_guard(engine, config))

        command.downgrade(config, "20260916_0014")
        assert not {"course_join_codes", "join_rate_limits"} & asyncio.run(
            _tables(engine)
        )
        asyncio.run(_append_only_guards(engine))

        command.upgrade(config, "head")
        assert {"course_join_codes", "join_rate_limits"} <= asyncio.run(_tables(engine))
        asyncio.run(_append_only_guards(engine))
    finally:
        try:
            command.upgrade(config, "head")
        finally:
            asyncio.run(engine.dispose())
