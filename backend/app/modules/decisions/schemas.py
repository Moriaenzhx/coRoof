from datetime import datetime
from typing import Literal

from pydantic import AwareDatetime, Field, field_validator

from app.core.schemas import DTO
from app.infrastructure.models import utc
from app.modules.intelligence.schemas import EvidenceOut, Option

DecisionView = Literal["all", "action_required", "pending", "follow_up", "recorded"]


class DecisionInput(DTO):
    analysis_id: str
    work_item_id: str
    idempotency_key: str = Field(min_length=8, max_length=100)


class DecisionConfirm(DTO):
    expected_version: int = Field(ge=1)
    selected_option: str = Field(min_length=1, max_length=40)
    selected_plan: str = Field(min_length=1, max_length=2000)
    follow_up: str = Field(min_length=1, max_length=1000)
    follow_up_at: AwareDatetime | None = None


class OutcomeInput(DTO):
    observed_result: str = Field(min_length=1, max_length=4000)
    evidence_refs: list[str] = Field(default_factory=list, max_length=20)
    idempotency_key: str = Field(min_length=8, max_length=100)


class OutcomeOut(DTO):
    id: str
    decision_id: str
    actor_id: str
    observed_result: str
    evidence_refs: list[str]
    recorded_at: datetime


class DecisionContext(DTO):
    evidence: EvidenceOut
    interpretation: str
    analysis_mode: str
    analysis_time: datetime
    signal_versions: dict[str, int]


class DecisionOut(DTO):
    id: str
    work_item_id: str
    signal_id: str | None
    analysis_id: str
    actor_id: str
    title: str
    work_version: int
    context_snapshot: DecisionContext
    options: list[Option]
    state: str
    selected_option: str | None
    selected_plan: str | None
    follow_up: str | None
    follow_up_at: datetime | None = None
    confirmed_by: str | None
    confirmed_at: datetime | None
    created_at: datetime
    version: int

    @field_validator("confirmed_at", "created_at", "follow_up_at")
    @classmethod
    def utc_times(cls, value: datetime | None) -> datetime | None:
        return utc(value) if value else value


class DecisionListOut(DecisionOut):
    outcome_count: int = Field(ge=0)


class ArrangementFeedbackOut(DTO):
    id: str
    decision_id: str
    actor_id: str
    summary: str
    recorded_at: datetime


class WorkArrangementOut(DTO):
    """Only the explicitly confirmed arrangement is shared with the work's current audience."""

    id: str
    work_item_id: str
    selected_plan: str
    follow_up: str
    follow_up_at: datetime | None
    confirmed_at: datetime
    feedback_count: int = Field(ge=0)
    latest_feedback: ArrangementFeedbackOut | None
