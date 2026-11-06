from app.infrastructure.db import session_factory
from app.modules.identity import mail
from worker.app import celery


@celery.task(name="coroof.invitation.dispatch")  # type: ignore[untyped-decorator]
def dispatch_pending() -> int:
    with session_factory()() as db:
        return mail.dispatch(
            db,
            lambda org, identifier, version: celery.send_task(
                "coroof.invitation.send", args=[org, identifier, version]
            ),
        )


@celery.task(name="coroof.invitation.send", soft_time_limit=60, time_limit=70)  # type: ignore[untyped-decorator]
def send_invitation(organization_id: str, identifier: str, version: int) -> None:
    with session_factory()() as db:
        mail.process(db, organization_id, identifier, version)
