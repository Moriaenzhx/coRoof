from functools import lru_cache
from typing import Literal
from urllib.parse import urlparse

from pydantic import Field, PrivateAttr, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="COROOF_", env_file=".env", extra="ignore", hide_input_in_errors=True
    )
    environment: Literal["development", "test", "production"] = "development"
    database_url: str = "postgresql+psycopg://coroof:coroof@127.0.0.1:5432/coroof"
    redis_url: str = "redis://127.0.0.1:6379/0"
    web_origin: str = "http://localhost:3000"
    auth_mode: Literal["mock", "oidc"] = "mock"
    oidc_issuer: str = ""
    oidc_client_id: str = ""
    oidc_client_secret: SecretStr = SecretStr("")
    oidc_session_secret: SecretStr = SecretStr("")
    oidc_allowed_hosts: list[str] = []
    oidc_token_auth_method: Literal["client_secret_basic", "client_secret_post"] = (
        "client_secret_basic"
    )
    auth_session_hours: int = Field(default=24, ge=1, le=24)
    auth_rate_limit: str = "10/minute"
    invite_rate_limit: str = "20/hour"
    rate_limit_url: str = ""
    smtp_host: str = ""
    smtp_port: int = Field(default=587, ge=1, le=65535)
    smtp_username: str = ""
    smtp_password: SecretStr = SecretStr("")
    smtp_from: str = ""
    smtp_tls: Literal["starttls", "tls", "local"] = "starttls"
    mail_secret_key: SecretStr = SecretStr("")
    delivery_mode: Literal["mock", "smtp"] = "mock"
    ai_provider: Literal[
        "rules",
        "chat_completions",
        "bailian",
        "openai",
        "anthropic",
        "gemini",
        "deepseek",
        "openai_compatible",
    ] = "rules"
    ai_base_url: str = ""
    ai_model: str = Field(default="", max_length=50)
    ai_api_key: SecretStr = SecretStr("")
    ai_model_verified: bool = False
    ai_timeout_seconds: float = Field(default=25, gt=0, le=120)
    ai_max_output_tokens: int = Field(default=2500, ge=256, le=8000)
    ai_max_input_tokens: int = Field(default=24_000, ge=4000, le=64_000)
    ai_daily_call_limit: int = Field(default=100, ge=1, le=10000)
    ai_daily_token_limit: int = Field(default=200_000, ge=1000, le=10_000_000)
    ai_concurrency_limit: int = Field(default=2, ge=1, le=10)
    ai_monthly_token_limit: int = Field(default=6_000_000, ge=1000, le=1_000_000_000)
    ai_output_mode: Literal["schema", "json"] = "schema"
    ai_managed_connection: bool = False
    ai_connection_id: str | None = None
    ai_billing_mode: Literal["platform", "byok"] = "platform"
    ai_config_revision: int = 0
    ai_secret_key: SecretStr = SecretStr("")
    ai_allowed_base_urls: list[str] = []
    ai_development_test_connection_ids: list[str] = []
    # Only a tenant-authorized saved connection may set this internal selection.
    # It is not a settings/env field or an HTTP input.
    _local_test_connection_selected: bool = PrivateAttr(default=False)
    connector_allowed_base_urls: list[str] = []

    @field_validator("ai_base_url")
    @classmethod
    def validate_ai_url(cls, value: str) -> str:
        if value:
            try:
                url = urlparse(value)
                _ = url.port
            except ValueError:
                raise ValueError("Model endpoint is not a valid URL") from None
            if not url.hostname:
                raise ValueError("Model endpoint requires a hostname")
            if url.username or url.password or url.query or url.fragment:
                raise ValueError("Model URL must not contain credentials or query parameters")
            if url.scheme != "https" and not (
                url.scheme == "http" and url.hostname in {"localhost", "127.0.0.1", "::1"}
            ):
                raise ValueError("Model endpoint requires HTTPS (except local development)")
        return value

    cookie_secure: bool = False
    production_release_verified: bool = False

    def check_deployment(self) -> None:
        if self.environment == "production":
            from app.core.deployment import issues

            missing = issues(self)
            if missing:
                raise RuntimeError("Production is blocked: " + ", ".join(missing))


@lru_cache
def settings() -> Settings:
    return Settings()
