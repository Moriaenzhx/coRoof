"use client";

import { useEffect, useState } from "react";
import { api, formatTime, unwrap, type Schemas } from "../lib/api";
import { Feedback } from "./status";

export type Arrangement = Schemas["WorkArrangementOut"];
type MemberFeedback = Schemas["ArrangementFeedbackOut"];

export function useArrangements(
  organizationId: string | undefined,
  revision: string,
  workId?: string,
  decisionId?: string,
) {
  const [attempt, setAttempt] = useState(0);
  const key = JSON.stringify([
    organizationId,
    revision,
    workId,
    decisionId,
    attempt,
  ]);
  const [result, setResult] = useState<{
    key: string;
    items: Arrangement[];
    error: string;
  } | null>(null);
  useEffect(() => {
    if (!organizationId) return;
    const controller = new AbortController();
    let current = true;
    async function load() {
      const items: Arrangement[] = [];
      let total = Infinity;
      while (items.length < total) {
        const params = {
          header: { "x-organization-id": organizationId! },
          query: { offset: items.length, limit: 100, decision_id: decisionId },
        };
        const page = workId
          ? unwrap(
              await api(organizationId).GET(
                "/api/v1/work-items/{work_id}/arrangements",
                {
                  params: { ...params, path: { work_id: workId } },
                  signal: controller.signal,
                },
              ),
            )
          : unwrap(
              await api(organizationId).GET("/api/v1/work-arrangements", {
                params: {
                  ...params,
                  query: { offset: items.length, limit: 100, mine: true },
                },
                signal: controller.signal,
              }),
            );
        if (!current) return;
        items.push(...page.items);
        total = page.total;
        if (!page.items.length) break;
      }
      if (current)
        setResult({
          key,
          items: [...new Map(items.map((item) => [item.id, item])).values()],
          error: "",
        });
    }
    void load().catch((error: Error) => {
      if (current)
        setResult({
          key,
          items: [],
          error: error.message || "暂时无法读取已确认安排",
        });
    });
    return () => {
      current = false;
      controller.abort();
    };
  }, [key, organizationId, workId, decisionId]);
  const value = result?.key === key ? result : null;
  return {
    items: value?.items || [],
    loading: !!organizationId && !value,
    error: value?.error || "",
    retry: () => setAttempt((value) => value + 1),
  };
}

function FeedbackHistory({
  organizationId,
  workId,
  arrangement,
  timezone,
}: {
  organizationId: string;
  workId: string;
  arrangement: Arrangement;
  timezone: string;
}) {
  const [expanded, setExpanded] = useState(false);
  const [items, setItems] = useState<MemberFeedback[]>([]);
  const [total, setTotal] = useState(0);
  const [offset, setOffset] = useState(0);
  const [attempt, setAttempt] = useState(0);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  useEffect(() => {
    if (!expanded) return;
    let current = true;
    const controller = new AbortController();
    setLoading(true);
    setError("");
    api(organizationId)
      .GET("/api/v1/work-items/{work_id}/arrangements/{decision_id}/feedback", {
        params: {
          header: { "x-organization-id": organizationId },
          path: { work_id: workId, decision_id: arrangement.id },
          query: { offset, limit: 20 },
        },
        signal: controller.signal,
      })
      .then(unwrap)
      .then((page) => {
        if (!current) return;
        setItems((previous) =>
          offset ? [...previous, ...page.items] : page.items,
        );
        setTotal(page.total);
      })
      .catch((error: Error) => {
        if (current) {
          setItems([]);
          setError(error.message);
        }
      })
      .finally(() => {
        if (current) setLoading(false);
      });
    return () => {
      current = false;
      controller.abort();
    };
  }, [organizationId, workId, arrangement.id, expanded, offset, attempt]);
  return (
    <div className="arrangement-feedback-history">
      <button
        className="plain"
        aria-expanded={expanded}
        onClick={() => setExpanded((value) => !value)}
      >
        {expanded
          ? "收起成员反馈"
          : `查看成员反馈（${arrangement.feedback_count}）`}
      </button>
      {expanded && (
        <>
          {error && (
            <Feedback kind="error">
              {error}
              <button
                onClick={() => {
                  setOffset(0);
                  setAttempt((value) => value + 1);
                }}
              >
                重新读取反馈
              </button>
            </Feedback>
          )}
          {items.map((item) => (
            <article key={item.id}>
              <p>{item.summary}</p>
              <small>
                {formatTime(item.recorded_at, timezone)} · 成员本人确认
              </small>
            </article>
          ))}
          {loading && <p role="status">正在读取反馈…</p>}
          {!loading && !error && items.length < total && (
            <button onClick={() => setOffset(items.length)}>
              查看更早反馈
            </button>
          )}
        </>
      )}
    </div>
  );
}

