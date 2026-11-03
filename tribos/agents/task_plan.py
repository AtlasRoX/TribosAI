"""The task plan: the parts a question asks for, each paired with the tool that does it.

"Solve this ODE, plot x(t), prove the energy decays and check it in Python" is four jobs for four tools (the SymPy
mathematics agent, matplotlib in the sandbox, reasoning or Lean, a Python session). The plan is read from the question
without a model call (tribos.agents.deliverables.requested_items finds the imperative clauses), shown to the reader as
a checklist while the run works, used to make sure each tool runs, given to the writer so the answer follows it part
by part, and closed with each step's outcome from the run's artifacts.
"""

from __future__ import annotations

import re
from typing import Any

# kind -> (tool label shown to the reader, short verb for the step title)
TOOLS: dict[str, str] = {
    "solve": "SymPy (verified math agent)",
    "formal_proof": "Lean 4 + Mathlib",
    "proof": "reasoning, checked with SymPy",
    "plot": "matplotlib (sandbox)",
    "simulate": "SciPy ODE/PDE solvers",
    "code": "Python (sandbox)",
    "sources": "literature search",
    "compare": "reasoning over the results",
    "optimize": "SciPy optimization",
    "explain": "reasoning",
    "file": "file export",
}

_PLOT_RE = re.compile(r"\b(?:plot|graph|chart|visuali[sz]e|sketch|draw|contour|histogram|heat\s?map|phase\s+portrait)\b", re.I)
_LEAN_RE = re.compile(r"\b(?:lean|mathlib|formal(?:ly)?(?:\s+(?:proof|verif\w*))?|machine[-\s]checked)\b", re.I)
_CODE_RE = re.compile(r"\b(?:python|code|script|numerically|numerical(?:ly)?|program|sandbox|monte\s+carlo)\b", re.I)
_SOURCES_RE = re.compile(r"\b(?:cite|citations?|papers?|literature|sources?|references?|published|studies)\b", re.I)
_PROOF_VERBS = {"prove", "disprove", "refute", "show"}
_SOLVE_VERBS = {"solve", "find", "calculate", "compute", "determine", "evaluate", "derive", "estimate", "quantify",
                "predict", "report", "give", "state", "return", "identify"}
_STEP_VERBS = r"(?:plot|graph|prove|show|verify|check|simulate|compute|calculate|find|derive|explain|compare|cite|give|write|export)"
# The opening clause runs to the next part ("..., plot x(t)", "and prove ..."), not to the first comma: "with x(0)=1,
# x'(0)=0" belongs to it.
_LEADING_VERB_RE = re.compile(
    r"^\s*(solve|find|calculate|compute|determine|evaluate|derive|simulate|prove|plot)\b\s+(.+?)"
    rf"(?=\s*(?:[,;]\s*(?:and\s+|then\s+)?{_STEP_VERBS}\b|\band\s+{_STEP_VERBS}\b|\bthen\b|[.?!]?\s*$))",
    re.I | re.S,
)
_ONE_PER_TOOL = frozenset({"plot", "code", "file", "sources", "formal_proof", "simulate"})
_FILE_WORDS_RE = re.compile(r"\b(?:word|docx|pdf|csv|excel|xlsx|spreadsheet|notebook|ipynb|markdown|report|file|download)\b", re.I)
_VERB_START_RE = re.compile(r"^(?:cite|list|give|provide|include|find|show|write)\b", re.I)


def _kind(verb: str, item: str) -> str:
    v, text = verb.lower(), f"{verb} {item}"
    if v == "plot" or _PLOT_RE.search(text):
        return "plot"
    if v == "simulate":
        return "simulate"
    if v in _PROOF_VERBS:
        return "formal_proof" if _LEAN_RE.search(text) else "proof"
    if v in ("verify", "check", "test"):
        if _LEAN_RE.search(text):
            return "formal_proof"
        return "code" if _CODE_RE.search(text) else "proof"
    if v == "compare":
        return "sources" if _SOURCES_RE.search(item) else "compare"
    if _SOURCES_RE.search(item) and v in ("cite", "list", "give", "provide", "include", "find"):
        return "sources"
    if _CODE_RE.search(text) and v in _SOLVE_VERBS:
        return "code"
    if v in _SOLVE_VERBS:
        return "solve"
    return "explain"


def _short(text: str, limit: int = 90) -> str:
    """A step title: plain text (no LaTeX), cut at a word boundary."""
    from ..utils.plain_math import plain_math

    text = re.sub(r"\s+", " ", plain_math(text)).strip(" .,;:")
    if len(text) <= limit:
        return text
    return text[:limit].rsplit(" ", 1)[0].rstrip(" ,;:") + "…"


