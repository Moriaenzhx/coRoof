import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import type { Dashboard } from "../lib/api";
import { Panorama } from "../components/panorama";

const data: Dashboard = {
  organization: {
    id: "o1",
    name: "模拟企业",
    timezone: "Asia/Shanghai",
    created_at: "2026-11-04T08:00:00Z",
  },
  departments: [
    {
      department: { id: "delivery", organization_id: "o1", name: "交付" },
      member_count: 3,
      work_count: 4,
      active_count: 3,
      support_count: 1,
      coverage: "recorded",
      updated_at: "2026-11-04T08:00:00Z",
    },
    {
      department: { id: "finance", organization_id: "o1", name: "财务" },
      member_count: 0,
      work_count: 0,
      active_count: 0,
      support_count: 0,
      coverage: "unknown",
      updated_at: null,
    },
  ],
  total_work: 4,
  active_work: 3,
  completed_work: 1,
  support_work: 1,
  member_count: 3,
  unscoped_members: 0,
  last_updated_at: "2026-11-04T08:00:00Z",
  generated_at: "2026-11-04T08:00:00Z",
  scope: "organization",
  source: "native",
  external_data: "not_connected",
  analysis_mode: "rules",
};

describe("有依据的动态企业全景", () => {
  it("指向部门预览实际工作数量，移开后恢复企业概览", async () => {
    const user = userEvent.setup();
    const onDepartment = vi.fn();
    render(
      <Panorama data={data} onDepartment={onDepartment} onSupport={vi.fn()} />,
    );
    const delivery = screen.getByRole("button", { name: /交付/ });
    expect(within(delivery).getByText("11/04 16:00")).toBeTruthy();
    await user.hover(delivery);
    expect(
      within(screen.getByRole("region", { name: "部门预览" })).getByText(
        "3 项进行与待开始",
      ),
    ).toBeTruthy();
    expect(onDepartment).not.toHaveBeenCalled();
    await user.unhover(delivery);
    expect(screen.getByRole("region", { name: "组织记录概览" })).toBeTruthy();
  });

  it("键盘聚焦提供同等预览，Enter 一次进入原部门详情", async () => {
    const user = userEvent.setup();
    const onDepartment = vi.fn();
    render(
      <Panorama data={data} onDepartment={onDepartment} onSupport={vi.fn()} />,
    );
    await user.tab(); // 查看支持需求
    await user.tab(); // 交付
    expect(screen.getByRole("region", { name: "部门预览" })).toBeTruthy();
    await user.keyboard("{Enter}");
    expect(onDepartment).toHaveBeenCalledExactlyOnceWith("delivery");
    await user.tab();
    expect(
      within(screen.getByRole("region", { name: "部门预览" })).getByText(
        "暂无记录 · 状态未知",
      ),
    ).toBeTruthy();
  });

  it("空部门没有活动或健康推断，新的真实快照更新已聚焦预览", async () => {
    const user = userEvent.setup();
    const onDepartment = vi.fn();
    const view = render(
      <Panorama data={data} onDepartment={onDepartment} onSupport={vi.fn()} />,
    );
    const finance = screen.getByRole("button", { name: /财务/ });
    expect(within(finance).getByText("0 人 · 未知 / 无数据")).toBeTruthy();
    expect(within(finance).getByText("等待第一条记录")).toBeTruthy();
    await user.hover(screen.getByRole("button", { name: /交付/ }));
    view.rerender(
      <Panorama
        data={{
          ...data,
          departments: data.departments.map((d) =>
            d.department.id === "delivery"
              ? { ...d, active_count: 2, updated_at: "2026-11-04T09:30:00Z" }
              : d,
          ),
        }}
        onDepartment={onDepartment}
        onSupport={vi.fn()}
      />,
    );
    expect(
      within(screen.getByRole("region", { name: "部门预览" })).getByText(
        "2 项进行与待开始",
      ),
    ).toBeTruthy();
    expect(
      within(screen.getByRole("button", { name: /交付/ })).getByText(
        "11/04 17:30",
      ),
    ).toBeTruthy();
    expect(screen.queryByText(/运行正常|在线|已自动处理/)).toBeNull();
  });

  it("部门撤出授权范围后清除预览，多部门仍可逐个进入", async () => {
    const user = userEvent.setup();
    const onDepartment = vi.fn();
    const view = render(
      <Panorama data={data} onDepartment={onDepartment} onSupport={vi.fn()} />,
    );
    await user.tab();
    await user.tab();
    const departments = Array.from({ length: 8 }, (_, index) => ({
      ...data.departments[1],
      department: {
        id: `d${index}`,
        organization_id: "o1",
        name: `部门${index}`,
      },
    }));
    view.rerender(
      <Panorama
        data={{ ...data, departments }}
        onDepartment={onDepartment}
        onSupport={vi.fn()}
      />,
    );
    expect(screen.queryByRole("region", { name: "部门预览" })).toBeNull();
    await user.hover(screen.getByRole("button", { name: /部门7/ }));
    expect(
      within(screen.getByRole("region", { name: "部门预览" })).getByText(
        "部门7",
      ),
    ).toBeTruthy();
    await user.click(screen.getByRole("button", { name: /部门7/ }));
    expect(onDepartment).toHaveBeenCalledExactlyOnceWith("d7");
  });
});
