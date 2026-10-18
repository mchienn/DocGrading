# citation-semantic-support-v1: AI-consensus evaluation dataset

Generated 2026-10-17T22:52:28+00:00. `annotation_status=AI_CONSENSUS`, `human_gold_pairs=0`. **Not human gold and not usable for the activation gate.**

## 1. Files

- `backend/tests/fixtures/semantic_citation_annotations.v1.json` — schema v2, 583 pairs, 147 sources (claims, labels, evidence quotes, judge votes per pair, split).
- `backend/scripts/semantic_citation_v1_benchmark.py` — stage 3 (retrieval) and stage 4 (verdicts) on this set with production code; results in [`citation-semantic-v1-ai-consensus.md`](citation-semantic-v1-ai-consensus.md).
- The generation, verification, judging and split scripts, raw generations and full judge vote logs were run outside the repository and are not committed; the per-pair votes in the fixture are the audit trail.

## 2. Counts

Total accepted pairs: **583** (synthetic 571, owner-paper 12).

| label | n | share |
|---|---|---|
| SUPPORTED | 288 | 49.4% |
| IRRELEVANT | 166 | 28.5% |
| PARTIALLY_SUPPORTED | 73 | 12.5% |
| CONTRADICTED | 52 | 8.9% |
| INSUFFICIENT_EVIDENCE | 4 | 0.7% |

Target mix: SUPPORTED 30, PARTIALLY_SUPPORTED 15, CONTRADICTED 15, IRRELEVANT 15, INSUFFICIENT_EVIDENCE 15, owner-paper ~10 (percent).

| language | n | share |
|---|---|---|
| vi | 304 | 52.1% |
| en | 223 | 38.3% |
| mixed | 56 | 9.6% |

| claim_type | n | share |
|---|---|---|
| contribution_or_limitation | 179 | 30.7% |
| method_detail | 134 | 23.0% |
| numeric_result | 116 | 19.9% |
| comparison | 110 | 18.9% |
| definition | 44 | 7.5% |

| construction | n | share |
|---|---|---|
| direct_support | 187 | 32.1% |
| cross_domain_pairing | 165 | 28.3% |
| table_or_caption | 54 | 9.3% |
| two_passage_synthesis | 42 | 7.2% |
| negation | 37 | 6.3% |
| over_generalisation | 26 | 4.5% |
| suggests_to_proves | 22 | 3.8% |
| added_unsupported_fact | 14 | 2.4% |
| owner_sentence | 12 | 2.1% |
| direction_swap | 10 | 1.7% |
| omitted_condition | 6 | 1.0% |
| concept_switch | 4 | 0.7% |
| unsupported_specific_fact | 3 | 0.5% |
| numeric_mismatch | 1 | 0.2% |

| difficulty tag (pairs can carry several) | n | share |
|---|---|---|
| cross_language | 360 | 61.7% |
| low_lexical_overlap | 199 | 34.1% |
| hedged_vs_strong | 66 | 11.3% |
| table_or_caption | 54 | 9.3% |
| two_passages | 42 | 7.2% |

| domain | n | share |
|---|---|---|
| nlp_llm | 89 | 15.3% |
| systems_data | 87 | 14.9% |
| rag_ir | 75 | 12.9% |
| security | 75 | 12.9% |
| ml | 71 | 12.2% |
| cv | 70 | 12.0% |
| se_testing | 59 | 10.1% |
| hci_web | 57 | 9.8% |

| split | n | share |
|---|---|---|
| test | 408 | 70.0% |
| dev | 175 | 30.0% |

Label x split:

| label | dev | test |
|---|---|---|
| SUPPORTED | 89 | 199 |
| PARTIALLY_SUPPORTED | 18 | 55 |
| CONTRADICTED | 22 | 30 |
| IRRELEVANT | 45 | 121 |
| INSUFFICIENT_EVIDENCE | 1 | 3 |

Label x language:

| label | vi | en | mixed |
|---|---|---|---|
| SUPPORTED | 162 | 94 | 32 |
| PARTIALLY_SUPPORTED | 42 | 30 | 1 |
| CONTRADICTED | 17 | 29 | 6 |
| IRRELEVANT | 83 | 66 | 17 |
| INSUFFICIENT_EVIDENCE | 0 | 4 | 0 |

## 3. Licenses and sources

| license URL | n | share |
|---|---|---|
| http://creativecommons.org/licenses/by/4.0/ | 134 | 91.2% |
| http://creativecommons.org/licenses/by-sa/4.0/ | 12 | 8.2% |
| http://creativecommons.org/publicdomain/zero/1.0/ | 1 | 0.7% |

