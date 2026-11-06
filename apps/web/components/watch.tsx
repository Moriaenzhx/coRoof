"use client";

import { useEffect, useRef, useState } from "react";
import { ArrowRight, Clock3, Eye, Plus, RefreshCw } from "lucide-react";
import {
  api,
  formatTime,
  unwrap,
  type Department,
  type Initiative,
  type Schemas,
} from "../lib/api";
import { CoRoofAvatar } from "./companion";
import { useWatch } from "../lib/use-watch";
import { Drawer } from "./drawer";
import { EvidenceCard } from "./evidence";
import { Feedback } from "./status";

type Policy = Schemas["WatchPolicyOut"];
type Item = Schemas["AttentionOut"];
type Action = Schemas["AttentionAction"];
type Context = { organizationId: string; timezone: string };
type Openers = {
  onWork: (id: string) => void;
  onPlan: (id: string, workId: string) => void;
  onDecision: (id: string) => void;
};
const policyStates: Record<Policy["effective_state"], string> = {
  active: "已授权",
  paused: "已暂停",
  revoked: "已撤销",
  expired: "授权到期",
  unauthorized: "授权已失效",
};
const itemStates: Record<Item["state"], string> = {
  open: "待审阅",
  snoozed: "稍后处理",
  dismissed: "已忽略",
  invalidated: "旧依据已失效",
  result_recorded: "已记录结果",
};
const outcomes: Record<string, string> = {
  no_data: "范围内暂无可读工作",
  no_change: "没有需要重新分析的变化",
  rules_only: "规则核对 · 未调用模型",
  model_unavailable: "模型不可用，已保留规则核对",
  analyzed: "分析完成，建议仍需审阅",
  analysis_budget_exceeded: "已达到本策略分析轮数额度",
  source_unavailable: "来源更新失败或待更新",
  authorization_changed: "授权发生变化",
  authorization_or_context_changed: "授权、事实或配置变化，旧结果已停止",
  model_failed: "模型执行失败",
  model_unknown: "调用结果未知，未自动重试",
};
const runStates: Record<string, string> = {
  queued: "等待后台处理",
  running: "正在核对",
  completed: "本轮结束",
  failed: "执行失败",
  cancelled: "已停止",
  unknown: "结果待核对",
};

export function WatchOverview({
  organizationId,
  timezone,
  onManage,
  ...open
}: Context & Openers & { onManage: () => void }) {
  const data = useWatch(organizationId);
  const visible = data.items
    .filter((item) => item.state === "open")
    .slice(0, 3);
  return (
    <section className="panel watch-overview">
      <div className="section-line">
        <h3>
          <CoRoofAvatar
            size={32}
            decorative
            state={visible.length ? "attention" : "idle"}
          />{" "}
          coRoof 的关注记录
        </h3>
        <button className="plain" onClick={onManage}>
          持续关注 <ArrowRight size={14} />
        </button>
      </div>
      {data.error ? (
        <Feedback kind="error">
          {data.error}
          <button onClick={() => void data.load()}>重试</button>
        </Feedback>
      ) : data.loading ? (
        <p className="muted">正在读取后台关注记录…</p>
      ) : (
        <>
          {!data.policies.length ? (
            <p className="muted">
              还没有授权持续关注。选定目标与范围后，后台可在你离线时核对记录、准备建议。
            </p>
          ) : (
            <p className="muted">
              {
                data.policies.filter((p) => p.effective_state === "active")
                  .length
              }{" "}
              项有效授权 · 无变化时保持安静
            </p>
          )}
          {!data.policies.some((p) => p.effective_state === "active") && (
            <button className="secondary" onClick={onManage}>
              选择关注范围与目标 <ArrowRight size={14} />
            </button>
          )}
          {visible.map((item) => (
            <div className="watch-summary" key={item.id}>
              <div>
                <strong>{item.title}</strong>
                <small>
                  {item.work_title || item.policy_name} ·{" "}
                  {formatTime(item.changed_at, timezone)}
                </small>
              </div>
              <button
                onClick={() =>
                  item.decision_id
                    ? open.onDecision(item.decision_id)
                    : item.agent_run_id && item.work_item_id
                      ? open.onPlan(item.agent_run_id, item.work_item_id)
                      : onManage()
                }
              >
                查看
              </button>
            </div>
          ))}
          {!!data.policies.length && !visible.length && (
            <p className="muted">暂无新的待处理项。尚未覆盖的信息仍然未知。</p>
          )}
        </>
      )}
    </section>
  );
}

