# Resubmission & Version Comparison API Plan

**Scope:** Backend-only T-015. `frontend/`, evaluator/rubric/rule/LLM execution, score calculation, and document diffing remain out of scope.

## Contract decisions

- Resubmission reuses `POST /api/v1/assignments/{assignment_id}/uploads/presign` and the T-009 completion flow. A new payload creates the next `DocumentVersion` on the existing `Submission`; idempotent or duplicate-file retries reuse the existing version.
- Upload initiation locks the `Assignment`, then the existing `Submission`, re-checks `OPEN` and `due_at`, and allocates the next version while the submission lock is held. The unique `(submission_id, version_number)` constraint remains the final defense.
- `GET /api/v1/submissions/{submission_id}/versions` returns versions oldest first. `processing_status` is normalized to `QUEUED`, `PROCESSING`, `AWAITING_REVIEW`, or `ERROR`; publication metadata comes from the latest immutable `PublishedResultVersion` when visible to the caller.
- `GET /api/v1/submissions/{submission_id}/versions/compare?left_version_id=&right_version_id=` returns two stored projections containing review comment and per-finding score, decision, and evidence count. It never parses a document, invokes an evaluator, or calculates a new score.
- Student access requires submission ownership. Student comparison requires both selected versions to be currently published and uses only immutable published snapshots. Internal failures, drafts, rejected findings, PDF/IR content, storage keys, prompts, model data, confidence, internal reasons, and audit data stay hidden.
- Admin may read every submission. Teacher may read only submissions under a Course they own. Strongest-role precedence prevents a Teacher/Student account from falling through to Student ownership.
- New versions never update or delete old `DocumentVersion`, `AnalysisJob`, `DocumentIR`, review result, or `PublishedResultVersion` rows. Older published snapshots remain available in authorized version history and comparison.
- T-015 allows any two distinct versions of one Submission, matching FR-25. This supersedes the older adjacent-only MVP wording in BR-22/AT-16.

## Migration security checklist

No migration is required: existing version, job, IR, review, approval-snapshot, and published-result tables already hold the required data.

Checklist completed before implementation:

- [x] **SC-1 — pin `search_path`:** not applicable because T-015 adds no Alembic revision or PL/pgSQL. Any later migration must start both directions with `SET search_path TO public` and pin every function to `pg_catalog, public, pg_temp`.
- [x] **SC-2 — guard append-only history:** T-015 changes no DDL, trigger, or mutation path for `public.audit_events` or `public.published_result_versions`; existing row/TRUNCATE guards remain untouched.
- [x] **SC-3 — schema-qualify DDL/FKs:** not applicable because T-015 adds no DDL or FK. Any later migration must qualify every application object and use `public.<table>.<column>` FK targets.
- [x] **Downgrade safety:** no revision means no downgrade and no path that discards submission, version, job, review, or publication history.

## Required proof

- Resubmission after `due_at` and after Assignment closure returns `409` without creating a version.
- Two concurrent duplicate resubmissions produce one next version; old jobs/results remain linked to the old version.
- Creating a new version leaves old published snapshot bytes and publication metadata unchanged.
- Student ownership denial returns `404`; Course owner Teacher and Admin are allowed.
- Student cannot compare an unpublished or error/internal-processing version.
- Ruff, Black check, full pytest, and database-enabled concurrency tests pass. Alembic roundtrip is required only if a migration is added.

## Required final review groups

### Functional Correctness

Verify the `OPEN`/`due_at` gate, chronological status projection, stored-only comparison, and stable published history.

### Data Integrity & Integration

Verify Submission row locking, monotonic version allocation, unchanged prior `AnalysisJob`/`DocumentIR`/review/publication links, and zero evaluator calls.

### Security & Privacy

Verify owner/Course authorization, strongest-role precedence, Student published-only comparison, explicit response allowlists, and absence of internal document/error data.
