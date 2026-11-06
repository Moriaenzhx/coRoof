import { act, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, expect, it, vi } from "vitest";
import { Knowledge } from "../components/knowledge";
import { SourceView } from "../components/knowledge-source";
import type { Schemas } from "../lib/api";

const mocks = vi.hoisted(() => ({ get: vi.fn(), post: vi.fn() }));
vi.mock("../lib/api", async (original) => ({
  ...(await original<object>()),
  api: () => ({ GET: mocks.get, POST: mocks.post }),
}));
const time = "2026-11-04T08:00:00Z";
const document: Schemas["DocumentOut"] = {
  id: "doc1",
  title: "报销制度",
  author_id: "m1",
  visibility: "private",
  department_id: null,
  member_ids: [],
  state: "draft",
  version: 2,
  published_id: null,
  draft_id: "rev1",
  can_edit: true,
  can_publish: true,
  created_at: time,
  updated_at: time,
};
const revision: Schemas["RevisionOut"] = {
  id: "rev1",
  document_id: "doc1",
  author_id: "m1",
  number: 1,
  title: "报销制度",
  content: "报销需要发票。",
  content_hash: "hash",
  file_name: null,
  file_hash: null,
  edited_extraction: false,
  published_at: null,
  created_at: time,
  current: false,
};
const props = {
  organizationId: "o1",
  memberId: "m1",
  timezone: "Asia/Shanghai",
  isOwner: true,
  departments: [],
  members: [],
};
let rows: Schemas["DocumentOut"][];
let active: Schemas["DocumentOut"];
beforeEach(() => {
  vi.resetAllMocks();
  rows = [];
  active = { ...document };
  mocks.get.mockImplementation(async (path: string, options) => {
    if (path === "/api/v1/knowledge/documents") {
      const query = options.params.query;
      const filtered = rows.filter(
        (row) =>
          (query.view !== "published" || row.state === "published") &&
          (query.view !== "my_drafts" || row.can_publish) &&
          (!query.visibility || row.visibility === query.visibility),
      );
      return {
        data: {
          items: filtered.slice(query.offset, query.offset + query.limit),
          total: filtered.length,
          offset: query.offset,
          limit: query.limit,
        },
      };
    }
    if (path.endsWith("/revisions/{revision_id}"))
      return {
        data: {
          ...revision,
          published_at: active.published_id ? time : null,
          current: !!active.published_id,
        },
      };
    if (path.endsWith("/documents/{identifier}")) return { data: active };
    if (path.endsWith("/search"))
      return {
        data: {
          items: [],
          total: 0,
          offset: 0,
          limit: 10,
          authorized_documents: 0,
          notice: "仅检索当前有权访问的已发布版本",
        },
      };
    return { data: [] };
  });
  mocks.post.mockImplementation(async (path: string, options) => {
    if (path.endsWith("/publish"))
      active = {
        ...active,
        state: "published",
        version: 3,
        published_id: "rev1",
        draft_id: null,
        can_publish: false,
      };
    if (path.endsWith("/access"))
      active = {
        ...active,
        visibility: options.body.visibility,
        version: active.version + 1,
      };
    if (path.endsWith("/action"))
      active = {
        ...active,
        state: options.body.action === "delete" ? "deleted" : "withdrawn",
        version: active.version + 1,
      };
    rows = active.state === "deleted" ? [] : [active];
    return { data: active };
  });
});

it("saves a draft and requires author acknowledgement before publishing", async () => {
  const user = userEvent.setup();
  render(<Knowledge {...props} />);
  await screen.findByText("这里还没有资料");
  await user.click(screen.getByRole("button", { name: "添加资料" }));
  expect(screen.queryByLabelText("文档标题")).toBeNull();
  await user.click(screen.getByRole("button", { name: /直接编写/ }));
  await user.click(screen.getByText("发布后谁可以看 · 仅自己"));
  expect(
    screen
      .getAllByRole("option")
      .map((option) => [
        (option as HTMLOptionElement).value,
        option.textContent,
      ]),
  ).toEqual([
    ["private", "仅自己"],
    ["department", "部门共享"],
    ["organization", "全员共享"],
    ["members", "指定共享"],
  ]);
  await user.type(screen.getByLabelText("文档标题"), "报销制度");
  await user.type(screen.getByLabelText("文档正文"), "报销需要发票。");
  await user.click(screen.getByRole("button", { name: "保存草稿" }));
  const publish = await screen.findByRole("button", { name: "确认发布" });
  expect((publish as HTMLButtonElement).disabled).toBe(true);
  expect(mocks.post).toHaveBeenCalledTimes(1);
  expect(mocks.post.mock.calls[0][1].body.visibility).toBe("private");
  await user.click(
    screen.getByRole("checkbox", {
      name: "我已核对全文，确认按当前可见范围发布",
    }),
  );
  await user.click(publish);
  await user.click(await screen.findByText("更多操作"));
  await screen.findByRole("button", { name: "撤回发布" });
  expect(mocks.post.mock.calls[1][1].body).toEqual(
    expect.objectContaining({
      confirm: true,
      revision_id: "rev1",
      expected_version: 2,
    }),
  );
});

