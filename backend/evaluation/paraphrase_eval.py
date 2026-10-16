"""Intent accuracy on hand-written paraphrases (``paraphrase_set.jsonl``).

    uv run python -m evaluation.paraphrase_eval
    uv run python -m evaluation.paraphrase_eval --keyword-only

Two modes, on the same questions:

- ``keyword``: ``classify_intent()`` only (the rule-based classifier);
- ``keyword+router``: as the chatbot does it - when the rules return
  ``UNKNOWN``, the LLM router (``route_with_llm``, no history) picks the
  intent; an unparseable/failed route stays ``UNKNOWN``.

Unlike the golden set's tier 1, these questions must NOT be checked against
``classify_intent()`` while being written, so they measure how the rules
generalise. No database is used. Prints accuracy, a confusion matrix and
every wrong case per mode, and writes ``results/paraphrase_<date>.json``.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.services.chat import Intent, classify_intent, route_with_llm
from evaluation import scoring
from evaluation.instrumentation import TokenLedger, make_llm_client

EVAL_DIR = Path(__file__).resolve().parent
PARAPHRASE_PATH = EVAL_DIR / "paraphrase_set.jsonl"
VALID_INTENTS = {i.value for i in Intent}


def load_paraphrases(path: Path) -> tuple[list[dict[str, Any]], list[str]]:
    """Rows with a non-empty question, plus problems found in the file."""
    rows, problems = [], []
    for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        row = json.loads(line)
        if not str(row.get("question", "")).strip():
            continue
        if row.get("intent_expected") not in VALID_INTENTS:
            problems.append(
                f"line {n}: invalid intent_expected {row.get('intent_expected')!r}"
            )
            continue
        rows.append(row)
    ids = [r["id"] for r in rows]
    problems += [f"duplicate id {i}" for i, c in Counter(ids).items() if c > 1]
    return rows, problems


def confusion_matrix(pairs: list[tuple[str, str]]) -> dict[str, dict[str, int]]:
    """{expected: {predicted: count}} over the labels that occur."""
    labels = sorted({e for e, _ in pairs} | {p for _, p in pairs})
    matrix = {e: dict.fromkeys(labels, 0) for e in labels}
    for expected, predicted in pairs:
        matrix[expected][predicted] += 1
    return matrix


def format_matrix(matrix: dict[str, dict[str, int]]) -> str:
    labels = list(matrix)
    short = {label: label[:10] for label in labels}
    head = "expected \\ predicted".ljust(24) + " ".join(
        short[c].rjust(10) for c in labels
    )
    lines = [head]
    for e in labels:
        lines.append(
            short[e].ljust(24) + " ".join(str(matrix[e][p]).rjust(10) for p in labels)
        )
    return "\n".join(lines)


async def predict(rows: list[dict[str, Any]], use_router: bool, llm: Any) -> list[str]:
    out = []
    for row in rows:
        intent = classify_intent(row["question"])
        if use_router and intent is Intent.UNKNOWN:
            try:
                routed = await route_with_llm(row["question"], [], llm)
            except Exception:  # noqa: BLE001 - same as chat._route_unknown
                routed = None
            if routed is not None:
                intent = routed.intent
        out.append(intent.value)
    return out


def score_mode(rows: list[dict[str, Any]], predicted: list[str]) -> dict[str, Any]:
    pairs = [(r["intent_expected"], p) for r, p in zip(rows, predicted, strict=True)]
    return {
        "n": len(pairs),
        "accuracy": scoring.rate(sum(1 for e, p in pairs if e == p), len(pairs)),
        "confusion": confusion_matrix(pairs),
        "wrong": [
            {
                "id": r["id"],
                "question": r["question"],
                "expected": r["intent_expected"],
                "predicted": p,
            }
            for r, p in zip(rows, predicted, strict=True)
            if r["intent_expected"] != p
        ],
    }


async def main(path: Path, keyword_only: bool) -> int:
    rows, problems = load_paraphrases(path)
    for problem in problems:
        print(f"[paraphrase] {problem}")
    if not rows:
        print(
            f"[paraphrase] 0 câu hỏi có nội dung trong {path.name} - chưa có gì để đo "
            "(dòng mẫu có question rỗng bị bỏ qua)."
        )
        return 0
    ledger = TokenLedger()
    modes = {"keyword": await predict(rows, False, None)}
    if not keyword_only:
        modes["keyword+router"] = await predict(rows, True, make_llm_client(ledger))
    result: dict[str, Any] = {"file": path.name, "n_rows": len(rows), "modes": {}}
    for mode, predicted in modes.items():
        scored = score_mode(rows, predicted)
        result["modes"][mode] = scored
        note = " (chỉ mang tính chỉ báo, N < 20)" if scored["n"] < 20 else ""
        print(
            f"\n=== {mode}: accuracy {scored['accuracy']:.1%} (N={scored['n']}){note}"
        )
        print(format_matrix(scored["confusion"]))
        for w in scored["wrong"]:
            print(
                f"  ✗ {w['id']}: {w['expected']} -> {w['predicted']}  | {w['question']}"
            )
    result["tokens"] = ledger.snapshot()
    stamp = datetime.now(UTC).strftime("%Y%m%d")
    out = EVAL_DIR / "results" / f"paraphrase_{stamp}.json"
    out.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n[paraphrase] LLM tokens {ledger.llm_total:,}; wrote {out.name}")
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--file", type=Path, default=PARAPHRASE_PATH)
    parser.add_argument("--keyword-only", action="store_true")
    args = parser.parse_args()
    sys.exit(asyncio.run(main(args.file, args.keyword_only)))
