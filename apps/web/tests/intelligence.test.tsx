import { act, render, screen, waitFor } from "@testing-library/react";
import { StrictMode } from "react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { Schemas, Work } from "../lib/api";
import { AiAssistant } from "../components/intelligence";
import { DecisionDetail } from "../components/decisions";

const mocks = vi.hoisted(() => ({ get: vi.fn(), post: vi.fn() }));
vi.mock("../lib/api", async (importOriginal) => ({
  ...(await importOriginal<object>()),
  api: () => ({ GET: mocks.get, POST: mocks.post }),
}));
const time = "2026-11-03T08:00:00Z";
const work: Work = {
  id: "w1",
  organization_id: "o1",
  title: "客户资料交付",
  description: null,
  department_id: "d1",
  initiative_id: null,
  owner_id: "m1",
  due_at: null,
  lifecycle_status: "planned",
  needs_support: true,
  source_authority: "native",
  version: 2,
  updated_at: time,
};
const evidence: Schemas["EvidenceOut"] = {
  id: "e1",
  work_item_id: work.id,
  work_version: work.version,
  event_id: "event1",
  facts: work,
  excerpt: "客户资料晚到，需要交付协调",
  source_at: time,
  captured_at: time,
  outdated: false,
};
const options: Schemas["Option"][] = [
  {
    id: "verify",
    title: "先核实事实",
    plan: "与负责人核实资料到位情况",
    tradeoff: "需要等待负责人确认",
  },
];
const answer: Schemas["AnswerOut"] = {
  id: "a1",
  mode: "rules",
  notice: "模型尚未配置，未调用模型。",
  summary: "已记录的工作有支持需求。",
  suggestions: [
    {
      work_item_id: work.id,
      evidence_id: evidence.id,
      signal_id: null,
      signal_version: null,
      interpretation: "可以先核实，再决定如何协调。",
      options,
    },
  ],
  evidence: [evidence],
  signals: [],
  considered_work_count: 1,
  authorized_work_count: 1,
  generated_at: time,
  prompt_version: "evidence-qa-v1",
  provider: "rules",
  model: "rules",
};
const decision: Schemas["DecisionOut"] = {
  id: "dec1",
  work_item_id: work.id,
  signal_id: null,
  analysis_id: answer.id,
  actor_id: "m1",
  title: work.title,
  work_version: work.version,
  context_snapshot: {
    evidence,
    interpretation: answer.suggestions[0].interpretation,
    analysis_mode: "rules",
    analysis_time: new Date().toISOString(),
    signal_versions: {},
  },
  options,
  state: "pending",
  selected_option: null,
  selected_plan: null,
  follow_up: null,
  confirmed_by: null,
  confirmed_at: null,
  created_at: time,
  version: 1,
};
function page(items: unknown[] = []) {
  return { data: { items, total: items.length, offset: 0, limit: 20 } };
}
beforeEach(() => {
  vi.resetAllMocks();
  mocks.get.mockImplementation(async (path: string) => {
    if (path === "/api/v1/evidence/{evidence_id}") return { data: evidence };
    if (path === "/api/v1/decisions/{decision_id}") return { data: decision };
    if (path === "/api/v1/agent/runs") return { data: [] };
    return page();
  });
});
const props = {
  organizationId: "o1",
  timezone: "Asia/Shanghai",
  onUpdated: vi.fn().mockResolvedValue(undefined),
};

function completedRun(
  id: string,
  question: string,
  summary = "已核实当前记录。",
): Schemas["RunOut"] {
  return {
    id,
    task: "read",
    work_item_id: work.id,
    question,
    state: "completed",
    version: 2,
    step_count: 1,
    max_steps: 6,
    steps: [],
    answer: { ...answer, id: `answer-${id}`, mode: "model", summary },
    draft: null,
    memory: null,
    error_code: null,
    created_at: time,
    deadline: time,
  };
}

