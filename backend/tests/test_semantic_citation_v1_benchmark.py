"""v1 AI-consensus semantic benchmark: verdict metrics and fixture invariants."""

from __future__ import annotations

import json

from scripts.semantic_citation_v1_benchmark import (
    _FIXTURE,
    EVIDENCE_LABELS,
    LABELS,
    _verdict_metrics,
)


def test_verdict_metrics_count_accusations_and_manual_review() -> None:
    metrics = _verdict_metrics(
        [
            ("SUPPORTED", "SUPPORTED"),
            ("PARTIALLY_SUPPORTED", "CONTRADICTED"),  # false accusation
            ("SUPPORTED", "IRRELEVANT"),  # false accusation
            ("SUPPORTED", "NEEDS_MANUAL_REVIEW"),  # not an accusation, not structured
            ("CONTRADICTED", "CONTRADICTED"),  # correct, not counted as support
            ("IRRELEVANT", "INSUFFICIENT_EVIDENCE"),
        ]
    )
    assert metrics["answered"] == 6
    assert metrics["false_accusation_rate"] == 0.5  # 2 of 4 supported/partial
    assert metrics["structured_success"] == round(5 / 6, 4)
    assert metrics["per_class_f1"]["CONTRADICTED"] == round(2 / 3, 4)
    assert metrics["per_class_f1"]["IRRELEVANT"] == 0.0
    assert metrics["confusion"]["SUPPORTED"] == {
        "SUPPORTED": 1,
        "IRRELEVANT": 1,
        "NEEDS_MANUAL_REVIEW": 1,
    }


def test_v1_fixture_is_ai_verified_with_disjoint_splits() -> None:
    fixture = json.loads(_FIXTURE.read_text(encoding="utf-8"))
    meta = fixture["annotation_set"]
    # AI labels are never reported as human gold; the set qualifies for the benchmark
    # gate only through rule v1.1 plus held-out confirmation (spec section 7).
    assert meta["annotation_status"] == "AI_CONSENSUS"
    assert meta["human_gold_pairs"] == 0
    assert meta["acceptance_rule"].startswith("v1.1")
    assert meta["heldout_agreement"] == round(
        sum(p["heldout_verdict"] == p["label"] for p in fixture["pairs"])
        / len(fixture["pairs"]),
        4,
    )
    source_ids = {source["source_id"] for source in fixture["sources"]}
    claims = {"dev": set(), "test": set()}
    for pair in fixture["pairs"]:
        assert pair["label"] in LABELS
        assert pair["source_id"] in source_ids
        if pair["label"] in EVIDENCE_LABELS and pair["origin"] == "synthetic":
            assert pair["evidence_quotes"], pair["pair_id"]
        claims[pair["split"]].add(pair["claim"])
    assert claims["dev"] and claims["test"]
    assert not claims["dev"] & claims["test"]