export function WatchCenter({
  organizationId,
  timezone,
  departments,
  initiatives,
  ...open
}: Context &
  Openers & { departments: Department[]; initiatives: Initiative[] }) {
  const [tab, setTab] = useState<"inbox" | "settings">("inbox");
  const [history, setHistory] = useState(false);
  const [editor, setEditor] = useState<Policy | "new" | null>(null);
  const [reviewing, setReviewing] = useState<Item | null>(null);
  const [runs, setRuns] = useState<Policy | null>(null);
  const [confirm, setConfirm] = useState<{
    row: Policy;
    action: "pause" | "resume" | "revoke";
  } | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const guard = useRef(false);
  const keys = useRef(new Map<string, string>());
  const data = useWatch(organizationId, history);
  const context = { organizationId, timezone };
  async function change() {
    if (!confirm || guard.current) return;
    guard.current = true;
    setBusy(true);
    setError("");
    const key = `${confirm.row.id}:${confirm.row.version}:${confirm.action}`;
    if (!keys.current.has(key)) keys.current.set(key, crypto.randomUUID());
    try {
      unwrap(
        await api(organizationId).POST(
          "/api/v1/watch/policies/{policy_id}/actions",
          {
            params: {
              header: { "x-organization-id": organizationId },
              path: { policy_id: confirm.row.id },
            },
            body: {
              action: confirm.action,
              confirm: true,
              expected_version: confirm.row.version,
              idempotency_key: keys.current.get(key)!,
            },
          },
        ),
      );
      setConfirm(null);
      await data.load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "保存失败");
    } finally {
      guard.current = false;
      setBusy(false);
    }
  }
  return (
    <div className="watch-center">
      <div className="settings-actions" aria-label="持续关注页面">
        <button
          aria-pressed={tab === "inbox"}
          className={tab === "inbox" ? "secondary" : "plain"}
          onClick={() => setTab("inbox")}
        >
          需要你处理
        </button>
        <button
          aria-pressed={tab === "settings"}
          className={tab === "settings" ? "secondary" : "plain"}
          onClick={() => setTab("settings")}
        >
          关注设置
        </button>
        <button
          className="icon-button"
          aria-label="刷新关注记录"
          onClick={() => void data.load()}
        >
          <RefreshCw size={16} />
        </button>
      </div>
      {(data.error || error) && (
        <Feedback kind="error">{data.error || error}</Feedback>
      )}
      {data.loading ? (
        <p role="status">正在读取持续关注…</p>
      ) : tab === "inbox" ? (
        <section className="settings-card">
          <div className="section-line">
            <h2>老板待办</h2>
            <label className="check-line">
              <input
                type="checkbox"
                checked={history}
                onChange={(e) => setHistory(e.target.checked)}
              />
              包含处理历史
            </label>
          </div>
          <p className="muted">
            仅展示本人授权范围内的建议和待核实事项，最近 100
            条。忽略或暂缓不会改变工作状态。
          </p>
          {!data.items.length && !data.error && (
            <div className="watch-empty">
              <Eye size={24} />
              <h3>
                {data.policies.length
                  ? "暂无待审阅的关注项"
                  : "先选定一项关注目标"}
              </h3>
              <p>以已确认的工作为依据；缺少资料时明确待核实。</p>
              <button onClick={() => setTab("settings")}>管理关注设置</button>
            </div>
          )}
          {data.items.map((item) => (
            <article className="watch-item" key={item.id}>
              <div className="section-line">
                <h3>{item.title}</h3>
                <span className="tag">{itemStates[item.state]}</span>
              </div>
              <p>{item.explanation}</p>
              <small>
                {item.work_title || item.policy_name} ·{" "}
                {item.agent_run_id
                  ? "含 AI 建议"
                  : item.kind === "work"
                    ? "规则核对"
                    : "系统待办"}{" "}
                · {formatTime(item.changed_at, timezone)}
              </small>
              {item.snoozed_until && item.state === "snoozed" && (
                <p className="muted">
                  <Clock3 size={14} />{" "}
                  {formatTime(item.snoozed_until, timezone)} 后再看
                </p>
              )}
              {item.review_note && (
                <p className="watch-note">核实备注：{item.review_note}</p>
              )}
              {item.evidence && (
                <details>
                  <summary>查看依据</summary>
                  <EvidenceCard evidence={item.evidence} timezone={timezone} />
                </details>
              )}
              <div className="settings-actions">
                {item.agent_run_id && item.work_item_id && (
                  <button
                    onClick={() =>
                      open.onPlan(item.agent_run_id!, item.work_item_id!)
                    }
                  >
                    审阅推进建议
                  </button>
                )}
                {item.decision_id && (
                  <button onClick={() => open.onDecision(item.decision_id!)}>
                    查看决策与实际结果
                  </button>
                )}
                {item.work_item_id && (
                  <button
                    className="plain"
                    onClick={() => open.onWork(item.work_item_id!)}
                  >
                    查看工作记录
                  </button>
                )}
                {!["invalidated", "result_recorded"].includes(item.state) && (
                  <button className="plain" onClick={() => setReviewing(item)}>
                    处理此项
                  </button>
                )}
              </div>
            </article>
          ))}
        </section>
      ) : (
        <>
          <section className="settings-card">
            <div className="section-line">
              <h2>持续关注授权</h2>
              <button className="primary" onClick={() => setEditor("new")}>
                <Plus size={16} />
                新建关注
              </button>
            </div>
            <p>
              后台持续可用，每轮按范围核对变化。有依据才准备建议；修改计划和确认结果仍由人决定。
            </p>
            <p className="muted">
              每轮最多分析一个事项、执行六个模型步骤。策略额度按滚动 24
              小时计算，同时受企业 AI 调用和 Token 额度限制。
            </p>
          </section>
          {!data.policies.length && !data.error && (
            <p className="muted">尚未创建关注策略，不会自行替企业安排事务。</p>
          )}
          {data.policies.map((row) => (
            <section className="settings-card" key={row.id}>
              <div className="section-line">
                <h3>{row.name}</h3>
                <span className="tag">{policyStates[row.effective_state]}</span>
              </div>
              <p>{row.goal}</p>
              <div className="watch-meta">
                <span>
                  范围：
                  {row.scope_kind === "organization"
                    ? "当前企业"
                    : row.scope_kind === "department"
                      ? departments.find((d) => d.id === row.department_id)
                          ?.name || "所选部门"
                      : initiatives.find((i) => i.id === row.initiative_id)
                          ?.title || "所选项目"}
                </span>
                <span>定时核对：每 {row.interval_minutes} 分钟</span>
                <span>分析额度：{row.daily_analysis_limit} 轮 / 24 小时</span>
                <span>授权至 {formatTime(row.expires_at, timezone)}</span>
                <span>
                  最近核对：
                  {row.last_checked_at
                    ? formatTime(row.last_checked_at, timezone)
                    : "尚未检查"}
                </span>
              </div>
              <div className="settings-actions">
                <button onClick={() => setRuns(row)}>执行记录</button>
                {row.state !== "revoked" && (
                  <>
                    <button onClick={() => setEditor(row)}>编辑授权</button>
                    {row.effective_state === "active" && (
                      <button
                        onClick={() => setConfirm({ row, action: "pause" })}
                      >
                        暂停关注
                      </button>
                    )}
                    {row.effective_state === "paused" && (
                      <button
                        onClick={() => setConfirm({ row, action: "resume" })}
                      >
                        恢复关注
                      </button>
                    )}
                    <button
                      className="plain"
                      onClick={() => setConfirm({ row, action: "revoke" })}
                    >
                      撤销授权
                    </button>
                  </>
                )}
              </div>
            </section>
          ))}
        </>
      )}
      {editor && (
        <Drawer
          title={editor === "new" ? "新建持续关注" : "编辑持续关注授权"}
          close={() => setEditor(null)}
        >
          <PolicyEditor
            key={editor === "new" ? "new" : editor.id}
            context={context}
            initial={editor === "new" ? undefined : editor}
            departments={departments}
            initiatives={initiatives}
            onSaved={async () => {
              setEditor(null);
              await data.load();
            }}
          />
        </Drawer>
      )}
      {reviewing && (
        <Drawer title="处理关注项" close={() => setReviewing(null)}>
          <ReviewItem
            item={reviewing}
            context={context}
            onSaved={async () => {
              setReviewing(null);
              await data.load();
            }}
          />
        </Drawer>
      )}
      {runs && (
        <Drawer title={`${runs.name} · 执行记录`} close={() => setRuns(null)}>
          <RunHistory context={context} policy={runs} />
        </Drawer>
      )}
      {confirm && (
        <Drawer
          title="核对持续关注授权"
          close={() => !busy && setConfirm(null)}
        >
          <h3>{confirm.row.name}</h3>
          <p>
            {confirm.action === "resume"
              ? "恢复后，后台会在原范围和剩余授权期限内继续核对，模型分析计入当前额度。"
              : "停止后不会开始新的分析，旧授权下的派生建议将不可用。已由你确认的业务记录保留。"}
          </p>
          {confirm.action === "revoke" && (
            <p>撤销后不能恢复此授权，需要重新创建关注。</p>
          )}
          <p className="muted">{confirm.row.goal}</p>
          {error && <Feedback kind="error">{error}</Feedback>}
          <button
            className="primary"
            disabled={busy}
            onClick={() => void change()}
          >
            {busy
              ? "正在保存…"
              : confirm.action === "resume"
                ? "确认恢复授权"
                : confirm.action === "pause"
                  ? "确认暂停关注"
                  : "确认撤销授权"}
          </button>
        </Drawer>
      )}
    </div>
  );
}

