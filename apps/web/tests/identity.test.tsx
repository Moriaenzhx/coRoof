import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, expect, it, vi } from "vitest";
import { Workspace } from "../components/workspace";
import { Setup } from "../components/setup";
import { AccountMenu } from "../components/account-menu";
import type { MembershipContext, Schemas } from "../lib/api";

const mocks = vi.hoisted(() => ({ get: vi.fn(), post: vi.fn() }));
vi.mock("../lib/api", async (original) => ({
  ...(await original<object>()),
  api: () => ({ GET: mocks.get, POST: mocks.post }),
}));
const context: MembershipContext = {
  organization: {
    id: "org",
    name: "验收企业",
    timezone: "Asia/Shanghai",
    created_at: "2026-11-04T00:00:00Z",
  },
  membership: {
    id: "owner",
    organization_id: "org",
    user_id: "user",
    name: "老板",
    roles: ["owner"],
    department_id: null,
    status: "active",
  },
};
const invitation: Schemas["InviteOut"] = {
  id: "invite",
  email: "colleague@example.com",
  department_id: "dept",
  roles: ["member"],
  expires_at: "2026-11-05T00:00:00Z",
  revoked: false,
  accepted_at: null,
  delivery_status: {
    mode: "smtp",
    state: "unknown",
    version: 3,
    attempts: 1,
    accepted_at: null,
    last_error: "delivery_unknown",
    notice: "邮件服务接受不等于收件箱送达",
  },
};
beforeEach(() => {
  vi.resetAllMocks();
  window.history.replaceState(null, "", "/");
  mocks.get.mockImplementation(async (path: string) =>
    path === "/api/v1/runtime"
      ? { data: { auth_mode: "oidc" } }
      : { response: { status: 401 } },
  );
});

it("正式登录不暴露模拟邮箱入口，并把邀请带入浏览器绑定的登录流程", async () => {
  window.history.replaceState(null, "", "/#invite=fixture-invitation-token");
  mocks.post.mockResolvedValue({
    error: { error: { message: "登录服务暂不可用" } },
  });
  const user = userEvent.setup();
  render(<Workspace />);
  await user.click(await screen.findByRole("button", { name: "安全登录" }));
  expect(mocks.post).toHaveBeenCalledWith("/api/v1/auth/oidc/start", {
    body: { invite_token: "fixture-invitation-token" },
  });
  expect(screen.queryByLabelText("你的姓名")).toBeNull();
  expect(screen.queryByText("开发模拟邮箱")).toBeNull();
  expect(await screen.findByText("登录服务暂不可用")).toBeTruthy();
});

it("无法获取登录配置时不会降级到模拟身份", async () => {
  mocks.get.mockImplementation(async (path: string) =>
    path === "/api/v1/runtime"
      ? { error: { error: { message: "服务暂不可用" } } }
      : { response: { status: 401 } },
  );
  render(<Workspace />);
  expect(
    await screen.findByText("暂时无法获取登录方式，请刷新重试。"),
  ).toBeTruthy();
  expect(screen.queryByRole("button", { name: "获取开发验证链接" })).toBeNull();
});

it("OIDC 错误只显示通用提示并移除地址栏错误标记", async () => {
  window.history.replaceState(null, "", "/?auth_error=1");
  render(<Workspace />);
  expect(await screen.findByText(/登录未完成/)).toBeTruthy();
  expect(window.location.search).toBe("");
});

it("已验证账户明确展示身份来源", () => {
  render(
    <AccountMenu
      name="老板"
      organization="企业"
      role="企业所有者"
      identityMode="oidc"
      owner
      onSelect={vi.fn()}
      onLogout={vi.fn()}
    />,
  );
  expect(screen.getByText("企业所有者 · 身份已验证")).toBeTruthy();
  expect(screen.queryByText(/开发身份/)).toBeNull();
});

it("邮件结果未知时展示原状态，用户明确确认后才重试且不会显示邀请令牌", async () => {
  mocks.get.mockResolvedValue({ data: { items: [invitation], total: 1 } });
  mocks.post.mockResolvedValue({
    data: { ...invitation.delivery_status, state: "queued", version: 4 },
  });
  const user = userEvent.setup();
  render(
    <Setup
      context={context}
      authMode="oidc"
      departments={[{ id: "dept", organization_id: "org", name: "交付" }]}
      initiatives={[]}
      members={[]}
      onUpdated={vi.fn()}
    />,
  );
  await user.click(screen.getByRole("tab", { name: "邀请成员" }));
  expect(await screen.findByText(/投递结果未知/)).toBeTruthy();
  expect(screen.queryByLabelText("邀请链接")).toBeNull();
  await user.click(screen.getByRole("button", { name: "核对后重试" }));
  expect(mocks.post).not.toHaveBeenCalled();
  await user.click(screen.getByRole("button", { name: "确认重试投递" }));
  expect(mocks.post).toHaveBeenCalledWith(
    "/api/v1/members/invitations/{invitation_id}/retry",
    expect.objectContaining({
      body: {
        expected_version: 3,
        confirm: true,
        idempotency_key: expect.any(String),
      },
    }),
  );
  expect(await screen.findByText("已重新加入投递队列。")).toBeTruthy();
});

it("邀请提交遇到网络错误时保留请求标识，重试不会创建重复邀请", async () => {
  mocks.get.mockResolvedValue({ data: { items: [], total: 0 } });
  mocks.post.mockRejectedValue(new Error("网络中断"));
  const user = userEvent.setup();
  render(
    <Setup
      context={context}
      authMode="oidc"
      departments={[{ id: "dept", organization_id: "org", name: "交付" }]}
      initiatives={[]}
      members={[]}
      onUpdated={vi.fn()}
    />,
  );
  await user.click(screen.getByRole("tab", { name: "邀请成员" }));
  await user.type(screen.getByLabelText("受邀邮箱"), "colleague@example.com");
  await user.click(screen.getByRole("button", { name: "发送邀请" }));
  expect(await screen.findByText("网络中断")).toBeTruthy();
  await user.click(screen.getByRole("button", { name: "发送邀请" }));
  await waitFor(() => expect(mocks.post).toHaveBeenCalledTimes(2));
  expect(mocks.post.mock.calls[0][1].body.idempotency_key).toBe(
    mocks.post.mock.calls[1][1].body.idempotency_key,
  );
});
