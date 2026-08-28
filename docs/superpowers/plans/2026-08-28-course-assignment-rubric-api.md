# T-008 Course, Assignment & Rubric API Completion Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Complete the backend-only T-008 contract with archived-course handling, object-scoped Student assignment access, immutable/published rubric versions, and real-PostgreSQL migration validation.

**Architecture:** Keep ownership enforcement centralized in `app.api.deps`: Teacher/Admin flows reuse `get_owned_course`, while Student reads require an active `Membership`. Add only the `CourseStatus` state the stated T-008 status coverage requires; archive blocks mutation but preserves read history. Rubric supersession remains lineage-based through `source_version_id`; creating the next DRAFT does not mutate the published source.

**Tech Stack:** FastAPI, Pydantic v2, SQLAlchemy 2 async, Alembic, PostgreSQL 17, pytest, Ruff, Black.

---

## Migration Security Checklist

- [x] **SC-1 — pin `search_path`:** `upgrade()` and `downgrade()` in migration 0004 begin with `SET search_path TO public`.
- [x] **SC-2 — preserve append-only audit protection:** migration 0004 does not alter `public.audit_events`; its `BEFORE TRUNCATE` guard from 0002 remains installed.
- [x] **SC-3 — schema-qualify database objects:** the enum is `public.course_status`, the column DDL targets `schema="public"`, and the migration introduces no foreign keys.

**Existing migration finding:** `20260825_0002` schema-qualifies its DDL/FKs and pins each PL/pgSQL function search path, but does not pin transaction-level `search_path` at the start of `upgrade()`/`downgrade()`. This predates T-008 and is not modified in this scoped migration.

## Requirements Traceability

| Requirement | Implementation / verification |
| --- | --- |
| Course archive state | `CourseStatus`, migration 0004, `archive_course`, archive route, mutation guard tests |
| Assignment all status branches | Existing DRAFT/OPEN/CLOSED tests plus ARCHIVED tests |
| Student object authorization | active Student `Membership` required for list/detail, non-member/inactive tests |
| No unpublished rubric data for Student | rubric routes require Teacher/Admin; Student denial test |
| Rubric publish validates enabled weights | `publish_rubric_version` sums persisted criteria; 100/≠100 tests |
| Published rubric immutable | service rejects all writes with 409; create-new-version clones to DRAFT |
| Superseded rubric version | lineage through `source_version_id`; next version receives a monotonic number while source remains PUBLISHED |
| Auditing | `record_audit` for course and assignment creation/lifecycle and all rubric writes/publish/version events |

## Task 1: Add archived Course state

**Files:**
- Create: `backend/alembic/versions/20260828_0004_course_status.py`
- Modify: `backend/app/models/enums.py`
- Modify: `backend/app/models/course.py`
- Modify: `backend/app/services/course.py`
- Modify: `backend/app/api/schemas_course.py`
- Modify: `backend/app/api/routers/courses.py`
- Test: `backend/tests/test_t008_course_assignment_rubric.py`

- [ ] Write tests proving an archived Course is readable but cannot be edited, deleted, receive a new Assignment, or transition to archive twice.
- [ ] Run the focused tests and observe failure because `CourseStatus`/`archive_course` do not exist.
- [ ] Add `CourseStatus.ACTIVE` and `CourseStatus.ARCHIVED`; define `status` on `Course` with an ACTIVE default.
- [ ] Add migration `20260828_0004` using the checklist above. Upgrade creates `public.course_status` then adds non-null `public.courses.status DEFAULT 'ACTIVE'::public.course_status`; downgrade drops the column then enum.
- [ ] Add `archive_course`: only ACTIVE can become ARCHIVED, increment `revision`, record `ARCHIVE` AuditEvent, and flush. Keep existing GET routes readable; provide `POST /courses/{course_id}/archive` behind `get_owned_course` + existing Teacher/Admin role check.
- [ ] Run targeted archive tests until green.

## Task 1b: Enforce published rubric immutability in PostgreSQL

**Files:**
- Create: `backend/alembic/versions/20260828_0005_published_rubric_immutable.py`
- Modify: `backend/tests/test_domain_invariants.py`

- [ ] Write a real-PostgreSQL regression test: publish a valid DRAFT rubric directly, then prove direct `UPDATE` on both `rubric_versions` and `criterion_versions` raises a database error.
- [ ] Run the test at revision 0004 and observe the direct update succeeds; this demonstrates that 0002 freezes only after the first submission.
- [ ] Add migration 0005. Both upgrade and downgrade pin `search_path TO public`, do not alter `audit_events`, schema-qualify all function/table/type references, and replace the existing rubric/criterion immutability functions.
- [ ] Upgrade blocks every `UPDATE`/`DELETE` of a non-DRAFT `RubricVersion` and every criterion write beneath it. The initial DRAFT → PUBLISHED transition remains allowed.
- [ ] Downgrade restores the pre-0005 0002 trigger-function behavior exactly.
- [ ] Upgrade the real database and rerun the regression test until green.

## Task 2: Enforce Course scope and active Student membership

**Files:**
- Modify: `backend/app/api/deps.py`
- Modify: `backend/app/api/routers/assignments.py`
- Test: `backend/tests/test_t008_course_assignment_rubric.py`

- [ ] Write tests for Student with active membership (can see only OPEN/CLOSED); inactive or absent membership returns 404; non-owner Teacher cannot read another Course's assignments.
- [ ] Run focused tests and observe failure because `get_visible_assignments` only filters statuses.
- [ ] Add one dependency that loads the Course, reuses `check_course_ownership` for Teacher/Admin, and requires `Membership(course_id, user_id, role=STUDENT, status=ACTIVE)` for Students. Outside-scope resources return 404.
- [ ] Make assignment list/detail share that dependency; retain `get_owned_course` for every mutation endpoint.
- [ ] Reject mutation routes for `CourseStatus.ARCHIVED`, but leave archived-course reads intact.
- [ ] Run focused authorization and archive tests until green.

## Task 3: Verify rubric supersession and audit invariants

**Files:**
- Modify: `backend/tests/test_t008_course_assignment_rubric.py`

- [ ] Add a test where a PUBLISHED source whose previous lineage has been superseded creates the next DRAFT version. Assert monotonic number, `source_version_id`, copied `total_weight`, and unchanged source status.
- [ ] Keep published-source writes rejected with 409; do not introduce a second `SUPERSEDED` enum because canonical schema models supersession with `source_version_id`.
- [ ] Verify `record_audit` is called for assignment creation, rubric publish, and new-version creation.
- [ ] Run the focused rubric tests until green.

## Task 4: Validate on real PostgreSQL

**Files:** no source changes expected.

- [ ] Start the repository PostgreSQL service.
- [ ] Run `alembic upgrade head`, `alembic downgrade 20260827_0003`, then `alembic upgrade head` against the real database.
- [ ] Run database invariant tests with `RUN_DATABASE_TESTS=1`.
- [ ] Run `uv run ruff check .`, `uv run black --check .`, and `uv run pytest -v`.
