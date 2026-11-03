"""LaTeX as plain text, for places that show a question without rendering math: conversation titles, plan step titles,
file headers. "$\\frac{x^4+2y^2}{6}$" -> "(x^4+2y^2)/6"; "\\[ \\nabla f \\]" -> "∇ f"; money such as "$60" is kept."""

from __future__ import annotations

import re

MATH_SYMBOLS = {
    "cdot": "\u00b7", "times": "\u00d7", "le": "\u2264", "leq": "\u2264", "ge": "\u2265", "geq": "\u2265",
    "neq": "\u2260", "ne": "\u2260", "approx": "\u2248", "int": "\u222b", "sum": "\u03a3", "prod": "\u03a0",
    "sqrt": "\u221a", "infty": "\u221e", "pi": "\u03c0", "alpha": "\u03b1", "beta": "\u03b2", "gamma": "\u03b3",
    "delta": "\u03b4", "theta": "\u03b8", "lambda": "\u03bb", "mu": "\u03bc", "sigma": "\u03c3", "omega": "\u03c9",
    "partial": "\u2202", "nabla": "\u2207", "to": "\u2192", "rightarrow": "\u2192", "in": "\u2208",
}


def plain_math(text: str) -> str:
    s = re.sub(r"\\[\[\]()]", " ", text or "")  # display and inline math delimiters: \[ \] \( \)
    s = re.sub(r"\\[dt]?frac\s*\{([^{}]*)\}\s*\{([^{}]*)\}", r"(\1)/(\2)", s)
    s = re.sub(r"\((\w+)\)/", r"\1/", s)
    s = re.sub(r"/\((\w+)\)", r"/\1", s)
    s = re.sub(r"\\(?:left|right|displaystyle)\b", "", s)
    s = re.sub(r"\\(?:quad|qquad)\b|\\[,;! ]", " ", s)  # LaTeX spacing is a space: "x\,dx" -> "x dx"
    s = re.sub(r"\\([A-Za-z]+)", lambda m: MATH_SYMBOLS.get(m.group(1), m.group(1)), s)
    s = s.replace("\\$", "$").replace("$$", "")
    s = re.sub(r"(?<![\w\\])\$(?!\d)|(?<=[^\s$])\$(?![\d])", "", s)
    s = re.sub(r"[{}]", "", s)
    return re.sub(r"[ \t]+", " ", s).strip()


__all__ = ["MATH_SYMBOLS", "plain_math"]
