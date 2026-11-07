"use client";

import { useEffect, useState } from "react";
import { ArrowRight, ChevronDown, ClipboardCheck } from "lucide-react";
import { api, unwrap } from "../lib/api";
import { DecisionQueue } from "./decision-queue";
import { Feedback } from "./status";

export function DecisionOverview({
  organizationId,
  timezone,
  revision,
  onMine,
  onOpen,
}: {
  organizationId: string;
  timezone: string;
  revision: string;
  onMine: () => void;
  onOpen: (id: string) => void;
}) {
  const [total, setTotal] = useState<number | null>(null);
  const [error, setError] = useState("");
  const [retry, setRetry] = useState(0);
  const [expanded, setExpanded] = useState(false);
  useEffect(() => {
    let current = true;
    setTotal(null);
    setError("");
    api(organizationId)
      .GET("/api/v1/decisions", {
        params: {
          header: { "x-organization-id": organizationId },
          query: { mine: true, view: "action_required", offset: 0, limit: 1 },
        },
      })
      .then(unwrap)
      .then((page) => {
        if (current) setTotal(page.total);
      })
      .catch((e: Error) => {
        if (current) setError(e.message || "暂时无法读取决策待办");
      });
    return () => {
      current = false;
    };
  }, [organizationId, revision, retry]);
  return (
    <section className="decision-overview" aria-label="决策待办与记录">
      <div className="decision-overview-line">
        <div>
          <h2>
            <ClipboardCheck size={18} aria-hidden="true" />
            我的决策待办
          </h2>
          {error ? (
            <Feedback kind="error">
              {error}
              <button onClick={() => setRetry((value) => value + 1)}>
                重试决策待办
              </button>
            </Feedback>
          ) : total === null ? (
            <p role="status">正在核对决策待办…</p>
          ) : (
            <p>
              {total
                ? `${total} 项待确认或待跟进，统一到“我的工作”处理。`
                : "当前没有待确认或待跟进的决策。"}
            </p>
          )}
        </div>
        <button className="secondary" onClick={onMine}>
          查看我的工作
          <ArrowRight size={15} aria-hidden="true" />
        </button>
      </div>
      <button
        className="decision-records-toggle"
        aria-expanded={expanded}
        onClick={() => setExpanded((value) => !value)}
      >
        {expanded ? "收起企业决策记录" : "查看企业决策记录"}
        <ChevronDown size={15} aria-hidden="true" />
      </button>
      {expanded && (
        <DecisionQueue
          key={organizationId}
          organizationId={organizationId}
          timezone={timezone}
          revision={revision}
          scope="company"
          onOpen={onOpen}
        />
      )}
    </section>
  );
}
