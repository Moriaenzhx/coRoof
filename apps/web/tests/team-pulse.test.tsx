import { act, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, it, vi, beforeEach } from "vitest";
import { TeamPulse } from "../components/team-pulse";
import type { Work, Member, Evidence } from "../lib/api";
const { get } = vi.hoisted(() => ({ get: vi.fn() }));
vi.mock("../lib/api", async (original) => ({
  ...(await original<object>()),
  api: () => ({ GET: get }),
}));
const work: Work = {
  id: "work",
  organization_id: "org",
  department_id: "dept",
  title: "确认客户资料",
  description: null,
  initiative_id: null,
  owner_id: "new-owner",
  due_at: null,
  lifecycle_status: "in_progress",
  needs_support: false,
  source_authority: "native",
  version: 2,
  updated_at: "2026-11-04T08:00:00Z",
};
const actor: Member = {
  id: "author",
  organization_id: "org",
  user_id: "user",
  name: "实际记录人",
  department_id: "dept",
  roles: ["member"],
  status: "active",
};
const event: Evidence = {
  id: "event",
  organization_id: "org",
  work_item_id: "work",
  actor_id: "author",
  draft_id: null,
  event_type: "work.updated",
  event_payload: { confirmed: { summary: "已核实资料，仍等待客户回复。" } },
  occurred_at: work.updated_at,
  recorded_at: work.updated_at,
  source_ref: "native",
};
const props = {
  organizationId: "org",
  works: [work],
  members: [actor],
  initiatives: [],
  timezone: "Asia/Shanghai",
  revision: "one",
  onWork: vi.fn(),
};
beforeEach(() => {
  vi.clearAllMocks();
});
it("attributes confirmed activity to its actor, with a path to the actual work", async () => {
  get.mockResolvedValue({ data: { items: [event], total: 1 } });
  const onWork = vi.fn();
  render(<TeamPulse {...props} onWork={onWork} />);
  expect(await screen.findByText("实际记录人")).toBeTruthy();
  expect(screen.getByText("已核实资料，仍等待客户回复。")).toBeTruthy();
  await userEvent.click(screen.getByRole("button", { name: "确认客户资料" }));
  expect(onWork).toHaveBeenCalledWith("work");
});
it("drops previous tenant content immediately and ignores late replies", async () => {
  let resolve: (result: unknown) => void = () => {};
  get.mockReturnValueOnce(
    new Promise((r) => {
      resolve = r;
    }),
  );
  const view = render(<TeamPulse {...props} />);
  view.rerender(
    <TeamPulse {...props} organizationId="other" works={[]} revision="two" />,
  );
  await act(async () => {
    resolve({ data: { items: [event], total: 1 } });
  });
  expect(screen.queryByText("实际记录人")).toBeNull();
  expect(screen.getByText(/暂无可展示的确认记录/)).toBeTruthy();
});
it("does not retain revoked event contents after a failed refresh", async () => {
  get.mockResolvedValueOnce({ data: { items: [event], total: 1 } });
  const view = render(<TeamPulse {...props} />);
  await screen.findByText("实际记录人");
  get.mockRejectedValue(new Error("forbidden"));
  view.rerender(<TeamPulse {...props} revision="two" />);
  expect(screen.queryByText("实际记录人")).toBeNull();
  expect(await screen.findByText(/部分记录暂时不可用/)).toBeTruthy();
});
it("distinguishes inaccessible project metadata from an independent work item", async () => {
  get.mockResolvedValue({ data: { items: [event], total: 1 } });
  const view = render(
    <TeamPulse {...props} works={[{ ...work, initiative_id: "hidden" }]} />,
  );
  expect(await screen.findByText(/项目信息当前不可见/)).toBeTruthy();
  expect(screen.queryByText(/独立事项/)).toBeNull();
  view.rerender(<TeamPulse {...props} />);
  expect(screen.getByText(/独立事项/)).toBeTruthy();
});
it("shows three confirmed entries in compact mode and expands only the already loaded records", async () => {
  const user = userEvent.setup();
  const secondWork = { ...work, id: "second", title: "另一个本人事项" };
  get.mockImplementation(async (_path, options) => {
    const id = options.params.path.work_id;
    return {
      data: {
        items: [1, 2, 3].map((n) => ({
          ...event,
          id: `${id}-${n}`,
          work_item_id: id,
          recorded_at: `2026-11-04T08:0${n}:00Z`,
        })),
        total: 3,
      },
    };
  });
  render(
    <TeamPulse
      {...props}
      works={[work, secondWork]}
      compact
      title="与我相关的动态"
      description="查看本人事项的进展与交接记录。"
    />,
  );
  expect(await screen.findAllByRole("listitem")).toHaveLength(3);
  expect(screen.getByRole("region", { name: "与我相关的动态" })).toBeTruthy();
  expect(screen.getByText("查看本人事项的进展与交接记录。")).toBeTruthy();
  expect(get).toHaveBeenCalledTimes(2);
  const expand = screen.getByRole("button", { name: "展开更多动态（3 条）" });
  expect(expand.getAttribute("aria-expanded")).toBe("false");
  await user.click(expand);
  expect(screen.getAllByRole("listitem")).toHaveLength(6);
  expect(
    screen
      .getByRole("button", { name: "收起动态" })
      .getAttribute("aria-expanded"),
  ).toBe("true");
  expect(get).toHaveBeenCalledTimes(2);
  await user.click(screen.getByRole("button", { name: "收起动态" }));
  expect(screen.getAllByRole("listitem")).toHaveLength(3);
});
it("requests only the supplied current-tenant work scope and rejects unrelated returned events", async () => {
  get.mockResolvedValue({
    data: {
      items: [
        event,
        {
          ...event,
          id: "foreign-event",
          organization_id: "other",
          event_payload: { confirmed: { summary: "不应展示的其他企业记录" } },
        },
      ],
      total: 2,
    },
  });
  render(
    <TeamPulse
      {...props}
      works={[work, { ...work, id: "foreign", organization_id: "other" }]}
      compact
    />,
  );
  expect(await screen.findByText("已核实资料，仍等待客户回复。")).toBeTruthy();
  expect(get).toHaveBeenCalledExactlyOnceWith(
    "/api/v1/work-items/{work_id}/events",
    expect.objectContaining({
      params: expect.objectContaining({
        header: { "x-organization-id": "org" },
        path: { work_id: "work" },
      }),
    }),
  );
  expect(screen.queryByText("不应展示的其他企业记录")).toBeNull();
  expect(screen.getAllByRole("listitem")).toHaveLength(1);
});
