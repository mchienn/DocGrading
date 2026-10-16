"""Retrieval-only comparison on the golden set's tier 2 (no LLM).

    POSTGRES_DB=docgrading_test uv run python -m evaluation.retrieval_eval

Methods, all asked for the same k = 6 chunks of the case's submission, with
the query the chatbot uses (``extract_search_topic``):

- ``vector``: pgvector cosine ranking only (``rag._vector_ranked``);
- ``tsvector``: Postgres full-text stages only (all terms, then any term) -
  ``rag._keyword_ranked`` without its substring fallback;
- ``substring``: the substring (ILIKE) fallback stage on its own;
- ``keyword``: ``rag._keyword_ranked`` as shipped (tsvector, then substring
  when full-text finds nothing);
- ``hybrid_rrf``: ``rag.retrieve_chunks`` as shipped (vector + keyword, RRF).

Per case, with k = 6 fixed as the denominator (a method that returns fewer
chunks is not rewarded for it): P@6, ceiling = min(n_rel, 6) / 6, Recall
(share of gold locations hit), reciprocal rank of the first relevant chunk.
Aggregates come with 95% percentile-bootstrap intervals (resampling cases).

Cases whose query shares few words with every relevant chunk (query-term
coverage < 1/3) are flagged as "low lexical overlap": keyword methods can
barely find them, so they are where new cases are most informative.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import random
import sys
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import sqlalchemy as sa

from app.core.config import get_settings
from app.db.session import _engine
from app.models.chunk import DocumentChunk
from app.services import rag
from app.services.chat import extract_search_topic
from evaluation import scoring
from evaluation.golden import golden_path, load_golden_set
from evaluation.instrumentation import TokenLedger, make_embedding_provider
from evaluation.run_ablation import load_documents
from evaluation.sandbox import rolled_back_session

K = 6
METHODS = ("vector", "tsvector", "substring", "keyword", "hybrid_rrf")
BOOTSTRAP_ITERATIONS = 2000
BOOTSTRAP_SEED = 20261009
LOW_OVERLAP = 1 / 3


class CachedEmbeddings:
    """Embeds each distinct query once; vector and hybrid share it."""

    def __init__(self, inner: Any) -> None:
        self._inner = inner
        self._cache: dict[str, list[float]] = {}
        self.model_name = inner.model_name

    async def embed(self, texts: list[str]) -> list[list[float]]:
        missing = [t for t in texts if t not in self._cache]
        if missing:
            for text, vector in zip(
                missing, await self._inner.embed(missing), strict=True
            ):
                self._cache[text] = vector
        return [self._cache[t] for t in texts]


async def _tsvector_ranked(
    db: Any, version_ids: list[uuid.UUID], query: str
) -> list[uuid.UUID]:
    """Stages 1-2 of ``rag._keyword_ranked`` (mirrors its SQL)."""
    terms = rag.query_terms(query)
    if not terms:
        return []
    simple = sa.literal_column("'simple'::regconfig")
    for tsquery in (
        sa.func.plainto_tsquery(simple, " ".join(terms)),
        sa.func.to_tsquery(simple, " | ".join(terms)),
    ):
        stmt = (
            sa.select(DocumentChunk.id)
            .where(
                DocumentChunk.document_version_id.in_(version_ids),
                rag._tsvector().op("@@")(tsquery),
            )
            .order_by(
                sa.func.ts_rank(rag._tsvector(), tsquery).desc(),
                DocumentChunk.chunk_index,
            )
            .limit(K)
        )
        ids = list((await db.execute(stmt)).scalars().all())
        if ids:
            return ids
    return []


async def _substring_ranked(
    db: Any, version_ids: list[uuid.UUID], query: str
) -> list[uuid.UUID]:
    """Stage 3 of ``rag._keyword_ranked`` on its own (mirrors its SQL)."""
    terms = rag.query_terms(query)
    if not terms:
        return []
    stmt = (
        sa.select(DocumentChunk.id)
        .where(
            DocumentChunk.document_version_id.in_(version_ids),
            sa.or_(*(DocumentChunk.text.icontains(t, autoescape=True) for t in terms)),
        )
        .order_by(DocumentChunk.document_version_id, DocumentChunk.chunk_index)
        .limit(K)
    )
    return list((await db.execute(stmt)).scalars().all())


async def ranked_ids(
    method: str, db: Any, version: uuid.UUID, query: str, embedder: Any
) -> list[uuid.UUID]:
    if method == "vector":
        return (await rag._vector_ranked(db, [version], query, embedder))[:K]
    if method == "tsvector":
        return await _tsvector_ranked(db, [version], query)
    if method == "substring":
        return await _substring_ranked(db, [version], query)
    if method == "keyword":
        return (await rag._keyword_ranked(db, [version], query))[:K]
    if method == "hybrid_rrf":
        chunks = await rag.retrieve_chunks(
            db, [version], query, provider=embedder, limit=K
        )
        return [c.id for c in chunks]
    raise ValueError(method)


def query_coverage(query: str, relevant: list[scoring.ChunkLike]) -> float | None:
    """Best share of the query's content terms found in one relevant chunk."""
    terms = [scoring.fold_compact(t) for t in rag.query_terms(query)]
    if not terms or not relevant:
        return None
    return max(
        sum(1 for t in terms if t in scoring.fold_compact(f"{c.section_path} {c.text}"))
        / len(terms)
        for c in relevant
    )


