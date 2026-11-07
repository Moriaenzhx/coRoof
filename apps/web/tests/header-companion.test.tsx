import { act, fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { HeaderCompanion } from "../components/header-companion";
import type { Member, Work } from "../lib/api";

const work: Work = {
  id: "w1",
  organization_id: "o1",
  title: "客户资料确认",
  description: null,
  department_id: "d1",
  initiative_id: null,
  owner_id: "m1",
  due_at: null,
  lifecycle_status: "planned",
  needs_support: true,
  source_authority: "native",
  version: 1,
  updated_at: "2026-11-04T08:00:00Z",
};
const member: Member = {
  id: "m1",
  organization_id: "o1",
  user_id: "u1",
  name: "陆川",
  department_id: "d1",
  roles: ["member"],
  status: "active",
};
const props = {
  members: [member],
  timezone: "Asia/Shanghai",
  onWork: vi.fn(),
  onAsk: vi.fn(),
  onWatch: vi.fn(),
  now: new Date("2026-11-04T09:00:00Z").getTime(),
  scopeKey: "o1:m1",
};
class TestPointerEvent extends MouseEvent {
  pointerId: number;
  isPrimary: boolean;
  pointerType: string;
  constructor(type: string, init: PointerEventInit = {}) {
    super(type, init);
    this.pointerId = init.pointerId ?? 1;
    this.isPrimary = init.isPrimary ?? true;
    this.pointerType = init.pointerType ?? "mouse";
  }
}
afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});
beforeEach(() => {
  vi.stubGlobal("PointerEvent", TestPointerEvent);
  vi.stubGlobal("innerWidth", 1200);
  vi.stubGlobal("innerHeight", 800);
  vi.clearAllMocks();
  sessionStorage.clear();
});

it("quietly shows factual reminders without opening itself or invoking actions", () => {
  render(<HeaderCompanion {...props} works={[work]} />);
  expect(
    screen.getByRole("button", { name: "查看提醒：客户资料确认 · 需要支持" }),
  ).toBeTruthy();
  expect(screen.queryByRole("dialog")).toBeNull();
  expect(props.onAsk).not.toHaveBeenCalled();
  expect(props.onWatch).not.toHaveBeenCalled();
  expect(props.onWork).not.toHaveBeenCalled();
});

it("opens a local greeting, handles Escape and close with focus return", async () => {
  const user = userEvent.setup();
  render(<HeaderCompanion {...props} works={[]} />);
  const trigger = screen.getByRole("button", { name: "和 coRoof 打个招呼" });
  await user.click(trigger);
  expect(screen.getByRole("dialog", { name: "coRoof 工作伙伴" })).toBeTruthy();
  expect(screen.getAllByText("嗨，我在这里。").length).toBeGreaterThan(0);
  await user.click(screen.getByRole("button", { name: "打个招呼" }));
  expect(
    screen.getAllByText("收到你的招呼，想聊工作时叫我。").length,
  ).toBeGreaterThan(0);
  expect(props.onAsk).not.toHaveBeenCalled();
  await user.keyboard("{Escape}");
  expect(screen.queryByRole("dialog")).toBeNull();
  expect(document.activeElement).toBe(trigger);
  await user.click(trigger);
  await user.click(screen.getByRole("button", { name: "关闭伙伴浮层" }));
  expect(document.activeElement).toBe(trigger);
});

it("outside click closes without stealing focus from the user's target", async () => {
  const user = userEvent.setup();
  render(
    <>
      <HeaderCompanion {...props} works={[work]} />
      <button>继续浏览</button>
    </>,
  );
  await user.click(screen.getByRole("button", { name: "和 coRoof 打个招呼" }));
  const outside = screen.getByRole("button", { name: "继续浏览" });
  await user.click(outside);
  expect(screen.queryByRole("dialog")).toBeNull();
  expect(document.activeElement).toBe(outside);
});

