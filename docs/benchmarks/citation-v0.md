# Citation v0 benchmark report

Generated: 2026-10-17T11:48:37.032696+00:00
Runtime: Python 3.13.13 on Windows 11
Document IR parser: `pypdf-pdfplumber-v8`

## Scope

- Issue #36 corpus: 35 PDF files.
- Gold corpus: 12 file entries, 11 unique PDF byte sets, 60 bibliography entries, 87 citation mentions.
- Identity gold: 6 fixed provider cases.
- Linkage edge gold: 2 deterministic cases.
- Annotation review: AI-assisted manual; `independent_human_review=false`. Regression baseline only; not evaluator activation or domain-review sign-off.
- Duplicate PDF bytes count for corpus integration but are deduplicated by SHA-256 for quality metrics.
- Gold annotations identify source PDFs by SHA-256 only; no paths stored.

## Corpus integration

- Validation + Document IR + citation parse: **35/35 passed** in 180.66s.
- Failed: 0.
- Extracted across all corpus files: 421 references, 413 mentions.
- Parser-uncertain documents: 3.

## Extraction metrics

Reference matching requires page overlap and normalized text similarity >= 0.82. Mention matching requires exact page and normalized marker text; element ID and line prefer duplicate matches.

| Metric | TP | FP | FN | Precision | Recall | F1 |
|---|---:|---:|---:|---:|---:|---:|
| Bibliography entries | 60 | 0 | 0 | 100.00% | 100.00% | 100.00% |
| Citation mentions | 87 | 0 | 0 | 100.00% | 100.00% | 100.00% |

- Bibliography status accuracy: **100.00%**.
- DOI/arXiv exact identifier accuracy: **100.00%**.
- DOI positive recall: **100.00%** (1 positive labels).
- arXiv positive recall: **100.00%** (22 positive labels).
- Gold parse time: 44.55s.

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

- Mention-to-reference exact mapping accuracy: **100.00%** (90/90).
- Mention linkage-status accuracy: **100.00%**.

| Metric | TP | FP | FN | Precision | Recall | F1 |
|---|---:|---:|---:|---:|---:|---:|
| Orphan mentions | 19 | 0 | 0 | 100.00% | 100.00% | 100.00% |
| Uncited references | 21 | 0 | 0 | 100.00% | 100.00% | 100.00% |
| Ambiguous / uncertain mappings | 1 | 0 | 0 | 100.00% | 100.00% | 100.00% |

## Crossref probe

- DOI: `10.1109/sp40000.2020.00063`.
- Adapter calls: 1 for 2 resolver attempts.
- Cache hits/rate: 1 / 50.00%.
- First resolution latency: 0.812s; cached latency: 0.000s.
- Live identity result: `VERIFIED`; cached external ID stable: `true`.

## Errors and limits

- Corpus failures: []
- Gold extraction mismatches: 0; SHA-256-prefix details: `[]`
- Live Crossref result is an operational probe, not gold truth. Offline identity metrics use fixed records.
- No OCR, arbitrary URL fetching, semantic claim support, or style grading is included.

Semantic claim support is benchmarked separately in
[`citation-semantic-v1.md`](citation-semantic-v1.md); that candidate set is not
human gold, so its quality gate remains blocked.

## Reproduce

```bash
cd backend
uv run python scripts/citation_benchmark.py --write-report --live-crossref
```
