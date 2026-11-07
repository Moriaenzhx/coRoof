import { act, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { MyWork } from "../components/my-work";
import { WorkDetail } from "../components/work-detail";
import {
  ArrangementList,
  useArrangements,
} from "../components/work-arrangements";
import type { Schemas, Work } from "../lib/api";

const mocks = vi.hoisted(() => ({
  get: vi.fn(),
  post: vi.fn(),
  patch: vi.fn(),
}));
vi.mock("../lib/api", async (original) => ({
  ...(await original<object>()),
  api: () => ({ GET: mocks.get, POST: mocks.post, PATCH: mocks.patch }),
}));
const work: Work = {
  id: "work",
  organization_id: "org",
  title: "核对客户资料",
  department_id: "department",
  owner_id: "member",
  lifecycle_status: "in_progress",
  needs_support: true,
  source_authority: "native",
  updated_at: "2026-11-05T02:00:00Z",
  version: 2,
};
const arrangement: Schemas["WorkArrangementOut"] = {
  id: "decision",
  work_item_id: "work",
  selected_plan: "先核实客户签字页，再协调缺失资料",
  follow_up: "核对后反馈缺失清单",
  follow_up_at: null,
  confirmed_at: "2026-11-05T02:00:00Z",
  feedback_count: 0,
  latest_feedback: null,
};
const draft: Schemas["DraftOut"] = {
  id: "draft",
  organization_id: "org",
  work_item_id: "work",
  decision_id: "decision",
  actor_id: "member",
  raw_text: "签字页已收到，仍有附件待补充",
  proposed_fields: {
    summary: "签字页已收到，仍有附件待补充",
    lifecycle_status: null,
    needs_support: null,
  },
  state: "pending",
  base_version: 2,
  revision: 1,
  provider: "manual_feedback",
  created_at: "2026-11-05T03:00:00Z",
  expires_at: "2026-11-06T03:00:00Z",
};
const page = <T,>(items: T[], total = items.length, offset = 0) => ({
  data: { items, total, offset, limit: 100 },
});
const detail = {
  organizationId: "org",
  work,
  members: [],
  timezone: "Asia/Shanghai",
  onUpdated: vi.fn(async () => {}),
};
beforeEach(() => {
  vi.resetAllMocks();
  mocks.get.mockImplementation(async (path: string) =>
    path.endsWith("/arrangements") || path === "/api/v1/work-arrangements"
      ? page([arrangement])
      : page([]),
  );
});

describe("已确认安排与员工反馈", () => {
  it("我的工作显式读取本人安排，点击反馈传递确定的事项和安排，不自动写入", async () => {
    const onWork = vi.fn();
    render(
      <MyWork
        works={[work]}
        members={[]}
        departments={[]}
        initiatives={[]}
        memberId="member"
        organizationId="org"
        revision="1"
        timezone="Asia/Shanghai"
        onWork={onWork}
        onAsk={vi.fn()}
      />,
    );
    await screen.findByText(arrangement.selected_plan);
    expect(mocks.get).toHaveBeenCalledWith(
      "/api/v1/work-arrangements",
      expect.objectContaining({
        params: expect.objectContaining({
          header: { "x-organization-id": "org" },
          query: expect.objectContaining({ mine: true }),
        }),
      }),
    );
    expect(screen.queryByText("context_snapshot")).toBeNull();
    await userEvent.click(screen.getByRole("button", { name: "反馈安排" }));
    expect(onWork).toHaveBeenCalledWith("work", "feedback", "decision");
    expect(mocks.post).not.toHaveBeenCalled();
  });

  it("原文反馈绑定安排，草稿后仍需本人确认且没有状态或AI操作", async () => {
    const user = userEvent.setup();
    mocks.post.mockImplementation(async (path: string) => ({
      data: path.endsWith("/drafts") ? draft : { id: "event" },
    }));
    render(
      <WorkDetail
        {...detail}
        initialIntent="feedback"
        initialDecisionId="decision"
      />,
    );
    await screen.findByText(arrangement.selected_plan);
    const input = screen.getByRole("textbox", { name: "这项安排进展如何" });
    expect((input as HTMLTextAreaElement).value).toBe("");
    expect(screen.queryByRole("button", { name: "AI 整理" })).toBeNull();
    expect(mocks.post).not.toHaveBeenCalled();
    await user.type(input, draft.raw_text);
    await user.click(screen.getByRole("button", { name: "核对这段反馈" }));
    await screen.findByRole("button", { name: "确认并反馈" });
    expect(mocks.post).toHaveBeenCalledExactlyOnceWith(
      "/api/v1/work-updates/drafts",
      expect.objectContaining({
        body: {
          work_item_id: "work",
          decision_id: "decision",
          raw_text: draft.raw_text,
        },
      }),
    );
    expect(detail.onUpdated).not.toHaveBeenCalled();
    expect(screen.queryByLabelText("工作状态")).toBeNull();
    expect(screen.queryByLabelText("支持需求")).toBeNull();
    expect(screen.getByText("原文反馈 · 非 AI")).toBeTruthy();
    await user.click(screen.getByRole("button", { name: "确认并反馈" }));
    await screen.findByText(
      "反馈已记录，事项负责人和获授权管理者可以查看；工作状态保持不变。",
    );
    expect(mocks.post).toHaveBeenLastCalledWith(
      "/api/v1/work-updates/drafts/{draft_id}/confirm",
      expect.objectContaining({
        params: expect.objectContaining({ path: { draft_id: "draft" } }),
        body: { expected_revision: 1 },
      }),
    );
    expect(
      mocks.post.mock.calls.some(
        ([path]) => path.includes("agent") || path.includes("outcomes"),
      ),
    ).toBe(false);
    expect(detail.onUpdated).toHaveBeenCalledOnce();
  });

  it("未找到指定安排时不能把反馈悄悄作为普通更新提交", async () => {
    mocks.get.mockResolvedValue(page([]));
    render(
      <WorkDetail
        {...detail}
        initialIntent="feedback"
        initialDecisionId="missing"
      />,
    );
    await screen.findByText("此安排当前不可见，请重新打开事项核对。");
    await userEvent.type(screen.getByLabelText("这项安排进展如何"), "我的反馈");
    expect(
      (
        screen.getByRole("button", {
          name: "核对这段反馈",
        }) as HTMLButtonElement
      ).disabled,
    ).toBe(true);
    expect(mocks.post).not.toHaveBeenCalled();
  });

  it("安排读取失权清空旧事实，重试恢复；跨企业迟到结果不能回填", async () => {
    let late!: (value: unknown) => void;
    let access = true;
    mocks.get.mockImplementation(
      (
        _: string,
        options: { params: { header: { "x-organization-id": string } } },
      ) => {
        if (options.params.header["x-organization-id"] === "old")
          return new Promise((resolve) => {
            late = resolve;
          });
        return Promise.resolve(
          access
            ? page([arrangement])
            : { error: { error: { message: "已无权查看" } } },
        );
      },
    );
    function List({ org, revision }: { org: string; revision: string }) {
      const data = useArrangements(org, revision, "work");
      return (
        <ArrangementList
          {...data}
          organizationId={org}
          workId="work"
          timezone="Asia/Shanghai"
          onRetry={data.retry}
        />
      );
    }
    const view = render(<List org="old" revision="1" />);
    view.rerender(<List org="org" revision="1" />);
    await screen.findByText(arrangement.selected_plan);
    await act(async () =>
      late(page([{ ...arrangement, selected_plan: "旧企业不能回填" }])),
    );
    expect(screen.queryByText("旧企业不能回填")).toBeNull();
    access = false;
    view.rerender(<List org="org" revision="2" />);
    expect(screen.queryByText(arrangement.selected_plan)).toBeNull();
    await screen.findByText("已无权查看");
    access = true;
    await userEvent.click(screen.getByRole("button", { name: "重新读取安排" }));
    await screen.findByText(arrangement.selected_plan);
    expect(mocks.post).not.toHaveBeenCalled();
  });

  it("多页安排读取完整，成员反馈按需分页并明确不是老板结果", async () => {
    const feedbacks = [0, 1, 2].map((index) => ({
      id: `event-${index}`,
      decision_id: "decision",
      actor_id: "member",
      summary: `实际反馈${index}`,
      recorded_at: arrangement.confirmed_at,
    }));
    const row = {
      ...arrangement,
      feedback_count: 3,
      latest_feedback: feedbacks[0],
    };
    mocks.get.mockImplementation(
      async (
        path: string,
        options: { params: { query: { offset: number } } },
      ) => {
        const offset = options.params.query.offset;
        if (path.endsWith("/feedback"))
          return page(
            offset ? feedbacks.slice(2) : feedbacks.slice(0, 2),
            3,
            offset,
          );
        return offset
          ? page(
              [{ ...row, id: "second", selected_plan: "第二条已确认安排" }],
              2,
              1,
            )
          : page([row], 2);
      },
    );
    function List() {
      const data = useArrangements("org", "1", "work");
      return (
        <ArrangementList
          {...data}
          organizationId="org"
          workId="work"
          timezone="Asia/Shanghai"
          onRetry={data.retry}
        />
      );
    }
    render(<List />);
    await screen.findByText("第二条已确认安排");
    expect(
      mocks.get.mock.calls.some(([path]) => path.endsWith("/feedback")),
    ).toBe(false);
    await userEvent.click(
      screen.getAllByRole("button", { name: "查看成员反馈（3）" })[0],
    );
    await screen.findByText("实际反馈1");
    expect(screen.getAllByText(/成员本人确认，待核实结果/).length).toBe(2);
    await userEvent.click(screen.getByRole("button", { name: "查看更早反馈" }));
    await screen.findByText("实际反馈2");
    await waitFor(() =>
      expect(screen.queryByRole("button", { name: "查看更早反馈" })).toBeNull(),
    );
    expect(mocks.post).not.toHaveBeenCalled();
  });
});
