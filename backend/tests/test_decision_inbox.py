from datetime import datetime, timedelta
from uuid import uuid4

import pytest
from conftest import API
from test_slice02 import ask, confirm_body, prepare, supported

from app.infrastructure.db import session_factory
from app.infrastructure.models import Decision, Membership, WorkItem, now
from app.main import app


def record(api, decision, text="已核对但仍缺资料，继续跟进", key=None):
    return api.post(
        f"/decisions/{decision['id']}/outcomes",
        {
            "observed_result": text,
            "evidence_refs": [],
            "idempotency_key": key or str(uuid4()),
        },
        201,
    )


@pytest.fixture
def inbox(loop):
    boss, employee, org, depts, _, work = supported(loop)
    other = API("inbox-owner@example.com", "合成老板乙")
    membership = other.join(boss.invite(depts[0], "inbox-owner@example.com"), org["id"])
    with session_factory()() as db:
        db.get(Membership, membership["id"]).roles = ["owner"]
        db.commit()
    project = boss.post("/initiatives", {"title": "合成第二项目"}, 201)
    second = boss.work(depts[1], initiative_id=project["id"], title="合成第二项目事项")
    solo = boss.work(depts[0], title="合成独立事项")
    for item in (second, solo):
        boss.confirm(boss.draft(item))

    def decision(actor, item, *, confirmed=False, future=False):
        row = prepare(actor, ask(actor, item), item)
        if confirmed:
            body = confirm_body(row)
            if future:
                body["follow_up_at"] = (now() + timedelta(days=14)).isoformat()
            row = actor.post(f"/decisions/{row['id']}/confirm", body)
        return row

    rows = {
        "pending": decision(boss, work),
        "follow_up": decision(boss, work, confirmed=True, future=True),
        "recorded": decision(boss, work, confirmed=True),
        "other_pending": decision(other, work),
        "other_follow_up": decision(other, second, confirmed=True),
        "solo_recorded": decision(boss, solo, confirmed=True),
    }
    # The result recorder is not necessarily the decision's author.
    record(other, rows["recorded"])
    record(boss, rows["recorded"], "再次核对仍未解决")
    record(boss, rows["solo_recorded"])
    return boss, other, employee, org, depts, work, second, solo, rows


def identifiers(page):
    return {row["id"] for row in page["items"]}


def test_mine_is_current_server_actor_and_does_not_hide_company_records(inbox):
    boss, other, _, _, _, work, _, _, rows = inbox
    own_ids = {rows[key]["id"] for key in ("pending", "follow_up", "recorded", "solo_recorded")}
    other_ids = {rows[key]["id"] for key in ("other_pending", "other_follow_up")}
    assert identifiers(boss.get("/decisions")) == own_ids | other_ids
    assert identifiers(other.get("/decisions?mine=false")) == own_ids | other_ids
    assert identifiers(boss.get("/decisions?mine=true")) == own_ids
    assert identifiers(other.get("/decisions?mine=true")) == other_ids
    personal = boss.get("/decisions?mine=true&view=action_required")
    assert personal["total"] == 2
    assert identifiers(personal) == {rows[key]["id"] for key in ("pending", "follow_up")}
    other.get(f"/decisions/{rows['pending']['id']}")
    other.post(f"/decisions/{rows['pending']['id']}/confirm", confirm_body(rows["pending"]), 404)
    for row in boss.get(f"/decisions?initiative_id={work['initiative_id']}")["items"]:
        assert row["work_item_id"] == work["id"]


def test_view_and_project_filters_apply_before_totals_and_stable_pagination(inbox):
    boss, _, _, _, _, work, second, _, rows = inbox
    expected = {
        "all": set(rows),
        "pending": {"pending", "other_pending"},
        "follow_up": {"follow_up", "other_follow_up"},
        "recorded": {"recorded", "solo_recorded"},
        "action_required": {"pending", "other_pending", "follow_up", "other_follow_up"},
    }
    # Equal creation times exercise the stable decision-id tie-breaker.
    with session_factory()() as db:
        timestamp = now() - timedelta(minutes=1)
        for row in rows.values():
            db.get(Decision, row["id"]).created_at = timestamp
        db.commit()
    for view, keys in expected.items():
        ids = sorted(rows[key]["id"] for key in keys)
        pages = [
            boss.get(f"/decisions?view={view}&offset={offset}&limit=1")
            for offset in range(len(ids) + 1)
        ]
        assert all(page["total"] == len(ids) for page in pages)
        assert [page["items"][0]["id"] for page in pages[:-1]] == ids
        assert pages[-1]["items"] == []
    project = work["initiative_id"]
    filtered = boss.get(f"/decisions?mine=true&initiative_id={project}&view=recorded&limit=1")
    assert filtered["total"] == 1 and identifiers(filtered) == {rows["recorded"]["id"]}
    assert filtered["items"][0]["outcome_count"] == 2
    second_page = boss.get(f"/decisions?initiative_id={second['initiative_id']}&view=follow_up")
    assert identifiers(second_page) == {rows["other_follow_up"]["id"]}
    assert boss.get(f"/decisions?mine=true&initiative_id={second['initiative_id']}")["total"] == 0
    follow_up = next(
        row
        for row in boss.get("/decisions?view=follow_up")["items"]
        if row["id"] == rows["follow_up"]["id"]
    )
    assert datetime.fromisoformat(follow_up["follow_up_at"]) > now()
    assert follow_up["outcome_count"] == 0


