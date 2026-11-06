"""Supported wire contracts, not a claim that every model or account has been verified."""

from dataclasses import dataclass
from typing import Literal
from urllib.parse import urlparse

from app.core.config import Settings
from app.modules.model_gateway.contracts import ModelFailure


@dataclass(frozen=True)
class Provider:
    id: str
    label: str
    base_url: str
    protocol: Literal["chat", "responses", "anthropic", "gemini"]
    output_mode: Literal["schema", "json"] = "schema"


PROVIDERS = {
    p.id: p
    for p in (
        Provider("openai", "OpenAI", "https://api.openai.com/v1", "responses"),
        Provider("anthropic", "Anthropic / Claude", "https://api.anthropic.com/v1", "anthropic"),
        Provider(
            "gemini",
            "Google / Gemini",
            "https://generativelanguage.googleapis.com/v1beta",
            "gemini",
        ),
        Provider(
            "bailian",
            "阿里云百炼 / Qwen",
            "https://dashscope.aliyuncs.com/compatible-mode/v1",
            "chat",
        ),
        Provider("deepseek", "DeepSeek", "https://api.deepseek.com/v1", "chat", "json"),
        Provider("openai_compatible", "其他 OpenAI 兼容服务", "", "chat", "json"),
    )
}


def check_endpoint(cfg: Settings) -> None:
    provider = PROVIDERS.get(cfg.ai_provider)
    if provider is None:
        raise ModelFailure("unsupported_capability")
    base = cfg.ai_base_url.rstrip("/")
    parsed = urlparse(base)
    if parsed.scheme != "https" or parsed.port not in (None, 443):
        raise ModelFailure("policy_denied")
    if base != provider.base_url and base not in cfg.ai_allowed_base_urls:
        raise ModelFailure("policy_denied")
