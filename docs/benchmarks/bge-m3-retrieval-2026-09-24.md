# BGE-M3 retrieval experiment

Date: 2026-09-24

## Decision

Keep production retrieval on bounded BM25. Do not add BGE-M3, PyTorch, Transformers, Sentence Transformers, or NumPy to production dependencies.

BGE-M3 improved ranking when evidence was found, but failed primary retrieval criterion: Hit@3 was lower than BM25. CPU latency and memory cost are too high for shared 8-vCPU/16-GB deployment target.

## Corpus and method

- Dataset: existing `semantic_citation_annotations.v0.json` synthetic draft.
- Evaluated pairs: 104 full-text claim/source pairs.
- Unique source passages: 520.
- Language mix: same Vietnamese-claim/English-source and English/English cases as semantic baseline.
- Gold status: synthetic `AI_DRAFT`; not human gold.
- Model ID: `BAAI/bge-m3`.
- Model revision: `5617a9f61b028005a4858fdac845db406aefb181` (Hugging Face commit SHA).
- Sequence cap: 512 tokens; current source passages fit this bounded retrieval use.
- Dense batch size: 8.
- Fusion: production reciprocal-rank fusion implementation over BM25 and dense rank IDs.
- Device: CPU. `torch 2.14.0+cpu`; CUDA unavailable to benchmark process.
- Host: Windows 11, 16 logical CPU cores. No production GPU assumption.
- Reproducibility status: Rerun on 2026-10-09 with the pinned command below
  (`sentence-transformers 6.1.0`, `torch 2.14.0+cpu`, `numpy 2.5.3`,
  `psutil 7.2.2`, model revision above) reproduced every quality metric exactly.

## Results

| Retriever | Hit@3 | MRR@3 | Top-1 |
|---|---:|---:|---:|
| BM25 | **93.27%** | 0.6811 | 50.96% |
| BGE-M3 dense | 91.35% | **0.7965** | **70.19%** |
| BM25 + BGE-M3 RRF | 86.54% | 0.7276 | 60.58% |

Primary gate is Hit@3 because model receives top three passages. BM25 wins by 1.92 percentage points over dense and 6.73 points over current RRF. Better dense MRR@3/top-1 does not compensate for lost evidence coverage.

## Resource measurements

| Run | Model load | RSS growth after load | Passage encoding | Throughput | Query encoding | Throughput |
|---|---:|---:|---:|---:|---:|---:|
| First uncached artifact run | 49.877 s | 1,381.5 MB | 46.686 s | 11.14 passages/s | 11.352 s | 9.16 queries/s |
| Cached artifact rerun | 9.182 s | 325.5 MB | 45.377 s | 11.46 passages/s | 11.268 s | 9.23 queries/s |
| Pinned cached rerun (2026-10-09) | 4.230 s | 319.1 MB | 28.473 s | 18.26 passages/s | 6.859 s | 15.16 queries/s |

RSS delta varies with model artifact and OS page cache; encoding time varies with host load. Encoding still costs roughly 30–45 seconds for 520 passages plus 7–11 seconds for 104 queries. This competes with PDF parsing, API, worker, and database workloads on shared host.

## Boundaries

- No human-gold verdict or retrieval set; metrics are regression evidence only.
- Dense path tested. BGE-M3 sparse and ColBERT outputs were not tested because dense already missed Hit@3 and resource budget; adding more scoring stages would increase cost.
- No CUDA result. GPU capacity is not part of current deployment contract.
- No production dependency or model artifact was added.

Reconsider BGE-M3 only when human-gold retrieval data shows BM25 below target, dedicated resource budget exists, and candidate improves Hit@3 without violating end-to-end latency.

## Reproduce

The script emits model ID/revision and runtime versions for each run.

```bash
cd backend
uv run --with sentence-transformers==6.1.0 --with torch==2.14.0 --with numpy==2.5.3 --with psutil==7.2.2 python scripts/bge_m3_retrieval_benchmark.py
```

## Primary references

- [BGE-M3 model documentation](https://bge-model.com/bge/bge_m3.html)
- [BAAI/bge-m3 model card](https://huggingface.co/BAAI/bge-m3)
