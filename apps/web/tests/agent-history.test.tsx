import { act, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, expect, it, vi } from "vitest";
import { AgentHistory } from "../components/agent-history";
import type { Schemas } from "../lib/api";

const mocks = vi.hoisted(() => ({ get: vi.fn(), post: vi.fn() }));
vi.mock("../lib/api", async (original) => ({
  ...(await original<object>()),
  api: () => ({ GET: mocks.get, POST: mocks.post }),
}));
const time = "2026-11-05T08:00:00Z";
const run: Schemas["RunOut"] = {
  id: "run-1",
  question: "核对交付资料",
  work_item_id: "work-1",
  task: "read",
  state: "completed",
  version: 2,
  step_count: 1,
  max_steps: 6,
  error_code: null,
  steps: [],
  answer: null,
  draft: null,
  memory: null,
  created_at: time,
  deadline: time,
};
const props = {
  organizationId: "org-1",
  timezone: "Asia/Shanghai",
  revision: "one",
  onOpen: vi.fn(),
};
function deferred() {
  let resolve!: (value: { data: Schemas["RunOut"][] }) => void;
  const promise = new Promise<{ data: Schemas["RunOut"][] }>((done) => {
    resolve = done;
  });
  return { promise, resolve };
}
beforeEach(() => {
  vi.resetAllMocks();
  mocks.get.mockResolvedValue({ data: [run] });
});

it("只读取本人查询历史，点击传已有运行上下文，不创建或推进任务", async () => {
  const user = userEvent.setup();
  render(<AgentHistory {...props} />);
  await screen.findByText("核对交付资料");
  expect(mocks.get).toHaveBeenCalledExactlyOnceWith(
    "/api/v1/agent/runs",
    expect.objectContaining({
      params: {
        header: { "x-organization-id": "org-1" },
        query: { task: "read" },
      },
    }),
  );
  expect(screen.getByText(/最多显示.*最近 5 次查询/)).toBeTruthy();
  expect(screen.getByText("已完成查询")).toBeTruthy();
  expect(screen.getByText(/16:00$/).getAttribute("datetime")).toBe(time);
  await user.click(
    screen.getByRole("button", { name: "查看查询：核对交付资料" }),
  );
  expect(props.onOpen).toHaveBeenCalledWith("run-1", "work-1", "核对交付资料");
  expect(mocks.post).not.toHaveBeenCalled();
  expect(mocks.get).toHaveBeenCalledOnce();
});

it("有限最近记录不展示草稿任务或假分页，缺工作ID仍按原运行查看", async () => {
  const user = userEvent.setup();
  mocks.get.mockResolvedValue({
    data: [
      { ...run, id: "draft", question: "草稿任务", task: "work_update" },
      ...Array.from({ length: 7 }, (_, index) => ({
        ...run,
        id: `run-${index}`,
        question: `查询${index}`,
        work_item_id: null,
        state: "interrupted",
      })),
    ],
  });
  render(<AgentHistory {...props} />);
  await screen.findByText("查询0");
  expect(screen.queryByText("草稿任务")).toBeNull();
  expect(screen.getAllByRole("listitem")).toHaveLength(5);
  expect(screen.queryByText("查询5")).toBeNull();
  expect(screen.getAllByText("结果待核对")).toHaveLength(5);
  expect(screen.queryByRole("button", { name: /下一页|继续分析/ })).toBeNull();
  await user.click(screen.getByRole("button", { name: "查看查询：查询0" }));
  expect(props.onOpen).toHaveBeenCalledWith("run-0", undefined, "查询0");
  expect(mocks.post).not.toHaveBeenCalled();
});

it("切换企业时立即清旧记录，取消旧读取并拒绝迟到结果", async () => {
  const old = deferred();
  mocks.get.mockReturnValueOnce(old.promise).mockResolvedValueOnce({
    data: [{ ...run, id: "new", question: "新企业查询" }],
  });
  const view = render(<AgentHistory {...props} />);
  const signal = mocks.get.mock.calls[0][1].signal as AbortSignal;
  view.rerender(<AgentHistory {...props} organizationId="org-2" />);
  await screen.findByText("新企业查询");
  expect(signal.aborted).toBe(true);
  await act(async () => old.resolve({ data: [run] }));
  expect(screen.queryByText("核对交付资料")).toBeNull();
  expect(screen.getByText("新企业查询")).toBeTruthy();
});

it("刷新或revision变化隐藏旧记录，失权不显示旧内容，重试只GET", async () => {
  const user = userEvent.setup();
  const pending = deferred();
  const view = render(<AgentHistory {...props} />);
  await screen.findByText("核对交付资料");
  mocks.get.mockReturnValueOnce(pending.promise);
  view.rerender(<AgentHistory {...props} revision="two" />);
  expect(screen.queryByText("核对交付资料")).toBeNull();
  mocks.get.mockRejectedValueOnce(new Error("权限已变更"));
  view.rerender(<AgentHistory {...props} revision="three" />);
  await screen.findByRole("alert");
  await act(async () => pending.resolve({ data: [run] }));
  expect(screen.queryByText("核对交付资料")).toBeNull();
  expect(screen.getByText(/权限已变更/)).toBeTruthy();
  mocks.get.mockResolvedValueOnce({ data: [] });
  await user.click(screen.getByRole("button", { name: "重试查询记录" }));
  await screen.findByText(/当前没有可查看的查询记录/);
  mocks.get.mockResolvedValueOnce({ data: [run] });
  await user.click(screen.getByRole("button", { name: "刷新记录" }));
  await screen.findByText("核对交付资料");
  expect(mocks.post).not.toHaveBeenCalled();
});

it("没有企业时不读取任何记录", async () => {
  render(<AgentHistory {...props} organizationId="" />);
  expect(screen.getByText("请先选择企业。")).toBeTruthy();
  await waitFor(() => expect(mocks.get).not.toHaveBeenCalled());
});
