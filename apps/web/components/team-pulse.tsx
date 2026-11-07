"use client";
import { useEffect, useId, useState } from "react";
import { ArrowUpRight, MessageSquareText } from "lucide-react";
import {
  api,
  unwrap,
  formatTime,
  type Work,
  type Member,
  type Initiative,
  type Evidence,
} from "../lib/api";

const actions: Record<string, string> = {
  "work.created": "建立事项",
  "work.updated": "确认进展",
  "update.confirmed": "确认进展",
  "work.assigned": "调整分工",
  "decision.confirmed": "确认方案",
  "decision.outcome": "记录实际结果",
  "source.synced": "同步来源记录",
};
export function TeamPulse({
  organizationId,
  works,
  members,
  initiatives,
  timezone,
  revision,
  onWork,
  compact = false,
  title = "团队协作动态",
  description = "跟随确认记录，了解同事的进展与交接。",
}: {
  organizationId: string;
  works: Work[];
  members: Member[];
  initiatives: Initiative[];
  timezone: string;
  revision: string;
  onWork: (id: string) => void;
  compact?: boolean;
  title?: string;
  description?: string;
}) {
  const [expanded, setExpanded] = useState(false);
  const timelineId = useId();
  useEffect(() => {
    setExpanded(false);
  }, [organizationId, compact]);
  const selected = works
    .filter((work) => work.organization_id === organizationId)
    .sort((a, b) => b.updated_at.localeCompare(a.updated_at))
    .slice(0, 6);
  const ids = selected.map((w) => w.id).join(",");
  const [data, setData] = useState<{
    scope: string;
    events: Evidence[];
    failed: boolean;
  } | null>(null);
  const scope = `${organizationId}:${ids}:${revision}`;
  useEffect(() => {
    let current = true;
    const workIds = ids ? ids.split(",") : [];
    void Promise.allSettled(
      workIds.map((work_id) =>
        api(organizationId)
          .GET("/api/v1/work-items/{work_id}/events", {
            params: {
              header: { "x-organization-id": organizationId },
              path: { work_id },
              query: { offset: 0, limit: 3 },
            },
          })
          .then(unwrap),
      ),
    ).then((results) => {
      if (!current) return;
      const failed = results.some((r) => r.status === "rejected");
      // Failed/revoked reads never leave cached event content on screen.
      const events = results.flatMap((r) =>
        r.status === "fulfilled" ? r.value.items : [],
      );
      setData({
        scope,
        failed,
        events: events
          .filter(
            (event) =>
              event.organization_id === organizationId &&
              workIds.includes(event.work_item_id),
          )
          .sort((a, b) => b.recorded_at.localeCompare(a.recorded_at))
          .slice(0, 6),
      });
    });
    return () => {
      current = false;
    };
  }, [organizationId, ids, revision, scope]);
  const current = data?.scope === scope ? data : null;
  return (
    <section className="panel team-pulse" aria-label={title}>
      <div className="section-line">
        <div>
          <h3>
            <MessageSquareText size={17} /> {title}
          </h3>
          <p className="muted">{description}</p>
        </div>
        <span className="pulse-label">事实流</span>
      </div>
      {!current ? (
        <p role="status" className="muted">
          正在读取协作记录…
        </p>
      ) : (
        <>
          {current.failed && (
            <p role="status" className="muted">
              部分记录暂时不可用，下一次同步时重试。
            </p>
          )}
          {!current.events.length && (
            <p className="muted">
              暂无可展示的确认记录；草稿不会显示为团队进展。
            </p>
          )}
          <ol className="team-timeline" id={timelineId}>
            {current.events
              .slice(0, compact && !expanded ? 3 : 6)
              .map((event) => {
                const work = selected.find(
                  (w) =>
                    w.id === event.work_item_id &&
                    w.organization_id === event.organization_id,
                );
                if (!work) return null;
                const actor = members.find(
                  (m) =>
                    m.id === event.actor_id &&
                    m.organization_id === organizationId,
                );
                const project = initiatives.find(
                  (i) =>
                    i.id === work.initiative_id &&
                    i.organization_id === organizationId,
                );
                const confirmed = event.event_payload.confirmed;
                const summary =
                  confirmed &&
                  typeof confirmed === "object" &&
                  "summary" in confirmed &&
                  typeof confirmed.summary === "string"
                    ? confirmed.summary
                    : null;
                return (
                  <li key={event.id}>
                    <span className="activity-avatar" aria-hidden="true">
                      {actor?.name.slice(0, 1) || "·"}
                    </span>
                    <div>
                      <div className="activity-byline">
                        <strong>{actor?.name || "记录作者"}</strong>
                        <span>{actions[event.event_type] || "追加记录"}</span>
                        <time dateTime={event.recorded_at}>
                          {formatTime(event.recorded_at, timezone)}
                        </time>
                      </div>
                      <button
                        className="activity-work"
                        onClick={() => onWork(work.id)}
                      >
                        {work.title}
                        <ArrowUpRight size={14} />
                      </button>
                      {summary && <p className="activity-excerpt">{summary}</p>}
                      <small>
                        {work.initiative_id
                          ? project?.title || "项目信息当前不可见"
                          : "独立事项"}{" "}
                        · 可打开查看原始依据
                      </small>
                    </div>
                  </li>
                );
              })}
          </ol>
          {compact && current.events.length > 3 && (
            <button
              className="plain"
              aria-expanded={expanded}
              aria-controls={timelineId}
              onClick={() => setExpanded(!expanded)}
            >
              {expanded
                ? "收起动态"
                : `展开更多动态（${current.events.length - 3} 条）`}
            </button>
          )}
        </>
      )}
      <p className="fine-print">
        当前授权范围内，最近 {selected.length} 项工作的部分记录。
      </p>
    </section>
  );
}
