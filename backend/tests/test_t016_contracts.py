from __future__ import annotations

import ast
import asyncio
import uuid
from pathlib import Path
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy.exc import IntegrityError

import app.models  # noqa: F401
from app.api.routers import submissions as submissions_router
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


class _ConstraintViolation(Exception):
    def __init__(self, constraint_name: str) -> None:
        super().__init__(constraint_name)
        self.constraint_name = constraint_name


def test_t016_create_route_maps_only_open_target_conflict(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def scenario() -> None:
        payload = ReviewRequestCreate(
            submission_id=uuid.uuid4(),
            criterion_id=uuid.uuid4(),
            reason="reason",
        )
        duplicate_driver_error = Exception("duplicate")
        duplicate_driver_error.__cause__ = _ConstraintViolation(
            "uq_review_requests_open_target"
        )
        duplicate_error = IntegrityError("INSERT", {}, duplicate_driver_error)
        db = AsyncMock()
        monkeypatch.setattr(
            submissions_router.appeal_svc,
            "create_review_request",
            AsyncMock(side_effect=duplicate_error),
        )

        with pytest.raises(HTTPException) as duplicate:
            await submissions_router.create_review_request(
                uuid.uuid4(), payload, user=object(), db=db
            )
        assert duplicate.value.status_code == 409
        assert duplicate.value.detail == "Open review request already exists"
        db.rollback.assert_awaited_once()
        db.commit.assert_not_awaited()

        unrelated_error = IntegrityError(
            "INSERT", {}, _ConstraintViolation("fk_review_requests_submission")
        )
        unrelated_db = AsyncMock()
        submissions_router.appeal_svc.create_review_request.side_effect = (
            unrelated_error
        )
        with pytest.raises(IntegrityError) as unrelated:
            await submissions_router.create_review_request(
                uuid.uuid4(), payload, user=object(), db=unrelated_db
            )
        assert unrelated.value is unrelated_error
        unrelated_db.rollback.assert_not_awaited()

    asyncio.run(scenario())
