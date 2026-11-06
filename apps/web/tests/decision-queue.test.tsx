import { act, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { DecisionQueue } from "../components/decision-queue";
import { formatTime, type Schemas, type Work } from "../lib/api";

const mocks = vi.hoisted(() => ({ get: vi.fn(), post: vi.fn() }));
vi.mock("../lib/api", async (importOriginal) => ({
  ...(await importOriginal<object>()),
  api: () => ({ GET: mocks.get, POST: mocks.post }),
}));

type Decision = Schemas["DecisionListOut"];
const time = "2026-11-03T08:00:00Z";
const work: Work = {
  id: "work-1",
  organization_id: "org-1",
  title: "交付资料核对",
  description: null,
  department_id: "department-1",
  initiative_id: "project-1",
  owner_id: "member-1",
  due_at: null,
  lifecycle_status: "in_progress",
  needs_support: true,
  source_authority: "native",
  version: 2,
  updated_at: time,
};
const decision: Decision = {
  id: "decision-1",
  work_item_id: work.id,
  signal_id: null,
  analysis_id: "analysis-1",
  actor_id: "member-1",
  title: work.title,
  work_version: work.version,
  context_snapshot: {
    evidence: {
      id: "evidence-1",
      work_item_id: work.id,
      work_version: work.version,
      event_id: "event-1",
      facts: work,
      excerpt: "资料尚待对齐",
      source_at: time,
      captured_at: time,
      outdated: false,
    },
    interpretation: "需要核实资料与交付安排",
    analysis_mode: "rules",
    analysis_time: time,
    signal_versions: {},
  },
  options: [],
  state: "pending",
  selected_option: null,
  selected_plan: null,
  follow_up: null,
  follow_up_at: null,
  confirmed_by: null,
  confirmed_at: null,
  created_at: time,
  version: 1,
  outcome_count: 0,
};
function confirmed(overrides: Partial<Decision> = {}): Decision {
  return {
    ...decision,
    state: "confirmed",
    selected_plan: "先核对缺失资料",
    follow_up: "协调后补充实际结果",
    confirmed_by: "member-1",
    confirmed_at: time,
    ...overrides,
  };
}
function page(items: Decision[] = [], total = items.length) {
  return { data: { items, total, offset: 0, limit: 10 } };
}
function deferred() {
  let resolve!: (value: ReturnType<typeof page>) => void;
  const promise = new Promise<ReturnType<typeof page>>((done) => {
    resolve = done;
  });
  return { promise, resolve };
}
function lastQuery() {
  return mocks.get.mock.calls.at(-1)?.[1].params.query;
}
const props = {
  organizationId: "org-1",
  timezone: "Asia/Shanghai",
  revision: "revision-1",
  scope: "mine" as const,
  onOpen: vi.fn(),
};

beforeEach(() => {
  vi.resetAllMocks();
  vi.spyOn(Date, "now").mockReturnValue(Date.parse(time) + 10 * 60 * 1000);
  mocks.get.mockResolvedValue(page([decision]));
});
afterEach(() => {
  vi.restoreAllMocks();
  vi.useRealTimers();
});

describe("共享决策列表", () => {
  it("没有个人待办时不铺开空分类，历史仍可明确读取", async () => {
    const user = userEvent.setup();
    mocks.get.mockImplementation(async (_path, options) =>
      options.params.query.view === "all" ? page([confirmed()]) : page(),
    );
    render(<DecisionQueue {...props} />);
    await screen.findByText("暂时没有等你确认或跟进的事。");
    expect(screen.queryByRole("group", { name: "决策分类" })).toBeNull();
    expect(screen.queryByText("0 条记录")).toBeNull();
    expect(mocks.get).toHaveBeenCalledTimes(1);
    await user.click(screen.getByRole("button", { name: "查看全部记录" }));
    await screen.findByText(decision.title);
    expect(lastQuery()).toMatchObject({ mine: true, view: "all" });
    expect(mocks.get).toHaveBeenCalledTimes(2);
    expect(mocks.post).not.toHaveBeenCalled();
    expect(props.onOpen).not.toHaveBeenCalled();
  });

  it("个人只请求本人待处理记录，阅读不打开详情或写入", async () => {
    render(<DecisionQueue {...props} />);
    expect(await screen.findByText("等你确认")).toBeTruthy();
    expect(
      screen.getByRole("heading", { name: "等我确认与跟进" }),
    ).toBeTruthy();
    expect(mocks.get).toHaveBeenCalledTimes(1);
    expect(mocks.get).toHaveBeenCalledWith(
      "/api/v1/decisions",
      expect.objectContaining({
        params: {
          header: { "x-organization-id": "org-1" },
          query: { mine: true, view: "action_required", offset: 0, limit: 10 },
        },
      }),
    );
    expect(props.onOpen).not.toHaveBeenCalled();
    expect(mocks.post).not.toHaveBeenCalled();
  });

  it.each([
    ["待确认", "pending"],
    ["待跟进", "follow_up"],
    ["已有结果", "recorded"],
    ["全部记录", "all"],
  ])("切换 %s 使用服务端分类 %s，不补发计数查询", async (label, view) => {
    const user = userEvent.setup();
    render(<DecisionQueue {...props} />);
    await screen.findByText(decision.title);
    if (view !== "all") await user.click(screen.getByText("按状态筛选"));
    await user.click(screen.getByRole("button", { name: label }));
    await waitFor(() => expect(lastQuery().view).toBe(view));
    expect(mocks.get).toHaveBeenCalledTimes(2);
    expect(lastQuery().mine).toBe(true);
    expect(
      screen.getByRole("button", { name: label }).getAttribute("aria-pressed"),
    ).toBe("true");
  });

  it("公司展示全部记录且不把他人草案说成等你确认", async () => {
    render(<DecisionQueue {...props} scope="company" />);
    await screen.findByText(decision.title);
    expect(lastQuery()).toEqual({
      mine: false,
      view: "all",
      offset: 0,
      limit: 10,
    });
    expect(screen.getByRole("heading", { name: "企业决策记录" })).toBeTruthy();
    expect(screen.queryByText("等你确认")).toBeNull();
    expect(screen.queryByRole("button", { name: "待我处理" })).toBeNull();
    expect(
      within(screen.getByRole("listitem")).getByText("待确认"),
    ).toBeTruthy();
  });

  it("项目请求绑定 initiative_id，缺项目或企业时不读取全局列表", async () => {
    const { rerender } = render(<DecisionQueue {...props} scope="project" />);
    expect(screen.getByText("请先选择项目，再查看决策记录。")).toBeTruthy();
    expect(mocks.get).not.toHaveBeenCalled();
    rerender(
      <DecisionQueue {...props} scope="project" initiativeId="project-1" />,
    );
    await screen.findByText(decision.title);
    expect(lastQuery()).toEqual({
      mine: false,
      initiative_id: "project-1",
      view: "all",
      offset: 0,
      limit: 10,
    });
    rerender(<DecisionQueue {...props} organizationId="" />);
    expect(screen.getByText("请先选择企业。")).toBeTruthy();
    expect(screen.queryByText(decision.title)).toBeNull();
    expect(mocks.get).toHaveBeenCalledTimes(1);
  });

  it("已有结果只表示追加记录，保留跟进安排与显式组织时区日期", async () => {
    const followUpAt = "2026-11-04T02:00:00Z";
    mocks.get.mockResolvedValue(
      page([confirmed({ outcome_count: 2, follow_up_at: followUpAt })]),
    );
    render(<DecisionQueue {...props} />);
    await screen.findByText(decision.title);
    const row = within(screen.getByRole("listitem"));
    expect(row.getByText("已有结果")).toBeTruthy();
    expect(
      row.getByText("已记录 2 条实际结果，不代表事项已完成。"),
    ).toBeTruthy();
    expect(row.getByText("跟进安排：协调后补充实际结果")).toBeTruthy();
    expect(
      row.getByText(`跟进时间 · ${formatTime(followUpAt, props.timezone)}`),
    ).toBeTruthy();
    expect(row.queryByText("已完成", { exact: true })).toBeNull();
  });

  it("尚无结果是待跟进，文字里的明天不推算具体日期", async () => {
    mocks.get.mockResolvedValue(
      page([confirmed({ follow_up: "明天沟通后核对", follow_up_at: null })]),
    );
    render(<DecisionQueue {...props} />);
    await screen.findByText(decision.title);
    const row = within(screen.getByRole("listitem"));
    expect(row.getByText("待跟进")).toBeTruthy();
    expect(row.getByText("跟进安排：明天沟通后核对")).toBeTruthy();
    expect(row.getByText("未设置跟进时间")).toBeTruthy();
    expect(row.queryByText(/跟进时间 ·/)).toBeNull();
  });

  it("分析超过 30 分钟提醒核对，点击仅打开现有详情", async () => {
    const user = userEvent.setup();
    mocks.get.mockResolvedValue(
      page([
        {
          ...decision,
          created_at: "2026-11-03T08:09:00Z",
          context_snapshot: {
            ...decision.context_snapshot,
            analysis_time: "2026-11-03T07:39:00Z",
          },
        },
      ]),
    );
    render(<DecisionQueue {...props} />);
    expect(
      await screen.findByText("这份方案需要重新核对后再确认。"),
    ).toBeTruthy();
    const button = screen.getByRole("button", {
      name: `查看决策：${decision.title}`,
    });
    expect(button.textContent).toContain("重新核对");
    await user.click(button);
    expect(props.onOpen).toHaveBeenCalledExactlyOnceWith(decision.id);
    expect(mocks.get).toHaveBeenCalledTimes(1);
    expect(mocks.post).not.toHaveBeenCalled();
  });

  it("不以创建时间推断分析过期，也不把未知时间当过期", async () => {
    mocks.get.mockResolvedValue(
      page([
        { ...decision, created_at: "2026-11-01T08:00:00Z" },
        {
          ...decision,
          id: "unknown-time",
          context_snapshot: {
            ...decision.context_snapshot,
            analysis_time: "unknown",
          },
        },
        confirmed({
          id: "confirmed-old",
          context_snapshot: {
            ...decision.context_snapshot,
            analysis_time: "2026-11-01T08:00:00Z",
          },
        }),
      ]),
    );
    render(<DecisionQueue {...props} />);
    await waitFor(() =>
      expect(screen.getAllByRole("listitem")).toHaveLength(3),
    );
    expect(screen.queryByText(/这份方案需要重新核对/)).toBeNull();
  });

  it("页面保持打开时越过分析期限也更新核对提示", async () => {
    vi.restoreAllMocks();
    vi.useFakeTimers();
    vi.setSystemTime(new Date("2026-11-03T08:29:59Z"));
    render(<DecisionQueue {...props} />);
    await act(async () => {});
    expect(screen.queryByText(/这份方案需要重新核对/)).toBeNull();
    await act(async () => {
      await vi.advanceTimersByTimeAsync(1_002);
    });
    expect(screen.getByText("这份方案需要重新核对后再确认。")).toBeTruthy();
  });

  it("分页按 offset 读取，切分类回第一页并移除上一页内容", async () => {
    const user = userEvent.setup();
    const first = Array.from({ length: 10 }, (_, index) => ({
      ...decision,
      id: `d-${index}`,
      title: `事项 ${index}`,
    }));
    mocks.get.mockImplementation(async (_path, options) =>
      options.params.query.offset === 10
        ? page([{ ...decision, title: "第二页事项" }], 11)
        : page(first, 11),
    );
    render(<DecisionQueue {...props} />);
    await screen.findByText("1–10 / 11 条");
    expect(
      (screen.getByRole("button", { name: "上一页决策" }) as HTMLButtonElement)
        .disabled,
    ).toBe(true);
    await user.click(screen.getByRole("button", { name: "下一页决策" }));
    await screen.findByText("第二页事项");
    expect(lastQuery().offset).toBe(10);
    expect(screen.queryByText("事项 0")).toBeNull();
    expect(
      (screen.getByRole("button", { name: "下一页决策" }) as HTMLButtonElement)
        .disabled,
    ).toBe(true);
    await user.click(screen.getByRole("button", { name: "全部记录" }));
    await screen.findByText("事项 0");
    expect(lastQuery()).toMatchObject({ view: "all", offset: 0 });
    expect(screen.queryByText("第二页事项")).toBeNull();
  });

  it("切换分类隔离迟到结果，并取消旧读取", async () => {
    const user = userEvent.setup();
    const old = deferred();
    mocks.get
      .mockReturnValueOnce(old.promise)
      .mockResolvedValue(page([confirmed({ title: "当前分类" })]));
    render(<DecisionQueue {...props} />);
    const oldSignal = mocks.get.mock.calls[0][1].signal as AbortSignal;
    await user.click(screen.getByRole("button", { name: "全部记录" }));
    await screen.findByText("当前分类");
    expect(oldSignal.aborted).toBe(true);
    await act(async () =>
      old.resolve(page([{ ...decision, title: "迟到旧分类" }])),
    );
    expect(screen.queryByText("迟到旧分类")).toBeNull();
    expect(screen.getByText("当前分类")).toBeTruthy();
  });

  it("刷新后最后一页记录消失时仍能返回上一页", async () => {
    const user = userEvent.setup();
    const first = Array.from({ length: 10 }, (_, index) => ({
      ...decision,
      id: `d-${index}`,
    }));
    mocks.get.mockImplementation(async (_path, options) =>
      options.params.query.offset === 10 ? page([], 0) : page(first, 11),
    );
    render(<DecisionQueue {...props} />);
    await screen.findByText("1–10 / 11 条");
    await user.click(screen.getByRole("button", { name: "下一页决策" }));
    await screen.findByText("这一页暂无记录，可以返回上一页查看。");
    await user.click(screen.getByRole("button", { name: "上一页决策" }));
    await screen.findByText("1–10 / 11 条");
    expect(lastQuery().offset).toBe(0);
  });

  it("切出后快速切回原分类也等待新读取，不恢复旧缓存", async () => {
    const user = userEvent.setup();
    const other = deferred();
    const returned = deferred();
    mocks.get
      .mockResolvedValueOnce(page([decision]))
      .mockReturnValueOnce(other.promise)
      .mockReturnValueOnce(returned.promise);
    render(<DecisionQueue {...props} />);
    await screen.findByText(decision.title);
    await user.click(screen.getByRole("button", { name: "全部记录" }));
    await user.click(screen.getByRole("button", { name: "待我处理" }));
    expect(screen.queryByText(decision.title)).toBeNull();
    expect(screen.getByText("正在读取决策记录…")).toBeTruthy();
    await act(async () => returned.resolve(page()));
    await act(async () => other.resolve(page([decision])));
    expect(screen.queryByText(decision.title)).toBeNull();
    expect(screen.getByText("暂时没有等你确认或跟进的事。")).toBeTruthy();
  });

  it("企业、scope 和项目切换清空旧记录及过滤状态，旧范围无法回填", async () => {
    const user = userEvent.setup();
    const old = deferred();
    mocks.get
      .mockResolvedValueOnce(page([decision]))
      .mockReturnValueOnce(old.promise)
      .mockResolvedValue(page([{ ...decision, title: "新企业项目" }]));
    const { rerender } = render(<DecisionQueue {...props} />);
    await screen.findByText(decision.title);
    await user.click(screen.getByText("按状态筛选"));
    await user.click(screen.getByRole("button", { name: "待跟进" }));
    expect(screen.queryByText(decision.title)).toBeNull();
    rerender(
      <DecisionQueue
        {...props}
        organizationId="org-2"
        scope="project"
        initiativeId="project-2"
      />,
    );
    await screen.findByText("新企业项目");
    expect(lastQuery()).toMatchObject({
      mine: false,
      initiative_id: "project-2",
      view: "all",
    });
    expect(mocks.get.mock.calls.at(-1)?.[1].params.header).toEqual({
      "x-organization-id": "org-2",
    });
    await act(async () =>
      old.resolve(page([{ ...decision, title: "旧企业迟到" }])),
    );
    expect(screen.queryByText("旧企业迟到")).toBeNull();
    const nextProject = deferred();
    mocks.get.mockReturnValueOnce(nextProject.promise);
    rerender(
      <DecisionQueue
        {...props}
        organizationId="org-2"
        scope="project"
        initiativeId="project-3"
      />,
    );
    expect(screen.queryByText("新企业项目")).toBeNull();
    expect(lastQuery().initiative_id).toBe("project-3");
    await act(async () => nextProject.resolve(page()));
    expect(screen.getByText(/还没有决策记录/)).toBeTruthy();
  });

  it("revision 刷新立即隐藏旧记录，迟到的中间刷新不能覆盖最新结果", async () => {
    const middle = deferred();
    const latest = deferred();
    mocks.get
      .mockResolvedValueOnce(page([decision]))
      .mockReturnValueOnce(middle.promise)
      .mockReturnValueOnce(latest.promise);
    const { rerender } = render(<DecisionQueue {...props} />);
    await screen.findByText(decision.title);
    rerender(<DecisionQueue {...props} revision="revision-2" />);
    expect(screen.queryByText(decision.title)).toBeNull();
    expect(screen.getByText("正在读取决策记录…")).toBeTruthy();
    rerender(<DecisionQueue {...props} revision="revision-3" />);
    await act(async () =>
      latest.resolve(
        page([confirmed({ title: "最新结果", outcome_count: 1 })]),
      ),
    );
    await act(async () =>
      middle.resolve(page([{ ...decision, title: "旧刷新结果" }])),
    );
    expect(screen.getByText("最新结果")).toBeTruthy();
    expect(screen.queryByText("旧刷新结果")).toBeNull();
  });

  it("失权或读取错误不保留旧记录，重试同一分类即可恢复", async () => {
    const user = userEvent.setup();
    mocks.get
      .mockResolvedValueOnce(page([decision]))
      .mockResolvedValueOnce({
        error: { error: { message: "当前无权读取这些决策" } },
      })
      .mockResolvedValueOnce(page([confirmed({ title: "恢复读取" })]));
    const { rerender } = render(<DecisionQueue {...props} />);
    await screen.findByText(decision.title);
    rerender(<DecisionQueue {...props} revision="recheck" />);
    expect(await screen.findByRole("alert")).toBeTruthy();
    expect(screen.getByText(/当前无权读取这些决策/)).toBeTruthy();
    expect(screen.queryByText(decision.title)).toBeNull();
    await user.click(screen.getByRole("button", { name: "重试" }));
    await screen.findByText("恢复读取");
    expect(lastQuery()).toMatchObject({
      mine: true,
      view: "action_required",
      offset: 0,
    });
    expect(screen.queryByRole("alert")).toBeNull();
  });

  it("空态只描述当前分类，不宣称工作全部完成", async () => {
    mocks.get.mockResolvedValue(page());
    render(<DecisionQueue {...props} />);
    expect(
      await screen.findByText("暂时没有等你确认或跟进的事。"),
    ).toBeTruthy();
    expect(screen.queryByText("0 条记录")).toBeNull();
    expect(screen.queryByRole("button", { name: /查看决策/ })).toBeNull();
    expect(props.onOpen).not.toHaveBeenCalled();
  });
});
