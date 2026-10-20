# citation-semantic-support-v1: AI-consensus evaluation dataset

Generated 2026-10-19T22:38:24+00:00. `annotation_status=AI_CONSENSUS`, `human_gold_pairs=0`, acceptance rule v1.1. Labels are AI-verified (section 4), not human gold.

## 1. Files

- `backend/tests/fixtures/semantic_citation_annotations.v1.json` — schema v2, 900 pairs, 149 sources (claims, labels, evidence quotes, judge votes per pair, split).
- `backend/scripts/semantic_citation_v1_benchmark.py` — stage 3 (retrieval) and stage 4 (verdicts) on this set with production code; results in [`citation-semantic-v1-ai-consensus.md`](citation-semantic-v1-ai-consensus.md).
- The generation, verification, judging and split scripts, raw generations and full judge vote logs were run outside the repository and are not committed; the per-pair votes in the fixture are the audit trail.

## 2. Counts

Total accepted pairs: **900** (synthetic 890, owner-paper 10).

| label | n | share |
|---|---|---|
| SUPPORTED | 334 | 37.1% |
| IRRELEVANT | 166 | 18.4% |
| PARTIALLY_SUPPORTED | 165 | 18.3% |
| CONTRADICTED | 138 | 15.3% |
| INSUFFICIENT_EVIDENCE | 97 | 10.8% |

Target mix: SUPPORTED 30, PARTIALLY_SUPPORTED 15, CONTRADICTED 15, IRRELEVANT 15, INSUFFICIENT_EVIDENCE 15, owner-paper ~10 (percent).

| language | n | share |
|---|---|---|
| vi | 463 | 51.4% |
| en | 359 | 39.9% |
| mixed | 78 | 8.7% |

| claim_type | n | share |
|---|---|---|
| contribution_or_limitation | 248 | 27.6% |
| numeric_result | 216 | 24.0% |
| method_detail | 204 | 22.7% |
| comparison | 177 | 19.7% |
| definition | 55 | 6.1% |

| construction | n | share |
|---|---|---|
| direct_support | 216 | 24.0% |
| cross_domain_pairing | 165 | 18.3% |
| unsupported_specific_fact | 96 | 10.7% |
| table_or_caption | 68 | 7.6% |
| negation | 63 | 7.0% |
| over_generalisation | 62 | 6.9% |
| suggests_to_proves | 49 | 5.4% |
| two_passage_synthesis | 46 | 5.1% |
| added_unsupported_fact | 41 | 4.6% |
| direction_swap | 31 | 3.4% |
| concept_switch | 22 | 2.4% |
| numeric_mismatch | 22 | 2.4% |
| owner_sentence | 10 | 1.1% |
| omitted_condition | 9 | 1.0% |

| difficulty tag (pairs can carry several) | n | share |
|---|---|---|
| cross_language | 541 | 60.1% |
| low_lexical_overlap | 317 | 35.2% |
| hedged_vs_strong | 97 | 10.8% |
| table_or_caption | 68 | 7.6% |
| two_passages | 46 | 5.1% |

| domain | n | share |
|---|---|---|
| nlp_llm | 149 | 16.6% |
| systems_data | 126 | 14.0% |
| security | 122 | 13.6% |
| rag_ir | 115 | 12.8% |
| se_testing | 112 | 12.4% |
| cv | 107 | 11.9% |
| ml | 94 | 10.4% |
| hci_web | 75 | 8.3% |

| split | n | share |
|---|---|---|
| test | 630 | 70.0% |
| dev | 270 | 30.0% |

Label x split:

| label | dev | test |
|---|---|---|
| SUPPORTED | 105 | 229 |
| PARTIALLY_SUPPORTED | 51 | 114 |
| CONTRADICTED | 25 | 113 |
| IRRELEVANT | 50 | 116 |
| INSUFFICIENT_EVIDENCE | 39 | 58 |

Label x language:

