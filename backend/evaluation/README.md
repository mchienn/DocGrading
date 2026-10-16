# Chatbot evaluation benchmark

Implements the test infrastructure described in
`docs/benchmarks/RAG_evaluation-benchmark.md`: a frozen golden set, a runner
that calls the real chatbot service (`handle_chat()`) directly, and an
ablation over three configurations of the chatbot.

## Files

- `golden_set.anonymized.jsonl` — the frozen test set (145 cases, tiers
  0–3), committed. Each line: `id`, `tier`, `intent_expected`, `question`,
  `scope` (`course_id`/`assignment_id`/`submission_id`), `gold`,
  `gold_source`. Tier 2's `gold.relevant` is a **list** of
  `{"page", "keyword"}` locations. Its three `T3-CACHE-*` rows are no longer
  run (see "Cache correctness").
- `golden_set.jsonl` — the original, identical except that 14 case ids carry
  student names; git-ignored. `anonymize_golden.py` regenerates the
  anonymized file from it (names → `SV001`…; the name→code map is
  `private/anonymization_map.json`, git-ignored). `golden.py` picks the file:
  anonymized by default, `EVAL_GOLDEN_SET=original` or `--golden original`
  for the original, any other value is a path. Runs made before 2026-10-10
  (e.g. `ablation_20261009_baseline_details.json`) use original ids, so read
  them with `--golden original`.
- `private/` — git-ignored: anonymization map, calibration answer key,
  cached judge verdicts.
- `paraphrase_set.jsonl` + `paraphrase_eval.py` — hand-written paraphrases
  (template only so far) and intent accuracy on them, rules only vs rules +
  LLM router, with a confusion matrix.
- `retrieval_eval.py` — retrieval-only comparison (see below).
- `regroup.py` — recomputes a run's per-group tables with the current
  document grouping, from its `_details.json`, without calling the chatbot.
- `rescore_tier2.py` — recomputes a run's tier 2 scores (adds the fixed-k
  P@k) from its `_details.json` and an aggregates-only base snapshot, with no
  chatbot/LLM/DB call; stops if the original-rule numbers don't reproduce.
  `results/ablation_20261009_baseline_regrouped_fixedk.*` came from it.
