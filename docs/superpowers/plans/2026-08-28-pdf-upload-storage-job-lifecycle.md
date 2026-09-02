# T-009 PDF Upload, Storage & Job Lifecycle Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:test-driven-development` while implementing each task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deliver backend-only PDF upload through a short-lived, object-scoped S3-compatible presigned POST; validate the received object as untrusted data; create one idempotent `AnalysisJob`; and enforce audited, race-safe `QUEUED → RUNNING → DONE/ERROR` transitions.

**Architecture:** Use a two-step upload contract. The API creates or reuses an `UPLOADING` `DocumentVersion` using `Idempotency-Key`, returns a five-minute S3 presigned POST constrained to one random object key, `application/pdf`, and the accepted byte range, then a completion endpoint locks both the document and its Assignment before verifying metadata and queueing the job. Every committed `QUEUED` job owns a transactional PostgreSQL dispatch row; the API drains it after commit and a FastAPI lifespan poller recovers broker failures. Workers claim queued or lease-expired `RUNNING` jobs with `SELECT ... FOR UPDATE SKIP LOCKED`, maintain a heartbeat, and fence every heartbeat/terminal write by the claimed `attempt_count` generation before transitioning the same job row. A specific-job redelivery received before lease expiry uses an unbounded Celery retry delayed until the remaining lease elapses, ensuring stale recovery remains reachable. Retries and worker-loss recovery reset that row rather than creating a new `Submission`, `DocumentVersion`, job, or future result.

**Tech Stack:** Python 3.13, FastAPI, Pydantic 2, SQLAlchemy 2 async, PostgreSQL 17, Alembic, Celery 5.6, Redis 7, Boto3/S3-compatible storage, pypdf 6.x, Docker Compose, pytest, Ruff, Black.

---

## Scope and selected approach

### Selected: presigned POST plus explicit completion

- `POST /api/v1/assignments/{assignment_id}/uploads/presign` requires `Idempotency-Key` and the client-declared SHA-256, plus bounded hints `filename`, `content_type`, and `size_bytes`; the worker recomputes and verifies the digest from stored bytes.
- The policy fixes the exact random object key, fixes `Content-Type=application/pdf`, applies `content-length-range`, and expires after 300 seconds.
- `POST /api/v1/document-versions/{version_id}/complete` locks the `DocumentVersion` and Assignment together. The first completion is accepted only while the Assignment is `OPEN` and its optional deadline has not passed; an already completed document remains idempotently readable afterward. It performs `HeadObject`, rejects server-observed content type/size mismatches, marks the document queued, and creates/reuses exactly one job plus one dispatch outbox row in the same transaction. After commit the API makes a bounded Celery publish attempt; the lifespan poller retains and retries failed dispatches without changing the accepted response. A transient `HeadObject` failure commits sanitized `PROCESSING_FAILED/STORAGE_UNAVAILABLE`; the same no-job document can retry completion without re-upload or a renewed presigned window while the Assignment gate still passes.
- The worker downloads at most the configured limit, verifies `%PDF-`, SHA-256, encryption, page count, active content/attachments, and a usable text layer. Total decoded page content shares one configured byte budget and is checked before each page's text extraction. pypdf never executes PDF JavaScript; malformed/parser failures become explicit validation errors.

### Alternatives rejected

1. **Presigned PUT:** simpler client request, but it cannot enforce `content-length-range` as directly as a signed POST policy. Server verification would still be mandatory.
2. **Proxy the PDF through FastAPI:** simpler local development, but it violates the direct object-storage upload requirement and ties web worker memory/latency to a 50 MB upload.
3. **Create a new job row on every retry:** preserves attempt history but makes queue redelivery/result idempotency harder. T-009 keeps one job row and records every transition in append-only `AuditEvent` instead.

## Contract decisions and documentation reconciliation

- T-009 superseded the old `multipart/form-data` wording in `docs/design/PROJECT_SCOPE_BUSINESS_RULES_TECH_STACK.md` §9.4.2; canonical documentation now specifies the validated two-step presigned POST contract.
- `AnalysisJobStatus.SUCCEEDED/FAILED` is cleanly renamed to `DONE/ERROR`; no aliases or compatibility enum values remain. Migration 0006 marks legacy `CANCELLED` rows with a collision-checked, migration-reserved snapshot sentinel so downgrade restores only those rows to `CANCELLED`; ordinary `ERROR` rows downgrade to `FAILED`.
- `DocumentVersion.status` remains the document lifecycle. Claiming a job sets it to `PROCESSING`; successful ingestion sets it to `AWAITING_REVIEW`; both changes and the job transition are audited in one transaction. Job `DONE` means the T-009 ingestion/validation job completed; T-009 does not fabricate `EvaluationResult` rows because that model/pipeline is not implemented yet.
- Admin may view every job. Teacher may view/retry only jobs under a Course they own. Student may view only their own job and cannot retry. Role checks evaluate `ADMIN`, then `TEACHER`, then `STUDENT`, so a multi-role account never falls through from a stronger denied/allowed branch into Student ownership semantics.
- Only an active Student member may initiate their own upload for an `OPEN`, non-expired Assignment while attempts remain. The same Assignment state/deadline gate is rechecked under the completion lock, except an already completed document preserves its idempotent response.