| label | vi | en | mixed |
|---|---|---|---|
| SUPPORTED | 165 | 134 | 35 |
| PARTIALLY_SUPPORTED | 97 | 63 | 5 |
| CONTRADICTED | 69 | 59 | 10 |
| IRRELEVANT | 83 | 66 | 17 |
| INSUFFICIENT_EVIDENCE | 49 | 37 | 11 |

## 3. Licenses and sources

| license URL | n | share |
|---|---|---|
| http://creativecommons.org/licenses/by/4.0/ | 135 | 90.6% |
| http://creativecommons.org/licenses/by-sa/4.0/ | 12 | 8.1% |
| http://creativecommons.org/publicdomain/zero/1.0/ | 2 | 1.3% |

149 arXiv papers in the dataset; production Source IR passages were built with `semantic_citation._source_from_pdf_bytes` (`extract_tables=False`, `upright_only`, <=192 passages, so long papers are truncated exactly as in production). Owner-paper references included: [23] 1908.10084v1, [26] 2301.13688v2, [16] 2308.08493v3, [14] 2401.07930v2, [15] 2402.03927v2, [17] 2502.06215v1. Two of them (`2402.03927v2`, `2502.06215v1`) exceed production PDF validator caps (link-annotation / active-content node limit, `PDF_STRUCTURE_LIMIT`); for those two only the caps were raised in-process (repository untouched), flagged `validator_override` in `sources`. `2503.05378` (owner ref [11], >100 pages) is rejected by production (`PDF_PAGE_LIMIT`), so its claim is excluded. Other owner references are not CC BY/BY-SA/CC0 on arXiv (arXiv non-exclusive licence) or not on arXiv, so they are not sources.

## 4. Judges and agreement

Judges: OpenCode free models run tool-less (`opencode run` from an empty scratch directory under `judge_sandbox/`, project config denying edit/write/bash/webfetch/websearch/task/external_directory, isolated `XDG_CONFIG_HOME` so no MCP servers load). Each judge sees the claim, the evidence passage(s) and two same-source distractors, shuffled (IRRELEVANT: top-3 passages of the unrelated source by production BM25; owner claims: production BM25 top-3). OpenCode free models rate-limit separately and stopped answering after a few hundred items, so every candidate was also judged by two open-weight models on a private Kaggle 2x T4 kernel with the same judge items and prompt (`Qwen/Qwen3-8B` with thinking off and `ibm-granite/granite-3.3-8b-instruct`; transformers fp16, greedy decoding, 96 new tokens, no tools or network use by the models). Every candidate was then judged by an audit judge, Claude (Anthropic, called through the agent harness with structured output; a family that neither generated claims nor sat on the first panel), with the same items and prompt.

**Acceptance rule v1.1**: a synthetic pair is kept iff it passed the structural checks (section 5) and both the audit judge and at least one other model family return the constructed label. Owner-paper claims keep the panel's majority label only when the audit judge agrees. Rule v1.0 required every recorded vote to agree; a judge that almost never uses a label (Granite answered INSUFFICIENT_EVIDENCE for 3 of 133 constructed items) then vetoes that label, while 42 of the 583 v1.0 labels were still disputed by the audit judge.

| model | calls | valid verdicts | errors/timeouts |
|---|---|---|---|
| claude-audit | 1608 | 1608 | 0 |
| granite-3.3-8b | 1608 | 1585 | 23 |
| qwen3-8b | 1608 | 1607 | 1 |
| beam-free | 307 | 236 | 71 |
| deepseek-v4.1-flash-free | 274 | 208 | 66 |
| glm-5.3-flash-free | 217 | 149 | 68 |
| longcat-2.5-preview-free | 133 | 70 | 63 |
| mimo-v2.6-flash-free | 66 | 4 | 62 |
| nemotron-3-ultra-free | 44 | 0 | 44 |
| nemotron-3.5-lightning-free | 117 | 31 | 86 |
| nemotron-3.5-super-vl-free | 48 | 5 | 43 |

