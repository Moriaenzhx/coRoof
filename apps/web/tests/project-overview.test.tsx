import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { ProjectOverview } from "../components/project-overview";
import type { Initiative, Member, Work } from "../lib/api";

function project(id: string, fields: Partial<Initiative> = {}): Initiative {
  return {
    id,
    organization_id: "org",
    title: id,
    goal: "核对并交付已约定的资料",
    department_id: "dept",
    owner_id: "owner",
    status: "in_progress",
    due_at: "2026-11-08T08:00:00Z",
    ...fields,
  };
}
function work(id: string, projectId: string, fields: Partial<Work> = {}): Work {
  return {
    id,
    organization_id: "org",
    title: id,
    initiative_id: projectId,
    department_id: "dept",
    owner_id: "owner",
    due_at: null,
    lifecycle_status: "planned",
    needs_support: false,
    source_authority: "native",
    version: 1,
    updated_at: "2026-11-05T08:00:00Z",
    ...fields,
  };
}
const member: Member = {
  id: "owner",
  organization_id: "org",
  user_id: "user",
  name: "项目负责人",
  roles: ["manager"],
  department_id: "dept",
  status: "active",
};
const common = {
  members: [member],
  departments: [{ id: "dept", organization_id: "org", name: "交付" }],
  timezone: "Asia/Shanghai",
  onProject: vi.fn(),
  onWork: vi.fn(),
  onAll: vi.fn(),
};

