"""
Premises for Lean repairs (docs/plans/tribos-harness-landscape.md items 2 and 13).

- Mathlib search: when Lean reports an unknown identifier or constant, the name is looked up in Loogle
  (loogle.lean-lang.org, the Mathlib search service lean-lsp-mcp also uses) and the closest real lemmas with their types
  go back to the model with the errors. Most failed formalisations call a lemma by a name that does not exist.
- Lemma library: every theorem Lean accepted is stored (statement, code, question) and the most similar ones are offered
  in later prompts, so a proof once found is reused rather than rediscovered (Seed-Prover's learning from experience).
"""

from __future__ import annotations

import json
import os
import re
import threading
import time
from pathlib import Path
from typing import Any

import httpx

LOOGLE_URL = "https://loogle.lean-lang.org/json"
_UNKNOWN_RE = re.compile(r"unknown (?:identifier|constant|declaration)\s+'?`?([A-Za-z_][\w.'₀-₉]*)", re.I)
_LOCK = threading.Lock()
MAX_LIBRARY = 2000


def unknown_names(errors: str) -> list[str]:
    seen: list[str] = []
    for m in _UNKNOWN_RE.finditer(errors or ""):
        name = m.group(1).strip("'`")
        if name not in seen:
            seen.append(name)
    return seen[:4]


def loogle(query: str, *, limit: int = 6, timeout_s: float = 8.0, transport: httpx.BaseTransport | None = None
           ) -> list[dict[str, str]]:
    """Mathlib declarations matching `query` (name substring in quotes, or a type pattern); [] on any failure."""
    try:
        with httpx.Client(timeout=timeout_s, transport=transport) as client:
            r = client.get(LOOGLE_URL, params={"q": query}, headers={"User-Agent": "Tribos/1.0 (research assistant)"})
        data = r.json() if r.status_code == 200 else {}
    except Exception:  # noqa: BLE001 - search is a hint; the repair goes ahead without it
        return []
    hits = data.get("hits") or []
    return [{"name": str(h.get("name") or ""), "type": re.sub(r"\s+", " ", str(h.get("type") or ""))[:300],
             "module": str(h.get("module") or "")} for h in hits[:limit] if h.get("name")]


def premise_hints(errors: str, *, transport: httpx.BaseTransport | None = None) -> str:
    """Real Mathlib names close to the unknown ones in `errors`, formatted for the repair prompt ("" when none)."""
    from tribos.config.settings import get_bool

    if not get_bool("TRIBOS_LEAN_PREMISE_SEARCH"):
        return ""
    lines: list[str] = []
    for name in unknown_names(errors):
        last = name.split(".")[-1]
        hits = loogle(f'"{last}"', transport=transport)
        if not hits and "_" in last:  # Nat.add_sub_cancel_left2 -> search the stem
            hits = loogle(f'"{last.rsplit("_", 1)[0]}"', transport=transport)
        if hits:
            lines.append(f"`{name}` does not exist. Mathlib has:")
            lines += [f"  - {h['name']} : {h['type']}" for h in hits]
    return "\n".join(lines)


def library_path() -> Path:
    from tribos.config.settings import get_str

    configured = str(get_str("TRIBOS_LEMMA_LIBRARY") or "").strip()
    return Path(configured) if configured else Path(os.getcwd()) / "data" / "lemma_library.json"


def _load(path: Path) -> list[dict[str, Any]]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, list) else []
    except (OSError, ValueError):
        return []


def remember(question: str, statement: str, code: str, *, path: Path | None = None) -> None:
    """Store a kernel-checked theorem (call only for status "verified")."""
    path = path or library_path()
    with _LOCK:
        items = [e for e in _load(path) if e.get("statement") != statement]
        items.append({"question": question[:1000], "statement": statement[:2000], "code": code[:8000],
                      "added": time.strftime("%Y-%m-%d")})
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(items[-MAX_LIBRARY:], ensure_ascii=False, indent=1), encoding="utf-8")
        tmp.replace(path)


def _tokens(text: str) -> set[str]:
    return set(re.findall(r"[a-zA-Z]{3,}|\d+", (text or "").lower()))


def recall(question: str, *, k: int = 3, path: Path | None = None) -> list[dict[str, Any]]:
    """The k stored theorems most similar to `question` (shared words, Jaccard), best first."""
    q = _tokens(question)
    if not q:
        return []
    scored = []
    for e in _load(path or library_path()):
        t = _tokens(e.get("question", "") + " " + e.get("statement", ""))
        overlap = len(q & t) / max(1, len(q | t))
        if overlap >= 0.2:
            scored.append((overlap, e))
    return [e for _, e in sorted(scored, key=lambda s: -s[0])[:k]]


def library_hint(question: str, *, path: Path | None = None) -> str:
    items = recall(question, path=path)
    if not items:
        return ""
    blocks = [f"-- previously proved for: {e['question'][:200]}\n{e['code']}" for e in items]
    return ("Theorems already checked by Lean in earlier runs (copy any you need into your file; rename to avoid "
            "clashes):\n```lean\n" + "\n\n".join(blocks)[:6000] + "\n```")


__all__ = ["library_hint", "library_path", "loogle", "premise_hints", "recall", "remember", "unknown_names"]
