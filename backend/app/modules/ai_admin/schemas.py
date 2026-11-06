from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import Field, SecretStr

from app.core.schemas import DTO

ProviderId = Literal["openai", "anthropic", "gemini", "bailian", "deepseek", "openai_compatible"]


class ProviderOut(DTO):
    id: ProviderId
    label: str
    base_url: str
    protocol: str
    output_mode: Literal["schema", "json"]


class ConnectionInput(DTO):
    name: str = Field(min_length=1, max_length=80)
    provider: ProviderId
    model: str = Field(min_length=1, max_length=50, pattern=r"^[A-Za-z0-9][A-Za-z0-9._:/-]*$")
    base_url: str = Field(max_length=500)
    output_mode: Literal["schema", "json"] = "schema"
    api_key: SecretStr = Field(min_length=8, max_length=2048)
    idempotency_key: UUID


class ConnectionOut(DTO):
    id: str
    name: str
    provider: ProviderId
    model: str
    base_url: str
    output_mode: Literal["schema", "json"]
    key_hint: str
    state: Literal["draft", "testing", "tested", "failed", "revoked"]
    version: int
    tested_at: datetime | None
    last_error: str | None
    usage_scope: Literal["application", "development_only"]
    usage_notice: str | None
    can_test: bool
    can_activate: bool


class ConnectionAction(DTO):
    expected_version: int = Field(ge=1)
    idempotency_key: UUID


class PolicyInput(DTO):
    expected_version: int = Field(ge=0)
    mode: Literal["platform", "byok", "disabled"]
    connection_id: str | None = None
    daily_call_limit: int = Field(ge=1, le=10000)
    daily_token_limit: int = Field(ge=1000, le=10_000_000)
    monthly_token_limit: int = Field(ge=1000, le=1_000_000_000)
    concurrency_limit: int = Field(ge=1, le=10)
    alert_percent: int = Field(ge=1, le=100)


class PolicyOut(DTO):
    version: int
    mode: Literal["platform", "byok", "disabled"]
    connection_id: str | None
    daily_call_limit: int
    daily_token_limit: int
    monthly_token_limit: int
    concurrency_limit: int
    alert_percent: int
    credential_storage_ready: bool
    platform_ready: bool
    platform_model: str | None
    platform_provider: str | None
    allowed_custom_base_urls: list[str]


class ConfigEventOut(DTO):
    id: str
    actor_name: str
    action: str
    revision: int
    detail: str
    recorded_at: datetime


class UsageGroup(DTO):
    label: str
    calls: int
    input_tokens: int
    output_tokens: int
    unknown_usage_calls: int


class UsageOut(DTO):
    scope: Literal["organization", "self"]
    start: datetime
    end: datetime
    calls: int
    business_tasks: int
    test_calls: int
    succeeded: int
    failed: int
    pending_or_unknown: int
    input_tokens: int
    output_tokens: int
    unknown_usage_calls: int
    average_latency_ms: float | None
    quota_occupied_tokens: int
    monthly_token_limit: int | None
    alert: bool
    cost: None = None
    cost_notice: str = "费用尚未对账；Token 不是供应商余额。"
    daily: list[UsageGroup]
    models: list[UsageGroup]
