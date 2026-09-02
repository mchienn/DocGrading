# Analysis Dispatch Outbox Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Guarantee that every committed `QUEUED` analysis job retains a durable worker wake-up across API crashes and broker publication failures.

**Architecture:** Store a unique pending dispatch row in PostgreSQL in the same transaction as each queued job transition. Drain due rows immediately after commit and through a one-second FastAPI lifespan poller using bounded Celery publication, exponential backoff, and `FOR UPDATE SKIP LOCKED`.

**Tech Stack:** Python 3.13, FastAPI, SQLAlchemy 2 async, PostgreSQL 17, Alembic, Celery 5.6, Redis 7, pytest, Ruff, Black.

---

### Task 1: Add the outbox schema and migration safety contract

**Files:**
- Create: `backend/alembic/versions/20260829_0007_analysis_job_dispatch_outbox.py`
- Modify: `backend/app/models/analysis.py`
- Modify: `backend/app/models/__init__.py`
- Modify: `backend/tests/test_t009_migration_roundtrip.py`
- Create: `backend/tests/test_t009_analysis_dispatch.py`

- [x] **Step 1: Add failing model and migration tests**

Add assertions that SQLAlchemy metadata exposes `analysis_job_dispatches` with one unique `analysis_job_id`, a non-negative attempt constraint, and the due-row index. In the real-PostgreSQL migration test:

1. downgrade to `20260828_0006`;
2. insert a valid queued analysis job using the existing domain fixture helpers;
3. upgrade to `20260829_0007`;
4. assert exactly one dispatch row references that job and the compatibility trigger exists;
5. transition a job to `QUEUED` after the upgrade and assert the trigger creates its dispatch;
6. assert downgrade raises while the row remains;
7. delete the row, downgrade to `20260828_0006`, then upgrade to head again.

Core assertions:

```python
row = connection.execute(
    sa.text(
        "SELECT analysis_job_id, attempt_count "
        "FROM public.analysis_job_dispatches "
        "WHERE analysis_job_id = :job_id"
    ),
    {"job_id": job_id},
).one()
assert row.analysis_job_id == job_id
assert row.attempt_count == 0

with pytest.raises(sa.exc.DBAPIError, match="pending analysis job dispatch"):
    command.downgrade(alembic_config, "20260828_0006")
```

- [x] **Step 2: Verify RED**

Run from `backend/` with the configured PostgreSQL environment:

```bash
RUN_DATABASE_TESTS=1 uv run pytest \
  tests/test_models.py \
  tests/test_t009_migration_roundtrip.py \
  tests/test_t009_analysis_dispatch.py -q
```

Expected: failures because the ORM model, revision `0007`, backfill, and guarded downgrade do not exist.

- [x] **Step 3: Add `AnalysisJobDispatch`**

In `backend/app/models/analysis.py`, define an internal model using the existing UUID and timestamp mixins:

```python
class AnalysisJobDispatch(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "analysis_job_dispatches"
    __table_args__ = (
        sa.CheckConstraint(
            "attempt_count >= 0",
            name="ck_analysis_job_dispatches_attempt_count_nonnegative",
        ),
        sa.Index(
            "ix_analysis_job_dispatches_due",
            "next_attempt_at",
            "created_at",
            "id",
        ),
    )

    analysis_job_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        sa.ForeignKey(
            "analysis_jobs.id",
            ondelete="CASCADE",
            name="fk_analysis_job_dispatches_analysis_job_id_analysis_jobs",
        ),
        unique=True,
        nullable=False,
    )
    attempt_count: Mapped[int] = mapped_column(
        sa.Integer, default=0, server_default=sa.text("0"), nullable=False
    )
    next_attempt_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
    )
```

Add one-to-one `AnalysisJob.dispatch` / `AnalysisJobDispatch.analysis_job` relationships and export the new model from `backend/app/models/__init__.py` so Alembic metadata imports it.

- [x] **Step 4: Implement revision `0007`**

The migration must:

```python
revision = "20260829_0007"
down_revision = "20260828_0006"
```

In `upgrade()`:

1. execute `SET search_path TO public`;
2. acquire `ACCESS EXCLUSIVE` on `public.analysis_jobs` before creating the outbox, blocking mixed-version job writers until the trigger is installed;
3. create the schema-qualified table, FK, unique constraint, check constraint, and due index;
4. install a schema-pinned `AFTER INSERT OR UPDATE OF status` trigger on `public.analysis_jobs` that inserts a dispatch for every inserted or newly `QUEUED` row;
5. backfill queued jobs atomically:

```sql
INSERT INTO public.analysis_job_dispatches
    (id, analysis_job_id, attempt_count, next_attempt_at, created_at, updated_at)
SELECT
    gen_random_uuid(), id, 0, now(), now(), now()
FROM public.analysis_jobs
WHERE status::text = 'QUEUED'
ON CONFLICT (analysis_job_id) DO NOTHING
```

In `downgrade()`, quiesce the application, acquire `ACCESS EXCLUSIVE` on `public.analysis_jobs` and then `public.analysis_job_dispatches`, drop the trigger/function, raise from a PostgreSQL `DO $$` block when any pending row exists, then drop the due index and table only when empty.

- [x] **Step 5: Verify schema GREEN**

Rerun the Task 1 test command. Expected: model, upgrade backfill, compatibility-trigger, guarded downgrade, explicit drain, and re-upgrade all pass.

### Task 2: Enqueue dispatch rows atomically with queued jobs

**Files:**
- Create: `backend/app/services/analysis_dispatch.py`
- Modify: `backend/app/services/analysis_job.py`
- Modify: `backend/app/services/submission.py`
- Modify: `backend/tests/test_t009_analysis_dispatch.py`
- Modify: `backend/tests/test_t009_upload_completion.py`
- Modify: `backend/tests/test_t009_job_concurrency.py`

- [x] **Step 1: Add failing atomic-enqueue tests**

Using real PostgreSQL sessions, prove:

```python
async def _dispatch_count(db: AsyncSession, job_id: uuid.UUID) -> int:
    return (
        await db.execute(
            sa.select(sa.func.count())
            .select_from(AnalysisJobDispatch)
            .where(AnalysisJobDispatch.analysis_job_id == job_id)
        )
    ).scalar_one()


job = await create_or_get_job(
    db,
    document_version_id=doc_id,
    rubric_version_id=rubric_id,
)
await db.commit()
assert await _dispatch_count(other_db, job.id) == 1

same_job = await create_or_get_job(
    db,
    document_version_id=doc_id,
    rubric_version_id=rubric_id,
)
await db.commit()
assert same_job.id == job.id
assert await _dispatch_count(other_db, job.id) == 1
```

Add rollback coverage by creating/retrying a queued job, rolling back, and asserting another session sees neither the transition nor a new dispatch row. Extend idempotent upload completion and `ERROR → QUEUED` retry tests to assert one pending dispatch.

- [x] **Step 2: Verify RED**

```bash
RUN_DATABASE_TESTS=1 uv run pytest \
  tests/test_t009_analysis_dispatch.py \
  tests/test_t009_upload_completion.py \
  tests/test_t009_job_concurrency.py -q
```

Expected: the new outbox-count assertions fail.
- [x] **Step 3: Implement idempotent enqueue**

Implement one unique pending dispatch per analysis job. Normal queued transitions use `ON CONFLICT (analysis_job_id) DO NOTHING`; explicit recovery schedules such as active-lease redelivery and manual retry pass `next_attempt_at` and update the existing row's due time.

- [x] **Step 4: Wire every queued transition**

Enqueue the dispatch in the same database transaction as job creation, upload completion, and `ERROR → QUEUED` retry. Keep the request response independent from the post-commit publisher.

- [x] **Step 5: Verify atomic enqueue GREEN**

Rerun the Task 2 test command. Expected: queued transitions create exactly one durable dispatch, rollback removes both changes, idempotent transitions do not duplicate rows, and manual retry resets an existing backoff schedule to its new `queued_at`.


### Task 3: Publish due outbox rows safely

**Files:**
- Modify: `backend/app/services/analysis_dispatch.py`
- Modify: `backend/app/workers/celery_app.py`
- Modify: `backend/tests/test_t009_analysis_dispatch.py`

- [x] **Step 1: Add failing publisher tests**

Cover four observable outcomes with a real database and a patched Celery producer:

```python
sent = await dispatch_due_analysis_jobs(db, limit=10)
await db.commit()
assert sent == 1
assert await _dispatch_count(check_db, job_id) == 0
```

