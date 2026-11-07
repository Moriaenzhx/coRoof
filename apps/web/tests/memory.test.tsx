import { act, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, expect, it, vi } from "vitest";
import { MemoryCenter, MemoryDetail } from "../components/memory";
import type { Schemas } from "../lib/api";

const mocks = vi.hoisted(() => ({ get: vi.fn(), post: vi.fn() }));
vi.mock("../lib/api", async (original) => ({
  ...(await original<object>()),
  api: () => ({ GET: mocks.get, POST: mocks.post }),
}));
const time = "2026-11-04T08:00:00Z";
const context = { organizationId: "o1", timezone: "Asia/Shanghai" };
const entry: Schemas["MemoryOut"] = {
  id: "memory1",
  kind: "preference",
  actor_id: "owner1",
  preference_key: "focus",
  title: "交付优先",
  content: "先核实客户交付",
  applicability: "本季度的规划",
  source_quote: "先核实客户交付",
  state: "proposed",
  version: 2,
  source: {
    work_item_id: null,
    decision_id: null,
    outcome_id: null,
    selected_plan: null,
    observed_result: null,
    owner_statement: "先核实客户交付",
    other_outcomes: [],
    outcome_count: 0,
    source_hash: "a".repeat(64),
    source_at: time,
  },
  outdated: false,
  can_edit: true,
  confirmed_at: null,
  created_at: time,
  updated_at: time,
};
const experience: Schemas["MemoryOut"] = {
  ...entry,
  id: "experience1",
  kind: "experience",
  preference_key: null,
  title: "交付复盘",
  content: "提前核对交接材料",
  source: {
    ...entry.source!,
    work_item_id: "work1",
    decision_id: "decision1",
    outcome_id: "outcome1",
    selected_plan: "先补齐交接材料",
    observed_result: "完成交接核对",
    owner_statement: null,
  },
};
let active: Schemas["MemoryOut"];
let rows: Schemas["MemoryOut"][];
beforeEach(() => {
  vi.resetAllMocks();
  active = { ...entry };
  rows = [];
  mocks.get.mockImplementation(async (path: string, options) => {
    if (path === "/api/v1/memory/entries") {
      const items = rows.filter(
        (row) => row.kind === options.params.query.kind,
      );
      return {
        data: { items, total: items.length, offset: 0, limit: 20 },
      };
    }
    if (path === "/api/v1/memory/entries/{identifier}") return { data: active };
    if (path === "/api/v1/decisions")
      return { data: { items: [], total: 0, offset: 0, limit: 30 } };
    return { data: [] };
  });
  mocks.post.mockImplementation(async (path: string, options) => {
    if (path.endsWith("/edit"))
      active = {
        ...active,
        ...options.body,
        version: active.version + 1,
        state: "proposed",
      };
    if (path.endsWith("/action"))
      active = {
        ...active,
        version: active.version + 1,
        state:
          options.body.action === "confirm"
            ? "confirmed"
            : options.body.action === "delete"
              ? "deleted"
              : "revoked",
      };
    rows = active.state === "deleted" ? [] : [active];
    return { data: active };
  });
});

it("requires explicit source acknowledgement and resets it after editing", async () => {
  const user = userEvent.setup();
  render(
    <MemoryDetail initial={entry} context={context} onChanged={vi.fn()} />,
  );
  const confirm = screen.getByRole("button", { name: "确认生效" });
  expect((confirm as HTMLButtonElement).disabled).toBe(true);
  await user.click(screen.getByRole("checkbox", { name: /我已核对来源/ }));
  expect((confirm as HTMLButtonElement).disabled).toBe(false);
  await user.type(screen.getByLabelText("偏好内容"), "，需核对");
  expect((confirm as HTMLButtonElement).disabled).toBe(true);
  await user.click(screen.getByRole("button", { name: "保存候选" }));
  await waitFor(() => expect(mocks.post).toHaveBeenCalledTimes(1));
  expect((confirm as HTMLButtonElement).disabled).toBe(true);
  await user.click(screen.getByRole("checkbox", { name: /我已核对来源/ }));
  await user.click(confirm);
  await screen.findByRole("button", { name: "撤销生效" });
  expect(mocks.post.mock.calls[1][1].body).toEqual(
    expect.objectContaining({
      action: "confirm",
      confirm: true,
      expected_version: 3,
      expected_source_hash: entry.source!.source_hash,
    }),
  );
});

