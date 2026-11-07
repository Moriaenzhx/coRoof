"use client";

import {
  useCallback,
  useEffect,
  useLayoutEffect,
  useRef,
  useState,
} from "react";

// Browser-only interfaces; no audio buffers, uploads or persistence are created here.
export type SpeechResult = ArrayLike<{ transcript: string }> & {
  isFinal: boolean;
};
export type SpeechResultEvent = { results: ArrayLike<SpeechResult> };
export type BrowserRecognition = {
  lang: string;
  continuous: boolean;
  interimResults: boolean;
  maxAlternatives: number;
  onstart: (() => void) | null;
  onresult: ((event: SpeechResultEvent) => void) | null;
  onerror: ((event: { error: string }) => void) | null;
  onend: (() => void) | null;
  start: () => void;
  stop: () => void;
  abort: () => void;
};
type SpeechWindow = Window & {
  SpeechRecognition?: new () => BrowserRecognition;
  webkitSpeechRecognition?: new () => BrowserRecognition;
};
type Phase = "idle" | "starting" | "listening" | "stopping";
type Session = {
  recognition: BrowserRecognition;
  finals: Set<number>;
  stopping: boolean;
  timer?: number;
};
const messages: Record<string, string> = {
  "not-allowed": "未获麦克风使用许可。可在浏览器设置中允许后重试，或直接输入。",
  "service-not-allowed": "浏览器未允许语音识别服务，请使用文字输入。",
  "audio-capture": "无法使用麦克风，请检查设备和浏览器权限。",
  "no-speech": "没有听到清晰语音，可以重试或直接输入。",
  network: "语音识别服务连接失败，已识别的文字仍保留在输入框。",
  "language-not-supported": "当前浏览器的语音服务不支持中文，请使用文字输入。",
  aborted: "语音输入已停止，已识别的文字仍保留在输入框。",
};

/**
 * stop() requests a last result; abort() discards in-flight results.
 * https://developer.mozilla.org/en-US/docs/Web/API/SpeechRecognition/stop
 * https://developer.mozilla.org/en-US/docs/Web/API/SpeechRecognitionEvent/results
 */
