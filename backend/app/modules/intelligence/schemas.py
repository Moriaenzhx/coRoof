from datetime import datetime
from typing import Literal

from pydantic import Field

from app.core.schemas import DTO, WorkOut
from app.modules.knowledge.schemas import Citation, DocumentAssessment, KnowledgeInventoryOut
from app.modules.memory.schemas import MemoryAssessment, MemoryCitation

Category = Literal["support", "overdue", "deadline_blocked", "stale"]
ActionKey = Literal["verify", "coordinate", "reschedule", "refresh"]


class EvidenceOut(DTO):
    id: str
    work_item_id: str
    work_version: int
    event_id: str | None
    facts: WorkOut
    excerpt: str
    source_at: datetime
    captured_at: datetime
    outdated: bool = False


class SignalOut(DTO):
    id: str
    work_item_id: str
    evidence_id: str
    category: Category
    severity: Literal["attention", "warning", "info"]
    state: Literal["active", "resolved"]
    rule_version: str
    detected_at: datetime
    evaluated_at: datetime
    version: int
    title: str
    explanation: str
    work_title: str


class AskInput(DTO):
    question: str = Field(min_length=1, max_length=2000)
    work_item_id: str | None = None


class Option(DTO):
    id: ActionKey
    title: str
    plan: str
    tradeoff: str


class Suggestion(DTO):
    work_item_id: str
    evidence_id: str
    signal_id: str | None
    signal_version: int | None
    interpretation: str
    options: list[Option]


class AnswerOut(DTO):
    id: str
    mode: Literal["model", "rules", "retrieval"]
    notice: str
    summary: str
    suggestions: list[Suggestion]
    evidence: list[EvidenceOut]
    signals: list[SignalOut]
    considered_work_count: int
    authorized_work_count: int
    generated_at: datetime
    prompt_version: str
    provider: str
    model: str
    documents: list[Citation] = Field(default_factory=list)
    document_answers: list[DocumentAssessment] = Field(default_factory=list)
    memories: list[MemoryCitation] = Field(default_factory=list)
    memory_answers: list[MemoryAssessment] = Field(default_factory=list)
    knowledge_inventory: KnowledgeInventoryOut | None = None


class ModelAssessment(DTO):
    evidence_id: str
    quote: str = Field(min_length=1, max_length=500)
    interpretation: str = Field(min_length=1, max_length=700)
    action_keys: list[ActionKey] = Field(min_length=1, max_length=4)


class ModelAnswer(DTO):
    assessments: list[ModelAssessment] = Field(max_length=5)
    document_answers: list[DocumentAssessment] = Field(default_factory=list, max_length=3)
    memory_answers: list[MemoryAssessment] = Field(default_factory=list, max_length=4)
