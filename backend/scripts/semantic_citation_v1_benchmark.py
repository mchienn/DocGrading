"""Stage 3/4 benchmark on the AI-consensus citation-semantic-support v1 set.

Stage 3: evidence Hit@3 / MRR@3 of production retrieval (BM25, or the shared encoder
when SEMANTIC_ENCODER_URL/SEMANTIC_ENCODER_MODEL are set) for SUPPORTED,
PARTIALLY_SUPPORTED and CONTRADICTED pairs; gold passages are the production
passages that contain an evidence quote.
Stage 4 (--model): production evaluate_claim with a hosted model on the test split
(--provider gemini or deepseek, key from GEMINI_API_KEY / DEEPSEEK_API_KEY):
macro-F1, false-accusation rate and structured success over the pairs the provider
answered; provider failures (HTTP 429, outages) are counted separately.

Sources are rebuilt with production Source IR from arXiv PDFs kept in --pdf-cache
(downloaded from the fixed arXiv PDF endpoint when missing, sha256-checked).
"""

from __future__ import annotations

import argparse
import collections
import concurrent.futures
import hashlib
import json
import os
import re
import sys
import threading
import time
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.models.enums import LLMProtocol, LLMProvider  # noqa: E402
from app.services import semantic_citation as semantic  # noqa: E402
from app.services.citation import (
    LINKED,
    PARSED,
    VERIFIED,
    CitationReference,
)  # noqa: E402
from app.services.semantic_adapters import HostedSemanticModel  # noqa: E402
from app.services.text_encoder import encoder_from_settings  # noqa: E402

_ROOT = Path(__file__).resolve().parents[2]
_FIXTURE = _ROOT / "backend/tests/fixtures/semantic_citation_annotations.v1.json"
_REPORT = _ROOT / "docs/benchmarks/citation-semantic-v1-ai-consensus.md"
LABELS = (
    "SUPPORTED",
    "PARTIALLY_SUPPORTED",
    "CONTRADICTED",
    "IRRELEVANT",
    "INSUFFICIENT_EVIDENCE",
)
EVIDENCE_LABELS = {"SUPPORTED", "PARTIALLY_SUPPORTED", "CONTRADICTED"}
# Benchmark gate for AI-consensus labels, chosen 2026-10-17 to mirror spec section 7
# minus the human-gold criteria. It does not unlock the production gate, which stays
# blocked until a human-gold set and server approval exist.
GATE = {
    "pairs": 800,
    "judge_families": 2,
    "macro_f1": 0.80,
    "false_accusation": 0.02,
    "hit_at_3": 0.90,
    "structured": 0.99,
}
_PROTOCOL = {
    LLMProvider.GEMINI: LLMProtocol.GEMINI_GENERATE_CONTENT,
    LLMProvider.DEEPSEEK: LLMProtocol.OPENAI_CHAT,
}


def _norm(text: str) -> str:
    return " ".join(text.split()).casefold()


def _reference(source: dict) -> CitationReference:
    raw = f"{', '.join(source['authors'])}. {source['title']}. {source['year']}."
    return CitationReference(
        id=source["source_id"],
        number=1,
        raw=raw,
        page_number=1,
        element_id="ref",
        start=0,
        end=len(raw),
        snippet=raw,
        arxiv_id=source["arxiv_id"],
        title=source["title"],
        authors=tuple(source["authors"]),
        year=source["year"],
        parser_status=PARSED,
        identity_status=VERIFIED,
        linkage_status=LINKED,
    )


def _pdf(source: dict, cache: Path) -> bytes | None:
    path = cache / f"{source['arxiv_id']}.pdf"
    if not path.exists():
        time.sleep(3.5)
        request = urllib.request.Request(
            f"https://arxiv.org/pdf/{source['arxiv_id']}",
            headers={"User-Agent": "DocGrading/1.0"},
        )
        try:
            with urllib.request.urlopen(request, timeout=60) as response:
                path.write_bytes(response.read(50_000_001))
        except OSError:
            return None
    data = path.read_bytes()
    return data if hashlib.sha256(data).hexdigest() == source["pdf_sha256"] else None


