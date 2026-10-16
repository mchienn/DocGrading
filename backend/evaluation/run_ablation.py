"""Ablation benchmark: the same golden set under three chatbot configurations.

Run from backend/ against the benchmark copy of the data, never the dev DB:

    POSTGRES_DB=docgrading_test uv run python -m evaluation.run_ablation
    POSTGRES_DB=docgrading_test uv run python -m evaluation.run_ablation \
        --configs hybrid

Configurations (see ``instrumentation.CONFIG_DESCRIPTIONS``): ``rule_only``,
``rag_only``, ``hybrid`` (the current system). Every request runs inside
``sandbox.rolled_back_session``, so the run leaves the database unchanged.

Outputs in ``evaluation/results/``:

- ``ablation_<YYYYMMDD>_<label>.json`` / ``.md`` - aggregate metrics only
  (no student names, no report text).
- ``ablation_<YYYYMMDD>_<label>_details.json`` - per-case replies, retrieved
  chunks and judge verdicts. Contains student report content: do not commit.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
import subprocess
import sys
import time
import uuid
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import sqlalchemy as sa
from fastapi import HTTPException

from app.core.config import get_settings
from app.db.session import _engine, _session_factory
from app.models.chunk import DocumentChunk
from app.models.identity import User
from app.models.submission import DocumentVersion
from app.services.chat import handle_chat
from evaluation import judge, scoring
from evaluation.cache_suite import load_cache_cases, run_cache_case, score_cache
from evaluation.golden import golden_path, load_golden_set
from evaluation.instrumentation import (
    CONFIG_DESCRIPTIONS,
    CONFIGS,
    LLM_TOKEN_BUDGET,
    RetrievalRecorder,
    TokenBudgetExceeded,
    TokenLedger,
    ablation_config,
    judge_model_name,
    make_judge_client,
)
from evaluation.sandbox import rolled_back_session

EVAL_DIR = Path(__file__).resolve().parent
REPO_ROOT = EVAL_DIR.parents[1]
RESULTS_DIR = EVAL_DIR / "results"
LABELS_PATH = EVAL_DIR / "calibration" / "citation_labels.jsonl"

TEACHER_ID = uuid.UUID("3d73249e-e187-4866-9787-a310bc588580")
ANCHOR_COURSE_ID = "2acdc4ff-b11c-437a-bcb8-3bb811c101c1"
DEV_DATABASE = "docgrading"
SMALL_N = 20  # below this, a metric is reported as indicative only

# Real assignment titles in the anchor dataset, needed to find the right
# bullet line in a NOT_SUBMITTED reply (``format_not_submitted``).
ASSIGNMENT_TITLES = {
    "srs": "Bài tập lớn: Báo cáo SRS Hoàn chỉnh",
    "kickoff": "Bài tập Khởi động Tuần 1",
}

# Rough per-call LLM token costs, only for the pre-run budget estimate.
_EST = {"answer": 4_500, "router": 1_500, "judge_answer": 5_500, "judge_cit": 1_200}
_EST_SUMMARY_PER_DOC = 11_000


@dataclass
class CaseRun:
    case_id: str
    tier: int
    intent_expected: str
    config: str
    intent: str | None = None
    reply: str = ""
    needs_clarification: str | None = None
    n_options: int = 0
    stats: dict[str, Any] | None = None
    citations: list[dict[str, Any]] = field(default_factory=list)
    retrieved: list[dict[str, Any]] = field(default_factory=list)
    error: str | None = None
    error_kind: str | None = None  # "5xx" (unhandled) | "4xx" (HTTPException)
    latency_s: float = 0.0
    judge_answer: dict[str, float] | None = None
    judge_citations: list[dict[str, Any]] = field(default_factory=list)


async def run_case(
    config: str, case: dict[str, Any], recorder: RetrievalRecorder
) -> CaseRun:
    scope = case["scope"]
    run = CaseRun(case["id"], case["tier"], case["intent_expected"], config)
    recorder.reset()
    start = time.perf_counter()
    try:
        async with rolled_back_session() as db:
            user = await db.get(User, TEACHER_ID)
            response = await handle_chat(
                db,
                user=user,
                message=case["question"],
                course_id=scope.get("course_id"),
                assignment_id=(
                    uuid.UUID(scope["assignment_id"])
                    if scope.get("assignment_id")
                    else None
                ),
                submission_id=(
                    uuid.UUID(scope["submission_id"])
                    if scope.get("submission_id")
                    else None
                ),
            )
        run.latency_s = time.perf_counter() - start
    except TokenBudgetExceeded:
        raise
    except HTTPException as exc:
        run.latency_s = time.perf_counter() - start
        run.error, run.error_kind = f"HTTP {exc.status_code}: {exc.detail}", "4xx"
        return run
    except Exception as exc:  # noqa: BLE001 - recorded as an error-rate hit
        run.latency_s = time.perf_counter() - start
        run.error, run.error_kind = f"{type(exc).__name__}: {exc}", "5xx"
        return run
    run.intent = str(response.intent)
    run.reply = response.reply
    run.needs_clarification = response.needs_clarification
    run.n_options = len(response.clarification_options or [])
    run.stats = response.stats.model_dump() if response.stats else None
    run.citations = [
        {
            "number": i,
            "chunk_id": str(c.chunk_id),
            "page": c.page,
            "page_end": c.page_end,
            "section_path": c.section_path,
        }
        for i, c in enumerate(response.citations or [], start=1)
    ]
    last = recorder.calls[-1] if recorder.calls else []
    run.retrieved = [
        {
            "chunk_id": str(c.id),
            "document_version_id": str(c.document_version_id),
            "page_start": c.page_start,
            "page_end": c.page_end,
            "section_path": c.section_path,
            "text": c.text,
        }
        for c in last
    ]
    return run


def _chunk_like(d: dict[str, Any]) -> scoring.ChunkLike:
    return scoring.ChunkLike(
        page_start=d["page_start"],
        page_end=d["page_end"],
        section_path=d["section_path"],
        text=d["text"],
    )


# --- Document metadata (corpus + glue group) ----------------------------------


async def load_documents(cases: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Per document version used by tier 2/3: whole chunk corpus + glue stats,
    computed from the stored chunks (same text the chunk audit measured)."""
    submission_ids = {
        uuid.UUID(c["scope"]["submission_id"])
        for c in cases
        if c["tier"] in (2, 3) and c["scope"].get("submission_id")
    }
    docs: dict[str, dict[str, Any]] = {}
    async with _session_factory()() as db:
        latest = (
            await db.execute(
                sa.select(DocumentVersion.submission_id, DocumentVersion.id)
                .where(DocumentVersion.submission_id.in_(submission_ids))
                .order_by(DocumentVersion.submission_id, DocumentVersion.version_number)
            )
        ).all()
        version_of = {str(s): str(v) for s, v in latest}  # last one wins
        for submission_id, version_id in version_of.items():
            rows = (
                await db.execute(
                    sa.select(
                        DocumentChunk.id,
                        DocumentChunk.page_start,
                        DocumentChunk.page_end,
                        DocumentChunk.section_path,
                        DocumentChunk.text,
                    )
                    .where(DocumentChunk.document_version_id == uuid.UUID(version_id))
                    .order_by(DocumentChunk.chunk_index)
                )
            ).all()
            corpus = [
                {
                    "chunk_id": str(r[0]),
                    "page_start": r[1],
                    "page_end": r[2],
                    "section_path": r[3],
                    "text": r[4],
                }
                for r in rows
            ]
            full_text = " ".join(c["text"] for c in corpus)
            docs[version_id] = {
                "submission_id": submission_id,
                "corpus": corpus,
                "glue": scoring.glue_stats(full_text),
                "language": scoring.detect_language(full_text),
                "glue_group": scoring.document_group(full_text),
            }
    return docs


