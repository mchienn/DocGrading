# Approval, Publication & Student Result API Plan

**Scope:** Backend-only T-012, US-026–US-030. `frontend/`, evaluator/rubric/rule execution, score calculation, review-request workflow, and new notification infrastructure remain out of scope. Approval snapshots only persisted Teacher-entered T-011 decisions, scores, comments, and evidence references.

## Contract decisions

- Canonical draft state is `AWAITING_REVIEW`. Approve locks Course/Submission/DocumentVersion, re-checks status after lock, validates every finding has a current review decision, stores an immutable approval snapshot on the DocumentVersion, changes only `AWAITING_REVIEW -> APPROVED`, and audits before/after. It never publishes.
- Publish locks and re-checks `APPROVED`, copies the stored approval snapshot unchanged into a new append-only `PublishedResultVersion`, changes only `APPROVED -> PUBLISHED`, and audits before/after. No score or evaluator code runs.
- Bulk publish is Assignment-scoped. It locks submissions and document versions in UUID order. Any missing, foreign, duplicate, or non-`APPROVED` item rejects the whole transaction; no partial result becomes visible.
- Student result lookup uses one ownership-and-status-filtered query. Only the owning Student receives the latest published snapshot when the latest submitted DocumentVersion is `PUBLISHED`; an older published version never becomes visible after a newer version is unpublished. Missing, foreign, `AWAITING_REVIEW`, `APPROVED`, and unpublished-reverted resources all return `404`, never `200` with `null`.
- Student output is an explicit allowlist: persisted score, public comment, accepted/edited finding description and suggestion, criterion/finding IDs, plus T-011 evidence reference geometry. It excludes rejected findings, PDF bytes/text, storage keys, raw IR, prompt/model/confidence, internal reasons, and audit data.
- Unpublish is in scope through canonical BR-33/AT-14. Course-owner Teacher or Admin may change the latest submitted DocumentVersion's latest result from `PUBLISHED -> APPROVED`; nonblank reason and audit before/after are required. Existing `PublishedResultVersion` remains unchanged and Student visibility ends in the same transaction. Review-request closure and notification delivery await their owning backlog because neither persistence model exists yet.
- `Idempotency-Key` follows canonical API contract for approve, publish, bulk publish, and unpublish. Actor/action/key is durable; same payload replays, changed payload returns `409`.
- Published-result versions are append-only. Re-publish creates the next version and never edits history.

## Persistence

Migration `20260911_0010` adds approval provenance/snapshot columns to `public.document_versions`, `public.published_result_versions`, and durable review-command idempotency rows. It refuses upgrade when legacy `APPROVED`/`PUBLISHED` rows lack an approval snapshot, requiring explicit backfill or re-review instead of marooning terminal state. Published snapshots contain normalized JSON only; Decimal scores are stored exactly as strings. No new scoring entity or calculation path is introduced.

## Migration security checklist

Hard gate before migration code:

- [x] **SC-1 — pin `search_path`:** first statement in both `upgrade()` and `downgrade()` is `SET search_path TO public`; every new PL/pgSQL function declares `SET search_path = pg_catalog, public, pg_temp`.
- [x] **SC-2 — guard append-only data:** migration never alters, disables, replaces, truncates, or drops `public.audit_events` or its row/TRUNCATE guards. Published-result append-only protection covers `UPDATE`, `DELETE`, and `TRUNCATE`. Real PostgreSQL roundtrip re-proves audit and published-result TRUNCATE rejection.
- [x] **SC-3 — schema-qualify DDL/FKs:** every Alembic table/index/constraint operation passes `schema="public"`; every FK target is `public.<table>.<column>`; every raw SQL table, type, function, trigger, cast, and sequence reference uses `public.` where applicable.
- [x] Downgrade locks affected objects and refuses any loss of published snapshots, idempotency history, or non-null approval provenance.
- [x] Upgrade fails closed before DDL when legacy `APPROVED`/`PUBLISHED` rows need approval-snapshot backfill.

## Implementation sequence

1. Add migration/metadata contract tests and real-PostgreSQL transition fixtures.
2. Add persistence only after this security checklist exists.
3. Add minimal schemas, review-service commands, and submission routes.
4. Prove separate transitions, concurrent actors, privacy, bulk rollback, idempotency, audit, and unpublish.
5. Run Ruff, Black check, full database-enabled pytest, Alembic upgrade/downgrade/re-upgrade, and append-only guard checks.
6. Review Functional Correctness, Data Integrity & Integration, Security & Privacy; reconcile this plan from verified behavior.

## Required proof

- `AWAITING_REVIEW -> APPROVED` does not publish; `APPROVED -> PUBLISHED` works; direct publish from `AWAITING_REVIEW` returns `409`.
- Two actors racing approve or publish produce one transition/result/audit only; loser re-checks locked status and cannot overwrite.
- Student gets `404` before publication, after unpublish, and for another Student's submission.
- Bulk publish commits all selected approved documents or rolls back every status, result, command, and audit row.
- Audit rows contain actor, reason, and exact before/after status/result provenance.
- Result payload contains no storage key, PDF/raw IR text, rejected finding, model/prompt/confidence, or internal override reason.
- Migration satisfies SC-1/2/3 and roundtrips on PostgreSQL 17 without weakening `audit_events` TRUNCATE protection.
