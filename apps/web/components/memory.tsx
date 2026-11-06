"use client";

import { useEffect, useRef, useState } from "react";
import { BookOpen, Plus, RefreshCw } from "lucide-react";
import { api, unwrap, formatTime, type Schemas } from "../lib/api";
import { Drawer } from "./drawer";
import { Feedback } from "./status";
import { AgentReader } from "./agent-reader";

type Entry = Schemas["MemoryOut"];
type Kind = Entry["kind"];
type Context = { organizationId: string; timezone: string };
const stateNames = {
  proposed: "待本人确认",
  confirmed: "已确认",
  revoked: "已撤销",
  deleted: "已删除",
};
const preferenceNames = {
  focus: "经营重点",
  communication: "沟通方式",
  decision_rule: "决策原则",
  planning_goal: "规划目标",
};

export function MemorySource({
  row,
  timezone,
}: {
  row: Entry;
  timezone: string;
}) {
  const source = row.source;
  if (!source) return <p>来源已不可用。</p>;
  return (
    <section className="knowledge-source" aria-label="候选来源">
      <h3>{row.kind === "experience" ? "决策与实际结果" : "本人原始输入"}</h3>
      <p className="fine-print">
        {formatTime(source.source_at, timezone)} ·{" "}
        {row.kind === "experience"
          ? "历史记录，需结合当前情况核实"
          : "私有偏好，仅本人可管理和引用"}
      </p>
      {source.selected_plan && (
        <>
          <h4>当时选择的方案</h4>
          <p className="document-content">{source.selected_plan}</p>
        </>
      )}
      <h4>{row.kind === "experience" ? "所选实际结果原文" : "本人表述"}</h4>
      <p className="document-content">
        {source.observed_result || source.owner_statement}
      </p>
      {source.other_outcomes.length > 0 && (
        <details>
          <summary>
            其他结果记录 · 共 {source.outcome_count} 条，展示最近{" "}
            {source.other_outcomes.length} 条其他结果
          </summary>
          {source.other_outcomes.map((value, index) => (
            <p className="document-content" key={index}>
              {value}
            </p>
          ))}
        </details>
      )}
    </section>
  );
}

