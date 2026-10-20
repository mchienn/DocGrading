"""v1 AI-consensus semantic benchmark: verdict metrics and fixture invariants."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from app.models.enums import LLMProvider
from app.services import semantic_gate
from app.services.text_encoder import TextEncoder
from scripts.semantic_citation_v1_benchmark import (
    _FIXTURE,
    EVIDENCE_LABELS,
    LABELS,
    _verdict_metrics,
    _write_gate_entry,
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


def _write_entry(path: Path, approved_by: str | None = None) -> None:
    _write_gate_entry(
        path,
        provider=LLMProvider.GEMINI,
        model_id="gemini-3.8-flash",
        encoder=TextEncoder("x", "BAAI/bge-m3", rerank_url="x"),
        fixture=_FIXTURE,
        pairs=884,
        stage3={"hit_at_3": 0.94981, "retrieval": "precomputed"},
        stage4={
            "anchor_completeness": 1.0,
            "structured_success": 0.9968,
            "macro_f1": 0.9186,
            "false_accusation_rate": 0.006,
        },
        approved_by=approved_by,
    )


def test_gate_entry_is_written_pending_then_replaced_when_approved(
    tmp_path: Path,
) -> None:
    path = tmp_path / "gates.json"
    other = {"approval_id": "other", "configuration": {"model_id": "other"}}
    path.write_text(json.dumps({"schema_version": 1, "approvals": [other]}))

    _write_entry(path)
    pending = semantic_gate.load_approvals(path)
    [entry] = pending
    assert entry.approval_id.startswith(
        "gemini-gemini-3.8-flash-" + entry.benchmark.measured_at.isoformat() + "-"
    )
    assert not pending[0].approved
    assert pending[0].benchmark.hit_at_3 == 0.9498
    assert json.loads(path.read_text())["approvals"][0] == other  # kept verbatim

    _write_entry(path, approved_by="Owner")
    entries = semantic_gate.load_approvals(path)
    assert len(entries) == 1  # same configuration replaced, not duplicated
    assert entries[0].approved and entries[0].approved_by == "Owner"
    assert entries[0].meets_thresholds


def test_shipped_gate_fixture_hash_matches_committed_fixture() -> None:
    committed = _FIXTURE.read_bytes().replace(b"\r\n", b"\n")
    digests = {a.benchmark.fixture_sha256 for a in semantic_gate.load_approvals()}
    assert digests == {hashlib.sha256(committed).hexdigest()}
