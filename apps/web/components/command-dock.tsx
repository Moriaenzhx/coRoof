"use client";

import { useLayoutEffect, useRef, type ReactNode } from "react";

export function CommandDock({
  children,
  obscured,
  onHeight,
}: {
  children: ReactNode;
  obscured: boolean;
  onHeight: (height: number) => void;
}) {
  const dock = useRef<HTMLDivElement>(null);

  useLayoutEffect(() => {
    const element = dock.current;
    const shell = element?.closest<HTMLElement>(".app-shell");
    if (!element || !shell) return;
    const measure = () => {
      const height = Math.ceil(element.getBoundingClientRect().height);
      if (height) {
        shell.style.setProperty("--command-dock-height", `${height}px`);
        onHeight(height);
      }
    };
    const viewport = window.visualViewport;
    const align = () => {
      const bottom = viewport
        ? Math.max(0, window.innerHeight - viewport.height - viewport.offsetTop)
        : 0;
      element.style.setProperty("--keyboard-offset", `${bottom}px`);
      shell.style.setProperty("--keyboard-offset", `${bottom}px`);
      shell.toggleAttribute("data-keyboard-open", bottom > 80);
      measure();
    };
    const observer =
      typeof ResizeObserver === "undefined"
        ? null
        : new ResizeObserver(measure);
    observer?.observe(element);
    viewport?.addEventListener("resize", align);
    viewport?.addEventListener("scroll", align);
    window.addEventListener("resize", align);
    align();
    return () => {
      observer?.disconnect();
      viewport?.removeEventListener("resize", align);
      viewport?.removeEventListener("scroll", align);
      window.removeEventListener("resize", align);
      shell.style.removeProperty("--command-dock-height");
      shell.style.removeProperty("--keyboard-offset");
      shell.removeAttribute("data-keyboard-open");
    };
  }, [onHeight]);

  return (
    <div
      ref={dock}
      className="command-dock"
      data-obscured={obscured || undefined}
    >
      {children}
    </div>
  );
}
