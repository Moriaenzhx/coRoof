"use client";

import { useEffect, useRef, useState, type ReactNode } from "react";
import { RefreshCw, Send, Square } from "lucide-react";
import { api, unwrap, type Schemas } from "../lib/api";
import { CoRoofAvatar } from "./companion";
import { Feedback } from "./status";

type Run = Schemas["RunOut"];
export type AgentCommand = {
  id: string;
  question: string;
  parentRunId?: string;
};
export type AgentReaderState = {
  run: Run | null;
  busy: boolean;
  error: string;
};
const names: Record<string, string> = {
  "company.overview": "查看工作概况",
  "attention.explain": "核对关注事项",
  "work.investigate": "查看工作经过",
  "coverage.explain": "核对信息覆盖",
  "knowledge.search": "检索已发布文档",
  "knowledge.list": "查看已发布知识目录",
  "experience.reference": "参考已确认经验",
  "preference.read": "核对本人偏好",
};
const states: Record<Run["state"], string> = {
  ready: "可以继续读取",
  running: "正在分析下一步",
  completed: "分析完成",
  failed: "本次分析已停止",
  cancelled: "已取消",
  interrupted: "执行中断，结果待核对",
};
const errors: Record<string, string> = {
  not_configured: "尚未配置可用的企业模型，请在企业 AI 设置中核对。",
  model_disabled:
    "企业已停用模型服务，请由企业所有者在企业 AI 设置中选择并启用可用服务。",
  not_verified: "模型连接尚未通过测试，请先在企业 AI 设置中核对。",
  authentication: "模型服务身份验证失败，请让管理员核对 API Key。",
  permission: "模型服务拒绝访问，请让管理员核对账号与模型权限。",
  policy_denied: "当前服务配置不允许这次调用，请让管理员核对企业 AI 设置。",
  unsupported_capability:
    "当前查询或模型不支持所需能力，请让管理员核对模型配置。",
  invalid_request: "模型服务未接受这次请求，请让管理员核对模型与接口配置。",
  rate_limited: "模型服务请求受到限制，本次已停止，可稍后重新核对。",
  unavailable: "暂时无法连接模型服务，或服务暂不可用。可稍后重新核对。",
  refused: "模型服务未提供这次回答，请调整问题后重新发送。",
  truncated: "模型回答被截断，本次未完成。请缩小问题范围后重新发送。",
  response_too_large: "模型返回内容超过接收上限，请缩小问题范围后重新发送。",
  budget_exceeded:
    "本次任务达到处理上限，可能涉及步骤、时长或用量。请缩小范围，或让管理员核对额度。",
  no_progress: "重复读取没有带来新信息，已停止。请补充问题或工作记录。",
  invalid_output: "模型返回的提案未通过校验，未执行后续查询。",
  invalid_evidence: "回答的引用未通过校验，请重新核对记录。",
  access_revoked: "执行期间权限或记录发生变化，结果未返回。",
  unknown: "部分调用的结果未知，刷新后可确认是否继续。已有调用可能产生费用。",
  timeout: "本次模型请求超时，已停止。",
};
const unexplainedFailure =
  "本次查询未完成，暂时无法确认原因。请重新核对；若仍失败，请联系管理员。";

