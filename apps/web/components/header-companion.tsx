"use client";

import {
  useEffect,
  useId,
  useLayoutEffect,
  useRef,
  useState,
  type PointerEvent as ReactPointerEvent,
} from "react";
import { createPortal } from "react-dom";
import {
  ArrowRight,
  Eye,
  Hand,
  MessageCircle,
  Pause,
  Play,
  RotateCcw,
  X,
} from "lucide-react";
import { formatTime, type Member, type Work } from "../lib/api";
import { companionContext } from "./companion-context";
import { CoRoofCharacter } from "./companion-character";
import "./header-companion.css";

const greetings = [
  "嗨，我在这里。",
  "收到你的招呼，想聊工作时叫我。",
  "先放松一下也好，我们随时再继续。",
];
const signature = (work: Work) =>
  `${work.organization_id}:${work.id}:${work.version}`;
const storageKey = (scope: string) => `coroof.companion.snoozed:${scope}`;
function savedSignatures(scope?: string): string[] {
  if (!scope || typeof window === "undefined") return [];
  try {
    const value: unknown = JSON.parse(
      sessionStorage.getItem(storageKey(scope)) || "[]",
    );
    return Array.isArray(value)
      ? value
          .filter((item): item is string => typeof item === "string")
          .slice(-200)
      : [];
  } catch {
    return [];
  }
}

type Point = { x: number; y: number };
const edge = 8;
function viewport() {
  const visible = window.visualViewport;
  return {
    left: visible?.offsetLeft || 0,
    top: visible?.offsetTop || 0,
    width:
      visible?.width ||
      document.documentElement.clientWidth ||
      window.innerWidth,
    height:
      visible?.height ||
      document.documentElement.clientHeight ||
      window.innerHeight,
  };
}
function mobileLayout() {
  return (document.documentElement.clientWidth || window.innerWidth) <= 600;
}
function clampPoint(point: Point, width: number, height: number): Point {
  const bounds = viewport();
  return {
    x: Math.max(
      bounds.left + edge,
      Math.min(point.x, bounds.left + bounds.width - width - edge),
    ),
    y: Math.max(
      bounds.top + edge,
      Math.min(point.y, bounds.top + bounds.height - height - edge),
    ),
  };
}
function samePoint(a: Point | null, b: Point): boolean {
  return a?.x === b.x && a?.y === b.y;
}

