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
    (re.compile(r"\breal\s+numbers?\b|\bover\s+the\s+reals\b|ℝ|\birrational\b|\bsqrt\b|√|\bπ\b|\bpi\b"
                # "for all real x,y", "real polynomials", "real roots": variables or objects over the reals
                r"|\breal\s+(?:[a-z]\b|variables?\b|polynomials?\b|coefficients?\b|roots?\b|solutions?\b|valued\b)",
                re.I), "real numbers"),
    (re.compile(r"\b(?:derivative|differentiab\w*|integral|integrat\w*|limit|continuous|converge\w*|series)\b", re.I), "analysis"),
    (re.compile(r"\b(?:sin|cos|tan|exp|log|ln)\s*\(", re.I), "transcendental functions"),
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
    raw_concl = rest[colon + 1:].strip()
    depth = 0
    concl_end = len(raw_concl)
    for i, ch in enumerate(raw_concl):
        if ch in "([{⦃":
            depth += 1
        elif ch in ")]}⦄":
            depth -= 1
        elif depth == 0 and raw_concl[i:i + 2] == ":=":
            concl_end = i
            break
        elif depth == 0 and (raw_concl[i:i + 3] == "by " or raw_concl[i:i + 3] == "by\n"):
            concl_end = i
            break
    conclusion = raw_concl[:concl_end].strip()
    return name, binders, conclusion


def _norm(prop: str) -> str:
    return re.sub(r"\s+", "", prop or "").strip("()")


def _constants(text: str) -> set[str]:
    return set(re.findall(r"(?<![\w.])\d+(?!\w|\.\d)", text or "")) - {"0", "1"}


def _split_implication(prop: str) -> list[str]:
    """Split top-level implications (-> or →) outside parentheses/brackets."""
    parts: list[str] = []
    current: list[str] = []
    depth = 0
    i = 0
    while i < len(prop):
        ch = prop[i]
        if ch in "([{⦃":
            depth += 1
            current.append(ch)
        elif ch in ")]}⦄":
            depth -= 1
            current.append(ch)
        elif depth == 0 and prop[i:i + 2] == "->":
            parts.append("".join(current).strip())
            current = []
            i += 1
        elif depth == 0 and ch == "→":
            parts.append("".join(current).strip())
            current = []
        else:
            current.append(ch)
        i += 1
    if current:
        parts.append("".join(current).strip())
    return parts


def _detect_question_domain(question: str) -> str | None:
    has_nat = bool(re.search(r"\b(?:natural\s+numbers?|non-?negative\s+integers?|nonnegative\s+integers?)\b|\bNat\b|ℕ", question, re.I))
    has_int = bool(re.search(r"\b(?:integers?)\b|\bInt\b|ℤ", question, re.I)) and not has_nat
    has_real = bool(re.search(r"\b(?:real\s+numbers?|over\s+the\s+reals?)\b|\bReal\b|ℝ", question, re.I))
    has_rat = bool(re.search(r"\b(?:rational\s+numbers?)\b|\bRat\b|ℚ", question, re.I))
    has_complex = bool(re.search(r"\b(?:complex\s+numbers?)\b|\bComplex\b|ℂ", question, re.I))
    domains = [d for d, present in [("Nat", has_nat), ("Int", has_int), ("Real", has_real), ("Rat", has_rat), ("Complex", has_complex)] if present]
    return domains[0] if len(domains) == 1 else None


def _detect_binder_domains(binders: list[tuple[str, str]]) -> set[str]:
    stmt_domains: set[str] = set()
    for _names, typ in binders:
        head = typ.split()[0].strip("()").lower()
        if head in ("nat", "ℕ"):
            stmt_domains.add("Nat")
        elif head in ("int", "ℤ"):
            stmt_domains.add("Int")
        elif head in ("real", "ℝ"):
            stmt_domains.add("Real")
        elif head in ("rat", "ℚ"):
            stmt_domains.add("Rat")
        elif head in ("complex", "ℂ"):
            stmt_domains.add("Complex")
    return stmt_domains


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

    impl_parts = _split_implication(conclusion)
    final_target = _norm(impl_parts[-1]) if impl_parts else concl

    if concl == "True" or final_target == "True":
        if not re.search(r"\b(?:True|true)\b", question or ""):
            issues.append("the target is the proposition True, which says nothing about the question")
    elif concl == "False" or final_target == "False":
        if not hyps and len(impl_parts) <= 1:
            if not re.search(r"\b(?:False|false)\b", question or ""):
                issues.append("the target is False with no hypotheses: it is not the question's statement (and is unprovable)")
        elif not _DISPROVE_RE.search(question or ""):
            issues.append("the target is False from the stated hypotheses, a refutation of them, but the question does "
                          "not ask to refute them")
    elif concl in ("trivial", "1=1", "0=0"):
        if concl not in _norm(question or "") and conclusion.strip() not in (question or ""):
            issues.append(f"the target is a trivial proposition ({conclusion.strip()}), which says nothing about the question")
    elif "=" in concl and "<" not in concl and ">" not in concl:
        sides = concl.split("=", 1)
        if len(sides) == 2 and sides[0] == sides[1] and concl not in _norm(question or ""):
            issues.append(f"the target is a trivial reflexivity equality ({conclusion.strip()}), which says nothing about the question")

    if len(impl_parts) > 1:
        premises_norm = [_norm(p) for p in impl_parts[:-1]]
        if final_target in premises_norm:
            issues.append("the conclusion is an implication whose hypothesis assumes its target")

    if concl and any(_norm(t) == concl for t in hyps):
        issues.append("the conclusion is assumed as a hypothesis")
    elif final_target and any(_norm(t) == final_target for t in hyps):
        issues.append("the conclusion is assumed as a hypothesis")

    # Domain correspondence check
    q_dom = _detect_question_domain(question)
    stmt_doms = _detect_binder_domains(binders)
    if q_dom and stmt_doms and q_dom not in stmt_doms:
        issues.append(f"the question is over {q_dom}, but the statement binds variables over {', '.join(sorted(stmt_doms))} (domain mismatch)")

    if not mathlib:
        lacking = needs_library(question)
        if lacking:
            issues.append(f"the question needs {lacking}, which requires the Mathlib library (TRIBOS_LEAN_PROJECT is not configured); "
                          "a statement over Nat or Int would be a different proposition")
    asked = _constants(_INSTRUCTION_RE.sub(" ", question or ""))
    if len(asked) >= 2 and not asked & _constants(statement):
        issues.append(f"the statement uses none of the question's constants ({', '.join(sorted(asked)[:6])})")
    return issues


__all__ = ["needs_library", "statement_issues"]
