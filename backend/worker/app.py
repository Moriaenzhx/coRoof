from celery import Celery

from app.core.config import settings

settings().check_deployment()
celery = Celery("coroof", broker=settings().redis_url, backend=settings().redis_url)
celery.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone="UTC",
    enable_utc=True,
    broker_connection_retry_on_startup=True,
    task_acks_late=True,
    worker_prefetch_multiplier=1,
)


@celery.task(name="coroof.ping")  # type: ignore[untyped-decorator]
def ping() -> str:
    """Read-only smoke task, safe to retry; no business facts are changed."""
    return "pong"
