"""The user's own task list, so the answer is organised by the user's numbering rather than by internal sub-questions.

"Tasks: 1. Derive x(t). 2. Separate transient and steady-state parts. ..." yields
[("1", "Derive x(t)."), ("2", "Separate transient and steady-state parts."), ...]. Lettered lists ("a)", "(b)") and
roman numerals ("i.", "(ii)") are read the same way. A question without an explicit list yields [].
"""

from __future__ import annotations

import re

_ITEM = re.compile(
    r"(?:^|(?<=\s))(?:\(\s*(?P<p>\d{1,2}|[a-h]|i{1,3}|iv|v|vi{0,3})\s*\)|(?P<n>\d{1,2})[.)]|(?P<l>[a-h])\)|"
    r"(?P<r>i{1,3}|iv|vi{0,3})[.)])\s+(?=\S)",
    re.M,
)
_ROMAN = {"i": 1, "ii": 2, "iii": 3, "iv": 4, "v": 5, "vi": 6, "vii": 7, "viii": 8}


def _ordinal(label: str) -> tuple[str, int]:
    """(scheme, position) of a list label: ("n", 3) for "3", ("a", 2) for "b", ("r", 4) for "iv"."""
    if label.isdigit():
        return "n", int(label)
    if label in _ROMAN and label not in ("v",) or label in ("iv", "vi", "vii", "viii"):
        return "r", _ROMAN[label]
    return "a", ord(label) - ord("a") + 1


def task_outline(question: str, limit: int = 20) -> list[tuple[str, str]]:
    """The first explicit list of at least two consecutive items (1, 2, 3 ... / a, b, c ... / i, ii, iii ...)."""
    text = question or ""
    matches = list(_ITEM.finditer(text))
    best: list[tuple[str, str]] = []
    run: list[tuple[re.Match[str], str]] = []
    scheme = None
    for m in matches:
        label = next(g for g in (m.group("p"), m.group("n"), m.group("l"), m.group("r")) if g)
        sch, pos = _ordinal(label)
        prev = _ordinal(run[-1][1])[1] if run else 0
        # Consecutive items continue a list; a numbered item on its own line may also skip numbers ("1. 2. 6. 7."
        # when the researcher kept only some of a longer list).
        at_line_start = m.start() == 0 or text[:m.start()].rstrip(" \t").endswith("\n")
        if run and sch == scheme and (pos == prev + 1 or (sch == "n" and pos > prev and at_line_start)):
            run.append((m, label))
        else:
            if len(run) >= 2 and not best:
                best = _items(text, run)
            run, scheme = ([(m, label)], sch) if pos == 1 else ([], None)
    if len(run) >= 2 and not best:
        best = _items(text, run)
    return best[:limit]


def _items(text: str, run: list[tuple[re.Match[str], str]]) -> list[tuple[str, str]]:
    out = []
    for i, (m, label) in enumerate(run):
        end = run[i + 1][0].start() if i + 1 < len(run) else len(text)
        body = text[m.end():end]
        if i + 1 == len(run):
            # The last item ends at a blank line or at a following non-item paragraph ("Requirements: ...").
            body = re.split(r"\n\s*\n|\n(?=[A-Z][A-Za-z ]{2,30}:)", body, maxsplit=1)[0]
        body = " ".join(body.split()).strip()
        body = re.sub(r"(?:[\s,;]+(?:and|then|also|or))+[\s,;.]*$|[\s,;]+$", "", body, flags=re.I).strip()
        if body:
            out.append((label, body))
    return out


def outline_text(items: list[tuple[str, str]]) -> str:
    return "\n".join(f"{label}. {body}" for label, body in items)


__all__ = ["outline_text", "task_outline"]
