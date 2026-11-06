import { StrictMode } from "react";
import { act, cleanup, render } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { CommandDock } from "../components/command-dock";

class TestViewport extends EventTarget {
  height = 800;
  offsetTop = 0;
}

class TestResizeObserver {
  static instances: TestResizeObserver[] = [];
  observe = vi.fn();
  disconnect = vi.fn();
  constructor(private readonly callback: ResizeObserverCallback) {
    TestResizeObserver.instances.push(this);
  }
  resize() {
    this.callback([], this as unknown as ResizeObserver);
  }
}

let viewport: TestViewport;
let dockHeight: number;

beforeEach(() => {
  viewport = new TestViewport();
  dockHeight = 148.2;
  TestResizeObserver.instances = [];
  vi.stubGlobal("innerHeight", 800);
  vi.stubGlobal("visualViewport", viewport);
  vi.stubGlobal("ResizeObserver", TestResizeObserver);
  vi.spyOn(HTMLElement.prototype, "getBoundingClientRect").mockImplementation(
    function (this: HTMLElement) {
      return new DOMRect(
        0,
        0,
        390,
        this.classList.contains("command-dock") ? dockHeight : 0,
      );
    },
  );
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

function shell(onHeight: (height: number) => void, obscured = false) {
  return (
    <div className="app-shell">
      <CommandDock onHeight={onHeight} obscured={obscured}>
        <textarea aria-label="指令" />
      </CommandDock>
    </div>
  );
}

function elements(container: HTMLElement) {
  return {
    shell: container.querySelector<HTMLElement>(".app-shell")!,
    dock: container.querySelector<HTMLElement>(".command-dock")!,
  };
}

it("shares the measured dock including its navigation space with every consumer", () => {
  const onHeight = vi.fn();
  const view = render(shell(onHeight));
  const nodes = elements(view.container);
  const observer = TestResizeObserver.instances[0];
  expect(observer.observe).toHaveBeenCalledWith(nodes.dock);
  expect(nodes.shell.style.getPropertyValue("--command-dock-height")).toBe(
    "149px",
  );
  expect(onHeight).toHaveBeenLastCalledWith(149);

  // Expansion, speech text, safe area and navigation all affect this one box.
  dockHeight = 237.4;
  act(() => observer.resize());
  expect(nodes.shell.style.getPropertyValue("--command-dock-height")).toBe(
    "238px",
  );
  expect(onHeight).toHaveBeenLastCalledWith(238);
  const calls = onHeight.mock.calls.length;
  dockHeight = 0;
  act(() => observer.resize());
  expect(onHeight).toHaveBeenCalledTimes(calls);
  expect(nodes.shell.style.getPropertyValue("--command-dock-height")).toBe(
    "238px",
  );
});

it("tracks viewport resize and pan, marking navigation hidden only for a keyboard-sized inset", () => {
  const onHeight = vi.fn();
  const view = render(shell(onHeight));
  const nodes = elements(view.container);
  expect(nodes.shell.hasAttribute("data-keyboard-open")).toBe(false);
  expect(nodes.dock.style.getPropertyValue("--keyboard-offset")).toBe("0px");

  viewport.height = 500;
  viewport.offsetTop = 24;
  dockHeight = 86; // Navigation has left the measured bottom area.
  act(() => viewport.dispatchEvent(new Event("resize")));
  expect(nodes.dock.style.getPropertyValue("--keyboard-offset")).toBe("276px");
  expect(nodes.shell.style.getPropertyValue("--keyboard-offset")).toBe("276px");
  expect(nodes.shell.hasAttribute("data-keyboard-open")).toBe(true);
  expect(nodes.shell.style.getPropertyValue("--command-dock-height")).toBe(
    "86px",
  );
  expect(onHeight).toHaveBeenLastCalledWith(86);

  viewport.height = 700;
  viewport.offsetTop = 20;
  act(() => viewport.dispatchEvent(new Event("scroll")));
  expect(nodes.shell.style.getPropertyValue("--keyboard-offset")).toBe("80px");
  expect(nodes.shell.hasAttribute("data-keyboard-open")).toBe(false);

  viewport.height = 780;
  viewport.offsetTop = 40;
  act(() => viewport.dispatchEvent(new Event("scroll")));
  expect(nodes.dock.style.getPropertyValue("--keyboard-offset")).toBe("0px");
  expect(nodes.shell.style.getPropertyValue("--keyboard-offset")).toBe("0px");
});

it("still measures window resize when visualViewport and ResizeObserver are unavailable", () => {
  vi.stubGlobal("visualViewport", undefined);
  vi.stubGlobal("ResizeObserver", undefined);
  const onHeight = vi.fn();
  const view = render(shell(onHeight));
  const nodes = elements(view.container);
  expect(nodes.shell.hasAttribute("data-keyboard-open")).toBe(false);
  dockHeight = 166;
  act(() => window.dispatchEvent(new Event("resize")));
  expect(onHeight).toHaveBeenLastCalledWith(166);
  expect(nodes.shell.style.getPropertyValue("--command-dock-height")).toBe(
    "166px",
  );
  expect(nodes.shell.style.getPropertyValue("--keyboard-offset")).toBe("0px");
});

it("obscures the dock for a dialog without discarding its measured clearance", () => {
  const onHeight = vi.fn();
  const view = render(shell(onHeight));
  view.rerender(shell(onHeight, true));
  const nodes = elements(view.container);
  expect(nodes.dock.hasAttribute("data-obscured")).toBe(true);
  expect(nodes.shell.style.getPropertyValue("--command-dock-height")).toBe(
    "149px",
  );
  expect(TestResizeObserver.instances).toHaveLength(1);
  view.rerender(shell(onHeight));
  expect(nodes.dock.hasAttribute("data-obscured")).toBe(false);
});

it("disconnects observers and removes viewport listeners and shared state on unmount", () => {
  viewport.height = 500;
  const onHeight = vi.fn();
  const removeViewport = vi.spyOn(viewport, "removeEventListener");
  const removeWindow = vi.spyOn(window, "removeEventListener");
  const view = render(shell(onHeight));
  const nodes = elements(view.container);
  expect(nodes.shell.hasAttribute("data-keyboard-open")).toBe(true);
  view.unmount();
  expect(TestResizeObserver.instances[0].disconnect).toHaveBeenCalledOnce();
  expect(removeViewport).toHaveBeenCalledWith("resize", expect.any(Function));
  expect(removeViewport).toHaveBeenCalledWith("scroll", expect.any(Function));
  expect(removeWindow).toHaveBeenCalledWith("resize", expect.any(Function));
  expect(nodes.shell.style.getPropertyValue("--command-dock-height")).toBe("");
  expect(nodes.shell.style.getPropertyValue("--keyboard-offset")).toBe("");
  expect(nodes.shell.hasAttribute("data-keyboard-open")).toBe(false);
  onHeight.mockClear();
  act(() => {
    viewport.dispatchEvent(new Event("resize"));
    viewport.dispatchEvent(new Event("scroll"));
    window.dispatchEvent(new Event("resize"));
  });
  expect(onHeight).not.toHaveBeenCalled();
});

it("keeps only the current listeners after StrictMode effect replay", () => {
  const onHeight = vi.fn();
  const view = render(<StrictMode>{shell(onHeight)}</StrictMode>);
  expect(TestResizeObserver.instances).toHaveLength(2);
  expect(TestResizeObserver.instances[0].disconnect).toHaveBeenCalledOnce();
  onHeight.mockClear();
  viewport.height = 500;
  act(() => viewport.dispatchEvent(new Event("resize")));
  expect(onHeight).toHaveBeenCalledOnce();
  expect(
    elements(view.container).shell.hasAttribute("data-keyboard-open"),
  ).toBe(true);
});
