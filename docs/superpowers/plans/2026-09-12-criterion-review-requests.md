# Criterion Review Request API Plan

**Scope:** Backend-only T-016. `frontend/`, evaluator/rubric/rule execution, score calculation, score/decision mutation, and notification delivery remain out of scope. Workflow records an appeal against stored T-011/T-012 publication data; any later score override must use existing review/approval/publication flow and create a new `PublishedResultVersion`.

## Contract decisions

- Student creates through `POST /published-results/{published_result_id}/review-requests` with `submission_id`, exactly one of stable `criterion_id` or published `finding_id`, and a nonblank reason. Authorization predicates run before row locks; service then locks Course, Assignment, Submission, DocumentVersion, and exact immutable `PublishedResultVersion` in that order. It validates owner, current `PUBLISHED` state, latest published result, target membership, seven-day window, and non-archived Course/Assignment.
- Persistence stores the exact `published_result_version_id`, owner `student_id`, resolved `criterion_version_id`, optional `finding_id`, status, request reason, response, responder, and timestamps. A partial unique index permits at most one `OPEN` request per Student, criterion, and published result even when the Student selected a finding within that criterion.
- Request statuses are `OPEN`, `RESOLVED`, and `REJECTED`. Only `OPEN -> RESOLVED|REJECTED` is valid. Terminal transitions require a nonblank response and record responder/time. They never mutate `ReviewDecision`, `DocumentVersion.approved_snapshot`, or `PublishedResultVersion.snapshot`.
- Course-owner Teacher and Admin list through `GET /courses/{course_id}/review-requests?status=...`; authorized actors and the owning Student may read `GET /review-requests/{review_request_id}`. Teacher/Admin respond through `PATCH /review-requests/{review_request_id}`. Strongest-role precedence prevents Teacher/Student accounts from falling through to Student ownership.
- Every open, resolve, and reject writes one atomic `AuditEvent` with actor, request reason, exact before/after state, and response reason. API responses use explicit allowlists and contain no raw IR, PDF text, storage key, prompt/model detail, internal review reason, score, or decision payload.
- Unpublish blocks new requests but does not rewrite existing request state. The complete state graph remains `OPEN -> RESOLVED|REJECTED`; no implicit `RESULT_WITHDRAWN` transition exists.

## Migration security checklist

Hard gate completed before migration code:

- [x] **SC-1 — pin `search_path`:** first statement in both `upgrade()` and `downgrade()` will be `SET search_path TO public`; no PL/pgSQL function is planned. Any function added during implementation must declare `SET search_path = pg_catalog, public, pg_temp`.
- [x] **SC-2 — preserve append-only TRUNCATE guards:** migration will not alter, disable, replace, truncate, or drop `public.audit_events`, `public.published_result_versions`, or their row/TRUNCATE guards. Real PostgreSQL roundtrip will prove `TRUNCATE public.audit_events` and `TRUNCATE public.published_result_versions` remain rejected after upgrade and downgrade/re-upgrade.
- [x] **SC-3 — schema-qualify every DDL/FK:** every Alembic table/index/constraint operation will pass `schema="public"`; every FK target will use `public.<table>.<column>` or explicit `source_schema`/`referent_schema`; every raw SQL application table/type/index reference will use `public.`.
- [x] **Downgrade safety:** downgrade will lock `public.review_requests`, refuse nonempty data, then remove only T-016 objects in dependency order.

## Implementation sequence

1. Add `ReviewRequestStatus`, ORM metadata, migration, schemas, service commands/queries, and routes using existing authorization and audit patterns.
2. Add focused contract, workflow/security, and real-PostgreSQL migration roundtrip checks.
3. Run Ruff, Black check, full database-enabled pytest, and explicit Alembic upgrade/downgrade/re-upgrade.
4. Review Functional Correctness, Data Integrity & Integration, Security & Privacy; reconcile verified behavior here and in canonical API documentation.

## Required proof

- Request binds one stable criterion or published finding to one exact current `PublishedResultVersion`; an unpublished, withdrawn, stale, foreign, expired, or archived target is rejected.
- `OPEN -> RESOLVED` and `OPEN -> REJECTED` persist response, responder, and audit; terminal replay is rejected.
- Student cannot create/read another Student's request. Teacher cannot list/read/respond outside owned Course. Admin can list/read/respond every Course.
- Open/respond actions do not change published snapshot, approved snapshot, review decision, score, or document publication state.
- Response schemas expose only request identifiers, target, status, reason/response, actor identifiers, and timestamps; raw IR and storage fields never enter the projection.
- Migration satisfies SC-1/2/3, refuses lossy downgrade, roundtrips on PostgreSQL 17, and preserves both append-only TRUNCATE guards.

## Required final review groups

### Functional Correctness

Verify exact published-result target binding, one criterion/finding target, publication/window/archive gates, Course filtering, and both terminal transitions.

### Data Integrity & Integration

Verify partial uniqueness, locked state changes, atomic audit, unchanged published/approved snapshots and review decisions, and zero evaluator/score execution.

### Security & Privacy

Verify strongest-role/object ownership in both Student/Teacher directions, Admin scope, 404 masking for foreign objects, explicit response allowlists, and absence of raw IR/storage/internal review data.

## Verification results

- `uv run ruff check`: passed.
- `uv run black --check .`: passed; 93 files unchanged.
- `RUN_DATABASE_TESTS=1 uv run pytest -q`: passed; 352 tests.
- Real PostgreSQL 17 migration checks: T-012/T-016 roundtrip tests passed; explicit Alembic `20260912_0011 -> 20260911_0010 -> 20260912_0011` passed. Both append-only TRUNCATE guards remained active; nonempty `review_requests` downgrade was refused.

## Final review

### Functional Correctness

Pass. Criterion and finding requests retain exact `PublishedResultVersion`; unpublished, stale, foreign, expired, and archived creation paths are rejected. Course/status listing and both terminal transitions are covered.

### Data Integrity & Integration

Pass. Partial uniqueness and lock order protect open/terminal transitions. Audit stores actor, reason, and before/after state. Workflow checks confirm unchanged finding score, `ReviewDecision`, approved snapshot, published snapshot, and publication state. No evaluator or rubric execution path is called.

### Security & Privacy

Pass. Student ownership, Teacher Course ownership, Admin scope, strongest-role precedence, authorization-before-lock, 404 masking, and response allowlists are enforced. Independent correctness and security reviews found no remaining scoped findings.
