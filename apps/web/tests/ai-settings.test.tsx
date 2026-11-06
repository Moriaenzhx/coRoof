import { act, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { AccountMenu } from "../components/account-menu";
import { AiSettings } from "../components/ai-settings";
import type { Schemas } from "../lib/api";

const mocks = vi.hoisted(() => ({ get: vi.fn(), post: vi.fn(), put: vi.fn() }));
vi.mock("../lib/api", async (original) => ({
  ...(await original<object>()),
  api: () => ({ GET: mocks.get, POST: mocks.post, PUT: mocks.put }),
}));
const time = "2026-11-04T08:00:00Z";
const usage: Schemas["UsageOut"] = {
  scope: "organization",
  start: time,
  end: time,
  calls: 2,
  business_tasks: 1,
  test_calls: 1,
  succeeded: 1,
  failed: 1,
  pending_or_unknown: 0,
  input_tokens: 10,
  output_tokens: 5,
  unknown_usage_calls: 1,
  average_latency_ms: null,
  quota_occupied_tokens: 2500,
  monthly_token_limit: 6000000,
  alert: false,
  cost: null,
  cost_notice: "尚未对账",
  daily: [],
  models: [],
};
const policy: Schemas["PolicyOut"] = {
  version: 0,
  mode: "platform",
  connection_id: null,
  daily_call_limit: 100,
  daily_token_limit: 200000,
  monthly_token_limit: 6000000,
  concurrency_limit: 2,
  alert_percent: 80,
  credential_storage_ready: true,
  platform_ready: false,
  platform_model: null,
  platform_provider: "rules",
  allowed_custom_base_urls: [],
};
const providers: Schemas["ProviderOut"][] = [
  {
    id: "openai",
    label: "OpenAI",
    base_url: "https://api.openai.com/v1",
    protocol: "responses",
    output_mode: "schema",
  },
  {
    id: "deepseek",
    label: "DeepSeek",
    base_url: "https://api.deepseek.com/v1",
    protocol: "chat",
    output_mode: "json",
  },
  {
    id: "bailian",
    label: "阿里云百炼 / Qwen",
    base_url: "https://dashscope.aliyuncs.com/compatible-mode/v1",
    protocol: "chat",
    output_mode: "schema",
  },
];
const connection: Schemas["ConnectionOut"] = {
  id: "c1",
  name: "企业主用",
  provider: "deepseek",
  model: "model-fixture",
  base_url: "https://api.deepseek.com/v1",
  output_mode: "json",
  key_hint: "••••real",
  state: "draft",
  version: 1,
  tested_at: null,
  last_error: null,
  usage_scope: "application",
  usage_notice: null,
  can_test: true,
  can_activate: false,
};
let rows: Schemas["ConnectionOut"][];
let currentPolicy: Schemas["PolicyOut"];
const props = {
  organizationId: "o1",
  isOwner: true,
  timezone: "Asia/Shanghai",
};
beforeEach(() => {
  vi.resetAllMocks();
  rows = [];
  currentPolicy = { ...policy };
  mocks.get.mockImplementation(async (path: string) => ({
    data: path.endsWith("/usage")
      ? usage
      : path.endsWith("/settings")
        ? currentPolicy
        : path.endsWith("/connections")
          ? rows
          : path.endsWith("/providers")
            ? providers
            : [],
  }));
});

describe("账户菜单与企业 AI 管理", () => {
  it("已保存的开发配置可见且脱敏，可以另配业务 Key，不会误启用", async () => {
    const user = userEvent.setup();
    rows = [
      {
        ...connection,
        name: "百炼原测试配置",
        provider: "bailian",
        model: "qwen3.7-plus",
        base_url: "https://coding.dashscope.aliyuncs.com/v1",
        state: "tested",
        tested_at: time,
        usage_scope: "development_only",
        usage_notice: "Coding Plan 凭据已保存，未启用企业业务调用。",
        can_test: false,
        can_activate: false,
      },
    ];
    render(<AiSettings {...props} initialTab="connections" />);
    await screen.findByText("百炼原测试配置");
    expect(screen.getByText(rows[0].base_url)).toBeTruthy();
    expect(screen.getByText(/API Key ••••real/)).toBeTruthy();
    expect(screen.queryByRole("button", { name: "确认启用" })).toBeNull();
    expect(screen.queryByRole("button", { name: "测试连接" })).toBeNull();
    expect(mocks.post).not.toHaveBeenCalled();
    await user.click(screen.getByRole("button", { name: "配置业务 API Key" }));
    expect((screen.getByLabelText("API Key") as HTMLInputElement).value).toBe(
      "",
    );
    expect((screen.getByLabelText("API 端点") as HTMLInputElement).value).toBe(
      "https://dashscope.aliyuncs.com/compatible-mode/v1",
    );
    expect((screen.getByLabelText("模型 ID") as HTMLInputElement).value).toBe(
      "qwen3.7-plus",
    );
    expect(screen.getByText("百炼原测试配置")).toBeTruthy();
    expect(mocks.put).not.toHaveBeenCalled();
  });

  it("服务器允许的开发连接显式测试后才能启用，始终标为本机测试而非生产", async () => {
    const user = userEvent.setup();
    rows = [
      {
        ...connection,
        name: "星桥本机测试连接",
        provider: "bailian",
        base_url: "https://coding.dashscope.aliyuncs.com/v1",
        usage_scope: "development_only",
        usage_notice:
          "部署配置仅允许本企业此连接用于本机开发测试，不用于生产或后台常驻任务。",
        can_test: true,
        can_activate: false,
      },
    ];
    mocks.post.mockImplementation(async () => {
      rows = [
        {
          ...rows[0],
          state: "tested",
          version: 2,
          tested_at: time,
          can_activate: true,
        },
      ];
      return { data: rows[0] };
    });
    mocks.put.mockImplementation(async (_path, { body }) => {
      currentPolicy = { ...policy, ...body, version: 1 };
      return { data: currentPolicy };
    });
    render(<AiSettings {...props} initialTab="connections" />);
    await screen.findByText("星桥本机测试连接");
    expect(
      screen.getByText(/^本机开发测试 · 待测试 · 不用于生产/),
    ).toBeTruthy();
    expect(screen.getByText(rows[0].usage_notice!)).toBeTruthy();
    expect(mocks.post).not.toHaveBeenCalled();
    const activate = screen.getByRole("button", {
      name: "确认启用本机测试",
    }) as HTMLButtonElement;
    expect(activate.disabled).toBe(true);
    await user.click(activate);
    expect(mocks.put).not.toHaveBeenCalled();
    await user.click(screen.getByRole("button", { name: "测试连接（本机）" }));
    await screen.findByText(
      "本机开发测试连接已通过。确认后仅用于本机测试，不用于生产。",
    );
    expect(mocks.post).toHaveBeenCalledExactlyOnceWith(
      "/api/v1/ai/connections/{connection_id}/test",
      expect.objectContaining({
        params: {
          header: { "x-organization-id": "o1" },
          path: { connection_id: "c1" },
        },
        body: { expected_version: 1, idempotency_key: expect.any(String) },
      }),
    );
    expect(mocks.put).not.toHaveBeenCalled();
    expect(activate.disabled).toBe(false);
    await user.click(activate);
    await screen.findByText("本机测试使用中");
    expect(
      screen.getByText("本机开发测试已启用，不用于生产或后台常驻任务。"),
    ).toBeTruthy();
    expect(
      screen.getByText("当前：本机开发测试（不用于生产） · 星桥本机测试连接"),
    ).toBeTruthy();
    expect(mocks.put).toHaveBeenCalledExactlyOnceWith(
      "/api/v1/ai/settings",
      expect.objectContaining({
        params: { header: { "x-organization-id": "o1" } },
        body: expect.objectContaining({
          mode: "byok",
          connection_id: "c1",
          expected_version: 0,
        }),
      }),
    );
  });

  it("开发连接的测试与启用分别服从服务器能力，刷新撤回能力后仅可管理", async () => {
    const user = userEvent.setup();
    rows = [
      {
        ...connection,
        name: "已通过的本机测试连接",
        usage_scope: "development_only",
        state: "tested",
        tested_at: time,
        can_test: false,
        can_activate: true,
        usage_notice: "本机开发测试，不用于生产。",
      },
    ];
    render(<AiSettings {...props} initialTab="connections" />);
    await screen.findByText("已通过的本机测试连接");
    expect(
      (
        screen.getByRole("button", {
          name: "测试连接（本机）",
        }) as HTMLButtonElement
      ).disabled,
    ).toBe(true);
    expect(
      (
        screen.getByRole("button", {
          name: "确认启用本机测试",
        }) as HTMLButtonElement
      ).disabled,
    ).toBe(false);
    rows = [
      {
        ...rows[0],
        can_activate: false,
        usage_notice: "开发测试许可已移除，仅供查看与管理。",
      },
    ];
    await user.click(screen.getByRole("button", { name: "刷新 AI 使用情况" }));
    await screen.findByText("开发测试许可已移除，仅供查看与管理。");
    expect(
      screen.queryByRole("button", { name: "测试连接（本机）" }),
    ).toBeNull();
    expect(
      screen.queryByRole("button", { name: "确认启用本机测试" }),
    ).toBeNull();
    expect(
      screen.getByRole("button", { name: "配置业务 API Key" }),
    ).toBeTruthy();
    expect(screen.getByRole("button", { name: "撤销" })).toBeTruthy();
    expect(mocks.post).not.toHaveBeenCalled();
    expect(mocks.put).not.toHaveBeenCalled();
  });

  it("已选开发连接被服务器限制后不继续宣称正在使用", async () => {
    rows = [
      {
        ...connection,
        name: "历史本机配置",
        usage_scope: "development_only",
        state: "tested",
        tested_at: time,
        can_test: false,
        can_activate: false,
        usage_notice: "此连接当前仅供查看与管理。",
      },
    ];
    currentPolicy = { ...policy, mode: "byok", connection_id: "c1" };
    render(<AiSettings {...props} initialTab="connections" />);
    await screen.findByText("已选连接 · 当前不可用");
    expect(screen.queryByText("本机测试使用中")).toBeNull();
    expect(
      screen.queryByRole("button", { name: "确认启用本机测试" }),
    ).toBeNull();
    expect(mocks.post).not.toHaveBeenCalled();
    expect(mocks.put).not.toHaveBeenCalled();
  });

  it("老板粘贴 Coding Plan Key 后可登记保存，刷新仍可见，不触发模型调用", async () => {
    const user = userEvent.setup();
    mocks.post.mockImplementation(async (_path, { body }) => {
      rows = [
        {
          ...connection,
          name: body.name,
          provider: body.provider,
          model: body.model,
          base_url: body.base_url,
          output_mode: body.output_mode,
          usage_scope: "development_only",
          can_test: false,
          can_activate: false,
          usage_notice: "仅登记管理，未启用企业业务调用。",
        },
      ];
      return { data: rows[0] };
    });
    const view = render(<AiSettings {...props} initialTab="connections" />);
    await screen.findByText("已保存的 API 连接");
    await user.click(
      screen.getByRole("button", { name: "配置自己的 API Key" }),
    );
    await user.selectOptions(screen.getByLabelText("供应商"), "bailian");
    await user.type(screen.getByLabelText("连接名称"), "我保存的百炼配置");
    await user.type(screen.getByLabelText("模型 ID"), "qwen3.7-plus");
    await user.type(
      screen.getByLabelText("API Key"),
      "sk-sp-test-only-fixture",
    );
    expect(
      (screen.getByLabelText("百炼凭据用途") as HTMLSelectElement).value,
    ).toBe("development");
    await user.click(screen.getByRole("button", { name: "保存开发凭据" }));
    await screen.findByText(
      "开发凭据已保存，可在下方查看和管理；尚未启用业务调用。",
    );
    view.unmount();
    render(<AiSettings {...props} initialTab="connections" />);
    await screen.findByText("我保存的百炼配置");
    expect(mocks.post.mock.calls.map((call) => call[0])).toEqual([
      "/api/v1/ai/connections",
    ]);
    expect(mocks.put).not.toHaveBeenCalled();
    expect(screen.queryByText("sk-sp-test-only-fixture")).toBeNull();
  });

  it("菜单支持键盘、关闭后恢复焦点，并按角色显示企业入口", async () => {
    const user = userEvent.setup();
    const onSelect = vi.fn(),
      onLogout = vi.fn();
    const menu = {
      name: "测试用户",
      role: "所有者",
      organization: "测试企业",
      owner: true,
      onSelect,
      onLogout,
    };
    const view = render(<AccountMenu {...menu} />);
    const trigger = screen.getByRole("button", { name: "打开账户菜单" });
    await user.click(trigger);
    expect(document.activeElement?.textContent).toContain("AI 使用情况");
    await user.keyboard("{ArrowDown}{ArrowDown}");
    expect(document.activeElement?.textContent).toContain("企业 AI 设置");
    await user.keyboard("{Enter}");
    expect(onSelect).toHaveBeenCalledWith("ai-settings", "connections");
    expect(document.activeElement).toBe(trigger);
    view.rerender(<AccountMenu {...menu} owner={false} />);
    await user.click(trigger);
    expect(screen.queryByRole("menuitem", { name: "企业 AI 设置" })).toBeNull();
    await user.keyboard("{End}{Enter}");
    expect(onLogout).toHaveBeenCalledOnce();
  });

  it("成员只请求本人用量，未知费用和缺失用量不会显示成余额", async () => {
    render(<AiSettings {...props} isOwner={false} />);
    await screen.findByText("尚未核算");
    expect(screen.getByText("1 次调用用量未知")).toBeTruthy();
    expect(screen.queryByRole("tab", { name: "AI 服务" })).toBeNull();
    expect(mocks.get.mock.calls.map((call) => call[0])).toEqual([
      "/api/v1/ai/usage",
    ]);
    expect(mocks.get.mock.calls[0][1].params.header["x-organization-id"]).toBe(
      "o1",
    );
  });

  it("保存、测试、启用各自确认，网络重试复用标识且凭据不留在输入框", async () => {
    const user = userEvent.setup();
    mocks.post.mockResolvedValueOnce({
      error: { error: { message: "连接中断" } },
    });
    mocks.post.mockImplementationOnce(async () => {
      rows = [{ ...connection }];
      return { data: rows[0] };
    });
    render(<AiSettings {...props} />);
    await screen.findByText("尚未核算");
    await user.click(screen.getByRole("tab", { name: "AI 服务" }));
    await user.click(
      screen.getByRole("button", { name: "配置自己的 API Key" }),
    );
    await user.selectOptions(screen.getByLabelText("供应商"), "deepseek");
    expect((screen.getByLabelText("API 端点") as HTMLInputElement).value).toBe(
      connection.base_url,
    );
    expect((screen.getByLabelText("输出模式") as HTMLSelectElement).value).toBe(
      "json",
    );
    await user.type(screen.getByLabelText("连接名称"), connection.name);
    await user.type(screen.getByLabelText("模型 ID"), connection.model);
    await user.type(screen.getByLabelText("API Key"), "fixture-not-real");
    await user.click(screen.getByRole("button", { name: "保存待测试连接" }));
    await screen.findByText("连接中断");
    await user.click(screen.getByRole("button", { name: "保存待测试连接" }));
    await screen.findByText("连接已保存，请先测试，再明确启用。");
    expect(mocks.post.mock.calls[0][1].body).toEqual(
      mocks.post.mock.calls[1][1].body,
    );
    expect(mocks.put).not.toHaveBeenCalled();
    expect(screen.queryByLabelText("API Key")).toBeNull();
    expect(
      screen.getByRole("button", { name: "确认启用" }).hasAttribute("disabled"),
    ).toBe(true);
    mocks.post.mockImplementationOnce(async () => {
      rows = [
        {
          ...connection,
          state: "tested",
          version: 2,
          tested_at: time,
          can_activate: true,
        },
      ];
      return { data: rows[0] };
    });
    await user.click(screen.getByRole("button", { name: "测试连接" }));
    await screen.findByText("连接测试通过。确认后可启用此连接。");
    expect(mocks.put).not.toHaveBeenCalled();
    mocks.put.mockImplementationOnce(async (_path, { body }) => {
      currentPolicy = { ...policy, ...body, version: 1 };
      return { data: currentPolicy };
    });
    await user.click(screen.getByRole("button", { name: "确认启用" }));
    await screen.findByText("使用中");
    expect(mocks.put.mock.calls[0][1].body).toMatchObject({
      mode: "byok",
      connection_id: "c1",
      expected_version: 0,
    });
    await user.click(
      screen.getByRole("button", { name: "配置自己的 API Key" }),
    );
    expect((screen.getByLabelText("API Key") as HTMLInputElement).value).toBe(
      "",
    );
  });

  it("测试响应丢失后重试沿用请求标识，撤销需要明确确认", async () => {
    const user = userEvent.setup();
    rows = [{ ...connection }];
    mocks.post.mockRejectedValue(new Error("网络错误"));
    render(<AiSettings {...props} />);
    await screen.findByText("尚未核算");
    await user.click(screen.getByRole("tab", { name: "AI 服务" }));
    await user.click(screen.getByRole("button", { name: "测试连接" }));
    await screen.findByText("网络错误");
    await user.click(screen.getByRole("button", { name: "测试连接" }));
    await waitFor(() => expect(mocks.post).toHaveBeenCalledTimes(2));
    expect(mocks.post.mock.calls[0][1].body).toEqual(
      mocks.post.mock.calls[1][1].body,
    );
    await user.click(screen.getByRole("button", { name: "撤销" }));
    expect(mocks.post).toHaveBeenCalledTimes(2);
    mocks.post.mockImplementationOnce(async () => {
      rows = [
        { ...connection, state: "revoked", key_hint: "••••", version: 2 },
      ];
      return { data: rows[0] };
    });
    await user.click(screen.getByRole("button", { name: "确认撤销" }));
    await screen.findByText("连接已撤销。");
  });

  it("过期版本保存失败保留输入，刷新后取新版本", async () => {
    const user = userEvent.setup();
    mocks.put.mockResolvedValue({
      error: { error: { message: "设置已更新，请刷新后再保存" } },
    });
    render(<AiSettings {...props} />);
    await screen.findByText("尚未核算");
    await user.click(screen.getByRole("tab", { name: "预算与限制" }));
    const input = screen.getByLabelText(
      "滚动 24 小时调用上限",
    ) as HTMLInputElement;
    await user.clear(input);
    await user.type(input, "50");
    await user.click(screen.getByRole("button", { name: "保存额度设置" }));
    await screen.findByText("设置已更新，请刷新后再保存");
    expect(input.value).toBe("50");
    currentPolicy = { ...policy, daily_call_limit: 75, version: 1 };
    await user.click(screen.getByRole("button", { name: "刷新数据" }));
    await waitFor(() => expect(input.value).toBe("75"));
  });

  it("切换企业忽略旧响应，撤去所有者角色清空管理数据", async () => {
    let finish!: (result: unknown) => void;
    mocks.get.mockImplementationOnce(
      () =>
        new Promise((resolve) => {
          finish = resolve;
        }),
    );
    const view = render(<AiSettings {...props} />);
    view.rerender(
      <AiSettings {...props} organizationId="o2" isOwner={false} />,
    );
    await screen.findByText("尚未核算");
    await act(async () => finish({ data: { ...usage, input_tokens: 999999 } }));
    expect(screen.queryByText("1,000,004")).toBeNull();
    expect(mocks.get.mock.calls.map((call) => call[0])).toEqual([
      "/api/v1/ai/usage",
      "/api/v1/ai/usage",
    ]);
    view.rerender(<AiSettings {...props} />);
    await screen.findByText("尚未核算");
    await userEvent.click(screen.getByRole("tab", { name: "AI 服务" }));
    view.rerender(<AiSettings {...props} isOwner={false} />);
    expect(screen.queryByText("自己配置 API Key")).toBeNull();
    await screen.findByText("尚未核算");
  });
});
