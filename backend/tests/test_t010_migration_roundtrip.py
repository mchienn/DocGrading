from __future__ import annotations

# SQL fixtures are intentionally readable as complete statements.
# ruff: noqa: E501
import ast
import asyncio
import contextlib
import importlib.util
import os
import uuid
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine
from sqlalchemy.pool import NullPool

from app.core.config import get_settings


def _get_migration_0008_module() -> tuple[Any, Path]:
    migration_path = (
        Path(__file__).resolve().parents[1]
        / "alembic"
        / "versions"
        / "20260902_0008_document_ir.py"
    )
    spec = importlib.util.spec_from_file_location("migration_0008", migration_path)
    assert spec is not None and spec.loader is not None
    migration_0008 = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration_0008)
    return migration_0008, migration_path


def verify_migration_security_and_schema_contracts(source: str) -> None:
    tree = ast.parse(source)

    upgrade_fn = next(
        (
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.FunctionDef) and node.name == "upgrade"
        ),
        None,
    )
    assert upgrade_fn is not None, "upgrade function must be defined"

    downgrade_fn = next(
        (
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.FunctionDef) and node.name == "downgrade"
        ),
        None,
    )
    assert downgrade_fn is not None, "downgrade function must be defined"

    # SC-1: Both upgrade and downgrade pin search_path to public as first statement
    assert len(upgrade_fn.body) > 0 and "SET search_path TO public" in ast.unparse(
        upgrade_fn.body[0]
    ), "SC-1 violation: upgrade() must pin search_path to public as first statement"
    assert len(downgrade_fn.body) > 0 and "SET search_path TO public" in ast.unparse(
        downgrade_fn.body[0]
    ), "SC-1 violation: downgrade() must pin search_path to public as first statement"

    # SC-2: Append-only audit triggers are never touched/dropped
    forbidden_audit_terms = (
        "audit_events",
        "trg_audit_events",
        "fn_audit_events",
    )
    for term in forbidden_audit_terms:
        assert term not in source, f"SC-2 violation: migration must not touch {term}"

    # SC-3: Schema qualification per Alembic DDL op (create_table, drop_table) and FK target
    create_table_calls = [
        node
        for node in ast.walk(upgrade_fn)
        if isinstance(node, ast.Call)
        and (
            (isinstance(node.func, ast.Attribute) and node.func.attr == "create_table")
            or "create_table" in ast.unparse(node.func)
        )
    ]
    assert (
        len(create_table_calls) == 1
    ), "upgrade() must call op.create_table exactly once"
    create_call = create_table_calls[0]
    assert any(
        kw.arg == "schema"
        and isinstance(kw.value, ast.Constant)
        and kw.value.value == "public"
        for kw in create_call.keywords
    ), 'SC-3 violation: op.create_table in upgrade() must explicitly set schema="public"'

    drop_table_calls = [
        node
        for node in ast.walk(downgrade_fn)
        if isinstance(node, ast.Call)
        and (
            (isinstance(node.func, ast.Attribute) and node.func.attr == "drop_table")
            or "drop_table" in ast.unparse(node.func)
        )
    ]
    assert (
        len(drop_table_calls) == 1
    ), "downgrade() must call op.drop_table exactly once"
    drop_call = drop_table_calls[0]
    assert any(
        kw.arg == "schema"
        and isinstance(kw.value, ast.Constant)
        and kw.value.value == "public"
        for kw in drop_call.keywords
    ), 'SC-3 violation: op.drop_table in downgrade() must explicitly set schema="public"'

    fk_calls = [
        node
        for node in ast.walk(upgrade_fn)
        if isinstance(node, ast.Call)
        and (
            (
                isinstance(node.func, ast.Attribute)
                and node.func.attr == "ForeignKeyConstraint"
            )
            or "ForeignKeyConstraint" in ast.unparse(node.func)
        )
    ]
    assert len(fk_calls) >= 1, "upgrade() must declare ForeignKeyConstraint"
    assert "public.document_versions.id" in ast.unparse(
        fk_calls[0]
    ), "SC-3 violation: ForeignKeyConstraint must reference public.document_versions.id"


