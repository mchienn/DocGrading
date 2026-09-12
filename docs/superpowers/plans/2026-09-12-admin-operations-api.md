# Admin Operations API Plan

**Scope:** Backend-only T-018. Add Admin user management, global `AnalysisJob` monitoring and retry, audit-log inspection, and basic aggregate dashboard endpoints. `frontend/`, evaluator/rule/LLM execution, new evaluator types, caching, billing, and new infrastructure remain out of scope.

## Contract decisions

- Every new endpoint uses the existing `require_roles(UserRole.ADMIN)` dependency. Teacher job access remains on the existing Course-scoped `GET/POST /analysis-jobs/{job_id}` flow; Admin operations never apply a Course ownership predicate.
- `GET /users` provides paginated filters for role, status, and case-insensitive email/display-name search. `GET /users/{user_id}` and `PATCH /users/{user_id}` use explicit response fields and never expose `password_hash` or session data.
- One user patch may change roles, account status, or both. A transaction-scoped advisory lock serializes account writes before the target row lock and active-Admin check: an Admin cannot remove their own `ADMIN` role or lock themselves, and concurrent cross-updates cannot remove the last active Admin. Validation precedes mutation; accepted changes increment `revision` only once and record separate atomic `AuditEvent` rows for `ROLE_CHANGE`, `LOCK`, and `UNLOCK`.
- `GET /operations/analysis-jobs` is paginated and filters by status and Course. List rows contain only identifiers, Course context, state, attempts, error code, and timestamps. `GET /operations/analysis-jobs/{job_id}` adds sanitized persisted error detail; neither response includes job snapshots, document storage keys, PDF data, provider settings, or credentials.
- `POST /operations/analysis-jobs/{job_id}/retry` calls the existing T-009 `retry_job` service, commits its same-row state change/audit/outbox atomically, then uses the existing dispatcher. No claim, lock, attempt, or evaluator logic is copied.
- `GET /operations/audit-events` filters by actor user, resource type, and inclusive timezone-aware bounds, with deterministic pagination. Per-resource top-level allowlists expose only known-safe audit fields; every unknown field is redacted wholesale, then known-safe values and reasons receive recursive credential/storage sanitization.
- `GET /operations/dashboard` runs uncached aggregate queries for jobs by every status, submissions by Course, and open review-request count. It does not invoke evaluator code or materialize new state.
- No schema change is needed: all required columns, relations, indexes, enums, and append-only audit protections already exist.

## Migration security checklist

Hard gate completed before any migration code:

- [x] **SC-1 — pin `search_path`:** no Alembic revision is needed. Any migration discovered during implementation must begin both `upgrade()` and `downgrade()` with `SET search_path TO public`; every PL/pgSQL function must declare `SET search_path = pg_catalog, public, pg_temp`.
- [x] **SC-2 — preserve append-only TRUNCATE guards:** no DDL touches, disables, replaces, truncates, or drops `public.audit_events` or `public.published_result_versions`, including their row and `TRUNCATE` guards.
- [x] **SC-3 — schema-qualify every DDL/FK:** no DDL or FK is planned. Any required Alembic operation must pass `schema="public"`, use `public.<table>.<column>` FK targets, and qualify raw SQL application objects with `public.`.
- [x] **Downgrade safety:** no revision means no downgrade path and no data-loss operation.

## Implementation sequence

1. Add explicit Admin operation schemas, query/mutation services, router, and application registration.
2. Reuse `record_audit`, `retry_job`, and `dispatch_analysis_job_now`; add no evaluator or queue implementation.
3. Add focused contract and PostgreSQL workflow coverage for Admin scope, unchanged Teacher Course scope, audited account changes, retry parity, filters, aggregates, redaction, pagination, and non-Admin rejection.
4. Run Ruff, Black check, targeted tests, full database-enabled pytest, and runtime API smoke checks. Alembic roundtrip is required only if implementation adds a revision.
5. Review Functional Correctness, Data Integrity & Integration, and Security & Privacy; reconcile canonical documentation from verified behavior.

## Required proof

- Admin lists jobs from multiple Courses; Teacher remains limited to owned-Course jobs through the existing flow.
- Role and lock-state changes persist one exact before/after audit per changed field in the same transaction; unchanged or rejected patches create no audit. Self-demotion/self-lock return `409`, and concurrent cross-demotion leaves exactly one active Admin.
- Admin retry mutates the existing job and document, creates the existing dispatch/audit effects, and creates no new `AnalysisJob`.
- Teacher and Student receive `403` from every new user, operations job, audit, and dashboard endpoint.
- Audit/job/user/dashboard responses use explicit allowlists and contain no password hash, session credential, signed-upload field, job snapshot, or storage key.
- Dashboard values come directly from current database aggregates and include zero counts for absent job statuses.

## Verification results

- `uv run ruff check .`: passed.
- `uv run black --check .`: passed; 104 files unchanged.
- `RUN_DATABASE_TESTS=1 uv run pytest -q tests/test_t018_admin_operations.py`: 7 passed.
- `uv run pytest -q tests/test_t009_job_recovery.py`: 21 passed.
- Full database-enabled suite on an isolated PostgreSQL 17 database: 371 passed in 527.33 seconds.
- Clean-database `alembic upgrade head`: passed through revision `20260912_0012`. T-018 adds no revision, so no T-018 downgrade exists or was required. Existing migration roundtrip tests passed inside the full isolated suite.
- Rebuilt local API/worker images after validation; API reached healthy state and worker started.

## Final review

### Functional Correctness

- No open finding. Coverage proves Admin cross-Course job visibility, unchanged Teacher Course scoping, user/job/audit filters and pagination, safe job detail, protected self-demotion/self-lock, concurrency-safe active-Admin preservation, account role/lock transitions, same-row retry parity, and live database dashboard aggregates.

### Data Integrity & Integration

- No open finding. A transaction-scoped advisory lock serializes Admin account writes before the target row lock and validation, preventing concurrent cross-updates from removing every active Admin. Accepted user mutations increment one revision, write exact field-specific audits in the same transaction, and emit none for replay or rejection. Admin retry directly reuses the T-009 service, existing job row, document transition, audit, dispatch outbox, and post-commit dispatcher.
- T-018 needs no schema change. First full-suite attempt used the populated development database and correctly hit existing lossy-downgrade guards. Final rerun on an isolated PostgreSQL 17 database passed all 371 tests; validation database was removed afterward.

### Security & Privacy

- No open finding. Independent security closeout confirmed Admin-only dependencies, CSRF on mutations, explicit user/job response fields, sanitized job error detail, per-resource audit allowlists, wholesale unknown-field redaction, nested-assignment scanning, quoted/multiword/camelCase/acronym credential-label handling, and no credential, storage path/key, signed-upload, job snapshot, evaluator config, or PDF exposure.