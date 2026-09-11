from __future__ import annotations

import ast
import uuid
from pathlib import Path

import pytest
from pydantic import ValidationError

import app.models  # noqa: F401
from app.api.schemas_submission import (
    BBox,
    EvidenceResponse,
    ReviewDecisionRequest,
    ReviewDraftRequest,
)
from app.db.base import Base

MIGRATION = (
    Path(__file__).parents[1]
    / "alembic"
    / "versions"
    / "20260910_0009_submission_review.py"
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


def test_bbox_uses_document_ir_coordinates_and_rejects_invalid_values() -> None:
    bbox = BBox.model_validate({"x0": 0, "top": 1, "x1": 10, "bottom": 20})
    assert bbox.model_dump() == {"x0": 0.0, "top": 1.0, "x1": 10.0, "bottom": 20.0}
    for invalid in (
        {"x0": 0, "top": 2, "x1": 1, "bottom": 1},
        {"x0": -1, "top": 0, "x1": 1, "bottom": 1},
        {"x0": 0, "top": 1, "x1": float("inf"), "bottom": 2},
    ):
        with pytest.raises(ValidationError):
            BBox.model_validate(invalid)


def test_decision_shape_allows_reason_only_when_service_needs_it() -> None:
    finding_id = uuid.uuid4()
    edit = ReviewDecisionRequest(
        finding_id=finding_id,
        decision="EDIT",
        edited_description="Corrected finding",
    )
    assert edit.reason is None
    accepted = ReviewDecisionRequest(
        finding_id=finding_id,
        decision="ACCEPT",
        reason="Restore original scored proposal",
    )
    assert accepted.decision.value == "ACCEPT"
    with pytest.raises(ValidationError):
        ReviewDecisionRequest(finding_id=finding_id, decision="EDIT")
    with pytest.raises(ValidationError):
        ReviewDecisionRequest(
            finding_id=finding_id,
            decision="REJECT",
            final_score=0,
        )
    with pytest.raises(ValidationError):
        ReviewDecisionRequest(
            finding_id=finding_id,
            decision="EDIT",
            final_score="1.005",
            reason="Too precise",
        )


def test_draft_rejects_duplicate_finding_decisions() -> None:
    finding_id = uuid.uuid4()
    with pytest.raises(ValidationError):
        ReviewDraftRequest(
            document_version_id=uuid.uuid4(),
            revision=1,
            decisions=[
                {"finding_id": finding_id, "decision": "ACCEPT"},
                {"finding_id": finding_id, "decision": "REJECT"},
            ],
        )


def test_evidence_response_exposes_only_ir_reference_geometry() -> None:
    assert set(EvidenceResponse.model_fields) == {
        "document_ir_id",
        "element_id",
        "page_number",
        "bbox",
    }


def test_review_model_metadata_matches_t011_tables() -> None:
    expected = {
        "findings",
        "evidence_anchors",
        "review_locks",
        "review_drafts",
        "review_decisions",
    }
    assert expected <= set(Base.metadata.tables)
    evidence = Base.metadata.tables["evidence_anchors"]
    assert set(evidence.columns.keys()) == {
        "id",
        "finding_id",
        "document_ir_id",
        "element_id",
        "page_number",
    }
    assert "bbox" not in evidence.columns
    draft = Base.metadata.tables["review_drafts"]
    assert "document_version_id" in draft.columns


def test_migration_enforces_sc1_sc2_sc3_and_downgrade_guard() -> None:
    source = MIGRATION.read_text(encoding="utf-8")
    tree = ast.parse(source)
    upgrade = _function(tree, "upgrade")
    downgrade = _function(tree, "downgrade")

    assert "SET search_path TO public" in ast.unparse(upgrade.body[0])
    assert "SET search_path TO public" in ast.unparse(downgrade.body[0])
    assert "audit_events" not in source

    for function in (upgrade, downgrade):
        for call in (node for node in ast.walk(function) if isinstance(node, ast.Call)):
            operation = getattr(call.func, "attr", None)
            if operation not in {
                "create_table",
                "create_index",
                "drop_table",
                "drop_index",
            }:
                continue
            assert any(
                keyword.arg == "schema"
                and isinstance(keyword.value, ast.Constant)
                and keyword.value.value == "public"
                for keyword in call.keywords
            ), f"SC-3 violation: {operation} must use public schema"

    foreign_keys = [
        node
        for node in ast.walk(upgrade)
        if isinstance(node, ast.Call)
        and getattr(node.func, "attr", None) == "ForeignKeyConstraint"
    ]
    assert foreign_keys
    assert all("public." in ast.unparse(call) for call in foreign_keys)
    assert "LOCK TABLE public.review_decisions" in source
    assert "Refusing downgrade: public." in source