Judge consensus with constructed label (candidates that passed structural checks and have an audit vote plus at least one other vote):

| label | judged | audit judge = constructed | all judges = constructed (v1.0 rule) | accepted (v1.1 rule) |
|---|---|---|---|---|
| SUPPORTED | 492 | 448 | 272 | 418 |
| PARTIALLY_SUPPORTED | 324 | 198 | 48 | 161 |
| CONTRADICTED | 292 | 261 | 55 | 138 |
| IRRELEVANT | 232 | 227 | 204 | 226 |
| INSUFFICIENT_EVIDENCE | 255 | 177 | 6 | 96 |

### Label verification by a held-out judge

Gemini 3.8 Flash judged every candidate with the same items and prompt after the fact; it took no part in acceptance. It agrees with **870 of 900** final labels (96.7%):

| label | pairs | held-out judge agrees | agreement | held-out verdict when it disagrees |
|---|---|---|---|---|
| SUPPORTED | 334 | 333 | 99.7% | PARTIALLY_SUPPORTED 1 |
| PARTIALLY_SUPPORTED | 165 | 145 | 87.9% | SUPPORTED 10, CONTRADICTED 6, INSUFFICIENT_EVIDENCE 4 |
| CONTRADICTED | 138 | 136 | 98.6% | PARTIALLY_SUPPORTED 1, INSUFFICIENT_EVIDENCE 1 |
| IRRELEVANT | 166 | 162 | 97.6% | INSUFFICIENT_EVIDENCE 3, CONTRADICTED 1 |
| INSUFFICIENT_EVIDENCE | 97 | 94 | 96.9% | PARTIALLY_SUPPORTED 2, IRRELEVANT 1 |

Caveat: the held-out judge is a Gemini model, like the claim generator (gemini-3.5-flash-lite), so it may recognise the constructions more readily than an unrelated family. A manual spot check of 20 accepted pairs (4 per label) found no wrong label.

Per judge agreement with the constructed label:

| judge | SUPPORTED | PARTIALLY_SUPPORTED | CONTRADICTED | IRRELEVANT | INSUFFICIENT_EVIDENCE |
|---|---|---|---|---|---|
| deepseek-v4.1-flash-free | 69/72 | 28/46 | 35/38 | 31/31 | 0/0 |
| glm-5.3-flash-free | 44/46 | 23/38 | 21/24 | 19/20 | 0/0 |
| nemotron-3.5-lightning-free | 6/6 | 3/5 | 4/5 | 3/3 | 0/0 |
| longcat-2.5-preview-free | 17/18 | 13/21 | 9/9 | 9/9 | 0/0 |
| qwen3-8b | 305/491 | 202/324 | 84/292 | 222/232 | 106/255 |
| granite-3.3-8b | 428/487 | 84/322 | 73/287 | 209/225 | 6/251 |
| claude-audit | 448/492 | 198/324 | 261/292 | 227/232 | 177/255 |
| beam-free | 86/92 | 39/59 | 32/37 | 46/48 | 0/0 |
| mimo-v2.6-flash-free | 2/2 | 0/1 | 1/1 | 0/0 | 0/0 |
| nemotron-3.5-super-vl-free | 1/1 | 0/2 | 2/2 | 0/0 | 0/0 |

Pairwise judge agreement (all judged candidates, synthetic + owner):

