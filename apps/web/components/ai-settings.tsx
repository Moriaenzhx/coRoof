"use client";
import { useCallback, useEffect, useRef, useState } from "react";
import {
  Check,
  ChevronRight,
  Plus,
  RefreshCw,
  ShieldCheck,
  Sparkles,
} from "lucide-react";
import { api, formatTime, unwrap, type Schemas } from "../lib/api";
import { Feedback } from "./status";

type Connection = Schemas["ConnectionOut"];
type Policy = Schemas["PolicyOut"];
type Usage = Schemas["UsageOut"];
type Tab = "usage" | "connections" | "budget" | "audit";
const stateLabels: Record<Connection["state"], string> = {
  draft: "待测试",
  testing: "测试中",
  tested: "连接测试通过",
  failed: "测试未通过",
  revoked: "已撤销",
};
const errorLabels: Record<string, string> = {
  authentication: "凭据未通过认证",
  permission: "账号无访问权限",
  timeout: "请求超时",
  rate_limited: "供应商限流或额度不足",
  invalid_request: "模型不支持当前请求参数",
  invalid_output: "输出未符合结构要求",
  not_configured: "连接或加密配置不可用",
  budget_exceeded: "应用额度不足",
  policy_denied: "端点不符合接入策略",
  unavailable: "供应商暂不可用",
};
const number = (n: number) => new Intl.NumberFormat("zh-CN").format(n);
const codingPlanUrl = "https://coding.dashscope.aliyuncs.com/v1";