def doc_of_case(case: dict[str, Any], docs: dict[str, dict[str, Any]]) -> str | None:
    sid = case["scope"].get("submission_id")
    for version_id, doc in docs.items():
        if doc["submission_id"] == sid:
            return version_id
    return None


# --- Tier 1 -------------------------------------------------------------------


def _check_summary(gold: dict[str, Any], run: CaseRun) -> bool:
    if "per_course_rate" in gold:
        parsed = scoring.parse_summary_all_courses_rate(run.reply)
        return parsed == gold["per_course_rate"]
    if run.stats is None:
        return False
    return all(run.stats.get(key) == value for key, value in gold.items())


def _check_not_submitted(gold: dict[str, Any], run: CaseRun) -> bool:
    if (
        scoring.parse_not_submitted_active_students(run.reply)
        != gold["active_students"]
    ):
        return False
    if "per_assignment" in gold:
        return all(
            scoring.parse_not_submitted_for_assignment(run.reply, title) == missing
            for title, missing in gold["per_assignment"].items()
        )
    return (
        scoring.parse_not_submitted_for_assignment(run.reply, ASSIGNMENT_TITLES["srs"])
        == gold["missing_count"]
    )


_NUMERIC_CHECKS = {
    "SUMMARY": _check_summary,
    "UNREVIEWED": lambda g, r: scoring.parse_unreviewed(r.reply) == g["pending_count"],
    "ERRORS": lambda g, r: scoring.parse_errors(r.reply) == g["error_count"],
    "NOT_SUBMITTED": _check_not_submitted,
    "NEW_REVIEW_REQUESTS": lambda g, r: scoring.parse_new_review_requests(r.reply)
    == g["count"],
}


