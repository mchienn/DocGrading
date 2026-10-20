"""Tests for Citation Semantic Support benchmark and annotation candidate fixture."""

from __future__ import annotations

import copy
import json
from collections import Counter
from typing import Any

import pytest

from scripts.semantic_citation_benchmark import (
    _DEFAULT_ANNOTATIONS,
    compute_prediction_metrics,
    evaluate_quality_gate,
    run_benchmark,
    run_stage1_extraction,
    run_stage2_resolution,
    run_stage3_retrieval,
    validate_fixture,
)


def _load_fixture() -> dict[str, Any]:
    assert _DEFAULT_ANNOTATIONS.exists(), f"Fixture missing at {_DEFAULT_ANNOTATIONS}"
    return json.loads(_DEFAULT_ANNOTATIONS.read_text(encoding="utf-8"))


def test_fixture_structure_and_invariants() -> None:
    """Validate 120-candidate fixture metadata, counts, and bilingual ratio."""
    data = _load_fixture()

    assert data.get("schema_version") == 1
    ann = data.get("annotation_set", {})
    assert ann.get("annotation_status") in {"AI_DRAFT", "SYNTHETIC_DRAFT"}
    assert ann.get("independent_human_review") is False
    assert ann.get("human_gold_pairs") == 0
    assert ann.get("double_review_required_count", 0) >= 24

    candidates = data.get("candidates", [])
    assert len(candidates) == 120

    # Unique pair IDs
    pair_ids = [cand.get("pair_id") for cand in candidates]
    assert len(set(pair_ids)) == 120
    assert all(pid.startswith("pair_") for pid in pair_ids)

    # Bilingual ratio: >= 80% vi_en
    vi_en_count = sum(1 for c in candidates if c.get("language_pair") == "vi_en")
    assert vi_en_count >= 96
    assert vi_en_count / 120 >= 0.80

    # Double review required: >= 24 (20%)
    double_review_count = sum(
        1 for c in candidates if c.get("double_review_required") is True
    )
    assert double_review_count >= 24
    assert double_review_count / 120 >= 0.20

    # 15 balanced scenarios, exactly 8 each
    scenario_counts = Counter(c.get("scenario") for c in candidates)
    assert len(scenario_counts) == 15
    for sc, count in scenario_counts.items():
        assert count == 8, f"Scenario {sc} has count {count}, expected 8"

    multi = [
        candidate
        for candidate in candidates
        if candidate.get("scenario") == "multiple_citations_one_claim"
    ]
    assert len(multi) == 8
    assert all(
        len(candidate["expected_extraction"]["expected_pairs"]) == 2
        for candidate in multi
    )
    assert all(
        {
            (mention["id"], reference_id)
            for mention in candidate["citation_report"]["mentions"]
            for reference_id in mention["reference_ids"]
        }
        == {
            (pair["mention_id"], pair["reference_id"])
            for pair in candidate["expected_extraction"]["expected_pairs"]
        }
        for candidate in multi
    )

    # Provenance and draft annotations on every candidate
    for cand in candidates:
        draft = cand.get("draft_annotation", {})
        assert draft.get("status") == "AI_DRAFT"
        assert draft.get("provenance")
        assert draft.get("verdict")
        assert draft.get("reason_code")