def _pair(pair: dict) -> semantic.ClaimCitationPair:
    claim = pair["claim"]
    return semantic.ClaimCitationPair(
        pair_id=pair["pair_id"],
        claim_id=pair["pair_id"],
        mention_id="m",
        reference_id=pair["source_id"],
        claim=claim,
        context="",
        extraction_method=semantic.ExtractionMethod.SENTENCE,
        claim_anchor=semantic.SemanticClaimAnchor(
            page_number=1, element_id="p", start=0, end=len(claim)
        ),
    )


def _f1(gold: list[str], pred: list[str], label: str) -> float:
    tp = sum(g == p == label for g, p in zip(gold, pred, strict=True))
    fp = sum(p == label and g != label for g, p in zip(gold, pred, strict=True))
    fn = sum(g == label and p != label for g, p in zip(gold, pred, strict=True))
    return 2 * tp / (2 * tp + fp + fn) if tp else 0.0


def _verdict_metrics(pairs: list[tuple[str, str]]) -> dict:
    """Metrics over (gold label, predicted status) pairs."""
    gold = [g for g, _ in pairs]
    predicted = [p for _, p in pairs]
    per_class = {label: round(_f1(gold, predicted, label), 4) for label in LABELS}
    supported = [
        i for i, g in enumerate(gold) if g in EVIDENCE_LABELS - {"CONTRADICTED"}
    ]
    accused = sum(predicted[i] in {"CONTRADICTED", "IRRELEVANT"} for i in supported)
    return {
        "answered": len(pairs),
        "accuracy": (
            round(sum(g == p for g, p in pairs) / len(pairs), 4) if pairs else 0.0
        ),
        "macro_f1": round(sum(per_class.values()) / len(LABELS), 4),
        "per_class_f1": per_class,
        "false_accusation_rate": (
            round(accused / len(supported), 4) if supported else 0.0
        ),
        "structured_success": (
            round(sum(p != "NEEDS_MANUAL_REVIEW" for p in predicted) / len(pairs), 4)
            if pairs
            else 0.0
        ),
        "confusion": {
            g: dict(collections.Counter(p for gg, p in pairs if gg == g))
            for g in LABELS
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--fixture", type=Path, default=_FIXTURE)
    parser.add_argument(
        "--pdf-cache", type=Path, default=_ROOT / "backend/.cache/semantic-v1-pdfs"
    )
    parser.add_argument(
        "--min-interval", type=float, default=0.0, help="seconds between model calls"
    )
    parser.add_argument("--model", help="hosted model ID for stage 4")
    parser.add_argument("--provider", choices=("gemini", "deepseek"), default="gemini")
    parser.add_argument("--concurrency", type=int, default=1)
    parser.add_argument("--sample", type=int, help="evaluate this many test pairs")
    parser.add_argument("--write-report", action="store_true")
    args = parser.parse_args()
    fixture = json.loads(args.fixture.read_text(encoding="utf-8"))
    args.pdf_cache.mkdir(parents=True, exist_ok=True)

    sources, references = {}, {}
    for item in fixture["sources"]:
        data = _pdf(item, args.pdf_cache)
        reference = _reference(item)
        try:
            built = (
                semantic._source_from_pdf_bytes(
                    reference,
                    "bench",
                    data,
                    50_000_000,
                    "benchmark",
                    require_pdf_magic=True,
                )
                if data
                else None
            )
        except Exception:  # production rejects it too (PDF limits); skip its pairs
            built = None
        if built is not None:
            sources[item["source_id"]], references[item["source_id"]] = built, reference
    pairs = [pair for pair in fixture["pairs"] if pair["source_id"] in sources]

    from app.core.config import get_settings

    encoder = encoder_from_settings(get_settings())
    ranker = semantic.EncoderRanker(encoder) if encoder else None
    hits = collections.Counter()
    totals = collections.Counter()
    reciprocal = 0.0
    for pair in pairs:
        quotes = [_norm(quote) for quote in pair.get("evidence_quotes", [])]
        if pair["label"] not in EVIDENCE_LABELS or not quotes:
            continue
        source = sources[pair["source_id"]]
        gold = {
            p.passage_id
            for p in source.passages
            if any(q in _norm(p.text) for q in quotes)
        }
        if not gold:
            continue
        query = semantic._retrieval_query(pair["claim"])
        ranked = ranker(query, source.passages) if ranker else None
        top = [
            p.passage_id for p, _ in semantic.retrieve_passages(query, source, ranked)
        ]
        rank = next((i + 1 for i, item in enumerate(top) if item in gold), None)
        for key in ("all", pair["claim_language"]):
            totals[key] += 1
            hits[key] += rank is not None
        reciprocal += 1 / rank if rank else 0.0
    stage3 = {
        "retrieval": (
            (f"{encoder.model} encoder" + (" + reranker" if encoder.rerank_url else ""))
            if encoder
            else "BM25"
        ),
        "queries": totals["all"],
        "hit_at_3": hits["all"] / totals["all"] if totals["all"] else 0.0,
        "mrr_at_3": reciprocal / totals["all"] if totals["all"] else 0.0,
        "hit_at_3_by_language": {
            k: f"{hits[k]}/{totals[k]}" for k in sorted(totals) if k != "all"
        },
    }

    stage4: dict = {"status": "NOT_MEASURED"}
    if args.model:
        provider = LLMProvider(args.provider.upper())
        inner = HostedSemanticModel(
            {
                "provider": provider,
                "protocol": _PROTOCOL[provider],
                "model_id": args.model,
                "credential": os.environ[f"{provider.value}_API_KEY"],
                "max_tokens": 512,
            }
        )
        failed_claims: set[str] = set()
        pace = threading.Lock()
        next_call = [0.0]

        class _RecordingModel:
            """Paces calls (--min-interval, for free-tier per-minute limits) and
            remembers claims whose call failed at the provider (429, outage), so
            model quality is reported apart from provider availability."""

            def evaluate(self, **kwargs):
                with pace:
                    time.sleep(max(0.0, next_call[0] - time.monotonic()))
                    next_call[0] = time.monotonic() + args.min_interval
                try:
                    return inner.evaluate(**kwargs)
                except semantic.SemanticProviderError:
                    failed_claims.add(kwargs["claim"])
                    raise

        model = semantic._BudgetedSemanticModel(_RecordingModel(), 10_000)
        test = [pair for pair in pairs if pair["split"] == "test"]
        test_size = len(test)
        if args.sample:
            # Deterministic uniform sample (free-tier daily request quotas).
            test = sorted(
                test, key=lambda p: hashlib.sha256(p["pair_id"].encode()).hexdigest()
            )[: args.sample]
        done = [0]

        def judge(pair: dict) -> tuple[str, str]:
            result = semantic.evaluate_claim(
                _pair(pair),
                references[pair["source_id"]],
                sources[pair["source_id"]],
                model,
                dense_ranker=ranker,
            )
            with pace:
                done[0] += 1
                if done[0] % 25 == 0:
                    print(
                        f"stage 4: {done[0]}/{len(test)}", file=sys.stderr, flush=True
                    )
            return result.status.value, result.reason_code

        with concurrent.futures.ThreadPoolExecutor(max(1, args.concurrency)) as pool:
            outcomes = list(pool.map(judge, test))
        answered = [
            (pair["label"], status)
            for pair, (status, _) in zip(test, outcomes, strict=True)
            if pair["claim"] not in failed_claims
        ]
        stage4 = {
            "model": f"{provider.value}/{args.model}",
            "pairs": len(test),
            "test_pairs": test_size,
            "provider_failures": len(test) - len(answered),
            **_verdict_metrics(answered),
            "manual_review_reasons": dict(
                collections.Counter(
                    reason
                    for pair, (status, reason) in zip(test, outcomes, strict=True)
                    if status == "NEEDS_MANUAL_REVIEW"
                    and pair["claim"] not in failed_claims
                )
            ),
        }

    judges = fixture["annotation_set"].get("judges", [])

    def family(name: str) -> str:
        return re.split(r"[-.]", name.split("/")[-1])[0].casefold()

    families = {family(name) for name in judges} - (
        {family(args.model)} if args.model else set()
    )
    gate_checks = {
        f"pairs >= {GATE['pairs']}": len(pairs) >= GATE["pairs"],
        f"judge families (not the evaluated model's) >= {GATE['judge_families']}": (
            len(families) >= GATE["judge_families"]
        ),
        f"evidence Hit@3 >= {GATE['hit_at_3']}": stage3["hit_at_3"] >= GATE["hit_at_3"],
        f"macro-F1 >= {GATE['macro_f1']}": (
            stage4.get("macro_f1", 0) >= GATE["macro_f1"]
        ),
        f"false accusation <= {GATE['false_accusation']}": (
            stage4.get("false_accusation_rate", 1) <= GATE["false_accusation"]
        ),
        f"structured output >= {GATE['structured']}": (
            stage4.get("structured_success", 0) >= GATE["structured"]
        ),
        "no provider failures": stage4.get("provider_failures", 1) == 0,
    }
    results = {
        "pairs": len(pairs),
        "sources": len(sources),
        "stage3": stage3,
        "stage4": stage4,
        "gate": {"passed": all(gate_checks.values()), "checks": gate_checks},
    }
    print(json.dumps(results, indent=2, ensure_ascii=False))
    if args.write_report:
        counts = collections.Counter(pair["label"] for pair in pairs)
        meta = fixture["annotation_set"]
        verdicts = (
            ["- `NOT_MEASURED` (run with `--model`)."]
            if stage4.get("status")
            else [
                f"- Model `{stage4['model']}` on {stage4['pairs']} of "
                f"{stage4['test_pairs']} test pairs (prompt "
                f"`{semantic.SEMANTIC_PROMPT_VERSION}`, "
                f"retrieval {stage3['retrieval']}); "
                f"provider failures (429/outage, excluded below) "
                f"{stage4['provider_failures']}; answered {stage4['answered']}: "
                f"accuracy {stage4['accuracy']:.2%}, "
                f"macro-F1 **{stage4['macro_f1']:.3f}**, "
                f"false accusation {stage4['false_accusation_rate']:.2%}, "
                f"structured output {stage4['structured_success']:.2%}.",
                f"- Per-class F1: {stage4['per_class_f1']}.",
                f"- Confusion (gold -> predicted): {stage4['confusion']}.",
                f"- `NEEDS_MANUAL_REVIEW` reasons: {stage4['manual_review_reasons']}.",
            ]
        )
        lines = [
            "# Citation semantic support v1 (AI-consensus) benchmark",
            "",
            f"Fixture: `{args.fixture.name}` ({meta.get('annotation_status')}, "
            f"human gold pairs {meta.get('human_gold_pairs', 0)}); "
            f"{len(pairs)} pairs over {len(sources)} rebuilt sources.",
            f"Labels: {dict(counts)}. Claims generated by {meta.get('generator')}. "
            f"Judges: {', '.join(judges)}.",
            "",
            "## Stage 3: evidence retrieval",
            "",
            f"- Retrieval: {stage3['retrieval']}; queries {stage3['queries']}.",
            f"- Hit@3 **{stage3['hit_at_3']:.2%}**, MRR@3 {stage3['mrr_at_3']:.3f}; "
            f"by claim language {stage3['hit_at_3_by_language']}.",
            "- Encoder retrieval on these queries (TEI on a GPU): "
            "[`bge-m3-retrieval-2026-09-24.md`](bge-m3-retrieval-2026-09-24.md).",
            "",
            "## Stage 4: verdicts",
            "",
            *verdicts,
            "",
            "## Gate (AI-consensus benchmark gate, 2026-10-17)",
            "",
            *(
                f"- {'PASS' if ok else 'FAIL'}: {name}"
                for name, ok in gate_checks.items()
            ),
            "",
            f"Gate {'passed' if results['gate']['passed'] else 'blocked'}. "
            "Passing also requires recorded owner approval; labels are AI consensus, "
            "not human gold.",
            "",
            "## Reproduce",
            "",
            "```bash",
            "cd backend",
            "# optional encoder: SEMANTIC_ENCODER_URL/_MODEL, SEMANTIC_RERANKER_URL",
            "GEMINI_API_KEY=... uv run python \\",
            "  scripts/semantic_citation_v1_benchmark.py --model <id> --write-report",
            "```",
            "",
        ]
        _REPORT.write_text("\n".join(lines), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
