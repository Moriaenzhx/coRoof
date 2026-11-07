from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import Field, SecretStr, field_validator, model_validator

from app.core.schemas import DTO, Status

Kind = Literal["gitlab", "feishu_project"]
Mode = Literal["verify", "full", "incremental"]


class Credentials(DTO):
    token: SecretStr = SecretStr("")
    plugin_id: str = Field(default="", max_length=100)
    plugin_secret: SecretStr = SecretStr("")
    user_key: str = Field(default="", max_length=100)


class ConnectorInput(DTO):
    name: str = Field(min_length=1, max_length=100)
    kind: Kind
    base_url: str = Field(max_length=200)
    project_key: str = Field(pattern=r"^[A-Za-z0-9_-]{1,100}$")
    item_type: str = Field(default="issue", pattern=r"^[A-Za-z0-9_-]{1,100}$")
    department_id: UUID
    owner_field: str | None = Field(default=None, pattern=r"^[A-Za-z0-9_-]{1,100}$")
    status_map: dict[str, Status] = Field(default_factory=dict, max_length=40)
    credentials: Credentials
    share_with_department: Literal[True]

    @model_validator(mode="after")
    def credentials_for_kind(self) -> "ConnectorInput":
        if self.kind == "gitlab":
            if not self.project_key.isdigit() or not self.credentials.token.get_secret_value():
                raise ValueError("GitLab requires a numeric project ID and read token")
            self.item_type = "issue"
        elif not all(
            (
                self.credentials.plugin_id,
                self.credentials.plugin_secret.get_secret_value(),
                self.credentials.user_key,
            )
        ):
            raise ValueError("Feishu Project requires plugin credentials and user_key")
        return self

    @field_validator("status_map")
    @classmethod
    def status_keys(cls, value: dict[str, Status]) -> dict[str, Status]:
        if any(not key.strip() or len(key) > 100 for key in value):
            raise ValueError("invalid_state_key")
        return value


class ConnectorOut(DTO):
    id: str
    name: str
    kind: Kind
    base_url: str
    project_key: str
    item_type: str
    department_id: str
    owner_field: str | None
    status_map: dict[str, Status]
    key_hint: str
    state: str
    version: int
    tested_at: datetime | None
    synced_at: datetime | None
    last_error: str | None
    source_count: int
    pending_count: int


class ConnectorVersion(DTO):
    expected_version: int = Field(ge=1)


class ConnectorAction(ConnectorVersion):
    action: Literal["activate", "pause", "revoke"]


class MappingInput(ConnectorVersion):
    status_map: dict[str, Status] = Field(max_length=40)
    members: dict[str, UUID | None] = Field(default_factory=dict, max_length=100)
    owner_field: str | None = Field(default=None, pattern=r"^[A-Za-z0-9_-]{1,100}$")

    @field_validator("status_map", "members")
    @classmethod
    def keys(cls, value: dict[str, Any]) -> dict[str, Any]:
        if any(not key.strip() or len(key) > 100 for key in value):
            raise ValueError("invalid_mapping_key")
        return value


class RotateInput(ConnectorVersion):
    credentials: Credentials


class SyncInput(ConnectorVersion):
    mode: Mode = "full"
    idempotency_key: UUID


class SyncOut(DTO):
    version: int
    id: str
    connector_id: str
    mode: Mode
    state: str
    phase: str
    page: int
    processed: int
    error_code: str | None
    created_at: datetime
    finished_at: datetime | None


class SourceOut(DTO):
    id: str
    external_id: str
    title: str
    external_state: str | None
    assignees: list[str]
    work_item_id: str | None
    state: str
    mapping_issue: str | None
    source_at: datetime
    checked_at: datetime


class MemberMapOut(DTO):
    external_id: str
    membership_id: str | None


class SourceDetail(DTO):
    connector_name: str
    kind: Kind
    external_id: str
    source_url: str | None
    source_at: datetime
    observed_at: datetime
    last_error: str | None
    notice: str = "外部源维护；截止日期与支持需求未同步，不据此判断健康。"