def test_confirmation_and_idempotent_results_move_views_without_claiming_resolution(loop):
    boss, _, _, _, _, work = supported(loop)
    row = prepare(boss, ask(boss, work), work)
    assert identifiers(boss.get("/decisions?mine=true&view=pending")) == {row["id"]}
    assert boss.get("/decisions?view=follow_up")["total"] == 0
    body = {**confirm_body(row), "follow_up_at": (now() + timedelta(days=7)).isoformat()}
    confirmed = boss.post(f"/decisions/{row['id']}/confirm", body)
    assert boss.post(f"/decisions/{row['id']}/confirm", body) == confirmed
    assert "outcome_count" not in confirmed
    assert "outcome_count" not in boss.get(f"/decisions/{row['id']}")
    assert boss.get("/decisions?view=pending")["total"] == 0
    assert identifiers(boss.get("/decisions?view=follow_up")) == {row["id"]}
    assert identifiers(boss.get("/decisions?view=action_required")) == {row["id"]}
    key = str(uuid4())
    first = record(boss, row, key=key)
    repeated = record(boss, row, key=key)
    assert repeated["id"] == first["id"]
    assert datetime.fromisoformat(repeated["recorded_at"]) == datetime.fromisoformat(
        first["recorded_at"]
    )
    assert boss.get("/decisions?view=follow_up")["total"] == 0
    assert boss.get("/decisions?view=action_required")["total"] == 0
    recorded = boss.get("/decisions?view=recorded")
    assert recorded["total"] == 1 and recorded["items"][0]["outcome_count"] == 1
    record(boss, row, "仍未解决，需要继续核实")
    recorded = boss.get("/decisions?mine=true&view=recorded")
    assert recorded["total"] == 1 and recorded["items"][0]["outcome_count"] == 2
    current_work = boss.get(f"/work-items/{work['id']}")
    assert current_work["needs_support"]
    assert current_work["lifecycle_status"] == work["lifecycle_status"]
    assert current_work["version"] == work["version"]


def test_filters_preserve_owner_tenant_and_work_scope_authorization(inbox):
    boss, _, employee, org, depts, work, second, _, rows = inbox
    manager = API("inbox-manager@example.com", "合成主管")
    manager.join(boss.invite(depts[0], "inbox-manager@example.com", ["manager"]), org["id"])
    for actor in (employee, manager):
        for query in ("", "?mine=true", f"?initiative_id={work['initiative_id']}&view=recorded"):
            actor.get("/decisions" + query, 403)
    foreign = API("inbox-foreign@example.com", "合成其他企业老板")
    foreign.org("合成权限验收其他企业")
    foreign_project = foreign.post("/initiatives", {"title": "合成外部项目"}, 201)
    foreign_work = foreign.work(foreign.department(), initiative_id=foreign_project["id"])
    foreign.confirm(foreign.draft(foreign_work))
    foreign_row = prepare(foreign, ask(foreign, foreign_work), foreign_work)
    foreign.post(f"/decisions/{foreign_row['id']}/confirm", confirm_body(foreign_row))
    record(foreign, foreign_row)
    assert foreign.get("/decisions?mine=true&view=recorded")["items"][0]["outcome_count"] == 1
    assert foreign.get(f"/decisions?initiative_id={work['initiative_id']}")["total"] == 0
    assert boss.get(f"/decisions?initiative_id={foreign_project['id']}")["items"] == []
    assert foreign_row["id"] not in identifiers(boss.get("/decisions"))
    # Simulate a source becoming unavailable: Owner does not bypass work_scope.
    with session_factory()() as db:
        db.get(WorkItem, work["id"]).source_authority = "external"
        db.commit()
    visible = boss.get("/decisions")
    assert identifiers(visible) == {rows["other_follow_up"]["id"], rows["solo_recorded"]["id"]}
    assert visible["total"] == 2
    assert boss.get(f"/decisions?initiative_id={work['initiative_id']}")["total"] == 0
    assert boss.get(f"/decisions?initiative_id={second['initiative_id']}")["total"] == 1
    boss.get(f"/decisions/{rows['recorded']['id']}", 404)


def test_decision_list_contract_adds_required_counts_without_changing_detail(loop):
    boss, *_ = loop
    boss.get("/decisions?view=resolved", 422)
    boss.get("/decisions?mine=another-owner-id", 422)
    boss.get("/decisions?offset=-1", 422)
    schema = app.openapi()
    listing = schema["paths"]["/api/v1/decisions"]["get"]
    params = {item["name"]: item["schema"] for item in listing["parameters"]}
    assert params["mine"]["default"] is False
    assert params["view"]["default"] == "all"
    assert params["view"]["enum"] == ["all", "action_required", "pending", "follow_up", "recorded"]
    assert "initiative_id" in params
    definitions = schema["components"]["schemas"]
    assert "outcome_count" in definitions["DecisionListOut"]["required"]
    assert "outcome_count" not in definitions["DecisionOut"]["properties"]
    assert listing["responses"]["200"]["content"]["application/json"]["schema"] == {
        "$ref": "#/components/schemas/Page_DecisionListOut_"
    }
