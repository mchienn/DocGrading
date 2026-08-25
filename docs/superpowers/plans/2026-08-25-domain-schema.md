# Domain Schema and Migration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add the 12 SQLAlchemy 2 async domain models and a reversible PostgreSQL migration after `20260825_0001`, with database-enforced rubric immutability, role ownership, and append-only audit events.

**Architecture:** Keep the existing `AsyncAttrs` declarative base, split model ownership by canonical domain boundary, and make `app.models` the complete metadata import boundary. Use typed ORM mappings for application code and a hand-authored Alembic revision for PostgreSQL tables, enum types, constraints, indexes, functions, and triggers. Protect fairness and audit invariants in PostgreSQL so direct SQL and background workers cannot bypass them.

**Tech Stack:** Python 3.13, SQLAlchemy 2.0.52 async ORM, Alembic 1.19.1, asyncpg, PostgreSQL 17, pytest 8.4, Ruff, Black, Docker Compose.

---

## File map

**Create:**

- `backend/app/models/enums.py` — all persisted enum values.
- `backend/app/models/mixins.py` — UUID and timestamp/revision mapped-column mixins.
- `backend/app/models/identity.py` — `User`.
- `backend/app/models/course.py` — `Course`, `Membership`.
- `backend/app/models/assignment.py` — `Assignment`, `AssignmentRequirement`.
- `backend/app/models/rubric.py` — `RubricVersion`, `CriterionVersion`, `TemplateVersion`.
- `backend/app/models/submission.py` — `Submission`, `DocumentVersion`.
- `backend/app/models/analysis.py` — `AnalysisJob`.
- `backend/app/models/audit.py` — `AuditEvent`.
- `backend/tests/test_models.py` — metadata and mapper contract tests without a database.
- `backend/tests/test_domain_invariants.py` — opt-in PostgreSQL behavior tests.
- `backend/alembic/versions/20260825_0002_create_domain_schema.py` — reversible domain DDL and triggers.

**Modify:**

- `backend/app/models/__init__.py` — import and export exactly the 12 models.
- `backend/alembic/env.py` — import `app.models` before binding `Base.metadata`.
- `backend/pyproject.toml` — register the `database` pytest marker only if pytest warns about it; no dependency change.

**Must not change:**

- `frontend/**`.
- `backend/app/api/routers/**`.
- Existing health endpoint behavior.

---

### Task 1: Establish the model metadata contract

**Files:**
- Create: `backend/tests/test_models.py`

- [ ] **Step 1: Write the failing exact-table test**

```python
from sqlalchemy import ARRAY, CheckConstraint, ForeignKeyConstraint, Index
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import configure_mappers

from app.db.base import Base
from app.models import (
    AnalysisJob,
    Assignment,
    AssignmentRequirement,
    AuditEvent,
    Course,
    CriterionVersion,
    DocumentVersion,
    Membership,
    RubricVersion,
    Submission,
    TemplateVersion,
    User,
)

EXPECTED_TABLES = {
    "analysis_jobs",
    "assignment_requirements",
    "assignments",
    "audit_events",
    "courses",
    "criterion_versions",
    "document_versions",
    "memberships",
    "rubric_versions",
    "submissions",
    "template_versions",
    "users",
}


def test_domain_models_register_exact_tables() -> None:
    configure_mappers()
    assert set(Base.metadata.tables) == EXPECTED_TABLES


def test_public_ids_use_postgresql_uuid() -> None:
    for table_name in EXPECTED_TABLES:
        assert isinstance(Base.metadata.tables[table_name].c.id.type, UUID)


def test_user_roles_and_json_snapshots_use_postgresql_types() -> None:
    assert isinstance(User.__table__.c.roles.type, ARRAY)
    assert isinstance(AnalysisJob.__table__.c.snapshot.type, JSONB)
    assert isinstance(AuditEvent.__table__.c.before.type, JSONB)
    assert isinstance(AuditEvent.__table__.c.after.type, JSONB)
```

- [ ] **Step 2: Add failing FK and invariant metadata assertions**

