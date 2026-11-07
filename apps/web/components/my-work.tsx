"use client";

import { useId, useState } from "react";
import {
  ArrowUpRight,
  CalendarDays,
  FolderKanban,
  MessageCircle,
  Search,
  SquarePen,
} from "lucide-react";
import {
  formatTime,
  type Department,
  type Initiative,
  type Member,
  type Work,
} from "../lib/api";
import { StatusLabel } from "./status";
import { useArrangements } from "./work-arrangements";
import "./my-work.css";

type Filter = "active" | "in_progress" | "planned" | "support" | "ended";
const filters: { id: Filter; label: string }[] = [
  { id: "active", label: "待推进" },
  { id: "in_progress", label: "进行中" },
  { id: "planned", label: "未开始" },
  { id: "support", label: "需要支持" },
  { id: "ended", label: "已结束" },
];
const isActive = (work: Work) =>
  work.lifecycle_status === "planned" ||
  work.lifecycle_status === "in_progress";
const needsSupport = (work: Work) =>
  isActive(work) && work.source_authority === "native" && work.needs_support;
function dueTime(work: Work) {
  const time =
    work.source_authority === "native" && work.due_at
      ? Date.parse(work.due_at)
      : NaN;
  return Number.isFinite(time) ? time : Infinity;
}

