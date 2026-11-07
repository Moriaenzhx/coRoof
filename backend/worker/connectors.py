from collections.abc import Callable

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.infrastructure.db import session_factory
from app.infrastructure.models import now
from app.modules.connectors.models import SyncOutbox
from app.modules.connectors.service import process, recover
from worker.app import celery


def dispatch(db: Session, publish: Callable[[str, str, int], None]) -> int:
    recover(db)
    count = 0
    for _ in range(50):
        row = db.scalar(
            select(SyncOutbox)
            .where(SyncOutbox.published_at.is_(None), SyncOutbox.available_at <= now())
            .order_by(SyncOutbox.available_at, SyncOutbox.id)
            .with_for_update(skip_locked=True)
            .limit(1)
        )
        if row is None:
            db.rollback()
            break
        try:
            publish(row.organization_id, row.run_id, row.run_version)
        except Exception:
            db.rollback()  # Broker down or ambiguous publish: retain outbox, redelivery is safe.
            break
        row.published_at = now()
        db.commit()
        count += 1
    return count


@celery.task(name="coroof.connector.dispatch")  # type: ignore[untyped-decorator]
def dispatch_pending() -> int:
    with session_factory()() as db:
        return dispatch(
            db,
            lambda org, run, version: celery.send_task(
                "coroof.connector.process", args=[org, run, version]
            ),
        )


@celery.task(name="coroof.connector.process", soft_time_limit=70, time_limit=80)  # type: ignore[untyped-decorator]
def process_page(organization_id: str, run_id: str, version: int) -> None:
    with session_factory()() as db:
        process(db, organization_id, run_id, version)