```python
def foreign_key_targets(model: type[Base]) -> set[str]:
    return {
        element.target_fullname
        for constraint in model.__table__.constraints
        if isinstance(constraint, ForeignKeyConstraint)
        for element in constraint.elements
    }


def test_ownership_and_version_foreign_keys_are_explicit() -> None:
    assert "users.id" in foreign_key_targets(Course)
    assert {"courses.id", "users.id"} <= foreign_key_targets(Membership)
    assert {"courses.id", "users.id", "rubric_versions.id"} <= foreign_key_targets(
        Assignment
    )
    assert "template_versions.id" in foreign_key_targets(AssignmentRequirement)
    assert {"assignments.id", "users.id"} <= foreign_key_targets(Submission)
    assert "submissions.id" in foreign_key_targets(DocumentVersion)
    assert {"document_versions.id", "rubric_versions.id"} <= foreign_key_targets(
        AnalysisJob
    )


def test_critical_constraints_and_indexes_have_stable_names() -> None:
    names = {
        item.name
        for table in Base.metadata.tables.values()
        for item in (*table.constraints, *table.indexes)
        if isinstance(item, (CheckConstraint, Index))
    }
    assert {
        "ck_users_roles_not_empty",
        "ck_assignments_publication_state",
        "ck_audit_events_actor",
        "ck_audit_events_snapshots",
        "uq_analysis_jobs_active_document_rubric",
    } <= names
```

- [ ] **Step 3: Run RED and confirm the expected missing-symbol failure**

Run: `cd backend && uv run pytest tests/test_models.py -q`

Expected: collection fails because the 12 symbols do not yet exist in `app.models`; no syntax/configuration error is acceptable as the RED reason.

---

### Task 2: Add enums, mixins, identity, and course ownership

**Files:**
- Create: `backend/app/models/enums.py`
- Create: `backend/app/models/mixins.py`
- Create: `backend/app/models/identity.py`
- Create: `backend/app/models/course.py`
- Modify: `backend/app/models/__init__.py`

- [ ] **Step 1: Define persisted enums with exact uppercase values**

Use `StrEnum` classes with these members and no aliases:

```python
class UserRole(StrEnum):
    ADMIN = "ADMIN"
    TEACHER = "TEACHER"
    STUDENT = "STUDENT"


class UserStatus(StrEnum):
    ACTIVE = "ACTIVE"
    LOCKED = "LOCKED"


class MembershipRole(StrEnum):
    TEACHER = "TEACHER"
    STUDENT = "STUDENT"


class MembershipStatus(StrEnum):
    ACTIVE = "ACTIVE"
    INACTIVE = "INACTIVE"


class AssignmentStatus(StrEnum):
    DRAFT = "DRAFT"
    OPEN = "OPEN"
    CLOSED = "CLOSED"
    ARCHIVED = "ARCHIVED"


class RubricStatus(StrEnum):
    DRAFT = "DRAFT"
    PUBLISHED = "PUBLISHED"
    ARCHIVED = "ARCHIVED"


class DocumentStatus(StrEnum):
    UPLOADING = "UPLOADING"
    VALIDATING = "VALIDATING"
    INVALID = "INVALID"
    QUEUED = "QUEUED"
    PROCESSING = "PROCESSING"
    AWAITING_REVIEW = "AWAITING_REVIEW"
    APPROVED = "APPROVED"
    PUBLISHED = "PUBLISHED"
    PROCESSING_FAILED = "PROCESSING_FAILED"


class AnalysisJobStatus(StrEnum):
    QUEUED = "QUEUED"
    RUNNING = "RUNNING"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class AuditActorType(StrEnum):
    USER = "USER"
    SYSTEM = "SYSTEM"
```

Define one helper returning `sqlalchemy.Enum` with `values_callable=lambda enum: [member.value for member in enum]`, `validate_strings=True`, and the supplied stable PostgreSQL type name.

- [ ] **Step 2: Define typed mapped-column mixins**

`UUIDPrimaryKeyMixin.id` uses `postgresql.UUID(as_uuid=True)`, `primary_key=True`, and `default=uuid4`. `TimestampMixin` defines timezone-aware `created_at` and `updated_at` with `server_default=func.now()`; `updated_at` also uses `onupdate=func.now()`. `RevisionMixin.revision` is an integer with Python/server default 1.

