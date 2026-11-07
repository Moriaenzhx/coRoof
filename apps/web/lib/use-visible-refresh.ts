"use client";
import { useEffect } from "react";

// Poll only while the workspace is visible. Reading never starts model work.
export function useVisibleRefresh(
  refresh: () => Promise<unknown>,
  enabled: boolean,
) {
  useEffect(() => {
    if (!enabled) return;
    let running = false;
    let active = true;
    const update = async () => {
      if (
        !active ||
        running ||
        document.visibilityState === "hidden" ||
        !navigator.onLine
      )
        return;
      running = true;
      try {
        await refresh();
      } catch {
        /* Caller owns error and stale-data handling. */
      } finally {
        running = false;
      }
    };
    const timer = window.setInterval(() => void update(), 30000);
    const wake = () => void update();
    window.addEventListener("focus", wake);
    window.addEventListener("online", wake);
    document.addEventListener("visibilitychange", wake);
    return () => {
      active = false;
      clearInterval(timer);
      window.removeEventListener("focus", wake);
      window.removeEventListener("online", wake);
      document.removeEventListener("visibilitychange", wake);
    };
  }, [refresh, enabled]);
}
