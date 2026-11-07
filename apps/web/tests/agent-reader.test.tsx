import { act, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { StrictMode } from "react";
import { AgentReader } from "../components/agent-reader";
import type { Schemas } from "../lib/api";

const mocks = vi.hoisted(() => ({ get: vi.fn(), post: vi.fn() }));
vi.mock("../lib/api", async (original) => ({
  ...(await original<object>()),
  api: () => ({ GET: mocks.get, POST: mocks.post }),
}));
const time = "2026-11-04T03:00:00Z";
const ready: Schemas["RunOut"] = {
  id: "r1",
  task: "read",
  draft: null,
  question: "合成验收问题",
  work_item_id: null,
  state: "ready",
  version: 1,
  step_count: 0,
  max_steps: 6,
  error_code: null,
  steps: [],
  answer: null,
  created_at: time,
  deadline: time,
};
const running: Schemas["RunOut"] = {
  ...ready,
  state: "running",
  version: 2,
  step_count: 1,
  steps: [
    {
      id: "s1",
      ordinal: 1,
      state: "pending",
      capability: null,
      error_code: null,
    },
  ],
};
const completed: Schemas["RunOut"] = {
  ...ready,
  state: "completed",
  version: 5,
  step_count: 2,
  answer: {
    id: "a1",
    mode: "model",
    notice: "只读分析",
    summary: "缺少资料，仍需核实。",
    suggestions: [],
    evidence: [],
    signals: [],
    considered_work_count: 0,
    authorized_work_count: 0,
    generated_at: time,
    prompt_version: "agent-read-v1",
    provider: "fixture",
    model: "fixture",
  },
};
const props = { organizationId: "o1", onAnswer: vi.fn() };
function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((done) => {
    resolve = done;
  });
  return { promise, resolve };
}
beforeEach(() => {
  vi.resetAllMocks();
  mocks.get.mockResolvedValue({ data: [] });
});
afterEach(() => vi.useRealTimers());
async function start(user: ReturnType<typeof userEvent.setup>) {
  await user.type(screen.getByLabelText("让 coRoof 继续查询"), "合成验收问题");
  await user.click(screen.getByRole("button", { name: "开始查询" }));
}