def case_metrics(
    ranked: list[scoring.ChunkLike],
    gold: list[dict[str, Any]],
    n_relevant: int,
) -> dict[str, float]:
    relevant_flags = [
        any(scoring.chunk_is_relevant(c, g["page"], g["keyword"]) for g in gold)
        for c in ranked
    ]
    first = next((i for i, hit in enumerate(relevant_flags, start=1) if hit), None)
    return {
        "precision_at_k": sum(relevant_flags) / K,
        "ceiling": scoring.theoretical_max_precision(n_relevant, K),
        "recall": scoring.context_recall(ranked, gold),
        "reciprocal_rank": 1 / first if first else 0.0,
        "n_returned": len(ranked),
    }


def bootstrap_ci(
    rows: list[dict[str, float]], statistic: Any, rng: random.Random
) -> tuple[float | None, float | None]:
    if not rows:
        return None, None
    values = []
    for _ in range(BOOTSTRAP_ITERATIONS):
        sample = [rows[rng.randrange(len(rows))] for _ in rows]
        value = statistic(sample)
        if value is not None:
            values.append(value)
    return scoring.percentile(values, 2.5), scoring.percentile(values, 97.5)


def _mean(key: str) -> Any:
    return lambda rows: scoring.mean([r[key] for r in rows])


def _precision_vs_ceiling(rows: list[dict[str, float]]) -> float | None:
    ceiling = scoring.mean([r["ceiling"] for r in rows])
    precision = scoring.mean([r["precision_at_k"] for r in rows])
    return precision / ceiling if ceiling else None


STATISTICS = {
    "recall": _mean("recall"),
    "precision_at_k": _mean("precision_at_k"),
    "precision_vs_ceiling": _precision_vs_ceiling,
    "mrr": _mean("reciprocal_rank"),
}


def aggregate(rows: list[dict[str, float]], seed: int) -> dict[str, Any]:
    rng = random.Random(seed)
    out: dict[str, Any] = {"n": len(rows)}
    for name, statistic in STATISTICS.items():
        low, high = bootstrap_ci(rows, statistic, rng)
        out[name] = {"value": statistic(rows) if rows else None, "ci95": [low, high]}
    out["ceiling"] = scoring.mean([r["ceiling"] for r in rows])
    out["n_returned_lt_k"] = sum(1 for r in rows if r["n_returned"] < K)
    return out


async def run(golden: str | None) -> dict[str, Any]:
    cases = [c for c in load_golden_set(golden) if c["tier"] == 2]
    docs = await load_documents(cases)
    ledger = TokenLedger()
    embedder = CachedEmbeddings(make_embedding_provider(ledger))
    per_case: list[dict[str, Any]] = []
    async with rolled_back_session() as db:
        for case in cases:
            version = case["gold"]["document_version_id"]
            doc = docs[version]
            by_id = {c["chunk_id"]: c for c in doc["corpus"]}
            corpus = [
                scoring.ChunkLike(
                    c["page_start"], c["page_end"], c["section_path"], c["text"]
                )
                for c in doc["corpus"]
            ]
            gold = case["gold"]["relevant"]
            relevant = [
                c
                for c in corpus
                if any(
                    scoring.chunk_is_relevant(c, g["page"], g["keyword"]) for g in gold
                )
            ]
            query = extract_search_topic(case["question"]) or case["question"]
            coverage = query_coverage(query, relevant)
            row: dict[str, Any] = {
                "case_id": case["id"],
                "group": doc["glue_group"],
                "n_relevant_in_corpus": len(relevant),
                "query_coverage": coverage,
                "low_lexical_overlap": coverage is not None and coverage < LOW_OVERLAP,
                "methods": {},
            }
            for method in METHODS:
                ids = await ranked_ids(method, db, uuid.UUID(version), query, embedder)
                ranked = [
                    scoring.ChunkLike(
                        by_id[str(i)]["page_start"],
                        by_id[str(i)]["page_end"],
                        by_id[str(i)]["section_path"],
                        by_id[str(i)]["text"],
                    )
                    for i in ids
                ]
                row["methods"][method] = case_metrics(ranked, gold, len(relevant))
            per_case.append(row)
    await _engine().dispose()

    def rows_for(method: str, predicate: Any = lambda r: True) -> list[dict]:
        return [r["methods"][method] for r in per_case if predicate(r)]

    results: dict[str, Any] = {}
    for i, method in enumerate(METHODS):
        results[method] = {
            "all": aggregate(rows_for(method), BOOTSTRAP_SEED + i),
            "by_group": {
                g: aggregate(
                    rows_for(method, lambda r, g=g: r["group"] == g), BOOTSTRAP_SEED + i
                )
                for g in scoring.GROUPS
            },
            "low_lexical_overlap": aggregate(
                rows_for(method, lambda r: r["low_lexical_overlap"]), BOOTSTRAP_SEED + i
            ),
        }
    return {
        "timestamp": datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ"),
        "postgres_db": get_settings().postgres_db,
        "golden_set": golden_path(golden).name,
        "k": K,
        "bootstrap": {"iterations": BOOTSTRAP_ITERATIONS, "seed": BOOTSTRAP_SEED},
        "methods": results,
        "flagged_low_lexical_overlap": [
            {"case_id": r["case_id"], "query_coverage": r["query_coverage"]}
            for r in per_case
            if r["low_lexical_overlap"]
        ],
        "per_case": per_case,
        "tokens": ledger.snapshot(),
    }


