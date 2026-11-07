import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, expect, it, vi } from "vitest";
import { Connectors } from "../components/connectors";
import { WorkDetail } from "../components/work-detail";
import type { Schemas } from "../lib/api";
const mocks = vi.hoisted(() => ({ get: vi.fn(), post: vi.fn(), put: vi.fn() }));
vi.mock("../lib/api", async (original) => ({
  ...(await original<object>()),
  api: () => ({ GET: mocks.get, POST: mocks.post, PUT: mocks.put }),
}));
const time = "2026-11-04T08:00:00Z";
const base: Schemas["ConnectorOut"] = {
  id: "c1",
  name: "项目连接",
  kind: "gitlab",
  base_url: "https://gitlab.com",
  project_key: "7",
  item_type: "issue",
  department_id: "d1",
  owner_field: null,
  status_map: {},
  key_hint: "••••1234",
  state: "saved",
  version: 1,
  tested_at: null,
  synced_at: null,
  last_error: null,
  source_count: 0,
  pending_count: 0,
};
const props = {
  organizationId: "o1",
  isOwner: true,
  timezone: "Asia/Shanghai",
  departments: [{ id: "d1", organization_id: "o1", name: "交付" }],
  members: [],
};
let rows: Schemas["ConnectorOut"][];
let tasks: Schemas["SyncOut"][];
const page = <T,>(items: T[]) => ({
  data: { items, total: items.length, offset: 0, limit: 50 },
});
beforeEach(() => {
  vi.resetAllMocks();
  rows = [];
  tasks = [];
  mocks.get.mockImplementation(async (path: string) =>
    path === "/api/v1/connectors"
      ? page(rows)
      : path.endsWith("/syncs")
        ? page(tasks)
        : page([]),
  );
  mocks.post.mockImplementation(async (path: string, options) => {
    if (path === "/api/v1/connectors") {
      rows = [{ ...base, name: options.body.name }];
      return { data: rows[0] };
    }
    if (path.endsWith("/syncs")) {
      tasks = [
        {
          id: "r1",
          connector_id: "c1",
          version: 1,
          mode: options.body.mode,
          state: "queued",
          phase: "pages",
          page: 1,
          processed: 0,
          error_code: null,
          created_at: time,
          finished_at: null,
        },
      ];
      return { data: tasks[0] };
    }
    if (path.endsWith("/state")) {
      rows = [
        {
          ...rows[0],
          state: options.body.action === "activate" ? "active" : "revoked",
          version: 3,
        },
      ];
      return { data: rows[0] };
    }
    return { data: { ...rows[0], state: "saved", version: 4 } };
  });
});
it("requires sharing acknowledgement and saves without testing or activating", async () => {
  const user = userEvent.setup();
  render(<Connectors {...props} />);
  await screen.findByText("还没有外部连接");
  await user.click(screen.getByRole("button", { name: "添加连接" }));
  await user.type(screen.getByLabelText("连接名称"), "离线验收");
  await user.type(screen.getByLabelText("项目数字 ID"), "7");
  await user.type(screen.getByLabelText("只读访问令牌"), "synthetic-secret");
  expect(
    (screen.getByRole("button", { name: "保存连接" }) as HTMLButtonElement)
      .disabled,
  ).toBe(true);
  await user.click(screen.getByRole("checkbox"));
  await user.click(screen.getByRole("button", { name: "保存连接" }));
  await screen.findByRole("button", { name: "测试连接" });
  expect(mocks.post).toHaveBeenCalledTimes(1);
  expect(mocks.post.mock.calls[0][1].body.credentials.token).toBe(
    "synthetic-secret",
  );
  expect(screen.queryByDisplayValue("synthetic-secret")).toBeNull();
  expect(screen.queryByRole("button", { name: "全量同步" })).toBeNull();
});
it("separates queued test, successful refresh, explicit activation, and sync", async () => {
  rows = [{ ...base }];
  const user = userEvent.setup();
  render(<Connectors {...props} />);
  await user.click(await screen.findByRole("button", { name: /项目连接/ }));
  await user.click(screen.getByRole("button", { name: "测试连接" }));
  await screen.findByText("测试连接 · 排队中");
  expect(
    (screen.getByRole("button", { name: "测试连接" }) as HTMLButtonElement)
      .disabled,
  ).toBe(true);
  rows = [{ ...base, state: "tested", version: 2, tested_at: time }];
  tasks = [{ ...tasks[0], state: "succeeded" }];
  await user.click(screen.getByRole("button", { name: "刷新结果" }));
  await user.click(await screen.findByRole("button", { name: "启用连接" }));
  await screen.findByRole("button", { name: "全量同步" });
  expect(
    mocks.post.mock.calls.map(
      (call) => call[1].body.action || call[1].body.mode,
    ),
  ).toEqual(["verify", "activate"]);
});
it("only owners can read settings and external sources are read-only with provenance", async () => {
  const root = render(<Connectors {...props} isOwner={false} />);
  expect(mocks.get).not.toHaveBeenCalled();
  root.unmount();
  mocks.get.mockImplementation(async (path: string) =>
    path.endsWith("/source")
      ? {
          data: {
            connector_name: "项目连接",
            external_id: "1",
            source_at: time,
            observed_at: time,
            source_url: "https://gitlab.com/demo/-/issues/1",
            last_error: null,
            kind: "gitlab",
            notice: "截止日期与支持需求未同步",
          },
        }
      : page([]),
  );
  render(
    <WorkDetail
      organizationId="o1"
      members={[]}
      timezone="Asia/Shanghai"
      onUpdated={vi.fn()}
      work={{
        id: "w1",
        organization_id: "o1",
        title: "外部任务",
        description: null,
        department_id: "d1",
        initiative_id: null,
        owner_id: null,
        lifecycle_status: "planned",
        source_authority: "external",
        needs_support: false,
        due_at: null,
        version: 2,
        updated_at: time,
      }}
    />,
  );
  expect(
    (await screen.findByRole("link", { name: "打开来源事项" })).getAttribute(
      "href",
    ),
  ).toBe("https://gitlab.com/demo/-/issues/1");
  expect(screen.queryByText("更新这项工作")).toBeNull();
  expect(screen.getByText("未同步 · 未知")).toBeTruthy();
});
it("keeps unknown state unmapped until an explicit mapping is saved", async () => {
  rows = [{ ...base, state: "active", tested_at: time }];
  const user = userEvent.setup();
  mocks.get.mockImplementation(async (path: string) =>
    path === "/api/v1/connectors"
      ? page(rows)
      : path.endsWith("/sources")
        ? page([
            {
              id: "s1",
              external_id: "1",
              title: "合成事项",
              external_state: "opened",
              assignees: [],
              work_item_id: null,
              state: "pending",
              mapping_issue: "unknown_status",
              source_at: time,
              checked_at: time,
            },
          ])
        : page([]),
  );
  mocks.put.mockResolvedValue({
    data: { ...rows[0], version: 2, status_map: { opened: "planned" } },
  });
  render(<Connectors {...props} />);
  await user.click(await screen.findByRole("button", { name: /项目连接/ }));
  const select = await screen.findByLabelText("来源状态：opened");
  expect((select as HTMLSelectElement).value).toBe("");
  await user.selectOptions(select, "planned");
  await user.click(screen.getByRole("button", { name: "保存映射" }));
  await screen.findByText("映射已保存。请全量同步，重新生成可见事项。");
  expect(mocks.put.mock.calls[0][1].body.status_map).toEqual({
    opened: "planned",
  });
  expect(mocks.post).not.toHaveBeenCalled();
});
it("requires concrete revoke confirmation and reports conflicts without claiming success", async () => {
  rows = [{ ...base, state: "active" }];
  const user = userEvent.setup();
  render(<Connectors {...props} />);
  await user.click(await screen.findByRole("button", { name: /项目连接/ }));
  await user.click(screen.getByRole("button", { name: "撤销连接" }));
  expect(mocks.post).not.toHaveBeenCalled();
  mocks.post.mockResolvedValue({
    error: { error: { message: "连接已变化，请刷新" } },
  });
  await user.click(screen.getByRole("button", { name: "确认撤销" }));
  expect((await screen.findByRole("alert")).textContent).toContain(
    "连接已变化，请刷新",
  );
  await waitFor(() =>
    expect(
      (screen.getByRole("button", { name: "全量同步" }) as HTMLButtonElement)
        .disabled,
    ).toBe(false),
  );
});
