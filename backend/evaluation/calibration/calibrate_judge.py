"""Compare hand labels in ``citation_labels.jsonl`` with the per-citation
LLM-judge (``evaluation.judge.judge_citation``).

    uv run python -m evaluation.calibration.calibrate_judge
    uv run python -m evaluation.calibration.calibrate_judge --negative-controls

With no hand label yet it prints "chưa hiệu chỉnh" and stops, before any LLM
call and without any number.

Otherwise every labeled sample is judged with the configured judge model
(``JUDGE_LLM_MODEL``, else ``LLM_MODEL``); verdicts are cached per model in
``evaluation/private/judge_verdicts_<model>.jsonl`` (``--rejudge`` ignores the
cache - the judge is not deterministic). Reported: agreement, Cohen's kappa,
confusion matrix, overall and split into real vs synthetic-negative samples
(from the git-ignored answer key ``evaluation/private/calibration_key.jsonl``).

``--negative-controls`` needs no hand label: it judges only the synthetic
negatives and reports how many the judge rejects. That is a sanity check of
the judge against samples unsupported by construction, NOT a calibration.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
import sys
from pathlib import Path
from typing import Any

from evaluation import scoring

CALIBRATION_DIR = Path(__file__).resolve().parent
LABELS_PATH = CALIBRATION_DIR / "citation_labels.jsonl"
PRIVATE_DIR = CALIBRATION_DIR.parent / "private"
KEY_PATH = PRIVATE_DIR / "calibration_key.jsonl"
MIN_LABELS = 30  # below this the kappa estimate is too noisy to call calibrated


def _jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def _verdict_cache_path(model: str) -> Path:
    return (
        PRIVATE_DIR / f"judge_verdicts_{re.sub(r'[^A-Za-z0-9._-]', '_', model)}.jsonl"
    )


async def judge_samples(
    samples: list[dict[str, Any]], rejudge: bool
) -> tuple[dict[str, bool | None], str, dict[str, Any]]:
    from evaluation.instrumentation import (
        TokenLedger,
        judge_model_name,
        make_judge_client,
    )
    from evaluation.judge import judge_citation

    model = judge_model_name()
    cache_path = _verdict_cache_path(model)
    cache = {} if rejudge else {r["id"]: r["supported"] for r in _jsonl(cache_path)}
    ledger = TokenLedger()
    client = make_judge_client(ledger)
    for s in samples:
        if s["id"] not in cache:
            cache[s["id"]] = await judge_citation(
                client, s["question"], s["claim"], s["chunk_text"]
            )
    PRIVATE_DIR.mkdir(exist_ok=True)
    cache_path.write_text(
        "".join(
            json.dumps({"id": k, "supported": v}) + "\n"
            for k, v in sorted(cache.items())
        ),
        encoding="utf-8",
    )
    return cache, model, ledger.snapshot()


def summarize(pairs: list[tuple[bool, bool]]) -> dict[str, Any]:
    """pairs = (human_label, judge_verdict)."""
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


def negative_controls(samples: list[dict[str, Any]], rejudge: bool) -> int:
    key = {k["id"]: k for k in _jsonl(KEY_PATH)}
    negatives = [s for s in samples if key.get(s["id"], {}).get("synthetic")]
    if not negatives:
        print("no synthetic negatives (answer key missing or empty)")
        return 1
    verdicts, model, tokens = asyncio.run(judge_samples(negatives, rejudge))
    by_kind: dict[str, list[bool | None]] = {}
    for s in negatives:
        by_kind.setdefault(key[s["id"]]["kind"], []).append(verdicts[s["id"]])
    judged = [v for v in verdicts.values() if v is not None]
    result = {
        "what": "negative-control check (NOT a calibration)",
        "judge_model": model,
        "n_synthetic": len(negatives),
        "n_judged": len(judged),
        "rejected_as_unsupported": sum(1 for v in judged if v is False),
        "accepted_as_supported": sum(1 for v in judged if v is True),
        "by_kind": {
            k: {
                "n": len(v),
                "rejected": sum(1 for x in v if x is False),
                "accepted": sum(1 for x in v if x is True),
                "unparseable": sum(1 for x in v if x is None),
            }
            for k, v in by_kind.items()
        },
        "tokens": tokens,
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    (PRIVATE_DIR / "negative_controls_result.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return 0


def main(labels_path: Path, rejudge: bool, controls: bool) -> int:
    samples = _jsonl(labels_path)
    if controls:
        return negative_controls(samples, rejudge)
    labeled = [s for s in samples if isinstance(s.get("human_label"), bool)]
    if not labeled:
        print(
            f"chưa hiệu chỉnh: 0/{len(samples)} mẫu trong {labels_path.name} có "
            "nhãn tay (human_label true/false). Không in số liệu."
        )
        return 0
    verdicts, model, tokens = asyncio.run(judge_samples(labeled, rejudge))
    key = {k["id"]: k for k in _jsonl(KEY_PATH)}
    pairs_all, pairs_real, pairs_synth, missing = [], [], [], []
    for s in labeled:
        verdict = verdicts.get(s["id"])
        if verdict is None:
            missing.append(s["id"])
            continue
        pair = (s["human_label"], verdict)
        pairs_all.append(pair)
        (pairs_synth if key.get(s["id"], {}).get("synthetic") else pairs_real).append(
            pair
        )
    synthetic_labeled = [s for s in labeled if key.get(s["id"], {}).get("synthetic")]
    result = {
        "judge_model": model,
        "all": summarize(pairs_all),
        "real_samples": summarize(pairs_real),
        "synthetic_negatives": summarize(pairs_synth),
        # Synthetic negatives are unsupported by construction: how often the
        # human labeler also said "not supported" (a check on the labels).
        "labeler_rejects_synthetic": scoring.rate(
            sum(1 for s in synthetic_labeled if s["human_label"] is False),
            len(synthetic_labeled),
        ),
        "n_labeled": len(labeled),
        "n_samples": len(samples),
        "no_judge_verdict": missing,
        "answer_key_found": bool(key),
        "tokens": tokens,
    }
    result["calibrated"] = len(pairs_all) >= MIN_LABELS
    status = (
        "đã hiệu chỉnh"
        if result["calibrated"]
        else f"chưa đủ để coi là hiệu chỉnh (cần >= {MIN_LABELS} cặp)"
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    print(
        f"{status}: judge={model}, N={result['all']['n']}, "
        f"đồng thuận={result['all']['agreement']}, "
        f"kappa={result['all']['cohen_kappa']}"
    )
    (CALIBRATION_DIR / "calibration_result.json").write_text(
        json.dumps(
            {k: v for k, v in result.items() if k != "no_judge_verdict"}
            | {
                "n": result["all"]["n"],
                "agreement": result["all"]["agreement"],
                "cohen_kappa": result["all"]["cohen_kappa"],
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--labels", type=Path, default=LABELS_PATH)
    parser.add_argument("--rejudge", action="store_true")
    parser.add_argument("--negative-controls", action="store_true")
    args = parser.parse_args()
    sys.exit(main(args.labels, args.rejudge, args.negative_controls))
