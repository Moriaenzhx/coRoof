"use client";
import { useEffect, useRef, useState } from "react";
import {
  ArrowUpRight,
  Check,
  CircleHelp,
  MessageSquareText,
} from "lucide-react";
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
} from "../lib/api";

export function WorkDetail({
  work,
  organizationId,
  members,
  timezone,
  onUpdated,
}: {
  work: Work;
  organizationId: string;
  members: Member[];
  timezone: string;
  onUpdated: () => Promise<void>;
}) {
  const [events, setEvents] = useState<Evidence[]>([]);
  const [eventTotal, setEventTotal] = useState(0);
  const [error, setError] = useState("");
  const [raw, setRaw] = useState("");
  const [draft, setDraft] = useState<Draft | null>(null);
  const [fields, setFields] = useState<ProposedFields | null>(null);
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState("");
  const quickRequest = useRef<{
    action: string;
    key: string;
    version: number;
  } | null>(null);
  const header = { "x-organization-id": organizationId };
  const active =
    work.lifecycle_status === "planned" ||
    work.lifecycle_status === "in_progress";

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
  }, [work.id, work.version, organizationId]);

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
    await run(async () => {
      const value = unwrap(
        await api().POST("/api/v1/work-updates/drafts", {
          params: { header },
          body: { work_item_id: work.id, raw_text: raw },
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
      setNotice("已确认，业务记录已保存。");
    });
  }

  return (
    <>
      <div className="detail-meta">
        <span className="tag">{statusLabels[work.lifecycle_status]}</span>
        {work.needs_support && <span className="tag amber">需要支持</span>}
      </div>
      {work.description && <p>{work.description}</p>}
      <dl className="facts">
        <div>
          <dt>负责人</dt>
          <dd>
            {members.find((m) => m.id === work.owner_id)?.name || "未分配"}
          </dd>
        </div>
        <div>
          <dt>截止时间</dt>
          <dd>{work.due_at ? formatTime(work.due_at, timezone) : "未设置"}</dd>
        </div>
        <div>
          <dt>最近更新</dt>
          <dd>{formatTime(work.updated_at, timezone)}</dd>
        </div>
        <div>
          <dt>来源</dt>
          <dd>成员确认 · coRoof</dd>
        </div>
      </dl>
      {error && (
        <p role="alert" className="error">
          {error}
        </p>
      )}
      {notice && (
        <p role="status" className="success">
          {notice}
        </p>
      )}
      {active && (
        <section className="update-section">
          <h3>更新这项工作</h3>
          <p className="muted">有变化时说一声，无需填写日报。</p>
          <div className="quick-actions">
            <button
              disabled={busy || !!draft}
              onClick={() => quick("progress")}
            >
              <ArrowUpRight size={16} />
              有进展
            </button>
            <button disabled={busy || !!draft} onClick={() => quick("done")}>
              <Check size={16} />
              已完成
            </button>
            <button
              disabled={busy || !!draft}
              onClick={() =>
                quick(work.needs_support ? "resolve_support" : "support")
              }
            >
              <CircleHelp size={16} />
              {work.needs_support ? "解除阻塞" : "需要支持"}
            </button>
          </div>
          {!draft ? (
            <form
              onSubmit={(e) => {
                e.preventDefault();
                void propose();
              }}
            >
              <label htmlFor="raw-update">说说进展或需要的支持</label>
              <textarea
                id="raw-update"
                value={raw}
                onChange={(e) => setRaw(e.target.value)}
                required
                maxLength={4000}
                placeholder="例如：客户资料晚到两天，需要交付协调"
                rows={4}
              />
              <button className="primary" disabled={busy || !raw.trim()}>
                <MessageSquareText size={16} />
                {busy ? "正在整理…" : "生成待确认草稿"}
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
                  <h3>确认更新</h3>
                  <span className="tag">规则降级 · 非 AI</span>
                </div>
                <p className="muted">
                  以下为规则整理的建议，确认后才会更新工作。
                </p>
                <blockquote>{draft.raw_text}</blockquote>
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
                <div className="form-actions">
                  <button
                    className="primary"
                    disabled={busy || !fields.summary.trim()}
                  >
                    {busy ? "正在保存…" : "确认并保存"}
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
      <section className="evidence">
        <h3>
          事实与来源 <span>{eventTotal}</span>
        </h3>
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
                {event.source_ref.startsWith("draft:")
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
      </section>
    </>
  );
}