it("opens exact work/question context and closes before handing off to drawers", async () => {
  const user = userEvent.setup();
  render(<HeaderCompanion {...props} works={[work]} />);
  const bubble = screen.getByRole("button", { name: /查看提醒/ });
  props.onWork.mockImplementationOnce(() => {
    expect(document.activeElement).toBe(bubble);
  });
  props.onAsk.mockImplementationOnce(() => {
    expect(document.activeElement).toBe(bubble);
  });
  await user.click(bubble);
  expect(screen.getByText(/记录明确标记了支持需求/)).toBeTruthy();
  expect(screen.getByText(/陆川负责/)).toBeTruthy();
  expect(screen.getByText("按已记录工作整理 · 未调用模型")).toBeTruthy();
  await user.click(screen.getByRole("button", { name: /查看工作记录/ }));
  expect(props.onWork).toHaveBeenCalledWith("w1");
  expect(screen.queryByRole("dialog")).toBeNull();
  await user.click(bubble);
  await user.click(screen.getByRole("button", { name: "梳理下一步" }));
  expect(props.onAsk).toHaveBeenCalledWith(
    "w1",
    expect.stringContaining("支持需求和协作缺口"),
  );
  expect(screen.queryByRole("dialog")).toBeNull();
});

it("snoozes only the current version across refresh and navigation; new facts can remind again", async () => {
  const user = userEvent.setup();
  const first = render(<HeaderCompanion {...props} works={[work]} />);
  await user.click(screen.getByRole("button", { name: /查看提醒/ }));
  await user.click(screen.getByRole("button", { name: "暂时收起" }));
  expect(screen.queryByRole("button", { name: /查看提醒/ })).toBeNull();
  first.rerender(<HeaderCompanion {...props} works={[{ ...work }]} />);
  expect(screen.queryByRole("button", { name: /查看提醒/ })).toBeNull();
  expect(sessionStorage.getItem("coroof.companion.snoozed:o1:m1")).toBe(
    '["o1:w1:1"]',
  );
  first.unmount();
  const next = render(<HeaderCompanion {...props} works={[work]} />);
  expect(screen.queryByRole("button", { name: /查看提醒/ })).toBeNull();
  next.rerender(
    <HeaderCompanion {...props} works={[{ ...work, version: 2 }]} />,
  );
  expect(screen.getByRole("button", { name: /查看提醒/ })).toBeTruthy();
  expect(screen.queryByRole("dialog")).toBeNull();
});

it("keeps an open popover, button and focus stable during ordinary refresh", async () => {
  const user = userEvent.setup();
  const { rerender } = render(<HeaderCompanion {...props} works={[work]} />);
  await user.click(screen.getByRole("button", { name: /查看提醒/ }));
  const action = screen.getByRole("button", { name: "梳理下一步" });
  action.focus();
  const dialog = screen.getByRole("dialog");
  rerender(<HeaderCompanion {...props} works={[{ ...work }]} loading />);
  expect(screen.getByRole("dialog")).toBe(dialog);
  expect(screen.getByRole("button", { name: "梳理下一步" })).toBe(action);
  expect(document.activeElement).toBe(action);
  expect(screen.getByText("正在更新记录")).toBeTruthy();
  rerender(<HeaderCompanion {...props} works={[{ ...work }]} />);
  expect(document.activeElement).toBe(action);
});

it("does not infer alerts from external, completed, cancelled or unknown-owner records", async () => {
  const user = userEvent.setup();
  render(
    <HeaderCompanion
      {...props}
      members={[]}
      works={[
        {
          ...work,
          id: "external",
          source_authority: "external",
          due_at: "2026-01-01T00:00:00Z",
        },
        { ...work, id: "done", lifecycle_status: "done" },
        { ...work, id: "cancelled", lifecycle_status: "cancelled" },
        { ...work, id: "native", needs_support: false },
      ]}
    />,
  );
  expect(screen.queryByRole("button", { name: /查看提醒/ })).toBeNull();
  await user.click(screen.getByRole("button", { name: "和 coRoof 打个招呼" }));
  expect(screen.queryByRole("button", { name: "暂时收起" })).toBeNull();
});

