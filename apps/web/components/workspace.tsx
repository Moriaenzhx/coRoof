"use client";
import { useCallback, useEffect, useRef, useState } from "react";
import {
  ArrowRight,
  ArrowUpRight,
  Building2,
  CircleDot,
  Compass,
  Home,
  Layers3,
  LayoutGrid,
  LogOut,
  Plus,
  RefreshCw,
  Users,
  BriefcaseBusiness,
} from "lucide-react";
import {
  api,
  unwrap,
  formatTime,
  statusLabels,
  type Dashboard,
  type Department,
  type Initiative,
  type Me,
  type Member,
  type MembershipContext,
  type Schemas,
  type Work,
} from "../lib/api";
import { Drawer } from "./drawer";
import { Panorama } from "./panorama";
import { Setup } from "./setup";
import { WorkDetail } from "./work-detail";

type PageName = "overview" | "people" | "business" | "decisions" | "mine";
type Detail =
  | { kind: "work" | "department" | "member"; id: string }
  | { kind: "setup" | "support" | "organization" };
type Snapshot = {
  dashboard: Dashboard;
  departments: Department[];
  members: Member[];
  initiatives: Initiative[];
  works: Work[];
};
const navItems = [
  { id: "overview", label: "全局", Icon: LayoutGrid },
  { id: "people", label: "部门与人员", Icon: Users },
  { id: "business", label: "业务进展", Icon: Layers3 },
  { id: "decisions", label: "重要决策", Icon: Compass },
] as const;

async function collect<T>(
  fetchPage: (offset: number) => Promise<{ items: T[]; total: number }>,
): Promise<T[]> {
  const values: T[] = [];
  let total = 1;
  while (values.length < total) {
    const result = await fetchPage(values.length);
    values.push(...result.items);
    total = result.total;
    if (!result.items.length) break;
  }
  return values;
}