it("shows no matching data and does not substitute a model answer", async () => {
  const user = userEvent.setup();
  render(<Knowledge {...props} />);
  await user.type(
    screen.getByRole("searchbox", { name: "搜索资料正文" }),
    "未提供的收款数据",
  );
  await user.click(screen.getByRole("button", { name: "搜索" }));
  await screen.findByText(/没有匹配的已发布文档/);
  expect(mocks.post).not.toHaveBeenCalled();
});

it("requires a separate confirmation before deleting and clears the document list", async () => {
  rows = [active];
  const user = userEvent.setup();
  render(<Knowledge {...props} />);
  await user.click(screen.getByRole("button", { name: "整理资料" }));
  await user.click(await screen.findByRole("button", { name: /报销制度/ }));
  await user.click(await screen.findByText("更多操作"));
  await user.click(await screen.findByRole("button", { name: "删除文档" }));
  const button = screen.getByRole("button", { name: "确认删除" });
  expect((button as HTMLButtonElement).disabled).toBe(true);
  await user.click(
    screen.getByRole("checkbox", { name: "我确认删除这份文档" }),
  );
  await user.click(button);
  await screen.findByText("没有待发布的草稿");
  expect(screen.queryByRole("dialog")).toBeNull();
});

it("keeps edited text for a version conflict, without auto-confirming", async () => {
  rows = [active];
  const user = userEvent.setup();
  render(<Knowledge {...props} />);
  await user.click(screen.getByRole("button", { name: "整理资料" }));
  await user.click(await screen.findByRole("button", { name: /报销制度/ }));
  await user.click(await screen.findByRole("button", { name: "编辑草稿" }));
  mocks.post.mockResolvedValue({
    error: { error: { message: "文档已变化，请刷新后重试" } },
  });
  await user.clear(screen.getByLabelText("文档正文"));
  await user.type(screen.getByLabelText("文档正文"), "保留我的修改");
  await user.click(screen.getByRole("button", { name: "保存草稿" }));
  await screen.findByText("文档已变化，请刷新后重试");
  expect(screen.getByDisplayValue("保留我的修改")).toBeTruthy();
  expect(mocks.post).toHaveBeenCalledTimes(1);
});

it("rechecks citation access and does not render the cached excerpt after revocation", async () => {
  mocks.get.mockResolvedValue({
    error: { error: { message: "未找到此文档" } },
  });
  render(
    <SourceView
      organizationId="o1"
      timezone="Asia/Shanghai"
      source={{
        document_id: "doc1",
        revision_id: "rev1",
      }}
    />,
  );
  await screen.findByText("未找到此文档");
  expect(screen.queryByText("撤权的敏感原文")).toBeNull();
  await waitFor(() => expect(mocks.get).toHaveBeenCalledTimes(1));
});

it("does not offer company sharing to a regular member", async () => {
  const user = userEvent.setup();
  render(<Knowledge {...props} isOwner={false} />);
  await user.click(screen.getByRole("button", { name: "添加资料" }));
  await user.click(screen.getByRole("button", { name: /直接编写/ }));
  await user.click(screen.getByText(/发布后谁可以看/));
  expect(screen.queryByRole("option", { name: "全员共享" })).toBeNull();
});

