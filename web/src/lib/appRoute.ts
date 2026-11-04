// The app's addressable places. The whole app is one page; these paths (served by app/research/[[...id]] and
// app/c/[id], which render the same page) let a link, a bookmark or the Back button land on a specific place:
//   /                      the current chat
//   /c/<conversation id>   one conversation (from this browser's history)
//   /research              research projects (the list and the new-project form)
//   /research/<research id> one research project

export type AppRoute =
  | { kind: "home" }
  | { kind: "chat"; id: string }
  | { kind: "research"; id: string | null };

const RESEARCH_RE = /^\/research(?:\/([^/]+))?\/?$/;
const CHAT_RE = /^\/c\/([^/]+)\/?$/;

export function parseRoute(pathname: string): AppRoute {
  const r = RESEARCH_RE.exec(pathname);
  if (r) return { kind: "research", id: r[1] ? decodeURIComponent(r[1]) : null };
  const c = CHAT_RE.exec(pathname);
  if (c) return { kind: "chat", id: decodeURIComponent(c[1]) };
  return { kind: "home" };
}

export function routePath(route: AppRoute): string {
  if (route.kind === "research") return route.id ? `/research/${encodeURIComponent(route.id)}` : "/research";
  if (route.kind === "chat") return `/c/${encodeURIComponent(route.id)}`;
  return "/";
}

/**
 * What a pasted identifier points at: a research id (cmp_…), a research project's conversation id (thread_cmp_…,
 * which opens the project), or a chat conversation id. A full link (…/research/cmp_…, …/c/…) works too.
 */
export function routeForId(raw: string): AppRoute | null {
  let text = raw.trim();
  if (!text) return null;
  try {
    if (/^https?:\/\//i.test(text)) text = new URL(text).pathname;
  } catch {
    // not a URL: treat as an id
  }
  if (text.startsWith("/")) {
    const r = parseRoute(text);
    return r.kind === "home" ? null : r;
  }
  const research = /^(?:thread_)?(cmp_[0-9a-f]{16})$/i.exec(text);
  if (research) return { kind: "research", id: research[1].toLowerCase() };
  return { kind: "chat", id: text };
}

/** Puts `route` in the address bar: a new history entry when `push`, else a replacement. No-op when already there. */
export function showRoute(route: AppRoute, push: boolean): void {
  if (typeof window === "undefined") return;
  const path = routePath(route);
  if (window.location.pathname === path) return;
  if (push) window.history.pushState(window.history.state, "", path);
  else window.history.replaceState(window.history.state, "", path);
}