def _gold_ints(value: Any) -> list[int]:
    if isinstance(value, bool):
        return []
    if isinstance(value, int):
        return [value]
    if isinstance(value, dict):
        return [n for v in value.values() for n in _gold_ints(v)]
    return []


def numeric_lenient(gold: dict[str, Any], reply: str) -> bool:
    """Every gold number appears as a standalone number in the reply - an
    upper bound used only for a configuration whose wording the strict
    parsers can't read (rag_only)."""
    numbers = set(re.findall(r"\d+", reply))
    return all(str(n) in numbers for n in _gold_ints(gold))


def score_tier1(
    runs: list[CaseRun], cases: dict[str, dict], config: str
) -> dict[str, Any]:
    noise = [r for r in runs if r.case_id.startswith("T1-NOISE")]
    normal = [r for r in runs if not r.case_id.startswith("T1-NOISE")]
    oos_ok = sum(
        1
        for r in noise
        if r.error is None and scoring.is_rejection(r.intent or "", len(r.citations))
    )
    intent_ok = sum(1 for r in normal if r.intent == r.intent_expected)
    strict_ok = sum(
        1
        for r in normal
        if r.error is None
        and r.intent == r.intent_expected
        and _NUMERIC_CHECKS[r.intent_expected](cases[r.case_id]["gold"], r)
    )
    lenient_ok = sum(
        1
        for r in normal
        if r.error is None and numeric_lenient(cases[r.case_id]["gold"], r.reply)
    )
    mismatches = [
        f"{r.case_id}: intent={r.intent} expected={r.intent_expected}"
        for r in normal
        if r.intent != r.intent_expected
    ] + [
        f"{r.case_id}: not rejected (intent={r.intent}, citations={len(r.citations)})"
        for r in noise
        if not (
            r.error is None and scoring.is_rejection(r.intent or "", len(r.citations))
        )
    ]
    return {
        "intent_accuracy": (
            None if config == "rag_only" else scoring.rate(intent_ok, len(normal))
        ),
        "intent_n": len(normal),
        "oos_rejection_rate": scoring.rate(oos_ok, len(noise)),
        "oos_n": len(noise),
        "numeric_correctness": scoring.rate(strict_ok, len(normal)),
        "numeric_n": len(normal),
        "numeric_lenient_upper_bound": scoring.rate(lenient_ok, len(normal)),
        "mismatches": mismatches,
    }


# --- Tier 0 -------------------------------------------------------------------


def score_tier0(runs: list[CaseRun], cases: dict[str, dict]) -> dict[str, Any]:
    outcomes = []
    mismatches = []
    for r in runs:
        gold = cases[r.case_id]["gold"]
        expected = gold["needs_clarification_expected"]
        got = None if r.error else r.needs_clarification
        outcomes.append(scoring.clarification_outcome(got, expected))
        ok = got == expected and r.n_options >= gold.get("min_options", 0)
        if not ok:
            mismatches.append(f"{r.case_id}: expected={expected!r} got={got!r}")
    precision, recall = scoring.precision_recall(outcomes)
    return {
        "precision": precision,
        "recall": recall,
        "n": len(runs),
        "n_should_ask": sum(1 for _, e in outcomes if e),
        "n_asked": sum(1 for a, _ in outcomes if a),
        "mismatches": mismatches,
    }


