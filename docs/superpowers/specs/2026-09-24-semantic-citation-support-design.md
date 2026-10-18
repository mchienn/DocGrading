# Citation Semantic Support Design

**Date:** 2026-09-24

**Status:** Implemented semantic pipeline; provider routing and credential management are Admin-controlled. Automatic scoring remains blocked until a human gold set and domain sign-off satisfy the quality gate.

**Baseline:** `main` and `mchienn/feature-semantic-citation-support-v-i-claim-leve` both at `881d3acc54918c69006a5362a895f1371d5230da` before implementation. Worktree was clean.

## 1. Goal and boundary

For each reliably linked citation, assess only whether the cited source supports the report claim. This does not establish scientific truth, detect plagiarism or AI authorship, rank journals, repair citations, or perform open-domain fact checking.

Semantic evaluation is eligible only when all conditions hold:

- document citation parser and bibliography status are `PARSED`;
- citation mention parser status and linkage status are `PARSED` and `LINKED`;
- exactly linked reference parser status is `PARSED`;
- reference identity status is `VERIFIED`;
- acquired source bytes/text pass identity confirmation against that reference.

Identity/linkage findings remain deterministic and unchanged. Semantic criteria use evaluator type `CITATION_SEMANTIC`; existing `CITATION`, `CITATION_IDENTITY`, and `CITATION_LINKAGE` criteria keep current behavior.

## 2. Selected architecture

Use one bounded module, `app.services.semantic_citation`, called by the existing citation evaluator after deterministic parsing and identity resolution. Parse/link/resolve work runs once per job. Semantic analysis and source evidence add no normalized relational schema: claim-level records, source provenance, source passage anchors, metrics, score state, and explicit result-to-Finding links live in the versioned `AnalysisJob.snapshot["semantic_citation"]` JSONB payload. Provider credentials and the single `CITATION_SEMANTIC` route are normalized operational configuration because they need Admin mutation, encryption, optimistic concurrency, revocation and audit. The active route is copied into each new job snapshot without secret material; queued jobs never silently adopt a later provider/model revision. Migration `20260924_0017` adds nullable `ReviewDecision.edited_semantic_verdict`, constrained to the semantic taxonomy, so Teacher overrides are durable and auditable. A separate internal `semantic_citation_trace` records evaluator/parser/Source-IR/retrieval/prompt versions, criterion/config hash, provider/model/protocol/region, budget/usage/latency and result provenance. Teacher/Student projections exclude provider routing, credentials and trace.

Source evidence cannot use current `EvidenceAnchor`: that table is constrained to a report `DocumentIR`. Source passage anchors therefore stay in the validated semantic snapshot with immutable source hash, passage ID, page, section, element ID, and retrieval provenance. Adding normalized source/evidence tables is deferred until retention/query needs justify migration.

Rejected alternatives:

1. Reuse report `DocumentIR` rows for source PDFs: invalid ownership; each row requires a report `DocumentVersion`.
2. Add source, passage, and cross-document anchor tables now: more DDL and lifecycle code without measured query need.
3. Send whole source PDF to model: violates retrieval and data-minimization requirements.
4. Fetch bibliography URLs: untrusted arbitrary-URL/SSRF boundary.
5. Superseded on 2026-10-15 by the real-paper benchmark reversal (BM25 Hit@3 5/16, BGE-M3 13/16, BGE-M3 + reranker 15/16; see §3 step 9 and §6): a shared encoder with optional reranker is now the recommended self-hosted retriever and BM25 remains the fallback. Original rejection: add a dense-model production dependency after local retrieval benchmark: BGE-M3 improved rank quality but reduced primary Hit@3 and added unacceptable CPU cold-start/RAM cost; see [`docs/benchmarks/bge-m3-retrieval-2026-09-24.md`](../../benchmarks/bge-m3-retrieval-2026-09-24.md).

## 3. Data flow

