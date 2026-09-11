from __future__ import annotations

import ast
import uuid
from pathlib import Path

import pytest
from pydantic import ValidationError

import app.models  # noqa: F401
from app.api.schemas_submission import (
    BBox,
    BulkPublishRequest,
    PublishedResultResponse,
    PublishRequest,
)
from app.db.base import Base

MIGRATION = (
    Path(__file__).parents[1]
    / "alembic"
    / "versions"
    / "20260911_0010_approval_publication.py"
)


def _function(tree: ast.AST, name: str) -> ast.FunctionDef:
    function = next(
        (
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.FunctionDef) and node.name == name
        ),
        None,
    )
    assert function is not None
    return function


def test_t012_models_and_student_response_are_allowlisted() -> None:
    assert {"published_result_versions", "review_commands"} <= set(Base.metadata.tables)
    version = Base.metadata.tables["document_versions"]
    assert {"approved_at", "approved_by_user_id", "approved_snapshot"} <= set(
        version.columns.keys()
    )
    assert set(PublishedResultResponse.model_fields) == {
        "published_result_id",
        "submission_id",
        "document_version_id",
        "version_number",
        "published_at",
        "comment",
        "findings",
    }


def test_t012_requests_reject_blank_reason_and_duplicate_bulk_ids() -> None:
    with pytest.raises(ValidationError):
        PublishRequest(reason="  ")
    value = uuid.uuid4()
    with pytest.raises(ValidationError):
        BulkPublishRequest(version_ids=[value, value], reason="publish")


def test_t012_migration_security_and_append_only_contract() -> None:
    source = MIGRATION.read_text(encoding="utf-8")
    tree = ast.parse(source)
    upgrade = _function(tree, "upgrade")
    downgrade = _function(tree, "downgrade")
    assert "SET search_path TO public" in ast.unparse(upgrade.body[0])
    assert "SET search_path TO public" in ast.unparse(downgrade.body[0])
    assert "audit_events" not in source
    assert "BEFORE UPDATE ON public.published_result_versions" in source
    assert "BEFORE DELETE ON public.published_result_versions" in source
    assert "BEFORE TRUNCATE ON public.published_result_versions" in source
    assert "LOCK TABLE public.published_result_versions" in source
    assert "Refusing downgrade: public." in source
    assert "SET search_path = pg_catalog, public, pg_temp" in source
    for function in (upgrade, downgrade):
        for call in (
            node
            for node in ast.walk(function)
            if isinstance(node, ast.Call)
            and getattr(node.func, "attr", None) in {"create_table", "drop_table"}
        ):
            assert any(
                keyword.arg == "schema"
                and isinstance(keyword.value, ast.Constant)
                and keyword.value.value == "public"
                for keyword in call.keywords
            )


def test_t012_evidence_schema_matches_t011_public_geometry() -> None:
    assert set(BBox.model_fields) == {"x0", "top", "x1", "bottom"}
