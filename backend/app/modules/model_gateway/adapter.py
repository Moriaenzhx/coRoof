"""LangChain integrations plus coRoof egress and result policy, without wire APIs."""

import asyncio
import re
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any, cast

import anthropic
import httpx
import openai
from google import genai
from google.genai import types
from langchain_anthropic import ChatAnthropic
from langchain_core.exceptions import ModelConnectionError, ModelTimeoutError
from langchain_core.messages import AIMessage
from langchain_core.runnables import Runnable
from langchain_deepseek import ChatDeepSeek
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_openai import ChatOpenAI
from langsmith import tracing_context
from pydantic import ValidationError

from app.core.config import Settings
from app.modules.model_gateway.contracts import ErrorCode, ModelFailure, PreparedCall, TokenUsage

http_client = httpx.AsyncClient


@dataclass(frozen=True)
class AdapterResult:
    content: str
    usage: TokenUsage
    returned_model: str | None
    provider_request_id: str | None


def identifier(value: Any, secret: str, limit: int = 150) -> str | None:
    if not isinstance(value, str) or not 0 < len(value) <= limit:
        return None
    if value.startswith("sk-") or (secret and secret in value):
        return None
    return value if re.fullmatch(r"[A-Za-z0-9._:/-]+", value) else None


class BoundedStream(httpx.AsyncByteStream):
    def __init__(self, source: httpx.AsyncByteStream, limit: int) -> None:
        self.source, self.limit = source, limit

    async def __aiter__(self) -> AsyncIterator[bytes]:
        size = 0
        async for chunk in self.source:
            size += len(chunk)
            if size > self.limit:
                raise ModelFailure("response_too_large", sent=True)
            yield chunk

    async def aclose(self) -> None:
        await self.source.aclose()


def structured_model(
    cfg: Settings, call: PreparedCall, client: httpx.AsyncClient
) -> Runnable[Any, Any]:
    """Select maintained integrations; kwargs express explicit model policy only."""
    secret, profile = cfg.ai_api_key.get_secret_value(), call.profile
    common: dict[str, Any] = {
        "model": profile.model,
        "api_key": secret,
        "base_url": cfg.ai_base_url.rstrip("/"),
        "max_retries": 0,
        "timeout": call.timeout_seconds,
        "cache": False,
    }
    schema = call.body["schema"]
    if profile.protocol == "anthropic":
        model = ChatAnthropic(
            **{**common, "base_url": cfg.ai_base_url.removesuffix("/v1")},
            max_tokens=cfg.ai_max_output_tokens,
        )
        # Integration exposes a cached SDK client rather than an http_client field.
        model.__dict__["_async_client"] = anthropic.AsyncAnthropic(
            api_key=secret,
            base_url=cfg.ai_base_url.removesuffix("/v1"),
            http_client=client,
            max_retries=0,
            timeout=call.timeout_seconds,
        )
        return model.with_structured_output(schema, method="json_schema", include_raw=True)
    if profile.protocol == "gemini":
        base, version = cfg.ai_base_url.rstrip("/").rsplit("/", 1)
        google = ChatGoogleGenerativeAI(
            **{**common, "base_url": base, "max_retries": 1},
            api_version=version,
            vertexai=False,
            max_output_tokens=cfg.ai_max_output_tokens,
        )
        assert google.client is not None
        google.client.close()
        google.client = genai.Client(
            vertexai=False,
            api_key=secret,
            http_options=types.HttpOptions(
                base_url=base,
                api_version=version,
                httpx_async_client=client,
                headers={"Accept-Encoding": "identity"},
                retry_options=types.HttpRetryOptions(attempts=1),
            ),
        )
        return google.with_structured_output(schema, method="json_schema", include_raw=True)
    cls = ChatDeepSeek if profile.provider == "deepseek" else ChatOpenAI
    chat = cls(
        **common,
        http_async_client=client,
        max_tokens=cfg.ai_max_output_tokens,
        use_responses_api=profile.protocol == "responses",
        stream_usage=False,
        include_response_headers=True,
        default_headers={"Accept-Encoding": "identity"},
        openai_organization="",
        http_socket_options=(),
        extra_body={"enable_thinking": profile.thinking} if profile.thinking is not None else None,
        store=False if profile.send_store else None,
    )
    return chat.with_structured_output(
        schema,
        method="json_mode" if profile.output_mode == "json" else "json_schema",
        include_raw=True,
        strict=True if profile.output_mode == "schema" else None,
    )


def token_usage(value: Any) -> TokenUsage:
    raw_usage = value if isinstance(value, dict) else {}
    try:
        usage = TokenUsage(
            input_tokens=raw_usage.get("input_tokens"),
            output_tokens=raw_usage.get("output_tokens"),
            reasoning_tokens=raw_usage.get("output_token_details", {}).get("reasoning"),
            cached_tokens=raw_usage.get("input_token_details", {}).get("cache_read"),
        )
    except ValidationError:
        usage = TokenUsage()
    return usage


