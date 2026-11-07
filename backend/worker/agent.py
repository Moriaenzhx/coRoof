"""Execute explicit interactive read requests independently of browser connectivity."""

from app.infrastructure.db import session_factory
from app.modules.agent import execution
from worker.app import celery


@celery.task(name="coroof.agent.dispatch", soft_time_limit=50, time_limit=60)  # type: ignore[untyped-decorator]
def dispatch_pending() -> int:
    with session_factory()() as db:
        return execution.dispatch(
            db,
            lambda org, run, generation: celery.send_task(
                "coroof.agent.process", args=[org, run, generation]
            ),
        )


@celery.task(name="coroof.agent.process", soft_time_limit=150, time_limit=160)  # type: ignore[untyped-decorator]
def process_step(organization_id: str, run_id: str, generation: int) -> None:
    with session_factory()() as db:
        execution.process(db, organization_id, run_id, generation)
