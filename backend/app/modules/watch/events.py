"""SQLAlchemy transaction hook for all confirmed domain events; never enqueues from a draft."""

from sqlalchemy import event, insert
from sqlalchemy.orm import Session

from app.infrastructure.models import WorkEvent, now, uid
from app.modules.watch.models import WatchWake


@event.listens_for(Session, "after_flush")
def wake_on_confirmed_event(db: Session, _: object) -> None:
    events = [row for row in db.new if isinstance(row, WorkEvent)]
    if events:
        # Flush has assigned IDs and inserted their parent rows. The Core insert
        # shares the caller's transaction: rollback cannot leave a wake behind.
        db.execute(
            insert(WatchWake),
            [
                {
                    "id": uid(),
                    "organization_id": row.organization_id,
                    "event_id": row.id,
                    "created_at": now(),
                }
                for row in events
            ],
        )