# --- Tier 2 -------------------------------------------------------------------


_TOLERANCES = (("", 0), ("_tol2", 2))


def _tier2_case(run: CaseRun, case: dict[str, Any], doc: dict[str, Any]) -> dict:
    gold = case["gold"]["relevant"]
    corpus = [_chunk_like(d) for d in doc["corpus"]]
    n_relevant = {
        label: scoring.count_relevant_chunks(corpus, gold, page_tolerance=tol)
        for label, tol in _TOLERANCES
    }
    return tier2_case_scores(
        run.case_id,
        doc["glue_group"],
        [_chunk_like(d) for d in run.retrieved],
        gold,
        n_relevant,
    )


def tier2_case_scores(
    case_id: str,
    group: str,
    retrieved: list[scoring.ChunkLike],
    gold: list[dict[str, Any]],
    n_relevant_in_corpus: dict[str, int],
) -> dict[str, Any]:
    """Per-case tier 2 scores. ``n_relevant_in_corpus`` is keyed by tolerance
    label ("" and "_tol2"), counted over the submission's whole corpus.

    Two precisions are kept: ``precision`` divides by the chunks actually
    returned (the original rule; a configuration returning fewer chunks scores
    higher), ``precision_fixed`` divides by ``scoring.FIXED_K`` for every
    configuration, so configurations are comparable.
    """
    k = len(retrieved)
    out: dict[str, Any] = {"case_id": case_id, "k": k, "group": group}
    for label, tol in _TOLERANCES:
        n_rel = n_relevant_in_corpus[label]
        out[f"precision{label}"] = scoring.context_precision_at_k(
            retrieved, gold, page_tolerance=tol
        )
        out[f"precision_fixed{label}"] = scoring.context_precision_fixed_k(
            retrieved, gold, page_tolerance=tol
        )
        out[f"recall{label}"] = scoring.context_recall(
            retrieved, gold, page_tolerance=tol
        )
        out[f"n_relevant_in_corpus{label}"] = n_rel
        out[f"ceiling{label}"] = (
            scoring.theoretical_max_precision(n_rel, k) if k else None
        )
        out[f"ceiling_fixed{label}"] = scoring.theoretical_max_precision(
            n_rel, scoring.FIXED_K
        )
    return out


def _aggregate_tier2(rows: list[dict[str, Any]]) -> dict[str, Any]:
    out: dict[str, Any] = {
        "n": len(rows),
        "n_zero_retrieved": sum(1 for r in rows if r["k"] == 0),
    }
    for label in ("", "_tol2"):
        precision = scoring.mean([r[f"precision{label}"] for r in rows])
        ceiling = scoring.mean([r[f"ceiling{label}"] for r in rows])
        out[f"precision_at_k{label}"] = precision
        out[f"recall{label}"] = scoring.mean([r[f"recall{label}"] for r in rows])
        out[f"precision_ceiling{label}"] = ceiling
        out[f"precision_vs_ceiling{label}"] = (
            precision / ceiling if precision is not None and ceiling else None
        )
        fixed = scoring.mean([r[f"precision_fixed{label}"] for r in rows])
        fixed_ceiling = scoring.mean([r[f"ceiling_fixed{label}"] for r in rows])
        out[f"precision_at_k_fixed{label}"] = fixed
        out[f"precision_ceiling_fixed{label}"] = fixed_ceiling
        out[f"precision_vs_ceiling_fixed{label}"] = (
            fixed / fixed_ceiling if fixed is not None and fixed_ceiling else None
        )
        out[f"n_gold_unmatchable_in_corpus{label}"] = sum(
            1 for r in rows if r[f"n_relevant_in_corpus{label}"] == 0
        )
    return out


