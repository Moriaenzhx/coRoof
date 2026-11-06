import asyncio
import hashlib
import json
from dataclasses import replace
from time import perf_counter
from typing import Any

from pydantic import BaseModel, ValidationError

from app.core.config import Settings
from app.modules.model_gateway import adapter
from app.modules.model_gateway.contracts import (
    ModelFailure,
    ModelRequest,
    ModelResult,
    PreparedCall,
)
from app.modules.model_gateway.profiles import resolve_profile


def validate_schema(schema: dict[str, Any]) -> None:
    """Fail before egress for unsupported constraints; never silently weaken the local contract."""
    unsupported = {
        "multipleOf",
        "uniqueItems",
        "contains",
        "minContains",
        "maxContains",
        "additionalItems",
        "patternProperties",
        "propertyNames",
        "oneOf",
    }

    def visit(node: Any, depth: int = 0) -> None:
        if depth > 40:
            raise ModelFailure("unsupported_capability")
        if isinstance(node, dict):
            if unsupported.intersection(node):
                raise ModelFailure("unsupported_capability")
            ref = node.get("$ref")
            if ref is not None and (not isinstance(ref, str) or not ref.startswith("#/$defs/")):
                raise ModelFailure("unsupported_capability")
            if node.get("type") == "object" and node.get("additionalProperties") is not False:
                raise ModelFailure("unsupported_capability")
            for key, value in node.items():
                if key in {"properties", "$defs"} and isinstance(value, dict):
                    for child in value.values():
                        visit(child, depth + 1)
                elif key in {"items", "anyOf", "allOf", "not", "prefixItems"}:
                    visit(value, depth + 1)
        elif isinstance(node, list):
            for child in node:
                visit(child, depth + 1)

    visit(schema)


class ModelGateway:
    def __init__(self, cfg: Settings) -> None:
        self.cfg = cfg

    def prepare(
        self,
        request: ModelRequest,
        output_type: type[BaseModel],
        *,
        verification_probe: bool = False,
    ) -> PreparedCall:
        started = perf_counter()
        profile = resolve_profile(self.cfg, verification_probe=verification_probe)
        schema = output_type.model_json_schema()
        validate_schema(schema)

        # Pydantic adds a display title to each field/definition. Nested titles
        # duplicate property names in both the grammar and the schema prompt.
        # Retain the root title for LangChain's structured-output tool name and
        # all constraints/descriptions; do not remove properties NAMED "title".
        def omit_display_titles(node: Any, *, root: bool = False) -> None:
            if isinstance(node, dict):
                if not root:
                    node.pop("title", None)
                for name, value in node.items():
                    if name in {"properties", "$defs"} and isinstance(value, dict):
                        for child in value.values():
                            omit_display_titles(child)
                    elif name in {"items", "anyOf", "allOf", "not", "prefixItems"}:
                        omit_display_titles(value)
            elif isinstance(node, list):
                for child in node:
                    omit_display_titles(child)

        omit_display_titles(schema, root=True)
        messages = [message.model_dump() for message in request.messages]
        if profile.schema_in_prompt:
            # This endpoint accepted response_format but omitted required fields in live tests.
            # Supply the full contract as instructions too; validation remains strict locally.
            messages.insert(
                0,
                {
                    "role": "system",
                    "content": (
                        "只返回符合以下 JSON Schema 的 JSON 对象。必须包含全部 required 字段，"
                        "不要返回 Markdown、Schema 本身或额外字段：\n"
                        + json.dumps(schema, ensure_ascii=False, separators=(",", ":"))
                    ),
                },
            )
        # Provider-neutral input. LangChain owns wire serialization and parsing.
        body = {"messages": messages, "schema": schema}
        # Reserve from compact JSON, as used on the wire, rather than charging
        # for display whitespace. The adapter also bounds the actual request.
        encoded = json.dumps(
            body, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode()
        # Conservative UTF-8 byte bound, plus protocol overhead. No guessed tokenizer counts.
        input_reserve = len(encoded) * 2 + 1024
        if input_reserve > self.cfg.ai_max_input_tokens:
            raise ModelFailure("budget_exceeded")
        fingerprint = json.dumps(
            {
                "body": body,
                "profile": profile.id,
                "prompt": request.prompt_version,
                "schema": request.schema_version,
                "task": request.task,
            },
            ensure_ascii=False,
            sort_keys=True,
        ).encode()
        return PreparedCall(
            request=request,
            profile=profile,
            body=body,
            request_hash=hashlib.sha256(fingerprint).hexdigest(),
            input_token_reserve=input_reserve,
            output_token_reserve=self.cfg.ai_max_output_tokens + 16,
            timeout_seconds=self.cfg.ai_timeout_seconds,
            prepared_at=started,
        )

    def generate[T: BaseModel](self, call: PreparedCall, output_type: type[T]) -> ModelResult[T]:
        """Synchronous domain services call this from FastAPI's worker thread, without DB locks."""
        started = perf_counter()
        remaining = call.timeout_seconds - (started - call.prepared_at)
        if remaining <= 0:
            raise ModelFailure("timeout")
        result = asyncio.run(adapter.complete(self.cfg, replace(call, timeout_seconds=remaining)))
        try:
            output = output_type.model_validate_json(result.content, strict=True)
        except (ValidationError, ValueError):
            raise ModelFailure(
                "invalid_output",
                sent=True,
                usage=result.usage,
                provider_request_id=result.provider_request_id,
            ) from None
        if perf_counter() - call.prepared_at > call.timeout_seconds:
            raise ModelFailure(
                "timeout",
                sent=True,
                usage=result.usage,
                provider_request_id=result.provider_request_id,
            )
        return ModelResult(
            output=output,
            profile=call.profile,
            usage=result.usage,
            latency_ms=int((perf_counter() - started) * 1000),
            returned_model=result.returned_model,
            provider_request_id=result.provider_request_id,
        )
