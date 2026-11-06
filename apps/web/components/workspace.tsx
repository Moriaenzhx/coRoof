"use client";
import { useCallback, useEffect, useRef, useState } from "react";
import {
  ArrowRight,
  ArrowUpRight,
  CircleDot,
  ChevronDown,
  Home,
  Layers3,
  LayoutGrid,
  PanelLeftClose,
  PanelLeftOpen,
  Plus,
  RefreshCw,
  Sparkles,
  Users,
  BriefcaseBusiness,
  BookOpen,
  type LucideIcon,
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
import { useVisibleRefresh } from "../lib/use-visible-refresh";
import { Drawer } from "./drawer";
import { AccountMenu } from "./account-menu";
import { Connectors } from "./connectors";
import { Knowledge } from "./knowledge";
import { MemoryCenter } from "./memory";
import { AiSettings } from "./ai-settings";
import { CommandBar } from "./command-bar";
import { CommandDock } from "./command-dock";
import { HeaderCompanion } from "./header-companion";
import { Projects } from "./projects";
import { ProjectOverview } from "./project-overview";
import { OverviewInbox } from "./overview-inbox";
import { MyWork } from "./my-work";
import { TeamPulse } from "./team-pulse";
import { TeamSpaces } from "./team-spaces";
import { Panorama } from "./panorama";
import { Setup } from "./setup";
import { WorkDetail } from "./work-detail";
import { AiAssistant, type Signal } from "./intelligence";
import { AssistantOverlay } from "./assistant-overlay";
import { AgentHistory } from "./agent-history";
import type { AgentCommand, AgentReaderState } from "./agent-reader";
import { EvidenceView } from "./evidence";
import { SourceView } from "./knowledge-source";
import { DecisionDetail } from "./decisions";
import { DecisionQueue } from "./decision-queue";
import { DecisionOverview } from "./decision-overview";
import { WatchCenter } from "./watch";
import { Feedback, StatusIcon, StatusLabel } from "./status";
import "./workspace-design.css";

type PageName =
  | "overview"
  | "people"
  | "business"
  | "mine"
  | "account"
  | "connectors"
  | "watch"
  | "memory"
  | "knowledge"
  | "ai-settings"
  | "help";
type Detail =
  | {
      kind: "work";
      id: string;
      intent?: "update" | "support" | "feedback";
      decisionId?: string;
    }
  | { kind: "department" | "member"; id: string }
  | { kind: "evidence"; id: string }
  | {
      kind: "document";
      source: Pick<Schemas["Citation"], "document_id" | "revision_id">;
    }
  | { kind: "decision"; id: string }
  | { kind: "setup" | "support" | "organization" };
type AssistantSession = {
  id: string;
  scope: string;
  work?: Work;
  initialRunId?: string;
  command?: AgentCommand;
  recovered?: boolean;
};
type Snapshot = {
  dashboard: Dashboard;
  departments: Department[];
  members: Member[];
  initiatives: Initiative[];
  works: Work[];
  signals: Signal[];
};
const navItems = [
  {
    id: "overview",
    label: "企业概览",
    description: "查看整体情况与需要关注的工作",
    Icon: LayoutGrid,
  },
  {
    id: "business",
    label: "项目与事项",
    description: "查看项目目标、期限与具体事项",
    Icon: Layers3,
  },
  {
    id: "people",
    label: "团队",
    description: "进入团队，查看工作与成员",
    Icon: Users,
  },
] as const;
const sidebarPreferenceKey = "coroof.sidebar.collapsed";

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
  const [projectTarget, setProjectTarget] = useState<{
    organizationId: string;
    id: string;
  } | null>(null);
  const [panoramaExpanded, setPanoramaExpanded] = useState(true);
  const [composerHeight, setComposerHeight] = useState(128);
  const [aiPage, setAiPage] = useState<{
    tab: "usage" | "connections";
    visit: number;
  }>({ tab: "usage", visit: 0 });
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false);
  const [detail, setDetail] = useState<Detail | null>(null);
  const [assistant, setAssistant] = useState<AssistantSession | null>(null);
  const assistantId = useRef<string | null>(null);
  const assistantBusy = useRef(false);
  const assistantAccessDeniedRef = useRef(false);
  const [assistantAccessDenied, setAssistantAccessDenied] = useState(false);
  const [commandRevision, setCommandRevision] = useState(0);
  const [assistantMinimized, setAssistantMinimized] = useState(false);
  const [assistantActivity, setAssistantActivity] = useState<AgentReaderState>({
    run: null,
    busy: false,
    error: "",
  });
  const [assistantNotice, setAssistantNotice] = useState("");
  const [conversationParent, setConversationParent] = useState<{
    id: string;
    question: string;
  } | null>(null);
  const [commandContext, setCommandContext] = useState<string | undefined>();
  const [commandPrefill, setCommandPrefill] = useState<{
    id: string;
    text: string;
  }>();
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [pendingInvite, setPendingInvite] = useState("");
  const [login, setLogin] = useState<Schemas["MockDelivery"] | null>(null);
  const [authMode, setAuthMode] = useState<string | null>(null);
  const generation = useRef(0);
  const [syncing, setSyncing] = useState(false);
  const [lastSync, setLastSync] = useState<string | null>(null);
  const manage =
    !!context &&
    context.membership.roles.some((r) => r === "owner" || r === "manager");
  const organizationId = context?.organization.id;
  const timezone = context?.organization.timezone || "Asia/Shanghai";
  const assistantScope = context
    ? `${context.organization.id}:${context.membership.id}:${context.membership.roles.join(",")}`
    : "";
  useEffect(() => {
    assistantId.current = null;
    assistantBusy.current = false;
    assistantAccessDeniedRef.current = false;
    setAssistantAccessDenied(false);
    setAssistant(null);
    setAssistantActivity({ run: null, busy: false, error: "" });
    setCommandContext(undefined);
    setConversationParent(null);
    setCommandPrefill(undefined);
    setAssistantNotice("");
  }, [assistantScope]);
  useEffect(() => {
    setAssistantMinimized(true);
  }, [page]);
  useEffect(() => {
    if (!organizationId || !snapshot || !assistantScope) return;
    let current = true;
    const expectedScope = assistantScope;
    void api(organizationId)
      .GET("/api/v1/agent/runs/active", {
        params: { header: { "x-organization-id": organizationId } },
      })
      .then((response) => {
        if (!current || assistantId.current) return;
        const runs = unwrap(response);
        const run = runs[0];
        if (!run) return;
        const work = run.work_item_id
          ? snapshot.works.find((item) => item.id === run.work_item_id)
          : undefined;
        if (run.work_item_id && !work) return;
        const id = crypto.randomUUID();
        assistantId.current = id;
        assistantBusy.current = true;
        setAssistant({
          id,
          scope: expectedScope,
          work,
          initialRunId: run.id,
          recovered: true,
        });
        setCommandContext(run.work_item_id || undefined);
        setAssistantActivity({ run, busy: true, error: "" });
        setAssistantMinimized(true);
        setAssistantNotice("已找回正在处理的任务。");
      })
      .catch(() => {
        // Recovery is read-only. A failed refresh must never submit another task.
      });
    return () => {
      current = false;
    };
  }, [organizationId, assistantScope, snapshot]);

  useEffect(() => {
    document.scrollingElement?.scrollTo({ top: 0, behavior: "instant" });
    if (window.innerWidth > 600)
      document
        .querySelector('.sidebar nav [aria-current="page"]')
        ?.scrollIntoView?.({
          block: "nearest",
          inline: "nearest",
          behavior: "instant",
        });
  }, [page, organizationId]);

  useEffect(() => {
    let collapsed = window.innerWidth <= 800;
    try {
      const saved = window.localStorage.getItem(sidebarPreferenceKey);
      if (saved !== null) collapsed = saved === "true";
    } catch {
      // Storage can be unavailable; navigation still works in this session.
    }
    setSidebarCollapsed(collapsed);
  }, []);

  function toggleSidebar() {
    const collapsed = !sidebarCollapsed;
    setSidebarCollapsed(collapsed);
    try {
      window.localStorage.setItem(sidebarPreferenceKey, String(collapsed));
    } catch {
      // Remember the preference in memory when browser storage is blocked.
    }
  }

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
    setSyncing(true);
    const header = { "x-organization-id": organizationId };
    let accessDenied = false;
    const accessDeniedMessage =
      "当前企业的访问权限已失效，已收起查询结果。请重新核对身份或切换企业。";
    // Inspect every response before Promise.all aggregates failures: a later
    // authorization denial must still clear old answers after a network error.
    const read = <T,>(result: {
      data?: T;
      error?: unknown;
      response?: { status: number };
    }): T => {
      if (
        current === generation.current &&
        !accessDenied &&
        (result.response?.status === 401 || result.response?.status === 403)
      ) {
        accessDenied = true;
        assistantId.current = null;
        assistantBusy.current = false;
        assistantAccessDeniedRef.current = true;
        setAssistantAccessDenied(true);
        setAssistant(null);
        setAssistantActivity({ run: null, busy: false, error: "" });
        setAssistantNotice("");
        setCommandContext(undefined);
        setConversationParent(null);
        setCommandPrefill(undefined);
        setCommandRevision((value) => value + 1);
        setSnapshot(null);
        setError(accessDeniedMessage);
      }
      if (result.response?.status === 401 || result.response?.status === 403)
        throw new Error(accessDeniedMessage);
      return unwrap(result);
    };
    try {
      const [dashboard, departments, members, initiatives, works, signals] =
        await Promise.all([
          api().GET("/api/v1/dashboard", { params: { header } }).then(read),
          collect((offset) =>
            api()
              .GET("/api/v1/departments", {
                params: { header, query: { offset, limit: 100 } },
              })
              .then(read),
          ),
          collect((offset) =>
            api()
              .GET("/api/v1/members", {
                params: { header, query: { offset, limit: 100 } },
              })
              .then(read),
          ),
          collect((offset) =>
            api()
              .GET("/api/v1/initiatives", {
                params: { header, query: { offset, limit: 100 } },
              })
              .then(read),
          ),
          collect((offset) =>
            api()
              .GET("/api/v1/work-items", {
                params: { header, query: { offset, limit: 100 } },
              })
              .then(read),
          ),
          collect((offset) =>
            api()
              .GET("/api/v1/signals", {
                params: { header, query: { offset, limit: 100 } },
              })
              .then(read),
          ),
        ]);
      if (current === generation.current) {
        assistantAccessDeniedRef.current = false;
        setAssistantAccessDenied(false);
        setError("");
        setLastSync(new Date().toISOString());
        setSnapshot({
          dashboard,
          departments,
          members,
          initiatives,
          works,
          signals,
        });
      }
    } catch (e) {
      if (current === generation.current) {
        setSnapshot(null);
        if (!accessDenied)
          setError(e instanceof Error ? e.message : "暂时无法更新记录");
      }
      throw e;
    } finally {
      if (current === generation.current) setSyncing(false);
    }
  }, [organizationId]);
  useVisibleRefresh(
    refresh,
    !!organizationId &&
      !detail &&
      !busy &&
      ["overview", "people", "business", "mine"].includes(page),
  );
  useEffect(() => {
    setPendingInvite(
      new URLSearchParams(window.location.hash.slice(1)).get("invite") || "",
    );
    api()
      .GET("/api/v1/auth/me")
      .then(async (result) => {
        if (result.response.status === 401) {
          const runtime = unwrap(await api().GET("/api/v1/runtime"));
          setAuthMode(runtime.auth_mode);
          if (new URLSearchParams(window.location.search).has("auth_error")) {
            setError(
              "登录未完成，请重试；如身份信息有变更，请联系部署管理员核验。",
            );
            window.history.replaceState(
              null,
              "",
              window.location.pathname + window.location.hash,
            );
          }
          return;
        }
        const user = unwrap(result);
        setAuthMode(user.mode || "mock");
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
    setLastSync(null);
    setPanoramaExpanded(window.innerWidth > 600);
    setProjectTarget(null);
    setError("");
    void refresh().catch(() => {
      /* refresh owns scope-guarded errors. */
    });
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
  async function oidcLogin() {
    await run(async () => {
      const result = unwrap(
        await api().POST("/api/v1/auth/oidc/start", {
          body: { invite_token: pendingInvite || null },
        }),
      );
      window.location.assign(result.authorization_url);
    });
  }
  async function logout() {
    await endSessions(false);
  }
  async function endSessions(all: boolean) {
    await run(async () => {
      const result = all
        ? await api().POST("/api/v1/auth/logout-all")
        : await api().POST("/api/v1/auth/logout");
      if (result.error) throw new Error("退出失败");
      generation.current++;
      setMe(null);
      setContext(null);
      setSnapshot(null);
      setDetail(null);
      setPage("overview");
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
          {error && <Feedback kind="error">{error}</Feedback>}
          {authMode === "oidc" ? (
            <>
              <p className="muted">
                通过已配置的身份服务验证邮箱后进入工作空间。
              </p>
              <button className="primary" disabled={busy} onClick={oidcLogin}>
                {busy ? "正在连接…" : "安全登录"}
                <ArrowRight size={16} />
              </button>
            </>
          ) : authMode !== "mock" ? (
            <p className="muted">暂时无法获取登录方式，请刷新重试。</p>
          ) : !login ? (
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
          {authMode === "mock" && (
            <p className="fine-print">
              本地开发版 ·
              模拟身份验证，未发送邮件。正式部署前必须接入真实身份与邮件服务。
            </p>
          )}
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
          {error && <Feedback kind="error">{error}</Feedback>}
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

  const requestedWorkId = detail?.kind === "work" ? detail.id : undefined;
  const selectedWork = snapshot?.works.find(
    (work) => work.id === requestedWorkId,
  );
  const currentWork = detail?.kind === "work" ? selectedWork : undefined;
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
          : detail?.kind === "decision"
            ? "决策详情"
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
        : detail?.kind === "support"
          ? snapshot?.works.filter(
              (w) =>
                w.needs_support &&
                w.source_authority === "native" &&
                !["done", "cancelled"].includes(w.lifecycle_status),
            )
          : [];
  const title =
    page === "mine"
      ? "我的工作"
      : page === "overview"
        ? context.membership.roles.includes("owner")
          ? "企业概览"
          : "部门概览"
        : navItems.find((n) => n.id === page)?.label;
  const isOwner = context.membership.roles.includes("owner");
  const navButton = ({
    id,
    label,
    description,
    Icon,
  }: {
    id: PageName;
    label: string;
    description: string;
    Icon: LucideIcon;
  }) => (
    <button
      key={id}
      className={page === id ? "active" : ""}
      aria-label={label}
      title={`${label} · ${description}`}
      aria-current={page === id ? "page" : undefined}
      onClick={() => {
        setPage(id);
        setDetail(null);
      }}
    >
      <Icon size={18} aria-hidden="true" />
      <span className="nav-label">{label}</span>
    </button>
  );
  const personalNavigation = (
    <div className="nav-group" role="group" aria-label="个人">
      <span className="nav-group-label" aria-hidden="true">
        个人
      </span>
      <div className="nav-group-items">
        {navButton({
          id: "mine",
          label: "我的工作",
          description: isOwner
            ? "处理本人事项、确认方案并跟进结果"
            : "查看分配给自己的事项并汇报进展",
          Icon: BriefcaseBusiness,
        })}
      </div>
    </div>
  );
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
              className="work-indicator"
              data-status={work.lifecycle_status}
            >
              <StatusIcon status={work.lifecycle_status} size={18} />
            </span>
            <span className="work-row-body">
              <strong>{work.title}</strong>
              <span className="work-row-meta">
                <span>
                  {snapshot?.members.find((m) => m.id === work.owner_id)
                    ?.name || "未分配"}
                </span>
                <span
                  className="work-lifecycle"
                  data-status={work.lifecycle_status}
                >
                  {statusLabels[work.lifecycle_status]}
                </span>
                {work.needs_support && <StatusLabel status="support" />}
              </span>
            </span>
            <ArrowUpRight size={16} />
          </button>
        ))}
      </div>
    ) : (
      <Empty text="这里还没有工作记录。" />
    );
  function openAssistant({
    workId,
    question = "",
    runId,
    autoStart = false,
  }: {
    workId?: string;
    question?: string;
    runId?: string;
    autoStart?: boolean;
  }) {
    if (assistantAccessDeniedRef.current) return false;
    if (assistantBusy.current) {
      setAssistantMinimized(false);
      setAssistantNotice(
        "正在处理上一条指令。你可以先切换页面，完成或停止后再发送下一条。",
      );
      return false;
    }
    const work = workId
      ? snapshot?.works.find((item) => item.id === workId)
      : undefined;
    if (workId && !work) {
      setDetail({ kind: "work", id: workId });
      return false;
    }
    const id = crypto.randomUUID();
    assistantId.current = id;
    assistantBusy.current = autoStart || !!runId;
    setAssistantActivity({ run: null, busy: autoStart || !!runId, error: "" });
    setAssistant({
      id,
      scope: assistantScope,
      work,
      initialRunId: runId,
      command: autoStart
        ? {
            id,
            question,
            ...(!workId && conversationParent
              ? { parentRunId: conversationParent.id }
              : {}),
          }
        : undefined,
    });
    setAssistantMinimized(false);
    setAssistantNotice("");
    if (!runId) setCommandContext(workId);
    if (runId || (!autoStart && workId)) setConversationParent(null);
    if (!autoStart && !runId) setCommandPrefill({ id, text: question });
    setDetail(null);
    return true;
  }
  const activeAssistant =
    assistant?.scope === assistantScope ? assistant : null;
  const workPartner = snapshot ? (
    <HeaderCompanion
      key={`${organizationId}:${context.membership.id}`}
      scopeKey={`${organizationId}:${context.membership.id}`}
      composerHeight={composerHeight}
      works={page === "mine" ? visibleWorks : snapshot.works}
      members={snapshot.members}
      timezone={timezone}
      loading={syncing}
      onWork={(id) => setDetail({ kind: "work", id })}
      onAsk={(workId, question) => openAssistant({ workId, question })}
      onWatch={
        context.membership.roles.includes("owner")
          ? () => setPage("watch")
          : undefined
      }
    />
  ) : null;
  return (
    <div className={`app-shell${sidebarCollapsed ? " sidebar-collapsed" : ""}`}>
      <aside className="sidebar" id="workspace-sidebar">
        <div className="sidebar-header">
          <Brand />
          <button
            className="icon-button sidebar-toggle"
            onClick={toggleSidebar}
            aria-label={sidebarCollapsed ? "展开侧边栏" : "收起侧边栏"}
            title={sidebarCollapsed ? "展开侧边栏" : "收起侧边栏"}
            aria-expanded={!sidebarCollapsed}
            aria-controls="workspace-sidebar"
          >
            {sidebarCollapsed ? (
              <PanelLeftOpen size={17} />
            ) : (
              <PanelLeftClose size={17} />
            )}
          </button>
        </div>
        <nav aria-label="主导航">
          {!manage && personalNavigation}
          {manage && (
            <div
              className="nav-group"
              role="group"
              aria-label={isOwner ? "企业经营" : "部门协作"}
            >
              <span className="nav-group-label" aria-hidden="true">
                {isOwner ? "企业经营" : "部门协作"}
              </span>
              <div className="nav-group-items">
                {navItems.map((item) =>
                  navButton({
                    ...item,
                    label:
                      item.id === "overview" && !isOwner
                        ? "部门概览"
                        : item.label,
                  }),
                )}
              </div>
            </div>
          )}
          <div className="nav-group" role="group" aria-label="资料">
            <span className="nav-group-label" aria-hidden="true">
              资料
            </span>
            <div className="nav-group-items">
              {navButton({
                id: "knowledge",
                label: "企业知识库",
                description: "查阅有权访问的制度、流程与资料",
                Icon: BookOpen,
              })}
            </div>
          </div>
          {manage && personalNavigation}
        </nav>
        <AccountMenu
          name={me.name}
          identityMode={me.mode}
          organization={context.organization.name}
          role={
            context.membership.roles.includes("owner")
              ? "企业所有者"
              : manage
                ? "部门负责人"
                : "成员"
          }
          owner={context.membership.roles.includes("owner")}
          onSelect={(next, tab) => {
            if (next === "ai-settings")
              setAiPage((value) => ({
                tab: tab || "usage",
                visit: value.visit + 1,
              }));
            setPage(next);
            setDetail(null);
          }}
          onLogout={logout}
        />
      </aside>
      <div className="main-column">
        <main
          className="workspace"
          aria-label={page === "overview" ? title : undefined}
        >
          <div className="page-heading">
            {page !== "overview" && (
              <div className="heading-copy">
                <h1>
                  {page === "watch"
                    ? "持续关注"
                    : page === "memory"
                      ? "决策经验"
                      : page === "knowledge"
                        ? "企业知识库"
                        : page === "ai-settings"
                          ? "AI 使用与设置"
                          : page === "connectors"
                            ? "外部连接"
                            : page === "account"
                              ? "个人设置"
                              : page === "help"
                                ? "使用帮助"
                                : page === "people"
                                  ? "团队空间"
                                  : title}
                </h1>
                <p>
                  {page === "memory"
                    ? "回看已确认的选择与实际结果，为下一次判断积累参考。"
                    : page === "knowledge"
                      ? "找制度、查流程，需要的资料在这里。"
                      : [
                            "ai-settings",
                            "connectors",
                            "watch",
                            "account",
                            "help",
                          ].includes(page)
                        ? "管理服务与偏好，让工作更顺畅。"
                        : page === "mine"
                          ? isOwner
                            ? "处理分配给你的事项、确认方案，并跟进实际结果。"
                            : "有进展、遇到阻塞，随时说一声。"
                          : page === "people"
                            ? "进入团队，看工作、找同事。"
                            : page === "business"
                              ? "查看项目目标、负责人、截止时间与事项进展。"
                              : "从整体态势出发，逐层了解企业正在发生什么。"}
                </p>
              </div>
            )}
            {![
              "ai-settings",
              "connectors",
              "watch",
              "account",
              "help",
              "knowledge",
              "memory",
            ].includes(page) && (
              <div className="heading-actions">
                <span className="sync-status" role="status" aria-live="polite">
                  <span
                    className={syncing ? "sync-dot updating" : "sync-dot"}
                    aria-hidden="true"
                  />
                  {syncing
                    ? "正在更新记录"
                    : lastSync
                      ? `已同步 ${formatTime(lastSync, timezone)} · 自动更新`
                      : "等待同步"}
                </span>
                <button
                  className="icon-button"
                  aria-label="刷新数据"
                  disabled={busy || syncing}
                  onClick={() => run(refresh)}
                >
                  <RefreshCw
                    size={17}
                    className={syncing ? "sync-spin" : undefined}
                  />
                </button>
                {manage && (
                  <button
                    className="primary"
                    onClick={() => setDetail({ kind: "setup" })}
                  >
                    <Plus size={16} />
                    {page === "people" ? "管理团队" : "组织与工作"}
                  </button>
                )}
              </div>
            )}
          </div>
          {error && (
            <Feedback kind="error">
              {error}
              <button className="plain" onClick={() => run(refresh)}>
                重试
              </button>
            </Feedback>
          )}
          {page === "account" && (
            <div className="account-page">
              <section className="settings-card account-settings">
                <span className="eyebrow">个人账户</span>
                <h2>{me.name}</h2>
                <p>{me.email}</p>
                <p>
                  {context.organization.name} ·{" "}
                  {context.membership.roles.includes("owner")
                    ? "企业所有者"
                    : manage
                      ? "部门负责人"
                      : "成员"}
                </p>
                <p className="muted">
                  {me.mode === "oidc"
                    ? "当前身份已通过登录服务验证。企业权限由工作空间独立管理。"
                    : "当前为开发模拟身份，尚未接入正式身份验证。"}
                </p>
                <button
                  className="secondary"
                  disabled={busy}
                  onClick={() => endSessions(true)}
                >
                  退出所有设备
                </button>
                <h3>企业</h3>
                <label htmlFor="account-organization">切换企业</label>
                <select
                  id="account-organization"
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
                <h3>工作区偏好</h3>
                <button className="secondary" onClick={toggleSidebar}>
                  {sidebarCollapsed ? "展开侧边栏" : "收起侧边栏"}
                </button>
                <p className="muted">侧边栏偏好仅保存在当前浏览器。</p>
              </section>
              {isOwner && (
                <button className="plain" onClick={() => setPage("memory")}>
                  查看以前的处理经验 <ArrowRight size={15} />
                </button>
              )}
              {isOwner && (
                <section
                  className="settings-card preference-settings"
                  aria-label="AI 协作偏好"
                >
                  <h2>AI 协作偏好</h2>
                  <p className="muted">
                    告诉 coRoof
                    你关注什么、希望如何沟通。偏好只属于当前企业中的你，确认后才会用于后续协助。
                  </p>
                  <MemoryCenter
                    key={`preferences-${organizationId}:${context.membership.id}`}
                    kind="preference"
                    organizationId={context.organization.id}
                    timezone={timezone}
                  />
                </section>
              )}
            </div>
          )}
          {!snapshot ? (
            <p className="muted" role="status">
              正在读取已授权的工作记录…
            </p>
          ) : (
            <>
              {page === "watch" &&
                context.membership.roles.includes("owner") && (
                  <WatchCenter
                    key={organizationId}
                    organizationId={context.organization.id}
                    timezone={timezone}
                    departments={snapshot.departments}
                    initiatives={snapshot.initiatives}
                    onWork={(id) => setDetail({ kind: "work", id })}
                    onPlan={(runId, workId) => openAssistant({ runId, workId })}
                    onDecision={(id) => setDetail({ kind: "decision", id })}
                  />
                )}
              {page === "memory" &&
                context.membership.roles.includes("owner") && (
                  <MemoryCenter
                    kind="experience"
                    key={`experience-${organizationId}:${context.membership.id}`}
                    organizationId={context.organization.id}
                    timezone={timezone}
                  />
                )}
              {page === "knowledge" && (
                <Knowledge
                  key={`${organizationId}:${context.membership.id}`}
                  organizationId={context.organization.id}
                  memberId={context.membership.id}
                  timezone={timezone}
                  isOwner={context.membership.roles.includes("owner")}
                  departments={snapshot.departments}
                  members={snapshot.members}
                  onAsk={(question) =>
                    openAssistant({
                      question: question || "帮我查找需要的企业资料",
                    })
                  }
                />
              )}
              {page === "ai-settings" && (
                <AiSettings
                  key={`${organizationId}:${context.membership.roles.includes("owner")}:${aiPage.visit}`}
                  initialTab={aiPage.tab}
                  organizationId={context.organization.id}
                  timezone={timezone}
                  isOwner={context.membership.roles.includes("owner")}
                />
              )}
              {page === "connectors" && (
                <Connectors
                  key={`${organizationId}:${context.membership.roles.includes("owner")}`}
                  organizationId={context.organization.id}
                  isOwner={context.membership.roles.includes("owner")}
                  departments={snapshot.departments}
                  members={snapshot.members}
                  timezone={timezone}
                />
              )}
              {page === "help" && (
                <section className="settings-card help-settings">
                  <span className="eyebrow">开始使用 COROOF</span>
                  <h2>从真实记录开始协作</h2>
                  <h3>记录与确认</h3>
                  <p>
                    在“我的工作”中选择事项，填写进展并检查草稿。明确确认后才会更新工作记录。
                  </p>
                  <h3>询问与决策</h3>
                  <p>
                    在底部输入问题并发送，或点击右下工作伙伴查看带依据的建议；AI
                    建议不会自动执行，重要决策需要明确确认。
                  </p>
                  <p>
                    按 ⌘K（Mac）或 Ctrl+K 唤醒输入框。支持的浏览器可点击麦克风
                    进行语音转文字，核对后再发送。
                  </p>
                  <h3>AI 服务与用量</h3>
                  <p>
                    通过账户菜单查看 AI
                    使用情况。企业所有者可以添加连接、测试并启用模型，或设置使用额度。
                  </p>
                  <p className="muted">
                    没有记录的情况会明确告诉你。模型暂时不可用时会提示原因，不会假装已经办好。当前为开发测试身份。
                  </p>
                </section>
              )}
              {page === "overview" && (
                <div className="overview-workspace">
                  <section className="organization-overview">
                    <button
                      className="organization-overview-toggle"
                      aria-expanded={panoramaExpanded}
                      aria-controls="organization-panorama"
                      onClick={() => setPanoramaExpanded((value) => !value)}
                    >
                      <span>
                        <strong>
                          {context.membership.roles.includes("owner")
                            ? "企业全景"
                            : "部门全景"}
                        </strong>
                        <small>
                          {snapshot.dashboard.member_count} 位成员 ·{" "}
                          {snapshot.dashboard.departments.length} 个部门 ·{" "}
                          {snapshot.dashboard.total_work} 项已记录工作
                        </small>
                      </span>
                      <span className="organization-overview-expand">
                        {panoramaExpanded ? "收起全景" : "展开全景"}
                        <ChevronDown size={16} />
                      </span>
                    </button>
                    {panoramaExpanded && (
                      <div id="organization-panorama">
                        <Panorama
                          data={snapshot.dashboard}
                          onDepartment={(id) =>
                            setDetail({ kind: "department", id })
                          }
                          onSupport={() => setDetail({ kind: "support" })}
                        />
                      </div>
                    )}
                  </section>
                  <OverviewInbox
                    key={`inbox-${organizationId}:${context.membership.id}`}
                    organizationId={context.organization.id}
                    timezone={timezone}
                    works={snapshot.works}
                    signals={snapshot.signals}
                    members={snapshot.members}
                    initiatives={snapshot.initiatives}
                    isOwner={context.membership.roles.includes("owner")}
                    onWork={(id) => setDetail({ kind: "work", id })}
                    onAsk={(workId, question) =>
                      openAssistant({ workId, question })
                    }
                    onPlan={(runId, workId) => openAssistant({ runId, workId })}
                    onDecision={(id) => setDetail({ kind: "decision", id })}
                    onManage={() => setPage("watch")}
                  />
                  <ProjectOverview
                    initiatives={snapshot.initiatives}
                    works={snapshot.works}
                    members={snapshot.members}
                    departments={snapshot.departments}
                    timezone={timezone}
                    onProject={(id) => {
                      setProjectTarget({
                        organizationId: context.organization.id,
                        id,
                      });
                      setPage("business");
                    }}
                    onWork={(id) => setDetail({ kind: "work", id })}
                    onAsk={(workId) => openAssistant({ workId })}
                    onAll={() => {
                      setProjectTarget(null);
                      setPage("business");
                    }}
                  />
                  <details className="overview-secondary">
                    <summary>处理记录与团队动态</summary>
                    {isOwner && (
                      <DecisionOverview
                        key={`decision-overview-${organizationId}:${context.membership.id}`}
                        organizationId={context.organization.id}
                        timezone={timezone}
                        revision={snapshot.dashboard.generated_at}
                        onMine={() => {
                          setPage("mine");
                          setDetail(null);
                        }}
                        onOpen={(id) => setDetail({ kind: "decision", id })}
                      />
                    )}
                    <TeamPulse
                      key={`pulse-${organizationId}`}
                      organizationId={context.organization.id}
                      works={snapshot.works}
                      members={snapshot.members}
                      initiatives={snapshot.initiatives}
                      timezone={timezone}
                      revision={snapshot.dashboard.generated_at}
                      compact
                      onWork={(id) => setDetail({ kind: "work", id })}
                    />
                  </details>
                </div>
              )}
              {page === "people" && (
                <TeamSpaces
                  key={`${organizationId}:${context.membership.id}`}
                  organizationName={context.organization.name}
                  departments={snapshot.departments}
                  members={snapshot.members}
                  works={snapshot.works}
                  initiatives={snapshot.initiatives}
                  timezone={timezone}
                  onWork={(id) => setDetail({ kind: "work", id })}
                  onMember={(id) => setDetail({ kind: "member", id })}
                  onProject={(id) => {
                    setProjectTarget({
                      organizationId: context.organization.id,
                      id,
                    });
                    setPage("business");
                  }}
                  onKnowledge={() => setPage("knowledge")}
                  onOverview={() => setPage("overview")}
                  onManage={
                    manage ? () => setDetail({ kind: "setup" }) : undefined
                  }
                />
              )}
              {page === "business" && (
                <Projects
                  organizationId={context.organization.id}
                  canDecide={isOwner}
                  revision={snapshot.dashboard.generated_at}
                  onDecision={(id) => setDetail({ kind: "decision", id })}
                  key={`${organizationId}:${projectTarget && projectTarget.organizationId === organizationId ? projectTarget.id : "all"}`}
                  initialProjectId={
                    projectTarget &&
                    projectTarget.organizationId === organizationId
                      ? projectTarget.id
                      : undefined
                  }
                  initiatives={snapshot.initiatives}
                  works={snapshot.works}
                  members={snapshot.members}
                  departments={snapshot.departments}
                  timezone={timezone}
                  onWork={(id) => setDetail({ kind: "work", id })}
                  onAsk={(workId) =>
                    openAssistant({
                      workId,
                      question:
                        "请核实这项工作的当前进展、支持需求与下一步，未记录的结果保持未知。",
                    })
                  }
                />
              )}
              {page === "mine" && (
                <div className="personal-workspace">
                  {isOwner && (
                    <DecisionQueue
                      key={`my-decisions-${organizationId}:${context.membership.id}`}
                      organizationId={context.organization.id}
                      timezone={timezone}
                      revision={snapshot.dashboard.generated_at}
                      scope="mine"
                      onOpen={(id) => setDetail({ kind: "decision", id })}
                    />
                  )}
                  {(!isOwner || visibleWorks.length > 0) && (
                    <MyWork
                      key={`${organizationId}:${context.membership.id}`}
                      organizationId={context.organization.id}
                      revision={snapshot.dashboard.generated_at}
                      works={visibleWorks}
                      memberId={context.membership.id}
                      members={snapshot.members}
                      departments={snapshot.departments}
                      initiatives={snapshot.initiatives}
                      timezone={timezone}
                      onWork={(id, intent, decisionId) =>
                        setDetail({ kind: "work", id, intent, decisionId })
                      }
                      onAsk={(workId, question) =>
                        openAssistant({ workId, question })
                      }
                    />
                  )}
                  <AgentHistory
                    key={`history-${assistantScope}`}
                    organizationId={context.organization.id}
                    timezone={timezone}
                    revision={`${snapshot.dashboard.generated_at}:${assistantActivity.run?.id || ""}:${assistantActivity.run?.version || 0}`}
                    onOpen={(runId, workId, question) =>
                      openAssistant({ runId, workId, question })
                    }
                  />
                  {visibleWorks.length > 0 && (
                    <details className="overview-secondary">
                      <summary>我的工作动态</summary>
                      <TeamPulse
                        key={`my-pulse-${organizationId}:${context.membership.id}`}
                        organizationId={context.organization.id}
                        works={visibleWorks}
                        members={snapshot.members}
                        initiatives={snapshot.initiatives}
                        timezone={timezone}
                        revision={snapshot.dashboard.generated_at}
                        compact
                        title="与我相关的动态"
                        description="查看本人事项的进展与交接记录。"
                        onWork={(id) => setDetail({ kind: "work", id })}
                      />
                    </details>
                  )}
                </div>
              )}
              <footer className="workspace-footer">
                仅展示当前获授权的已记录工作 · 未覆盖的信息仍然未知
                <span>按 {timezone} 展示时间</span>
              </footer>
            </>
          )}
        </main>
      </div>
      <CommandDock obscured={!!detail} onHeight={setComposerHeight}>
        <CommandBar
          key={`${organizationId}:${context.membership.id}:${commandRevision}`}
          scopeKey={`${organizationId}:${context.membership.id}:${page}:${commandContext || ""}:${commandPrefill?.id || ""}`}
          disabled={busy || !!detail || assistantAccessDenied}
          processing={!!activeAssistant && assistantActivity.busy}
          prefill={commandPrefill}
          contextLabel={
            commandContext
              ? snapshot?.works.find((work) => work.id === commandContext)
                  ?.title || "工作记录待重新核对"
              : conversationParent
                ? `接着聊：${conversationParent.question}`
                : undefined
          }
          clearContextLabel={
            conversationParent && !commandContext
              ? "换个话题"
              : "清除工作上下文"
          }
          onClearContext={() => {
            setCommandContext(undefined);
            setConversationParent(null);
          }}
          onSubmit={(question) =>
            openAssistant({ question, workId: commandContext, autoStart: true })
          }
        />
      </CommandDock>
      {workPartner}
      {activeAssistant && (
        <AssistantOverlay
          activity={assistantActivity}
          minimized={assistantMinimized}
          obscured={!!detail}
          notice={assistantNotice}
          onMinimize={() => setAssistantMinimized(true)}
          onRestore={() => setAssistantMinimized(false)}
          onHistory={() => {
            setPage("mine");
            setAssistantMinimized(true);
          }}
          onConfigure={
            isOwner
              ? () => {
                  setAiPage({ tab: "connections", visit: Date.now() });
                  setPage("ai-settings");
                  setAssistantMinimized(true);
                }
              : undefined
          }
        >
          <AiAssistant
            key={activeAssistant.id}
            presentation="floating"
            organizationId={context.organization.id}
            work={activeAssistant.work}
            timezone={timezone}
            canDecide={isOwner}
            command={activeAssistant.command}
            initialRunId={activeAssistant.initialRunId}
            onStateChange={(state) => {
              if (assistantId.current !== activeAssistant.id) return;
              if (
                (activeAssistant.command || activeAssistant.initialRunId) &&
                !state.run &&
                !state.busy &&
                !state.error
              )
                return;
              assistantBusy.current = state.busy;
              setAssistantActivity(state);
              if (
                state.run?.state === "completed" &&
                (activeAssistant.command || activeAssistant.recovered) &&
                !activeAssistant.work
              ) {
                setConversationParent({
                  id: state.run.id,
                  question: state.run.question,
                });
              }
              if (state.error && !state.run) setConversationParent(null);
            }}
            onDecision={(id) => setDetail({ kind: "decision", id })}
            onEvidence={(id) => setDetail({ kind: "evidence", id })}
            onDocument={(source) => setDetail({ kind: "document", source })}
            onUpdated={refresh}
          />
        </AssistantOverlay>
      )}
      {detail && (
        <Drawer
          title={
            detail.kind === "evidence"
              ? "原始依据"
              : detail.kind === "decision"
                ? "确认处理安排"
                : detail.kind === "document"
                  ? "公司资料"
                  : drawerTitle
          }
          close={() => setDetail(null)}
        >
          {requestedWorkId && !selectedWork ? (
            <Feedback kind="info">
              这项工作尚未载入，或已不在当前可见范围。重新读取后再查看具体记录。
              {error && <p>{error}</p>}
              <button
                className="secondary"
                disabled={busy || syncing}
                onClick={() => run(refresh)}
              >
                {busy || syncing ? "正在读取…" : "重新读取工作记录"}
              </button>
            </Feedback>
          ) : detail.kind === "evidence" ? (
            <EvidenceView
              key={`${organizationId}:${detail.id}`}
              id={detail.id}
              organizationId={context.organization.id}
              timezone={timezone}
              onBack={() => setDetail(null)}
            />
          ) : detail.kind === "document" ? (
            <SourceView
              source={detail.source}
              organizationId={context.organization.id}
              timezone={timezone}
            />
          ) : detail.kind === "decision" ? (
            <DecisionDetail
              actorId={context.membership.id}
              key={`${organizationId}:${context.membership.id}:${detail.id}`}
              id={detail.id}
              organizationId={context.organization.id}
              timezone={timezone}
              onUpdated={refresh}
              onReask={(workId) =>
                openAssistant({
                  workId,
                  question:
                    "请根据最新记录看看这件事怎么处理，并给出一个建议。",
                  autoStart: true,
                })
              }
            />
          ) : detail.kind === "organization" ? (
            organizationForm
          ) : detail.kind === "setup" && snapshot ? (
            <Setup
              authMode={me.mode}
              context={context}
              departments={snapshot.departments}
              initiatives={snapshot.initiatives}
              members={snapshot.members}
              onUpdated={refresh}
            />
          ) : currentWork && snapshot ? (
            <>
              <button
                className="context-ask"
                onClick={() => openAssistant({ workId: currentWork.id })}
              >
                <Sparkles size={16} />
                询问这项工作
                <ArrowUpRight size={15} />
              </button>
              <WorkDetail
                key={`${currentWork.id}:${detail.kind === "work" ? `${detail.intent || "view"}:${detail.decisionId || ""}` : "view"}`}
                initialIntent={
                  detail.kind === "work" ? detail.intent : undefined
                }
                initialDecisionId={
                  detail.kind === "work" ? detail.decisionId : undefined
                }
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
      {error && <Feedback kind="error">{error}</Feedback>}
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
