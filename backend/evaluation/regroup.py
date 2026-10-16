"""Recompute an ablation run's per-group tables with the current document
grouping (``scoring.document_group``: English documents -> "en", Vietnamese
ones by glue rate), from its ``_details.json`` - no chatbot or LLM call.

    POSTGRES_DB=docgrading_test uv run python -m evaluation.regroup \\
        evaluation/results/ablation_20261009_baseline_details.json --golden original

Reads document chunk text from the database (read-only) to classify the
documents. ``--golden`` must name the golden set whose case ids the run used.
Writes ``<run>_regrouped.json`` / ``.md`` next to the run (aggregates only).
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from dataclasses import fields
from pathlib import Path
from typing import Any

from app.db.session import _engine
from evaluation import scoring
from evaluation.golden import golden_path, load_golden_set
from evaluation.report import render_markdown
from evaluation.run_ablation import (
    CaseRun,
    _aggregate_tier2,
    _aggregate_tier3,
    _strip_case_content,
    doc_of_case,
    load_documents,
)

_CASE_RUN_FIELDS = {f.name for f in fields(CaseRun)}


async def regroup(details_path: Path, golden: str | None) -> dict[str, Any]:
    snapshot = json.loads(details_path.read_text(encoding="utf-8"))
    cases_list = [
        c
        for c in load_golden_set(golden)
        if not c["gold"].get("cache_correctness_case")
    ]
    cases = {c["id"]: c for c in cases_list}
    try:
        docs = await load_documents(cases_list)
    finally:
        await _engine().dispose()

    for config, result in snapshot["configs"].items():
        if config == "cache" or not isinstance(result, dict):
            continue
        t2 = result["tier2"]
        for row in t2["per_case"]:
            row["group"] = docs[cases[row["case_id"]]["gold"]["document_version_id"]][
                "glue_group"
            ]
        t2["by_group"] = {
            g: _aggregate_tier2([r for r in t2["per_case"] if r["group"] == g])
            for g in scoring.GROUPS
        }
        if result.get("tier3_ask") is None:
            continue
        runs = [
            CaseRun(**{k: v for k, v in r.items() if k in _CASE_RUN_FIELDS})
            for r in snapshot["details"]["runs"][config]
            if r["tier"] == 3 and r["intent_expected"] == "ASK_ABOUT_REQUIREMENT"
        ]

        def group(run: CaseRun) -> str:
            version = doc_of_case(cases[run.case_id], docs)
            return docs[version]["glue_group"] if version else "unknown"

        result["tier3_ask"]["by_group"] = {
            g: _aggregate_tier3([r for r in runs if group(r) == g])
            for g in scoring.GROUPS
        }

    snapshot["documents"] = {
        version[:8]: {
            "glue_rate": doc["glue"]["rate"],
            "vi_words": doc["glue"]["vi_words"],
            "language": doc["language"],
            "glue_group": doc["glue_group"],
            "n_chunks": len(doc["corpus"]),
        }
        for version, doc in docs.items()
    }
    snapshot["label"] = f"{snapshot.get('label', 'run')}_regrouped"
    snapshot["regrouped_from"] = details_path.name
    snapshot["golden_set"] = golden_path(golden).name
    snapshot.pop("details", None)
    return _strip_case_content(snapshot)


def main(details_path: Path, golden: str | None) -> int:
    public = asyncio.run(regroup(details_path, golden))
    stem = details_path.name.removesuffix("_details.json") + "_regrouped"
    out_dir = details_path.parent
    (out_dir / f"{stem}.json").write_text(
        json.dumps(public, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (out_dir / f"{stem}.md").write_text(render_markdown(public), encoding="utf-8")
    print(f"wrote {stem}.json / .md")
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("details", type=Path)
    parser.add_argument("--golden", default=None)
    args = parser.parse_args()
    sys.exit(main(args.details, args.golden))
