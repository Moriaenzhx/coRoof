"use client";
import { useCallback, useEffect, useRef, useState } from "react";
import {
  ArrowLeft,
  ArrowUpRight,
  BookOpen,
  CircleHelp,
  Send,
  Sparkles,
} from "lucide-react";
import { api, formatTime, unwrap, type Schemas, type Work } from "../lib/api";
import { Feedback } from "./status";
import { DecisionDetail } from "./decisions";
import { CoRoofAvatar } from "./companion";
import {
  AgentReader,
  type AgentCommand,
  type AgentReaderState,
} from "./agent-reader";
import { DocumentCitations } from "./knowledge-source";
import { MemoryCitations } from "./memory";

type Answer = Schemas["AnswerOut"];
function answerModeLabel(mode: Answer["mode"]) {
  return mode === "model"
    ? "AI 建议"
    : mode === "retrieval"
      ? "原文检索 · 未调用模型"
      : "规则整理 · 非 AI";
}
export { AttentionList, type Signal } from "./evidence";
import { EvidenceView, SignalLabel } from "./evidence";

export function AiAssistant({
  organizationId,
  work,
  timezone,
  canDecide,
  onUpdated,
  initialRunId,
  initialQuestion = "",
  autoStart = false,
  presentation = "default",
  command,
  onStateChange,
  onDecision,
  onEvidence,
  onDocument,
}: {
  organizationId: string;
  work?: Work;
  timezone: string;
  canDecide: boolean;
  onUpdated: () => Promise<void>;
  initialRunId?: string;
  initialQuestion?: string;
  autoStart?: boolean;
  presentation?: "default" | "floating";
  command?: AgentCommand;
  onStateChange?: (state: AgentReaderState) => void;
  onDecision?: (id: string) => void;
  onEvidence?: (id: string) => void;
  onDocument?: (
    source: Pick<Schemas["Citation"], "document_id" | "revision_id">,
  ) => void;
}) {
  const floating = presentation === "floating";
  const [question, setQuestion] = useState(initialQuestion);
  const [turns, setTurns] = useState<
    { question: string; answer: Answer; agent?: boolean }[]
  >([]);
  const [mode, setMode] = useState<"agent" | "quick">("agent");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [evidenceId, setEvidenceId] = useState<string | null>(null);
  const [decisionId, setDecisionId] = useState<string | null>(null);
  const [readerState, setReaderState] = useState<AgentReaderState>({
    run: null,
    busy: false,
    error: "",
  });
  const onStateChangeRef = useRef(onStateChange);
  const emittedState = useRef<AgentReaderState | null>(null);
  const generation = useRef(0);
  const pending = useRef(false);
  const autoStartConsumed = useRef(false);
  const prepareKey = useRef<{ target: string; key: string } | null>(null);
  const resultAnchor = useRef<HTMLDivElement>(null);
  useEffect(() => {
    onStateChangeRef.current = onStateChange;
  }, [onStateChange]);
  useEffect(() => {
    generation.current++;
    return () => {
      generation.current++;
    };
  }, [organizationId, work?.id]);
  const receiveState = useCallback((state: AgentReaderState) => {
    setReaderState((previous) =>
      previous.run === state.run &&
      previous.busy === state.busy &&
      previous.error === state.error
        ? previous
        : state,
    );
  }, []);
  useEffect(() => {
    if (presentation !== "floating") return;
    const next = {
      run: readerState.run,
      busy: busy || readerState.busy,
      error: error || readerState.error,
    };
    if (
      emittedState.current?.run === next.run &&
      emittedState.current?.busy === next.busy &&
      emittedState.current?.error === next.error
    )
      return;
    emittedState.current = next;
    onStateChangeRef.current?.(next);
  }, [presentation, readerState, busy, error]);
  useEffect(() => {
    if (presentation !== "floating") return;
    setTurns([]);
    setEvidenceId(null);
    setDecisionId(null);
    setError("");
    setReaderState({ run: null, busy: false, error: "" });
  }, [presentation, command?.id, initialRunId]);
  useEffect(() => {
    if (!initialRunId || floating) return;
    let current = true;
    api(organizationId)
      .GET("/api/v1/agent/runs/{run_id}", {
        params: {
          header: { "x-organization-id": organizationId },
          path: { run_id: initialRunId },
        },
      })
      .then(unwrap)
      .then((run) => {
        if (!current) return;
        if (run.state !== "completed" || !run.answer)
          throw new Error("此分析已失效，请重新核对当前记录。");
        setTurns([
          {
            question: "持续关注 · 推进建议待审阅",
            answer: run.answer,
            agent: true,
          },
        ]);
      })
      .catch((e: Error) => {
        if (current) {
          setTurns([]);
          setError(e.message);
        }
      });
    return () => {
      current = false;
    };
  }, [organizationId, initialRunId, presentation]);
  async function ask(value: string) {
    if (pending.current || !value.trim()) return;
    pending.current = true;
    setBusy(true);
    setError("");
    try {
      const answer = unwrap(
        await api(organizationId).POST("/api/v1/ai/ask", {
          params: { header: { "x-organization-id": organizationId } },
          body: { question: value, work_item_id: work?.id },
        }),
      );
      setTurns((previous) => [
        ...previous.slice(-5),
        { question: value, answer },
      ]);
      setQuestion("");
    } catch (e) {
      setError(e instanceof Error ? e.message : "暂时无法回答，请重试");
    } finally {
      pending.current = false;
      setBusy(false);
    }
  }
  useEffect(() => {
    const result = resultAnchor.current;
    const drawer = result?.closest("dialog");
    if (drawer && result)
      drawer.scrollTo?.({
        top:
          turns.length <= 1
            ? 0
            : drawer.scrollTop +
              result.getBoundingClientRect().top -
              drawer.getBoundingClientRect().top -
              140,
      });
  }, [turns]);
  async function prepare(answerId: string, workId: string) {
    if (pending.current || !canDecide) return;
    const ticket = generation.current;
    pending.current = true;
    setBusy(true);
    setError("");
    const target = answerId + workId;
    if (prepareKey.current?.target !== target)
      prepareKey.current = { target, key: crypto.randomUUID() };
    try {
      const result = unwrap(
        await api(organizationId).POST("/api/v1/decisions", {
          params: { header: { "x-organization-id": organizationId } },
          body: {
            analysis_id: answerId,
            work_item_id: workId,
            idempotency_key: prepareKey.current.key,
          },
        }),
      );
      if (ticket !== generation.current) return;
      if (floating) onDecision?.(result.id);
      else setDecisionId(result.id);
    } catch (e) {
      if (ticket === generation.current)
        setError(e instanceof Error ? e.message : "准备失败");
    } finally {
      if (ticket === generation.current) {
        pending.current = false;
        setBusy(false);
      }
    }
  }
  function openEvidence(id: string) {
    if (floating) onEvidence?.(id);
    else setEvidenceId(id);
  }
  const displayedTurns = floating
    ? readerState.run?.answer && !readerState.error
      ? [
          {
            question: readerState.run.question,
            answer: readerState.run.answer,
            agent: true,
          },
        ]
      : []
    : turns;
  if (floating) {
    const answer = readerState.error ? null : readerState.run?.answer;
    const inventory = answer?.knowledge_inventory;
    const suggestions = answer?.suggestions || [];
    const documents = answer?.document_answers || [];
    const memories = answer?.memory_answers || [];
    const suggestionRow = (suggestion: Schemas["Suggestion"]) => {
      const source = answer?.evidence.find(
        (item) => item.id === suggestion.evidence_id,
      );
      return (
        <div className="assistant-advice-row" key={suggestion.work_item_id}>
          {source && <h3>{source.facts.title}</h3>}
          <p>{suggestion.interpretation}</p>
          {suggestion.options[0] && (
            <p className="assistant-next-step">
              <span>建议下一步：</span>
              {suggestion.options[0].plan}
            </p>
          )}
          {canDecide && onDecision && (
            <button
              className="plain assistant-action"
              disabled={busy}
              onClick={() => void prepare(answer!.id, suggestion.work_item_id)}
            >
              处理这件事
              <ArrowUpRight size={14} aria-hidden="true" />
            </button>
          )}
        </div>
      );
    };
    const answerBody = answer ? (
      <div className="assistant-answer-copy">
        {answer.mode !== "model" && (
          <p className="assistant-answer-label">
            {answerModeLabel(answer.mode)}
          </p>
        )}
        {answer.evidence.some((item) => item.outdated) && (
          <Feedback kind="error">
            部分工作记录已变化，请先重新核对，再决定如何处理。
          </Feedback>
        )}
        {suggestions.slice(0, 3).map(suggestionRow)}
        {!suggestions.length && <p>{answer.summary}</p>}
        {!suggestions.length &&
          documents.slice(0, 2).map((item) => {
            const source = answer.documents?.find(
              (value) => value.id === item.citation_id,
            );
            return source ? (
              <div className="assistant-document-quote" key={item.citation_id}>
                <blockquote>{item.quote}</blockquote>
                <button
                  className="plain assistant-source-link"
                  disabled={!onDocument}
                  onClick={() => onDocument?.(source)}
                >
                  {source.title} · 版本 {source.revision_number}
                  <ArrowUpRight size={13} aria-hidden="true" />
                </button>
              </div>
            ) : null;
          })}
        {!suggestions.length && documents.length > 0 && (
          <p className="assistant-answer-label">
            以下为相关原文片段，点击资料名称查看完整内容。
          </p>
        )}
        {!suggestions.length &&
          !documents.length &&
          memories.slice(0, 2).map((item) => {
            const source = answer.memories?.find(
              (value) => value.id === item.citation_id,
            );
            return source ? (
              <div className="assistant-document-quote" key={item.citation_id}>
                <blockquote>{item.quote}</blockquote>
                <p className="assistant-answer-label">
                  {source.kind === "preference" ? "本人偏好" : "历史经验"} ·
                  适用条件：{source.applicability}
                </p>
              </div>
            ) : null;
          })}
        {inventory && inventory.items.length > 0 && (
          <ul className="assistant-document-list" aria-label="可查看的资料">
            {inventory.items.map((item) => (
              <li key={item.revision_id}>
                <button
                  className="plain assistant-source-link"
                  disabled={!onDocument}
                  onClick={() =>
                    onDocument?.({
                      document_id: item.document_id,
                      revision_id: item.revision_id,
                    })
                  }
                >
                  <BookOpen size={15} aria-hidden="true" />
                  <span>
                    {item.title}
                    <small>
                      版本 {item.revision_number} · 发布于{" "}
                      {formatTime(item.source_at, timezone)}
                    </small>
                  </span>
                  <ArrowUpRight size={13} aria-hidden="true" />
                </button>
              </li>
            ))}
          </ul>
        )}
        {inventory?.truncated && (
          <p className="assistant-answer-label">
            共 {inventory.total} 份资料，当前列出 {inventory.items.length} 份。
          </p>
        )}
      </div>
    ) : null;
    const answerDetails = answer ? (
      <>
        <p>
          {answerModeLabel(answer.mode)}
          {answer.mode === "model" ? "，尚未执行。" : "。"} {answer.notice}
        </p>
        <p>
          本次参考 {answer.considered_work_count} /{" "}
          {answer.authorized_work_count} 项获授权工作 ·{" "}
          {formatTime(answer.generated_at, timezone)}
        </p>
        {suggestions.length > 0 && <p>{answer.summary}</p>}
        {suggestions.slice(3).map(suggestionRow)}
        {suggestions.map((suggestion) => (
          <div className="assistant-option-notes" key={suggestion.work_item_id}>
            <strong>
              {
                answer.evidence.find(
                  (item) => item.id === suggestion.evidence_id,
                )?.facts.title
              }{" "}
              · 可选安排
            </strong>
            {suggestion.options.map((option) => (
              <p key={option.id}>
                <strong>{option.title}：</strong>
                {option.plan}
                <br />
                <span>{option.tradeoff}</span>
              </p>
            ))}
          </div>
        ))}
        {answer.evidence.length > 0 && (
          <ul className="assistant-source-list" aria-label="工作依据">
            {answer.evidence.map((source) => (
              <li key={source.id}>
                <button
                  className="plain assistant-source-link"
                  disabled={!onEvidence}
                  onClick={() => openEvidence(source.id)}
                >
                  <BookOpen size={14} aria-hidden="true" />
                  <span>
                    查看原始依据：{source.facts.title}
                    <small>{formatTime(source.source_at, timezone)}</small>
                  </span>
                </button>
              </li>
            ))}
          </ul>
        )}
        {answer.documents?.map((source) => (
          <div className="assistant-source-note" key={source.id}>
            <button
              className="plain assistant-source-link"
              disabled={!onDocument}
              onClick={() => onDocument?.(source)}
            >
              查看资料：{source.title} · 版本 {source.revision_number}
            </button>
            <p>{formatTime(source.source_at, timezone)}</p>
            {answer.document_answers
              ?.filter((item) => item.citation_id === source.id)
              .map((item) => (
                <blockquote key={item.citation_id}>{item.quote}</blockquote>
              ))}
          </div>
        ))}
        {inventory && <p>{inventory.notice}</p>}
        <MemoryCitations
          answer={answer}
          organizationId={organizationId}
          timezone={timezone}
        />
      </>
    ) : null;
    return (
      <div className="ai-assistant assistant-conversation">
        <AgentReader
          presentation="progress"
          organizationId={organizationId}
          workId={work?.id}
          command={command}
          initialRunId={initialRunId}
          onStateChange={receiveState}
          details={answerDetails}
        >
          {answerBody}
        </AgentReader>
        {error && <Feedback kind="error">{error}</Feedback>}
      </div>
    );
  }
  if (evidenceId && presentation === "default")
    return (
      <EvidenceView
        id={evidenceId}
        organizationId={organizationId}
        timezone={timezone}
        onBack={() => setEvidenceId(null)}
      />
    );
  if (decisionId && presentation === "default")
    return (
      <>
        <button className="plain back-link" onClick={() => setDecisionId(null)}>
          <ArrowLeft size={15} />
          返回问答
        </button>
        <DecisionDetail
          id={decisionId}
          organizationId={organizationId}
          timezone={timezone}
          onUpdated={onUpdated}
          onReask={() => {
            setDecisionId(null);
            setQuestion("请根据当前记录重新核对这项工作及处理建议");
          }}
        />
      </>
    );
  return (
    <div className="ai-assistant">
      <div className="ai-context">
        <CoRoofAvatar size={40} decorative />
        <span>
          {work ? `围绕「${work.title}」` : "基于当前获授权的工作记录"}
        </span>
      </div>
      {presentation === "default" && (
        <div className="settings-actions" aria-label="查询方式">
          <button
            className={mode === "agent" ? "secondary" : "plain"}
            aria-pressed={mode === "agent"}
            onClick={() => setMode("agent")}
          >
            连续查询
          </button>
          <button
            className={mode === "quick" ? "secondary" : "plain"}
            aria-pressed={mode === "quick"}
            onClick={() => setMode("quick")}
          >
            快速整理
          </button>
        </div>
      )}
      {(floating || mode === "agent") && (
        <AgentReader
          presentation={floating ? "progress" : "default"}
          command={floating ? command : undefined}
          initialRunId={floating ? initialRunId : undefined}
          onStateChange={floating ? receiveState : undefined}
          initialQuestion={question}
          autoStart={autoStart && !initialRunId && !autoStartConsumed.current}
          onAutoStart={() => {
            autoStartConsumed.current = true;
          }}
          organizationId={organizationId}
          workId={work?.id}
          onAnswer={(value, answer) => {
            if (floating) return;
            setTurns((previous) =>
              previous.some((turn) => turn.answer.id === answer.id)
                ? previous
                : [
                    ...previous.slice(-5),
                    { question: value, answer, agent: true },
                  ],
            );
          }}
        />
      )}
      {presentation === "default" && mode === "quick" && !turns.length && (
        <div className="ai-welcome">
          <h3>{work ? "一起看清这件事。" : "想了解企业的哪一面？"}</h3>
          <p>回答会附上依据；方案由你确认后才记录。</p>
          <div className="suggested-questions">
            {(work
              ? ["这件事为什么需要关注？", "有哪些处理方案？"]
              : [
                  "现在有哪些工作需要关注？",
                  "哪些事项需要协调支持？",
                  "有哪些信息还需要补充？",
                ]
            ).map((q) => (
              <button
                key={q}
                disabled={busy}
                onClick={() => {
                  setQuestion(q);
                  void ask(q);
                }}
              >
                {q}
                <ArrowUpRight size={14} />
              </button>
            ))}
          </div>
        </div>
      )}
      {displayedTurns.map((turn, index) => (
        <section
          className="ai-turn"
          key={turn.answer.id}
          ref={index === displayedTurns.length - 1 ? resultAnchor : undefined}
        >
          <p className="ai-question">{turn.question}</p>
          <div className="ai-answer">
            <div className="section-line">
              <strong>coRoof</strong>
              <span className="tag">{answerModeLabel(turn.answer.mode)}</span>
            </div>
            <p className="fine-print">{turn.answer.notice}</p>
            <p>{turn.answer.summary}</p>
            <MemoryCitations
              answer={turn.answer}
              organizationId={organizationId}
              timezone={timezone}
            />
            <DocumentCitations
              answer={turn.answer}
              organizationId={organizationId}
              timezone={timezone}
            />
            <p className="fine-print">
              本次参考 {turn.answer.considered_work_count} /{" "}
              {turn.answer.authorized_work_count} 项获授权工作 ·{" "}
              {formatTime(turn.answer.generated_at, timezone)}
            </p>
            {turn.answer.suggestions.map((s) => (
              <article className="ai-suggestion" key={s.work_item_id}>
                <h3>
                  {
                    turn.answer.evidence.find((e) => e.id === s.evidence_id)
                      ?.facts.title
                  }
                </h3>
                <div className="signal-labels">
                  {turn.answer.signals
                    .filter((signal) => signal.work_item_id === s.work_item_id)
                    .map((signal) => (
                      <SignalLabel key={signal.id} signal={signal} />
                    ))}
                </div>
                <p>{s.interpretation}</p>
                <button
                  className="evidence-link"
                  disabled={floating && !onEvidence}
                  onClick={() => openEvidence(s.evidence_id)}
                >
                  <BookOpen size={15} />
                  查看原始依据
                  <ArrowUpRight size={14} />
                </button>
                <div className="advice-options">
                  {s.options.map((o) => (
                    <div key={o.id}>
                      <strong>{o.title}</strong>
                      <p>{o.plan}</p>
                      <small>{o.tradeoff}</small>
                    </div>
                  ))}
                </div>
                {canDecide && (presentation === "default" || onDecision) && (
                  <button
                    disabled={busy}
                    onClick={() => prepare(turn.answer.id, s.work_item_id)}
                  >
                    处理这件事
                    <ArrowUpRight size={15} />
                  </button>
                )}
              </article>
            ))}
            {!turn.answer.suggestions.length && (
              <p className="muted">
                <CircleHelp size={14} aria-hidden="true" />{" "}
                尚无可支撑具体方案的分析，请查看记录或补充问题。
              </p>
            )}
            <details className="answer-sources">
              <summary>
                本次参考的工作记录（{turn.answer.evidence.length}）
              </summary>
              {turn.answer.evidence.map((e) => (
                <button
                  key={e.id}
                  className="evidence-link"
                  disabled={floating && !onEvidence}
                  onClick={() => openEvidence(e.id)}
                >
                  <BookOpen size={14} />
                  {e.facts.title}
                  <span>{formatTime(e.source_at, timezone)}</span>
                </button>
              ))}
            </details>
          </div>
        </section>
      ))}
      {error && <Feedback kind="error">{error}</Feedback>}
      {presentation === "default" && mode === "quick" && (
        <form
          className="ai-composer"
          onSubmit={(e) => {
            e.preventDefault();
            void ask(question);
          }}
        >
          <label htmlFor="ai-question">询问 coRoof</label>
          <textarea
            id="ai-question"
            rows={3}
            maxLength={2000}
            value={question}
            onChange={(e) => setQuestion(e.target.value)}
            placeholder={
              work
                ? "询问这项工作的情况或处理建议…"
                : "例如：现在有哪些工作需要我关注？"
            }
          />
          <div className="section-line">
            <small>每次查询当前记录 · 建议尚未执行</small>
            <button className="primary" disabled={busy || !question.trim()}>
              <Send size={15} />
              {busy ? "正在整理…" : "发送问题"}
            </button>
          </div>
          {busy && (
            <span role="status" className="fine-print">
              正在核对获授权的记录与来源…
            </span>
          )}
        </form>
      )}
    </div>
  );
}