function NewMemory({
  context,
  kind,
  onSaved,
}: {
  context: Context;
  kind: Kind;
  onSaved: (row: Entry) => void;
}) {
  const [decisions, setDecisions] = useState<Schemas["DecisionOut"][]>([]);
  const [total, setTotal] = useState(0);
  const [decisionId, setDecisionId] = useState("");
  const [outcomes, setOutcomes] = useState<Schemas["OutcomeOut"][]>([]);
  const [outcomeTotal, setOutcomeTotal] = useState(0);
  const [outcomeId, setOutcomeId] = useState("");
  const [sourceText, setSourceText] = useState("");
  const [preferenceKey, setPreferenceKey] =
    useState<NonNullable<Entry["preference_key"]>>("focus");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const request = useRef({ signature: "", key: crypto.randomUUID() });
  const header = { "x-organization-id": context.organizationId };
  async function moreDecisions(offset: number) {
    setBusy(true);
    setError("");
    try {
      const result = unwrap(
        await api(context.organizationId).GET("/api/v1/decisions", {
          params: { header, query: { offset, limit: 30 } },
        }),
      );
      setDecisions((old) =>
        offset ? [...old, ...result.items] : result.items,
      );
      setTotal(result.total);
    } catch (e) {
      setError(e instanceof Error ? e.message : "读取决策失败");
    } finally {
      setBusy(false);
    }
  }
  useEffect(() => {
    if (kind === "experience") void moreDecisions(0);
  }, [kind]);
  useEffect(() => {
    let active = true;
    setOutcomes([]);
    setOutcomeId("");
    setOutcomeTotal(0);
    if (decisionId)
      api(context.organizationId)
        .GET("/api/v1/decisions/{decision_id}/outcomes", {
          params: {
            header,
            path: { decision_id: decisionId },
            query: { offset: 0, limit: 30 },
          },
        })
        .then(unwrap)
        .then((result) => {
          if (active) {
            setOutcomes(result.items);
            setOutcomeTotal(result.total);
          }
        })
        .catch((e: Error) => {
          if (active) setError(e.message);
        });
    return () => {
      active = false;
    };
  }, [decisionId, context.organizationId]);
  async function save() {
    if (busy) return;
    setBusy(true);
    setError("");
    const data =
      kind === "experience"
        ? {
            kind,
            decision_id: decisionId,
            outcome_id: outcomeId,
            source_text: "",
          }
        : { kind, preference_key: preferenceKey, source_text: sourceText };
    const signature = JSON.stringify(data);
    if (request.current.signature !== signature)
      request.current = { signature, key: crypto.randomUUID() };
    try {
      onSaved(
        unwrap(
          await api(context.organizationId).POST("/api/v1/memory/entries", {
            params: { header },
            body: { ...data, idempotency_key: request.current.key },
          }),
        ),
      );
    } catch (e) {
      setError(e instanceof Error ? e.message : "保存失败");
    } finally {
      setBusy(false);
    }
  }
  return (
    <form
      onSubmit={(event) => {
        event.preventDefault();
        void save();
      }}
    >
      <p className="muted">
        {kind === "experience"
          ? "选择一项已确认决策及实际结果，再整理经验。未记录结果时，请先在对应决策详情中补录。"
          : "写下你希望 coRoof 参考的经营重点或工作方式。只保存你明确表达并确认的内容。"}
      </p>
      {kind === "experience" ? (
        <>
          <label>
            已确认决策
            <select
              required
              value={decisionId}
              onChange={(e) => setDecisionId(e.target.value)}
            >
              <option value="">选择决策</option>
              {decisions
                .filter((d) => d.state === "confirmed")
                .map((d) => (
                  <option key={d.id} value={d.id}>
                    {d.title}
                  </option>
                ))}
            </select>
          </label>
          {decisions.length < total && (
            <button
              type="button"
              className="plain"
              disabled={busy}
              onClick={() => void moreDecisions(decisions.length)}
            >
              加载更多决策
            </button>
          )}
          <label>
            实际结果
            <select
              required
              value={outcomeId}
              onChange={(e) => setOutcomeId(e.target.value)}
            >
              <option value="">选择实际结果</option>
              {outcomes.map((o) => (
                <option key={o.id} value={o.id}>
                  {formatTime(o.recorded_at, context.timezone)} ·{" "}
                  {o.observed_result.slice(0, 80)}
                </option>
              ))}
            </select>
          </label>
          {outcomes.length < outcomeTotal && (
            <button
              type="button"
              className="plain"
              disabled={busy}
              onClick={async () => {
                setBusy(true);
                setError("");
                try {
                  const result = unwrap(
                    await api(context.organizationId).GET(
                      "/api/v1/decisions/{decision_id}/outcomes",
                      {
                        params: {
                          header,
                          path: { decision_id: decisionId },
                          query: { offset: outcomes.length, limit: 30 },
                        },
                      },
                    ),
                  );
                  setOutcomes((old) => [...old, ...result.items]);
                  setOutcomeTotal(result.total);
                } catch (e) {
                  setError(e instanceof Error ? e.message : "读取失败");
                } finally {
                  setBusy(false);
                }
              }}
            >
              加载更多结果
            </button>
          )}
          {outcomeId && (
            <p className="document-content">
              {outcomes.find((o) => o.id === outcomeId)?.observed_result}
            </p>
          )}
        </>
      ) : (
        <>
          <label>
            偏好类别
            <select
              value={preferenceKey}
              onChange={(e) =>
                setPreferenceKey(
                  e.target.value as NonNullable<Entry["preference_key"]>,
                )
              }
            >
              {Object.entries(preferenceNames).map(([key, name]) => (
                <option key={key} value={key}>
                  {name}
                </option>
              ))}
            </select>
          </label>
          <label>
            我的明确表述
            <textarea
              required
              rows={5}
              maxLength={2000}
              value={sourceText}
              onChange={(e) => setSourceText(e.target.value)}
              placeholder="例如：需要我决策的问题，先说明事实依据、可选方案和待核实的信息。"
            />
          </label>
          <p className="fine-print">
            每类仅保留一条生效偏好；新目标不代表已经实现，也不授予自动执行权限。
          </p>
        </>
      )}
      {error && <Feedback kind="error">{error}</Feedback>}
      <button
        className="primary"
        disabled={
          busy || (kind === "experience" ? !outcomeId : !sourceText.trim())
        }
      >
        建立候选
      </button>
    </form>
  );
}

