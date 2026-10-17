# arXiv source acquisition smoke report

Date: 2026-09-24

## Decision

Superseded on 2026-10-17: two automatic acquisition lanes now ship, both disabled by default (`SEMANTIC_SOURCE_FETCH_ENABLED`) and both requiring a `VERIFIED` reference and a private cache prefix. The arXiv lane (this smoke report) takes arXiv-only references with an exact `vN`. The OpenAlex lane takes references with a DOI and downloads open-access PDFs through `fetch_public_https`. Everything else remains operator-cache-only. See [`design §5`](../superpowers/specs/2026-09-24-semantic-citation-support-design.md).

Original 2026-09-24 decision: automatic source acquisition is arXiv-only and disabled by default; DOI and every non-arXiv source remain operator-cache-only.

## Live papers

| arXiv ID | Paper | PDF bytes | SHA-256 | Parsed passages | Result |
|---|---|---:|---|---:|---|
| `1810.04805v2` | BERT: Pre-training of Deep Bidirectional Transformers for Language Understanding | 775,166 | `5692a5514787a8c6727b4ff3b726a3385798bc68e12138d1d4af83947e2acf6e` | 192 | Downloaded, validated, identity-confirmed, cached |
| `1412.6980v9` | Adam: A Method for Stochastic Optimization | 584,641 | `eab9c73ae2ceda884b94830bda99312254bac4806f6c9f045cbab90721ecda31` | 192 | Downloaded, validated, identity-confirmed, cached |

Cache-miss provenance was `arxiv_oa_download`. Second resolution returned `arxiv_oa_cache` with identical hashes and passage counts. BM25 top-three output contained claim-relevant passages for both queries.

Live arXiv Atom probe resolved versioned records `1810.04805v2` and `1412.6980v9`, mapped unversioned requested IDs to exact revisions, and reported publication years 2018 and 2014. Public API intermittently returned HTTP 406 for multi-ID requests. Adapter selects at most 16 arXiv-only references/job, tries one batch plus at most four unresolved single-ID requests under three-second process pacing, and negative-caches misses for five minutes.

## Fail-closed case

`1706.03762` (Attention Is All You Need) downloaded successfully but existing untrusted-PDF validator returned `PDF_SCAN_LIMIT`. Source was rejected and not cached. No paper-specific bypass was added. This compatibility limit remains preferable to weakening active-content bounds.

Production semantic parsing skips table discovery after security validation. BERT and Adam previously hit table `PDF_STRUCTURE_LIMIT`; text-only retrieval needs prose, not structured table reconstruction. Table glyph text remains in bounded page/paragraph extraction.

Follow-up 2026-10-12: with pdfplumber's fixed 3 pt word gap, justified LaTeX papers produced glued passages (`1503.02531v1`: `Manyinsectshavealarvalform...`; 114–167 tokens over 18 characters in the first four pages of each of four arXiv papers). Source parsing now uses a word gap of 15% of glyph size, leaving 1–6 such tokens per paper. Student Document IR is unchanged; see #47.

## Security boundary

- Metadata: fixed `https://export.arxiv.org/api/query` endpoint; canonical IDs only; redirects denied; 2 MB response bound; XML parser; bounded request fan-out, negative/process cache.
- PDF: fixed `https://arxiv.org/pdf/<exact-version-id>` endpoint; no redirects; 15-second timeout; declared and actual size bounds; accepted PDF/octet-stream content types; `%PDF-` magic required.
- Parse: normal page, decoded-byte, active-content, and structure security validation before source use.
- Identity: DOI or arXiv ID in front matter, otherwise bounded title plus author match. A mixed DOI+arXiv reference cannot pass from arXiv ID alone.
- Storage: exact `vN` private S3 key/write only after validation; failed write denies source; no user download route.
- Licensing/operations: arXiv metadata is CC0. Paper PDFs retain paper-specific rights; cache is private analysis infrastructure. Configure lifecycle retention and review licensing before redistribution. Process-local pacing requires shared outbound proxy/egress control to enforce aggregate arXiv rate across workers/replicas.

## Configuration

```dotenv
SEMANTIC_SOURCE_CACHE_PREFIX=semantic-sources
SEMANTIC_SOURCE_FETCH_ENABLED=true
```

Both controls are server-owned. Default remains `SEMANTIC_SOURCE_FETCH_ENABLED=false`.

## Primary references

- [arXiv API Terms of Use](https://info.arxiv.org/help/api/tou.html)
- [arXiv API User's Manual](https://info.arxiv.org/help/api/user-manual.html)
