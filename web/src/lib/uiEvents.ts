/**
 * Page-wide UI events between components that do not share state: a card asking the page to send a question, the
 * answer asking a card to highlight a value, the keyboard opening or closing every card.
 */

export interface UiEvents {
  /** Put a question in the composer (send: true sends it right away). */
  "tribos:ask": { text: string; send?: boolean };
  /** Open (true) or close (false) every collapsible card. */
  "tribos:cards": { open: boolean };
  /** Highlight the element that holds a computed value ("param:steady_state_amplitude"). */
  "tribos:highlight": { key: string };
  /** Open a tab of the evidence deck under one answer (messageId) and scroll to it. */
  "tribos:evidence-tab": { tab: "literature" | "hypotheses" | "verification" | "diagnostics"; messageId?: string };
}

export function emitUi<K extends keyof UiEvents>(name: K, detail: UiEvents[K]): void {
  if (typeof window === "undefined") return;
  window.dispatchEvent(new CustomEvent(name, { detail }));
}

export function onUi<K extends keyof UiEvents>(name: K, handler: (detail: UiEvents[K]) => void): () => void {
  if (typeof window === "undefined") return () => undefined;
  const listener = (e: Event) => handler((e as CustomEvent<UiEvents[K]>).detail);
  window.addEventListener(name, listener);
  return () => window.removeEventListener(name, listener);
}

/** True when a keyboard shortcut should not fire because the user is typing. */
export function isTypingTarget(target: EventTarget | null): boolean {
  const el = target as HTMLElement | null;
  return Boolean(el && (el.closest("input, textarea, select, [contenteditable='true']") || el.isContentEditable));
}