def test_migration_0008_contract_definitions() -> None:
    migration_0008, _ = _get_migration_0008_module()

    assert migration_0008.revision == "20260902_0008"
    assert migration_0008.down_revision == "20260829_0007"
    assert hasattr(migration_0008, "upgrade") and callable(migration_0008.upgrade)
    assert hasattr(migration_0008, "downgrade") and callable(migration_0008.downgrade)
    assert migration_0008.branch_labels is None
    assert migration_0008.depends_on is None


def test_migration_0008_security_and_schema_static_contracts() -> None:
    _, migration_path = _get_migration_0008_module()
    source = migration_path.read_text(encoding="utf-8")
    verify_migration_security_and_schema_contracts(source)


@pytest.mark.parametrize(
    ("bad_source", "expected_err"),
    [
        (
            "def upgrade(): pass\ndef downgrade(): pass",
            r"SC-1 violation: upgrade\(\) must pin search_path",
        ),
        (
            "def upgrade():\n    op.execute('SET search_path TO public')\ndef downgrade(): pass",
            r"SC-1 violation: downgrade\(\) must pin search_path",
        ),
        (
            "def upgrade():\n    op.execute('SET search_path TO public')\ndef downgrade():\n    op.execute('SET search_path TO public')\n# touches audit_events",
            r"SC-2 violation: migration must not touch audit_events",
        ),
        (
            "def upgrade():\n    op.execute('SET search_path TO public')\n    op.create_table('document_irs')\ndef downgrade():\n    op.execute('SET search_path TO public')\n    op.drop_table('document_irs', schema='public')",
            r'SC-3 violation: op\.create_table in upgrade\(\) must explicitly set schema="public"',
        ),
        (
            "def upgrade():\n    op.execute('SET search_path TO public')\n    op.create_table('document_irs', schema='public')\ndef downgrade():\n    op.execute('SET search_path TO public')\n    op.drop_table('document_irs')",
            r'SC-3 violation: op\.drop_table in downgrade\(\) must explicitly set schema="public"',
        ),
        (
            "def upgrade():\n    op.execute('SET search_path TO public')\n    op.create_table('document_irs', sa.ForeignKeyConstraint(['document_version_id'], ['document_versions.id']), schema='public')\ndef downgrade():\n    op.execute('SET search_path TO public')\n    op.drop_table('document_irs', schema='public')",
            r"SC-3 violation: ForeignKeyConstraint must reference public\.document_versions\.id",
        ),
    ],
)
def test_static_contract_verifier_detects_violations(
    bad_source: str, expected_err: str
) -> None:
    with pytest.raises(AssertionError, match=expected_err):
        verify_migration_security_and_schema_contracts(bad_source)


