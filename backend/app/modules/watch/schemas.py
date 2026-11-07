from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import AwareDatetime, Field, model_validator

from app.core.schemas import DTO
from app.modules.intelligence.schemas import EvidenceOut


class PolicyFields(DTO):
    name: str = Field(min_length=1, max_length=100)
    goal: str = Field(min_length=1, max_length=1500)
    scope_kind: Literal["organization", "department", "initiative"]
    department_id: UUID | None = None
    initiative_id: UUID | None = None
    interval_minutes: int = Field(default=60, ge=15, le=1440)
    daily_analysis_limit: int = Field(default=4, ge=1, le=24)
    expires_at: AwareDatetime

    @model_validator(mode="after")
    def target(self) -> "PolicyFields":
        if (self.scope_kind == "department") != (self.department_id is not None) or (
            self.scope_kind == "initiative"
        ) != (self.initiative_id is not None):
            raise ValueError("请选择与范围一致的目标")
        return self


class PolicyCreate(PolicyFields):
    confirm: Literal[True]
    idempotency_key: UUID


class PolicyEdit(PolicyCreate):
    expected_version: int = Field(ge=1)


class PolicyAction(DTO):
    action: Literal["pause", "resume", "revoke"]
    confirm: Literal[True]
    expected_version: int = Field(ge=1)
    idempotency_key: UUID


class WatchPolicyOut(PolicyFields):
    id: str
    actor_id: str
    state: Literal["active", "paused", "revoked"]
    effective_state: Literal["active", "paused", "revoked", "expired", "unauthorized"]
    version: int
    created_at: datetime
    next_due_at: datetime
    last_checked_at: datetime | None
    notice: str = (
        "后台仅在授权范围内读取和准备建议。业务修改仍需明确确认；"
        "日额度为分析轮数，每轮最多六次模型步骤。"
    )


class AttentionOut(DTO):
    id: str
    policy_id: str
    policy_name: str
    kind: Literal["work", "follow_up", "coverage"]
    category: str
    title: str
    explanation: str
    work_item_id: str | None
    work_title: str | None
    decision_id: str | None
    agent_run_id: str | None
    evidence: EvidenceOut | None
    state: Literal["open", "snoozed", "dismissed", "invalidated", "result_recorded"]
    version: int
    snoozed_until: datetime | None
    review_note: str | None
    created_at: datetime
    changed_at: datetime


class AttentionAction(DTO):
    action: Literal["snooze", "dismiss", "correct", "reopen"]
    expected_version: int = Field(ge=1)
    idempotency_key: UUID
    snoozed_until: AwareDatetime | None = None
    note: str | None = Field(default=None, max_length=1000)

    @model_validator(mode="after")
    def details(self) -> "AttentionAction":
        if (self.action == "snooze") != (self.snoozed_until is not None):
            raise ValueError("仅暂缓时提供下次处理时间")
        if self.action == "correct" and (not self.note or not self.note.strip()):
            raise ValueError("请说明需要核实或纠正的内容；此备注不改变实际工作记录")
        return self


class WatchRunOut(DTO):
    id: str
    policy_id: str
    state: str
    phase: str
    trigger_kind: str
    outcome_code: str | None
    error_code: str | None
    coverage_count: int
    considered_count: int
    source_warning_count: int
    work_item_id: str | None
    agent_run_id: str | None
    created_at: datetime
    finished_at: datetime | None
