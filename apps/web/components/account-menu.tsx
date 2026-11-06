"use client";
import { useEffect, useRef, useState } from "react";
import {
  ChevronUp,
  Eye,
  Gauge,
  HelpCircle,
  LogOut,
  Link2,
  Settings,
  UserRound,
} from "lucide-react";

export function AccountMenu({
  name,
  role,
  identityMode = "mock",
  organization,
  owner,
  onSelect,
  onLogout,
}: {
  name: string;
  role: string;
  identityMode?: "mock" | "oidc";
  organization: string;
  owner: boolean;
  onSelect: (
    page: "account" | "ai-settings" | "connectors" | "watch" | "help",
    aiTab?: "usage" | "connections",
  ) => void;
  onLogout: () => void;
}) {
  const [open, setOpen] = useState(false);
  const root = useRef<HTMLDivElement>(null);
  const trigger = useRef<HTMLButtonElement>(null);
  const panel = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!open) return;
    panel.current?.querySelector<HTMLButtonElement>("button")?.focus();
    const outside = (event: PointerEvent) => {
      if (!root.current?.contains(event.target as Node)) setOpen(false);
    };
    document.addEventListener("pointerdown", outside);
    return () => document.removeEventListener("pointerdown", outside);
  }, [open]);
  function close() {
    setOpen(false);
    trigger.current?.focus();
  }
  function go(
    page: "account" | "ai-settings" | "connectors" | "watch" | "help",
    aiTab?: "usage" | "connections",
  ) {
    close();
    onSelect(page, aiTab);
  }
  return (
    <div
      className="account-root"
      ref={root}
      onBlur={(event) => {
        if (!event.currentTarget.contains(event.relatedTarget)) setOpen(false);
      }}
    >
      {open && (
        <div
          className="account-popover"
          ref={panel}
          role="menu"
          aria-label="账户菜单"
          onKeyDown={(event) => {
            if (event.key === "Escape") {
              event.preventDefault();
              close();
            }
            const buttons = Array.from(
              panel.current?.querySelectorAll<HTMLButtonElement>("button") ||
                [],
            );
            const index = buttons.indexOf(
              document.activeElement as HTMLButtonElement,
            );
            if (["ArrowDown", "ArrowUp", "Home", "End"].includes(event.key)) {
              event.preventDefault();
              const next =
                event.key === "Home"
                  ? 0
                  : event.key === "End"
                    ? buttons.length - 1
                    : (index +
                        (event.key === "ArrowDown" ? 1 : -1) +
                        buttons.length) %
                      buttons.length;
              buttons[next]?.focus();
            }
          }}
        >
          <div className="account-menu-heading">
            <strong>{name}</strong>
            <small>
              {organization} · {role}
            </small>
          </div>
          <button role="menuitem" onClick={() => go("ai-settings", "usage")}>
            <Gauge size={17} />
            AI 使用情况
          </button>
          <button role="menuitem" onClick={() => go("account")}>
            <UserRound size={17} />
            个人设置
          </button>
          {owner && (
            <button
              role="menuitem"
              onClick={() => go("ai-settings", "connections")}
            >
              <Settings size={17} />
              企业 AI 设置
            </button>
          )}
          {owner && (
            <button role="menuitem" onClick={() => go("connectors")}>
              <Link2 size={17} />
              外部连接
            </button>
          )}
          {owner && (
            <button role="menuitem" onClick={() => go("watch")}>
              <Eye size={17} />
              持续关注
            </button>
          )}
          <div className="menu-divider" />
          <button role="menuitem" onClick={() => go("help")}>
            <HelpCircle size={17} />
            帮助
          </button>
          <button
            role="menuitem"
            onClick={() => {
              close();
              onLogout();
            }}
          >
            <LogOut size={17} />
            退出登录
          </button>
        </div>
      )}
      <button
        className="account-trigger"
        ref={trigger}
        aria-label="打开账户菜单"
        aria-haspopup="menu"
        aria-expanded={open}
        onClick={() => setOpen(!open)}
      >
        <span className="avatar">{name.slice(0, 1)}</span>
        <span className="account-identity">
          <strong>{name}</strong>
          <small>
            {role} · {identityMode === "oidc" ? "身份已验证" : "开发身份"}
          </small>
        </span>
        <ChevronUp size={16} className="account-chevron" />
      </button>
    </div>
  );
}
