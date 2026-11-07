from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import Field, SecretStr, field_validator

from app.core.schemas import DTO
from app.modules.model_gateway.contracts import StrictModel

Visibility = Literal["private", "department", "organization", "members"]
DocumentView = Literal["all", "published", "my_drafts", "mine", "my_withdrawn"]


class DocumentAccess(DTO):
    visibility: Visibility = "private"
    department_id: UUID | None = None
    member_ids: list[UUID] = Field(default_factory=list, max_length=100)


class DocumentInput(DocumentAccess):
    title: str = Field(min_length=1, max_length=200)
    content: str = Field(min_length=1, max_length=120_000)
    idempotency_key: UUID

    @field_validator("title", "content")
    @classmethod
    def not_blank(cls, value: str) -> str:
        if not value.strip() or "\x00" in value:
            raise ValueError("empty_or_invalid_content")
        return value


class ImportInput(DocumentAccess):
    title: str = Field(min_length=1, max_length=200)
    file_name: str = Field(min_length=1, max_length=180)
    file_base64: SecretStr = Field(max_length=5_600_000)
    idempotency_key: UUID

    @field_validator("file_name")
    @classmethod
    def filename(cls, value: str) -> str:
        if any(char in value for char in "/\\\r\n\x00") or value.startswith("."):
            raise ValueError("invalid_filename")
        return value


class DocumentCommand(DTO):
    expected_version: int = Field(ge=1)
    idempotency_key: UUID


class DocumentEdit(DocumentCommand):
    title: str = Field(min_length=1, max_length=200)
    content: str = Field(min_length=1, max_length=120_000)

    @field_validator("title", "content")
    @classmethod
    def not_blank(cls, value: str) -> str:
        if not value.strip() or "\x00" in value:
            raise ValueError("empty_or_invalid_content")
        return value


class AccessChange(DocumentAccess, DocumentCommand):
    pass


class DocumentPublish(DocumentCommand):
    revision_id: UUID
    confirm: Literal[True]


class DocumentAction(DocumentCommand):
    action: Literal["withdraw", "delete"]
    confirm: Literal[True]


class DocumentOut(DTO):
    id: str
    title: str
    author_id: str
    visibility: Visibility
    department_id: str | None
    member_ids: list[str]
    state: str
    version: int
    published_id: str | None
    draft_id: str | None
    can_edit: bool
    can_publish: bool
    updated_at: datetime
    created_at: datetime


class RevisionOut(DTO):
    id: str
    document_id: str
    author_id: str
    number: int
    title: str
    content: str
    content_hash: str
    file_name: str | None
    file_hash: str | None
    edited_extraction: bool
    published_at: datetime | None
    created_at: datetime
    current: bool


class Citation(DTO):
    id: str
    document_id: str
    revision_id: str
    revision_number: int
    title: str
    excerpt: str
    start_offset: int
    end_offset: int
    source_at: datetime
    file_name: str | None


class KnowledgeInventoryItem(DTO):
    document_id: str
    revision_id: str
    revision_number: int
    title: str
    source_at: datetime


class KnowledgeInventoryOut(DTO):
    items: list[KnowledgeInventoryItem]
    total: int = Field(ge=0)
    limit: int = Field(ge=1, le=20)
    truncated: bool
    notice: str


class SearchOut(DTO):
    items: list[Citation]
    total: int
    offset: int
    limit: int
    authorized_documents: int
    notice: str = "仅检索当前有权访问的已发布版本；匹配原文不等于已执行业务动作。"


class DocumentAssessment(StrictModel):
    citation_id: str = Field(min_length=1, max_length=36)
    quote: str = Field(min_length=1, max_length=500)