147 arXiv papers in the dataset; production Source IR passages were built with `semantic_citation._source_from_pdf_bytes` (`extract_tables=False`, `upright_only`, <=192 passages, so long papers are truncated exactly as in production). Owner-paper references included: [23] 1908.10084v1, [26] 2301.13688v2, [16] 2308.08493v3, [14] 2401.07930v2, [15] 2402.03927v2, [17] 2502.06215v1. Two of them (`2402.03927v2`, `2502.06215v1`) exceed production PDF validator caps (link-annotation / active-content node limit, `PDF_STRUCTURE_LIMIT`); for those two only the caps were raised in-process (repository untouched), flagged `validator_override` in `sources`. `2503.05378` (owner ref [11], >100 pages) is rejected by production (`PDF_PAGE_LIMIT`), so its claim is excluded. Other owner references are not CC BY/BY-SA/CC0 on arXiv (arXiv non-exclusive licence) or not on arXiv, so they are not sources.

## 4. Judges and agreement

Judges: OpenCode free models run tool-less (`opencode run` from an empty scratch directory under `judge_sandbox/`, project config denying edit/write/bash/webfetch/websearch/task/external_directory, isolated `XDG_CONFIG_HOME` so no MCP servers load). Each judge sees the claim, the evidence passage(s) and two same-source distractors, shuffled (IRRELEVANT: top-3 passages of the unrelated source by production BM25; owner claims: production BM25 top-3). OpenCode free models rate-limit separately and stopped answering after a few hundred items, so every candidate was also judged by two open-weight models on a private Kaggle 2x T4 kernel with the same judge items and prompt (`Qwen/Qwen3-8B` with thinking off and `ibm-granite/granite-3.3-8b-instruct`; transformers fp16, greedy decoding, 96 new tokens, no tools or network use by the models). Every accepted pair has verdicts from **at least two different model families**; the rule is: keep a synthetic pair only if every recorded vote equals the constructed label.

| model | calls | valid verdicts | errors/timeouts |
|---|---|---|---|
| granite-3.3-8b | 1487 | 1467 | 20 |
| qwen3-8b | 1487 | 1486 | 1 |
| beam-free | 297 | 227 | 70 |
| deepseek-v4.1-flash-free | 266 | 200 | 66 |
| glm-5.3-flash-free | 211 | 145 | 66 |
| longcat-2.5-preview-free | 127 | 66 | 61 |
| mimo-v2.6-flash-free | 58 | 0 | 58 |
| nemotron-3-ultra-free | 40 | 0 | 40 |
| nemotron-3.5-lightning-free | 112 | 29 | 83 |
| nemotron-3.5-super-vl-free | 40 | 0 | 40 |

Judge consensus with constructed label (candidates that passed structural checks and received >=2 family votes):

| label | judged | all judges = constructed label | acceptance | judges agree with each other |
|---|---|---|---|---|
| SUPPORTED | 487 | 283 | 58.1% | 63.9% |
| PARTIALLY_SUPPORTED | 322 | 68 | 21.1% | 49.4% |
| CONTRADICTED | 288 | 52 | 18.1% | 41.7% |
| IRRELEVANT | 228 | 204 | 89.5% | 89.9% |
| INSUFFICIENT_EVIDENCE | 133 | 3 | 2.3% | 39.1% |

Per judge agreement with the constructed label:

| judge | SUPPORTED | PARTIALLY_SUPPORTED | CONTRADICTED | IRRELEVANT | INSUFFICIENT_EVIDENCE |
|---|---|---|---|---|---|
| deepseek-v4.1-flash-free | 66/69 | 27/44 | 33/35 | 31/31 | 0/0 |
| glm-5.3-flash-free | 43/45 | 21/36 | 20/23 | 19/20 | 0/0 |
| nemotron-3.5-lightning-free | 6/6 | 2/4 | 3/4 | 3/3 | 0/0 |
| longcat-2.5-preview-free | 16/17 | 13/20 | 7/7 | 9/9 | 0/0 |
| qwen3-8b | 303/487 | 201/322 | 80/288 | 218/228 | 57/133 |
| granite-3.3-8b | 428/487 | 84/322 | 73/287 | 209/225 | 3/133 |
| beam-free | 84/90 | 36/55 | 32/37 | 42/44 | 0/0 |

Pairwise judge agreement (all judged candidates, synthetic + owner):

