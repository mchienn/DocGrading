"""Build ``citation_labels.jsonl``: ~40 (question, answer, cited chunk) samples
for a human to label, taken from an ablation run's ``_details.json``.

    uv run python -m evaluation.calibration.build_label_set \\
        evaluation/results/ablation_<date>_baseline_details.json

Samples are picked WITHOUT looking at the LLM-judge verdicts (a sample
chosen by verdict would bias the agreement/kappa estimate): round-robin over
(document, configuration) so every document and both generating
configurations are represented, then by citation position. The LLM verdict
is deliberately NOT written into the label file, so the labeler isn't
anchored by it; ``calibrate_judge.py`` joins it back from the details file.

Refuses to overwrite a label file that already contains any human label.
"""

from __future__ import annotations

import argparse
import json
import random
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

from evaluation.golden import golden_path

LABELS_PATH = Path(__file__).resolve().parent / "citation_labels.jsonl"
TARGET = 40
SEED = 20261009


def candidates(details: dict[str, Any]) -> list[dict[str, Any]]:
    docs = details["documents"]
    out = []
    for config, runs in details["details"]["runs"].items():
        for run in runs:
            if not run["judge_citations"]:
                continue
            retrieved = {d["chunk_id"]: d for d in run["retrieved"]}
            for cit in run["judge_citations"]:
                chunk = retrieved.get(cit["chunk_id"])
                if chunk is None or not cit["claim"]:
                    continue
                doc_key = chunk["document_version_id"][:8]
                out.append(
                    {
                        "config": config,
                        "case_id": run["case_id"],
                        "question": None,  # filled from the golden set below
                        "answer": run["reply"],
                        "citation_number": cit["number"],
                        "claim": cit["claim"],
                        "chunk_id": cit["chunk_id"],
                        "document_version": doc_key,
                        "page_start": chunk["page_start"],
                        "page_end": chunk["page_end"],
                        "section_path": chunk["section_path"],
                        "chunk_text": chunk["text"],
                        "glue_group": docs.get(doc_key, {}).get("glue_group"),
                    }
                )
    return out


def pick(pool: list[dict[str, Any]], target: int) -> list[dict[str, Any]]:
    rng = random.Random(SEED)
    buckets: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for c in pool:
        buckets[(c["document_version"], c["config"])].append(c)
    for bucket in buckets.values():
        rng.shuffle(bucket)
        bucket.sort(key=lambda c: c["citation_number"] > 2)  # stable: early [n] first
    keys = sorted(buckets)
    rng.shuffle(keys)
    picked: list[dict[str, Any]] = []
    while len(picked) < target and any(buckets[k] for k in keys):
        for key in keys:
            if buckets[key] and len(picked) < target:
                picked.append(buckets[key].pop(0))
    return picked


def main(details_path: Path, golden_path: Path) -> int:
    if LABELS_PATH.exists():
        existing = [
            json.loads(line)
            for line in LABELS_PATH.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        if any(isinstance(s.get("human_label"), bool) for s in existing):
            print(f"{LABELS_PATH} already has human labels - not overwriting.")
            return 1
    details = json.loads(details_path.read_text(encoding="utf-8"))
    questions = {
        c["id"]: c["question"]
        for c in (
            json.loads(line)
            for line in golden_path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        )
    }
    pool = candidates(details)
    samples = pick(pool, TARGET)
    LABELS_PATH.parent.mkdir(parents=True, exist_ok=True)
    with LABELS_PATH.open("w", encoding="utf-8") as f:
        for i, s in enumerate(samples, start=1):
            s["question"] = questions[s["case_id"]]
            row = {
                "id": f"CAL-{i:02d}",
                "source_run": details_path.name,
                **s,
                "human_label": None,
                "human_note": "",
            }
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
    by_config: dict[str, int] = defaultdict(int)
    by_group: dict[str, int] = defaultdict(int)
    for s in samples:
        by_config[s["config"]] += 1
        by_group[str(s["glue_group"])] += 1
    print(
        f"wrote {len(samples)} samples (pool {len(pool)}) to {LABELS_PATH}; "
        f"documents={len({s['document_version'] for s in samples})}, "
        f"by config={dict(by_config)}, by glue group={dict(by_group)}"
    )
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("details", type=Path)
    parser.add_argument(
        "--golden",
        default=None,
        help="anonymized (default) | original | <path>; or set EVAL_GOLDEN_SET",
    )
    args = parser.parse_args()
    sys.exit(main(args.details, golden_path(args.golden)))