1. Existing parser produces `CitationReport`.
2. Identity resolution (Crossref, arXiv Atom, OpenAlex title search and DOI lookup; provider limits and matching rules in BR-11) runs once in the citation evaluator; semantic evaluation reuses its `VERIFIED` references.
3. Claim extractor indexes Document IR paragraphs and consumes only eligible linked mentions.
4. Deterministic scope selects sentence containing mention, then an unambiguous semicolon clause when possible. Citation markers at different places in one sentence split it: each marker owns the text since the previous marker, and the sentence tail belongs to the last marker; a segment of fewer than four words keeps the whole sentence. Adjacent markers (`[7] [11]`, `[7], [11]`) cite one statement, so each reference gets the whole sentence as its own claim-reference pair and is retrieved in its own source. Markers are parsed mention spans plus bracketed markers; parentheses such as "(DNN)" are not markers. Exact paragraph character offsets, page, element ID, line range, and bbox remain attached. Previous/next sentence is context only; it never changes verbatim claim span.
5. A single-marker sentence that coordinates several propositions (", and B shows ...") returns `AMBIGUOUS_CLAIM`. Optional scope resolver may run only on those cases; failure remains ambiguous. On the 30 distinct student reports (parser v8, every reference treated as verified), splitting by marker cut `AMBIGUOUS_CLAIM` from 167 of 339 pairs to 0 of 344; median claim length fell from 166 to 105 characters.
6. Source repository checks the operator-managed private-object cache at a key derived from the verified DOI/arXiv identifier. On a cache miss, and only when `SEMANTIC_SOURCE_FETCH_ENABLED=true`, it downloads an arXiv-only reference from the fixed `https://arxiv.org/pdf/` endpoint, or a reference with a DOI (printed, or matched by Crossref/OpenAlex during identity resolution) from open-access locations OpenAlex lists for that DOI. Every downloaded PDF is validated and identity-confirmed before it is written to the private cache. Report annotations, Teacher payloads, and criterion config cannot supply raw object keys, URLs, or source bytes.
7. Source identity validator requires matching DOI/arXiv text or bounded title plus author metadata evidence before semantic evaluation. A mixed DOI+arXiv reference cannot pass on arXiv ID alone; DOI or title/author agreement is required. Mismatch is unavailable/manual review, never semantic contradiction.
8. Production semantic PDF parsing reuses the existing untrusted-PDF validator but skips table discovery; table text remains searchable as bounded text passages. This avoids table-analysis cost and compatibility failures irrelevant to top-passage retrieval. The pure adapter still accepts explicit table passages for deterministic fixtures. All Document IR, student reports and sources alike, treats a horizontal gap above 15% of glyph size as a word break (`document_ir.WORD_X_TOLERANCE_RATIO`); pdfplumber's fixed 3 pt default glued justified LaTeX words, which made arXiv passages unreadable and hid author-year mentions in student reports (#47). Source parsing also drops rotated words (`upright_only`), so arXiv's vertical margin stamp cannot split body paragraphs. Shared Document IR reads justified two-column pages with a narrow gutter column by column, so ACL/IEEE sources no longer interleave left and right lines. Before windowing, Source IR drops paragraphs with fewer than two words of three or more letters (equation numbers, formula fragments), rejoins a lowercase continuation onto a same-page paragraph that stopped mid-sentence, and rejoins words hyphenated across lines.
9. Retrieval ranks Source IR passages with the shared text encoder when one is configured, else with bounded BM25 plus deterministic numeric/unit reranking. The query drops bracketed numeric citation markers (`[2]`, `[1, 3]`) so they never match equation numbers or count as numeric evidence. With a cross-encoder reranker configured, the encoder's top 20 are reranked; a reranker failure keeps the encoder order. Top three passages continue. Encoder order is used alone: BM25+dense RRF measured worse than either on both the synthetic set and real papers. On 16 AI-drafted Vietnamese claims over five real arXiv papers (136–192 passages), BM25 Hit@3 is 5/16, BGE-M3 dense 13/16 and BGE-M3 plus `bge-reranker-v2-m3` 15/16, on CPU and identically on real TEI 1.9 on a Kaggle T4 ([`bge-m3-retrieval-2026-09-24.md`](../../benchmarks/bge-m3-retrieval-2026-09-24.md)).
10. Only normalized whole-passage equality can return deterministic `SUPPORTED`, after stripping the linked mention when it is itself a trailing bracketed numeric citation marker. Normalization performs NFKC/case-fold/whitespace and terminal-period handling while preserving mathematical/comparison operators and unpaired internal punctuation. Claims/passages containing negation, Unicode quotation punctuation, or paired delimiters never use this shortcut. Safe exact equality works even when model routing is disabled. Author-year/superscript markers, unrelated trailing numeric text, and every non-exact case continue to the provider route or manual review; with no active route they are `NEEDS_MANUAL_REVIEW` with reason `MODEL_NOT_ROUTED`, never `INSUFFICIENT_EVIDENCE`. Invalid structured output gets one retry; second failure yields `NEEDS_MANUAL_REVIEW`. A server-owned per-job budget counts every model attempt, including schema retry.
11. Every result creates deterministic Teacher feedback and one reviewable Finding per semantic criterion, anchored to the report claim. `finding_links` maps response records to persisted Finding IDs. Each result retains only its top-three passage anchors/text. Report-level `sources` stores metadata with an empty passage list, preventing full retrieval corpora from being duplicated into JSONB/API payloads.
12. Score and coverage are computed separately. Automatic proposed score remains null unless a trusted quality-gate artifact and configured coverage threshold both pass. Criterion `evaluator_config` may display metrics but cannot self-approve the gate.