def _fmt(stat: dict[str, Any]) -> str:
    value, (low, high) = stat["value"], stat["ci95"]
    if value is None:
        return "—"
    if low is None:
        return f"{value * 100:.1f}%"
    return f"{value * 100:.1f}% [{low * 100:.1f}–{high * 100:.1f}]"


def render(result: dict[str, Any]) -> str:
    lines = [
        f"# Truy hồi riêng — {result['timestamp']}",
        "",
        f"- DB `{result['postgres_db']}`, gold `{result['golden_set']}`, "
        f"k = {result['k']} "
        "(mẫu số cố định 6), CI 95% bootstrap "
        f"({result['bootstrap']['iterations']} lần, theo ca)",
        f"- Embedding: {result['tokens']['embedding']['tokens']:,} token / "
        f"{result['tokens']['embedding']['calls']} lần gọi; LLM: 0",
        "",
        "| Phương pháp | N | Recall | P@6 | P@6 / trần | MRR | Trả về < 6 chunk |",
        "|---|---|---|---|---|---|---|",
    ]
    for method, data in result["methods"].items():
        a = data["all"]
        lines.append(
            f"| {method} | {a['n']} | {_fmt(a['recall'])} "
            f"| {_fmt(a['precision_at_k'])} "
            f"| {_fmt(a['precision_vs_ceiling'])} | {_fmt(a['mrr'])} "
            f"| {a['n_returned_lt_k']} |"
        )
    lines += [
        "",
        f"Trần lý thuyết P@6 trung bình: "
        f"{result['methods']['vector']['all']['ceiling'] * 100:.1f}%.",
        "",
        "## Tách theo nhóm tài liệu (Recall / MRR)",
        "",
        "| Phương pháp | " + " | ".join(scoring.GROUPS) + " |",
        "|---|" + "---|" * len(scoring.GROUPS),
    ]
    for method, data in result["methods"].items():
        cells = []
        for g in scoring.GROUPS:
            a = data["by_group"][g]
            cells.append(
                "—"
                if not a["n"]
                else f"N={a['n']}: {_fmt(a['recall'])} / {_fmt(a['mrr'])}"
            )
        lines.append(f"| {method} | " + " | ".join(cells) + " |")
    flagged = result["flagged_low_lexical_overlap"]
    lines += [
        "",
        f"## Ca ít trùng từ khóa (độ phủ từ của truy vấn < {LOW_OVERLAP:.2f}): "
        f"{len(flagged)}",
        "",
    ]
    lines += [f"- {f['case_id']}: độ phủ {f['query_coverage']:.2f}" for f in flagged]
    if flagged:
        lines += [
            "",
            "| Phương pháp | Recall trên ca ít trùng | MRR |",
            "|---|---|---|",
        ]
        for method, data in result["methods"].items():
            a = data["low_lexical_overlap"]
            lines.append(f"| {method} | {_fmt(a['recall'])} | {_fmt(a['mrr'])} |")
    lines += [
        "",
        "⚠ N = 36 ca trên 6 tài liệu (mỗi tài liệu 6 câu): các ca trong cùng tài "
        "liệu không độc lập, nên khoảng tin cậy bootstrap theo ca có thể hẹp hơn "
        "thực tế. Nhóm mid/high mỗi nhóm chỉ có 1 tài liệu.",
    ]
    return "\n".join(lines) + "\n"


def main(golden: str | None) -> int:
    settings = get_settings()
    if settings.postgres_db == "docgrading":
        print("refusing to run against the dev database")
        return 2
    result = asyncio.run(run(golden))
    stem = f"retrieval_{result['timestamp'][:8]}"
    out_dir = Path(__file__).resolve().parent / "results"
    (out_dir / f"{stem}.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (out_dir / f"{stem}.md").write_text(render(result), encoding="utf-8")
    print(render(result))
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--golden", default=None)
    sys.exit(main(parser.parse_args().golden))