| pair | n | observed agreement | Cohen kappa |
|---|---|---|---|
| deepseek-v4.1-flash-free vs glm-5.3-flash-free | 137 | 0.9343 | 0.9066 |
| deepseek-v4.1-flash-free vs longcat-2.5-preview-free | 66 | 0.8788 | 0.8289 |
| deepseek-v4.1-flash-free vs qwen3-8b | 200 | 0.69 | 0.5735 |
| deepseek-v4.1-flash-free vs granite-3.3-8b | 197 | 0.7107 | 0.5528 |
| deepseek-v4.1-flash-free vs claude-audit | 200 | 0.9 | 0.8592 |
| glm-5.3-flash-free vs longcat-2.5-preview-free | 66 | 0.8636 | 0.8043 |
| glm-5.3-flash-free vs qwen3-8b | 141 | 0.695 | 0.5694 |
| glm-5.3-flash-free vs granite-3.3-8b | 139 | 0.6691 | 0.487 |
| glm-5.3-flash-free vs claude-audit | 141 | 0.8652 | 0.8122 |
| nemotron-3.5-lightning-free vs qwen3-8b | 31 | 0.6129 | 0.4904 |
| nemotron-3.5-lightning-free vs granite-3.3-8b | 31 | 0.7097 | 0.5419 |
| nemotron-3.5-lightning-free vs claude-audit | 31 | 0.6129 | 0.4775 |
| longcat-2.5-preview-free vs qwen3-8b | 70 | 0.6714 | 0.5417 |
| longcat-2.5-preview-free vs granite-3.3-8b | 69 | 0.6522 | 0.4551 |
| longcat-2.5-preview-free vs claude-audit | 70 | 0.8714 | 0.822 |
| qwen3-8b vs granite-3.3-8b | 1585 | 0.5937 | 0.4412 |
| qwen3-8b vs claude-audit | 1607 | 0.6073 | 0.4957 |
| granite-3.3-8b vs claude-audit | 1585 | 0.535 | 0.3692 |
| beam-free vs qwen3-8b | 235 | 0.6766 | 0.5449 |
| beam-free vs granite-3.3-8b | 234 | 0.6795 | 0.517 |
| beam-free vs claude-audit | 236 | 0.8941 | 0.8486 |

Most common disagreement patterns (constructed label -> judge verdict set):

| constructed | judge verdicts | n |
|---|---|---|
| SUPPORTED | SUPPORTED | 272 |
| SUPPORTED | PARTIALLY_SUPPORTED|SUPPORTED | 202 |
| SUPPORTED | IRRELEVANT|PARTIALLY_SUPPORTED|SUPPORTED | 6 |
| SUPPORTED | CONTRADICTED|SUPPORTED | 4 |
| PARTIALLY_SUPPORTED | PARTIALLY_SUPPORTED|SUPPORTED | 169 |
| PARTIALLY_SUPPORTED | SUPPORTED | 51 |
| PARTIALLY_SUPPORTED | PARTIALLY_SUPPORTED | 48 |
| PARTIALLY_SUPPORTED | CONTRADICTED|PARTIALLY_SUPPORTED | 20 |
| CONTRADICTED | CONTRADICTED|PARTIALLY_SUPPORTED|SUPPORTED | 74 |
| CONTRADICTED | CONTRADICTED|PARTIALLY_SUPPORTED | 66 |
| CONTRADICTED | CONTRADICTED | 55 |
| CONTRADICTED | CONTRADICTED|SUPPORTED | 52 |
| IRRELEVANT | IRRELEVANT | 204 |
| IRRELEVANT | IRRELEVANT|PARTIALLY_SUPPORTED | 13 |
| IRRELEVANT | INSUFFICIENT_EVIDENCE|IRRELEVANT | 7 |
| IRRELEVANT | CONTRADICTED|IRRELEVANT | 3 |
| INSUFFICIENT_EVIDENCE | INSUFFICIENT_EVIDENCE|IRRELEVANT | 100 |
| INSUFFICIENT_EVIDENCE | INSUFFICIENT_EVIDENCE|PARTIALLY_SUPPORTED | 38 |
| INSUFFICIENT_EVIDENCE | PARTIALLY_SUPPORTED|SUPPORTED | 24 |
| INSUFFICIENT_EVIDENCE | IRRELEVANT | 11 |

### Owner-paper claims

