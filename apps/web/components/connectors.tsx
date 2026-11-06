"use client";
import { useCallback, useEffect, useRef, useState } from "react";
import { Link2, Plus, RefreshCw } from "lucide-react";
import {
  api,
  unwrap,
  formatTime,
  statusLabels,
  type Schemas,
  type Department,
  type Member,
} from "../lib/api";
import { Drawer } from "./drawer";
import { Feedback } from "./status";

type Connection = Schemas["ConnectorOut"];
type Source = Schemas["SourceOut"];
type Mapping = Schemas["MemberMapOut"];
type Run = Schemas["SyncOut"];
type Mode = Schemas["SyncInput"]["mode"];
type Status = Schemas["WorkOut"]["lifecycle_status"];
const labels: Record<string, string> = {
  saved: "待测试",
  tested: "测试通过 · 待启用",
  active: "已启用",
  paused: "已暂停",
  revoked: "已撤销",
  permission_lost: "来源授权失效",
  queued: "排队中",
  running: "同步中",
  retry_wait: "等待重试",
  succeeded: "已完成",
  failed: "未完成",
  cancelled: "已取消",
  pending: "待映射",
  linked: "已同步",
  unknown_status: "状态待对应",
  unknown_assignees: "负责人字段未知",
  unmapped_member: "成员待对应",
  invalid_member: "成员已失效或不在该部门",
  multiple_owners: "多个负责人，需在来源核对",
  mapping_changed: "映射已修改，请重新全量同步",
  source_removed: "来源已移除",
  source_denied: "来源授权不足或已撤销",
  source_unavailable: "来源暂不可用，请查看任务状态",
  invalid_response: "来源响应无法识别",
  scope_mismatch: "来源超出所配置的范围",
  endpoint_denied: "服务地址未获部署允许",
  response_too_large: "来源响应超过单页限制",
  configuration_changed: "配置或操作权限已改变",
  sync_limit: "本次同步超出大小或时间限制",
  worker_interrupted: "任务中断，已重新排队",
  credential_unavailable: "凭据不可用，请更新",
};
const label = (value: string) => labels[value] || "需检查连接配置";
const modes = { verify: "测试连接", full: "全量同步", incremental: "增量同步" };
const running = (run: Run) =>
  ["queued", "running", "retry_wait"].includes(run.state);
const emptyCredentials = {
  token: "",
  plugin_id: "",
  plugin_secret: "",
  user_key: "",
};

function CredentialsFields({
  kind,
  value,
  onChange,
}: {
  kind: Connection["kind"];
  value: typeof emptyCredentials;
  onChange: (value: typeof emptyCredentials) => void;
}) {
  const fields =
    kind === "gitlab"
      ? [["token", "只读访问令牌"]]
      : [
          ["plugin_id", "插件 ID"],
          ["plugin_secret", "插件密钥"],
          ["user_key", "授权用户 Key"],
        ];
  return (
    <>
      {fields.map(([key, title]) => (
        <label key={key}>
          {title}
          <input
            required
            autoComplete="off"
            type={
              key === "token" || key === "plugin_secret" ? "password" : "text"
            }
            value={value[key as keyof typeof value]}
            onChange={(e) => onChange({ ...value, [key]: e.target.value })}
          />
        </label>
      ))}
    </>
  );
}