export function MemoryDetail({
  initial,
  context,
  onChanged,
}: {
  initial: Entry;
  context: Context;
  onChanged: (row: Entry) => void;
}) {
  const [row, setRow] = useState(initial);
  const [title, setTitle] = useState(row.title);
  const [content, setContent] = useState(row.content);
  const [applicability, setApplicability] = useState(row.applicability);
  const [quote, setQuote] = useState(row.source_quote);
  const [confirmed, setConfirmed] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const pending = useRef(false);
  const keys = useRef(new Map<string, string>());
  const header = { "x-organization-id": context.organizationId };
  const params = { header, path: { identifier: row.id } };
  function receive(value: Entry) {
    setRow(value);
    setTitle(value.title);
    setContent(value.content);
    setApplicability(value.applicability);
    setQuote(value.source_quote);
    setConfirmed(false);
    setDeleting(false);
    onChanged(value);
  }
  function key(body: object) {
    const signature = JSON.stringify(body);
    if (!keys.current.has(signature))
      keys.current.set(signature, crypto.randomUUID());
    return keys.current.get(signature)!;
  }
  async function perform(action: () => Promise<Entry>) {
    if (pending.current) return;
    pending.current = true;
    setBusy(true);
    setError("");
    try {
      receive(await action());
    } catch (e) {
      setError(e instanceof Error ? e.message : "操作失败，请刷新核对");
    } finally {
      pending.current = false;
      setBusy(false);
    }
  }
  const dirty =
    title !== row.title ||
    content !== row.content ||
    applicability !== row.applicability ||
    quote !== row.source_quote;
  async function save() {
    const body = {
      title,
      content,
      applicability,
      source_quote: quote,
      expected_version: row.version,
      expected_source_hash: row.source?.source_hash || "",
    };
    await perform(async () =>
      unwrap(
        await api(context.organizationId).POST(
          "/api/v1/memory/entries/{identifier}/edit",
          { params, body: { ...body, idempotency_key: key(body) } },
        ),
      ),
    );
  }
  async function act(action: Schemas["MemoryAction"]["action"]) {
    const body = {
      action,
      confirm: true as const,
      expected_version: row.version,
      expected_source_hash: row.source?.source_hash || "",
    };
    await perform(async () =>
      unwrap(
        await api(context.organizationId).POST(
          "/api/v1/memory/entries/{identifier}/action",
          { params, body: { ...body, idempotency_key: key(body) } },
        ),
      ),
    );
  }
  return (
    <div className="memory-detail">
      <div className="section-line">
        <span className="tag">
          {row.outdated ? "来源已更新 · 需复核" : stateNames[row.state]}
        </span>
        <button
          className="plain"
          disabled={busy}
          onClick={() =>
            void perform(async () =>
              unwrap(
                await api(context.organizationId).GET(
                  "/api/v1/memory/entries/{identifier}",
                  { params },
                ),
              ),
            )
          }
        >
          <RefreshCw size={14} />
          刷新
        </button>
      </div>
      <MemorySource row={row} timezone={context.timezone} />
      {row.outdated && (
        <Feedback kind="error">
          出现新的结果。请核对全部来源、更新候选并重新确认；当前不会供 Agent
          引用。
        </Feedback>
      )}
      {row.can_edit ? (
        <>
          <form
            onSubmit={(e) => {
              e.preventDefault();
              void save();
            }}
          >
            <label>
              标题
              <input
                required
                maxLength={200}
                value={title}
                onChange={(e) => {
                  setTitle(e.target.value);
                  setConfirmed(false);
                }}
              />
            </label>
            <label>
              {row.kind === "experience" ? "经验解释" : "偏好内容"}
              <textarea
                required
                rows={4}
                maxLength={800}
                value={content}
                onChange={(e) => {
                  setContent(e.target.value);
                  setConfirmed(false);
                }}
              />
            </label>
            <label>
              适用条件与待核实信息
              <textarea
                required
                rows={3}
                maxLength={600}
                value={applicability}
                onChange={(e) => {
                  setApplicability(e.target.value);
                  setConfirmed(false);
                }}
              />
            </label>
            <label>
              来源原文引句
              <textarea
                required
                rows={3}
                maxLength={500}
                value={quote}
                onChange={(e) => {
                  setQuote(e.target.value);
                  setConfirmed(false);
                }}
              />
            </label>
            <button
              className="secondary"
              disabled={
                busy ||
                !title.trim() ||
                !content.trim() ||
                !applicability.trim() ||
                !quote.trim() ||
                (!dirty && !row.outdated && row.state === "proposed")
              }
            >
              保存候选
            </button>
            <p className="fine-print">
              修改后需重新确认。引句必须逐字来自所选实际结果或本人输入。
            </p>
          </form>
          {row.state === "proposed" && !row.outdated && !dirty && (
            <AgentReader
              key={`${row.id}:${row.version}`}
              organizationId={context.organizationId}
              task="memory_draft"
              memoryId={row.id}
              onMemory={receive}
            />
          )}
          {row.state === "proposed" && (
            <div className="confirmation-box">
              <label className="checkbox-line">
                <input
                  type="checkbox"
                  checked={confirmed}
                  disabled={dirty || row.outdated || !row.content}
                  onChange={(e) => setConfirmed(e.target.checked)}
                />
                我已核对来源、内容和适用条件，确认供后续参考
              </label>
              <button
                className="primary"
                disabled={busy || !confirmed || dirty || row.outdated}
                onClick={() => void act("confirm")}
              >
                确认生效
              </button>
            </div>
          )}
          <div className="settings-actions">
            {row.state === "confirmed" && (
              <button
                className="plain"
                disabled={busy}
                onClick={() => void act("revoke")}
              >
                撤销生效
              </button>
            )}
            <button
              className="plain"
              disabled={busy}
              onClick={() => setDeleting(true)}
            >
              删除条目
            </button>
          </div>
          {deleting && (
            <div className="confirmation-box">
              <p>删除后清除条目内容及相关旧分析，审计和原始决策记录保留。</p>
              <button
                className="secondary"
                disabled={busy}
                onClick={() => void act("delete")}
              >
                确认删除
              </button>
              <button className="plain" onClick={() => setDeleting(false)}>
                保留
              </button>
            </div>
          )}
        </>
      ) : (
        <>
          <h3>{row.title}</h3>
          <p>{row.content}</p>
          <p>适用条件：{row.applicability}</p>
          <blockquote>{row.source_quote}</blockquote>
        </>
      )}
      {error && <Feedback kind="error">{error}</Feedback>}
    </div>
  );
}

