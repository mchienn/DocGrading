# T-009 Clipping and Durable Dispatch Hardening Design

## Status

Approved design for resolving the two blocking findings reported by CodeRabbit on PR #8 at commit `f993ec2204ef6211eeccc1e6613dcb22a27c887b`.

## Problems

### Unsupported PDF clipping bypasses BR-07

The raster-coverage walker represents an unsupported clipping path as `None`, and `_image_coverage()` interprets `None` as zero visible area. A compound non-zero-winding path, such as two rectangle subpaths whose union covers the page, can therefore hide a full-page raster placement from the scan-page rule.

### Job dispatch is not durable

Upload completion and job retry commit `AnalysisJob.status = QUEUED` before publishing a Celery message. A process or broker failure after the database commit can leave a durable queued job without any message that wakes a worker. Client retries reduce but do not eliminate that gap.

## Constraints

- PostgreSQL remains the authoritative state store.
- Celery tasks remain idempotent and may be delivered more than once.
- The MVP continues to use task/retry primitives without Celery Beat or canvas workflows.
- Upload completion remains HTTP 202 once the database transaction commits, even if Redis is temporarily unavailable.
- No broker, storage, URL, credential, or PDF content may be persisted or logged as an error detail.
- Scan-page validation must never convert unsupported clipping geometry into zero coverage and silently accept the page.

## Decision 1: Fail Closed for Unsupported PDF Clipping

The validator continues exact geometry for the supported case: one simple convex path applied with the non-zero winding operator `W`. Page crop boxes, Form bounding boxes, CTM composition, graphics-state save/restore, and supported content clipping remain polygon intersections.

The walker raises `_PDFGeometryLimit` when a clipping operation is pending and its path is not representable exactly by the supported geometry. This includes:

- a second `re` or `m` subpath;
- a curved segment (`c`, `v`, or `y`);
- even-odd clipping (`W*`);
- a non-convex or degenerate polygon;
- inherited unsupported clipping state.

`validate_pdf()` already maps `_PDFGeometryLimit` through the malformed-input boundary to `PDF_MALFORMED`. Unsupported clipping is therefore rejected explicitly instead of being treated as zero raster coverage. Paths used only for drawing do not fail validation; the failure occurs only when an unsupported path is applied as a clip.

This design deliberately prefers a bounded false rejection of an unsupported PDF over a BR-07 bypass. It does not add a general-purpose PDF boolean-geometry engine or a new geometry dependency.

## Decision 2: Transactional Analysis-Job Dispatch Outbox

### Data model

Add `public.analysis_job_dispatches` in Alembic revision `20260829_0007`:

- `id UUID` primary key;
- `analysis_job_id UUID NOT NULL`, unique, referencing `public.analysis_jobs(id)`;
- `attempt_count INTEGER NOT NULL DEFAULT 0`, constrained to be non-negative;
- `next_attempt_at TIMESTAMPTZ NOT NULL DEFAULT now()`;
- `created_at TIMESTAMPTZ NOT NULL DEFAULT now()`;
- `updated_at TIMESTAMPTZ NOT NULL DEFAULT now()`;
- an index on `(next_attempt_at, created_at, id)` for deterministic due-row polling.

The migration follows the repository security rules: pin `search_path` and schema-qualify DDL and foreign keys. Its upgrade backfills one pending dispatch row for every `analysis_jobs.status = 'QUEUED'` row that exists at revision `0006`, so deployment recovers jobs that may already have lost their broker wake-up. Its downgrade first checks for pending dispatch rows and raises a clear database exception when any exist; operators must drain or explicitly reconcile those rows before downgrading to `20260828_0006`. The downgrade never silently discards pending work.

Only one pending dispatch row may exist per analysis job. Successful publication deletes the row, so a later explicit retry can create a new dispatch for the same durable job row.

### Atomic enqueue

Creating or reusing a queued job and creating its dispatch row occur in the same database transaction. The same rule applies to `ERROR → QUEUED` retry. Idempotent completion of an already queued document ensures a dispatch row exists before returning.

A transaction therefore commits both:

```text
AnalysisJob = QUEUED
AnalysisJobDispatch = pending
```

or commits neither.

### Publisher

A dedicated dispatch service selects due rows in deterministic order using `FOR UPDATE SKIP LOCKED` and a bounded batch. This permits multiple API replicas without publishing the same locked row concurrently.

For each locked row:

1. Run the synchronous Celery producer call outside the event loop with `asyncio.to_thread()`. Disable producer retries for that attempt, configure finite Redis producer connect/socket timeouts, and wrap the await in a finite `asyncio.timeout()` boundary.
2. On successful producer return, delete the dispatch row.
3. On publication error or timeout, retain the row, increment `attempt_count`, and set `next_attempt_at` using exponential backoff capped at 60 seconds.
4. Commit the row outcomes as one bounded batch.