| pair | n | observed agreement | Cohen kappa |
|---|---|---|---|
| deepseek-v4.1-flash-free vs glm-5.3-flash-free | 137 | 0.9343 | 0.9066 |
| deepseek-v4.1-flash-free vs longcat-2.5-preview-free | 66 | 0.8788 | 0.8289 |
| deepseek-v4.1-flash-free vs qwen3-8b | 192 | 0.6927 | 0.577 |
| deepseek-v4.1-flash-free vs granite-3.3-8b | 189 | 0.6984 | 0.5361 |
| glm-5.3-flash-free vs longcat-2.5-preview-free | 66 | 0.8636 | 0.8043 |
| glm-5.3-flash-free vs qwen3-8b | 137 | 0.708 | 0.5898 |
| glm-5.3-flash-free vs granite-3.3-8b | 135 | 0.6741 | 0.4934 |
| nemotron-3.5-lightning-free vs qwen3-8b | 29 | 0.5862 | 0.4485 |
| nemotron-3.5-lightning-free vs granite-3.3-8b | 29 | 0.7241 | 0.5513 |
| longcat-2.5-preview-free vs qwen3-8b | 66 | 0.6515 | 0.5098 |
| longcat-2.5-preview-free vs granite-3.3-8b | 65 | 0.6769 | 0.4958 |
| qwen3-8b vs granite-3.3-8b | 1467 | 0.6115 | 0.4548 |
| beam-free vs qwen3-8b | 226 | 0.6681 | 0.5315 |
| beam-free vs granite-3.3-8b | 225 | 0.6756 | 0.5082 |

Most common disagreement patterns (constructed label -> judge verdict set):

| constructed | judge verdicts | n |
|---|---|---|
| SUPPORTED | SUPPORTED | 283 |
| SUPPORTED | PARTIALLY_SUPPORTED|SUPPORTED | 164 |
| SUPPORTED | PARTIALLY_SUPPORTED | 28 |
| SUPPORTED | IRRELEVANT|PARTIALLY_SUPPORTED | 4 |
| PARTIALLY_SUPPORTED | PARTIALLY_SUPPORTED|SUPPORTED | 145 |
| PARTIALLY_SUPPORTED | SUPPORTED | 90 |
| PARTIALLY_SUPPORTED | PARTIALLY_SUPPORTED | 68 |
| PARTIALLY_SUPPORTED | IRRELEVANT|PARTIALLY_SUPPORTED | 5 |
| CONTRADICTED | PARTIALLY_SUPPORTED|SUPPORTED | 72 |
| CONTRADICTED | CONTRADICTED | 52 |
| CONTRADICTED | CONTRADICTED|PARTIALLY_SUPPORTED | 38 |
| CONTRADICTED | SUPPORTED | 34 |
| IRRELEVANT | IRRELEVANT | 204 |
| IRRELEVANT | IRRELEVANT|PARTIALLY_SUPPORTED | 13 |
| IRRELEVANT | INSUFFICIENT_EVIDENCE|IRRELEVANT | 3 |
| IRRELEVANT | CONTRADICTED|IRRELEVANT | 3 |
| INSUFFICIENT_EVIDENCE | IRRELEVANT | 36 |
| INSUFFICIENT_EVIDENCE | INSUFFICIENT_EVIDENCE|IRRELEVANT | 31 |
| INSUFFICIENT_EVIDENCE | PARTIALLY_SUPPORTED|SUPPORTED | 18 |
| INSUFFICIENT_EVIDENCE | INSUFFICIENT_EVIDENCE|PARTIALLY_SUPPORTED | 13 |

### Owner-paper claims

