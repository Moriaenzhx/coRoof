"use client";

import { useEffect, useId, useState } from "react";
import { ArrowUpRight, ChevronLeft, ChevronRight } from "lucide-react";
import type { paths } from "../../../packages/api-client/schema";
import { api, formatTime, unwrap, type Schemas } from "../lib/api";
import "./decision-queue.css";

type Decision = Schemas["DecisionListOut"];
type Query = NonNullable<
  paths["/api/v1/decisions"]["get"]["parameters"]["query"]
>;
type View = NonNullable<Query["view"]>;
type Scope = "mine" | "company" | "project";
type Props = {
  organizationId: string;
  timezone: string;
  revision: string;
  onOpen: (id: string) => void;
  scope: Scope;
  initiativeId?: string;
};
type Result = {
  key: string;
  items: Decision[];
  total: number;
  error: string;
};

const PAGE_SIZE = 10;
const scopes = {
  mine: {
    title: "等我确认与跟进",
    description: "确认自己的方案，记下后续结果。",
  },
  company: {
    title: "企业决策记录",
    description: "查阅企业的方案、跟进安排与实际结果。",
  },
  project: {
    title: "项目决策记录",
    description: "查阅本项目事项的方案、跟进安排与实际结果。",
  },
} satisfies Record<Scope, { title: string; description: string }>;
const views: { value: View; label: string }[] = [
  { value: "pending", label: "待确认" },
  { value: "follow_up", label: "待跟进" },
  { value: "recorded", label: "已有结果" },
  { value: "all", label: "全部" },
];

export function DecisionQueue(props: Props) {
  // Reset filters and drop every previous result when its authority/scope changes.
  return (
    <ScopedDecisionQueue
      key={JSON.stringify([
        props.organizationId,
        props.scope,
        props.scope === "project" ? props.initiativeId : null,
      ])}
      {...props}
    />
  );
}

function ScopedDecisionQueue({
  organizationId,
  timezone,
  revision,
  onOpen,
  scope,
  initiativeId,
}: Props) {
  const headingId = useId();
  const [view, setView] = useState<View>(
    scope === "mine" ? "action_required" : "all",
  );
  const [offset, setOffset] = useState(0);
  const [attempt, setAttempt] = useState(0);
  const [result, setResult] = useState<Result | null>(null);
  const canRead = Boolean(
    organizationId && (scope !== "project" || initiativeId),
  );
  const requestKey = JSON.stringify([
    organizationId,
    scope,
    initiativeId,
    view,
    offset,
    revision,
    attempt,
  ]);
  const current = result?.key === requestKey ? result : null;
  const busy = canRead && current === null;

  useEffect(() => {
    if (!canRead) return;
    setResult(null);
    const controller = new AbortController();
    let active = true;
    async function load() {
      try {
        const page = unwrap(
          await api(organizationId).GET("/api/v1/decisions", {
            signal: controller.signal,
            params: {
              header: { "x-organization-id": organizationId },
              query: {
                mine: scope === "mine",
                ...(scope === "project" ? { initiative_id: initiativeId } : {}),
                view,
                offset,
                limit: PAGE_SIZE,
              },
            },
          }),
        );
        if (active) {
          setResult({
            key: requestKey,
            items: page.items,
            total: page.total,
            error: "",
          });
        }
      } catch (error) {
        if (active) {
          setResult({
            key: requestKey,
            items: [],
            total: 0,
            error:
              error instanceof Error ? error.message : "读取失败，请重试。",
          });
        }
      }
    }
    void load();
    return () => {
      active = false;
      controller.abort();
    };
  }, [canRead, organizationId, scope, initiativeId, view, offset, requestKey]);

  const filters =
    scope === "mine"
      ? [{ value: "action_required" as const, label: "待我处理" }, ...views]
      : views;
  const emptyInbox =
    scope === "mine" &&
    view === "action_required" &&
    offset === 0 &&
    current &&
    !current.error &&
    current.total === 0;
  function selectView(next: View) {
    if (view === next && offset === 0) return;
    setResult(null);
    setView(next);
    setOffset(0);
  }

  return (
    <section className="decision-queue" aria-labelledby={headingId}>
      <div className="decision-queue-heading">
        <h2 id={headingId}>{scopes[scope].title}</h2>
        {!emptyInbox && <p>{scopes[scope].description}</p>}
      </div>
      {canRead && !emptyInbox && (
        <div
          className="decision-queue-filters"
          role="group"
          aria-label="决策分类"
        >
          {scope === "mine" &&
            filters
              .filter(
                (filter) =>
                  filter.value === "action_required" || filter.value === "all",
              )
              .map((filter) => (
                <button
                  key={filter.value}
                  type="button"
                  aria-pressed={view === filter.value}
                  onClick={() => selectView(filter.value)}
                >
                  {filter.value === "all" ? "全部记录" : filter.label}
                </button>
              ))}
          <details className="decision-queue-refine">
            <summary>
              {view !== "all" && view !== "action_required"
                ? views.find((filter) => filter.value === view)?.label
                : "按状态筛选"}
            </summary>
            {views
              .filter((filter) => scope !== "mine" || filter.value !== "all")
              .map((filter) => (
                <button
                  key={filter.value}
                  type="button"
                  aria-pressed={view === filter.value}
                  onClick={() => selectView(filter.value)}
                >
                  {filter.label}
                </button>
              ))}
          </details>
        </div>
      )}
      {!canRead && (
        <p className="decision-queue-message" role="status">
          {organizationId ? "请先选择项目，再查看决策记录。" : "请先选择企业。"}
        </p>
      )}
      {busy && (
        <p className="decision-queue-message" role="status">
          正在读取决策记录…
        </p>
      )}
      {current?.error && (
        <div className="decision-queue-error" role="alert">
          <p>决策记录读取失败：{current.error}</p>
          <button
            type="button"
            onClick={() => setAttempt((value) => value + 1)}
          >
            重试
          </button>
        </div>
      )}
      {current && !current.error && (
        <>
          {!current.items.length ? (
            <p className="decision-queue-message" role="status">
              {offset > 0
                ? "这一页暂无记录，可以返回上一页查看。"
                : view === "action_required"
                  ? "暂时没有等你确认或跟进的事。"
                  : view === "pending"
                    ? "当前没有待确认的决策方案。"
                    : view === "follow_up"
                      ? "当前没有尚未记录结果的已确认决策。"
                      : view === "recorded"
                        ? "当前还没有已记录实际结果的决策。"
                        : "还没有决策记录。可从具体事项的依据与建议中准备方案。"}
            </p>
          ) : (
            <ul className="decision-queue-list" aria-label="决策记录">
              {current.items.map((decision) => (
                <DecisionRow
                  key={decision.id}
                  decision={decision}
                  scope={scope}
                  timezone={timezone}
                  onOpen={onOpen}
                />
              ))}
            </ul>
          )}
          {emptyInbox && (
            <button
              className="decision-queue-history"
              type="button"
              onClick={() => selectView("all")}
            >
              查看全部记录 <ArrowUpRight size={14} aria-hidden="true" />
            </button>
          )}
          {(current.total > 0 || offset > 0) && (
            <div className="decision-queue-pagination">
              <span role="status">
                {current.items.length
                  ? `${offset + 1}–${offset + current.items.length} / ${current.total} 条`
                  : `${current.total} 条记录`}
              </span>
              {(offset > 0 || current.total > PAGE_SIZE) && (
                <div>
                  <button
                    type="button"
                    aria-label="上一页决策"
                    disabled={offset === 0}
                    onClick={() => {
                      setResult(null);
                      setOffset(Math.max(0, offset - PAGE_SIZE));
                    }}
                  >
                    <ChevronLeft size={15} aria-hidden="true" /> 上一页
                  </button>
                  <button
                    type="button"
                    aria-label="下一页决策"
                    disabled={offset + PAGE_SIZE >= current.total}
                    onClick={() => {
                      setResult(null);
                      setOffset(offset + PAGE_SIZE);
                    }}
                  >
                    下一页 <ChevronRight size={15} aria-hidden="true" />
                  </button>
                </div>
              )}
            </div>
          )}
        </>
      )}
    </section>
  );
}

