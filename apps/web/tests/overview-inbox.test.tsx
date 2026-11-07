import {
  act,
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, expect, it, vi } from "vitest";
import { OverviewInbox } from "../components/overview-inbox";
import type { Initiative, Member, Schemas, Work } from "../lib/api";

const mocks = vi.hoisted(() => ({ get: vi.fn(), post: vi.fn() }));
vi.mock("../lib/api", async (original) => ({
  ...(await original<object>()),
  api: () => ({ GET: mocks.get, POST: mocks.post }),
}));
const time = "2026-11-04T08:00:00Z";
const work: Work = {
  id: "w1",
  organization_id: "o1",
  title: "确认客户资料",
  description: null,
  department_id: "d1",
  initiative_id: "i1",
  owner_id: "m1",
  due_at: "2026-11-03T08:00:00Z",
  lifecycle_status: "in_progress",
  needs_support: true,
  source_authority: "native",
  version: 2,
  updated_at: time,
};
const member: Member = {
  id: "m1",
  organization_id: "o1",
  user_id: "u1",
  department_id: "d1",
  name: "陆川",
  roles: ["member"],
  status: "active",
};
const initiative: Initiative = {
  id: "i1",
  organization_id: "o1",
  title: "青禾交付",
  goal: null,
  department_id: "d1",
  owner_id: "m1",
  due_at: null,
  status: "in_progress",
};
const signal: Schemas["SignalOut"] = {
  id: "s1",
  work_item_id: "w1",
  work_title: work.title,
  evidence_id: "e1",
  category: "support",
  severity: "attention",
  state: "active",
  rule_version: "v1",
  detected_at: time,
  evaluated_at: time,
  version: 1,
  title: "需要支持",
  explanation: "已记录支持需求，尚未解除。",
};
const policy: Schemas["WatchPolicyOut"] = {
  id: "p1",
  actor_id: "m1",
  name: "交付关注",
  goal: "核对已确认事项",
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
  policy_name: policy.name,
  kind: "work",
  category: "support",
  title: "需要支持",
  explanation: "后台核对了已记录的支持需求。",
  work_item_id: "w1",
  work_title: work.title,
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
const props = {
  organizationId: "o1",
  timezone: "Asia/Shanghai",
  works: [work],
  signals: [] as Schemas["SignalOut"][],
  members: [member],
  initiatives: [initiative],
  isOwner: true,
  onWork: vi.fn(),
  onAsk: vi.fn(),
  onPlan: vi.fn(),
  onDecision: vi.fn(),
  onManage: vi.fn(),
};
let policies: Schemas["WatchPolicyOut"][];
let items: Schemas["AttentionOut"][];
beforeEach(() => {
  vi.clearAllMocks();
  policies = [policy];
  items = [];
  mocks.get.mockImplementation(async (path) => ({
    data: path.endsWith("/policies") ? policies : items,
  }));
});

it("prioritizes a concrete reason, owner and date with exactly one primary action and folded audit", async () => {
  const user = userEvent.setup();
  render(<OverviewInbox {...props} isOwner={false} />);
  const row = screen.getByRole("article", { name: work.title });
  const content = within(row);
  for (const visibleText of [
    "已记录支持需求，需要核实缺口并协调负责人。",
    "陆川负责",
    "工作截止 11/03 16:00",
    "需要支持",
  ])
    expect(content.getByText(visibleText).closest("details")).toBeNull();
  const primary = within(
    row.querySelector(".overview-inbox-row-actions") as HTMLElement,
  );
  expect(
    primary.getAllByRole("button").map((button) => button.textContent),
  ).toEqual(["查看支持需求"]);
  expect(content.getByText("依据与来源").closest("details")?.open).toBe(false);
  expect(props.onWork).not.toHaveBeenCalled();
  expect(props.onAsk).not.toHaveBeenCalled();
  await user.click(primary.getByRole("button", { name: "查看支持需求" }));
  expect(props.onWork).toHaveBeenCalledExactlyOnceWith("w1");
  expect(mocks.post).not.toHaveBeenCalled();
});

it("does not call unread owner attention zero while its read is still pending", () => {
  mocks.get.mockReturnValue(new Promise(() => {}));
  render(<OverviewInbox {...props} works={[]} />);
  expect(
    screen.getByRole("heading", { name: "先处理这几件事 关注记录待核对" }),
  ).toBeTruthy();
  expect(screen.queryByText("0 项待关注")).toBeNull();
  expect(screen.queryByRole("article")).toBeNull();
  expect(mocks.post).not.toHaveBeenCalled();
});

it("merges native support, multiple rules and background findings into one work with traceable sources", async () => {
  items = [
    item,
    { ...item, id: "a2", policy_id: "p2", policy_name: "第二关注范围" },
  ];
  policies.push({ ...policy, id: "p2" });
  const user = userEvent.setup();
  render(
    <OverviewInbox
      {...props}
      signals={[
        signal,
        {
          ...signal,
          id: "s2",
          category: "overdue",
          title: "已过截止时间",
          explanation: "实际交付仍需核实。",
        },
      ]}
    />,
  );
  await screen.findByRole("button", { name: "查看处理建议" });
  expect(screen.getAllByRole("article")).toHaveLength(1);
  expect(
    screen.getByRole("heading", { name: "先处理这几件事 1 项待关注" }),
  ).toBeTruthy();
  const row = within(screen.getByRole("article"));
  expect(row.getByText("依据与来源").closest("details")?.open).toBe(false);
  expect(
    row.getByRole("button", { name: "查看工作" }).closest("details")?.open,
  ).toBe(false);
  expect(row.getByText("陆川负责")).toBeTruthy();
  expect(row.getByText("青禾交付")).toBeTruthy();
  expect(row.getByText("工作截止 11/03 16:00")).toBeTruthy();
  expect(row.getByText("工作记录 11/04 16:00")).toBeTruthy();
  for (const label of ["已确认工作", "规则提示", "后台关注"])
    expect(row.getByText(label)).toBeTruthy();
  expect(row.getByText(/第二关注范围/)).toBeTruthy();
  expect(props.onPlan).not.toHaveBeenCalled();
  expect(props.onAsk).not.toHaveBeenCalled();
  expect(mocks.post).not.toHaveBeenCalled();
  await user.click(row.getByText("依据与来源"));
  expect(row.getByText("依据与来源").closest("details")?.open).toBe(true);
  await user.click(row.getByRole("button", { name: "查看处理建议" }));
  expect(props.onPlan).toHaveBeenCalledWith("r1", "w1");
  await user.click(row.getByRole("button", { name: "查看工作" }));
  expect(props.onWork).toHaveBeenCalledWith("w1");
});

it("orders explicit follow-up and existing plans before ordinary support and dates, and expands the deduplicated list", async () => {
  const works = Array.from({ length: 6 }, (_, index) => ({
    ...work,
    id: `w${index + 1}`,
    title: `事项${index + 1}`,
    needs_support: index > 1,
  }));
  items = [
    {
      ...item,
      work_item_id: "w1",
      work_title: "事项1",
      id: "follow",
      kind: "follow_up",
      category: "follow_up_due",
      decision_id: "decision-1",
      agent_run_id: null,
    },
    {
      ...item,
      work_item_id: "w2",
      work_title: "事项2",
      id: "plan",
      category: "plan",
    },
  ];
  const user = userEvent.setup();
  render(<OverviewInbox {...props} works={works} />);
  await screen.findByRole("button", { name: "核实跟进结果" });
  expect(
    screen.getAllByRole("article").map((row) => row.getAttribute("aria-label")),
  ).toEqual(["事项1", "事项2", "事项3"]);
  expect(
    screen.getByRole("heading", { name: "先处理这几件事 6 项待关注" }),
  ).toBeTruthy();
  await user.click(screen.getByRole("button", { name: "还有 3 项，展开查看" }));
  expect(screen.getAllByRole("article")).toHaveLength(6);
  await user.click(screen.getByRole("button", { name: "核实跟进结果" }));
  expect(props.onDecision).toHaveBeenCalledWith("decision-1");
  await user.click(screen.getByRole("button", { name: "收起其余事项" }));
  expect(screen.getAllByRole("article")).toHaveLength(3);
});

it("同一事项同时有跟进和建议时只突出跟进，已有建议仍可从依据中打开", async () => {
  const user = userEvent.setup();
  items = [
    item,
    {
      ...item,
      id: "follow",
      kind: "follow_up",
      category: "follow_up_due",
      decision_id: "decision-1",
      agent_run_id: null,
    },
  ];
  render(<OverviewInbox {...props} />);
  await screen.findByRole("button", { name: "核实跟进结果" });
  const row = screen.getByRole("article");
  const actions = within(
    row.querySelector(".overview-inbox-row-actions") as HTMLElement,
  );
  expect(
    actions.getAllByRole("button").map((button) => button.textContent),
  ).toEqual(["核实跟进结果"]);
  const sources = within(row).getByText("依据与来源").closest("details")!;
  expect(sources.open).toBe(false);
  await user.click(within(row).getByText("依据与来源"));
  await user.click(
    within(sources).getByRole("button", { name: "审阅这条建议" }),
  );
  expect(props.onPlan).toHaveBeenCalledExactlyOnceWith("r1", "w1");
  expect(mocks.post).not.toHaveBeenCalled();
});

it("keeps an authorized attention item without a work snapshot, including no-data coverage", async () => {
  items = [
    item,
    {
      ...item,
      id: "coverage",
      kind: "coverage",
      category: "no_data",
      title: "销售范围没有工作记录",
      explanation: "范围内无可核对资料。",
      work_item_id: null,
      work_title: null,
      agent_run_id: null,
    },
  ];
  const user = userEvent.setup();
  render(<OverviewInbox {...props} works={[]} members={[]} initiatives={[]} />);
  await screen.findByRole("button", { name: "查看处理建议" });
  expect(screen.getAllByRole("article")).toHaveLength(2);
  expect(screen.getByText("负责人待核实")).toBeTruthy();
  expect(screen.getByText("项目待核实")).toBeTruthy();
  expect(screen.getByText("工作截止待核实")).toBeTruthy();
  await user.click(screen.getByRole("button", { name: "查看关注范围" }));
  expect(props.onManage).toHaveBeenCalledOnce();
  await user.click(screen.getByRole("button", { name: "查看处理建议" }));
  expect(props.onPlan).toHaveBeenCalledWith("r1", "w1");
});

it("does not request owner endpoints for a manager and only prefills an explicit work question", async () => {
  const user = userEvent.setup();
  render(<OverviewInbox {...props} isOwner={false} />);
  expect(mocks.get).not.toHaveBeenCalled();
  expect(screen.queryByRole("button", { name: "管理提醒" })).toBeNull();
  expect(screen.queryByText(/待审批/)).toBeNull();
  expect(props.onAsk).not.toHaveBeenCalled();
  expect(screen.getByRole("button", { name: "查看支持需求" })).toBeTruthy();
  expect(
    screen.getByRole("button", { name: "梳理下一步" }).closest("details")?.open,
  ).toBe(false);
  await user.click(screen.getByText("依据与来源"));
  await user.click(screen.getByRole("button", { name: "梳理下一步" }));
  expect(props.onAsk).toHaveBeenCalledWith(
    "w1",
    expect.stringContaining("支持需求和协作缺口"),
  );
  expect(mocks.post).not.toHaveBeenCalled();
});

it("uses a compact truthful empty state and never claims all work is healthy", async () => {
  policies = [];
  render(<OverviewInbox {...props} works={[]} />);
  expect(await screen.findByText("尚未授权持续关注")).toBeTruthy();
  expect(screen.getByText(/还没有可整理的工作记录/)).toBeTruthy();
  expect(screen.getByText("尚未记录的情况仍然未知。")).toBeTruthy();
  expect(screen.queryByRole("article")).toBeNull();
  expect(screen.queryByText(/运行正常|全部顺利|已完成所有/)).toBeNull();
  expect(mocks.post).not.toHaveBeenCalled();
});

it("does not turn completed, cancelled or external support fields into new support requests", () => {
  render(
    <OverviewInbox
      {...props}
      isOwner={false}
      works={[
        { ...work, id: "done", lifecycle_status: "done" },
        { ...work, id: "cancelled", lifecycle_status: "cancelled" },
        { ...work, id: "external", source_authority: "external" },
      ]}
      signals={[
        { ...signal, work_item_id: "done" },
        {
          ...signal,
          id: "resolved",
          state: "resolved",
          work_item_id: "cancelled",
        },
        { ...signal, id: "external", work_item_id: "external" },
      ]}
    />,
  );
  expect(screen.queryByRole("article")).toBeNull();
  expect(screen.getByText(/当前已记录事项中，暂无/)).toBeTruthy();
});

it("shows paused, expired and invalid grants without resurfacing closed or unauthorized suggestions", async () => {
  policies = [
    { ...policy, state: "paused", effective_state: "paused" },
    { ...policy, id: "p2", effective_state: "expired" },
    { ...policy, id: "p3", effective_state: "unauthorized" },
    { ...policy, id: "p4", effective_state: "active" },
  ];
  items = [
    item,
    { ...item, id: "expired", policy_id: "p2" },
    { ...item, id: "invalid", policy_id: "p3" },
    { ...item, id: "closed", policy_id: "p4", state: "invalidated" },
    { ...item, id: "snoozed", policy_id: "p4", state: "snoozed" },
  ];
  render(<OverviewInbox {...props} works={[]} />);
  expect(
    await screen.findByText(/1 项已暂停.*1 项授权到期.*1 项授权失效/),
  ).toBeTruthy();
  expect(screen.queryByRole("button", { name: "查看处理建议" })).toBeNull();
  expect(screen.queryByRole("article")).toBeNull();
});

it("keeps current native support on backend failure and offers a read-only retry", async () => {
  mocks.get.mockResolvedValue({ error: { error: { message: "授权已失效" } } });
  const user = userEvent.setup();
  render(<OverviewInbox {...props} />);
  expect(await screen.findByText("后台记录读取失败：授权已失效")).toBeTruthy();
  expect(screen.getAllByRole("article")).toHaveLength(1);
  expect(screen.queryByRole("button", { name: "查看处理建议" })).toBeNull();
  mocks.get.mockImplementation(async (path) => ({
    data: path.endsWith("/policies") ? [policy] : [item],
  }));
  await user.click(screen.getByRole("button", { name: "重试" }));
  expect(
    await screen.findByRole("button", { name: "查看处理建议" }),
  ).toBeTruthy();
  expect(mocks.post).not.toHaveBeenCalled();
});

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((done) => {
    resolve = done;
  });
  return { promise, resolve };
}