| pair | label | first two judges agree | votes | claim |
|---|---|---|---|---|
| v1-0572 | IRRELEVANT | yes | deepseek-v4.1-flash-free=IRRELEVANT, glm-5.3-flash-free=IRRELEVANT, nemotron-3.5-lightning-free=IRRELEVANT, longcat-2.5-preview-free=INSUFFICIENT_EVIDENCE, qwen3-8b=IRRELEVANT, granite-3.3-8b=PARTIALLY_SUPPORTED | We evaluate several representative models for the EO-to-JSON transformation task, including CodeT5-small (60M) [24], Cod |
| v1-0573 | PARTIALLY_SUPPORTED | yes | deepseek-v4.1-flash-free=PARTIALLY_SUPPORTED, glm-5.3-flash-free=PARTIALLY_SUPPORTED, longcat-2.5-preview-free=PARTIALLY_SUPPORTED, qwen3-8b=PARTIALLY_SUPPORTED, granite-3.3-8b=SUPPORTED | Zhou et al. [18] use MinHash+LSH to identify potential duplicate pairs between the benchmarks and the pretraining datase |
| v1-0574 | PARTIALLY_SUPPORTED | yes | deepseek-v4.1-flash-free=PARTIALLY_SUPPORTED, glm-5.3-flash-free=PARTIALLY_SUPPORTED, nemotron-3.5-lightning-free=INSUFFICIENT_EVIDENCE, longcat-2.5-preview-free=PARTIALLY_SUPPORTED, qwen3-8b=PARTIALLY_SUPPORTED, granite-3.3-8b=SUPPORTED | Lopez et al. [14] investigate dataset leakage in small language models, such as CodeBERT. The main idea is to use an aut |
| v1-0575 | INSUFFICIENT_EVIDENCE | yes | deepseek-v4.1-flash-free=INSUFFICIENT_EVIDENCE, glm-5.3-flash-free=INSUFFICIENT_EVIDENCE, nemotron-3.5-lightning-free=IRRELEVANT, longcat-2.5-preview-free=INSUFFICIENT_EVIDENCE, qwen3-8b=IRRELEVANT, granite-3.3-8b=PARTIALLY_SUPPORTED | Lopez et al. [14] investigate dataset leakage in small language models, such as CodeBERT. |
| v1-0576 | SUPPORTED | tie-break | deepseek-v4.1-flash-free=PARTIALLY_SUPPORTED, glm-5.3-flash-free=SUPPORTED, nemotron-3.5-lightning-free=SUPPORTED, longcat-2.5-preview-free=PARTIALLY_SUPPORTED, qwen3-8b=PARTIALLY_SUPPORTED, granite-3.3-8b=SUPPORTED | Golchin et al. [16] use a LM to complete a sentence retrieved from a known benchmark. |
| v1-0577 | SUPPORTED | yes | deepseek-v4.1-flash-free=SUPPORTED, glm-5.3-flash-free=SUPPORTED, nemotron-3.5-lightning-free=SUPPORTED, longcat-2.5-preview-free=SUPPORTED, qwen3-8b=SUPPORTED, granite-3.3-8b=SUPPORTED | Zhou et al. [18] use MinHash+LSH to identify potential duplicate pairs between the benchmarks and the pretraining datase |
| v1-0578 | SUPPORTED | yes | deepseek-v4.1-flash-free=SUPPORTED, glm-5.3-flash-free=SUPPORTED, nemotron-3.5-lightning-free=INSUFFICIENT_EVIDENCE, longcat-2.5-preview-free=SUPPORTED, qwen3-8b=PARTIALLY_SUPPORTED, granite-3.3-8b=SUPPORTED | Balloccu et al. [15] studied the issue of data contamination in closed-source LMs. |
| v1-0579 | SUPPORTED | yes | deepseek-v4.1-flash-free=SUPPORTED, glm-5.3-flash-free=SUPPORTED, nemotron-3.5-lightning-free=SUPPORTED, longcat-2.5-preview-free=SUPPORTED, qwen3-8b=SUPPORTED, granite-3.3-8b=SUPPORTED | Balloccu et al. [15] studied the issue of data contamination in closed-source LMs. They conclude that 42% of the reviewe |
| v1-0580 | PARTIALLY_SUPPORTED | yes | deepseek-v4.1-flash-free=PARTIALLY_SUPPORTED, glm-5.3-flash-free=PARTIALLY_SUPPORTED, nemotron-3.5-lightning-free=SUPPORTED, longcat-2.5-preview-free=SUPPORTED, qwen3-8b=SUPPORTED, granite-3.3-8b=SUPPORTED | Data contamination in SLMs refers to the unintentional inclusion of evaluation data during the training process of a SLM |
| v1-0581 | PARTIALLY_SUPPORTED | yes | deepseek-v4.1-flash-free=PARTIALLY_SUPPORTED, glm-5.3-flash-free=PARTIALLY_SUPPORTED, nemotron-3.5-lightning-free=SUPPORTED, longcat-2.5-preview-free=SUPPORTED, qwen3-8b=PARTIALLY_SUPPORTED, granite-3.3-8b=SUPPORTED | For string-based values, the proposed method uses a Sentence Transformer [23] to convert values into semantic embedding  |
| v1-0582 | PARTIALLY_SUPPORTED | yes | deepseek-v4.1-flash-free=PARTIALLY_SUPPORTED, glm-5.3-flash-free=PARTIALLY_SUPPORTED, nemotron-3.5-lightning-free=SUPPORTED, longcat-2.5-preview-free=INSUFFICIENT_EVIDENCE, qwen3-8b=PARTIALLY_SUPPORTED, granite-3.3-8b=PARTIALLY_SUPPORTED | The data contamination issue is becoming increasingly recognized and significant due to the growing usage of LMs [14]. |
| v1-0583 | SUPPORTED | yes | deepseek-v4.1-flash-free=SUPPORTED, glm-5.3-flash-free=SUPPORTED, nemotron-3.5-lightning-free=SUPPORTED, longcat-2.5-preview-free=SUPPORTED, qwen3-8b=PARTIALLY_SUPPORTED, granite-3.3-8b=SUPPORTED | Golchin et al. [16] use a LM to complete a sentence retrieved from a known benchmark. The completion is then compared wi |

