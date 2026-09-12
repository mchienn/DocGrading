# In-App Notification API Plan

**Scope:** Backend-only T-017. Create durable in-app `Notification` records and polling endpoints. `frontend/`, push, email, websocket, and external delivery are out of scope because no delivery infrastructure exists.

## Contract decisions

- The exact source events are: each successful `AnalysisJob` transition to `ERROR`; creation of a `PublishedResultVersion`; creation of a `ReviewRequest`; transition of a `ReviewRequest` to `RESOLVED` or `REJECTED`. A retried job that fails again is a new source transition and creates a new notification.
- Recipients are resolved from locked or source-owned records: the Submission Student for job errors and publication; the Course owner Teacher for a new review request; the requesting Student for resolution or rejection.
- Notification types are `ANALYSIS_JOB_ERROR`, `RESULT_PUBLISHED`, `REVIEW_REQUEST_CREATED`, `REVIEW_REQUEST_RESOLVED`, and `REVIEW_REQUEST_REJECTED`.
- Payloads contain reference IDs only. They never copy PDF text, storage keys, error detail, review reason/response, result snapshot, score, prompt/model data, or internal audit data.
- Notification insertion uses the source event's existing `AsyncSession` and commit boundary. Failure rolls back both source event and notification. Canonical BR-27 now distinguishes this durable in-app write from any future best-effort external delivery after commit.
- Polling is the only delivery mechanism: actor-scoped paginated listing with optional unread filter, plus actor-scoped idempotent single and bulk mark-as-read.
- T-017 does not add the BR-33 unpublish notification because the task's required event list excludes unpublish. Follow-up `DOC-30` tracks that canonical requirement.

## Migration security checklist

Hard gate completed before migration code:

- [x] **SC-1 — pin `search_path`:** first statement in both `upgrade()` and `downgrade()` will be `SET search_path TO public`; any PL/pgSQL function added during implementation must declare `SET search_path = pg_catalog, public, pg_temp`.
- [x] **SC-2 — preserve append-only TRUNCATE guards:** migration will not alter, disable, replace, truncate, or drop `public.audit_events`, `public.published_result_versions`, or their row/TRUNCATE guards. Real PostgreSQL roundtrip will prove both append-only tables still reject `TRUNCATE` after upgrade and downgrade/re-upgrade. `public.notifications` is not append-only because mark-as-read updates `read_at`.
- [x] **SC-3 — schema-qualify every DDL/FK:** every Alembic table/index/constraint operation will pass `schema="public"`; every FK target will use `public.<table>.<column>`; every raw SQL application table/type/index reference will use `public.`.
- [x] **Downgrade safety:** downgrade will lock `public.notifications`, refuse nonempty data, then remove only T-017 objects in dependency order.

## Implementation sequence

1. Add `NotificationType`, ORM metadata, migration, explicit API schemas, service queries/mutations, router, and registration.
2. Insert notifications at the existing atomic source-event integration points without adding commits or external delivery.
3. Add focused integration coverage for every event/recipient, cross-Course privacy, actor ownership, idempotent mark-as-read, rollback, payload allowlists, and migration roundtrip.
4. Run Ruff, Black check, full database-enabled pytest, and explicit Alembic upgrade/downgrade/re-upgrade.
5. Review Functional Correctness, Data Integrity & Integration, and Security & Privacy; reconcile canonical documentation from verified behavior.

## Required proof

- Each required source event creates exactly one notification for the specified recipient; replay or rejected transitions create none.
- Teacher B receives no notification for Teacher A's Course. Each actor can list and mark only their own notifications; foreign IDs return the same not-found result as missing IDs.
- Repeated single or bulk mark-as-read preserves the original `read_at` value.
- Rolling back a source transaction leaves neither the source transition nor a notification.
- API payloads expose only notification ID, type, reference-ID payload, `read_at`, and `created_at`.
- Migration satisfies SC-1/2/3, refuses lossy downgrade, roundtrips on PostgreSQL 17, and preserves append-only TRUNCATE guards.

## Verification results

- `uv run ruff check`: passed.
- `uv run black --check .`: passed; 100 files unchanged.
- `uv run pytest -q tests/test_t017_contracts.py`: 8 passed.
- `RUN_DATABASE_TESTS=1 uv run pytest -q tests/test_t017_workflow.py`: 4 passed.
- Targeted integration cleanup and migration sequence: 7 passed.
- Full database-enabled suite on an isolated PostgreSQL 17 database: 364 passed in 476.27 seconds.
- Explicit `alembic upgrade head`, downgrade to `20260912_0011`, then upgrade to `head`: passed on PostgreSQL 17.

## Final review

### Functional Correctness

- No open finding. Tests cover every required source transition, exact recipient and reference payload, source replay, rejected transition, retry-to-new-error behavior, pagination, unread filtering, and idempotent mark-as-read.

### Data Integrity & Integration

- No open finding. Notification insert and source transition share one `AsyncSession`; forced notification failure rolls back both. Migration uses schema-qualified DDL, pinned `search_path`, guarded downgrade, and preserves both append-only TRUNCATE guards.
- Full-suite isolation required T-012 concurrency cleanup to remove notifications created by its committed publish races. Live API/worker consumers were stopped during DB tests so they could not consume test outbox rows.

### Security & Privacy

- No open finding. Independent security review confirmed reference-ID-only payloads, actor ownership predicates on list and updates, uniform not-found behavior for missing and foreign IDs, bounded bulk input, and no cross-Course Teacher leakage.
