import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { MyWork } from "../components/my-work";
import type { Department, Initiative, Member, Schemas, Work } from "../lib/api";

const mocks = vi.hoisted(() => ({ get: vi.fn() }));
vi.mock("../lib/api", async (original) => ({
  ...(await original<object>()),
  api: () => ({ GET: mocks.get }),
}));

const member: Member = {
  id: "me",
  organization_id: "org",
  user_id: "user",
  name: "小林",
  department_id: "delivery",
  roles: ["member"],
  status: "active",
};
const department: Department = {
  id: "delivery",
  organization_id: "org",
  name: "交付组",
};
const project: Initiative = {
  id: "project",
  organization_id: "org",
  title: "青禾验收",
  department_id: "delivery",
  owner_id: null,
  due_at: null,
  goal: null,
  status: "in_progress",
};
function work(id: string, extra: Partial<Work> = {}): Work {
  return {
    id,
    organization_id: "org",
    title: id,
    department_id: "delivery",
    initiative_id: "project",
    owner_id: "me",
    lifecycle_status: "planned",
    needs_support: false,
    source_authority: "native",
    due_at: null,
    updated_at: "2026-11-05T02:00:00Z",
    version: 1,
    ...extra,
  };
}
const works = [
  work("稍后核对", { due_at: "2026-11-07T02:00:00Z" }),
  work("截止待核实", {
    lifecycle_status: "in_progress",
    due_at: "2026-11-04T02:00:00Z",
  }),
  work("资料需协作", { needs_support: true, due_at: "2026-11-08T02:00:00Z" }),
  work("未定期限", { initiative_id: null }),
  work("已归档纪要", { lifecycle_status: "done", needs_support: true }),
  work("已取消工作", { lifecycle_status: "cancelled" }),
  work("外部同步任务", {
    source_authority: "external",
    needs_support: true,
    due_at: "2026-11-01T02:00:00Z",
  }),
  work("同事的事项", { owner_id: "colleague" }),
  work("另一企业事项", { organization_id: "other" }),
];
const base = {
  works,
  members: [member],
  departments: [department],
  initiatives: [project],
  memberId: member.id,
  timezone: "Asia/Shanghai",
  onWork: vi.fn(),
  onAsk: vi.fn(),
};
beforeEach(() => {
  vi.clearAllMocks();
  mocks.get.mockResolvedValue({
    data: { items: [], total: 0, offset: 0, limit: 100 },
  });
  vi.spyOn(Date, "now").mockReturnValue(Date.parse("2026-11-05T08:00:00Z"));
});
afterEach(() => vi.restoreAllMocks());