## 5. Rejections

Structural stage (candidates generated by Gemini and owner sentences; counts per constructed label):

| label | reason | n |
|---|---|---|
| IRRELEVANT | generator_flagged_unusable | 28 |
| IRRELEVANT | language_mismatch | 16 |
| IRRELEVANT | claim_number_not_in_evidence | 3 |
| IRRELEVANT | near_duplicate_claim | 1 |
| CONTRADICTED | generator_flagged_unusable | 50 |
| CONTRADICTED | language_mismatch | 17 |
| CONTRADICTED | claim_number_not_in_evidence | 11 |
| CONTRADICTED | numeric_mismatch_not_applied | 7 |
| CONTRADICTED | claim_copies_quote | 2 |
| CONTRADICTED | near_duplicate_claim | 1 |
| SUPPORTED | generator_flagged_unusable | 72 |
| SUPPORTED | language_mismatch | 34 |
| SUPPORTED | claim_number_not_in_evidence | 2 |
| PARTIALLY_SUPPORTED | key_fact_present_in_source_or_missing | 77 |
| PARTIALLY_SUPPORTED | generator_flagged_unusable | 19 |
| PARTIALLY_SUPPORTED | language_mismatch | 18 |
| PARTIALLY_SUPPORTED | claim_copies_quote | 2 |
| INSUFFICIENT_EVIDENCE | key_fact_present_in_source_or_missing | 269 |
| INSUFFICIENT_EVIDENCE | generator_flagged_unusable | 40 |
| INSUFFICIENT_EVIDENCE | language_mismatch | 17 |
| OWNER | source_not_built_in_production_ir | 1 |

Structural stage also dropped 380 INSUFFICIENT_EVIDENCE candidates of the first design (see section 8); 2160 generated items entered the checks.

Judge stage (candidates rejected because at least one judge disagreed with the constructed label):

| label | rejected by judges | accepted pool before mix selection |
|---|---|---|
| SUPPORTED | 204 | 283 |
| PARTIALLY_SUPPORTED | 254 | 68 |
| CONTRADICTED | 236 | 52 |
| IRRELEVANT | 24 | 204 |
| INSUFFICIENT_EVIDENCE | 130 | 3 |

Candidates without votes from two families (judge errors / quota): {'SUPPORTED': 5, 'CONTRADICTED': 4, 'IRRELEVANT': 4, 'PARTIALLY_SUPPORTED': 2, 'INSUFFICIENT_EVIDENCE': 1}.

Pairs surviving structural + judge checks were then down-sampled to the target mix with per-label language quotas (vi 50%, en ~39.5%, mixed ~10.5% of synthetic) and a least-used-source-first rule.

## 6. Dual Split and leakage

