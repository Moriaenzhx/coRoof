import { act, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { Dashboard, Draft, Member, Schemas, Work } from "../lib/api";
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
function pendingDecision(): Schemas["DecisionOut"] {
  const timestamp = new Date().toISOString();
  return {
    id: "decision1",
    work_item_id: work.id,
    signal_id: null,
    analysis_id: "analysis1",
    actor_id: member.id,
    title: "核实客户资料的处理方案",
    work_version: work.version,
    context_snapshot: {
      evidence: {
        id: "evidence1",
        work_item_id: work.id,
        work_version: work.version,
        event_id: null,
        facts: work,
        excerpt: "客户资料仍待核实",
        source_at: timestamp,
        captured_at: timestamp,
        outdated: false,
      },
      interpretation: "核实资料后记录实际结果",
      analysis_mode: "rules",
      analysis_time: timestamp,
      signal_versions: {},
    },
    options: [
      {
        id: "verify",
        title: "核实资料",
        plan: "联系负责人核实资料",
        tradeoff: "需要等待实际回复",
      },
    ],
    state: "pending",
    selected_option: null,
    selected_plan: null,
    follow_up: null,
    follow_up_at: null,
    confirmed_by: null,
    confirmed_at: null,
    created_at: timestamp,
    version: 1,
  };
}
function completedQuery(): Schemas["RunOut"] {
  return {
    id: "permission-query",
    task: "read",
    draft: null,
    question: "核对目前的工作",
    work_item_id: null,
    state: "completed",
    version: 3,
    step_count: 1,
    max_steps: 6,
    error_code: null,
    steps: [],
    created_at: work.updated_at,
    deadline: work.updated_at,
    answer: {
      id: "permission-answer",
      mode: "model",
      notice: "合成权限验收",
      summary: "权限核对前已完成的测试答复。",
      suggestions: [],
      evidence: [],
      signals: [],
      considered_work_count: 1,
      authorized_work_count: 1,
      generated_at: work.updated_at,
      prompt_version: "fixture",
      provider: "fixture",
      model: "fixture",
    },
  };
}
function mockOwnerWorkspace(
  works: Work[] = [work],
  overview = dashboard,
  signals: Schemas["SignalOut"][] = [],
) {
  const owner: Member = { ...member, name: "老板", roles: ["owner"] };
  mocks.get.mockImplementation(async (path: string) => {
    if (path === "/api/v1/auth/me")
      return {
        data: {
          id: "u1",
          name: owner.name,
          email: "owner@example.com",
          mode: "mock",
          memberships: [
            { membership: owner, organization: dashboard.organization },
          ],
        },
        response: { status: 200 },
      };
    if (path === "/api/v1/agent/runs") return { data: [] };
    if (path === "/api/v1/ai/usage")
      return {
        data: {
          scope: "organization",
          start: work.updated_at,
          end: work.updated_at,
          calls: 0,
          business_tasks: 0,
          test_calls: 0,
          succeeded: 0,
          failed: 0,
          pending_or_unknown: 0,
          input_tokens: 0,
          output_tokens: 0,
          unknown_usage_calls: 0,
          average_latency_ms: null,
          quota_occupied_tokens: 0,
          monthly_token_limit: 6000000,
          alert: false,
          cost: null,
          cost_notice: "尚未对账",
          daily: [],
          models: [],
        } satisfies Schemas["UsageOut"],
      };
    if (path === "/api/v1/ai/settings")
      return {
        data: {
          version: 0,
          mode: "platform",
          connection_id: null,
          daily_call_limit: 100,
          daily_token_limit: 200000,
          monthly_token_limit: 6000000,
          concurrency_limit: 2,
          alert_percent: 80,
          credential_storage_ready: true,
          platform_ready: false,
          platform_model: null,
          platform_provider: "rules",
          allowed_custom_base_urls: [],
        } satisfies Schemas["PolicyOut"],
      };
    if (
      [
        "/api/v1/ai/connections",
        "/api/v1/ai/providers",
        "/api/v1/ai/config-events",
      ].includes(path)
    )
      return { data: [] };
    if (path === "/api/v1/dashboard") return { data: overview };
    if (path === "/api/v1/departments")
      return page(dashboard.departments.map((d) => d.department));
    if (path === "/api/v1/members") return page([owner]);
    if (path === "/api/v1/work-items") return page(works);
    if (path === "/api/v1/signals") return page(signals);
    if (path === "/api/v1/watch/policies" || path === "/api/v1/watch/attention")
      return { data: [] };
    return page([]);
  });
}
function mockSwitchableWorkspace(
  initialOverview = async (): Promise<{ data: Dashboard }> => ({
    data: dashboard,
  }),
) {
  const owner: Member = { ...member, name: "老板", roles: ["owner"] };
  const otherOrganization = {
    ...dashboard.organization,
    id: "o2",
    name: "另一家测试企业",
  };
  const otherMember: Member = {
    ...member,
    id: "m2",
    organization_id: "o2",
    department_id: "d3",
  };
  const otherWork: Work = {
    ...work,
    id: "w2",
    organization_id: "o2",
    department_id: "d3",
    owner_id: "m2",
    title: "另一企业的验收工作",
  };
  mocks.get.mockImplementation(async (path: string, options) => {
    if (path === "/api/v1/auth/me")
      return {
        data: {
          id: "u1",
          name: owner.name,
          email: "owner@example.com",
          mode: "mock",
          memberships: [
            { membership: owner, organization: dashboard.organization },
            { membership: otherMember, organization: otherOrganization },
          ],
        },
        response: { status: 200 },
      };
    const other = options?.params?.header?.["x-organization-id"] === "o2";
    if (path === "/api/v1/agent/runs") return { data: [] };
    if (path === "/api/v1/dashboard")
      return other
        ? {
            data: {
              ...dashboard,
              organization: otherOrganization,
              departments: [],
              scope: "assigned",
            },
          }
        : initialOverview();
    if (path === "/api/v1/departments")
      return page(other ? [] : dashboard.departments.map((d) => d.department));
    if (path === "/api/v1/members") return page([other ? otherMember : owner]);
    if (path === "/api/v1/work-items") return page([other ? otherWork : work]);
    if (path === "/api/v1/watch/policies" || path === "/api/v1/watch/attention")
      return { data: [] };
    return page([]);
  });
}
beforeEach(() => {
  vi.restoreAllMocks();
  vi.resetAllMocks();
  window.localStorage.clear();
  mocks.get.mockResolvedValue(page([]));
  window.history.replaceState(null, "", "/");
});

describe("团队工作入口", () => {
  it("从团队进入工作台，不打开团队抽屉，资料复用企业知识库", async () => {
    mockOwnerWorkspace();
    const user = userEvent.setup();
    render(<Workspace />);
    const navigation = within(
      await screen.findByRole("navigation", { name: "主导航" }),
    );
    await user.click(navigation.getByRole("button", { name: "团队" }));
    await screen.findByRole("heading", { name: "团队空间" });
    await user.click(screen.getByRole("button", { name: "进入交付团队" }));
    const team = within(screen.getByRole("region", { name: "交付团队工作台" }));
    expect(team.getByText(work.title)).toBeTruthy();
    expect(screen.queryByRole("dialog")).toBeNull();
    await user.click(team.getByRole("button", { name: /企业知识库/ }));
    await screen.findByRole("navigation", { name: "知识库视图" });
    expect(
      navigation
        .getByRole("button", { name: "企业知识库" })
        .getAttribute("aria-current"),
    ).toBe("page");
    expect(mocks.post).not.toHaveBeenCalled();
    expect(mocks.patch).not.toHaveBeenCalled();
  });
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
    await user.click(screen.getByRole("button", { name: "整理这段进展" }));
    expect(await screen.findByText("文字整理 · 非 AI")).toBeTruthy();
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
    await user.click(screen.getByRole("button", { name: "整理这段进展" }));
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
  it.each(["manager", "owner"] as const)(
    "员工退出后以 %s 登录回到对应概览，再次登录员工仍进入我的工作",
    async (role) => {
      const manager: Member = {
        ...member,
        id: "manager",
        user_id: "manager-user",
        name: "管理者",
        roles: [role],
      };
      const identities: Record<string, Member> = {
        "member@example.com": member,
        "manager@example.com": manager,
      };
      let actor: Member | null = member;
      let pendingEmail = "";
      mocks.get.mockImplementation(async (path: string) => {
        if (path === "/api/v1/auth/me")
          return actor
            ? {
                data: {
                  id: actor.user_id,
                  name: actor.name,
                  email:
                    actor.id === member.id
                      ? "member@example.com"
                      : "manager@example.com",
                  mode: "mock",
                  memberships: [
                    { membership: actor, organization: dashboard.organization },
                  ],
                },
                response: { status: 200 },
              }
            : { response: { status: 401 } };
        if (path === "/api/v1/dashboard") return { data: dashboard };
        if (path === "/api/v1/work-items") return page([work]);
        if (path === "/api/v1/members") return page([member, manager]);
        if (path === "/api/v1/departments")
          return page(dashboard.departments.map((item) => item.department));
        if (
          path === "/api/v1/watch/policies" ||
          path === "/api/v1/watch/attention"
        )
          return { data: [] };
        return page([]);
      });
      mocks.post.mockImplementation(async (path: string, options) => {
        if (path === "/api/v1/auth/logout") {
          actor = null;
          return { data: {} };
        }
        if (path === "/api/v1/auth/request-link") {
          pendingEmail = options.body.email;
          return {
            data: {
              mode: "mock",
              token: "fixture-login",
              notice: "开发模拟邮件；未发送真实邮件。",
              expires_at: "2026-11-06T00:00:00Z",
            },
          };
        }
        if (path === "/api/v1/auth/verify") {
          actor = identities[pendingEmail];
          return { data: {} };
        }
        throw new Error(`Unexpected write: ${path}`);
      });
      const user = userEvent.setup();
      async function switchIdentity(email: string) {
        await user.click(screen.getByRole("button", { name: "打开账户菜单" }));
        await user.click(screen.getByRole("menuitem", { name: "退出登录" }));
        await user.type(
          await screen.findByLabelText("你的姓名"),
          identities[email].name,
        );
        await user.type(screen.getByLabelText("邮箱"), email);
        await user.click(
          screen.getByRole("button", { name: "获取开发验证链接" }),
        );
        await user.click(
          await screen.findByRole("button", { name: "确认开发身份并进入" }),
        );
      }
      render(<Workspace />);
      await screen.findByRole("button", { name: "汇报进展" });
      expect(screen.getByRole("heading", { name: "我的工作" })).toBeTruthy();
      expect(
        within(screen.getByRole("navigation", { name: "主导航" }))
          .getAllByRole("button")
          .map((button) => button.getAttribute("aria-label")),
      ).toEqual(["我的工作", "企业知识库"]);
      await switchIdentity("manager@example.com");
      await screen.findByRole("heading", { name: /先处理这几件事/ });
      expect(
        screen
          .getByRole("button", {
            name: role === "owner" ? "企业概览" : "部门概览",
          })
          .getAttribute("aria-current"),
      ).toBe("page");
      const navigation = within(
        screen.getByRole("navigation", { name: "主导航" }),
      );
      expect(
        navigation
          .getAllByRole("button")
          .map((button) => button.getAttribute("aria-label")),
      ).toEqual(
        role === "owner"
          ? ["企业概览", "项目与事项", "团队", "企业知识库", "我的工作"]
          : ["部门概览", "项目与事项", "团队", "企业知识库", "我的工作"],
      );
      if (role === "manager") {
        expect(
          mocks.get.mock.calls.some(([path]) => path === "/api/v1/decisions"),
        ).toBe(false);
        await user.click(screen.getByRole("button", { name: "打开账户菜单" }));
        await user.click(screen.getByRole("menuitem", { name: "个人设置" }));
        expect(
          screen.queryByRole("region", { name: "AI 协作偏好" }),
        ).toBeNull();
        expect(
          mocks.get.mock.calls.some(
            ([path]) => path === "/api/v1/memory/entries",
          ),
        ).toBe(false);
      }
      expect(screen.queryByRole("heading", { name: "我的工作" })).toBeNull();
      await switchIdentity("member@example.com");
      await screen.findByRole("button", { name: "汇报进展" });
      expect(screen.getByRole("heading", { name: "我的工作" })).toBeTruthy();
      expect(screen.queryByRole("button", { name: "企业概览" })).toBeNull();
      expect(screen.queryByRole("button", { name: "部门概览" })).toBeNull();
      expect(mocks.post.mock.calls.map(([path]) => path)).toEqual([
        "/api/v1/auth/logout",
        "/api/v1/auth/request-link",
        "/api/v1/auth/verify",
        "/api/v1/auth/logout",
        "/api/v1/auth/request-link",
        "/api/v1/auth/verify",
      ]);
    },
  );

  it("老板按分组导航，决策经验与个人偏好独立读取，切换入口不写入", async () => {
    mockOwnerWorkspace();
    const user = userEvent.setup();
    render(<Workspace />);
    const navigation = within(
      await screen.findByRole("navigation", { name: "主导航" }),
    );
    expect(
      navigation
        .getAllByRole("group")
        .map((group) => group.getAttribute("aria-label")),
    ).toEqual(["企业经营", "资料", "个人"]);
    expect(
      mocks.get.mock.calls.some(([path]) => path === "/api/v1/memory/entries"),
    ).toBe(false);
    expect(navigation.queryByRole("button", { name: "决策经验" })).toBeNull();
    await user.click(screen.getByRole("button", { name: "打开账户菜单" }));
    await user.click(screen.getByRole("menuitem", { name: "个人设置" }));
    await user.click(
      await screen.findByRole("button", { name: "查看以前的处理经验" }),
    );
    await screen.findByText("还没有决策经验。记录实际结果后，可以在这里整理。");
    expect(
      screen.queryByRole("tablist", { name: "经验与偏好类别" }),
    ).toBeNull();
    expect(
      navigation.queryAllByRole("button", { current: "page" }),
    ).toHaveLength(0);
    expect(screen.queryByRole("button", { name: "添加偏好" })).toBeNull();
    await user.click(screen.getByRole("button", { name: "打开账户菜单" }));
    await user.click(screen.getByRole("menuitem", { name: "个人设置" }));
    const preferences = within(
      await screen.findByRole("region", { name: "AI 协作偏好" }),
    );
    await preferences.findByText(
      "还没有明确确认的偏好。你可以先写下希望参考的重点。",
    );
    expect(preferences.getByRole("button", { name: "添加偏好" })).toBeTruthy();
    expect(screen.queryByRole("button", { name: "整理经验" })).toBeNull();
    expect(
      navigation.queryAllByRole("button", { current: "page" }),
    ).toHaveLength(0);
    expect(
      mocks.get.mock.calls
        .filter(([path]) => path === "/api/v1/memory/entries")
        .map(([, options]) => options.params.query.kind),
    ).toEqual(["preference", "experience", "preference"]);
    expect(mocks.post).not.toHaveBeenCalled();
  });

  it("指令在非阻塞浮层执行，切页收起后仍完成，历史只读打开不重发", async () => {
    mockOwnerWorkspace();
    const baseGet = mocks.get.getMockImplementation()!;
    const ready: Schemas["RunOut"] = {
      id: "query1",
      task: "read",
      draft: null,
      question: "有哪些需要我处理的",
      work_item_id: null,
      state: "ready",
      version: 1,
      step_count: 0,
      max_steps: 6,
      error_code: null,
      steps: [],
      answer: null,
      created_at: work.updated_at,
      deadline: work.updated_at,
    };
    const complete: Schemas["RunOut"] = {
      ...ready,
      state: "completed",
      version: 3,
      step_count: 1,
      answer: {
        id: "answer1",
        mode: "model",
        notice: "合成测试回答",
        summary: "已核对本人待办，仍有资料需要确认。",
        suggestions: [],
        evidence: [],
        signals: [],
        considered_work_count: 1,
        authorized_work_count: 1,
        generated_at: work.updated_at,
        prompt_version: "fixture",
        provider: "fixture",
        model: "fixture",
      },
    };
    let finish!: (value: { data: Schemas["RunOut"] }) => void;
    const request = new Promise<{ data: Schemas["RunOut"] }>((resolve) => {
      finish = resolve;
    });
    mocks.get.mockImplementation(async (path: string, options) => {
      if (path === "/api/v1/agent/runs") return { data: [complete] };
      if (path === "/api/v1/agent/runs/{run_id}") return { data: complete };
      return baseGet(path, options);
    });
    mocks.post.mockImplementation(async (path: string) => {
      if (path === "/api/v1/agent/runs/submit") return { data: ready };
      if (path === "/api/v1/agent/runs/{run_id}/advance") return request;
      throw new Error(`Unexpected write: ${path}`);
    });
    const user = userEvent.setup();
    render(<Workspace />);
    await user.type(
      await screen.findByLabelText("告诉 coRoof 你想做什么"),
      ready.question,
    );
    await user.click(screen.getByRole("button", { name: "发送指令" }));
    await waitFor(() =>
      expect(
        mocks.post.mock.calls.filter(([path]) => path.endsWith("/advance")),
      ).toHaveLength(1),
    );
    expect(
      screen.getByRole("region", { name: "coRoof 处理进度与结果" }),
    ).toBeTruthy();
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(screen.queryByRole("button", { name: "连续查询" })).toBeNull();
    expect(screen.queryByRole("button", { name: "快速整理" })).toBeNull();
    expect(screen.queryByLabelText("让 coRoof 继续查询")).toBeNull();
    expect(document.body.style.overflow).not.toBe("hidden");
    await user.click(screen.getByRole("button", { name: "项目与事项" }));
    expect(
      screen.getByRole("heading", { name: "项目与事项", level: 1 }),
    ).toBeTruthy();
    expect(
      screen.queryByRole("region", { name: "coRoof 处理进度与结果" }),
    ).toBeNull();
    await act(async () => finish({ data: complete }));
    await user.click(
      await screen.findByRole("button", {
        name: "展开 coRoof 处理结果：处理完成",
      }),
    );
    await screen.findByText("已核对本人待办，仍有资料需要确认。");
    expect(mocks.post).toHaveBeenCalledTimes(2);
    await user.click(screen.getByRole("button", { name: "查看处理记录" }));
    await user.click(
      await screen.findByRole("button", {
        name: `查看查询：${ready.question}`,
      }),
    );
    await screen.findByText("已核对本人待办，仍有资料需要确认。");
    expect(mocks.post).toHaveBeenCalledTimes(2);
  });

  it("自然追问只继承最近完成的问题，换话题后不再带旧上下文", async () => {
    mockOwnerWorkspace();
    let index = 0;
    mocks.post.mockImplementation(async (path: string, options) => {
      if (path !== "/api/v1/agent/runs/submit")
        throw new Error(`Unexpected write: ${path}`);
      index++;
      return {
        data: {
          ...completedQuery(),
          id: `turn-${index}`,
          work_item_id: null,
          question: options.body.question,
        },
      };
    });
    const user = userEvent.setup();
    render(<Workspace />);
    const input = await screen.findByLabelText("告诉 coRoof 你想做什么");
    await user.type(input, "有哪些公司资料？");
    await user.click(screen.getByRole("button", { name: "发送指令" }));
    await screen.findByRole("button", { name: "换个话题" });
    expect(mocks.post.mock.calls[0][1].body.parent_run_id).toBeUndefined();
    await user.type(input, "里面写了什么？");
    await user.click(screen.getByRole("button", { name: "发送指令" }));
    await waitFor(() => expect(mocks.post).toHaveBeenCalledTimes(2));
    expect(mocks.post.mock.calls[1][1].body.parent_run_id).toBe("turn-1");
    await user.click(await screen.findByRole("button", { name: "换个话题" }));
    await user.type(input, "看看项目进度");
    await user.click(screen.getByRole("button", { name: "发送指令" }));
    await waitFor(() => expect(mocks.post).toHaveBeenCalledTimes(3));
    expect(mocks.post.mock.calls[2][1].body.parent_run_id).toBeUndefined();
  });

  it("创建查询时重复发送不创建第二次，切换企业后迟到结果不继续推进", async () => {
    mockSwitchableWorkspace();
    let finish!: (value: { data: Schemas["RunOut"] }) => void;
    mocks.post.mockImplementation((path: string) => {
      if (path !== "/api/v1/agent/runs/submit")
        throw new Error(`Unexpected write: ${path}`);
      return new Promise((resolve) => {
        finish = resolve;
      });
    });
    const user = userEvent.setup();
    render(<Workspace />);
    await user.type(
      await screen.findByLabelText("告诉 coRoof 你想做什么"),
      "核对第一家企业的资料",
    );
    await user.dblClick(screen.getByRole("button", { name: "发送指令" }));
    await waitFor(() => expect(mocks.post).toHaveBeenCalledOnce());
    expect(mocks.post.mock.calls[0][1].params.header["x-organization-id"]).toBe(
      "o1",
    );
    await user.click(screen.getByRole("button", { name: "打开账户菜单" }));
    await user.click(screen.getByRole("menuitem", { name: "个人设置" }));
    await user.selectOptions(
      screen.getByRole("combobox", { name: "切换企业" }),
      "o2",
    );
    await user.click(screen.getByRole("button", { name: "我的工作" }));
    await screen.findByRole("heading", { name: "另一企业的验收工作" });
    await act(async () =>
      finish({
        data: {
          id: "old-organization-query",
          task: "read",
          work_item_id: null,
          question: "核对第一家企业的资料",
          state: "ready",
          version: 1,
          step_count: 0,
          max_steps: 6,
          steps: [],
          answer: null,
          error_code: null,
          created_at: work.updated_at,
          deadline: work.updated_at,
        },
      }),
    );
    expect(mocks.post).toHaveBeenCalledOnce();
    expect(
      screen.queryByRole("region", { name: "coRoof 处理进度与结果" }),
    ).toBeNull();
    expect(
      screen.queryByRole("button", { name: /展开 coRoof 处理结果/ }),
    ).toBeNull();
    expect(screen.queryByText("核对第一家企业的资料")).toBeNull();
    expect(screen.queryByRole("region", { name: "等我确认与跟进" })).toBeNull();
  });

  it.each(["not_configured", "model_disabled"])(
    "服务 %s 的指令显示可操作失败原因并保留我的工作入口",
    async (code) => {
      mockOwnerWorkspace();
      const ready: Schemas["RunOut"] = {
        id: "query2",
        task: "read",
        draft: null,
        question: "核实当前工作",
        work_item_id: null,
        state: "ready",
        version: 1,
        step_count: 0,
        max_steps: 6,
        error_code: null,
        steps: [],
        answer: null,
        created_at: work.updated_at,
        deadline: work.updated_at,
      };
      mocks.post.mockImplementation(async (path: string) => ({
        data: path.endsWith("/advance")
          ? {
              ...ready,
              state: "failed",
              version: 2,
              error_code: code,
            }
          : ready,
      }));
      const user = userEvent.setup();
      render(<Workspace />);
      await user.type(
        await screen.findByLabelText("告诉 coRoof 你想做什么"),
        ready.question,
      );
      await user.click(screen.getByRole("button", { name: "发送指令" }));
      await screen.findByRole("button", { name: "检查企业 AI 设置" });
      expect(
        screen.getByText(
          code === "model_disabled"
            ? "企业已停用模型服务，请由企业所有者在企业 AI 设置中选择并启用可用服务。"
            : "尚未配置可用的企业模型，请在企业 AI 设置中核对。",
        ),
      ).toBeTruthy();
      expect(screen.queryByRole("dialog")).toBeNull();
      await user.click(screen.getByRole("button", { name: "收起处理浮层" }));
      const chip = screen.getByRole("button", {
        name: "展开 coRoof 处理结果：需要留意",
      });
      expect(document.activeElement).toBe(chip);
      await user.click(chip);
      expect(document.activeElement).toBe(
        screen.getByRole("region", { name: "coRoof 处理进度与结果" }),
      );
      await user.click(
        screen.getByRole("button", { name: "检查企业 AI 设置" }),
      );
      expect(
        screen.getByRole("heading", { name: "AI 使用与设置", level: 1 }),
      ).toBeTruthy();
      expect(
        await screen.findByRole("button", { name: "配置自己的 API Key" }),
      ).toBeTruthy();
      expect(mocks.post.mock.calls.map(([path]) => path)).toEqual([
        "/api/v1/agent/runs/submit",
        "/api/v1/agent/runs/{run_id}/advance",
      ]);
    },
  );

  it.each([401, 403])(
    "完成答复后收到 %s 即清除旧结果与输入，不被先到的网络错误掩盖",
    async (status) => {
      mockOwnerWorkspace();
      const baseGet = mocks.get.getMockImplementation()!;
      const completed = completedQuery();
      let failRefresh = false;
      let deny!: (value: {
        error: { error: { message: string } };
        response: { status: number };
      }) => void;
      const denied = new Promise<{
        error: { error: { message: string } };
        response: { status: number };
      }>((resolve) => {
        deny = resolve;
      });
      mocks.get.mockImplementation(async (path: string, options) => {
        if (failRefresh && path === "/api/v1/dashboard")
          throw new Error("概览暂时连接中断");
        if (failRefresh && path === "/api/v1/work-items") return denied;
        return baseGet(path, options);
      });
      mocks.post.mockImplementation(async (path: string) => ({
        data: path.endsWith("/advance")
          ? completed
          : {
              ...completed,
              state: "ready",
              answer: null,
              version: 1,
              step_count: 0,
            },
      }));
      const user = userEvent.setup();
      render(<Workspace />);
      await user.type(
        await screen.findByLabelText("告诉 coRoof 你想做什么"),
        completed.question,
      );
      await user.click(screen.getByRole("button", { name: "发送指令" }));
      await screen.findByText(completed.answer!.summary);
      await user.type(
        screen.getByLabelText("告诉 coRoof 你想做什么"),
        "仍未发送的旧草稿",
      );
      failRefresh = true;
      await act(async () => {
        window.dispatchEvent(new Event("focus"));
      });
      await screen.findByText("概览暂时连接中断");
      expect(screen.getByText(completed.answer!.summary)).toBeTruthy();
      await act(async () => {
        deny({
          error: { error: { message: "当前权限已撤销" } },
          response: { status },
        });
      });
      await screen.findByText(
        "当前企业的访问权限已失效，已收起查询结果。请重新核对身份或切换企业。",
      );
      expect(screen.queryByText(completed.answer!.summary)).toBeNull();
      expect(
        screen.queryByRole("region", { name: "coRoof 处理进度与结果" }),
      ).toBeNull();
      expect(
        screen.queryByRole("button", { name: /展开 coRoof 处理结果/ }),
      ).toBeNull();
      const input = screen.getByLabelText(
        "告诉 coRoof 你想做什么",
      ) as HTMLTextAreaElement;
      expect(input.value).toBe("");
      expect(input.disabled).toBe(true);
      expect(mocks.post).toHaveBeenCalledTimes(2);
      failRefresh = false;
      await act(async () => {
        window.dispatchEvent(new Event("focus"));
      });
      await waitFor(() => expect(input.disabled).toBe(false));
      expect(screen.queryByText(completed.answer!.summary)).toBeNull();
      expect(mocks.post).toHaveBeenCalledTimes(2);
    },
  );

  it("普通工作区网络错误保留正在执行的任务和未发送草稿，后续结果仍可显示", async () => {
    mockOwnerWorkspace();
    const baseGet = mocks.get.getMockImplementation()!;
    const completed = completedQuery();
    let failRefresh = false;
    let finish!: (value: { data: Schemas["RunOut"] }) => void;
    const advanced = new Promise<{ data: Schemas["RunOut"] }>((resolve) => {
      finish = resolve;
    });
    mocks.get.mockImplementation(async (path: string, options) => {
      if (failRefresh && path === "/api/v1/dashboard")
        throw new Error("普通网络连接中断");
      return baseGet(path, options);
    });
    mocks.post.mockImplementation(async (path: string) =>
      path.endsWith("/advance")
        ? advanced
        : {
            data: {
              ...completed,
              state: "ready",
              answer: null,
              version: 1,
              step_count: 0,
            },
          },
    );
    const user = userEvent.setup();
    render(<Workspace />);
    await user.type(
      await screen.findByLabelText("告诉 coRoof 你想做什么"),
      completed.question,
    );
    await user.click(screen.getByRole("button", { name: "发送指令" }));
    await waitFor(() => expect(mocks.post).toHaveBeenCalledTimes(2));
    await user.type(
      screen.getByLabelText("告诉 coRoof 你想做什么"),
      "下一条未发送的问题",
    );
    failRefresh = true;
    await act(async () => {
      window.dispatchEvent(new Event("focus"));
    });
    await screen.findByText("普通网络连接中断");
    expect(
      screen.getByRole("region", { name: "coRoof 处理进度与结果" }),
    ).toBeTruthy();
    await act(async () => {
      finish({ data: completed });
    });
    await screen.findByText(completed.answer!.summary);
    const input = screen.getByLabelText(
      "告诉 coRoof 你想做什么",
    ) as HTMLTextAreaElement;
    expect(input.value).toBe("下一条未发送的问题");
    expect(input.disabled).toBe(false);
    expect(mocks.post).toHaveBeenCalledTimes(2);
  });

  it("决策从我的工作确认和跟进，概览与企业记录使用同一状态，不增加一级入口", async () => {
    mockOwnerWorkspace();
    const baseGet = mocks.get.getMockImplementation()!;
    let decision = pendingDecision();
    let outcomes: Schemas["OutcomeOut"][] = [];
    let revision = 0;
    mocks.get.mockImplementation(async (path: string, options) => {
      if (path === "/api/v1/dashboard")
        return { data: { ...dashboard, generated_at: `revision-${revision}` } };
      if (path === "/api/v1/decisions") {
        const query = options.params.query;
        const isRecorded = outcomes.length > 0;
        const visible =
          query.view === "all" ||
          (query.view === "recorded"
            ? isRecorded
            : query.view === "pending"
              ? decision.state === "pending"
              : query.view === "follow_up"
                ? decision.state === "confirmed" && !isRecorded
                : !isRecorded);
        return page(
          visible ? [{ ...decision, outcome_count: outcomes.length }] : [],
        );
      }
      if (path === "/api/v1/decisions/{decision_id}") return { data: decision };
      if (path === "/api/v1/decisions/{decision_id}/outcomes")
        return page(outcomes);
      return baseGet(path, options);
    });
    mocks.post.mockImplementation(async (path: string, options) => {
      if (path === "/api/v1/decisions/{decision_id}/confirm") {
        decision = {
          ...decision,
          ...options.body,
          state: "confirmed",
          confirmed_by: member.id,
          confirmed_at: new Date().toISOString(),
          version: 2,
        };
        revision++;
        return { data: decision };
      }
      if (path === "/api/v1/decisions/{decision_id}/outcomes") {
        outcomes = [
          {
            id: "outcome1",
            decision_id: decision.id,
            actor_id: member.id,
            observed_result: options.body.observed_result,
            evidence_refs: [],
            recorded_at: new Date().toISOString(),
          },
        ];
        revision++;
        return { data: outcomes[0] };
      }
      throw new Error(`Unexpected write: ${path}`);
    });
    const user = userEvent.setup();
    render(<Workspace />);
    await screen.findByText("1 项待确认或待跟进，统一到“我的工作”处理。");
    expect(
      within(screen.getByRole("navigation", { name: "主导航" })).queryByRole(
        "button",
        { name: "决策与跟进" },
      ),
    ).toBeNull();
    await user.click(screen.getByRole("button", { name: "我的工作" }));
    let queue = within(
      await screen.findByRole("region", { name: "等我确认与跟进" }),
    );
    await user.click(
      await queue.findByRole("button", { name: new RegExp(decision.title) }),
    );
    let detail = within(screen.getByRole("dialog", { name: "确认处理安排" }));
    await user.click(await detail.findByText("修改这个安排"));
    await user.click(detail.getByRole("radio", { name: /核实资料/ }));
    await user.clear(detail.getByLabelText("后续如何跟进"));
    await user.type(
      detail.getByLabelText("后续如何跟进"),
      "核实后记录实际回复",
    );
    expect(mocks.post).not.toHaveBeenCalled();
    await user.click(detail.getByRole("button", { name: "确认这个安排" }));
    await detail.findByText("方案已确认并记录，可以继续补充实际跟进结果。");
    await user.click(detail.getByRole("button", { name: "关闭详情" }));
    queue = within(screen.getByRole("region", { name: "等我确认与跟进" }));
    await within(queue.getByRole("list", { name: "决策记录" })).findByText(
      "待跟进",
    );
    await user.click(
      queue.getByRole("button", { name: new RegExp(decision.title) }),
    );
    detail = within(screen.getByRole("dialog", { name: "确认处理安排" }));
    await user.type(
      await detail.findByLabelText("记录实际结果"),
      "已联系负责人，资料仍未到位，需要继续核实。",
    );
    await user.click(detail.getByRole("button", { name: "保存跟进结果" }));
    await detail.findByText("实际结果已追加到决策记录。");
    await user.click(detail.getByRole("button", { name: "关闭详情" }));
    queue = within(screen.getByRole("region", { name: "等我确认与跟进" }));
    await waitFor(() =>
      expect(
        queue.queryByRole("button", { name: new RegExp(decision.title) }),
      ).toBeNull(),
    );
    await user.click(queue.getByRole("button", { name: "查看全部记录" }));
    await queue.findByRole("button", { name: new RegExp(decision.title) });
    await user.click(screen.getByRole("button", { name: "企业概览" }));
    await screen.findByText("当前没有待确认或待跟进的决策。");
    await user.click(screen.getByText("处理记录与团队动态"));
    await user.click(screen.getByRole("button", { name: "查看企业决策记录" }));
    const records = within(
      await screen.findByRole("region", { name: "企业决策记录" }),
    );
    await user.click(
      await records.findByRole("button", { name: new RegExp(decision.title) }),
    );
    await within(
      screen.getByRole("dialog", { name: "确认处理安排" }),
    ).findByText("已联系负责人，资料仍未到位，需要继续核实。");
    expect(
      mocks.get.mock.calls
        .filter(([path]) => path === "/api/v1/decisions/{decision_id}")
        .every(
          ([, options]) => options.params.path.decision_id === "decision1",
        ),
    ).toBe(true);
    expect(mocks.post.mock.calls.map(([path]) => path)).toEqual([
      "/api/v1/decisions/{decision_id}/confirm",
      "/api/v1/decisions/{decision_id}/outcomes",
    ]);
  });

  it("收起侧栏后仍可从个人设置切换或建立企业，打开入口不写入", async () => {
    mockOwnerWorkspace();
    const user = userEvent.setup();
    render(<Workspace />);
    await user.click(await screen.findByRole("button", { name: "收起侧边栏" }));
    expect(screen.queryByRole("heading", { name: "企业概览" })).toBeNull();
    expect(screen.queryByRole("combobox", { name: "切换企业" })).toBeNull();
    expect(screen.getByLabelText("告诉 coRoof 你想做什么")).toBeTruthy();
    await user.click(screen.getByRole("button", { name: "打开账户菜单" }));
    await user.click(screen.getByRole("menuitem", { name: "个人设置" }));
    expect(screen.getByRole("heading", { name: "个人设置" })).toBeTruthy();
    const switcher = screen.getByRole("combobox", { name: "切换企业" });
    expect((switcher as HTMLSelectElement).value).toBe("o1");
    expect(
      screen.getByText("当前为开发模拟身份，尚未接入正式身份验证。"),
    ).toBeTruthy();
    await user.selectOptions(switcher, "new");
    const creation = within(
      screen.getByRole("dialog", { name: "建立新的企业" }),
    );
    expect(creation.getByLabelText("企业名称")).toBeTruthy();
    expect(creation.getByRole("button", { name: "建立企业" })).toBeTruthy();
    await user.click(creation.getByRole("button", { name: "关闭详情" }));
    expect(
      (screen.getByRole("combobox", { name: "切换企业" }) as HTMLSelectElement)
        .value,
    ).toBe("o1");
    expect(mocks.post).not.toHaveBeenCalled();
  });

  it("从个人设置切换企业时清空未发送指令并采用目标成员权限，旧读取不能覆盖新企业", async () => {
    let completeOldRead!: (value: { data: Dashboard }) => void;
    let reads = 0;
    mockSwitchableWorkspace(() => {
      if (reads++ === 0) return Promise.resolve({ data: dashboard });
      return new Promise((resolve) => {
        completeOldRead = resolve;
      });
    });
    const user = userEvent.setup();
    render(<Workspace />);
    await screen.findByRole("button", { name: /收起全景/ });
    await user.type(
      screen.getByLabelText("告诉 coRoof 你想做什么"),
      "仅针对原企业的未发送问题",
    );
    await user.click(screen.getByRole("button", { name: "刷新数据" }));
    await waitFor(() => expect(completeOldRead).toBeTypeOf("function"));
    await user.click(screen.getByRole("button", { name: "打开账户菜单" }));
    await user.click(screen.getByRole("menuitem", { name: "个人设置" }));
    const switchCall = mocks.get.mock.calls.length;
    await user.selectOptions(
      screen.getByRole("combobox", { name: "切换企业" }),
      "o2",
    );
    expect(
      await screen.findByRole("heading", { name: "我的工作" }),
    ).toBeTruthy();
    await screen.findByText("另一企业的验收工作");
    expect(
      (screen.getByLabelText("告诉 coRoof 你想做什么") as HTMLTextAreaElement)
        .value,
    ).toBe("");
    expect(screen.queryByRole("button", { name: "组织与工作" })).toBeNull();
    expect(screen.queryByRole("button", { name: "决策与跟进" })).toBeNull();
    const scopedReads = mocks.get.mock.calls
      .slice(switchCall)
      .filter(([path]) =>
        [
          "/api/v1/dashboard",
          "/api/v1/departments",
          "/api/v1/members",
          "/api/v1/initiatives",
          "/api/v1/work-items",
          "/api/v1/signals",
        ].includes(path),
      );
    expect(scopedReads.length).toBeGreaterThanOrEqual(6);
    for (const [, options] of scopedReads)
      expect(options.params.header["x-organization-id"]).toBe("o2");
    await act(async () => completeOldRead({ data: dashboard }));
    expect(screen.getByText("另一企业的验收工作")).toBeTruthy();
    expect(screen.queryByText("客户资料交付")).toBeNull();
    await user.click(screen.getByRole("button", { name: "打开账户菜单" }));
    expect(screen.queryByRole("menuitem", { name: "企业 AI 设置" })).toBeNull();
    await user.click(screen.getByRole("menuitem", { name: "个人设置" }));
    expect(
      (screen.getByRole("combobox", { name: "切换企业" }) as HTMLSelectElement)
        .value,
    ).toBe("o2");
    expect(mocks.post).not.toHaveBeenCalled();
  });

  it("业务读取失败时个人设置仍可达，能够切换到另一个已加入的企业", async () => {
    mockSwitchableWorkspace(async () => {
      throw new Error("原企业工作记录暂时不可读取");
    });
    const user = userEvent.setup();
    render(<Workspace />);
    expect((await screen.findByRole("alert")).textContent).toContain(
      "原企业工作记录暂时不可读取",
    );
    await user.click(screen.getByRole("button", { name: "打开账户菜单" }));
    await user.click(screen.getByRole("menuitem", { name: "个人设置" }));
    await user.selectOptions(
      screen.getByRole("combobox", { name: "切换企业" }),
      "o2",
    );
    await screen.findByText("另一企业的验收工作");
    expect(screen.queryByText("原企业工作记录暂时不可读取")).toBeNull();
    expect(screen.getByRole("heading", { name: "我的工作" })).toBeTruthy();
    expect(mocks.post).not.toHaveBeenCalled();
  });

  it("支持需求与生命周期并存，列表和详情保留相同事实", async () => {
    mockOwnerWorkspace([
      { ...work, lifecycle_status: "in_progress", needs_support: true },
    ]);
    const user = userEvent.setup();
    render(<Workspace />);
    await user.click(await screen.findByRole("button", { name: "项目与事项" }));
    const item = screen.getByRole("button", {
      name: /客户资料交付.*进行中.*需要支持/,
    });
    expect(within(item).getByText("进行中")).toBeTruthy();
    expect(within(item).getByText("需要支持")).toBeTruthy();
    await user.click(item);
    const detail = within(screen.getByRole("dialog"));
    expect(detail.getByText("进行中", { exact: true })).toBeTruthy();
    expect(detail.getByText("需要支持", { exact: true })).toBeTruthy();
    expect(detail.getByRole("button", { name: "解除阻塞" })).toBeTruthy();
    expect(mocks.post).not.toHaveBeenCalled();
  });

  it("只有真实支持需求才突出提示，同时保留其他部门的未知状态", async () => {
    const user = userEvent.setup();
    const onSupport = vi.fn();
    const onDepartment = vi.fn();
    const view = render(
      <Panorama
        data={dashboard}
        onSupport={onSupport}
        onDepartment={onDepartment}
      />,
    );
    expect(screen.queryByText("当前有支持需求")).toBeNull();
    expect(screen.queryByRole("button", { name: /查看支持需求/ })).toBeNull();
    view.rerender(
      <Panorama
        data={{
          ...dashboard,
          support_work: 1,
          departments: dashboard.departments.map((d) =>
            d.department.id === "d1" ? { ...d, support_count: 1 } : d,
          ),
        }}
        onSupport={onSupport}
        onDepartment={onDepartment}
      />,
    );
    expect(
      screen.getByRole("heading", { name: /项工作需要支持/ }),
    ).toBeTruthy();
    expect(
      screen.getByRole("button", { name: /交付.*1 项需要支持/ }),
    ).toBeTruthy();
    expect(
      screen.getByRole("button", { name: /研发.*未知 \/ 无数据/ }),
    ).toBeTruthy();
    await user.click(screen.getByRole("button", { name: /查看支持需求/ }));
    expect(onSupport).toHaveBeenCalledOnce();
  });

  it("收起后图标仍可导航，键盘能展开，重新进入保留偏好", async () => {
    mockOwnerWorkspace();
    const user = userEvent.setup();
    const view = render(<Workspace />);
    const collapse = await screen.findByRole("button", { name: "收起侧边栏" });
    expect(collapse.getAttribute("aria-expanded")).toBe("true");
    await user.click(collapse);
    const expand = screen.getByRole("button", { name: "展开侧边栏" });
    expect(expand.getAttribute("aria-expanded")).toBe("false");
    const business = screen.getByRole("button", { name: "项目与事项" });
    expect(business.getAttribute("title")).toBe(
      "项目与事项 · 查看项目目标、期限与具体事项",
    );
    await user.click(business);
    expect(screen.getByRole("heading", { name: "项目与事项" })).toBeTruthy();
    expect(business.getAttribute("aria-current")).toBe("page");
    expand.focus();
    await user.keyboard("{Enter}");
    expect(screen.getByRole("heading", { name: "项目与事项" })).toBeTruthy();
    expect(
      screen
        .getByRole("button", { name: "收起侧边栏" })
        .getAttribute("aria-expanded"),
    ).toBe("true");
    await user.keyboard(" ");
    view.unmount();
    render(<Workspace />);
    expect(
      (await screen.findByRole("button", { name: "展开侧边栏" })).getAttribute(
        "aria-expanded",
      ),
    ).toBe("false");
    expect(mocks.post).not.toHaveBeenCalled();
  });

  it("浏览器禁用偏好存储时仍可收起和展开", async () => {
    mockOwnerWorkspace();
    vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => {
      throw new Error("Storage blocked");
    });
    vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
      throw new Error("Storage blocked");
    });
    const user = userEvent.setup();
    render(<Workspace />);
    await user.click(await screen.findByRole("button", { name: "收起侧边栏" }));
    await user.click(screen.getByRole("button", { name: "展开侧边栏" }));
    expect(screen.getByRole("button", { name: "收起侧边栏" })).toBeTruthy();
    expect(
      screen
        .getByRole("button", { name: "企业概览" })
        .getAttribute("aria-current"),
    ).toBe("page");
  });

  it("提示引用未载入工作时要求重读，不显示无关支持工作或退回全企业问答", async () => {
    mockOwnerWorkspace([{ ...work, needs_support: true }], dashboard, [
      {
        id: "missing-signal",
        work_item_id: "missing-work",
        work_title: "待重新读取的工作",
        evidence_id: "e-missing",
        category: "overdue",
        severity: "attention",
        state: "active",
        rule_version: "v1",
        detected_at: work.updated_at,
        evaluated_at: work.updated_at,
        version: 1,
        title: "日期待核实",
        explanation: "请核对记录中的截止时间。",
      },
    ]);
    const user = userEvent.setup();
    render(<Workspace />);
    const row = within(
      await screen.findByRole("article", { name: "待重新读取的工作" }),
    );
    await user.click(row.getByRole("button", { name: "核实当前进展" }));
    let detail = within(screen.getByRole("dialog"));
    expect(
      detail.getByRole("button", { name: "重新读取工作记录" }),
    ).toBeTruthy();
    expect(detail.queryByText("客户资料交付")).toBeNull();
    await user.click(detail.getByRole("button", { name: "关闭详情" }));
    await user.click(row.getByText("依据与来源"));
    await user.click(row.getByRole("button", { name: "梳理下一步" }));
    detail = within(screen.getByRole("dialog"));
    expect(
      detail.getByRole("button", { name: "重新读取工作记录" }),
    ).toBeTruthy();
    expect(detail.queryByRole("textbox")).toBeNull();
    expect(mocks.post).not.toHaveBeenCalled();
  });

  it("首页先展示可收起动态全景，再显示要处理的事，未知部门可下钻且不写入", async () => {
    mockOwnerWorkspace();
    const user = userEvent.setup();
    render(<Workspace />);
    const toggle = await screen.findByRole("button", { name: /收起全景/ });
    expect(toggle.getAttribute("aria-expanded")).toBe("true");
    const panorama = screen.getByRole("region", { name: "企业运行全景" });
    const inbox = screen.getByRole("region", { name: /先处理这几件事/ });
    expect(
      panorama.compareDocumentPosition(inbox) &
        Node.DOCUMENT_POSITION_FOLLOWING,
    ).toBeTruthy();
    expect(within(panorama).getByText("0 人 · 未知 / 无数据")).toBeTruthy();
    await user.click(within(panorama).getByRole("button", { name: /研发/ }));
    expect(screen.getByRole("dialog", { name: "研发" })).toBeTruthy();
    await user.click(screen.getByRole("button", { name: "关闭详情" }));
    await user.click(screen.getByRole("button", { name: /收起全景/ }));
    expect(screen.queryByRole("region", { name: "企业运行全景" })).toBeNull();
    expect(mocks.post).not.toHaveBeenCalled();
  });

  it("手机首次读取工作空间后保留顶部全景摘要，展开仍可查看部门", async () => {
    vi.stubGlobal("innerWidth", 390);
    try {
      mockOwnerWorkspace();
      const user = userEvent.setup();
      render(<Workspace />);
      const toggle = await screen.findByRole("button", { name: /展开全景/ });
      expect(toggle.getAttribute("aria-expanded")).toBe("false");
      expect(screen.queryByRole("region", { name: "企业运行全景" })).toBeNull();
      expect(
        screen.getByRole("region", { name: /先处理这几件事/ }),
      ).toBeTruthy();
      await user.click(toggle);
      expect(screen.getByRole("region", { name: "企业运行全景" })).toBeTruthy();
      expect(mocks.post).not.toHaveBeenCalled();
    } finally {
      vi.unstubAllGlobals();
    }
  });

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
  it("员工可从本人工作直接汇报，打开草稿入口不写入，也不请求老板关注数据", async () => {
    const user = userEvent.setup();
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
      await screen.findByRole("button", { name: "汇报进展" }),
    ).toBeTruthy();
    expect(
      screen.queryByRole("button", { name: "决策与跟进" }),
    ).not.toBeTruthy();
    expect(
      screen.queryByRole("button", { name: "组织与工作" }),
    ).not.toBeTruthy();
    await user.click(screen.getByRole("button", { name: "汇报进展" }));
    const detail = within(screen.getByRole("dialog"));
    expect(detail.getByRole("heading", { name: "汇报进展" })).toBeTruthy();
    expect(detail.getByRole("button", { name: "询问这项工作" })).toBeTruthy();
    expect(document.activeElement).toBe(
      detail.getByLabelText("说说进展或需要的支持"),
    );
    expect(mocks.post).not.toHaveBeenCalled();
    expect(
      mocks.get.mock.calls.some(([path]) => path.startsWith("/api/v1/watch/")),
    ).toBe(false);
  });
  it("未登录显示真实开发验证路径，不预置演示身份", async () => {
    mocks.get.mockImplementation(async (path: string) =>
      path === "/api/v1/runtime"
        ? { data: { auth_mode: "mock" } }
        : { response: { status: 401 } },
    );
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

it("AI 草稿复用编辑确认表单，生成完成不会自动写入", async () => {
  const user = userEvent.setup();
  const aiDraft = { ...draft, provider: "bailian" };
  const ready = {
    id: "run1",
    task: "update_draft",
    state: "ready",
    version: 1,
    step_count: 0,
    max_steps: 6,
    steps: [],
    answer: null,
    draft: null,
    question: draft.raw_text,
  };
  mocks.get.mockImplementation(async (path: string) =>
    path === "/api/v1/agent/runs" ? { data: [] } : page([]),
  );
  mocks.post
    .mockResolvedValueOnce({ data: ready })
    .mockResolvedValueOnce({
      data: {
        ...ready,
        state: "completed",
        version: 3,
        step_count: 1,
        draft: aiDraft,
      },
    })
    .mockResolvedValueOnce({ data: { id: "event1" } });
  render(
    <WorkDetail
      work={work}
      organizationId="o1"
      members={[member]}
      timezone="Asia/Shanghai"
      onUpdated={async () => {}}
    />,
  );
  expect(
    screen.getByRole("button", { name: "AI 整理" }).closest("details")?.open,
  ).toBe(false);
  await user.click(screen.getByText("按原话记录 · 非 AI"));
  await user.click(screen.getByRole("button", { name: "AI 整理" }));
  expect(mocks.post).not.toHaveBeenCalled();
  await user.type(
    screen.getByLabelText("说说进展或需要的支持"),
    draft.raw_text,
  );
  await user.click(screen.getByRole("button", { name: "AI 整理草稿" }));
  await screen.findByText("AI 草稿 · 待本人确认");
  expect(mocks.post.mock.calls.map((call) => call[0])).toEqual([
    "/api/v1/agent/runs",
    "/api/v1/agent/runs/{run_id}/advance",
  ]);
  expect(mocks.post.mock.calls[0][1].body.task).toBe("update_draft");
  await user.click(screen.getByRole("button", { name: "确认并保存" }));
  await screen.findByText("已确认，业务记录已保存。");
  expect(mocks.post.mock.calls[2][0]).toBe(
    "/api/v1/work-updates/drafts/{draft_id}/confirm",
  );
});

it.each([false, true])(
  "刷新恢复后台查询并保留追问范围（事项=%s），读取不会重发",
  async (specificWork) => {
    mockOwnerWorkspace();
    const base = mocks.get.getMockImplementation()!;
    const complete = {
      ...completedQuery(),
      work_item_id: specificWork ? work.id : null,
      execution: { state: "stopped", updated_at: work.updated_at },
    };
    mocks.get.mockImplementation(async (path: string, options) => {
      if (path === "/api/v1/agent/runs/active")
        return {
          data: [
            {
              ...complete,
              state: "ready",
              answer: null,
              execution: { state: "queued", updated_at: work.updated_at },
            },
          ],
        };
      if (path === "/api/v1/agent/runs/{run_id}") return { data: complete };
      return base(path, options);
    });
    mocks.post.mockResolvedValue({ data: { ...complete, id: "follow-up" } });
    const user = userEvent.setup();
    render(<Workspace />);
    await screen.findByRole("button", {
      name: /展开 coRoof 处理结果：处理完成/,
    });
    expect(mocks.post).not.toHaveBeenCalled();
    await user.type(
      screen.getByLabelText("告诉 coRoof 你想做什么"),
      "再说详细一点",
    );
    await user.click(screen.getByRole("button", { name: "发送指令" }));
    await waitFor(() => expect(mocks.post).toHaveBeenCalledOnce());
    expect(mocks.post.mock.calls[0][1].body.work_item_id).toBe(
      specificWork ? work.id : undefined,
    );
    expect(mocks.post.mock.calls[0][1].body.parent_run_id).toBe(
      specificWork ? undefined : complete.id,
    );
  },
);