def score_tier2(
    runs: list[CaseRun], cases: dict[str, dict], docs: dict[str, dict]
) -> dict[str, Any]:
    rows = []
    for r in runs:
        if r.error:
            continue
        case = cases[r.case_id]
        doc = docs[case["gold"]["document_version_id"]]
        rows.append(_tier2_case(r, case, doc))
    return {
        "all": _aggregate_tier2(rows),
        "by_group": {
            g: _aggregate_tier2([r for r in rows if r["group"] == g])
            for g in scoring.GROUPS
        },
        "n_errors": sum(1 for r in runs if r.error),
        "per_case": rows,
    }


# --- Tier 3 -------------------------------------------------------------------


async def judge_tier3(runs: list[CaseRun], cases: dict[str, dict], llm: Any) -> None:
    """Fill judge verdicts in place for generated ASK answers."""
    for r in runs:
        if r.error or r.intent != "ASK_ABOUT_REQUIREMENT" or not r.retrieved:
            continue
        by_id = {d["chunk_id"]: d for d in r.retrieved}
        cited_ids = {c["chunk_id"]: c["number"] for c in r.citations}
        chunks = [
            judge.JudgeChunk(
                number=cited_ids.get(d["chunk_id"]),
                page_start=d["page_start"],
                page_end=d["page_end"],
                section_path=d["section_path"],
                text=d["text"],
            )
            for d in r.retrieved
        ]
        question = cases[r.case_id]["question"]
        r.judge_answer = await judge.judge_answer(
            llm,
            question,
            r.reply,
            chunks,
            cases[r.case_id]["gold"]["expected_claims"],
        )
        for citation in r.citations:
            claim = judge.sentences_citing(r.reply, citation["number"])
            chunk = by_id.get(citation["chunk_id"])
            verdict = (
                await judge.judge_citation(llm, question, claim, chunk["text"])
                if chunk and claim
                else None
            )
            r.judge_citations.append(
                {
                    "number": citation["number"],
                    "chunk_id": citation["chunk_id"],
                    "claim": claim,
                    "supported": verdict,
                }
            )


def _aggregate_tier3(runs: list[CaseRun]) -> dict[str, Any]:
    judged = [r for r in runs if r.judge_answer is not None]
    per_case_cp = []
    for r in runs:
        verdicts = [
            c["supported"] for c in r.judge_citations if c["supported"] is not None
        ]
        if verdicts:
            per_case_cp.append(sum(verdicts) / len(verdicts))
    n_citations = sum(len(r.judge_citations) for r in runs)
    return {
        "n": len(runs),
        "n_judged": len(judged),
        "n_with_citations": len(per_case_cp),
        "n_citations_judged": n_citations,
        "faithfulness": scoring.mean([r.judge_answer["faithfulness"] for r in judged]),
        "citation_precision": scoring.mean(per_case_cp),
        "citation_recall": scoring.mean(
            [r.judge_answer["citation_recall"] for r in judged]
        ),
        "answer_relevancy": scoring.mean(
            [r.judge_answer["answer_relevancy"] for r in judged]
        ),
        "claim_coverage": scoring.mean(
            [r.judge_answer["claim_coverage"] for r in judged]
        ),
        "n_no_citation_answers": sum(
            1 for r in runs if r.error is None and not r.citations
        ),
    }


def score_tier3_ask(
    runs: list[CaseRun], cases: dict[str, dict], docs: dict[str, dict]
) -> dict[str, Any]:
    def group(r: CaseRun) -> str:
        version = doc_of_case(cases[r.case_id], docs)
        return docs[version]["glue_group"] if version else "unknown"

    return {
        "all": _aggregate_tier3(runs),
        "by_group": {
            g: _aggregate_tier3([r for r in runs if group(r) == g])
            for g in scoring.GROUPS
        },
        "intent_counts": {
            i: sum(1 for r in runs if r.intent == i)
            for i in sorted({r.intent or "ERROR" for r in runs})
        },
    }


def score_tier3_summarize(runs: list[CaseRun]) -> dict[str, Any]:
    ok = [r for r in runs if r.error is None]
    return {
        "n": len(runs),
        "structure_score_avg_of_5": scoring.mean(
            [float(scoring.summary_structure_score(r.reply)) for r in ok]
        ),
        "intent_counts": {
            i: sum(1 for r in runs if r.intent == i)
            for i in sorted({r.intent or "ERROR" for r in runs})
        },
    }