function DecisionRow({
  decision,
  scope,
  timezone,
  onOpen,
}: {
  decision: Decision;
  scope: Scope;
  timezone: string;
  onOpen: (id: string) => void;
}) {
  const [now, setNow] = useState(Date.now);
  const pending = decision.state === "pending";
  const confirmed = decision.state === "confirmed";
  const expiresAt =
    Date.parse(decision.context_snapshot.analysis_time) + 30 * 60 * 1000;
  const needsReview = pending && Number.isFinite(expiresAt) && now > expiresAt;

  useEffect(() => {
    setNow(Date.now());
    if (!pending || !Number.isFinite(expiresAt) || expiresAt < Date.now())
      return;
    const timer = window.setTimeout(
      () => setNow(Date.now()),
      Math.min(expiresAt - Date.now() + 1, 2_147_483_647),
    );
    return () => window.clearTimeout(timer);
  }, [pending, expiresAt]);

  const status = pending
    ? scope === "mine"
      ? "等你确认"
      : "待确认"
    : confirmed
      ? decision.outcome_count > 0
        ? "已有结果"
        : "待跟进"
      : "状态待核实";

  return (
    <li className="decision-queue-row">
      <div className="decision-queue-content">
        <div className="decision-queue-title">
          <h3>{decision.title}</h3>
          <span
            className="decision-queue-status"
            data-pending={pending || undefined}
          >
            {status}
          </span>
        </div>
        {confirmed && decision.selected_plan && (
          <p className="decision-queue-plan">方案：{decision.selected_plan}</p>
        )}
        {(decision.follow_up || confirmed) && (
          <p className="decision-queue-follow-up">
            {decision.follow_up
              ? `跟进安排：${decision.follow_up}`
              : "尚未记录跟进安排。"}
          </p>
        )}
        <div className="decision-queue-meta">
          <span>
            {confirmed ? "方案确认" : "方案准备"} ·{" "}
            {formatTime(
              confirmed ? decision.confirmed_at : decision.created_at,
              timezone,
            )}
          </span>
          {confirmed && (
            <span>
              {decision.follow_up_at
                ? `跟进时间 · ${formatTime(decision.follow_up_at, timezone)}`
                : "未设置跟进时间"}
            </span>
          )}
        </div>
        {confirmed && decision.outcome_count > 0 && (
          <p className="decision-queue-note">
            已记录 {decision.outcome_count} 条实际结果，不代表事项已完成。
          </p>
        )}
        {needsReview && (
          <p className="decision-queue-review">
            这份方案需要重新核对后再确认。
          </p>
        )}
      </div>
      <button
        className="decision-queue-open"
        type="button"
        aria-label={`查看决策：${decision.title}`}
        onClick={() => onOpen(decision.id)}
      >
        {needsReview ? "重新核对" : "查看"}
        <ArrowUpRight size={15} aria-hidden="true" />
      </button>
    </li>
  );
}
