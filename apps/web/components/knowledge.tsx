"use client";

import { useEffect, useRef, useState } from "react";
import {
  BookOpen,
  ChevronRight,
  FilePlus2,
  FileText,
  Search,
  Upload,
} from "lucide-react";
import {
  api,
  formatTime,
  unwrap,
  type Department,
  type Member,
  type Schemas,
} from "../lib/api";
import { Drawer } from "./drawer";
import { Feedback } from "./status";
import { DocumentText, SourceView } from "./knowledge-source";
import "./knowledge.css";

type Document = Schemas["DocumentOut"];
type Access = Pick<
  Schemas["DocumentInput"],
  "visibility" | "department_id" | "member_ids"
>;
type Context = {
  organizationId: string;
  memberId?: string;
  timezone: string;
  isOwner: boolean;
  departments: Department[];
  members: Member[];
  onAsk?: (question?: string) => void;
};
const scopeNames: Record<NonNullable<Access["visibility"]>, string> = {
  private: "仅自己",
  department: "部门共享",
  organization: "全员共享",
  members: "指定共享",
};
const stateNames: Record<string, string> = {
  draft: "草稿",
  published: "已发布",
  withdrawn: "已撤回",
  deleted: "已删除",
};
const initialAccess: Access = {
  visibility: "private",
  department_id: null,
  member_ids: [],
};

function AccessFields({
  value,
  onChange,
  context,
}: {
  value: Access;
  onChange: (value: Access) => void;
  context: Context;
}) {
  return (
    <div className="knowledge-access">
      <label>
        可见范围
        <select
          value={value.visibility}
          onChange={(event) =>
            onChange({
              visibility: event.target.value as Access["visibility"],
              department_id: null,
              member_ids: [],
            })
          }
        >
          <option value="private">{scopeNames.private}</option>
          <option value="department">{scopeNames.department}</option>
          {context.isOwner && (
            <option value="organization">{scopeNames.organization}</option>
          )}
          <option value="members">{scopeNames.members}</option>
        </select>
      </label>
      {value.visibility === "department" && (
        <label>
          可见部门
          <select
            required
            value={value.department_id || ""}
            onChange={(event) =>
              onChange({ ...value, department_id: event.target.value })
            }
          >
            <option value="">选择部门</option>
            {context.departments.map((department) => (
              <option key={department.id} value={department.id}>
                {department.name}
              </option>
            ))}
          </select>
        </label>
      )}
      {value.visibility === "members" && (
        <fieldset>
          <legend>可见成员</legend>
          {context.members.map((member) => (
            <label className="checkbox-line" key={member.id}>
              <input
                type="checkbox"
                checked={value.member_ids?.includes(member.id) || false}
                onChange={(event) =>
                  onChange({
                    ...value,
                    member_ids: event.target.checked
                      ? [...(value.member_ids || []), member.id]
                      : value.member_ids?.filter((id) => id !== member.id),
                  })
                }
              />
              {member.name}
            </label>
          ))}
        </fieldset>
      )}
      <p className="fine-print">
        发布前仅作者可见。私有文档不会因他人是企业所有者而自动共享。
      </p>
    </div>
  );
}

