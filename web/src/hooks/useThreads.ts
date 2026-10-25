"use client";

// The saved conversations of the sidebar: the list, and the edits a row menu makes (rename, pin, move to a project,
// export). Selection and deletion stay in the page, which owns the open conversation.

import { useCallback, useState } from "react";
import { type InvestigationItem, localStorageService } from "@/services/localStorageService";
import type { Message } from "@/types/chat";

/** One conversation as Markdown: its title, then every message under a "You" / "Tribos" heading. */
export function threadMarkdown(title: string, messages: Pick<Message, "sender" | "content">[]): string {
  const body = messages.map((m) => `## ${m.sender === "user" ? "You" : "Tribos"}\n\n${String(m.content || "").trim()}`);
  return [`# ${title}`, ...body].join("\n\n") + "\n";
}

export function useThreads() {
  const [investigations, setInvestigations] = useState<InvestigationItem[]>([]);
  const refresh = useCallback(() => {
    const list = localStorageService.getInvestigations();
    setInvestigations(list);
    return list;
  }, []);

  const rename = useCallback((id: string, title: string) => {
    if (title.trim()) localStorageService.renameInvestigation(id, title.trim());
    refresh();
  }, [refresh]);

  const togglePin = useCallback((inv: InvestigationItem) => {
    localStorageService.setPinned(inv.id, !inv.pinned);
    refresh();
  }, [refresh]);

  const moveToProject = useCallback((id: string, projectId: string | null) => {
    localStorageService.setThreadProject(id, projectId);
    refresh();
  }, [refresh]);

  const exportThread = useCallback((inv: InvestigationItem) => {
    const text = threadMarkdown(inv.title, localStorageService.getMessages(inv.id));
    const url = URL.createObjectURL(new Blob([text], { type: "text/markdown" }));
    const a = document.createElement("a");
    a.href = url;
    a.download = `${inv.title.replace(/[^A-Za-z0-9._-]+/g, "_").slice(0, 60) || "conversation"}.md`;
    a.click();
    URL.revokeObjectURL(url);
  }, []);

  return { investigations, setInvestigations, refresh, rename, togglePin, moveToProject, exportThread };
}
