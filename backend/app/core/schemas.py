from datetime import UTC, datetime
from typing import Literal
from uuid import UUID
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import AwareDatetime, BaseModel, ConfigDict, EmailStr, Field, field_validator

Role = Literal["owner", "manager", "member"]
Status = Literal["planned", "in_progress", "done", "cancelled"]


class DTO(BaseModel):
    model_config = ConfigDict(from_attributes=True, extra="forbid", str_strip_whitespace=True)


class ErrorDetail(DTO):
    code: str
    message: str


class ErrorResponse(DTO):
    error: ErrorDetail


class LoginInput(DTO):
    email: EmailStr
    name: str = Field(min_length=1, max_length=100)


class TokenInput(DTO):
    token: str = Field(min_length=20, max_length=200)


class MockDelivery(DTO):
    mode: Literal["mock"] = "mock"
    token: str
    expires_at: datetime
    notice: str = "开发模拟邮件；未发送真实邮件，不能作为生产身份验证。"


class OrgInput(DTO):
    name: str = Field(min_length=1, max_length=100)
    timezone: str = "Asia/Shanghai"

    @field_validator("timezone")
    @classmethod
    def valid_timezone(cls, value: str) -> str:
        try:
            ZoneInfo(value)
        except ZoneInfoNotFoundError as exc:
            raise ValueError("Invalid IANA timezone") from exc
        return value


class OrgOut(OrgInput):
    id: str
    created_at: datetime


class DepartmentInput(DTO):
    name: str = Field(min_length=1, max_length=100)


class DepartmentOut(DepartmentInput):
    id: str
    organization_id: str


class MemberOut(DTO):
    id: str
    organization_id: str
    user_id: str
    name: str
    roles: list[Role]
    department_id: str | None
    status: str


class MembershipContext(DTO):
    membership: MemberOut
    organization: OrgOut


class MeOut(DTO):
    id: str
    name: str
    email: str
    mode: Literal["mock", "oidc"] = "mock"
    memberships: list[MembershipContext]


class InviteInput(DTO):
    idempotency_key: UUID | None = None
    email: EmailStr
    department_id: str
    roles: list[Literal["manager", "member"]] = Field(default=["member"], min_length=1)


class DeliveryStatus(DTO):
    mode: Literal["smtp"] = "smtp"
    state: Literal["queued", "sending", "retry_wait", "accepted", "unknown", "failed", "cancelled"]
    version: int
    attempts: int
    accepted_at: datetime | None
    last_error: str | None
    notice: str = "邮件服务接受不等于收件箱送达；发送中无法撤回，邀请可单独撤销。"


class DeliveryRetry(DTO):
    expected_version: int = Field(ge=1)
    confirm: Literal[True]
    idempotency_key: UUID


class InviteOut(DTO):
    id: str
    email: str
    department_id: str
    roles: list[str]
    expires_at: datetime
    revoked: bool
    accepted_at: datetime | None
    delivery_status: DeliveryStatus | None = None


class InviteDelivery(InviteOut):
    delivery: MockDelivery | DeliveryStatus | None


class InitiativeInput(DTO):
    title: str = Field(min_length=1, max_length=200)
    goal: str | None = Field(default=None, max_length=4000)
    department_id: str | None = None
    owner_id: str | None = None
    due_at: AwareDatetime | None = None


class InitiativeOut(InitiativeInput):
    id: str
    organization_id: str
    status: Status


class WorkInput(DTO):
    title: str = Field(min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=4000)
    department_id: str
    initiative_id: str | None = None
    owner_id: str | None = None
    due_at: AwareDatetime | None = None

    @field_validator("due_at")
    @classmethod
    def due_in_utc(cls, value: datetime | None) -> datetime | None:
        return value.astimezone(UTC) if value else value


class AssignmentInput(DTO):
    owner_id: str | None
    expected_version: int = Field(ge=1)
    idempotency_key: str = Field(min_length=8, max_length=100)


class WorkOut(WorkInput):
    id: str
    organization_id: str
    lifecycle_status: Status
    needs_support: bool
    source_authority: str
    updated_at: datetime
    version: int

    @field_validator("due_at", "updated_at", mode="before")
    @classmethod
    def restore_database_timezone(cls, value: object) -> object:
        # SQLite drops tzinfo on persisted UTC timestamps; input DTOs still require it.
        if isinstance(value, datetime) and value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value


class ProposedFields(DTO):
    summary: str = Field(min_length=1, max_length=4000)
    lifecycle_status: Status | None = None
    needs_support: bool | None = None


class DraftInput(DTO):
    work_item_id: str
    raw_text: str = Field(min_length=1, max_length=4000)
    decision_id: str | None = None


class DraftEdit(DTO):
    proposed_fields: ProposedFields
    expected_revision: int = Field(ge=1)


class DraftOut(DTO):
    id: str
    organization_id: str
    work_item_id: str
    decision_id: str | None = None
    actor_id: str
    raw_text: str
    proposed_fields: ProposedFields
    state: str
    base_version: int
    revision: int
    provider: str
    created_at: datetime
    expires_at: datetime


class ConfirmInput(DTO):
    expected_revision: int = Field(ge=1)


class QuickUpdate(DTO):
    action: Literal["progress", "done", "support", "resolve_support"]
    summary: str = Field(default="", max_length=4000)
    expected_version: int = Field(ge=1)
    idempotency_key: str = Field(min_length=8, max_length=100)


class EventOut(DTO):
    id: str
    organization_id: str
    work_item_id: str
    actor_id: str
    draft_id: str | None
    event_type: str
    event_payload: dict[str, object]
    occurred_at: datetime
    recorded_at: datetime
    source_ref: str


class Page[T](DTO):
    items: list[T]
    total: int
    offset: int
    limit: int


class DepartmentSummary(DTO):
    department: DepartmentOut
    member_count: int
    work_count: int
    active_count: int
    support_count: int
    coverage: Literal["unknown", "recorded"]
    updated_at: datetime | None


class DashboardOut(DTO):
    organization: OrgOut
    departments: list[DepartmentSummary]
    total_work: int
    active_work: int
    completed_work: int
    support_work: int
    member_count: int
    unscoped_members: int
    last_updated_at: datetime | None
    generated_at: datetime
    scope: Literal["organization", "department", "assigned"]
    source: Literal["native", "mixed"] = "native"
    external_data: Literal["not_connected", "partial"] = "not_connected"
    analysis_mode: Literal["rules"] = "rules"


class RuntimeInfo(DTO):
    environment: str
    auth_mode: str
    analysis_mode: str
    production_ready: bool = False
    deployment_prerequisites: list[str]


class HealthOut(DTO):
    status: str