it("blocks confirmation and model generation when results require review", () => {
  render(
    <MemoryDetail
      initial={{ ...entry, outdated: true }}
      context={context}
      onChanged={vi.fn()}
    />,
  );
  expect(
    (screen.getByRole("button", { name: "确认生效" }) as HTMLButtonElement)
      .disabled,
  ).toBe(true);
  expect(screen.queryByRole("button", { name: "AI 整理候选" })).toBeNull();
  expect(screen.getByText(/出现新的结果/)).toBeTruthy();
});

it("keeps user edits after conflict and never confirms automatically", async () => {
  const user = userEvent.setup();
  mocks.post.mockResolvedValue({
    error: {
      error: { code: "version_conflict", message: "条目已变化，请刷新" },
    },
  });
  render(
    <MemoryDetail initial={entry} context={context} onChanged={vi.fn()} />,
  );
  await user.type(screen.getByLabelText("偏好内容"), "，核实后再判断");
  await user.click(screen.getByRole("button", { name: "保存候选" }));
  await screen.findByText("条目已变化，请刷新");
  expect(
    (screen.getByLabelText("偏好内容") as HTMLTextAreaElement).value,
  ).toContain("核实后再判断");
  expect(mocks.post).toHaveBeenCalledTimes(1);
  expect(
    (screen.getByRole("button", { name: "确认生效" }) as HTMLButtonElement)
      .disabled,
  ).toBe(true);
});

it("creates preferences from the owner's statement and deletes only after a separate choice", async () => {
  const user = userEvent.setup();
  render(<MemoryCenter {...context} />);
  await user.click(screen.getByRole("tab", { name: "我的偏好" }));
  await user.click(screen.getByRole("button", { name: "添加偏好" }));
  await user.type(screen.getByLabelText("我的明确表述"), "先核实客户交付");
  await user.click(screen.getByRole("button", { name: "建立候选" }));
  await screen.findByRole("button", { name: "确认生效" });
  expect(mocks.post.mock.calls[0][1].body).toEqual(
    expect.objectContaining({
      kind: "preference",
      source_text: "先核实客户交付",
      preference_key: "focus",
    }),
  );
  await user.click(screen.getByRole("button", { name: "删除条目" }));
  expect(mocks.post).toHaveBeenCalledTimes(1);
  await user.click(screen.getByRole("button", { name: "确认删除" }));
  await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
});

it("does not invent an outcome when the organization has no decisions", async () => {
  const user = userEvent.setup();
  render(<MemoryCenter {...context} />);
  await user.click(screen.getByRole("button", { name: "整理经验" }));
  expect(
    (screen.getByRole("button", { name: "建立候选" }) as HTMLButtonElement)
      .disabled,
  ).toBe(true);
  expect(screen.getByText(/未记录结果时/)).toBeTruthy();
  expect(mocks.post).not.toHaveBeenCalled();
});

it.each(["experience", "preference"] as const)(
  "fixes the %s view and only requests that kind and its own creation sources",
  async (kind) => {
    const user = userEvent.setup();
    rows = [entry, experience];
    const current = kind === "experience" ? experience : entry;
    const other = kind === "experience" ? entry : experience;
    render(<MemoryCenter {...context} kind={kind} />);
    await screen.findByRole("button", { name: new RegExp(current.title) });
    expect(
      screen.getByRole("heading", {
        level: 2,
        name: kind === "experience" ? "经验记录" : "我的偏好",
      }),
    ).toBeTruthy();
    expect(
      screen.getByRole("region", {
        name: kind === "experience" ? "决策经验" : "我的偏好",
      }),
    ).toBeTruthy();
    expect(screen.queryByRole("tablist")).toBeNull();
    expect(
      screen.queryByRole("button", { name: new RegExp(other.title) }),
    ).toBeNull();
    expect(mocks.get).toHaveBeenCalledWith("/api/v1/memory/entries", {
      params: {
        header: { "x-organization-id": context.organizationId },
        query: { kind, offset: 0, limit: 20 },
      },
    });
    await user.click(
      screen.getByRole("button", {
        name: kind === "experience" ? "整理经验" : "添加偏好",
      }),
    );
    if (kind === "experience") {
      await waitFor(() =>
        expect(mocks.get).toHaveBeenCalledWith(
          "/api/v1/decisions",
          expect.anything(),
        ),
      );
      expect(screen.getByLabelText("已确认决策")).toBeTruthy();
      expect(screen.queryByLabelText("我的明确表述")).toBeNull();
    } else {
      expect(screen.getByLabelText("我的明确表述")).toBeTruthy();
      expect(screen.queryByLabelText("已确认决策")).toBeNull();
      expect(mocks.get.mock.calls.map(([path]) => path)).toEqual([
        "/api/v1/memory/entries",
      ]);
    }
    expect(mocks.post).not.toHaveBeenCalled();
  },
);

