"use client";

import { useId, useState } from "react";
import { ArrowRight, ChevronDown, ChevronUp, Inbox } from "lucide-react";
import {
  formatTime,
  type Initiative,
  type Member,
  type Schemas,
  type Work,
} from "../lib/api";
import { useWatch } from "../lib/use-watch";
import "./overview-inbox.css";

type Signal = Schemas["SignalOut"];
type Attention = Schemas["AttentionOut"];
type Row = {
  id: string;
  workId: string | null;
  title: string;
  work?: Work;
  support: boolean;
  signals: Signal[];
  attention: Attention[];
};

const terminal = (work: Work) =>
  work.lifecycle_status === "done" || work.lifecycle_status === "cancelled";
const attentionRank = (item: Attention) =>
  item.kind === "follow_up" && item.decision_id
    ? 0
    : item.agent_run_id && item.work_item_id
      ? 1
      : item.category === "support" || item.category === "deadline_blocked"
        ? 2
        : item.category === "overdue"
          ? 3
          : 4;
function rowRank(row: Row) {
  return Math.min(
    ...row.attention.map(attentionRank),
    row.support ||
      row.signals.some((signal) =>
        ["support", "deadline_blocked"].includes(signal.category),
      )
      ? 2
      : row.signals.some((signal) => signal.category === "overdue")
        ? 3
        : 4,
  );
}
function mergeRows(
  organizationId: string,
  works: Work[],
  signals: Signal[],
  items: Attention[],
) {
  const workById = new Map(
    works
      .filter((work) => work.organization_id === organizationId)
      .map((work) => [work.id, work]),
  );
  const rows = new Map<string, Row>();
  function row(id: string, workId: string | null, title: string) {
    let value = rows.get(id);
    if (!value) {
      const work = workId ? workById.get(workId) : undefined;
      value = {
        id,
        workId,
        title: work?.title || title,
        work,
        support: false,
        signals: [],
        attention: [],
      };
      rows.set(id, value);
    }
    return value;
  }
  for (const work of workById.values()) {
    if (
      !terminal(work) &&
      work.source_authority === "native" &&
      work.needs_support
    )
      row(work.id, work.id, work.title).support = true;
  }
  for (const signal of signals) {
    const work = workById.get(signal.work_item_id);
    if (signal.state !== "active" || (work && terminal(work))) continue;
    // External sources do not establish a native support request or deadline.
    if (work?.source_authority === "external" && signal.category !== "stale")
      continue;
    const value = row(
      signal.work_item_id,
      signal.work_item_id,
      signal.work_title,
    );
    if (!value.signals.some((current) => current.id === signal.id))
      value.signals.push(signal);
  }
  for (const item of items) {
    const value = row(
      item.work_item_id || `attention:${item.id}`,
      item.work_item_id,
      item.work_title || item.title,
    );
    if (!value.attention.some((current) => current.id === item.id))
      value.attention.push(item);
  }
  for (const value of rows.values())
    value.attention.sort(
      (a, b) =>
        attentionRank(a) - attentionRank(b) ||
        b.changed_at.localeCompare(a.changed_at),
    );
  const recent = (value: Row) =>
    Math.max(
      0,
      value.work ? Date.parse(value.work.updated_at) : 0,
      ...value.signals.map((signal) => Date.parse(signal.evaluated_at)),
      ...value.attention.map((item) => Date.parse(item.changed_at)),
    );
  return [...rows.values()].sort(
    (a, b) =>
      rowRank(a) - rowRank(b) ||
      recent(b) - recent(a) ||
      a.id.localeCompare(b.id),
  );
}

