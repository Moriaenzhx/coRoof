import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { Dashboard, Draft, Member, Work } from "../lib/api";
import { WorkDetail } from "../components/work-detail";
import { Panorama } from "../components/panorama";
import { Workspace } from "../components/workspace";

const mocks = vi.hoisted(() => ({
  get: vi.fn(),
  post: vi.fn(),
  patch: vi.fn(),
}));
vi.mock("../lib/api", async (importOriginal) => ({
  ...(await importOriginal<object>()),
  api: () => ({ GET: mocks.get, POST: mocks.post, PATCH: mocks.patch }),
}));
const work: Work = {
  id: "w1",
  organization_id: "o1",
  title: "客户资料交付",
  description: null,
  department_id: "d1",
  initiative_id: null,
  owner_id: "m1",
  due_at: null,
  lifecycle_status: "planned",
  needs_support: false,
  source_authority: "native",
  version: 1,
  updated_at: "2026-11-03T08:00:00Z",
};
const member: Member = {
  id: "m1",
  organization_id: "o1",
  user_id: "u1",
  name: "同事甲",
  department_id: "d1",
  roles: ["member"],
  status: "active",
};
const draft: Draft = {
  id: "draft1",
  organization_id: "o1",
  work_item_id: "w1",
  actor_id: "m1",
  raw_text: "客户资料晚到两天，需要交付协调",
  proposed_fields: {
    summary: "客户资料晚到两天，需要交付协调",
    lifecycle_status: null,
    needs_support: true,
  },
  state: "pending",
  revision: 1,
  base_version: 1,
  provider: "rules",
  created_at: "2026-11-03T08:00:00Z",
  expires_at: "2026-11-04T08:00:00Z",
};
const dashboard: Dashboard = {
  organization: {
    id: "o1",
    name: "测试企业",
    timezone: "Asia/Shanghai",
    created_at: "2026-11-03T08:00:00Z",
  },
  departments: [
    {
      department: { id: "d1", organization_id: "o1", name: "交付" },
      member_count: 1,
      work_count: 1,
      active_count: 1,
      support_count: 0,
      coverage: "recorded",
      updated_at: work.updated_at,
    },
    {
      department: { id: "d2", organization_id: "o1", name: "研发" },
      member_count: 0,
      work_count: 0,
      active_count: 0,
      support_count: 0,
      coverage: "unknown",
      updated_at: null,
    },
  ],
  total_work: 1,
  active_work: 1,
  completed_work: 0,
  support_work: 0,
  member_count: 1,
  unscoped_members: 0,
  last_updated_at: work.updated_at,
  generated_at: work.updated_at,
  scope: "organization",
  source: "native",
  external_data: "not_connected",
  analysis_mode: "rules",
};
function page<T>(items: T[]) {
  return {
    data: { items, total: items.length, offset: 0, limit: 100 },
    response: { status: 200 },
  };
}
beforeEach(() => {
  vi.resetAllMocks();
  mocks.get.mockResolvedValue(page([]));
  window.history.replaceState(null, "", "/");
});