function localDate(value: string) {
  const date = new Date(value);
  return new Date(date.getTime() - date.getTimezoneOffset() * 60000)
    .toISOString()
    .slice(0, 16);
}

function PolicyEditor({
  context,
  initial,
  departments,
  initiatives,
  onSaved,
}: {
  context: Context;
  initial?: Policy;
  departments: Department[];
  initiatives: Initiative[];
  onSaved: () => Promise<void>;
}) {
  const [name, setName] = useState(initial?.name || "");
  const [goal, setGoal] = useState(initial?.goal || "");
  const [scope, setScope] = useState<Policy["scope_kind"]>(
    initial?.scope_kind || "organization",
  );
  const [target, setTarget] = useState(
    initial?.department_id || initial?.initiative_id || "",
  );
  const [interval, setIntervalValue] = useState(
    initial?.interval_minutes || 60,
  );
  const [budget, setBudget] = useState(initial?.daily_analysis_limit || 4);
  const [expiry, setExpiry] = useState(
    localDate(
      initial?.expires_at || new Date(Date.now() + 7 * 86400000).toISOString(),
    ),
  );
  const [confirmed, setConfirmed] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const guard = useRef(false);
  const request = useRef({ body: "", key: "" });
  async function save() {
    if (guard.current || !confirmed) return;
    guard.current = true;
    setBusy(true);
    setError("");
    try {
      const fields = {
        name: name.trim(),
        goal: goal.trim(),
        scope_kind: scope,
        department_id: scope === "department" ? target : null,
        initiative_id: scope === "initiative" ? target : null,
        interval_minutes: interval,
        daily_analysis_limit: budget,
        expires_at: new Date(expiry).toISOString(),
        confirm: true as const,
      };
      const serialized = JSON.stringify(fields);
      if (request.current.body !== serialized)
        request.current = { body: serialized, key: crypto.randomUUID() };
      const body = { ...fields, idempotency_key: request.current.key };
      const header = { "x-organization-id": context.organizationId };
      if (initial)
        unwrap(
          await api(context.organizationId).POST(
            "/api/v1/watch/policies/{policy_id}/edit",
            {
              params: { header, path: { policy_id: initial.id } },
              body: { ...body, expected_version: initial.version },
            },
          ),
        );
      else
        unwrap(
          await api(context.organizationId).POST("/api/v1/watch/policies", {
            params: { header },
            body,
          }),
        );
      await onSaved();
    } catch (e) {
      setError(e instanceof Error ? e.message : "保存失败");
    } finally {
      guard.current = false;
      setBusy(false);
    }
  }
  return (
    <form
      className="watch-form"
      onSubmit={(e) => {
        e.preventDefault();
        void save();
      }}
    >
      {error && <Feedback kind="error">{error}</Feedback>}
      <fieldset disabled={busy} onChange={() => setConfirmed(false)}>
        <label>
          关注名称
          <input
            required
            maxLength={100}
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="例如：交付支持核实"
          />
        </label>
        <label>
          你确认的关注目标
          <textarea
            required
            rows={4}
            maxLength={1500}
            value={goal}
            onChange={(e) => setGoal(e.target.value)}
            placeholder="写明要推进什么、已知约束，以及希望核实的问题。"
          />
        </label>
        <label>
          授权范围
          <select
            value={scope}
            onChange={(e) => {
              setScope(e.target.value as Policy["scope_kind"]);
              setTarget("");
            }}
          >
            <option value="organization">当前企业</option>
            <option value="department">指定部门</option>
            <option value="initiative">指定项目</option>
          </select>
        </label>
        {scope !== "organization" && (
          <label>
            {scope === "department" ? "选择部门" : "选择项目"}
            <select
              required
              value={target}
              onChange={(e) => setTarget(e.target.value)}
            >
              <option value="">请选择</option>
              {scope === "department"
                ? departments.map((d) => (
                    <option key={d.id} value={d.id}>
                      {d.name}
                    </option>
                  ))
                : initiatives.map((i) => (
                    <option key={i.id} value={i.id}>
                      {i.title}
                    </option>
                  ))}
            </select>
          </label>
        )}
        <label>
          定时核对间隔（分钟）
          <input
            type="number"
            min={15}
            max={1440}
            required
            value={interval}
            onChange={(e) => setIntervalValue(Number(e.target.value))}
          />
        </label>
        <label>
          24 小时内最多分析轮数
          <input
            type="number"
            min={1}
            max={24}
            required
            value={budget}
            onChange={(e) => setBudget(Number(e.target.value))}
          />
        </label>
        <label>
          授权到期时间（按本机时区输入）
          <input
            type="datetime-local"
            required
            value={expiry}
            onChange={(e) => setExpiry(e.target.value)}
          />
        </label>
        <p className="muted">
          期限为五分钟后至九十天内。已确认的工作变化也会触发核对，未发生变化时不重复分析。
        </p>
      </fieldset>
      <label className="check-line">
        <input
          type="checkbox"
          checked={confirmed}
          onChange={(e) => setConfirmed(e.target.checked)}
        />
        我确认以上目标、范围和额度，允许后台在我离线后继续读取和准备建议。
      </label>
      <p className="muted">
        此授权不会代员工确认更新，也不会发送外部消息。你可随时暂停或撤销。
      </p>
      <button
        className="primary"
        disabled={busy || !confirmed || !name.trim() || !goal.trim()}
      >
        {busy ? "正在保存…" : initial ? "确认更新授权" : "确认并启用关注"}
      </button>
    </form>
  );
}

