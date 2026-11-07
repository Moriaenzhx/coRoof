"use client";

import { useEffect, useRef, useState } from "react";
import {
  ArrowLeft,
  ArrowRight,
  BookOpen,
  Building2,
  ChevronRight,
  FolderKanban,
  LayoutGrid,
  Search,
  TriangleAlert,
  Users,
} from "lucide-react";
import {
  formatTime,
  type Department,
  type Initiative,
  type Member,
  type Work,
} from "../lib/api";
import { StatusLabel } from "./status";
import "./team-spaces.css";

type TeamSpacesProps = {
  organizationName: string;
  departments: Department[];
  members: Member[];
  works: Work[];
  initiatives: Initiative[];
  timezone: string;
  onWork: (id: string) => void;
  onMember: (id: string) => void;
  onProject: (id: string) => void;
  onKnowledge: () => void;
  onOverview: () => void;
  onManage?: () => void;
};

function isOpen(work: Work) {
  return !["done", "cancelled"].includes(work.lifecycle_status);
}

function needsSupport(work: Work) {
  return (
    isOpen(work) && work.source_authority === "native" && work.needs_support
  );
}

function orderWorks(works: Work[]) {
  return [...works].sort(
    (left, right) =>
      Number(needsSupport(right)) - Number(needsSupport(left)) ||
      (left.due_at ? Date.parse(left.due_at) : Infinity) -
        (right.due_at ? Date.parse(right.due_at) : Infinity) ||
      Date.parse(right.updated_at) - Date.parse(left.updated_at) ||
      left.id.localeCompare(right.id),
  );
}

function MemberList({
  members,
  onMember,
}: Pick<TeamSpacesProps, "members" | "onMember">) {
  return (
    <div className="team-space-members">
      {members.map((member) => (
        <button
          className="team-space-person"
          key={member.id}
          onClick={() => onMember(member.id)}
        >
          <span className="team-space-avatar" aria-hidden="true">
            {member.name.slice(0, 1)}
          </span>
          <span className="team-space-person-copy">
            <strong>{member.name}</strong>
            <small>
              {member.roles.includes("owner")
                ? "企业所有者"
                : member.roles.includes("manager")
                  ? "团队负责人"
                  : "成员"}
            </small>
          </span>
          <ChevronRight size={16} aria-hidden="true" />
        </button>
      ))}
    </div>
  );
}