it("ignores a late response from the previous tenant", async () => {
  const late = deferred<{ data: Schemas["AttentionOut"][] }>();
  mocks.get.mockImplementation(async (path, options) => {
    if (path.endsWith("/policies")) return { data: [policy] };
    return options.params.header["x-organization-id"] === "o1"
      ? late.promise
      : {
          data: [
            {
              ...item,
              id: "b",
              work_item_id: "b-work",
              work_title: "乙企业事项",
            },
          ],
        };
  });
  const { rerender } = render(<OverviewInbox {...props} works={[]} />);
  rerender(<OverviewInbox {...props} organizationId="o2" works={[]} />);
  await screen.findByRole("article", { name: "乙企业事项" });
  await act(async () => late.resolve({ data: [item] }));
  expect(screen.queryByRole("article", { name: work.title })).toBeNull();
  expect(screen.getAllByRole("article")).toHaveLength(1);
});

it("hides old tenant data immediately and does not resurrect it when switching back before a read completes", async () => {
  items = [item];
  const pending = deferred<{ data: Schemas["AttentionOut"][] }>();
  const { rerender } = render(<OverviewInbox {...props} works={[]} />);
  await screen.findByRole("button", { name: "查看处理建议" });
  mocks.get.mockImplementation(async (path) =>
    path.endsWith("/policies") ? { data: [policy] } : pending.promise,
  );
  rerender(<OverviewInbox {...props} organizationId="o2" works={[]} />);
  expect(screen.queryByRole("article")).toBeNull();
  rerender(<OverviewInbox {...props} works={[]} />);
  expect(screen.queryByRole("article")).toBeNull();
  await act(async () => pending.resolve({ data: [] }));
});

