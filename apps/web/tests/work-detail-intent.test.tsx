import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { WorkDetail } from "../components/work-detail";
import { Drawer } from "../components/drawer";
import type { Draft, Evidence, Member, Work } from "../lib/api";

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
  title: "资料交付",
  department_id: "delivery",
  initiative_id: null,
  owner_id: "me",
  due_at: null,
  lifecycle_status: "in_progress",
  needs_support: false,
  source_authority: "native",
  updated_at: "2026-11-05T02:00:00Z",
  version: 2,
};
const member: Member = {
  id: "me",
  organization_id: "org",
  user_id: "user",
  name: "本人",
  department_id: "delivery",
  roles: ["member"],
  status: "active",
};
const draft: Draft = {
  id: "draft",
  organization_id: "org",
  work_item_id: work.id,
  actor_id: member.id,
  raw_text: "资料未到，需要同事协助核实",
  proposed_fields: {
    summary: "资料未到，需要同事协助核实",
    lifecycle_status: null,
    needs_support: true,
  },
  state: "pending",
  revision: 1,
  base_version: 2,
  provider: "rules",
  created_at: work.updated_at,
  expires_at: "2026-11-06T02:00:00Z",
};
const base = {
  work,
  organizationId: "org",
  members: [member],
  timezone: "Asia/Shanghai",
  onUpdated: vi.fn(async () => {}),
};
beforeEach(() => {
  vi.resetAllMocks();
  mocks.get.mockImplementation(async (path: string) => ({
    data: path.endsWith("/source")
      ? null
      : { items: [], total: 0, offset: 0, limit: 20 },
  }));
});

