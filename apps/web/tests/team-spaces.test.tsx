import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { TeamSpaces } from "../components/team-spaces";
import type { Department, Initiative, Member, Work } from "../lib/api";

const departments: Department[] = [
  { id: "dev", organization_id: "org", name: "研发" },
  { id: "sales", organization_id: "org", name: "销售" },
  { id: "finance", organization_id: "org", name: "财务" },
];

function member(id: string, fields: Partial<Member> = {}): Member {
  return {
    id,
    organization_id: "org",
    user_id: `user-${id}`,
    name: id,
    department_id: "dev",
    roles: ["member"],
    status: "active",
    ...fields,
  };
}

const members = [
  member("研发同事甲", { roles: ["manager"] }),
  member("研发同事乙"),
  member("销售同事", { department_id: "sales" }),
  member("企业老板", { department_id: null, roles: ["owner"] }),
];

function work(id: string, fields: Partial<Work> = {}): Work {
  return {
    id,
    organization_id: "org",
    title: id,
    department_id: "dev",
    initiative_id: null,
    owner_id: null,
    due_at: null,
    lifecycle_status: "in_progress",
    needs_support: false,
    source_authority: "native",
    version: 1,
    updated_at: "2026-11-06T08:00:00Z",
    ...fields,
  };
}

const works = [
  work("接口联调", { needs_support: true, initiative_id: "shared-project" }),
  work("准备测试资料", { lifecycle_status: "planned" }),
  work("外部同步事项", { source_authority: "external", needs_support: true }),
  work("已完成复盘", { lifecycle_status: "done", needs_support: true }),
  work("已取消旧需求", { lifecycle_status: "cancelled", needs_support: true }),
  work("销售客户沟通", {
    department_id: "sales",
    needs_support: true,
    initiative_id: "sales-project",
  }),
];

function project(id: string, fields: Partial<Initiative> = {}): Initiative {
  return {
    id,
    organization_id: "org",
    title: id,
    goal: null,
    owner_id: null,
    department_id: null,
    due_at: null,
    status: "in_progress",
    ...fields,
  };
}

const initiatives = [
  project("shared-project", {
    title: "跨团队交付",
    department_id: "sales",
  }),
  project("sales-project", { title: "销售续约", department_id: "sales" }),
  project("unrelated-project", {
    title: "尚无本团队工作关联的项目",
    department_id: "dev",
  }),
];

function props(
  overrides: Partial<React.ComponentProps<typeof TeamSpaces>> = {},
): React.ComponentProps<typeof TeamSpaces> {
  return {
    organizationName: "星桥软件（模拟）",
    departments,
    members,
    works,
    initiatives,
    timezone: "Asia/Shanghai",
    onWork: vi.fn(),
    onMember: vi.fn(),
    onProject: vi.fn(),
    onKnowledge: vi.fn(),
    onOverview: vi.fn(),
    ...overrides,
  };
}

afterEach(() => vi.unstubAllGlobals());