export function OverviewInbox({
  organizationId,
  timezone,
  works,
  signals,
  members,
  initiatives,
  isOwner,
  onWork,
  onAsk,
  onPlan,
  onDecision,
  onManage,
}: {
  organizationId: string;
  timezone: string;
  works: Work[];
  signals: Signal[];
  members: Member[];
  initiatives: Initiative[];
  isOwner: boolean;
  onWork: (id: string) => void;
  onAsk: (workId: string, question?: string) => void;
  onPlan: (runId: string, workId: string) => void;
  onDecision: (id: string) => void;
  onManage: () => void;
}) {
  const watch = useWatch(organizationId, false, isOwner);
  const [expandedScope, setExpandedScope] = useState<string | null>(null);
  const titleId = useId();
  const listId = useId();
  const scope = `${organizationId}:${isOwner}`;
  const expanded = expandedScope === scope;
  const activePolicies = new Set(
    watch.policies
      .filter((policy) => policy.effective_state === "active")
      .map((policy) => policy.id),
  );
  const items = watch.items.filter(
    (item) => item.state === "open" && activePolicies.has(item.policy_id),
  );
  const rows = mergeRows(organizationId, works, signals, items);
  const visible = expanded ? rows : rows.slice(0, 3);
  const policyStatus = [
    ["active", "项有效关注"],
    ["paused", "项已暂停"],
    ["expired", "项授权到期"],
    ["unauthorized", "项授权失效"],
    ["revoked", "项已撤销"],
  ]
    .flatMap(([state, label]) => {
      const count = watch.policies.filter(
        (policy) => policy.effective_state === state,
      ).length;
      return count ? [`${count} ${label}`] : [];
    })
    .join(" · ");

  return (
    <section
      className="overview-inbox overview-priority-inbox"
      aria-labelledby={titleId}
    >
      <div className="overview-inbox-heading">
        <div>
          <h2 id={titleId}>
            先处理这几件事{" "}
            <span>
              {isOwner && (watch.loading || watch.error)
                ? rows.length
                  ? `${rows.length} 项已知提醒`
                  : "关注记录待核对"
                : `${rows.length} 项待关注`}
            </span>
          </h2>
          <p>
            {rows.length
              ? "先核实已有跟进，再看处理建议和支持需求。"
              : "这里集中放需要你关注的事项。"}
          </p>
        </div>
        {isOwner && (
          <button className="overview-inbox-manage" onClick={onManage}>
            管理提醒 <ArrowRight size={14} />
          </button>
        )}
      </div>
      {rows.length ? (
        <div id={listId} className="overview-inbox-list overview-priority-list">
          {visible.map((row, index) => {
            const attention = row.attention[0];
            const followUp = row.attention.find(
              (item) => item.kind === "follow_up" && item.decision_id,
            );
            const plan = row.attention.find(
              (item) => item.agent_run_id && item.work_item_id,
            );
            const evidence = row.attention.find(
              (item) =>
                item.evidence &&
                !item.evidence.outdated &&
                item.evidence.work_item_id === row.workId &&
                item.evidence.facts.id === row.workId &&
                item.evidence.facts.organization_id === organizationId,
            )?.evidence;
            const facts = row.work || evidence?.facts;
            const owner = members.find(
              (member) =>
                member.organization_id === organizationId &&
                member.id === facts?.owner_id,
            );
            const project = initiatives.find(
              (initiative) =>
                initiative.organization_id === organizationId &&
                initiative.id === facts?.initiative_id,
            );
            const support =
              row.support ||
              row.signals.some((signal) =>
                ["support", "deadline_blocked"].includes(signal.category),
              ) ||
              row.attention.some((item) =>
                ["support", "deadline_blocked"].includes(item.category),
              );
            const date =
              row.signals.some((signal) => signal.category === "overdue") ||
              attention?.category === "overdue";
            const label = followUp
              ? "跟进待核实"
              : plan
                ? "建议待审阅"
                : support
                  ? "需要支持"
                  : date
                    ? "日期待核实"
                    : attention?.category === "source_unavailable"
                      ? "来源更新失败"
                      : attention?.category === "source_stale"
                        ? "来源待更新"
                        : "资料待核实";
            const explanation =
              attention?.explanation ||
              row.signals.find(
                (signal) => signal.category === "deadline_blocked",
              )?.explanation ||
              (row.support
                ? "已记录支持需求，先核实当前协作缺口。"
                : row.signals[0]?.explanation);
            const reason = followUp
              ? followUp.category === "follow_up_due"
                ? "已到记录的跟进时间，需要核实实际结果。"
                : "已有跟进安排，需要核实实际结果。"
              : plan
                ? "已有处理建议，先核对是否适合当前情况。"
                : support
                  ? "已记录支持需求，需要核实缺口并协调负责人。"
                  : date
                    ? "已过记录的截止时间，实际交付仍待核实。"
                    : explanation || "还缺少可核对的信息，需要补充当前情况。";
            const supportStatus = facts
              ? facts.source_authority === "external"
                ? "支持情况未同步"
                : terminal(facts)
                  ? "事项已结束"
                  : facts.needs_support
                    ? "需要支持"
                    : "未记录支持需求"
              : "支持情况待核实";
            const sourceTime = row.work
              ? `工作记录 ${formatTime(row.work.updated_at, timezone)}`
              : attention
                ? `关注记录更新 ${formatTime(attention.changed_at, timezone)}`
                : `规则核对 ${formatTime(row.signals[0]?.evaluated_at, timezone)}`;
            const question = `请根据已确认记录核实「${row.title}」的${support ? "支持需求和协作缺口" : "当前进展与待核实信息"}，整理下一步和需要谁补充的信息。缺少依据请明确说明，不代替任何人确认。`;
            return (
              <article
                key={row.id}
                className={`overview-inbox-row ${index < 3 ? "overview-priority-row" : "overview-inbox-secondary-row"}`}
                aria-label={row.title}
              >
                {index < 3 && (
                  <span className="overview-priority-number" aria-hidden="true">
                    {String(index + 1).padStart(2, "0")}
                  </span>
                )}
                <div className="overview-inbox-row-main">
                  <div className="overview-inbox-row-title">
                    <h3>{row.title}</h3>
                    <span
                      className="overview-inbox-kind"
                      data-review={!!(followUp || plan) || undefined}
                    >
                      {label}
                    </span>
                  </div>
                  <p className="overview-inbox-explanation">{reason}</p>
                  <div className="overview-priority-context">
                    {row.workId && (
                      <p className="overview-inbox-meta">
                        <span className="overview-priority-owner">
                          {owner
                            ? `${owner.name}负责`
                            : facts?.owner_id
                              ? "负责人信息未载入"
                              : facts
                                ? "未分配负责人"
                                : "负责人待核实"}
                        </span>
                        <span>
                          {project?.title ||
                            (facts?.initiative_id
                              ? "项目信息未载入"
                              : facts
                                ? "未关联项目"
                                : "项目待核实")}
                        </span>
                        <span>
                          {facts?.source_authority === "external"
                            ? "工作截止未同步"
                            : facts?.due_at
                              ? `工作截止 ${formatTime(facts.due_at, timezone)}`
                              : facts
                                ? "未设工作截止"
                                : "工作截止待核实"}
                        </span>
                        {supportStatus !== label && (
                          <span
                            className="overview-priority-support"
                            data-support={
                              supportStatus === "需要支持" || undefined
                            }
                          >
                            {supportStatus}
                          </span>
                        )}
                      </p>
                    )}
                    <div className="overview-inbox-trace">
                      <details className="overview-inbox-evidence">
                        <summary>依据与来源</summary>
                        <div className="overview-inbox-sources">
                          {row.support && <span>已确认工作</span>}
                          {!!row.signals.length && <span>规则提示</span>}
                          {!!row.attention.length && <span>后台关注</span>}
                          <small>{sourceTime}</small>
                        </div>
                        {explanation && explanation !== reason && (
                          <p>{explanation}</p>
                        )}
                        <ul>
                          {row.support && (
                            <li>
                              已确认工作：支持需求尚未解除；记录版本{" "}
                              {row.work?.version}。
                            </li>
                          )}
                          {row.signals.map((signal) => (
                            <li key={signal.id}>
                              规则提示 · {signal.title}：{signal.explanation}{" "}
                              核对于 {formatTime(signal.evaluated_at, timezone)}
                              。
                            </li>
                          ))}
                          {row.attention.map((item) => (
                            <li key={item.id}>
                              后台关注 · {item.policy_name}：{item.explanation}{" "}
                              更新于 {formatTime(item.changed_at, timezone)}。
                              {item.agent_run_id
                                ? "含已有分析，仍需审阅。"
                                : "规则或系统核对。"}
                              {item.decision_id &&
                                item.decision_id !== followUp?.decision_id && (
                                  <button
                                    onClick={() =>
                                      onDecision(item.decision_id!)
                                    }
                                  >
                                    查看这条跟进
                                  </button>
                                )}
                              {item.agent_run_id &&
                                item.work_item_id &&
                                (followUp ||
                                  item.agent_run_id !== plan?.agent_run_id) && (
                                  <button
                                    onClick={() =>
                                      onPlan(
                                        item.agent_run_id!,
                                        item.work_item_id!,
                                      )
                                    }
                                  >
                                    审阅这条建议
                                  </button>
                                )}
                            </li>
                          ))}
                        </ul>
                        {!row.work && evidence && (
                          <p>
                            负责人、项目和工作截止来自本条关注记录的证据快照。
                          </p>
                        )}
                        {row.workId && (
                          <div className="overview-inbox-secondary-actions">
                            {(followUp || plan) && (
                              <button onClick={() => onWork(row.workId!)}>
                                查看工作
                              </button>
                            )}
                            {!plan && !followUp && (
                              <button
                                onClick={() => onAsk(row.workId!, question)}
                              >
                                梳理下一步
                              </button>
                            )}
                          </div>
                        )}
                      </details>
                    </div>
                  </div>
                </div>
                <div className="overview-inbox-row-actions">
                  {followUp && (
                    <button onClick={() => onDecision(followUp.decision_id!)}>
                      核实跟进结果
                    </button>
                  )}
                  {plan && !followUp && (
                    <button
                      onClick={() =>
                        onPlan(plan.agent_run_id!, plan.work_item_id!)
                      }
                    >
                      查看处理建议
                    </button>
                  )}
                  {row.workId && !followUp && !plan && (
                    <button onClick={() => onWork(row.workId!)}>
                      {support ? "查看支持需求" : "核实当前进展"}
                    </button>
                  )}
                  {!row.workId && !followUp && !plan && (
                    <button onClick={onManage}>查看关注范围</button>
                  )}
                </div>
              </article>
            );
          })}
        </div>
      ) : (
        <div className="overview-inbox-empty">
          <Inbox size={20} aria-hidden="true" />
          <p>
            {isOwner && watch.loading
              ? "正在合并已授权的工作与关注记录…"
              : works.length
                ? "当前已记录事项中，暂无需要在这里提醒的内容。"
                : "还没有可整理的工作记录。建立工作并记录进展后，支持需求和核实提示会集中在这里。"}
            <span>尚未记录的情况仍然未知。</span>
          </p>
        </div>
      )}
      {rows.length > 3 && (
        <button
          className="overview-inbox-expand"
          aria-expanded={expanded}
          aria-controls={listId}
          onClick={() => setExpandedScope(expanded ? null : scope)}
        >
          {expanded ? (
            <>
              收起其余事项 <ChevronUp size={14} />
            </>
          ) : (
            <>
              还有 {rows.length - 3} 项，展开查看 <ChevronDown size={14} />
            </>
          )}
        </button>
      )}
      {isOwner && (
        <div className="overview-inbox-watch-status" role="status">
          {watch.error ? (
            <>
              <span>后台记录读取失败：{watch.error}</span>
              <button onClick={() => void watch.load()}>重试</button>
            </>
          ) : watch.loading ? (
            <span>正在读取后台关注记录…</span>
          ) : (
            <details>
              <summary>自动关注情况</summary>
              <span>{policyStatus || "尚未授权持续关注"}</span>
            </details>
          )}
        </div>
      )}
    </section>
  );
}