Dual Split (owner paper, Algorithm 1/2) with the input side = claim text (citation marker stripped) and the output side = the evidence quote(s) the claim was built from (IRRELEVANT: the origin quote; INSUFFICIENT_EVIDENCE: the related quote; owner claims: the source id). `df_cut=0.01`, `k=3`, target dev ratio 0.30. Clusters are visited largest first and the pair goes to the most under-filled split (the paper's argmin rule read this way converges to the ratio); both deviations are noted in `scripts/dual_split.py`.

Clusters: 522 (largest 3, singletons 470).

| metric (test claims vs dev claims) | Dual Split | random split (mean of 5 seeds, same sizes) |
|---|---|---|
| ngram4_leaked_pct | 25.98 | 28.482 |
| max_trigram_jaccard_mean | 0.0173 | 0.0213 |
| cosine_max_mean | 0.2252 | 0.236 |
| cosine_max_p95 | 0.3183 | 0.3527 |
| cosine_ge_0.8_pct | 0.0 | 0.0 |
| cosine_ge_0.9_pct | 0.0 | 0.0 |
| test_with_same_evidence_in_dev_pct | 0.0 | 6.864 |

`ngram4_leaked_pct`: share of test claims sharing at least one word 4-gram with any dev claim. Cosine: char-4-gram TF cosine to the nearest dev claim. `test_with_same_evidence_in_dev_pct`: test pairs whose evidence text also anchors a dev pair.

## 7. Runtime and API usage

- Gemini: 597 successful `generateContent` calls ({'gemini-3.5-flash-lite': 597}), prompt tokens 859,108, output tokens 186,729. ~4.5 s pacing between calls; no 429 daily-quota hit.
- OpenCode free judges: see vote table above (about 16k input tokens per call because the OpenCode agent prompt is attached; free models rate-limit independently, which forced pooling several model families).
- arXiv: OAI-PMH discovery (27 ListRecords requests), one OAI `arXivRaw` GetRecord per paper for the exact version, one PDF download per paper, all >=3 s apart on one connection. The Atom `export.arxiv.org/api/query` endpoint answered HTTP 429 ('Rate exceeded') so versions/licences come from OAI-PMH (`oaipmh.arxiv.org`).

## 8. Design notes and known weaknesses

- **Size and mix are below target.** The request was 700-1000 pairs; 583 survived the all-judges-agree rule. Rare labels are thin (INSUFFICIENT_EVIDENCE 4, CONTRADICTED 52, PARTIALLY_SUPPORTED 73): judges seldom agree on INSUFFICIENT_EVIDENCE and on constructed contradictions, so per-class scores for those labels are noisy and INSUFFICIENT_EVIDENCE F1 is not meaningful. Relaxing the rule to a 2/3 majority would add only ~100 pairs, because most candidates have exactly the two Kaggle votes.
- **Labels are AI consensus.** Two LLM judges agreeing with a constructed label shows the construction is recognisable to LLMs, not that humans agree. Judges and generator are LLMs with their own blind spots; free-tier models differ in strictness (see per-judge table). The generator (Gemini) is also the model family evaluated in stage 4, which can favour it.
- **Synthetic errors are easier than real miscitations.** Negations, swapped numbers, concept swaps and cross-domain IRRELEVANT pairs are cleaner than real student errors (loose paraphrase, wrong paper section, mixed correct/incorrect claims). Expect optimistic accuracy; the acceptance filter additionally removes ambiguous cases, so the set has fewer borderline items than reality.
- **IRRELEVANT is cross-domain by construction** (different arXiv category family, lowest BM25 overlap of several candidates) — far easier than real "same field, wrong paper" miscitations. INSUFFICIENT_EVIDENCE is the realistic hard counterpart.
- **INSUFFICIENT_EVIDENCE design change.** First design (quote topic + one invented fact) was judged PARTIALLY_SUPPORTED by both judges on a 8-item probe (the supported topic part counts as support). It was regenerated as "same subject, different aspect, whole claim is an unsupported specific fact"; the 380 old candidates were discarded. The key fact must be absent from the full 192-passage Source IR (digits, rare words); absence from the *PDF beyond 192 passages* is not checked.
- **PARTIALLY_SUPPORTED vs INSUFFICIENT_EVIDENCE boundary is inherently fuzzy**; the judge prompt states the spec definitions, but real annotators may split differently.
- **Owner-paper claims are far fewer than the 10% target.** Only the owner paper sentences that cite a reference available on arXiv under CC BY/BY-SA/CC0 *and* parseable by the production Source IR can be used (12 pairs, 2.1% of the set). Their labels come from judge agreement only, with BM25 top-3 retrieval.
- **Language**: Vietnamese/mixed claims were written by Gemini, not by Vietnamese students; mixed-language detection is a heuristic (ASCII-token share >= 0.33). Citation markers `[n]` were appended to ~25% of synthetic claims.
- **Evidence quotes are sentences cut from passages by regex**, so "table" evidence is limited to figure/table captions that survive as passages (production extracts no tables). Passages are capped at 192 per paper and PDFs rejected by production validators are absent (~20% of selected papers), so the source set is biased toward PDFs production can ingest.
- **Judge context** is the evidence passage plus two retrieval-ranked distractors (not production's top-3 for the claim), so retrieval errors are not measured here; stage 3 of the benchmark script measures retrieval.
- Dual Split controls claim/evidence overlap, not paper-level overlap: the same paper can appear in dev and test.