export function Workspace() {
  const [me, setMe] = useState<Me | null>(null);
  const [loading, setLoading] = useState(true);
  const [context, setContext] = useState<MembershipContext | null>(null);
  const [snapshot, setSnapshot] = useState<Snapshot | null>(null);
  const [page, setPage] = useState<PageName>("overview");
  const [detail, setDetail] = useState<Detail | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [pendingInvite, setPendingInvite] = useState("");
  const [login, setLogin] = useState<Schemas["MockDelivery"] | null>(null);
  const generation = useRef(0);
  const manage =
    !!context &&
    context.membership.roles.some((r) => r === "owner" || r === "manager");
  const organizationId = context?.organization.id;
  const timezone = context?.organization.timezone || "Asia/Shanghai";

  const refreshMe = useCallback(async (prefer?: string) => {
    const result = unwrap(await api().GET("/api/v1/auth/me"));
    setMe(result);
    const ctx =
      result.memberships.find((m) => m.organization.id === prefer) ||
      result.memberships[0] ||
      null;
    setContext(ctx);
    if (
      ctx &&
      !ctx.membership.roles.some((r) => r === "owner" || r === "manager")
    )
      setPage("mine");
    return result;
  }, []);
  const refresh = useCallback(async () => {
    if (!organizationId) return;
    const current = ++generation.current;
    const header = { "x-organization-id": organizationId };
    const [dashboard, departments, members, initiatives, works] =
      await Promise.all([
        api().GET("/api/v1/dashboard", { params: { header } }).then(unwrap),
        collect((offset) =>
          api()
            .GET("/api/v1/departments", {
              params: { header, query: { offset, limit: 100 } },
            })
            .then(unwrap),
        ),
        collect((offset) =>
          api()
            .GET("/api/v1/members", {
              params: { header, query: { offset, limit: 100 } },
            })
            .then(unwrap),
        ),
        collect((offset) =>
          api()
            .GET("/api/v1/initiatives", {
              params: { header, query: { offset, limit: 100 } },
            })
            .then(unwrap),
        ),
        collect((offset) =>
          api()
            .GET("/api/v1/work-items", {
              params: { header, query: { offset, limit: 100 } },
            })
            .then(unwrap),
        ),
      ]);
    if (current === generation.current)
      setSnapshot({ dashboard, departments, members, initiatives, works });
  }, [organizationId]);
  useEffect(() => {
    setPendingInvite(
      new URLSearchParams(window.location.hash.slice(1)).get("invite") || "",
    );
    api()
      .GET("/api/v1/auth/me")
      .then((result) => {
        if (result.response.status === 401) return;
        const user = unwrap(result);
        setMe(user);
        setContext(user.memberships[0] || null);
        if (
          user.memberships[0] &&
          !user.memberships[0].membership.roles.some(
            (r) => r === "owner" || r === "manager",
          )
        )
          setPage("mine");
      })
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false));
  }, []);
  useEffect(() => {
    setSnapshot(null);
    setError("");
    void refresh().catch((e) => setError(e.message));
    return () => {
      generation.current++;
    };
  }, [refresh]);
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
  async function requestLogin(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const values = new FormData(event.currentTarget);
    await run(async () => {
      setLogin(
        unwrap(
          await api().POST("/api/v1/auth/request-link", {
            body: {
              email: String(values.get("email")),
              name: String(values.get("name")),
            },
          }),
        ),
      );
    });
  }
  async function verify() {
    if (!login) return;
    await run(async () => {
      unwrap(
        await api().POST("/api/v1/auth/verify", {
          body: { token: login.token },
        }),
      );
      setLogin(null);
      await refreshMe();
    });
  }
  async function logout() {
    await run(async () => {
      const result = await api().POST("/api/v1/auth/logout");
      if (result.error) throw new Error("退出失败");
      generation.current++;
      setMe(null);
      setContext(null);
      setSnapshot(null);
      setDetail(null);
    });
  }
  async function createOrganization(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const values = new FormData(event.currentTarget);
    await run(async () => {
      const org = unwrap(
        await api().POST("/api/v1/organizations", {
          body: { name: String(values.get("name")), timezone: "Asia/Shanghai" },
        }),
      );
      await refreshMe(org.id);
      setPage("overview");
      setDetail(null);
    });
  }
  async function acceptInvite() {
    await run(async () => {
      const member = unwrap(
        await api().POST("/api/v1/members/invitations/accept", {
          body: { token: pendingInvite },
        }),
      );
      setPendingInvite("");
      window.history.replaceState(null, "", window.location.pathname);
      await refreshMe(member.organization_id);
    });
  }
  const organizationForm = (
    <form onSubmit={createOrganization}>
      <label>
        企业名称
        <input
          name="name"
          placeholder="输入企业名称"
          required
          maxLength={100}
        />
      </label>
      <p className="muted">
        初始时区：Asia/Shanghai。创建后可建立部门和分配事项。
      </p>
      <button className="primary" disabled={busy}>
        建立企业 <ArrowRight size={16} />
      </button>
    </form>
  );
  if (loading)
    return (
      <main className="auth-shell">
        <div className="auth-card">
          <Brand />
          <p>正在连接工作空间…</p>
        </div>
      </main>
    );
  if (!me)
    return (
      <main className="auth-shell">
        <div className="auth-card">
          <Brand />
          <span className="eyebrow">YOUR COMPANY AT A GLANCE</span>
          <h1>
            让工作，
            <br />
            在同一屋檐下清晰。
          </h1>
          <p className="muted">用真实的进展，连接企业与每一个人。</p>
          {error && (
            <p role="alert" className="error">
              {error}
            </p>
          )}
          {!login ? (
            <form onSubmit={requestLogin}>
              <label>
                你的姓名
                <input
                  name="name"
                  autoComplete="name"
                  required
                  maxLength={100}
                />
              </label>
              <label>
                邮箱
                <input
                  name="email"
                  type="email"
                  autoComplete="email"
                  required
                />
              </label>
              <button className="primary" disabled={busy}>
                {busy ? "正在准备…" : "获取开发验证链接"}
                <ArrowRight size={16} />
              </button>
            </form>
          ) : (
            <div className="mock-delivery">
              <h3>开发模拟邮箱</h3>
              <p>{login.notice}</p>
              <button className="primary" disabled={busy} onClick={verify}>
                确认开发身份并进入
              </button>
              <button
                className="plain"
                disabled={busy}
                onClick={() => setLogin(null)}
              >
                使用其他邮箱
              </button>
            </div>
          )}
          <p className="fine-print">
            本地开发版 ·
            模拟身份验证，未发送邮件。正式部署前必须接入真实身份与邮件服务。
          </p>
        </div>
      </main>
    );
  if (!context || pendingInvite)
    return (
      <main className="auth-shell">
        <div className="auth-card">
          <Brand />
          <h1>{pendingInvite ? "加入共同的工作空间。" : "从你的企业开始。"}</h1>
          <p className="muted">当前身份：{me.email}</p>
          {error && (
            <p role="alert" className="error">
              {error}
            </p>
          )}
          {pendingInvite ? (
            <>
              <p>邀请与受邀邮箱绑定。确认后，你将只能看到获授权的工作。</p>
              <button
                className="primary"
                disabled={busy}
                onClick={acceptInvite}
              >
                接受邀请
              </button>
              <button
                className="plain"
                onClick={() => {
                  setPendingInvite("");
                  window.history.replaceState(
                    null,
                    "",
                    window.location.pathname,
                  );
                }}
              >
                暂不加入
              </button>
            </>
          ) : (
            organizationForm
          )}
          <button className="plain" onClick={logout}>
            退出当前身份
          </button>
        </div>
      </main>
    );

  const currentWork =
    detail?.kind === "work"
      ? snapshot?.works.find((w) => w.id === detail.id)
      : undefined;
  const currentDepartment =
    detail?.kind === "department"
      ? snapshot?.departments.find((d) => d.id === detail.id)
      : undefined;
  const currentMember =
    detail?.kind === "member"
      ? snapshot?.members.find((m) => m.id === detail.id)
      : undefined;
  const drawerTitle =
    detail?.kind === "setup"
      ? "组织与工作设置"
      : detail?.kind === "organization"
        ? "建立新的企业"
        : detail?.kind === "support"
          ? "需要支持的工作"
          : currentWork?.title ||
            currentDepartment?.name ||
            currentMember?.name ||
            "工作详情";
  const visibleWorks =
    snapshot?.works.filter(
      (w) => page !== "mine" || w.owner_id === context.membership.id,
    ) || [];
  const scopeWorks =
    detail?.kind === "department"
      ? snapshot?.works.filter((w) => w.department_id === detail.id)
      : detail?.kind === "member"
        ? snapshot?.works.filter((w) => w.owner_id === detail.id)
        : snapshot?.works.filter((w) => w.needs_support);
  const title =
    page === "mine"
      ? "我的工作"
      : page === "overview"
        ? context.membership.roles.includes("owner")
          ? "企业全局"
          : "部门全局"
        : navItems.find((n) => n.id === page)?.label;
  const workList = (works: Work[]) =>
    works.length ? (
      <div className="work-list">
        {works.map((work) => (
          <button
            key={work.id}
            className="work-row"
            onClick={() => setDetail({ kind: "work", id: work.id })}
          >
            <span
              className={`work-indicator ${work.needs_support ? "amber" : ""}`}
            >
              <CircleDot size={18} />
            </span>
            <span className="work-row-body">
              <strong>{work.title}</strong>
              <small>
                {snapshot?.members.find((m) => m.id === work.owner_id)?.name ||
                  "未分配"}{" "}
                · {statusLabels[work.lifecycle_status]}
                {work.needs_support ? " · 需要支持" : ""}
              </small>
            </span>
            <ArrowUpRight size={16} />
          </button>
        ))}
      </div>
    ) : (
      <Empty text="这里还没有工作记录。" />
    );
  return (
    <div className="app-shell">
      <aside className="sidebar">
        <Brand />
        <span className="sidebar-label">WORKSPACE</span>
        <nav aria-label="主导航">
          {manage &&
            navItems.map(({ id, label, Icon }) => (
              <button
                key={id}
                className={page === id ? "active" : ""}
                onClick={() => {
                  setPage(id);
                  setDetail(null);
                }}
              >
                <Icon size={18} />
                {label}
              </button>
            ))}
          <button
            className={page === "mine" ? "active" : ""}
            onClick={() => {
              setPage("mine");
              setDetail(null);
            }}
          >
            <BriefcaseBusiness size={18} />
            我的工作
          </button>
        </nav>
        <div className="sidebar-company">
          <span className="sidebar-label">COMPANY</span>
          <strong>{context.organization.name}</strong>
          <span>从已知事实出发</span>
        </div>
        <div className="sidebar-user">
          <span className="avatar">{me.name.slice(0, 1)}</span>
          <div>
            <strong>{me.name}</strong>
            <small>
              {context.membership.roles.includes("owner")
                ? "企业所有者"
                : manage
                  ? "部门负责人"
                  : "成员"}{" "}
              · 开发身份
            </small>
          </div>
          <button
            className="icon-button"
            onClick={logout}
            aria-label="退出登录"
          >
            <LogOut size={16} />
          </button>
        </div>
      </aside>
      <div className="main-column">
        <header className="topbar">
          <div className="company-switch">
            <select
              aria-label="切换企业"
              value={context.organization.id}
              onChange={(e) => {
                if (e.target.value === "new") {
                  setDetail({ kind: "organization" });
                  return;
                }
                generation.current++;
                setSnapshot(null);
                setDetail(null);
                const selected = me.memberships.find(
                  (m) => m.organization.id === e.target.value,
                )!;
                setContext(selected);
                setPage(
                  selected.membership.roles.some(
                    (r) => r === "owner" || r === "manager",
                  )
                    ? "overview"
                    : "mine",
                );
              }}
            >
              {me.memberships.map((c) => (
                <option key={c.organization.id} value={c.organization.id}>
                  {c.organization.name}
                </option>
              ))}
              <option value="new">＋ 建立新企业</option>
            </select>
            <span className="topbar-divider" />
            <strong>企业运行全景</strong>
          </div>
          <span className="environment-tag">
            <span />
            本地开发 · 规则降级
          </span>
        </header>
        <main className="workspace">
          <div className="page-heading">
            <div>
              <span className="eyebrow">
                {page === "mine"
                  ? "A LITTLE UPDATE, A CLEARER PICTURE"
                  : "YOUR COMPANY AT A GLANCE"}
              </span>
              <h1>{title}</h1>
              <p>
                {page === "mine"
                  ? "有进展、遇到阻塞，随时说一声。"
                  : page === "decisions"
                    ? "从可追溯的事实出发，再做重要判断。"
                    : "从整体态势出发，逐层了解企业正在发生什么。"}
              </p>
            </div>
            <div className="heading-actions">
              <button
                className="icon-button"
                aria-label="刷新数据"
                disabled={busy}
                onClick={() => run(refresh)}
              >
                <RefreshCw size={17} />
              </button>
              {manage && (
                <button onClick={() => setDetail({ kind: "setup" })}>
                  <Plus size={16} />
                  组织与工作
                </button>
              )}
            </div>
          </div>
          {error && (
            <p className="error" role="alert">
              {error}
              <button className="plain" onClick={() => run(refresh)}>
                重试
              </button>
            </p>
          )}
          {!snapshot ? (
            <p className="muted" role="status">
              正在读取已授权的工作记录…
            </p>
          ) : (
            <>
              {page === "overview" && (
                <>
                  <Panorama
                    data={snapshot.dashboard}
                    onDepartment={(id) => setDetail({ kind: "department", id })}
                    onSupport={() => setDetail({ kind: "support" })}
                  />
                  <div className="section-line lower-heading">
                    <div>
                      <h2>组织运行状态</h2>
                      <p className="muted">事实、进展，以及仍然未知的部分。</p>
                    </div>
                    <button className="plain" onClick={() => setPage("people")}>
                      查看部门与人员 <ArrowRight size={16} />
                    </button>
                  </div>
                  <div className="overview-lower">
                    <section className="panel">
                      <div className="section-line">
                        <h3>部门概况</h3>
                        <Building2 size={18} />
                      </div>
                      {snapshot.dashboard.departments.length ? (
                        snapshot.dashboard.departments.map((d) => (
                          <button
                            className="department-row"
                            key={d.department.id}
                            onClick={() =>
                              setDetail({
                                kind: "department",
                                id: d.department.id,
                              })
                            }
                          >
                            <strong>{d.department.name}</strong>
                            <span>{d.member_count} 人</span>
                            <span
                              className={
                                d.support_count ? "amber-text" : "muted"
                              }
                            >
                              {d.coverage === "unknown"
                                ? "未知 / 无数据"
                                : d.support_count
                                  ? `${d.support_count} 项需要支持`
                                  : `${d.work_count} 项已记录`}
                            </span>
                            <ArrowUpRight size={14} />
                          </button>
                        ))
                      ) : (
                        <Empty text="还没有部门，先建立你的组织。" />
                      )}
                    </section>
                    <section className="panel">
                      <div className="section-line">
                        <h3>最近的工作记录</h3>
                        <span className="muted">
                          {snapshot.works.length} 项
                        </span>
                      </div>
                      {workList(snapshot.works.slice(0, 4))}
                    </section>
                  </div>
                </>
              )}
              {page === "people" && (
                <div className="people-grid">
                  {snapshot.departments.map((department) => (
                    <section className="panel" key={department.id}>
                      <button
                        className="section-line full-width plain"
                        onClick={() =>
                          setDetail({ kind: "department", id: department.id })
                        }
                      >
                        <h2>{department.name}</h2>
                        <ArrowUpRight size={18} />
                      </button>
                      {snapshot.members
                        .filter((m) => m.department_id === department.id)
                        .map((member) => (
                          <button
                            className="member-row"
                            key={member.id}
                            onClick={() =>
                              setDetail({ kind: "member", id: member.id })
                            }
                          >
                            <span className="avatar">
                              {member.name.slice(0, 1)}
                            </span>
                            <span>
                              <strong>{member.name}</strong>
                              <small>
                                {member.roles.includes("manager")
                                  ? "部门负责人"
                                  : "成员"}
                              </small>
                            </span>
                            <ArrowUpRight size={15} />
                          </button>
                        ))}
                      {!snapshot.members.some(
                        (m) => m.department_id === department.id,
                      ) && <Empty text="尚无成员" />}
                    </section>
                  ))}
                  {snapshot.members.some((m) => !m.department_id) && (
                    <section className="panel">
                      <h2>企业管理</h2>
                      {snapshot.members
                        .filter((m) => !m.department_id)
                        .map((member) => (
                          <button
                            className="member-row"
                            key={member.id}
                            onClick={() =>
                              setDetail({ kind: "member", id: member.id })
                            }
                          >
                            <span className="avatar">
                              {member.name.slice(0, 1)}
                            </span>
                            <strong>{member.name}</strong>
                            <small>未归属部门</small>
                          </button>
                        ))}
                    </section>
                  )}
                  {!snapshot.departments.length && (
                    <Empty text="先建立部门，再邀请同事加入。" />
                  )}
                </div>
              )}
              {page === "business" && (
                <div className="business-list">
                  {snapshot.initiatives.map((initiative) => (
                    <section className="panel" key={initiative.id}>
                      <span className="eyebrow">重点项目</span>
                      <h2>{initiative.title}</h2>
                      {initiative.goal && (
                        <p className="muted">{initiative.goal}</p>
                      )}
                      {workList(
                        snapshot.works.filter(
                          (w) => w.initiative_id === initiative.id,
                        ),
                      )}
                    </section>
                  ))}
                  {snapshot.works.some((w) => !w.initiative_id) && (
                    <section className="panel">
                      <h2>独立事项</h2>
                      {workList(snapshot.works.filter((w) => !w.initiative_id))}
                    </section>
                  )}
                  {!snapshot.initiatives.length && !snapshot.works.length && (
                    <Empty text="暂无业务记录。建立第一个项目和工作事项。" />
                  )}
                </div>
              )}
              {page === "decisions" && (
                <section className="panel decisions-empty">
                  <Compass size={30} />
                  <h2>重要决策，等待事实积累。</h2>
                  <p>
                    决策与 AI
                    分析将在下一阶段开放。当前可以查看成员明确提出的支持需求与原始记录。
                  </p>
                  {snapshot.dashboard.support_work > 0 && (
                    <button onClick={() => setDetail({ kind: "support" })}>
                      查看 {snapshot.dashboard.support_work} 项支持需求{" "}
                      <ArrowRight size={16} />
                    </button>
                  )}
                  <span className="tag">尚未启用</span>
                </section>
              )}
              {page === "mine" && (
                <div className="my-work-grid">
                  {visibleWorks
                    .filter(
                      (w) =>
                        w.lifecycle_status === "planned" ||
                        w.lifecycle_status === "in_progress",
                    )
                    .map((work) => (
                      <article className="panel my-work-card" key={work.id}>
                        <div className="section-line">
                          <span className="tag">
                            {statusLabels[work.lifecycle_status]}
                          </span>
                          {work.needs_support && (
                            <span className="tag amber">需要支持</span>
                          )}
                        </div>
                        <h2>{work.title}</h2>
                        <p className="muted">
                          {work.description || "有变化时更新，让协作更清晰。"}
                        </p>
                        <small>
                          最近更新 {formatTime(work.updated_at, timezone)}
                        </small>
                        <button
                          className="primary"
                          onClick={() =>
                            setDetail({ kind: "work", id: work.id })
                          }
                        >
                          查看与更新 <ArrowRight size={16} />
                        </button>
                      </article>
                    ))}
                  {!visibleWorks.some(
                    (w) =>
                      w.lifecycle_status === "planned" ||
                      w.lifecycle_status === "in_progress",
                  ) && <Empty text="当前没有分配给你的进行中事项。" />}
                  {visibleWorks.some(
                    (w) =>
                      w.lifecycle_status === "done" ||
                      w.lifecycle_status === "cancelled",
                  ) && (
                    <section className="panel">
                      <h2>已结束</h2>
                      {workList(
                        visibleWorks.filter(
                          (w) =>
                            w.lifecycle_status === "done" ||
                            w.lifecycle_status === "cancelled",
                        ),
                      )}
                    </section>
                  )}
                </div>
              )}
              <footer className="workspace-footer">
                记录来自 coRoof · 外部系统尚未接入
                <span>按 {timezone} 展示时间</span>
              </footer>
            </>
          )}
        </main>
      </div>
      {detail && (
        <Drawer title={drawerTitle} close={() => setDetail(null)}>
          {detail.kind === "organization" ? (
            organizationForm
          ) : detail.kind === "setup" && snapshot ? (
            <Setup
              context={context}
              departments={snapshot.departments}
              initiatives={snapshot.initiatives}
              members={snapshot.members}
              onUpdated={refresh}
            />
          ) : currentWork && snapshot ? (
            <>
              <WorkDetail
                key={currentWork.id}
                work={currentWork}
                organizationId={context.organization.id}
                members={snapshot.members}
                timezone={timezone}
                onUpdated={refresh}
              />
              {manage && (
                <Assignment
                  work={currentWork}
                  context={context}
                  members={snapshot.members}
                  onUpdated={refresh}
                />
              )}
            </>
          ) : (
            <>
              {currentDepartment && (
                <div className="drawer-members">
                  {snapshot?.members
                    .filter((m) => m.department_id === currentDepartment.id)
                    .map((member) => (
                      <button
                        className="member-chip"
                        key={member.id}
                        onClick={() =>
                          setDetail({ kind: "member", id: member.id })
                        }
                      >
                        <span className="avatar">
                          {member.name.slice(0, 1)}
                        </span>
                        {member.name}
                      </button>
                    ))}
                </div>
              )}
              {currentMember && (
                <p className="muted">只展示当前身份获授权的工作。</p>
              )}
              {workList(scopeWorks || [])}
            </>
          )}
        </Drawer>
      )}
    </div>
  );
}

