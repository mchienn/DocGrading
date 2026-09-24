# Citation v0 benchmark report

Generated: 2026-09-24T08:42:04.619101+00:00
Runtime: Python 3.13.14 on Windows 11
Document IR parser: `pypdf-pdfplumber-v5`

## Scope

- Issue #36 corpus: 35 PDF files.
- Gold corpus: 12 file entries, 11 unique PDF byte sets, 60 bibliography entries, 69 citation mentions.
- Identity gold: 6 fixed provider cases.
- Linkage edge gold: 2 deterministic cases.
- Annotation review: AI-assisted manual; `independent_human_review=false`. Regression baseline only; not evaluator activation or domain-review sign-off.
- Duplicate PDF bytes count for corpus integration but are deduplicated by SHA-256 for quality metrics.

## Corpus integration

- Validation + Document IR + citation parse: **35/35 passed** in 169.78s.
- Failed: 0.
- Extracted across all corpus files: 433 references, 397 mentions.
- Parser-uncertain documents: 10.

## Extraction metrics

Reference matching requires page overlap and normalized text similarity >= 0.82. Mention matching requires exact page and normalized marker text; element ID and line prefer duplicate matches.

| Metric | TP | FP | FN | Precision | Recall | F1 |
|---|---:|---:|---:|---:|---:|---:|
| Bibliography entries | 59 | 1 | 1 | 98.33% | 98.33% | 98.33% |
| Citation mentions | 69 | 0 | 0 | 100.00% | 100.00% | 100.00% |

- Bibliography status accuracy: **100.00%**.
- DOI/arXiv exact identifier accuracy: **98.33%**.
- DOI positive recall: **100.00%** (1 positive labels).
- arXiv positive recall: **95.45%** (22 positive labels).
- Gold parse time: 42.20s.

## Identity metrics

- Identifier extraction accuracy: **100.00%**.
- Identity status accuracy: **100.00%**.
- Unresolved rate: **50.00%**.
- `METADATA_MISMATCH` false-positive rate: **0.00%**.

| Metric | TP | FP | FN | Precision | Recall | F1 |
|---|---:|---:|---:|---:|---:|---:|
| Metadata mismatch cases | 2 | 0 | 0 | 100.00% | 100.00% | 100.00% |
| Field-level mismatches | 5 | 0 | 0 | 100.00% | 100.00% | 100.00% |

## Linkage metrics

- Mention-to-reference exact mapping accuracy: **97.22%** (70/72).
- Mention linkage-status accuracy: **97.22%**.

| Metric | TP | FP | FN | Precision | Recall | F1 |
|---|---:|---:|---:|---:|---:|---:|
| Orphan mentions | 1 | 0 | 0 | 100.00% | 100.00% | 100.00% |
| Uncited references | 21 | 0 | 0 | 100.00% | 100.00% | 100.00% |
| Ambiguous / uncertain mappings | 1 | 2 | 0 | 33.33% | 100.00% | 50.00% |

## Crossref probe

- DOI: `10.1109/sp40000.2020.00063`.
- Adapter calls: 1 for 2 resolver attempts.
- Cache hits/rate: 1 / 50.00%.
- First resolution latency: 0.970s; cached latency: 0.000s.
- Live identity result: `VERIFIED`; cached external ID stable: `true`.

## Errors and limits

- Corpus failures: []
- Gold extraction mismatches: 2; SHA-256-prefix details: `[{"kind": "reference_fn", "gold_id": "reference-7", "best_similarity": 0.6314, "sha256_prefix": "8e4dd65a4590"}, {"kind": "reference_fp", "actual_id": "reference-7", "sha256_prefix": "8e4dd65a4590"}]`
- Live Crossref result is an operational probe, not gold truth. Offline identity metrics use fixed records.
- No OCR, arbitrary URL fetching, semantic claim support, or style grading is included.

## Reproduce

```bash
cd backend
uv run python scripts/citation_benchmark.py --write-report --live-crossref
```
