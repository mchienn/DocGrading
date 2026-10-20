# Citation Semantic Support v1 Benchmark Report

Generated: 2026-10-15 06:54:32 UTC
Runtime: Python 3.13.13 on Windows 11
Benchmark Suite: `backend/scripts/semantic_citation_benchmark.py`

## Quality Gate Outcome

- Status: **BLOCKED**
- Passed: `false`
- Reason: `quality gate blocked: human_gold_pairs=0 (<100), double_annotated_fraction=0.0 (<0.20), domain_approved=false, verdict unmeasured`

### Quality Gate Blockers

1. **human_gold_pairs=0 (<100 threshold required for production promotion)**: human_gold_pairs=0 (<100 threshold required for production promotion). Current set is synthetic draft candidates.
2. **double_annotated_fraction=0**: double_annotated_fraction=0.0% (<20.0% threshold required). Double review target designated but not completed.
3. **domain_approved=false**: domain_approved=false. Expert domain review and signed off criteria required.
4. **verdict / e2e accuracy is unmeasured against human ground truth**: verdict / e2e accuracy is unmeasured against human ground truth.

## Candidate Dataset Composition

- Total Candidate Pairs: **120**
- Annotation Status: `AI_DRAFT` (Candidate set for annotation workbook; not human ground truth).
- Independent Human Review: `false`
- Human Gold Pairs: **0**
- Language Distribution:
  - Vietnamese Claim / English Source (`vi_en`): **105 / 120** (87.50% - target >= 80.0%).
  - Monolingual English (`en_en`): **15 / 120** (12.50%).
- Double Review Flagged: **30 / 120** (25.00% - target >= 20.0%).

### Scenario Breakdown

| Scenario | Description / Fault Injected | Candidate Count |
|---|---|---:|
| `direct_support` | Direct semantic alignment and textual support | 8 |
| `can_cannot_negation` | Polarity inversion / can vs cannot negation | 8 |
| `numeric_mismatch` | Discrepancy in numeric metrics or quantitative results | 8 |
| `added_unsupported_fact` | True statement bundled with unverified assertion | 8 |
| `concept_switch` | Swapped entity, algorithm, or metric definition | 8 |
| `partial_to_whole_exaggeration` | Overgeneralization from narrow benchmark to universal claim | 8 |
| `omitted_condition` | Omission of prerequisite hardware, dataset, or assumption | 8 |
| `suggests_to_proves` | Upgrading preliminary correlation/hypothesis to absolute proof | 8 |
| `related_unsupported` | Domain overlap without support for specific assertion | 8 |
| `irrelevant` | Completely unrelated research domain or topic | 8 |
| `multiple_citations_one_claim` | Multiple citation markers within single sentence scope | 8 |
| `multiple_claims_one_citation` | Multiple sentences referencing single citation source | 8 |
| `table_evidence` | Evidence situated in structured table row rather than prose | 8 |
| `abstract_only` | Source restricted to abstract-only metadata (fails verification) | 8 |
| `source_unavailable` | Source unindexed, proprietary, or unavailable | 8 |

## Stage 1: Claim Extraction & Citation Scope Attribution

- Expected claim-reference pairs: **128** across 120 candidates
*Note: Evaluated against candidate draft spans [DRAFT/SYNTHETIC - NOT HUMAN VALIDATED]*

- Claim extraction precision: **100.00%** (128/128)
- Claim extraction recall: **100.00%** (128/128)
- Claim extraction F1: **100.00%**
- Citation-scope attribution accuracy: **100.00%** (128/128)

| Metric | TP | FP | FN | Precision | Recall | F1 |
|---|---:|---:|---:|---:|---:|---:|
| Claim Extraction | 128 | 0 | 0 | 100.00% | 100.00% | 100.00% |
| Citation Attribution | 128 | 0 | 0 | 100.00% | 100.00% | 100.00% |

## Stage 2: Source Resolution & Availability

*Note: Offline resolution from self-contained candidate descriptors without live network or external resolvers.*

- Available Sources Resolved: **112 / 112** (100.00%)
- Full-text access coverage: **86.67%** (104/120)
- Abstract-only rate: **6.67%** (8/120)
- Source unavailable rate: **6.67%** (8/120)

| Source Category | Count | Proportion | Resolution Outcome |
|---|---:|---:|---|
| Full-Text Indexed | 104 | 86.67% | Resolved (passages indexed) |
| Abstract-Only | 8 | 6.67% | Resolved (abstract paragraph) |
| Unavailable / Unindexed | 8 | 6.67% | Handled (`SOURCE_UNAVAILABLE`) |

## Stage 3: Lexical Passage Retrieval (BM25)

*Note: Evaluated on 104 full-text candidates with anchored source passages. This stage measures the BM25 fallback used when no encoder is configured. BGE-M3 dense measured 91.35% Hit@3 here versus 93.27% for BM25, but each synthetic source has only five passages; on real arXiv papers dense retrieval is far ahead for Vietnamese claims (see `docs/benchmarks/bge-m3-retrieval-2026-09-24.md`).*

- Evaluated Candidates: **104**
- Hit@3: **93.27%** (97/104)
- Recall@3: **93.27%**
- Mean Reciprocal Rank (MRR@3): **0.681**
- Evidence Anchor Top-1 Accuracy: **50.96%**

### Subgroup Analysis

| Subset | Count | Hit@3 | Recall@3 | MRR@3 | Anchor Top-1 Acc |
|---|---:|---:|---:|---:|---:|
| Overall Full-Text | 104 | 93.27% | 93.27% | 0.681 | 50.96% |
| Cross-Lingual (`vi_en`) | 91 | 92.31% | 92.31% | 0.654 | 47.25% |
| Monolingual (`en_en`) | 13 | 100.00% | 100.00% | 0.872 | 76.92% |

## Stage 4: Prediction & Verdict Classification

- Status: `NOT_MEASURED`
- Predictions file: None supplied (`--predictions` not specified).
- Note: Verdict accuracy, Macro-F1, Confusion Matrix, and False Accusation Rate are strictly NOT_MEASURED without predictions. Metrics are never fabricated.

## Stage 5: End-to-End System Performance & Telemetry

- Verdict E2E Accuracy: **NOT_MEASURED**
- Teacher Acceptance Rate: **NOT_MEASURED**
- Teacher Override Rate: **NOT_MEASURED**
- Benchmark Execution Latency: **0.028s** (0.23 ms/candidate pair across Stages 1-3)
- Model API Calls: **0**
- Input Tokens: **0**
- Output Tokens: **0**
- Model Cost: **null** ($0.00)

## Errors and Known Limits

1. **No Human Semantic Gold**: Current dataset is a synthetic AI draft set (`human_gold_pairs=0`). Accuracy numbers must not be claimed until independent double annotation by domain experts is conducted.
2. **Encoder Retrieval Not Scored Here**: Configured deployments rank passages with the shared encoder instead of BM25. Its measurements on this corpus and on real papers are in `docs/benchmarks/bge-m3-retrieval-2026-09-24.md`.
3. **Abstract-Only Denial**: Under security policy, abstract-only sources fail semantic verification (`INSUFFICIENT_EVIDENCE`), denying ungrounded claims by default.
4. **No Live Network / AWS**: Benchmark executes 100% offline without live network, PDF parser subprocesses, or Bedrock API calls.

## Reproduce

```bash
cd backend
uv run python scripts/semantic_citation_benchmark.py --write-report
```

With predictions:

```bash
cd backend
uv run python scripts/semantic_citation_benchmark.py --predictions path/to/predictions.json --write-report
```