- [ ] **Step 3: Implement `User`, `Course`, and `Membership` exactly as approved**

Use the columns and constraints in design sections 4.1 and 4.2. Required schema details:

- `users.email` length 320 and `uq_users_email_lower` unique expression index on `lower(email)`;
- `users.roles` is `ARRAY(user_role)` with `default=list` and `ck_users_roles_not_empty` using `cardinality(roles) > 0`;
- `courses.owner_teacher_id` and membership FKs use `ondelete="RESTRICT"`;
- `memberships` has `uq_memberships_course_user_role`;
- all relationships use explicit `back_populates`; relationships involving multiple User FKs specify `foreign_keys`.

- [ ] **Step 4: Export the implemented classes temporarily**

Update `app/models/__init__.py` to import the four supporting enum types needed by callers and the three implemented models. Do not create compatibility aliases such as `CourseMembership`.

- [ ] **Step 5: Run the focused test and confirm RED advances**

Run: `cd backend && uv run pytest tests/test_models.py -q`

Expected: collection now fails only for the next missing model symbol, proving the first slice imports and maps.

---

### Task 3: Add assignment and versioned rubric aggregates

**Files:**
- Create: `backend/app/models/assignment.py`
- Create: `backend/app/models/rubric.py`
- Modify: `backend/app/models/__init__.py`

- [ ] **Step 1: Implement `Assignment` and `AssignmentRequirement`**

Use typed columns and exact stable constraint names:

- `ck_assignments_max_submissions` for `max_submissions BETWEEN 1 AND 5`;
- `ck_assignments_publication_state` for DRAFT/null published time, OPEN/published and not closed, CLOSED/ARCHIVED with published and closed times;
- `uq_assignment_requirements_position` on `(assignment_id, position)`;
- positive nullable file/page limits;
- FK to `template_versions.id` remains a string FK so module import order does not create a second metadata registry.

- [ ] **Step 2: Implement `RubricVersion`**

Required fields: UUID grouping `rubric_id`, positive `version_number`, status, name/description, calculation method, numeric total weight, owner/creator/source FKs, publication time, revision and timestamps. Required uniqueness: `(rubric_id, version_number)`. Required checks: positive version, weight 0..100, publication timestamp consistent with status, revision positive.

- [ ] **Step 3: Implement `CriterionVersion`**

Required fields: stable `criterion_id`, parent `rubric_version_id`, code/title/description/scope, numeric weight, position, enabled flag, evaluation method, JSONB `levels`, `evaluator_config`, `evidence_requirements`, revision and timestamps. Add uniqueness for parent+criterion, parent+code, and parent+position. Check levels is a JSON array; evaluator/evidence are JSON objects; weight is 0..100; position/revision are positive.

- [ ] **Step 4: Implement `TemplateVersion`**

Use stable `template_id` plus positive version, owner/creator FKs, structure JSON object, private `storage_key`, optional 64-character lowercase hex checksum, created timestamp, and unique `(template_id, version_number)`.

- [ ] **Step 5: Export all seven models implemented so far**

Update `app/models/__init__.py`; retain one canonical import per class and an explicit `__all__`.

- [ ] **Step 6: Run focused RED again**

Run: `cd backend && uv run pytest tests/test_models.py -q`

Expected: collection fails only for `Submission`, `DocumentVersion`, `AnalysisJob`, or `AuditEvent` still missing.

---

### Task 4: Complete submission, analysis, audit, and metadata import

**Files:**
- Create: `backend/app/models/submission.py`
- Create: `backend/app/models/analysis.py`
- Create: `backend/app/models/audit.py`
- Modify: `backend/app/models/__init__.py`
- Modify: `backend/alembic/env.py`

- [ ] **Step 1: Implement `Submission` and `DocumentVersion`**

`Submission` has Assignment/Student restricted FKs and unique `(assignment_id, student_id)`. `DocumentVersion` has positive version, optional self-referential previous version, private storage metadata, lowercase SHA-256, lifecycle status, failure fields, timestamps, and unique `(submission_id, version_number)` plus `(submission_id, sha256)`.

