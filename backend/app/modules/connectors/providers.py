"""Bounded read-only adapters. GitLab transport and resources use python-gitlab.

Feishu Project wire definitions are checked against larksuite/project-oapi-sdk-java;
this Python adapter only exposes plugin authentication and work_item/filter.
"""

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlsplit

import gitlab
import httpx
import requests
from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.core.config import settings
from app.modules.connectors.schemas import Credentials

PAGE_SIZE = 50
MAX_BODY = 2_000_000


class SourceFailure(Exception):
    def __init__(self, code: str, retryable: bool = False, status: int | None = None):
        self.code, self.retryable = code, retryable
        self.status = status
        super().__init__(code)  # Never include vendor response text or credentials.


class Item(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)
    external_id: str = Field(pattern=r"^[0-9]{1,100}$")
    title: str = Field(min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=16000)
    state: str | None = Field(default=None, max_length=100)
    assignees: list[str] | None = Field(default=None, max_length=20)
    source_at: datetime
    source_url: str | None = None
    deleted: bool = False
    raw: dict[str, Any]

    @field_validator("assignees")
    @classmethod
    def member_ids(cls, value: list[str] | None) -> list[str] | None:
        if value is not None and any(not member or len(member) > 100 for member in value):
            raise ValueError("invalid_member_id")
        return value


@dataclass(frozen=True)
class SourceConfig:
    kind: str
    base_url: str
    project_key: str
    item_type: str
    owner_field: str | None
    credentials: Credentials


@dataclass(frozen=True)
class Batch:
    items: list[Item]
    more: bool


def endpoint(value: str, kind: str) -> str:
    value = value.rstrip("/")
    url = urlsplit(value)
    allowed = {"https://gitlab.com"} if kind == "gitlab" else {"https://project.feishu.cn"}
    allowed.update(settings().connector_allowed_base_urls)
    if (
        value not in allowed
        or url.scheme != "https"
        or not url.hostname
        or url.username
        or url.password
        or url.query
        or url.fragment
        or url.path
    ):
        raise SourceFailure("endpoint_denied")
    return value


def same_origin(value: str, base: str) -> bool:
    left, right = urlsplit(value), urlsplit(base)
    return (left.scheme, left.netloc) == (right.scheme, right.netloc) and not left.username


def source_url(value: Any, base: str) -> str | None:
    if not isinstance(value, str) or len(value) > 1000:
        return None
    url = urlsplit(value)
    return value if same_origin(value, base) and not (url.query or url.fragment) else None


def status_error(status: int) -> None:
    if status in {401, 403, 404}:
        raise SourceFailure("source_denied", status=status)
    if status == 429 or status >= 500:
        raise SourceFailure("source_unavailable", retryable=True)
    if status != 200:
        raise SourceFailure("invalid_response")


class ReadSession(requests.Session):
    def __init__(self, base: str, project: str):
        super().__init__()
        self.base, self.project = base, project
        self.trust_env = False

    def send(self, request: requests.PreparedRequest, **kwargs: Any) -> requests.Response:
        url = request.url or ""
        path = urlsplit(url).path
        allowed_path = f"/api/v4/projects/{self.project}"
        if (
            request.method != "GET"
            or not same_origin(url, self.base)
            or not (path == allowed_path or path.startswith(allowed_path + "/issues"))
        ):
            raise SourceFailure("endpoint_denied")
        kwargs.update(allow_redirects=False, stream=True, timeout=15)
        response = super().send(request, **kwargs)
        if response.status_code != 200:
            response.close()
            status_error(response.status_code)
        data = bytearray()
        try:
            for chunk in response.iter_content(65536):
                data.extend(chunk)
                if len(data) > MAX_BODY:
                    raise SourceFailure("response_too_large")
        finally:
            response.close()
        response._content = bytes(data)
        return response


def gitlab_item(raw: dict[str, Any], cfg: SourceConfig) -> Item:
    if str(raw["project_id"]) != cfg.project_key:
        raise SourceFailure("scope_mismatch")
    at = datetime.fromisoformat(raw["updated_at"].replace("Z", "+00:00"))
    if at.tzinfo is None:
        raise SourceFailure("invalid_response")
    assignees = raw.get("assignees")
    owners = [str(member["id"]) for member in assignees] if isinstance(assignees, list) else None
    return Item(
        external_id=str(raw["iid"]),
        title=raw["title"],
        description=raw.get("description"),
        state=raw.get("state"),
        assignees=owners,
        source_at=at,
        source_url=source_url(raw.get("web_url"), cfg.base_url),
        raw=raw,
    )