it("offers only local play until explicitly asked to chat and lets motion be paused", async () => {
  const user = userEvent.setup();
  render(<HeaderCompanion {...props} works={[]} />);
  await user.click(screen.getByRole("button", { name: "和 coRoof 打个招呼" }));
  expect(screen.getByText(/尚未记录的情况仍然未知/)).toBeTruthy();
  await user.click(screen.getByRole("button", { name: "暂停伙伴动画" }));
  expect(
    screen
      .getByRole("button", { name: "恢复伙伴动画" })
      .getAttribute("aria-pressed"),
  ).toBe("true");
  expect(props.onAsk).not.toHaveBeenCalled();
  await user.click(screen.getByRole("button", { name: "聊聊工作" }));
  expect(props.onAsk).toHaveBeenCalledWith();
  expect(screen.queryByRole("dialog")).toBeNull();
});

it("keeps reminder receipts isolated by identity and survives unavailable storage", async () => {
  const user = userEvent.setup();
  const { rerender } = render(<HeaderCompanion {...props} works={[work]} />);
  const failure = vi
    .spyOn(Storage.prototype, "setItem")
    .mockImplementation(() => {
      throw new Error("disabled");
    });
  await user.click(screen.getByRole("button", { name: /查看提醒/ }));
  await user.click(screen.getByRole("button", { name: "暂时收起" }));
  expect(screen.queryByRole("button", { name: /查看提醒/ })).toBeNull();
  rerender(<HeaderCompanion {...props} scopeKey="o1:m2" works={[work]} />);
  expect(screen.getByRole("button", { name: /查看提醒/ })).toBeTruthy();
  failure.mockRestore();
});

function rect(
  left: number,
  top: number,
  width: number,
  height: number,
): DOMRect {
  return {
    left,
    top,
    width,
    height,
    x: left,
    y: top,
    right: left + width,
    bottom: top + height,
    toJSON: () => ({}),
  };
}
function prepareDrag() {
  const trigger = screen.getByRole("button", { name: "和 coRoof 打个招呼" });
  const cluster = trigger.closest(".header-companion-floating") as HTMLElement;
  vi.spyOn(cluster, "getBoundingClientRect").mockImplementation(() =>
    rect(
      Number.parseFloat(cluster.style.left),
      Number.parseFloat(cluster.style.top),
      window.innerWidth <= 600 ? 62 : 72,
      window.innerWidth <= 600 ? 74 : 86,
    ),
  );
  const captured = new Set<number>();
  const setCapture = vi.fn((id: number) => captured.add(id));
  const releaseCapture = vi.fn((id: number) => captured.delete(id));
  Object.assign(trigger, {
    setPointerCapture: setCapture,
    hasPointerCapture: (id: number) => captured.has(id),
    releasePointerCapture: releaseCapture,
  });
  fireEvent(window, new Event("resize"));
  return { trigger, cluster, setCapture, releaseCapture };
}
function dragTo(
  trigger: HTMLElement,
  x: number,
  y: number,
  pointerType = "mouse",
) {
  fireEvent.pointerDown(trigger, {
    pointerId: 3,
    clientX: 120,
    clientY: 120,
    button: 0,
    pointerType,
  });
  fireEvent.pointerMove(trigger, {
    pointerId: 3,
    clientX: x,
    clientY: y,
    pointerType,
  });
  fireEvent.pointerUp(trigger, {
    pointerId: 3,
    clientX: x,
    clientY: y,
    pointerType,
  });
  fireEvent.click(trigger, { detail: 1 });
}

