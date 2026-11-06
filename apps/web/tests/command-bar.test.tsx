import {
  act,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { CommandBar } from "../components/command-bar";
import type {
  BrowserRecognition,
  SpeechResultEvent,
} from "../lib/use-speech-input";

class Recognition implements BrowserRecognition {
  static instances: Recognition[] = [];
  lang = "";
  continuous = false;
  interimResults = false;
  maxAlternatives = 0;
  onstart: (() => void) | null = null;
  onresult: ((event: SpeechResultEvent) => void) | null = null;
  onerror: ((event: { error: string }) => void) | null = null;
  onend: (() => void) | null = null;
  start = vi.fn();
  stop = vi.fn();
  abort = vi.fn();
  constructor() {
    Recognition.instances.push(this);
  }
}
const resultEvent = (...parts: [string, boolean][]): SpeechResultEvent => ({
  results: parts.map(([transcript, isFinal]) =>
    Object.assign([{ transcript }], { isFinal }),
  ),
});
function recognize(instance: Recognition, ...parts: [string, boolean][]) {
  act(() => instance.onresult?.(resultEvent(...parts)));
}
beforeEach(() => {
  Recognition.instances = [];
  vi.stubGlobal("SpeechRecognition", undefined);
  vi.stubGlobal("webkitSpeechRecognition", undefined);
});
afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe("coRoof 多行指令输入", () => {
  it("expands for focus inside the composer and preserves a draft when focus leaves", async () => {
    const user = userEvent.setup();
    const submit = vi.fn();
    render(
      <>
        <CommandBar onSubmit={submit} />
        <button>其他工作</button>
      </>,
    );
    const form = screen.getByRole("form", { name: "向 coRoof 发送指令" });
    const input = screen.getByLabelText("告诉 coRoof 你想做什么");
    expect(form.hasAttribute("data-expanded")).toBe(false);
    await user.click(input);
    expect(form.hasAttribute("data-expanded")).toBe(true);
    fireEvent.blur(input, { relatedTarget: form.querySelector("button") });
    expect(form.hasAttribute("data-expanded")).toBe(true);
    await user.click(screen.getByRole("button", { name: "其他工作" }));
    expect(form.hasAttribute("data-expanded")).toBe(false);
    await user.type(input, "今天先做什么");
    await user.click(screen.getByRole("button", { name: "其他工作" }));
    expect(form.hasAttribute("data-expanded")).toBe(true);
    expect(submit).not.toHaveBeenCalled();
  });

  it("processing lets the user draft the next question without submitting until available", async () => {
    const submit = vi.fn();
    const user = userEvent.setup();
    const view = render(<CommandBar onSubmit={submit} processing />);
    const input = screen.getByLabelText(
      "告诉 coRoof 你想做什么",
    ) as HTMLTextAreaElement;
    await user.type(input, "下一个问题");
    await user.keyboard("{Enter}");
    expect(submit).not.toHaveBeenCalled();
    expect(input.value).toBe("下一个问题");
    view.rerender(<CommandBar onSubmit={submit} />);
    await user.keyboard("{Enter}");
    expect(submit).toHaveBeenCalledExactlyOnceWith("下一个问题");
  });

  it("context suggestions only prefill and a rejected submission retains its text", async () => {
    const submit = vi.fn().mockReturnValue(false);
    const clear = vi.fn();
    const user = userEvent.setup();
    render(
      <CommandBar
        onSubmit={submit}
        prefill={{ id: "prefill1", text: "核实资料" }}
        contextLabel="客户资料"
        onClearContext={clear}
      />,
    );
    const input = screen.getByLabelText(
      "告诉 coRoof 你想做什么",
    ) as HTMLTextAreaElement;
    expect(input.value).toBe("核实资料");
    expect(submit).not.toHaveBeenCalled();
    await user.keyboard("{Enter}");
    expect(input.value).toBe("核实资料");
    await user.click(screen.getByRole("button", { name: "清除工作上下文" }));
    expect(clear).toHaveBeenCalledOnce();
  });

  it("accepts an explicit Enter submission, trims it, and clears only the sent input", async () => {
    const user = userEvent.setup();
    const submit = vi.fn();
    render(<CommandBar onSubmit={submit} />);
    const input = screen.getByLabelText(
      "告诉 coRoof 你想做什么",
    ) as HTMLTextAreaElement;
    const send = screen.getByRole("button", { name: "发送指令" });
    expect(send.hasAttribute("disabled")).toBe(true);
    await user.type(input, "   ");
    expect(send.hasAttribute("disabled")).toBe(true);
    await user.keyboard("{Enter}");
    expect(submit).not.toHaveBeenCalled();
    await user.type(input, "核实交付进展  ");
    await user.keyboard("{Enter}");
    expect(submit).toHaveBeenCalledExactlyOnceWith("核实交付进展");
    expect(input.value).toBe("");
    expect(send.hasAttribute("disabled")).toBe(true);
  });

  it("does not send when Enter confirms an IME candidate, including Safari's 229 event", async () => {
    const user = userEvent.setup();
    const submit = vi.fn();
    render(<CommandBar onSubmit={submit} />);
    const input = screen.getByLabelText(
      "告诉 coRoof 你想做什么",
    ) as HTMLTextAreaElement;
    const form = screen.getByRole("form", { name: "向 coRoof 发送指令" });
    fireEvent.compositionStart(input);
    fireEvent.change(input, { target: { value: "检查客户资料" } });
    expect(fireEvent.keyDown(input, { key: "Enter", isComposing: true })).toBe(
      false,
    );
    fireEvent.submit(form);
    expect(submit).not.toHaveBeenCalled();
    fireEvent.compositionEnd(input);
    expect(fireEvent.keyDown(input, { key: "Enter", isComposing: true })).toBe(
      false,
    );
    expect(fireEvent.keyDown(input, { key: "Enter", keyCode: 229 })).toBe(
      false,
    );
    expect(submit).not.toHaveBeenCalled();
    await user.click(input);
    await user.keyboard("{Enter}");
    expect(submit).toHaveBeenCalledExactlyOnceWith("检查客户资料");
  });

  it("preserves a draft while disabled and allows an explicit button submission after re-enabling", async () => {
    const user = userEvent.setup();
    const submit = vi.fn();
    const view = render(<CommandBar onSubmit={submit} />);
    const input = screen.getByLabelText(
      "告诉 coRoof 你想做什么",
    ) as HTMLTextAreaElement;
    await user.type(input, "核对需要支持的工作");
    view.rerender(<CommandBar onSubmit={submit} disabled />);
    expect(input.disabled).toBe(true);
    fireEvent.submit(screen.getByRole("form", { name: "向 coRoof 发送指令" }));
    expect(submit).not.toHaveBeenCalled();
    expect(input.value).toBe("核对需要支持的工作");
    view.rerender(<CommandBar onSubmit={submit} />);
    await user.click(screen.getByRole("button", { name: "发送指令" }));
    expect(submit).toHaveBeenCalledExactlyOnceWith("核对需要支持的工作");
    expect(input.value).toBe("");
  });

  it("keeps Shift+Enter as a newline and sends the complete multiline question with Enter", async () => {
    const user = userEvent.setup();
    const submit = vi.fn();
    render(<CommandBar onSubmit={submit} />);
    const input = screen.getByLabelText(
      "告诉 coRoof 你想做什么",
    ) as HTMLTextAreaElement;
    await user.type(input, "核实交付进展");
    await user.keyboard("{Shift>}{Enter}{/Shift}");
    await user.type(input, "指出还缺少的资料");
    expect(input.value).toBe("核实交付进展\n指出还缺少的资料");
    expect(submit).not.toHaveBeenCalled();
    await user.keyboard("{Enter}");
    expect(submit).toHaveBeenCalledExactlyOnceWith(
      "核实交付进展\n指出还缺少的资料",
    );
    expect(input.value).toBe("");
  });

  it("grows with content, scrolls after five lines, and shrinks after clearing", () => {
    render(<CommandBar onSubmit={vi.fn()} />);
    const input = screen.getByLabelText(
      "告诉 coRoof 你想做什么",
    ) as HTMLTextAreaElement;
    // jsdom has no text layout; supply the browser's measured content height.
    Object.defineProperty(input, "scrollHeight", {
      configurable: true,
      get: () => input.value.split("\n").length * 24,
    });
    fireEvent.change(input, { target: { value: "甲\n乙\n丙" } });
    expect(input.style.height).toBe("72px");
    expect(input.style.overflowY).toBe("hidden");
    fireEvent.change(input, { target: { value: "甲\n乙\n丙\n丁\n戊\n己" } });
    expect(input.style.height).toBe("120px");
    expect(input.style.overflowY).toBe("auto");
    fireEvent.change(input, { target: { value: "" } });
    expect(input.style.height).toBe("48px");
    expect(input.style.overflowY).toBe("hidden");
  });
});

describe("浏览器语音输入", () => {
  it("starts only on click, shows interim feedback, deduplicates cumulative final results and waits for manual sending", async () => {
    vi.stubGlobal("SpeechRecognition", Recognition);
    const user = userEvent.setup();
    const submit = vi.fn();
    render(<CommandBar onSubmit={submit} scopeKey="o1:m1:overview" />);
    const input = screen.getByRole("textbox") as HTMLTextAreaElement;
    await user.type(input, "已经收到资料。");
    expect(Recognition.instances).toHaveLength(0);
    const mic = screen.getByRole("button", { name: "开始语音输入" });
    expect(mic.getAttribute("title")).toContain("可能联网处理音频");
    await user.click(mic);
    const recognition = Recognition.instances[0];
    expect(recognition.start).toHaveBeenCalledOnce();
    expect(recognition.lang).toBe("zh-CN");
    expect(recognition.continuous).toBe(true);
    expect(recognition.interimResults).toBe(true);
    expect(recognition.maxAlternatives).toBe(1);
    act(() => recognition.onstart?.());
    recognize(recognition, ["交付计划", false]);
    expect(screen.getByText("正在识别：交付计划")).toBeTruthy();
    expect(input.value).toBe("已经收到资料。");
    recognize(recognition, ["交付计划需要确认。", true], ["还需", false]);
    expect(input.value).toBe("已经收到资料。 交付计划需要确认。");
    expect(
      screen.getByRole("button", { name: "发送指令" }).hasAttribute("disabled"),
    ).toBe(true);
    fireEvent.submit(screen.getByRole("form"));
    expect(submit).not.toHaveBeenCalled();
    await user.click(screen.getByRole("button", { name: "停止语音输入" }));
    expect(recognition.stop).toHaveBeenCalledOnce();
    recognize(
      recognition,
      ["交付计划需要确认。", true],
      ["还需要核实日期。", true],
    );
    recognize(
      recognition,
      ["交付计划需要确认。", true],
      ["还需要核实日期。", true],
    );
    act(() => recognition.onend?.());
    expect(input.value).toBe(
      "已经收到资料。 交付计划需要确认。 还需要核实日期。",
    );
    expect(submit).not.toHaveBeenCalled();
    expect(screen.getByText("转写已填入，请检查后发送。")).toBeTruthy();
    await user.click(screen.getByRole("button", { name: "发送指令" }));
    expect(submit).toHaveBeenCalledExactlyOnceWith(
      "已经收到资料。 交付计划需要确认。 还需要核实日期。",
    );
  });

  it("supports a prefixed recognizer and allows typed edits without overwriting them", async () => {
    vi.stubGlobal("webkitSpeechRecognition", Recognition);
    const user = userEvent.setup();
    render(<CommandBar onSubmit={vi.fn()} />);
    const input = screen.getByRole("textbox") as HTMLTextAreaElement;
    await user.click(screen.getByRole("button", { name: "开始语音输入" }));
    const recognition = Recognition.instances[0];
    recognize(recognition, ["第一句。", true]);
    fireEvent.change(input, { target: { value: "手动修正。" } });
    recognize(recognition, ["第一句。", true], ["第二句。", true]);
    expect(input.value).toBe("手动修正。 第二句。");
  });

  it("explains unsupported browsers without starting a recording or hiding the microphone", async () => {
    const user = userEvent.setup();
    const submit = vi.fn();
    render(<CommandBar onSubmit={submit} />);
    await user.click(screen.getByRole("button", { name: "开始语音输入" }));
    expect(
      screen.getByText("当前浏览器不支持语音输入，请直接输入文字。"),
    ).toBeTruthy();
    expect(screen.getByRole("button", { name: "开始语音输入" })).toBeTruthy();
    expect(Recognition.instances).toHaveLength(0);
    expect(submit).not.toHaveBeenCalled();
  });

  it.each([
    ["not-allowed", "未获麦克风使用许可"],
    ["audio-capture", "无法使用麦克风"],
    ["network", "语音识别服务连接失败"],
    ["no-speech", "没有听到清晰语音"],
    ["service-not-allowed", "浏览器未允许语音识别服务"],
  ])(
    "handles %s without losing the draft or restarting automatically",
    async (error, text) => {
      vi.stubGlobal("SpeechRecognition", Recognition);
      const user = userEvent.setup();
      const submit = vi.fn();
      render(<CommandBar onSubmit={submit} />);
      const input = screen.getByRole("textbox") as HTMLTextAreaElement;
      await user.type(input, "保留这段文字");
      await user.click(screen.getByRole("button", { name: "开始语音输入" }));
      const recognition = Recognition.instances[0];
      const lateResult = recognition.onresult!;
      act(() => recognition.onerror?.({ error }));
      act(() => lateResult(resultEvent(["过期转写", true])));
      expect(screen.getByText(new RegExp(text))).toBeTruthy();
      expect(input.value).toBe("保留这段文字");
      expect(recognition.abort).toHaveBeenCalledOnce();
      expect(recognition.start).toHaveBeenCalledOnce();
      expect(submit).not.toHaveBeenCalled();
    },
  );

  it("handles synchronous browser start failures with a recoverable message", async () => {
    class BlockedRecognition extends Recognition {
      start = vi.fn(() => {
        throw new DOMException("blocked", "NotAllowedError");
      });
    }
    vi.stubGlobal("SpeechRecognition", BlockedRecognition);
    const user = userEvent.setup();
    render(<CommandBar onSubmit={vi.fn()} />);
    await user.click(screen.getByRole("button", { name: "开始语音输入" }));
    expect(screen.getByText(/未获麦克风使用许可/)).toBeTruthy();
    expect(screen.getByRole("button", { name: "开始语音输入" })).toBeTruthy();
  });

  it("aborts on page changes and unmount, preserving the draft and ignoring captured late callbacks", async () => {
    vi.stubGlobal("SpeechRecognition", Recognition);
    const user = userEvent.setup();
    const submit = vi.fn();
    const view = render(
      <CommandBar onSubmit={submit} scopeKey="o1:m1:overview" />,
    );
    await user.click(screen.getByRole("button", { name: "开始语音输入" }));
    const first = Recognition.instances[0];
    recognize(first, ["甲企业草稿", true]);
    const lateFirst = first.onresult!;
    view.rerender(<CommandBar onSubmit={submit} scopeKey="o1:m1:projects" />);
    expect(first.abort).toHaveBeenCalledOnce();
    act(() => lateFirst(resultEvent(["甲企业迟到文字", true])));
    expect((screen.getByRole("textbox") as HTMLTextAreaElement).value).toBe(
      "甲企业草稿",
    );
    await user.click(screen.getByRole("button", { name: "开始语音输入" }));
    const second = Recognition.instances[1];
    const lateSecond = second.onresult!;
    view.unmount();
    act(() => lateSecond(resultEvent(["卸载后迟到文字", true])));
    expect(second.abort).toHaveBeenCalledOnce();
    expect(second.onresult).toBeNull();
    expect(submit).not.toHaveBeenCalled();
  });

  it("clears drafts on identity remount and rejects the previous identity's recognizer", async () => {
    vi.stubGlobal("SpeechRecognition", Recognition);
    const user = userEvent.setup();
    const submit = vi.fn();
    const view = render(
      <CommandBar key="o1:m1" onSubmit={submit} scopeKey="o1:m1:overview" />,
    );
    await user.click(screen.getByRole("button", { name: "开始语音输入" }));
    const recognition = Recognition.instances[0];
    recognize(recognition, ["旧身份草稿", true]);
    const late = recognition.onresult!;
    view.rerender(
      <CommandBar key="o2:m2" onSubmit={submit} scopeKey="o2:m2:overview" />,
    );
    act(() => late(resultEvent(["旧身份迟到内容", true])));
    expect(recognition.abort).toHaveBeenCalledOnce();
    expect((screen.getByRole("textbox") as HTMLTextAreaElement).value).toBe("");
    expect(submit).not.toHaveBeenCalled();
  });

  it("aborts when disabled, keeps confirmed text and does not accept results after re-enabling", async () => {
    vi.stubGlobal("SpeechRecognition", Recognition);
    const user = userEvent.setup();
    const submit = vi.fn();
    const view = render(<CommandBar onSubmit={submit} />);
    await user.click(screen.getByRole("button", { name: "开始语音输入" }));
    const recognition = Recognition.instances[0];
    recognize(recognition, ["已确认转写", true]);
    const late = recognition.onresult!;
    view.rerender(<CommandBar onSubmit={submit} disabled />);
    expect(recognition.abort).toHaveBeenCalledOnce();
    act(() => late(resultEvent(["未获许可的迟到内容", true])));
    view.rerender(<CommandBar onSubmit={submit} />);
    expect((screen.getByRole("textbox") as HTMLTextAreaElement).value).toBe(
      "已确认转写",
    );
    expect(screen.getByRole("button", { name: "开始语音输入" })).toBeTruthy();
    expect(Recognition.instances).toHaveLength(1);
  });

  it("bounds stopping when the browser never ends and does not commit interim-only text", () => {
    vi.useFakeTimers();
    vi.stubGlobal("SpeechRecognition", Recognition);
    render(<CommandBar onSubmit={vi.fn()} />);
    fireEvent.click(screen.getByRole("button", { name: "开始语音输入" }));
    const recognition = Recognition.instances[0];
    recognize(recognition, ["未确认的识别", false]);
    fireEvent.click(screen.getByRole("button", { name: "停止语音输入" }));
    act(() => {
      vi.advanceTimersByTime(4000);
    });
    expect(recognition.abort).toHaveBeenCalledOnce();
    expect((screen.getByRole("textbox") as HTMLTextAreaElement).value).toBe("");
    expect(screen.getByRole("button", { name: "开始语音输入" })).toBeTruthy();
  });

  it("respects the text limit and stops receiving further audio when it is reached", async () => {
    vi.stubGlobal("SpeechRecognition", Recognition);
    const user = userEvent.setup();
    render(<CommandBar onSubmit={vi.fn()} />);
    const input = screen.getByRole("textbox") as HTMLTextAreaElement;
    fireEvent.change(input, { target: { value: "甲".repeat(1999) } });
    await user.click(screen.getByRole("button", { name: "开始语音输入" }));
    const recognition = Recognition.instances[0];
    recognize(recognition, ["超出长度的识别文字", true]);
    expect(input.value).toHaveLength(2000);
    expect(recognition.abort).toHaveBeenCalledOnce();
    expect(screen.getByText(/已达到 2000 字上限/)).toBeTruthy();
  });

  it("aborts when the page is hidden while keeping final text; permission-related blur alone does not abort", async () => {
    vi.stubGlobal("SpeechRecognition", Recognition);
    let visibility: DocumentVisibilityState = "visible";
    vi.spyOn(document, "visibilityState", "get").mockImplementation(
      () => visibility,
    );
    const user = userEvent.setup();
    const submit = vi.fn();
    render(<CommandBar onSubmit={submit} />);
    await user.click(screen.getByRole("button", { name: "开始语音输入" }));
    const recognition = Recognition.instances[0];
    fireEvent.blur(window);
    expect(recognition.abort).not.toHaveBeenCalled();
    recognize(recognition, ["已经识别的文字", true], ["还没完成", false]);
    const late = recognition.onresult!;
    visibility = "hidden";
    fireEvent(document, new Event("visibilitychange"));
    expect(recognition.abort).toHaveBeenCalledOnce();
    expect(screen.getByText(/页面已进入后台，语音输入已停止/)).toBeTruthy();
    act(() => late(resultEvent(["不应接收的后台文字", true])));
    visibility = "visible";
    fireEvent(document, new Event("visibilitychange"));
    expect((screen.getByRole("textbox") as HTMLTextAreaElement).value).toBe(
      "已经识别的文字",
    );
    expect(screen.queryByText(/正在识别：/)).toBeNull();
    expect(Recognition.instances).toHaveLength(1);
    expect(submit).not.toHaveBeenCalled();
  });

  it("stops for an independent feature drawer, keeps final text, and ignores late results after it closes", async () => {
    vi.stubGlobal("SpeechRecognition", Recognition);
    const user = userEvent.setup();
    const submit = vi.fn();
    render(
      <>
        <CommandBar onSubmit={submit} scopeKey="o1:m1:knowledge" />
        <button
          onClick={() =>
            (
              document.getElementById("feature-drawer") as HTMLDialogElement
            ).showModal()
          }
        >
          打开知识详情
        </button>
        <dialog id="feature-drawer" aria-label="知识详情">
          <p>独立管理的详情窗口</p>
        </dialog>
      </>,
    );
    await user.click(screen.getByRole("button", { name: "开始语音输入" }));
    const recognition = Recognition.instances[0];
    recognize(recognition, ["已识别工作说明", true], ["尚未完成的部分", false]);
    const lateResult = recognition.onresult!;
    await user.click(screen.getByRole("button", { name: "打开知识详情" }));
    await waitFor(() => expect(recognition.abort).toHaveBeenCalledOnce());
    expect(screen.getByText(/已打开其他窗口，语音输入已停止/)).toBeTruthy();
    expect(screen.queryByText(/正在识别：/)).toBeNull();
    act(() =>
      (
        screen.getByRole("dialog", { name: "知识详情" }) as HTMLDialogElement
      ).close(),
    );
    act(() => lateResult(resultEvent(["不应接收的旧回调", true])));
    expect((screen.getByRole("textbox") as HTMLTextAreaElement).value).toBe(
      "已识别工作说明",
    );
    expect(Recognition.instances).toHaveLength(1);
    expect(submit).not.toHaveBeenCalled();
  });

  it.each(["onstart", "onresult", "onerror", "onend"] as const)(
    "checks modal state synchronously in %s before MutationObserver runs",
    (callback) => {
      vi.stubGlobal("SpeechRecognition", Recognition);
      render(
        <>
          <CommandBar onSubmit={vi.fn()} />
          <dialog data-testid="independent-modal" />
        </>,
      );
      fireEvent.click(screen.getByRole("button", { name: "开始语音输入" }));
      const recognition = Recognition.instances[0];
      recognize(recognition, ["已确认文字", true]);
      act(() => {
        screen.getByTestId("independent-modal").setAttribute("open", "");
        if (callback === "onresult")
          recognition.onresult?.(
            resultEvent(["已确认文字", true], ["弹窗后的新文字", true]),
          );
        else if (callback === "onerror")
          recognition.onerror?.({ error: "network" });
        else recognition[callback]?.();
        // Still in the mutation's synchronous stack: the observer has not run.
        expect(recognition.abort).toHaveBeenCalledOnce();
      });
      expect((screen.getByRole("textbox") as HTMLTextAreaElement).value).toBe(
        "已确认文字",
      );
      expect(screen.getByText(/已打开其他窗口，语音输入已停止/)).toBeTruthy();
    },
  );

  it.each(["attribute", "insert"])(
    "observes a custom aria-modal opened by %s and does not resume after closing",
    async (method) => {
      vi.stubGlobal("SpeechRecognition", Recognition);
      render(
        <>
          <CommandBar onSubmit={vi.fn()} />
          <div data-testid="modal-host">
            <div data-testid="custom-modal" />
          </div>
        </>,
      );
      fireEvent.click(screen.getByRole("button", { name: "开始语音输入" }));
      const recognition = Recognition.instances[0];
      let modal = screen.getByTestId("custom-modal");
      act(() => {
        if (method === "insert") {
          modal = document.createElement("div");
          modal.setAttribute("aria-modal", "true");
          screen.getByTestId("modal-host").appendChild(modal);
        } else modal.setAttribute("aria-modal", "true");
      });
      await waitFor(() => expect(recognition.abort).toHaveBeenCalledOnce());
      act(() => modal.removeAttribute("aria-modal"));
      expect(Recognition.instances).toHaveLength(1);
      expect(screen.getByRole("button", { name: "开始语音输入" })).toBeTruthy();
    },
  );

  it("blocks a new start synchronously while a custom modal is open", () => {
    vi.stubGlobal("SpeechRecognition", Recognition);
    render(
      <>
        <CommandBar onSubmit={vi.fn()} />
        <div data-testid="modal" />
      </>,
    );
    act(() => {
      screen.getByTestId("modal").setAttribute("aria-modal", "true");
      fireEvent.click(screen.getByRole("button", { name: "开始语音输入" }));
      expect(Recognition.instances).toHaveLength(0);
    });
    expect(screen.getByText("请先关闭当前窗口，再开始语音输入。")).toBeTruthy();
  });
});

describe("聚焦指令框快捷键", () => {
  it.each([
    ["MacIntel", "⌘K", { metaKey: true }],
    ["Win32", "Ctrl+K", { ctrlKey: true }],
  ])(
    "shows the %s shortcut and focuses without sending",
    (platform, label, modifiers) => {
      vi.spyOn(navigator, "platform", "get").mockReturnValue(
        platform as string,
      );
      const submit = vi.fn();
      render(<CommandBar onSubmit={submit} />);
      expect(screen.getByText(label as string)).toBeTruthy();
      const input = screen.getByRole("textbox");
      expect(
        fireEvent.keyDown(document, { key: "k", ...(modifiers as object) }),
      ).toBe(false);
      expect(document.activeElement).toBe(input);
      expect(submit).not.toHaveBeenCalled();
    },
  );

  it("does not steal focus from an open native dialog or during composition outside the composer", () => {
    render(
      <>
        <CommandBar onSubmit={vi.fn()} />
        <dialog open>
          <input aria-label="详情字段" />
        </dialog>
      </>,
    );
    const outside = screen.getByRole("textbox", { name: "详情字段" });
    outside.focus();
    expect(fireEvent.keyDown(outside, { key: "k", metaKey: true })).toBe(true);
    expect(document.activeElement).toBe(outside);
    screen.getByRole("dialog").removeAttribute("open");
    fireEvent.compositionStart(outside);
    expect(fireEvent.keyDown(document, { key: "k", ctrlKey: true })).toBe(true);
    expect(document.activeElement).toBe(outside);
    fireEvent.compositionEnd(outside);
    expect(
      fireEvent.keyDown(document, {
        key: "k",
        ctrlKey: true,
        isComposing: true,
      }),
    ).toBe(true);
    expect(
      fireEvent.keyDown(document, { key: "k", ctrlKey: true, keyCode: 229 }),
    ).toBe(true);
    expect(document.activeElement).toBe(outside);
  });

  it("skips disabled, repeated, already handled and modified shortcuts, and removes the listener on unmount", () => {
    const view = render(<CommandBar onSubmit={vi.fn()} disabled />);
    expect(fireEvent.keyDown(document, { key: "k", metaKey: true })).toBe(true);
    view.rerender(<CommandBar onSubmit={vi.fn()} />);
    for (const extra of [
      { repeat: true },
      { altKey: true },
      { shiftKey: true },
      { ctrlKey: true },
    ]) {
      expect(
        fireEvent.keyDown(document, { key: "k", metaKey: true, ...extra }),
      ).toBe(true);
    }
    const handled = new KeyboardEvent("keydown", {
      key: "k",
      metaKey: true,
      cancelable: true,
      bubbles: true,
    });
    handled.preventDefault();
    document.dispatchEvent(handled);
    expect(document.activeElement).not.toBe(screen.getByRole("textbox"));
    view.unmount();
    expect(fireEvent.keyDown(document, { key: "k", metaKey: true })).toBe(true);
  });
});
