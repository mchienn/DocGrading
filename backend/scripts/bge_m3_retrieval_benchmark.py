"""Compare bounded BM25 retrieval with BGE-M3 dense retrieval."""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import numpy as np
import psutil
import sentence_transformers
import torch
from sentence_transformers import SentenceTransformer

_REPO_ROOT = Path(__file__).resolve().parents[2]
_BACKEND_DIR = _REPO_ROOT / "backend"
if str(_BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(_BACKEND_DIR))

from app.services.semantic_citation import retrieve_passages  # noqa: E402
from scripts.semantic_citation_benchmark import _semantic_source  # noqa: E402

_FIXTURE = _BACKEND_DIR / "tests/fixtures/semantic_citation_annotations.v0.json"
_MODEL_ID = "BAAI/bge-m3"
_MODEL_REVISION = "5617a9f61b028005a4858fdac845db406aefb181"


def main() -> None:
    fixture = json.loads(_FIXTURE.read_text(encoding="utf-8"))
    candidates = [
        candidate
        for candidate in fixture["candidates"]
        if candidate["source_resolution"]["source_available"]
        and candidate["source_resolution"]["access_type"] == "FULL_TEXT"
        and candidate["expected_retrieval"]["evidence_passage_ids"]
    ]

    device = "cuda" if torch.cuda.is_available() else "cpu"
    process = psutil.Process()
    start_rss = process.memory_info().rss
    started = time.perf_counter()
    model = SentenceTransformer(
        _MODEL_ID,
        revision=_MODEL_REVISION,
        device=device,
        model_kwargs={"torch_dtype": torch.float16} if device == "cuda" else {},
    )
    model.max_seq_length = 512
    load_seconds = time.perf_counter() - started
    loaded_rss = process.memory_info().rss
    if device == "cuda":
        torch.cuda.reset_peak_memory_stats()

    all_texts: list[str] = []
    text_index: dict[str, int] = {}
    for candidate in candidates:
        for passage in candidate["source_data"]["passages"]:
            text = passage["text"]
            if text not in text_index:
                text_index[text] = len(all_texts)
                all_texts.append(text)
    queries = [
        candidate["expected_extraction"]["claim_text"] for candidate in candidates
    ]

    started = time.perf_counter()
    passage_vectors = model.encode(
        all_texts,
        batch_size=8,
        normalize_embeddings=True,
        convert_to_numpy=True,
        show_progress_bar=False,
    )
    passage_seconds = time.perf_counter() - started
    started = time.perf_counter()
    query_vectors = model.encode(
        queries,
        batch_size=8,
        normalize_embeddings=True,
        convert_to_numpy=True,
        show_progress_bar=False,
    )
    query_seconds = time.perf_counter() - started

    metrics = {
        name: {"hit": 0, "mrr_at_3_sum": 0.0, "top1": 0} for name in ("bm25", "dense")
    }
    for candidate, query_vector in zip(candidates, query_vectors, strict=True):
        query = candidate["expected_extraction"]["claim_text"]
        source = _semantic_source(candidate)
        local_vectors = np.stack(
            [passage_vectors[text_index[passage.text]] for passage in source.passages]
        )
        dense_order = np.argsort(-(local_vectors @ query_vector))
        dense_ids = [source.passages[index].passage_id for index in dense_order]
        ranked_ids = {
            "bm25": [
                passage.passage_id
                for passage, _score in retrieve_passages(query, source, top_k=3)
            ],
            "dense": dense_ids[:3],
        }
        gold = set(candidate["expected_retrieval"]["evidence_passage_ids"])
        for name, passage_ids in ranked_ids.items():
            rank = next(
                (
                    index
                    for index, passage_id in enumerate(passage_ids, 1)
                    if passage_id in gold
                ),
                None,
            )
            if rank is not None:
                metrics[name]["hit"] += 1
                metrics[name]["mrr_at_3_sum"] += 1 / rank
            if passage_ids and passage_ids[0] in gold:
                metrics[name]["top1"] += 1

    count = len(candidates)
    result = {
        "model_id": _MODEL_ID,
        "model_revision": _MODEL_REVISION,
        "sentence_transformers_version": sentence_transformers.__version__,
        "torch_version": torch.__version__,
        "numpy_version": np.__version__,
        "psutil_version": psutil.__version__,
        "device": device,
        "candidate_count": count,
        "unique_passages": len(all_texts),
        "model_load_seconds": round(load_seconds, 3),
        "rss_growth_mb": round((loaded_rss - start_rss) / 1024 / 1024, 1),
        "passage_encode_seconds": round(passage_seconds, 3),
        "passages_per_second": round(len(all_texts) / passage_seconds, 2),
        "query_encode_seconds": round(query_seconds, 3),
        "queries_per_second": round(len(queries) / query_seconds, 2),
        "gpu_peak_allocated_mb": (
            round(torch.cuda.max_memory_allocated() / 1024 / 1024, 1)
            if device == "cuda"
            else None
        ),
        "gpu_peak_reserved_mb": (
            round(torch.cuda.max_memory_reserved() / 1024 / 1024, 1)
            if device == "cuda"
            else None
        ),
        **{
            name: {
                "hit_at_3": round(values["hit"] / count, 6),
                "mrr_at_3": round(values["mrr_at_3_sum"] / count, 6),
                "top1": round(values["top1"] / count, 6),
            }
            for name, values in metrics.items()
        },
    }
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