function NewDocument({
  context,
  onSaved,
}: {
  context: Context;
  onSaved: (document: Document) => void;
}) {
  const [method, setMethod] = useState<"write" | "import" | null>(null);
  const [title, setTitle] = useState("");
  const [content, setContent] = useState("");
  const [access, setAccess] = useState<Access>(initialAccess);
  const [file, setFile] = useState<File | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const request = useRef({ signature: "", key: crypto.randomUUID() });
  const active = useRef(true);
  useEffect(() => {
    active.current = true;
    return () => {
      active.current = false;
    };
  }, []);
  async function save() {
    if (busy) return;
    setBusy(true);
    setError("");
    try {
      const signature = JSON.stringify([
        method,
        title,
        content,
        access,
        file?.name,
        file?.size,
        file?.lastModified,
      ]);
      if (signature !== request.current.signature)
        request.current = { signature, key: crypto.randomUUID() };
      const params = {
        header: { "x-organization-id": context.organizationId },
      };
      let result: Document;
      if (method === "import") {
        if (!file) throw new Error("请选择要导入的文件。");
        if (file.size > 4_000_000 || !file.size)
          throw new Error("文件须小于 4 MB 且不为空。");
        const bytes = new Uint8Array(await file.arrayBuffer());
        if (!active.current) return;
        let binary = "";
        for (let index = 0; index < bytes.length; index += 8192)
          binary += String.fromCharCode(...bytes.subarray(index, index + 8192));
        result = unwrap(
          await api(context.organizationId).POST("/api/v1/knowledge/import", {
            params,
            body: {
              ...access,
              title,
              file_name: file.name,
              file_base64: btoa(binary),
              idempotency_key: request.current.key,
            },
          }),
        );
      } else {
        result = unwrap(
          await api(context.organizationId).POST(
            "/api/v1/knowledge/documents",
            {
              params,
              body: {
                ...access,
                title,
                content,
                idempotency_key: request.current.key,
              },
            },
          ),
        );
      }
      if (active.current) onSaved(result);
    } catch (e) {
      if (active.current) setError(e instanceof Error ? e.message : "保存失败");
    } finally {
      if (active.current) setBusy(false);
    }
  }
  if (!method)
    return (
      <div className="knowledge-add-choices">
        <p className="muted">先保存为草稿，核对后再由你发布。</p>
        <button
          className="knowledge-add-choice"
          onClick={() => setMethod("import")}
        >
          <Upload size={24} aria-hidden="true" />
          <span>
            <strong>导入文件</strong>
            <small>上传已有制度、手册或说明</small>
          </span>
          <ChevronRight size={18} aria-hidden="true" />
        </button>
        <button
          className="knowledge-add-choice"
          onClick={() => setMethod("write")}
        >
          <FileText size={24} aria-hidden="true" />
          <span>
            <strong>直接编写</strong>
            <small>写一份新资料，或粘贴已有内容</small>
          </span>
          <ChevronRight size={18} aria-hidden="true" />
        </button>
      </div>
    );
  return (
    <form
      className="knowledge-form"
      onSubmit={(event) => {
        event.preventDefault();
        void save();
      }}
    >
      <p className="muted">
        保存后先核对草稿，再由你确认发布。只有已发布内容可用于查阅和问答。
      </p>
      <button
        className="plain knowledge-method-back"
        type="button"
        onClick={() => setMethod(null)}
      >
        重新选择添加方式
      </button>
      <label>
        文档标题
        <input
          required
          maxLength={200}
          value={title}
          onChange={(event) => setTitle(event.target.value)}
        />
      </label>
      {method === "import" && (
        <>
          <label>
            选择文件
            <input
              type="file"
              required
              accept=".txt,.md,.pdf,.docx"
              onChange={(event) => {
                const next = event.target.files?.[0] || null;
                setFile(next);
                if (next && !title.trim())
                  setTitle(next.name.replace(/\.[^.]+$/, "").slice(0, 200));
              }}
            />
          </label>
          <p className="fine-print">
            支持 TXT、Markdown、文本 PDF、DOCX，最大 4 MB。扫描 PDF 暂不支持。
          </p>
        </>
      )}
      {method === "write" && (
        <label>
          文档正文
          <textarea
            required
            rows={12}
            maxLength={120000}
            value={content}
            onChange={(event) => setContent(event.target.value)}
          />
        </label>
      )}
      <details className="knowledge-disclosure">
        <summary>
          发布后谁可以看 · {scopeNames[access.visibility || "private"]}
        </summary>
        <AccessFields value={access} onChange={setAccess} context={context} />
      </details>
      {error && <Feedback kind="error">{error}</Feedback>}
      <button className="primary" disabled={busy} type="submit">
        {busy ? "正在保存…" : "保存草稿"}
      </button>
    </form>
  );
}