describe("持久化 Agent 读取循环", () => {
  it.each([
    ["not_configured", "尚未配置可用的企业模型，请在企业 AI 设置中核对。"],
    [
      "model_disabled",
      "企业已停用模型服务，请由企业所有者在企业 AI 设置中选择并启用可用服务。",
    ],
  ])(
    "失败原因 %s 向外传递可读说明，主动取消不作为失败",
    async (code, message) => {
      const onStateChange = vi.fn();
      mocks.get
        .mockResolvedValueOnce({
          data: { ...ready, state: "failed", error_code: code },
        })
        .mockResolvedValueOnce({
          data: {
            ...ready,
            id: "r2",
            state: "cancelled",
            error_code: "cancelled",
          },
        });
      const view = render(
        <AgentReader
          {...props}
          presentation="progress"
          initialRunId="r1"
          onStateChange={onStateChange}
        />,
      );
      await screen.findByText(message);
      expect(onStateChange.mock.calls.at(-1)?.[0]).toMatchObject({
        busy: false,
        error: message,
      });
      view.rerender(
        <AgentReader
          {...props}
          presentation="progress"
          initialRunId="r2"
          onStateChange={onStateChange}
        />,
      );
      await screen.findByText("已取消");
      expect(onStateChange.mock.calls.at(-1)?.[0]).toMatchObject({
        busy: false,
        error: "",
      });
      expect(
        screen.queryByText("本次处理未完成，请核对连接或补充资料。"),
      ).toBeNull();
      expect(mocks.post).not.toHaveBeenCalled();
    },
  );

  it.each([
    ["authentication", "身份验证失败"],
    ["permission", "模型服务拒绝访问"],
    ["rate_limited", "请求受到限制"],
    ["unavailable", "暂时无法连接模型服务"],
    ["timeout", "请求超时"],
    ["budget_exceeded", "可能涉及步骤、时长或用量"],
    ["unsupported_capability", "不支持所需能力"],
    ["future_service_code", "暂时无法确认原因"],
  ])(
    "服务错误 %s 显示对应原因而非缺资料，读取失败记录不自动重试模型",
    async (code, explanation) => {
      const onStateChange = vi.fn();
      mocks.get.mockResolvedValue({
        data: { ...ready, state: "failed", error_code: code },
      });
      render(
        <AgentReader
          {...props}
          presentation="progress"
          initialRunId="r1"
          onStateChange={onStateChange}
        />,
      );
      const alert = await screen.findByRole("alert");
      expect(alert.textContent).toContain(explanation);
      expect(alert.textContent).not.toContain("补充资料");
      expect(onStateChange).toHaveBeenLastCalledWith({
        run: expect.objectContaining({ error_code: code }),
        busy: false,
        error: expect.stringContaining(explanation),
      });
      expect(mocks.post).not.toHaveBeenCalled();
      expect(mocks.get).toHaveBeenCalledOnce();
      expect(screen.getAllByRole("button", { name: "重新核对" })).toHaveLength(
        1,
      );
    },
  );

  it("progress 只显示真实创建与服务器步骤，不读取历史或重复输入", async () => {
    const created = deferred<{ data: Schemas["RunOut"] }>();
    const advanced = deferred<{ data: Schemas["RunOut"] }>();
    const onStateChange = vi.fn();
    mocks.post
      .mockReturnValueOnce(created.promise)
      .mockReturnValueOnce(advanced.promise);
    render(
      <AgentReader
        {...props}
        presentation="progress"
        command={{ id: "command-1", question: "核实资料" }}
        onStateChange={onStateChange}
      />,
    );
    expect(await screen.findByText("正在创建查询任务…")).toBeTruthy();
    expect(screen.queryByRole("textbox")).toBeNull();
    expect(screen.queryByText("最近的查询任务")).toBeNull();
    expect(screen.queryByText(/分析下一步/)).toBeNull();
    expect(mocks.get).not.toHaveBeenCalled();
    expect(onStateChange).toHaveBeenLastCalledWith({
      run: null,
      busy: true,
      error: "",
    });
    await act(async () => created.resolve({ data: ready }));
    expect(screen.getByText("正在核对相关记录…")).toBeTruthy();
    expect(
      screen.getByText("已记录 0 轮 · 上限 6 轮").closest("details")?.open,
    ).toBe(false);
    expect(screen.queryByRole("listitem")).toBeNull();
    await act(async () =>
      advanced.resolve({
        data: {
          ...completed,
          steps: [
            {
              ...running.steps[0],
              state: "succeeded",
              capability: "work.investigate",
            },
          ],
        },
      }),
    );
    expect(screen.getByText("查看工作经过 · 已完成")).toBeTruthy();
    expect(onStateChange.mock.calls.at(-1)?.[0]).toMatchObject({
      run: { state: "completed" },
      busy: false,
      error: "",
    });
    expect(props.onAnswer).toHaveBeenCalledOnce();
  });

  it("command 在 StrictMode 和普通重渲染中只提交一次，同问题新 id 可独立查询", async () => {
    mocks.post
      .mockResolvedValueOnce({ data: completed })
      .mockResolvedValueOnce({ data: { ...completed, id: "r2" } });
    const view = render(
      <StrictMode>
        <AgentReader
          {...props}
          presentation="progress"
          command={{ id: "c1", question: "同一个问题" }}
        />
      </StrictMode>,
    );
    await screen.findByText("分析完成");
    expect(mocks.post).toHaveBeenCalledOnce();
    view.rerender(
      <StrictMode>
        <AgentReader
          {...props}
          presentation="progress"
          command={{ id: "c1", question: "同一个问题" }}
          onStateChange={vi.fn()}
        />
      </StrictMode>,
    );
    await act(async () => {});
    expect(mocks.post).toHaveBeenCalledOnce();
    view.rerender(
      <StrictMode>
        <AgentReader
          {...props}
          presentation="progress"
          command={{ id: "c2", question: "同一个问题" }}
        />
      </StrictMode>,
    );
    await waitFor(() => expect(mocks.post).toHaveBeenCalledTimes(2));
    expect(mocks.post.mock.calls[0][1].body.idempotency_key).not.toBe(
      mocks.post.mock.calls[1][1].body.idempotency_key,
    );
  });

  it("新命令不会与在途任务并行，也不会在原任务结束后偷偷排队执行", async () => {
    const advanced = deferred<{ data: Schemas["RunOut"] }>();
    mocks.post
      .mockResolvedValueOnce({ data: ready })
      .mockReturnValueOnce(advanced.promise);
    const view = render(
      <AgentReader
        {...props}
        presentation="progress"
        command={{ id: "c1", question: "先核实" }}
      />,
    );
    await waitFor(() => expect(mocks.post).toHaveBeenCalledTimes(2));
    view.rerender(
      <AgentReader
        {...props}
        presentation="progress"
        command={{ id: "c2", question: "另一个问题" }}
      />,
    );
    expect(await screen.findByRole("alert")).toBeTruthy();
    await act(async () => advanced.resolve({ data: completed }));
    expect(mocks.post).toHaveBeenCalledTimes(2);
    expect(props.onAnswer).toHaveBeenCalledOnce();
  });

  it("仅隐藏再显示进度不影响当前任务和结果，不重复提交", async () => {
    const advanced = deferred<{ data: Schemas["RunOut"] }>();
    mocks.post
      .mockResolvedValueOnce({ data: ready })
      .mockReturnValueOnce(advanced.promise);
    const command = { id: "c1", question: "后台继续核实" };
    const view = render(
      <div>
        <AgentReader {...props} presentation="progress" command={command} />
      </div>,
    );
    await waitFor(() => expect(mocks.post).toHaveBeenCalledTimes(2));
    view.rerender(
      <div hidden>
        <AgentReader {...props} presentation="progress" command={command} />
      </div>,
    );
    await act(async () => advanced.resolve({ data: completed }));
    view.rerender(
      <div>
        <AgentReader {...props} presentation="progress" command={command} />
      </div>,
    );
    expect(screen.getByText("分析完成")).toBeTruthy();
    expect(mocks.post).toHaveBeenCalledTimes(2);
    expect(props.onAnswer).toHaveBeenCalledOnce();
  });

  it("创建响应未返回也可停止，拿到标识后取消，不推进模型步骤", async () => {
    const user = userEvent.setup();
    const created = deferred<{ data: Schemas["RunOut"] }>();
    mocks.post.mockReturnValueOnce(created.promise).mockResolvedValueOnce({
      data: { ...ready, state: "cancelled", version: 2 },
    });
    mocks.get.mockResolvedValue({ data: ready });
    render(
      <AgentReader
        {...props}
        presentation="progress"
        command={{ id: "c1", question: "请核实" }}
      />,
    );
    await screen.findByText("正在创建查询任务…");
    await user.click(screen.getByRole("button", { name: "停止后续步骤" }));
    expect(screen.getByText("正在停止后续步骤，等待服务器确认…")).toBeTruthy();
    await act(async () => created.resolve({ data: ready }));
    await screen.findByText("已取消");
    expect(mocks.post.mock.calls.map((call) => call[0])).toEqual([
      "/api/v1/agent/runs/submit",
      "/api/v1/agent/runs/{run_id}/cancel",
    ]);
    expect(props.onAnswer).not.toHaveBeenCalled();
  });

  it("progress 停止拒绝迟到成功答案，也不会继续下一步", async () => {
    const user = userEvent.setup();
    const advanced = deferred<{ data: Schemas["RunOut"] }>();
    const onStateChange = vi.fn();
    mocks.post
      .mockResolvedValueOnce({ data: ready })
      .mockReturnValueOnce(advanced.promise)
      .mockResolvedValueOnce({
        data: { ...running, state: "cancelled", version: 3 },
      });
    mocks.get.mockResolvedValue({ data: running });
    render(
      <AgentReader
        {...props}
        presentation="progress"
        command={{ id: "c1", question: "请核实" }}
        onStateChange={onStateChange}
      />,
    );
    await waitFor(() => expect(mocks.post).toHaveBeenCalledTimes(2));
    await user.click(screen.getByRole("button", { name: "停止后续步骤" }));
    await screen.findByText("已取消");
    await act(async () => advanced.resolve({ data: completed }));
    expect(props.onAnswer).not.toHaveBeenCalled();
    expect(onStateChange.mock.calls.at(-1)?.[0]).toMatchObject({
      run: { state: "cancelled" },
      busy: false,
    });
    expect(mocks.post).toHaveBeenCalledTimes(3);
  });

  it("已完成历史仅 GET，不创建或推进；状态和答案正常返回", async () => {
    const onStateChange = vi.fn();
    mocks.get.mockResolvedValue({ data: completed });
    render(
      <StrictMode>
        <AgentReader
          {...props}
          presentation="progress"
          initialRunId="history-1"
          onStateChange={onStateChange}
        />
      </StrictMode>,
    );
    await screen.findByText("分析完成");
    expect(mocks.get).toHaveBeenCalledExactlyOnceWith(
      "/api/v1/agent/runs/{run_id}",
      {
        params: {
          header: { "x-organization-id": "o1" },
          path: { run_id: "history-1" },
        },
      },
    );
    expect(mocks.post).not.toHaveBeenCalled();
    expect(props.onAnswer).toHaveBeenCalledOnce();
    expect(onStateChange).toHaveBeenLastCalledWith({
      run: completed,
      busy: false,
      error: "",
    });
  });

  it("未完成历史也不自动推进，只在明确继续时执行", async () => {
    const user = userEvent.setup();
    mocks.get.mockResolvedValue({ data: ready });
    mocks.post.mockResolvedValue({ data: completed });
    render(
      <AgentReader {...props} presentation="progress" initialRunId="r1" />,
    );
    await screen.findByText("可以继续读取");
    expect(mocks.post).not.toHaveBeenCalled();
    await user.click(screen.getByRole("button", { name: "继续核对" }));
    await screen.findByText("分析完成");
    expect(mocks.post.mock.calls.map((call) => call[0])).toEqual([
      "/api/v1/agent/runs/{run_id}/advance",
    ]);
  });

  it("历史读取失败只允许重新读取，不转成新模型调用", async () => {
    const user = userEvent.setup();
    mocks.get
      .mockRejectedValueOnce(new Error("读取中断"))
      .mockResolvedValueOnce({ data: completed });
    render(
      <AgentReader {...props} presentation="progress" initialRunId="r1" />,
    );
    expect(await screen.findByRole("alert")).toBeTruthy();
    await user.click(screen.getByRole("button", { name: "重新核对" }));
    await screen.findByText("分析完成");
    expect(mocks.post).not.toHaveBeenCalled();
    expect(mocks.get).toHaveBeenCalledTimes(2);
  });

  it("切换历史拒绝迟到响应，切换企业也不会重放原命令或回填答案", async () => {
    const old = deferred<{ data: Schemas["RunOut"] }>();
    mocks.get.mockReturnValueOnce(old.promise).mockResolvedValueOnce({
      data: { ...completed, id: "r2", question: "新历史" },
    });
    const view = render(
      <AgentReader {...props} presentation="progress" initialRunId="r1" />,
    );
    await waitFor(() => expect(mocks.get).toHaveBeenCalledOnce());
    view.rerender(
      <AgentReader {...props} presentation="progress" initialRunId="r2" />,
    );
    await screen.findByText("新历史");
    await act(async () => old.resolve({ data: completed }));
    expect(screen.queryByText(ready.question)).toBeNull();
    expect(props.onAnswer).toHaveBeenCalledOnce();
    const pendingCreate = deferred<{ data: Schemas["RunOut"] }>();
    mocks.post.mockReturnValueOnce(pendingCreate.promise);
    view.rerender(
      <AgentReader
        {...props}
        presentation="progress"
        command={{ id: "c1", question: "旧企业问题" }}
      />,
    );
    await waitFor(() => expect(mocks.post).toHaveBeenCalledOnce());
    view.rerender(
      <AgentReader
        {...props}
        organizationId="o2"
        presentation="progress"
        command={{ id: "c1", question: "旧企业问题" }}
      />,
    );
    await act(async () => pendingCreate.resolve({ data: completed }));
    expect(mocks.post).toHaveBeenCalledOnce();
    expect(props.onAnswer).toHaveBeenCalledOnce();
    expect(screen.queryByText("分析完成")).toBeNull();
  });

  it("创建失败不自动重试，明确重试复用同一个幂等标识", async () => {
    const user = userEvent.setup();
    mocks.post
      .mockRejectedValueOnce(new Error("连接暂时中断"))
      .mockResolvedValueOnce({ data: completed });
    const view = render(
      <AgentReader
        {...props}
        presentation="progress"
        command={{ id: "c1", question: "请核实" }}
      />,
    );
    await screen.findByRole("alert");
    view.rerender(
      <AgentReader
        {...props}
        presentation="progress"
        command={{ id: "c1", question: "请核实" }}
      />,
    );
    await act(async () => {});
    expect(mocks.post).toHaveBeenCalledOnce();
    await user.click(screen.getByRole("button", { name: "重新核对" }));
    await screen.findByText("分析完成");
    expect(mocks.post.mock.calls[0][1].body.idempotency_key).toBe(
      mocks.post.mock.calls[1][1].body.idempotency_key,
    );
  });

  it("现有任务重新读取失败时保留任务标识，重试仍只 GET", async () => {
    const user = userEvent.setup();
    mocks.post.mockResolvedValue({ data: completed });
    mocks.get
      .mockRejectedValueOnce(new Error("记录暂不可读"))
      .mockResolvedValueOnce({ data: completed });
    render(
      <AgentReader
        {...props}
        presentation="progress"
        command={{ id: "c1", question: "请核实" }}
      />,
    );
    await screen.findByText("分析完成");
    await user.click(screen.getByText("查看依据与处理过程"));
    await user.click(screen.getByRole("button", { name: "刷新这次查询" }));
    await screen.findByRole("alert");
    await user.click(screen.getByRole("button", { name: "重新核对" }));
    await screen.findByText("分析完成");
    expect(mocks.post).toHaveBeenCalledOnce();
    expect(mocks.get).toHaveBeenCalledTimes(2);
    expect(mocks.get.mock.calls[1][1].params.path).toEqual({ run_id: "r1" });
  });

  it("明确追问透传父查询，网络重试保留父引用和幂等键，新问题不自动继承", async () => {
    const user = userEvent.setup();
    mocks.post
      .mockRejectedValueOnce(new Error("网络中断"))
      .mockResolvedValue({ data: completed });
    const view = render(
      <AgentReader
        {...props}
        presentation="progress"
        command={{
          id: "followup",
          question: "再看一下",
          parentRunId: "parent-1",
        }}
      />,
    );
    await screen.findByRole("alert");
    expect(mocks.post.mock.calls[0][1].body.parent_run_id).toBe("parent-1");
    await user.click(screen.getByRole("button", { name: "重新核对" }));
    await screen.findByText("分析完成");
    expect(mocks.post.mock.calls[1][1].body).toEqual(
      mocks.post.mock.calls[0][1].body,
    );
    view.rerender(
      <AgentReader
        {...props}
        presentation="progress"
        command={{ id: "fresh", question: "另一个问题" }}
      />,
    );
    await waitFor(() => expect(mocks.post).toHaveBeenCalledTimes(3));
    expect(mocks.post.mock.calls[2][1].body).not.toHaveProperty(
      "parent_run_id",
    );
  });

  it("父查询失效不自动重发，只有明确作为新问题发送才移除父引用", async () => {
    const user = userEvent.setup();
    mocks.post
      .mockResolvedValueOnce({
        error: {
          error: {
            code: "parent_context_unavailable",
            message: "parent unavailable",
          },
        },
      })
      .mockResolvedValueOnce({ data: completed });
    render(
      <StrictMode>
        <AgentReader
          {...props}
          presentation="progress"
          command={{
            id: "followup",
            question: "继续核对",
            parentRunId: "old-parent",
          }}
        />
      </StrictMode>,
    );
    expect((await screen.findByRole("alert")).textContent).toContain(
      "上一轮查询已失效或不在当前范围",
    );
    expect(mocks.post).toHaveBeenCalledOnce();
    await user.click(screen.getByRole("button", { name: "作为新问题发送" }));
    await screen.findByText("分析完成");
    expect(mocks.post.mock.calls[1][1].body.question).toBe("继续核对");
    expect(mocks.post.mock.calls[1][1].body).not.toHaveProperty(
      "parent_run_id",
    );
    expect(mocks.post.mock.calls[1][1].body.idempotency_key).not.toBe(
      mocks.post.mock.calls[0][1].body.idempotency_key,
    );
  });

  it("父查询在推进时失效后清掉旧任务，只能明确按原问题创建无父任务", async () => {
    const user = userEvent.setup();
    const child = { ...ready, question: "原来的追问", parent_run_id: "parent" };
    const onStateChange = vi.fn();
    mocks.post
      .mockResolvedValueOnce({ data: child })
      .mockResolvedValueOnce({
        error: {
          error: { code: "parent_context_unavailable", message: "expired" },
        },
      })
      .mockResolvedValueOnce({
        data: { ...completed, id: "fresh", question: child.question },
      });
    render(
      <AgentReader
        {...props}
        presentation="progress"
        command={{
          id: "followup",
          question: child.question,
          parentRunId: "parent",
        }}
        onStateChange={onStateChange}
      />,
    );
    await screen.findByRole("alert");
    expect(mocks.post).toHaveBeenCalledTimes(2);
    expect(mocks.get).not.toHaveBeenCalled();
    expect(onStateChange).toHaveBeenLastCalledWith({
      run: null,
      busy: false,
      error: expect.stringContaining("上一轮查询已失效"),
    });
    expect(screen.queryByRole("button", { name: "重新核对" })).toBeNull();
    expect(screen.queryByRole("button", { name: "停止后续步骤" })).toBeNull();
    await user.click(screen.getByRole("button", { name: "作为新问题发送" }));
    await screen.findByText("分析完成");
    expect(mocks.post.mock.calls[2][0]).toBe("/api/v1/agent/runs/submit");
    expect(mocks.post.mock.calls[2][1].body.question).toBe(child.question);
    expect(mocks.post.mock.calls[2][1].body).not.toHaveProperty(
      "parent_run_id",
    );
  });

  it("已读取的历史在再次GET时失效，用同一历史原问题显式重发而不是旁边的command", async () => {
    const user = userEvent.setup();
    const history = {
      ...completed,
      question: "历史中的原问题",
      parent_run_id: "parent",
    };
    mocks.get.mockResolvedValueOnce({ data: history }).mockResolvedValueOnce({
      error: {
        error: { code: "parent_context_unavailable", message: "expired" },
      },
    });
    mocks.post.mockResolvedValueOnce({
      data: { ...completed, id: "fresh", question: history.question },
    });
    render(
      <AgentReader
        {...props}
        presentation="progress"
        initialRunId={history.id}
        command={{
          id: "unrelated",
          question: "不应发送的另一个问题",
          parentRunId: "other",
        }}
      />,
    );
    await screen.findByText(history.question);
    await user.click(screen.getByText("查看依据与处理过程"));
    await user.click(screen.getByRole("button", { name: "刷新这次查询" }));
    await screen.findByRole("alert");
    expect(screen.getByText(history.question)).toBeTruthy();
    expect(mocks.post).not.toHaveBeenCalled();
    await user.click(screen.getByRole("button", { name: "作为新问题发送" }));
    await screen.findByText("分析完成");
    expect(mocks.post.mock.calls[0][1].body.question).toBe(history.question);
    expect(mocks.post.mock.calls[0][1].body).not.toHaveProperty(
      "parent_run_id",
    );
    expect(mocks.get).toHaveBeenCalledTimes(2);
  });

  it("首次历史GET失效且原问题未知时不给代发按钮，换历史不沿用上个问题", async () => {
    mocks.get.mockResolvedValueOnce({ data: completed }).mockResolvedValueOnce({
      error: {
        error: { code: "parent_context_unavailable", message: "expired" },
      },
    });
    const view = render(
      <AgentReader {...props} presentation="progress" initialRunId="r1" />,
    );
    await screen.findByText(completed.question);
    view.rerender(
      <AgentReader
        {...props}
        presentation="progress"
        initialRunId="unread-history"
        command={{ id: "unrelated", question: "别的问题" }}
      />,
    );
    expect((await screen.findByRole("alert")).textContent).toContain(
      "尚未读取到原问题",
    );
    expect(screen.queryByRole("button", { name: "作为新问题发送" })).toBeNull();
    expect(screen.queryByRole("button", { name: "重新核对" })).toBeNull();
    expect(screen.queryByText(completed.question)).toBeNull();
    expect(screen.queryByText("别的问题")).toBeNull();
    expect(mocks.post).not.toHaveBeenCalled();
  });

  it("显式恢复中断任务时父查询失效，同样提供一次无父重发入口", async () => {
    const user = userEvent.setup();
    mocks.get.mockResolvedValue({
      data: {
        ...ready,
        state: "interrupted",
        parent_run_id: "parent",
        error_code: "unknown",
      },
    });
    mocks.post
      .mockResolvedValueOnce({
        error: {
          error: { code: "parent_context_unavailable", message: "expired" },
        },
      })
      .mockResolvedValueOnce({ data: completed });
    render(
      <AgentReader {...props} presentation="progress" initialRunId="r1" />,
    );
    await user.click(await screen.findByRole("button", { name: "继续核对" }));
    await screen.findByText(
      "上一轮查询已失效或不在当前范围，请作为新问题发送。",
    );
    expect(mocks.post).toHaveBeenCalledOnce();
    expect(mocks.post.mock.calls[0][0]).toBe(
      "/api/v1/agent/runs/{run_id}/resume",
    );
    await user.click(screen.getByRole("button", { name: "作为新问题发送" }));
    await screen.findByText("分析完成");
    expect(mocks.post.mock.calls[1][1].body.question).toBe(ready.question);
    expect(mocks.post.mock.calls[1][1].body).not.toHaveProperty(
      "parent_run_id",
    );
  });

  it("旧范围迟到的父失效错误不能清除新历史或提供旧问题重发", async () => {
    const old = deferred<{
      error: { error: { code: string; message: string } };
    }>();
    mocks.get.mockReturnValueOnce(old.promise).mockResolvedValueOnce({
      data: { ...completed, id: "new", question: "新范围问题" },
    });
    const view = render(
      <AgentReader {...props} presentation="progress" initialRunId="old" />,
    );
    await waitFor(() => expect(mocks.get).toHaveBeenCalledOnce());
    view.rerender(
      <AgentReader
        {...props}
        organizationId="o2"
        presentation="progress"
        initialRunId="new"
      />,
    );
    await screen.findByText("新范围问题");
    await act(async () =>
      old.resolve({
        error: {
          error: { code: "parent_context_unavailable", message: "expired" },
        },
      }),
    );
    expect(screen.getByText("新范围问题")).toBeTruthy();
    expect(screen.queryByRole("alert")).toBeNull();
    expect(screen.queryByRole("button", { name: "作为新问题发送" })).toBeNull();
    expect(mocks.post).not.toHaveBeenCalled();
  });

  it("starts an explicitly submitted command once under StrictMode and ordinary rerenders", async () => {
    mocks.post
      .mockResolvedValueOnce({ data: ready })
      .mockResolvedValueOnce({ data: completed });
    const view = render(
      <StrictMode>
        <AgentReader {...props} initialQuestion="  合成验收问题  " autoStart />
      </StrictMode>,
    );
    await screen.findByText("分析完成");
    expect(mocks.post.mock.calls.map((call) => call[0])).toEqual([
      "/api/v1/agent/runs/submit",
      "/api/v1/agent/runs/{run_id}/advance",
    ]);
    expect(mocks.post.mock.calls[0][1].body.question).toBe("合成验收问题");
    expect(props.onAnswer).toHaveBeenCalledExactlyOnceWith(
      ready.question,
      completed.answer,
    );
    view.rerender(
      <StrictMode>
        <AgentReader
          {...props}
          initialQuestion="  合成验收问题  "
          autoStart
          onDraft={vi.fn()}
        />
      </StrictMode>,
    );
    await act(async () => {});
    expect(mocks.post).toHaveBeenCalledTimes(2);
  });

  it("shows automatic command errors without retrying and retains the question for an explicit retry", async () => {
    mocks.post.mockRejectedValue(new Error("当前企业没有可用的模型连接"));
    const view = render(
      <AgentReader {...props} initialQuestion="核实交付" autoStart />,
    );
    expect((await screen.findByRole("alert")).textContent).toContain(
      "当前企业没有可用的模型连接",
    );
    expect(
      (screen.getByLabelText("让 coRoof 继续查询") as HTMLTextAreaElement)
        .value,
    ).toBe("核实交付");
    view.rerender(
      <AgentReader {...props} initialQuestion="核实交付" autoStart />,
    );
    await act(async () => {});
    expect(mocks.post).toHaveBeenCalledOnce();
  });

  it("does not automatically send an empty command", async () => {
    render(<AgentReader {...props} initialQuestion="  " autoStart />);
    await waitFor(() => expect(mocks.get).toHaveBeenCalled());
    expect(mocks.post).not.toHaveBeenCalled();
  });

  it("retains a contextual suggested question without starting a model call", async () => {
    render(
      <AgentReader
        {...props}
        workId="w1"
        initialQuestion="请核实客户资料缺口"
      />,
    );
    await waitFor(() => expect(mocks.get).toHaveBeenCalled());
    expect(
      (screen.getByLabelText("让 coRoof 继续查询") as HTMLTextAreaElement)
        .value,
    ).toBe("请核实客户资料缺口");
    expect(mocks.post).not.toHaveBeenCalled();
  });
  it("只有明确提问才调用模型，按服务器状态串行推进并返回引用答案", async () => {
    const user = userEvent.setup();
    mocks.post
      .mockResolvedValueOnce({ data: ready })
      .mockResolvedValueOnce({
        data: {
          ...ready,
          version: 3,
          step_count: 1,
          steps: [
            {
              ...running.steps[0],
              state: "succeeded",
              capability: "company.overview",
            },
          ],
        },
      })
      .mockResolvedValueOnce({ data: completed });
    render(<AgentReader {...props} />);
    expect(mocks.post).not.toHaveBeenCalled();
    await start(user);
    await screen.findByText("分析完成");
    expect(props.onAnswer).toHaveBeenCalledExactlyOnceWith(
      ready.question,
      completed.answer,
    );
    expect(mocks.post.mock.calls.map((call) => call[0])).toEqual([
      "/api/v1/agent/runs/submit",
      "/api/v1/agent/runs/{run_id}/advance",
      "/api/v1/agent/runs/{run_id}/advance",
    ]);
    expect(mocks.post.mock.calls[2][1].body.expected_version).toBe(3);
    expect(mocks.post.mock.calls[1][1].params.header["x-organization-id"]).toBe(
      "o1",
    );
  });

  it("执行中取消阻止继续，迟到的成功响应不能显示或启动新步骤", async () => {
    const user = userEvent.setup();
    let resolveAdvance!: (value: unknown) => void;
    mocks.post
      .mockResolvedValueOnce({ data: ready })
      .mockImplementationOnce(
        () =>
          new Promise((resolve) => {
            resolveAdvance = resolve;
          }),
      )
      .mockResolvedValueOnce({
        data: {
          ...running,
          state: "cancelled",
          version: 3,
          error_code: "cancelled",
        },
      });
    mocks.get.mockImplementation(async (path) => ({
      data: path.endsWith("/{run_id}") ? running : [],
    }));
    render(<AgentReader {...props} />);
    await start(user);
    await waitFor(() => expect(mocks.post).toHaveBeenCalledTimes(2));
    await user.click(screen.getByRole("button", { name: "取消任务" }));
    await screen.findByText("已取消");
    await act(async () => resolveAdvance({ data: completed }));
    expect(props.onAnswer).not.toHaveBeenCalled();
    expect(mocks.post).toHaveBeenCalledTimes(3);
    expect(screen.queryByText("分析完成")).toBeNull();
  });

  it("响应丢失后先读取已持久化结果，不自动重复模型请求", async () => {
    const user = userEvent.setup();
    mocks.post
      .mockResolvedValueOnce({ data: ready })
      .mockRejectedValueOnce(new Error("网络中断"));
    mocks.get.mockImplementation(async (path) => ({
      data: path.endsWith("/{run_id}") ? completed : [],
    }));
    render(<AgentReader {...props} />);
    await start(user);
    await screen.findByText("网络中断");
    await user.click(screen.getByRole("button", { name: "刷新任务" }));
    await screen.findByText("分析完成");
    expect(mocks.post).toHaveBeenCalledTimes(2);
    expect(props.onAnswer).toHaveBeenCalledOnce();
  });

  it("切换企业后丢弃旧响应，不能继续发送旧任务步骤", async () => {
    const user = userEvent.setup();
    let finish!: (value: unknown) => void;
    mocks.post.mockResolvedValueOnce({ data: ready }).mockImplementationOnce(
      () =>
        new Promise((resolve) => {
          finish = resolve;
        }),
    );
    const view = render(<AgentReader {...props} />);
    await start(user);
    await waitFor(() => expect(mocks.post).toHaveBeenCalledTimes(2));
    view.rerender(<AgentReader {...props} organizationId="o2" />);
    await act(async () => finish({ data: completed }));
    expect(props.onAnswer).not.toHaveBeenCalled();
    expect(screen.queryByText("合成验收问题")).toBeNull();
    expect(mocks.post).toHaveBeenCalledTimes(2);
  });

  it("中断任务需要明确继续，未知步骤保留且不自动重放", async () => {
    const user = userEvent.setup();
    const interrupted = {
      ...running,
      state: "interrupted",
      version: 3,
      error_code: "unknown",
      steps: [{ ...running.steps[0], state: "unknown", error_code: "unknown" }],
    };
    mocks.get.mockImplementation(async (path) => ({
      data: path.endsWith("/{run_id}") ? interrupted : [interrupted],
    }));
    mocks.post
      .mockResolvedValueOnce({
        data: { ...interrupted, state: "ready", version: 4 },
      })
      .mockResolvedValueOnce({ data: completed });
    render(<AgentReader {...props} />);
    await user.click(
      await screen.findByRole("button", { name: /合成验收问题 · 执行中断/ }),
    );
    await screen.findByRole("button", { name: "确认继续剩余步骤" });
    expect(mocks.post).not.toHaveBeenCalled();
    await user.click(screen.getByRole("button", { name: "确认继续剩余步骤" }));
    await screen.findByText("分析完成");
    expect(mocks.post.mock.calls[0][0]).toBe(
      "/api/v1/agent/runs/{run_id}/resume",
    );
    expect(mocks.post.mock.calls[1][1].body.expected_version).toBe(4);
  });
});