## Migration Security Checklist

This checklist is a hard gate before creating migration `20260828_0006`.

- [x] **SC-1 — pin `search_path`:** `upgrade()` and `downgrade()` begin with `SET search_path TO public`; any new PL/pgSQL function uses `SET search_path = pg_catalog, public, pg_temp`.
- [x] **SC-2 — preserve append-only audit protection:** migration 0006 does not disable, replace, or bypass `public.trg_audit_events_append_only` or `public.trg_audit_events_append_only_truncate`; real-PostgreSQL verification proves `TRUNCATE public.audit_events` is still rejected after upgrade and downgrade/upgrade.
- [x] **SC-3 — schema-qualify all DDL/FK references:** every Alembic table/index/constraint operation passes `schema="public"`; every FK target is `public.<table>.<column>`; raw SQL qualifies tables, indexes, enum types, casts, and functions with `public.`.
- [x] Enum value migration is reversible: `SUCCEEDED → DONE` and `FAILED → ERROR` on upgrade; a collision-checked reserved snapshot sentinel maps legacy `CANCELLED → ERROR → CANCELLED`, while ordinary `ERROR` rows downgrade to `FAILED`.
- [x] Replace `uq_analysis_jobs_active_document_rubric` with a full unique constraint on `(document_version_id, rubric_version_id)` so one logical analysis owns one durable job row across retries.
- [x] Add and downgrade the upload idempotency fields/index without dropping or truncating append-only tables.
- [x] **Production preflight:** before upgrading a populated database, query `public.analysis_jobs` grouped by `(document_version_id, rubric_version_id)` and require zero groups with `count(*) > 1`. If historical terminal duplicates exist under the old partial index, stop for audited reconciliation; migration 0006 deliberately never deletes job history to force the new unique constraint.
- [x] **Migration 0007 dispatch safety:** upgrade locks `public.analysis_jobs`, installs a schema-pinned compatibility trigger, and backfills one dispatch for every existing `QUEUED` job. Before downgrading below `20260829_0007`, quiesce the application, lock both tables in order, and require zero rows in `public.analysis_job_dispatches`; drain or explicitly reconcile pending rows because the migration refuses to discard them.

## Requirements traceability

| Requirement | Implementation / verification |
| --- | --- |
| Short-lived, one-object presigned upload | `S3Storage.create_presigned_post`; exact key, MIME and size conditions; 300-second expiry tests |
| Client-hint and server-side verification | Request schema bounds plus `HeadObject` and bounded `GetObject` validation |
| PDF size / magic / scan-only errors | Stable error codes `PDF_TOO_LARGE`, `PDF_DECODED_TOO_LARGE`, `NOT_A_PDF`, `PDF_SCAN_ONLY`; BR-07 recursively measures visible raster placements against crop, Form, and supported content clipping, and fails unsupported applied clipping closed as `PDF_MALFORMED`; raw/decoded-size and scan-geometry regression tests |
| Treat PDF as untrusted | Current pinned pypdf, strict parsing, raw-byte/total-decoded/page-count limits, no execution, active-content/attachment rejection |
| Idempotent job creation/retry | Full DB uniqueness, locked create/retry, same-row transition tests |
| Race-safe pickup and worker-loss recovery | PostgreSQL `FOR UPDATE SKIP LOCKED`, locked-status re-check, lease/heartbeat recovery, delayed Celery retry for redelivery during an active lease, `attempt_count` compare-and-set fencing for heartbeat/terminal writes, and committed-`RUNNING` split-brain integration tests |
| Durable queue wake-up | Transactional `AnalysisJobDispatch`, migration backfill/guard, bounded post-commit drain, one-second FastAPI lifespan poller, backoff, and concurrent `SKIP LOCKED` publisher tests |
| Audited job/document lifecycle | `record_system_audit`/`record_audit` in the same transaction as job transitions and document `PROCESSING`/`AWAITING_REVIEW` changes |
| Cross-object authorization | Admin/Teacher/Student precedence and other-user denial tests |
| Retry creates no duplicate data | Submission/DocumentVersion/job row counts remain stable after `ERROR → QUEUED → RUNNING → DONE` |
| DevOps | LocalStack 4.11.1 S3 service/bucket bootstrap, API/worker storage settings, Compose config validation |

## File map

**Create**

