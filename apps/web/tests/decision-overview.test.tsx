import { act, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, expect, it, vi } from "vitest";
import { DecisionOverview } from "../components/decision-overview";

const get = vi.hoisted(() => vi.fn());
vi.mock("../lib/api", async (original) => ({
  ...(await original<object>()),
  api: () => ({ GET: get }),
}));
const props = {
  organizationId: "org1",
  timezone: "Asia/Shanghai",
  revision: "1",
  onMine: vi.fn(),
  onOpen: vi.fn(),
};
const result = (total: number) => ({
  data: { items: [], total, offset: 0, limit: 1 },
});
beforeEach(() => vi.resetAllMocks());

it("读取服务器本人待办总数，企业记录仅展开后读取", async () => {
  get.mockResolvedValue(result(23));
  const user = userEvent.setup();
  render(<DecisionOverview {...props} />);
  await screen.findByText("23 项待确认或待跟进，统一到“我的工作”处理。");
  expect(get).toHaveBeenCalledTimes(1);
  expect(get.mock.calls[0][1].params.query).toEqual({
    mine: true,
    view: "action_required",
    offset: 0,
    limit: 1,
  });
  await user.click(screen.getByRole("button", { name: "查看我的工作" }));
  expect(props.onMine).toHaveBeenCalledOnce();
  await user.click(screen.getByRole("button", { name: "查看企业决策记录" }));
  await waitFor(() =>
    expect(
      get.mock.calls.some(
        ([, options]) =>
          options.params.query.mine === false &&
          options.params.query.view === "all",
      ),
    ).toBe(true),
  );
});

it("读取失败不显示零待办，重试后使用真实计数", async () => {
  get
    .mockRejectedValueOnce(new Error("读取决策失败"))
    .mockResolvedValueOnce(result(0));
  const user = userEvent.setup();
  render(<DecisionOverview {...props} />);
  await screen.findByText("读取决策失败");
  expect(screen.queryByText("当前没有待确认或待跟进的决策。")).toBeNull();
  await user.click(screen.getByRole("button", { name: "重试决策待办" }));
  await screen.findByText("当前没有待确认或待跟进的决策。");
});

it("刷新后的计数不被迟到的旧请求恢复", async () => {
  let resolveOld!: (value: ReturnType<typeof result>) => void;
  get
    .mockImplementationOnce(
      () =>
        new Promise((resolve) => {
          resolveOld = resolve;
        }),
    )
    .mockResolvedValue(result(0));
  const view = render(<DecisionOverview {...props} />);
  view.rerender(<DecisionOverview {...props} revision="2" />);
  await screen.findByText("当前没有待确认或待跟进的决策。");
  await act(async () => resolveOld(result(9)));
  expect(screen.queryByText(/9 项待确认/)).toBeNull();
});
