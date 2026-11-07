"use client";

import {
  ArrowRight,
  ArrowUpRight,
  Clock3,
  Eye,
  MessageCircle,
} from "lucide-react";
import { formatTime, type Member, type Work } from "../lib/api";
import { companionContext } from "./companion-context";
import "./companion.css";

type Presence = "idle" | "loading" | "attention";

/** A coRoof identity, not an indication that a model is running. */
export function CoRoofAvatar({
  state = "idle",
  size = 64,
  decorative = false,
}: {
  state?: Presence;
  size?: number;
  decorative?: boolean;
}) {
  return (
    <svg
      className="coroof-companion-avatar"
      data-state={state}
      viewBox="0 0 80 80"
      width={size}
      height={size}
      role={decorative ? undefined : "img"}
      aria-hidden={decorative || undefined}
      aria-label={
        decorative
          ? undefined
          : `coRoof 工作伙伴：${state === "loading" ? "正在更新记录" : state === "attention" ? "有待核实事项" : "准备好一起看工作"}`
      }
    >
      <rect x="2" y="2" width="76" height="76" rx="26" fill="#f0eee7" />
      <path
        className="companion-roof"
        d="M19 36 40 19l21 17"
        fill="none"
        stroke="#17264f"
        strokeWidth="5"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
      <path
        d="M24 36v20c0 5 4 8 9 8h14c5 0 9-3 9-8V36"
        fill="#fff"
        stroke="#17264f"
        strokeWidth="3"
        strokeLinecap="round"
      />
      <g className="companion-eyes" fill="#17264f">
        <rect x="31" y="41" width="5" height="8" rx="2.5" />
        <rect x="44" y="41" width="5" height="8" rx="2.5" />
      </g>
      <path
        d={state === "attention" ? "M36 55h8" : "M35 54q5 5 10 0"}
        fill="none"
        stroke="#17264f"
        strokeWidth="2.5"
        strokeLinecap="round"
      />
      <circle
        className="companion-note"
        cx="64"
        cy="20"
        r="6"
        fill={state === "attention" ? "#b7883d" : "#d9d4c6"}
      />
    </svg>
  );
}

type WatchSummary = {
  activeCount: number;
  lastCheckedAt?: string | null;
};

export function Companion({
  works,
  members,
  timezone,
  onWork,
  onAsk,
  onWatch,
  watchSummary,
  loading = false,
  now = Date.now(),
}: {
  works: Work[];
  members: Member[];
  timezone: string;
  onWork: (id: string) => void;
  onAsk: (workId?: string, question?: string) => void;
  onWatch?: () => void;
  watchSummary?: WatchSummary;
  loading?: boolean;
  now?: number;
}) {
  const {
    active,
    support,
    overdue,
    unassigned,
    reason,
    focus,
    explanation,
    question,
  } = companionContext(works, now);
  const owner = members.find((member) => member.id === focus?.owner_id);
  const headline = loading
    ? "正在更新工作记录…"
    : support.length
      ? `${support.length} 项工作提出支持需求，一起看看。`
      : overdue.length
        ? `${overdue.length} 项工作已过记录中的截止时间。`
        : unassigned.length
          ? `${unassigned.length} 项工作还没有明确负责人。`
          : active.length
            ? "从最近一条进展，接着往前看。"
            : works.length
              ? "已有的工作已结束，下一步还待记录。"
              : "从一条真实进展开始，我陪你一起梳理。";

  return (
    <section
      className="companion-panel"
      aria-label="coRoof 工作伙伴"
      aria-busy={loading}
    >
      <div className="companion-heading">
        <CoRoofAvatar
          state={
            loading ? "loading" : reason !== "latest" ? "attention" : "idle"
          }
          decorative
        />
        <div className="companion-intro">
          <span className="companion-name">coRoof · 工作伙伴</span>
          <h2>{headline}</h2>
          <p className="companion-source">按已记录工作整理 · 未调用模型</p>
        </div>
        <button
          className="companion-chat"
          disabled={loading}
          onClick={() => onAsk()}
        >
          <MessageCircle size={16} /> 聊聊工作
        </button>
      </div>

      {!loading && focus ? (
        <div className="companion-next">
          <div className="companion-next-body">
            <span className="companion-kicker">
              {reason === "latest" ? "从这条记录继续" : "建议先核实"}
            </span>
            <button
              className="companion-work-title"
              onClick={() => onWork(focus.id)}
            >
              {focus.title} <ArrowUpRight size={15} />
            </button>
            <p>{explanation}</p>
            <div className="companion-facts">
              <span>
                {owner
                  ? `${owner.name}负责`
                  : focus.owner_id
                    ? "负责人信息未载入"
                    : "未分配负责人"}
              </span>
              <span>
                <Clock3 size={12} /> 记录更新于{" "}
                {formatTime(focus.updated_at, timezone)}
              </span>
              {reason === "overdue" && (
                <span>记录截止 {formatTime(focus.due_at, timezone)}</span>
              )}
            </div>
          </div>
          <button
            className="companion-next-action"
            onClick={() => onAsk(focus.id, question)}
          >
            一起梳理下一步 <ArrowRight size={15} />
          </button>
        </div>
      ) : !loading ? (
        <div className="companion-empty">
          <p>
            {works.length
              ? "可以回看已有记录，再讨论后续安排。没有记录的新进展仍然未知。"
              : "先记下要做的事、负责人和已知进展。有了依据，再讨论分工和下一步。"}
          </p>
          <button onClick={() => onAsk(undefined, question)}>
            帮我梳理信息缺口 <ArrowRight size={15} />
          </button>
        </div>
      ) : (
        <p className="companion-loading" role="status">
          正在读取当前获授权的记录，稍后继续。
        </p>
      )}

      {onWatch && (
        <div className="companion-watch">
          <span>
            <Eye size={14} />
            {watchSummary
              ? watchSummary.activeCount > 0
                ? `${watchSummary.activeCount} 项持续关注已授权`
                : "当前没有有效的持续关注授权"
              : "持续关注按你确认的范围执行"}
            {watchSummary?.lastCheckedAt && (
              <small>
                上次核对 {formatTime(watchSummary.lastCheckedAt, timezone)}
              </small>
            )}
          </span>
          <button className="plain" disabled={loading} onClick={onWatch}>
            查看持续关注 <ArrowUpRight size={14} />
          </button>
        </div>
      )}
    </section>
  );
}