it("lets a regular employee browse and read an authorized shared document without granting editing rights", async () => {
  active = {
    ...document,
    visibility: "organization",
    state: "published",
    draft_id: null,
    published_id: "rev1",
    can_edit: false,
    can_publish: false,
  };
  rows = [active];
  const user = userEvent.setup();
  render(<Knowledge {...props} isOwner={false} />);
  expect(
    screen.getByRole("note", { name: "当前知识库范围" }).textContent,
  ).toContain("只展示你有权查看的已发布资料");
  expect(screen.getByRole("button", { name: "搜索" })).toBeTruthy();
  await user.click(await screen.findByRole("button", { name: /报销制度/ }));
  expect(await screen.findByText("报销需要发票。")).toBeTruthy();
  expect(screen.queryByRole("button", { name: "编辑草稿" })).toBeNull();
  expect(screen.queryByRole("button", { name: "确认发布" })).toBeNull();
  expect(screen.queryByRole("button", { name: "删除文档" })).toBeNull();
  expect(mocks.get).toHaveBeenCalledWith(
    "/api/v1/knowledge/documents/{identifier}",
    expect.objectContaining({
      params: {
        header: { "x-organization-id": "o1" },
        path: { identifier: "doc1" },
      },
    }),
  );
  expect(mocks.post).not.toHaveBeenCalled();
});

it("starts with published reading and separates drafts and organizing searches", async () => {
  rows = [active];
  const user = userEvent.setup();
  render(<Knowledge {...props} />);
  await screen.findByText("这里还没有资料");
  expect(screen.queryByRole("button", { name: /报销制度/ })).toBeNull();
  expect(mocks.get).toHaveBeenLastCalledWith(
    "/api/v1/knowledge/documents",
    expect.objectContaining({
      params: expect.objectContaining({
        query: expect.objectContaining({ view: "published", offset: 0 }),
      }),
    }),
  );
  await user.click(screen.getByRole("button", { name: "整理资料" }));
  expect(await screen.findByRole("button", { name: /报销制度/ })).toBeTruthy();
  expect(
    screen
      .getByRole("button", { name: "我的草稿" })
      .getAttribute("aria-pressed"),
  ).toBe("true");
  await user.type(
    screen.getByRole("searchbox", { name: "搜索资料标题" }),
    "报销",
  );
  await user.keyboard("{Enter}");
  await waitFor(() =>
    expect(mocks.get).toHaveBeenLastCalledWith(
      "/api/v1/knowledge/documents",
      expect.objectContaining({
        params: expect.objectContaining({
          query: expect.objectContaining({
            view: "my_drafts",
            q: "报销",
            offset: 0,
          }),
        }),
      }),
    ),
  );
  await user.click(screen.getByRole("button", { name: "已撤回" }));
  await waitFor(() =>
    expect(mocks.get).toHaveBeenLastCalledWith(
      "/api/v1/knowledge/documents",
      expect.objectContaining({
        params: expect.objectContaining({
          query: expect.objectContaining({
            view: "my_withdrawn",
            q: "报销",
            offset: 0,
          }),
        }),
      }),
    ),
  );
  expect(mocks.post).not.toHaveBeenCalled();
});

function hit(title: string): Schemas["Citation"] {
  return {
    id: title,
    document_id: "doc1",
    revision_id: "rev1",
    revision_number: 1,
    title,
    excerpt: `${title}的授权原文`,
    start_offset: 0,
    end_offset: 12,
    source_at: time,
    file_name: null,
  };
}
function searchResult(title: string, offset = 0, total = 21) {
  return {
    data: {
      items: [hit(title)],
      total,
      offset,
      limit: 10,
      authorized_documents: 3,
      notice: "仅检索当前有权访问的已发布版本",
    },
  };
}

it("paginates the submitted search snapshot and asks the server to filter before paging", async () => {
  const original = mocks.get.getMockImplementation()!;
  mocks.get.mockImplementation((path, options) =>
    path.endsWith("/search")
      ? Promise.resolve(searchResult("匹配资料", options.params.query.offset))
      : original(path, options),
  );
  const user = userEvent.setup();
  render(<Knowledge {...props} />);
  await user.click(screen.getByRole("button", { name: "全员共享" }));
  const input = screen.getByRole("searchbox", { name: "搜索资料正文" });
  await user.type(input, "报销");
  await user.keyboard("{Enter}");
  await screen.findByRole("button", { name: "匹配资料" });
  await user.clear(input);
  await user.type(input, "尚未提交的新问题");
  await user.click(screen.getByRole("button", { name: "下一页" }));
  await waitFor(() =>
    expect(mocks.get).toHaveBeenLastCalledWith("/api/v1/knowledge/search", {
      params: {
        header: { "x-organization-id": "o1" },
        query: { q: "报销", visibility: "organization", offset: 10, limit: 10 },
      },
    }),
  );
  await user.click(screen.getByRole("button", { name: "部门资料" }));
  await waitFor(() =>
    expect(mocks.get).toHaveBeenLastCalledWith("/api/v1/knowledge/search", {
      params: {
        header: { "x-organization-id": "o1" },
        query: { q: "报销", visibility: "department", offset: 0, limit: 10 },
      },
    }),
  );
  expect(screen.getByDisplayValue("尚未提交的新问题")).toBeTruthy();
  expect(mocks.post).not.toHaveBeenCalled();
});

