from __future__ import annotations

import ast
import uuid
from pathlib import Path

import pytest
from pydantic import ValidationError

import app.models  # noqa: F401
from app.api.schemas_submission import (
    ReviewRequestCreate,
    ReviewRequestResponse,
    ReviewRequestUpdate,
)
from app.db.base import Base
from app.main import app
from app.models.enums import ReviewRequestStatus

MIGRATION = (
    Path(__file__).parents[1]
    / "alembic"
    / "versions"
    / "20260912_0011_review_requests.py"
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


def test_t016_schema_forbids_extra_and_requires_one_target() -> None:
    value = uuid.uuid4()
    with pytest.raises(ValidationError):
        ReviewRequestCreate(
            submission_id=value,
            criterion_id=uuid.uuid4(),
            finding_id=uuid.uuid4(),
            reason="reason",
        )
    with pytest.raises(ValidationError):
        ReviewRequestCreate(submission_id=value, reason="reason")
    with pytest.raises(ValidationError):
        ReviewRequestCreate(
            submission_id=value,
            criterion_id=uuid.uuid4(),
            reason="  ",
        )
    with pytest.raises(ValidationError):
        ReviewRequestCreate(
            submission_id=value,
            criterion_id=uuid.uuid4(),
            reason="reason",
            storage_key="raw-ir",
        )
    with pytest.raises(ValidationError):
        ReviewRequestUpdate(status=ReviewRequestStatus.OPEN, response="reply")


def test_t016_model_and_response_are_allowlisted() -> None:
    table = Base.metadata.tables["review_requests"]
    assert {
        "published_result_id",
        "submission_id",
        "student_id",
        "criterion_version_id",
        "finding_id",
        "status",
        "reason",
        "response",
        "responded_by_user_id",
        "responded_at",
        "created_at",
        "updated_at",
    } <= set(table.columns.keys())
    assert set(ReviewRequestResponse.model_fields) == {
        "id",
        "published_result_id",
        "submission_id",
        "student_id",
        "criterion_id",
        "finding_id",
        "status",
        "reason",
        "response",
        "responded_by_user_id",
        "responded_at",
        "created_at",
        "updated_at",
    }
    indexes = {index.name: index for index in table.indexes}
    assert indexes["uq_review_requests_open_target"].unique
    assert (
        indexes["uq_review_requests_open_target"]
        .dialect_options["postgresql"]
        .get("where")
        is not None
    )


def test_t016_routes_and_migration_security_contract() -> None:
    schema = app.openapi()
    assert (
        "/api/v1/published-results/{published_result_id}/review-requests"
        in schema["paths"]
    )
    assert "/api/v1/courses/{course_id}/review-requests" in schema["paths"]
    assert "/api/v1/review-requests/{review_request_id}" in schema["paths"]
    assert (
        "post"
        in schema["paths"][
            "/api/v1/published-results/{published_result_id}/review-requests"
        ]
    )
    assert "get" in schema["paths"]["/api/v1/courses/{course_id}/review-requests"]
    assert {"get", "patch"} <= set(
        schema["paths"]["/api/v1/review-requests/{review_request_id}"]
    )

    source = MIGRATION.read_text(encoding="utf-8")
    tree = ast.parse(source)
    upgrade = _function(tree, "upgrade")
    downgrade = _function(tree, "downgrade")
    assert "SET search_path TO public" in ast.unparse(upgrade.body[0])
    assert "SET search_path TO public" in ast.unparse(downgrade.body[0])
    assert "audit_events" not in source
    assert "published_result_versions" in source
    assert "LOCK TABLE public.review_requests" in source
    assert "Refusing downgrade" in source
    for function in (upgrade, downgrade):
        for call in (
            node
            for node in ast.walk(function)
            if isinstance(node, ast.Call)
            and getattr(node.func, "attr", None) in {"create_table", "drop_table"}
        ):
            if getattr(call.func, "attr", None) == "create_table":
                assert any(
                    keyword.arg == "schema"
                    and isinstance(keyword.value, ast.Constant)
                    and keyword.value.value == "public"
                    for keyword in call.keywords
                )
