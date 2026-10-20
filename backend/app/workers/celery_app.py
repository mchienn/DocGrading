from celery import Celery
from celery.signals import worker_init

from app.core.config import get_settings

settings = get_settings()
celery_app = Celery(
    "docgrading",
    broker=settings.celery_broker_url,
    backend=settings.celery_result_backend,
    include=["app.workers.tasks"],
)
celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    result_accept_content=["json"],
    enable_utc=True,
    timezone="UTC",
    task_publish_retry=True,
    broker_transport_options={
        "socket_connect_timeout": 3,
        "socket_timeout": 3,
        "retry_on_timeout": False,
    },
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    worker_pool="threads",
    worker_concurrency=1,
)


@worker_init.connect
def preload_analysis_models(**kwargs):
    """Warm native models once in the long-lived threads worker process."""
    if not get_settings().logical_llm_enabled:
        return
    # Startup occurs before Celery configures logging; expose warm-up timings.
    celery_app.log.setup_logging_subsystem(loglevel="INFO")
    from app.services.analysis_logging import error_details, log_event
    from app.services.logical_pipeline import preload_models

    try:
        preload_models()
    except Exception as exc:
        log_event("models.preload_failed", **error_details(exc))
        # Do not accept jobs when the required models failed to initialize.
        raise SystemExit(1) from exc
