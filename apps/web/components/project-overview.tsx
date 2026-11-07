"use client";

import {
  ArrowUpRight,
  CalendarDays,
  FolderKanban,
  Sparkles,
  UserRound,
} from "lucide-react";
import {
  formatTime,
  statusLabels,
  type Department,
  type Initiative,
  type Member,
  type Work,
} from "../lib/api";
import { StatusLabel } from "./status";
import "./project-overview.css";

const states: Work["lifecycle_status"][] = [
  "done",
  "in_progress",
  "planned",
  "cancelled",
];
const unfinished = (status: Work["lifecycle_status"]) =>
  status === "planned" || status === "in_progress";
const deadline = (date: string | null | undefined) =>
  date ? Date.parse(date) : Number.POSITIVE_INFINITY;

export function ProjectOverview({
  initiatives,
  works,
  members,
  departments,
  timezone,
  onProject,
  onWork,
  onAsk,
  onAll,
}: {
  initiatives: Initiative[];
  works: Work[];
  members: Member[];
  departments: Department[];
  timezone: string;
  onProject: (id: string) => void;
  onWork: (id: string) => void;
  onAsk?: (workId: string) => void;
  onAll: () => void;
}) {
  const projects = initiatives
    .filter((project) => unfinished(project.status))
    .map((project) => {
      const items = works.filter(
        (work) =>
          work.organization_id === project.organization_id &&
          work.initiative_id === project.id,
      );
      const support = items
        .filter(
          (work) =>
            work.source_authority === "native" &&
            work.needs_support &&
            unfinished(work.lifecycle_status),
        )
        .sort(
          (a, b) =>
            deadline(a.due_at) - deadline(b.due_at) ||
            a.title.localeCompare(b.title, "zh-CN") ||
            a.id.localeCompare(b.id),
        );
      return { project, items, support };
    })
    .sort(
      (a, b) =>
        Number(b.support.length > 0) - Number(a.support.length > 0) ||
        deadline(a.project.due_at) - deadline(b.project.due_at) ||
        a.project.title.localeCompare(b.project.title, "zh-CN") ||
        a.project.id.localeCompare(b.project.id),
    )
    .slice(0, 3);

  return (
    <section className="project-overview" aria-label="项目进展">
      <div className="project-overview-heading">
        <div>
          <h2>
            <FolderKanban size={18} aria-hidden="true" />
            项目进展
          </h2>
          <p title="支持需求优先，其次按项目截止时间；最多显示 3 个未结束项目。">
            看目标、负责人和已记录的进展。
          </p>
        </div>
        <button className="plain" onClick={onAll}>
          查看全部项目 <ArrowUpRight size={15} aria-hidden="true" />
        </button>
      </div>
      {projects.length ? (
        <div className="project-overview-grid">
          {projects.map(({ project, items, support }) => {
            const owner = members.find(
              (member) =>
                member.organization_id === project.organization_id &&
                member.id === project.owner_id,
            );
            const department = departments.find(
              (department) =>
                department.organization_id === project.organization_id &&
                department.id === project.department_id,
            );
            const firstSupport = support[0];
            return (
              <article
                className="project-overview-card"
                aria-label={project.title}
                key={`${project.organization_id}:${project.id}`}
              >
                <div className="project-overview-title">
                  <h3>
                    <button
                      className="plain"
                      aria-label={`查看项目：${project.title}`}
                      onClick={() => onProject(project.id)}
                    >
                      {project.title}
                      <ArrowUpRight size={15} aria-hidden="true" />
                    </button>
                  </h3>
                  <StatusLabel status={project.status} />
                </div>
                <p
                  className="project-overview-goal"
                  title={project.goal || undefined}
                >
                  {project.goal || "项目目标尚未记录。"}
                </p>
                <div className="project-overview-facts">
                  <span>
                    <UserRound size={13} aria-hidden="true" />
                    {project.owner_id
                      ? owner?.name || "负责人信息不可见"
                      : "未分配负责人"}
                  </span>
                  <span>
                    {project.department_id
                      ? department?.name || "部门信息不可见"
                      : "企业项目"}
                  </span>
                  <span>
                    <CalendarDays size={13} aria-hidden="true" />
                    {project.due_at
                      ? `项目截止 ${formatTime(project.due_at, timezone)}`
                      : "项目未设截止时间"}
                  </span>
                </div>
                {items.length ? (
                  <p className="project-overview-progress">
                    已完成{" "}
                    {
                      items.filter((work) => work.lifecycle_status === "done")
                        .length
                    }{" "}
                    项
                    <span>
                      {" "}
                      · 未完成{" "}
                      {
                        items.filter((work) =>
                          unfinished(work.lifecycle_status),
                        ).length
                      }{" "}
                      项
                    </span>
                    {items.some(
                      (work) => work.lifecycle_status === "cancelled",
                    ) && (
                      <span>
                        {" "}
                        · 已取消{" "}
                        {
                          items.filter(
                            (work) => work.lifecycle_status === "cancelled",
                          ).length
                        }{" "}
                        项
                      </span>
                    )}
                    {support.length > 0 && (
                      <strong> · {support.length} 项需要支持</strong>
                    )}
                  </p>
                ) : (
                  <p className="project-overview-unknown">
                    当前权限内暂无事项，执行情况未知。
                  </p>
                )}
                {items.length > 0 && (
                  <details className="project-overview-details">
                    <summary>展开详情</summary>
                    <dl
                      className="project-overview-counts"
                      aria-label="已授权事项状态计数"
                    >
                      {states.map((status) => (
                        <div key={status} data-status={status}>
                          <dt>{statusLabels[status]}</dt>
                          <dd>
                            {
                              items.filter(
                                (work) => work.lifecycle_status === status,
                              ).length
                            }
                          </dd>
                        </div>
                      ))}
                    </dl>
                    {firstSupport && (
                      <div className="project-overview-support">
                        <span>{support.length} 项未结束事项需要支持</span>
                        <div>
                          <button
                            className="plain"
                            onClick={() => onWork(firstSupport.id)}
                            aria-label={`查看支持事项：${firstSupport.title}`}
                          >
                            <span>{firstSupport.title}</span>
                            <ArrowUpRight size={14} aria-hidden="true" />
                          </button>
                          {onAsk && (
                            <button
                              className="project-overview-ask"
                              aria-label={`询问 ${firstSupport.title}`}
                              onClick={() => onAsk(firstSupport.id)}
                            >
                              <Sparkles size={14} aria-hidden="true" />
                            </button>
                          )}
                        </div>
                        {support.length > 1 && (
                          <small>
                            另有 {support.length - 1} 项，可在项目中查看
                          </small>
                        )}
                      </div>
                    )}
                  </details>
                )}
              </article>
            );
          })}
        </div>
      ) : (
        <p className="project-overview-empty">
          {initiatives.length
            ? "当前权限内没有未结束的项目，可查看全部项目核对历史记录。"
            : "当前权限内暂无项目。独立事项仍可在“项目与事项”中查看。"}
        </p>
      )}
      {projects.length > 0 && (
        <p className="project-overview-scope">
          仅汇总当前获授权的事项；事项数量不代表项目整体完成度。
        </p>
      )}
    </section>
  );
}