def test_fixture_schema_strict_validation() -> None:
    """Verify validator rejects malformed, undersized, or invalid fixture."""
    data = _load_fixture()

    # Valid fixture passes
    summary = validate_fixture(data)
    assert summary["total"] == 120
    assert summary["expected_pair_count"] == 128
    assert summary["multi_pair_candidate_count"] == 8
    assert summary["vi_en_ratio"] >= 0.80
    assert summary["double_review_count"] >= 24

    # Invalid schema_version
    bad_ver = copy.deepcopy(data)
    bad_ver["schema_version"] = 2
    with pytest.raises(ValueError, match="Expected schema_version=1"):
        validate_fixture(bad_ver)

    # Claiming human review or gold pairs in draft fixture
    bad_gold = copy.deepcopy(data)
    bad_gold["annotation_set"]["human_gold_pairs"] = 10
    with pytest.raises(ValueError, match="human_gold_pairs must be strictly 0"):
        validate_fixture(bad_gold)

    bad_review = copy.deepcopy(data)
    bad_review["annotation_set"]["independent_human_review"] = True
    with pytest.raises(ValueError, match="independent_human_review must be false"):
        validate_fixture(bad_review)

    # Duplicate pair_id
    bad_dupe = copy.deepcopy(data)
    bad_dupe["candidates"][1]["pair_id"] = bad_dupe["candidates"][0]["pair_id"]
    with pytest.raises(ValueError, match="Duplicate pair_id"):
        validate_fixture(bad_dupe)

    # Undersized fixture (< 100)
    bad_size = copy.deepcopy(data)
    bad_size["candidates"] = bad_size["candidates"][:50]
    with pytest.raises(ValueError, match="Candidate count 50 outside required range"):
        validate_fixture(bad_size)

    # Missing evidence passage reference
    bad_ev = copy.deepcopy(data)
    bad_ev["candidates"][0]["expected_retrieval"]["evidence_passage_ids"] = [
        "nonexistent-passage-id"
    ]
    with pytest.raises(
        ValueError, match="evidence passage 'nonexistent-passage-id' not found"
    ):
        validate_fixture(bad_ev)
    bad_multi = copy.deepcopy(data)
    bad_multi["candidates"][80]["expected_extraction"].pop("expected_pairs")
    with pytest.raises(
        ValueError, match="multi-citation scenario must declare expected_pairs"
    ):
        validate_fixture(bad_multi)


def test_benchmark_stages_execution_without_predictions() -> None:
    """Exercise stage 1-3 execution without predictions; verify stage 4/5."""
    data = _load_fixture()
    candidates = data["candidates"]

    # Stage 1
    st1 = run_stage1_extraction(candidates)
    assert st1["candidate_count"] == 120
    assert st1["total"] == 128
    assert st1["expected_pair_count"] == 128
    assert st1["predicted_pair_count"] == 128
    assert st1["tp"] == 128
    assert st1["fp"] == 0
    assert st1["fn"] == 0
    assert st1["attribution_correct"] == 128
    assert st1["attribution_total"] == 128
    assert st1["attribution_accuracy"] == 1.0

    # Stage 2
    st2 = run_stage2_resolution(candidates)
    assert st2["total"] == 120
    assert st2["available_count"] == 112
    assert st2["unavailable_count"] == 8
    assert st2["full_text_count"] == 104
    assert st2["abstract_only_count"] == 8
    assert 0.0 <= st2["precision"] <= 1.0
    assert 0.0 <= st2["full_text_coverage"] <= 1.0

    # Stage 3
    st3 = run_stage3_retrieval(candidates)
    assert st3["evaluated_count"] == 104
    assert 0.0 <= st3["hit_at_3"] <= 1.0
    assert 0.0 <= st3["recall_at_3"] <= 1.0
    assert 0.0 <= st3["mrr_at_3"] <= 1.0
    assert 0.0 <= st3["anchor_top1_accuracy"] <= 1.0
    assert "cross_lingual" in st3
    assert "monolingual" in st3
    assert st3["cross_lingual"]["count"] == 91
    assert st3["monolingual"]["count"] == 13

    # End-to-end benchmark run without predictions
    report, results = run_benchmark(_DEFAULT_ANNOTATIONS)
    assert results["stage4"]["status"] == "NOT_MEASURED"
    assert results["stage5"]["model_calls"] == 0
    assert results["stage5"]["input_tokens"] == 0
    assert results["stage5"]["output_tokens"] == 0
    assert results["stage5"]["model_cost"] is None
    assert results["quality_gate"]["passed"] is False
    assert "BLOCKED" in report


