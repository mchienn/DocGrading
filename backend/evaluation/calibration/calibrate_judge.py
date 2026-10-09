"""Compare hand labels in ``citation_labels.jsonl`` with the per-citation
LLM-judge (``evaluation.judge.judge_citation``) verdicts.

    uv run python -m evaluation.calibration.calibrate_judge

The LLM verdict for each sample is the one recorded in the run named by the
sample's ``source_run`` (``evaluation/results/<source_run>``), i.e. exactly
the verdict that went into that run's citation-precision number. With
``--rejudge`` the judge is called again instead (needs LLM_API_KEY; the
judge is not deterministic, so a re-judged verdict can differ).

Prints "chưa hiệu chỉnh" and no numbers when no sample has a hand label yet.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path
from typing import Any

from evaluation import scoring

CALIBRATION_DIR = Path(__file__).resolve().parent
LABELS_PATH = CALIBRATION_DIR / "citation_labels.jsonl"
RESULTS_DIR = CALIBRATION_DIR.parent / "results"
MIN_LABELS = 30  # below this the kappa estimate is too noisy to call calibrated


def load_labels(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def stored_verdicts(source_run: str) -> dict[tuple[str, str, str], bool | None]:
    details = json.loads((RESULTS_DIR / source_run).read_text(encoding="utf-8"))
    out = {}
    for config, runs in details["details"]["runs"].items():
        for run in runs:
            for cit in run["judge_citations"]:
                out[(config, run["case_id"], cit["chunk_id"])] = cit["supported"]
    return out


async def rejudge(samples: list[dict[str, Any]]) -> dict[str, bool | None]:
    from app.services.rag import get_llm_client
    from evaluation.judge import judge_citation

    client = get_llm_client()
    return {
        s["id"]: await judge_citation(
            client, s["question"], s["claim"], s["chunk_text"]
        )
        for s in samples
    }


def summarize(pairs: list[tuple[bool, bool]]) -> dict[str, Any]:
    tp = sum(1 for h, j in pairs if h and j)
    tn = sum(1 for h, j in pairs if not h and not j)
    fp = sum(1 for h, j in pairs if not h and j)  # judge says supported, human no
    fn = sum(1 for h, j in pairs if h and not j)
    return {
        "n": len(pairs),
        "agreement": scoring.agreement(pairs),
        "cohen_kappa": scoring.cohen_kappa(pairs),
        "confusion": {
            "tp": tp,
            "tn": tn,
            "fp_judge_lenient": fp,
            "fn_judge_strict": fn,
        },
        "human_supported_rate": scoring.rate(sum(1 for h, _ in pairs if h), len(pairs)),
        "judge_supported_rate": scoring.rate(sum(1 for _, j in pairs if j), len(pairs)),
    }


def main(labels_path: Path, use_rejudge: bool) -> int:
    samples = load_labels(labels_path)
    labeled = [s for s in samples if isinstance(s.get("human_label"), bool)]
    if not labeled:
        print(
            f"chưa hiệu chỉnh: 0/{len(samples)} mẫu trong {labels_path.name} có "
            "nhãn tay (human_label true/false). Không in số liệu."
        )
        return 0
    if use_rejudge:
        verdicts_by_id = asyncio.run(rejudge(labeled))
    else:
        verdicts_by_id = {}
        cache: dict[str, dict] = {}
        for s in labeled:
            if s["source_run"] not in cache:
                cache[s["source_run"]] = stored_verdicts(s["source_run"])
            verdicts_by_id[s["id"]] = cache[s["source_run"]].get(
                (s["config"], s["case_id"], s["chunk_id"])
            )
    pairs = []
    missing = []
    for s in labeled:
        verdict = verdicts_by_id.get(s["id"])
        if verdict is None:
            missing.append(s["id"])
            continue
        pairs.append((s["human_label"], verdict))
    result = summarize(pairs)
    result["n_labeled"] = len(labeled)
    result["n_samples"] = len(samples)
    result["no_judge_verdict"] = missing
    result["calibrated"] = len(pairs) >= MIN_LABELS
    status = (
        "đã hiệu chỉnh"
        if result["calibrated"]
        else f"chưa đủ để coi là hiệu chỉnh (cần >= {MIN_LABELS} cặp)"
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    print(
        f"{status}: N={result['n']}, đồng thuận={result['agreement']}, "
        f"kappa={result['cohen_kappa']}"
    )
    (CALIBRATION_DIR / "calibration_result.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--labels", type=Path, default=LABELS_PATH)
    parser.add_argument("--rejudge", action="store_true")
    args = parser.parse_args()
    sys.exit(main(args.labels, args.rejudge))
