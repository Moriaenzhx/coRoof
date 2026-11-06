import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, expect, it, vi } from "vitest";
import { Companion, CoRoofAvatar } from "../components/companion";
import type { Member, Work } from "../lib/api";

const work: Work = {
  id: "w1",
  organization_id: "o1",
  title: "客户资料确认",
  description: null,
  department_id: "d1",
  initiative_id: null,
  owner_id: "m1",
  due_at: null,
  lifecycle_status: "planned",
  needs_support: false,
  source_authority: "native",
  version: 1,
  updated_at: "2026-11-04T08:00:00Z",
};
const member: Member = {
  id: "m1",
  organization_id: "o1",
  user_id: "u1",
  name: "陆川",
  department_id: "d1",
  roles: ["member"],
  status: "active",
};
const props = {
  members: [member],
  timezone: "Asia/Shanghai",
  onWork: vi.fn(),
  onAsk: vi.fn(),
  now: new Date("2026-11-04T09:00:00Z").getTime(),
};
beforeEach(() => vi.clearAllMocks());

it("keeps missing facts unknown and performs no implicit model or watch action", async () => {
  const watch = vi.fn();
  render(<Companion {...props} works={[]} onWatch={watch} />);
  expect(screen.getByText(/从一条真实进展开始/)).toBeTruthy();
  expect(screen.getByText("按已记录工作整理 · 未调用模型")).toBeTruthy();
  expect(screen.getByText("持续关注按你确认的范围执行")).toBeTruthy();
  expect(screen.queryByText(/运行正常|正在持续扫描|已自动安排/)).toBeNull();
  expect(props.onAsk).not.toHaveBeenCalled();
  expect(watch).not.toHaveBeenCalled();
  await userEvent.click(screen.getByRole("button", { name: /梳理信息缺口/ }));
  expect(props.onAsk).toHaveBeenCalledWith(
    undefined,
    expect.stringContaining("不要假设"),
  );
});

it("grounds support suggestions in active work and opens the exact work or prefilled question", async () => {
  render(
    <Companion
      {...props}
      works={[
        { ...work, needs_support: true },
        {
          ...work,
          id: "done",
          title: "已结束",
          lifecycle_status: "done",
          needs_support: true,
        },
        {
          ...work,
          id: "cancelled",
          title: "已取消",
          lifecycle_status: "cancelled",
          needs_support: true,
        },
      ]}
    />,
  );
  expect(screen.getByText("1 项工作提出支持需求，一起看看。")).toBeTruthy();
  expect(screen.getByText("陆川负责")).toBeTruthy();
  expect(screen.queryByRole("button", { name: "已结束" })).toBeNull();
  await userEvent.click(screen.getByRole("button", { name: "客户资料确认" }));
  expect(props.onWork).toHaveBeenCalledWith("w1");
  await userEvent.click(screen.getByRole("button", { name: /一起梳理下一步/ }));
  expect(props.onAsk).toHaveBeenCalledWith(
    "w1",
    expect.stringContaining("支持需求和协作缺口"),
  );
  expect(props.onAsk.mock.calls[0][1]).toContain("不代替同事确认进展");
});

it("uses explicit due dates and preserves unknown delivery results", () => {
  render(
    <Companion
      {...props}
      works={[{ ...work, due_at: "2026-11-03T08:00:00Z" }]}
    />,
  );
  expect(screen.getByText("1 项工作已过记录中的截止时间。")).toBeTruthy();
  expect(screen.getByText(/实际交付结果仍需核实/)).toBeTruthy();
  expect(screen.getByText(/记录截止 11\/03 16:00/)).toBeTruthy();
});

it("does not infer unassigned work from an inaccessible owner name", () => {
  const { rerender } = render(
    <Companion {...props} members={[]} works={[work]} />,
  );
  expect(screen.getByText("负责人信息未载入")).toBeTruthy();
  expect(screen.queryByText(/项工作还没有明确负责人/)).toBeNull();
  rerender(<Companion {...props} works={[{ ...work, owner_id: null }]} />);
  expect(screen.getByText("1 项工作还没有明确负责人。")).toBeTruthy();
});

it("does not turn external status into confirmed support or overdue claims", () => {
  render(
    <Companion
      {...props}
      works={[
        {
          ...work,
          source_authority: "external",
          needs_support: true,
          due_at: "2026-11-01T00:00:00Z",
        },
      ]}
    />,
  );
  expect(
    screen.getByText(/外部同步记录，实际支持需求与交付情况仍需核实/),
  ).toBeTruthy();
  expect(screen.queryByText(/项工作提出支持需求|项工作已过记录/)).toBeNull();
});

it("exposes actual loading and only reports watch authorization when provided", async () => {
  const watch = vi.fn();
  const { rerender } = render(
    <Companion {...props} works={[work]} loading onWatch={watch} />,
  );
  expect(
    screen
      .getByRole("region", { name: "coRoof 工作伙伴" })
      .getAttribute("aria-busy"),
  ).toBe("true");
  expect(screen.queryByRole("button", { name: /一起梳理下一步/ })).toBeNull();
  expect(
    (screen.getByRole("button", { name: /聊聊工作/ }) as HTMLButtonElement)
      .disabled,
  ).toBe(true);
  rerender(
    <Companion
      {...props}
      works={[work]}
      onWatch={watch}
      watchSummary={{ activeCount: 0, lastCheckedAt: work.updated_at }}
    />,
  );
  expect(screen.getByText("当前没有有效的持续关注授权")).toBeTruthy();
  expect(screen.getByText(/上次核对 11\/04 16:00/)).toBeTruthy();
  await userEvent.click(screen.getByRole("button", { name: /查看持续关注/ }));
  expect(watch).toHaveBeenCalledOnce();
});

it("gives the standalone avatar an accessible truthful state", () => {
  render(<CoRoofAvatar state="attention" />);
  expect(
    screen.getByRole("img", { name: "coRoof 工作伙伴：有待核实事项" }),
  ).toBeTruthy();
});