## 4. Contracts

### 4.1 Claim-citation pair

Each pair contains:

- stable `pair_id`, `claim_id`, mention ID, reference ID;
- verbatim atomic claim and bounded citation context;
- report anchor: page, element ID, exact character `start`/`end`, line range, bbox;
- extraction method: `SENTENCE`, `CLAUSE`, or `MODEL`;
- ambiguity reason when no reliable scope exists.

A marker linking multiple verified references produces one pair per distinct source while retaining one claim ID. This permits multiple citations to jointly support one claim without merging source evidence. Bibliography entries sharing a canonical DOI, else arXiv ID, count as one source: the claim gets one pair for the first such entry in document order, Source IR is acquired once per canonical identity, and metadata resolution runs once per identity. Duplicate-reference findings stay unchanged.

### 4.2 Source IR

Source metadata:

- `source_id`, DOI/arXiv/provider identifier, version, title, authors;
- immutable SHA-256, retrieval timestamp and provenance;
- access type `FULL_TEXT`, `ABSTRACT_ONLY`, or `USER_PROVIDED`.

Passage metadata:

- stable `passage_id`, text, page, section, element ID;
- source hash and source ID;
- passage kind `TEXT` or `TABLE`;
- source bbox when available.

`ABSTRACT_ONLY` may have no PDF page; provider provenance replaces page coordinates. Detailed numeric, method, dataset, conditional, causal, and comparative claims cannot receive support/contradiction from abstract-only input.

### 4.3 Taxonomy

Pipeline statuses:

- `SUPPORTED`
- `PARTIALLY_SUPPORTED`
- `CONTRADICTED`
- `IRRELEVANT`
- `INSUFFICIENT_EVIDENCE`
- `SOURCE_UNAVAILABLE`
- `AMBIGUOUS_CLAIM`
- `NEEDS_MANUAL_REVIEW`

Only first five are model output values. `SOURCE_UNAVAILABLE`, `AMBIGUOUS_CLAIM`, and `NEEDS_MANUAL_REVIEW` are deterministic routing outcomes.

`CONTRADICTED` requires direct conflicting evidence. `IRRELEVANT` means retrieved source content concerns a different topic. `INSUFFICIENT_EVIDENCE` means source is readable/relevant but evidence is too weak or incomplete. None of the last four statuses is automatically a student error.

The fixed system instruction (prompt version `citation-semantic-v2`) states these five definitions, that claims may be Vietnamese, English or mixed against English passages, and the output field rules: evidence IDs come from the supplied passages, `supported_parts`/`unsupported_parts` are verbatim claim substrings, and each verdict has one reason code. Version 1 sent only the schema and allowed values; on the v1 AI-consensus set (§7) models then answered `INSUFFICIENT_EVIDENCE` for off-topic sources (`IRRELEVANT` F1 0) and paraphrased claim parts, which validation rejects as invalid output.

