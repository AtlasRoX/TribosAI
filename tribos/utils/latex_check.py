"""Broken LaTeX in a question: notation a reader would read differently from the parser.

Copying rendered math out of a web page can drop the braces of a fraction: "\\frac{x^4+2y^2}{6}" arrives as "\\frac6",
which a parser reads as 6 (or as 6 over the next "+"). The run must say so instead of silently plotting a different
function. Only clear breakage is reported: a \\frac whose arguments are missing or are operators, unbalanced braces,
and an opened display or inline math block that is never closed.
"""

from __future__ import annotations

import re

_OPERATOR = set("+-=*/^_)]},;")


def _argument(text: str, i: int) -> tuple[str, int]:
    """One TeX macro argument starting at i: a braced group, a control word, or one character ("" when none)."""
    n = len(text)
    while i < n and text[i] in " \t\r\n":
        i += 1
    if i >= n:
        return "", i
    if text[i] == "{":
        depth, j = 0, i
        while j < n:
            depth += {"{": 1, "}": -1}.get(text[j], 0)
            if depth == 0:
                return text[i:j + 1], j + 1
            j += 1
        return text[i:], n
    m = re.match(r"\\[A-Za-z]+", text[i:])
    if m:
        return m.group(0), i + m.end()
    return text[i], i + 1


def malformed_latex(text: str) -> list[str]:
    """Plain-language descriptions of the broken notation in `text` ([] when none is found)."""
    problems: list[str] = []
    for m in re.finditer(r"\\[dt]?frac(?![A-Za-z])", text or ""):
        num, j = _argument(text, m.end())
        den, k = _argument(text, j)
        bad = [a for a in (num, den) if not a or a in _OPERATOR]
        if bad or (not num.startswith("{") and not den.startswith("{") and num.isdigit() and not den):
            shown = re.sub(r"\s+", " ", text[m.start():min(len(text), k + 6)]).strip()
            problems.append(f'"{shown}" is a fraction without a proper numerator and denominator')
    depth = 0
    for ch in re.sub(r"\\[{}]", "", text or ""):
        depth += {"{": 1, "}": -1}.get(ch, 0)
        if depth < 0:
            break
    if depth != 0:
        problems.append("the braces { } in the formula are unbalanced")
    for opener, closer, name in (("\\[", "\\]", "display math"), ("\\(", "\\)", "inline math")):
        if (text or "").count(opener) != (text or "").count(closer):
            problems.append(f"a {name} block ({opener} ... {closer}) is not closed")
    return list(dict.fromkeys(problems))


__all__ = ["malformed_latex"]
