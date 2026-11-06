"use client";

import { useEffect, useState } from "react";
import { BookOpen, Download } from "lucide-react";
import { api, formatTime, unwrap, type Schemas } from "../lib/api";
import { Drawer } from "./drawer";
import { Feedback } from "./status";

export function DocumentText({
  revision,
  organizationId,
  timezone,
}: {
  revision: Schemas["RevisionOut"];
  organizationId: string;
  timezone: string;
}) {
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  async function download() {
    setBusy(true);
    setError("");
    try {
      const result = await api(organizationId).GET(
        "/api/v1/knowledge/documents/{identifier}/revisions/{revision_id}/file",
        {
          params: {
            header: { "x-organization-id": organizationId },
            path: {
              identifier: revision.document_id,
              revision_id: revision.id,
            },
          },
          parseAs: "blob",
        },
      );
      if (result.error || !result.response.ok || !result.data)
        throw new Error(
          "原文件暂不可用，权限或文档状态可能已变化。请刷新后核对。",
        );
      const url = URL.createObjectURL(result.data);
      const anchor = document.createElement("a");
      anchor.href = url;
      anchor.download = revision.file_name || "document";
      anchor.click();
      window.setTimeout(() => URL.revokeObjectURL(url), 1000);
    } catch (e) {
      setError(e instanceof Error ? e.message : "下载失败");
    } finally {
      setBusy(false);
    }
  }
  return (
    <section className="knowledge-source">
      <div className="section-line">
        <h3>{revision.title}</h3>
        <span className="tag">版本 {revision.number}</span>
      </div>
      <p className="fine-print">
        {revision.published_at
          ? `${revision.current ? "当前已发布版本" : "历史版本 · 不是当前制度"} · ${formatTime(revision.published_at, timezone)}`
          : "待作者确认 · 尚未进入检索"}
      </p>
      {revision.file_name && (
        <>
          <button
            className="plain evidence-link"
            disabled={busy}
            onClick={() => void download()}
          >
            <Download size={15} />
            下载原文件 · {revision.file_name}
          </button>
          <p className="fine-print">
            {revision.edited_extraction
              ? "此文本经人工编辑，与导入的原文件可能不同。"
              : "正文为文件提取文本，版式可能与原文件不同。"}
          </p>
        </>
      )}
      {error && <Feedback kind="error">{error}</Feedback>}
      <div className="document-content">{revision.content}</div>
    </section>
  );
}

export function SourceView({
  source,
  organizationId,
  timezone,
}: {
  source: Pick<Schemas["Citation"], "document_id" | "revision_id">;
  organizationId: string;
  timezone: string;
}) {
  const [revision, setRevision] = useState<Schemas["RevisionOut"] | null>(null);
  const [error, setError] = useState("");
  useEffect(() => {
    let active = true;
    setRevision(null);
    setError("");
    api(organizationId)
      .GET("/api/v1/knowledge/documents/{identifier}/revisions/{revision_id}", {
        params: {
          header: { "x-organization-id": organizationId },
          path: {
            identifier: source.document_id,
            revision_id: source.revision_id,
          },
        },
      })
      .then(unwrap)
      .then((value) => {
        if (active) setRevision(value);
      })
      .catch((e: Error) => {
        if (active) setError(e.message);
      });
    return () => {
      active = false;
    };
  }, [organizationId, source.document_id, source.revision_id]);
  return (
    <>
      {error ? (
        <Feedback kind="error">{error}</Feedback>
      ) : revision ? (
        <DocumentText
          revision={revision}
          organizationId={organizationId}
          timezone={timezone}
        />
      ) : (
        <p role="status">正在核对文档访问权限…</p>
      )}
    </>
  );
}

export function DocumentCitations({
  answer,
  organizationId,
  timezone,
}: {
  answer: Schemas["AnswerOut"];
  organizationId: string;
  timezone: string;
}) {
  const [selected, setSelected] = useState<Schemas["Citation"] | null>(null);
  if (!answer.document_answers?.length) return null;
  return (
    <section className="document-citations" aria-label="文档引用">
      <h3>文档中的相关说明</h3>
      <p className="fine-print">
        以下为已发布文档原文，不代表工作已经执行。引用范围有限，请结合全文核对。
      </p>
      {answer.document_answers.map((item) => {
        const source = answer.documents?.find(
          (value) => value.id === item.citation_id,
        );
        return source ? (
          <article key={source.id} className="knowledge-hit">
            <blockquote>{item.quote}</blockquote>
            <button
              className="plain evidence-link"
              onClick={() => setSelected(source)}
            >
              <BookOpen size={15} />
              {source.title} · 版本 {source.revision_number}
            </button>
            <p className="fine-print">
              发布于 {formatTime(source.source_at, timezone)}
            </p>
          </article>
        ) : null;
      })}
      {selected && (
        <Drawer title="引用原文" close={() => setSelected(null)}>
          <SourceView
            source={selected}
            organizationId={organizationId}
            timezone={timezone}
          />
        </Drawer>
      )}
    </section>
  );
}