- `backend/app/services/storage.py` — S3-compatible client boundary and typed presign/head/get/delete results.
- `backend/app/services/pdf_validation.py` — pure, bounded PDF validation and stable error codes.
- `backend/app/services/submission.py` — upload initiation/completion, assignment/member checks, upload idempotency.
- `backend/app/services/analysis_job.py` — create/reuse, claim, complete, fail, retry, authorization, audit.
- `backend/app/api/schemas_submission.py` — upload/job request and response models.
- `backend/app/api/routers/submissions.py` — presign, completion, job detail, retry endpoints.
- `backend/alembic/versions/20260828_0006_pdf_upload_job_lifecycle.py` — enum/idempotency/job-uniqueness migration.
- `backend/tests/test_t009_contracts.py`, `backend/tests/test_t009_pdf_behavior.py` — storage, parser, upload, worker, retry, authorization, and role-precedence behavior.
- `backend/tests/test_t009_job_concurrency.py` — real-PostgreSQL two-worker locking contract.

**Modify**

- `backend/app/core/config.py` — bucket, internal/public endpoints, region, credentials, expiry and validation limits.
- `backend/app/models/enums.py` — `AnalysisJobStatus.DONE/ERROR` clean cutover.
- `backend/app/models/submission.py` — upload idempotency key and expiry fields/index.
- `backend/app/models/analysis.py` — full logical-job uniqueness and terminal-state constraints.
- `backend/app/models/__init__.py` — retain complete model exports.
- `backend/app/workers/tasks.py` — claim one job, validate object, and settle status.
- `backend/app/workers/celery_app.py` — late acknowledgement/reject-on-worker-loss settings for idempotent work.
- `backend/app/main.py` — register backend-only submission/job router.
- `backend/pyproject.toml`, `backend/uv.lock` — pin current Boto3 and pypdf major ranges.
- `.env.example`, `docker-compose.yml`, `backend/Dockerfile` — S3-compatible storage settings/service; remove obsolete shared PDF volume.
- `docs/design/PROJECT_SCOPE_BUSINESS_RULES_TECH_STACK.md` — reconcile multipart/status wording after behavior passes.

## Task 1: Lock database and status invariants

- [x] Add failing model/migration tests for `DONE/ERROR`, one job per document/rubric across every status, upload idempotency fields, and legal terminal timestamps.
- [x] Run the focused tests and record the expected failures against revision 0005.
- [x] Implement model enum/constraint changes.
- [x] Create migration 0006 only after checking every SC-1/2/3 item above in the migration docstring and code.
- [x] Upgrade a real PostgreSQL database and prove schema/model alignment plus the surviving audit TRUNCATE guard.

## Task 2: Implement storage and PDF validation boundaries

- [x] Add failing tests for a 300-second presigned POST whose policy fixes one key, PDF MIME, and accepted size range.
- [x] Add failing tests for server-observed MIME/size mismatch and bounded object reads.
- [x] Add failing pure tests for valid text PDF plus `PDF_TOO_LARGE`, `NOT_A_PDF`, `PDF_SCAN_ONLY`, encrypted, over-page-limit, malformed, JavaScript, and attachment cases.
- [x] Implement `S3Storage` with separate internal and browser-reachable clients; never log credentials, URLs, form fields, or PDF content.
- [x] Implement `validate_pdf` with `%PDF-`, strict pypdf parsing, configured byte/page bounds, SHA-256, encryption/active-content/attachment rejection, and useful-text detection.
- [x] Run focused storage/PDF tests until green.

## Task 3: Implement idempotent upload API

- [x] Add failing tests for active Student membership, `OPEN`/deadline/attempt limits, required `Idempotency-Key`, same-key/same-payload replay, same-key/different-payload conflict, and duplicate SHA reuse.
- [x] Add failing tests proving client-declared MIME/size are only hints and completion trusts server-observed object metadata/bytes.
- [x] Implement initiation under a transaction/row lock; create no duplicate `Submission` or `DocumentVersion` under retry.
- [x] Implement completion as idempotent: lock the document and Assignment together; accept first completion only while the Assignment is `OPEN` and not past its optional deadline; already queued/processed returns the existing job even after later closure/deadline; first completion creates/reuses the single job and its unique dispatch row in the same transaction, then makes a bounded post-commit publish attempt. Persist transient storage failure before 503 and allow only that `STORAGE_UNAVAILABLE`/no-job state to retry completion without re-upload or presign-expiry rejection.
- [x] Register the router without changing `frontend/`.
- [x] Run focused upload API/service tests until green.

## Task 4: Implement race-safe audited job lifecycle