function ReviewItem({
  item,
  context,
  onSaved,
}: {
  item: Item;
  context: Context;
  onSaved: () => Promise<void>;
}) {
  const [note, setNote] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const guard = useRef(false);
  const requests = useRef(new Map<string, Action>());
  async function act(action: Action["action"]) {
    if (guard.current) return;
    guard.current = true;
    setBusy(true);
    setError("");
    const key = action + note;
    if (!requests.current.has(key))
      requests.current.set(key, {
        action,
        note: note.trim() || null,
        expected_version: item.version,
        idempotency_key: crypto.randomUUID(),
        snoozed_until:
          action === "snooze"
            ? new Date(Date.now() + 86400000).toISOString()
            : null,
      });
    try {
      unwrap(
        await api(context.organizationId).POST(
          "/api/v1/watch/attention/{item_id}/actions",
          {
            params: {
              header: { "x-organization-id": context.organizationId },
              path: { item_id: item.id },
            },
            body: requests.current.get(key)!,
          },
        ),
      );
      await onSaved();
    } catch (e) {
      setError(e instanceof Error ? e.message : "处理失败");
    } finally {
      guard.current = false;
      setBusy(false);
    }
  }
  return (
    <div className="watch-form">
      <h3>{item.title}</h3>
      <p>{item.explanation}</p>
      {error && <Feedback kind="error">{error}</Feedback>}
      <label>
        核实或纠正意见
        <textarea
          rows={3}
          maxLength={1000}
          value={note}
          onChange={(e) => setNote(e.target.value)}
        />
      </label>
      <p className="muted">
        这里只记录处理意见，不把备注写成工作事实。实际进展请由原作者更新并确认；忽略不代表问题解决。
      </p>
      <div className="settings-actions">
        <button disabled={busy} onClick={() => void act("snooze")}>
          24 小时后再看
        </button>
        <button disabled={busy} onClick={() => void act("dismiss")}>
          忽略此版本
        </button>
        <button
          disabled={busy || !note.trim()}
          onClick={() => void act("correct")}
        >
          记录纠正意见
        </button>
        {["snoozed", "dismissed"].includes(item.state) && (
          <button disabled={busy} onClick={() => void act("reopen")}>
            恢复待审阅
          </button>
        )}
      </div>
    </div>
  );
}