it("preserves explicit confirmation, revocation and deletion in the fixed preference view", async () => {
  const user = userEvent.setup();
  render(<MemoryCenter {...context} kind="preference" />);
  await user.click(screen.getByRole("button", { name: "添加偏好" }));
  await user.type(screen.getByLabelText("我的明确表述"), "先核实客户交付");
  await user.click(screen.getByRole("button", { name: "建立候选" }));
  const confirm = await screen.findByRole("button", { name: "确认生效" });
  expect((confirm as HTMLButtonElement).disabled).toBe(true);
  expect(mocks.post).toHaveBeenCalledTimes(1);
  expect(mocks.post.mock.calls[0][1].body).toEqual(
    expect.objectContaining({
      kind: "preference",
      source_text: "先核实客户交付",
      preference_key: "focus",
    }),
  );
  await user.click(screen.getByRole("checkbox", { name: /我已核对来源/ }));
  await user.click(confirm);
  await user.click(await screen.findByRole("button", { name: "撤销生效" }));
  await screen.findByText("已撤销", { selector: ".memory-detail .tag" });
  await user.click(screen.getByRole("button", { name: "删除条目" }));
  expect(mocks.post).toHaveBeenCalledTimes(3);
  await user.click(screen.getByRole("button", { name: "确认删除" }));
  await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
  expect(
    mocks.post.mock.calls.slice(1).map(([, options]) => options.body),
  ).toEqual([
    expect.objectContaining({
      action: "confirm",
      confirm: true,
      expected_version: 2,
    }),
    expect.objectContaining({
      action: "revoke",
      confirm: true,
      expected_version: 3,
    }),
    expect.objectContaining({
      action: "delete",
      confirm: true,
      expected_version: 4,
    }),
  ]);
  expect(
    mocks.get.mock.calls
      .filter(([path]) => path === "/api/v1/memory/entries")
      .every(([, options]) => options.params.query.kind === "preference"),
  ).toBe(true);
  expect(
    mocks.get.mock.calls.some(([path]) => path.startsWith("/api/v1/decisions")),
  ).toBe(false);
});

it.each(["kind", "organization"] as const)(
  "ignores a late list response after changing %s without a caller remount",
  async (change) => {
    const current =
      change === "kind"
        ? entry
        : {
            ...experience,
            id: "experience2",
            title: "另一企业的复盘",
          };
    let resolveOld!: (value: unknown) => void;
    const pending = new Promise((resolve) => {
      resolveOld = resolve;
    });
    mocks.get.mockImplementation((path, options) => {
      if (
        options.params.header["x-organization-id"] === "o1" &&
        options.params.query.kind === "experience"
      )
        return pending;
      return Promise.resolve({
        data: { items: [current], total: 1, offset: 0, limit: 20 },
      });
    });
    const view = render(<MemoryCenter {...context} kind="experience" />);
    view.rerender(
      <MemoryCenter
        {...context}
        organizationId={change === "organization" ? "o2" : "o1"}
        kind={change === "kind" ? "preference" : "experience"}
      />,
    );
    await screen.findByRole("button", { name: new RegExp(current.title) });
    await act(async () => {
      resolveOld({
        data: { items: [experience], total: 21, offset: 0, limit: 20 },
      });
      await pending;
    });
    expect(
      screen.queryByRole("button", { name: new RegExp(experience.title) }),
    ).toBeNull();
    expect(screen.queryByRole("button", { name: "下一页" })).toBeNull();
    expect(mocks.get).toHaveBeenCalledTimes(2);
    expect(mocks.get.mock.calls[1][1].params).toEqual({
      header: { "x-organization-id": change === "organization" ? "o2" : "o1" },
      query: {
        kind: change === "kind" ? "preference" : "experience",
        offset: 0,
        limit: 20,
      },
    });
  },
);

