from typing import Any

from sqlalchemy import ColumnElement, case, func, select

from app.core.access import owner
from app.core.auth import Actor, Db
from app.infrastructure.models import ModelInvocation as Call
from app.infrastructure.models import now
from app.modules.ai_admin.api import router as router
from app.modules.ai_admin.schemas import UsageGroup, UsageOut
from app.modules.ai_admin.service import limits, policy


@router.get("/usage", response_model=UsageOut)
def usage(db: Db, actor: Actor) -> UsageOut:
    end = now()
    start = end.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    conditions = [
        Call.organization_id == actor.organization_id,
        Call.started_at >= start,
        Call.started_at <= end,
    ]
    is_owner = owner(actor)
    if not is_owner:
        conditions.append(Call.actor_id == actor.id)
    input_tokens = Call.usage["input_tokens"].as_integer()
    output_tokens = Call.usage["output_tokens"].as_integer()
    unknown = (input_tokens.is_(None) | output_tokens.is_(None)) & (Call.request_sent.is_not(False))

    def count(condition: ColumnElement[bool]) -> ColumnElement[int]:
        return func.coalesce(func.sum(case((condition, 1), else_=0)), 0)

    (
        total,
        business,
        tests,
        success,
        failed,
        pending,
        inputs,
        outputs,
        missing,
        latency,
        occupied,
    ) = db.execute(
        select(
            func.count(),
            count(Call.task.not_in(["connection_test", "agent_read_test"])),
            count(Call.task.in_(["connection_test", "agent_read_test"])),
            count(Call.status == "succeeded"),
            count(Call.status == "failed"),
            count(Call.status.in_(["pending", "unknown"])),
            func.coalesce(func.sum(input_tokens), 0),
            func.coalesce(func.sum(output_tokens), 0),
            count(unknown),
            func.avg(Call.latency_ms),
            func.coalesce(func.sum(Call.charged_tokens), 0),
        ).where(*conditions)
    ).one()

    def groups(column: ColumnElement[Any], limit: int) -> list[UsageGroup]:
        rows = db.execute(
            select(
                column,
                func.count(),
                func.coalesce(func.sum(input_tokens), 0),
                func.coalesce(func.sum(output_tokens), 0),
                count(unknown),
            )
            .where(*conditions)
            .group_by(column)
            .order_by(column)
            .limit(limit)
        )
        return [
            UsageGroup(
                label=str(label),
                calls=calls,
                input_tokens=ins,
                output_tokens=outs,
                unknown_usage_calls=unknown_count,
            )
            for label, calls, ins, outs, unknown_count in rows
        ]

    current = policy(db, actor) if is_owner else None
    limit = limits(current)["monthly_token_limit"] if is_owner else None
    threshold = current.alert_percent if current else 80
    # PostgreSQL date(timestamptz) otherwise uses the connection's local timezone.
    day = func.date(
        func.timezone("UTC", Call.started_at)
        if db.get_bind().dialect.name == "postgresql"
        else Call.started_at
    )
    return UsageOut(
        scope="organization" if is_owner else "self",
        start=start,
        end=end,
        calls=total,
        business_tasks=business,
        test_calls=tests,
        succeeded=success,
        failed=failed,
        pending_or_unknown=pending,
        input_tokens=inputs,
        output_tokens=outputs,
        unknown_usage_calls=missing,
        average_latency_ms=latency,
        quota_occupied_tokens=occupied,
        monthly_token_limit=limit,
        alert=limit is not None and occupied * 100 >= limit * threshold,
        daily=groups(day, 31),
        models=groups(Call.provider + "/" + Call.model, 20),
    )
