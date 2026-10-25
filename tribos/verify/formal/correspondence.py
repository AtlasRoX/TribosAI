"""Whether a Lean theorem statement encodes the question it claims to prove (audit I33).

A clean compile proves the statement that was written, not the question. `theorem riemann_hypothesis : False` names
the question but states something else; a hypothesis equal to the conclusion assumes what is to be shown; a statement
over Nat for a question about complex numbers changes the domain. These are rejected before (and after) Lean runs, so
"formally verified" is only ever attached to a statement that says what the question says, as far as these
deterministic checks can tell. The Lean statement is still shown to the reader, who remains the final judge.

Core Lean 4 without Mathlib has no real or complex numbers and no analysis: a question that needs them is reported as
not formalisable in this environment instead of being converted into a different core-Lean proposition that compiles.
"""

from __future__ import annotations

import re

# Mathematics core Lean (no Mathlib) cannot state faithfully.
_NEEDS_LIBRARY = (
    (re.compile(r"\bcomplex\b|ℂ|\bRe\s*\(|\bIm\s*\(|\bimaginary\b", re.I), "complex numbers"),
    (re.compile(r"\bzeta\b|ζ|\banalytic(?:ally)?\b|\bholomorphic\b|\bmeromorphic\b", re.I), "complex analysis (the zeta function)"),
    (re.compile(r"\breal\s+numbers?\b|\bover\s+the\s+reals\b|ℝ|\birrational\b|\bsqrt\b|√|\bπ\b|\bpi\b", re.I), "real numbers"),
    (re.compile(r"\b(?:derivative|differentiab\w*|integral|integrat\w*|limit|continuous|converge\w*|series)\b", re.I), "analysis"),
    (re.compile(r"\b(?:sin|cos|tan|exp|log|ln)\s*\(", re.I), "transcendental functions"),
    (re.compile(r"(?<![\w.])\d+\s*/\s*\d+(?![\w.])|\brational\s+numbers?\b|ℚ", re.I), "rational numbers"),
)
# Words that only frame the request; numerals in them are not the statement's constants.
_INSTRUCTION_RE = re.compile(r"(?im)\b\d+[-\s]word\b|\b\d+\s+(?:words|lines|sentences)\b|\bstep\s+\d+\b|^\s*\d+\.\s")
_BASE_TYPES = {"nat", "int", "ℕ", "ℤ", "real", "ℝ", "complex", "ℂ", "rat", "ℚ", "prop", "type", "bool", "string"}
_DISPROVE_RE = re.compile(r"(?i)\bdisprove\b|\bno\s+\w+\s+(?:exists?|can)\b|\bimpossible\b|\bcannot\b|\bcontradiction\b|"
                          r"\bthere\s+is\s+no\b|\bnot\s+(?:true|hold)")


def needs_library(question: str) -> str | None:
    """What core Lean 4 cannot state in the question (e.g. "complex numbers"), or None when core Lean suffices."""
    found = [label for rx, label in _NEEDS_LIBRARY if rx.search(question or "")]
    return ", ".join(dict.fromkeys(found)) or None


def _split_header(statement: str) -> tuple[str, list[tuple[str, str]], str] | None:
    """(name, [(binder names, binder type)], conclusion) of 'theorem name binders : conclusion'."""
    m = re.match(r"\s*(?:theorem|lemma|example)\b\s*([^\s(\[{⦃:]*)", statement)
    if m is None:
        return None
    name, rest = m.group(1), statement[m.end():]
    depth, colon = 0, -1
    for i, ch in enumerate(rest):
        if ch in "([{⦃":
            depth += 1
        elif ch in ")]}⦄":
            depth -= 1
        elif ch == ":" and depth == 0 and not rest[i + 1: i + 2] == "=":
            colon = i
            break
    if colon < 0:
        return None
    binders = [(b.split(":", 1)[0].strip(), b.split(":", 1)[1].strip())
               for b in re.findall(r"[(\[{⦃]([^()\[\]{}⦃⦄]*:[^()\[\]{}⦃⦄]*)[)\]}⦄]", rest[:colon])]
    return name, binders, rest[colon + 1:].strip()


def _norm(prop: str) -> str:
    return re.sub(r"\s+", "", prop or "").strip("()")


def _constants(text: str) -> set[str]:
    return set(re.findall(r"(?<![\w.])\d+(?!\w|\.\d)", text or "")) - {"0", "1"}


def statement_issues(question: str, statement: str, *, mathlib: bool) -> list[str]:
    """Why the Lean statement does not encode the question (empty when no mismatch was detected)."""
    if not statement.strip():
        return ["the code has no theorem statement to compare with the question"]
    parts = _split_header(statement)
    if parts is None:
        return ["the theorem statement could not be read (no ': proposition' after the binders)"]
    _name, binders, conclusion = parts
    issues: list[str] = []
    hyps = [t for _n, t in binders if t.split()[0].lower().strip("()") not in _BASE_TYPES]
    concl = _norm(conclusion)
    if concl == "True":
        issues.append("the target is the proposition True, which says nothing about the question")
    elif concl == "False":
        if not hyps:
            issues.append("the target is False with no hypotheses: it is not the question's statement (and is unprovable)")
        elif not _DISPROVE_RE.search(question or ""):
            issues.append("the target is False from the stated hypotheses, a refutation of them, but the question does "
                          "not ask to refute them")
    if concl and any(_norm(t) == concl for t in hyps):
        issues.append("the conclusion is assumed as a hypothesis")
    if not mathlib:
        lacking = needs_library(question)
        if lacking:
            issues.append(f"the question needs {lacking}, which core Lean (without Mathlib) cannot state; a statement "
                          "over Nat or Int would be a different proposition")
    asked = _constants(_INSTRUCTION_RE.sub(" ", question or ""))
    if len(asked) >= 2 and not asked & _constants(statement):
        issues.append(f"the statement uses none of the question's constants ({', '.join(sorted(asked)[:6])})")
    return issues


__all__ = ["needs_library", "statement_issues"]