export function MemoryCenter({
  organizationId,
  timezone,
  kind: fixedKind,
}: Context & { kind?: Kind }) {
  const [chosenKind, setChosenKind] = useState<Kind>("experience");
  const kind = fixedKind ?? chosenKind;
  return (
    <MemoryCollection
      key={`${organizationId}:${kind}`}
      organizationId={organizationId}
      timezone={timezone}
      kind={kind}
      onKindChange={fixedKind ? undefined : setChosenKind}
    />
  );
}

// Scope changes remount the collection and its drawers together. Late reads or
// saves keep their old instance's callbacks and cannot restore an old draft.
function MemoryCollection({
  organizationId,
  timezone,
  kind,
  onKindChange,
}: Context & { kind: Kind; onKindChange?: (kind: Kind) => void }) {
  const [rows, setRows] = useState<Entry[]>([]);
  const [total, setTotal] = useState(0);
  const [offset, setOffset] = useState(0);
  const [revision, setRevision] = useState(0);
  const [selected, setSelected] = useState<Entry | null>(null);
  const [creating, setCreating] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const context = { organizationId, timezone };
  useEffect(() => {
    let active = true;
    setLoading(true);
    setRows([]);
    setError("");
    api(organizationId)
      .GET("/api/v1/memory/entries", {
        params: {
          header: { "x-organization-id": organizationId },
          query: { kind, offset, limit: 20 },
        },
      })
      .then(unwrap)
      .then((result) => {
        if (active) {
          setRows(result.items);
          setTotal(result.total);
        }
      })
      .catch((e: Error) => {
        if (active) setError(e.message);
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => {
      active = false;
    };
  }, [organizationId, kind, offset, revision]);
  function changed(row: Entry) {
    setSelected(row.state === "deleted" ? null : row);
    setRevision((value) => value + 1);
  }
  return (
    <section
      className="memory-center"
      aria-label={kind === "experience" ? "决策经验" : "我的偏好"}
    >
      <div className="section-line">
        {onKindChange ? (
          <div
            className="settings-tabs"
            role="tablist"
            aria-label="经验与偏好类别"
          >
            {(["experience", "preference"] as const).map((value) => (
              <button
                key={value}
                role="tab"
                aria-selected={kind === value}
                className={kind === value ? "active" : ""}
                onClick={() => onKindChange(value)}
              >
                {value === "experience" ? "决策经验" : "我的偏好"}
              </button>
            ))}
          </div>
        ) : (
          <h2>{kind === "experience" ? "经验记录" : "我的偏好"}</h2>
        )}
        <button className="primary" onClick={() => setCreating(true)}>
          <Plus size={16} />
          {kind === "experience" ? "整理经验" : "添加偏好"}
        </button>
      </div>
      <p className="muted">
        {kind === "experience"
          ? "从已确认决策及实际结果中整理经验，保留适用条件、失败和不确定信息。"
          : "只参考你明确表达并确认的重点与原则。其他人无法查看你的私人偏好。"}
      </p>
      {error && <Feedback kind="error">{error}</Feedback>}
      {loading ? (
        <p role="status">正在读取已授权条目…</p>
      ) : rows.length ? (
        <div className="memory-list">
          {rows.map((row) => (
            <button
              key={row.id}
              className="memory-row"
              onClick={() => setSelected(row)}
            >
              <BookOpen size={18} />
              <span>
                <strong>{row.title}</strong>
                <small>{row.content || "尚未整理内容"}</small>
              </span>
              <span className="tag">
                {row.outdated ? "需复核" : stateNames[row.state]}
              </span>
            </button>
          ))}
        </div>
      ) : (
        <div className="empty-state">
          <BookOpen size={24} />
          <p>
            {kind === "experience"
              ? "还没有决策经验。记录实际结果后，可以在这里整理。"
              : "还没有明确确认的偏好。你可以先写下希望参考的重点。"}
          </p>
        </div>
      )}
      {total > 20 && (
        <div className="settings-actions">
          <button
            className="plain"
            disabled={loading || offset === 0}
            onClick={() => setOffset(Math.max(0, offset - 20))}
          >
            上一页
          </button>
          <span>
            {offset + 1}–{Math.min(offset + 20, total)} / {total}
          </span>
          <button
            className="plain"
            disabled={loading || offset + 20 >= total}
            onClick={() => setOffset(offset + 20)}
          >
            下一页
          </button>
        </div>
      )}
      {creating && (
        <Drawer
          title={kind === "experience" ? "整理决策经验" : "记录我的偏好"}
          close={() => setCreating(false)}
        >
          <NewMemory
            context={context}
            kind={kind}
            onSaved={(row) => {
              setCreating(false);
              changed(row);
            }}
          />
        </Drawer>
      )}
      {selected && (
        <Drawer
          title={selected.kind === "experience" ? "决策经验" : "我的偏好"}
          close={() => setSelected(null)}
        >
          <MemoryDetail
            key={selected.id}
            initial={selected}
            context={context}
            onChanged={changed}
          />
        </Drawer>
      )}
    </section>
  );
}

export function MemoryCitations({
  answer,
  organizationId,
  timezone,
}: { answer: Schemas["AnswerOut"] } & Context) {
  const [selected, setSelected] = useState<Entry | null>(null);
  const [error, setError] = useState("");
  if (!answer.memory_answers?.length) return null;
  return (
    <section className="document-citations" aria-label="经验与偏好引用">
      <h3>历史经验与本人偏好</h3>
      <p className="fine-print">
        仅作参考，不代表当前事实或执行授权；请核对适用条件。
      </p>
      {answer.memory_answers.map((item) => {
        const source = answer.memories?.find(
          (value) => value.id === item.citation_id,
        );
        return source ? (
          <article key={source.id} className="knowledge-hit">
            <span className="tag">
              {source.kind === "experience"
                ? "已确认历史经验"
                : "本人确认的私有偏好"}
            </span>
            <blockquote>{item.quote}</blockquote>
            <p>适用条件：{source.applicability}</p>
            <button
              className="plain evidence-link"
              onClick={async () => {
                setError("");
                try {
                  setSelected(
                    unwrap(
                      await api(organizationId).GET(
                        "/api/v1/memory/entries/{identifier}",
                        {
                          params: {
                            header: { "x-organization-id": organizationId },
                            path: { identifier: source.id },
                          },
                        },
                      ),
                    ),
                  );
                } catch (e) {
                  setError(
                    e instanceof Error ? e.message : "来源已变化，请重新查询",
                  );
                }
              }}
            >
              核对来源 · {source.title}
            </button>
          </article>
        ) : null;
      })}
      {error && <Feedback kind="error">{error}</Feedback>}
      {selected && (
        <Drawer title="核对经验与偏好来源" close={() => setSelected(null)}>
          <p className="fine-print">
            当前状态：{stateNames[selected.state]} · 版本 {selected.version}
          </p>
          {(selected.outdated ||
            selected.state !== "confirmed" ||
            answer.memories?.find((item) => item.id === selected.id)
              ?.version !== selected.version) && (
            <Feedback kind="error">
              条目或来源已变化，请重新查询并核对当前内容。
            </Feedback>
          )}
          <MemorySource row={selected} timezone={timezone} />
        </Drawer>
      )}
    </section>
  );
}
