# Citation Semantic Support Implementation Plan

**Scope:** Claim extraction, Source IR, bounded retrieval, validated semantic verdicts, score/coverage gating, Teacher review projection, stage-wise benchmark, tests, and canonical docs. Identity/linkage contracts remain intact.

## Contract decisions

- Add `app.services.semantic_citation`; keep deterministic identity/linkage in `app.services.citation`.
- Existing citation evaluator parses and resolves once, then passes enriched report to semantic evaluator.
- Select semantic criteria only through `evaluation_method` or `evaluator_config.type == "CITATION_SEMANTIC"`.
- Persist semantic detail in `AnalysisJob.snapshot["semantic_citation"]`; migration `20260924_0017` adds only nullable `ReviewDecision.edited_semantic_verdict` plus taxonomy constraint for durable Teacher overrides.
- Persist one Finding per eligible pair/result, report claim anchor only. Each result keeps at most three selected source passages; report-level `sources` keeps metadata without full passage corpus. Source anchor stays in validated snapshot because current evidence FK can reference only report Document IR.
- Superseded 2026-10-17 (see [design §5](../specs/2026-09-24-semantic-citation-support-design.md)): production source descriptors are still server-owned, but DOI is no longer operator-cache-only. Two private write-through lanes ship, both opt-in via `SEMANTIC_SOURCE_FETCH_ENABLED`: verified arXiv-only references with exact `vN`, and DOI references through OpenAlex open-access PDFs fetched with `fetch_public_https`. Bibliography URLs and arbitrary network fetch remain forbidden.
- Superseded 2026-10-15 (see design §3 step 9 and §6): bounded BM25 plus the RRF/dense adapter boundary shipped first; the real-paper probe then reversed the synthetic BGE-M3 result (Hit@3 BM25 5/16, BGE-M3 13/16, BGE-M3 + reranker 15/16). A shared OpenAI-compatible/TEI encoder with optional reranker is the recommended self-hosted retriever; BM25 stays the fallback when no encoder URL is configured.
- Superseded 2026-10-17 (see design §6): the route selects one fixed adapter among OpenAI, Anthropic, Gemini, DeepSeek, OpenCode Zen and Bedrock, not Bedrock alone. Every adapter sets a token limit, sends no tools and makes one normal call plus one schema-error retry maximum. Safe NFKC/case-fold/whitespace whole-passage equality may return deterministic support without a model only after removing the linked mention when it is itself a trailing bracketed numeric marker; operators and unpaired internal punctuation remain exact, while negation, Unicode quotes, paired delimiters, other marker formats, unrelated trailing numeric text, and non-exact text do not bypass model/manual routing.
- Automatic score stays disabled until recorded gate metrics and domain approval pass. No human gold exists at baseline.
- Reuse existing Teacher `ACCEPT`/`EDIT`/`REJECT` and reason flow. Add semantic projection/UI, not another review state machine.

## Implementation order

1. Add Pydantic contracts/enums, deterministic claim extraction, Source IR builder, safe identity confirmation.
2. Add BM25, optional dense ranking/RRF, deterministic rerank, top-three anchors.
3. Add model protocol, Bedrock adapter, output validation/retry, abstract-only constraints, feedback templates, score/coverage gate.
4. Integrate semantic criteria into citation persistence without changing identity/linkage findings.
5. Extend evidence API/OpenAPI-generated frontend types and Teacher semantic cards.
6. Add focused unit/integration tests for eligibility, claim scope, numeric/negation/condition cases through fixed model outputs, table passages, abstract-only, unavailable source, retry, scoring, and unchanged identity behavior.
7. Add stage-wise benchmark fixture/schema/script. Mark annotations synthetic/AI-draft unless human provenance is supplied; gate must report blocked.
8. Reconcile BR-11/13/14/21/24/32 and benchmark docs.

## Required proof

- Unlinked, parser-uncertain, unverified, unavailable, abstract-only, or ambiguous citations cause zero semantic model calls.
- Every persisted semantic Finding has report claim anchor.
- Every model verdict references only supplied source passage IDs with source hash/provenance.
- Unavailable source and invalid model output never become student-error verdicts.
- Exact safe textual equality invokes zero model calls; other normal paths invoke once per pair; invalid schema invokes at most twice.
- Score denominator excludes non-evaluable statuses; low coverage/gate leaves proposed score null.
- Teacher API/UI exposes verdict and source anchor; existing override path handles decision and reason.
- Existing citation suite still passes.
- Backend pytest/Ruff/Black, frontend typecheck/build, benchmark script, and changed-path smoke pass.

## Final review groups

### Functional correctness

Verify citation scope, source identity gate, passage ranking, verdict validation, abstract-only routing, score/coverage math, and idempotent persistence.

### Security/privacy

Verify fixed private-storage boundary, canonical arXiv IDs and exact revisions, no redirect/arbitrary URLs/tools, bounded request count/input/output/cache payload, prompt-injection framing, sanitized provider failures, and no Student exposure of internal scores/model metadata.

### Compatibility/data

Verify migration upgrade/downgrade, old citation snapshots still validate, missing semantic snapshot remains optional, and identity/linkage outputs remain unchanged.

### Quality claim

Report fixture provenance, exact pair counts/metrics, unavailable full-text cases, latency/calls/tokens, and blocked gate. Never claim semantic accuracy without human gold and independent review.