export function AiSettings({
  organizationId,
  isOwner,
  timezone,
  initialTab = "usage",
}: {
  organizationId: string;
  isOwner: boolean;
  timezone: string;
  initialTab?: "usage" | "connections";
}) {
  const [tab, setTab] = useState<Tab>("usage");
  const [usage, setUsage] = useState<Usage | null>(null);
  const [policy, setPolicy] = useState<Policy | null>(null);
  const [connections, setConnections] = useState<Connection[]>([]);
  const [providers, setProviders] = useState<Schemas["ProviderOut"][]>([]);
  const [events, setEvents] = useState<Schemas["ConfigEventOut"][]>([]);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [busy, setBusy] = useState(false);
  const [adding, setAdding] = useState(false);
  const [revokeId, setRevokeId] = useState<string | null>(null);
  const generation = useRef(0);
  const createKey = useRef(crypto.randomUUID());
  const testKeys = useRef(new Map<string, string>());
  const [form, setForm] = useState({
    name: "",
    provider: "openai" as Schemas["ConnectionInput"]["provider"],
    model: "",
    base_url: "https://api.openai.com/v1",
    output_mode: "schema" as "schema" | "json",
    api_key: "",
  });
  const load = useCallback(async () => {
    const request = ++generation.current;
    const client = api(organizationId);
    const params = { header: { "x-organization-id": organizationId } };
    const currentUsage = unwrap(
      await client.GET("/api/v1/ai/usage", { params }),
    );
    if (request !== generation.current) return;
    if (isOwner) {
      const [p, c, catalog, audit] = await Promise.all([
        client.GET("/api/v1/ai/settings", { params }),
        client.GET("/api/v1/ai/connections", { params }),
        client.GET("/api/v1/ai/providers", { params }),
        client.GET("/api/v1/ai/config-events", { params }),
      ]);
      if (request !== generation.current) return;
      setPolicy(unwrap(p));
      setConnections(unwrap(c));
      setProviders(unwrap(catalog));
      setEvents(unwrap(audit));
    }
    if (request === generation.current) setUsage(currentUsage);
  }, [organizationId, isOwner]);
  useEffect(() => {
    let alive = true;
    setUsage(null);
    setPolicy(null);
    setConnections([]);
    setProviders([]);
    setEvents([]);
    setTab(isOwner ? initialTab : "usage");
    setAdding(false);
    setError("");
    setNotice("");
    setForm((value) => ({ ...value, api_key: "" }));
    load().catch((e: Error) => {
      if (alive) setError(e.message);
    });
    return () => {
      alive = false;
      generation.current++;
    };
  }, [load, initialTab, isOwner]);
  useEffect(() => {
    createKey.current = crypto.randomUUID();
  }, [form]);
  async function run(action: () => Promise<void>) {
    setBusy(true);
    setError("");
    setNotice("");
    try {
      await action();
    } catch (e) {
      setError(e instanceof Error ? e.message : "操作失败，请重试");
    } finally {
      setBusy(false);
    }
  }
  function policyBody(
    mode: Policy["mode"],
    connectionId: string | null,
  ): Schemas["PolicyInput"] {
    if (!policy) throw new Error("设置尚未加载");
    return {
      expected_version: policy.version,
      mode,
      connection_id: connectionId,
      daily_call_limit: policy.daily_call_limit,
      daily_token_limit: policy.daily_token_limit,
      monthly_token_limit: policy.monthly_token_limit,
      concurrency_limit: policy.concurrency_limit,
      alert_percent: policy.alert_percent,
    };
  }
  async function savePolicy(mode: Policy["mode"], connectionId: string | null) {
    unwrap(
      await api(organizationId).PUT("/api/v1/ai/settings", {
        params: { header: { "x-organization-id": organizationId } },
        body: policyBody(mode, connectionId),
      }),
    );
    await load();
    setNotice(
      mode === "byok" &&
        connections.find((row) => row.id === connectionId)?.usage_scope ===
          "development_only"
        ? "本机开发测试已启用，不用于生产或后台常驻任务。"
        : "企业 AI 设置已保存。",
    );
  }
  async function test(row: Connection) {
    const attempt = `${row.id}:${row.version}`;
    if (!testKeys.current.has(attempt))
      testKeys.current.set(attempt, crypto.randomUUID());
    const result = unwrap(
      await api(organizationId).POST(
        "/api/v1/ai/connections/{connection_id}/test",
        {
          params: {
            header: { "x-organization-id": organizationId },
            path: { connection_id: row.id },
          },
          body: {
            expected_version: row.version,
            idempotency_key: testKeys.current.get(attempt)!,
          },
        },
      ),
    );
    testKeys.current.delete(attempt);
    await load();
    setNotice(
      result.state === "tested"
        ? !result.can_activate
          ? "连接测试结果已记录；当前未获准启用。"
          : result.usage_scope === "development_only"
            ? "本机开发测试连接已通过。确认后仅用于本机测试，不用于生产。"
            : "连接测试通过。确认后可启用此连接。"
        : errorLabels[result.last_error || ""] ||
            "连接测试未完成，请检查配置后重试。",
    );
  }
  const selected = connections.find((row) => row.id === policy?.connection_id);
  const registeringDeveloperKey =
    form.provider === "bailian" &&
    form.base_url.replace(/\/$/, "") === codingPlanUrl;
  function configureFrom(row: Connection) {
    const preset = providers.find((p) => p.id === row.provider);
    setForm({
      name: `${row.name.slice(0, 60)} · 新连接`,
      provider: row.provider,
      model: row.model,
      base_url:
        row.usage_scope === "development_only"
          ? preset?.base_url || ""
          : row.base_url,
      output_mode: preset?.output_mode || row.output_mode,
      api_key: "",
    });
    setAdding(true);
    setNotice("填写新的 API Key 后保存并测试。确认启用前，当前连接保持不变。");
  }
  const tabs: { id: Tab; label: string }[] = [
    { id: "usage", label: "使用概览" },
    ...(isOwner
      ? [
          { id: "connections" as const, label: "AI 服务" },
          { id: "budget" as const, label: "预算与限制" },
          { id: "audit" as const, label: "操作记录" },
        ]
      : []),
  ];
  return (
    <section className="ai-settings" aria-label="AI 使用与设置">
      <div className="settings-toolbar">
        <div className="settings-tabs" role="tablist" aria-label="AI 管理栏目">
          {tabs.map(({ id, label }) => (
            <button
              key={id}
              role="tab"
              aria-selected={tab === id}
              aria-controls={`ai-panel-${id}`}
              id={`ai-tab-${id}`}
              tabIndex={tab === id ? 0 : -1}
              onKeyDown={(event) => {
                if (
                  !["ArrowLeft", "ArrowRight", "Home", "End"].includes(
                    event.key,
                  )
                )
                  return;
                event.preventDefault();
                const index = tabs.findIndex((item) => item.id === id);
                const next =
                  event.key === "Home"
                    ? 0
                    : event.key === "End"
                      ? tabs.length - 1
                      : (index +
                          (event.key === "ArrowRight" ? 1 : -1) +
                          tabs.length) %
                        tabs.length;
                setTab(tabs[next].id);
                document.getElementById(`ai-tab-${tabs[next].id}`)?.focus();
              }}
              onClick={() => setTab(id)}
            >
              {label}
            </button>
          ))}
        </div>
        <button
          className="icon-button"
          aria-label="刷新 AI 使用情况"
          disabled={busy}
          onClick={() => run(load)}
        >
          <RefreshCw size={17} />
        </button>
      </div>
      {error && (
        <Feedback kind="error">
          {error}
          <button className="plain" onClick={() => run(load)}>
            刷新数据
          </button>
        </Feedback>
      )}
      {notice && (
        <p role="status" className="settings-notice">
          {notice}
        </p>
      )}
      {!usage ? (
        <p className="muted" role="status">
          正在读取 AI 使用记录…
        </p>
      ) : (
        <div
          role="tabpanel"
          id={`ai-panel-${tab}`}
          aria-labelledby={`ai-tab-${tab}`}
        >
          {tab === "usage" && (
            <>
              <div className="settings-intro">
                <span className="eyebrow">
                  {isOwner ? "企业用量" : "我的用量"} / 本月 · UTC
                </span>
                <h2>了解 AI 如何支持工作</h2>
                <p>
                  按实际调用记录统计，连接测试单独计数。更新时间{" "}
                  {formatTime(usage.end, timezone)}
                </p>
              </div>
              {usage.alert && (
                <Feedback kind="error">
                  本月预算占用已达到预警线。请检查用量或调整额度。
                </Feedback>
              )}
              <div className="ai-stat-grid">
                <div>
                  <span>业务模型调用</span>
                  <strong>{number(usage.business_tasks)}</strong>
                  <small>另有 {number(usage.test_calls)} 次验收测试调用</small>
                </div>
                <div>
                  <span>已报告 Token</span>
                  <strong>
                    {number(usage.input_tokens + usage.output_tokens)}
                  </strong>
                  <small>
                    {usage.unknown_usage_calls
                      ? `${usage.unknown_usage_calls} 次调用用量未知`
                      : "输入与输出合计"}
                  </small>
                </div>
                <div>
                  <span>本月预算占用</span>
                  <strong>{number(usage.quota_occupied_tokens)}</strong>
                  <small>
                    {usage.monthly_token_limit
                      ? `上限 ${number(usage.monthly_token_limit)} Token`
                      : "企业额度由所有者管理"}
                  </small>
                </div>
                <div>
                  <span>实际费用</span>
                  <strong className="unknown-value">尚未核算</strong>
                  <small>以供应商账单为准</small>
                </div>
              </div>
              <p className="settings-footnote">
                预算占用包含未完成或用量未知请求的预留额度，可能高于已报告
                Token。金额预算和供应商余额尚未接入。
              </p>
              <div className="settings-card">
                <div className="settings-card-heading">
                  <h3>使用趋势</h3>
                  <span className="muted">模型调用次数</span>
                </div>
                {usage.daily.length ? (
                  <div className="usage-bars">
                    {usage.daily.map((day) => (
                      <div key={day.label} className="usage-bar-row">
                        <span>{day.label.slice(5)}</span>
                        <div>
                          <i
                            style={{
                              width: `${(day.calls / Math.max(...usage.daily.map((d) => d.calls), 1)) * 100}%`,
                            }}
                          />
                        </div>
                        <strong>{number(day.calls)}</strong>
                      </div>
                    ))}
                  </div>
                ) : (
                  <p className="settings-empty">
                    本月尚无模型调用记录。这里不会计入独立脚本中的开发测试。
                  </p>
                )}
              </div>
              <div className="settings-card">
                <h3>模型分布</h3>
                {usage.models.length ? (
                  <div className="settings-table-wrap">
                    <table className="settings-table">
                      <thead>
                        <tr>
                          <th>供应商 / 模型（最多 20 项）</th>
                          <th>调用</th>
                          <th>已报告 Token</th>
                          <th>用量未知</th>
                        </tr>
                      </thead>
                      <tbody>
                        {usage.models.map((model) => (
                          <tr key={model.label}>
                            <td>{model.label}</td>
                            <td>{number(model.calls)}</td>
                            <td>
                              {number(model.input_tokens + model.output_tokens)}
                            </td>
                            <td>{model.unknown_usage_calls} 次</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                ) : (
                  <p className="muted">有实际调用后显示。</p>
                )}
              </div>
              <div className="settings-health">
                <span>成功 {usage.succeeded}</span>
                <span>失败 {usage.failed}</span>
                <span>处理中 / 结果未知 {usage.pending_or_unknown}</span>
                <span>
                  平均耗时{" "}
                  {usage.average_latency_ms === null
                    ? "未知"
                    : `${(usage.average_latency_ms / 1000).toFixed(1)} 秒`}
                </span>
              </div>
            </>
          )}
          {isOwner && tab === "connections" && policy && (
            <>
              <div className="settings-intro">
                <span className="eyebrow">企业 AI 服务</span>
                <h2>选择适合企业的模型连接</h2>
                <p>
                  当前：
                  {policy.mode === "byok"
                    ? `${selected?.usage_scope === "development_only" ? "本机开发测试（不用于生产）" : "企业自带凭据"} · ${selected?.name || "连接不可用"}`
                    : policy.mode === "disabled"
                      ? "已停用模型 · 使用规则整理"
                      : "平台提供服务"}
                </p>
              </div>
              <div className="service-options">
                <div className="settings-card">
                  <Sparkles size={22} />
                  <h3>平台提供服务</h3>
                  <p>由部署管理员维护模型与凭据，企业无需提供 API Key。</p>
                  <p className="muted">
                    {policy.platform_ready
                      ? `${policy.platform_provider} / ${policy.platform_model}`
                      : "平台模型尚未就绪，当前使用规则整理。"}
                  </p>
                  <button
                    className="secondary"
                    disabled={
                      busy ||
                      !policy.platform_ready ||
                      policy.mode === "platform"
                    }
                    onClick={() => run(() => savePolicy("platform", null))}
                  >
                    {policy.mode === "platform"
                      ? "当前模式"
                      : "确认使用平台服务"}
                  </button>
                </div>
                <div className="settings-card">
                  <ShieldCheck size={22} />
                  <h3>自己配置 API Key</h3>
                  <p>
                    老板可在这里填写供应商、模型和 API
                    Key，测试后供本企业使用。模型费用由供应商向企业收取。
                  </p>
                  <p className="muted">
                    支持 OpenAI、Claude、Gemini、Qwen、DeepSeek
                    与经允许的兼容服务。
                  </p>
                  <button
                    className="secondary"
                    disabled={busy || !policy.credential_storage_ready}
                    onClick={() => setAdding(true)}
                  >
                    <Plus size={16} />
                    配置自己的 API Key
                  </button>
                </div>
              </div>
              {!policy.credential_storage_ready && (
                <p className="settings-notice">
                  服务器尚未启用凭据加密存储。部署管理员完成配置后，可添加企业连接。
                </p>
              )}
              {adding && (
                <form
                  className="settings-card connection-form"
                  onSubmit={(event) => {
                    event.preventDefault();
                    run(async () => {
                      const saved = unwrap(
                        await api(organizationId).POST(
                          "/api/v1/ai/connections",
                          {
                            params: {
                              header: { "x-organization-id": organizationId },
                            },
                            body: {
                              ...form,
                              idempotency_key: createKey.current,
                            },
                          },
                        ),
                      );
                      setForm({ ...form, api_key: "", name: "", model: "" });
                      setAdding(false);
                      await load();
                      setNotice(
                        saved.usage_scope === "development_only"
                          ? saved.can_test || saved.can_activate
                            ? "开发凭据已保存。可先进行本机开发测试；不用于生产。"
                            : "开发凭据已保存，可在下方查看和管理；尚未启用业务调用。"
                          : "连接已保存，请先测试，再明确启用。",
                      );
                    });
                  }}
                >
                  <h3>新增模型连接</h3>
                  <p className="muted">
                    更换模型或凭据时创建新连接，通过测试后切换；旧连接可用于回退。
                  </p>
                  <div className="settings-form-grid">
                    <label>
                      连接名称
                      <input
                        autoFocus
                        required
                        maxLength={80}
                        value={form.name}
                        onChange={(e) =>
                          setForm({ ...form, name: e.target.value })
                        }
                        placeholder="例如：企业主用模型"
                      />
                    </label>
                    <label>
                      供应商
                      <select
                        value={form.provider}
                        onChange={(e) => {
                          const p = providers.find(
                            (p) => p.id === e.target.value,
                          );
                          if (p)
                            setForm({
                              ...form,
                              provider: p.id,
                              base_url: p.base_url,
                              output_mode: p.output_mode,
                              api_key: "",
                            });
                        }}
                      >
                        {providers.map((p) => (
                          <option key={p.id} value={p.id}>
                            {p.label}
                          </option>
                        ))}
                      </select>
                    </label>
                    <label>
                      模型 ID
                      <input
                        required
                        maxLength={50}
                        value={form.model}
                        onChange={(e) =>
                          setForm({ ...form, model: e.target.value })
                        }
                        placeholder="供应商账号中可用的精确模型 ID"
                      />
                    </label>
                    {form.provider === "bailian" && (
                      <label>
                        百炼凭据用途
                        <select
                          value={
                            registeringDeveloperKey
                              ? "development"
                              : "application"
                          }
                          onChange={(e) =>
                            setForm({
                              ...form,
                              api_key: "",
                              base_url:
                                e.target.value === "development"
                                  ? codingPlanUrl
                                  : providers.find((p) => p.id === "bailian")!
                                      .base_url,
                            })
                          }
                        >
                          <option value="application">
                            企业应用 · 通用 API Key
                          </option>
                          <option value="development">
                            Coding Plan · 仅保存管理
                          </option>
                        </select>
                      </label>
                    )}
                    <label>
                      API 端点
                      <input
                        required
                        type="url"
                        value={form.base_url}
                        onChange={(e) =>
                          setForm({ ...form, base_url: e.target.value })
                        }
                      />
                    </label>
                    <label>
                      输出模式
                      <select
                        value={form.output_mode}
                        disabled={
                          providers.find((p) => p.id === form.provider)
                            ?.protocol !== "chat"
                        }
                        onChange={(e) =>
                          setForm({
                            ...form,
                            output_mode: e.target.value as "schema" | "json",
                          })
                        }
                      >
                        <option value="schema">JSON Schema</option>
                        <option value="json">JSON 对象 + 本地严格校验</option>
                      </select>
                    </label>
                    <label>
                      API Key
                      <input
                        type="password"
                        required
                        minLength={8}
                        maxLength={2048}
                        autoComplete="off"
                        value={form.api_key}
                        onChange={(e) => {
                          const key = e.target.value;
                          setForm({
                            ...form,
                            api_key: key,
                            ...(form.provider === "bailian" &&
                            key.startsWith("sk-sp-")
                              ? { base_url: codingPlanUrl }
                              : {}),
                          });
                        }}
                      />
                    </label>
                  </div>
                  <p className="settings-footnote">
                    凭据加密保存在服务器，保存后仅显示尾号。自定义端点须由部署管理员预先允许。连接测试会发送合成材料并消耗供应商额度。
                  </p>
                  {registeringDeveloperKey && (
                    <p className="settings-notice">
                      这是 Coding Plan
                      开发凭据。可以保存到企业列表查看、撤销或另配业务连接；不会自动启用为企业应用模型。
                    </p>
                  )}
                  {form.provider === "openai_compatible" && (
                    <p className="muted">
                      允许的兼容端点：
                      {policy.allowed_custom_base_urls.join("、") || "尚未登记"}
                    </p>
                  )}
                  <div className="settings-actions">
                    <button className="primary" disabled={busy}>
                      {registeringDeveloperKey
                        ? "保存开发凭据"
                        : "保存待测试连接"}
                    </button>
                    <button
                      type="button"
                      className="plain"
                      onClick={() => {
                        setAdding(false);
                        setForm({ ...form, api_key: "" });
                      }}
                    >
                      取消
                    </button>
                  </div>
                </form>
              )}
              <div className="settings-card">
                <h3>已保存的 API 连接</h3>
                <p className="muted">
                  保存后即在这里显示。测试和启用需要分别操作；本机开发测试连接不用于生产。
                </p>
                {connections.length === 0 && (
                  <p className="settings-empty">尚未添加企业连接。</p>
                )}
                {connections.map((row) => (
                  <div className="connection-row" key={row.id}>
                    <div>
                      <strong>
                        {row.name}{" "}
                        {policy.connection_id === row.id && (
                          <span className="connection-active">
                            <Check size={13} />
                            {row.usage_scope === "development_only"
                              ? row.can_activate
                                ? "本机测试使用中"
                                : "已选连接 · 当前不可用"
                              : "使用中"}
                          </span>
                        )}
                      </strong>
                      <p>
                        {providers.find((p) => p.id === row.provider)?.label ||
                          row.provider}{" "}
                        / {row.model}
                      </p>
                      <p className="connection-endpoint">{row.base_url}</p>
                      <small>
                        {row.usage_scope === "development_only" &&
                        row.state !== "revoked"
                          ? row.can_test || row.can_activate
                            ? `本机开发测试 · ${stateLabels[row.state]} · 不用于生产`
                            : "已保存 · 仅开发用途"
                          : stateLabels[row.state]}{" "}
                        · API Key {row.key_hint}
                        {(row.usage_scope === "application" ||
                          row.can_test ||
                          row.can_activate) && (
                          <>
                            {" "}
                            ·{" "}
                            {row.tested_at
                              ? formatTime(row.tested_at, timezone)
                              : "尚未测试"}
                          </>
                        )}
                      </small>
                      {row.usage_notice && (
                        <p className="connection-notice">{row.usage_notice}</p>
                      )}
                      {row.last_error && (
                        <p className="connection-error">
                          {errorLabels[row.last_error] ||
                            "测试失败，请核对配置。"}
                        </p>
                      )}
                    </div>
                    {row.state !== "revoked" && (
                      <div className="settings-actions">
                        {(row.can_test || row.can_activate) && (
                          <>
                            <button
                              className="secondary"
                              disabled={
                                busy ||
                                !row.can_test ||
                                policy.connection_id === row.id
                              }
                              onClick={() => run(() => test(row))}
                            >
                              {row.state === "testing"
                                ? "检查并重试测试"
                                : row.usage_scope === "development_only"
                                  ? "测试连接（本机）"
                                  : "测试连接"}
                            </button>
                            <button
                              className="secondary"
                              disabled={
                                busy ||
                                !row.can_activate ||
                                policy.connection_id === row.id
                              }
                              onClick={() =>
                                run(() => savePolicy("byok", row.id))
                              }
                            >
                              {row.usage_scope === "development_only"
                                ? "确认启用本机测试"
                                : "确认启用"}
                              <ChevronRight size={14} />
                            </button>
                          </>
                        )}
                        <button
                          className="secondary"
                          disabled={busy || !policy.credential_storage_ready}
                          onClick={() => configureFrom(row)}
                        >
                          {row.usage_scope === "development_only"
                            ? "配置业务 API Key"
                            : "更换配置"}
                        </button>
                        <button
                          className="plain"
                          disabled={busy}
                          onClick={() => setRevokeId(row.id)}
                        >
                          撤销
                        </button>
                        {revokeId === row.id && (
                          <div className="revoke-confirm">
                            <span>
                              撤销会删除已保存的凭据，并停用正在使用的此连接。
                            </span>
                            <button
                              className="secondary"
                              disabled={busy}
                              onClick={() =>
                                run(async () => {
                                  unwrap(
                                    await api(organizationId).POST(
                                      "/api/v1/ai/connections/{connection_id}/revoke",
                                      {
                                        params: {
                                          header: {
                                            "x-organization-id": organizationId,
                                          },
                                          path: { connection_id: row.id },
                                        },
                                        body: {
                                          expected_version: row.version,
                                          idempotency_key: crypto.randomUUID(),
                                        },
                                      },
                                    ),
                                  );
                                  setRevokeId(null);
                                  await load();
                                  setNotice("连接已撤销。");
                                })
                              }
                            >
                              确认撤销
                            </button>
                            <button
                              className="plain"
                              onClick={() => setRevokeId(null)}
                            >
                              取消
                            </button>
                          </div>
                        )}
                      </div>
                    )}
                  </div>
                ))}
              </div>
              <div className="settings-card settings-pause">
                <div>
                  <h3>暂停企业模型调用</h3>
                  <p>
                    暂停后使用明确标识的规则整理。已发出的请求可能仍产生费用。
                  </p>
                </div>
                <button
                  className="secondary"
                  disabled={busy || policy.mode === "disabled"}
                  onClick={() => run(() => savePolicy("disabled", null))}
                >
                  {policy.mode === "disabled" ? "已暂停" : "确认暂停"}
                </button>
              </div>
            </>
          )}
          {isOwner && tab === "budget" && policy && (
            <>
              <div className="settings-intro">
                <span className="eyebrow">企业额度</span>
                <h2>让使用保持在可控范围</h2>
                <p>这里设置应用调用额度。金额账单与供应商余额尚未接入。</p>
              </div>
              <form
                className="settings-card"
                onSubmit={(event) => {
                  event.preventDefault();
                  run(() => savePolicy(policy.mode, policy.connection_id));
                }}
              >
                <div className="settings-form-grid">
                  {(
                    [
                      {
                        key: "daily_call_limit",
                        label: "滚动 24 小时调用上限",
                        min: 1,
                        max: 10000,
                      },
                      {
                        key: "daily_token_limit",
                        label: "滚动 24 小时 Token 上限",
                        min: 1000,
                        max: 10000000,
                      },
                      {
                        key: "monthly_token_limit",
                        label: "自然月 Token 上限（UTC）",
                        min: 1000,
                        max: 1000000000,
                      },
                      {
                        key: "concurrency_limit",
                        label: "同时处理的调用数",
                        min: 1,
                        max: 10,
                      },
                      {
                        key: "alert_percent",
                        label: "月度额度预警线（%）",
                        min: 1,
                        max: 100,
                      },
                    ] as const
                  ).map((field) => (
                    <label key={field.key}>
                      {field.label}
                      <input
                        type="number"
                        required
                        min={field.min}
                        max={field.max}
                        value={policy[field.key]}
                        onChange={(event) =>
                          setPolicy({
                            ...policy,
                            [field.key]: Number(event.target.value),
                          })
                        }
                      />
                    </label>
                  ))}
                </div>
                <p className="settings-footnote">
                  请求前预留额度，达到上限时停止接收新的模型调用并转为规则整理。平台服务受部署方额度上限约束。预警在本页展示；邮件或短信通知尚未接入。
                </p>
                <button className="primary" disabled={busy}>
                  保存额度设置
                </button>
              </form>
            </>
          )}
          {isOwner && tab === "audit" && (
            <>
              <div className="settings-intro">
                <span className="eyebrow">配置历史</span>
                <h2>每次变更都有记录</h2>
                <p>显示最近 50 条配置和连接测试记录，不记录密钥或业务原文。</p>
              </div>
              <div className="settings-card">
                {events.length ? (
                  <ol className="config-event-list">
                    {events.map((event) => (
                      <li key={event.id}>
                        <strong>
                          {(
                            {
                              "connection.created": "新增连接",
                              "connection.imported": "导入已有配置",
                              "connection.revoked": "撤销连接",
                              "connection.test_started": "开始连接测试",
                              "connection.test_finished": "连接测试结束",
                              "settings.saved": "更新企业设置",
                            } as Record<string, string>
                          )[event.action] || "配置变更"}
                        </strong>
                        <p>{event.detail}</p>
                        <small>
                          {event.actor_name} · 版本 {event.revision} ·{" "}
                          {formatTime(event.recorded_at, timezone)}
                        </small>
                      </li>
                    ))}
                  </ol>
                ) : (
                  <p className="settings-empty">尚无配置变更。</p>
                )}
              </div>
            </>
          )}
        </div>
      )}
    </section>
  );
}
