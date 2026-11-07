from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import Field, model_validator

from app.core.schemas import DTO, DraftOut, Status
from app.modules.intelligence.schemas import AnswerOut, ModelAnswer
from app.modules.memory.schemas import MemoryOut
from app.modules.model_gateway.contracts import StrictModel

Capability = Literal[
    "company.overview",
    "attention.explain",
    "work.investigate",
    "coverage.explain",
    "knowledge.search",
    "knowledge.list",
    "experience.reference",
    "preference.read",
]
RunState = Literal["ready", "running", "completed", "failed", "cancelled", "interrupted"]
Task = Literal["read", "update_draft", "memory_draft"]


class DraftProposal(StrictModel):
    summary: str = Field(min_length=1, max_length=4000)
    lifecycle_status: Status | None
    needs_support: bool | None


class Proposal(StrictModel):
    kind: Literal["read", "finish"]
    capability: Capability | None
    work_item_id: str | None = Field(max_length=36)
    answer: ModelAnswer | None
    outcome: Literal["answer", "insufficient_data", "unsupported"] | None

    @model_validator(mode="after")
    def coherent(self) -> "Proposal":
        if self.kind == "read":
            if self.capability is None or self.answer is not None or self.outcome is not None:
                raise ValueError("invalid_read_proposal")
            if (self.capability == "work.investigate") != (self.work_item_id is not None):
                raise ValueError("invalid_work_scope")
        elif (
            self.capability is not None
            or self.work_item_id is not None
            or self.answer is None
            or self.outcome is None
        ):
            raise ValueError("invalid_finish_proposal")
        return self


class RunInput(DTO):
    task: Task = "read"
    question: str = Field(min_length=1, max_length=2000)
    work_item_id: UUID | None = None
    memory_entry_id: UUID | None = None
    parent_run_id: UUID | None = None
    idempotency_key: UUID

    @model_validator(mode="after")
    def draft_scope(self) -> "RunInput":
        if self.parent_run_id is not None and self.task != "read":
            raise ValueError("只有只读问答可以承接上一轮查询")
        if self.task == "update_draft" and self.work_item_id is None:
            raise ValueError("更新草稿必须指定事项")
        if (self.task == "memory_draft") != (self.memory_entry_id is not None):
            raise ValueError("经验整理必须指定候选，其他任务不能绑定候选")
        if self.task == "memory_draft" and self.work_item_id is not None:
            raise ValueError("经验事项由服务端从来源确定")
        return self


class AdvanceInput(DTO):
    expected_version: int = Field(ge=1)
    idempotency_key: UUID


class VersionInput(DTO):
    expected_version: int = Field(ge=1)


class StepOut(DTO):
    id: str
    ordinal: int
    state: Literal["pending", "succeeded", "failed", "unknown"]
    capability: Capability | None
    error_code: str | None


class ExecutionOut(DTO):
    state: Literal["queued", "running", "stopped"]
    updated_at: datetime


class RunOut(DTO):
    id: str
    question: str
    work_item_id: str | None
    parent_run_id: str | None = None
    state: RunState
    version: int
    step_count: int
    max_steps: int = 6
    error_code: str | None
    steps: list[StepOut]
    answer: AnswerOut | None
    task: Task = "read"
    draft: DraftOut | None = None
    memory: MemoryOut | None = None
    created_at: datetime
    deadline: datetime
    execution: ExecutionOut | None = None