For producer failure/timeout, assert the row remains, `attempt_count == 1`, and `next_attempt_at > before`. For two concurrent sessions, block the first producer while the second executes and assert the second skips the locked row. Simulate publish-before-delete by forcing the first transaction to roll back after producer success; the next attempt may publish again, and `claim_job_by_id()` still has one winner.

- [x] **Step 2: Verify RED**

```bash
RUN_DATABASE_TESTS=1 uv run pytest tests/test_t009_analysis_dispatch.py -q
```

Expected: publisher symbols are missing.

- [x] **Step 3: Implement bounded publication**

Add constants:

```python
_DISPATCH_BATCH_SIZE = 10
_PUBLISH_TIMEOUT_SECONDS = 5.0
_MAX_BACKOFF_SECONDS = 60
```

Publish outside the event loop:

```python
async def _publish_analysis_job(job_id: uuid.UUID) -> None:
    from app.workers.tasks import process_analysis_job

    async with asyncio.timeout(_PUBLISH_TIMEOUT_SECONDS):
        await asyncio.to_thread(
            process_analysis_job.apply_async,
            args=(str(job_id),),
            retry=False,
        )
```

Select due rows with `next_attempt_at <= now()`, deterministic ordering, `.with_for_update(skip_locked=True)`, and a bounded limit. Delete successful rows. For `Exception` other than cancellation, retain the row and set:

```python
dispatch.attempt_count += 1
delay = min(2 ** min(dispatch.attempt_count, 6), _MAX_BACKOFF_SECONDS)
dispatch.next_attempt_at = datetime.now(UTC) + timedelta(seconds=delay)
```

Never persist or log exception text. Propagate `CancelledError`.

- [x] **Step 4: Bound Celery Redis producer I/O**

In `backend/app/workers/celery_app.py`, keep task retry publication enabled because `Task.retry()` uses the same producer path for lease-safe worker redelivery:

```python
task_publish_retry=True,
broker_transport_options={
    "socket_connect_timeout": 3,
    "socket_timeout": 3,
    "retry_on_timeout": False,
},
```

The outbox's own `apply_async(..., retry=False)` disables producer retry only for its bounded publication attempt. Retain late acknowledgement and worker-loss rejection.

When a targeted worker invocation finds an unexpired active lease, it upserts the dispatch row with the lease-expiry time before calling `Task.retry()`. The retry schedule updates an existing row as well as creating a missing one, so a publish-before-delete race cannot remove the only durable wake-up.

- [x] **Step 5: Verify publisher GREEN**

Rerun the Task 3 test command. Expected: success/delete, failure/backoff, timeout responsiveness, concurrent `SKIP LOCKED`, and duplicate-safe claim tests pass.

### Task 4: Add immediate and lifespan recovery dispatch

**Files:**
- Modify: `backend/app/services/analysis_dispatch.py`
- Modify: `backend/app/api/routers/submissions.py`
- Modify: `backend/app/main.py`
- Modify: `backend/tests/test_t009_analysis_dispatch.py`
- Modify: `backend/tests/test_t009_contracts.py`

- [x] **Step 1: Add failing route and poller tests**

Assert both routes call the outbox drain only after their request-session commit. Patch immediate publication to fail and assert the route still returns the committed response instead of raising. Add a poller recovery test where the first session factory/execute fails and the next fresh session drains successfully. Add a lifespan test that cancels and awaits the poller without leaking an asyncio task.

Expected route order:

```python
assert events == ["commit", "dispatch"]
```

Expected failure behavior:

```python
response = client.post(...)
assert response.status_code == 202
assert pending_dispatch_count == 1
```
- [x] **Step 3: Implement immediate drain wrapper**

Create a wrapper that owns a fresh session, shares the process-local publisher gate with the poller, and never invalidates the successful request transaction:

```python
async def dispatch_analysis_job_now(job_id: uuid.UUID) -> bool:
    try:
        async with asyncio.timeout(_PUBLISH_TIMEOUT_SECONDS):
            async with _dispatch_gate, _session_factory()() as db:
                sent = await dispatch_due_analysis_jobs(db, job_id=job_id, limit=1)
                await db.commit()
                return sent == 1
    except asyncio.CancelledError:
        raise
    except TimeoutError:
        return False
    except Exception:
        return False
```

