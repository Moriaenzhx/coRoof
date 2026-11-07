"""Short database transactions around the model gateway; never hold locks across network I/O."""

from datetime import timedelta
from time import perf_counter

from sqlalchemy import func, select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.infrastructure.models import (
    AISettings,
    AnalysisRun,
    Membership,
    ModelInvocation,
    Organization,
    now,
    utc,
)
from app.modules.model_gateway.contracts import ErrorCode, ModelFailure, PreparedCall, TokenUsage


def reserve(
    db: Session, actor: Membership, run: AnalysisRun, call: PreparedCall, cfg: Settings
) -> ModelInvocation:
    remaining = call.timeout_seconds - (perf_counter() - call.prepared_at)
    if remaining <= 0:
        raise ModelFailure("timeout")
    # Admission wait consumes the same deadline as the subsequent network call.
    if db.get_bind().dialect.name == "postgresql":
        db.execute(
            text("SELECT set_config('lock_timeout', :timeout, true)"),
            {"timeout": f"{max(1, int(remaining * 1000))}ms"},
        )
    try:
        db.scalar(
            select(Organization).where(Organization.id == actor.organization_id).with_for_update()
        )
    except DBAPIError as exc:
        if getattr(exc.orig, "sqlstate", None) == "55P03":
            db.rollback()
            raise ModelFailure("timeout") from None
        raise
    clock = now()
    current_policy = db.scalar(
        select(AISettings)
        .where(AISettings.organization_id == actor.organization_id)
        .execution_options(populate_existing=True)
    )
    if (current_policy.version if current_policy else 0) != cfg.ai_config_revision:
        raise ModelFailure("not_verified")
    stale = db.scalars(
        select(ModelInvocation).where(
            ModelInvocation.organization_id == actor.organization_id,
            ModelInvocation.status == "pending",
            ModelInvocation.lease_expires_at < clock,
        )
    ).all()
    for row in stale:
        row.status, row.error_code, row.finished_at = "unknown", "unknown", clock
        old_run = db.get(AnalysisRun, row.analysis_run_id)
        if old_run and old_run.status == "pending":
            old_run.status, old_run.failure_code, old_run.cost_estimate = (
                "unknown",
                "unknown",
                "unknown",
            )
        # Keep the reserved token charge; no evidence that the provider did not execute it.
    db.flush()
    duplicate = db.scalar(
        select(ModelInvocation.id).where(
            ModelInvocation.organization_id == actor.organization_id,
            ModelInvocation.actor_id == actor.id,
            ModelInvocation.request_id == run.id,
        )
    )
    if duplicate:
        raise ModelFailure("policy_denied")
    in_flight = (
        db.scalar(
            select(func.count())
            .select_from(ModelInvocation)
            .where(
                ModelInvocation.organization_id == actor.organization_id,
                ModelInvocation.status == "pending",
            )
        )
        or 0
    )
    # UTC rolling 24 hours also bounds midnight bursts. Unknown attempts remain charged.
    calls, tokens = db.execute(
        select(func.count(), func.coalesce(func.sum(ModelInvocation.charged_tokens), 0))
        .select_from(ModelInvocation)
        .where(
            ModelInvocation.organization_id == actor.organization_id,
            ModelInvocation.started_at >= clock - timedelta(hours=24),
        )
    ).one()
    reserved = call.input_token_reserve + call.output_token_reserve
    month_start = clock.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    monthly_tokens = (
        db.scalar(
            select(func.coalesce(func.sum(ModelInvocation.charged_tokens), 0)).where(
                ModelInvocation.organization_id == actor.organization_id,
                ModelInvocation.started_at >= month_start,
            )
        )
        or 0
    )
    if (
        in_flight >= cfg.ai_concurrency_limit
        or calls >= cfg.ai_daily_call_limit
        or tokens + reserved > cfg.ai_daily_token_limit
        or monthly_tokens + reserved > cfg.ai_monthly_token_limit
    ):
        raise ModelFailure("budget_exceeded")
    invocation = ModelInvocation(
        connection_id=cfg.ai_connection_id,
        billing_mode=cfg.ai_billing_mode,
        config_revision=cfg.ai_config_revision,
        organization_id=actor.organization_id,
        actor_id=actor.id,
        analysis_run_id=run.id,
        request_id=run.id,
        request_hash=call.request_hash,
        task=call.request.task,
        provider=call.profile.provider,
        model=call.profile.model,
        profile_id=call.profile.id,
        adapter_version=call.profile.adapter_version,
        prompt_version=call.request.prompt_version,
        schema_version=call.request.schema_version,
        charged_tokens=reserved,
        started_at=clock,
        lease_expires_at=clock
        + timedelta(
            seconds=max(0, call.timeout_seconds - (perf_counter() - call.prepared_at)) + 10
        ),
    )
    db.add(invocation)
    db.commit()
    return invocation


def finish(
    db: Session,
    invocation: ModelInvocation,
    *,
    error: ErrorCode | None,
    sent: bool,
    usage: TokenUsage,
    request_id: str | None = None,
    returned_model: str | None = None,
) -> None:
    invocation.status = "failed" if error else "succeeded"
    invocation.error_code = error
    invocation.request_sent = sent
    invocation.usage = usage.model_dump()
    invocation.provider_request_id = request_id
    invocation.returned_model = returned_model
    invocation.finished_at = now()
    invocation.latency_ms = max(0, int((now() - utc(invocation.started_at)).total_seconds() * 1000))
    if not sent:
        invocation.charged_tokens = 0
    elif usage.input_tokens is not None and usage.output_tokens is not None:
        invocation.charged_tokens = usage.input_tokens + usage.output_tokens
    db.flush()