describe("中央问答内容", () => {
  it("显式命令仅发送一次，不展示第二输入框、模式切换或历史入口", async () => {
    const run = completedRun("floating-run", "核对交付");
    const state = vi.fn();
    let finish!: (value: { data: Schemas["RunOut"] }) => void;
    mocks.post.mockReturnValue(
      new Promise((resolve) => {
        finish = resolve;
      }),
    );
    render(
      <StrictMode>
        <AiAssistant
          {...props}
          presentation="floating"
          command={{ id: "send-1", question: run.question }}
          onStateChange={state}
          canDecide={false}
        />
      </StrictMode>,
    );
    await waitFor(() =>
      expect(state).toHaveBeenCalledWith(
        expect.objectContaining({ busy: true }),
      ),
    );
    await act(async () => finish({ data: run }));
    await screen.findByText(run.answer!.summary);
    expect(screen.getAllByText(run.question)).toHaveLength(1);
    expect(
      screen.getByText(answer.suggestions[0].interpretation).closest("details"),
    ).toBeNull();
    expect(screen.getByText(run.answer!.summary).closest("details")?.open).toBe(
      false,
    );
    expect(
      screen.getByRole("button", { name: "刷新这次查询" }).closest("details")
        ?.open,
    ).toBe(false);
    expect(document.querySelectorAll("details")).toHaveLength(1);
    expect(screen.queryByRole("textbox")).toBeNull();
    expect(
      screen.queryByRole("button", { name: /快速整理|连续查询|开始查询/ }),
    ).toBeNull();
    expect(screen.queryByText("最近查询")).toBeNull();
    expect(mocks.post).toHaveBeenCalledExactlyOnceWith(
      "/api/v1/agent/runs/submit",
      expect.objectContaining({
        body: expect.objectContaining({ question: run.question, task: "read" }),
      }),
    );
    expect(state).toHaveBeenCalledWith(expect.objectContaining({ busy: true }));
    await waitFor(() =>
      expect(state).toHaveBeenLastCalledWith({ run, busy: false, error: "" }),
    );
    expect(screen.queryByRole("button", { name: "处理这件事" })).toBeNull();
    expect(mocks.get).not.toHaveBeenCalledWith(
      "/api/v1/agent/runs",
      expect.anything(),
    );
  });

  it("新命令立即清旧答复，同一command重渲染不重复查询或循环上报状态", async () => {
    const first = completedRun("first", "第一个问题", "第一份答复");
    const next = completedRun("next", "第二个问题", "第二份答复");
    let finish!: (value: { data: Schemas["RunOut"] }) => void;
    mocks.post.mockResolvedValueOnce({ data: first }).mockReturnValueOnce(
      new Promise((resolve) => {
        finish = resolve;
      }),
    );
    const state = vi.fn();
    const view = render(
      <AiAssistant
        {...props}
        presentation="floating"
        command={{ id: "one", question: first.question }}
        onStateChange={state}
        canDecide={false}
      />,
    );
    await screen.findByText("第一份答复");
    view.rerender(
      <AiAssistant
        {...props}
        presentation="floating"
        command={{ id: "two", question: next.question }}
        onStateChange={(value) => state(value)}
        canDecide={false}
      />,
    );
    expect(screen.queryByText("第一份答复")).toBeNull();
    await waitFor(() => expect(mocks.post).toHaveBeenCalledTimes(2));
    await act(async () => finish({ data: next }));
    await screen.findByText("第二份答复");
    await waitFor(() =>
      expect(state).toHaveBeenLastCalledWith({
        run: next,
        busy: false,
        error: "",
      }),
    );
    const reported = state.mock.calls.length;
    view.rerender(
      <AiAssistant
        {...props}
        presentation="floating"
        command={{ id: "two", question: next.question }}
        onStateChange={(value) => state(value)}
        canDecide={false}
      />,
    );
    expect(mocks.post).toHaveBeenCalledTimes(2);
    expect(state).toHaveBeenCalledTimes(reported);
    expect(screen.queryByText("第一份答复")).toBeNull();
  });

  it("查看历史只GET既有运行，依据和准备方案交给原详情，失败重试保持幂等", async () => {
    const user = userEvent.setup();
    const run = completedRun("history-run", "历史问题");
    const onDecision = vi.fn();
    const onEvidence = vi.fn();
    mocks.get.mockResolvedValue({ data: run });
    mocks.post
      .mockRejectedValueOnce(new Error("暂时无法准备方案"))
      .mockResolvedValueOnce({ data: decision });
    render(
      <AiAssistant
        {...props}
        work={work}
        presentation="floating"
        initialRunId={run.id}
        canDecide
        onDecision={onDecision}
        onEvidence={onEvidence}
      />,
    );
    await screen.findByText(run.answer!.summary);
    expect(mocks.get).toHaveBeenCalledExactlyOnceWith(
      "/api/v1/agent/runs/{run_id}",
      expect.objectContaining({
        params: {
          header: { "x-organization-id": "o1" },
          path: { run_id: run.id },
        },
      }),
    );
    expect(mocks.post).not.toHaveBeenCalled();
    await user.click(screen.getByText("查看依据与处理过程"));
    await user.click(
      screen.getByRole("button", { name: /查看原始依据：客户资料交付/ }),
    );
    expect(onEvidence).toHaveBeenCalledWith("e1");
    expect(mocks.get).toHaveBeenCalledOnce();
    await user.click(screen.getByRole("button", { name: "处理这件事" }));
    await screen.findByRole("alert");
    await user.click(screen.getByRole("button", { name: "处理这件事" }));
    await waitFor(() => expect(onDecision).toHaveBeenCalledWith("dec1"));
    expect(mocks.post.mock.calls.map((call) => call[0])).toEqual([
      "/api/v1/decisions",
      "/api/v1/decisions",
    ]);
    expect(mocks.post.mock.calls[0][1].body).toEqual(
      mocks.post.mock.calls[1][1].body,
    );
    expect(screen.queryByRole("button", { name: "确认方案并记录" })).toBeNull();
    expect(screen.getByText(run.answer!.summary)).toBeTruthy();
  });

  it("模型配置失败如实上报，不自动调用快速整理或改用规则", async () => {
    const run = {
      ...completedRun("failed", "检查进展"),
      state: "failed",
      answer: null,
      error_code: "not_configured",
    };
    const state = vi.fn();
    mocks.post.mockResolvedValue({ data: run });
    render(
      <AiAssistant
        {...props}
        presentation="floating"
        command={{ id: "failed-command", question: run.question }}
        onStateChange={state}
        canDecide={false}
      />,
    );
    await waitFor(() =>
      expect(state).toHaveBeenLastCalledWith(
        expect.objectContaining({
          busy: false,
          error: expect.stringMatching(/模型|配置/),
        }),
      ),
    );
    expect(mocks.post.mock.calls.map((call) => call[0])).toEqual([
      "/api/v1/agent/runs/submit",
    ]);
    expect(screen.queryByText("规则整理 · 非 AI")).toBeNull();
    expect(screen.queryByRole("button", { name: "快速整理" })).toBeNull();
  });

  it("历史重新读取失权后清除原答复，恢复读取不依赖再次调用模型", async () => {
    const user = userEvent.setup();
    const run = completedRun("history-recheck", "已保存的问题");
    mocks.get
      .mockResolvedValueOnce({ data: run })
      .mockRejectedValueOnce(new Error("当前无权读取此查询"))
      .mockResolvedValueOnce({ data: run });
    render(
      <AiAssistant
        {...props}
        presentation="floating"
        initialRunId={run.id}
        canDecide={false}
      />,
    );
    await screen.findByText(run.answer!.summary);
    await user.click(screen.getByText("查看依据与处理过程"));
    await user.click(screen.getByRole("button", { name: "刷新这次查询" }));
    await screen.findByText("当前无权读取此查询");
    expect(screen.queryByText(run.answer!.summary)).toBeNull();
    await user.click(screen.getByRole("button", { name: "重新核对" }));
    await screen.findByText(run.answer!.summary);
    expect(mocks.post).not.toHaveBeenCalled();
  });

  it("关闭浮层后迟到的准备结果不再打开其他范围的详情", async () => {
    const user = userEvent.setup();
    const run = completedRun("history-prepare", "待准备的问题");
    let finish!: (value: { data: Schemas["DecisionOut"] }) => void;
    mocks.get.mockResolvedValue({ data: run });
    mocks.post.mockReturnValue(
      new Promise((resolve) => {
        finish = resolve;
      }),
    );
    const onDecision = vi.fn();
    const view = render(
      <AiAssistant
        {...props}
        presentation="floating"
        initialRunId={run.id}
        canDecide
        onDecision={onDecision}
      />,
    );
    await user.click(await screen.findByRole("button", { name: "处理这件事" }));
    view.unmount();
    await act(async () => finish({ data: decision }));
    expect(onDecision).not.toHaveBeenCalled();
  });
  it("目录答复直接列出授权资料，打开原文只回调，不伪装检索正文或生成处理方案", async () => {
    const user = userEvent.setup();
    const onDocument = vi.fn();
    const run = completedRun("catalog", "有哪些文档");
    run.answer = {
      ...answer,
      suggestions: [],
      evidence: [],
      summary: "当前有 1 份可查看的已发布文档。",
      knowledge_inventory: {
        items: [
          {
            document_id: "doc-1",
            revision_id: "rev-2",
            revision_number: 2,
            title: "项目交付说明",
            source_at: time,
          },
        ],
        total: 1,
        limit: 20,
        truncated: false,
        notice: "仅列目录，未读取正文。",
      },
    };
    mocks.get.mockResolvedValue({ data: run });
    render(
      <AiAssistant
        {...props}
        presentation="floating"
        initialRunId={run.id}
        canDecide
        onDocument={onDocument}
      />,
    );
    await screen.findByText(run.answer.summary);
    expect(screen.getByText("规则整理 · 非 AI").closest("details")).toBeNull();
    await user.click(screen.getByRole("button", { name: /项目交付说明/ }));
    expect(onDocument).toHaveBeenCalledExactlyOnceWith({
      document_id: "doc-1",
      revision_id: "rev-2",
    });
    expect(screen.queryByText(/尚无可支撑具体方案/)).toBeNull();
    expect(screen.queryByRole("button", { name: "处理这件事" })).toBeNull();
    expect(mocks.post).not.toHaveBeenCalled();
    expect(mocks.get).toHaveBeenCalledOnce();
  });

  it("文档答复展示已校验的原文并打开同一版本，不把原文当作已执行工作", async () => {
    const user = userEvent.setup();
    const onDocument = vi.fn();
    const run = completedRun("doc-answer", "交付前要核对什么");
    const source: Schemas["Citation"] = {
      id: "cite-1",
      document_id: "doc-1",
      revision_id: "rev-3",
      revision_number: 3,
      title: "交付制度",
      excerpt: "交付前应核对客户资料。",
      start_offset: 0,
      end_offset: 12,
      source_at: time,
      file_name: null,
    };
    run.answer = {
      ...answer,
      suggestions: [],
      evidence: [],
      summary: "已找到相关资料原文。",
      documents: [source],
      document_answers: [{ citation_id: source.id, quote: source.excerpt }],
    };
    mocks.get.mockResolvedValue({ data: run });
    render(
      <AiAssistant
        {...props}
        presentation="floating"
        initialRunId={run.id}
        canDecide={false}
        onDocument={onDocument}
      />,
    );
    await screen.findByText(run.answer.summary);
    expect(
      screen
        .getAllByText(source.excerpt)
        .find((element) => !element.closest("details")),
    ).toBeTruthy();
    expect(
      screen
        .getByText("以下为相关原文片段，点击资料名称查看完整内容。")
        .closest("details"),
    ).toBeNull();
    await user.click(screen.getByRole("button", { name: "交付制度 · 版本 3" }));
    expect(onDocument).toHaveBeenCalledWith(
      expect.objectContaining({ document_id: "doc-1", revision_id: "rev-3" }),
    );
    expect(mocks.post).not.toHaveBeenCalled();
  });

  it.each(["floating", "default"] as const)(
    "%s 原文检索明确未调用模型，不误标AI建议或规则整理",
    async (presentation) => {
      const run = completedRun("retrieved", "里面写了什么");
      run.answer = {
        ...answer,
        mode: "retrieval",
        provider: "knowledge_retrieval",
        model: "none",
        suggestions: [],
        evidence: [],
        summary: "检索到以下原文片段。",
        notice: "最多展示 3 个相关原文片段，不代表全文。",
        documents: [
          {
            id: "cite",
            document_id: "doc",
            revision_id: "rev",
            revision_number: 1,
            title: "交付规范",
            excerpt: "交付前核对客户资料。",
            start_offset: 0,
            end_offset: 11,
            source_at: time,
            file_name: null,
          },
        ],
        document_answers: [
          { citation_id: "cite", quote: "交付前核对客户资料。" },
        ],
      };
      mocks.get.mockImplementation(async (path: string) => ({
        data: path === "/api/v1/agent/runs/{run_id}" ? run : [],
      }));
      render(
        <AiAssistant
          {...props}
          presentation={presentation}
          initialRunId={run.id}
          canDecide={false}
          onDocument={vi.fn()}
        />,
      );
      await screen.findByText("原文检索 · 未调用模型");
      if (presentation === "floating") {
        expect(
          screen
            .getByText(run.answer.notice, { exact: false })
            .closest("details")?.open,
        ).toBe(false);
        expect(
          screen
            .getByText("以下为相关原文片段，点击资料名称查看完整内容。")
            .closest("details"),
        ).toBeNull();
      } else {
        expect(
          screen.getByText(run.answer.notice).closest("details"),
        ).toBeNull();
      }
      expect(screen.queryByText(/规则整理 · 非 AI|AI 建议/)).toBeNull();
      expect(mocks.post).not.toHaveBeenCalled();
    },
  );

  it("无匹配正文和空目录保留服务器说明，不伪造引用", async () => {
    const run = completedRun("empty-catalog", "找交付文档");
    run.answer = {
      ...answer,
      suggestions: [],
      evidence: [],
      summary: "未找到与本问题匹配的原文，当前也没有可查看的已发布文档。",
      knowledge_inventory: {
        items: [],
        total: 0,
        limit: 20,
        truncated: false,
        notice: "仅查看获授权目录。",
      },
    };
    mocks.get.mockResolvedValue({ data: run });
    render(
      <AiAssistant
        {...props}
        presentation="floating"
        initialRunId={run.id}
        canDecide={false}
        onDocument={vi.fn()}
      />,
    );
    expect(
      (await screen.findByText(run.answer.summary)).closest("details"),
    ).toBeNull();
    expect(screen.queryByRole("list", { name: "可查看的资料" })).toBeNull();
    expect(mocks.post).not.toHaveBeenCalled();
  });

  it("已变化的依据提示始终可见，更多事项和处理过程按需展开且不调用模型", async () => {
    const user = userEvent.setup();
    const run = completedRun("many", "需要做什么");
    run.answer = {
      ...answer,
      evidence: [{ ...evidence, outdated: true }],
      suggestions: Array.from({ length: 4 }, (_, index) => ({
        ...answer.suggestions[0],
        work_item_id: `work-${index}`,
        interpretation: `核对事项 ${index + 1}`,
      })),
    };
    mocks.get.mockResolvedValue({ data: run });
    render(
      <AiAssistant
        {...props}
        presentation="floating"
        initialRunId={run.id}
        canDecide={false}
      />,
    );
    const warning = await screen.findByRole("alert");
    expect(warning.textContent).toContain("部分工作记录已变化");
    expect(warning.closest("details")).toBeNull();
    expect(screen.getByText("核对事项 3").closest("details")).toBeNull();
    expect(screen.getByText("核对事项 4").closest("details")?.open).toBe(false);
    await user.click(screen.getByText("查看依据与处理过程"));
    expect(screen.getByText("核对事项 4").closest("details")?.open).toBe(true);
    expect(mocks.post).not.toHaveBeenCalled();
    expect(mocks.get).toHaveBeenCalledOnce();
  });
});