it("discards late search results after changing the sharing category", async () => {
  let finish: (result: ReturnType<typeof searchResult>) => void = () => {};
  const oldSearch = new Promise((resolve) => {
    finish = resolve;
  });
  const original = mocks.get.getMockImplementation()!;
  mocks.get.mockImplementation((path, options) =>
    path.endsWith("/search")
      ? options.params.query.visibility === "department"
        ? Promise.resolve(searchResult("部门中的新结果", 0, 1))
        : oldSearch
      : original(path, options),
  );
  const user = userEvent.setup();
  render(<Knowledge {...props} />);
  await user.type(
    screen.getByRole("searchbox", { name: "搜索资料正文" }),
    "流程",
  );
  await user.keyboard("{Enter}");
  await user.click(screen.getByRole("button", { name: "部门资料" }));
  await screen.findByRole("button", { name: "部门中的新结果" });
  await act(async () => finish(searchResult("旧范围迟到结果", 0, 1)));
  expect(screen.queryByText("旧范围迟到结果")).toBeNull();
  expect(screen.getByRole("button", { name: "部门中的新结果" })).toBeTruthy();
});

it("clears searches and forms on organization or member changes without displaying late old data", async () => {
  let finish: (result: ReturnType<typeof searchResult>) => void = () => {};
  const oldSearch = new Promise((resolve) => {
    finish = resolve;
  });
  const original = mocks.get.getMockImplementation()!;
  mocks.get.mockImplementation((path, options) =>
    path.endsWith("/search") ? oldSearch : original(path, options),
  );
  const user = userEvent.setup();
  const { rerender } = render(<Knowledge {...props} />);
  await user.type(
    screen.getByRole("searchbox", { name: "搜索资料正文" }),
    "旧企业问题",
  );
  await user.keyboard("{Enter}");
  await user.click(screen.getByRole("button", { name: "添加资料" }));
  await user.click(screen.getByRole("button", { name: /直接编写/ }));
  await user.type(screen.getByLabelText("文档标题"), "旧身份未保存草稿");
  rerender(<Knowledge {...props} memberId="m2" />);
  expect(screen.queryByRole("dialog")).toBeNull();
  expect(
    (
      screen.getByRole("searchbox", {
        name: "搜索资料正文",
      }) as HTMLInputElement
    ).value,
  ).toBe("");
  await act(async () => finish(searchResult("旧身份的私有结果", 0, 1)));
  expect(screen.queryByText("旧身份的私有结果")).toBeNull();
  rerender(<Knowledge {...props} organizationId="o2" memberId="m2" />);
  await waitFor(() =>
    expect(mocks.get).toHaveBeenLastCalledWith(
      "/api/v1/knowledge/documents",
      expect.objectContaining({
        params: expect.objectContaining({
          header: { "x-organization-id": "o2" },
          query: expect.objectContaining({ view: "published", offset: 0 }),
        }),
      }),
    ),
  );
  expect(mocks.post).not.toHaveBeenCalled();
});