it("keeps one portal node while dragging, captures the pointer and never mistakes a drag for a greeting", async () => {
  const user = userEvent.setup();
  const { container } = render(<HeaderCompanion {...props} works={[work]} />);
  const { trigger, cluster, setCapture, releaseCapture } = prepareDrag();
  expect(container.contains(cluster)).toBe(false);
  expect(document.body.contains(cluster)).toBe(true);
  dragTo(trigger, 20, 40);
  expect(screen.getByRole("button", { name: "和 coRoof 打个招呼" })).toBe(
    trigger,
  );
  expect(cluster.style.left).toBe("1004px");
  expect(cluster.style.top).toBe("610px");
  expect(cluster.dataset.floating).toBe("true");
  expect(cluster.dataset.dragging).toBeUndefined();
  expect(setCapture).toHaveBeenCalledWith(3);
  expect(releaseCapture).toHaveBeenCalledWith(3);
  expect(screen.queryByRole("dialog")).toBeNull();
  expect(props.onAsk).not.toHaveBeenCalled();
  expect(props.onWork).not.toHaveBeenCalled();
  expect(props.onWatch).not.toHaveBeenCalled();
  await user.click(trigger);
  expect(screen.getByRole("dialog")).toBeTruthy();
  expect(screen.getAllByText("嗨，我在这里。").length).toBeGreaterThan(0);
});

it("treats small pointer motion as a click and cancels touch dragging without opening or continuing it", () => {
  render(<HeaderCompanion {...props} works={[]} />);
  const { trigger, cluster, releaseCapture } = prepareDrag();
  dragTo(trigger, 122, 121);
  expect(screen.getByRole("dialog")).toBeTruthy();
  expect(cluster.dataset.floating).toBeUndefined();
  fireEvent.pointerDown(trigger, {
    pointerId: 3,
    clientX: 120,
    clientY: 120,
    button: 0,
    pointerType: "touch",
  });
  fireEvent.pointerMove(trigger, {
    pointerId: 3,
    clientX: 240,
    clientY: 240,
    pointerType: "touch",
  });
  fireEvent.pointerCancel(trigger, { pointerId: 3, pointerType: "touch" });
  const stoppedAt = cluster.style.left;
  fireEvent.pointerMove(trigger, {
    pointerId: 3,
    clientX: 400,
    clientY: 400,
    pointerType: "touch",
  });
  fireEvent.click(trigger, { detail: 1 });
  expect(cluster.style.left).toBe(stoppedAt);
  expect(releaseCapture).toHaveBeenCalledWith(3);
  expect(cluster.dataset.dragging).toBeUndefined();
  expect(screen.queryByRole("dialog")).toBeNull();
  expect(props.onAsk).not.toHaveBeenCalled();
});

it("clamps dragged positions on both edges and resize, preserves them on scroll, and restores home with the keyboard", async () => {
  vi.stubGlobal("innerWidth", 800);
  vi.stubGlobal("innerHeight", 600);
  const user = userEvent.setup();
  render(<HeaderCompanion {...props} works={[]} />);
  const { trigger, cluster } = prepareDrag();
  dragTo(trigger, -1000, -1000, "touch");
  expect(cluster.style.left).toBe("8px");
  expect(cluster.style.top).toBe("8px");
  dragTo(trigger, 1000, 1000, "touch");
  expect(cluster.style.left).toBe("720px");
  expect(cluster.style.top).toBe("506px");
  vi.stubGlobal("innerWidth", 400);
  vi.stubGlobal("innerHeight", 300);
  fireEvent(window, new Event("resize"));
  expect(cluster.style.left).toBe("330px");
  expect(cluster.style.top).toBe("218px");
  fireEvent(window, new Event("scroll"));
  expect(cluster.style.left).toBe("330px");
  expect(cluster.style.top).toBe("218px");
  trigger.focus();
  await user.keyboard("{Enter}");
  const reset = screen.getByRole("button", { name: "恢复原位" });
  reset.focus();
  await user.keyboard("{Enter}");
  expect(cluster.dataset.floating).toBeUndefined();
  expect(cluster.style.left).toBe("314px");
  expect(cluster.style.top).toBe("106px");
  expect(document.activeElement).toBe(trigger);
  expect(screen.queryByRole("dialog")).toBeNull();
  expect(props.onAsk).not.toHaveBeenCalled();
});