- [ ] **Step 2: Implement `AnalysisJob`**

Use restricted FKs to document/rubric versions, attempt counters, required JSON object snapshot, lifecycle timestamps/error fields, timestamps, and checks for attempt bounds. Define:

```python
Index(
    "uq_analysis_jobs_active_document_rubric",
    "document_version_id",
    "rubric_version_id",
    unique=True,
    postgresql_where=column("status").in_(["QUEUED", "RUNNING"]),
)
```

Use a PostgreSQL-correct status expression that compiles against the native enum; if SQLAlchemy requires it, replace `column("status")` with `text("status IN ('QUEUED', 'RUNNING')")`.

- [ ] **Step 3: Implement `AuditEvent`**

Use resource/action fields, `actor_type`, restricted nullable actor FK, `before`/`after` JSONB, nonblank reason, and occurred timestamp. Add `ck_audit_events_actor`, `ck_audit_events_snapshots`, `ck_audit_events_before_object`, `ck_audit_events_after_object`, and `ck_audit_events_reason_not_blank`.

- [ ] **Step 4: Complete the import boundary**

`app/models/__init__.py` imports/exports exactly the 12 required classes. In `alembic/env.py`, add `import app.models  # noqa: F401` after application imports so `target_metadata` is complete without referencing private class names.

- [ ] **Step 5: Run GREEN metadata tests**

Run: `cd backend && uv run pytest tests/test_models.py -q`

Expected: all metadata tests pass. If mapper configuration fails, fix relationship/FK ambiguity rather than weakening the test.

- [ ] **Step 6: Run existing tests**

Run: `cd backend && uv run pytest tests/test_health.py -q`

Expected: health contract remains passing and no model import opens a database connection.

---

### Task 5: Write the reversible PostgreSQL migration

**Files:**
- Create: `backend/alembic/versions/20260825_0002_create_domain_schema.py`

- [ ] **Step 1: Add revision metadata and reusable enum objects**

Set `revision = "20260825_0002"`, `down_revision = "20260825_0001"`, and no branch/dependency labels. Define `postgresql.ENUM(..., create_type=False)` objects for every enum in `enums.py`. Upgrade explicitly calls `.create(op.get_bind(), checkfirst=False)` in dependency order; downgrade drops them in reverse.

- [ ] **Step 2: Create all 12 tables with migration-local definitions**

Mirror the model columns, defaults, named PK/FK/unique/check constraints, and indexes exactly. Do not import ORM model classes into the revision. Use `postgresql.ARRAY`, `postgresql.JSONB`, `postgresql.UUID(as_uuid=True)`, and timezone-aware `sa.DateTime`.

- [ ] **Step 3: Add role and ownership trigger functions**

Create PL/pgSQL functions that raise SQLSTATE `23514` with stable messages:

- `validate_course_owner_role()` — owner contains `TEACHER` in `users.roles`;
- `validate_membership_role()` — membership role text exists in the target User role array;
- `prevent_invalid_user_role_removal()` — updated roles cannot invalidate owned Courses or Membership rows;
- `validate_submission_student_membership()` — Student global role and ACTIVE Student membership exist in Assignment's Course.

Attach BEFORE INSERT/UPDATE triggers to the relevant tables and a BEFORE UPDATE OF roles trigger to users.

- [ ] **Step 4: Add rubric immutability triggers**

Create separate functions and triggers with these exact conditions:

```sql
EXISTS (
    SELECT 1
    FROM assignments AS a
    JOIN submissions AS s ON s.assignment_id = a.id
    WHERE a.rubric_version_id = OLD.id
)
```

for RubricVersion, and the same join using `OLD.rubric_version_id` for CriterionVersion. Both triggers fire BEFORE UPDATE OR DELETE. The Assignment trigger fires BEFORE UPDATE OF `rubric_version_id` and rejects a changed FK when a Submission exists for `OLD.id`. Error messages identify `rubric_version`, `criterion_version`, or `assignment rubric` as immutable after the first submission.

- [ ] **Step 5: Add AuditEvent append-only trigger**

Create a trigger function that always raises SQLSTATE `23514` for UPDATE or DELETE and attach it BEFORE UPDATE OR DELETE on `audit_events`.