def parse_message(message: AIMessage, secret: str, request_id: str | None) -> AdapterResult:
    """Validate normalized output; never execute model tool calls or store reasoning."""
    usage = token_usage(message.usage_metadata)
    meta = message.response_metadata
    request_id = request_id or identifier(meta.get("id"), secret)
    finish = meta.get("finish_reason", meta.get("stop_reason", meta.get("status")))
    if finish in {"length", "max_tokens", "MAX_TOKENS", "incomplete"}:
        raise ModelFailure("truncated", sent=True, usage=usage, provider_request_id=request_id)
    if message.additional_kwargs.get("refusal") or finish in {
        "refusal",
        "content_filter",
        "SAFETY",
        "RECITATION",
        "PROHIBITED_CONTENT",
    }:
        raise ModelFailure("refused", sent=True, usage=usage, provider_request_id=request_id)
    blocks = message.content if isinstance(message.content, list) else []
    if any(isinstance(b, dict) and b.get("type") == "refusal" for b in blocks):
        raise ModelFailure("refused", sent=True, usage=usage, provider_request_id=request_id)
    if (
        finish not in {"stop", "end_turn", "STOP", "completed"}
        or message.tool_calls
        or message.invalid_tool_calls
        or message.additional_kwargs.get("function_call")
        or any(
            not isinstance(b, dict)
            or b.get("type")
            not in {
                "text",
                "reasoning",
                "thinking",
                "redacted_thinking",
            }
            for b in blocks
        )
        or not message.text.strip()
        or secret in message.text
    ):
        raise ModelFailure("invalid_output", sent=True, usage=usage, provider_request_id=request_id)
    return AdapterResult(
        content=message.text,
        usage=usage,
        returned_model=identifier(meta.get("model_name", meta.get("model")), secret, 100),
        provider_request_id=request_id,
    )


async def complete(cfg: Settings, call: PreparedCall) -> AdapterResult:
    sent, request_id = False, None
    secret = cfg.ai_api_key.get_secret_value()

    async def before_request(request: httpx.Request) -> None:
        nonlocal sent
        expected = httpx.URL(cfg.ai_base_url)
        if request.url.host != expected.host or request.url.scheme != expected.scheme:
            raise ModelFailure("policy_denied")
        if len(request.content) + 512 > call.input_token_reserve:
            raise ModelFailure("budget_exceeded")
        request.headers["Accept-Encoding"] = "identity"
        sent = True

    async def after_response(response: httpx.Response) -> None:
        nonlocal request_id
        request_id = identifier(response.headers.get("x-request-id"), secret)
        if response.status_code != 200:
            code = {401: "authentication", 403: "permission", 429: "rate_limited"}.get(
                response.status_code,
                "unavailable" if response.status_code >= 500 else "invalid_request",
            )
            await response.aclose()
            raise ModelFailure(cast(ErrorCode, code), sent=True, provider_request_id=request_id)
        if response.headers.get("content-encoding", "identity").lower() != "identity":
            await response.aclose()
            raise ModelFailure("invalid_output", sent=True)
        if response.is_stream_consumed:
            if len(response.content) > call.max_response_bytes:
                raise ModelFailure("response_too_large", sent=True)
        else:
            response.stream = BoundedStream(
                cast(httpx.AsyncByteStream, response.stream), call.max_response_bytes
            )

    try:
        with tracing_context(enabled=False):
            async with (
                asyncio.timeout(call.timeout_seconds),
                http_client(
                    timeout=httpx.Timeout(
                        call.timeout_seconds, connect=min(5, call.timeout_seconds)
                    ),
                    follow_redirects=False,
                    trust_env=False,
                    event_hooks={"request": [before_request], "response": [after_response]},
                ) as client,
            ):
                model = structured_model(cfg, call, client)
                result = await model.ainvoke(call.body["messages"], config={"callbacks": []})
                # Raw text prevents permissive JSON parsers from repairing invalid output.
                return parse_message(result["raw"], secret, request_id)
    except ModelFailure:
        raise
    except Exception as exc:
        cause: BaseException | None = exc
        while cause is not None:
            if isinstance(cause, ModelFailure):
                raise cause from None
            cause = cause.__cause__
        if isinstance(exc, openai.LengthFinishReasonError):
            code = "truncated"
        elif isinstance(exc, openai.ContentFilterFinishReasonError):
            code = "refused"
        elif isinstance(exc, (TimeoutError, httpx.TimeoutException, ModelTimeoutError)):
            code = "timeout"
        elif isinstance(exc, (httpx.HTTPError, ModelConnectionError)):
            code = "unavailable"
        else:
            code = "invalid_output"
        raise ModelFailure(
            cast(ErrorCode, code), sent=sent, provider_request_id=request_id
        ) from None