The total timeout includes gate acquisition, database work, and broker publication. The batch function handles producer errors as row backoff; the outer catches cover transient database/session failures without exposing details.

- [x] **Step 4: Replace router `.delay()` calls**

After `await db.commit()`, call:

```python
if job.status is AnalysisJobStatus.QUEUED:
    await dispatch_analysis_job_now(job.id)
```

Apply this to completion and retry. Import `AnalysisJobStatus` and the dispatch wrapper directly; remove lazy imports of `process_analysis_job` from the router.

- [x] **Step 5: Implement the fresh-session poller and lifespan ownership**

The loop sleeps before the first poll and creates a new session every iteration:

```python
async def run_analysis_dispatch_poller() -> None:
    await asyncio.sleep(1)
    while True:
        try:
            async with _session_factory()() as db:
                try:
                    await dispatch_due_analysis_jobs(db, limit=_DISPATCH_BATCH_SIZE)
                    await db.commit()
                except BaseException:
                    await db.rollback()
                    raise
        except asyncio.CancelledError:
            raise
        except Exception:
            pass
        await asyncio.sleep(1)
```

In FastAPI lifespan, create the task before `yield`; in `finally`, cancel it and await it under `contextlib.suppress(asyncio.CancelledError)`.

- [x] **Step 6: Verify route and recovery GREEN**

Rerun the Task 4 tests. Expected: commit-before-dispatch ordering, 202 on broker failure, fresh-session recovery, and graceful cancellation all pass.

### Task 5: Reconcile documentation and verify the integrated result

**Files:**
- Modify: `docs/design/PROJECT_SCOPE_BUSINESS_RULES_TECH_STACK.md`
- Modify: `docs/superpowers/plans/2026-08-28-pdf-upload-storage-job-lifecycle.md`
- Modify: `docs/superpowers/plans/2026-08-29-analysis-dispatch-outbox.md`
- Modify: `docs/superpowers/plans/2026-08-29-pdf-clipping-fail-closed.md`
- Reference: `docs/superpowers/specs/2026-08-29-t009-clipping-outbox-hardening-design.md`

- [x] **Step 1: Reconcile canonical architecture**

Document that queued job transitions atomically create a PostgreSQL dispatch row; immediate publication is only a latency optimization; a FastAPI poller recovers pending rows; delivery is at least once; and the design still uses no Celery Beat/canvas.

Record the guarded downgrade prerequisite:

```text
Before downgrading below revision 0007, require zero rows in
public.analysis_job_dispatches. Drain or explicitly reconcile pending rows;
the migration refuses to discard them.
```

- [x] **Step 2: Run focused verification**

```bash
RUN_DATABASE_TESTS=1 uv run pytest \
  tests/test_t009_analysis_dispatch.py \
  tests/test_t009_upload_completion.py \
  tests/test_t009_job_concurrency.py \
  tests/test_t009_job_recovery.py \
  tests/test_t009_migration_roundtrip.py \
  tests/test_t009_pdf_scan_detection.py \
  tests/test_t009_pdf_decoded_limit.py \
  tests/test_t009_pdf_behavior.py -q
```

Expected: all focused tests pass.

- [x] **Step 3: Run migration round-trip**

Against PostgreSQL 17 with no pending dispatch rows:

```bash
uv run alembic upgrade head
uv run alembic downgrade 20260828_0006
uv run alembic upgrade head
```

Expected: all commands succeed. Separately retain the automated test proving downgrade fails when a pending row exists.

- [x] **Step 4: Run full verification**

```bash
uv run ruff check .
uv run black --check .
RUN_DATABASE_TESTS=1 uv run pytest -v
```

Expected: Ruff and Black succeed and the entire test suite passes.

- [ ] **Step 5: Review, commit, push, and request CodeRabbit**

Run one focused independent review covering clipping fail-closed behavior, outbox crash windows, migration safety, concurrency, event-loop responsiveness, and privacy. Fix only verified findings and rerun affected/full verification.

Create one atomic conventional implementation commit, push the existing PR branch without force, verify remote HEAD equals local HEAD, assign the verified SHA with `FINAL_SHA="$(git rev-parse HEAD)"`, then expand that variable in this comment:

```text
@coderabbitai full review

Please review exact final PR HEAD `${FINAL_SHA}`.
```

Wait for CodeRabbit, report its final result verbatim, and stop for the user's decision if any finding remains.