Model output validates with Pydantic:

```json
{
  "verdict": "SUPPORTED",
  "evidence_passage_ids": ["passage-id"],
  "supported_parts": ["verbatim supported part"],
  "unsupported_parts": [],
  "reason_code": "DIRECT_SUPPORT",
  "manual_review_required": false
}
```

Evidence IDs must be a non-empty subset of supplied passages. Model gets no tools, URLs, source discovery, citation repair, DOI generation, or permission to use outside knowledge.

## 5. Source acquisition boundary

Production source acquisition is server-owned. `SEMANTIC_SOURCE_CACHE_PREFIX` names an operator-managed private S3 prefix; the object key is deterministically derived as `<prefix>/<doi|arxiv>/<sha256(kind:canonical-id)>.pdf`. Criterion config, report annotations, and Teacher requests cannot choose raw keys or URLs. Reads are bounded by both semantic and PDF decoded-byte limits, parsed through the existing PDF validator, and identity-confirmed before any retrieval/model call.

Two automatic acquisition adapters exist, both requiring a `VERIFIED` reference, `SEMANTIC_SOURCE_FETCH_ENABLED=true` and a configured private cache prefix. The arXiv adapter takes arXiv-only references with a provider-bound exact `vN`; metadata enrichment binds unversioned arXiv-only citations to provider-returned exact revisions, so persistent object keys and source metadata identify immutable PDFs. It constructs one fixed canonical HTTPS PDF URL, refuses redirects, permits only PDF/octet-stream responses with bounded declared and actual size and requires PDF magic bytes. The OpenAlex adapter takes references with a DOI, including mixed DOI+arXiv references and references whose DOI Crossref or OpenAlex matched during identity resolution. It reads the work record from the fixed `https://api.openalex.org/works/doi:` endpoint and tries at most two locations flagged `is_oa` with a `pdf_url`, best location first, so paywalled publisher copies are never requested. At most 16 OpenAlex lookups run per job. Provider-listed URLs go through a public-HTTPS fetcher: HTTPS on port 443 only, no credentials in the URL, malformed URLs refused, every resolved address globally routable (NAT64 and IPv4-compatible IPv6 addresses are judged by their embedded IPv4 address) and the connection pinned to the checked address, at most three redirects each re-checked, no environment proxies, at most 60 s per fetch including redirects and body, bounded declared and actual size and PDF/octet-stream content type. Both adapters then require PDF magic bytes, run the normal PDF security validator and confirm identity (DOI in the PDF, else title plus author) before writing exact bytes with private S3 controls; the evaluator re-checks identity with the same printed or matched DOI. Cache write failure denies source. Report URLs, search snippets, LLM-suggested URLs, unversioned arXiv IDs and non-open-access locations are never fetched. Missing source returns `SOURCE_UNAVAILABLE`; abstract-only input remains `INSUFFICIENT_EVIDENCE` without a model call.

