"use client";

import { useEffect, useId, useState } from "react";
import {
  ArrowUpRight,
  CalendarDays,
  ChevronDown,
  FolderKanban,
  Search,
  Sparkles,
  UserRound,
  Users,
} from "lucide-react";
import {
  formatTime,
  statusLabels,
  type Department,
  type Initiative,
  type Member,
  type Work,
} from "../lib/api";
import { StatusIcon, StatusLabel } from "./status";
import { DecisionQueue } from "./decision-queue";
import "./projects.css";

type Filter = "all" | "support" | Work["lifecycle_status"];
const states: Work["lifecycle_status"][] = [
  "done",
  "in_progress",
  "planned",
  "cancelled",
];
type ProjectContext = {
  members: Member[];
  departments: Department[];
  timezone: string;
  onWork: (id: string) => void;
  onAsk?: (workId: string) => void;
};
type ProjectDecisionContext = {
  organizationId?: string;
  canDecide?: boolean;
  revision?: string;
  onDecision?: (id: string) => void;
};

function ProjectDecisions({
  organizationId,
  initiativeId,
  timezone,
  revision,
  onOpen,
}: {
  organizationId: string;
  initiativeId: string;
  timezone: string;
  revision: string;
  onOpen: (id: string) => void;
}) {
  const [open, setOpen] = useState(false);
  const contentId = useId();
  return (
    <div className="project-decisions">
      <button
        className="project-decisions-toggle"
        aria-expanded={open}
        aria-controls={contentId}
        onClick={() => setOpen(!open)}
      >
        {open ? "收起项目决策记录" : "查看项目决策记录"}
        <ChevronDown size={15} aria-hidden="true" />
      </button>
      {open && (
        <div className="project-decisions-content" id={contentId}>
          <DecisionQueue
            key={`${organizationId}:${initiativeId}`}
            organizationId={organizationId}
            timezone={timezone}
            revision={revision}
            onOpen={onOpen}
            scope="project"
            initiativeId={initiativeId}
          />
        </div>
      )}
    </div>
  );
}

function needsSupport(work: Work) {
  return (
    work.source_authority === "native" &&
    work.needs_support &&
    work.lifecycle_status !== "done" &&
    work.lifecycle_status !== "cancelled"
  );
}

function ownerName(id: string | null | undefined, members: Member[]) {
  return !id
    ? "未分配负责人"
    : members.find((member) => member.id === id)?.name || "负责人信息不可见";
}

function WorkRows({ works, ...context }: ProjectContext & { works: Work[] }) {
  return (
    <div className="project-work-list">
      {works.map((work) => (
        <div className="project-work" key={work.id}>
          <button
            className="project-work-open"
            onClick={() => context.onWork(work.id)}
          >
            <span
              className="project-work-icon"
              data-status={work.lifecycle_status}
            >
              <StatusIcon status={work.lifecycle_status} size={18} />
            </span>
            <span className="project-work-body">
              <strong>{work.title}</strong>
              <span className="project-work-meta">
                <span>{ownerName(work.owner_id, context.members)}</span>
                <span>
                  {context.departments.find((d) => d.id === work.department_id)
                    ?.name || "部门信息不可见"}
                </span>
                <span>
                  {work.due_at
                    ? `截止 ${formatTime(work.due_at, context.timezone)}`
                    : "未设截止时间"}
                </span>
              </span>
            </span>
            <span className="project-work-state">
              <StatusLabel status={work.lifecycle_status} />
              {needsSupport(work) && <StatusLabel status="support" />}
            </span>
            <ArrowUpRight size={15} aria-hidden="true" />
          </button>
          {context.onAsk && (
            <button
              className="project-work-ask"
              aria-label={`询问 ${work.title}`}
              title="结合这项工作的依据询问 coRoof"
              onClick={() => context.onAsk?.(work.id)}
            >
              <Sparkles size={15} aria-hidden="true" />
              <span>询问</span>
            </button>
          )}
        </div>
      ))}
    </div>
  );
}