- `cache_cases.jsonl` — 12 summary-cache cases (submission ids only).
- `scoring.py` — pure scoring functions (reply parsers, retrieval
  precision/recall, glue heuristic, Cohen's kappa, percentiles). No
  DB/HTTP/LLM calls; unit-tested in `tests/test_scoring.py`.
- `instrumentation.py` — benchmark-only wrappers: token accounting from the
  OpenAI `usage` field with a hard LLM budget, a recorder for what
  `retrieve_chunks` returned, and the three ablation configurations (applied
  by swapping module attributes; product code is not modified).
- `sandbox.py` — `rolled_back_session()`: every benchmark request runs in a
  transaction that is rolled back, so a run never changes the database.
- `judge.py` — LLM-as-judge prompts: one per answer (faithfulness, citation
  recall, relevancy, claim coverage) and one per citation (citation
  precision).
- `cache_suite.py` — the cache-correctness cases.
- `run_ablation.py` — the runner; `report.py` renders its Markdown report.
- `run_all.py` — same runner, hybrid configuration only.
- `calibration/` — judge calibration (see below).
- `results/` — run outputs (see "Outputs").

## How to run

The golden set's scope ids are rows of the `teacher@docgrading.com` / CS101
anchor dataset (31 real student reports). Run against **`docgrading_test`
holding a copy of the dev data**, never the dev database (the runner refuses
`POSTGRES_DB=docgrading`):

```bash
# once, with nothing connected to either database:
#   DROP DATABASE docgrading_test; CREATE DATABASE docgrading_test TEMPLATE docgrading;
cd backend
POSTGRES_DB=docgrading_test uv run python -m evaluation.run_ablation           # 3 configs
POSTGRES_DB=docgrading_test uv run python -m evaluation.run_ablation --sample 1 --label smoke
POSTGRES_DB=docgrading_test uv run python -m evaluation.run_all                # hybrid only
```

Do not run the `*_migration_roundtrip` DB tests against `docgrading_test`
while it holds the benchmark copy: they downgrade and wipe it. The copy must
be at alembic head (`POSTGRES_DB=docgrading_test uv run alembic upgrade
head`; head is `20261009_0020`, which adds `document_summaries.source_hash`).

Both keys are required (`LLM_API_KEY`, `EMBEDDING_API_KEY`); without them the
runner exits instead of producing partial numbers. Before any call it prints
an estimate of LLM tokens and stops if it exceeds the 2,000,000-token budget;
during the run it aborts as soon as the API-reported usage crosses it.

## Configurations (ablation)

| name | intent routing | numbers | retrieval | answer / summary |
|---|---|---|---|---|
| `rule_only` | keyword rules only (no LLM router) | SQL handlers | full-text only | none: passages returned verbatim; no summaries |
| `rag_only` | none: every question → `ASK_ABOUT_REQUIREMENT` | none (RAG over PDFs) | vector only | LLM answer with citations |
| `hybrid` | keyword rules, LLM router for `UNKNOWN` | SQL handlers | vector + full-text (RRF) | LLM answer with citations; cached LLM summaries |

Metrics that cannot apply to a configuration are reported as N/A with the
reason (e.g. intent accuracy for `rag_only`, faithfulness for `rule_only`).

## Outputs

- `results/ablation_<YYYYMMDD>_<label>.json` / `.md` — aggregates only
  (no case ids, replies or report text).
- `results/ablation_<YYYYMMDD>_<label>_details.json` — per-case replies,
  retrieved chunk text and judge verdicts. Contains student report content:
  **do not commit**.
- `results/<timestamp>_<commit>.json` — snapshot of the first run
  (2026-10-02, old scoring rule; not comparable, see below).

## Scoring decisions

### Tier 2 retrieval: multiple correct locations, exact page

Scored on the chunks `retrieve_chunks` actually returned (full text), not on
the 320-character excerpts in the reply. A retrieved chunk is relevant to a
question when, for **any** of its gold locations `{page, keyword}`:

- the gold page lies in the chunk's `[page_start, page_end]` range, and
- the keyword occurs in the chunk's section path or text after normalising
  **both** sides with `fold_compact`: diacritics removed, lower-cased, all
  whitespace removed — so a chunk whose words the PDF reader glued together
  ("dựatrênđồthị") still matches "dựa trên đồ thị".

Then:

- Context Precision@k = relevant chunks among the top 6 / 6
  (`scoring.FIXED_K`), the same denominator for every configuration and the
  same rule as `retrieval_eval`. This is the headline P@k and carries the
  70% threshold;
- the original P@k, relevant retrieved chunks / number of chunks
  **returned**, is still reported, labelled "mẫu số = số chunk trả về". It
  is not comparable across configurations: `rule_only` often returns fewer
  than 6 chunks, so its P@k was 45.0% under this rule but 16.2% at k = 6
  in the 2026-10-09 baseline;
- Context Recall = gold locations hit by at least one retrieved chunk /
  gold locations.

The ±2-page tolerance used by the 2026-10-02 run is still computed, but only
as a sensitivity column. Together with the switch from excerpts to full
chunk text, this means numbers from the first run are **not comparable**
with ablation runs.

### Why the 70% precision threshold can't be reached on this gold set

Precision@k can never exceed `min(n_rel, k) / k`, where `n_rel` is the number
of chunks in the submission's **whole** corpus that match a gold location.
Most golden questions are narrow ("which datasets…", "what is stage 1…")
and are answered by one passage, i.e. 1–2 chunks. With k = 6, one relevant
chunk caps precision at 1/6 = 16.7% and two at 33.3%. Reaching 70% needs
at least 5 of the 6 retrieved chunks to be relevant, so `n_rel >= 5` for
every question, which this gold set doesn't have. Listing more gold locations
per question only helps when the document really discusses the topic in
several places, and padding the gold to lift the number would defeat it.

The threshold is therefore **kept at 70% and reported as "not reached"**,
next to `theoretical_max_precision(n_rel, k)` (the ceiling) and
`precision / ceiling`. The ceiling uses the same matching rule, counted over
the whole corpus. Precision close to its ceiling means retrieval puts the
few relevant chunks in the top k; a large gap is the real regression signal.
The threshold was not changed because no mathematical argument picks a
different flat value: the reachable maximum differs per question.

### Out-of-scope rejection

A noise question counts as rejected when the bot returned
`UNKNOWN`/`HELP`/`GREETING`, or answered through RAG **without any
citation**. The second clause applies the same definition to `rag_only`,
which has no `UNKNOWN`. For `hybrid` it is slightly broader than the first
run's "intent == UNKNOWN".

### Numeric correctness

Over all 53 non-noise tier 1 cases: the intent must be right and the strict
parser (mirroring the exact wording of the SQL handlers) must read the gold
number. `rag_only` has no SQL handler, so it also reports a lenient upper
bound: every gold number appears somewhere in the reply.

### Grouping by PDF word-gluing

The language is detected first (`scoring.detect_language`): a document is
Vietnamese when it contains more Vietnamese than English function words.
On the anchor dataset the populations don't overlap: Vietnamese reports have
≥ 39% accented words and ≤ 2.1% English function words; English ones have
≤ 0.1% accented words and ≥ 14% English function words. English documents
form the group **en** and stay out of the glue groups, because the glue
heuristic only sees Vietnamese. Before this rule, one English report sat in
"high" because 1 of its 2 accented words was a person's name.

Vietnamese documents get the glue rate of the chunk-audit heuristic
(`scoring.glue_candidates`): among words carrying Vietnamese diacritics, the
share that are 9+ letters long or switch lower→upper case mid-word.
Groups: low < 2%, mid 2–10%, high ≥ 10%. In tiers 2–3 "mid" and "high" each
contain a single document, so a group comparison is a per-document one.

### Tier 3 (LLM-as-judge)

Only `ASK_ABOUT_REQUIREMENT` cases. The judge model is `JUDGE_LLM_MODEL`
(environment or root `.env`) if set, else the system's `LLM_MODEL`, with
the same OpenAI key. Every report states the judge model and whether it is
the system's model; when it is, self-preference bias is possible. The judge
sees the full text of every chunk the generator received.

- Faithfulness, citation recall, relevancy, claim coverage: one call per answer.
- Citation precision: one call per citation ("does chunk [n] support the
  sentence carrying [n]?"); the per-answer mean of supported verdicts.

All of these are **uncalibrated** until `calibration/` has hand labels.

## Judge calibration

1. `uv run python -m evaluation.calibration.build_label_set
   evaluation/results/ablation_<date>_baseline_details.json` writes
   `calibration/citation_labels.jsonl` with 40 samples. Samples are chosen
   round-robin over (document, configuration), **without** looking at the
   judge's verdict, and the verdict is not written into the file, so the
   labeler isn't anchored by it. The script won't overwrite a file that
   already has a label.
2. `uv run python -m evaluation.calibration.add_synthetic_negatives` adds 14
   synthetic negatives. Each copies a real sample's question, answer and
   cited sentence, and swaps the chunk for one that cannot support it:
   7 come from another submission, 7 from the same submission but a
   different top-level section at least 3 pages away. All have < 20%
   content-word overlap with the claim. Real and synthetic samples are
   shuffled and renumbered together. Which ids are synthetic is recorded
   only in `private/calibration_key.jsonl`.
3. A human fills `human_label` (`true` = the chunk supports the claim,
   `false` = it doesn't) and optionally `human_note`, without opening
   `private/`.
4. `uv run python -m evaluation.calibration.calibrate_judge` judges each
   labeled sample with the configured judge model (verdicts cached in
   `private/judge_verdicts_<model>.jsonl`; `--rejudge` refreshes them). It
   prints agreement, Cohen's kappa and the confusion matrix: overall, for
   real samples only, and for synthetic negatives only. It also reports how
   often the labeler rejected the synthetic negatives, as a check on the
   labels. It writes `calibration/calibration_result.json`. With no labels it
   prints "chưa hiệu chỉnh", makes no LLM call and prints no numbers. Below
   30 labeled pairs it reports the numbers but doesn't call the judge
   calibrated.

`calibrate_judge --negative-controls` needs no labels. It judges only the
synthetic negatives and counts how many the judge rejects. That is a sanity
check against samples that are unsupported by construction, **not** a
calibration.

The label file contains report text: do not commit it.

## Cache correctness

`cache_suite.py` runs the 12 cases in `cache_cases.jsonl`, each in its own
rolled-back transaction (`POSTGRES_DB=docgrading_test uv run python -m
evaluation.cache_suite` runs them alone):

| kind | N | passes when |
|---|---|---|
| `miss_then_hit` | 6 | request 1 makes ≥1 LLM call, request 2 makes 0 and returns the same text |
| `legacy_row_regenerates` | 2 | a row without a matching `source_hash` exists; request 1 rebuilds it (≥1 call) and stamps the hash, request 2 hits |
| `content_change_same_version` | 2 | after miss+hit, one chunk of the same version is edited (1-row `UPDATE`); the next request must rebuild (≥1 LLM call) |
| `new_version` | 2 | a new version (version_number+1, one chunk changed) is inserted; the next request builds a summary for it, the one after hits |

`precached_hit` (a row whose hash matches: 0 calls) is still supported. Its
two cases became `legacy_row_regenerates` once `source_hash` existed: their
rows predate the column, and the fix regenerates such rows by design. A case
whose precondition doesn't hold is reported as `precondition_failed` and
not counted. The old `T3-CACHE-*` golden rows are superseded.

The summary cache is keyed on `document_version_id` **and** `source_hash`
(migration `20261009_0020`). The hash is the sha256 of the IR parser version
plus the version's chunks in order (section path, token count, text), see
`rag.summary_source_hash`. A row whose hash doesn't match the current
chunks, including every row written before the column existed (NULL), is
regenerated on its next request and updated in place. The cache does
**not** depend on the LLM model, so changing `LLM_MODEL` keeps old summaries.

## Retrieval-only comparison

`POSTGRES_DB=docgrading_test uv run python -m evaluation.retrieval_eval`
runs every tier-2 case through `vector`, `tsvector` (full-text stages only),
`substring` (the ILIKE fallback on its own), `keyword` (`_keyword_ranked` as
shipped: full-text, then substring when full-text finds nothing) and
`hybrid_rrf` (`retrieve_chunks` as shipped). Each method uses the
chatbot's query and k = 6. Reported:

- Recall, P@6 (denominator fixed at 6, so a method returning fewer chunks
  isn't rewarded), P@6 / ceiling and MRR;
- 95% percentile-bootstrap intervals (2000 resamples of cases);
- the same tables per document group;
- cases where the query covers < 1/3 of its terms in every relevant chunk
  ("low lexical overlap"), the place to add cases.

The 36 cases come from 6 documents, so cases are not independent. The
case-level intervals are therefore optimistic. It makes no LLM calls,
only one query embedding per case.

## Adding a new case

1. Append a line to the original `golden_set.jsonl` with a new unique `id`,
   then rerun `anonymize_golden` so the committed file follows. It stops if
   a student name appears outside the id.
2. Decide the `gold` value **before** running with it, by reading the real
   DB/DocumentIR content directly, never from what the chatbot answers
   (benchmark doc section 4).
3. For tier 0/1 cases, check the wording triggers the intended intent with
   `classify_intent()` (a wording lint; it decides no gold value).
4. **Never edit an existing case's `gold` after seeing a run's output.** A
   genuine transcription mistake gets its own commit explaining why.
5. Keep `gold_source` accurate.

## Known limitations

- The anchor dataset is small and skewed (31 submissions, 1 reviewed,
  0 errors). Clarification (N=10), out-of-scope (N=18), tier 3 (N=16 ASK,
  12 summaries) and cache (N=12) numbers are indicative only. The report
  flags every metric with N < 20.
- The keyword/page proxy is not an exact span match: a chunk can contain the
  keyword without answering the question, and a correct chunk can paraphrase
  it.
- The LLM-judge is uncalibrated (see above) and shares its model with the
  system under test.
- Latency is measured in-process against a local Postgres plus OpenAI over the
  network; it includes the rolled-back transaction setup and is not the
  HTTP latency a user sees.
