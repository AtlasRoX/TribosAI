/**
 * The right-hand code panel's state: which files are open and which tab is active.
 *
 * Any component opens code with `openCode(...)` (a code block's "Open" button, the Python session, construct mode's
 * best program, a Lean proof); the panel (components/CodePanel.tsx) subscribes with `useCodePanel()`.
 */
import { useSyncExternalStore } from "react";

export interface CodeFile {
  name: string;
  language: string;
  code: string;
  /** Optional text shown under the code, e.g. the cell's printed output. */
  output?: string;
}

export interface CodePanelState {
  open: boolean;
  title: string;
  files: CodeFile[];
  active: number;
}

let state: CodePanelState = { open: false, title: "", files: [], active: 0 };
const listeners = new Set<() => void>();

function set(next: CodePanelState) {
  state = next;
  listeners.forEach((l) => l());
}

export function openCode(title: string, files: CodeFile[], active = 0) {
  if (!files.length) return;
  set({ open: true, title, files, active: Math.min(Math.max(active, 0), files.length - 1) });
}

export function closeCode() {
  set({ ...state, open: false });
}

export function selectFile(index: number) {
  if (index >= 0 && index < state.files.length) set({ ...state, active: index });
}

function subscribe(listener: () => void) {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

export function useCodePanel(): CodePanelState {
  return useSyncExternalStore(subscribe, () => state, () => state);
}

const EXTENSIONS: Record<string, string> = {
  python: "py", py: "py", lean: "lean", lean4: "lean", typescript: "ts", ts: "ts", tsx: "tsx", javascript: "js",
  js: "js", json: "json", bash: "sh", sh: "sh", latex: "tex", tex: "tex", julia: "jl", r: "R", cpp: "cpp", c: "c",
  rust: "rs", go: "go", sql: "sql", yaml: "yaml", toml: "toml", markdown: "md", md: "md",
};

export function extensionFor(language: string): string {
  return EXTENSIONS[language.toLowerCase()] ?? "txt";
}
