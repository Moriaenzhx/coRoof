import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { Projects } from "../components/projects";
import { DecisionQueue } from "../components/decision-queue";
import type { Department, Initiative, Member, Work } from "../lib/api";

vi.mock("../components/decision-queue", () => ({
  DecisionQueue: vi.fn(
    ({
      organizationId,
      initiativeId,
      revision,
      onOpen,
    }: React.ComponentProps<typeof DecisionQueue>) => (
      <section
        aria-label={`决策记录 ${organizationId}/${initiativeId}`}
        data-revision={revision}
      >
        <button onClick={() => onOpen(`decision-${initiativeId}`)}>
          打开项目决策 {initiativeId}
        </button>
      </section>
    ),
  ),
}));
beforeEach(() => {
  vi.clearAllMocks();
});

const departments: Department[] = [
  { id: "dev", organization_id: "org", name: "研发" },
  { id: "delivery", organization_id: "org", name: "交付" },
];
const members: Member[] = [
  {
    id: "alice",
    organization_id: "org",
    user_id: "user-alice",
    name: "同事甲",
    department_id: "delivery",
    roles: ["member"],
    status: "active",
  },
];
const project: Initiative = {
  id: "project",
  organization_id: "org",
  title: "青禾交付",
  goal: "完成验收资料核对",
  owner_id: "hidden-owner",
  department_id: null,
  due_at: null,
  status: "in_progress",
};
function work(id: string, fields: Partial<Work> = {}): Work {
  return {
    id,
    organization_id: "org",
    title: id,
    department_id: "dev",
    initiative_id: project.id,
    owner_id: null,
    due_at: null,
    lifecycle_status: "planned",
    needs_support: false,
    source_authority: "native",
    version: 1,
    updated_at: "2026-11-04T08:00:00Z",
    ...fields,
  };
}
const works = [
  work("待核实范围"),
  work("验收资料", {
    lifecycle_status: "in_progress",
    owner_id: "alice",
    department_id: "delivery",
    needs_support: true,
    due_at: "2026-11-06T08:00:00Z",
  }),
  work("已完成纪要", {
    lifecycle_status: "done",
    department_id: "delivery",
    owner_id: "hidden-colleague",
  }),
  work("已取消脚本", { lifecycle_status: "cancelled", needs_support: true }),
  work("独立需求", { initiative_id: null }),
];
function mount(overrides: Partial<React.ComponentProps<typeof Projects>> = {}) {
  const onWork = vi.fn();
  const onAsk = vi.fn();
  render(
    <Projects
      initiatives={[
        project,
        {
          ...project,
          id: "empty",
          title: "待核实项目",
          owner_id: null,
          goal: null,
        },
      ]}
      works={works}
      members={members}
      departments={departments}
      timezone="Asia/Shanghai"
      onWork={onWork}
      onAsk={onAsk}
      {...overrides}
    />,
  );
  return { onWork, onAsk };
}