export function useSpeechInput({
  disabled,
  scopeKey,
  onFinal,
}: {
  disabled: boolean;
  scopeKey?: string;
  /** False means the text limit was reached; stop collecting further audio. */
  onFinal: (text: string) => boolean;
}) {
  const [phase, setPhase] = useState<Phase>("idle");
  const [interim, setInterim] = useState("");
  const [message, setMessage] = useState("");
  const [error, setError] = useState(false);
  const session = useRef<Session | null>(null);
  const final = useRef(onFinal);
  useLayoutEffect(() => {
    final.current = onFinal;
  });

  const detach = useCallback((current: Session, abort: boolean) => {
    if (session.current === current) session.current = null;
    window.clearTimeout(current.timer);
    const recognition = current.recognition;
    recognition.onstart =
      recognition.onresult =
      recognition.onerror =
      recognition.onend =
        null;
    if (abort) {
      try {
        recognition.abort();
      } catch {
        /* It may already have ended. */
      }
    }
  }, []);
  const cancel = useCallback(() => {
    if (session.current) detach(session.current, true);
  }, [detach]);
  const blockForModal = useCallback(
    (announce = false) => {
      if (!document.querySelector("dialog[open], [aria-modal='true']"))
        return false;
      if (session.current) {
        detach(session.current, true);
        setPhase("idle");
        setInterim("");
        setMessage(
          "已打开其他窗口，语音输入已停止。已识别的文字保留在输入框。",
        );
        setError(false);
      } else if (announce) {
        setMessage("请先关闭当前窗口，再开始语音输入。");
        setError(false);
      }
      return true;
    },
    [detach],
  );
  useLayoutEffect(() => {
    setPhase("idle");
    setInterim("");
    setMessage("");
    setError(false);
    return cancel;
  }, [disabled, scopeKey, cancel]);
  useEffect(() => {
    const hide = () => {
      if (document.visibilityState !== "hidden" || !session.current) return;
      detach(session.current, true);
      setPhase("idle");
      setInterim("");
      setMessage("页面已进入后台，语音输入已停止。已识别的文字保留在输入框。");
      setError(false);
    };
    document.addEventListener("visibilitychange", hide);
    return () => document.removeEventListener("visibilitychange", hide);
  }, [detach]);
  useEffect(() => {
    // Feature drawers manage their own native dialogs, independently of the
    // workspace's disabled prop. Observe those dialogs and custom modal roots.
    const observer = new MutationObserver(() => blockForModal());
    observer.observe(document.documentElement, {
      subtree: true,
      childList: true,
      attributes: true,
      attributeFilter: ["open", "aria-modal"],
    });
    blockForModal();
    return () => observer.disconnect();
  }, [blockForModal]);

  function stop() {
    const current = session.current;
    if (!current || blockForModal() || current.stopping) return;
    current.stopping = true;
    setPhase("stopping");
    setMessage("正在完成转写…");
    // A service that never emits end must not leave the UI stuck listening.
    const finish = () => {
      if (session.current !== current || blockForModal()) return;
      detach(current, true);
      setPhase("idle");
      setInterim("");
      setMessage("语音输入已停止，请检查已识别的文字后发送。");
    };
    current.timer = window.setTimeout(finish, 4000);
    try {
      current.recognition.stop();
    } catch {
      finish();
    }
  }

  function start() {
    if (disabled || blockForModal(true) || session.current) return;
    const browser = window as SpeechWindow;
    const Recognition =
      browser.SpeechRecognition || browser.webkitSpeechRecognition;
    setInterim("");
    setError(false);
    if (!Recognition) {
      setMessage("当前浏览器不支持语音输入，请直接输入文字。");
      setError(true);
      return;
    }
    let current: Session | null = null;
    try {
      const recognition = new Recognition();
      current = { recognition, finals: new Set(), stopping: false };
      const active = current;
      session.current = active;
      recognition.lang = "zh-CN";
      recognition.continuous = true;
      recognition.interimResults = true;
      recognition.maxAlternatives = 1;
      setPhase("starting");
      setMessage("正在请求麦克风…");
      recognition.onstart = () => {
        if (session.current !== active || blockForModal() || active.stopping)
          return;
        setPhase("listening");
        setMessage("正在听，请说话；完成后点击停止。");
      };
      recognition.onresult = (event) => {
        if (session.current !== active || blockForModal()) return;
        const confirmed: string[] = [];
        const pending: string[] = [];
        // The result list is cumulative. Final entries are immutable; interim
        // entries can be replaced or removed by the browser on the next event.
        for (let index = 0; index < event.results.length; index++) {
          const result = event.results[index];
          const text = result[0]?.transcript || "";
          if (result.isFinal) {
            if (!active.finals.has(index)) {
              active.finals.add(index);
              if (text.trim()) confirmed.push(text);
            }
          } else pending.push(text);
        }
        setInterim(pending.join("").slice(0, 2000));
        if (confirmed.length && !final.current(confirmed.join(""))) {
          detach(active, true);
          setPhase("idle");
          setInterim("");
          setMessage("已达到 2000 字上限，语音已停止，请检查文字后发送。");
        }
      };
      recognition.onerror = (event) => {
        if (session.current !== active || blockForModal()) return;
        detach(active, true);
        setPhase("idle");
        setInterim("");
        setMessage(
          messages[event.error] || "语音识别暂时不可用，请重试或直接输入。",
        );
        setError(event.error !== "aborted");
      };
      recognition.onend = () => {
        if (session.current !== active || blockForModal()) return;
        detach(active, false);
        setPhase("idle");
        setInterim("");
        setMessage(
          active.finals.size
            ? "转写已填入，请检查后发送。"
            : "没有识别到文字，可以重试或直接输入。",
        );
      };
      recognition.start();
    } catch (reason) {
      if (current) detach(current, true);
      setPhase("idle");
      setMessage(
        reason instanceof DOMException && reason.name === "NotAllowedError"
          ? messages["not-allowed"]
          : "语音输入未能启动，请重试或直接输入。",
      );
      setError(true);
    }
  }

  return {
    active: phase !== "idle",
    phase,
    interim,
    message,
    error,
    start,
    stop,
  };
}
