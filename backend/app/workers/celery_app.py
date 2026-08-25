from celery import Celery

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
)