def test_quality_gate_cannot_be_spoofed_by_draft_labels() -> None:
    """Ensure quality gate remains BLOCKED even if synthetic draft is perfect."""
    data = _load_fixture()
    summary = validate_fixture(data)
    candidates = data["candidates"]

    st1 = run_stage1_extraction(candidates)
    st2 = run_stage2_resolution(candidates)
    st3 = run_stage3_retrieval(candidates)

    # Mock perfect draft predictions
    perfect_preds = {
        cand["pair_id"]: cand["draft_annotation"]["verdict"] for cand in candidates
    }
    st4 = compute_prediction_metrics(candidates, perfect_preds)
    assert st4["accuracy"] == 1.0
    assert st4["macro_f1"] == 1.0

    gate_eval = evaluate_quality_gate(summary, st1, st2, st3, st4)
    assert gate_eval["passed"] is False
    assert gate_eval["gate"]["passed"] is False
    assert len(gate_eval["blockers"]) >= 4
    assert any("human_gold_pairs=0" in b for b in gate_eval["blockers"])
    assert any("domain_approved=false" in b for b in gate_eval["blockers"])


def test_prediction_metrics_computation() -> None:
    """Verify accuracy, macro-F1, per-class metrics, confusion matrix, and FAR."""
    data = _load_fixture()
    candidates = data["candidates"]

    # 1. Perfect predictions
    perfect = {
        cand["pair_id"]: cand["draft_annotation"]["verdict"] for cand in candidates
    }
    res_perfect = compute_prediction_metrics(candidates, perfect)
    assert res_perfect["accuracy"] == 1.0
    assert res_perfect["macro_f1"] == 1.0
    assert res_perfect["false_accusation_rate"] == 0.0
    for _cls, m in res_perfect["per_class"].items():
        assert m["precision"] == 1.0
        assert m["recall"] == 1.0
        assert m["f1"] == 1.0

    # 2. Imperfect predictions with false accusations
    imperfect = copy.deepcopy(perfect)
    # Turn supported candidates into CONTRADICTED
    for cand in candidates[:10]:
        if cand["draft_annotation"]["verdict"] in {"SUPPORTED", "PARTIALLY_SUPPORTED"}:
            imperfect[cand["pair_id"]] = "CONTRADICTED"

    res_imp = compute_prediction_metrics(candidates, imperfect)
    assert res_imp["accuracy"] < 1.0
    assert res_imp["macro_f1"] < 1.0
    assert res_imp["false_accusation_rate"] > 0.0

    # 3. Missing prediction IDs raise ValueError
    missing = copy.deepcopy(perfect)
    del missing[candidates[0]["pair_id"]]
    with pytest.raises(ValueError, match="Predictions missing"):
        compute_prediction_metrics(candidates, missing)


def test_report_generation_deterministic() -> None:
    """Verify markdown report generation contains all required sections."""
    report, _ = run_benchmark(_DEFAULT_ANNOTATIONS)

    assert "# Citation Semantic Support v1 Benchmark Report" in report
    assert "## Quality Gate Outcome" in report
    assert "**BLOCKED**" in report
    assert "## Candidate Dataset Composition" in report
    assert "## Stage 1: Claim Extraction & Citation Scope Attribution" in report
    assert "## Stage 2: Source Resolution & Availability" in report
    assert "## Stage 3: Lexical Passage Retrieval (BM25)" in report
    assert "## Stage 4: Prediction & Verdict Classification" in report
    assert "## Stage 5: End-to-End System Performance & Telemetry" in report
    assert "## Errors and Known Limits" in report
    assert "## Reproduce" in report
    assert "Expected claim-reference pairs: **128** across 120 candidates" in report
    assert "| Claim Extraction | 128 | 0 | 0 | 100.00% | 100.00% | 100.00% |" in report
    assert "Mean Reciprocal Rank (MRR@3)" in report