| pair | label | first two judges agree | votes | claim |
|---|---|---|---|---|
| v1-0891 | PARTIALLY_SUPPORTED | yes | deepseek-v4.1-flash-free=PARTIALLY_SUPPORTED, glm-5.3-flash-free=PARTIALLY_SUPPORTED, nemotron-3.5-lightning-free=INSUFFICIENT_EVIDENCE, longcat-2.5-preview-free=PARTIALLY_SUPPORTED, qwen3-8b=PARTIALLY_SUPPORTED, granite-3.3-8b=SUPPORTED, claude-audit=PARTIALLY_SUPPORTED | Lopez et al. [14] investigate dataset leakage in small language models, such as CodeBERT. The main idea is to use an aut |
| v1-0892 | SUPPORTED | yes | deepseek-v4.1-flash-free=SUPPORTED, glm-5.3-flash-free=SUPPORTED, nemotron-3.5-lightning-free=SUPPORTED, longcat-2.5-preview-free=SUPPORTED, qwen3-8b=SUPPORTED, granite-3.3-8b=SUPPORTED, claude-audit=SUPPORTED | Balloccu et al. [15] studied the issue of data contamination in closed-source LMs. They conclude that 42% of the reviewe |
| v1-0893 | SUPPORTED | yes | deepseek-v4.1-flash-free=SUPPORTED, glm-5.3-flash-free=SUPPORTED, nemotron-3.5-lightning-free=SUPPORTED, longcat-2.5-preview-free=SUPPORTED, qwen3-8b=PARTIALLY_SUPPORTED, granite-3.3-8b=SUPPORTED, claude-audit=SUPPORTED | Golchin et al. [16] use a LM to complete a sentence retrieved from a known benchmark. The completion is then compared wi |
| v1-0894 | PARTIALLY_SUPPORTED | yes | deepseek-v4.1-flash-free=PARTIALLY_SUPPORTED, glm-5.3-flash-free=PARTIALLY_SUPPORTED, longcat-2.5-preview-free=PARTIALLY_SUPPORTED, qwen3-8b=PARTIALLY_SUPPORTED, granite-3.3-8b=SUPPORTED, claude-audit=PARTIALLY_SUPPORTED | Zhou et al. [18] use MinHash+LSH to identify potential duplicate pairs between the benchmarks and the pretraining datase |
| v1-0895 | INSUFFICIENT_EVIDENCE | yes | deepseek-v4.1-flash-free=INSUFFICIENT_EVIDENCE, glm-5.3-flash-free=INSUFFICIENT_EVIDENCE, nemotron-3.5-lightning-free=IRRELEVANT, longcat-2.5-preview-free=INSUFFICIENT_EVIDENCE, qwen3-8b=IRRELEVANT, granite-3.3-8b=PARTIALLY_SUPPORTED, claude-audit=INSUFFICIENT_EVIDENCE | Lopez et al. [14] investigate dataset leakage in small language models, such as CodeBERT. |
| v1-0896 | IRRELEVANT | yes | deepseek-v4.1-flash-free=IRRELEVANT, glm-5.3-flash-free=IRRELEVANT, nemotron-3.5-lightning-free=IRRELEVANT, longcat-2.5-preview-free=INSUFFICIENT_EVIDENCE, qwen3-8b=IRRELEVANT, granite-3.3-8b=PARTIALLY_SUPPORTED, claude-audit=IRRELEVANT | We evaluate several representative models for the EO-to-JSON transformation task, including CodeT5-small (60M) [24], Cod |
| v1-0897 | PARTIALLY_SUPPORTED | yes | deepseek-v4.1-flash-free=PARTIALLY_SUPPORTED, glm-5.3-flash-free=PARTIALLY_SUPPORTED, nemotron-3.5-lightning-free=SUPPORTED, longcat-2.5-preview-free=SUPPORTED, qwen3-8b=PARTIALLY_SUPPORTED, granite-3.3-8b=SUPPORTED, claude-audit=PARTIALLY_SUPPORTED | For string-based values, the proposed method uses a Sentence Transformer [23] to convert values into semantic embedding  |
| v1-0898 | SUPPORTED | yes | deepseek-v4.1-flash-free=SUPPORTED, glm-5.3-flash-free=SUPPORTED, nemotron-3.5-lightning-free=INSUFFICIENT_EVIDENCE, longcat-2.5-preview-free=SUPPORTED, qwen3-8b=PARTIALLY_SUPPORTED, granite-3.3-8b=SUPPORTED, claude-audit=SUPPORTED | Balloccu et al. [15] studied the issue of data contamination in closed-source LMs. |
| v1-0899 | PARTIALLY_SUPPORTED | yes | deepseek-v4.1-flash-free=PARTIALLY_SUPPORTED, glm-5.3-flash-free=PARTIALLY_SUPPORTED, nemotron-3.5-lightning-free=SUPPORTED, longcat-2.5-preview-free=SUPPORTED, qwen3-8b=SUPPORTED, granite-3.3-8b=SUPPORTED, claude-audit=PARTIALLY_SUPPORTED | Data contamination in SLMs refers to the unintentional inclusion of evaluation data during the training process of a SLM |
| v1-0900 | SUPPORTED | tie-break | deepseek-v4.1-flash-free=PARTIALLY_SUPPORTED, glm-5.3-flash-free=SUPPORTED, nemotron-3.5-lightning-free=SUPPORTED, longcat-2.5-preview-free=PARTIALLY_SUPPORTED, qwen3-8b=PARTIALLY_SUPPORTED, granite-3.3-8b=SUPPORTED, claude-audit=SUPPORTED | Golchin et al. [16] use a LM to complete a sentence retrieved from a known benchmark. |

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
| INSUFFICIENT_EVIDENCE | key_fact_present_in_source_or_missing | 525 |
| INSUFFICIENT_EVIDENCE | generator_flagged_unusable | 103 |
| INSUFFICIENT_EVIDENCE | language_mismatch | 34 |
| INSUFFICIENT_EVIDENCE | ie_claim_restates_quote | 3 |
| OWNER | source_not_built_in_production_ir | 1 |