@pytest.mark.skipif(
    os.environ.get("RUN_DATABASE_TESTS") != "1",
    reason="Database integration tests require RUN_DATABASE_TESTS=1",
)
def test_migration_0008_roundtrip_postgres() -> None:
    """Real PostgreSQL roundtrip verifying migration 0008 upgrade, metadata, audit truncate protection, and downgrade."""
    import alembic.command
    import alembic.config

    backend_dir = os.path.dirname(os.path.dirname(__file__))
    alembic_ini_path = os.path.join(backend_dir, "alembic.ini")
    alembic_cfg = alembic.config.Config(alembic_ini_path)
    alembic_cfg.set_main_option(
        "script_location",
        os.path.join(backend_dir, "alembic"),
    )

    settings = get_settings()
    engine = create_async_engine(
        settings.database_url,
        poolclass=NullPool,
    )

    sentinel_user_id = uuid.uuid4()
    sentinel_data = {
        "id": sentinel_user_id,
        "email": f"sentinel_{sentinel_user_id.hex[:12]}@example.com",
        "display_name": "Migration Sentinel User",
        "password_hash": "sentinel_hash_value",
        "roles": ["STUDENT"],
        "status": "ACTIVE",
        "revision": 1,
    }

    async def _get_public_tables(eng: AsyncEngine) -> set[str]:
        async with eng.connect() as conn:
            res = await conn.execute(text("""
                    SELECT table_name
                    FROM information_schema.tables
                    WHERE table_schema = 'public'
                """))
            return {row.table_name for row in res.fetchall()}

    async def _insert_sentinel_user(eng: AsyncEngine, data: dict[str, Any]) -> None:
        async with eng.begin() as conn:
            await conn.execute(
                text("""
                    INSERT INTO public.users
                        (id, email, display_name, password_hash, roles, status, revision)
                    VALUES
                        (:id, :email, :display_name, :password_hash,
                         CAST(ARRAY[:role] AS public.user_role[]),
                         CAST(:status AS public.user_status),
                         :revision)
                """),
                {
                    "id": data["id"],
                    "email": data["email"],
                    "display_name": data["display_name"],
                    "password_hash": data["password_hash"],
                    "role": data["roles"][0],
                    "status": data["status"],
                    "revision": data["revision"],
                },
            )

    async def _verify_sentinel_user_unchanged(
        eng: AsyncEngine, data: dict[str, Any]
    ) -> None:
        async with eng.connect() as conn:
            row = (
                (
                    await conn.execute(
                        text("""
                        SELECT id, email, display_name, password_hash, roles,
                               CAST(status AS text) AS status, revision
                        FROM public.users
                        WHERE id = :id
                    """),
                        {"id": data["id"]},
                    )
                )
                .mappings()
                .one()
            )
            assert row["status"] == data["status"]
            assert row["revision"] == data["revision"]

    async def _cleanup_sentinel_user(eng: AsyncEngine, user_id: uuid.UUID) -> None:
        async with eng.begin() as conn:
            await conn.execute(
                text("DELETE FROM public.users WHERE id = :id"),
                {"id": user_id},
            )

    async def _verify_metadata_0008(eng: AsyncEngine) -> None:
        async with eng.connect() as conn:
            # 1. Table existence in information_schema.tables
            table_exists = (await conn.execute(text("""
                        SELECT EXISTS (
                            SELECT 1
                            FROM information_schema.tables
                            WHERE table_schema = 'public'
                              AND table_name = 'document_irs'
                        )
                    """))).scalar_one()
            assert (
                table_exists is True
            ), "public.document_irs table must exist after upgrade"

            # 2. Columns verification in information_schema.columns
            columns_res = await conn.execute(text("""
                    SELECT column_name, data_type, udt_name, is_nullable,
                           column_default, character_maximum_length
                    FROM information_schema.columns
                    WHERE table_schema = 'public'
                      AND table_name = 'document_irs'
                """))
            columns = {
                row.column_name: {
                    "data_type": row.data_type,
                    "udt_name": row.udt_name,
                    "is_nullable": row.is_nullable,
                    "column_default": row.column_default,
                    "character_maximum_length": row.character_maximum_length,
                }
                for row in columns_res.fetchall()
            }

            expected_columns = {
                "id",
                "document_version_id",
                "schema_version",
                "parser_version",
                "content",
                "created_at",
                "updated_at",
            }
            assert set(columns.keys()) == expected_columns

            # Column types, nullability, defaults, and constraints
            assert columns["id"]["udt_name"] == "uuid"
            assert columns["id"]["is_nullable"] == "NO"

            assert columns["document_version_id"]["udt_name"] == "uuid"
            assert columns["document_version_id"]["is_nullable"] == "NO"

            assert columns["schema_version"]["udt_name"] in ("int4", "integer")
            assert columns["schema_version"]["is_nullable"] == "NO"
            assert columns["schema_version"]["column_default"] is not None
            assert "1" in str(columns["schema_version"]["column_default"])

            assert columns["parser_version"]["udt_name"] == "varchar"
            assert columns["parser_version"]["character_maximum_length"] == 64
            assert columns["parser_version"]["is_nullable"] == "NO"

            assert columns["content"]["udt_name"] == "jsonb"
            assert columns["content"]["is_nullable"] == "NO"

            assert columns["created_at"]["udt_name"] in (
                "timestamptz",
                "timestamp with time zone",
            )
            assert columns["created_at"]["is_nullable"] == "NO"

            assert columns["updated_at"]["udt_name"] in (
                "timestamptz",
                "timestamp with time zone",
            )
            assert columns["updated_at"]["is_nullable"] == "NO"

            # 3. Constraints in pg_constraint
            constraints_res = await conn.execute(text("""
                    SELECT
                        c.conname,
                        CAST(c.contype AS text) AS contype,
                        CAST(c.confdeltype AS text) AS confdeltype,
                        pg_get_constraintdef(c.oid) AS constraint_def,
                        cl_rel.relname AS foreign_table,
                        nsp_rel.nspname AS foreign_schema,
                        ARRAY(
                            SELECT attname
                            FROM pg_attribute
                            WHERE attrelid = c.conrelid AND attnum = ANY(c.conkey)
                            ORDER BY array_position(c.conkey, attnum)
                        ) AS local_columns,
                        ARRAY(
                            SELECT attname
                            FROM pg_attribute
                            WHERE attrelid = c.confrelid AND attnum = ANY(c.confkey)
                            ORDER BY array_position(c.confkey, attnum)
                        ) AS foreign_columns
                    FROM pg_constraint c
                    JOIN pg_class cl_src ON c.conrelid = cl_src.oid
                    JOIN pg_namespace nsp_src ON cl_src.relnamespace = nsp_src.oid
                    LEFT JOIN pg_class cl_rel ON c.confrelid = cl_rel.oid
                    LEFT JOIN pg_namespace nsp_rel ON cl_rel.relnamespace = nsp_rel.oid
                    WHERE nsp_src.nspname = 'public'
                      AND cl_src.relname = 'document_irs'
                """))
            constraints_by_name = {
                row.conname: row for row in constraints_res.fetchall()
            }

            # Primary Key: pk_document_irs
            assert "pk_document_irs" in constraints_by_name
            pk = constraints_by_name["pk_document_irs"]
            assert pk.contype == "p"
            assert list(pk.local_columns) == ["id"]

            # Unique constraint: uq_document_irs_document_version_id
            assert "uq_document_irs_document_version_id" in constraints_by_name
            uq = constraints_by_name["uq_document_irs_document_version_id"]
            assert uq.contype == "u"
            assert list(uq.local_columns) == ["document_version_id"]

            # Foreign key: fk_document_irs_document_version_id_document_versions
            assert (
                "fk_document_irs_document_version_id_document_versions"
                in constraints_by_name
            )
            fk = constraints_by_name[
                "fk_document_irs_document_version_id_document_versions"
            ]
            assert fk.contype == "f"
            assert list(fk.local_columns) == ["document_version_id"]
            assert fk.foreign_table == "document_versions"
            assert fk.foreign_schema == "public"
            assert list(fk.foreign_columns) == ["id"]
            assert fk.confdeltype == "c"  # CASCADE

            # Check constraint: ck_document_irs_schema_version_positive
            assert "ck_document_irs_schema_version_positive" in constraints_by_name
            ck_ver = constraints_by_name["ck_document_irs_schema_version_positive"]
            assert ck_ver.contype == "c"
            clean_ck_ver_def = (
                ck_ver.constraint_def.replace("(", "").replace(")", "").replace(" ", "")
            )
            assert "schema_version>0" in clean_ck_ver_def

            # Check constraint: ck_document_irs_parser_version_not_blank
            # (must contain both length/btrim and !~ predicates in the same check constraint)
            assert "ck_document_irs_parser_version_not_blank" in constraints_by_name
            ck_parser = constraints_by_name["ck_document_irs_parser_version_not_blank"]
            assert ck_parser.contype == "c"
            ck_parser_def = ck_parser.constraint_def
            assert (
                "length" in ck_parser_def and "btrim" in ck_parser_def
            ) or "length(btrim(parser_version))" in ck_parser_def
            assert (
                "!~" in ck_parser_def and "[:space:]" in ck_parser_def
            ) or "!~ '^[[:space:]]*$'" in ck_parser_def

            # Check constraint: ck_document_irs_content_object
            assert "ck_document_irs_content_object" in constraints_by_name
            ck_content = constraints_by_name["ck_document_irs_content_object"]
            assert ck_content.contype == "c"
            assert "jsonb_typeof" in ck_content.constraint_def
            assert "'object'" in ck_content.constraint_def

    async def _assert_audit_truncate_rejected(eng: AsyncEngine) -> None:
        async with eng.connect() as conn:
            with pytest.raises(Exception, match="audit events are append-only"):
                async with conn.begin_nested():
                    await conn.execute(text("TRUNCATE TABLE public.audit_events"))

            # Ensure connection is clean and not poisoned
            canary = await conn.execute(text("SELECT 1"))
            assert canary.scalar_one() == 1

    async def _verify_downgrade_0007(
        eng: AsyncEngine, baseline_tables: set[str]
    ) -> None:
        async with eng.connect() as conn:
            downgraded_tables = await _get_public_tables(eng)
            assert (
                "document_irs" not in downgraded_tables
            ), "public.document_irs table must be dropped after downgrade"
            assert (
                downgraded_tables == baseline_tables
            ), "Exact public table set after downgrade must match baseline 0007 set"

            # Prior invariants remain (e.g., dispatch trigger on analysis_jobs)
            trigger_exists = (await conn.execute(text("""
                        SELECT EXISTS (
                            SELECT 1
                            FROM pg_trigger
                            WHERE tgname = 'trg_analysis_jobs_dispatch_outbox'
                              AND NOT tgisinternal
                        )
                    """))).scalar_one()
            assert (
                trigger_exists is True
            ), "Dispatch outbox trigger must remain after downgrade"

    try:
        # Step 1: Ensure downgrade to 20260829_0007 and capture baseline tables & insert sentinel
        try:
            alembic.command.downgrade(alembic_cfg, "20260829_0007")
        except Exception:
            alembic.command.upgrade(alembic_cfg, "20260829_0007")

        baseline_tables = asyncio.run(_get_public_tables(engine))
        assert "document_irs" not in baseline_tables
        asyncio.run(_insert_sentinel_user(engine, sentinel_data))

        # Step 2: Upgrade to 20260902_0008
        alembic.command.upgrade(alembic_cfg, "20260902_0008")

        # Step 3: Verify upgraded tables == baseline | {'document_irs'}, metadata, and sentinel unchanged
        upgraded_tables = asyncio.run(_get_public_tables(engine))
        assert upgraded_tables == baseline_tables | {"document_irs"}
        asyncio.run(_verify_metadata_0008(engine))
        asyncio.run(_verify_sentinel_user_unchanged(engine, sentinel_data))

        # Step 4: Assert audit TRUNCATE rejected inside savepoint without poisoning connection
        asyncio.run(_assert_audit_truncate_rejected(engine))

        # Step 5: Downgrade back to 20260829_0007 and prove only document_irs disappeared & sentinel unchanged
        alembic.command.downgrade(alembic_cfg, "20260829_0007")
        asyncio.run(_verify_downgrade_0007(engine, baseline_tables))
        asyncio.run(_verify_sentinel_user_unchanged(engine, sentinel_data))

        # Step 6: Assert audit TRUNCATE still rejected after downgrade
        asyncio.run(_assert_audit_truncate_rejected(engine))

    finally:
        # Step 7: Clean sentinel safely and always upgrade to head in finally block, including after failures
        try:
            with contextlib.suppress(Exception):
                asyncio.run(_cleanup_sentinel_user(engine, sentinel_data["id"]))
        finally:
            try:
                alembic.command.upgrade(alembic_cfg, "head")
            finally:
                asyncio.run(engine.dispose())
