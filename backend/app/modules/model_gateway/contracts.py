from dataclasses import dataclass
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

ErrorCode = Literal[
    "not_configured",
    "model_disabled",
    "policy_denied",
    "not_verified",
    "unsupported_capability",
    "authentication",
    "permission",
    "invalid_request",
    "rate_limited",
    "unavailable",
    "timeout",
    "refused",
    "truncated",
    "response_too_large",
    "invalid_output",
    "invalid_evidence",
    "budget_exceeded",
    "access_revoked",
    "unknown",
]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True, hide_input_in_errors=True)


class Message(StrictModel):
    role: Literal["system", "user"]
    content: str = Field(min_length=1, max_length=100_000)


class ModelRequest(StrictModel):
    task: Literal[
        "evidence_qa",
        "connection_test",
        "agent_read",
        "agent_read_test",
        "update_draft",
        "memory_draft",
    ] = "evidence_qa"
    prompt_version: str = Field(min_length=1, max_length=30)
    schema_version: Literal[
        "assessment-v1",
        "connection-probe-v1",
        "agent-proposal-v1",
        "agent-proposal-v2",
        "agent-proposal-v3",
        "memory-proposal-v1",
        "agent-draft-v1",
    ] = "assessment-v1"
    messages: tuple[Message, ...] = Field(min_length=1, max_length=4)


class TokenUsage(StrictModel):
    input_tokens: int | None = Field(default=None, ge=0, le=1_000_000_000)
    output_tokens: int | None = Field(default=None, ge=0, le=1_000_000_000)
    reasoning_tokens: int | None = Field(default=None, ge=0, le=1_000_000_000)
    cached_tokens: int | None = Field(default=None, ge=0, le=1_000_000_000)


class ModelFailure(Exception):
    """Only stable codes are printable; never wrap raw provider errors."""

    def __init__(
        self,
        code: ErrorCode,
        *,
        sent: bool = False,
        usage: TokenUsage | None = None,
        provider_request_id: str | None = None,
    ) -> None:
        super().__init__(code)
        self.code = code
        self.sent = sent
        self.usage = usage or TokenUsage()
        self.provider_request_id = provider_request_id


@dataclass(frozen=True)
class ModelProfile:
    id: str
    provider: str
    model: str
    thinking: bool | None
    send_store: bool
    adapter_version: str = "langchain-v1"
    capability_status: str = "documented"
    schema_in_prompt: bool = False
    protocol: Literal["chat", "responses", "anthropic", "gemini"] = "chat"
    output_mode: Literal["schema", "json"] = "schema"
    max_tokens_field: str = "max_completion_tokens"


@dataclass(frozen=True)
class PreparedCall:
    request: ModelRequest
    profile: ModelProfile
    body: dict[str, Any]
    request_hash: str
    input_token_reserve: int
    output_token_reserve: int
    timeout_seconds: float
    prepared_at: float
    max_response_bytes: int = 150_000


@dataclass(frozen=True)
class ModelResult[T: BaseModel]:
    output: T
    profile: ModelProfile
    usage: TokenUsage
    latency_ms: int
    returned_model: str | None = None
    provider_request_id: str | None = None