describe("员工汇报入口", () => {
  it("distinguishes an inaccessible assigned owner from an unassigned work item", async () => {
    const view = render(
      <WorkDetail
        {...base}
        members={[
          { ...member, organization_id: "other", name: "另一企业成员" },
        ]}
      />,
    );
    expect(screen.getByText("负责人信息不可见")).toBeTruthy();
    expect(screen.queryByText("未分配")).toBeNull();
    expect(screen.queryByText("另一企业成员")).toBeNull();
    view.rerender(<WorkDetail {...base} members={[]} />);
    expect(screen.getByText("负责人信息不可见")).toBeTruthy();
    view.rerender(
      <WorkDetail {...base} work={{ ...work, owner_id: null }} members={[]} />,
    );
    expect(screen.getByText("未分配")).toBeTruthy();
    expect(screen.queryByText("负责人信息不可见")).toBeNull();
    await waitFor(() => expect(mocks.get).toHaveBeenCalled());
    expect(mocks.post).not.toHaveBeenCalled();
  });

  it("does not present an external support field as a confirmed native request", async () => {
    const view = render(
      <WorkDetail
        {...base}
        work={{ ...work, needs_support: true }}
        initialIntent="update"
      />,
    );
    expect(screen.getByText("需要支持", { exact: true })).toBeTruthy();
    view.rerender(
      <WorkDetail
        {...base}
        work={{ ...work, source_authority: "external", needs_support: true }}
        initialIntent="update"
      />,
    );
    expect(screen.queryByText("需要支持", { exact: true })).toBeNull();
    expect(screen.getByText("进行中", { exact: true })).toBeTruthy();
    expect(screen.getByText("未同步 · 未知")).toBeTruthy();
    expect(
      screen.getByText("此事项由外部源维护，截止日期与支持需求未知。"),
    ).toBeTruthy();
    await waitFor(() => expect(mocks.get).toHaveBeenCalled());
    expect(mocks.post).not.toHaveBeenCalled();
  });

  it.each(["update", "support"] as const)(
    "opens %s in an empty focused draft editor without writing or invoking AI",
    async (initialIntent) => {
      render(<WorkDetail {...base} initialIntent={initialIntent} />);
      const input = screen.getByLabelText(
        "说说进展或需要的支持",
      ) as HTMLTextAreaElement;
      await waitFor(() => expect(document.activeElement).toBe(input));
      expect(input.value).toBe("");
      expect(screen.queryByRole("button", { name: "有进展" })).toBeNull();
      expect(screen.queryByRole("button", { name: "需要支持" })).toBeNull();
      expect(
        screen.getByText(
          "先写下实际情况，生成草稿后核对并确认；现在还不会更新工作。",
        ),
      ).toBeTruthy();
      expect(mocks.post).not.toHaveBeenCalled();
    },
  );

  it("历史事实默认折叠，展开仍能读全信息、原文和证据标识且不触发写入", async () => {
    const user = userEvent.setup();
    const events: Evidence[] = Array.from({ length: 8 }, (_, index) => ({
      id: `event-${index}`,
      organization_id: work.organization_id,
      work_item_id: work.id,
      actor_id: member.id,
      draft_id: `draft-${index}`,
      event_type: "work.updated",
      event_payload: {
        confirmed: { summary: `已确认的进展 ${index + 1}` },
        raw_text: `原始说明 ${index + 1}`,
      },
      occurred_at: work.updated_at,
      recorded_at: work.updated_at,
      source_ref: `draft:source-${index}`,
    }));
    mocks.get.mockImplementation(async (path: string) => ({
      data: path.endsWith("/arrangements")
        ? { items: [], total: 0, offset: 0, limit: 100 }
        : { items: events, total: events.length, offset: 0, limit: 20 },
    }));
    const view = render(<WorkDetail {...base} initialIntent="update" />);
    const summary = await screen.findByText("事实与来源（8）");
    const history = summary.closest("details")!;
    expect(history.open).toBe(false);
    expect(screen.getByText("已确认的进展 8").closest("details")).toBe(history);
    expect(
      screen.getByText("按原话记录 · 非 AI").closest("details")?.open,
    ).toBe(false);
    expect(
      screen.getByRole("button", { name: "AI 整理" }).closest("details")?.open,
    ).toBe(false);
    expect(
      (
        screen.getByRole("button", {
          name: "整理这段进展",
        }) as HTMLButtonElement
      ).disabled,
    ).toBe(true);
    await user.click(summary);
    expect(history.open).toBe(true);
    expect(screen.getByText("原文：原始说明 8")).toBeTruthy();
    const identifier = screen.getAllByText("查看证据标识")[7];
    expect(identifier.closest("details")?.open).toBe(false);
    await user.click(identifier);
    expect(identifier.closest("details")?.open).toBe(true);
    expect(screen.getByText("event-7")).toBeTruthy();
    expect(screen.getByText("draft:source-7")).toBeTruthy();
    expect(mocks.post).not.toHaveBeenCalled();
    expect(
      mocks.get.mock.calls.filter(([path]) => path.endsWith("/events")),
    ).toHaveLength(1);
    view.rerender(
      <WorkDetail
        {...base}
        work={{ ...work, id: "other-work" }}
        initialIntent="update"
      />,
    );
    expect(screen.getByText("事实与来源（8）").closest("details")?.open).toBe(
      false,
    );
  });

  it("focuses the editor after the native dialog assigns its opening focus", async () => {
    const showModal = vi
      .spyOn(HTMLDialogElement.prototype, "showModal")
      .mockImplementation(function (this: HTMLDialogElement) {
        this.setAttribute("open", "");
        this.querySelector<HTMLButtonElement>("button")?.focus();
      });
    try {
      render(
        <Drawer title={work.title} close={vi.fn()}>
          <WorkDetail {...base} initialIntent="update" />
        </Drawer>,
      );
      await waitFor(() =>
        expect(document.activeElement).toBe(
          screen.getByLabelText("说说进展或需要的支持"),
        ),
      );
      expect(mocks.post).not.toHaveBeenCalled();
    } finally {
      showModal.mockRestore();
    }
  });

  it("creates only a draft first and records the support update only after explicit confirmation", async () => {
    const user = userEvent.setup();
    mocks.post.mockImplementation(async (path: string) => ({
      data: path === "/api/v1/work-updates/drafts" ? draft : {},
    }));
    render(<WorkDetail {...base} initialIntent="support" />);
    await user.type(
      screen.getByLabelText("说说进展或需要的支持"),
      draft.raw_text,
    );
    await user.click(screen.getByRole("button", { name: "整理支持需求" }));
    await screen.findByRole("button", { name: "确认并保存" });
    expect(mocks.post).toHaveBeenCalledExactlyOnceWith(
      "/api/v1/work-updates/drafts",
      expect.objectContaining({
        body: { work_item_id: work.id, raw_text: draft.raw_text },
      }),
    );
    expect(base.onUpdated).not.toHaveBeenCalled();
    await user.click(screen.getByRole("button", { name: "确认并保存" }));
    await screen.findByText("已确认，业务记录已保存。");
    expect(mocks.post.mock.calls.map((call) => call[0])).toEqual([
      "/api/v1/work-updates/drafts",
      "/api/v1/work-updates/drafts/{draft_id}/confirm",
    ]);
    expect(mocks.post.mock.calls[1][1].body).toEqual({ expected_revision: 1 });
    expect(base.onUpdated).toHaveBeenCalledOnce();
  });

  it.each([
    { lifecycle_status: "done" as const },
    { source_authority: "external" as const },
  ])(
    "keeps terminal or external work read-only despite an editing intent",
    async (changes) => {
      render(
        <WorkDetail
          {...base}
          work={{ ...work, ...changes }}
          initialIntent="support"
        />,
      );
      await waitFor(() => expect(mocks.get).toHaveBeenCalled());
      expect(screen.queryByLabelText("说说进展或需要的支持")).toBeNull();
      expect(screen.queryByRole("button", { name: "整理支持需求" })).toBeNull();
      expect(mocks.post).not.toHaveBeenCalled();
    },
  );
});
