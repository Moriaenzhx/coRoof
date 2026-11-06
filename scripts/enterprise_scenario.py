"""A reproducible, synthetic multi-role company rehearsal over the public HTTP API.

Only loopback development/mock stacks are accepted by the CLI. Every actor has
an independent session. No external connector or model is enabled by this run.
The same scenario is exercised against an isolated PostgreSQL schema in pytest.
"""

import argparse
import json
import re
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from urllib.parse import urlparse
from uuid import uuid4

import httpx


def key():
    return str(uuid4())


def timestamp(days=0, seconds=0):
    return (datetime.now(UTC) + timedelta(days=days, seconds=seconds)).isoformat()


class ScenarioFailure(Exception):
    """Safe assertion text; never includes response bodies, cookies or tokens."""


class EnterpriseScenario:
    def __init__(self, client_factory, label, tick=None, *, pause_models=True):
        if not re.fullmatch(r"[a-z0-9-]{1,32}", label):
            raise ValueError("label_must_be_short_ascii")
        self.factory, self.label, self.tick = client_factory, label, tick
        self.pause_models = pause_models
        self.clients, self.people, self.works, self.departments = {}, {}, {}, {}
        self.timings = []
        self.report = {
            "scenario": "星桥软件 · 双项目交付演练",
            "synthetic_data": True,
            "real_identity_verified": False,
            "external_connectors_used": False,
            "model_mode": "rules_only",
            "passed": False,
            "checks": [],
            "accounts": [],
            "artifacts": {},
            "started_at": timestamp(),
        }

    def check(self, name, condition):
        self.report["checks"].append({"name": name, "passed": bool(condition)})
        if not condition:
            raise ScenarioFailure(name)

    def request(self, who, method, path, body=None, status=None):
        start = time.monotonic()
        response = self.clients[who].request(method, "/api/v1" + path, json=body)
        self.timings.append(time.monotonic() - start)
        allowed = {status} if isinstance(status, int) else set(status or [200, 201])
        if response.status_code not in allowed:
            raise ScenarioFailure(f"{who} {method} {path}: HTTP {response.status_code}")
        return response.json() if response.content else None

    def get(self, who, path):
        return self.request(who, "GET", path)

    def post(self, who, path, body=None):
        return self.request(who, "POST", path, body)

    def deny(self, name, who, method, path, body=None, status=(403, 404)):
        self.request(who, method, path, body, status=status)
        self.check(name, True)

    def login(self, who, name, role, department=None):
        email = f"{who}-{self.label}@example.com"
        self.clients[who] = self.factory()
        self.clients[who].headers["X-CoRoof-Request"] = "1"
        runtime = self.get(who, "/runtime")
        if runtime["environment"] not in {"test", "development"} or runtime["auth_mode"] != "mock":
            raise ScenarioFailure("development_mock_stack_required")
        if not self.pause_models and runtime["environment"] != "test":
            raise ScenarioFailure("model_probe_requires_isolated_test_environment")
        challenge = self.post(who, "/auth/request-link", {"email": email, "name": name})
        self.post(who, "/auth/verify", {"token": challenge["token"]})
        self.report["accounts"].append(
            {
                "actor": who,
                "name": name,
                "role": role,
                "department": department,
                "email": email,
            }
        )
        return email

    def initialize(self):
        self.login("owner", "林澄 · 模拟老板", "owner")
        self.org = self.post(
            "owner", "/organizations", {"name": f"模拟企业 · 星桥软件 · {self.label}"}
        )
        self.clients["owner"].headers["X-Organization-Id"] = self.org["id"]
        self.report["artifacts"]["organization_id"] = self.org["id"]
        # This rehearsal must never spend a tenant's inherited model budget.
        current = self.get("owner", "/ai/settings")
        self.request(
            "owner",
            "PUT",
            "/ai/settings",
            {
                "expected_version": current["version"],
                "mode": "disabled" if self.pause_models else "platform",
                "daily_call_limit": 20,
                "daily_token_limit": 50000,
                "monthly_token_limit": 100000,
                "concurrency_limit": 1,
                "alert_percent": 80,
            },
        )
        for dept, title in [
            ("sales", "销售"),
            ("dev", "研发"),
            ("delivery", "交付"),
            ("finance", "财务（未录入）"),
        ]:
            self.departments[dept] = self.post("owner", "/departments", {"name": title})
        names = {
            "sales": ["沈宁", "许禾", "赵远"],
            "dev": ["陈屿", "周然", "唐悦"],
            "delivery": ["顾岚", "陆川", "宋晴"],
        }
        for dept, members in names.items():
            for index, name in enumerate(members):
                who = f"{dept}-{index}"
                role = "manager" if index == 0 else "member"
                email = self.login(who, name + " · 模拟", role, dept)
                invite = self.post(
                    "owner",
                    "/members/invitations",
                    {
                        "email": email,
                        "department_id": self.departments[dept]["id"],
                        "roles": [role],
                        "idempotency_key": key(),
                    },
                )
                self.people[who] = self.post(
                    who,
                    "/members/invitations/accept",
                    {"token": invite["delivery"]["token"]},
                )
                self.clients[who].headers["X-Organization-Id"] = self.org["id"]
        self.login("outsider", "外部企业老板 · 模拟", "foreign_owner")
        foreign = self.post(
            "outsider",
            "/organizations",
            {"name": f"隔离对照 · 模拟外部企业 · {self.label}"},
        )
        self.clients["outsider"].headers["X-Organization-Id"] = foreign["id"]
        self.report["artifacts"]["foreign_organization_id"] = foreign["id"]
        self.check(
            "01 建立10人企业、3种角色及独立外部企业",
            self.get("owner", "/members")["total"] == 10,
        )
        self.projects = {}
        for code, title, goal in [
            (
                "atlas",
                "青禾商城一期交付（模拟）",
                "核实客户资料、完成开发与验收；未收到客户确认不视为交付完成。",
            ),
            (
                "beacon",
                "远帆客户续约与升级（模拟）",
                "推进续约材料和升级验证；未登记回款数据时保持未知。",
            ),
        ]:
            self.projects[code] = self.post(
                "owner",
                "/initiatives",
                {"title": title, "goal": goal, "due_at": timestamp(days=7)},
            )
        self.report["artifacts"]["projects"] = self.projects
        definitions = [
            ("scope", "青禾需求范围确认", "sales-1", "atlas", 1),
            ("renewal", "远帆续约材料整理", "sales-2", "beacon", 4),
            ("handoff", "青禾客户交接清单", "sales-1", "atlas", 2),
            ("api", "青禾订单接口联调", "dev-1", "atlas", 1),
            ("ui", "青禾后台界面验收", "dev-2", "atlas", 3),
            ("upgrade", "远帆升级回归验证", "dev-1", "beacon", 5),
            ("material", "青禾客户资料确认", "delivery-1", "atlas", 1),
            ("training", "青禾用户培训准备", "delivery-2", "atlas", 3),
            ("overdue", "远帆验收记录补齐", "delivery-2", "beacon", -1),
            ("done", "青禾启动会纪要", "sales-2", "atlas", 0),
            ("cancelled", "远帆旧版导入脚本", "dev-2", "beacon", 2),
            ("unknown", "远帆后续运维范围待核实", "delivery-1", "beacon", None),
        ]
        assigned_scopes = set()
        for code, title, actor, project, days in definitions:
            dept = actor.split("-")[0]
            # Company projects become visible to a manager through assigned work.
            # The owner assigns the first item; the manager can then break down more.
            creator = dept + "-0" if (dept, project) in assigned_scopes else "owner"
            self.works[code] = self.post(
                creator,
                "/work-items",
                {
                    "title": title + "（模拟）",
                    "description": "经营演练合成事项，不代表真实客户。",
                    "department_id": self.departments[dept]["id"],
                    "owner_id": self.people[actor]["id"],
                    "initiative_id": self.projects[project]["id"],
                    "due_at": timestamp(days=days) if days is not None else None,
                },
            )
            assigned_scopes.add((dept, project))
        self.report["artifacts"]["work_ids"] = {code: row["id"] for code, row in self.works.items()}
        self.check(
            "02 两项目12事项、负责人和截止时间可追踪",
            self.get("owner", "/work-items")["total"] == 12,
        )

    def permissions(self):
        for dept in ("sales", "dev", "delivery"):
            self.check(
                f"03 {dept}负责人仅见本部门4项工作",
                self.get(dept + "-0", "/work-items")["total"] == 4,
            )
            for index in (1, 2):
                self.check(
                    f"03 {dept}-{index}员工仅见本人2项工作",
                    self.get(f"{dept}-{index}", "/work-items")["total"] == 2,
                )
        work = self.works["material"]
        for who in ("sales-0", "delivery-2", "outsider"):
            self.deny(f"04 {who}不能查看未授权事项", who, "GET", f"/work-items/{work['id']}")
        self.deny(
            "04 员工不能列出同事详情",
            "delivery-1",
            "GET",
            f"/members/{self.people['delivery-2']['id']}",
        )
        self.deny(
            "04 员工不能创建事项",
            "delivery-1",
            "POST",
            "/work-items",
            {
                "title": "越权应拒绝",
                "department_id": self.departments["delivery"]["id"],
            },
        )
        self.deny(
            "04 主管不能跨部门创建事项",
            "sales-0",
            "POST",
            "/work-items",
            {"title": "越权应拒绝", "department_id": self.departments["dev"]["id"]},
        )
        for who in ("delivery-0", "delivery-1"):
            self.deny(f"04 {who}不能配置企业模型", who, "GET", "/ai/settings")
            self.deny(f"04 {who}不能查看老板记忆", who, "GET", "/memory/entries")
            self.check(
                f"04 {who}仅见本人模型用量",
                self.get(who, "/ai/usage")["scope"] == "self",
            )
        invitation = {
            "email": f"declined-{self.label}@example.com",
            "department_id": self.departments["dev"]["id"],
            "roles": ["manager"],
        }
        self.deny(
            "04 主管不能跨部门邀请和提权",
            "sales-0",
            "POST",
            "/members/invitations",
            invitation,
        )
        self.clients["outsider"].headers["X-Organization-Id"] = self.org["id"]
        try:
            self.deny("04 伪造企业头不能取得租户权限", "outsider", "GET", "/dashboard")
        finally:
            self.clients["outsider"].headers["X-Organization-Id"] = self.report["artifacts"][
                "foreign_organization_id"
            ]
        dash = self.get("owner", "/dashboard")
        finance = next(
            d
            for d in dash["departments"]
            if d["department"]["id"] == self.departments["finance"]["id"]
        )
        self.check(
            "05 空财务部门保持未知，不编造收入或健康",
            finance["coverage"] == "unknown"
            and finance["work_count"] == 0
            and dash["external_data"] == "not_connected",
        )

    def work(self, code):
        return self.get("owner", f"/work-items/{self.works[code]['id']}")

    def events(self, code):
        return self.get("owner", f"/work-items/{self.works[code]['id']}/events")["items"]

    def quick(self, who, code, action, summary):
        row = self.work(code)
        return self.post(
            who,
            f"/work-items/{row['id']}/updates",
            {
                "action": action,
                "summary": summary,
                "expected_version": row["version"],
                "idempotency_key": key(),
            },
        )

    def updates(self):
        target = self.works["material"]
        before = len(self.events("material"))
        draft = self.post(
            "delivery-1",
            "/work-updates/drafts",
            {
                "work_item_id": target["id"],
                "raw_text": (
                    "模拟汇报：客户商品图片和价格表尚未到位，需要销售支持。实际交付结果未知。"
                ),
            },
        )
        self.check(
            "06 未确认草稿不改变工作或产生进展事件",
            not self.work("material")["needs_support"] and len(self.events("material")) == before,
        )
        confirm = {"expected_revision": draft["revision"]}
        path = f"/work-updates/drafts/{draft['id']}/confirm"
        self.deny("06 老板不能代员工确认草稿", "owner", "POST", path, confirm)
        self.deny("06 主管不能代员工确认草稿", "delivery-0", "POST", path, confirm)
        event = self.post("delivery-1", path, confirm)
        self.check(
            "07 作者确认和重放只有一次效果",
            self.post("delivery-1", path, confirm)["id"] == event["id"]
            and len(self.events("material")) == before + 1
            and self.work("material")["needs_support"],
        )
        self.report["artifacts"]["support_event_id"] = event["id"]
        for who, code, summary in [
            ("sales-1", "scope", "已核对需求清单，待客户确认。"),
            ("dev-2", "ui", "界面已进入内部检查，未确认客户验收。"),
            ("dev-1", "upgrade", "开始升级回归，实际结果待记录。"),
        ]:
            self.quick(who, code, "progress", "模拟汇报：" + summary)
        self.quick("dev-1", "api", "support", "模拟汇报：测试接口凭据未收到，需要项目协调。")
        self.quick("sales-2", "done", "done", "模拟确认：启动会纪要已核对完成。")
        cancel = self.post(
            "dev-2",
            "/work-updates/drafts",
            {
                "work_item_id": self.works["cancelled"]["id"],
                "raw_text": "模拟确认：旧版导入脚本已取消。",
            },
        )
        cancel = self.request(
            "dev-2",
            "PATCH",
            f"/work-updates/drafts/{cancel['id']}",
            {
                "expected_revision": cancel["revision"],
                "proposed_fields": {
                    "summary": "模拟确认：旧版导入脚本已取消。",
                    "lifecycle_status": "cancelled",
                    "needs_support": False,
                },
            },
        )
        self.post(
            "dev-2",
            f"/work-updates/drafts/{cancel['id']}/confirm",
            {"expected_revision": cancel["revision"]},
        )
        row = self.work("ui")
        body = {
            "action": "progress",
            "summary": "模拟：第一轮检查完成，等待复核。",
            "expected_version": row["version"],
            "idempotency_key": key(),
        }
        first = self.post("dev-2", f"/work-items/{row['id']}/updates", body)
        self.check(
            "08 快捷更新重放不重复写入",
            self.post("dev-2", f"/work-items/{row['id']}/updates", body)["id"] == first["id"],
        )
        self.deny(
            "08 同一幂等键不同内容拒绝",
            "dev-2",
            "POST",
            f"/work-items/{row['id']}/updates",
            {**body, "summary": "不同内容"},
            status=409,
        )
        self.deny(
            "08 旧工作版本更新拒绝",
            "dev-2",
            "POST",
            f"/work-items/{row['id']}/updates",
            {**body, "idempotency_key": key()},
            status=409,
        )
        done = self.work("done")
        self.deny(
            "08 已完成事项不能继续更新",
            "sales-2",
            "POST",
            f"/work-items/{done['id']}/updates",
            {**body, "expected_version": done["version"], "idempotency_key": key()},
            status=409,
        )
        signals = self.get("owner", "/signals")["items"]
        self.check(
            "09 明确支持、临近截止、逾期信号来自实际字段",
            all(
                any(
                    s["work_item_id"] == self.works[code]["id"] and s["category"] == category
                    for s in signals
                )
                for code, category in [
                    ("material", "support"),
                    ("material", "deadline_blocked"),
                    ("overdue", "overdue"),
                ]
            ),
        )
        self.check(
            "09 完成与取消事项无有效信号",
            not any(
                s["work_item_id"] in {done["id"], self.works["cancelled"]["id"]} for s in signals
            ),
        )

    def knowledge(self):
        def create(who, title, content, **extra):
            return self.post(
                who,
                "/knowledge/documents",
                {"title": title, "content": content, "idempotency_key": key(), **extra},
            )

        def publish(who, doc):
            return self.post(
                who,
                f"/knowledge/documents/{doc['id']}/publish",
                {
                    "expected_version": doc["version"],
                    "idempotency_key": key(),
                    "revision_id": doc["draft_id"],
                    "confirm": True,
                },
            )

        handbook = create(
            "owner",
            "模拟交付验收制度",
            "模拟制度：客户验收必须附清单和客户确认记录。资料未齐全时不得写成已交付。",
            visibility="organization",
        )
        self.check(
            "10 未发布知识不被员工检索",
            self.get("delivery-1", "/knowledge/search?q=验收")["total"] == 0,
        )
        self.deny(
            "10 员工不能代作者发布制度",
            "delivery-1",
            "POST",
            f"/knowledge/documents/{handbook['id']}/publish",
            {
                "expected_version": handbook["version"],
                "idempotency_key": key(),
                "revision_id": handbook["draft_id"],
                "confirm": True,
            },
        )
        handbook = publish("owner", handbook)
        self.check(
            "10 企业制度发布后可按原文检索",
            self.get("delivery-1", "/knowledge/search?q=验收")["total"] > 0,
        )
        private = publish(
            "sales-1",
            create(
                "sales-1",
                "模拟私人访谈笔记",
                "合成私密标识：紫杉报价底线，仅用于访问隔离验证。",
            ),
        )
        departmental = publish(
            "dev-0",
            create(
                "dev-0",
                "模拟研发回归清单",
                "模拟研发制度：回归结果需要保留测试记录。",
                visibility="department",
                department_id=self.departments["dev"]["id"],
            ),
        )
        self.deny(
            "11 老板也不能读取员工私有文档",
            "owner",
            "GET",
            f"/knowledge/documents/{private['id']}",
        )
        self.deny(
            "11 销售不能读取研发部门文档",
            "sales-1",
            "GET",
            f"/knowledge/documents/{departmental['id']}",
        )
        self.deny(
            "11 外部企业不能读取企业制度",
            "outsider",
            "GET",
            f"/knowledge/documents/{handbook['id']}",
        )
        self.check(
            "11 未授权私有内容不进入老板检索",
            self.get("owner", "/knowledge/search?q=紫杉")["total"] == 0,
        )
        edit = self.post(
            "owner",
            f"/knowledge/documents/{handbook['id']}/edit",
            {
                "expected_version": handbook["version"],
                "idempotency_key": key(),
                "title": handbook["title"],
                "content": "模拟制度第二版：验收需客户确认记录，未确认的交付结果必须标明未知。",
            },
        )
        old = self.get("delivery-1", "/knowledge/search?q=验收")["items"][0]
        self.check(
            "12 修订草稿不替代已发布制度",
            old["revision_id"] == handbook["published_id"],
        )
        revised = publish("owner", edit)
        self.check(
            "12 新版发布后检索指向新版本",
            self.get("delivery-1", "/knowledge/search?q=验收")["items"][0]["revision_id"]
            == revised["published_id"],
        )
        self.report["artifacts"]["handbook_id"] = revised["id"]

    def decisions(self):
        work = self.works["material"]
        answer = self.post(
            "owner",
            "/ai/ask",
            {
                "question": "客户资料不足，下一步需要核实什么？",
                "work_item_id": work["id"],
            },
        )
        self.check(
            "13 规则模式明确标记且引用已确认支持需求",
            answer["mode"] == "rules" and answer["evidence"][0]["facts"]["needs_support"],
        )
        self.report["artifacts"]["rules_analysis_id"] = answer["id"]
        decision = self.post(
            "owner",
            "/decisions",
            {
                "analysis_id": answer["id"],
                "work_item_id": work["id"],
                "idempotency_key": key(),
            },
        )
        before = len(self.events("material"))
        self.check(
            "14 准备方案不代表已决策或已交付",
            decision["state"] == "pending" and self.work("material")["needs_support"],
        )
        body = {
            "expected_version": decision["version"],
            "selected_option": decision["options"][0]["id"],
            "selected_plan": "模拟决策：销售负责人核实图片和价格表缺口，交付同事收到后复核。",
            "follow_up": "记录实际资料到位情况，不能把协调安排当成已解决。",
            "follow_up_at": timestamp(seconds=3),
        }
        path = f"/decisions/{decision['id']}/confirm"
        self.deny("14 部门负责人不能替老板确认决策", "delivery-0", "POST", path, body)
        confirmed = self.post("owner", path, body)
        self.check(
            "14 决策确认重放仅追加一个事件",
            self.post("owner", path, body) == confirmed
            and len(self.events("material")) == before + 1,
        )
        self.decision, self.answer = confirmed, answer
        self.report["artifacts"]["decision_id"] = confirmed["id"]
        stale_answer = self.post(
            "owner",
            "/ai/ask",
            {
                "question": "接口联调需要怎样协调？",
                "work_item_id": self.works["api"]["id"],
            },
        )
        stale = self.post(
            "owner",
            "/decisions",
            {
                "analysis_id": stale_answer["id"],
                "work_item_id": self.works["api"]["id"],
                "idempotency_key": key(),
            },
        )
        self.quick("dev-1", "api", "progress", "模拟：接口仍缺测试凭据，已核对申请渠道。")
        self.deny(
            "15 新事实出现后旧方案不能确认",
            "owner",
            "POST",
            f"/decisions/{stale['id']}/confirm",
            {
                **body,
                "expected_version": stale["version"],
                "selected_option": stale["options"][0]["id"],
                "follow_up_at": None,
            },
            status=409,
        )

    def wait_watch(self, policy, predicate, timeout=45):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if self.tick:
                self.tick()
            rows = self.get("owner", "/watch/attention?include_closed=true")
            if predicate(rows):
                return rows
            time.sleep(0.2 if self.tick else 1)
        raise ScenarioFailure("bounded_watch_wait_expired:" + policy["id"])

    def watching(self):
        # The compressed follow-up timestamp is explicit test data, not a clock rewrite.
        due = datetime.fromisoformat(self.decision["follow_up_at"])
        remaining = (due - datetime.now(UTC)).total_seconds()
        if remaining > 0:
            time.sleep(min(remaining + 0.05, 5))
        body = {
            "name": "模拟演练 · 青禾交付关注",
            "goal": (
                "仅依据青禾项目的确认记录核实资料和接口缺口，整理需老板决定的事项；"
                "实际结果未知时保持未知。"
            ),
            "scope_kind": "initiative",
            "initiative_id": self.projects["atlas"]["id"],
            "interval_minutes": 15,
            "daily_analysis_limit": 1,
            "expires_at": timestamp(days=1),
            "confirm": True,
            "idempotency_key": key(),
        }
        self.deny(
            "16 部门负责人不能建立老板后台授权",
            "delivery-0",
            "POST",
            "/watch/policies",
            body,
        )
        policy = self.post("owner", "/watch/policies", body)
        self.policy = policy
        self.report["artifacts"]["watch_policy_id"] = policy["id"]
        before = {code: len(self.events(code)) for code in self.works}
        rows = self.wait_watch(
            policy,
            lambda rs: (
                any(r["kind"] == "follow_up" for r in rs)
                and any(
                    r["work_item_id"] == self.works["material"]["id"] and r["kind"] == "work"
                    for r in rs
                )
            ),
        )
        self.check("17 后台真实消费后产生有依据待办和到期跟进", bool(rows))
        self.check(
            "17 项目关注不会混入另一个项目",
            all(
                r["work_item_id"]
                in {
                    w["id"]
                    for w in self.works.values()
                    if w["initiative_id"] == self.projects["atlas"]["id"]
                }
                for r in rows
            ),
        )
        self.check(
            "17 自主关注不修改业务进展事件",
            before == {code: len(self.events(code)) for code in self.works},
        )
        self.deny("17 员工不能读取老板关注列表", "delivery-1", "GET", "/watch/attention")
        item = next(
            r
            for r in rows
            if r["kind"] == "work" and r["work_item_id"] == self.works["material"]["id"]
        )
        action = {
            "action": "snooze",
            "expected_version": item["version"],
            "idempotency_key": key(),
            "snoozed_until": timestamp(days=1),
        }
        snoozed = self.post("owner", f"/watch/attention/{item['id']}/actions", action)
        self.check(
            "18 暂缓和重复点击不改变真实支持状态",
            snoozed["state"] == "snoozed"
            and self.post("owner", f"/watch/attention/{item['id']}/actions", action) == snoozed
            and self.work("material")["needs_support"],
        )
        corrected = self.post(
            "owner",
            f"/watch/attention/{item['id']}/actions",
            {
                "action": "correct",
                "expected_version": snoozed["version"],
                "idempotency_key": key(),
                "note": "模拟核实备注：还不能确认图片已收到。",
            },
        )
        self.check(
            "18 核实备注不成为已解决的业务事实",
            corrected["review_note"] is not None and self.work("material")["needs_support"],
        )

    def memory_and_result(self):
        outcome_body = {
            "observed_result": (
                "模拟实际结果：销售已联系客户，但图片仍未收到，协调尚未解决资料缺口。"
            ),
            "evidence_refs": [self.answer["evidence"][0]["id"]],
            "idempotency_key": key(),
        }
        path = f"/decisions/{self.decision['id']}/outcomes"
        outcome = self.post("owner", path, outcome_body)
        self.check(
            "19 实际结果追加幂等，不自动解除支持需求",
            self.post("owner", path, outcome_body)["id"] == outcome["id"]
            and self.work("material")["needs_support"],
        )
        rows = self.wait_watch(
            self.policy,
            lambda rs: any(
                r["kind"] == "follow_up" and r["state"] == "result_recorded" for r in rs
            ),
        )
        self.check(
            "19 跟进仅标记结果已记录，不冒称问题解决",
            any(r["state"] == "result_recorded" for r in rows),
        )

        def confirm_memory(row, title, content, quote):
            row = self.post(
                "owner",
                f"/memory/entries/{row['id']}/edit",
                {
                    "expected_version": row["version"],
                    "expected_source_hash": row["source"]["source_hash"],
                    "idempotency_key": key(),
                    "title": title,
                    "content": content,
                    "applicability": "仅适用于已确认的客户资料缺失；先核对当前来源。",
                    "source_quote": quote,
                },
            )
            return self.post(
                "owner",
                f"/memory/entries/{row['id']}/action",
                {
                    "action": "confirm",
                    "confirm": True,
                    "expected_version": row["version"],
                    "expected_source_hash": row["source"]["source_hash"],
                    "idempotency_key": key(),
                },
            )

        row = self.post(
            "owner",
            "/memory/entries",
            {
                "kind": "experience",
                "decision_id": self.decision["id"],
                "outcome_id": outcome["id"],
                "idempotency_key": key(),
            },
        )
        self.check(
            "20 未确认经验不进入检索",
            self.get("owner", "/memory/search?q=资料")["total"] == 0,
        )
        experience = confirm_memory(
            row,
            "模拟经验：联系客户不等于资料齐全",
            "客户资料需要实际到位记录，不能以沟通动作推断已解决。",
            outcome_body["observed_result"],
        )
        self.check(
            "20 经作者确认的失败经验可追溯检索",
            any(
                r["id"] == experience["id"]
                for r in self.get("owner", "/memory/search?q=资料")["items"]
            ),
        )
        pref_text = "模拟偏好：优先核实客户资料和交付风险，没有依据时先提出待核实问题。"
        pref = self.post(
            "owner",
            "/memory/entries",
            {
                "kind": "preference",
                "preference_key": "focus",
                "source_text": pref_text,
                "idempotency_key": key(),
            },
        )
        preference = confirm_memory(pref, "模拟老板关注重点", pref_text, pref_text)
        self.deny(
            "21 私有经营偏好不泄漏给员工",
            "delivery-1",
            "GET",
            f"/memory/entries/{preference['id']}",
        )
        self.deny(
            "21 经验与偏好不泄漏给外部企业",
            "outsider",
            "GET",
            f"/memory/entries/{preference['id']}",
        )
        self.post(
            "owner",
            path,
            {
                "observed_result": "模拟后续结果：图片已收到，价格表仍待客户复核，问题未完全解决。",
                "evidence_refs": [],
                "idempotency_key": key(),
            },
        )
        self.check(
            "22 后续结果变化使旧经验要求复核",
            self.get("owner", f"/memory/entries/{experience['id']}")["outdated"]
            and not any(
                r["id"] == experience["id"]
                for r in self.get("owner", "/memory/search?q=资料&kind=experience")["items"]
            ),
        )
        self.report["artifacts"].update(
            experience_id=experience["id"], preference_id=preference["id"]
        )

    def handover_and_finish(self):
        row = self.work("training")
        draft = self.post(
            "delivery-2",
            "/work-updates/drafts",
            {"work_item_id": row["id"], "raw_text": "模拟：培训材料待核实。"},
        )
        assignment = {
            "owner_id": self.people["delivery-1"]["id"],
            "expected_version": row["version"],
            "idempotency_key": key(),
        }
        self.request("delivery-0", "PATCH", f"/work-items/{row['id']}/assignment", assignment)
        self.check(
            "23 主管移交事项只改变指定事项归属",
            self.work("training")["owner_id"] == self.people["delivery-1"]["id"],
        )
        self.deny(
            "23 移交后原员工不能读取旧事项",
            "delivery-2",
            "GET",
            f"/work-items/{row['id']}",
        )
        self.deny(
            "23 移交后原员工不能确认旧草稿",
            "delivery-2",
            "POST",
            f"/work-updates/drafts/{draft['id']}/confirm",
            {"expected_revision": draft["revision"]},
        )
        self.check(
            "23 新负责人能读取移交事项",
            self.get("delivery-1", f"/work-items/{row['id']}")["id"] == row["id"],
        )
        policy = next(
            p for p in self.get("owner", "/watch/policies") if p["id"] == self.policy["id"]
        )
        body = {
            "action": "pause",
            "confirm": True,
            "expected_version": policy["version"],
            "idempotency_key": key(),
        }
        paused = self.post("owner", f"/watch/policies/{policy['id']}/actions", body)
        self.check(
            "24 暂停授权使旧关注结果不可见",
            paused["effective_state"] == "paused" and self.get("owner", "/watch/attention") == [],
        )
        self.report["artifacts"]["watch_policy_state"] = "paused"
        dashboard = self.get("owner", "/dashboard")
        self.check(
            "25 最终全景与业务状态一致",
            dashboard["member_count"] == 10
            and dashboard["total_work"] == 12
            and dashboard["completed_work"] == 1
            and dashboard["active_work"] == 10
            and dashboard["support_work"] == 2,
        )
        self.check("25 无截止时间保持未知", self.work("unknown")["due_at"] is None)
        self.report["final_dashboard"] = dashboard
        self.report["model_usage"] = self.get("owner", "/ai/usage")
        self.check(
            "25 模拟经营全程未发起计费模型调用",
            self.report["model_usage"]["calls"] == 0,
        )
        self.report["passed"] = True

    def run(self):
        for phase in (
            self.initialize,
            self.permissions,
            self.updates,
            self.knowledge,
            self.decisions,
            self.watching,
            self.memory_and_result,
            self.handover_and_finish,
        ):
            phase()
        return self.report

    def close(self):
        # A failed rehearsal must not leave its own background policy running.
        if not self.report["passed"] and hasattr(self, "policy"):
            try:
                policy = next(
                    p for p in self.get("owner", "/watch/policies") if p["id"] == self.policy["id"]
                )
                if policy["effective_state"] == "active":
                    self.post(
                        "owner",
                        f"/watch/policies/{policy['id']}/actions",
                        {
                            "action": "pause",
                            "confirm": True,
                            "expected_version": policy["version"],
                            "idempotency_key": key(),
                        },
                    )
            except Exception:
                self.report["cleanup_required"] = "pause_this_test_policy"
        for client in self.clients.values():
            client.close()
        self.report["finished_at"] = timestamp()
        if self.timings:
            values = sorted(self.timings)
            self.report["http_observation"] = {
                "requests": len(values),
                "p50_ms": round(values[len(values) // 2] * 1000, 2),
                "p95_ms": round(values[min(len(values) - 1, int(len(values) * 0.95))] * 1000, 2),
                "max_ms": round(values[-1] * 1000, 2),
                "production_load_test": False,
            }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://localhost:3000")
    parser.add_argument("--label", default="rehearsal-" + uuid4().hex[:8])
    parser.add_argument("--report", type=Path, default=Path(".local/enterprise-scenario.json"))
    args = parser.parse_args()
    url = urlparse(args.base_url)
    if (
        url.scheme not in {"http", "https"}
        or url.hostname not in {"localhost", "127.0.0.1", "::1"}
        or url.username
        or url.password
        or url.query
        or url.fragment
        or url.path not in {"", "/"}
    ):
        parser.error("Only a loopback development origin is allowed")
    if args.report.exists():
        parser.error("Choose a new report path; previous acceptance evidence is preserved")
    scenario = EnterpriseScenario(
        lambda: httpx.Client(base_url=args.base_url, timeout=30, trust_env=False),
        args.label,
    )
    try:
        scenario.run()
    except Exception as error:
        scenario.report["failure"] = (
            str(error) if isinstance(error, ScenarioFailure) else type(error).__name__
        )
    finally:
        scenario.close()
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(scenario.report, ensure_ascii=False, indent=2) + "\n")
    print(
        json.dumps(
            {
                "passed": scenario.report["passed"],
                "checks": len(scenario.report["checks"]),
                "report": str(args.report),
                "failure": scenario.report.get("failure"),
            },
            ensure_ascii=False,
        )
    )
    return 0 if scenario.report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