function DocumentPanel({
  id,
  context,
  onChanged,
  onDeleted,
  initialView,
}: {
  id: string;
  context: Context;
  onChanged: () => void;
  onDeleted: () => void;
  initialView: "published" | "manage";
}) {
  const [row, setRow] = useState<Document | null>(null);
  const [revision, setRevision] = useState<Schemas["RevisionOut"] | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [refresh, setRefresh] = useState(0);
  const [editing, setEditing] = useState(false);
  const [sharing, setSharing] = useState(false);
  const [showPublished, setShowPublished] = useState(
    initialView === "published",
  );
  const [managing, setManaging] = useState(initialView === "manage");
  const [title, setTitle] = useState("");
  const [content, setContent] = useState("");
  const [access, setAccess] = useState<Access>(initialAccess);
  const [confirmed, setConfirmed] = useState(false);
  const [action, setAction] = useState<"withdraw" | "delete" | null>(null);
  const request = useRef({ signature: "", key: crypto.randomUUID() });
  const { organizationId } = context;
  useEffect(() => {
    let active = true;
    setRow(null);
    setRevision(null);
    setError("");
    setConfirmed(false);
    async function load() {
      try {
        const header = { "x-organization-id": organizationId };
        const current = unwrap(
          await api(organizationId).GET(
            "/api/v1/knowledge/documents/{identifier}",
            { params: { header, path: { identifier: id } } },
          ),
        );
        const revisionId = showPublished
          ? current.published_id
          : current.draft_id || current.published_id;
        const version = revisionId
          ? unwrap(
              await api(organizationId).GET(
                "/api/v1/knowledge/documents/{identifier}/revisions/{revision_id}",
                {
                  params: {
                    header,
                    path: { identifier: id, revision_id: revisionId },
                  },
                },
              ),
            )
          : null;
        if (!active) return;
        setRow(current);
        setRevision(version);
        setTitle(version?.title || current.title);
        setContent(version?.content || "");
        setAccess({
          visibility: current.visibility,
          department_id: current.department_id,
          member_ids: current.member_ids,
        });
      } catch (e) {
        if (active) setError(e instanceof Error ? e.message : "读取失败");
      }
    }
    void load();
    return () => {
      active = false;
    };
  }, [id, organizationId, refresh, showPublished]);
  async function mutate(kind: "edit" | "publish" | "access" | "action") {
    if (!row || busy) return;
    setBusy(true);
    setError("");
    const signature = JSON.stringify([
      kind,
      row.version,
      title,
      content,
      access,
      action,
    ]);
    if (signature !== request.current.signature)
      request.current = { signature, key: crypto.randomUUID() };
    const base = {
      expected_version: row.version,
      idempotency_key: request.current.key,
    };
    const params = {
      header: { "x-organization-id": organizationId },
      path: { identifier: id },
    };
    try {
      if (kind === "edit")
        unwrap(
          await api(organizationId).POST(
            "/api/v1/knowledge/documents/{identifier}/edit",
            { params, body: { ...base, title, content } },
          ),
        );
      if (kind === "publish" && row.draft_id && confirmed)
        unwrap(
          await api(organizationId).POST(
            "/api/v1/knowledge/documents/{identifier}/publish",
            {
              params,
              body: { ...base, revision_id: row.draft_id, confirm: true },
            },
          ),
        );
      if (kind === "access")
        unwrap(
          await api(organizationId).POST(
            "/api/v1/knowledge/documents/{identifier}/access",
            { params, body: { ...base, ...access } },
          ),
        );
      if (kind === "action" && action && confirmed)
        unwrap(
          await api(organizationId).POST(
            "/api/v1/knowledge/documents/{identifier}/action",
            { params, body: { ...base, action, confirm: true } },
          ),
        );
      onChanged();
      if (kind === "action" && action === "delete") {
        onDeleted();
        return;
      }
      setEditing(false);
      setSharing(false);
      setAction(null);
      setConfirmed(false);
      setShowPublished(false);
      setRefresh((value) => value + 1);
    } catch (e) {
      setError(e instanceof Error ? e.message : "操作失败，请刷新后重试");
    } finally {
      setBusy(false);
    }
  }
  return (
    <div className="knowledge-detail">
      {error && (
        <Feedback kind="error">
          {error}
          <button
            className="plain"
            onClick={() => {
              setEditing(false);
              setSharing(false);
              setAction(null);
              setRefresh((value) => value + 1);
            }}
          >
            重新读取
          </button>
        </Feedback>
      )}
      {!row && !error && <p role="status">正在读取文档…</p>}
      {row && (
        <>
          <p className="fine-print">
            {scopeNames[row.visibility]} · {stateNames[row.state]}
          </p>
          {managing && row.draft_id && row.published_id && (
            <div className="settings-actions">
              <button
                className="plain"
                aria-pressed={!showPublished}
                onClick={() => {
                  setEditing(false);
                  setShowPublished(false);
                }}
              >
                待发布草稿
              </button>
              <button
                className="plain"
                aria-pressed={showPublished}
                onClick={() => {
                  setEditing(false);
                  setShowPublished(true);
                }}
              >
                当前发布版本
              </button>
            </div>
          )}
          {editing ? (
            <form
              className="knowledge-form"
              onSubmit={(event) => {
                event.preventDefault();
                void mutate("edit");
              }}
            >
              <label>
                文档标题
                <input
                  required
                  value={title}
                  maxLength={200}
                  onChange={(event) => setTitle(event.target.value)}
                />
              </label>
              <label>
                文档正文
                <textarea
                  required
                  rows={15}
                  maxLength={120000}
                  value={content}
                  onChange={(event) => setContent(event.target.value)}
                />
              </label>
              <p className="fine-print">
                保存不会替换已发布版本，仍需草稿作者单独确认。
              </p>
              <div className="settings-actions">
                <button className="primary" disabled={busy}>
                  保存草稿
                </button>
                <button
                  className="plain"
                  type="button"
                  disabled={busy}
                  onClick={() => setEditing(false)}
                >
                  取消编辑
                </button>
              </div>
            </form>
          ) : (
            revision && (
              <DocumentText
                revision={revision}
                organizationId={organizationId}
                timezone={context.timezone}
              />
            )
          )}
          {!managing && !revision && (
            <p className="muted">当前没有可查阅的发布版本。</p>
          )}
          {row.can_edit && !managing && (
            <button
              className="secondary"
              onClick={() => {
                setManaging(true);
                setShowPublished(false);
              }}
            >
              整理这份资料
            </button>
          )}
          {row.can_edit && managing && !editing && (
            <div className="settings-actions">
              <button
                className="secondary"
                disabled={busy || (!!row.draft_id && !row.can_publish)}
                onClick={() => {
                  setEditing(true);
                  setSharing(false);
                  setAction(null);
                }}
              >
                {row.draft_id ? "编辑草稿" : "修订文档"}
              </button>
              <button
                className="plain"
                disabled={busy}
                onClick={() => {
                  setSharing(!sharing);
                  setAction(null);
                  setConfirmed(false);
                }}
              >
                修改可见范围
              </button>
            </div>
          )}
          {sharing && (
            <form
              className="knowledge-form"
              onSubmit={(event) => {
                event.preventDefault();
                void mutate("access");
              }}
            >
              <AccessFields
                value={access}
                onChange={setAccess}
                context={context}
              />
              <p className="fine-print">
                修改权限会使引用这份文档的旧分析失效。
              </p>
              <button className="secondary" disabled={busy}>
                保存可见范围
              </button>
            </form>
          )}
          {managing &&
            row.can_publish &&
            !editing &&
            !sharing &&
            !action &&
            !showPublished && (
              <section className="knowledge-confirm">
                <label className="checkbox-line">
                  <input
                    type="checkbox"
                    checked={confirmed}
                    onChange={(event) => setConfirmed(event.target.checked)}
                  />
                  我已核对全文，确认按当前可见范围发布
                </label>
                <button
                  className="primary"
                  disabled={busy || !confirmed}
                  onClick={() => void mutate("publish")}
                >
                  确认发布
                </button>
              </section>
            )}
          {row.can_edit && managing && !editing && !sharing && (
            <details className="knowledge-actions knowledge-disclosure">
              <summary>更多操作</summary>
              <div className="settings-actions">
                {row.state === "published" && (
                  <button
                    className="plain"
                    disabled={busy}
                    onClick={() => {
                      setAction("withdraw");
                      setConfirmed(false);
                    }}
                  >
                    撤回发布
                  </button>
                )}
                <button
                  className="plain"
                  disabled={busy}
                  onClick={() => {
                    setAction("delete");
                    setConfirmed(false);
                  }}
                >
                  删除文档
                </button>
              </div>
              {action && (
                <>
                  <p>
                    {action === "delete"
                      ? "删除会清除所有版本正文、原文件和检索片段，并使相关旧分析失效。"
                      : "撤回后停止共享和检索，相关旧分析失效；作者仍可查看及修订。"}
                  </p>
                  <label className="checkbox-line">
                    <input
                      type="checkbox"
                      checked={confirmed}
                      onChange={(event) => setConfirmed(event.target.checked)}
                    />
                    我确认{action === "delete" ? "删除这份文档" : "撤回发布"}
                  </label>
                  <div className="settings-actions">
                    <button
                      className="secondary"
                      disabled={busy || !confirmed}
                      onClick={() => void mutate("action")}
                    >
                      确认{action === "delete" ? "删除" : "撤回"}
                    </button>
                    <button
                      className="plain"
                      disabled={busy}
                      onClick={() => {
                        setAction(null);
                        setConfirmed(false);
                      }}
                    >
                      取消
                    </button>
                  </div>
                </>
              )}
            </details>
          )}
        </>
      )}
    </div>
  );
}