describe("项目明细", () => {
  it("老板按需展开项目决策，并将当前项目、组织与刷新版本交给队列", async () => {
    const user = userEvent.setup();
    const onDecision = vi.fn();
    mount({
      organizationId: "org",
      canDecide: true,
      revision: "snapshot-2",
      onDecision,
    });
    const first = within(screen.getByRole("article", { name: "青禾交付" }));
    const empty = within(screen.getByRole("article", { name: "待核实项目" }));
    expect(DecisionQueue).not.toHaveBeenCalled();
    expect(
      empty.queryByRole("button", { name: "查看项目决策记录" }),
    ).toBeNull();
    await user.click(first.getByRole("button", { name: "查看项目决策记录" }));
    expect(DecisionQueue).toHaveBeenLastCalledWith(
      expect.objectContaining({
        organizationId: "org",
        initiativeId: "project",
        scope: "project",
        revision: "snapshot-2",
        timezone: "Asia/Shanghai",
      }),
      undefined,
    );
    await user.click(
      first.getByRole("button", { name: "打开项目决策 project" }),
    );
    expect(onDecision).toHaveBeenCalledWith("decision-project");
    await user.click(first.getByRole("button", { name: "收起项目决策记录" }));
    expect(first.queryByRole("region", { name: /决策记录/ })).toBeNull();
    await user.click(
      empty.getByRole("button", { name: "展开待核实项目的事项" }),
    );
    expect(empty.queryByRole("region", { name: /决策记录/ })).toBeNull();
    await user.click(empty.getByRole("button", { name: "查看项目决策记录" }));
    expect(
      empty.getByRole("region", { name: "决策记录 org/empty" }),
    ).toBeTruthy();
    expect(DecisionQueue).toHaveBeenLastCalledWith(
      expect.objectContaining({ initiativeId: "empty", scope: "project" }),
      undefined,
    );
  });

  it("收起项目或移除老板权限即卸载决策记录，重新进入需再次明确展开", async () => {
    const user = userEvent.setup();
    const props = {
      initiatives: [project],
      works,
      members,
      departments,
      timezone: "Asia/Shanghai",
      onWork: vi.fn(),
      organizationId: "org",
      canDecide: true,
      revision: "one",
      onDecision: vi.fn(),
    };
    const view = render(<Projects {...props} />);
    await user.click(screen.getByRole("button", { name: "查看项目决策记录" }));
    view.rerender(<Projects {...props} revision="two" />);
    expect(
      screen
        .getByRole("region", { name: "决策记录 org/project" })
        .getAttribute("data-revision"),
    ).toBe("two");
    await user.click(
      screen.getByRole("button", { name: "收起青禾交付的事项" }),
    );
    expect(screen.queryByRole("region", { name: /决策记录/ })).toBeNull();
    await user.click(
      screen.getByRole("button", { name: "展开青禾交付的事项" }),
    );
    expect(screen.queryByRole("region", { name: /决策记录/ })).toBeNull();
    await user.click(screen.getByRole("button", { name: "查看项目决策记录" }));
    view.rerender(<Projects {...props} canDecide={false} />);
    expect(screen.queryByRole("region", { name: /决策记录/ })).toBeNull();
    expect(screen.queryByRole("button", { name: /项目决策记录/ })).toBeNull();
    view.rerender(<Projects {...props} />);
    expect(screen.queryByRole("region", { name: /决策记录/ })).toBeNull();
  });

  it("切换组织不沿用旧项目的决策展开状态", async () => {
    const user = userEvent.setup();
    const props = {
      initiatives: [project],
      works,
      members,
      departments,
      timezone: "Asia/Shanghai",
      onWork: vi.fn(),
      organizationId: "org",
      canDecide: true,
      onDecision: vi.fn(),
    };
    const view = render(<Projects {...props} />);
    await user.click(screen.getByRole("button", { name: "查看项目决策记录" }));
    view.rerender(
      <Projects
        {...props}
        organizationId="other"
        initiatives={[{ ...project, organization_id: "other" }]}
        works={[]}
      />,
    );
    expect(screen.queryByRole("region", { name: /决策记录/ })).toBeNull();
    await user.click(screen.getByRole("button", { name: "查看项目决策记录" }));
    expect(
      screen.getByRole("region", { name: "决策记录 other/project" }),
    ).toBeTruthy();
  });

  it.each([
    { canDecide: false },
    { canDecide: undefined },
    { organizationId: undefined },
    { organizationId: "other" },
    { onDecision: undefined },
  ])("缺少 Owner 权限或匹配上下文时不挂载决策队列：%j", (override) => {
    mount({
      organizationId: "org",
      canDecide: true,
      onDecision: vi.fn(),
      ...override,
    });
    expect(screen.queryByRole("button", { name: /项目决策记录/ })).toBeNull();
    expect(DecisionQueue).not.toHaveBeenCalled();
  });

  it("从首页选中的项目排在首位并展开，刷新数据不重置用户手动收起状态", async () => {
    const user = userEvent.setup();
    const second = { ...project, id: "second", title: "选中的项目" };
    const props = {
      initiatives: [project, second],
      works: [work("目标事项", { initiative_id: "second" })],
      members,
      departments,
      timezone: "Asia/Shanghai",
      onWork: vi.fn(),
      initialProjectId: "second",
    };
    const view = render(<Projects {...props} />);
    expect(screen.getAllByRole("article")[0].getAttribute("aria-label")).toBe(
      "选中的项目",
    );
    expect(screen.getByText("目标事项")).toBeTruthy();
    expect(screen.queryByLabelText("青禾交付的事项筛选")).toBeNull();
    await user.click(
      screen.getByRole("button", { name: "收起选中的项目的事项" }),
    );
    view.rerender(<Projects {...props} works={[...props.works]} />);
    expect(screen.queryByText("目标事项")).toBeNull();
    view.rerender(<Projects {...props} initialProjectId="project" />);
    expect(screen.getAllByRole("article")[0].getAttribute("aria-label")).toBe(
      "青禾交付",
    );
    expect(screen.getByLabelText("青禾交付的事项筛选")).toBeTruthy();
  });

  it("按已授权事项展示真实状态分布，不把任务数量或空项目当作整体进度", () => {
    mount();
    const card = within(screen.getByRole("article", { name: "青禾交付" }));
    expect(
      card.getByRole("img", {
        name: "事项状态分布：已完成 1 项，进行中 1 项，未开始 1 项，已取消 1 项",
      }),
    ).toBeTruthy();
    expect(card.getByText("1 项需要支持")).toBeTruthy();
    expect(card.getByText("项目未设截止时间")).toBeTruthy();
    expect(card.getAllByText("负责人信息不可见").length).toBeGreaterThan(0);
    expect(card.getByText("研发 · 交付")).toBeTruthy();
    expect(
      card.getByText(/事项负责人：同事甲.*部分人员信息不可见.*有事项尚未分配/),
    ).toBeTruthy();
    expect(
      screen.getByText("当前权限内暂无事项记录，项目执行情况未知。"),
    ).toBeTruthy();
    expect(
      screen.getByText("仅汇总当前获授权的事项 · 状态分布不代表项目整体完成度"),
    ).toBeTruthy();
    expect(screen.queryByRole("progressbar")).toBeNull();
    expect(card.queryByText("独立需求")).toBeNull();
    expect(screen.getByRole("region", { name: "独立事项" })).toBeTruthy();
  });

  it("筛选支持/完成事项，并将真实事项 ID 交给详情及询问入口", async () => {
    const user = userEvent.setup();
    const { onWork, onAsk } = mount();
    await user.selectOptions(
      screen.getByLabelText("青禾交付的事项筛选"),
      "support",
    );
    const card = within(screen.getByRole("article", { name: "青禾交付" }));
    expect(card.queryByText("已取消脚本")).toBeNull();
    expect(card.queryByText("待核实范围")).toBeNull();
    await user.click(card.getByRole("button", { name: /^验收资料/ }));
    expect(onWork).toHaveBeenCalledWith("验收资料");
    await user.click(card.getByRole("button", { name: "询问 验收资料" }));
    expect(onAsk).toHaveBeenCalledWith("验收资料");
    await user.selectOptions(card.getByLabelText("青禾交付的事项筛选"), "done");
    expect(card.getByText("已完成纪要")).toBeTruthy();
    expect(card.queryByText("验收资料")).toBeNull();
  });

  it("支持项目筛选排除空项目，搜索无结果可恢复；独立事项保持可访问", async () => {
    const user = userEvent.setup();
    mount();
    await user.click(
      screen.getByRole("button", { name: "只看需要支持的项目" }),
    );
    expect(screen.queryByRole("article", { name: "待核实项目" })).toBeNull();
    expect(screen.getByRole("article", { name: "青禾交付" })).toBeTruthy();
    await user.type(
      screen.getByRole("searchbox", { name: "查找项目" }),
      "不存在的项目",
    );
    expect(screen.queryByRole("article", { name: "青禾交付" })).toBeNull();
    expect(screen.getByText("没有符合筛选的项目")).toBeTruthy();
    expect(screen.getByText("独立需求")).toBeTruthy();
    await user.click(screen.getByRole("button", { name: "清除筛选" }));
    expect(screen.getByRole("article", { name: "待核实项目" })).toBeTruthy();
  });

  it("展开收起可操作，并随工作状态刷新统计而不丢失当前筛选", async () => {
    const user = userEvent.setup();
    const props = {
      initiatives: [project],
      works,
      members,
      departments,
      timezone: "Asia/Shanghai",
      onWork: vi.fn(),
    };
    const { rerender } = render(<Projects {...props} />);
    await user.click(
      screen.getByRole("button", { name: "收起青禾交付的事项" }),
    );
    expect(screen.queryByLabelText("青禾交付的事项筛选")).toBeNull();
    await user.click(
      screen.getByRole("button", { name: "展开青禾交付的事项" }),
    );
    await user.selectOptions(
      screen.getByLabelText("青禾交付的事项筛选"),
      "support",
    );
    rerender(
      <Projects
        {...props}
        works={works.map((w) =>
          w.id === "验收资料"
            ? { ...w, lifecycle_status: "done", needs_support: false }
            : w,
        )}
      />,
    );
    expect(screen.getByText("当前筛选下没有事项。")).toBeTruthy();
    expect(screen.queryByText("1 项需要支持")).toBeNull();
    expect(
      screen.getByRole("img", {
        name: "事项状态分布：已完成 2 项，进行中 0 项，未开始 1 项，已取消 1 项",
      }),
    ).toBeTruthy();
  });

  it("未能取得项目元数据的授权事项仍可打开，不能假设它没有项目", () => {
    mount({
      initiatives: [],
      works: [work("可见事项", { initiative_id: "unseen-project" })],
    });
    const other = within(
      screen.getByRole("region", { name: "其他已授权事项" }),
    );
    expect(other.getByText("可见事项")).toBeTruthy();
    expect(
      other.getByText("这些事项已获授权，关联项目的信息当前不可见。"),
    ).toBeTruthy();
    expect(screen.queryByRole("region", { name: "独立事项" })).toBeNull();
  });
  it("外部记录即使携带支持标记也不呈现为已确认支持需求，生命周期仍按同步事实显示", async () => {
    const user = userEvent.setup();
    mount({
      initiatives: [project],
      works: [
        work("外部记录", {
          source_authority: "external",
          needs_support: true,
          lifecycle_status: "in_progress",
        }),
      ],
    });
    expect(screen.getByRole("img", { name: /进行中 1 项/ })).toBeTruthy();
    expect(screen.queryByText("1 项需要支持")).toBeNull();
    await user.click(
      screen.getByRole("button", { name: "只看需要支持的项目" }),
    );
    expect(screen.queryByRole("article", { name: "青禾交付" })).toBeNull();
    expect(screen.getByText("没有符合筛选的项目")).toBeTruthy();
  });
});