it("reads the published version first even when its author has an unpublished revision", async () => {
  active = {
    ...document,
    state: "published",
    published_id: "published1",
    draft_id: "draft2",
  };
  rows = [active];
  const original = mocks.get.getMockImplementation()!;
  mocks.get.mockImplementation((path, options) =>
    path.endsWith("/revisions/{revision_id}")
      ? Promise.resolve({
          data: {
            ...revision,
            id: options.params.path.revision_id,
            content:
              options.params.path.revision_id === "published1"
                ? "当前生效的原文。"
                : "尚待本人发布的草稿。",
          },
        })
      : original(path, options),
  );
  const user = userEvent.setup();
  render(<Knowledge {...props} />);
  await user.click(await screen.findByRole("button", { name: /报销制度/ }));
  await screen.findByText("当前生效的原文。");
  expect(screen.queryByText("尚待本人发布的草稿。")).toBeNull();
  expect(screen.queryByRole("button", { name: "确认发布" })).toBeNull();
  await user.click(screen.getByRole("button", { name: "整理这份资料" }));
  await screen.findByText("尚待本人发布的草稿。");
  expect(
    (screen.getByRole("button", { name: "确认发布" }) as HTMLButtonElement)
      .disabled,
  ).toBe(true);
  expect(mocks.post).not.toHaveBeenCalled();
});

it("offers import and writing from one entry without automatically creating or publishing", async () => {
  const user = userEvent.setup();
  render(<Knowledge {...props} />);
  expect(screen.queryByLabelText("选择文件")).toBeNull();
  expect(screen.queryByLabelText("文档正文")).toBeNull();
  await user.click(screen.getByRole("button", { name: "添加资料" }));
  await user.click(screen.getByRole("button", { name: /导入文件/ }));
  expect(screen.getByLabelText("选择文件").getAttribute("accept")).toBe(
    ".txt,.md,.pdf,.docx",
  );
  expect(screen.queryByLabelText("文档正文")).toBeNull();
  expect(screen.getByText(/扫描 PDF 暂不支持/)).toBeTruthy();
  await user.click(screen.getByRole("button", { name: "重新选择添加方式" }));
  await user.click(screen.getByRole("button", { name: /直接编写/ }));
  expect(screen.getByLabelText("文档正文")).toBeTruthy();
  expect(mocks.post).not.toHaveBeenCalled();
});

it("hands questions to the single global input without opening an assistant or sending", async () => {
  const onAsk = vi.fn();
  const user = userEvent.setup();
  render(<Knowledge {...props} onAsk={onAsk} />);
  await user.click(screen.getByRole("button", { name: "在下方输入框提问" }));
  expect(onAsk).toHaveBeenCalledWith(undefined);
  expect(screen.queryByRole("dialog")).toBeNull();
  expect(mocks.post).not.toHaveBeenCalled();
});

it("does not let a late initial catalog replace an explicitly submitted search", async () => {
  let finish: (result: unknown) => void = () => {};
  const delayedCatalog = new Promise((resolve) => {
    finish = resolve;
  });
  mocks.get.mockImplementation((path) =>
    path.endsWith("/search")
      ? Promise.resolve(searchResult("刚刚提交的搜索结果", 0, 1))
      : delayedCatalog,
  );
  const user = userEvent.setup();
  render(<Knowledge {...props} />);
  await user.type(
    screen.getByRole("searchbox", { name: "搜索资料正文" }),
    "报销",
  );
  await user.keyboard("{Enter}");
  await screen.findByRole("button", { name: "刚刚提交的搜索结果" });
  await act(async () =>
    finish({ data: { items: [document], total: 1, offset: 0, limit: 12 } }),
  );
  expect(screen.queryByRole("button", { name: /报销制度/ })).toBeNull();
  expect(
    screen.getByRole("button", { name: "刚刚提交的搜索结果" }),
  ).toBeTruthy();
});

it("stops an unfinished file read from importing after the member changes", async () => {
  let finish: (result: ArrayBuffer) => void = () => {};
  const fileBytes = new Promise<ArrayBuffer>((resolve) => {
    finish = resolve;
  });
  const file = new File(["合成导入内容"], "合成测试.txt", {
    type: "text/plain",
  });
  Object.defineProperty(file, "arrayBuffer", { value: () => fileBytes });
  const user = userEvent.setup();
  const { rerender } = render(<Knowledge {...props} />);
  await user.click(screen.getByRole("button", { name: "添加资料" }));
  await user.click(screen.getByRole("button", { name: /导入文件/ }));
  await user.upload(screen.getByLabelText("选择文件"), file);
  expect(screen.getByDisplayValue("合成测试")).toBeTruthy();
  await user.click(screen.getByRole("button", { name: "保存草稿" }));
  rerender(<Knowledge {...props} memberId="new-member" />);
  await act(async () => finish(new ArrayBuffer(4)));
  expect(mocks.post).not.toHaveBeenCalled();
  expect(screen.queryByRole("dialog")).toBeNull();
});