function Assignment({
  work,
  context,
  members,
  onUpdated,
}: {
  work: Work;
  context: MembershipContext;
  members: Member[];
  onUpdated: () => Promise<void>;
}) {
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  if (
    !context.membership.roles.includes("owner") &&
    context.membership.department_id !== work.department_id
  )
    return null;
  return (
    <form
      className="assignment"
      onSubmit={async (e) => {
        e.preventDefault();
        const values = new FormData(e.currentTarget);
        setBusy(true);
        setError("");
        try {
          unwrap(
            await api().PATCH("/api/v1/work-items/{work_id}/assignment", {
              params: {
                header: { "x-organization-id": context.organization.id },
                path: { work_id: work.id },
              },
              body: {
                owner_id: String(values.get("owner")) || null,
                expected_version: work.version,
                idempotency_key: crypto.randomUUID(),
              },
            }),
          );
          await onUpdated();
        } catch (err) {
          setError(err instanceof Error ? err.message : "分配失败");
        } finally {
          setBusy(false);
        }
      }}
    >
      <h3>分配负责人</h3>
      <label>
        成员
        <select
          name="owner"
          defaultValue={work.owner_id || ""}
          key={work.owner_id}
        >
          <option value="">暂不分配</option>
          {members
            .filter((m) => m.department_id === work.department_id)
            .map((m) => (
              <option key={m.id} value={m.id}>
                {m.name}
              </option>
            ))}
        </select>
      </label>
      {error && (
        <p className="error" role="alert">
          {error}
        </p>
      )}
      <button disabled={busy}>保存分配</button>
    </form>
  );
}
function Brand() {
  return (
    <div className="brand">
      <span>
        <Home size={22} />
      </span>
      <b>
        co<span>Roof</span>
      </b>
    </div>
  );
}
function Empty({ text }: { text: string }) {
  return (
    <div className="empty-state">
      <CircleDot size={22} />
      <p>{text}</p>
    </div>
  );
}
