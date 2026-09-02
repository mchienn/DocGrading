# T-010 Document IR & PDF Parser Core Design

**Date:** 2026-09-02

**Status:** Approved design, pending implementation plan

**Baseline:** `main` at `59a3a7ab3e855caafc98b44e2ce3185c26400708`. Work remains backend-only and does not depend on an unmerged T-009 branch.

## 1. Goal

Validate and parse each accepted, text-native PDF once into a durable Document IR shared by every evaluator. The IR preserves page text, headings and nested sections, paragraphs, tables including page-spanning tables, and verifiable page coordinates.

A forced rebuild for the same `DocumentVersion` replaces the existing IR atomically. Normal processing reuses the existing IR without parsing the PDF again.

## 2. Scope

Included:

- reuse `app.services.pdf_validation.validate_pdf` as the first parser step;
- extract page text and top-left page coordinates;
- infer headings, nested section ownership, and paragraphs;
- extract ruled or text-aligned tables and join compatible page fragments;
- persist one versioned IR payload per `DocumentVersion`;
- integrate IR creation into the analysis worker before job completion;
- enforce bounded structure traversal and sanitized parser failures;
- test functional edge cases, idempotency, locking, and untrusted-PDF limits;
- add a reversible PostgreSQL migration following SC-1/2/3.

Excluded:

- frontend and evidence-navigation APIs;
- evaluator-specific requirement/use-case classification;
- OCR and scanned-PDF support;
- semantic or ML-based layout inference;
- evaluation findings, scoring, LLM calls, and review results;
- normalized page/section/cell tables until measured query needs justify them.

## 3. Selected approach

### 3.1 One relational owner row with a versioned JSONB payload

Create `public.document_irs` with:

- UUID `id` primary key;
- UUID `document_version_id`, non-null, unique, foreign key to `public.document_versions.id`;
- positive integer `schema_version`;
- non-blank bounded string `parser_version`;
- JSONB object `content`;
- timezone-aware `created_at` and `updated_at`.

Database constraints enforce one IR per document version, positive schema version, non-blank parser version, and object-shaped JSONB. `DocumentVersion.document_ir` is a one-to-one ORM relationship.

This keeps replacement atomic and eliminates orphaned child rows during rebuild. Evaluators load one stable payload. Page/section/cell normalization is deferred because current consumers need the complete IR, not independent SQL analytics over every block.

### 3.2 Rejected alternatives

1. Separate page, section, paragraph, table, row, and cell tables: stronger independent SQL querying, but substantially more DDL, cascade behavior, locking, and duplicate-cleanup paths without a current consumer.
2. Store IR in object storage and retain only a database pointer: weakens transactional replacement and makes evaluator reads depend on two persistence systems.
3. Use only pypdf callbacks: already installed, but canonical architecture selects `pypdf + pdfplumber`; pdfplumber provides stable word and table bounding boxes without a custom table engine.

## 4. Document IR contract

`content` is a JSON object with deterministic ordering and these top-level fields:

```json
{
  "schema_version": 1,
  "source": {
    "sha256": "0000000000000000000000000000000000000000000000000000000000000000",
    "size_bytes": 1234,
    "page_count": 2
  },
  "pages": [],
  "sections": [],
  "paragraphs": [],
  "tables": []
}
```

### 4.1 Coordinates

All bounding boxes use pdfplumber's top-left page coordinate system in PDF points:

```json
{"x0": 72.0, "top": 96.0, "x1": 310.5, "bottom": 110.0}
```

Every coordinate-bearing object also stores a one-based `page_number`. Values are finite, rounded consistently, ordered as `0 <= x0 <= x1 <= page.width` and `0 <= top <= bottom <= page.height`.

### 4.2 Pages

Each page stores:

- `number`, `width`, `height`;
- reading-order `text` reconstructed from accepted lines;
- ordered IDs of headings, paragraphs, and table regions on that page.

An accepted blank page remains present with empty text and block IDs.