describe("团队工作入口", () => {
  it("目录按当前团队的真实记录计数，结束和外部事项不冒充支持需求", async () => {
    const user = userEvent.setup();
    render(<TeamSpaces {...props()} />);
    const dev = within(screen.getByRole("button", { name: "进入研发团队" }));
    expect(dev.getByText("3 项待推进")).toBeTruthy();
    expect(dev.getByText("2 位成员")).toBeTruthy();
    expect(dev.getByText("1 项工作需要支持")).toBeTruthy();
    expect(dev.getByText("接口联调")).toBeTruthy();
    expect(dev.queryByRole("button")).toBeNull();

    await user.click(screen.getByRole("button", { name: "进入研发团队" }));
    const external = within(
      screen.getByRole("button", { name: /外部同步事项/ }),
    );
    expect(external.getByText("外部记录")).toBeTruthy();
    expect(external.queryByText("需要支持")).toBeNull();
    const finished = screen.getByText("已结束的工作").closest("details");
    expect(finished?.open).toBe(false);
    await user.click(screen.getByText("已结束的工作"));
    expect(finished?.open).toBe(true);
    for (const title of ["已完成复盘", "已取消旧需求"]) {
      expect(
        within(
          screen.getByRole("button", { name: new RegExp(title) }),
        ).queryByText("需要支持"),
      ).toBeNull();
    }
  });

  it("进入后先看本团队的工作，仅显示通过实际工作关联的项目", async () => {
    const user = userEvent.setup();
    render(<TeamSpaces {...props()} />);
    await user.click(screen.getByRole("button", { name: "进入研发团队" }));

    expect(document.activeElement).toBe(
      screen.getByRole("heading", { name: "研发", level: 2 }),
    );
    expect(
      screen.getByRole("button", { name: "工作" }).getAttribute("aria-pressed"),
    ).toBe("true");
    expect(screen.getByRole("button", { name: /接口联调/ })).toBeTruthy();
    expect(screen.queryByRole("button", { name: /销售客户沟通/ })).toBeNull();
    expect(screen.getByRole("button", { name: "跨团队交付" })).toBeTruthy();
    expect(screen.queryByRole("button", { name: "销售续约" })).toBeNull();
    expect(screen.queryByText("尚无本团队工作关联的项目")).toBeNull();
    expect(screen.queryByRole("button", { name: /研发同事甲/ })).toBeNull();
    expect(screen.queryByText("销售同事")).toBeNull();
  });

  it("工作、项目、成员和公共入口使用真实回调，浏览不会自动发起网络或模型请求", async () => {
    const user = userEvent.setup();
    const fetch = vi.fn();
    vi.stubGlobal("fetch", fetch);
    const handlers = props();
    render(<TeamSpaces {...handlers} />);

    await user.click(screen.getByRole("button", { name: "查看概览" }));
    expect(handlers.onOverview).toHaveBeenCalledOnce();
    await user.click(screen.getByRole("button", { name: "进入研发团队" }));
    await user.click(screen.getByRole("button", { name: /接口联调/ }));
    expect(handlers.onWork).toHaveBeenCalledWith("接口联调");
    await user.click(screen.getByRole("button", { name: "跨团队交付" }));
    expect(handlers.onProject).toHaveBeenCalledWith("shared-project");
    await user.click(screen.getByRole("button", { name: "成员" }));
    expect(screen.queryByRole("button", { name: /接口联调/ })).toBeNull();
    expect(screen.queryByText("销售同事")).toBeNull();
    await user.click(screen.getByRole("button", { name: /研发同事甲/ }));
    expect(handlers.onMember).toHaveBeenCalledWith("研发同事甲");
    await user.click(screen.getByRole("button", { name: /企业知识库/ }));
    expect(handlers.onKnowledge).toHaveBeenCalledOnce();
    expect(screen.getByText("查看我有权看的资料")).toBeTruthy();
    await user.click(screen.getByRole("button", { name: "全部团队" }));
    await user.click(screen.getByRole("button", { name: "进入销售团队" }));
    expect(screen.getByRole("button", { name: /销售客户沟通/ })).toBeTruthy();
    expect(
      screen.getByRole("button", { name: "工作" }).getAttribute("aria-pressed"),
    ).toBe("true");
    expect(fetch).not.toHaveBeenCalled();
  });

  it("空团队仍能进入并说明情况未知，只在提供管理权限入口时显示管理操作", async () => {
    const user = userEvent.setup();
    const onManage = vi.fn();
    const options = props({ onManage });
    const view = render(<TeamSpaces {...options} />);
    const finance = within(
      screen.getByRole("button", { name: "进入财务团队" }),
    );
    expect(finance.getByText("尚无工作记录")).toBeTruthy();
    expect(finance.getByText("还不了解这个团队的工作情况")).toBeTruthy();
    await user.click(screen.getByRole("button", { name: "进入财务团队" }));
    expect(screen.getByText("还没有工作记录")).toBeTruthy();
    expect(screen.queryByText(/一切正常|团队健康|运转正常/)).toBeNull();
    await user.click(screen.getByRole("button", { name: "管理团队" }));
    expect(onManage).toHaveBeenCalledOnce();
    await user.click(screen.getByRole("button", { name: "成员" }));
    expect(screen.getByRole("heading", { name: "尚未添加成员" })).toBeTruthy();
    view.rerender(<TeamSpaces {...options} onManage={undefined} />);
    expect(screen.queryByRole("button", { name: "管理团队" })).toBeNull();
  });

  it("未归属团队的成员默认折叠，展开后仍能打开实际成员", async () => {
    const user = userEvent.setup();
    const handlers = props();
    render(<TeamSpaces {...handlers} />);
    const unassigned = screen.getByText("未归属团队的成员").closest("details");
    expect(unassigned?.open).toBe(false);
    expect(
      screen.queryByRole("button", { name: "进入企业管理团队" }),
    ).toBeNull();
    await user.click(screen.getByText("未归属团队的成员"));
    expect(unassigned?.open).toBe(true);
    await user.click(screen.getByRole("button", { name: /企业老板/ }));
    expect(handlers.onMember).toHaveBeenCalledWith("企业老板");
    await user.click(screen.getByText("未归属团队的成员"));
    expect(unassigned?.open).toBe(false);
  });

  it("可见团队撤权后立即离开旧团队，重新获得可见性也不恢复旧详情", async () => {
    const user = userEvent.setup();
    const options = props();
    const view = render(<TeamSpaces {...options} />);
    await user.click(screen.getByRole("button", { name: "进入研发团队" }));
    await user.click(screen.getByRole("button", { name: "成员" }));
    expect(screen.getByRole("button", { name: /研发同事甲/ })).toBeTruthy();
    view.rerender(
      <TeamSpaces
        {...options}
        departments={[departments[1]]}
        members={members.filter((person) => person.department_id === "sales")}
        works={works.filter((item) => item.department_id === "sales")}
      />,
    );
    expect(screen.queryByRole("region", { name: "研发团队工作台" })).toBeNull();
    expect(screen.queryByText("研发同事甲")).toBeNull();
    expect(screen.queryByText("接口联调")).toBeNull();
    expect(screen.getByRole("button", { name: "进入销售团队" })).toBeTruthy();
    view.rerender(<TeamSpaces {...options} />);
    expect(screen.queryByRole("region", { name: "研发团队工作台" })).toBeNull();
    expect(screen.getByRole("button", { name: "进入研发团队" })).toBeTruthy();
  });

  it("较多团队可搜索，授权缩小隐藏搜索框时不会残留旧筛选而丢失入口", async () => {
    const user = userEvent.setup();
    const extra = ["设计", "交付", "行政"].map((name) => ({
      id: name,
      organization_id: "org",
      name,
    }));
    const options = props({ departments: [...departments, ...extra] });
    const view = render(<TeamSpaces {...options} />);
    await user.type(screen.getByRole("textbox", { name: "查找团队" }), "研发");
    expect(screen.getByRole("button", { name: "进入研发团队" })).toBeTruthy();
    expect(screen.queryByRole("button", { name: "进入财务团队" })).toBeNull();
    view.rerender(<TeamSpaces {...options} departments={[departments[2]]} />);
    expect(screen.queryByRole("textbox", { name: "查找团队" })).toBeNull();
    expect(screen.getByRole("button", { name: "进入财务团队" })).toBeTruthy();
  });
});
