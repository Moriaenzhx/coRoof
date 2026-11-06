"use client";
import { useEffect, useRef, useState } from "react";
import { MessageSquareText } from "lucide-react";
import {
  api,
  unwrap,
  formatTime,
  statusLabels,
  type Draft,
  type Evidence,
  type Member,
  type ProposedFields,
  type Work,
  type Schemas,
} from "../lib/api";
import { AgentReader } from "./agent-reader";
import { Feedback, StatusIcon, StatusLabel } from "./status";
import { ArrangementList, useArrangements } from "./work-arrangements";

export function WorkDetail({
  work,
  organizationId,
  members,
  timezone,
  onUpdated,
  initialIntent,
  initialDecisionId,
}: {
  work: Work;
  organizationId: string;
  members: Member[];
  timezone: string;
  onUpdated: () => Promise<void>;
  initialIntent?: "update" | "support" | "feedback";
  initialDecisionId?: string;
}) {
  const [source, setSource] = useState<Schemas["SourceDetail"] | null>(null);
  const external = work.source_authority === "external";
  const [events, setEvents] = useState<Evidence[]>([]);
  const [eventTotal, setEventTotal] = useState(0);
  const [error, setError] = useState("");
  const [raw, setRaw] = useState("");
  const [draft, setDraft] = useState<Draft | null>(null);
  const [fields, setFields] = useState<ProposedFields | null>(null);
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState("");
  const [draftMode, setDraftMode] = useState<"rules" | "model">("rules");
  const [feedbackId, setFeedbackId] = useState<string | undefined>(
    initialDecisionId,
  );
  const [feedbackCancelled, setFeedbackCancelled] = useState(false);
  const feedbackMode =
    !!feedbackId || (initialIntent === "feedback" && !feedbackCancelled);
  const arrangements = useArrangements(
    organizationId,
    String(work.version),
    work.id,
  );
  const selectedArrangement = arrangements.items.find(
    (item) => item.id === feedbackId,
  );
  const rawInput = useRef<HTMLTextAreaElement>(null);
  const quickRequest = useRef<{
    action: string;
    key: string;
    version: number;
  } | null>(null);
  const header = { "x-organization-id": organizationId };
  const active =
    !external &&
    (work.lifecycle_status === "planned" ||
      work.lifecycle_status === "in_progress");

  useEffect(() => {
    if (initialIntent && active) setDraftMode("rules");
  }, [initialIntent, active, work.id]);
  useEffect(() => {
    if (!initialIntent || !active || draftMode !== "rules") return;
    let current = true;
    // A parent dialog opens after child effects; focus once showModal has run.
    queueMicrotask(() => {
      if (current) rawInput.current?.focus();
    });
    return () => {
      current = false;
    };
  }, [initialIntent, active, draftMode, work.id]);

  async function loadEvents(offset = 0) {
    const page = unwrap(
      await api().GET("/api/v1/work-items/{work_id}/events", {
        params: {
          header,
          path: { work_id: work.id },
          query: { offset, limit: 20 },
        },
      }),
    );
    setEvents((previous) =>
      offset ? [...previous, ...page.items] : page.items,
    );
    setEventTotal(page.total);
  }
  useEffect(() => {
    let current = true;
    setSource(null);
    if (work.source_authority === "external")
      api()
        .GET("/api/v1/work-items/{work_id}/source", {
          params: {
            header: { "x-organization-id": organizationId },
            path: { work_id: work.id },
          },
        })
        .then(unwrap)
        .then((value) => {
          if (current) setSource(value);
        })
        .catch((e) => {
          if (current) setError(e.message);
        });
    api()
      .GET("/api/v1/work-items/{work_id}/events", {
        params: {
          header: { "x-organization-id": organizationId },
          path: { work_id: work.id },
          query: { limit: 20 },
        },
      })
      .then(unwrap)
      .then((page) => {
        if (current) {
          setEvents(page.items);
          setEventTotal(page.total);
        }
      })
      .catch((e) => {
        if (current) setError(String(e.message));
      });
    return () => {
      current = false;
    };
  }, [work.id, work.version, work.source_authority, organizationId]);

  async function run(action: () => Promise<void>) {
    setBusy(true);
    setError("");
    setNotice("");
    try {
      await action();
    } catch (e) {
      setError(e instanceof Error ? e.message : "请求失败");
    } finally {
      setBusy(false);
    }
  }
  async function quick(
    action: "progress" | "done" | "support" | "resolve_support",
  ) {
    await run(async () => {
      if (
        !quickRequest.current ||
        quickRequest.current.action !== action ||
        quickRequest.current.version !== work.version
      ) {
        quickRequest.current = {
          action,
          key: crypto.randomUUID(),
          version: work.version,
        };
      }
      unwrap(
        await api().POST("/api/v1/work-items/{work_id}/updates", {
          params: { header, path: { work_id: work.id } },
          body: {
            action,
            summary: "",
            expected_version: quickRequest.current.version,
            idempotency_key: quickRequest.current.key,
          },
        }),
      );
      quickRequest.current = null;
      await onUpdated();
      await loadEvents();
      setNotice("更新已记录。");
    });
  }
  async function propose() {
    if (feedbackMode && !selectedArrangement) return;
    await run(async () => {
      const value = unwrap(
        await api().POST("/api/v1/work-updates/drafts", {
          params: { header },
          body: {
            work_item_id: work.id,
            raw_text: raw,
            ...(feedbackMode ? { decision_id: feedbackId } : {}),
          },
        }),
      );
      setDraft(value);
      setFields(value.proposed_fields);
    });
  }
  async function confirm() {
    if (!draft || !fields) return;
    await run(async () => {
      let current = draft;
      if (JSON.stringify(fields) !== JSON.stringify(draft.proposed_fields)) {
        current = unwrap(
          await api().PATCH("/api/v1/work-updates/drafts/{draft_id}", {
            params: { header, path: { draft_id: draft.id } },
            body: {
              proposed_fields: fields,
              expected_revision: draft.revision,
            },
          }),
        );
        setDraft(current);
      }
      unwrap(
        await api().POST("/api/v1/work-updates/drafts/{draft_id}/confirm", {
          params: { header, path: { draft_id: current.id } },
          body: { expected_revision: current.revision },
        }),
      );
      setDraft(null);
      setFields(null);
      setRaw("");
      await onUpdated();
      await loadEvents();
      if (current.decision_id) {
        setFeedbackId(undefined);
        setFeedbackCancelled(true);
        arrangements.retry();
      }
      setNotice(
        current.decision_id
          ? "反馈已记录，事项负责人和获授权管理者可以查看；工作状态保持不变。"
          : "已确认，业务记录已保存。",
      );
    });
  }

  return (
    <>
      <div className="detail-meta">
        <StatusLabel status={work.lifecycle_status} />
        {!external && work.needs_support && <StatusLabel status="support" />}
      </div>
      {work.description && <p>{work.description}</p>}
      <dl className="facts">
        <div>
          <dt>负责人</dt>
          <dd>
            {work.owner_id
              ? members.find(
                  (member) =>
                    member.id === work.owner_id &&
                    member.organization_id === organizationId,
                )?.name || "负责人信息不可见"
              : "未分配"}
          </dd>
        </div>
        <div>
          <dt>截止时间</dt>
          <dd>
            {external
              ? "未同步 · 未知"
              : work.due_at
                ? formatTime(work.due_at, timezone)
                : "未设置"}
          </dd>
        </div>
        <div>
          <dt>最近更新</dt>
          <dd>{formatTime(work.updated_at, timezone)}</dd>
        </div>
        <div>
          <dt>来源</dt>
          <dd>
            {external
              ? source?.connector_name || "外部来源 · 只读"
              : "成员确认 · coRoof"}
          </dd>
        </div>
      </dl>
      {external && (
        <Feedback kind="info">
          {source?.notice || "此事项由外部源维护，截止日期与支持需求未知。"}
          {source && (
            <>
              <p>
                来源更新时间 {formatTime(source.source_at, timezone)} · 最近读取{" "}
                {formatTime(source.observed_at, timezone)}
              </p>
              {source.last_error && <p>最近同步未完成，当前内容可能陈旧。</p>}
              {source.source_url && (
                <a href={source.source_url} target="_blank" rel="noreferrer">
                  打开来源事项
                </a>
              )}
            </>
          )}
        </Feedback>
      )}
      {error && <Feedback kind="error">{error}</Feedback>}
      {notice && <Feedback kind="success">{notice}</Feedback>}
      <ArrangementList
        organizationId={organizationId}
        workId={work.id}
        timezone={timezone}
        {...arrangements}
        onRetry={arrangements.retry}
        selectedId={feedbackId}
        disabled={busy || !!draft}
        onFeedback={
          active
            ? (item) => {
                setFeedbackId(item.id);
                setFeedbackCancelled(false);
                setDraftMode("rules");
                queueMicrotask(() => rawInput.current?.focus());
              }
            : undefined
        }
      />
      {active && (
        <section className="update-section">
          <h3>
            {feedbackMode
              ? "反馈这项安排"
              : initialIntent === "support"
                ? "说明支持需求"
                : initialIntent === "update"
                  ? "汇报进展"
                  : "更新这项工作"}
          </h3>
          <p className="muted">
            {feedbackMode
              ? "写下实际进展，核对后由你确认。反馈不会改变工作状态。"
              : initialIntent
                ? "先写下实际情况，生成草稿后核对并确认；现在还不会更新工作。"
                : "有变化时说一声，无需填写日报。"}
          </p>
          {!initialIntent && !feedbackMode && (
            <div className="quick-actions">
              <button
                disabled={busy || !!draft}
                data-status="in_progress"
                onClick={() => quick("progress")}
              >
                <StatusIcon status="in_progress" size={16} />
                有进展
              </button>
              <button
                disabled={busy || !!draft}
                data-status="done"
                onClick={() => quick("done")}
              >
                <StatusIcon status="done" size={16} />
                已完成
              </button>
              <button
                disabled={busy || !!draft}
                data-status={work.needs_support ? "done" : "support"}
                onClick={() =>
                  quick(work.needs_support ? "resolve_support" : "support")
                }
              >
                <StatusIcon
                  status={work.needs_support ? "done" : "support"}
                  size={16}
                />
                {work.needs_support ? "解除阻塞" : "需要支持"}
              </button>
            </div>
          )}
          {feedbackMode && !draft && (
            <button
              className="plain"
              disabled={busy}
              onClick={() => {
                setFeedbackId(undefined);
                setFeedbackCancelled(true);
              }}
            >
              改为普通进展汇报
            </button>
          )}
          {feedbackMode &&
            !selectedArrangement &&
            !arrangements.loading &&
            !arrangements.error && (
              <Feedback kind="info">
                {feedbackId
                  ? "此安排当前不可见，请重新打开事项核对。"
                  : "请先选择上方要反馈的安排。"}
              </Feedback>
            )}
          {!draft && !feedbackMode && (
            <details className="draft-methods">
              <summary>
                {draftMode === "model"
                  ? "AI 整理 · 切换方式"
                  : "按原话记录 · 非 AI"}
              </summary>
              <div
                className="settings-actions"
                role="group"
                aria-label="草稿整理方式"
              >
                <button
                  className={draftMode === "rules" ? "secondary" : "plain"}
                  aria-pressed={draftMode === "rules"}
                  onClick={() => setDraftMode("rules")}
                >
                  文字整理 · 非 AI
                </button>
                <button
                  className={draftMode === "model" ? "secondary" : "plain"}
                  aria-pressed={draftMode === "model"}
                  onClick={() => setDraftMode("model")}
                >
                  AI 整理
                </button>
              </div>
            </details>
          )}
          {!draft && !feedbackMode && draftMode === "model" ? (
            <AgentReader
              key={`${organizationId}:${work.id}`}
              organizationId={organizationId}
              workId={work.id}
              task="update_draft"
              onDraft={(value) => {
                setDraft(value);
                setFields(value.proposed_fields);
              }}
            />
          ) : !draft ? (
            <form
              onSubmit={(e) => {
                e.preventDefault();
                void propose();
              }}
            >
              <label htmlFor="raw-update">
                {feedbackMode ? "这项安排进展如何" : "说说进展或需要的支持"}
              </label>
              <textarea
                ref={rawInput}
                id="raw-update"
                value={raw}
                onChange={(e) => setRaw(e.target.value)}
                required
                maxLength={4000}
                placeholder={
                  feedbackMode
                    ? "已落实哪些内容？还有什么问题需要核实？"
                    : initialIntent === "support"
                      ? "遇到了什么阻塞？需要谁协作、补充什么？请按实际情况说明。"
                      : initialIntent === "update"
                        ? "已经做了什么，还有哪些待核实或待完成的内容？"
                        : "例如：客户资料晚到两天，需要交付协调"
                }
                rows={4}
              />
              <button
                className="primary"
                disabled={
                  busy || !raw.trim() || (feedbackMode && !selectedArrangement)
                }
              >
                <MessageSquareText size={16} />
                {busy
                  ? "正在整理…"
                  : feedbackMode
                    ? "核对这段反馈"
                    : initialIntent === "support"
                      ? "整理支持需求"
                      : "整理这段进展"}
              </button>
            </form>
          ) : (
            fields && (
              <form
                className="draft-box"
                onSubmit={(e) => {
                  e.preventDefault();
                  void confirm();
                }}
              >
                <div className="section-line">
                  <h3>{draft.decision_id ? "确认安排反馈" : "确认更新"}</h3>
                  <span className="tag">
                    {draft.decision_id
                      ? "原文反馈 · 非 AI"
                      : draft.provider === "rules"
                        ? "文字整理 · 非 AI"
                        : "AI 草稿 · 待本人确认"}
                  </span>
                </div>
                <p className="muted">
                  {draft.decision_id
                    ? "核对内容后确认反馈；不会改变工作状态或自动记为已完成。"
                    : "请核对并编辑以下建议，确认后才会更新工作。"}
                </p>
                <details className="draft-original">
                  <summary>查看原话</summary>
                  <blockquote>{draft.raw_text}</blockquote>
                </details>
                <label htmlFor="draft-summary">更新内容</label>
                <textarea
                  id="draft-summary"
                  rows={3}
                  required
                  maxLength={4000}
                  value={fields.summary}
                  onChange={(e) =>
                    setFields({ ...fields, summary: e.target.value })
                  }
                />
                {!draft.decision_id && (
                  <>
                    <label htmlFor="draft-status">工作状态</label>
                    <select
                      id="draft-status"
                      value={fields.lifecycle_status || ""}
                      onChange={(e) =>
                        setFields({
                          ...fields,
                          lifecycle_status: (e.target.value ||
                            null) as ProposedFields["lifecycle_status"],
                        })
                      }
                    >
                      <option value="">保持不变</option>
                      <option value="in_progress">进行中</option>
                      <option value="done">已完成</option>
                      <option value="cancelled">已取消</option>
                    </select>
                    <label htmlFor="draft-support">支持需求</label>
                    <select
                      id="draft-support"
                      value={
                        fields.needs_support === null ||
                        fields.needs_support === undefined
                          ? ""
                          : String(fields.needs_support)
                      }
                      onChange={(e) =>
                        setFields({
                          ...fields,
                          needs_support:
                            e.target.value === ""
                              ? null
                              : e.target.value === "true",
                        })
                      }
                    >
                      <option value="">保持不变</option>
                      <option value="true">需要支持</option>
                      <option value="false">阻塞已解除</option>
                    </select>
                  </>
                )}
                <div className="form-actions">
                  <button
                    className="primary"
                    disabled={busy || !fields.summary.trim()}
                  >
                    {busy
                      ? "正在保存…"
                      : draft.decision_id
                        ? "确认并反馈"
                        : "确认并保存"}
                  </button>
                  <button
                    type="button"
                    disabled={busy}
                    onClick={() => {
                      setDraft(null);
                      setFields(null);
                    }}
                  >
                    返回编辑原文
                  </button>
                </div>
              </form>
            )
          )}
        </section>
      )}
      <details className="evidence" key={`${organizationId}:${work.id}`}>
        <summary>事实与来源（{eventTotal}）</summary>
        {events.map((event) => (
          <article key={event.id} className="event">
            <span className="timeline-dot" />
            <div>
              <div className="section-line">
                <strong>
                  {event.event_type === "work.created"
                    ? "创建事项"
                    : event.event_type === "work.assigned"
                      ? "分配负责人"
                      : event.event_type === "decision.confirmed"
                        ? "确认决策"
                        : event.event_type === "decision.feedback"
                          ? "反馈已确认安排"
                          : event.event_type === "decision.outcome"
                            ? "记录决策结果"
                            : "工作更新"}
                </strong>
                <time>{formatTime(event.recorded_at, timezone)}</time>
              </div>
              <p>
                {String(
                  (
                    event.event_payload.confirmed as
                      { summary?: string } | undefined
                  )?.summary ||
                    event.event_payload.title ||
                    "负责人分配已记录",
                )}
              </p>
              {typeof event.event_payload.raw_text === "string" && (
                <blockquote>原文：{event.event_payload.raw_text}</blockquote>
              )}
              <small>
                {members.find((m) => m.id === event.actor_id)?.name ||
                  "相关成员"}{" "}
                ·{" "}
                {event.source_ref.startsWith("source:")
                  ? "外部来源同步"
                  : event.source_ref.startsWith("draft:")
                    ? "本人确认的文字更新"
                    : "手动操作"}
              </small>
              <details>
                <summary>查看证据标识</summary>
                <code>{event.id}</code>
                <br />
                <code>{event.source_ref}</code>
              </details>
            </div>
          </article>
        ))}
        {events.length < eventTotal && (
          <button
            disabled={busy}
            onClick={() => run(() => loadEvents(events.length))}
          >
            加载更早记录
          </button>
        )}
      </details>
    </>
  );
}