### 4.3 Sections and headings

Each detected heading stores:

- deterministic ID;
- heading text;
- positive nesting `level`;
- nullable `parent_id`;
- page number and bounding box.

Detection order:

1. numbered headings such as `1`, `1.2`, or `1.2.3` derive level from numbering depth;
2. short typography outliers derive level from ranked font size and boldness;
3. ordinary prose is never promoted solely because it starts with a capital letter.

A stack assigns each heading to the closest preceding lower-level parent. Missing intermediate levels attach to the closest available lower level; no synthetic sections are created. A document with no headings has `sections: []`; its paragraphs have `section_id: null`.

### 4.4 Paragraphs

Words are grouped into lines by vertical tolerance and sorted left-to-right. Adjacent non-heading, non-table lines become one paragraph when alignment and vertical-gap tolerances match. Each paragraph stores deterministic ID, text, nullable section ID, page number, and union bounding box.

Paragraphs never span pages. Page boundaries remain explicit evidence boundaries.

### 4.5 Tables

Use `pdfplumber.Page.find_tables()` and each table's cell geometry. A page table region stores page number, bounding box, rows, cell text, and cell bounding boxes. Missing cells remain explicit null values so column positions do not shift.

Two table regions on consecutive pages form one logical table only when:

- normalized column boundaries and column count match within a fixed tolerance;
- previous region reaches the lower page continuation zone;
- next region begins in the upper page continuation zone;
- optional repeated header rows are equal after whitespace normalization.

The logical table stores ordered regions rather than fabricating one cross-page bounding box. Uncertain regions remain separate tables; false merging is worse than under-merging.

## 5. Parse flow

`parse_document_ir(data, limits)` is pure and synchronous:

1. call `validate_pdf(data, max_size_bytes, max_page_count)`;
2. only after validation succeeds, open the same bytes with pdfplumber;
3. traverse pages and layout nodes under one shared node budget;
4. extract words, lines, headings, paragraphs, and tables;
5. validate the in-memory IR contract;
6. return validation metadata plus the JSON-compatible payload.

The worker runs CPU-bound parsing in `asyncio.to_thread`. It does not log PDF bytes, extracted text, object keys, or parser internals that may contain document data.

## 6. Bounded untrusted-data handling

Add a positive `pdf_ir_max_nodes` setting. One shared budget counts every visited or emitted page, layout object, word, line, heading, paragraph, table, region, row, and cell. Exceeding the budget raises `PDF_STRUCTURE_LIMIT` before further traversal.

Additional invariants:

- no recursion over PDF objects is added;
- section-stack depth is bounded by the same node budget;
- non-finite or out-of-page coordinates are rejected;
- table dimensions are checked before iterating cells;
- only text/layout/table extraction APIs are used;
- JavaScript, launch actions, forms, attachments, URLs, and embedded files are never executed or opened;
- existing `validate_pdf` active-content, decoded-size, page-count, encryption, and scan-only checks remain authoritative.

`PDFValidationError` and `PDF_STRUCTURE_LIMIT` mark the document invalid with stable, non-sensitive details. Unexpected extractor/storage failures mark processing failed with sanitized details and no PDF content.

## 7. Persistence and concurrency

`get_or_build_document_ir(db, document_version_id, data, rebuild=False)` owns the write contract:

1. select the target `DocumentVersion` using `.with_for_update()`;
2. read its one-to-one `DocumentIR` while the document row is locked;
3. return the existing row immediately when present and `rebuild` is false;
4. otherwise parse exactly once while retaining the document-version lock;
5. verify parser SHA-256 against the declared/current document digest and preserve existing duplicate-document checks;
6. insert the first row or replace `schema_version`, `parser_version`, and `content` on the existing row;
7. flush in the caller's transaction.

The unique constraint is the final defense, not the primary concurrency mechanism. Concurrent normal builds serialize on `DocumentVersion`; the second caller reuses the first row. Forced rebuild updates the same row and leaves row count and identity stable.

