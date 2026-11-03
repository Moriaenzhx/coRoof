from functools import lru_cache
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="COROOF_", env_file=".env", extra="ignore")
    environment: Literal["development", "test", "production"] = "development"
    database_url: str = "postgresql+psycopg://coroof:coroof@127.0.0.1:5432/coroof"
    redis_url: str = "redis://127.0.0.1:6379/0"
    web_origin: str = "http://localhost:3000"
    auth_mode: Literal["mock"] = "mock"
    ai_provider: Literal["rules"] = "rules"
    cookie_secure: bool = False

    def check_deployment(self) -> None:
        if self.environment == "production":
            raise RuntimeError(
                "Production is blocked: implement verified identity and real invite delivery; "
                "configure HTTPS, secure cookies, secrets, backups and access review first."
            )


@lru_cache
def settings() -> Settings:
    return Settings()
