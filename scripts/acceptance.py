"""HTTP acceptance against a running *development* stack, creating labeled synthetic data.

Run from backend: uv run python ../scripts/acceptance.py --base-url http://localhost:3000
"""

import argparse
import json
from uuid import uuid4

import httpx

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--base-url", default="http://localhost:3000")
parser.add_argument("--label", default=uuid4().hex[:8])
parser.add_argument(
    "--slice02", action="store_true", help="Also verify evidence, decisions and outcomes"
)
args = parser.parse_args()
base = args.base_url.rstrip("/") + "/api/v1"


def login(email, name):
    client = httpx.Client(base_url=base, headers={"X-CoRoof-Request": "1"}, timeout=20)
    runtime = client.get("/runtime").raise_for_status().json()
    assert runtime["environment"] in {"development", "test"} and runtime["auth_mode"] == "mock"
    challenge = post(client, "/auth/request-link", {"email": email, "name": name})
    post(client, "/auth/verify", {"token": challenge["token"]})
    return client


def post(client, path, payload):
    response = client.post(path, json=payload)
    response.raise_for_status()
    return response.json()


owner_email = f"owner-{args.label}@example.com"
member_email = f"member-{args.label}@example.com"
boss = login(owner_email, "验收老板")
org = post(boss, "/organizations", {"name": f"coRoof 验收示例 · {args.label}"})
boss.headers["X-Organization-Id"] = org["id"]
departments = [post(boss, "/departments", {"name": name}) for name in ("销售", "研发", "交付")]
initiative = post(boss, "/initiatives", {"title": "客户交付项目", "goal": "完成客户资料确认与交付"})
invitation = post(
    boss,
    "/members/invitations",
    {
        "email": member_email,
        "department_id": departments[2]["id"],
        "roles": ["member"],
    },
)
employee = login(member_email, "验收同事")
member = post(employee, "/members/invitations/accept", {"token": invitation["delivery"]["token"]})
employee.headers["X-Organization-Id"] = org["id"]
work = post(
    boss,
    "/work-items",
    {
        "title": "客户资料确认",
        "description": "确认资料后进入交付环节。",
        "department_id": departments[2]["id"],
        "owner_id": member["id"],
        "initiative_id": initiative["id"],
    },
)
assert employee.get("/work-items?mine=true").raise_for_status().json()["total"] == 1
draft = post(
    employee,
    "/work-updates/drafts",
    {
        "work_item_id": work["id"],
        "raw_text": "客户资料晚到两天，需要交付协调",
    },
)
assert not boss.get(f"/work-items/{work['id']}").raise_for_status().json()["needs_support"]
event = post(
    employee,
    f"/work-updates/drafts/{draft['id']}/confirm",
    {
        "expected_revision": draft["revision"],
    },
)
repeat = post(
    employee,
    f"/work-updates/drafts/{draft['id']}/confirm",
    {
        "expected_revision": draft["revision"],
    },
)
assert repeat["id"] == event["id"]
dashboard = boss.get("/dashboard").raise_for_status().json()
assert dashboard["support_work"] == 1
assert sum(d["coverage"] == "unknown" for d in dashboard["departments"]) == 2
assert boss.get(f"/work-items/{work['id']}/events").json()["total"] == 2
slice02 = None
if args.slice02:
    signals = boss.get("/signals").raise_for_status().json()["items"]
    assert any(s["category"] == "support" for s in signals)
    answer = post(
        boss, "/ai/ask", {"question": "这项工作需要怎样跟进？", "work_item_id": work["id"]}
    )
    evidence = boss.get("/evidence/" + answer["evidence"][0]["id"]).raise_for_status().json()
    assert evidence["event_id"] == event["id"] and evidence["facts"]["needs_support"]
    decision = post(
        boss,
        "/decisions",
        {"analysis_id": answer["id"], "work_item_id": work["id"], "idempotency_key": str(uuid4())},
    )
    assert decision["state"] == "pending"
    confirm = {
        "expected_version": decision["version"],
        "selected_option": decision["options"][0]["id"],
        "selected_plan": "验收：与负责人核实资料到位情况",
        "follow_up": "验收：核实后追加实际结果",
    }
    path = f"/decisions/{decision['id']}/confirm"
    assert employee.post(path, json=confirm).status_code == 403
    first = post(boss, path, confirm)
    assert first == post(boss, path, confirm)
    outcome = {
        "observed_result": "验收：已核实仍缺资料，尚未解除支持需求",
        "evidence_refs": [evidence["id"]],
        "idempotency_key": str(uuid4()),
    }
    path = f"/decisions/{decision['id']}/outcomes"
    recorded = post(boss, path, outcome)
    assert recorded["id"] == post(boss, path, outcome)["id"]
    assert boss.get(path).raise_for_status().json()["total"] == 1
    assert boss.get(f"/work-items/{work['id']}").raise_for_status().json()["needs_support"]
    assert boss.get(f"/work-items/{work['id']}/events").raise_for_status().json()["total"] == 4
    slice02 = {
        "analysis_mode": answer["mode"],
        "decision_id": decision["id"],
        "outcome_id": recorded["id"],
        "duplicate_decision_confirmation": "one event",
    }
print(
    json.dumps(
        {
            "result": "passed",
            "data": "synthetic acceptance data in real local database",
            "owner_email": owner_email,
            "member_email": member_email,
            "organization_id": org["id"],
            "work_id": work["id"],
            "event_id": event["id"],
            "duplicate_confirmation": "one event",
            "slice02": slice02,
        },
        ensure_ascii=False,
        indent=2,
    )
)
boss.close()
employee.close()
