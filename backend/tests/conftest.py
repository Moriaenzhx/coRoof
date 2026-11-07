import os
from pathlib import Path
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

from app.core.config import settings
from app.infrastructure.db import session_factory
from app.main import app


@pytest.fixture(autouse=True)
def database(tmp_path, monkeypatch):
    # Offline tests must never inherit a developer's real model configuration.
    monkeypatch.setenv("COROOF_AI_PROVIDER", "rules")
    monkeypatch.setenv("COROOF_AI_API_KEY", "")
    monkeypatch.setenv("COROOF_AI_MODEL_VERIFIED", "false")
    base_url = os.environ.get("COROOF_TEST_DATABASE_URL")
    admin = None
    schema = "test_" + uuid4().hex
    if base_url:
        parsed = make_url(base_url)
        if "test" not in (parsed.database or ""):
            raise RuntimeError("Only a dedicated database with 'test' in its name is allowed")
        admin = create_engine(base_url)
        with admin.begin() as connection:
            connection.execute(text(f'CREATE SCHEMA "{schema}"'))
        url = parsed.update_query_dict({"options": f"-csearch_path={schema}"})
        target = url.render_as_string(hide_password=False)
    else:
        target = f"sqlite:///{tmp_path / 'test.db'}"
    monkeypatch.setenv("COROOF_DATABASE_URL", target)
    monkeypatch.setenv("COROOF_ENVIRONMENT", "test")
    settings.cache_clear()
    session_factory.cache_clear()
    config = Config(str(Path(__file__).parents[1] / "alembic.ini"))
    command.upgrade(config, "head")
    yield config
    engine = session_factory().kw["bind"]
    engine.dispose()
    session_factory.cache_clear()
    settings.cache_clear()
    if admin:
        with admin.begin() as connection:
            connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        admin.dispose()


class API:
    def __init__(self, email="owner@example.com", name="老板"):
        self.client = TestClient(app)
        self.client.headers["X-CoRoof-Request"] = "1"
        result = self.post("/auth/request-link", {"email": email, "name": name})
        self.user = self.post("/auth/verify", {"token": result["token"]})

    def request(self, method, path, body=None):
        return self.client.request(method, f"/api/v1{path}", json=body)

    def post(self, path, body=None, status=200):
        response = self.request("POST", path, body)
        assert response.status_code == status, response.text
        return response.json()

    def get(self, path, status=200):
        response = self.request("GET", path)
        assert response.status_code == status, response.text
        return response.json()

    def org(self, name="验收企业甲"):
        org = self.post("/organizations", {"name": name}, 201)
        self.client.headers["X-Organization-Id"] = org["id"]
        return org

    def department(self, name="交付"):
        return self.post("/departments", {"name": name}, 201)

    def invite(self, dept, email="member@example.com", roles=None):
        return self.post(
            "/members/invitations",
            {
                "email": email,
                "department_id": dept["id"],
                "roles": roles or ["member"],
            },
            201,
        )

    def join(self, invitation, org_id):
        member = self.post(
            "/members/invitations/accept", {"token": invitation["delivery"]["token"]}
        )
        self.client.headers["X-Organization-Id"] = org_id
        return member

    def work(self, dept, member=None, **extra):
        return self.post(
            "/work-items",
            {
                "title": "确认客户交付资料",
                "department_id": dept["id"],
                "owner_id": member["id"] if member else None,
                **extra,
            },
            201,
        )

    def draft(self, work, raw="客户资料晚到两天，需要交付协调"):
        return self.post("/work-updates/drafts", {"work_item_id": work["id"], "raw_text": raw}, 201)

    def confirm(self, draft, status=200):
        return self.post(
            f"/work-updates/drafts/{draft['id']}/confirm",
            {"expected_revision": draft["revision"]},
            status,
        )


@pytest.fixture
def loop():
    boss = API()
    org = boss.org()
    depts = [boss.department(name) for name in ("交付", "销售", "研发")]
    initiative = boss.post("/initiatives", {"title": "客户交付项目"}, 201)
    employee = API("member@example.com", "同事甲")
    invitation = boss.invite(depts[0])
    member = employee.join(invitation, org["id"])
    work = boss.work(depts[0], member, initiative_id=initiative["id"])
    return boss, employee, org, depts, member, work