export function AgentReader({
  organizationId,
  workId,
  onAnswer,
  onDraft,
  onMemory,
  memoryId,
  task = "read",
  initialQuestion = "",
  autoStart = false,
  onAutoStart,
  presentation = "default",
  command,
  initialRunId,
  onStateChange,
  children,
  details,
}: {
  organizationId: string;
  workId?: string;
  initialQuestion?: string;
  autoStart?: boolean;
  onAutoStart?: () => void;
  onAnswer?: (question: string, answer: Schemas["AnswerOut"]) => void;
  onDraft?: (draft: Schemas["DraftOut"]) => void;
  task?: Schemas["RunInput"]["task"];
  memoryId?: string;
  onMemory?: (entry: Schemas["MemoryOut"]) => void;
  presentation?: "default" | "progress";
  command?: AgentCommand;
  initialRunId?: string;
  onStateChange?: (state: AgentReaderState) => void;
  children?: ReactNode;
  details?: ReactNode;
}) {
  const scope = JSON.stringify([
    organizationId,
    workId,
    task,
    memoryId,
    initialRunId,
  ]);
  const [stateScope, setStateScope] = useState(scope);
  const [question, setQuestion] = useState(initialQuestion);
  const [storedRow, setRow] = useState<Run | null>(null);
  const row = stateScope === scope ? storedRow : null;
  const serverRunning = Boolean(
    row?.execution &&
    row.execution.state !== "stopped" &&
    ["ready", "running"].includes(row.state),
  );
  const [recent, setRecent] = useState<Run[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [parentUnavailable, setParentUnavailable] = useState(false);
  const [parentQuestion, setParentQuestion] = useState("");
  const [phase, setPhase] = useState<
    "creating" | "reading" | "advancing" | "cancelling" | null
  >(null);
  const generation = useRef(0);
  const pending = useRef(false);
  const onAnswerRef = useRef(onAnswer);
  const onDraftRef = useRef(onDraft);
  const onMemoryRef = useRef(onMemory);
  const onAutoStartRef = useRef(onAutoStart);
  const onStateChangeRef = useRef(onStateChange);
  const autoStarted = useRef(false);
  const consumedCommands = useRef(new Set<string>());
  const stopBeforeCreate = useRef(false);
  const cancelling = useRef(false);
  const readTarget = useRef<string | undefined>(undefined);
  const knownRun = useRef<{ id: string; question: string } | null>(null);
  const delivered = useRef(new Set<string>());
  const requestKeys = useRef(new Map<string, string>());
  const createRequest = useRef({
    question: "",
    commandId: undefined as string | undefined,
    parentRunId: undefined as string | undefined,
    key: crypto.randomUUID(),
  });
  useEffect(() => {
    onAnswerRef.current = onAnswer;
    onDraftRef.current = onDraft;
    onMemoryRef.current = onMemory;
    onAutoStartRef.current = onAutoStart;
    onStateChangeRef.current = onStateChange;
  }, [onAnswer, onDraft, onMemory, onAutoStart, onStateChange]);
  useEffect(() => {
    ++generation.current;
    pending.current = false;
    stopBeforeCreate.current = false;
    cancelling.current = false;
    readTarget.current = undefined;
    knownRun.current = null;
    setParentUnavailable(false);
    setParentQuestion("");
    setStateScope(scope);
    setBusy(false);
    setPhase(null);
    setRow(null);
    setRecent([]);
    setQuestion(initialQuestion);
    setError("");
    delivered.current.clear();
    requestKeys.current.clear();
    createRequest.current = {
      question: "",
      commandId: undefined,
      parentRunId: undefined,
      key: crypto.randomUUID(),
    };
    return () => {
      generation.current++;
    };
  }, [scope]);
  useEffect(() => {
    if (presentation === "progress") return;
    const ticket = generation.current;
    let active = true;
    api(organizationId)
      .GET("/api/v1/agent/runs", {
        params: {
          header: { "x-organization-id": organizationId },
          query: { work_item_id: workId, task, memory_entry_id: memoryId },
        },
      })
      .then((result) => {
        if (active && ticket === generation.current) setRecent(unwrap(result));
      })
      .catch((e: Error) => {
        if (active && ticket === generation.current) setError(e.message);
      });
    return () => {
      active = false;
    };
  }, [organizationId, workId, task, memoryId, presentation]);
  useEffect(() => {
    if (!pending.current) setQuestion(initialQuestion);
  }, [initialQuestion]);
  useEffect(() => {
    const failure =
      row?.error_code && (row.state === "failed" || row.state === "interrupted")
        ? errors[row.error_code] || unexplainedFailure
        : "";
    onStateChangeRef.current?.({
      run: row,
      busy:
        stateScope === scope &&
        (busy || serverRunning || row?.state === "running"),
      error: stateScope === scope ? error || failure : "",
    });
  }, [row, busy, serverRunning, error, stateScope, scope]);
  useEffect(() => {
    if (!row || !serverRunning) return;
    const id = row.id;
    const ticket = generation.current;
    let disposed = false;
    let timer: ReturnType<typeof setTimeout>;
    const poll = async () => {
      if (disposed || ticket !== generation.current) return;
      if (pending.current || document.visibilityState === "hidden") {
        timer = setTimeout(poll, 1200);
        return;
      }
      try {
        const current = unwrapRun(
          await api(organizationId).GET("/api/v1/agent/runs/{run_id}", {
            params: params(id),
          }),
          ticket,
        );
        if (!disposed && ticket === generation.current) show(current);
      } catch (e) {
        if (!disposed && ticket === generation.current) {
          // Do not leave a previously authorized answer visible after a failed read.
          setRow(null);
          setError(
            e instanceof Error ? e.message : "暂时无法读取进展，请重新核对。",
          );
        }
      }
    };
    timer = setTimeout(poll, 1200);
    return () => {
      disposed = true;
      clearTimeout(timer);
    };
  }, [row, serverRunning, organizationId]);
  useEffect(() => {
    if (!initialRunId) return;
    let active = true;
    void Promise.resolve().then(() => {
      if (active) void refresh(initialRunId);
    });
    return () => {
      active = false;
    };
  }, [scope, initialRunId]);
  useEffect(() => {
    if (
      !command?.id ||
      !command.question.trim() ||
      initialRunId ||
      task !== "read"
    )
      return;
    let active = true;
    void Promise.resolve().then(() => {
      if (!active || consumedCommands.current.has(command.id)) return;
      consumedCommands.current.add(command.id);
      if (pending.current || serverRunning || row?.state === "running") {
        setError("已有任务正在进行，新问题尚未提交。完成后请重新发送。");
        return;
      }
      void start(command.question, command.id, command.parentRunId);
    });
    return () => {
      active = false;
    };
  }, [command?.id, command?.question, command?.parentRunId, scope]);
  useEffect(() => {
    if (
      !autoStart ||
      command ||
      initialRunId ||
      !initialQuestion.trim() ||
      task !== "read"
    )
      return;
    let active = true;
    // Defer until after effect replay: StrictMode's discarded setup must not
    // create a model run whose response is then invalidated by scope cleanup.
    void Promise.resolve().then(() => {
      if (!active || autoStarted.current) return;
      autoStarted.current = true;
      onAutoStartRef.current?.();
      void start(initialQuestion);
    });
    return () => {
      active = false;
    };
  }, [
    autoStart,
    initialQuestion,
    organizationId,
    workId,
    task,
    memoryId,
    command,
    initialRunId,
  ]);
  const params = (id: string) => ({
    header: { "x-organization-id": organizationId },
    path: { run_id: id },
  });
  function show(value: Run) {
    readTarget.current = value.id;
    knownRun.current = { id: value.id, question: value.question };
    setRow(value);
    if (
      value.draft &&
      value.draft.state === "pending" &&
      !delivered.current.has(value.id)
    ) {
      delivered.current.add(value.id);
      onDraftRef.current?.(value.draft);
    }
    if (value.memory && !delivered.current.has(value.id)) {
      delivered.current.add(value.id);
      onMemoryRef.current?.(value.memory);
    }
    if (value.answer && !delivered.current.has(value.id)) {
      delivered.current.add(value.id);
      onAnswerRef.current?.(value.question, value.answer);
    }
  }
  function unwrapRun<T>(
    result: { data?: T; error?: unknown },
    ticket: number,
    originalQuestion?: string,
  ): T {
    const failure = result.error as { error?: { code?: string } } | undefined;
    if (failure?.error?.code === "parent_context_unavailable") {
      if (ticket === generation.current) {
        setParentUnavailable(true);
        setParentQuestion(originalQuestion || "");
        setRow(null);
      }
      throw new Error(
        originalQuestion
          ? "上一轮查询已失效或不在当前范围，请作为新问题发送。"
          : "此历史查询的上下文已失效，尚未读取到原问题。请在下方重新输入问题。",
      );
    }
    return unwrap(result);
  }
  async function perform(action: (ticket: number) => Promise<void>) {
    if (pending.current) return;
    const ticket = generation.current;
    pending.current = true;
    setBusy(true);
    setError("");
    setParentUnavailable(false);
    setParentQuestion("");
    try {
      await action(ticket);
    } catch (e) {
      if (ticket === generation.current)
        setError(e instanceof Error ? e.message : "操作失败，请刷新任务");
    } finally {
      if (ticket === generation.current) {
        pending.current = false;
        setBusy(false);
        setPhase(null);
      }
    }
  }
  async function drive(current: Run, ticket: number) {
    if (ticket !== generation.current) return;
    show(current);
    // Submitted read tasks belong to the worker; the browser only observes them.
    if (current.execution) return;
    for (let n = 0; current.state === "ready" && n <= current.max_steps; n++) {
      if (ticket !== generation.current) return;
      setPhase("advancing");
      const attempt = `${current.id}:${current.version}`;
      if (!requestKeys.current.has(attempt))
        requestKeys.current.set(attempt, crypto.randomUUID());
      current = unwrapRun(
        await api(organizationId).POST("/api/v1/agent/runs/{run_id}/advance", {
          params: params(current.id),
          body: {
            expected_version: current.version,
            idempotency_key: requestKeys.current.get(attempt)!,
          },
        }),
        ticket,
        current.question,
      );
      if (ticket !== generation.current) return;
      show(current);
    }
  }
  async function start(
    input = question,
    commandId?: string,
    parentRunId?: string,
  ) {
    if (!input.trim() && task !== "memory_draft") return;
    await perform(async (ticket) => {
      setRow(null);
      readTarget.current = undefined;
      knownRun.current = null;
      setPhase("creating");
      stopBeforeCreate.current = false;
      const value =
        task === "memory_draft"
          ? "依据所选来源整理候选及适用条件，保留不确定信息。"
          : input.trim();
      if (
        createRequest.current.question !== value ||
        createRequest.current.commandId !== commandId ||
        createRequest.current.parentRunId !== parentRunId
      )
        createRequest.current = {
          question: value,
          commandId,
          parentRunId,
          key: crypto.randomUUID(),
        };
      setParentUnavailable(false);
      const response = await api(organizationId).POST(
        task === "read" ? "/api/v1/agent/runs/submit" : "/api/v1/agent/runs",
        {
          params: { header: { "x-organization-id": organizationId } },
          body: {
            question: value,
            task,
            work_item_id: workId,
            memory_entry_id: memoryId,
            ...(parentRunId ? { parent_run_id: parentRunId } : {}),
            idempotency_key: createRequest.current.key,
          },
        },
      );
      if (ticket !== generation.current) return;
      const created = unwrapRun<Run>(response, ticket, value);
      if (ticket === generation.current) {
        readTarget.current = created.id;
        knownRun.current = { id: created.id, question: created.question };
        setQuestion("");
        if (stopBeforeCreate.current) await cancelKnown(created.id, ticket);
        else await drive(created, ticket);
      }
    });
  }
  async function refresh(id: string) {
    await perform(async (ticket) => {
      readTarget.current = id;
      if (knownRun.current?.id !== id) knownRun.current = null;
      setPhase("reading");
      setRow(null);
      const current = unwrapRun(
        await api(organizationId).GET("/api/v1/agent/runs/{run_id}", {
          params: params(id),
        }),
        ticket,
        knownRun.current?.question,
      );
      if (ticket === generation.current) show(current);
    });
  }
  async function cancel() {
    if (cancelling.current) return;
    if (!row) {
      if (pending.current && phase === "creating") {
        stopBeforeCreate.current = true;
        setPhase("cancelling");
      }
      return;
    }
    // Stop local continuation immediately; late responses cannot restart the loop.
    const ticket = ++generation.current;
    pending.current = true;
    cancelling.current = true;
    setBusy(true);
    setPhase("cancelling");
    setError("");
    try {
      await cancelKnown(row.id, ticket);
    } catch (e) {
      if (ticket === generation.current) {
        setRow(null);
        setError(e instanceof Error ? e.message : "取消未确认，请刷新任务");
      }
    } finally {
      if (ticket === generation.current) {
        pending.current = false;
        cancelling.current = false;
        setBusy(false);
        setPhase(null);
      }
    }
  }
  async function cancelKnown(id: string, ticket: number) {
    let current = unwrapRun(
      await api(organizationId).GET("/api/v1/agent/runs/{run_id}", {
        params: params(id),
      }),
      ticket,
      knownRun.current?.id === id ? knownRun.current.question : undefined,
    );
    for (
      let attempt = 0;
      attempt < 2 &&
      ["ready", "running", "interrupted"].includes(current.state);
      attempt++
    ) {
      if (ticket !== generation.current) return;
      const response = await api(organizationId).POST(
        "/api/v1/agent/runs/{run_id}/cancel",
        {
          params: params(id),
          body: { expected_version: current.version },
        },
      );
      if (ticket !== generation.current) return;
      if (response.error?.error.code === "version_conflict" && attempt === 0) {
        current = unwrapRun(
          await api(organizationId).GET("/api/v1/agent/runs/{run_id}", {
            params: params(id),
          }),
          ticket,
          current.question,
        );
      } else {
        current = unwrap(response);
        break;
      }
    }
    if (ticket === generation.current) show(current);
  }
  async function continueReading() {
    if (!row) return;
    await perform(async (ticket) => {
      const current =
        row.state === "interrupted"
          ? unwrapRun(
              await api(organizationId).POST(
                "/api/v1/agent/runs/{run_id}/resume",
                {
                  params: params(row.id),
                  body: { expected_version: row.version },
                },
              ),
              ticket,
              row.question,
            )
          : row;
      if (ticket === generation.current) await drive(current, ticket);
    });
  }
  const failedMessage =
    error ||
    (row?.error_code && row.state !== "cancelled"
      ? errors[row.error_code] || unexplainedFailure
      : "");
  const configurationFailure = [
    "not_configured",
    "not_verified",
    "model_disabled",
  ].includes(row?.error_code || "");
  const currentQuestion =
    stateScope === scope
      ? row?.question ||
        parentQuestion ||
        (knownRun.current?.id === readTarget.current
          ? knownRun.current?.question
          : !readTarget.current
            ? createRequest.current.question
            : undefined)
      : undefined;
  const canStop =
    (busy && phase === "creating") ||
    (row && ["ready", "running", "interrupted"].includes(row.state));
  const process = row && (
    <>
      <p className="fine-print">
        已记录 {row.step_count} 轮 · 上限 {row.max_steps} 轮
      </p>
      {row.steps.length > 0 && (
        <ol className="agent-steps">
          {row.steps.map((step) => (
            <li key={step.id}>
              {step.capability
                ? names[step.capability] || "读取获授权记录"
                : "分析下一步"}{" "}
              ·{" "}
              {step.state === "succeeded"
                ? "已完成"
                : step.state === "pending"
                  ? "进行中"
                  : step.state === "unknown"
                    ? "结果未知"
                    : "未通过"}
            </li>
          ))}
        </ol>
      )}
    </>
  );
  const recovery = stateScope === scope &&
    !busy &&
    !serverRunning &&
    !configurationFailure &&
    (!parentUnavailable || Boolean(parentQuestion)) &&
    (error ||
      row?.state === "running" ||
      row?.state === "failed" ||
      row?.state === "interrupted" ||
      row?.state === "ready") && (
      <button
        className="secondary"
        onClick={() => {
          if (parentUnavailable) {
            void start(parentQuestion, crypto.randomUUID());
          } else if (error && (readTarget.current || initialRunId)) {
            void refresh(readTarget.current || initialRunId!);
          } else if (row?.state === "running") {
            void refresh(row.id);
          } else if (row?.state === "ready" || row?.state === "interrupted") {
            void continueReading();
          } else if (row?.state === "failed") {
            void start(
              row.question,
              crypto.randomUUID(),
              createRequest.current.parentRunId,
            );
          } else if (createRequest.current.question) {
            void start(
              createRequest.current.question,
              createRequest.current.commandId,
              createRequest.current.parentRunId,
            );
          }
        }}
      >
        {parentUnavailable
          ? "作为新问题发送"
          : row && !error && ["ready", "interrupted"].includes(row.state)
            ? "继续核对"
            : row?.state === "running" && !error
              ? "查看最新进展"
              : "重新核对"}
      </button>
    );
  const progressView = (
    <>
      {currentQuestion && (
        <p className="assistant-question">{currentQuestion}</p>
      )}
      {busy && (
        <p role="status" className="assistant-progress-line">
          {phase === "reading"
            ? "正在读取已保存的任务…"
            : phase === "cancelling"
              ? "正在停止后续步骤，等待服务器确认…"
              : phase === "creating"
                ? "正在创建查询任务…"
                : "正在核对相关记录…"}
        </p>
      )}
      {!busy && row && !children && !failedMessage && (
        <p role="status" className="assistant-progress-line">
          {serverRunning
            ? row.execution?.state === "queued"
              ? "已收到，正在安排处理…"
              : "正在核对相关记录，可以先做别的事…"
            : states[row.state]}
        </p>
      )}
      {failedMessage && <Feedback kind="error">{failedMessage}</Feedback>}
      {children}
      {(recovery || canStop || phase === "cancelling") && (
        <div className="assistant-recovery-actions">
          {recovery}
          {(canStop || phase === "cancelling") && (
            <button
              className="plain"
              disabled={phase === "cancelling"}
              onClick={() => void cancel()}
            >
              <Square size={13} aria-hidden="true" />
              停止后续步骤
            </button>
          )}
        </div>
      )}
      {row && (
        <details className="assistant-answer-details" key={row.id}>
          <summary>查看依据与处理过程</summary>
          <div className="assistant-answer-details-body">
            {details}
            {process}
            {!busy && !failedMessage && row.state === "completed" && (
              <button className="plain" onClick={() => void refresh(row.id)}>
                <RefreshCw size={13} aria-hidden="true" />
                刷新这次查询
              </button>
            )}
          </div>
        </details>
      )}
    </>
  );
  return (
    <div className="agent-reader" data-presentation={presentation}>
      {presentation === "progress" ? (
        progressView
      ) : (
        <>
          <p className="fine-print">
            {task === "memory_draft"
              ? "依据已选择的实际来源整理候选；不会自动确认或改变工作。"
              : task === "update_draft"
                ? "AI 整理你的原文，生成可编辑草稿。只有你明确确认后才更新工作。"
                : "根据你的问题查询获授权记录，展示依据与建议。业务变更仍需明确确认。"}
          </p>
          {recent.length > 0 && (
            <details className="answer-sources">
              <summary>
                {task === "update_draft" ? "最近的草稿任务" : "最近的查询任务"}
              </summary>
              {recent.map((item) => (
                <button
                  key={item.id}
                  className="evidence-link"
                  disabled={busy}
                  onClick={() => void refresh(item.id)}
                >
                  {item.question} · {states[item.state]}
                </button>
              ))}
            </details>
          )}
          {row && (
            <section className="agent-task" aria-label="查询任务进度">
              <div className="section-line">
                <strong role="status" className="agent-presence-status">
                  <CoRoofAvatar
                    size={32}
                    state={
                      busy || row.state === "running"
                        ? "loading"
                        : row.error_code
                          ? "attention"
                          : "idle"
                    }
                    decorative
                  />
                  {states[row.state]}
                </strong>
              </div>
              <p>{row.question}</p>
              {process}
              {row.error_code && row.state !== "cancelled" && (
                <p className="fine-print">
                  {errors[row.error_code] || unexplainedFailure}
                </p>
              )}
              <div className="settings-actions">
                <button
                  className="plain"
                  disabled={busy}
                  onClick={() => void refresh(row.id)}
                >
                  <RefreshCw size={14} />
                  刷新任务
                </button>
                {row.state === "ready" && !serverRunning && (
                  <button
                    className="secondary"
                    disabled={busy}
                    onClick={() => void continueReading()}
                  >
                    继续读取
                  </button>
                )}
                {row.state === "interrupted" && (
                  <button
                    className="secondary"
                    disabled={busy}
                    onClick={() => void continueReading()}
                  >
                    确认继续剩余步骤
                  </button>
                )}
                {["ready", "running", "interrupted"].includes(row.state) && (
                  <button
                    className="plain"
                    disabled={phase === "cancelling"}
                    onClick={() => void cancel()}
                  >
                    <Square size={14} />
                    取消任务
                  </button>
                )}
              </div>
            </section>
          )}
          {error && <Feedback kind="error">{error}</Feedback>}
          {task === "memory_draft" ? (
            <button
              className="secondary"
              disabled={busy}
              onClick={() => void start()}
            >
              {busy ? "正在整理…" : "AI 整理候选"}
            </button>
          ) : (
            <form
              className="ai-composer"
              onSubmit={(event) => {
                event.preventDefault();
                void start();
              }}
            >
              <label htmlFor="agent-question">
                {task === "update_draft"
                  ? "说说进展或需要的支持"
                  : "让 coRoof 继续查询"}
              </label>
              <textarea
                id="agent-question"
                rows={3}
                maxLength={2000}
                value={question}
                onChange={(event) => setQuestion(event.target.value)}
                placeholder={
                  task === "update_draft"
                    ? "例如：资料已整理，正在核对，需要交付同事协助。"
                    : "例如：查看需要关注的工作，再追查其中一件事的经过。"
                }
              />
              <div className="section-line">
                <small>
                  {task === "update_draft"
                    ? "生成提案 · 不自动确认"
                    : "只读查询 · 可随时取消后续步骤"}
                </small>
                <button className="primary" disabled={busy || !question.trim()}>
                  <Send size={15} />
                  {busy
                    ? "正在处理…"
                    : task === "update_draft"
                      ? "AI 整理草稿"
                      : "开始查询"}
                </button>
              </div>
            </form>
          )}
        </>
      )}
    </div>
  );
}