const browseCategories = [
  { value: "all", label: "全部资料" },
  { value: "organization", label: "全员共享" },
  { value: "department", label: "部门资料" },
  { value: "members", label: "指定共享" },
  { value: "private", label: "仅自己" },
] as const;
const organizeCategories = [
  { value: "my_drafts", label: "我的草稿" },
  { value: "mine", label: "我创建的" },
  { value: "my_withdrawn", label: "已撤回" },
] as const;
type BrowseCategory = (typeof browseCategories)[number]["value"];
type OrganizeCategory = (typeof organizeCategories)[number]["value"];
type CatalogResult =
  | { kind: "documents"; data: Schemas["Page_DocumentOut_"] }
  | { kind: "search"; data: Schemas["SearchOut"] };

function Catalog({
  context,
  view,
  visibility,
  query,
  onOpen,
  onSource,
}: {
  context: Context;
  view: "published" | OrganizeCategory;
  visibility: NonNullable<Access["visibility"]> | undefined;
  query: string;
  onOpen: (id: string) => void;
  onSource: (source: Schemas["Citation"]) => void;
}) {
  const [result, setResult] = useState<CatalogResult | null>(null);
  const [offset, setOffset] = useState(0);
  const [retry, setRetry] = useState(0);
  const [error, setError] = useState("");
  const generation = useRef(0);
  const searching = view === "published" && !!query;
  const limit = searching ? 10 : 12;
  const { organizationId } = context;
  useEffect(() => {
    const ticket = ++generation.current;
    setResult(null);
    setError("");
    async function load() {
      try {
        const header = { "x-organization-id": organizationId };
        const loaded: CatalogResult = searching
          ? {
              kind: "search",
              data: unwrap(
                await api(organizationId).GET("/api/v1/knowledge/search", {
                  params: {
                    header,
                    query: { q: query, visibility, offset, limit },
                  },
                }),
              ),
            }
          : {
              kind: "documents",
              data: unwrap(
                await api(organizationId).GET("/api/v1/knowledge/documents", {
                  params: {
                    header,
                    query: {
                      view,
                      visibility,
                      q: query || undefined,
                      offset,
                      limit,
                    },
                  },
                }),
              ),
            };
        if (ticket === generation.current) setResult(loaded);
      } catch (e) {
        if (ticket === generation.current)
          setError(e instanceof Error ? e.message : "读取失败");
      }
    }
    void load();
    return () => {
      generation.current++;
    };
  }, [
    organizationId,
    view,
    visibility,
    query,
    searching,
    offset,
    limit,
    retry,
  ]);
  function changePage(next: number) {
    setResult(null);
    setOffset(next);
  }
  if (error)
    return (
      <Feedback kind="error">
        {error}
        <button
          className="plain"
          onClick={() => setRetry((value) => value + 1)}
        >
          重新读取
        </button>
      </Feedback>
    );
  if (!result)
    return (
      <p className="knowledge-loading" role="status">
        正在查找资料…
      </p>
    );
  const { data } = result;
  return (
    <section
      className="knowledge-catalog"
      aria-label={searching ? "资料搜索结果" : "文档列表"}
    >
      <div className="knowledge-results-heading" role="status">
        <p>
          {query ? <>“{query}” · </> : null}
          {data.total}{" "}
          {searching
            ? "个匹配片段"
            : view === "published"
              ? "份已发布资料"
              : "份资料"}
        </p>
        {data.total > data.limit && (
          <span>
            第 {Math.floor(data.offset / data.limit) + 1} 页 / 共{" "}
            {Math.ceil(data.total / data.limit)} 页
          </span>
        )}
      </div>
      {data.items.length === 0 ? (
        <div className="knowledge-empty">
          <BookOpen size={28} aria-hidden="true" />
          <h3>
            {query
              ? "没有找到匹配的资料"
              : view === "my_drafts"
                ? "没有待发布的草稿"
                : view === "my_withdrawn"
                  ? "没有已撤回的资料"
                  : "这里还没有资料"}
          </h3>
          <p>
            {query
              ? searching
                ? "当前分类中没有匹配的已发布文档。试试其他关键词，或切换到全部资料。"
                : "当前分类中没有匹配的标题。试试更短的关键词。"
              : view === "published"
                ? "当前分类没有你可查阅的已发布资料。其他范围的资料仍按权限保留。"
                : "从「添加资料」开始，先保存草稿，核对后再发布。"}
          </p>
        </div>
      ) : result.kind === "search" ? (
        <div className="knowledge-results-list">
          {result.data.items.map((item) => (
            <article className="knowledge-result" key={item.id}>
              <button
                className="knowledge-result-title"
                onClick={() => onSource(item)}
              >
                <BookOpen size={18} aria-hidden="true" />
                <strong>{item.title}</strong>
                <ChevronRight size={16} aria-hidden="true" />
              </button>
              <blockquote>{item.excerpt}</blockquote>
              <p className="fine-print">
                已发布 · {formatTime(item.source_at, context.timezone)} · 版本{" "}
                {item.revision_number}
              </p>
            </article>
          ))}
        </div>
      ) : (
        <div className="knowledge-document-list">
          {result.data.items.map((document) => (
            <button
              key={document.id}
              className="knowledge-document-row"
              onClick={() => onOpen(document.id)}
            >
              <span className="knowledge-document-icon" aria-hidden="true">
                <FileText size={21} />
              </span>
              <span className="knowledge-document-copy">
                <strong>{document.title}</strong>
                <small>
                  {document.visibility === "department" &&
                  context.departments.find(
                    (department) => department.id === document.department_id,
                  )?.name
                    ? `${context.departments.find((department) => department.id === document.department_id)?.name} · `
                    : ""}
                  {scopeNames[document.visibility]} ·{" "}
                  {formatTime(document.updated_at, context.timezone)}
                </small>
              </span>
              <span className="knowledge-document-state">
                {stateNames[document.state] || "状态未知"}
                {view !== "published" &&
                document.state === "published" &&
                document.draft_id
                  ? " · 有新草稿"
                  : ""}
              </span>
              <ChevronRight
                className="knowledge-document-arrow"
                size={16}
                aria-hidden="true"
              />
            </button>
          ))}
        </div>
      )}
      {data.total > data.limit || data.offset > 0 ? (
        <nav
          className="knowledge-pagination"
          aria-label={searching ? "搜索结果分页" : "资料分页"}
        >
          <button
            className="plain"
            disabled={data.offset === 0}
            onClick={() => changePage(Math.max(0, data.offset - data.limit))}
          >
            上一页
          </button>
          <button
            className="plain"
            disabled={data.offset + data.limit >= data.total}
            onClick={() => changePage(data.offset + data.limit)}
          >
            下一页
          </button>
        </nav>
      ) : null}
      {result.kind === "search" && (
        <details className="knowledge-disclosure knowledge-search-scope">
          <summary>检索范围</summary>
          <p className="fine-print">{result.data.notice}</p>
        </details>
      )}
    </section>
  );
}