it("closes access immediately on role loss, ignores its in-flight refresh and re-reads after restoration", async () => {
  items = [item];
  const { rerender } = render(<OverviewInbox {...props} works={[]} />);
  await screen.findByRole("button", { name: "查看处理建议" });
  const late = deferred<{ data: Schemas["AttentionOut"][] }>();
  mocks.get.mockImplementation(async (path) =>
    path.endsWith("/policies") ? { data: [policy] } : late.promise,
  );
  fireEvent.focus(window);
  const beforeLoss = mocks.get.mock.calls.length;
  rerender(<OverviewInbox {...props} works={[]} isOwner={false} />);
  expect(screen.queryByRole("article")).toBeNull();
  fireEvent.focus(window);
  expect(mocks.get).toHaveBeenCalledTimes(beforeLoss);
  await act(async () => late.resolve({ data: [item] }));
  expect(screen.queryByRole("article")).toBeNull();
  const next = deferred<{ data: Schemas["AttentionOut"][] }>();
  mocks.get.mockImplementation(async (path) =>
    path.endsWith("/policies") ? { data: [policy] } : next.promise,
  );
  rerender(<OverviewInbox {...props} works={[]} />);
  expect(screen.queryByRole("article")).toBeNull();
  await act(async () => next.resolve({ data: [] }));
});