export function HeaderCompanion({
  works,
  members,
  timezone,
  onWork,
  onAsk,
  onWatch,
  loading = false,
  now = Date.now(),
  scopeKey,
  composerHeight = 108,
}: {
  works: Work[];
  members: Member[];
  timezone: string;
  onWork: (id: string) => void;
  onAsk: (workId?: string, question?: string) => void;
  onWatch?: () => void;
  loading?: boolean;
  now?: number;
  /** Tenant + member identity, for content-free tab-session reminder receipts. */
  scopeKey?: string;
  /** Measured bottom input dock height, used only to keep local UI clear. */
  composerHeight?: number;
}) {
  const [host, setHost] = useState<HTMLElement | null>(null);
  const [home, setHome] = useState<Point | null>(null);
  const [position, setPosition] = useState<Point | null>(null);
  const [bubblePosition, setBubblePosition] = useState<Point | null>(null);
  const [panelPosition, setPanelPosition] = useState<Point | null>(null);
  const [dragging, setDragging] = useState(false);
  const [open, setOpen] = useState(false);
  const [paused, setPaused] = useState(false);
  const [greeting, setGreeting] = useState(-1);
  const [waving, setWaving] = useState(false);
  const [snoozed, setSnoozed] = useState(() => ({
    scopeKey,
    signatures: savedSignatures(scopeKey),
  }));
  const bubbleElement = useRef<HTMLButtonElement>(null);
  const root = useRef<HTMLDivElement>(null);
  const drag = useRef<{
    id: number;
    start: Point;
    origin: Point;
    moved: boolean;
  } | null>(null);
  const suppressClick = useRef(false);
  const trigger = useRef<HTMLButtonElement>(null);
  const panel = useRef<HTMLDivElement>(null);
  const opener = useRef<HTMLElement | null>(null);
  const panelId = useId();
  const titleId = useId();
  const hidden = snoozed.scopeKey === scopeKey ? snoozed.signatures : [];
  const context = companionContext(
    works.filter((work) => !hidden.includes(signature(work))),
    now,
  );
  const { focus, reason, explanation, question } = context;
  const initialLoading = loading && works.length === 0;
  const important = !initialLoading && !!focus && reason !== "latest";
  const owner = members.find((member) => member.id === focus?.owner_id);
  const bubble = initialLoading
    ? "正在更新工作记录"
    : important
      ? `${focus.title} · ${reason === "support" ? "需要支持" : reason === "overdue" ? "截止情况待核实" : "还未分配负责人"}`
      : greeting >= 0
        ? greetings[greeting % greetings.length]
        : hidden.length
          ? "先不打扰，想聊时点我"
          : "有事叫我，也可以打个招呼";

  useEffect(() => {
    setSnoozed({ scopeKey, signatures: savedSignatures(scopeKey) });
    setOpen(false);
    setGreeting(-1);
    setPosition(null);
  }, [scopeKey]);
  useEffect(() => setHost(document.body), []);
  useLayoutEffect(() => {
    if (!host) return;
    const measure = () => {
      if (!root.current) return;
      const visible = viewport();
      const aboveComposer = visible.width <= 1100;
      const bottom = mobileLayout()
        ? composerHeight + 12
        : aboveComposer
          ? Math.max(180, composerHeight + 44)
          : 24;
      const size = root.current.getBoundingClientRect();
      const width = size.width || (mobileLayout() ? 62 : 72);
      const height = size.height || (mobileLayout() ? 74 : 86);
      const next = clampPoint(
        {
          x: visible.left + visible.width - width - 24,
          y: visible.top + visible.height - height - bottom,
        },
        width,
        height,
      );
      setHome((current) => (samePoint(current, next) ? current : next));
      setPosition((current) => {
        if (!current) return current;
        const bounded = clampPoint(current, width, height);
        return samePoint(current, bounded) ? current : bounded;
      });
      const target = position ? clampPoint(position, width, height) : next;
      if (bubbleElement.current) {
        bubbleElement.current.style.maxWidth = `${Math.min(mobileLayout() ? 174 : 215, Math.max(0, visible.width - width - 3 * edge))}px`;
        const bubbleSize = bubbleElement.current.getBoundingClientRect();
        const bubbleWidth = bubbleSize.width || (mobileLayout() ? 174 : 215);
        const bubbleHeight = bubbleSize.height || 34;
        const left = target.x - bubbleWidth - edge;
        const point = clampPoint(
          {
            x: left >= visible.left + edge ? left : target.x + width + edge,
            // Narrow viewports reserve the input area below the character.
            // On wide screens only the reminder needs to sit above it.
            y: aboveComposer
              ? target.y + (height - bubbleHeight) / 2
              : Math.min(
                  target.y - bubbleHeight - 20,
                  visible.top +
                    visible.height -
                    Math.max(90, composerHeight + 24) -
                    bubbleHeight,
                ),
          },
          bubbleWidth,
          bubbleHeight,
        );
        setBubblePosition((current) =>
          samePoint(current, point) ? current : point,
        );
      }
    };
    measure();
    const observer =
      typeof ResizeObserver === "undefined"
        ? null
        : new ResizeObserver(measure);
    if (root.current) observer?.observe(root.current);
    if (bubbleElement.current) observer?.observe(bubbleElement.current);
    window.addEventListener("resize", measure);
    window.addEventListener("scroll", measure, true);
    window.visualViewport?.addEventListener("resize", measure);
    window.visualViewport?.addEventListener("scroll", measure);
    return () => {
      observer?.disconnect();
      window.removeEventListener("resize", measure);
      window.removeEventListener("scroll", measure, true);
      window.visualViewport?.removeEventListener("resize", measure);
      window.visualViewport?.removeEventListener("scroll", measure);
    };
  }, [host, position, bubble, composerHeight]);
  useLayoutEffect(() => {
    if (!open) return;
    const measure = () => {
      if (!root.current || !panel.current) return;
      const visible = viewport();
      panel.current.style.maxWidth = `${visible.width - 2 * edge}px`;
      panel.current.style.maxHeight = `${Math.min(540, visible.height - 2 * edge)}px`;
      const target = root.current.getBoundingClientRect();
      const size = panel.current.getBoundingClientRect();
      const below = target.bottom + edge;
      const above = target.top - size.height - edge;
      const top =
        above >= visible.top + edge
          ? above
          : below + size.height <= visible.top + visible.height - edge
            ? below
            : visible.top + edge;
      const next = clampPoint(
        { x: target.right - size.width, y: top },
        size.width,
        size.height,
      );
      setPanelPosition((current) =>
        samePoint(current, next) ? current : next,
      );
    };
    measure();
    const observer =
      typeof ResizeObserver === "undefined"
        ? null
        : new ResizeObserver(measure);
    if (panel.current) observer?.observe(panel.current);
    window.addEventListener("resize", measure);
    window.addEventListener("scroll", measure, true);
    window.visualViewport?.addEventListener("resize", measure);
    window.visualViewport?.addEventListener("scroll", measure);
    return () => {
      observer?.disconnect();
      window.removeEventListener("resize", measure);
      window.removeEventListener("scroll", measure, true);
      window.visualViewport?.removeEventListener("resize", measure);
      window.visualViewport?.removeEventListener("scroll", measure);
    };
  }, [open, position, home, bubble, loading]);
  useEffect(() => {
    if (!waving) return;
    const timeout = window.setTimeout(() => setWaving(false), 1600);
    return () => window.clearTimeout(timeout);
  }, [waving, greeting]);
  useEffect(() => {
    if (!open) return;
    panel.current?.focus();
    const outside = (event: PointerEvent | FocusEvent) => {
      if (!root.current?.contains(event.target as Node)) setOpen(false);
    };
    document.addEventListener("pointerdown", outside);
    document.addEventListener("focusin", outside);
    return () => {
      document.removeEventListener("pointerdown", outside);
      document.removeEventListener("focusin", outside);
    };
  }, [open]);

  function close(restoreFocus = true) {
    setOpen(false);
    if (restoreFocus) (opener.current || trigger.current)?.focus();
  }
  function show(source: HTMLElement, greet = false) {
    opener.current = source;
    if (greet) {
      setGreeting((value) => value + 1);
      setWaving(true);
    }
    setOpen(true);
  }
  function go(action: () => void) {
    // Native dialogs remember the focused opener. Move focus out of this
    // temporary panel before it unmounts and the parent opens its drawer.
    close();
    action();
  }
  function startDrag(event: ReactPointerEvent<HTMLButtonElement>) {
    if (event.button !== 0 || event.isPrimary === false || !root.current)
      return;
    const bounds = root.current.getBoundingClientRect();
    suppressClick.current = false;
    drag.current = {
      id: event.pointerId,
      start: { x: event.clientX, y: event.clientY },
      origin: { x: bounds.left, y: bounds.top },
      moved: false,
    };
    event.currentTarget.setPointerCapture?.(event.pointerId);
  }
  function moveDrag(event: ReactPointerEvent<HTMLButtonElement>) {
    const gesture = drag.current;
    if (!gesture || gesture.id !== event.pointerId || !root.current) return;
    const delta = {
      x: event.clientX - gesture.start.x,
      y: event.clientY - gesture.start.y,
    };
    if (!gesture.moved && Math.hypot(delta.x, delta.y) < 6) return;
    gesture.moved = true;
    suppressClick.current = true;
    setDragging(true);
    setOpen(false);
    event.preventDefault();
    const bounds = root.current.getBoundingClientRect();
    setPosition(
      clampPoint(
        { x: gesture.origin.x + delta.x, y: gesture.origin.y + delta.y },
        bounds.width,
        bounds.height,
      ),
    );
  }
  function finishDrag(event: ReactPointerEvent<HTMLButtonElement>) {
    if (drag.current?.id !== event.pointerId) return;
    suppressClick.current = drag.current.moved;
    drag.current = null;
    setDragging(false);
    if (event.currentTarget.hasPointerCapture?.(event.pointerId)) {
      event.currentTarget.releasePointerCapture(event.pointerId);
    }
  }
  function snooze() {
    if (!focus || !important) return;
    const signatures = [...new Set([...hidden, signature(focus)])].slice(-200);
    setSnoozed({ scopeKey, signatures });
    if (scopeKey) {
      try {
        sessionStorage.setItem(
          storageKey(scopeKey),
          JSON.stringify(signatures),
        );
      } catch {
        // The in-memory receipt still suppresses repeated refresh reminders.
      }
    }
    close();
  }

  return (
    <>
      {host &&
        createPortal(
          <div
            className="header-companion header-companion-floating"
            ref={root}
            data-floating={!!position || undefined}
            data-dragging={dragging || undefined}
            style={{
              left: (position || home)?.x ?? 0,
              top: (position || home)?.y ?? 0,
              visibility: home ? undefined : "hidden",
            }}
            data-attention={important || undefined}
            onKeyDown={(event) => {
              if (open && event.key === "Escape") {
                event.preventDefault();
                event.stopPropagation();
                close();
              }
            }}
          >
            <button
              className="header-companion-character"
              ref={trigger}
              aria-label="和 coRoof 打个招呼"
              aria-haspopup="dialog"
              aria-expanded={open}
              aria-controls={open ? panelId : undefined}
              title="点击打招呼，拖动换个位置"
              onPointerDown={startDrag}
              onPointerMove={moveDrag}
              onPointerUp={finishDrag}
              onPointerCancel={finishDrag}
              onLostPointerCapture={finishDrag}
              onClick={(event) => {
                if (suppressClick.current && event.detail !== 0) {
                  suppressClick.current = false;
                  event.preventDefault();
                  return;
                }
                suppressClick.current = false;
                if (open) close();
                else show(event.currentTarget, true);
              }}
            >
              <CoRoofCharacter
                state={waving ? "greeting" : important ? "attention" : "idle"}
                paused={paused}
              />
            </button>
            <button
              ref={bubbleElement}
              className="header-companion-bubble"
              style={{
                left: bubblePosition?.x ?? edge,
                top: bubblePosition?.y ?? edge,
              }}
              aria-label={
                important ? `查看提醒：${bubble}` : "打开 coRoof 工作伙伴"
              }
              title={bubble}
              aria-haspopup="dialog"
              aria-expanded={open}
              aria-controls={open ? panelId : undefined}
              onClick={(event) => (open ? close() : show(event.currentTarget))}
            >
              {important && (
                <span className="header-companion-dot" aria-hidden="true" />
              )}
              <span className="header-companion-bubble-copy">{bubble}</span>
              <span className="header-companion-mobile-copy" aria-hidden="true">
                {important ? "看提醒" : "聊一聊"}
              </span>
            </button>

            {open && (
              <div
                id={panelId}
                ref={panel}
                role="dialog"
                aria-modal="false"
                aria-labelledby={titleId}
                tabIndex={-1}
                className="header-companion-popover"
                style={{
                  left: panelPosition?.x ?? edge,
                  top: panelPosition?.y ?? edge,
                }}
              >
                <div className="header-companion-popover-heading">
                  <div>
                    <h2 id={titleId}>coRoof 工作伙伴</h2>
                    <p className="header-companion-source">
                      按已记录工作整理 · 未调用模型
                    </p>
                  </div>
                  <button
                    className="header-companion-close"
                    aria-label="关闭伙伴浮层"
                    onClick={() => close()}
                  >
                    <X size={16} />
                  </button>
                </div>
                {loading && !initialLoading && (
                  <small className="header-companion-updating" role="status">
                    正在更新记录
                  </small>
                )}
                {greeting >= 0 && (
                  <p className="header-companion-reply" role="status">
                    {greetings[greeting % greetings.length]}
                  </p>
                )}
                {initialLoading ? (
                  <p className="header-companion-copy">
                    正在读取工作记录。你仍然可以打个招呼。
                  </p>
                ) : focus ? (
                  <div className="header-companion-fact">
                    <span className="header-companion-eyebrow">
                      {important
                        ? "有一件事值得核实"
                        : "也可以从最近的记录聊起"}
                    </span>
                    <h3>{focus.title}</h3>
                    <p className="header-companion-copy">{explanation}</p>
                    <p className="header-companion-metadata">
                      {owner
                        ? `${owner.name}负责`
                        : focus.owner_id
                          ? "负责人信息未载入"
                          : "未分配负责人"}
                      <br />
                      记录更新 {formatTime(focus.updated_at, timezone)}
                      {reason === "overdue" && (
                        <>
                          <br />
                          记录截止 {formatTime(focus.due_at, timezone)}
                        </>
                      )}
                    </p>
                    <div className="header-companion-actions">
                      <button onClick={() => go(() => onWork(focus.id))}>
                        查看工作记录 <ArrowRight size={14} />
                      </button>
                      <button
                        onClick={() => go(() => onAsk(focus.id, question))}
                      >
                        梳理下一步
                      </button>
                    </div>
                    {important && (
                      <button
                        className="header-companion-snooze"
                        onClick={snooze}
                      >
                        暂时收起
                      </button>
                    )}
                    {important && (
                      <small className="header-companion-snooze-hint">
                        {scopeKey
                          ? "本次会话不重复提醒这条记录；记录更新后再提示。"
                          : "本次查看先收起这条提醒；记录更新后再提示。"}
                      </small>
                    )}
                  </div>
                ) : (
                  <p className="header-companion-copy">
                    {hidden.length
                      ? "刚才的提醒已暂缓。想继续时，可以打开工作记录或和我聊聊。"
                      : "没有需要在这里提示的已记录事项。尚未记录的情况仍然未知。"}
                  </p>
                )}
                <div className="header-companion-local-actions">
                  <button
                    onClick={() => {
                      setGreeting((value) => value + 1);
                      setWaving(true);
                    }}
                  >
                    <Hand size={14} />
                    打个招呼
                  </button>
                  <button
                    disabled={initialLoading}
                    onClick={() => go(() => onAsk())}
                  >
                    <MessageCircle size={14} />
                    聊聊工作
                  </button>
                </div>
                <div className="header-companion-footer">
                  {position && (
                    <button
                      onClick={() => {
                        setPosition(null);
                        close();
                      }}
                    >
                      <RotateCcw size={13} />
                      恢复原位
                    </button>
                  )}
                  {onWatch && (
                    <button onClick={() => go(onWatch)}>
                      <Eye size={13} />
                      持续关注
                    </button>
                  )}
                  <button
                    aria-pressed={paused}
                    aria-label={paused ? "恢复伙伴动画" : "暂停伙伴动画"}
                    onClick={() => setPaused(!paused)}
                  >
                    {paused ? <Play size={13} /> : <Pause size={13} />}
                    {paused ? "恢复动画" : "暂停动画"}
                  </button>
                </div>
              </div>
            )}
          </div>,
          host,
        )}
    </>
  );
}
