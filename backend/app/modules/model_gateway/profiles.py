import re
from urllib.parse import urlparse

from app.core.config import Settings
from app.modules.model_gateway.catalog import PROVIDERS, check_endpoint
from app.modules.model_gateway.contracts import ModelFailure, ModelProfile

CODING_PLAN_BASE_URL = "https://coding.dashscope.aliyuncs.com/v1"


def development_connection_allowed(
    cfg: Settings, identifier: str | None, provider: str, model: str, base_url: str
) -> bool:
    """Deployment-only permission for one saved local test connection; never a DTO flag."""
    try:
        origin = urlparse(cfg.web_origin)
        _ = origin.port
    except ValueError:
        return False
    return bool(
        cfg.environment in {"development", "test"}
        and cfg.auth_mode == "mock"
        and origin.scheme in {"http", "https"}
        and origin.hostname in {"localhost", "127.0.0.1", "::1"}
        and not (origin.username or origin.password or origin.query or origin.fragment)
        and origin.path in {"", "/"}
        and identifier
        and identifier in cfg.ai_development_test_connection_ids
        and provider == "bailian"
        and model == "qwen3.7-plus"
        and base_url.rstrip("/") == CODING_PLAN_BASE_URL
    )


def resolve_profile(cfg: Settings, *, verification_probe: bool = False) -> ModelProfile:
    if cfg.ai_provider == "rules" or not all(
        (cfg.ai_base_url, cfg.ai_model, cfg.ai_api_key.get_secret_value())
    ):
        raise ModelFailure("not_configured")
    endpoint = urlparse(cfg.ai_base_url)
    host = (endpoint.hostname or "").lower()
    if (
        cfg._local_test_connection_selected
        and cfg.ai_managed_connection
        and development_connection_allowed(
            cfg, cfg.ai_connection_id, cfg.ai_provider, cfg.ai_model, cfg.ai_base_url
        )
        and cfg.ai_api_key.get_secret_value().startswith("sk-sp-")
    ):
        if not (cfg.ai_model_verified or verification_probe):
            raise ModelFailure("not_verified")
        return ModelProfile(
            id=f"bailian-coding-plan-qwen37-local-{cfg.ai_output_mode}-v1",
            provider="bailian_coding_plan_test",
            model=cfg.ai_model,
            thinking=False,
            send_store=False,
            output_mode=cfg.ai_output_mode,
            capability_status="verified" if cfg.ai_model_verified else "documented",
            schema_in_prompt=True,
        )
    # An explicitly invoked developer probe may test the subscription endpoint.
    # It never enables the application route or verifies a general MaaS deployment.
    if (
        verification_probe
        and cfg.environment == "test"
        and cfg.ai_provider == "bailian"
        and cfg.ai_base_url.rstrip("/") == "https://coding.dashscope.aliyuncs.com/v1"
        and cfg.ai_api_key.get_secret_value().startswith("sk-sp-")
    ):
        if cfg.ai_model != "qwen3.7-plus":
            raise ModelFailure("unsupported_capability")
        return ModelProfile(
            id="bailian-coding-plan-qwen37-test-v2",
            provider="bailian_coding_plan_test",
            model=cfg.ai_model,
            thinking=False,
            send_store=False,
            capability_status="documented",
            schema_in_prompt=True,
        )
    # A subscription credential does not enable the application backend, even via a proxy.
    if cfg.ai_api_key.get_secret_value().startswith("sk-sp-") or host.startswith(
        ("coding.", "coding-intl.", "token-plan.")
    ):
        raise ModelFailure("policy_denied")
    if cfg.ai_managed_connection or cfg.ai_provider in {
        "openai",
        "anthropic",
        "gemini",
        "deepseek",
        "openai_compatible",
    }:
        check_endpoint(cfg)
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:/-]{0,99}", cfg.ai_model):
            raise ModelFailure("unsupported_capability")
        if not (cfg.ai_model_verified or verification_probe):
            raise ModelFailure("not_verified")
        provider = PROVIDERS[cfg.ai_provider]
        return ModelProfile(
            id=f"{cfg.ai_provider}-{cfg.ai_output_mode}-v1",
            provider=cfg.ai_provider,
            model=cfg.ai_model,
            thinking=False if cfg.ai_provider == "bailian" else None,
            send_store=cfg.ai_provider == "openai",
            protocol=provider.protocol,
            output_mode=cfg.ai_output_mode,
            schema_in_prompt=True,
            max_tokens_field="max_completion_tokens"
            if cfg.ai_provider == "bailian"
            else "max_tokens",
            capability_status="verified" if cfg.ai_model_verified else "documented",
        )
    if cfg.ai_provider == "bailian":
        legacy_host = host in {
            "dashscope.aliyuncs.com",
            "dashscope-intl.aliyuncs.com",
            "dashscope-us.aliyuncs.com",
        }
        workspace_host = re.fullmatch(
            r"[a-z0-9-]+\.(?:cn-beijing|ap-southeast-1|us-east-1|eu-central-1|"
            r"ap-northeast-1|cn-hongkong)\.maas\.aliyuncs\.com",
            host,
        )
        if (
            not (legacy_host or workspace_host)
            or endpoint.scheme != "https"
            or endpoint.port not in {None, 443}
            or endpoint.path.rstrip("/") != "/compatible-mode/v1"
        ):
            raise ModelFailure("policy_denied")
        if cfg.ai_model not in {"qwen3.7-plus", "qwen3.7-plus-2026-05-26"}:
            raise ModelFailure("unsupported_capability")
        if not (cfg.ai_model_verified or verification_probe):
            raise ModelFailure("not_verified")
        return ModelProfile(
            id="bailian-qwen37-fast-v1",
            provider="bailian",
            model=cfg.ai_model,
            thinking=False,
            send_store=False,
            capability_status="verified" if cfg.ai_model_verified else "documented",
        )
    return ModelProfile(
        id="legacy-chat-json-v1",
        provider="chat_completions",
        model=cfg.ai_model,
        thinking=None,
        send_store=True,
        capability_status="unknown",
    )
