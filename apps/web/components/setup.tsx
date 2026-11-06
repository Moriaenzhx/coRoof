"use client";
import { useEffect, useRef, useState } from "react";
import { Copy, Plus, RefreshCw } from "lucide-react";
import { Feedback } from "./status";
import {
  api,
  unwrap,
  formatTime,
  type Department,
  type Initiative,
  type Member,
  type MembershipContext,
  type Schemas,
} from "../lib/api";

export function Setup({
  context,
  departments,
  initiatives,
  members,
  onUpdated,
  authMode = "mock",
}: {
  context: MembershipContext;
  departments: Department[];
  initiatives: Initiative[];
  members: Member[];
  onUpdated: () => Promise<void>;
  authMode?: "mock" | "oidc";
}) {
  const owner = context.membership.roles.includes("owner");
  const [tab, setTab] = useState(owner ? "department" : "work");
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [busy, setBusy] = useState(false);
  const [departmentId, setDepartmentId] = useState(
    context.membership.department_id || departments[0]?.id || "",
  );
  const [delivery, setDelivery] = useState<Schemas["InviteDelivery"] | null>(
    null,
  );
  const [invites, setInvites] = useState<Schemas["InviteOut"][]>([]);
  const [retrying, setRetrying] = useState<string | null>(null);
  const inviteRequest = useRef<{ fingerprint: string; key: string } | null>(
    null,
  );
  const retries = useRef(new Map<string, string>());
  const header = { "x-organization-id": context.organization.id };
  const scopedDepartments = owner
    ? departments
    : departments.filter((d) => d.id === context.membership.department_id);
  useEffect(() => {
    if (!departmentId && departments.length) setDepartmentId(departments[0].id);
  }, [departmentId, departments]);
  async function loadInvites() {
    const all: Schemas["InviteOut"][] = [];
    let total = 1;
    while (all.length < total) {
      const result = unwrap(
        await api().GET("/api/v1/members/invitations", {
          params: { header, query: { offset: all.length, limit: 100 } },
        }),
      );
      all.push(...result.items);
      total = result.total;
      if (!result.items.length) break;
    }
    setInvites(all);
  }
  useEffect(() => {
    if (tab === "invite") void loadInvites().catch((e) => setError(e.message));
  }, [tab]);
  async function submit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = event.currentTarget;
    const values = new FormData(form);
    const value = (name: string) => String(values.get(name) || "");
    setBusy(true);
    setError("");
    setNotice("");
    try {
      if (tab === "department")
        unwrap(
          await api().POST("/api/v1/departments", {
            params: { header },
            body: { name: value("name") },
          }),
        );
      if (tab === "invite") {
        const body: Schemas["InviteInput"] = {
          email: value("email"),
          department_id: departmentId,
          roles:
            value("role") === "manager" ? ["manager", "member"] : ["member"],
        };
        const fingerprint = JSON.stringify(body);
        if (inviteRequest.current?.fingerprint !== fingerprint)
          inviteRequest.current = { fingerprint, key: crypto.randomUUID() };
        setDelivery(
          unwrap(
            await api().POST("/api/v1/members/invitations", {
              params: { header },
              body: { ...body, idempotency_key: inviteRequest.current.key },
            }),
          ),
        );
        await loadInvites();
      }
      if (tab === "initiative")
        unwrap(
          await api().POST("/api/v1/initiatives", {
            params: { header },
            body: {
              title: value("title"),
              goal: value("goal") || null,
              department_id: owner && !value("scoped") ? null : departmentId,
            },
          }),
        );
      if (tab === "work")
        unwrap(
          await api().POST("/api/v1/work-items", {
            params: { header },
            body: {
              title: value("title"),
              description: value("description") || null,
              department_id: departmentId,
              initiative_id: value("initiative") || null,
              owner_id: value("owner") || null,
              due_at: value("due")
                ? new Date(value("due")).toISOString()
                : null,
            },
          }),
        );
      await onUpdated();
      form.reset();
      inviteRequest.current = null;
      setNotice(
        tab === "invite" ? "邀请已保存，请查看下方投递信息。" : "已保存。",
      );
    } catch (e) {
      setError(e instanceof Error ? e.message : "保存失败");
    } finally {
      setBusy(false);
    }
  }
  async function revoke(id: string) {
    setBusy(true);
    setError("");
    try {
      unwrap(
        await api().POST("/api/v1/members/invitations/{invitation_id}/revoke", {
          params: { header, path: { invitation_id: id } },
        }),
      );
      if (delivery?.id === id) setDelivery(null);
      await loadInvites();
    } catch (e) {
      setError(e instanceof Error ? e.message : "撤销失败");
    } finally {
      setBusy(false);
    }
  }
  async function retry(invite: Schemas["InviteOut"]) {
    if (!invite.delivery_status) return;
    setBusy(true);
    setError("");
    const receipt = `${invite.id}:${invite.delivery_status.version}`;
    if (!retries.current.has(receipt))
      retries.current.set(receipt, crypto.randomUUID());
    try {
      unwrap(
        await api().POST("/api/v1/members/invitations/{invitation_id}/retry", {
          params: { header, path: { invitation_id: invite.id } },
          body: {
            expected_version: invite.delivery_status.version,
            confirm: true,
            idempotency_key: retries.current.get(receipt)!,
          },
        }),
      );
      setRetrying(null);
      await loadInvites();
      setNotice("已重新加入投递队列。");
    } catch (e) {
      setError(e instanceof Error ? e.message : "重试失败");
    } finally {
      setBusy(false);
    }
  }
  const link =
    delivery?.delivery?.mode === "mock" && typeof window !== "undefined"
      ? `${window.location.origin}/#invite=${encodeURIComponent(delivery.delivery.token)}`
      : "";
  return (
    <>
      <div className="tabs" role="tablist" aria-label="组织配置">
        {(owner
          ? [
              ["department", "部门"],
              ["invite", "邀请成员"],
              ["initiative", "项目"],
              ["work", "事项"],
            ]
          : [
              ["invite", "邀请成员"],
              ["initiative", "项目"],
              ["work", "事项"],
            ]
        ).map(([id, label]) => (
          <button
            role="tab"
            aria-selected={tab === id}
            className={tab === id ? "selected" : ""}
            onClick={() => {
              setTab(id);
              setError("");
              setNotice("");
            }}
            key={id}
          >
            {label}
          </button>
        ))}
      </div>
      {error && <Feedback kind="error">{error}</Feedback>}
      {notice && <Feedback kind="success">{notice}</Feedback>}
      <form key={tab} onSubmit={submit} className="setup-form">
        <h3>
          {
            {
              department: "建立部门",
              invite: "邀请一位成员",
              initiative: "建立重点项目",
              work: "记录一项工作",
            }[tab]
          }
        </h3>
        {tab === "department" ? (
          <label>
            部门名称
            <input
              name="name"
              required
              maxLength={100}
              placeholder="例如：交付"
            />
          </label>
        ) : (
          <>
            {tab === "invite" ? (
              <>
                <label>
                  受邀邮箱
                  <input
                    name="email"
                    type="email"
                    required
                    placeholder="colleague@example.com"
                  />
                </label>
                <label>
                  角色
                  <select name="role">
                    <option value="member">员工</option>
                    {owner && (
                      <option value="manager">部门负责人（兼任员工）</option>
                    )}
                  </select>
                </label>
              </>
            ) : (
              <label>
                {tab === "work" ? "事项名称" : "项目名称"}
                <input
                  name="title"
                  required
                  maxLength={200}
                  placeholder={
                    tab === "work"
                      ? "例如：确认客户交付资料"
                      : "例如：客户交付项目"
                  }
                />
              </label>
            )}
            <label>
              所属部门
              <select
                value={departmentId}
                onChange={(e) => setDepartmentId(e.target.value)}
                required={tab !== "initiative" || !owner}
              >
                <option value="" disabled>
                  先建立部门
                </option>
                {scopedDepartments.map((d) => (
                  <option key={d.id} value={d.id}>
                    {d.name}
                  </option>
                ))}
              </select>
            </label>
            {tab === "initiative" && (
              <>
                {owner && (
                  <label className="checkbox">
                    <input name="scoped" type="checkbox" />
                    仅关联所选部门（默认公司级项目）
                  </label>
                )}
                <label>
                  项目目标
                  <textarea name="goal" rows={3} maxLength={4000} />
                </label>
              </>
            )}
            {tab === "work" && (
              <>
                <label>
                  所属项目
                  <select name="initiative">
                    <option value="">暂不关联</option>
                    {initiatives
                      .filter(
                        (i) =>
                          !i.department_id || i.department_id === departmentId,
                      )
                      .map((i) => (
                        <option key={i.id} value={i.id}>
                          {i.title}
                        </option>
                      ))}
                  </select>
                </label>
                <label>
                  负责人
                  <select name="owner" key={departmentId}>
                    <option value="">暂不分配</option>
                    {members
                      .filter((m) => m.department_id === departmentId)
                      .map((m) => (
                        <option key={m.id} value={m.id}>
                          {m.name}
                        </option>
                      ))}
                  </select>
                </label>
                <label>
                  截止时间（当前设备时区）
                  <input name="due" type="datetime-local" />
                </label>
                <label>
                  说明
                  <textarea name="description" rows={3} maxLength={4000} />
                </label>
              </>
            )}
          </>
        )}
        <button
          className="primary"
          disabled={
            busy ||
            (tab !== "department" && tab !== "initiative" && !departmentId)
          }
        >
          <Plus size={16} />
          {busy
            ? "正在保存…"
            : tab === "invite"
              ? authMode === "oidc"
                ? "发送邀请"
                : "生成开发邀请"
              : "保存"}
        </button>
      </form>
      {tab === "invite" && (
        <>
          <p className="fine-print">
            {authMode === "oidc" || delivery?.delivery?.mode === "smtp"
              ? "邀请 24 小时有效，仅受邀邮箱验证身份后可加入。邮件服务接受不等于收件箱送达。"
              : "开发模拟邮件 · 未发送真实邮件。邀请 24 小时有效，只允许受邀邮箱加入。"}
          </p>
          {link && (
            <div className="invite-delivery">
              <label>
                邀请链接
                <input aria-label="邀请链接" readOnly value={link} />
              </label>
              <button
                onClick={() =>
                  navigator.clipboard
                    .writeText(link)
                    .then(() => setNotice("邀请链接已复制"))
                    .catch(() => setError("请手动复制上方链接"))
                }
              >
                <Copy size={15} />
                复制链接
              </button>
            </div>
          )}
          <h3>邀请记录</h3>
          <button
            disabled={busy}
            onClick={() => loadInvites().catch((e) => setError(e.message))}
          >
            <RefreshCw size={15} /> 刷新投递状态
          </button>
          {invites.map((invite) => (
            <div className="invite-row" key={invite.id}>
              <div>
                <strong>{invite.email}</strong>
                <small>
                  {invite.revoked
                    ? "已撤销"
                    : invite.accepted_at
                      ? "已加入"
                      : `有效期至 ${formatTime(invite.expires_at, context.organization.timezone)}`}
                </small>
                {invite.delivery_status && (
                  <small>
                    {deliveryLabels[invite.delivery_status.state]} · 已尝试{" "}
                    {invite.delivery_status.attempts} 次
                  </small>
                )}
                {invite.delivery_status &&
                  ["failed", "unknown"].includes(
                    invite.delivery_status.state,
                  ) &&
                  !invite.revoked &&
                  !invite.accepted_at &&
                  (retrying === invite.id ? (
                    <div>
                      <p className="fine-print">
                        结果未知时可能已经发送。请先核对收件箱，确认需要再次投递。
                      </p>
                      <button disabled={busy} onClick={() => retry(invite)}>
                        确认重试投递
                      </button>
                      <button disabled={busy} onClick={() => setRetrying(null)}>
                        取消
                      </button>
                    </div>
                  ) : (
                    <button
                      disabled={busy}
                      onClick={() => setRetrying(invite.id)}
                    >
                      核对后重试
                    </button>
                  ))}
              </div>
              {!invite.revoked && !invite.accepted_at && (
                <button disabled={busy} onClick={() => revoke(invite.id)}>
                  撤销
                </button>
              )}
            </div>
          ))}
          {!invites.length && <p className="muted">尚无邀请。</p>}
        </>
      )}
    </>
  );
}

const deliveryLabels: Record<Schemas["DeliveryStatus"]["state"], string> = {
  queued: "等待投递",
  sending: "投递中",
  retry_wait: "等待重试",
  accepted: "邮件服务已接受",
  unknown: "投递结果未知",
  failed: "投递失败",
  cancelled: "投递已取消",
};