def _title(verb: str, item: str) -> str:
    item = _short(item)
    if _VERB_START_RE.match(item):  # "cite papers" under the verb "compare": the item names its own action
        return item[:1].upper() + item[1:]
    return f"{verb.capitalize()} {item}"


_NUMBERED_RE = re.compile(r"(?m)^\s*(\d{1,2})[.)]\s+(\S.+)$")
_OPTIMIZE_RE = re.compile(r"\b(?:minimi[sz]\w*|maximi[sz]\w*|optimi[sz]\w*|optimum|optimal)\b", re.I)
_STATS_RE = re.compile(r"\b(?:monte\s+carlo|samples?|histogram|standard\s+deviation|confidence|percentile|"
                       r"(?:95|99)\s*%\s*interval|propagat\w*\s+(?:the\s+)?uncertaint\w*|uncertainty\s+propagation)\b", re.I)
_EXTRA_TOOLS = (("plot", _PLOT_RE), ("code", _STATS_RE), ("formal_proof", _LEAN_RE))


def _numbered_steps(question: str) -> list[dict[str, Any]]:
    """One step per numbered part ("1. Solve ... and plot x(t)", "2. Compute ..."): the reader's own outline, each
    labelled with every tool the part needs."""
    parts = _NUMBERED_RE.findall(question or "")
    if len(parts) < 2 or [int(n) for n, _ in parts] != list(range(int(parts[0][0]), int(parts[0][0]) + len(parts))):
        return []
    steps = []
    for _n, text in parts:
        verb, _, rest = text.strip().partition(" ")
        verb = verb.lower().strip(",:;")
        if _STATS_RE.search(text) and verb not in ("plot", "prove"):
            kind = "code"
        elif _OPTIMIZE_RE.search(text) and verb in _SOLVE_VERBS:
            kind = "optimize"
        elif verb in _SOLVE_VERBS:
            # The leading verb names the part ("Solve ... and plot x(t)" is a solve that also plots).
            kind = "code" if _CODE_RE.search(text) else "solve"
        else:
            kind = _kind(verb, rest)
        tools = [TOOLS[kind]]
        for extra, pattern in _EXTRA_TOOLS:
            if extra != kind and pattern.search(text) and TOOLS[extra] not in tools:
                tools.append(TOOLS[extra])
        steps.append({"id": f"step-{len(steps) + 1}", "kind": kind, "title": _short(text, 110),
                      "tool": " + ".join(tools), "status": "planned",
                      "also": [k for k, p in _EXTRA_TOOLS if k != kind and p.search(text)]})
    return steps


def build_task_plan(question: str) -> list[dict[str, Any]]:
    """[{id, kind, title, tool, status}] for a question with two or more distinct parts ([] otherwise: a single ask
    needs no plan). Requested files (a Word report, a CSV) are a step of their own."""
    from .deliverables import requested_items
    from .question_text import typed_part

    # An attached image's transcription describes the problem; the parts to plan are the ones the user typed.
    q = typed_part(question or "")
    numbered = _numbered_steps(q)
    if numbered:
        return numbered
    items = requested_items(q, limit=8)
    lead = _LEADING_VERB_RE.match(q)
    if lead:
        covered = bool(items) and len(items[0]["item"]) >= 8 and items[0]["item"][:12].lower() in lead.group(2).lower()
        if not covered:
            # "Solve x'' + ... = 0 with ..., plot x(t)": the opening verb's clause is the first part.
            items = [{"id": "req-0", "verb": lead.group(1).lower(), "item": lead.group(2)}, *items]
        elif items[0]["verb"].lower() == lead.group(1).lower():
            # The first part is a tail of the opening clause ("theta'(0)=0 for 10 s" of "Simulate the pendulum ...
            # with theta(0)=0.5, theta'(0)=0 for 10 s"): the whole clause names it.
            items = [{**items[0], "item": lead.group(2)}, *items[1:]]
    try:
        from ..files import requested_files

        file_kinds = requested_files(q)
    except Exception:  # noqa: BLE001 - the file step is optional
        file_kinds = []
    steps: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for it in items:
        verb, item = str(it.get("verb") or ""), str(it.get("item") or "")
        if file_kinds and _FILE_WORDS_RE.search(item):
            continue  # "give me a Word report" is the file step below
        kind = _kind(verb, item)
        words = re.findall(r"[A-Za-z]{2,}|\d+", _short(item))
        if len(words) < 2 and kind in ("explain", "compare", "proof"):
            continue  # "Include the following:", "show it": a lead-in, not a part of its own
        if len(words) <= 3 and re.search(r"\b(?:it|them|this|that|these|those)$", " ".join(words), re.I):
            continue  # "... and mark them": a detail of the part before it
        # One step per tool for work that produces one thing: a detailed figure request ("plot ... as a filled
        # contour ..., plot includes axis labels ...") is one plot, not one step per sentence that mentions it.
        key = (kind, "") if kind in _ONE_PER_TOOL else (kind, " ".join(words).lower()[:40])
        if key in seen:
            # The merged step keeps the most descriptive title: "Plot plot" gives way to "Plot the exact function".
            first = next(s for s in steps if s["kind"] == kind)
            if len(first["title"].split()) <= 2 < len(_title(verb, item).split()):
                first["title"] = _title(verb, item)
            continue
        seen.add(key)
        steps.append({"id": f"step-{len(steps) + 1}", "kind": kind, "title": _title(verb, item),
                      "tool": TOOLS[kind], "status": "planned"})
    if file_kinds:
        from ..files import KIND_LABELS

        for kind in file_kinds:
            steps.append({"id": f"step-{len(steps) + 1}", "kind": "file", "title": f"Prepare the {KIND_LABELS[kind]}",
                          "tool": TOOLS["file"], "status": "planned"})
    # One part is one ask: the plan only earns its place when there are several.
    return steps if len(steps) >= 2 else []