Structural stage also dropped 380 INSUFFICIENT_EVIDENCE candidates of the first design (see section 8); 2620 generated items entered the checks.

Judge stage (candidates rejected because the audit judge or every other family disagreed with the constructed label):

| label | rejected by judges | accepted pool before mix selection |
|---|---|---|
| SUPPORTED | 74 | 418 |
| PARTIALLY_SUPPORTED | 163 | 161 |
| CONTRADICTED | 154 | 138 |
| IRRELEVANT | 6 | 226 |
| INSUFFICIENT_EVIDENCE | 159 | 96 |

Candidates without an audit vote or any other vote (judge errors / quota): {}.

Pairs surviving structural + judge checks were then down-sampled to the target mix with per-label language quotas (vi 50%, en ~39.5%, mixed ~10.5% of synthetic) and a least-used-source-first rule.

## 6. Dual Split and leakage

Dual Split (owner paper, Algorithm 1/2) with the input side = claim text (citation marker stripped) and the output side = the evidence quote(s) the claim was built from (IRRELEVANT: the origin quote; INSUFFICIENT_EVIDENCE: the related quote; owner claims: the source id). `df_cut=0.01`, `k=3`, target dev ratio 0.30. Clusters are visited largest first and the pair goes to the most under-filled split (the paper's argmin rule read this way converges to the ratio); both deviations are noted in `scripts/dual_split.py`.

Clusters: 793 (largest 3, singletons 695).

| metric (test claims vs dev claims) | Dual Split | random split (mean of 5 seeds, same sizes) |
|---|---|---|
| ngram4_leaked_pct | 34.76 | 36.412 |
| max_trigram_jaccard_mean | 0.0232 | 0.0272 |
| cosine_max_mean | 0.2395 | 0.2519 |
| cosine_max_p95 | 0.3445 | 0.3905 |
| cosine_ge_0.8_pct | 0.0 | 0.032 |
| cosine_ge_0.9_pct | 0.0 | 0.0 |
| test_with_same_evidence_in_dev_pct | 0.0 | 7.524 |

`ngram4_leaked_pct`: share of test claims sharing at least one word 4-gram with any dev claim. Cosine: char-4-gram TF cosine to the nearest dev claim. `test_with_same_evidence_in_dev_pct`: test pairs whose evidence text also anchors a dev pair.

## 7. Runtime and API usage

- Gemini: 747 successful `generateContent` calls ({'gemini-3.5-flash-lite': 747}), prompt tokens 1,074,011, output tokens 220,103. ~4.5 s pacing between calls; no 429 daily-quota hit.
- OpenCode free judges: see vote table above (about 16k input tokens per call because the OpenCode agent prompt is attached; free models rate-limit independently, which forced pooling several model families).
- arXiv: OAI-PMH discovery (27 ListRecords requests), one OAI `arXivRaw` GetRecord per paper for the exact version, one PDF download per paper, all >=3 s apart on one connection. The Atom `export.arxiv.org/api/query` endpoint answered HTTP 429 ('Rate exceeded') so versions/licences come from OAI-PMH (`oaipmh.arxiv.org`).

## 8. Design notes and known weaknesses

- **Size and mix.** 900 pairs passed rule v1.1 (request: 700-1000). Rare labels are thinner than the target mix (INSUFFICIENT_EVIDENCE 97, CONTRADICTED 138): judges seldom confirm constructed contradictions and INSUFFICIENT_EVIDENCE, so per-class scores for those labels are noisier.
- **Labels are AI-verified, not human.** Agreement of constructed label, audit judge and another family shows the construction is recognisable to strong LLMs, not that humans agree. The generator (Gemini) is also the model family evaluated in stage 4, which can favour it.
- **Synthetic errors are easier than real miscitations.** Negations, swapped numbers, concept swaps and cross-domain IRRELEVANT pairs are cleaner than real student errors (loose paraphrase, wrong paper section, mixed correct/incorrect claims). Expect optimistic accuracy; the acceptance filter additionally removes ambiguous cases, so the set has fewer borderline items than reality.
- **IRRELEVANT is cross-domain by construction** (different arXiv category family, lowest BM25 overlap of several candidates) — far easier than real "same field, wrong paper" miscitations. INSUFFICIENT_EVIDENCE is the realistic hard counterpart.
- **INSUFFICIENT_EVIDENCE design change.** First design (quote topic + one invented fact) was judged PARTIALLY_SUPPORTED by both judges on a 8-item probe (the supported topic part counts as support). It was regenerated as "same subject, different aspect, whole claim is an unsupported specific fact"; the 380 old candidates were discarded. The key fact must be absent from the full 192-passage Source IR (digits, rare words); absence from the *PDF beyond 192 passages* is not checked.
- **PARTIALLY_SUPPORTED vs INSUFFICIENT_EVIDENCE boundary is inherently fuzzy**; the judge prompt states the spec definitions, but real annotators may split differently.
- **Owner-paper claims are far fewer than the 10% target.** Only the owner paper sentences that cite a reference available on arXiv under CC BY/BY-SA/CC0 *and* parseable by the production Source IR can be used (10 pairs, 1.1% of the set). Their labels come from judge agreement only, with BM25 top-3 retrieval.
- **Language**: Vietnamese/mixed claims were written by Gemini, not by Vietnamese students; mixed-language detection is a heuristic (ASCII-token share >= 0.33). Citation markers `[n]` were appended to ~25% of synthetic claims.
- **Evidence quotes are sentences cut from passages by regex**, so "table" evidence is limited to figure/table captions that survive as passages (production extracts no tables). Passages are capped at 192 per paper and PDFs rejected by production validators are absent (~20% of selected papers), so the source set is biased toward PDFs production can ingest.
- **Judge context** is the evidence passage plus two retrieval-ranked distractors (not production's top-3 for the claim), so retrieval errors are not measured here; stage 3 of the benchmark script measures retrieval.
- Dual Split controls claim/evidence overlap, not paper-level overlap: the same paper can appear in dev and test.