function KnowledgeWorkspace(context: Context) {
  const [mode, setMode] = useState<"browse" | "organize">("browse");
  const [category, setCategory] = useState<BrowseCategory>("all");
  const [organizeCategory, setOrganizeCategory] =
    useState<OrganizeCategory>("my_drafts");
  const [query, setQuery] = useState("");
  const [submittedQuery, setSubmittedQuery] = useState("");
  const [refresh, setRefresh] = useState(0);
  const [selected, setSelected] = useState<{
    id: string;
    view: "published" | "manage";
  } | null>(null);
  const [creating, setCreating] = useState(false);
  const [source, setSource] = useState<Schemas["Citation"] | null>(null);
  const view = mode === "browse" ? "published" : organizeCategory;
  const visibility =
    mode === "browse" && category !== "all" ? category : undefined;
  const refreshCatalog = () => setRefresh((value) => value + 1);
  function switchMode(next: "browse" | "organize") {
    setMode(next);
    setQuery("");
    setSubmittedQuery("");
  }
  return (
    <div className="knowledge-page knowledge-library">
      <div className="knowledge-toolbar">
        <nav className="knowledge-modes" aria-label="知识库视图">
          <button
            aria-pressed={mode === "browse"}
            onClick={() => switchMode("browse")}
          >
            查资料
          </button>
          <button
            aria-pressed={mode === "organize"}
            onClick={() => switchMode("organize")}
          >
            整理资料
          </button>
        </nav>
        <button
          className="primary knowledge-add"
          onClick={() => setCreating(true)}
        >
          <FilePlus2 size={18} aria-hidden="true" />
          添加资料
        </button>
      </div>
      <div className="knowledge-browser">
        <nav
          className="knowledge-categories"
          aria-label={mode === "browse" ? "资料共享范围" : "资料整理分类"}
        >
          {(mode === "browse" ? browseCategories : organizeCategories).map(
            (item) => (
              <button
                key={item.value}
                aria-pressed={
                  (mode === "browse" ? category : organizeCategory) ===
                  item.value
                }
                onClick={() => {
                  if (mode === "browse")
                    setCategory(item.value as BrowseCategory);
                  else setOrganizeCategory(item.value as OrganizeCategory);
                }}
              >
                {item.label}
              </button>
            ),
          )}
        </nav>
        <form
          className="knowledge-search-form"
          onSubmit={(event) => {
            event.preventDefault();
            setSubmittedQuery(query.trim());
          }}
        >
          <label className="knowledge-search-field">
            <Search size={19} aria-hidden="true" />
            <span className="sr-only">
              {mode === "browse" ? "搜索资料正文" : "搜索资料标题"}
            </span>
            <input
              type="search"
              maxLength={mode === "browse" ? 2000 : 200}
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              placeholder={
                mode === "browse" ? "搜索制度、流程或关键词" : "搜索资料标题"
              }
            />
          </label>
          <button className="secondary" type="submit">
            搜索
          </button>
          {submittedQuery && (
            <button
              className="plain"
              type="button"
              onClick={() => {
                setQuery("");
                setSubmittedQuery("");
              }}
            >
              清除搜索
            </button>
          )}
        </form>
        <p
          className="knowledge-scope-note"
          role="note"
          aria-label="当前知识库范围"
        >
          {mode === "browse"
            ? "只展示你有权查看的已发布资料。共享范围由发布者设置，私有资料不会向其他人开放。"
            : organizeCategory === "my_drafts"
              ? "这里是待你核对和发布的草稿，也包括已发布资料的新修订；草稿不会用于检索或问答。"
              : organizeCategory === "mine"
                ? "这里是你创建的资料，包括草稿、已发布和已撤回内容。"
                : "撤回的资料停止共享和检索，你仍可查看、修订后重新发布。"}
        </p>
        <Catalog
          key={`${view}:${visibility || "all"}:${submittedQuery}:${refresh}`}
          context={context}
          view={view}
          visibility={visibility}
          query={submittedQuery}
          onOpen={(id) =>
            setSelected({
              id,
              view: mode === "browse" ? "published" : "manage",
            })
          }
          onSource={setSource}
        />
      </div>
      {mode === "browse" && context.onAsk && (
        <div className="knowledge-ask-hint">
          <span>需要帮忙理解资料？</span>
          <button
            className="plain"
            onClick={() =>
              context.onAsk?.(
                submittedQuery
                  ? `帮我查找与“${submittedQuery}”相关的资料`
                  : undefined,
              )
            }
          >
            在下方输入框提问
          </button>
        </div>
      )}
      {creating && (
        <Drawer title="添加资料" close={() => setCreating(false)}>
          <NewDocument
            context={context}
            onSaved={(document) => {
              setCreating(false);
              setMode("organize");
              setOrganizeCategory("my_drafts");
              setQuery("");
              setSubmittedQuery("");
              setSelected({ id: document.id, view: "manage" });
              refreshCatalog();
            }}
          />
        </Drawer>
      )}
      {selected && (
        <Drawer
          title={selected.view === "published" ? "查阅资料" : "整理资料"}
          close={() => setSelected(null)}
        >
          <DocumentPanel
            key={`${selected.id}:${selected.view}`}
            id={selected.id}
            initialView={selected.view}
            context={context}
            onChanged={refreshCatalog}
            onDeleted={() => setSelected(null)}
          />
        </Drawer>
      )}
      {source && (
        <Drawer title="引用原文" close={() => setSource(null)}>
          <SourceView
            source={source}
            organizationId={context.organizationId}
            timezone={context.timezone}
          />
        </Drawer>
      )}
    </div>
  );
}

export function Knowledge(context: Context) {
  return (
    <KnowledgeWorkspace
      key={`${context.organizationId}:${context.memberId || ""}:${context.isOwner}`}
      {...context}
    />
  );
}