export function TeamSpaces({
  organizationName,
  departments,
  members,
  works,
  initiatives,
  timezone,
  onWork,
  onMember,
  onProject,
  onKnowledge,
  onOverview,
  onManage,
}: TeamSpacesProps) {
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [view, setView] = useState<"work" | "members">("work");
  const [query, setQuery] = useState("");
  const visibleQuery = departments.length > 5 ? query.trim() : "";
  const headingRef = useRef<HTMLHeadingElement>(null);
  const directoryButtons = useRef(new Map<string, HTMLButtonElement>());
  const selected = departments.find(
    (department) => department.id === selectedId,
  );
  const activeMembers = members.filter((member) => member.status === "active");
  const unassigned = activeMembers.filter((member) => !member.department_id);
  const teamMembers = activeMembers.filter(
    (member) => member.department_id === selectedId,
  );
  const teamWorks = works.filter((work) => work.department_id === selectedId);
  const openWorks = orderWorks(teamWorks.filter(isOpen));
  const finishedWorks = orderWorks(teamWorks.filter((work) => !isOpen(work)));
  const projects = initiatives.filter((initiative) =>
    teamWorks.some((work) => work.initiative_id === initiative.id),
  );

  useEffect(() => {
    if (selectedId && !selected) setSelectedId(null);
  }, [selectedId, selected]);

  useEffect(() => {
    if (selectedId) headingRef.current?.focus();
  }, [selectedId]);

  function enterTeam(id: string) {
    setView("work");
    setSelectedId(id);
  }

  function leaveTeam() {
    const previous = selectedId;
    setSelectedId(null);
    requestAnimationFrame(() => {
      if (previous) directoryButtons.current.get(previous)?.focus();
    });
  }

  function workRows(items: Work[]) {
    return (
      <div className="team-space-work-list">
        {items.map((work) => {
          const owner = activeMembers.find(
            (member) => member.id === work.owner_id,
          );
          return (
            <button
              key={work.id}
              className="team-space-work-row"
              onClick={() => onWork(work.id)}
            >
              <span className="team-space-work-copy">
                <strong>{work.title}</strong>
                <span className="team-space-work-meta">
                  <span>
                    {owner?.name ||
                      (work.owner_id ? "负责人信息不可见" : "尚未指定负责人")}
                  </span>
                  {work.due_at && (
                    <span>截止 {formatTime(work.due_at, timezone)}</span>
                  )}
                  {work.source_authority !== "native" && <span>外部记录</span>}
                </span>
              </span>
              <StatusLabel
                status={needsSupport(work) ? "support" : work.lifecycle_status}
              />
              <ChevronRight size={17} aria-hidden="true" />
            </button>
          );
        })}
      </div>
    );
  }

  return (
    <div className="team-spaces">
      {!selected ? (
        <>
          <section className="team-space-company" aria-label="公司公共入口">
            <div className="team-space-company-name">
              <span className="team-space-company-icon" aria-hidden="true">
                <Building2 size={24} strokeWidth={1.6} />
              </span>
              <div>
                <span className="team-space-eyebrow">公司公共入口</span>
                <h2>{organizationName}</h2>
              </div>
            </div>
            <div className="team-space-company-links">
              <button onClick={onOverview}>
                <LayoutGrid size={18} aria-hidden="true" />
                查看概览
                <ArrowRight size={16} aria-hidden="true" />
              </button>
              <button onClick={onKnowledge}>
                <BookOpen size={18} aria-hidden="true" />
                企业知识库
                <ArrowRight size={16} aria-hidden="true" />
              </button>
            </div>
          </section>

          <div className="team-space-directory-heading">
            <div>
              <h2>进入团队</h2>
            </div>
            {departments.length > 5 && (
              <label className="team-space-search">
                <Search size={17} aria-hidden="true" />
                <input
                  aria-label="查找团队"
                  placeholder="查找团队"
                  value={query}
                  onChange={(event) => setQuery(event.target.value)}
                />
              </label>
            )}
          </div>

          <div className="team-space-grid">
            {departments
              .filter((department) => department.name.includes(visibleQuery))
              .map((department, index) => {
                const people = activeMembers.filter(
                  (member) => member.department_id === department.id,
                );
                const recorded = works.filter(
                  (work) => work.department_id === department.id,
                );
                const ongoing = orderWorks(recorded.filter(isOpen));
                const supportCount = ongoing.filter(needsSupport).length;
                const priority = ongoing[0];
                return (
                  <button
                    className="team-space-card"
                    key={department.id}
                    aria-label={`进入${department.name}团队`}
                    data-tone={index % 4}
                    onClick={() => enterTeam(department.id)}
                    ref={(element) => {
                      if (element)
                        directoryButtons.current.set(department.id, element);
                      else directoryButtons.current.delete(department.id);
                    }}
                  >
                    <span className="team-space-card-heading">
                      <span className="team-space-card-icon" aria-hidden="true">
                        <Users size={21} strokeWidth={1.6} />
                      </span>
                      <strong>{department.name}</strong>
                      <ArrowRight size={18} aria-hidden="true" />
                    </span>
                    <span className="team-space-card-counts">
                      <span>{ongoing.length} 项待推进</span>
                      <span>{people.length} 位成员</span>
                    </span>
                    <span
                      className="team-space-card-priority"
                      data-attention={supportCount > 0}
                    >
                      <span className="team-space-priority-label">
                        {supportCount > 0 ? (
                          <>
                            <TriangleAlert size={13} aria-hidden="true" />
                            {supportCount} 项工作需要支持
                          </>
                        ) : recorded.length ? (
                          priority ? (
                            "当前工作"
                          ) : (
                            "已记录工作均已结束"
                          )
                        ) : (
                          "尚无工作记录"
                        )}
                      </span>
                      <span className="team-space-priority-title">
                        {priority?.title ||
                          (recorded.length
                            ? "进入查看工作记录"
                            : "还不了解这个团队的工作情况")}
                      </span>
                    </span>
                    <span className="team-space-card-footer">
                      <span
                        className="team-space-avatar-stack"
                        aria-hidden="true"
                      >
                        {people.slice(0, 3).map((person) => (
                          <span className="team-space-avatar" key={person.id}>
                            {person.name.slice(0, 1)}
                          </span>
                        ))}
                        {people.length === 0 && <span>尚未添加成员</span>}
                      </span>
                      <span>
                        查看团队 <ChevronRight size={14} aria-hidden="true" />
                      </span>
                    </span>
                  </button>
                );
              })}
          </div>

          {!departments.length && (
            <div className="team-space-empty">
              <Users size={28} strokeWidth={1.5} aria-hidden="true" />
              <h3>团队从这里开始</h3>
              <p>
                目前没有可查看的团队。建立部门后，就能在这里查看工作与成员。
              </p>
              {onManage && (
                <button className="secondary" onClick={onManage}>
                  管理团队
                </button>
              )}
            </div>
          )}
          {departments.length > 5 &&
            !departments.some((department) =>
              department.name.includes(visibleQuery),
            ) && (
              <p className="team-space-empty">
                没有找到这个团队，换个名称试试。
              </p>
            )}
          {unassigned.length > 0 && (
            <details className="team-space-unassigned">
              <summary>
                <Users size={17} aria-hidden="true" />
                未归属团队的成员
                <span>{unassigned.length}</span>
                <ChevronRight size={16} aria-hidden="true" />
              </summary>
              <MemberList members={unassigned} onMember={onMember} />
            </details>
          )}
        </>
      ) : (
        <section
          className="team-space-detail"
          aria-label={`${selected.name}团队工作台`}
        >
          <button className="team-space-back" onClick={leaveTeam}>
            <ArrowLeft size={17} aria-hidden="true" />
            全部团队
          </button>
          <div className="team-space-detail-heading">
            <div>
              <h2 ref={headingRef} tabIndex={-1}>
                {selected.name}
              </h2>
              <p>
                {openWorks.length} 项待推进 · {teamMembers.length} 位成员
              </p>
            </div>
            <button className="team-space-library-link" onClick={onKnowledge}>
              <BookOpen size={18} aria-hidden="true" />
              <span>
                企业知识库<small>查看我有权看的资料</small>
              </span>
              <ArrowRight size={16} aria-hidden="true" />
            </button>
          </div>
          <nav className="team-space-tabs" aria-label="团队视图">
            <button
              aria-pressed={view === "work"}
              onClick={() => setView("work")}
            >
              工作
            </button>
            <button
              aria-pressed={view === "members"}
              onClick={() => setView("members")}
            >
              成员
            </button>
          </nav>
          {view === "work" ? (
            <>
              {openWorks.length > 0 ? (
                <section
                  className="team-space-work-section"
                  aria-label="待推进的工作"
                >
                  <div className="team-space-section-heading">
                    <h3>待推进</h3>
                    <span>需要支持的工作排在前面</span>
                  </div>
                  {workRows(openWorks)}
                </section>
              ) : (
                <div className="team-space-empty">
                  <FolderKanban
                    size={28}
                    strokeWidth={1.5}
                    aria-hidden="true"
                  />
                  <h3>
                    {teamWorks.length
                      ? "已记录的工作均已结束"
                      : "还没有工作记录"}
                  </h3>
                  <p>
                    {teamWorks.length
                      ? "可以展开下面的记录查看具体情况。"
                      : "目前还不了解这个团队正在做什么。添加工作后，进展会显示在这里。"}
                  </p>
                  {onManage && !teamWorks.length && (
                    <button className="secondary" onClick={onManage}>
                      管理团队
                    </button>
                  )}
                </div>
              )}
              {finishedWorks.length > 0 && (
                <details className="team-space-finished">
                  <summary>
                    已结束的工作 <span>{finishedWorks.length}</span>
                    <ChevronRight size={16} aria-hidden="true" />
                  </summary>
                  {workRows(finishedWorks)}
                </details>
              )}
              {projects.length > 0 && (
                <section
                  className="team-space-projects"
                  aria-label="参与的项目"
                >
                  <h3>参与的项目</h3>
                  <div>
                    {projects.map((project) => (
                      <button
                        key={project.id}
                        onClick={() => onProject(project.id)}
                      >
                        <FolderKanban size={17} aria-hidden="true" />
                        <span>{project.title}</span>
                        <ArrowRight size={15} aria-hidden="true" />
                      </button>
                    ))}
                  </div>
                </section>
              )}
            </>
          ) : teamMembers.length ? (
            <MemberList members={teamMembers} onMember={onMember} />
          ) : (
            <div className="team-space-empty">
              <Users size={28} strokeWidth={1.5} aria-hidden="true" />
              <h3>尚未添加成员</h3>
              <p>同事加入这个团队后，会显示在这里。</p>
              {onManage && (
                <button className="secondary" onClick={onManage}>
                  管理团队
                </button>
              )}
            </div>
          )}
        </section>
      )}
    </div>
  );
}