export function Connectors({
  organizationId,
  isOwner,
  departments,
  members,
  timezone,
}: {
  organizationId: string;
  isOwner: boolean;
  departments: Department[];
  members: Member[];
  timezone: string;
}) {
  const [rows, setRows] = useState<Connection[]>([]);
  const [total, setTotal] = useState(0);
  const [selected, setSelected] = useState<string | null>(null);
  const [adding, setAdding] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [loaded, setLoaded] = useState(false);
  const generation = useRef(0);
  const [form, setForm] = useState({
    name: "",
    kind: "gitlab" as Connection["kind"],
    base_url: "https://gitlab.com",
    project_key: "",
    item_type: "story",
    owner_field: "",
    department_id: departments[0]?.id || "",
    credentials: { ...emptyCredentials },
    share: false,
  });
  const load = useCallback(
    async (offset = 0) => {
      const ticket = ++generation.current;
      const result = unwrap(
        await api(organizationId).GET("/api/v1/connectors", {
          params: {
            header: { "x-organization-id": organizationId },
            query: { offset, limit: 50 },
          },
        }),
      );
      if (ticket !== generation.current) return;
      setRows((previous) =>
        offset ? [...previous, ...result.items] : result.items,
      );
      setTotal(result.total);
      setLoaded(true);
    },
    [organizationId],
  );
  useEffect(() => {
    if (isOwner) load().catch((e) => setError(e.message));
    return () => {
      generation.current++;
    };
  }, [isOwner, load]);
  async function run(action: () => Promise<void>) {
    setBusy(true);
    setError("");
    try {
      await action();
    } catch (e) {
      setError(e instanceof Error ? e.message : "请求失败");
    } finally {
      setBusy(false);
    }
  }
  if (!isOwner)
    return <Feedback kind="info">仅企业所有者可管理外部连接。</Feedback>;
  const current = rows.find((row) => row.id === selected);
  return (
    <div className="connector-settings">
      <section className="settings-card">
        <div className="connector-heading">
          <div>
            <span className="eyebrow">外部数据</span>
            <h2>只读连接</h2>
          </div>
          <div className="heading-actions">
            <button
              className="icon-button"
              aria-label="刷新连接"
              disabled={busy}
              onClick={() => run(() => load())}
            >
              <RefreshCw size={17} />
            </button>
            <button onClick={() => setAdding(true)}>
              <Plus size={16} />
              添加连接
            </button>
          </div>
        </div>
        <p className="muted">
          把项目中的工作带入企业视图，保留来源与更新时间。外部事项仍由源系统维护。
        </p>
        <Feedback kind="info">
          当前支持 GitLab
          议题与飞书项目工作项。开发预览尚未完成真实项目验收。保存后需单独测试、启用，再发起同步。
        </Feedback>
        {error && <Feedback kind="error">{error}</Feedback>}
        {loaded && rows.length === 0 && (
          <div className="connector-empty">
            <Link2 size={24} />
            <h3>还没有外部连接</h3>
            <p>准备好项目范围和只读授权后，再添加连接。现有工作可继续使用。</p>
          </div>
        )}
        {rows.map((row) => (
          <button
            className="connector-row"
            key={row.id}
            onClick={() => setSelected(row.id)}
          >
            <span>
              <strong>{row.name}</strong>
              <small>
                {row.kind === "gitlab" ? "GitLab" : "飞书项目"} ·{" "}
                {row.project_key} · {row.key_hint}
              </small>
            </span>
            <span>
              <strong>{label(row.state)}</strong>
              <small>
                {row.source_count} 条来源 · {row.pending_count} 条待映射
              </small>
            </span>
          </button>
        ))}
        {rows.length < total && (
          <button disabled={busy} onClick={() => run(() => load(rows.length))}>
            加载更多连接
          </button>
        )}
      </section>
      {adding && (
        <Drawer
          title="添加只读连接"
          close={() => {
            setAdding(false);
            setForm((v) => ({ ...v, credentials: { ...emptyCredentials } }));
          }}
        >
          <form
            className="form-stack"
            onSubmit={(event) => {
              event.preventDefault();
              run(async () => {
                const created = unwrap(
                  await api(organizationId).POST("/api/v1/connectors", {
                    params: { header: { "x-organization-id": organizationId } },
                    body: {
                      name: form.name.trim(),
                      kind: form.kind,
                      base_url: form.base_url.trim(),
                      project_key: form.project_key.trim(),
                      item_type:
                        form.kind === "gitlab"
                          ? "issue"
                          : form.item_type.trim(),
                      owner_field:
                        form.kind === "feishu_project"
                          ? form.owner_field.trim() || null
                          : null,
                      department_id: form.department_id,
                      status_map: {},
                      credentials: form.credentials,
                      share_with_department: true,
                    },
                  }),
                );
                setForm((v) => ({
                  ...v,
                  credentials: { ...emptyCredentials },
                }));
                setAdding(false);
                await load();
                setSelected(created.id);
              });
            }}
          >
            <label>
              连接名称
              <input
                required
                maxLength={100}
                value={form.name}
                onChange={(e) => setForm({ ...form, name: e.target.value })}
              />
            </label>
            <label>
              平台
              <select
                value={form.kind}
                onChange={(e) => {
                  const kind = e.target.value as Connection["kind"];
                  setForm({
                    ...form,
                    kind,
                    base_url:
                      kind === "gitlab"
                        ? "https://gitlab.com"
                        : "https://project.feishu.cn",
                    credentials: { ...emptyCredentials },
                  });
                }}
              >
                <option value="gitlab">GitLab</option>
                <option value="feishu_project">飞书项目</option>
              </select>
            </label>
            <label>
              服务地址
              <input
                required
                type="url"
                value={form.base_url}
                onChange={(e) => setForm({ ...form, base_url: e.target.value })}
              />
            </label>
            <p className="muted">自建地址需由部署管理员加入允许列表。</p>
            <label>
              {form.kind === "gitlab" ? "项目数字 ID" : "空间 Project Key"}
              <input
                required
                value={form.project_key}
                onChange={(e) =>
                  setForm({ ...form, project_key: e.target.value })
                }
              />
            </label>
            {form.kind === "feishu_project" && (
              <>
                <label>
                  工作项类型 Key
                  <input
                    required
                    value={form.item_type}
                    onChange={(e) =>
                      setForm({ ...form, item_type: e.target.value })
                    }
                  />
                </label>
                <label>
                  负责人字段 Key
                  <input
                    required
                    value={form.owner_field}
                    onChange={(e) =>
                      setForm({ ...form, owner_field: e.target.value })
                    }
                  />
                </label>
              </>
            )}
            <label>
              归属部门
              {departments.length === 0 && (
                <small className="muted">
                  请先在“团队”页点击“组织与工作”建立部门。
                </small>
              )}
              <select
                required
                value={form.department_id}
                onChange={(e) =>
                  setForm({ ...form, department_id: e.target.value })
                }
              >
                <option value="">选择部门</option>
                {departments.map((dept) => (
                  <option value={dept.id} key={dept.id}>
                    {dept.name}
                  </option>
                ))}
              </select>
            </label>
            <CredentialsFields
              kind={form.kind}
              value={form.credentials}
              onChange={(credentials) => setForm({ ...form, credentials })}
            />
            <p className="muted">
              凭据加密保存，仅显示末四位。请使用只读、限定项目范围的授权。
            </p>
            <label className="connector-consent">
              <input
                type="checkbox"
                required
                checked={form.share}
                onChange={(e) => setForm({ ...form, share: e.target.checked })}
              />
              确认将此范围的事项按 coRoof
              权限提供给企业所有者、对应部门负责人及被分配的成员。
            </label>
            {error && <Feedback kind="error">{error}</Feedback>}
            <button
              className="primary"
              disabled={busy || !form.share || !form.department_id}
            >
              保存连接
            </button>
          </form>
        </Drawer>
      )}
      {current && (
        <Drawer title={current.name} close={() => setSelected(null)}>
          <ConnectionDetail
            key={current.id}
            connection={current}
            organizationId={organizationId}
            members={members}
            timezone={timezone}
            onChanged={(value) =>
              setRows((previous) =>
                previous.map((row) => (row.id === value.id ? value : row)),
              )
            }
            onRefresh={load}
          />
        </Drawer>
      )}
    </div>
  );
}