The broker call has no access to the database session. A timed-out worker thread may return later and may have published successfully; retaining the row can then cause a duplicate publication, which is safe under the existing idempotent claim contract. Finite transport timeouts bound the thread lifetime, while the async timeout keeps the API event loop and poller responsive.

No provider exception text is persisted or logged. Logs contain only a generic dispatch-failure message and safe identifiers when existing logging policy permits them.

### Immediate and recovery paths

After the request transaction commits, the completion and retry routes invoke a job-specific outbox drain. This preserves low normal-case queueing latency. Failure of this immediate attempt does not change the successful HTTP response because the pending row is already durable.

FastAPI lifespan starts one asynchronous poller per API process. The poller:

- waits one second before the first recovery poll;
- creates a fresh `AsyncSession` for every poll iteration and discards it after commit or rollback;
- drains due rows, then sleeps one second;
- catches transient database and broker failures without terminating; a failed session is rolled back/discarded and is never reused;
- is cancelled and awaited during graceful shutdown after any in-flight bounded publication returns.

Multiple pollers are safe because PostgreSQL row locks and `SKIP LOCKED` serialize ownership. A restarted API discovers persisted pending rows automatically. This preserves the documented no-Celery-Beat MVP architecture and keeps normal enqueue latency under the five-second acceptance bound.

## Delivery Semantics

The outbox provides at-least-once publication:

- crash before publication: the row remains pending;
- broker failure: the row remains pending with backoff;
- crash after broker acceptance but before row deletion commits: the message may be published twice;
- duplicate message: existing job row locking, status checks, leases, attempt fencing, uniqueness, and late acknowledgement prevent duplicate domain outcomes.

Exactly-once broker delivery is neither required nor claimed.

## Components and File Boundaries

- `backend/app/models/analysis.py`: internal `AnalysisJobDispatch` ORM model and relationship.
- `backend/app/models/__init__.py`: model registration/export for metadata discovery.
- `backend/alembic/versions/20260829_0007_analysis_job_dispatch_outbox.py`: schema migration.
- `backend/app/services/analysis_dispatch.py`: enqueue, bounded due-row dispatch, backoff, and lifespan polling loop.
- `backend/app/services/analysis_job.py`: enqueue outbox records in the job create/reuse and retry transactions.
- `backend/app/services/submission.py`: ensure idempotent queued completion retains a pending dispatch path.
- `backend/app/api/routers/submissions.py`: replace direct `.delay()` calls with post-commit immediate outbox drains.
- `backend/app/main.py`: own poller startup, cancellation, and shutdown.
- `backend/app/services/pdf_validation.py`: fail closed for unsupported clipping.
- Focused test and canonical documentation files are updated with the new observable contracts.

## Verification

### PDF regression tests

- two rectangle subpaths whose union covers at least 80% cannot be accepted;
- `W*`, curved, and non-convex clipping used as a clip fail with `PDF_MALFORMED`;
- one supported rectangular clip still reduces visible raster coverage correctly;
- graphics-state save/restore, Form clipping, exact 80% comparison, and nested decode bounds remain green.

### Outbox tests

- revision `0007` backfills one outbox row for every pre-existing queued job;
- downgrade refuses to drop the table while pending rows exist, then succeeds after an explicit drain;
- queued job state and outbox row commit or roll back together;
- idempotent completion/retry creates at most one pending row;
- successful publication deletes the row;
- broker failure or timeout retains the row and advances bounded backoff;
- concurrent pollers publish a locked row once;
- a second publication after a simulated publish-before-delete crash is harmless to job claims;
- the API event loop remains responsive while producer I/O is blocked;
- one poll iteration may fail at the database boundary and the next fresh-session iteration still drains successfully;
- the API returns the committed job when immediate broker publication fails;
- lifespan shutdown cancels and awaits the poller within the configured producer bound.

### Integrated verification

Run focused PDF, upload, outbox, lifecycle, concurrency, migration, and recovery tests; Ruff; Black; the full database-enabled pytest suite; and Alembic upgrade/downgrade/upgrade through revision `0007`. Reconcile canonical documentation, commit and push the exact final HEAD, request a new CodeRabbit full review, report its result verbatim, and stop for the user's decision if any finding remains.

## Non-Goals

- General boolean geometry for arbitrary PDF clipping paths.
- Celery Beat, task canvas, or a new dispatcher container.
- Exactly-once message delivery.
- Frontend changes or evaluator-result implementation.