def needs(plan: list[dict[str, Any]], kind: str) -> bool:
    return any(s.get("kind") == kind for s in plan or [])


def writer_note(plan: list[dict[str, Any]]) -> str:
    """The answer follows the plan: one short section per step, in order."""
    if len(plan or []) < 2:
        return ""
    lines = "\n".join(f"{i}. {s['title']} ({s['tool']})" for i, s in enumerate(plan, 1) if s["kind"] != "file")
    return ("TASK PLAN: the question has these parts. Answer them in this order, each under a short heading that names "
            "the part (### 1. ..., ### 2. ...), using that part's tool results; keep each section to what the part "
            "asks. A part whose tool did not produce a result says so in one sentence instead of guessing. A figure "
            "or file is described, not redrawn.\n" + lines)


def close_plan(plan: list[dict[str, Any]], artifacts: dict[str, Any], answer: str) -> list[dict[str, Any]]:
    """Each step's outcome from the run's artifacts: done, verified, failed or not run (never claimed without them)."""
    arts = artifacts or {}
    def _dict(key: str) -> dict[str, Any]:
        value = arts.get(key)
        return value if isinstance(value, dict) else {}

    math, formal, codeact = _dict("math_agent"), _dict("formal_proof"), _dict("codeact")
    literature = arts.get("literature") or arts.get("archivon")
    out = []
    for step in plan or []:
        kind, status, detail = step["kind"], "done", ""
        critical = _dict("critical_points")
        if kind in ("solve", "explain") and re.search(r"critical|stationary|extrem", step["title"], re.I) and critical:
            status = "verified" if critical.get("status") == "complete" else "done"
            n = len(critical.get("points") or [])
            detail = (f"{n} found, completeness proved" if critical.get("status") == "complete"
                      else f"{n} certified, completeness not proved")
            out.append({**step, "tool": "interval arithmetic (certified)", "status": status, "detail": detail})
            continue
        if kind == "solve":
            st = str(math.get("status") or "")
            status = "verified" if st == "verified" else ("done" if answer.strip() else "not_run")
            detail = {"verified": "checked by computation", "partially_verified": "partly checked"}.get(st, "")
        elif kind == "plot":
            figs = (arts.get("plot") or {}).get("figures") if isinstance(arts.get("plot"), dict) else None
            status, detail = ("done", f"{len(figs)} figure{'s' if len(figs) != 1 else ''}") if figs else ("failed", "no figure drawn")
        elif kind == "formal_proof":
            st = str(formal.get("status") or "")
            status = "verified" if st in ("verified", "proved") else ("failed" if formal else "not_run")
            detail = {"verified": "Lean accepted the proof", "proved": "Lean accepted the proof"}.get(st, st.replace("_", " "))
        elif kind == "simulate":
            sim = arts.get("dynamis") or arts.get("vivarix") or arts.get("ode_verification") or arts.get("plot")
            status = "done" if sim else "not_run"
        elif kind == "code":
            ok = int(codeact.get("ok_cells") or 0)
            status, detail = ("done", f"{ok} cell{'s' if ok != 1 else ''} ran") if ok else ("not_run" if not codeact else "failed", "")
        elif kind == "sources":
            status = "done" if literature else "not_run"
        elif kind == "file":
            status = "done" if arts.get("files") else "failed"
        out.append({**step, "status": status, "detail": detail})
    return out


__all__ = ["TOOLS", "build_task_plan", "close_plan", "needs", "writer_note"]
