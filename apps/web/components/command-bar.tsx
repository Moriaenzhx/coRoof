"use client";

import { useEffect, useId, useLayoutEffect, useRef, useState } from "react";
import { ArrowUp, Mic, Square, X } from "lucide-react";
import { useSpeechInput } from "../lib/use-speech-input";
import "./command-bar.css";

function resizeInput(input: HTMLTextAreaElement) {
  const lineHeight =
    Number.parseFloat(getComputedStyle(input).lineHeight) || 24;
  const maximum = lineHeight * 5;
  const minimumLines =
    Number.parseFloat(
      getComputedStyle(input).getPropertyValue("--composer-min-lines"),
    ) || 2;
  input.style.height = "0px";
  input.style.height = `${Math.min(Math.max(input.scrollHeight, lineHeight * minimumLines), maximum)}px`;
  input.style.overflowY = input.scrollHeight > maximum ? "auto" : "hidden";
}

export function CommandBar({
  onSubmit,
  disabled = false,
  scopeKey,
  prefill,
  contextLabel,
  onClearContext,
  clearContextLabel = "清除工作上下文",
  processing = false,
}: {
  onSubmit: (question: string) => void | boolean;
  disabled?: boolean;
  /** Identity / organization / page scope: changing it discards pending speech. */
  scopeKey?: string;
  prefill?: { id: string; text: string };
  contextLabel?: string;
  onClearContext?: () => void;
  clearContextLabel?: string;
  processing?: boolean;
}) {
  const [question, setQuestion] = useState("");
  const [focused, setFocused] = useState(false);
  const [shortcut, setShortcut] = useState("Ctrl+K");
  const questionValue = useRef("");
  const composing = useRef(false);
  const input = useRef<HTMLTextAreaElement>(null);
  const inputId = useId();
  const hintId = useId();
  const speechId = useId();
  const voice = useSpeechInput({
    disabled,
    scopeKey,
    onFinal: (text) => {
      const current = questionValue.current;
      const next = `${current}${current && !/\s$/.test(current) ? " " : ""}${text.trim()}`;
      questionValue.current = next.slice(0, 2000);
      setQuestion(questionValue.current);
      return next.length < 2000;
    },
  });
  useLayoutEffect(() => {
    composing.current = false;
  }, [scopeKey]);
  useEffect(() => {
    if (!prefill) return;
    questionValue.current = prefill.text;
    setQuestion(prefill.text);
    input.current?.focus();
  }, [prefill]);
  useEffect(() => {
    setShortcut(
      /Mac|iPhone|iPad|iPod/.test(navigator.platform) ? "⌘K" : "Ctrl+K",
    );
    let ime = false;
    const begin = () => {
      ime = true;
    };
    const end = () => {
      ime = false;
    };
    const focusInput = (event: KeyboardEvent) => {
      if (
        disabled ||
        event.defaultPrevented ||
        event.repeat ||
        ime ||
        composing.current ||
        event.isComposing ||
        event.keyCode === 229 ||
        event.altKey ||
        event.shiftKey ||
        !(event.metaKey || event.ctrlKey) ||
        (event.metaKey && event.ctrlKey) ||
        event.key.toLowerCase() !== "k" ||
        document.querySelector("dialog[open], [aria-modal='true']")
      )
        return;
      event.preventDefault();
      input.current?.focus();
    };
    document.addEventListener("compositionstart", begin);
    document.addEventListener("compositionend", end);
    document.addEventListener("keydown", focusInput);
    return () => {
      document.removeEventListener("compositionstart", begin);
      document.removeEventListener("compositionend", end);
      document.removeEventListener("keydown", focusInput);
    };
  }, [disabled]);

  useLayoutEffect(() => {
    if (input.current) resizeInput(input.current);
  }, [question, focused, voice.active, voice.message]);
  useEffect(() => {
    const field = input.current;
    if (!field) return;
    const resize = () => resizeInput(field);
    if (typeof ResizeObserver === "undefined") {
      window.addEventListener("resize", resize);
      return () => window.removeEventListener("resize", resize);
    }
    let width = field.getBoundingClientRect().width;
    const observer = new ResizeObserver(([entry]) => {
      if (!entry || entry.contentRect.width === width) return;
      width = entry.contentRect.width;
      resize();
    });
    observer.observe(field);
    return () => observer.disconnect();
  }, []);

  return (
    <form
      className="coroof-command-bar"
      data-expanded={
        focused || !!question || voice.active || !!voice.message || undefined
      }
      aria-label="向 coRoof 发送指令"
      onFocusCapture={() => setFocused(true)}
      onBlurCapture={(event) => {
        if (!event.currentTarget.contains(event.relatedTarget))
          setFocused(false);
      }}
      onSubmit={(event) => {
        event.preventDefault();
        const value = question.trim();
        if (
          disabled ||
          processing ||
          voice.active ||
          composing.current ||
          !value
        )
          return;
        if (onSubmit(value) === false) return;
        questionValue.current = "";
        setQuestion("");
      }}
    >
      {contextLabel && (
        <div className="coroof-command-context">
          <span>{contextLabel}</span>
          <button
            type="button"
            aria-label={clearContextLabel}
            title={clearContextLabel}
            disabled={processing}
            onClick={onClearContext}
          >
            <X size={13} />
          </button>
        </div>
      )}
      <label className="coroof-command-label" htmlFor={inputId}>
        告诉 coRoof 你想做什么
      </label>
      <textarea
        ref={input}
        id={inputId}
        rows={2}
        value={question}
        disabled={disabled}
        maxLength={2000}
        autoComplete="off"
        enterKeyHint="send"
        aria-describedby={`${hintId} ${speechId}`}
        aria-keyshortcuts={shortcut === "⌘K" ? "Meta+K" : "Control+K"}
        placeholder="直接问我，比如：今天有哪些事需要我处理？"
        onChange={(event) => {
          questionValue.current = event.target.value;
          setQuestion(event.target.value);
        }}
        onCompositionStart={() => {
          composing.current = true;
        }}
        onCompositionEnd={() => {
          composing.current = false;
        }}
        onKeyDown={(event) => {
          if (event.key !== "Enter") return;
          if (
            composing.current ||
            event.nativeEvent.isComposing ||
            event.nativeEvent.keyCode === 229
          ) {
            event.preventDefault();
            return;
          }
          if (event.shiftKey) return;
          event.preventDefault();
          event.currentTarget.form?.requestSubmit();
        }}
      />
      {(voice.message || voice.interim) && (
        <div
          className="coroof-command-speech-status"
          role="status"
          aria-live="polite"
          data-error={voice.error || undefined}
        >
          <span>{voice.message}</span>
          {voice.interim && (
            <span className="coroof-command-interim">
              正在识别：{voice.interim}
            </span>
          )}
        </div>
      )}
      <div className="coroof-command-footer">
        <div className="coroof-command-tools">
          <button
            type="button"
            className="coroof-command-mic"
            aria-label={voice.active ? "停止语音输入" : "开始语音输入"}
            aria-pressed={voice.active}
            disabled={disabled || voice.phase === "stopping"}
            aria-describedby={speechId}
            title="使用浏览器语音识别，可能联网处理音频；coRoof 不保存音频。转写后请检查并手动发送。"
            onClick={() => {
              if (!composing.current) {
                if (voice.active) voice.stop();
                else voice.start();
              }
            }}
          >
            {voice.active ? (
              <Square size={13} fill="currentColor" aria-hidden="true" />
            ) : (
              <Mic size={17} aria-hidden="true" />
            )}
          </button>
          <span className="coroof-command-shortcut">
            <kbd>{shortcut}</kbd> 聚焦
          </span>
        </div>
        <div className="coroof-command-send">
          <span className="coroof-command-hint" id={hintId}>
            {processing ? (
              "处理中，可先写下一个问题"
            ) : (
              <>
                Enter 发送<span> · Shift+Enter 换行</span>
              </>
            )}
          </span>
          <button
            type="submit"
            aria-label="发送指令"
            disabled={
              disabled || processing || voice.active || !question.trim()
            }
          >
            <ArrowUp size={18} strokeWidth={2.1} aria-hidden="true" />
          </button>
        </div>
      </div>
      <span className="coroof-command-label" id={speechId}>
        语音由浏览器识别，可能联网处理；coRoof
        不保存音频。转写内容需检查后手动发送。
      </span>
    </form>
  );
}