Holding the document lock during parsing is intentional. PDF work already runs in a background worker with a separate heartbeat session; strict one-parse behavior is more important than maximizing concurrent mutations of one document version.

## 8. Worker integration

Replace the worker's standalone validation-only success path with the build-or-reuse operation. The parser itself still invokes `validate_pdf` first. On success:

- use IR source metadata to update `DocumentVersion.sha256`, `size_bytes`, and `page_count`;
- preserve checksum and duplicate-document rejection;
- persist IR and call the existing fenced `mark_done` in the same transaction;
- a superseded job attempt rolls back pending IR changes and cannot mark the job done.

Queue delivery, job claim, heartbeat, attempt fencing, status transitions, and dispatch-outbox behavior remain unchanged.

## 9. Migration security checklist

This checklist is a hard gate before creating migration `20260902_0008`.

- [ ] **SC-1 — pin `search_path`:** `upgrade()` and `downgrade()` begin with `SET search_path TO public`; no unpinned function or trigger is introduced.
- [ ] **SC-2 — preserve append-only TRUNCATE protection:** migration never disables, replaces, bypasses, truncates, or drops `public.audit_events`, `public.trg_audit_events_append_only`, or `public.trg_audit_events_append_only_truncate`; real-PostgreSQL upgrade/downgrade verification proves `TRUNCATE public.audit_events` remains rejected.
- [ ] **SC-3 — schema-qualify DDL and FK references:** every Alembic table/index/constraint operation passes `schema="public"`; every FK target uses `public.<table>.<column>`; raw SQL qualifies every application table, index, function, cast, and type.
- [ ] Upgrade creates only `public.document_irs` and its named constraints/indexes; it does not rewrite existing document/job rows.
- [ ] Downgrade drops only Document IR objects and refuses no unrelated application state.
- [ ] Upgrade, downgrade to revision `20260829_0007`, and re-upgrade run against PostgreSQL 17.

## 10. Tests

### Functional Correctness

- no-heading PDF yields pages and paragraphs with no synthetic section;
- numeric headings with several levels produce correct parent chains, including skipped levels;
- table fragments spanning consecutive pages become one logical table with page-specific regions and stable cell coordinates;
- ordinary prose is not misclassified as headings;
- malformed/out-of-page coordinates fail closed.

### Data Integrity & Integration

- first build creates one `DocumentIR`;
- normal replay returns the same row without invoking parser again;
- forced rebuild updates the same row and replaces old content completely;
- two independent PostgreSQL sessions building the same version serialize through `FOR UPDATE` and leave one row;
- worker retry/redelivery produces no duplicate IR;
- superseded job attempt cannot commit IR or terminal job state;
- model metadata and migration schema remain aligned.

### Security & Privacy

- parser entrypoint proves `validate_pdf` runs before pdfplumber opens bytes;
- node-budget exhaustion raises `PDF_STRUCTURE_LIMIT` without continuing traversal;
- JavaScript/embedded-file PDFs are rejected by existing validation and never reach layout extraction;
- parser errors and logs contain no extracted text, bytes, signed fields, credentials, or storage URLs;
- migration preserves append-only audit UPDATE/DELETE/TRUNCATE guards.

## 11. Verification

From `backend/`:

```text
uv run ruff check .
uv run black --check .
uv run pytest -v
```

With isolated PostgreSQL 17 and database tests enabled:

```text
uv run alembic upgrade head
uv run alembic downgrade 20260829_0007
uv run alembic upgrade head
```

Run the real-PostgreSQL concurrency and migration-roundtrip tests. Final report includes separate confirmations for Functional Correctness, Data Integrity & Integration, and Security & Privacy.

## 12. Documentation impact

After integrated verification, update canonical backend architecture/technology wording only if actual IR schema, coordinate convention, parser dependency, or worker lifecycle differs from `docs/design/PROJECT_SCOPE_BUSINESS_RULES_TECH_STACK.md`. No frontend contract changes are part of T-010.