it("drops previously loaded background actions when a refresh fails authorization", async () => {
  items = [item];
  render(<OverviewInbox {...props} />);
  await screen.findByRole("button", { name: "查看处理建议" });
  mocks.get.mockResolvedValue({
    error: { error: { message: "不再具有读取权限" } },
  });
  fireEvent.focus(window);
  await waitFor(() =>
    expect(screen.queryByRole("button", { name: "查看处理建议" })).toBeNull(),
  );
  expect(screen.getByText("后台记录读取失败：不再具有读取权限")).toBeTruthy();
  expect(screen.getByText("已确认工作")).toBeTruthy();
});

it("preserves every decision follow-up after work completion without counting the same work twice", async () => {
  items = [
    {
      ...item,
      id: "follow-1",
      kind: "follow_up",
      category: "follow_up_due",
      decision_id: "decision-1",
      agent_run_id: null,
      explanation: "确认的跟进时间已到，实际结果待核实。",
    },
    {
      ...item,
      id: "follow-2",
      kind: "follow_up",
      category: "follow_up_due",
      decision_id: "decision-2",
      agent_run_id: null,
      explanation: "另一项决策也到了跟进时间。",
    },
  ];
  const user = userEvent.setup();
  render(
    <OverviewInbox
      {...props}
      works={[{ ...work, lifecycle_status: "done" }]}
      signals={[signal]}
    />,
  );
  await screen.findByRole("button", { name: "核实跟进结果" });
  expect(screen.getAllByRole("article")).toHaveLength(1);
  expect(screen.queryByText("已确认工作")).toBeNull();
  expect(screen.queryByText("规则提示")).toBeNull();
  await user.click(screen.getByRole("button", { name: "核实跟进结果" }));
  await user.click(screen.getByText("依据与来源"));
  await user.click(screen.getByRole("button", { name: "查看这条跟进" }));
  expect(props.onDecision.mock.calls.map(([id]) => id).sort()).toEqual([
    "decision-1",
    "decision-2",
  ]);
  expect(mocks.post).not.toHaveBeenCalled();
});

