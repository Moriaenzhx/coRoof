"use client";

import { useEffect, useId, useState } from "react";
import { ArrowUpRight, History, RefreshCw } from "lucide-react";
import { api, formatTime, unwrap, type Schemas } from "../lib/api";
import "./agent-history.css";

type Run = Schemas["RunOut"];
const stateLabels: Record<Run["state"], string> = {
  ready: "尚未完成",
  running: "处理中",
  completed: "已完成查询",
  failed: "已停止",
  cancelled: "已取消",
  interrupted: "结果待核对",
};

export function AgentHistory({
  organizationId,
  timezone,
  revision,
  onOpen,
}: {
  organizationId: string;
  timezone: string;
  revision: string;
  onOpen: (runId: string, workId?: string, question?: string) => void;
}) {
  const headingId = useId();
  const [attempt, setAttempt] = useState(0);
  const [result, setResult] = useState<{
    key: string;
    rows: Run[];
    error: string;
  } | null>(null);
  const requestKey = JSON.stringify([organizationId, revision, attempt]);
  const current = result?.key === requestKey ? result : null;
  const busy = Boolean(organizationId) && current === null;

  useEffect(() => {
    if (!organizationId) return;
    const controller = new AbortController();
    let active = true;
    api(organizationId)
      .GET("/api/v1/agent/runs", {
        signal: controller.signal,
        params: {
          header: { "x-organization-id": organizationId },
          query: { task: "read" },
        },
      })
      .then(unwrap)
      .then((rows) => {
        if (active)
          setResult({
            key: requestKey,
            rows: rows.filter((run) => run.task === "read").slice(0, 5),
            error: "",
          });
      })
      .catch((error: unknown) => {
        if (active)
          setResult({
            key: requestKey,
            rows: [],
            error:
              error instanceof Error ? error.message : "暂时无法读取查询记录。",
          });
      });
    return () => {
      active = false;
      controller.abort();
    };
  }, [organizationId, requestKey]);

  return (
    <section className="agent-history" aria-labelledby={headingId}>
      <div className="agent-history-heading">
        <div>
          <h2 id={headingId}>
            <History size={17} aria-hidden="true" />
            最近查询
          </h2>
          <p>最多显示本人仍有权限查看的最近 5 次查询，不含后台持续关注。</p>
        </div>
        <button
          type="button"
          className="agent-history-refresh"
          disabled={busy || !organizationId}
          onClick={() => setAttempt((value) => value + 1)}
        >
          <RefreshCw size={15} aria-hidden="true" />
          刷新记录
        </button>
      </div>
      {!organizationId && (
        <p className="agent-history-message">请先选择企业。</p>
      )}
      {busy && (
        <p className="agent-history-message" role="status">
          正在读取查询记录…
        </p>
      )}
      {current?.error && (
        <div className="agent-history-error" role="alert">
          <p>查询记录读取失败：{current.error}</p>
          <button
            type="button"
            onClick={() => setAttempt((value) => value + 1)}
          >
            重试查询记录
          </button>
        </div>
      )}
      {current &&
        !current.error &&
        (current.rows.length ? (
          <ul className="agent-history-list">
            {current.rows.map((run) => (
              <li key={run.id}>
                <div className="agent-history-content">
                  <h3>{run.question}</h3>
                  <div className="agent-history-meta">
                    <span>{stateLabels[run.state]}</span>
                    <time dateTime={run.created_at}>
                      {formatTime(run.created_at, timezone)}
                    </time>
                  </div>
                </div>
                <button
                  type="button"
                  aria-label={`查看查询：${run.question}`}
                  onClick={() =>
                    onOpen(run.id, run.work_item_id || undefined, run.question)
                  }
                >
                  查看记录
                  <ArrowUpRight size={15} aria-hidden="true" />
                </button>
              </li>
            ))}
          </ul>
        ) : (
          <p className="agent-history-message">
            当前没有可查看的查询记录。可在底部输入框发送工作问题。
          </p>
        ))}
      <p className="agent-history-note">
        查看记录不会发起新的模型查询；查询完成不代表业务已执行。
      </p>
    </section>
  );
}
