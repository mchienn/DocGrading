# Submission Queue & Review Workspace API Implementation Plan

**Scope:** Backend-only T-011. `frontend/`, PDF viewer UI, evaluator execution, approval, publication, and Student result APIs remain out of scope.

## Contract decisions

- Queue targets logical `Submission` rows and exposes latest `DocumentVersion`. Status groups are exhaustive: `UNREVIEWED` for every non-terminal/non-error document state, `REVIEWED` for `APPROVED`/`PUBLISHED`, `ERROR` for `INVALID`/`PROCESSING_FAILED`. Filter and submitted-time sort are server-side; `Submission.id` is the deterministic secondary sort key. Page is one-based with default 1. `page_size` defaults to 50 and accepts 1–100. FastAPI rejects invalid values before query execution.
- Admin may access every Course. Teacher may access only Courses where `courses.owner_teacher_id` matches. Multi-role evaluation checks Admin before Teacher and never falls through to Student semantics.
- Findings are durable evaluator proposals tied to `AnalysisJob` and `CriterionVersion`. Evidence anchors store only an existing `DocumentIR` ID, deterministic IR element ID, and one-based page. API allowlist contains finding `id`, `criterion_version_id`, `severity`, `description`, `suggestion`, `proposed_score`, plus evidence `document_ir_id`, `element_id`, `page_number`, and `bbox`. It returns no PDF bytes, page text, paragraph text, storage key, prompt, model detail, or raw IR payload.
- Drafts are unique per `(submission_id, reviewer_user_id)` and bound to the current `DocumentVersion`. `PUT` echoes response `document_version_id`; a mismatch returns `409`, preventing prior-version comments or decisions from crossing a resubmission. A new version presents an empty draft at the existing revision, then atomically replaces obsolete decisions on a valid current-version save. `PUT` is a full draft replacement guarded by revision. Exact stale replay for the same document returns current state; divergent writes return `409`.
- Review decisions are normalized rows keyed by `(review_draft_id, finding_id)`: `ACCEPT`, `EDIT`, or `REJECT`. Scores accept at most two decimal places. Score-affecting `EDIT`/`REJECT` requires nonblank reason and creates atomic `AuditEvent` before/after snapshots with `analysis_job_id` provenance. Exact replay creates no duplicate audit.
- Soft lock is one durable row per `Submission`. Acquisition locks `public.courses` with `FOR SHARE`, then `public.submissions` with `FOR UPDATE`; same reviewer refreshes it. Another reviewer receives holder name and expiry without acquiring it. TTL is 10 minutes. Heartbeat and every draft write refresh TTL. Every write locks and re-checks current owner after expiry evaluation. Admin may release any lock; release and holder details are audited atomically.

## API

- `GET /api/v1/courses/{course_id}/submission-queue?status=&sort=&page=&page_size=`
- `GET /api/v1/submissions/{submission_id}/evidence`
- `POST /api/v1/submissions/{submission_id}/review-lock`
- `PUT /api/v1/submissions/{submission_id}/review-lock/heartbeat`
- `DELETE /api/v1/submissions/{submission_id}/review-lock`
- `GET /api/v1/submissions/{submission_id}/review-draft`
- `PUT /api/v1/submissions/{submission_id}/review-draft`

## Persistence

Migration `20260910_0009` adds `findings`, `evidence_anchors`, `review_locks`, `review_drafts`, and `review_decisions`, plus native `review_decision_type`. Drafts carry a required `document_version_id` FK so stale retries cannot cross document versions. Named PK/FK/unique/check/index objects mirror ORM metadata. Downgrade refuses to discard nonempty review/finding tables, then drops only T-011 objects in dependency order.

## Migration security checklist

Hard gate before migration code:

- [x] **SC-1 — pin `search_path`:** first statement in `upgrade()` and `downgrade()` is `SET search_path TO public`; no unpinned function or trigger is introduced.
- [x] **SC-2 — guard append-only history:** migration never alters, disables, replaces, truncates, or drops `public.audit_events` or its append-only row/TRUNCATE triggers. Real PostgreSQL upgrade/downgrade verification proves `TRUNCATE public.audit_events` remains rejected.
- [x] **SC-3 — schema-qualify DDL/FKs:** every Alembic table/index/constraint operation uses `schema="public"`; every FK target is `public.<table>.<column>`; every raw SQL application object/type is qualified.
- [x] Downgrade uses an explicit nonempty-data guard; no finding, draft, decision, or active lock is silently discarded.
- [x] Upgrade, downgrade to `20260902_0008`, and re-upgrade run on PostgreSQL 17.

## Implementation sequence

1. Add failing model, service, authorization, concurrency, privacy, audit, and migration tests.
2. Add review enum/models and migration only after security checklist exists.
3. Add request/response schemas, review service, and submission router routes.
4. Run focused tests, Ruff, Black, full database-enabled pytest, explicit Alembic roundtrip, then re-run concurrency and TRUNCATE checks.
5. Review Functional Correctness, Data Integrity & Integration, Security & Privacy; reconcile canonical documentation only from verified behavior.

## Required proof

- Course-owner Teacher allowed; other Teacher denied; Admin allowed; multi-role precedence preserved.
- Two independent Teacher sessions contend for one lock; exactly one owner until expiry; expired owner cannot write; new owner can acquire. Course archive serializes against review writes. Admin release works for another holder and creates an audit event.
- Draft survives reload. Exact request retry is idempotent. Divergent stale revision never overwrites. A new `DocumentVersion` invalidates previous-document replay and clears obsolete decisions on the next valid save.
- Score-affecting override persists one audit event with exact normalized before/after, reason, actor, and job provenance.
- Evidence endpoint enforces ownership and returns only fields in the explicit response allowlist above. Coverage asserts exact response keys and proves unreferenced malformed IR elements cannot affect referenced evidence.
- `ruff check`, `black --check`, full `pytest`, and real PostgreSQL Alembic upgrade/downgrade/re-upgrade pass.