describe("后台交互任务", () => {
  const queued: Schemas["RunOut"] = {
    ...ready,
    execution: { state: "queued", updated_at: time },
  };
  const finished: Schemas["RunOut"] = {
    ...completed,
    execution: { state: "stopped", updated_at: time },
  };
  it("一次提交后只读进度，服务端结束后显示答案，不由浏览器推进模型", async () => {
    vi.useFakeTimers();
    const onStateChange = vi.fn();
    mocks.post.mockResolvedValue({ data: queued });
    mocks.get.mockResolvedValue({ data: finished });
    render(
      <AgentReader
        {...props}
        presentation="progress"
        command={{ id: "background", question: ready.question }}
        onStateChange={onStateChange}
      />,
    );
    await act(async () => {});
    expect(screen.getByText("已收到，正在安排处理…")).toBeTruthy();
    expect(onStateChange.mock.calls.at(-1)?.[0].busy).toBe(true);
    expect(screen.queryByRole("button", { name: "继续核对" })).toBeNull();
    await act(async () => vi.advanceTimersByTimeAsync(1250));
    expect(props.onAnswer).toHaveBeenCalledExactlyOnceWith(
      ready.question,
      completed.answer,
    );
    expect(mocks.post.mock.calls.map((call) => call[0])).toEqual([
      "/api/v1/agent/runs/submit",
    ]);
    expect(onStateChange.mock.calls.at(-1)?.[0].busy).toBe(false);
  });
  it("刷新后读取正在处理的任务并继续观察，不重新提交", async () => {
    vi.useFakeTimers();
    mocks.get
      .mockResolvedValueOnce({ data: queued })
      .mockResolvedValueOnce({ data: finished });
    render(
      <AgentReader
        {...props}
        presentation="progress"
        initialRunId={ready.id}
      />,
    );
    await act(async () => {});
    await act(async () => vi.advanceTimersByTimeAsync(1250));
    expect(props.onAnswer).toHaveBeenCalledOnce();
    expect(mocks.post).not.toHaveBeenCalled();
  });
  it("进度读取失权后停止轮询并清除任务，不自动重新发送", async () => {
    vi.useFakeTimers();
    const onStateChange = vi.fn();
    mocks.post.mockResolvedValue({ data: queued });
    mocks.get.mockRejectedValue(new Error("任务权限已失效"));
    render(
      <AgentReader
        {...props}
        presentation="progress"
        command={{ id: "revoked", question: ready.question }}
        onStateChange={onStateChange}
      />,
    );
    await act(async () => {});
    await act(async () => vi.advanceTimersByTimeAsync(1250));
    expect(onStateChange).toHaveBeenLastCalledWith({
      run: null,
      busy: false,
      error: "任务权限已失效",
    });
    await act(async () => vi.advanceTimersByTimeAsync(5000));
    expect(mocks.get).toHaveBeenCalledTimes(1);
    expect(mocks.post).toHaveBeenCalledTimes(1);
  });
  it("切换企业后旧任务的迟到进度不进入新页面", async () => {
    vi.useFakeTimers();
    const response = deferred<{ data: Schemas["RunOut"] }>();
    mocks.post.mockResolvedValue({ data: queued });
    mocks.get.mockReturnValue(response.promise);
    const view = render(
      <AgentReader
        {...props}
        presentation="progress"
        command={{ id: "old", question: ready.question }}
      />,
    );
    await act(async () => {});
    await act(async () => vi.advanceTimersByTimeAsync(1250));
    view.rerender(
      <AgentReader {...props} organizationId="other" presentation="progress" />,
    );
    await act(async () => response.resolve({ data: finished }));
    expect(props.onAnswer).not.toHaveBeenCalled();
    expect(screen.queryByText(ready.question)).toBeNull();
  });
});

it("后台任务取消未确认后允许只读核对，不永久卡在忙碌状态", async () => {
  const user = userEvent.setup();
  const queued: Schemas["RunOut"] = {
    ...ready,
    execution: { state: "queued", updated_at: time },
  };
  const onStateChange = vi.fn();
  mocks.post
    .mockResolvedValueOnce({ data: queued })
    .mockRejectedValueOnce(new Error("取消未确认"));
  mocks.get
    .mockResolvedValueOnce({ data: queued })
    .mockResolvedValueOnce({ data: completed });
  render(
    <AgentReader
      {...props}
      presentation="progress"
      command={{ id: "cancel-unconfirmed", question: ready.question }}
      onStateChange={onStateChange}
    />,
  );
  await user.click(await screen.findByRole("button", { name: "停止后续步骤" }));
  await screen.findByText("取消未确认");
  expect(onStateChange.mock.calls.at(-1)?.[0]).toMatchObject({
    run: null,
    busy: false,
  });
  await user.click(screen.getByRole("button", { name: "重新核对" }));
  await screen.findByText("分析完成");
  expect(mocks.post).toHaveBeenCalledTimes(2);
});