function ProjectCard({
  initiative,
  works,
  initiallyOpen,
  selected,
  organizationId,
  canDecide,
  revision,
  onDecision,
  ...context
}: ProjectContext &
  ProjectDecisionContext & {
    initiative: Initiative;
    works: Work[];
    initiallyOpen: boolean;
    selected: boolean;
  }) {
  const [open, setOpen] = useState(initiallyOpen);
  const [filter, setFilter] = useState<Filter>("all");
  const bodyId = useId();
  useEffect(() => {
    if (selected) {
      setOpen(true);
      setFilter("all");
    }
  }, [selected]);
  const counts = Object.fromEntries(
    states.map((status) => [
      status,
      works.filter((work) => work.lifecycle_status === status).length,
    ]),
  ) as Record<Work["lifecycle_status"], number>;
  const support = works.filter(needsSupport).length;
  const participantIds = [
    ...new Set(works.map((w) => w.owner_id).filter(Boolean)),
  ];
  const participants = context.members.filter((member) =>
    participantIds.includes(member.id),
  );
  const departmentIds = [...new Set(works.map((work) => work.department_id))];
  const departmentNames = departmentIds.map(
    (id) =>
      context.departments.find((d) => d.id === id)?.name || "部门信息不可见",
  );
  const latest = [...works].sort(
    (a, b) => Date.parse(b.updated_at) - Date.parse(a.updated_at),
  )[0]?.updated_at;
  const filtered = works.filter((work) =>
    filter === "all"
      ? true
      : filter === "support"
        ? needsSupport(work)
        : work.lifecycle_status === filter,
  );
  return (
    <article className="project-card" aria-label={initiative.title}>
      <div className="project-card-heading">
        <span className="project-mark" aria-hidden="true">
          <FolderKanban size={23} />
        </span>
        <div className="project-title">
          <span className="project-scope">
            {initiative.department_id
              ? context.departments.find(
                  (d) => d.id === initiative.department_id,
                )?.name || "部门信息不可见"
              : "企业项目"}
          </span>
          <h2>{initiative.title}</h2>
        </div>
        <StatusLabel status={initiative.status} />
      </div>
      <p className="project-goal">{initiative.goal || "项目目标尚未记录。"}</p>
      <div className="project-facts">
        <span>
          <UserRound size={14} aria-hidden="true" />
          {ownerName(initiative.owner_id, context.members)}
        </span>
        <span>
          <CalendarDays size={14} aria-hidden="true" />
          {initiative.due_at
            ? `项目截止 ${formatTime(initiative.due_at, context.timezone)}`
            : "项目未设截止时间"}
        </span>
        {support > 0 && (
          <StatusLabel status="support">{support} 项需要支持</StatusLabel>
        )}
      </div>
      {works.length ? (
        <>
          <div className="project-distribution-heading">
            <span>已记录的事项</span>
            <strong>{works.length} 项</strong>
          </div>
          <div
            className="project-distribution"
            role="img"
            aria-label={`事项状态分布：${states.map((s) => `${statusLabels[s]} ${counts[s]} 项`).join("，")}`}
          >
            {states.map((status) =>
              counts[status] ? (
                <span
                  key={status}
                  data-status={status}
                  style={{ flexGrow: counts[status] }}
                />
              ) : null,
            )}
          </div>
          <div className="project-legend" aria-hidden="true">
            {states.map((status) => (
              <span key={status}>
                <i data-status={status} />
                {statusLabels[status]} <b>{counts[status]}</b>
              </span>
            ))}
          </div>
          <div className="project-team">
            <Users size={15} aria-hidden="true" />
            <div>
              <p>{departmentNames.join(" · ")}</p>
              <span>
                事项负责人：
                {participants.map((member) => member.name).join("、") ||
                  (participantIds.length ? "信息不可见" : "尚未分配")}
                {participants.length > 0 &&
                participants.length < participantIds.length
                  ? " · 部分人员信息不可见"
                  : ""}
                {works.some((work) => !work.owner_id)
                  ? " · 有事项尚未分配"
                  : ""}
              </span>
            </div>
          </div>
        </>
      ) : (
        <p className="project-unknown">
          当前权限内暂无事项记录，项目执行情况未知。
        </p>
      )}
      <div className="project-card-footer">
        <small>
          {latest
            ? `最近工作记录 ${formatTime(latest, context.timezone)}`
            : "尚无工作记录时间"}
        </small>
        <button
          className="project-expand"
          aria-expanded={open}
          aria-controls={bodyId}
          aria-label={`${open ? "收起" : "展开"}${initiative.title}的事项`}
          onClick={() => setOpen(!open)}
        >
          {open ? "收起事项" : "查看事项"}
          <ChevronDown size={15} aria-hidden="true" />
        </button>
      </div>
      {open && (
        <div className="project-detail" id={bodyId}>
          <div className="project-detail-heading">
            <h3>事项明细</h3>
            <label className="project-filter">
              <span className="project-sr-only">
                {initiative.title}的事项筛选
              </span>
              <select
                value={filter}
                onChange={(e) => setFilter(e.target.value as Filter)}
              >
                <option value="all">全部事项</option>
                <option value="support">需要支持</option>
                {states.map((status) => (
                  <option key={status} value={status}>
                    {statusLabels[status]}
                  </option>
                ))}
              </select>
            </label>
          </div>
          {filtered.length ? (
            <WorkRows works={filtered} {...context} />
          ) : (
            <p className="project-filter-empty">
              {works.length ? "当前筛选下没有事项。" : "当前权限内暂无事项。"}
            </p>
          )}
          {canDecide &&
            organizationId === initiative.organization_id &&
            onDecision && (
              <ProjectDecisions
                key={`${organizationId}:${initiative.id}`}
                organizationId={organizationId}
                initiativeId={initiative.id}
                timezone={context.timezone}
                revision={revision || ""}
                onOpen={onDecision}
              />
            )}
        </div>
      )}
    </article>
  );
}

