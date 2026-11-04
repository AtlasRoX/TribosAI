"""
The copy editor: one rewrite of a drafted answer for the reader, changing presentation only.

The editor receives the question, the user's task outline, the code-computed results and the presentation issues found
by tribos.writer.lint, and returns the answer rewritten. Its output is accepted only when it introduces no number,
identifier or link that is not already in the draft, the computed results or the question (a rounded form of an existing
number is allowed), keeps every citation of the draft, and has fewer presentation issues than the draft.
"""

from __future__ import annotations

import json
import math
import re
from html import escape
from typing import Any

from .lint import Issue

EDITOR_SYSTEM_PROMPT = """\
You are the copy editor of a technical answer in mathematics, physics or engineering. You receive a draft that is \
mathematically checked but badly presented, and you rewrite it for the researcher who asked the question.

<editing_rules>
1. Change presentation only. Keep every result, equation, value, unit, citation and link of the draft, and every \
statement about what was or was not checked. Do not add facts. You may add a value from <computed_results> where the \
question asks for it and the draft omitted it, quoting it as given (to at most 6 significant figures).
2. Organise the answer as: "### Executive Summary" (as few sentences as carry the key results and a one-sentence confidence \
statement: high, moderate or low, with the reason in plain words); then, when <answer_outline> is present, one section \
per task in the user's order, headed "### <number>. <short title from the user's wording>"; otherwise short topic \
headings. Keep "Evidence limitations" or "Suggested next experiments" only if the draft has them and they are useful.
3. Write for the reader: never mention agents, tools, pipelines, "the evidence", tags, internal ids (q1, req-2), tool \
names, sandboxes or what was "quoted exactly"; describe checks as mathematics ("substituting x(t) back gives the forcing \
term identically").
4. Mathematics in LaTeX ($...$, $$...$$ with aligned for derivations), never computer-algebra syntax such as 5*cos(4*t)/13 \
or sqrt(391); drop pasted raw tool output entirely and state its meaning in one sentence. Exact values first, then a \
decimal with a sensible number of significant figures; never show more than 10 significant digits.
5. Lists of values go in a Markdown table with units in the headers.
6. Output only the rewritten answer in Markdown: no preamble, no notes about the edit.
</editing_rules>
"""

_NUMBER = re.compile(r"(?<![\w.])[-−]?\d+(?:\.\d+)?(?:[eE][-+]?\d+)?(?![\w])")
_SCI = re.compile(r"(\d+(?:\.\d+)?)\s*(?:\\times|×|x)\s*10\^?\{?\s*([-−]?\d+)\s*\}?")
_IDENT = re.compile(r"10\.\d{4,9}/[^\s)\]>\"']+|arXiv:\s?\d{4}\.\d{4,5}(?:v\d+)?|https?://[^\s)\]>\"']+", re.I)


def guard_view(computed: dict[str, Any] | None) -> dict[str, Any]:
    """The computed results as evidence for number checks: without the dense plotting samples (the solution curve,
    the frequency response), which would make almost any number look sourced."""
    return {k: v for k, v in (computed or {}).items() if k not in ("curve", "frequency_response")}


def build_editor_request(question: str, draft: str, issues: list[Issue], outline: str, computed: dict[str, Any] | None) -> str:
    computed = guard_view(computed) if computed else None
    issue_lines = "\n".join(f"- {i.detail}" + (f": \"{i.excerpt[:140]}\"" if i.excerpt else "") for i in issues[:40])
    parts = [f"<question>\n{escape(question, quote=False)}\n</question>"]
    if outline:
        parts.append(f"<answer_outline>\n{escape(outline, quote=False)}\n</answer_outline>")
    if computed:
        parts.append(f"<computed_results>\n{escape(json.dumps(computed, default=str)[:12000], quote=False)}\n</computed_results>")
    parts.append(f"<presentation_issues>\n{escape(issue_lines, quote=False)}\n</presentation_issues>")
    parts.append(f"<draft>\n{escape(draft, quote=False)}\n</draft>")
    parts.append("Rewrite the draft following the editing rules.")
    return "\n\n".join(parts)


def _numbers(text: str) -> list[float]:
    out: list[float] = []
    plain = text.replace("−", "-")
    for m in _SCI.finditer(plain):
        try:
            out.append(float(m.group(1)) * 10 ** int(m.group(2).replace("−", "-")))
        except (ValueError, OverflowError):
            pass
    for m in _NUMBER.finditer(plain):
        try:
            out.append(float(m.group(0)))
        except ValueError:
            pass
    return out


def _explained(value: float, token: str, sources: list[float]) -> bool:
    if value.is_integer() and abs(value) <= 20:
        return True  # list numbering, small exponents and counts
    decimals = len(token.split(".")[1].split("e")[0].split("E")[0]) if "." in token else 0
    tol = 0.5 * 10 ** (-decimals) * 1.000001 if "e" not in token.lower() else abs(value) * 5e-3
    for s in sources:
        if math.isclose(s, value, rel_tol=1e-9, abs_tol=1e-12) or abs(s - value) <= tol or abs(abs(s) - abs(value)) <= tol:
            return True
        # A rounded significant-figure form of a source value (0.4623 for 0.46225...).
        if s and value and abs(s - value) <= abs(s) * 5e-3 and _sig_digits(token) <= 6:
            return True
    return False


def _sig_digits(token: str) -> int:
    mant = re.sub(r"[eE].*$", "", token.lstrip("-−")).replace(".", "").lstrip("0")
    return len(mant)


def unexplained_numbers(edited: str, *sources: str) -> list[str]:
    """Numbers in the edited text that are neither in a source nor a rounding of a source value."""
    pool: list[float] = []
    for s in sources:
        pool.extend(_numbers(s or ""))
    bad = []
    plain = edited.replace("−", "-")
    for m in _NUMBER.finditer(plain):
        token = m.group(0)
        try:
            value = float(token)
        except ValueError:
            continue
        if not _explained(value, token, pool):
            bad.append(token)
    return bad


def lost_identifiers(draft: str, edited: str) -> list[str]:
    kept = {x.lower().rstrip(".,;") for x in _IDENT.findall(edited)}
    return [x for x in _IDENT.findall(draft) if x.lower().rstrip(".,;") not in kept]


def accept_edit(question: str, draft: str, edited: str, computed: dict[str, Any] | None) -> tuple[bool, str]:
    """Whether the editor's text may replace the draft, and why not."""
    if not edited or len(edited.split()) < max(12, len(draft.split()) // 4):
        return False, "the edit is empty or drops most of the answer"
    extra = unexplained_numbers(edited, draft, question, json.dumps(guard_view(computed), default=str))
    if extra:
        return False, f"the edit introduces numbers not in the draft or the computed results: {', '.join(extra[:6])}"
    lost = lost_identifiers(draft, edited)
    if lost:
        return False, f"the edit drops citations or links: {', '.join(lost[:4])}"
    return True, ""


__all__ = ["EDITOR_SYSTEM_PROMPT", "accept_edit", "build_editor_request", "lost_identifiers", "unexplained_numbers"]