describe("员工更新闭环", () => {
  it("文本仅生成草稿，编辑并确认后才提交业务事件", async () => {
    const user = userEvent.setup();
    const updated = vi.fn().mockResolvedValue(undefined);
    mocks.post
      .mockResolvedValueOnce({ data: draft })
      .mockResolvedValueOnce({ data: { id: "event1" } });
    mocks.patch.mockImplementation(async (_path, options) => ({
      data: {
        ...draft,
        revision: 2,
        proposed_fields: options.body.proposed_fields,
      },
    }));
    render(
      <WorkDetail
        work={work}
        organizationId="o1"
        members={[member]}
        timezone="Asia/Shanghai"
        onUpdated={updated}
      />,
    );
    await user.type(
      screen.getByLabelText("说说进展或需要的支持"),
      draft.raw_text,
    );
    await user.click(screen.getByRole("button", { name: "生成待确认草稿" }));
    expect(await screen.findByText("规则降级 · 非 AI")).toBeTruthy();
    expect(mocks.post).toHaveBeenCalledTimes(1);
    expect(updated).not.toHaveBeenCalled();
    await user.clear(screen.getByLabelText("更新内容"));
    await user.type(screen.getByLabelText("更新内容"), "需要协调交付资源");
    await user.selectOptions(screen.getByLabelText("工作状态"), "in_progress");
    await user.click(screen.getByRole("button", { name: "确认并保存" }));
    await waitFor(() => expect(updated).toHaveBeenCalledOnce());
    expect(mocks.patch.mock.calls[0][1].body.proposed_fields.summary).toBe(
      "需要协调交付资源",
    );
    expect(mocks.post.mock.calls[1][0]).toBe(
      "/api/v1/work-updates/drafts/{draft_id}/confirm",
    );
    expect(mocks.post.mock.calls[1][1].body.expected_revision).toBe(2);
    expect(screen.getByRole("status").textContent).toContain("已确认");
  });

  it("确认失败保留草稿，避免丢失用户输入", async () => {
    const user = userEvent.setup();
    mocks.post.mockResolvedValueOnce({ data: draft }).mockResolvedValueOnce({
      error: { error: { message: "事项已发生变化，请刷新后重新确认" } },
    });
    render(
      <WorkDetail
        work={work}
        organizationId="o1"
        members={[member]}
        timezone="Asia/Shanghai"
        onUpdated={vi.fn()}
      />,
    );
    await user.type(
      screen.getByLabelText("说说进展或需要的支持"),
      draft.raw_text,
    );
    await user.click(screen.getByRole("button", { name: "生成待确认草稿" }));
    await user.click(await screen.findByRole("button", { name: "确认并保存" }));
    expect((await screen.findByRole("alert")).textContent).toContain(
      "事项已发生变化",
    );
    expect(
      (screen.getByLabelText("更新内容") as HTMLTextAreaElement).value,
    ).toBe(draft.raw_text);
  });

  it("发送中禁止重复点击，快捷更新携带幂等键和事项版本", async () => {
    const user = userEvent.setup();
    let finish!: (value: unknown) => void;
    mocks.post.mockReturnValue(
      new Promise((resolve) => {
        finish = resolve;
      }),
    );
    render(
      <WorkDetail
        work={work}
        organizationId="o1"
        members={[member]}
        timezone="Asia/Shanghai"
        onUpdated={vi.fn().mockResolvedValue(undefined)}
      />,
    );
    await user.click(screen.getByRole("button", { name: "需要支持" }));
    expect(
      screen.getByRole("button", { name: "需要支持" }).hasAttribute("disabled"),
    ).toBe(true);
    await user.click(screen.getByRole("button", { name: "需要支持" }));
    expect(mocks.post).toHaveBeenCalledTimes(1);
    expect(mocks.post.mock.calls[0][1].body).toMatchObject({
      action: "support",
      expected_version: 1,
    });
    expect(mocks.post.mock.calls[0][1].body.idempotency_key).toHaveLength(36);
    finish({ data: { id: "event1" } });
    await screen.findByRole("status");
  });
});

describe("企业全景与权限界面", () => {
  it("无数据部门保持未知，节点可以下钻", async () => {
    const user = userEvent.setup();
    const onDepartment = vi.fn();
    render(
      <Panorama
        data={dashboard}
        onDepartment={onDepartment}
        onSupport={vi.fn()}
      />,
    );
    expect(screen.getByText("0 人 · 未知 / 无数据")).toBeTruthy();
    expect(screen.queryByText("运行平稳")).not.toBeTruthy();
    await user.click(screen.getByRole("button", { name: /研发/ }));
    expect(onDepartment).toHaveBeenCalledWith("d2");
  });
  it("员工进入我的工作，不显示老板页面入口", async () => {
    mocks.get.mockImplementation(async (path: string) => {
      if (path === "/api/v1/auth/me")
        return {
          data: {
            id: "u1",
            name: "同事甲",
            email: "member@example.com",
            mode: "mock",
            memberships: [
              { membership: member, organization: dashboard.organization },
            ],
          },
          response: { status: 200 },
        };
      if (path === "/api/v1/dashboard")
        return { data: { ...dashboard, scope: "assigned" } };
      if (path === "/api/v1/work-items") return page([work]);
      if (path === "/api/v1/members") return page([member]);
      return page([]);
    });
    render(<Workspace />);
    expect(
      await screen.findByRole("heading", { name: "我的工作" }),
    ).toBeTruthy();
    expect(
      await screen.findByRole("button", { name: "查看与更新" }),
    ).toBeTruthy();
    expect(screen.queryByRole("button", { name: "重要决策" })).not.toBeTruthy();
    expect(
      screen.queryByRole("button", { name: "组织与工作" }),
    ).not.toBeTruthy();
  });
  it("未登录显示真实开发验证路径，不预置演示身份", async () => {
    mocks.get.mockResolvedValue({ response: { status: 401 } });
    mocks.post.mockResolvedValue({
      data: {
        mode: "mock",
        token: "test-only-token",
        notice: "开发模拟邮件；未发送真实邮件。",
        expires_at: "2026-11-03T08:10:00Z",
      },
    });
    const user = userEvent.setup();
    render(<Workspace />);
    await user.type(await screen.findByLabelText("你的姓名"), "验收用户");
    await user.type(screen.getByLabelText("邮箱"), "test@example.com");
    await user.click(screen.getByRole("button", { name: "获取开发验证链接" }));
    expect(
      await screen.findByRole("button", { name: "确认开发身份并进入" }),
    ).toBeTruthy();
    expect(mocks.post.mock.calls[0][1].body.email).toBe("test@example.com");
  });
});