export function Projects({
  initiatives,
  works,
  initialProjectId,
  ...context
}: ProjectContext &
  ProjectDecisionContext & {
    initiatives: Initiative[];
    works: Work[];
    initialProjectId?: string;
  }) {
  const [query, setQuery] = useState("");
  const [supportOnly, setSupportOnly] = useState(false);
  useEffect(() => {
    setQuery("");
    setSupportOnly(false);
  }, [initialProjectId]);
  const selectedId = initiatives.some(
    (project) => project.id === initialProjectId,
  )
    ? initialProjectId
    : undefined;
  const visible = initiatives
    .filter((initiative) => {
      const matchesText = `${initiative.title} ${initiative.goal || ""}`
        .toLocaleLowerCase()
        .includes(query.trim().toLocaleLowerCase());
      return (
        matchesText &&
        (!supportOnly ||
          works.some(
            (work) =>
              work.organization_id === initiative.organization_id &&
              work.initiative_id === initiative.id &&
              needsSupport(work),
          ))
      );
    })
    .sort((a, b) => Number(b.id === selectedId) - Number(a.id === selectedId));
  const independent = works.filter((work) => !work.initiative_id);
  const other = works.filter(
    (work) =>
      work.initiative_id &&
      !initiatives.some(
        (i) =>
          i.id === work.initiative_id &&
          i.organization_id === work.organization_id,
      ),
  );
  return (
    <section className="projects" aria-label="项目与事项">
      <div className="projects-toolbar">
        <label className="project-search">
          <Search size={17} aria-hidden="true" />
          <input
            aria-label="查找项目"
            type="search"
            placeholder="查找项目或目标"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
          />
        </label>
        <button
          className="project-support-toggle"
          aria-pressed={supportOnly}
          onClick={() => setSupportOnly(!supportOnly)}
        >
          只看需要支持的项目
        </button>
      </div>
      <p className="projects-scope-note">
        仅汇总当前获授权的事项 · 状态分布不代表项目整体完成度
      </p>
      <div className="project-cards">
        {visible.map((initiative, index) => (
          <ProjectCard
            key={`${initiative.organization_id}:${initiative.id}`}
            initiative={initiative}
            works={works.filter(
              (work) =>
                work.organization_id === initiative.organization_id &&
                work.initiative_id === initiative.id,
            )}
            initiallyOpen={
              selectedId ? initiative.id === selectedId : index === 0
            }
            selected={initiative.id === selectedId}
            {...context}
          />
        ))}
      </div>
      {!visible.length && (
        <div className="projects-empty">
          <FolderKanban size={27} aria-hidden="true" />
          <h2>
            {initiatives.length ? "没有符合筛选的项目" : "项目从清晰的目标开始"}
          </h2>
          <p>
            {initiatives.length
              ? "调整项目名称或关闭支持需求筛选。"
              : "当前权限内暂无项目。已记录的独立事项会保留在下方。"}
          </p>
          {(query || supportOnly) && (
            <button
              onClick={() => {
                setQuery("");
                setSupportOnly(false);
              }}
            >
              清除筛选
            </button>
          )}
        </div>
      )}
      {[
        { title: "独立事项", items: independent },
        { title: "其他已授权事项", items: other },
      ].map(
        ({ title, items }) =>
          items.length > 0 && (
            <section
              className="project-card project-independent"
              key={title}
              aria-label={title}
            >
              <h2>
                {title} <span>{items.length}</span>
              </h2>
              <p className="muted">
                {title === "独立事项"
                  ? "尚未归入项目的工作，也有清晰的负责人和进展。"
                  : "这些事项已获授权，关联项目的信息当前不可见。"}
              </p>
              <WorkRows works={items} {...context} />
            </section>
          ),
      )}
    </section>
  );
}