describe("依据问答与明确决策", () => {
  it("待确认方案可直接重新核对，无需先失败提交，打开入口不写入", async () => {
    const onReask = vi.fn();
    const user = userEvent.setup();
    render(
      <DecisionDetail
        {...props}
        id={decision.id}
        actorId="m1"
        onReask={onReask}
      />,
    );
    await user.click(
      await screen.findByRole("button", { name: "重新核对当前记录" }),
    );
    expect(onReask).toHaveBeenCalledWith(work.id);
    expect(mocks.post).not.toHaveBeenCalled();
  });

  it("consumes an explicit command once, including after switching query modes", async () => {
    const user = userEvent.setup();
    mocks.post.mockResolvedValue({
      data: {
        id: "command-run",
        task: "read",
        question: "核实交付",
        state: "completed",
        version: 2,
        step_count: 1,
        max_steps: 6,
        steps: [],
        answer,
        draft: null,
        error_code: null,
        created_at: time,
        deadline: time,
      },
    });
    render(
      <AiAssistant
        {...props}
        work={work}
        canDecide
        initialQuestion="核实交付"
        autoStart
      />,
    );
    await screen.findByText(answer.summary);
    expect(mocks.post).toHaveBeenCalledExactlyOnceWith(
      "/api/v1/agent/runs/submit",
      expect.objectContaining({
        body: expect.objectContaining({
          question: "核实交付",
          task: "read",
          work_item_id: "w1",
        }),
      }),
    );
    await user.click(screen.getByRole("button", { name: "快速整理" }));
    await user.click(screen.getByRole("button", { name: "连续查询" }));
    await waitFor(() => expect(mocks.get).toHaveBeenCalledTimes(2));
    expect(mocks.post).toHaveBeenCalledOnce();
    expect(screen.getByRole("button", { name: "处理这件事" })).toBeTruthy();
  });

  it("打开入口不会请求模型，提问携带事项上下文，依据可回看，准备不等于确认", async () => {
    const user = userEvent.setup();
    mocks.post.mockImplementation(async (path: string) => ({
      data: path === "/api/v1/ai/ask" ? answer : decision,
    }));
    render(<AiAssistant {...props} work={work} canDecide />);
    expect(mocks.post).not.toHaveBeenCalled();
    await user.click(screen.getByRole("button", { name: "快速整理" }));
    await user.click(
      screen.getByRole("button", { name: "这件事为什么需要关注？" }),
    );
    expect(mocks.post.mock.calls[0][1].body).toEqual({
      question: "这件事为什么需要关注？",
      work_item_id: "w1",
    });
    expect(await screen.findByText("规则整理 · 非 AI")).toBeTruthy();
    await user.click(screen.getByRole("button", { name: "查看原始依据" }));
    expect(await screen.findByText(evidence.excerpt)).toBeTruthy();
    expect(screen.getByText("来源：coRoof 工作记录 · 版本 2")).toBeTruthy();
    await user.click(screen.getByRole("button", { name: "返回问答" }));
    await user.click(screen.getByRole("button", { name: "处理这件事" }));
    const confirm = await screen.findByRole("button", {
      name: "确认这个安排",
    });
    expect(confirm.hasAttribute("disabled")).toBe(false);
    expect((screen.getByRole("radio") as HTMLInputElement).checked).toBe(true);
    expect(screen.getByText("修改这个安排").closest("details")?.open).toBe(
      false,
    );
    expect(mocks.post.mock.calls.map((call) => call[0])).toEqual([
      "/api/v1/ai/ask",
      "/api/v1/decisions",
    ]);
    expect(mocks.post.mock.calls[1][1].body.idempotency_key).toHaveLength(36);
  });

  it("默认提供可核对的安排，打开不提交，明确确认只保存一次", async () => {
    const user = userEvent.setup();
    let finish!: (result: unknown) => void;
    mocks.post.mockReturnValue(
      new Promise((resolve) => {
        finish = resolve;
      }),
    );
    render(<DecisionDetail {...props} id="dec1" actorId="m1" />);
    const confirm = await screen.findByRole("button", { name: "确认这个安排" });
    expect(confirm.hasAttribute("disabled")).toBe(false);
    expect(
      screen.getByRole("region", { name: "请确认的安排" }).textContent,
    ).toContain(options[0].plan);
    expect(
      screen.getByRole("region", { name: "请确认的安排" }).textContent,
    ).toContain("与事项负责人核实进展后，补充实际结果。");
    expect(screen.getByText("修改这个安排").closest("details")?.open).toBe(
      false,
    );
    expect(
      screen.getByText("查看当时的事实与建议").closest("details")?.open,
    ).toBe(false);
    expect(mocks.post).not.toHaveBeenCalled();
    await user.click(confirm);
    await user.click(screen.getByRole("button", { name: "正在保存…" }));
    expect(mocks.post).toHaveBeenCalledExactlyOnceWith(
      "/api/v1/decisions/{decision_id}/confirm",
      expect.objectContaining({
        body: {
          expected_version: 1,
          selected_option: "verify",
          selected_plan: options[0].plan,
          follow_up: "与事项负责人核实进展后，补充实际结果。",
        },
      }),
    );
    await act(async () =>
      finish({
        data: {
          ...decision,
          state: "confirmed",
          selected_option: "verify",
          selected_plan: options[0].plan,
          follow_up: "与事项负责人核实进展后，补充实际结果。",
          confirmed_by: "m1",
          confirmed_at: new Date().toISOString(),
          version: 2,
        },
      }),
    );
    await screen.findByText("方案已确认并记录，可以继续补充实际跟进结果。");
    expect(props.onUpdated).toHaveBeenCalledOnce();
    expect(mocks.post).toHaveBeenCalledOnce();
  });

  it("可展开修改安排，保存失败保留输入，不自动重试", async () => {
    const user = userEvent.setup();
    const reask = vi.fn();
    let finish!: (result: unknown) => void;
    mocks.post.mockReturnValue(
      new Promise((resolve) => {
        finish = resolve;
      }),
    );
    render(
      <DecisionDetail {...props} id="dec1" actorId="m1" onReask={reask} />,
    );
    await screen.findByRole("button", { name: "确认这个安排" });
    await user.click(screen.getByText("修改这个安排"));
    expect(mocks.post).not.toHaveBeenCalled();
    await user.clear(screen.getByLabelText("你的处理方案"));
    await user.type(
      screen.getByLabelText("你的处理方案"),
      "请交付负责人核对资料",
    );
    await user.clear(screen.getByLabelText("后续如何跟进"));
    expect(
      screen
        .getByRole("button", { name: "确认这个安排" })
        .hasAttribute("disabled"),
    ).toBe(true);
    await user.type(
      screen.getByLabelText("后续如何跟进"),
      "沟通后补充实际结果",
    );
    await user.click(screen.getByRole("button", { name: "确认这个安排" }));
    expect(mocks.post.mock.calls[0][1].body).toEqual({
      expected_version: 1,
      selected_option: "verify",
      selected_plan: "请交付负责人核对资料",
      follow_up: "沟通后补充实际结果",
    });
    await act(async () =>
      finish({ error: { error: { message: "工作已变化，请重新询问" } } }),
    );
    expect((await screen.findByRole("alert")).textContent).toContain(
      "工作已变化",
    );
    expect(screen.getByDisplayValue("请交付负责人核对资料")).toBeTruthy();
    expect(screen.getByDisplayValue("沟通后补充实际结果")).toBeTruthy();
    expect(screen.getByText("修改这个安排").closest("details")?.open).toBe(
      true,
    );
    expect(mocks.post).toHaveBeenCalledOnce();
    await user.click(screen.getByRole("button", { name: "重新核对当前记录" }));
    expect(reask).toHaveBeenCalledExactlyOnceWith("w1");
    expect(mocks.post).toHaveBeenCalledOnce();
  });

  it.each(["超过三十分钟", "工作记录过时"])(
    "%s 时只提供重新核对，不显示确认表单",
    async (reason) => {
      const user = userEvent.setup();
      const reask = vi.fn();
      const stale = {
        ...decision,
        context_snapshot: {
          ...decision.context_snapshot,
          analysis_time:
            reason === "超过三十分钟"
              ? new Date(Date.now() - 31 * 60 * 1000).toISOString()
              : new Date().toISOString(),
          evidence: { ...evidence, outdated: reason === "工作记录过时" },
        },
      };
      mocks.get.mockImplementation(async (path) =>
        path === "/api/v1/decisions/{decision_id}" ? { data: stale } : page(),
      );
      render(
        <DecisionDetail {...props} id="dec1" actorId="m1" onReask={reask} />,
      );
      await screen.findByText("这份建议已过时，需要先看看最新进展。");
      expect(screen.queryByRole("button", { name: "确认这个安排" })).toBeNull();
      expect(screen.queryByText("修改这个安排")).toBeNull();
      expect(screen.queryByLabelText("你的处理方案")).toBeNull();
      await user.click(
        screen.getByRole("button", { name: "重新核对当前记录" }),
      );
      expect(reask).toHaveBeenCalledExactlyOnceWith("w1");
      expect(mocks.post).not.toHaveBeenCalled();
    },
  );

  it("实际结果通过独立确认追加，带证据与稳定的重试标识", async () => {
    const user = userEvent.setup();
    mocks.get.mockImplementation(async (path: string) =>
      path === "/api/v1/decisions/{decision_id}"
        ? {
            data: {
              ...decision,
              state: "confirmed",
              selected_plan: options[0].plan,
              follow_up: "沟通后补充结果",
              confirmed_at: time,
            },
          }
        : page(),
    );
    mocks.post
      .mockResolvedValueOnce({
        error: { error: { message: "网络暂时不可用" } },
      })
      .mockResolvedValueOnce({ data: { id: "out1" } });
    render(<DecisionDetail {...props} id="dec1" />);
    await user.type(
      await screen.findByLabelText("记录实际结果"),
      "已沟通，资料仍未到位",
    );
    await user.click(screen.getByLabelText("引用决策时的工作记录"));
    await user.click(screen.getByRole("button", { name: "保存跟进结果" }));
    await screen.findByRole("alert");
    await user.click(screen.getByRole("button", { name: "保存跟进结果" }));
    await screen.findByText("实际结果已追加到决策记录。");
    expect(mocks.post.mock.calls[0][1].body).toEqual(
      mocks.post.mock.calls[1][1].body,
    );
    expect(mocks.post.mock.calls[1][1].body.evidence_refs).toEqual(["e1"]);
  });

  it("非老板能看问答，不能准备或查询决策记录", async () => {
    const user = userEvent.setup();
    mocks.post.mockResolvedValue({ data: answer });
    render(<AiAssistant {...props} work={work} canDecide={false} />);
    await user.click(screen.getByRole("button", { name: "快速整理" }));
    await user.click(screen.getByRole("button", { name: "有哪些处理方案？" }));
    await screen.findByText("规则整理 · 非 AI");
    expect(screen.queryByRole("button", { name: "处理这件事" })).toBeNull();
    expect(mocks.get).not.toHaveBeenCalledWith(
      "/api/v1/decisions",
      expect.anything(),
    );
  });
});

