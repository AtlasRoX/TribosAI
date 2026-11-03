"use client";

import React, { useEffect, useState } from "react";
import { Check, Copy, Link2, Pencil, RefreshCw, Square, ThumbsDown, ThumbsUp, Volume2 } from "lucide-react";

import { ExportMenu } from "@/components/ExportMenu";
import { MessageActionsExtra } from "@/components/MessageActionsExtra";
import type { Message } from "@/types/chat";

const ICON = { width: 14, height: 14 } as const;
const RATINGS_KEY = "tribos-answer-ratings";

type Rating = "up" | "down";
type Headers = (extra?: Record<string, string>) => Record<string, string>;

function loadRatings(): Record<string, Rating> {
  try {
    return JSON.parse(localStorage.getItem(RATINGS_KEY) || "{}") as Record<string, Rating>;
  } catch {
    return {};
  }
}

function saveRating(messageId: string, rating: Rating | null) {
  try {
    const all = loadRatings();
    if (rating) all[messageId] = rating;
    else delete all[messageId];
    localStorage.setItem(RATINGS_KEY, JSON.stringify(all));
  } catch {
    /* storage unavailable: the rating still reaches the backend */
  }
}

/** Plain text for speech: no code, interface blocks, math, links or Markdown marks. */
export function speakableText(markdown: string): string {
  return markdown
    .replace(/```[\s\S]*?```/g, " ")
    .replace(/\$\$[\s\S]*?\$\$/g, " ")
    .replace(/\\\[[\s\S]*?\\\]/g, " ")
    .replace(/\$[^$\n]+\$/g, " ")
    .replace(/!\[[^\]]*\]\([^)]*\)/g, " ")
    .replace(/\[([^\]]+)\]\([^)]*\)/g, "$1")
    .replace(/\[\^?\d+\]/g, "")
    .replace(/`([^`]+)`/g, "$1")
    .replace(/^\s{0,3}(#{1,6}|>|[-*+]|\d+\.)\s+/gm, "")
    .replace(/^\s*\|?[-:| ]+\|?\s*$/gm, " ")
    .replace(/[|*_~]/g, " ")
    .replace(/\s+/g, " ")
    .trim();
}

function IconButton({
  label,
  onClick,
  pressed,
  disabled,
  children,
}: {
  label: string;
  onClick: () => void;
  pressed?: boolean;
  disabled?: boolean;
  children: React.ReactNode;
}) {
  return (
    <button
      type="button"
      className={`msg-action-btn msg-icon-btn${pressed ? " is-on" : ""}`}
      onClick={onClick}
      aria-label={label}
      aria-pressed={pressed}
      title={label}
      disabled={disabled}
    >
      {children}
    </button>
  );
}

/** A short "done" state for copy-style actions. */
function useFlash(): [string | null, (key: string) => void] {
  const [flash, setFlash] = useState<string | null>(null);
  useEffect(() => {
    if (!flash) return;
    const t = setTimeout(() => setFlash(null), 1800);
    return () => clearTimeout(t);
  }, [flash]);
  return [flash, setFlash];
}

async function copyText(text: string): Promise<boolean> {
  try {
    await navigator.clipboard.writeText(text);
    return true;
  } catch {
    return false;
  }
}

export interface AnswerActionsProps {
  message: Message;
  /** The question this answer replies to ("" when unknown). */
  question: string;
  /** Answer text without the verification banner. */
  text: string;
  threadId: string;
  backendUrl: string;
  authHeaders: Headers;
  busy: boolean;
  showDetails: boolean;
  onRegenerate: () => void;
}

/** The row under an answer: copy, regenerate, rate, read aloud, export, copy link (and the research extras). */
export function AnswerActions({
  message,
  question,
  text,
  threadId,
  backendUrl,
  authHeaders,
  busy,
  showDetails,
  onRegenerate,
}: AnswerActionsProps) {
  const [flash, setFlash] = useFlash();
  // Answers come from browser storage after mount, so the saved rating can be read on first render.
  const [rating, setRating] = useState<Rating | null>(() => (typeof window === "undefined" ? null : loadRatings()[message.id] ?? null));
  const [speaking, setSpeaking] = useState(false);
  const isSystem = message.agent === "System" || !text.trim();
  const canSpeak = typeof window !== "undefined" && "speechSynthesis" in window;

  // Stop reading when the answer leaves the screen.
  useEffect(() => () => {
    if (speaking && canSpeak) window.speechSynthesis.cancel();
  }, [speaking, canSpeak]);

  const rate = (value: Rating) => {
    const next = rating === value ? null : value;
    setRating(next);
    saveRating(message.id, next);
    void fetch(`${backendUrl}/api/feedback`, {
      method: "POST",
      headers: authHeaders({ "Content-Type": "application/json" }),
      body: JSON.stringify({
        rating: next ?? "none",
        run_id: message.run_id || message.run_manifest?.run_id || null,
        thread_id: threadId || null,
        message_id: message.id,
        question: question.slice(0, 4000),
        framework: message.framework_used || null,
        model: message.model || null,
      }),
    }).catch(() => undefined);
  };

  const readAloud = () => {
    if (!canSpeak) return;
    const synth = window.speechSynthesis;
    if (speaking) {
      synth.cancel();
      setSpeaking(false);
      return;
    }
    synth.cancel();
    const utterance = new SpeechSynthesisUtterance(speakableText(text));
    utterance.rate = 1.05;
    utterance.onend = () => setSpeaking(false);
    utterance.onerror = () => setSpeaking(false);
    setSpeaking(true);
    synth.speak(utterance);
  };

  return (
    <div className="msg-actions" role="toolbar" aria-label="Answer actions">
      <IconButton
        label={flash === "copy" ? "Copied" : "Copy answer"}
        onClick={async () => (await copyText(text)) && setFlash("copy")}
        disabled={!text.trim()}
      >
        {flash === "copy" ? <Check style={{ ...ICON, color: "var(--nvidia-green)" }} /> : <Copy style={ICON} />}
      </IconButton>
      <IconButton label="Regenerate answer" onClick={onRegenerate} disabled={busy || !question}>
        <RefreshCw style={ICON} />
      </IconButton>
      {!isSystem && (
        <>
          <IconButton label={rating === "up" ? "Rated good (click to clear)" : "Good answer"} onClick={() => rate("up")} pressed={rating === "up"}>
            <ThumbsUp style={ICON} />
          </IconButton>
          <IconButton label={rating === "down" ? "Rated poor (click to clear)" : "Poor answer"} onClick={() => rate("down")} pressed={rating === "down"}>
            <ThumbsDown style={ICON} />
          </IconButton>
          {canSpeak && (
            <IconButton label={speaking ? "Stop reading" : "Read aloud"} onClick={readAloud} pressed={speaking}>
              {speaking ? <Square style={ICON} /> : <Volume2 style={ICON} />}
            </IconButton>
          )}
          <ExportMenu message={message} question={question} backendUrl={backendUrl} authHeaders={authHeaders} compact />
          {threadId && (
            <IconButton
              label={flash === "link" ? "Link copied" : "Copy link to this conversation"}
              onClick={async () => (await copyText(`${window.location.origin}/c/${threadId}`)) && setFlash("link")}
            >
              {flash === "link" ? <Check style={{ ...ICON, color: "var(--nvidia-green)" }} /> : <Link2 style={ICON} />}
            </IconButton>
          )}
        </>
      )}
      {showDetails && !isSystem && (
        <MessageActionsExtra message={message} question={question} backendUrl={backendUrl} authHeaders={authHeaders} rerunOnly />
      )}
    </div>
  );
}

export interface PromptActionsProps {
  text: string;
  busy: boolean;
  onEdit: () => void;
  onResend: () => void;
}

/** The row under the user's own prompt: copy, edit, send again. */
export function PromptActions({ text, busy, onEdit, onResend }: PromptActionsProps) {
  const [flash, setFlash] = useFlash();
  return (
    <div className="msg-actions msg-user-actions" role="toolbar" aria-label="Prompt actions">
      <IconButton
        label={flash ? "Prompt copied" : "Copy prompt"}
        onClick={async () => (await copyText(text)) && setFlash("copy")}
      >
        {flash ? <Check style={{ ...ICON, color: "var(--nvidia-green)" }} /> : <Copy style={ICON} />}
      </IconButton>
      <IconButton label="Edit prompt" onClick={onEdit} disabled={busy}>
        <Pencil style={ICON} />
      </IconButton>
      <IconButton label="Send again" onClick={onResend} disabled={busy}>
        <RefreshCw style={ICON} />
      </IconButton>
    </div>
  );
}

export interface PromptEditorProps {
  initial: string;
  onCancel: () => void;
  onSubmit: (text: string) => void;
}

/** Inline editor that replaces the prompt bubble; sending it drops the later turns and asks again. */
export function PromptEditor({ initial, onCancel, onSubmit }: PromptEditorProps) {
  const [draft, setDraft] = useState(initial);
  const ref = React.useRef<HTMLTextAreaElement>(null);

  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    el.focus();
    el.setSelectionRange(el.value.length, el.value.length);
  }, []);

  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    el.style.height = "auto";
    el.style.height = `${Math.min(el.scrollHeight, 320)}px`;
  }, [draft]);

  const submit = () => {
    if (draft.trim()) onSubmit(draft.trim());
  };

  return (
    <div className="prompt-editor">
      <textarea
        ref={ref}
        value={draft}
        aria-label="Edit prompt"
        onChange={(e) => setDraft(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === "Escape") {
            e.preventDefault();
            onCancel();
          } else if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) {
            e.preventDefault();
            submit();
          }
        }}
      />
      <div className="prompt-editor-actions">
        <span className="prompt-editor-hint">Sending replaces this turn and everything after it.</span>
        <button type="button" className="prompt-editor-btn" onClick={onCancel}>
          Cancel
        </button>
        <button type="button" className="prompt-editor-btn is-primary" onClick={submit} disabled={!draft.trim()}>
          Send
        </button>
      </div>
    </div>
  );
}

export interface UnansweredNoticeProps {
  /** The last message of the thread: it can be asked again in place. */
  isLast: boolean;
  busy: boolean;
  onRetry: () => void;
  onRemove: () => void;
}

/** Under a question that never got an answer (the page reloaded or the connection dropped mid-run). */
export function UnansweredNotice({ isLast, busy, onRetry, onRemove }: UnansweredNoticeProps) {
  return (
    <div className="msg-unanswered" role="status">
      <span>No answer arrived for this question. The page reloaded or the connection dropped while it ran.</span>
      {isLast && (
        <button type="button" className="prompt-editor-btn is-primary" onClick={onRetry} disabled={busy}>
          Ask again
        </button>
      )}
      <button type="button" className="prompt-editor-btn" onClick={onRemove} disabled={busy}>
        Remove
      </button>
    </div>
  );
}