export function ArrangementList({
  organizationId,
  workId,
  timezone,
  items,
  loading,
  error,
  onRetry,
  onFeedback,
  disabled,
  selectedId,
  showPlan = true,
}: {
  organizationId: string;
  workId: string;
  timezone: string;
  items: Arrangement[];
  loading: boolean;
  error: string;
  onRetry: () => void;
  onFeedback?: (item: Arrangement) => void;
  disabled?: boolean;
  selectedId?: string;
  showPlan?: boolean;
}) {
  if (!loading && !error && !items.length) return null;
  return (
    <section
      className="work-arrangements"
      aria-label={showPlan ? "已确认安排" : "成员反馈"}
    >
      <h3>{showPlan ? "已确认安排" : "成员反馈"}</h3>
      {loading && <p role="status">正在读取安排…</p>}
      {error && (
        <Feedback kind="error">
          {error}
          <button onClick={onRetry}>重新读取安排</button>
        </Feedback>
      )}
      {items.map((item) => (
        <article
          key={item.id}
          className="work-arrangement"
          data-selected={selectedId === item.id || undefined}
        >
          {showPlan && (
            <>
              <p className="arrangement-plan">{item.selected_plan}</p>
              <p>后续安排：{item.follow_up}</p>
              <small>
                确认于 {formatTime(item.confirmed_at, timezone)}
                {item.follow_up_at
                  ? ` · 跟进时间 ${formatTime(item.follow_up_at, timezone)}`
                  : " · 未指定跟进时间"}
              </small>
            </>
          )}
          {item.latest_feedback ? (
            <div className="arrangement-latest-feedback">
              <p>最新反馈：{item.latest_feedback.summary}</p>
              <small>
                {formatTime(item.latest_feedback.recorded_at, timezone)} ·
                成员本人确认，待核实结果
              </small>
            </div>
          ) : (
            <p className="muted">尚无成员反馈</p>
          )}
          {item.feedback_count > 0 && (
            <FeedbackHistory
              key={`${organizationId}:${workId}:${item.id}:${item.feedback_count}:${item.latest_feedback?.id}`}
              organizationId={organizationId}
              workId={workId}
              arrangement={item}
              timezone={timezone}
            />
          )}
          {onFeedback && (
            <button
              className="secondary"
              disabled={disabled || selectedId === item.id}
              onClick={() => onFeedback(item)}
            >
              {selectedId === item.id ? "正在反馈这项安排" : "反馈这项安排"}
            </button>
          )}
        </article>
      ))}
    </section>
  );
}

export function DecisionFeedback({
  organizationId,
  workId,
  decisionId,
  timezone,
  revision,
}: {
  organizationId: string;
  workId: string;
  decisionId: string;
  timezone: string;
  revision: string;
}) {
  const list = useArrangements(organizationId, revision, workId, decisionId);
  return (
    <ArrangementList
      organizationId={organizationId}
      workId={workId}
      timezone={timezone}
      {...list}
      onRetry={list.retry}
      showPlan={false}
    />
  );
}
