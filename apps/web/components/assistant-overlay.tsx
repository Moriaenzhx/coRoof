"use client";

import { useEffect, useRef, type ReactNode } from "react";
import {
  Check,
  CircleAlert,
  LoaderCircle,
  Maximize2,
  Minus,
  Sparkles,
} from "lucide-react";
import type { AgentReaderState } from "./agent-reader";
import "./assistant-overlay.css";

export function AssistantOverlay({
  children,
  activity,
  minimized,
  obscured,
  notice,
  onMinimize,
  onRestore,
  onHistory,
  onConfigure,
}: {
  children: ReactNode;
  activity: AgentReaderState;
  minimized: boolean;
  obscured: boolean;
  notice?: string;
  onMinimize: () => void;
  onRestore: () => void;
  onHistory: () => void;
  onConfigure?: () => void;
}) {
  const panel = useRef<HTMLElement>(null);
  const chip = useRef<HTMLButtonElement>(null);
  const moveFocus = useRef(false);
  const minimize = () => {
    moveFocus.current = true;
    onMinimize();
  };
  useEffect(() => {
    if (!moveFocus.current || obscured) return;
    (minimized ? chip.current : panel.current)?.focus({ preventScroll: true });
    moveFocus.current = false;
  }, [minimized, obscured]);
  const running = activity.busy || activity.run?.state === "running";
  const stopped = Boolean(
    activity.error ||
    activity.run?.state === "failed" ||
    activity.run?.state === "interrupted",
  );
  const status = running
    ? "正在处理"
    : stopped
      ? "需要留意"
      : activity.run?.state === "completed"
        ? "处理完成"
        : activity.run?.state === "cancelled"
          ? "已停止"
          : activity.run
            ? "等待继续"
            : "准备就绪";
  const needsConfiguration = [
    "not_configured",
    "not_verified",
    "model_disabled",
  ].includes(activity.run?.error_code || "");
  const StatusIcon = running
    ? LoaderCircle
    : stopped
      ? CircleAlert
      : activity.run?.state === "completed"
        ? Check
        : Sparkles;
  useEffect(() => {
    if (minimized || obscured) return;
    const keydown = (event: KeyboardEvent) => {
      if (
        event.key === "Escape" &&
        !event.defaultPrevented &&
        !event.isComposing &&
        !document.querySelector("dialog[open], [aria-modal='true']")
      ) {
        event.preventDefault();
        moveFocus.current = true;
        onMinimize();
      }
    };
    document.addEventListener("keydown", keydown);
    return () => document.removeEventListener("keydown", keydown);
  }, [minimized, obscured, onMinimize]);
  return (
    <div className="assistant-overlay" data-obscured={obscured || undefined}>
      <section
        ref={panel}
        className="assistant-overlay-panel"
        aria-label="coRoof 处理进度与结果"
        tabIndex={-1}
        hidden={minimized || obscured}
      >
        <header className="assistant-overlay-heading">
          <div className="assistant-overlay-identity">
            <span
              className="assistant-overlay-symbol"
              data-running={running || undefined}
            >
              <StatusIcon size={19} aria-hidden="true" />
            </span>
            <div>
              <h2>coRoof</h2>
              <p role="status" aria-live="polite">
                {status}
                {running ? " · 可以先做别的事" : ""}
              </p>
            </div>
          </div>
          <button
            className="icon-button"
            onClick={minimize}
            aria-label="收起处理浮层"
            title="收起，任务继续保留"
          >
            <Minus size={19} />
          </button>
        </header>
        <div className="assistant-overlay-content">
          {notice && (
            <p className="assistant-overlay-notice" role="status">
              {notice}
            </p>
          )}
          {children}
          {!activity.run && !activity.busy && !activity.error && (
            <p className="assistant-overlay-empty">
              在下方输入问题并发送，处理过程和结果会显示在这里。
            </p>
          )}
          {needsConfiguration && (
            <div className="assistant-overlay-recovery">
              {onConfigure ? (
                <button className="secondary" onClick={onConfigure}>
                  检查企业 AI 设置
                </button>
              ) : (
                <p>请联系企业管理员检查 AI 服务。</p>
              )}
            </div>
          )}
        </div>
        <footer className="assistant-overlay-footer">
          <button className="plain" onClick={onHistory}>
            查看处理记录
          </button>
        </footer>
      </section>
      {minimized && !obscured && (
        <button
          className="assistant-overlay-chip"
          ref={chip}
          onClick={() => {
            moveFocus.current = true;
            onRestore();
          }}
          aria-label={`展开 coRoof 处理结果：${status}`}
        >
          <StatusIcon
            size={16}
            className={running ? "assistant-overlay-spin" : ""}
            aria-hidden="true"
          />
          <span>coRoof · {status}</span>
          <Maximize2 size={14} aria-hidden="true" />
        </button>
      )}
    </div>
  );
}