On the 35 real student reports (374 references), identity resolution first verified 56 references; 273 stayed `UNRESOLVED`, mostly because 8 parallel Crossref requests 0.1 s apart and 4–5 s timeouts were throttled (Crossref's public pool allows 1 request/s on one connection) and because exact year/title comparison failed on glued words, misparsed title fields and preprint-vs-proceedings years. With provider-paced requests, title checking against the raw reference, a ±1 year, OpenAlex title search and an OpenAlex fallback for arXiv IDs, 250 references verified when arXiv answered and 224 when export.arxiv.org answered 503 (arXiv lane 81, DOI lane 143). For the 143 DOI references OpenAlex listed open-access PDFs for 85; 67 downloaded (ACM and IEEE copies answer 403/420 to automated requests) and 42 passed identity, so about 123 references now have a usable full text against 46 before. The remaining `UNRESOLVED` references are mostly web pages, Vietnamese theses and books, and references whose title the parser could not isolate.

LLM web-search discovery is approved but not built. Free options were checked on 2026-10-17: Gemini Grounding with Google Search forbids using returned links to pick pages to fetch or analyse, Perplexity Pro subscriptions no longer include API credit, and OpenCode's free models only answer inside the OpenCode client. A plain search API with a free tier (Tavily: 1,000 credits/month) can suggest candidate URLs for web-page references; each URL would still go through the public-HTTPS fetcher and an identity check (title, site, date), never be accepted from an LLM answer, and never be taken from the student report.

The fixed arXiv Atom metadata client selects at most 64 arXiv-only references per job, in batches of 32 IDs. Each batch is retried once after the three-second pacing; only when arXiv answered but omitted IDs does it make at most eight single-ID requests; misses are cached for five minutes. Metadata and PDF clients reject redirects. Rate/cache state is process-local, so production egress policy or a shared proxy must enforce aggregate arXiv pacing across replicas. arXiv PDFs remain private analysis inputs: no presigned download path exposes this cache. Operators must set lifecycle retention and confirm paper-specific redistribution/license obligations before any use beyond private analysis. Live download/cache evidence and one fail-closed compatibility case are recorded in [`docs/benchmarks/arxiv-source-acquisition-2026-09-24.md`](../../benchmarks/arxiv-source-acquisition-2026-09-24.md).

## 6. Retrieval, provider routing and credentials

BM25 is standard-library code over bounded Source IR passages and stays the fallback. Dense retrieval goes through one shared client (`app.services.text_encoder`) that speaks OpenAI-compatible `POST {url}/embeddings` and Text Embeddings Inference `POST {url}/rerank`, so the model is configuration: `SEMANTIC_ENCODER_URL`, `SEMANTIC_ENCODER_MODEL`, optional `SEMANTIC_ENCODER_API_KEY` (HTTPS only, sent only to the embeddings URL, never to the reranker), query/document prefixes for models that need them (e5, Gemini Embedding 2) and optional `SEMANTIC_RERANKER_URL`. The self-hosted default is the Compose `encoder` profile: Text Embeddings Inference CPU containers serving pinned `BAAI/bge-m3` and `BAAI/bge-reranker-v2-m3` (MIT/Apache-2.0); hosted OpenAI-compatible embedding APIs work with the same client but receive de-identified claims and public source passages. Claims are de-identified with the submission owner's identity before encoding; without that identity retrieval stays on BM25. Passage vectors are computed once per encoder fingerprint and exact passage texts and stored as packed float32 under `<prefix>/embeddings/` in the private cache, so later jobs citing the same paper skip encoding and a parser change can never pair old vectors with new passages. Any encoder, reranker or cache failure, including malformed responses, falls back to BM25 for that claim and is counted in the trace. BGE-M3 on CPU encodes about 5 passages/s (about 40 s for a 192-passage paper) and the reranker adds about 8 s per claim. Hosted `gemini-embedding-001` through Gemini's OpenAI-compatible endpoint (rows arrive without `index`, so input order is kept) reached Hit@3 14/16 on the real-paper probe with no local CPU, but the free tier answered unpaced batches with 429 and needed 8-text batches 12 s apart, so a hosted encoder needs paid quota.

One versioned `CITATION_SEMANTIC` route selects exactly one fixed provider adapter: OpenAI, Anthropic Claude, Google Gemini, DeepSeek, OpenCode Zen or Amazon Bedrock. OpenAI/DeepSeek use OpenAI chat-compatible requests (OpenAI sends `max_completion_tokens`, which its reasoning models require; DeepSeek and OpenCode Zen send `max_tokens`); Claude uses Messages; Gemini uses `generateContent`; OpenCode Zen stores the model protocol explicitly because its catalog routes models through OpenAI Chat, OpenAI Responses, Anthropic Messages or Gemini `generateContent`. Every protocol sends the semantic instruction through its dedicated system channel (`system` message, `instructions`, `system` or Gemini `systemInstruction`), never concatenated with untrusted claim/source text. Hosts, schemes and paths are code-owned HTTPS constants. Admin input cannot set base URL, raw path, proxy or redirect. There is no automatic provider fallback.

OpenCode requests use the Console inference API at `https://opencode.ai/inference/v1` (`/chat/completions`, `/responses`, `/messages`, `/models/<id>:generateContent`, catalog `/models`); Console service-account keys (`oc_sk_…`) are rejected by the legacy `/zen/v1` Messages and Gemini paths. OpenCode's free models answer `FreeTierError` outside the OpenCode client, so routes must select a paid model on a funded workspace. Every hosted request sends `User-Agent: DocGrading/1.0`: OpenCode's Cloudflare front returns 403 (error 1010) to urllib's default agent, which would otherwise surface as an invalid credential.

OpenAI, Anthropic, Gemini, DeepSeek and OpenCode keys come from a fixed server-environment allowlist or Admin-pasted encrypted storage. Bedrock uses the AWS IAM credential chain only. Stored keys use vetted authenticated encryption with a versioned key ID and encrypted envelope bound to credential row/provider; the encryption keyring exists only in API/worker environment. Plaintext key is never returned, audited, logged, queued or copied into a job snapshot. Reads expose source and masked hint only. Unknown key version, failed decryption, disabled provider, policy denial, missing environment key or credential revision mismatch fails closed to manual review. Previous encryption keys must remain available for live rows and restorable backups until re-encryption and backup retention complete.

Before hosted or Bedrock generation, worker resolves submission owner and de-identifies outbound text with exact owner UUID, email and display name plus bounded generic email, UUID and labeled student-identity patterns. Display names of three or more characters are redacted as case-insensitive substrings; shorter names are redacted only as standalone Unicode tokens. Provider payload contains only redacted claim/context, `source_id`, access type and redacted passage ID/text; source title, author, page and section metadata are omitted. Missing submission identity fails closed to manual review.

Keyring rotation order is fixed: add new key version to every API/worker environment, set it active, restart all processes, re-save each stored provider credential so its envelope uses the active key, verify catalog access and explicitly reactivate affected routes. Keep old versions through live-row and backup retention; remove them only after no row references the version and a restore drill succeeds. Removing a referenced version fails closed. Environment-key catalog verification compares fingerprints; successful rotation increments credential revision and deactivates affected routes before reactivation.

Admin catalog verification calls fixed model-list endpoints without report/claim/source content. Status is bound to the exact credential revision and means only catalog/credential access, not successful generation. Provider/config mutation makes the previous check stale and atomically deactivates any affected active route. Route activation separately requires enabled credential, current catalog verification, data-policy approval, quality approval and explicit fee acknowledgment. API mutation uses CSRF, `If-Match` and locked provider/route rows; audit payloads are write-time allowlists that exclude request bodies, secrets, ciphertext, headers, provider bodies and exception text.

Every new job snapshots route/config revision, provider, protocol, model, region, token/call limits and credential revision before dispatch. Runtime resolves only that snapshot; it never falls back to a current or legacy environment route. Credential disable or revision change stops model calls for queued/retried jobs. Model responses remain Pydantic-validated; provider errors map to fixed safe classes and semantic review continues manually.

Sources resolve sequentially (provider pacing); claims then run in parallel, at most `SEMANTIC_MODEL_CONCURRENCY` (default 4) per job, and results keep pair order. Under budget pressure, which of the first few concurrent claims receive the last model calls is not fixed. Hosted adapters retry HTTP 429/503 twice, waiting what the provider asks (`Retry-After`, Gemini `retryDelay`) up to 30 s; free tiers with few requests per minute should run with concurrency 1. One prompt per claim stays the contract: grouping several claims into one prompt saves at most a third of calls (49% of real pairs share a source with another claim) but published batch-prompting results lose 2–4 accuracy points, show position bias, and let an injected instruction in one student claim steer the others; token cost per report is already about $0.01–0.02.

Bedrock adapter uses `bedrock-runtime.converse`, explicit `maxTokens`, temperature zero, adaptive SDK retry, no tools and a server-owned model/inference-profile ID and region. Global and ARN inference profiles remain rejected. A geographic profile such as `us.` is accepted only when its exact prefix is explicitly approved. Bedrock ignores ambient endpoint overrides, disables SDK proxies and accepts only resolved AWS HTTPS endpoints. Hosted adapters use bounded request/response bytes, fixed timeout, TLS 1.2+, no redirects/proxy, header authentication and no tool support.

Internal trace persists model ID/region/protocol, stable prompt fingerprint/version, token usage, actual call count/budget and measured provider/total latency; `estimated_cost_usd` stays null. Student-triggered jobs may consume provider quota, but pricing, chargeback and billing are intentionally outside this feature. Admin UI must disclose max tokens/call, call budget/job, up to three durable job attempts and unknown cost before activation.

Official contracts used for adapters:

- OpenAI API authentication and model listing: <https://developers.openai.com/api/reference/overview>
- Anthropic API authentication, Messages and model listing: <https://platform.claude.com/docs/en/api/overview>
- Gemini API keys and model listing: <https://ai.google.dev/gemini-api/docs/api-key>
- DeepSeek OpenAI-compatible API: <https://api-docs.deepseek.com/>
- OpenCode Console models, endpoints and inference API: <https://opencode.ai/docs/zen/>, <https://opencode.ai/v2/docs/console/inference>

## 7. Scoring and quality gate

Evaluable weights:

- `SUPPORTED = 1.0`
- `PARTIALLY_SUPPORTED = 0.5`
- `CONTRADICTED = 0.0`
- `IRRELEVANT = 0.0`

Excluded from denominator:

- `SOURCE_UNAVAILABLE`
- `INSUFFICIENT_EVIDENCE`
- `AMBIGUOUS_CLAIM`
- `NEEDS_MANUAL_REVIEW`

`semantic_support_score = 100 * sum(weights) / evaluable_claim_count`

`semantic_coverage = evaluable_claim_count / eligible_linked_claim_count`

Findings remain visible below threshold. Automatic proposed score requires all:

- at least 100 human-gold claim/source pairs;
- at least 20% independently double-annotated;
- claim-anchor and source-anchor completeness 100%;
- no snippet-derived verdicts and no contradiction from unavailable source;
- structured-output success at least 99%;
- verdict macro-F1 at least 0.80;
- `CONTRADICTED`/`IRRELEVANT` false-accusation rate at most 2%;
- evidence Hit@3 at least 0.90;
- configured coverage threshold met;
- domain reviewer approval recorded.

Current repository has no human semantic gold set. Gate therefore remains blocked and no automatic semantic score is produced.

The checked-in `semantic_citation_annotations.v0.json` contains 120
`AI_DRAFT`/synthetic annotation candidates and 128 explicit expected
claim-reference pairs, including 8 candidates with two citation pairs each.
It includes 30 candidates flagged for future double review. `human_gold_pairs=0`;
a flag is not a completed independent annotation. The reproducible baseline is
[`docs/benchmarks/citation-semantic-v1.md`](../../benchmarks/citation-semantic-v1.md).

`backend/tests/fixtures/semantic_citation_annotations.v1.json` (owner decision 2026-10-17: synthetic data is acceptable for evaluation) holds 583 `AI_CONSENSUS` claim/source pairs over 147 CC-licensed arXiv papers: claims generated by Gemini from production Source IR passages plus 12 sentences of the project owner's paper, labels kept only when every judge agreed (7 judges from 7 model families, at least two families per pair), Dual Split dev/test. `human_gold_pairs=0`, so it never satisfies the human-gold criteria above; the production gate stays blocked. `backend/scripts/semantic_citation_v1_benchmark.py` runs production retrieval and `evaluate_claim` on it and checks an AI-consensus benchmark gate (the criteria above minus the human-gold ones, plus at least 800 pairs). Results on 2026-10-18 ([report](../../benchmarks/citation-semantic-v1-ai-consensus.md), [dataset card](../../benchmarks/citation-semantic-v1-dataset.md)): evidence Hit@3 BM25 70.8% (Vietnamese 52.1%), `bge-m3` + reranker 95.0% (Vietnamese 95.9%); prompt v2 with `gemini-3.1-flash-lite` on 200 test pairs (BM25, free tier, 42 lost to HTTP 429): macro-F1 0.555, structured output 99.4%, false accusation 4.0%, 43 of its 54 errors are `INSUFFICIENT_EVIDENCE` answers; stage 3 shows BM25 misses the evidence passage for about half the Vietnamese claims, the likely cause (not yet measured per pair or with the encoder in stage 4). Prompt v1 on the 69-pair pilot: `IRRELEVANT` F1 0 and 17-29% invalid output.

## 8. Teacher and Student behavior

Teacher workspace shows score/coverage separately, gate state, each claim/verdict, source access type, source passage anchors, reason code, and manual-review flag. Existing `ACCEPT`, `EDIT`, and `REJECT` decisions apply to every semantic Finding. `EDIT` can change feedback, score, and a structured semantic verdict; a semantic verdict or score override requires a reason and is recorded separately from the model output in audit/published internal snapshots.

Student sees only published accepted findings under existing publication policy. Raw retrieval/model confidence, prompts, model details, internal scores, and rejected findings remain hidden.

Admin alone can list provider configuration, import/replace/remove credentials, verify catalog access, edit a route draft, activate/deactivate routing and see safe provider status. Teacher and Student receive no provider list, source, hint, status, model, route or technical failure metadata. The UI uses `Manual review only`, `Draft` and `Active` as route states; it never labels catalog access as generation health. Disabling routing affects new jobs; disabling or rotating the credential also prevents queued/retried snapshots from calling the old credential.

The Admin dashboard also shows the semantic retrieval mode (`Encoder + reranker`, `Encoder` or `Keyword search only (BM25)`, from settings) and how many finished jobs in the last 7 days recorded encoder failures in their trace, with the latest failure time. Without an encoder, or with failures, it warns that claims written in another language than the source match passages poorly. The counts come from stored job traces, not a live probe.

## 9. Benchmark

Stage-wise script consumes a versioned fixture manifest and reports:

1. extraction precision/recall/F1 and scope attribution accuracy;
2. source-resolution precision, full-text coverage, abstract-only and unavailable rates;
3. Hit@3, Recall@3, MRR@3, and evidence-anchor accuracy;
4. verdict accuracy, macro-F1, per-class metrics, confusion matrix, false-accusation rate;
5. end-to-end accuracy, Teacher acceptance/override fields when supplied, latency, calls, tokens, and estimated/recorded cost.

Fixtures must declare annotation provenance. AI-draft/synthetic cases can test software but do not count toward activation gate. No benchmark report may call evaluator accurate before human review.

## 10. Security and failure invariants

- Report/source text is untrusted data, never instruction.
- No report-supplied URL fetch, search snippet evidence, paywall bypass, tool call, or open-domain completion; provider-listed open-access URLs go only through the public-HTTPS fetcher.
- All text/counts/passages/model output are bounded; Source IR construction stops at 192 passages; arXiv metadata fan-out is bounded and misses are negative-cached.
- Source identity mismatch or mixed-identifier disagreement cannot reach model.
- `SOURCE_UNAVAILABLE` cannot become contradiction or irrelevant.
- Invalid output retries once, then manual review.
- Existing identity/linkage findings and counts stay independent.
- Provider exceptions are sanitized; document content and prompts are not logged.
- Reproducibility trace stores only versions, hashes, IDs, counters, token usage and latency; report-level source metadata omits full passage corpora.

## 11. Primary external references

- [arXiv API Terms of Use](https://info.arxiv.org/help/api/tou.html)
- [arXiv API User's Manual](https://info.arxiv.org/help/api/user-manual.html)
- [AWS Bedrock DeepSeek model cards](https://docs.aws.amazon.com/bedrock/latest/userguide/model-cards-deepseek.html)
- [AWS Bedrock DeepSeek model parameters](https://docs.aws.amazon.com/bedrock/latest/userguide/model-parameters-deepseek.html)
- [BGE-M3 documentation](https://bge-model.com/bge/bge_m3.html)
- [OpenAlex authentication, rate limits and costs](https://help.openalex.org/api/authentication/)
- [Text Embeddings Inference](https://github.com/huggingface/text-embeddings-inference)
