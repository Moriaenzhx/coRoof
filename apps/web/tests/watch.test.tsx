import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, expect, it, vi } from "vitest";
import { WatchCenter, WatchOverview } from "../components/watch";
import type { Schemas } from "../lib/api";

const mocks = vi.hoisted(() => ({ get: vi.fn(), post: vi.fn() }));
vi.mock("../lib/api", async (original) => ({
  ...(await original<object>()),
  api: () => ({ GET: mocks.get, POST: mocks.post }),
}));
const time = "2026-11-04T08:00:00Z";
const props = {
  organizationId: "o1",
  timezone: "Asia/Shanghai",
  departments: [],
  initiatives: [],
  onWork: vi.fn(),
  onPlan: vi.fn(),
  onDecision: vi.fn(),
};
const policy: Schemas["WatchPolicyOut"] = {
  id: "p1",
  actor_id: "m1",
  name: "交付支持",
  goal: "核实客户资料缺口",
  scope_kind: "organization",
  department_id: null,
  initiative_id: null,
  interval_minutes: 60,
  daily_analysis_limit: 4,
  expires_at: "2026-11-11T08:00:00Z",
  state: "active",
  effective_state: "active",
  version: 1,
  created_at: time,
  next_due_at: time,
  last_checked_at: null,
  notice: "只读建议",
};
const item: Schemas["AttentionOut"] = {
  id: "a1",
  policy_id: "p1",
  policy_name: "交付支持",
  kind: "work",
  category: "support",
  title: "需要支持",
  explanation: "成员明确提出支持需求。",
  work_item_id: "w1",
  work_title: "确认客户资料",
  decision_id: null,
  agent_run_id: "r1",
  evidence: null,
  state: "open",
  version: 2,
  snoozed_until: null,
  review_note: null,
  created_at: time,
  changed_at: time,
};
let policies: Schemas["WatchPolicyOut"][];
let items: Schemas["AttentionOut"][];
beforeEach(() => {
  vi.clearAllMocks();
  policies = [];
  items = [];
  mocks.get.mockImplementation(async (path) => ({
    data:
      path === "/api/v1/watch/policies"
        ? policies
        : path === "/api/v1/watch/attention"
          ? items
          : [],
  }));
  mocks.post.mockImplementation(async (path, options) => {
    if (path === "/api/v1/watch/policies")
      policies = [{ ...policy, ...options.body }];
    if (path.endsWith("/actions") && path.includes("attention"))
      items = [{ ...item, state: "dismissed" }];
    return { data: path.includes("attention") ? items[0] : policies[0] };
  });
});

it("requires explicit bounded authorization and resets acknowledgement when fields change", async () => {
  const user = userEvent.setup();
  render(<WatchCenter {...props} />);
  await user.click(await screen.findByRole("button", { name: "关注设置" }));
  await user.click(screen.getByRole("button", { name: "新建关注" }));
  const submit = screen.getByRole("button", { name: "确认并启用关注" });
  expect((submit as HTMLButtonElement).disabled).toBe(true);
  await user.type(screen.getByLabelText("关注名称"), "交付核实");
  await user.type(
    screen.getByLabelText("你确认的关注目标"),
    "仅根据已确认记录核实交付缺口",
  );
  const confirm = screen.getByRole("checkbox", { name: /我确认以上目标/ });
  await user.click(confirm);
  expect((submit as HTMLButtonElement).disabled).toBe(false);
  await user.type(screen.getByLabelText("你确认的关注目标"), "，不推测结果");
  expect((submit as HTMLButtonElement).disabled).toBe(true);
  await user.click(confirm);
  await user.click(submit);
  await waitFor(() => expect(mocks.post).toHaveBeenCalledOnce());
  const body = mocks.post.mock.calls[0][1].body;
  expect(body).toMatchObject({
    confirm: true,
    scope_kind: "organization",
    interval_minutes: 60,
    daily_analysis_limit: 4,
  });
  expect(body.idempotency_key).toBeTruthy();
});

it("opens a validated existing plan without initiating another model call", async () => {
  policies = [policy];
  items = [item];
  const user = userEvent.setup();
  render(<WatchCenter {...props} />);
  await user.click(await screen.findByRole("button", { name: "审阅推进建议" }));
  expect(props.onPlan).toHaveBeenCalledWith("r1", "w1");
  expect(mocks.post).not.toHaveBeenCalled();
});

it("records correction as a review opinion with version and idempotency", async () => {
  policies = [policy];
  items = [item];
  const user = userEvent.setup();
  render(<WatchCenter {...props} />);
  await user.click(await screen.findByRole("button", { name: "处理此项" }));
  const correct = screen.getByRole("button", { name: "记录纠正意见" });
  expect((correct as HTMLButtonElement).disabled).toBe(true);
  await user.type(
    screen.getByLabelText("核实或纠正意见"),
    "请核实资料是否已到位",
  );
  await user.click(correct);
  await waitFor(() => expect(mocks.post).toHaveBeenCalledOnce());
  expect(mocks.post.mock.calls[0][1].body).toMatchObject({
    action: "correct",
    expected_version: 2,
    note: "请核实资料是否已到位",
  });
});

it("asks the owner to confirm stopping the exact policy", async () => {
  policies = [policy];
  const user = userEvent.setup();
  render(<WatchCenter {...props} />);
  await user.click(await screen.findByRole("button", { name: "关注设置" }));
  await user.click(await screen.findByRole("button", { name: "暂停关注" }));
  expect(mocks.post).not.toHaveBeenCalled();
  await user.click(screen.getByRole("button", { name: "确认暂停关注" }));
  await waitFor(() => expect(mocks.post).toHaveBeenCalledOnce());
  expect(mocks.post.mock.calls[0][1]).toMatchObject({
    params: { path: { policy_id: "p1" } },
    body: { action: "pause", confirm: true, expected_version: 1 },
  });
});

it("empty overview does not invent health or autonomous progress", async () => {
  render(<WatchOverview {...props} onManage={vi.fn()} />);
  expect(await screen.findByText(/还没有授权持续关注/)).toBeTruthy();
  expect(screen.queryByText(/运行正常|所有项目顺利/)).toBeNull();
  expect(mocks.post).not.toHaveBeenCalled();
});

it("shows lost access as an error and clears derived items", async () => {
  mocks.get.mockResolvedValue({
    error: { error: { message: "当前授权已失效" } },
  });
  render(<WatchCenter {...props} />);
  expect(await screen.findByText("当前授权已失效")).toBeTruthy();
  expect(screen.queryByRole("button", { name: "审阅推进建议" })).toBeNull();
});