it("连续查询的引用建议可以准备决策，仍等待单独确认", async () => {
  const user = userEvent.setup();
  const ready = {
    id: "run1",
    state: "ready",
    task: "read",
    version: 1,
    question: "核对工作",
    step_count: 0,
    max_steps: 6,
    steps: [],
    answer: null,
    draft: null,
  };
  mocks.post
    .mockResolvedValueOnce({ data: ready })
    .mockResolvedValueOnce({
      data: {
        ...ready,
        state: "completed",
        version: 3,
        answer: { ...answer, mode: "model" },
      },
    })
    .mockResolvedValueOnce({ data: decision });
  render(<AiAssistant {...props} work={work} canDecide />);
  await user.type(screen.getByLabelText("让 coRoof 继续查询"), "核对工作");
  await user.click(screen.getByRole("button", { name: "开始查询" }));
  await user.click(await screen.findByRole("button", { name: "处理这件事" }));
  expect(
    (await screen.findByRole("button", { name: "确认这个安排" })).hasAttribute(
      "disabled",
    ),
  ).toBe(false);
  expect(screen.getByText("修改这个安排").closest("details")?.open).toBe(false);
  expect(mocks.post.mock.calls.map((call) => call[0])).toEqual([
    "/api/v1/agent/runs/submit",
    "/api/v1/agent/runs/{run_id}/advance",
    "/api/v1/decisions",
  ]);
});

it("他人准备的方案展示等待作者确认而不显示确认表单", async () => {
  render(
    <DecisionDetail {...props} id={decision.id} actorId="another-owner" />,
  );
  await screen.findByText("此方案等待准备者本人确认。");
  expect(screen.queryByRole("button", { name: "确认这个安排" })).toBeNull();
  expect(mocks.post).not.toHaveBeenCalled();
});
