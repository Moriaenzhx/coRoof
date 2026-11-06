"use client";
import { useEffect, useState } from "react";
import {
  ArrowLeft,
  ArrowUpRight,
  BookOpen,
  Clock3,
  TriangleAlert,
} from "lucide-react";
import { api, formatTime, unwrap, type Schemas } from "../lib/api";
import { Feedback, StatusLabel } from "./status";

export type Signal = Schemas["SignalOut"];
export type SnapshotEvidence = Schemas["EvidenceOut"];

export function SignalLabel({ signal }: { signal: Signal }) {
  const Icon = signal.category === "stale" ? Clock3 : TriangleAlert;
  return (
    <span className={`signal-label signal-${signal.severity}`}>
      <Icon size={14} aria-hidden="true" />
      {signal.title}
    </span>
  );
}

export function AttentionList({
  signals,
  onAsk,
}: {
  signals: Signal[];
  onAsk: (workId: string) => void;
}) {
  const groups = [...new Set(signals.map((s) => s.work_item_id))];
  return (
    <div className="attention-list">
      {groups.map((id) => {
        const related = signals.filter((s) => s.work_item_id === id);
        return (
          <button className="attention-row" key={id} onClick={() => onAsk(id)}>
            <span>
              <strong>{related[0].work_title}</strong>
              <span className="signal-labels">
                {related.map((s) => (
                  <SignalLabel key={s.id} signal={s} />
                ))}
              </span>
            </span>
            <ArrowUpRight size={16} aria-hidden="true" />
          </button>
        );
      })}
    </div>
  );
}

export function EvidenceCard({
  evidence,
  timezone,
}: {
  evidence: SnapshotEvidence;
  timezone: string;
}) {
  return (
    <section className="evidence-card">
      <div className="section-line">
        <h3>{evidence.facts.title}</h3>
        <BookOpen size={17} aria-hidden="true" />
      </div>
      <div className="detail-meta">
        <StatusLabel status={evidence.facts.lifecycle_status} />
        {evidence.facts.needs_support && <StatusLabel status="support" />}
      </div>
      {evidence.outdated && (
        <p className="muted">这是历史快照，工作已有更新，请以最新记录为准。</p>
      )}
      <blockquote>{evidence.excerpt}</blockquote>
      <dl className="facts">
        <div>
          <dt>记录时间</dt>
          <dd>{formatTime(evidence.source_at, timezone)}</dd>
        </div>
        <div>
          <dt>截止时间</dt>
          <dd>
            {evidence.facts.source_authority === "external"
              ? "未同步 · 未知"
              : evidence.facts.due_at
                ? formatTime(evidence.facts.due_at, timezone)
                : "未设置"}
          </dd>
        </div>
      </dl>
      <small>
        来源：
        {evidence.facts.source_authority === "external"
          ? "外部来源同步，支持需求未知"
          : "coRoof 工作记录"}{" "}
        · 版本 {evidence.work_version}
      </small>
      <details>
        <summary>证据标识</summary>
        <code>{evidence.id}</code>
        {evidence.event_id && (
          <p>
            <code>{evidence.event_id}</code>
          </p>
        )}
      </details>
    </section>
  );
}

export function EvidenceView({
  id,
  organizationId,
  timezone,
  onBack,
  backLabel = "返回问答",
}: {
  id: string;
  organizationId: string;
  timezone: string;
  onBack?: () => void;
  backLabel?: string;
}) {
  const [data, setData] = useState<SnapshotEvidence | null>(null);
  const [error, setError] = useState("");
  useEffect(() => {
    let current = true;
    api(organizationId)
      .GET("/api/v1/evidence/{evidence_id}", {
        params: {
          path: { evidence_id: id },
          header: { "x-organization-id": organizationId },
        },
      })
      .then(unwrap)
      .then((e) => {
        if (current) setData(e);
      })
      .catch((e) => {
        if (current) setError(e.message);
      });
    return () => {
      current = false;
    };
  }, [id, organizationId]);
  return (
    <>
      {onBack && (
        <button className="plain back-link" onClick={onBack}>
          <ArrowLeft size={15} />
          {backLabel}
        </button>
      )}
      {error && <Feedback kind="error">{error}</Feedback>}
      {data ? (
        <EvidenceCard evidence={data} timezone={timezone} />
      ) : (
        !error && <p role="status">正在读取获授权的证据…</p>
      )}
    </>
  );
}
