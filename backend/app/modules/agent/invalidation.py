"""Transactional invalidation shared by authorized retrieval sources."""

from sqlalchemy import Select, select
from sqlalchemy.orm import Session

from app.infrastructure.models import AgentRun, AgentStep, AnalysisRun


def read_barrier(db: Session, organization_id: str, except_run: str = "") -> None:
    # Source commands hold the organization's NO KEY UPDATE lock before this.
    # Already executing domain reads can finish their FK inserts and commit;
    # new runs cannot capture the previous source scope during the barrier.
    list(
        db.scalars(
            select(AgentRun)
            .where(
                AgentRun.organization_id == organization_id,
                AgentRun.state.in_(["ready", "running"]),
                AgentRun.id != except_run,
            )
            .order_by(AgentRun.id)
            .with_for_update()
        )
    )


def clear_runs(
    db: Session, organization_id: str, run_ids: Select[tuple[str]], except_run: str = ""
) -> None:
    runs = db.scalars(
        select(AgentRun)
        .where(
            AgentRun.organization_id == organization_id,
            AgentRun.id.in_(run_ids),
            AgentRun.id != except_run,
        )
        .order_by(AgentRun.id)
        .with_for_update()
    ).all()
    for run in runs:
        run.state, run.error_code, run.answer = "cancelled", "context_changed", None
        run.version += 1
        for step in db.scalars(
            select(AgentStep).where(
                AgentStep.organization_id == organization_id, AgentStep.run_id == run.id
            )
        ):
            step.result = None
            if step.state == "pending":
                step.state, step.error_code = "failed", "context_changed"
            analysis = db.get(AnalysisRun, step.analysis_id) if step.analysis_id else None
            if analysis:
                analysis.result, analysis.status, analysis.failure_code = (
                    None,
                    "access_revoked",
                    "context_changed",
                )
