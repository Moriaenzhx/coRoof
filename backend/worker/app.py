from celery import Celery

from app.core.config import settings
from app.modules.watch import events as watch_events  # noqa: F401

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
    imports=("worker.connectors", "worker.invitations", "worker.watch", "worker.agent"),
    beat_schedule={
        "connector-outbox": {"task": "coroof.connector.dispatch", "schedule": 10.0},
        "invitation-outbox": {"task": "coroof.invitation.dispatch", "schedule": 10.0},
        "continuous-agent": {"task": "coroof.watch.dispatch", "schedule": 10.0},
        "interactive-agent": {"task": "coroof.agent.dispatch", "schedule": 2.0},
    },
)


@celery.task(name="coroof.ping")  # type: ignore[untyped-decorator]
def ping() -> str:
    """Read-only smoke task, safe to retry; no business facts are changed."""
    return "pong"
