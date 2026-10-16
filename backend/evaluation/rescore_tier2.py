"""Recompute an ablation run's tier 2 (retrieval) scores from its
``_details.json`` with the current rules, which add Context Precision@k at a
fixed denominator k = ``scoring.FIXED_K`` for every configuration. No chatbot,
LLM, embedding or database call:

    uv run python -m evaluation.rescore_tier2 \\
        evaluation/results/ablation_20261009_baseline_details.json \\
        --base evaluation/results/ablation_20261009_baseline_regrouped.json \\
        --golden original

- the chunks each case retrieved come from ``_details.json``;
- ``n_relevant_in_corpus`` (for the ceilings) is the value stored per case in
  the same file, computed by the run over the submission's whole corpus;
- document groups and every non-tier-2 number come from ``--base`` (an
  aggregates-only snapshot of the same run, e.g. its ``_regrouped.json``).

Before writing anything it recomputes the original-rule numbers and stops if
they differ from what the run stored, per case or in the base's aggregates.
Writes ``<base>_fixedk.json`` / ``.md`` next to the base.
"""

from __future__ import annotations

import argparse
import copy
import json
import math
import sys
from pathlib import Path
from typing import Any

from evaluation import scoring
from evaluation.golden import load_golden_set
from evaluation.report import render_markdown
from evaluation.run_ablation import (
    _aggregate_tier2,
    _chunk_like,
    _strip_case_content,
    tier2_case_scores,
)

# Original-rule numbers that must come out identical to what the run stored.
_CASE_KEYS = ("k", "precision", "recall", "precision_tol2", "recall_tol2")
_AGGREGATE_KEYS = (
    "n",
    "precision_at_k",
    "recall",
    "precision_ceiling",
    "precision_at_k_tol2",
    "recall_tol2",
)


class RescoreMismatchError(RuntimeError):
    """Recomputed original-rule scores differ from the stored ones."""


def _same(a: Any, b: Any) -> bool:
    if a is None or b is None:
        return a is b
    return math.isclose(a, b, rel_tol=0, abs_tol=1e-12)


def rescore(
    details: dict[str, Any], base: dict[str, Any], cases: dict[str, dict]
) -> dict[str, Any]:
    out = copy.deepcopy(base)
    groups = {prefix: doc["glue_group"] for prefix, doc in base["documents"].items()}
    for config, result in details["configs"].items():
        if not isinstance(result, dict) or not result.get("tier2"):
            continue
        stored = {row["case_id"]: row for row in result["tier2"]["per_case"]}
        rows = []
        for run in details["details"]["runs"][config]:
            if run["tier"] != 2 or run.get("error"):
                continue
            case = cases[run["case_id"]]
            previous = stored[run["case_id"]]
            row = tier2_case_scores(
                run["case_id"],
                groups[case["gold"]["document_version_id"][:8]],
                [_chunk_like(d) for d in run["retrieved"]],
                case["gold"]["relevant"],
                {
                    "": previous["n_relevant_in_corpus"],
                    "_tol2": previous["n_relevant_in_corpus_tol2"],
                },
            )
            for key in _CASE_KEYS:
                if not _same(row[key], previous[key]):
                    raise RescoreMismatchError(
                        f"{config}: case {len(rows) + 1} {key}: "
                        f"stored {previous[key]!r}, recomputed {row[key]!r}"
                    )
            rows.append(row)

        t2 = out["configs"][config]["tier2"]
        t2["all"] = _aggregate_tier2(rows)
        t2["by_group"] = {
            g: _aggregate_tier2([r for r in rows if r["group"] == g])
            for g in scoring.GROUPS
        }
        base_t2 = base["configs"][config]["tier2"]
        for name, expected in [("all", base_t2["all"]), *base_t2["by_group"].items()]:
            got = t2["all"] if name == "all" else t2["by_group"][name]
            for key in _AGGREGATE_KEYS:
                if key in expected and not _same(got[key], expected[key]):
                    raise RescoreMismatchError(
                        f"{config}/{name} {key}: base {expected[key]!r}, "
                        f"recomputed {got[key]!r}"
                    )

    out["label"] = f"{base.get('label', 'run')}_fixedk"
    out["tier2_rescored"] = (
        f"Context Precision@k thêm mẫu số cố định k={scoring.FIXED_K}; tính lại "
        "từ chunk đã truy hồi trong lần chạy gốc, không gọi lại chatbot/LLM."
    )
    return _strip_case_content(out)


def main(details_path: Path, base_path: Path, golden: str | None) -> int:
    details = json.loads(details_path.read_text(encoding="utf-8"))
    base = json.loads(base_path.read_text(encoding="utf-8"))
    cases = {c["id"]: c for c in load_golden_set(golden)}
    public = rescore(details, base, cases)
    public["tier2_rescored_from"] = [details_path.name, base_path.name]
    stem = base_path.name.removesuffix(".json") + "_fixedk"
    out_dir = base_path.parent
    (out_dir / f"{stem}.json").write_text(
        json.dumps(public, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (out_dir / f"{stem}.md").write_text(render_markdown(public), encoding="utf-8")
    print(f"wrote {stem}.json / .md")
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("details", type=Path)
    parser.add_argument("--base", type=Path, required=True)
    parser.add_argument("--golden", default=None)
    args = parser.parse_args()
    sys.exit(main(args.details, args.base, args.golden))
