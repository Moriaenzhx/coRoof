from pydantic import Field

from app.core.schemas import DTO


class OIDCStart(DTO):
    invite_token: str | None = Field(default=None, min_length=20, max_length=200)


class OIDCStartOut(DTO):
    authorization_url: str