- [x] Add real-PostgreSQL tests using independent sessions: prove exactly one `SKIP LOCKED` claim wins, then commit a `RUNNING` claim, simulate worker loss with an expired heartbeat, and prove the same row is reclaimed or exhausted with audit evidence.
- [x] Implement the exact pickup query ordered by `(queued_at, id)` with `.with_for_update(skip_locked=True).limit(1)`.
- [x] Re-check the locked job as `QUEUED` or lease-expired `RUNNING`; maintain heartbeat updates while work is active, requeue stale work only while attempts remain, and terminally fail exhausted stale work.
- [x] Fence heartbeat, `DONE`, and `ERROR` writes by the claimed `attempt_count`; a superseded attempt rolls back pending document mutations and cannot refresh or settle the newer attempt.
- [x] Record job `QUEUED`, `RUNNING`, `DONE`, `ERROR`, and `ERROR → QUEUED` transitions atomically; set and audit the linked document as `PROCESSING` on claim and `AWAITING_REVIEW` on success in those same transactions.
- [x] Configure Celery late acknowledgement and worker-loss rejection; a specific-job redelivery during an active lease retries after the remaining lease instead of being acknowledged away, and duplicate deliveries remain safe because locked status, leases, attempt-generation fencing, attempt limits, and DB uniqueness are authoritative.
- [x] Run focused lifecycle, recovery, and concurrency tests until green.

## Task 5: Enforce role precedence and safe retry

- [x] Add tests for Admin viewing/retrying any job, owning Teacher viewing/retrying course jobs, Student viewing only their own job, and other-user access returning 404.
- [x] Add a dedicated multi-role test proving `ADMIN`/`TEACHER` is evaluated before `STUDENT` and an owning Teacher+Student may view another Student's job in that Course.
- [x] Add a retry test proving `ERROR → QUEUED` mutates the same job/document objects, preserves attempt count until the next claim, and adds no new domain row; T-009 intentionally creates no evaluation-result model or row.
- [x] Implement retry on the locked existing row, enforce `max_attempts`, clear terminal error fields, create its unique dispatch row atomically, and attempt publish only after commit.
- [x] Run focused authorization/retry tests until green.

## Task 6: Wire S3-compatible DevOps configuration

- [x] Add LocalStack 4.11.1 S3 service and one-shot idempotent bucket initialization with health-gated API/worker dependencies.
- [x] Expose storage only on loopback for local development; use separate internal and browser endpoint settings.
- [x] Remove the obsolete API/worker shared `pdf_storage` volume and `STORAGE_PATH` settings.
- [x] Keep credentials in `.env`; `.env.example` contains development-only placeholders, never real secrets. Settings reject known development placeholder storage credentials whenever `APP_ENV` is not `development`.
- [x] Run `docker compose config` and inspect the rendered dependency graph and volume declarations.

## Task 7: Integrated verification and documentation reconciliation

- [x] Run `uv run ruff check .` from `backend/`.
- [x] Run `uv run black --check .` from `backend/`.
- [x] Run `uv run pytest -v` from `backend/` with `RUN_DATABASE_TESTS=1`: 196 passed.
- [x] With isolated PostgreSQL 17 healthy, run `alembic upgrade head`, `alembic downgrade 20260828_0005`, and `alembic upgrade head`.
- [x] Run database tests and confirm the two-worker test has exactly one winner.
- [x] Run `docker compose config` and a real presigned POST/object HEAD smoke test.
- [x] Reconcile canonical upload and job status wording without expanding T-009 into frontend or evaluation-result implementation.
- [x] Independent scoped review completed after integration; its early-redelivery recovery finding was fixed with lease-aware delayed Celery retry, and re-review returned `NO_SCOPED_FINDINGS`.

## Required final review groups

### Functional Correctness

- Role precedence is `ADMIN → TEACHER → STUDENT` wherever job visibility/retry branches by role.
- A dedicated multi-role regression test covers the stronger branch.
- Stable failure codes distinguish size, MIME/magic, scan-only, encrypted, active-content/attachment, malformed, and page-limit failures.

### Data Integrity & Integration

- Pickup SQL renders `FOR UPDATE SKIP LOCKED` on PostgreSQL.
- Status is re-checked after the lock and before `RUNNING`.
- Two independent worker sessions produce one winner and one empty claim.
- Full logical-job uniqueness and same-row retry prevent duplicate jobs; upload idempotency prevents duplicate submission/document rows.

### Security & Privacy

- Presigned POST expires in 300 seconds and is scoped to one unpredictable key, exact PDF MIME, and bounded size.
- Client hints are checked early but never trusted; server `HeadObject`, bounded download, magic bytes, SHA-256, and parser validation are authoritative.
- PDF bytes/content and signed form fields are never logged. Parsing uses current pinned pypdf with strict/bounded behavior and no execution path.
- Migration 0006 satisfies SC-1/2/3 and preserves the append-only audit TRUNCATE guard.
