"""Transactional outbox for durable analysis-job wake-ups."""

from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime, timedelta

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import _session_factory
from app.models.analysis import AnalysisJobDispatch

_DISPATCH_BATCH_SIZE = 10
_PUBLISH_TIMEOUT_SECONDS = 5.0
_MAX_BACKOFF_SECONDS = 60
_dispatch_gate = asyncio.Semaphore(1)
_active_publish_tasks: set[asyncio.Task[None]] = set()


def _forget_publish_task(task: asyncio.Task[None]) -> None:
    _active_publish_tasks.discard(task)
    if not task.cancelled():
        task.exception()


async def _publish_analysis_job(job_id: uuid.UUID) -> None:
    from app.workers.tasks import process_analysis_job

    async def publish() -> None:
        await asyncio.to_thread(
            process_analysis_job.apply_async,
            args=(str(job_id),),
            retry=False,
        )

    publish_task = asyncio.create_task(publish())
    _active_publish_tasks.add(publish_task)
    publish_task.add_done_callback(_forget_publish_task)
    try:
        async with asyncio.timeout(_PUBLISH_TIMEOUT_SECONDS):
            await asyncio.shield(publish_task)
    finally:
        if publish_task.done():
            _active_publish_tasks.discard(publish_task)


async def enqueue_analysis_job_dispatch(
    db: AsyncSession,
    analysis_job_id: uuid.UUID,
    *,
    next_attempt_at: datetime | None = None,
) -> None:
    """Ensure one pending dispatch exists in the caller's transaction."""
    values: dict[str, object] = {"analysis_job_id": analysis_job_id}
    if next_attempt_at is not None:
        values["next_attempt_at"] = next_attempt_at
    insert = pg_insert(AnalysisJobDispatch).values(**values)
    if next_attempt_at is None:
        stmt = insert.on_conflict_do_nothing(index_elements=["analysis_job_id"])
    else:
        stmt = insert.on_conflict_do_update(
            index_elements=["analysis_job_id"],
            set_={
                "next_attempt_at": insert.excluded.next_attempt_at,
                "updated_at": sa.func.now(),
            },
        )
    await db.execute(stmt)


async def dispatch_due_analysis_jobs(
    db: AsyncSession,
    *,
    job_id: uuid.UUID | None = None,
    limit: int = _DISPATCH_BATCH_SIZE,
) -> int:
    """Publish one bounded locked batch; the caller owns commit/rollback."""
    now = datetime.now(UTC)
    stmt = (
        sa.select(AnalysisJobDispatch)
        .where(AnalysisJobDispatch.next_attempt_at <= now)
        .order_by(
            AnalysisJobDispatch.next_attempt_at,
            AnalysisJobDispatch.created_at,
            AnalysisJobDispatch.id,
        )
        .with_for_update(skip_locked=True)
        .limit(min(max(1, limit), _DISPATCH_BATCH_SIZE))
    )
    if job_id is not None:
        stmt = stmt.where(AnalysisJobDispatch.analysis_job_id == job_id)
    dispatches = (await db.execute(stmt)).scalars().all()
    sent = 0
    for dispatch in dispatches:
        try:
            await _publish_analysis_job(dispatch.analysis_job_id)
        except asyncio.CancelledError:
            raise
        except Exception:
            dispatch.attempt_count += 1
            delay = min(
                2 ** min(dispatch.attempt_count, 6),
                _MAX_BACKOFF_SECONDS,
            )
            dispatch.next_attempt_at = datetime.now(UTC) + timedelta(seconds=delay)
        else:
            await db.delete(dispatch)
            sent += 1
    await db.flush()
    return sent


async def dispatch_analysis_job_now(job_id: uuid.UUID) -> bool:
    """Try one bounded post-commit dispatch without failing the request."""
    try:
        async with asyncio.timeout(_PUBLISH_TIMEOUT_SECONDS):
            async with _dispatch_gate, _session_factory()() as db:
                sent = await dispatch_due_analysis_jobs(
                    db,
                    job_id=job_id,
                    limit=1,
                )
                await db.commit()
                return sent == 1
    except asyncio.CancelledError:
        raise
    except TimeoutError:
        return False
    except Exception:
        return False


async def wait_for_analysis_dispatch_publications() -> None:
    """Join bounded broker calls still running during graceful shutdown."""
    publish_tasks = tuple(_active_publish_tasks)
    if publish_tasks:
        await asyncio.wait(
            publish_tasks,
            timeout=_PUBLISH_TIMEOUT_SECONDS,
        )


async def run_analysis_dispatch_poller() -> None:
    """Recover pending dispatches with a fresh session per iteration."""
    await asyncio.sleep(1)
    while True:
        try:
            async with _dispatch_gate, _session_factory()() as db:
                try:
                    await dispatch_due_analysis_jobs(
                        db,
                        limit=_DISPATCH_BATCH_SIZE,
                    )
                    await db.commit()
                except BaseException:
                    await db.rollback()
                    raise
        except asyncio.CancelledError:
            raise
        except Exception:
            pass
        await asyncio.sleep(1)
