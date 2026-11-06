"use client";
import { useEffect, useRef } from "react";
import { X } from "lucide-react";

export function Drawer({
  title,
  close,
  children,
}: {
  title: string;
  close: () => void;
  children: React.ReactNode;
}) {
  const dialog = useRef<HTMLDialogElement>(null);
  useEffect(() => {
    const el = dialog.current;
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    el?.showModal();
    return () => {
      el?.close();
      document.body.style.overflow = previousOverflow;
    };
  }, []);
  return (
    <dialog
      className="drawer"
      ref={dialog}
      onCancel={close}
      aria-label={title}
      onClick={(e) => {
        if (e.target === dialog.current) close();
      }}
    >
      <div className="drawer-inner">
        <header>
          <div>
            <h2>{title}</h2>
          </div>
          <button className="icon-button" onClick={close} aria-label="关闭详情">
            <X size={20} />
          </button>
        </header>
        {children}
      </div>
    </dialog>
  );
}
