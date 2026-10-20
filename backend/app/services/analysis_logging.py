"""Timing diagnostics without document text, prompts or provider credentials."""

import inspect
import logging
from contextlib import contextmanager
from contextvars import ContextVar
from functools import wraps
from time import perf_counter

logger = logging.getLogger(__name__)
job_context = ContextVar("analysis_job_id", default="-")
stage_context = ContextVar("analysis_stage", default="-")


def log_event(event: str, **metrics) -> None:
    logger.info(
        "analysis event=%s job=%s stage=%s %s",
        event,
        job_context.get(),
        stage_context.get(),
        " ".join(f"{key}={value}" for key, value in metrics.items()),
    )


def error_details(exc: Exception) -> dict:
    # Exception messages can contain document text or authenticated URLs.
    details = {"error_type": type(exc).__name__}
    if isinstance(getattr(exc, "errno", None), int):
        details["errno"] = exc.errno
    if isinstance(getattr(exc, "code", None), int):
        details["http_status"] = exc.code
    if exc.__cause__ is not None:
        details["cause_type"] = type(exc.__cause__).__name__
    tb = exc.__traceback__
    if tb is not None:
        while tb.tb_next is not None:
            tb = tb.tb_next
        details["location"] = f"{tb.tb_frame.f_code.co_name}:{tb.tb_lineno}"
    return details


@contextmanager
def timed_step(stage: str, **metrics):
    metrics = {"parent_stage": stage_context.get(), **metrics}
    token = stage_context.set(stage)
    started = perf_counter()
    log_event("start", **metrics)
    try:
        yield
    except Exception as exc:
        log_event(
            "failed",
            elapsed_s=round(perf_counter() - started, 3),
            **metrics,
            **error_details(exc),
        )
        raise
    else:
        log_event("done", elapsed_s=round(perf_counter() - started, 3), **metrics)
    finally:
        stage_context.reset(token)


def timed(stage: str):
    def decorate(function):
        if inspect.iscoroutinefunction(function):

            @wraps(function)
            async def async_wrapper(*args, **kwargs):
                with timed_step(stage):
                    return await function(*args, **kwargs)

            return async_wrapper

        @wraps(function)
        def wrapper(*args, **kwargs):
            with timed_step(stage):
                return function(*args, **kwargs)

        return wrapper

    return decorate
