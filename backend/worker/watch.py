"""Celery wakes bounded, persisted checks; no browser session or endless model loop."""

from collections.abc import Callable

from sqlalchemy.orm import Session

from app.infrastructure.db import session_factory
from app.modules.watch import runner, scheduler
from worker.app import celery


def dispatch(db: Session, publish: Callable[[str, str, int], None]) -> int:
    scheduler.recover(db)
    scheduler.merge_events(db)
    scheduler.schedule(db)
    return scheduler.publish(db, publish)


@celery.task(name="coroof.watch.dispatch", soft_time_limit=50, time_limit=60)  # type: ignore[untyped-decorator]
def dispatch_pending() -> int:
    with session_factory()() as db:
        return dispatch(
            db,
            lambda org, run, version: celery.send_task(
                "coroof.watch.process", args=[org, run, version]
            ),
        )


@celery.task(name="coroof.watch.process", soft_time_limit=150, time_limit=160)  # type: ignore[untyped-decorator]
def process_step(organization_id: str, run_id: str, version: int) -> None:
    with session_factory()() as db:
        runner.process(db, organization_id, run_id, version)