describe("员工个人工作台", () => {
  it("顶部只统计本人有效事项，并把真实支持事项作为唯一重点", async () => {
    const view = render(<MyWork {...base} />);
    expect(screen.getByRole("status").textContent).toMatch(
      /5 项待推进，1 项已记录支持需求/,
    );
    expect(screen.getAllByText("先从这件事开始")).toHaveLength(1);
    const priority = screen.getByRole("article", { name: "资料需协作" });
    expect(
      within(priority).getByText(
        "这项工作已记录支持需求，先核实还缺什么、需要谁协作。",
      ),
    ).toBeTruthy();
    expect(within(priority).getByText("负责人 小林")).toBeTruthy();
    expect(within(priority).getByText("截止 11/08 10:00")).toBeTruthy();
    expect(within(priority).getByText("需要支持")).toBeTruthy();
    expect(
      within(priority).getByRole("button", { name: "汇报进展" }),
    ).toBeTruthy();
    expect(base.onWork).not.toHaveBeenCalled();
    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: "已结束 2" }));
    expect(screen.queryByText("先从这件事开始")).toBeNull();
    expect(screen.getByRole("status").textContent).toMatch(
      /5 项待推进，1 项已记录支持需求/,
    );
    view.unmount();
  });

  it("依据已记录日期选出的重点保留准确安排和反馈上下文", async () => {
    const arrangement: Schemas["WorkArrangementOut"] = {
      id: "decision-1",
      work_item_id: "按安排推进",
      selected_plan: "先核对签字页，再反馈缺口",
      follow_up: "补充核对结果",
      follow_up_at: null,
      confirmed_at: "2026-11-05T02:00:00Z",
      feedback_count: 0,
      latest_feedback: null,
    };
    mocks.get.mockResolvedValue({
      data: { items: [arrangement], total: 1, offset: 0, limit: 100 },
    });
    render(
      <MyWork
        {...base}
        organizationId="org"
        works={[
          work("近期事项", { due_at: "2026-11-07T02:00:00Z" }),
          work("按安排推进", { due_at: "2026-11-06T02:00:00Z" }),
        ]}
      />,
    );
    await screen.findByText(arrangement.selected_plan);
    expect(screen.getByRole("status").textContent).toMatch(
      /2 项待推进，0 项已记录支持需求，1 项有已确认安排/,
    );
    const first = screen.getAllByRole("article")[0];
    expect(within(first).getByRole("heading", { level: 3 }).textContent).toBe(
      "按安排推进",
    );
    expect(
      within(first).getByText("这项工作已有确认安排，可以反馈落实情况。"),
    ).toBeTruthy();
    expect(within(first).getByText("截止 11/06 10:00")).toBeTruthy();
    expect(screen.queryByText(/必须今天|已完成安排|完成率/)).toBeNull();
    await userEvent.click(
      within(first).getByRole("button", { name: "反馈安排" }),
    );
    expect(base.onWork).toHaveBeenCalledExactlyOnceWith(
      "按安排推进",
      "feedback",
      "decision-1",
    );
  });

  it("安排读取失败时不把未知统计成零，负责人缺数据也明确标记", async () => {
    mocks.get.mockResolvedValue({ error: { error: { message: "未授权" } } });
    render(
      <MyWork
        {...base}
        organizationId="org"
        members={[]}
        works={[work("当前事项")]}
      />,
    );
    await screen.findByRole("alert");
    expect(screen.getByRole("status").textContent).not.toContain(
      "0 项有已确认安排",
    );
    expect(screen.getByText("负责人 资料不可见")).toBeTruthy();
    expect(screen.queryByText("负责人 未分配")).toBeNull();
    mocks.get.mockResolvedValue({
      data: { items: [], total: 0, offset: 0, limit: 100 },
    });
    await userEvent.click(screen.getByRole("button", { name: "重新读取安排" }));
    await waitFor(() =>
      expect(screen.getByRole("status").textContent).toContain(
        "0 项有已确认安排",
      ),
    );
    expect(base.onAsk).not.toHaveBeenCalled();
  });
  it("没有本人事项时只解释范围，不显示空搜索和空筛选", () => {
    render(<MyWork {...base} works={[]} />);
    expect(screen.getByText("分配给你的工作会出现在这里。")).toBeTruthy();
    expect(screen.queryByLabelText("搜索我的工作")).toBeNull();
    expect(screen.queryByRole("group", { name: "筛选我的工作" })).toBeNull();
    expect(screen.queryByRole("article")).toBeNull();
    expect(base.onWork).not.toHaveBeenCalled();
    expect(base.onAsk).not.toHaveBeenCalled();
  });

  it("只显示有事项的分类，默认不铺开次要操作", () => {
    render(<MyWork {...base} works={[work("准备交付")]} />);
    const filters = within(screen.getByRole("group", { name: "筛选我的工作" }));
    expect(
      filters.getAllByRole("button").map((button) => button.textContent),
    ).toEqual(["待推进 1"]);
    expect(screen.getByText("更多操作").closest("details")?.open).toBe(false);
    expect(base.onAsk).not.toHaveBeenCalled();
  });

  it("scopes to the current member and orders actual support, overdue, then deadlines", () => {
    render(<MyWork {...base} />);
    expect(
      screen
        .getAllByRole("article")
        .map(
          (item) => within(item).getByRole("heading", { level: 3 }).textContent,
        ),
    ).toEqual([
      "资料需协作",
      "截止待核实",
      "稍后核对",
      "外部同步任务",
      "未定期限",
    ]);
    expect(screen.queryByText("同事的事项")).toBeNull();
    expect(screen.queryByText("另一企业事项")).toBeNull();
    expect(screen.queryByText("已归档纪要")).toBeNull();
    expect(screen.getByText("已过记录截止 · 实际交付待核实")).toBeTruthy();
    expect(screen.getByText("截止 11/04 10:00")).toBeTruthy();
    const external = within(
      screen.getByRole("article", { name: "外部同步任务" }),
    );
    expect(external.getByText("截止日期未同步 · 未知")).toBeTruthy();
    expect(external.queryByRole("button", { name: "汇报进展" })).toBeNull();
    expect(external.queryByRole("button", { name: "需要支持" })).toBeNull();
  });

  it("filters active lifecycle, real support and ended history without stale support counts", async () => {
    const user = userEvent.setup();
    render(<MyWork {...base} />);
    const filters = within(screen.getByRole("group", { name: "筛选我的工作" }));
    await user.click(filters.getByRole("button", { name: "进行中 1" }));
    expect(screen.getAllByRole("article")).toHaveLength(1);
    expect(screen.getByRole("article", { name: "截止待核实" })).toBeTruthy();
    await user.click(filters.getByRole("button", { name: "需要支持 1" }));
    expect(screen.getByRole("article", { name: "资料需协作" })).toBeTruthy();
    await user.click(filters.getByRole("button", { name: "已结束 2" }));
    expect(screen.getAllByRole("article")).toHaveLength(2);
    expect(screen.queryByRole("button", { name: "汇报进展" })).toBeNull();
    expect(screen.queryByRole("button", { name: "需要支持" })).toBeNull();
  });

  it("searches only authorized project context, clears an empty result and never joins another tenant", async () => {
    const user = userEvent.setup();
    render(
      <MyWork
        {...base}
        works={[
          work("可见事项"),
          work("资料受限", {
            initiative_id: "hidden",
            department_id: "hidden",
          }),
        ]}
        initiatives={[
          project,
          {
            ...project,
            id: "hidden",
            organization_id: "other",
            title: "跨租户机密项目",
          },
        ]}
        departments={[
          department,
          {
            ...department,
            id: "hidden",
            organization_id: "other",
            name: "机密部门",
          },
        ]}
      />,
    );
    expect(screen.getByText("项目资料不可见")).toBeTruthy();
    expect(screen.getByText("部门资料不可见")).toBeTruthy();
    expect(screen.queryByText("跨租户机密项目")).toBeNull();
    await user.type(screen.getByLabelText("搜索我的工作"), "青禾");
    expect(screen.getAllByRole("article")).toHaveLength(1);
    await user.clear(screen.getByLabelText("搜索我的工作"));
    await user.type(screen.getByLabelText("搜索我的工作"), "跨租户机密");
    expect(screen.getByText("没有匹配的工作")).toBeTruthy();
    await user.click(screen.getByRole("button", { name: "清空搜索" }));
    expect(screen.getAllByRole("article")).toHaveLength(2);
  });

  it("passes explicit editing intent and a grounded question without submitting a business change", async () => {
    const user = userEvent.setup();
    render(<MyWork {...base} works={[work("准备资料")]} />);
    await user.click(screen.getByRole("button", { name: "汇报进展" }));
    expect(base.onWork).toHaveBeenLastCalledWith("准备资料", "update");
    const more = screen.getByText("更多操作").closest("details")!;
    expect(more.open).toBe(false);
    await user.click(screen.getByText("更多操作"));
    expect(more.open).toBe(true);
    await user.click(screen.getByRole("button", { name: "需要支持" }));
    expect(base.onWork).toHaveBeenLastCalledWith("准备资料", "support");
    await user.click(screen.getByRole("button", { name: "询问这项工作" }));
    expect(base.onAsk).toHaveBeenCalledExactlyOnceWith(
      "准备资料",
      expect.stringContaining("不代替我确认进展"),
    );
    expect(base.onWork).toHaveBeenCalledTimes(2);
  });

  it("reflects a confirmed completion on refresh and keeps ended work read-only", async () => {
    const user = userEvent.setup();
    const view = render(<MyWork {...base} works={[work("我的交付")]} />);
    view.rerender(
      <MyWork
        {...base}
        works={[work("我的交付", { lifecycle_status: "done", version: 2 })]}
      />,
    );
    expect(screen.queryByRole("article")).toBeNull();
    await user.click(screen.getByRole("button", { name: "已结束 1" }));
    expect(screen.getByRole("article", { name: "我的交付" })).toBeTruthy();
    expect(screen.queryByRole("button", { name: "汇报进展" })).toBeNull();
  });
});