# --- Reporting ------------------------------------------------------------------


def calibration_status() -> dict[str, Any]:
    if not LABELS_PATH.exists():
        return {"calibrated": False, "reason": "chưa có file nhãn tay"}
    labels = [
        json.loads(line)
        for line in LABELS_PATH.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    labeled = [s for s in labels if isinstance(s.get("human_label"), bool)]
    if not labeled:
        return {
            "calibrated": False,
            "reason": f"0/{len(labels)} mẫu đã có nhãn tay",
        }
    result_path = LABELS_PATH.parent / "calibration_result.json"
    if result_path.exists():
        result = json.loads(result_path.read_text(encoding="utf-8"))
        if result.get("calibrated") and result.get("n_labeled") == len(labeled):
            # "Calibrated" means agreement was measured, not that it is good:
            # the kappa is quoted so a reader can judge.
            return {
                "calibrated": True,
                "reason": f"N={result['n']} cặp, đồng thuận "
                f"{result['agreement']:.2f}, Cohen's kappa {result['cohen_kappa']}",
            }
    return {
        "calibrated": False,
        "reason": f"{len(labeled)}/{len(labels)} mẫu có nhãn tay nhưng chưa chạy "
        "(lại) evaluation.calibration.calibrate_judge",
    }


def _git_commit() -> str:
    try:
        return (
            subprocess.check_output(
                ["git", "rev-parse", "--short", "HEAD"], cwd=REPO_ROOT
            )
            .decode()
            .strip()
        )
    except Exception:  # noqa: BLE001
        return "unknown"


def _git_dirty() -> bool:
    try:
        out = subprocess.check_output(
            ["git", "status", "--porcelain", "--", "backend/app"], cwd=REPO_ROOT
        )
        return bool(out.strip())
    except Exception:  # noqa: BLE001
        return True


def estimate_llm_tokens(
    configs: list[str], counts: dict[str, int], n_cache: int
) -> int:
    total = 0
    for config in configs:
        if config == "rag_only":
            total += counts["all"] * _EST["answer"]
        elif config == "hybrid":
            total += counts["router_candidates"] * _EST["router"]
            total += counts["ask"] * _EST["answer"]
        if config in ("rag_only", "hybrid"):
            total += counts["ask"] * (_EST["judge_answer"] + 3 * _EST["judge_cit"])
    if "hybrid" in configs:
        total += n_cache * 2 * _EST_SUMMARY_PER_DOC
    return total


async def main(
    configs: list[str],
    label: str,
    run_cache: bool,
    sample: int | None = None,
    golden: str | None = None,
) -> int:
    settings = get_settings()
    print(f"[ablation] POSTGRES_DB={settings.postgres_db}")
    if settings.postgres_db == DEV_DATABASE:
        print(
            "[ablation] refusing to run against the dev database; set "
            "POSTGRES_DB=docgrading_test (a copy of the dev data)"
        )
        return 2
    if not settings.llm_api_key.strip() or not settings.embedding_api_key.strip():
        print("[ablation] LLM_API_KEY/EMBEDDING_API_KEY missing - not running")
        return 2

    from app.services.chat import classify_intent

    cases_list = [
        c
        for c in load_golden_set(golden)
        if not c["gold"].get("cache_correctness_case")
    ]
    if sample:
        # Smoke-test mode: the first N cases of each tier/intent pair.
        seen: dict[tuple[int, str, bool], int] = {}
        picked = []
        for c in cases_list:
            key = (c["tier"], c["intent_expected"], c["id"].startswith("T1-NOISE"))
            if seen.get(key, 0) < sample:
                seen[key] = seen.get(key, 0) + 1
                picked.append(c)
        cases_list = picked
    cases = {c["id"]: c for c in cases_list}
    cache_cases = load_cache_cases() if run_cache and "hybrid" in configs else []
    if sample:
        cache_cases = cache_cases[:sample]
    counts = {
        "all": len(cases_list),
        "ask": sum(
            1
            for c in cases_list
            if c["tier"] == 3 and c["intent_expected"] == "ASK_ABOUT_REQUIREMENT"
        ),
        "router_candidates": sum(
            1 for c in cases_list if classify_intent(c["question"]).value == "UNKNOWN"
        ),
    }
    estimate = estimate_llm_tokens(configs, counts, len(cache_cases))
    print(
        f"[ablation] {len(cases_list)} golden cases, {len(cache_cases)} cache cases; "
        f"estimated LLM tokens ~{estimate:,} (budget {LLM_TOKEN_BUDGET:,})"
    )
    if estimate > LLM_TOKEN_BUDGET:
        print("[ablation] estimate exceeds the budget - stopping before any call")
        return 3

    docs = await load_documents(cases_list)
    ledger = TokenLedger()
    recorder = RetrievalRecorder()
    results: dict[str, Any] = {}
    details: dict[str, Any] = {"runs": {}, "cache": None}
    aborted: str | None = None

    # Warm the connection pool so the first timed case isn't a cold connect.
    async with _session_factory()() as db:
        await db.execute(sa.text("SELECT 1"))

    order = [c for c in ("hybrid", "rag_only", "rule_only") if c in configs]
    try:
        for config in order:
            before = ledger.snapshot()
            print(f"[ablation] === {config} ===")
            runs: list[CaseRun] = []
            with ablation_config(config, ledger, recorder):
                for i, case in enumerate(cases_list, start=1):
                    run = await run_case(config, case, recorder)
                    runs.append(run)
                    if ledger.exceeded:
                        raise TokenBudgetExceeded("LLM token budget exceeded")
                    if run.error:
                        print(f"  ! {case['id']}: {run.error}")
                    if i % 25 == 0:
                        print(
                            f"  {i}/{len(cases_list)} cases, LLM tokens so far "
                            f"{ledger.llm_total:,}"
                        )
            by_tier = {t: [r for r in runs if r.tier == t] for t in (0, 1, 2, 3)}
            ask = [
                r for r in by_tier[3] if r.intent_expected == "ASK_ABOUT_REQUIREMENT"
            ]
            summ = [
                r for r in by_tier[3] if r.intent_expected == "SUMMARIZE_SUBMISSION"
            ]
            if config != "rule_only":
                print(f"  judging {len(ask)} ASK answers...")
                await judge_tier3(ask, cases, make_judge_client(ledger))
            latencies = [r.latency_s for r in runs]
            results[config] = {
                "description": CONFIG_DESCRIPTIONS[config],
                "tier0": score_tier0(by_tier[0], cases),
                "tier1": score_tier1(by_tier[1], cases, config),
                "tier2": score_tier2(by_tier[2], cases, docs),
                "tier3_ask": (
                    None if config == "rule_only" else score_tier3_ask(ask, cases, docs)
                ),
                "tier3_summarize": (
                    None if config == "rule_only" else score_tier3_summarize(summ)
                ),
                "latency_p50_s": scoring.percentile(latencies, 50),
                "latency_p95_s": scoring.percentile(latencies, 95),
                "latency_n": len(latencies),
                "latency_by_tier": {
                    t: {
                        "p50": scoring.percentile([r.latency_s for r in rs], 50),
                        "p95": scoring.percentile([r.latency_s for r in rs], 95),
                        "n": len(rs),
                    }
                    for t, rs in by_tier.items()
                },
                "error_rate_5xx": scoring.rate(
                    sum(1 for r in runs if r.error_kind == "5xx"), len(runs)
                ),
                "error_count_5xx": sum(1 for r in runs if r.error_kind == "5xx"),
                "error_count_4xx": sum(1 for r in runs if r.error_kind == "4xx"),
                "n_cases": len(runs),
                "tokens": _token_delta(before, ledger.snapshot()),
            }
            details["runs"][config] = [asdict(r) for r in runs]
            if config == "hybrid" and cache_cases:
                print(f"[ablation] cache suite ({len(cache_cases)} cases)...")
                before_cache = ledger.snapshot()
                with ablation_config("hybrid", ledger, recorder) as llm:
                    cache_details = []
                    for case in cache_cases:
                        d = await run_cache_case(
                            case, llm, TEACHER_ID, ANCHOR_COURSE_ID
                        )
                        print(f"  - {d}")
                        cache_details.append(d)
                        if ledger.exceeded:
                            raise TokenBudgetExceeded("LLM token budget exceeded")
                results["cache"] = score_cache(cache_details)
                results["cache"]["tokens"] = _token_delta(
                    before_cache, ledger.snapshot()
                )
    except TokenBudgetExceeded as exc:
        aborted = str(exc)
        print(f"[ablation] ABORTED: {exc}")
    finally:
        await _engine().dispose()

    timestamp = datetime.now(UTC)
    snapshot = {
        "timestamp": timestamp.strftime("%Y%m%dT%H%M%SZ"),
        "label": label,
        "golden_set": golden_path(golden).name,
        "git_commit": _git_commit(),
        "app_code_dirty": _git_dirty(),
        "postgres_db": settings.postgres_db,
        "llm_model": settings.llm_model,
        "judge_model": judge_model_name(),
        "judge_same_model_as_system": judge_model_name() == settings.llm_model,
        "embedding_model": settings.embedding_model,
        "aborted": aborted,
        "token_usage_total": ledger.snapshot(),
        "token_estimate_before_run": estimate,
        "judge_calibration": calibration_status(),
        "documents": {
            version[:8]: {
                "glue_rate": doc["glue"]["rate"],
                "vi_words": doc["glue"]["vi_words"],
                "glue_group": doc["glue_group"],
                "language": doc["language"],
                "n_chunks": len(doc["corpus"]),
            }
            for version, doc in docs.items()
        },
        "configs": results,
    }
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    stem = f"ablation_{timestamp.strftime('%Y%m%d')}_{label}"
    public = _strip_case_content(snapshot)
    (RESULTS_DIR / f"{stem}.json").write_text(
        json.dumps(public, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (RESULTS_DIR / f"{stem}_details.json").write_text(
        json.dumps({**snapshot, "details": details}, ensure_ascii=False, indent=1),
        encoding="utf-8",
    )
    from evaluation.report import render_markdown

    (RESULTS_DIR / f"{stem}.md").write_text(render_markdown(public), encoding="utf-8")
    print(f"[ablation] wrote {stem}.json / .md / _details.json")
    return 1 if aborted else 0


def _token_delta(before: dict[str, Any], after: dict[str, Any]) -> dict[str, Any]:
    by_purpose = {}
    for purpose, v in after["llm_by_purpose"].items():
        b = before["llm_by_purpose"].get(
            purpose, {"calls": 0, "prompt": 0, "completion": 0}
        )
        by_purpose[purpose] = {k: v[k] - b[k] for k in v}
    return {
        "llm_total_tokens": after["llm_total_tokens"] - before["llm_total_tokens"],
        "llm_by_purpose": by_purpose,
        "embedding_tokens": after["embedding"]["tokens"]
        - before["embedding"]["tokens"],
        "embedding_calls": after["embedding"]["calls"] - before["embedding"]["calls"],
    }


def _strip_case_content(snapshot: dict[str, Any]) -> dict[str, Any]:
    """The public snapshot keeps aggregates only: per-case rows and mismatch
    lists (case ids embed student/project names; replies quote reports) are
    left to the _details file."""
    out = json.loads(json.dumps(snapshot))
    for config in out["configs"].values():
        if not isinstance(config, dict):
            continue
        for tier in ("tier0", "tier1"):
            if config.get(tier):
                config[tier].pop("mismatches", None)
        if config.get("tier2"):
            config["tier2"].pop("per_case", None)
    return out


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--configs", nargs="+", choices=CONFIGS, default=list(CONFIGS))
    parser.add_argument("--label", default="baseline")
    parser.add_argument("--no-cache-suite", action="store_true")
    parser.add_argument(
        "--sample", type=int, default=None, help="smoke test: N cases per tier/intent"
    )
    parser.add_argument(
        "--golden",
        default=None,
        help="anonymized (default) | original | <path>; or set EVAL_GOLDEN_SET",
    )
    args = parser.parse_args()
    sys.exit(
        asyncio.run(
            main(
                args.configs,
                args.label,
                not args.no_cache_suite,
                args.sample,
                args.golden,
            )
        )
    )