export function MyWork({
  works,
  initiatives,
  departments,
  members,
  timezone,
  memberId,
  organizationId,
  revision = "",
  onWork,
  onAsk,
}: {
  /** The parent supplies only the current member's server-authorized works. */
  works: Work[];
  initiatives: Initiative[];
  departments: Department[];
  members: Member[];
  timezone: string;
  memberId?: string;
  organizationId?: string;
  revision?: string;
  onWork: (
    id: string,
    intent?: "update" | "support" | "feedback",
    decisionId?: string,
  ) => void;
  onAsk: (id: string, question?: string) => void;
}) {
  const [filter, setFilter] = useState<Filter>("active");
  const [search, setSearch] = useState("");
  const searchId = useId();
  const itemPrefix = useId();
  const arrangements = useArrangements(organizationId, revision);
  const now = Date.now();
  const member = members.find((item) => item.id === memberId);
  const own = works.filter(
    (work) =>
      (!memberId || work.owner_id === memberId) &&
      (!organizationId || work.organization_id === organizationId) &&
      (!member || work.organization_id === member.organization_id),
  );
  const projectFor = (work: Work) =>
    initiatives.find(
      (item) =>
        item.id === work.initiative_id &&
        item.organization_id === work.organization_id,
    );
  const departmentFor = (work: Work) =>
    departments.find(
      (item) =>
        item.id === work.department_id &&
        item.organization_id === work.organization_id,
    );
  const matches = (work: Work, target: Filter) =>
    target === "active"
      ? isActive(work)
      : target === "support"
        ? needsSupport(work)
        : target === "ended"
          ? !isActive(work)
          : work.lifecycle_status === target;
  const arrangementFor = (work: Work) =>
    arrangements.items.find((item) => item.work_item_id === work.id);
  const activeOwn = own.filter(isActive);
  const supportedCount = activeOwn.filter(needsSupport).length;
  const arrangedCount = activeOwn.filter(
    (work) => !!arrangementFor(work),
  ).length;
  const needle = search.trim().toLocaleLowerCase();
  const shown = own
    .filter(
      (work) =>
        matches(work, filter) &&
        (!needle ||
          [
            work.title,
            work.description,
            projectFor(work)?.title,
            departmentFor(work)?.name,
          ]
            .filter(Boolean)
            .join(" ")
            .toLocaleLowerCase()
            .includes(needle)),
    )
    .sort((a, b) => {
      if (filter === "ended")
        return (
          Date.parse(b.updated_at) - Date.parse(a.updated_at) ||
          a.id.localeCompare(b.id)
        );
      return (
        Number(needsSupport(b)) - Number(needsSupport(a)) ||
        Number(dueTime(b) < now) - Number(dueTime(a) < now) ||
        (dueTime(a) === dueTime(b) ? 0 : dueTime(a) - dueTime(b)) ||
        Date.parse(b.updated_at) - Date.parse(a.updated_at) ||
        a.id.localeCompare(b.id)
      );
    });

  const first = filter === "active" && !needle ? shown[0] : undefined;
  const remaining = first ? shown.slice(1) : shown;
  const renderWork = (work: Work, featured = false) => {
    const project = projectFor(work);
    const department = departmentFor(work);
    const owner = members.find(
      (item) =>
        item.id === work.owner_id &&
        item.organization_id === work.organization_id,
    );
    const active = isActive(work);
    const external = work.source_authority === "external";
    const editable = active && !external;
    const support = needsSupport(work);
    const overdue = active && dueTime(work) < now;
    const titleId = `${itemPrefix}-${work.id}`;
    const arrangement = arrangementFor(work);
    const reason = support
      ? "这项工作已记录支持需求，先核实还缺什么、需要谁协作。"
      : overdue
        ? "已过记录的截止时间，先核实实际进展。"
        : arrangement
          ? "这项工作已有确认安排，可以反馈落实情况。"
          : external
            ? "进展由来源系统维护，可以先查看同步记录。"
            : work.due_at
              ? "按已记录的截止时间，这项工作排在前面。"
              : "还没有截止时间，可以先确认下一步并汇报进展。";
    return (
      <article
        className={`my-work-task ${featured ? "my-work-priority" : "my-work-compact"}`}
        key={work.id}
        aria-labelledby={titleId}
        data-support={support || undefined}
      >
        {featured && (
          <div className="my-work-priority-intro">
            <span>先从这件事开始</span>
            <p>{reason}</p>
          </div>
        )}
        <div className="my-work-task-body">
          <div className="my-work-task-main">
            <div className="my-work-task-title">
              <h3 id={titleId}>
                <button
                  className="my-work-title"
                  onClick={() => onWork(work.id)}
                >
                  {work.title}
                  <ArrowUpRight size={15} aria-hidden="true" />
                </button>
              </h3>
              <StatusLabel status={work.lifecycle_status} />
              {support ? (
                <StatusLabel status="support" />
              ) : (
                active && (
                  <span className="my-work-support-note">
                    {external ? "支持情况未同步" : "未记录支持需求"}
                  </span>
                )
              )}
            </div>
            <p className="my-work-task-context">
              <span className="my-work-owner">
                负责人{" "}
                {owner?.name || (work.owner_id ? "资料不可见" : "未分配")}
              </span>
              <span>
                <FolderKanban size={14} aria-hidden="true" />
                {project?.title ||
                  (work.initiative_id ? "项目资料不可见" : "未关联项目")}
              </span>
              <span>{department?.name || "部门资料不可见"}</span>
            </p>
            <p
              className="my-work-task-date"
              data-overdue={overdue || undefined}
            >
              <CalendarDays size={14} aria-hidden="true" />
              <span>
                {external
                  ? "截止日期未同步 · 未知"
                  : work.due_at
                    ? `截止 ${formatTime(work.due_at, timezone)}`
                    : "未设置截止时间"}
              </span>
              {overdue && <strong>已过记录截止 · 实际交付待核实</strong>}
            </p>
            {arrangement && (
              <div className="my-work-arrangement">
                <span>已确认安排</span>
                <p>{arrangement.selected_plan}</p>
              </div>
            )}
          </div>
          <div className="my-work-task-actions">
            {editable ? (
              <button
                className="my-work-report"
                onClick={() =>
                  arrangement
                    ? onWork(work.id, "feedback", arrangement.id)
                    : onWork(work.id, "update")
                }
              >
                <SquarePen size={16} aria-hidden="true" />
                {arrangement ? "反馈安排" : "汇报进展"}
              </button>
            ) : (
              <button onClick={() => onWork(work.id)}>查看记录</button>
            )}
            <details className="my-work-more">
              <summary>更多操作</summary>
              <div className="my-work-more-content">
                <p>记录更新 {formatTime(work.updated_at, timezone)}</p>
                {arrangement?.latest_feedback && (
                  <p>
                    最近反馈{" "}
                    {formatTime(
                      arrangement.latest_feedback.recorded_at,
                      timezone,
                    )}
                  </p>
                )}
                {editable && (
                  <>
                    {arrangement && (
                      <button onClick={() => onWork(work.id, "update")}>
                        汇报其他进展
                      </button>
                    )}
                    <button onClick={() => onWork(work.id, "support")}>
                      {support ? "补充支持需求" : "需要支持"}
                    </button>
                  </>
                )}
                <button
                  onClick={() =>
                    onAsk(
                      work.id,
                      `请根据「${work.title}」的已记录进展，说明我可以核实的下一步与缺少的信息，不代替我确认进展。`,
                    )
                  }
                >
                  <MessageCircle size={14} aria-hidden="true" />
                  询问这项工作
                </button>
              </div>
            </details>
          </div>
        </div>
        {!editable && (
          <p className="my-work-readonly">
            {external
              ? "外部来源 · 只读；请在来源系统更新工作。"
              : "此事项已结束，可查看确认过的进展与来源。"}
          </p>
        )}
      </article>
    );
  };

  return (
    <section
      className="my-work-board my-work-focus-board"
      aria-label="我的工作清单"
    >
      <header className="my-work-start-heading">
        <h2>{activeOwn.length ? "把眼前的事往前推一步" : "你的工作"}</h2>
        <p className="my-work-summary" role="status">
          {own.length ? (
            <>
              <strong>{activeOwn.length}</strong> 项待推进，
              <strong>{supportedCount}</strong> 项已记录支持需求
              {organizationId &&
                !arrangements.loading &&
                !arrangements.error && (
                  <>
                    ，<strong>{arrangedCount}</strong> 项有已确认安排
                  </>
                )}
              。
            </>
          ) : (
            "分配给你的工作会出现在这里。"
          )}
        </p>
        {arrangements.loading && <small>正在核对已确认安排…</small>}
        {arrangements.error && (
          <p className="my-work-arrangement-error" role="alert">
            安排暂未读取，可重试或打开事项查看。
            <button onClick={arrangements.retry}>重新读取安排</button>
          </p>
        )}
      </header>
      {first && renderWork(first, true)}
      {own.length > 0 && (
        <div className="my-work-rest-heading">
          <div className="my-work-rest-label">
            <h2>
              {first
                ? "其余工作"
                : filter === "ended"
                  ? "已结束的记录"
                  : "工作清单"}
            </h2>
            <span>
              {remaining.length} 项{needle ? "匹配工作" : ""}
            </span>
          </div>
          <div className="my-work-search">
            <Search size={16} aria-hidden="true" />
            <label htmlFor={searchId}>搜索我的工作</label>
            <input
              id={searchId}
              type="search"
              placeholder="搜索工作或项目"
              value={search}
              onChange={(event) => setSearch(event.target.value)}
            />
          </div>
          <div
            className="my-work-filters"
            role="group"
            aria-label="筛选我的工作"
          >
            {filters
              .filter(
                ({ id }) =>
                  id === filter ||
                  (own.some((work) => matches(work, id)) &&
                    (id === "active" ||
                      id === "ended" ||
                      own.filter((work) => matches(work, id)).length !==
                        activeOwn.length)),
              )
              .map(({ id, label }) => (
                <button
                  key={id}
                  aria-pressed={filter === id}
                  onClick={() => setFilter(id)}
                >
                  {label}{" "}
                  <span>{own.filter((work) => matches(work, id)).length}</span>
                </button>
              ))}
          </div>
        </div>
      )}
      {remaining.length ? (
        <div className="my-work-compact-list">
          {remaining.map((work) => renderWork(work))}
        </div>
      ) : first ? (
        <p className="my-work-rest-empty">
          其余暂无待推进工作。已结束的记录可通过筛选查看。
        </p>
      ) : (
        <div className="my-work-empty">
          <h3>
            {search
              ? "没有匹配的工作"
              : filter === "ended"
                ? "还没有已结束的工作"
                : filter === "support"
                  ? "当前没有已记录的支持需求"
                  : "这个范围里还没有工作"}
          </h3>
          <p>
            {search
              ? "试试其他关键词，或清空搜索查看当前范围。"
              : own.length
                ? "可以切换筛选查看其他已分配工作；未记录的情况仍然未知。"
                : "这里只显示已分配给你的事项。工作分配后，可以在这里汇报进展。"}
          </p>
          {search && <button onClick={() => setSearch("")}>清空搜索</button>}
        </div>
      )}
    </section>
  );
}