function RunHistory({ context, policy }: { context: Context; policy: Policy }) {
  const [rows, setRows] = useState<Schemas["WatchRunOut"][]>([]);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  useEffect(() => {
    let current = true;
    api(context.organizationId)
      .GET("/api/v1/watch/policies/{policy_id}/runs", {
        params: {
          header: { "x-organization-id": context.organizationId },
          path: { policy_id: policy.id },
        },
      })
      .then(unwrap)
      .then((value) => {
        if (current) setRows(value);
      })
      .catch((e: Error) => {
        if (current) setError(e.message);
      })
      .finally(() => {
        if (current) setLoading(false);
      });
    return () => {
      current = false;
    };
  }, [context.organizationId, policy.id]);
  return (
    <div>
      {error && <Feedback kind="error">{error}</Feedback>}
      <p className="muted">
        最近 20 轮。核对数量不代表工作健康或实际完成情况。
      </p>
      {loading ? (
        <p role="status">正在读取…</p>
      ) : !rows.length && !error ? (
        <p>尚未执行。后台收到任务后会在这里留下记录。</p>
      ) : (
        rows.map((row) => (
          <article className="watch-item" key={row.id}>
            <div className="section-line">
              <strong>{runStates[row.state] || row.state}</strong>
              <small>{formatTime(row.created_at, context.timezone)}</small>
            </div>
            <p>
              {row.outcome_code
                ? outcomes[row.outcome_code] || "本轮已停止，请核对配置与权限"
                : row.error_code
                  ? "执行中断或授权发生变化"
                  : "等待本轮结果"}
            </p>
            <small>
              本轮核对 {row.considered_count} / {row.coverage_count} 项 ·
              来源待更新 {row.source_warning_count} 项 ·{" "}
              {row.trigger_kind === "event" ? "已确认记录变化触发" : "定时核对"}
            </small>
          </article>
        ))
      )}
    </div>
  );
}
