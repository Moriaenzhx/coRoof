from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import Field, model_validator

from app.core.schemas import DTO
from app.modules.model_gateway.contracts import StrictModel

MemoryKind = Literal["experience", "preference"]
PreferenceKey = Literal["focus", "communication", "decision_rule", "planning_goal"]


class MemoryInput(DTO):
    kind: MemoryKind
    decision_id: UUID | None = None
    outcome_id: UUID | None = None
    preference_key: PreferenceKey | None = None
    source_text: str = Field(default="", max_length=2000)
    idempotency_key: UUID

    @model_validator(mode="after")
    def valid_source(self) -> "MemoryInput":
        if "\x00" in self.source_text:
            raise ValueError("invalid_source")
        if self.kind == "experience":
            if (
                not self.decision_id
                or not self.outcome_id
                or self.preference_key
                or self.source_text
            ):
                raise ValueError("experience_requires_actual_outcome")
        elif (
            self.decision_id
            or self.outcome_id
            or not self.preference_key
            or not self.source_text.strip()
        ):
            raise ValueError("preference_requires_owner_statement")
        return self


class MemoryProposal(StrictModel):
    title: str = Field(min_length=1, max_length=200)
    content: str = Field(min_length=1, max_length=800)
    applicability: str = Field(min_length=1, max_length=600)
    source_quote: str = Field(min_length=1, max_length=500)


class MemoryCommand(DTO):
    expected_version: int = Field(ge=1)
    idempotency_key: UUID


class MemoryEdit(MemoryCommand):
    title: str = Field(min_length=1, max_length=200)
    content: str = Field(min_length=1, max_length=800)
    applicability: str = Field(min_length=1, max_length=600)
    source_quote: str = Field(min_length=1, max_length=500)
    expected_source_hash: str = Field(min_length=64, max_length=64)


class MemoryAction(MemoryCommand):
    action: Literal["confirm", "revoke", "delete"]
    confirm: Literal[True]
    expected_source_hash: str = Field(min_length=64, max_length=64)


class MemorySource(DTO):
    work_item_id: str | None
    decision_id: str | None
    outcome_id: str | None
    selected_plan: str | None
    observed_result: str | None
    owner_statement: str | None
    other_outcomes: list[str]
    outcome_count: int
    source_hash: str
    source_at: datetime


class MemoryOut(DTO):
    id: str
    kind: MemoryKind
    actor_id: str
    preference_key: PreferenceKey | None
    title: str
    content: str
    applicability: str
    source_quote: str
    state: Literal["proposed", "confirmed", "revoked", "deleted"]
    version: int
    source: MemorySource | None
    outdated: bool
    can_edit: bool
    confirmed_at: datetime | None
    created_at: datetime
    updated_at: datetime


class MemoryCitation(DTO):
    id: str
    kind: MemoryKind
    title: str
    excerpt: str
    applicability: str
    version: int
    source_at: datetime
    decision_id: str | None
    outcome_id: str | None


class MemoryAssessment(StrictModel):
    citation_id: str = Field(min_length=1, max_length=36)
    quote: str = Field(min_length=1, max_length=500)


class MemorySearchOut(DTO):
    items: list[MemoryCitation]
    total: int
    offset: int
    limit: int
    notice: str = "仅含当前有权访问且来源有效的已确认条目；经验与偏好不代表当前工作事实。"
