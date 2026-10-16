from __future__ import annotations

import json
from pathlib import Path

import pytest

from evaluation.report import render_markdown
from evaluation.rescore_tier2 import RescoreMismatchError, rescore
from evaluation.run_ablation import _aggregate_tier2, tier2_case_scores
from evaluation.scoring import ChunkLike

GOLD = [{"page": 5, "keyword": "benchmarks"}]
RESULTS = Path(__file__).resolve().parents[1] / "results"
VERSION = "aaaaaaaa-0000-0000-0000-000000000000"


def _chunk(page: int, section: str) -> dict:
    return {
        "chunk_id": f"c-{page}-{section}",
        "document_version_id": VERSION,
        "page_start": page,
        "page_end": page,
        "section_path": section,
        "text": "x",
    }


def _like(d: dict) -> ChunkLike:
    return ChunkLike(d["page_start"], d["page_end"], d["section_path"], d["text"])


# rule_only-like: 2 chunks back, 1 relevant. hybrid-like: 6 back, 1 relevant.
FEW = [_chunk(5, "Benchmarks"), _chunk(9, "Other")]
SIX = [_chunk(5, "Benchmarks")] + [_chunk(9, f"Other {i}") for i in range(5)]


def test_case_scores_keep_old_precision_and_add_fixed_k() -> None:
    row = tier2_case_scores(
        "T2-X", "low", [_like(d) for d in FEW], GOLD, {"": 1, "_tol2": 1}
    )
    assert row["k"] == 2
    assert row["precision"] == 0.5, "old rule: denominator = chunks returned"
    assert row["precision_fixed"] == 1 / 6
    assert row["ceiling"] == 0.5, "old ceiling uses the returned k"
    assert row["ceiling_fixed"] == 1 / 6
    assert row["recall"] == 1.0


def test_aggregate_reports_both_precisions() -> None:
    rows = [
        tier2_case_scores(
            "a", "low", [_like(d) for d in FEW], GOLD, {"": 1, "_tol2": 1}
        ),
        tier2_case_scores(
            "b", "low", [_like(d) for d in SIX], GOLD, {"": 1, "_tol2": 1}
        ),
    ]
    agg = _aggregate_tier2(rows)
    assert agg["precision_at_k"] == pytest.approx((0.5 + 1 / 6) / 2)
    assert agg["precision_at_k_fixed"] == pytest.approx(1 / 6)
    assert agg["precision_ceiling_fixed"] == pytest.approx(1 / 6)
    assert agg["precision_vs_ceiling_fixed"] == pytest.approx(1.0)


def _details(config_runs: dict[str, list[dict]]) -> dict:
    configs = {}
    runs = {}
    for config, retrieved in config_runs.items():
        k = len(retrieved)
        per_case = [
            {
                "case_id": "T2-X",
                "k": k,
                "group": "high",  # stale grouping: rescore must use the base's
                "precision": 1 / k,
                "recall": 1.0,
                "n_relevant_in_corpus": 1,
                "ceiling": 1 / k,
                "precision_tol2": 1 / k,
                "recall_tol2": 1.0,
                "n_relevant_in_corpus_tol2": 1,
                "ceiling_tol2": 1 / k,
            }
        ]
        configs[config] = {"tier2": {"per_case": per_case}}
        runs[config] = [
            {"case_id": "T2-X", "tier": 2, "error": None, "retrieved": retrieved}
        ]
    return {"configs": configs, "details": {"runs": runs}}


def _base(config_runs: dict[str, list[dict]]) -> dict:
    configs = {}
    for config, retrieved in config_runs.items():
        k = len(retrieved)
        old = {
            "n": 1,
            "precision_at_k": 1 / k,
            "recall": 1.0,
            "precision_ceiling": 1 / k,
            "precision_at_k_tol2": 1 / k,
            "recall_tol2": 1.0,
        }
        configs[config] = {
            "tier2": {"all": dict(old), "by_group": {"low": dict(old)}, "n_errors": 0}
        }
    return {
        "label": "baseline_regrouped",
        "documents": {VERSION[:8]: {"glue_group": "low"}},
        "configs": configs,
    }


CASES = {"T2-X": {"gold": {"document_version_id": VERSION, "relevant": GOLD}}}


def test_rescore_adds_fixed_k_without_changing_old_numbers() -> None:
    config_runs = {"rule_only": FEW, "hybrid": SIX}
    out = rescore(_details(config_runs), _base(config_runs), CASES)

    rule = out["configs"]["rule_only"]["tier2"]
    hybrid = out["configs"]["hybrid"]["tier2"]
    assert rule["all"]["precision_at_k"] == 0.5
    assert rule["all"]["precision_at_k_fixed"] == pytest.approx(1 / 6)
    assert hybrid["all"]["precision_at_k_fixed"] == pytest.approx(1 / 6)
    assert set(rule["by_group"]) >= {"low"} and rule["by_group"]["low"]["n"] == 1
    assert rule["by_group"]["high"]["n"] == 0, "grouping comes from the base"
    assert "per_case" not in rule, "public output keeps aggregates only"
    assert out["label"] == "baseline_regrouped_fixedk"


def test_rescore_refuses_when_recomputed_old_scores_differ() -> None:
    config_runs = {"hybrid": SIX}
    details = _details(config_runs)
    details["configs"]["hybrid"]["tier2"]["per_case"][0]["precision"] = 0.5
    with pytest.raises(RescoreMismatchError):
        rescore(details, _base(config_runs), CASES)


def test_rescore_refuses_when_base_aggregates_differ() -> None:
    config_runs = {"hybrid": SIX}
    base = _base(config_runs)
    base["configs"]["hybrid"]["tier2"]["all"]["precision_at_k"] = 0.9
    with pytest.raises(RescoreMismatchError):
        rescore(_details(config_runs), base, CASES)


def test_report_labels_both_precision_columns() -> None:
    snapshot = json.loads(
        (RESULTS / "ablation_20261009_baseline_regrouped.json").read_text("utf-8")
    )
    old_md = render_markdown(snapshot)  # snapshots without fixed-k still render
    assert "mẫu số = số chunk trả về" in old_md

    for config in snapshot["configs"].values():
        if not isinstance(config, dict) or "tier2" not in config:
            continue
        t2 = config["tier2"]
        for agg in [t2["all"], *t2["by_group"].values()]:
            agg.update(
                precision_at_k_fixed=0.123,
                precision_ceiling_fixed=0.2,
                precision_vs_ceiling_fixed=0.615,
            )
    md = render_markdown(snapshot)
    assert "mẫu số cố định k=6" in md
    assert "mẫu số = số chunk trả về" in md
    assert "12.3%" in md
