"""Add synthetic negative samples to ``citation_labels.jsonl``.

    uv run python -m evaluation.calibration.add_synthetic_negatives

Each synthetic sample copies a real sample's question, answer and cited
sentence, but swaps the cited chunk for one that does not support it:

- ``other_document``: a chunk from a different submission;
- ``same_document_other_section``: a chunk of the same submission from a
  different top-level section, at least 3 pages away.

Both kinds also require low word overlap with the claim (< 20% of the
claim's content words appear in the replacement chunk), so the swap is
"clearly unsupported" by construction, not by anyone's judgement.

All samples (real + synthetic) are shuffled and renumbered, so neither the
order nor the id gives a synthetic one away. Which ids are synthetic is
written only to ``evaluation/private/calibration_key.jsonl`` (git-ignored).
Refuses to run if any sample already has a human label.
"""

from __future__ import annotations

import argparse
import json
import random
import sys
from collections import Counter
from pathlib import Path
from typing import Any

from evaluation.scoring import fold

CALIBRATION_DIR = Path(__file__).resolve().parent
LABELS_PATH = CALIBRATION_DIR / "citation_labels.jsonl"
RESULTS_DIR = CALIBRATION_DIR.parent / "results"
KEY_PATH = CALIBRATION_DIR.parent / "private" / "calibration_key.jsonl"
SEED = 20261011
N_OTHER_DOCUMENT = 7
N_SAME_DOCUMENT = 7
MAX_OVERLAP = 0.2
MIN_PAGE_GAP = 3


def _content_words(text: str) -> set[str]:
    return {w for w in fold(text).replace("[", " ").split() if len(w) >= 4}


def overlap(claim: str, chunk_text: str) -> float:
    words = _content_words(claim)
    if not words:
        return 0.0
    haystack = "".join(fold(chunk_text).split())
    return sum(1 for w in words if w in haystack) / len(words)


def _top_section(path: str | None) -> str:
    return (path or "").split(" > ", 1)[0].strip().lower()


def chunk_pool(details: dict[str, Any]) -> list[dict[str, Any]]:
    """Every distinct chunk any configuration retrieved in the run."""
    pool: dict[str, dict[str, Any]] = {}
    for runs in details["details"]["runs"].values():
        for run in runs:
            for chunk in run["retrieved"]:
                pool.setdefault(chunk["chunk_id"], chunk)
    return sorted(pool.values(), key=lambda c: c["chunk_id"])


def make_negative(
    sample: dict[str, Any],
    pool: list[dict[str, Any]],
    kind: str,
    groups: dict[str, str],
    rng: random.Random,
) -> dict[str, Any] | None:
    doc = sample["document_version"]
    if kind == "other_document":
        candidates = [c for c in pool if c["document_version_id"][:8] != doc]
    else:
        candidates = [
            c
            for c in pool
            if c["document_version_id"][:8] == doc
            and c["chunk_id"] != sample["chunk_id"]
            and _top_section(c["section_path"]) != _top_section(sample["section_path"])
            and min(
                abs(c["page_start"] - sample["page_end"]),
                abs(sample["page_start"] - c["page_end"]),
            )
            >= MIN_PAGE_GAP
        ]
    candidates = [
        c for c in candidates if overlap(sample["claim"], c["text"]) < MAX_OVERLAP
    ]
    if not candidates:
        return None
    chunk = rng.choice(candidates)
    replacement_doc = chunk["document_version_id"][:8]
    return {
        **sample,
        "chunk_id": chunk["chunk_id"],
        "document_version": replacement_doc,
        "page_start": chunk["page_start"],
        "page_end": chunk["page_end"],
        "section_path": chunk["section_path"],
        "chunk_text": chunk["text"],
        "glue_group": groups.get(replacement_doc),
        "_synthetic": {
            "kind": kind,
            "replaces_chunk_id": sample["chunk_id"],
            "claim_overlap": round(overlap(sample["claim"], chunk["text"]), 3),
        },
    }


def main() -> int:
    samples = [
        json.loads(line)
        for line in LABELS_PATH.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    if any(isinstance(s.get("human_label"), bool) for s in samples):
        print("citation_labels.jsonl already has human labels - not modifying it.")
        return 1
    if KEY_PATH.exists():
        print(f"{KEY_PATH} exists - synthetic samples were already added.")
        return 1
    source_runs = {s["source_run"] for s in samples}
    pool: list[dict[str, Any]] = []
    groups: dict[str, str] = {}
    for run_name in sorted(source_runs):
        details = json.loads((RESULTS_DIR / run_name).read_text(encoding="utf-8"))
        pool += chunk_pool(details)
        groups.update(
            {k: v.get("glue_group") for k, v in details.get("documents", {}).items()}
        )

    rng = random.Random(SEED)
    bases = samples[:]
    rng.shuffle(bases)
    synthetic: list[dict[str, Any]] = []
    plan = ["other_document"] * N_OTHER_DOCUMENT + [
        "same_document_other_section"
    ] * N_SAME_DOCUMENT
    used: set[str] = set()
    for kind in plan:
        for base in bases:
            if base["id"] in used:
                continue
            negative = make_negative(base, pool, kind, groups, rng)
            if negative is not None:
                used.add(base["id"])
                synthetic.append(negative)
                break
    kind_counts = Counter(s["_synthetic"]["kind"] for s in synthetic)
    combined = [{**s, "_synthetic": None} for s in samples] + synthetic
    rng.shuffle(combined)

    KEY_PATH.parent.mkdir(exist_ok=True)
    with (
        LABELS_PATH.open("w", encoding="utf-8") as labels,
        KEY_PATH.open("w", encoding="utf-8") as key,
    ):
        for i, sample in enumerate(combined, start=1):
            marker = sample.pop("_synthetic")
            sample["id"] = f"CAL-{i:02d}"
            labels.write(json.dumps(sample, ensure_ascii=False) + "\n")
            key.write(
                json.dumps(
                    {
                        "id": sample["id"],
                        "synthetic": marker is not None,
                        **(marker or {}),
                    },
                    ensure_ascii=False,
                )
                + "\n"
            )
    print(
        f"{len(samples)} real + {len(synthetic)} synthetic negatives "
        f"({dict(kind_counts)}; planned {len(plan)}) -> {len(combined)} samples "
        f"in {LABELS_PATH.name}; answer key in {KEY_PATH}"
    )
    return 0


if __name__ == "__main__":
    argparse.ArgumentParser(description=__doc__.splitlines()[0]).parse_args()
    sys.exit(main())
