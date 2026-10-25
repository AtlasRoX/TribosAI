"use client";

import React, { useEffect, useMemo, useState } from "react";
import { ListTree } from "lucide-react";
import { answerSections } from "@/lib/sections";

export { answerSections, sectionSlug } from "@/lib/sections";

/**
 * Contents of a long answer (four or more sections): a sticky row of section links that marks the section in view.
 */
export function AnswerToc({ content, messageId }: { content: string; messageId: string }) {
  const sections = useMemo(() => answerSections(content), [content]);
  const [current, setCurrent] = useState<string>("");
  const [open, setOpen] = useState(false);

  useEffect(() => {
    if (sections.length < 4 || typeof IntersectionObserver === "undefined") return;
    const root = document.querySelector(`[data-message-id="${CSS.escape(messageId)}"]`);
    if (!root) return;
    const heads = Array.from(root.querySelectorAll<HTMLElement>("[data-section]"));
    const observer = new IntersectionObserver(
      (entries) => {
        const visible = entries.filter((e) => e.isIntersecting).sort((a, b) => a.boundingClientRect.top - b.boundingClientRect.top);
        if (visible[0]) setCurrent(visible[0].target.getAttribute("data-section") || "");
      },
      { rootMargin: "0px 0px -70% 0px" }
    );
    heads.forEach((h) => observer.observe(h));
    return () => observer.disconnect();
  }, [sections, messageId]);

  if (sections.length < 4) return null;
  const go = (slug: string) => {
    const root = document.querySelector(`[data-message-id="${CSS.escape(messageId)}"]`);
    root?.querySelector<HTMLElement>(`[data-section="${CSS.escape(slug)}"]`)?.scrollIntoView({ behavior: "smooth", block: "start" });
    setOpen(false);
  };
  const index = sections.findIndex((s) => s.slug === current);

  return (
    <nav className="answer-toc" aria-label="Sections of this answer">
      <button type="button" className="answer-toc-toggle" aria-expanded={open} onClick={() => setOpen((o) => !o)}>
        <ListTree style={{ width: 13, height: 13 }} aria-hidden="true" />
        <span>{index >= 0 ? sections[index].title : "Contents"}</span>
        <span className="answer-toc-count">
          {index >= 0 ? `${index + 1} of ${sections.length}` : `${sections.length} sections`}
        </span>
      </button>
      {open && (
        <ol className="answer-toc-list">
          {sections.map((s) => (
            <li key={s.slug}>
              <button type="button" data-current={s.slug === current || undefined} onClick={() => go(s.slug)}>
                {s.title}
              </button>
            </li>
          ))}
        </ol>
      )}
    </nav>
  );
}
