# Load, Metrics, Backup & Restore Smoke — T-022

**Scope:** Backend + DevOps only. Establish a measured real-stack baseline and prove PostgreSQL logical backup/restore before evaluator workloads are added. No frontend, evaluator, rule, LLM, or rubric behavior changes.

## Contract decisions

- Load runs against API, PostgreSQL 17, Redis 7, Celery worker, and LocalStack S3 from Docker Compose. No application dependency is mocked.
- Default load is 8 concurrent users for 30 seconds with 0.05-second think time. Each Student performs at most 5 complete upload-to-publish rounds because Assignment `max_submissions` is 5. Queue-list requests run concurrently for the full requested duration.
- Percentiles use nearest-rank over observed durations. HTTP rows measure response time. `job_claim` measures persisted queue wait, `AnalysisJob.started_at - AnalysisJob.queued_at`. Per-operation throughput is completed observations divided by actual total run duration.
- `GET /metrics` is outside `/api/v1`, requires an authenticated Admin session, and returns Prometheus text. It reuses the T-018 job-status aggregate. Metrics are `docgrading_analysis_jobs{status=...}`, `docgrading_analysis_queue_depth`, and `docgrading_analysis_job_age_seconds_avg`; age covers `QUEUED` and `RUNNING` jobs from `queued_at`.
- Backup uses PostgreSQL 17 `pg_dump --format=custom` with owner and ACL restoration disabled. Before/after source row counts must match or backup is rejected. `umask 077` protects generated files where host filesystem permissions support POSIX modes.
- Restore uses a dedicated internal Compose network and a PostgreSQL tmpfs service. It force-drops and recreates only `docgrading_restore`, restores in one transaction, compares every tracked table count, checks critical-flow relationships, and executes `TRUNCATE public.audit_events` expecting SQLSTATE-trigger failure.
- Load, backup, and restore scripts refuse non-development `APP_ENV`. Generated `artifacts/` and `backups/` paths are Git ignored. No connection string or password is logged.

## Reproduction

From repository root with `.env` copied from `.env.example`:

```bash
docker compose up --build
docker compose --profile smoke run --rm load-smoke
docker compose --profile ops run --rm backup
docker compose --profile ops run --rm restore-smoke
docker compose --profile smoke --profile ops config --quiet
```

A disposable Compose project can isolate baseline data from an existing development volume:

```bash
docker compose -p docgrading-t022 up --build
docker compose -p docgrading-t022 --profile smoke run --rm load-smoke
docker compose -p docgrading-t022 --profile ops run --rm backup
docker compose -p docgrading-t022 --profile ops run --rm restore-smoke
```

Do not add `down --volumes` to routine commands; it deletes that Compose project's development data.

## Verification results

Final baseline used disposable Compose project `docgrading-t022` with a new PostgreSQL volume. Configuration: 8 concurrent users, requested duration 30.0 seconds, actual duration 30.08150516600017 seconds, think time 0.05 seconds, 5 rounds per Student, 40 complete upload/claim/publish flows. Every measured operation had 0 errors.

| Operation | Observations | Errors | p50 ms | p95 ms | Throughput observations/s |
|---|---:|---:|---:|---:|---:|
| `job_claim` | 40 | 0 | 1520.8509999999999 | 2111.0350000000003 | 1.329720696463363 |
| `object_upload` | 40 | 0 | 12.578539000060118 | 24.734151999837195 | 1.329720696463363 |
| `publish` | 40 | 0 | 390.90862499961077 | 671.32563999985 | 1.329720696463363 |
| `submission_queue_list` | 1168 | 0 | 111.19383100049163 | 389.8698989996774 | 38.8278443367302 |
| `upload_complete` | 40 | 0 | 1535.751196000092 | 2178.4633819997907 | 1.329720696463363 |
| `upload_presign` | 40 | 0 | 1073.0305940005564 | 2723.6251430003904 | 1.329720696463363 |

These are baseline observations, not SLO claims. No benchmark input, timing, or result was adjusted to improve numbers.

### Backup/restore row-count comparison

| Table | Source | Restored |
|---|---:|---:|
| `users` | 10 | 10 |
| `courses` | 1 | 1 |
| `memberships` | 8 | 8 |
| `assignments` | 1 | 1 |
| `assignment_requirements` | 0 | 0 |
| `rubric_versions` | 1 | 1 |
| `criterion_versions` | 1 | 1 |
| `template_versions` | 0 | 0 |
| `submissions` | 8 | 8 |
| `document_versions` | 40 | 40 |
| `analysis_jobs` | 40 | 40 |
| `analysis_job_dispatches` | 0 | 0 |
| `document_irs` | 40 | 40 |
| `findings` | 0 | 0 |
| `evidence_anchors` | 0 | 0 |
| `review_locks` | 0 | 0 |
| `review_drafts` | 8 | 8 |
| `review_decisions` | 0 | 0 |
| `published_result_versions` | 40 | 40 |
| `review_requests` | 0 | 0 |
| `review_commands` | 80 | 80 |
| `notifications` | 40 | 40 |
| `sessions` | 10 | 10 |
| `audit_events` | 296 | 296 |

Restore smoke also returned `published flow rows=40`, `relationship orphans=0`, and retained 296 audit rows after rejected `TRUNCATE public.audit_events`.

An earlier attempt against the shared pre-existing development volume failed restore because a `document_versions.approved_by_user_id` referenced a missing user. That contaminated volume was not used for final numbers. Failure confirms restore smoke rejects inconsistent source data instead of reporting false success.

- `docker compose --profile smoke --profile ops config --quiet`: passed.
- Targeted backend tests on a separately migrated empty database: 9 passed. A first run against the populated load database correctly proved that T-018's active-Admin concurrency fixture requires database isolation; it was not used as validation evidence.
- Real-stack load, authenticated Prometheus response (`DONE=40`, other job statuses and active age `0`), non-Admin `403`, backup, restore, critical-flow join, row-count comparison, and audit TRUNCATE guard: passed.

## Final review

### Functional Correctness

No open finding. Independent read-only review confirmed endpoint coverage, timing semantics, concurrency configuration, real storage/worker path, Admin-authenticated metrics, and reuse of the T-018 status aggregate.

### Data Integrity & Integration

No open finding for requested contract. Custom dump restore uses a new database, one restore transaction, exact tracked-table counts, restored relationship checks, published critical-flow rows, and effective audit TRUNCATE rejection. First dirty-volume failure is retained above as evidence that invalid source data is not hidden.

### Security & Privacy

Security review found restore services initially shared the application network. Final Compose uses a dedicated `internal: true` restore network. Smoke scripts are development-only, backup permissions are restrictive, generated backup/result files are ignored, metrics requires Admin, restore PostgreSQL publishes no host port, and logs contain no password or connection string.

Local smoke backup is not a production backup system and is not encrypted by this task. Non-development execution is blocked; production encrypted-at-rest backup remains a deployment responsibility under AT-24/AT-27.