def gitlab_fetch(
    cfg: SourceConfig,
    page: int,
    since: datetime | None,
    until: datetime,
    external_id: str | None,
    verify: bool,
) -> Batch:
    with ReadSession(cfg.base_url, cfg.project_key) as session:
        client = gitlab.Gitlab(
            cfg.base_url,
            private_token=cfg.credentials.token.get_secret_value(),
            session=session,
            timeout=15,
            retry_transient_errors=False,
        )
        # Check the actual project scope on every operation, including item reconciliation.
        project = client.projects.get(cfg.project_key, obey_rate_limit=False, max_retries=0)
        if str(project.id) != cfg.project_key:
            raise SourceFailure("scope_mismatch")
        if external_id:
            try:
                row = project.issues.get(external_id, obey_rate_limit=False, max_retries=0)
            except SourceFailure as exc:
                if exc.status in {403, 404}:
                    # The project was just checked. A missing/inaccessible item is withdrawn.
                    return Batch([], False)
                raise
            return Batch([gitlab_item(row.attributes, cfg)], False)
        per_page = 1 if verify else PAGE_SIZE
        query: dict[str, Any] = {"updated_before": until.isoformat()}
        if since:
            query["updated_after"] = since.isoformat()
        rows = project.issues.list(
            page=page,
            per_page=per_page,
            get_all=False,
            order_by="updated_at",
            sort="asc",
            scope="all",
            state="all",
            obey_rate_limit=False,
            max_retries=0,
            **query,
        )
        if len(rows) > per_page:
            raise SourceFailure("invalid_response")
        return Batch([gitlab_item(row.attributes, cfg) for row in rows], len(rows) == per_page)


def feishu_item(raw: dict[str, Any], cfg: SourceConfig) -> Item:
    if raw["project_key"] != cfg.project_key or raw["work_item_type_key"] != cfg.item_type:
        raise SourceFailure("scope_mismatch")
    fields = {field["field_key"]: field.get("field_value") for field in raw.get("fields", [])}
    owners = fields.get(cfg.owner_field) if cfg.owner_field else None
    if isinstance(owners, str):
        owners = [owners]
    if owners is not None and (
        not isinstance(owners, list) or not all(isinstance(x, str) for x in owners)
    ):
        owners = None
    state = raw.get("work_item_status") or {}
    return Item(
        external_id=str(raw["id"]),
        title=raw["name"],
        state=state.get("state_key"),
        assignees=owners,
        source_at=datetime.fromtimestamp(raw["updated_at"] / 1000, UTC),
        deleted=bool(raw.get("deleted_at")),
        raw=raw,
    )


def feishu_fetch(
    cfg: SourceConfig,
    page: int,
    since: datetime | None,
    until: datetime,
    external_id: str | None,
    verify: bool,
) -> Batch:
    with httpx.Client(timeout=15, follow_redirects=False, trust_env=False) as client:

        def post(
            path: str, body: dict[str, Any], headers: dict[str, str] | None = None
        ) -> dict[str, Any]:
            with client.stream("POST", cfg.base_url + path, json=body, headers=headers) as response:
                status_error(response.status_code)
                data = bytearray()
                for chunk in response.iter_bytes():
                    data.extend(chunk)
                    if len(data) > MAX_BODY:
                        raise SourceFailure("response_too_large")
            result = json.loads(data)
            if not isinstance(result, dict):
                raise SourceFailure("invalid_response")
            return result

        token = post(
            "/open_api/authen/plugin_token",
            {
                "plugin_id": cfg.credentials.plugin_id,
                "plugin_secret": cfg.credentials.plugin_secret.get_secret_value(),
                "type": 0,
            },
        )
        if token.get("error"):
            raise SourceFailure("source_denied")
        access_token = token["data"]["token"]
        if not isinstance(access_token, str) or not access_token:
            raise SourceFailure("source_denied")
        size = 1 if verify or external_id else PAGE_SIZE
        body: dict[str, Any] = {
            "work_item_type_keys": [cfg.item_type],
            "page_num": page,
            "page_size": size,
        }
        if external_id:
            body["work_item_ids"] = [int(external_id)]
        else:
            body["updated_at"] = {
                "start": int(since.timestamp() * 1000) if since else 0,
                "end": int(until.timestamp() * 1000),
            }
        result = post(
            f"/open_api/{cfg.project_key}/work_item/filter",
            body,
            {"X-Plugin-Token": access_token, "X-User-Key": cfg.credentials.user_key},
        )
        if result.get("err_code") != 0 or result.get("err"):
            raise SourceFailure("source_denied")
        data, pagination = result["data"], result["pagination"]
        if (
            not isinstance(data, list)
            or len(data) > size
            or pagination["page_num"] != page
            or pagination["page_size"] != size
            or pagination["total"] < len(data)
        ):
            raise SourceFailure("invalid_response")
        more = page * size < pagination["total"]
        if more and not data:
            raise SourceFailure("invalid_response")
        return Batch([feishu_item(row, cfg) for row in data], more)


def fetch(
    cfg: SourceConfig,
    page: int,
    since: datetime | None,
    until: datetime,
    *,
    external_id: str | None = None,
    verify: bool = False,
) -> Batch:
    endpoint(cfg.base_url, cfg.kind)
    try:
        batch = (gitlab_fetch if cfg.kind == "gitlab" else feishu_fetch)(
            cfg, page, since, until, external_id, verify
        )
        if external_id and any(item.external_id != external_id for item in batch.items):
            raise SourceFailure("scope_mismatch")
        return batch
    except SourceFailure:
        raise
    except (httpx.TransportError, requests.RequestException):
        raise SourceFailure("source_unavailable", retryable=True) from None
    except (gitlab.GitlabError, ValueError, TypeError, KeyError, OverflowError, AttributeError):
        raise SourceFailure("invalid_response") from None