it("reports an actual source failure without inventing a native support request or deadline", async () => {
  items = [
    {
      ...item,
      category: "source_unavailable",
      title: "来源更新失败",
      explanation: "来源暂不可核对，实际进展仍未知。",
      agent_run_id: null,
    },
  ];
  render(
    <OverviewInbox
      {...props}
      works={[{ ...work, source_authority: "external" }]}
    />,
  );
  await screen.findByText("来源更新失败");
  expect(screen.getByText("工作截止未同步")).toBeTruthy();
  expect(screen.queryByText("需要支持")).toBeNull();
  expect(screen.queryByText("已确认工作")).toBeNull();
  expect(screen.getByText("来源暂不可核对，实际进展仍未知。")).toBeTruthy();
});

it("uses only current authorized evidence as fallback metadata and labels its dates", async () => {
  const evidence: Schemas["EvidenceOut"] = {
    id: "e1",
    work_item_id: "w1",
    work_version: 2,
    event_id: null,
    facts: work,
    excerpt: "已确认资料待补充",
    source_at: time,
    captured_at: time,
    outdated: false,
  };
  items = [{ ...item, evidence }];
  const { unmount } = render(<OverviewInbox {...props} works={[]} />);
  await screen.findByText("陆川负责");
  expect(screen.getByText("关注记录更新 11/04 16:00")).toBeTruthy();
  expect(
    screen.getByText("负责人、项目和工作截止来自本条关注记录的证据快照。"),
  ).toBeTruthy();
  unmount();
  items = [{ ...item, evidence: { ...evidence, outdated: true } }];
  render(<OverviewInbox {...props} works={[]} />);
  await screen.findByText("负责人待核实");
  expect(screen.queryByText("陆川负责")).toBeNull();
  expect(screen.queryByText("青禾交付")).toBeNull();
});