function ConnectionDetail({
  connection: row,
  organizationId,
  members,
  timezone,
  onChanged,
  onRefresh,
}: {
  connection: Connection;
  organizationId: string;
  members: Member[];
  timezone: string;
  onChanged: (row: Connection) => void;
  onRefresh: () => Promise<void>;
}) {
  const [runs, setRuns] = useState<Run[]>([]);
  const [runTotal, setRunTotal] = useState(0);
  const [sources, setSources] = useState<Source[]>([]);
  const [sourceTotal, setSourceTotal] = useState(0);
  const [externalMembers, setExternalMembers] = useState<Mapping[]>([]);
  const [memberTotal, setMemberTotal] = useState(0);
  const [statuses, setStatuses] = useState<Record<string, Status>>({
    ...row.status_map,
  });
  const [ownerField, setOwnerField] = useState(row.owner_field || "");
  const [memberMap, setMemberMap] = useState<Record<string, string | null>>({});
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [rotating, setRotating] = useState(false);
  const [revoking, setRevoking] = useState(false);
  const [credentials, setCredentials] = useState({ ...emptyCredentials });
  const generation = useRef(0);
  const pending = useRef<{ mode: Mode; version: number; key: string } | null>(
    null,
  );
  const header = { "x-organization-id": organizationId };
  const path = { connector_id: row.id };
  const load = useCallback(async () => {
    const ticket = ++generation.current;
    const client = api(organizationId);
    const params = {
      header: { "x-organization-id": organizationId },
      path: { connector_id: row.id },
    };
    const tasks = unwrap(
      await client.GET("/api/v1/connectors/{connector_id}/syncs", { params }),
    );
    if (ticket !== generation.current) return;
    setRuns(tasks.items);
    setRunTotal(tasks.total);
    if (row.state === "active") {
      const [s, m] = await Promise.all([
        client.GET("/api/v1/connectors/{connector_id}/sources", { params }),
        client.GET("/api/v1/connectors/{connector_id}/members", { params }),
      ]);
      if (ticket !== generation.current) return;
      const sourcePage = unwrap(s),
        memberPage = unwrap(m);
      setSources(sourcePage.items);
      setSourceTotal(sourcePage.total);
      setExternalMembers(memberPage.items);
      setMemberTotal(memberPage.total);
      setMemberMap({});
    } else {
      setSources([]);
      setExternalMembers([]);
      setSourceTotal(0);
      setMemberTotal(0);
    }
  }, [row.id, row.state, organizationId]);
  useEffect(() => {
    load().catch((e) => setError(e.message));
    return () => {
      generation.current++;
    };
  }, [load]);
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
  async function sync(mode: Mode) {
    await run(async () => {
      if (
        !pending.current ||
        pending.current.mode !== mode ||
        pending.current.version !== row.version
      )
        pending.current = {
          mode,
          version: row.version,
          key: crypto.randomUUID(),
        };
      unwrap(
        await api(organizationId).POST(
          "/api/v1/connectors/{connector_id}/syncs",
          {
            params: { header, path },
            body: {
              mode,
              expected_version: pending.current.version,
              idempotency_key: pending.current.key,
            },
          },
        ),
      );
      pending.current = null;
      await load();
      setNotice("任务已排队，可刷新查看结果。");
    });
  }
  async function state(action: Schemas["ConnectorAction"]["action"]) {
    await run(async () => {
      const updated = unwrap(
        await api(organizationId).POST(
          "/api/v1/connectors/{connector_id}/state",
          {
            params: { header, path },
            body: { action, expected_version: row.version },
          },
        ),
      );
      onChanged(updated);
      setRevoking(false);
    });
  }
  const inFlight = runs.some(running);
  const states = [
    ...new Set([
      ...Object.keys(statuses),
      ...sources
        .map((source) => source.external_state)
        .filter((s): s is string => !!s),
    ]),
  ];
  return (
    <div className="form-stack connector-detail">
      <div className="connector-heading">
        <strong>{label(row.state)}</strong>
        <button
          disabled={busy}
          onClick={() =>
            run(async () => {
              await onRefresh();
              await load();
            })
          }
        >
          <RefreshCw size={15} />
          刷新结果
        </button>
      </div>
      <dl className="facts">
        <div>
          <dt>项目范围</dt>
          <dd>
            {row.project_key} · {row.item_type}
          </dd>
        </div>
        <div>
          <dt>凭据</dt>
          <dd>{row.key_hint}</dd>
        </div>
        <div>
          <dt>最近成功同步</dt>
          <dd>{formatTime(row.synced_at, timezone)}</dd>
        </div>
        <div>
          <dt>连接测试</dt>
          <dd>{formatTime(row.tested_at, timezone)}</dd>
        </div>
      </dl>
      <p className="muted">{row.base_url}</p>
      {row.last_error && (
        <Feedback kind="error">{label(row.last_error)}</Feedback>
      )}
      {error && <Feedback kind="error">{error}</Feedback>}
      {notice && <Feedback kind="success">{notice}</Feedback>}
      <div className="quick-actions">
        {row.state !== "revoked" && (
          <button disabled={busy || inFlight} onClick={() => sync("verify")}>
            测试连接
          </button>
        )}
        {["tested", "paused"].includes(row.state) && (
          <button
            className="primary"
            disabled={busy}
            onClick={() => state("activate")}
          >
            启用连接
          </button>
        )}
        {row.state === "active" && (
          <>
            <button disabled={busy || inFlight} onClick={() => sync("full")}>
              全量同步
            </button>
            <button
              disabled={busy || inFlight || !row.synced_at}
              onClick={() => sync("incremental")}
            >
              增量同步
            </button>
            <button disabled={busy} onClick={() => state("pause")}>
              暂停连接
            </button>
          </>
        )}
        <button disabled={busy} onClick={() => setRotating(!rotating)}>
          更新凭据
        </button>
        {row.state !== "revoked" && (
          <button disabled={busy} onClick={() => setRevoking(true)}>
            撤销连接
          </button>
        )}
      </div>
      {revoking && (
        <Feedback kind="info">
          撤销后会停止任务、清除凭据并隐藏相关外部事项。
          <button disabled={busy} onClick={() => state("revoke")}>
            确认撤销
          </button>
          <button onClick={() => setRevoking(false)}>保留连接</button>
        </Feedback>
      )}
      {rotating && (
        <form
          className="form-stack settings-card"
          onSubmit={(e) => {
            e.preventDefault();
            run(async () => {
              const value = unwrap(
                await api(organizationId).POST(
                  "/api/v1/connectors/{connector_id}/credentials",
                  {
                    params: { header, path },
                    body: { expected_version: row.version, credentials },
                  },
                ),
              );
              setCredentials({ ...emptyCredentials });
              setRotating(false);
              onChanged(value);
              setNotice("凭据已更新，请重新测试并启用。");
            });
          }}
        >
          <CredentialsFields
            kind={row.kind}
            value={credentials}
            onChange={setCredentials}
          />
          <button disabled={busy}>保存新凭据</button>
        </form>
      )}
      <section>
        <h3>同步记录</h3>
        <p className="muted">
          每次最多 100 页、30
          分钟；失败可能已同步部分来源。增量不检查删除，定期全量同步可核对撤回。
        </p>
        {!runs.length && <p className="muted">尚未发起任务。</p>}
        {runs.map((task) => (
          <div className="connector-task" key={task.id}>
            <div>
              <strong>
                {modes[task.mode || "full"]} · {label(task.state)}
              </strong>
              <small>
                {formatTime(task.created_at, timezone)} · 已处理{" "}
                {task.processed} 条
                {task.phase === "reconcile" ? " · 核对缺失来源" : ""}
              </small>
              {task.error_code && <small>{label(task.error_code)}</small>}
            </div>
            {running(task) && (
              <button
                disabled={busy}
                onClick={() =>
                  run(async () => {
                    unwrap(
                      await api(organizationId).POST(
                        "/api/v1/connectors/{connector_id}/syncs/{run_id}/cancel",
                        {
                          params: {
                            header,
                            path: { ...path, run_id: task.id },
                          },
                          body: { expected_version: task.version },
                        },
                      ),
                    );
                    await load();
                  })
                }
              >
                取消任务
              </button>
            )}
          </div>
        ))}
        {runs.length < runTotal && (
          <button
            disabled={busy}
            onClick={() =>
              run(async () => {
                const page = unwrap(
                  await api(organizationId).GET(
                    "/api/v1/connectors/{connector_id}/syncs",
                    {
                      params: { header, path, query: { offset: runs.length } },
                    },
                  ),
                );
                setRuns([...runs, ...page.items]);
              })
            }
          >
            加载更多任务
          </button>
        )}
      </section>
      {row.state === "active" && (
        <>
          <section>
            <h3>来源与映射</h3>
            <p className="muted">
              未对应的状态或负责人会保留为待映射。截止日期与支持需求不在此次同步范围内。
            </p>
            {!sources.length && (
              <p className="muted">暂无已读取的来源，请先发起全量同步。</p>
            )}
            {sources.map((source) => (
              <div className="connector-source" key={source.id}>
                <strong>{source.title}</strong>
                <small>
                  #{source.external_id} · {source.external_state || "状态未知"}{" "}
                  · {label(source.state)}
                  {source.mapping_issue
                    ? ` · ${label(source.mapping_issue)}`
                    : ""}
                </small>
                <small>来源更新 {formatTime(source.source_at, timezone)}</small>
              </div>
            ))}
            {sources.length < sourceTotal && (
              <button
                disabled={busy}
                onClick={() =>
                  run(async () => {
                    const page = unwrap(
                      await api(organizationId).GET(
                        "/api/v1/connectors/{connector_id}/sources",
                        {
                          params: {
                            header,
                            path,
                            query: { offset: sources.length },
                          },
                        },
                      ),
                    );
                    setSources([...sources, ...page.items]);
                  })
                }
              >
                加载更多来源
              </button>
            )}
          </section>
          {(states.length > 0 || externalMembers.length > 0) && (
            <form
              className="form-stack"
              onSubmit={(e) => {
                e.preventDefault();
                run(async () => {
                  onChanged(
                    unwrap(
                      await api(organizationId).PUT(
                        "/api/v1/connectors/{connector_id}/mapping",
                        {
                          params: { header, path },
                          body: {
                            expected_version: row.version,
                            status_map: statuses,
                            ...(row.kind === "feishu_project"
                              ? { owner_field: ownerField || null }
                              : {}),
                            members: memberMap,
                          },
                        },
                      ),
                    ),
                  );
                  await load();
                  setNotice("映射已保存。请全量同步，重新生成可见事项。");
                });
              }}
            >
              <h3>人工对应</h3>
              {states.map((state) => (
                <label key={state}>
                  来源状态：{state}
                  <select
                    value={statuses[state] || ""}
                    onChange={(e) =>
                      setStatuses((previous) => {
                        const next = { ...previous };
                        if (e.target.value)
                          next[state] = e.target.value as Status;
                        else delete next[state];
                        return next;
                      })
                    }
                  >
                    <option value="">待映射</option>
                    {Object.entries(statusLabels).map(([key, title]) => (
                      <option key={key} value={key}>
                        {title}
                      </option>
                    ))}
                  </select>
                </label>
              ))}
              {externalMembers.map((member) => (
                <label key={member.external_id}>
                  外部成员：{member.external_id}
                  <select
                    value={
                      (Object.hasOwn(memberMap, member.external_id)
                        ? memberMap[member.external_id]
                        : member.membership_id) || ""
                    }
                    onChange={(e) =>
                      setMemberMap({
                        ...memberMap,
                        [member.external_id]: e.target.value || null,
                      })
                    }
                  >
                    <option value="">待映射</option>
                    {members
                      .filter(
                        (m) =>
                          m.department_id === row.department_id &&
                          m.status === "active",
                      )
                      .map((m) => (
                        <option value={m.id} key={m.id}>
                          {m.name}
                        </option>
                      ))}
                  </select>
                </label>
              ))}
              {externalMembers.length < memberTotal && (
                <button
                  type="button"
                  disabled={busy}
                  onClick={() =>
                    run(async () => {
                      const page = unwrap(
                        await api(organizationId).GET(
                          "/api/v1/connectors/{connector_id}/members",
                          {
                            params: {
                              header,
                              path,
                              query: { offset: externalMembers.length },
                            },
                          },
                        ),
                      );
                      setExternalMembers([...externalMembers, ...page.items]);
                    })
                  }
                >
                  加载更多成员
                </button>
              )}
              <button disabled={busy || inFlight}>保存映射</button>
            </form>
          )}
        </>
      )}
    </div>
  );
}