it("keeps the popover inside the viewport near a dragged bottom corner and preserves focus across resize", async () => {
  vi.stubGlobal("innerWidth", 800);
  vi.stubGlobal("innerHeight", 600);
  const user = userEvent.setup();
  render(<HeaderCompanion {...props} works={[work]} />);
  const { trigger, cluster } = prepareDrag();
  dragTo(trigger, 1000, 1000);
  await user.click(trigger);
  const dialog = screen.getByRole("dialog");
  vi.spyOn(dialog, "getBoundingClientRect").mockReturnValue(
    rect(0, 0, 340, 320),
  );
  const action = screen.getByRole("button", { name: "梳理下一步" });
  action.focus();
  fireEvent(window, new Event("resize"));
  expect(dialog.style.left).toBe("452px");
  expect(dialog.style.top).toBe("178px");
  expect(Number.parseFloat(dialog.style.left) + 340).toBeLessThanOrEqual(792);
  expect(Number.parseFloat(dialog.style.top) + 320).toBeLessThanOrEqual(592);
  expect(document.activeElement).toBe(action);
  expect(cluster.dataset.floating).toBe("true");
});

it("rests in the bottom-right without a page anchor and keeps its reminder above the composer", () => {
  const { container, rerender } = render(
    <HeaderCompanion {...props} works={[work]} />,
  );
  const { cluster } = prepareDrag();
  expect(container.querySelector(".header-companion-anchor")).toBeNull();
  expect(container.contains(cluster)).toBe(false);
  expect(cluster.style.left).toBe("1104px");
  expect(cluster.style.top).toBe("690px");
  const bubble = screen.getByRole("button", { name: /查看提醒/ });
  expect(Number.parseFloat(bubble.style.left) + 215).toBeLessThan(1104);
  expect(Number.parseFloat(bubble.style.top) + 34).toBeLessThanOrEqual(
    800 - 108 - 24,
  );
  rerender(<HeaderCompanion {...props} works={[work]} composerHeight={220} />);
  expect(cluster.style.top).toBe("690px");
  expect(Number.parseFloat(bubble.style.top) + 34).toBeLessThanOrEqual(
    800 - 220 - 24,
  );
  fireEvent(window, new Event("scroll"));
  expect(cluster.style.top).toBe("690px");
  expect(props.onAsk).not.toHaveBeenCalled();
});

it("raises the full-size character above a 650px composer and switches back only beyond 1100px", () => {
  vi.stubGlobal("innerWidth", 650);
  const view = render(
    <HeaderCompanion {...props} works={[work]} composerHeight={220} />,
  );
  const { cluster } = prepareDrag();
  expect(cluster.style.left).toBe("554px");
  expect(cluster.style.top).toBe("450px");
  const bubble = screen.getByRole("button", { name: /查看提醒/ });
  expect(Number.parseFloat(bubble.style.top) + 34).toBeLessThan(800 - 220 - 24);
  view.rerender(
    <HeaderCompanion {...props} works={[work]} composerHeight={108} />,
  );
  expect(cluster.style.top).toBe("534px");
  vi.stubGlobal("innerWidth", 1100);
  fireEvent(window, new Event("resize"));
  expect(cluster.style.top).toBe("534px");
  vi.stubGlobal("innerWidth", 1101);
  fireEvent(window, new Event("resize"));
  expect(cluster.style.top).toBe("690px");
});

it("reserves mobile composer height and restores the updated bottom-right home after dragging", async () => {
  vi.stubGlobal("innerWidth", 390);
  vi.stubGlobal("innerHeight", 844);
  const user = userEvent.setup();
  const view = render(<HeaderCompanion {...props} works={[]} />);
  const { trigger, cluster } = prepareDrag();
  expect(cluster.style.left).toBe("304px");
  expect(cluster.style.top).toBe("650px");
  dragTo(trigger, 20, 40, "touch");
  view.rerender(<HeaderCompanion {...props} works={[]} composerHeight={260} />);
  await user.click(trigger);
  await user.click(screen.getByRole("button", { name: "恢复原位" }));
  expect(cluster.style.left).toBe("304px");
  expect(cluster.style.top).toBe("498px");
  expect(document.activeElement).toBe(trigger);
  expect(props.onAsk).not.toHaveBeenCalled();
});