- [ ] **Step 6: Implement symmetric downgrade**

Drop triggers before functions, then indexes/tables in reverse FK order, then enum types in reverse creation order. The downgrade target is exactly revision `20260825_0001`.

- [ ] **Step 7: Run static migration import check**

Run: `cd backend && uv run python -m compileall -q app alembic`

Expected: exit 0 with no output.

---

### Task 6: Test PostgreSQL invariants on the real migration

**Files:**
- Create: `backend/tests/test_domain_invariants.py`
- Modify: `backend/pyproject.toml` only if registering `database` marker is used

- [ ] **Step 1: Write the opt-in database test harness**

Use a normal synchronous pytest function calling `asyncio.run`, so no pytest-asyncio dependency is added. Skip unless `RUN_DATABASE_TESTS == "1"`. Create a fresh async engine from `get_settings().database_url`, open a connection/outer transaction, and roll it back at the end. Use nested transactions for every expected database exception so one rejected statement does not abort the whole test.

- [ ] **Step 2: Insert a complete valid graph**

Insert unique Teacher and Student users, Course, ACTIVE Student Membership, two RubricVersions, one CriterionVersion, Assignment, and Submission. Supply UUID parameters and cast literal role arrays/statuses to the named PostgreSQL enum types in raw SQL.

- [ ] **Step 3: Assert all mandatory failures behaviorally**

Using `pytest.raises(DBAPIError, match=...)` around a nested transaction, assert rejection of:

- Course owned by a User without TEACHER role;
- Membership whose role is absent from User.roles;
- removal of a role used by Course ownership or Membership;
- Submission by a Student without active Course membership;
- RubricVersion UPDATE and DELETE after a Submission;
- CriterionVersion UPDATE and DELETE after a Submission;
- Assignment `rubric_version_id` change after a Submission;
- USER AuditEvent without `actor_user_id` and SYSTEM AuditEvent with one;
- AuditEvent UPDATE and DELETE.

- [ ] **Step 4: Run RED before applying the new migration**

With PostgreSQL at revision `20260825_0001`, run the integration test in the container/host environment with `RUN_DATABASE_TESTS=1`.

Expected: fail because domain tables do not exist. This is the trigger/migration RED proof.

- [ ] **Step 5: Upgrade and run GREEN**

Run `alembic upgrade head` against Docker PostgreSQL, then run the same test with `RUN_DATABASE_TESTS=1`.

Expected: pass; every rejection comes from the intended constraint/trigger message.

---

### Task 7: Final validation, review, and delivery commit

**Files:** all changed files from Tasks 1–6

- [ ] **Step 1: Run format/lint/test gates**

From `backend/`:

```bash
uv run ruff check .
uv run black --check .
uv run pytest
```

Expected: all exit 0. The default pytest run may report the database suite skipped because Docker behavior is verified separately with `RUN_DATABASE_TESTS=1`.

- [ ] **Step 2: Prove migration downgrade and re-upgrade**

Against Docker PostgreSQL:

```bash
alembic upgrade head
alembic current
alembic downgrade 20260825_0001
alembic current
alembic upgrade head
alembic current
```

Expected revisions in order: `20260825_0002`, `20260825_0001`, `20260825_0002`. Run the integration invariant test after the final upgrade.

- [ ] **Step 3: Request independent review**

Reviewer scope: schema correctness, PostgreSQL DDL symmetry, trigger bypasses, cross-role ownership, audit completeness, no API/frontend scope leak, and documentation impact. Fix every confirmed in-scope defect and repeat focused checks.

- [ ] **Step 4: Verify scope and secrets before staging**

Confirm changed paths contain no `frontend/` or `backend/app/api/routers/` entries and stage only T-006 model, migration, test, and plan files. Never stage `.env` or credentials.

- [ ] **Step 5: Commit implementation**

Commit with:

```bash
git commit -m "feat(backend): add domain schema and migration"
```

- [ ] **Step 6: Report in the required format**

Return exactly three top-level sections: `Đã triển khai`, `Kiểm chứng`, and `HEAD commit`. List exact validation commands/results and the final commit SHA; identify any remaining risk only if observed.
