"""The parts of a question: what the user typed, and what attached images contain.

An attached image's transcription is appended to the question ("Attached image 1 (q.png), transcribed: ...") so the
problem can be solved. It describes the problem, it does not instruct Tribos: "The plot starts at (0, 0)" in a figure
description is not a request to plot, and "q.png" is not a request for a PNG file. Requests for actions (a plot, a
file, a formal proof, the task plan) are read from the typed text only; understanding the problem uses all of it.
"""

from __future__ import annotations

import re

_IMAGE_BLOCK_RE = re.compile(r"(?m)^Attached image \d+ \([^\n]*\), transcribed:\s*$")
# "(a) 60 m  (b) 55 m  (c) 25 m  (d) 30 m": three or more lettered options, each on its own line or inline.
_OPTION_RE = re.compile(r"(?:^|\s)\(?([a-eA-E])[).]\s+\S", re.M)


def typed_part(question: str) -> str:
    """The text the user typed, without the attached images' transcriptions."""
    m = _IMAGE_BLOCK_RE.search(question or "")
    return (question or "")[: m.start()].rstrip() if m else (question or "")


def image_part(question: str) -> str:
    """The attached images' transcriptions ("" when there are none)."""
    m = _IMAGE_BLOCK_RE.search(question or "")
    return (question or "")[m.start():] if m else ""


# An option that starts its own line ("(A) ...", "b) ..."): read first, so a letter in the stem ("to form compound B.
# B reacts ...") is never taken for an option.
_LINE_OPTION_RE = re.compile(r"^[ \t]*\(?([a-eA-E])[).][ \t]+\S", re.M)


def _in_order(marks: list[re.Match[str]]) -> bool:
    seen = "".join(dict.fromkeys(m.group(1).lower() for m in marks))
    return len(seen) >= 3 and "abc" in seen


def _option_marks(question: str) -> list[re.Match[str]]:
    q = question or ""
    lines = list(_LINE_OPTION_RE.finditer(q))
    if _in_order(lines):
        return lines
    inline = list(_OPTION_RE.finditer(q))
    return inline if _in_order(inline) else []


def is_multiple_choice(question: str) -> bool:
    """Three or more lettered options in order ((a), (b), (c) ...): one problem with candidate answers."""
    return bool(_option_marks(question))


def option_texts(question: str) -> list[str]:
    """The text of each lettered option of a multiple-choice question ([] when it is not one)."""
    q = question or ""
    marks = _option_marks(q)
    if not marks:
        return []
    out = []
    for i, m in enumerate(marks):
        end = marks[i + 1].start() if i + 1 < len(marks) else len(q)
        out.append(q[m.start(): end].strip())
    return out


# A choose-one question: "Answer choices:", "Which of the following ...", "Choose the correct option".
_CHOOSE_RE = re.compile(
    r"\b(?:answer\s+(?:choices|options)|which\s+(?:one\s+)?of\s+the\s+(?:following|options|choices|statements)|"
    r"choose|select|pick|circle)\b|\b(?:correct|best|right)\s+(?:option|answer|choice|statement)\b", re.I)


def is_choice_question(question: str) -> bool:
    """A multiple-choice question whose lettered items are candidate answers to pick from, not parts of a task:
    "(a) Simulate the Lorenz system (b) Plot x(t) (c) ..." lists requests, "What is ...? (A) 1 (B) 2 (C) 3" lists
    answers. The stem asks to choose, or ends with a question before the options."""
    options = option_texts(question)
    if not options:
        return False
    q = question or ""
    stem = q[: q.find(options[0])] if options[0] in q else ""
    rest = q
    for o in options:
        rest = rest.replace(o, " ")
    if _CHOOSE_RE.search(rest):
        return True
    return bool(re.search(r"\?\s*(?:\w+\s+(?:choices|options)\s*:?\s*)?$", stem.strip()))


# Mathematics in an option: LaTeX ("$\omega/5$", "\frac"), an equation, a power or a root.
_OPTION_MATH_RE = re.compile(r"\$|\\[A-Za-z]+|[=^√∫]")


def is_math_multiple_choice(question: str) -> bool:
    """A multiple-choice problem whose options (three or more) state formulas or values to check: "(A) the centre of
    mass rotates at $\\omega/5$". One problem, solved by derivation; the options are not separate questions."""
    options = option_texts(question)
    return sum(1 for o in options if _OPTION_MATH_RE.search(o)) >= 3


__all__ = ["image_part", "is_choice_question", "is_math_multiple_choice", "is_multiple_choice", "option_texts",
           "typed_part"]