it.each([132, 166, 260])(
  "keeps a 12px mobile gap above the full measured %ipx dock, including navigation and safe area",
  (composerHeight) => {
    vi.stubGlobal("innerWidth", 390);
    vi.stubGlobal("innerHeight", 844);
    render(
      <HeaderCompanion {...props} works={[]} composerHeight={composerHeight} />,
    );
    const { cluster } = prepareDrag();
    const characterBottom = Number.parseFloat(cluster.style.top) + 74;
    expect(844 - composerHeight - characterBottom).toBe(12);
    expect(cluster.style.left).toBe("304px");
  },
);

it("uses the closer mobile home through 600px while keeping tablet clearance from 601px", () => {
  vi.stubGlobal("innerWidth", 600);
  render(<HeaderCompanion {...props} works={[]} composerHeight={132} />);
  const { cluster } = prepareDrag();
  expect(cluster.style.top).toBe("582px");
  vi.stubGlobal("innerWidth", 601);
  fireEvent(window, new Event("resize"));
  expect(cluster.style.top).toBe("534px");
});

it("repositions the mobile home above the resized keyboard dock and clamps an exceptionally short viewport", () => {
  vi.stubGlobal("innerWidth", 390);
  vi.stubGlobal("innerHeight", 844);
  const visible = Object.assign(new EventTarget(), {
    width: 390,
    height: 844,
    offsetLeft: 0,
    offsetTop: 0,
  });
  vi.stubGlobal("visualViewport", visible);
  const view = render(
    <HeaderCompanion {...props} works={[]} composerHeight={132} />,
  );
  const { cluster } = prepareDrag();
  expect(cluster.style.top).toBe("626px");
  visible.height = 420;
  visible.offsetTop = 100;
  act(() => visible.dispatchEvent(new Event("resize")));
  view.rerender(<HeaderCompanion {...props} works={[]} composerHeight={180} />);
  expect(cluster.style.top).toBe("254px");
  expect(100 + 420 - 180 - (Number.parseFloat(cluster.style.top) + 74)).toBe(
    12,
  );
  visible.height = 150;
  act(() => visible.dispatchEvent(new Event("resize")));
  expect(cluster.style.top).toBe("108px");
  visible.height = 844;
  visible.offsetTop = 0;
  act(() => visible.dispatchEvent(new Event("resize")));
  view.rerender(<HeaderCompanion {...props} works={[]} composerHeight={132} />);
  expect(cluster.style.top).toBe("626px");
});

it("tracks visualViewport resize and pan so the character and upward popover stay visible", async () => {
  vi.stubGlobal("innerWidth", 390);
  vi.stubGlobal("innerHeight", 844);
  const visible = Object.assign(new EventTarget(), {
    width: 390,
    height: 844,
    offsetLeft: 0,
    offsetTop: 0,
  });
  vi.stubGlobal("visualViewport", visible);
  const user = userEvent.setup();
  render(<HeaderCompanion {...props} works={[work]} />);
  const { trigger, cluster } = prepareDrag();
  Object.assign(visible, {
    width: 320,
    height: 420,
    offsetLeft: 30,
    offsetTop: 120,
  });
  act(() => {
    visible.dispatchEvent(new Event("resize"));
  });
  expect(cluster.style.left).toBe("264px");
  expect(cluster.style.top).toBe("346px");
  await user.click(trigger);
  const dialog = screen.getByRole("dialog");
  vi.spyOn(dialog, "getBoundingClientRect").mockReturnValue(
    rect(0, 0, 300, 250),
  );
  const action = screen.getByRole("button", { name: "梳理下一步" });
  action.focus();
  act(() => {
    visible.dispatchEvent(new Event("resize"));
  });
  expect(dialog.style.left).toBe("38px");
  expect(dialog.style.top).toBe("128px");
  expect(dialog.style.maxHeight).toBe("404px");
  visible.offsetTop = 140;
  act(() => {
    visible.dispatchEvent(new Event("scroll"));
  });
  expect(cluster.style.top).toBe("366px");
  expect(dialog.style.top).toBe("148px");
  expect(document.activeElement).toBe(action);
});