it("starts the next fixed kind on its first page", async () => {
  const user = userEvent.setup();
  mocks.get.mockImplementation(async (path, options) => {
    const { kind, offset } = options.params.query;
    return {
      data: {
        items: [kind === "experience" ? experience : entry],
        total: kind === "experience" ? 21 : 1,
        offset,
        limit: 20,
      },
    };
  });
  const view = render(<MemoryCenter {...context} kind="experience" />);
  await user.click(await screen.findByRole("button", { name: "下一页" }));
  await waitFor(() =>
    expect(mocks.get.mock.calls[1][1].params.query.offset).toBe(20),
  );
  view.rerender(<MemoryCenter {...context} kind="preference" />);
  await screen.findByRole("button", { name: new RegExp(entry.title) });
  expect(mocks.get.mock.calls[2][1].params.query).toEqual({
    kind: "preference",
    offset: 0,
    limit: 20,
  });
  expect(screen.queryByRole("button", { name: "上一页" })).toBeNull();
});

it.each(["create", "edit"] as const)(
  "clears the previous kind's %s form and ignores its in-flight save when kind changes",
  async (operation) => {
    const user = userEvent.setup();
    rows = [entry, experience];
    let resolveSave!: (value: unknown) => void;
    const pending = new Promise((resolve) => {
      resolveSave = resolve;
    });
    mocks.post.mockReturnValueOnce(pending);
    const view = render(<MemoryCenter {...context} kind="preference" />);
    if (operation === "create") {
      await user.click(screen.getByRole("button", { name: "添加偏好" }));
      await user.type(
        screen.getByLabelText("我的明确表述"),
        "不会带入新页面的草稿",
      );
      await user.click(screen.getByRole("button", { name: "建立候选" }));
    } else {
      await user.click(
        await screen.findByRole("button", { name: new RegExp(entry.title) }),
      );
      await user.type(screen.getByLabelText("偏好内容"), "，尚未保存的修改");
      await user.click(screen.getByRole("button", { name: "保存候选" }));
    }
    expect(mocks.post).toHaveBeenCalledTimes(1);
    view.rerender(<MemoryCenter {...context} kind="experience" />);
    await screen.findByRole("button", { name: new RegExp(experience.title) });
    expect(screen.queryByRole("dialog")).toBeNull();
    await act(async () => {
      resolveSave({ data: entry });
      await pending;
    });
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(
      screen.queryByRole("button", { name: new RegExp(entry.title) }),
    ).toBeNull();
    view.rerender(<MemoryCenter {...context} kind="preference" />);
    await user.click(screen.getByRole("button", { name: "添加偏好" }));
    expect(
      (screen.getByLabelText("我的明确表述") as HTMLTextAreaElement).value,
    ).toBe("");
    expect(mocks.post).toHaveBeenCalledTimes(1);
  },
);

it("keeps non-editable experience read-only in its fixed view", async () => {
  const user = userEvent.setup();
  rows = [{ ...experience, can_edit: false, state: "confirmed" }];
  render(<MemoryCenter {...context} kind="experience" />);
  await user.click(
    await screen.findByRole("button", { name: new RegExp(experience.title) }),
  );
  expect(screen.getByRole("dialog", { name: "决策经验" })).toBeTruthy();
  expect(screen.queryByRole("button", { name: "保存候选" })).toBeNull();
  expect(screen.queryByRole("button", { name: "确认生效" })).toBeNull();
  expect(screen.queryByRole("button", { name: "撤销生效" })).toBeNull();
  expect(screen.queryByRole("button", { name: "删除条目" })).toBeNull();
  expect(screen.queryByRole("button", { name: "AI 整理候选" })).toBeNull();
  expect(mocks.post).not.toHaveBeenCalled();
});
