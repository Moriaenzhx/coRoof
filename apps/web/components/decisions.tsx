"use client";
import { useCallback, useEffect, useRef, useState } from "react";
import { Check } from "lucide-react";
import { api, formatTime, unwrap, type Schemas } from "../lib/api";
import { Feedback } from "./status";
import { EvidenceCard, EvidenceView } from "./evidence";
import { DecisionFeedback } from "./work-arrangements";

type Decision = Schemas["DecisionOut"];
type Outcome = Schemas["OutcomeOut"];

export function DecisionDetail({
  id,
  organizationId,
  timezone,
  onUpdated,
  onReask,
  actorId,
}: {
  id: string;
  organizationId: string;
  timezone: string;
  onUpdated: () => Promise<void>;
  onReask?: (workId: string) => void;
  actorId?: string;
}) {
  const [data, setData] = useState<Decision | null>(null);
  const [outcomes, setOutcomes] = useState<Outcome[]>([]);
  const [outcomeTotal, setOutcomeTotal] = useState(0);
  const [selected, setSelected] = useState("");
  const [plan, setPlan] = useState("");
  const [followUp, setFollowUp] = useState("");
  const [followUpAt, setFollowUpAt] = useState("");
  const [observed, setObserved] = useState("");
  const [cite, setCite] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [busy, setBusy] = useState(false);
  const [evidenceId, setEvidenceId] = useState<string | null>(null);
  const guard = useRef(false);
  const outcomeKey = useRef<{ body: string; key: string } | null>(null);
  const header = { "x-organization-id": organizationId };
  const loadOutcomes = useCallback(
    async (offset = 0) => {
      const page = unwrap(
        await api(organizationId).GET(
          "/api/v1/decisions/{decision_id}/outcomes",
          {
            params: {
              header: { "x-organization-id": organizationId },
              path: { decision_id: id },
              query: { offset, limit: 20 },
            },
          },
        ),
      );
      setOutcomes((prev) => (offset ? [...prev, ...page.items] : page.items));
      setOutcomeTotal(page.total);
    },
    [id, organizationId],
  );
  useEffect(() => {
    let current = true;
    setData(null);
    api(organizationId)
      .GET("/api/v1/decisions/{decision_id}", {
        params: {
          header: { "x-organization-id": organizationId },
          path: { decision_id: id },
        },
      })
      .then(unwrap)
      .then((d) => {
        if (current) {
          setData(d);
          const first = d.options[0];
          setSelected(first?.id || "");
          setPlan(first?.plan || "");
          setFollowUp("与事项负责人核实进展后，补充实际结果。");
        }
      })
      .catch((e) => {
        if (current) setError(e.message);
      });
    void loadOutcomes().catch((e) => {
      if (current) setError(e.message);
    });
    return () => {
      current = false;
    };
  }, [id, organizationId, loadOutcomes]);
  async function act(fn: () => Promise<void>) {
    if (guard.current) return;
    guard.current = true;
    setBusy(true);
    setError("");
    setNotice("");
    try {
      await fn();
    } catch (e) {
      setError(e instanceof Error ? e.message : "保存失败");
    } finally {
      guard.current = false;
      setBusy(false);
    }
  }
  if (evidenceId)
    return (
      <EvidenceView
        id={evidenceId}
        organizationId={organizationId}
        timezone={timezone}
        onBack={() => setEvidenceId(null)}
        backLabel="返回决策"
      />
    );
  const stale =
    data?.state === "pending" &&
    (data.context_snapshot.evidence.outdated ||
      Date.now() - Date.parse(data.context_snapshot.analysis_time) >
        30 * 60 * 1000);
  return (
    <div className="decision-detail">
      {error && <Feedback kind="error">{error}</Feedback>}
      {notice && <Feedback kind="success">{notice}</Feedback>}
      {!data ? (
        !error && <p role="status">正在读取决策依据…</p>
      ) : (
        <>
          <h3>{data.title}</h3>
          <p className="muted">
            {data.state === "confirmed"
              ? `方案已确认 · ${formatTime(data.confirmed_at, timezone)}`
              : "先看看这个安排，合适再确认。"}
          </p>
          {data.state === "pending" && onReask && (stale || error) && (
            <div className="decision-recheck">
              {stale && <p>这份建议已过时，需要先看看最新进展。</p>}
              <button
                className="plain"
                disabled={busy}
                onClick={() => onReask(data.work_item_id)}
              >
                重新核对当前记录
              </button>
            </div>
          )}
          <details>
            <summary>查看当时的事实与建议</summary>
            <EvidenceCard
              evidence={data.context_snapshot.evidence}
              timezone={timezone}
            />
            <p>{data.context_snapshot.interpretation}</p>
            <small>
              {data.context_snapshot.analysis_mode === "model"
                ? "AI 建议"
                : "规则整理"}{" "}
              · {formatTime(data.context_snapshot.analysis_time, timezone)}
            </small>
            {data.state === "pending" && onReask && !stale && !error && (
              <button
                className="plain"
                disabled={busy}
                onClick={() => onReask(data.work_item_id)}
              >
                重新核对当前记录
              </button>
            )}
          </details>
          {data.state === "pending" && actorId && data.actor_id !== actorId ? (
            <p className="muted">此方案等待准备者本人确认。</p>
          ) : data.state === "pending" &&
            stale &&
            onReask ? null : data.state === "pending" ? (
            <form
              onSubmit={(e) => {
                e.preventDefault();
                void act(async () => {
                  const updated = unwrap(
                    await api(organizationId).POST(
                      "/api/v1/decisions/{decision_id}/confirm",
                      {
                        params: { header, path: { decision_id: id } },
                        body: {
                          expected_version: data.version,
                          selected_option: selected,
                          selected_plan: plan,
                          follow_up: followUp,
                          ...(followUpAt
                            ? {
                                follow_up_at: new Date(
                                  followUpAt,
                                ).toISOString(),
                              }
                            : {}),
                        },
                      },
                    ),
                  );
                  setData(updated);
                  setNotice("方案已确认并记录，可以继续补充实际跟进结果。");
                  await onUpdated();
                });
              }}
            >
              <section className="decision-proposal" aria-label="请确认的安排">
                <p className="decision-proposal-plan">{plan}</p>
                {selected && (
                  <p className="muted">
                    {
                      data.options.find((option) => option.id === selected)
                        ?.tradeoff
                    }
                  </p>
                )}
                <p>
                  <strong>之后：</strong>
                  {followUp}
                </p>
                {followUpAt && (
                  <p>
                    跟进时间：
                    {formatTime(new Date(followUpAt).toISOString(), timezone)}
                  </p>
                )}
              </section>
              <details className="decision-edit">
                <summary>修改这个安排</summary>
                <fieldset disabled={busy}>
                  <legend>选择一个方案</legend>
                  {data.options.map((o) => (
                    <label className="decision-option" key={o.id}>
                      <input
                        type="radio"
                        name="decision-option"
                        value={o.id}
                        checked={selected === o.id}
                        onChange={() => {
                          setSelected(o.id);
                          setPlan(o.plan);
                        }}
                      />
                      <span>
                        <strong>{o.title}</strong>
                        <small>{o.tradeoff}</small>
                      </span>
                    </label>
                  ))}
                </fieldset>
                <label>
                  你的处理方案
                  <textarea
                    rows={3}
                    maxLength={2000}
                    value={plan}
                    onChange={(e) => setPlan(e.target.value)}
                    required
                  />
                </label>
                <label>
                  后续如何跟进
                  <textarea
                    rows={2}
                    maxLength={1000}
                    value={followUp}
                    onChange={(e) => setFollowUp(e.target.value)}
                    placeholder="例如：与负责人核实资料到位情况，下次沟通后补充实际结果。"
                    required
                  />
                </label>
                <label>
                  跟进时间（可选，按本机时区输入）
                  <input
                    type="datetime-local"
                    value={followUpAt}
                    onChange={(e) => setFollowUpAt(e.target.value)}
                  />
                </label>
                <p className="muted">
                  可以选一个回来看进展的时间，留空也能确认。
                </p>
              </details>
              <p className="decision-effect">
                确认后，事项负责人可看到安排并反馈。不会自动通知同事或改变工作状态。
              </p>
              <button
                className="primary"
                disabled={busy || !selected || !plan.trim() || !followUp.trim()}
              >
                <Check size={16} />
                {busy ? "正在保存…" : "确认这个安排"}
              </button>
            </form>
          ) : (
            <>
              <section className="confirmed-plan">
                <h3>已选方案</h3>
                <p>{data.selected_plan}</p>
                <h3>跟进安排</h3>
                <p>{data.follow_up}</p>
                {data.follow_up_at && (
                  <p className="muted">
                    跟进时间：{formatTime(data.follow_up_at, timezone)}
                  </p>
                )}
              </section>
              <DecisionFeedback
                key={`${organizationId}:${id}`}
                organizationId={organizationId}
                workId={data.work_item_id}
                decisionId={id}
                timezone={timezone}
                revision={String(data.version)}
              />
              <section className="outcomes">
                <h3>实际跟进结果</h3>
                {!outcomes.length && (
                  <p className="muted">
                    还没有实际结果，确认方案不代表工作已经完成。
                  </p>
                )}
                {outcomes.map((o) => (
                  <article key={o.id}>
                    <p>{o.observed_result}</p>
                    <small>
                      {formatTime(o.recorded_at, timezone)} · 人工确认
                      {o.evidence_refs.length
                        ? ` · ${o.evidence_refs.length} 条证据引用`
                        : ""}
                    </small>
                    {o.evidence_refs.map((ref) => (
                      <button
                        className="evidence-link"
                        key={ref}
                        onClick={() => setEvidenceId(ref)}
                      >
                        查看引用的工作记录
                      </button>
                    ))}
                  </article>
                ))}
                {outcomes.length < outcomeTotal && (
                  <button
                    disabled={busy}
                    onClick={() =>
                      void act(() => loadOutcomes(outcomes.length))
                    }
                  >
                    加载更早结果
                  </button>
                )}
                <form
                  onSubmit={(e) => {
                    e.preventDefault();
                    void act(async () => {
                      const evidence_refs = cite
                        ? [data.context_snapshot.evidence.id]
                        : [];
                      const body = JSON.stringify({
                        observed_result: observed,
                        evidence_refs,
                      });
                      if (outcomeKey.current?.body !== body)
                        outcomeKey.current = { body, key: crypto.randomUUID() };
                      unwrap(
                        await api(organizationId).POST(
                          "/api/v1/decisions/{decision_id}/outcomes",
                          {
                            params: { header, path: { decision_id: id } },
                            body: {
                              observed_result: observed,
                              evidence_refs,
                              idempotency_key: outcomeKey.current.key,
                            },
                          },
                        ),
                      );
                      await loadOutcomes();
                      setObserved("");
                      setNotice("实际结果已追加到决策记录。");
                      await onUpdated();
                    });
                  }}
                >
                  <label>
                    记录实际结果
                    <textarea
                      rows={3}
                      maxLength={4000}
                      value={observed}
                      onChange={(e) => setObserved(e.target.value)}
                      required
                      placeholder="只记录已经确认的结果，也可以记录尚未解决的问题。"
                    />
                  </label>
                  <label className="check-line">
                    <input
                      type="checkbox"
                      checked={cite}
                      onChange={(e) => setCite(e.target.checked)}
                    />
                    引用决策时的工作记录
                  </label>
                  <button disabled={busy || !observed.trim()}>
                    保存跟进结果
                  </button>
                </form>
              </section>
            </>
          )}
        </>
      )}
    </div>
  );
}