describe("首页项目速览", () => {
  it("按支持需求与实际截止时间选出最多三个未结束项目，完成与取消的支持标记不影响排序", () => {
    render(
      <ProjectOverview
        {...common}
        initiatives={[
          project("较晚项目", { due_at: "2026-11-20T08:00:00Z" }),
          project("支持项目", { due_at: null }),
          project("最早截止", { due_at: "2026-11-06T08:00:00Z" }),
          project("其次截止", { due_at: "2026-11-07T08:00:00Z" }),
          project("已结项", { status: "done" }),
          project("已取消项目", { status: "cancelled" }),
        ]}
        works={[
          work("需要协调", "支持项目", { needs_support: true }),
          work("已结束需求", "较晚项目", {
            lifecycle_status: "done",
            needs_support: true,
          }),
          work("已取消需求", "较晚项目", {
            lifecycle_status: "cancelled",
            needs_support: true,
          }),
          work("旧需求", "已结项", { needs_support: true }),
          work("外部支持未知", "较晚项目", {
            source_authority: "external",
            needs_support: true,
          }),
        ]}
      />,
    );
    expect(
      screen
        .getAllByRole("article")
        .map((card) => card.getAttribute("aria-label")),
    ).toEqual(["支持项目", "最早截止", "其次截止"]);
    expect(screen.getByTitle(/支持需求优先，其次按项目截止时间/)).toBeTruthy();
    expect(screen.queryByText("已结束需求")).toBeNull();
    expect(screen.queryByText("已取消需求")).toBeNull();
    expect(screen.queryByRole("progressbar")).toBeNull();
  });

  it("保留真实目标、负责人、当地截止时间和四种状态计数，只汇总关联项目当前租户的事项", async () => {
    render(
      <ProjectOverview
        {...common}
        initiatives={[project("项目甲")]}
        works={[
          work("待开始", "项目甲"),
          work("进行", "项目甲", { lifecycle_status: "in_progress" }),
          work("完成", "项目甲", { lifecycle_status: "done" }),
          work("取消", "项目甲", { lifecycle_status: "cancelled" }),
          work("其他项目", "项目乙"),
          work("其他企业", "项目甲", { organization_id: "other" }),
        ]}
      />,
    );
    const card = within(screen.getByRole("article", { name: "项目甲" }));
    expect(card.getByText("核对并交付已约定的资料")).toBeTruthy();
    expect(card.getByText("项目负责人")).toBeTruthy();
    expect(card.getByText("交付")).toBeTruthy();
    expect(card.getByText("项目截止 11/08 16:00")).toBeTruthy();
    await userEvent.click(card.getByText("展开详情"));
    expect(
      card.getAllByRole("definition").map((entry) => entry.textContent),
    ).toEqual(["1", "1", "1", "1"]);
    expect(screen.getByText(/事项数量不代表项目整体完成度/)).toBeTruthy();
    expect(screen.queryByText("其他企业")).toBeNull();
  });

  it("仅在点击时传递真实项目或支持事项ID，更多支持保留数量并可进入项目核对", async () => {
    const user = userEvent.setup();
    const onProject = vi.fn(),
      onWork = vi.fn(),
      onAsk = vi.fn(),
      onAll = vi.fn();
    render(
      <ProjectOverview
        {...common}
        initiatives={[project("项目甲")]}
        works={[
          work("后续支持", "项目甲", {
            needs_support: true,
            due_at: "2026-11-09T08:00:00Z",
          }),
          work("先核对资料", "项目甲", {
            needs_support: true,
            due_at: "2026-11-06T08:00:00Z",
          }),
        ]}
        onProject={onProject}
        onWork={onWork}
        onAsk={onAsk}
        onAll={onAll}
      />,
    );
    expect(onAsk).not.toHaveBeenCalled();
    const details = screen.getByText("展开详情").closest("details")!;
    expect(details.open).toBe(false);
    await user.click(screen.getByText("展开详情"));
    expect(details.open).toBe(true);
    expect(screen.getByText("2 项未结束事项需要支持")).toBeTruthy();
    expect(screen.getByText("另有 1 项，可在项目中查看")).toBeTruthy();
    await user.click(screen.getByRole("button", { name: "查看项目：项目甲" }));
    expect(onProject).toHaveBeenCalledExactlyOnceWith("项目甲");
    await user.click(
      screen.getByRole("button", { name: "查看支持事项：先核对资料" }),
    );
    expect(onWork).toHaveBeenCalledExactlyOnceWith("先核对资料");
    await user.click(screen.getByRole("button", { name: "询问 先核对资料" }));
    expect(onAsk).toHaveBeenCalledExactlyOnceWith("先核对资料");
    await user.click(screen.getByRole("button", { name: "查看全部项目" }));
    expect(onAll).toHaveBeenCalledOnce();
  });

  it("缺少记录与不可见元数据保持未知，不借用其他租户同名ID或推断负责人", () => {
    render(
      <ProjectOverview
        {...common}
        initiatives={[
          project("待记录", { goal: null, due_at: null }),
          project("未分配", { owner_id: null, department_id: null }),
        ]}
        works={[]}
        members={[
          { ...member, organization_id: "other", name: "其他企业负责人" },
        ]}
        departments={[
          { id: "dept", organization_id: "other", name: "其他企业部门" },
        ]}
      />,
    );
    const card = within(screen.getByRole("article", { name: "待记录" }));
    expect(card.getByText("项目目标尚未记录。")).toBeTruthy();
    expect(card.getByText("项目未设截止时间")).toBeTruthy();
    expect(card.getByText("负责人信息不可见")).toBeTruthy();
    expect(card.getByText("部门信息不可见")).toBeTruthy();
    expect(card.getByText("当前权限内暂无事项，执行情况未知。")).toBeTruthy();
    expect(card.queryByRole("definition")).toBeNull();
    expect(screen.getByText("未分配负责人")).toBeTruthy();
    expect(screen.queryByText("其他企业负责人")).toBeNull();
    expect(screen.queryByText("其他企业部门")).toBeNull();
  });

  it("没有未结束项目时提供简短空状态，历史项目入口始终保留", async () => {
    const onAll = vi.fn();
    const view = render(
      <ProjectOverview {...common} initiatives={[]} works={[]} onAll={onAll} />,
    );
    expect(screen.getByText(/当前权限内暂无项目/)).toBeTruthy();
    view.rerender(
      <ProjectOverview
        {...common}
        initiatives={[project("已结束", { status: "done" })]}
        works={[]}
        onAll={onAll}
      />,
    );
    expect(screen.getByText(/当前权限内没有未结束的项目/)).toBeTruthy();
    expect(screen.queryByRole("article")).toBeNull();
    await userEvent.click(screen.getByRole("button", { name: "查看全部项目" }));
    expect(onAll).toHaveBeenCalledOnce();
  });
});
