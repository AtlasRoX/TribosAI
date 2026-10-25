/** Sections of an answer: the slugs on its headings and the list the contents bar shows. */

/** "1. Analytical Solution" -> "1-analytical-solution": the data-section slug the renderer puts on each heading. */
export function sectionSlug(title: string): string {
  return title
    .toLowerCase()
    .replace(/[$\\*`_]/g, "")
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-|-$/g, "")
    .slice(0, 60);
}

/** Second-level headings of an answer's Markdown (outside code fences), in order. */
export function answerSections(markdown: string): { title: string; slug: string }[] {
  const out: { title: string; slug: string }[] = [];
  let fenced = false;
  for (const line of markdown.split("\n")) {
    if (/^```/.test(line)) fenced = !fenced;
    const m = !fenced && /^##\s+(.+?)\s*#*\s*$/.exec(line);
    if (m) out.push({ title: m[1].replace(/\*\*/g, ""), slug: sectionSlug(m[1]) });
  }
  return out;
}
