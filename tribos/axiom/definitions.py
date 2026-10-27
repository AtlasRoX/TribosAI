"""
Questions that define their own functions, evaluate independent cases, or state a universal claim.

The generic parsers in problem.py read "T(n) = n/2" as an equation in two unknowns T and n, and "f(x) - x^2 = 1" as
the product f*x minus x^2. This module keeps what such questions actually say, as plain JSON-friendly data:

- function definitions: name, parameter, declared domain and branches, each branch with its own condition
  ("n/2 for even positive integers", "2t - 3 if t < 0", "t^2 otherwise");
- tasks, each with an id taken from the question: evaluate an expression that applies the defined functions
  ("T(4)", "f(2) + f(3)"), iterate a function from a start value ("the cycle starting at 1"), evaluate one expression
  under case-local bindings ("Case A: n = 40"), or decide a universal claim ("... is prime for every nonnegative
  integer n");
- checks that are kept apart: interpretation (a defined function is applied, never multiplied), domain (every argument
  and witness lies in the stated domain and exactly one branch applies), computation (values recomputed by a second
  route), coverage (every requested item has a result).

All mathematics goes through the allowlist parser (engine.safe_parse_expr); nothing here evaluates user text, and
every search is bounded.
"""

from __future__ import annotations

import math
from collections.abc import Callable
import re
from fractions import Fraction
from typing import Any

import sympy as sp
from sympy.core.function import AppliedUndef

from .engine import safe_parse_expr

DOMAINS = ("unspecified", "complex", "real", "rational", "integer", "nonnegative_integer", "positive_integer")
_INTEGER_DOMAINS = ("integer", "nonnegative_integer", "positive_integer")
CLAIM_SEARCH_LIMIT = 1000  # domain values tried when looking for a counterexample
ORBIT_LIMIT = 1000  # applications when iterating a function from a start value
_MAX_TASKS = 24

# Names that are mathematical functions, not user definitions ("sin(x) = 0" is an equation).
_RESERVED = frozenset({
    "sin", "cos", "tan", "cot", "sec", "csc", "sinh", "cosh", "tanh", "asin", "acos", "atan", "arcsin", "arccos",
    "arctan", "exp", "log", "ln", "sqrt", "abs", "floor", "ceil", "gcd", "lcm", "max", "min", "det", "lim", "sum",
    "Eq", "Abs", "re", "im", "arg", "sign", "mod", "deg", "rad", "P", "Pr", "E", "Var",
})
# Probability/expectation notation that is also a common function name: a definition only when its formula uses the
# parameter (P(s) = (s - 1/4)(s - 3/4)), never for P(A) = 0.3.
_NOTATION_NAMES = frozenset({"P", "E"})

_REL_OPS = {"<=": sp.Le, ">=": sp.Ge, "!=": sp.Ne, "<": sp.Lt, ">": sp.Gt, "=": sp.Eq}
_UNICODE_REL = {"≤": "<=", "≥": ">=", "≠": "!=", "⩽": "<=", "⩾": ">="}
_NUMBER = r"[-+]?\d+(?:\.\d+)?(?:/\d+)?"


class DefinitionError(ValueError):
    """A definition cannot be applied at a value (outside its domain, no branch, ambiguous branches)."""


def _ascii_rel(text: str) -> str:
    for u, a in _UNICODE_REL.items():
        text = text.replace(u, a)
    return text


# Domains -------------------------------------------------------------------------------------------------------------

_ELLIPSIS = r"(?:\.{3}|…|\\ldots|\\dots|\\cdots)"
# Set literals for the integer domains: {1, 2, 3, ...}, {0, 1, 2, ...}, {..., -1, 0, 1, ...}.
# Braces or parentheses: normalisation writes "{1, 2, 3, ...}" as "(1, 2, 3, ...)".
_SET_POSITIVE_RE = re.compile(rf"[{{(]\s*1\s*,\s*2\s*(?:,\s*3\s*)?,\s*{_ELLIPSIS}\s*[}})]")
_SET_NONNEG_RE = re.compile(rf"[{{(]\s*0\s*,\s*1\s*(?:,\s*2\s*)?,\s*{_ELLIPSIS}\s*[}})]")
_SET_INTEGER_RE = re.compile(rf"[{{(]\s*{_ELLIPSIS}\s*,\s*-\s*1\s*,\s*0\s*,\s*1\s*,\s*{_ELLIPSIS}\s*[}})]")
_SET_INT_RAY_RE = re.compile(rf"[{{(]\s*({_NUMBER})\s*,\s*({_NUMBER})\s*(?:,\s*({_NUMBER})\s*)?,\s*{_ELLIPSIS}\s*[}})]")
_SET_FINITE_RE = re.compile(rf"^\{{\s*({_NUMBER}(?:\s*,\s*{_NUMBER})*)\s*\}}$")
_INTERVAL_RE = re.compile(rf"^([\[\(])\s*(-?oo|-?inf|{_NUMBER})\s*,\s*(-?oo|-?inf|{_NUMBER})\s*([\]\)])$")
_EXCLUSION_RE = re.compile(
    rf"(?i)(?:ℝ|reals?)\s*(?:\\?\s*\\setminus|excluding|except|without|\\)\s*\{{\s*({_NUMBER}(?:\s*,\s*{_NUMBER})*)\s*\}}"
)


def domain_from_words(text: str) -> str | None:
    """The number set named in a phrase ("positive integers", "positive-integer-only", "{1, 2, 3, ...}", "{2, 3, 4, ...}",
    "every real x", "ℤ", "R -> R")."""
    low = text.lower().strip()
    mex = _EXCLUSION_RE.search(low)
    if mex:
        nums = [p.strip() for p in mex.group(1).split(",") if p.strip()]
        return f"real_excluding:{{{','.join(nums)}}}"
    minterval = _INTERVAL_RE.match(low)
    if minterval:
        left, a, b, right = minterval.groups()
        return f"interval:{left}{a},{b}{right}"
    mray = _SET_INT_RAY_RE.search(low)
    if mray:
        try:
            n1 = int(safe_parse_expr(mray.group(1)))
            n2 = int(safe_parse_expr(mray.group(2)))
            if n2 - n1 == 1:
                if n1 == 1:
                    return "positive_integer"
                if n1 == 0:
                    return "nonnegative_integer"
                return f"integer_ge_{n1}"
        except Exception:
            pass
    m_ineq = re.search(rf"\bintegers?\s*(>=|>=?|\\geq?|≥|at least)\s*({_NUMBER})\b", low)
    if m_ineq:
        try:
            k = int(safe_parse_expr(m_ineq.group(2)))
            if k == 1:
                return "positive_integer"
            if k == 0:
                return "nonnegative_integer"
            return f"integer_ge_{k}"
        except Exception:
            pass
    m_ineq_gt = re.search(rf"\bintegers?\s*(>|greater than)\s*({_NUMBER})\b", low)
    if m_ineq_gt:
        try:
            k = int(safe_parse_expr(m_ineq_gt.group(2)))
            if k == 0:
                return "positive_integer"
            return f"integer_ge_{k + 1}"
        except Exception:
            pass
    mfin = _SET_FINITE_RE.match(low)
    if mfin and not re.search(_ELLIPSIS, low):
        nums = [p.strip() for p in mfin.group(1).split(",") if p.strip()]
        if nums:
            return f"finite_set:{{{','.join(nums)}}}"
    if _SET_NONNEG_RE.search(low) or re.search(
            r"\bnon[\s-]?negative[\s-]+(?:integers?|whole[\s-]+numbers?)\b|\bwhole[\s-]+numbers?\b|ℕ\s*(?:_\{?0\}?|₀|∪\s*\{\s*0\s*\})|"
            r"ℤ\s*(?:_\{?\s*(?:≥|>=|\\geq?)\s*0\s*\}?|≥0)|\bn\s*0\b", low):
        return "nonnegative_integer"
    if _SET_POSITIVE_RE.search(low) or re.search(
            r"\bpositive[\s-]+integers?\b|\bnatural[\s-]+numbers?\b|ℕ|ℤ\s*(?:\+|⁺|\^\{?\+\}?)|ℤ\s*_\{?\s*(?:>|≥\s*1|>=\s*1|\\geq?\s*1)\s*0?\s*\}?|\bz\s*\+",
            low):
        return "positive_integer"
    if _SET_INTEGER_RE.search(low):
        return "integer"
    if re.search(r"\bintegers?\b|ℤ", low):
        return "integer"
    if re.search(r"\brationals?\b|\brational\s+numbers?\b|ℚ", low):
        return "rational"
    if re.search(r"\breals?\b|\breal\s+numbers?\b|ℝ", low):
        return "real"
    if re.search(r"\bcomplex\b|ℂ", low):
        return "complex"
    return None


def _domain_from_symbol(sym: str) -> str | None:
    return {"r": "real", "ℝ": "real", "z": "integer", "ℤ": "integer", "n": "positive_integer", "ℕ": "positive_integer",
            "q": "rational", "ℚ": "rational", "c": "complex", "ℂ": "complex"}.get(sym.strip().lower())


def is_valid_domain(dom: str) -> bool:
    """Whether dom is a recognized canonical domain string."""
    if not isinstance(dom, str) or not dom.strip():
        return False
    if dom in DOMAINS:
        return True
    if re.fullmatch(r"integer_(?:ge|gt|le|lt)_-?\d+", dom):
        return True
    if dom.startswith("finite_set:{") and dom.endswith("}"):
        content = dom[len("finite_set:{"):-1]
        parts = [p.strip() for p in content.split(",") if p.strip()]
        return bool(parts) and all(re.fullmatch(_NUMBER, p) for p in parts)
    if dom.startswith("interval:") and len(dom) > 10:
        return bool(_INTERVAL_RE.match(dom[len("interval:"):]))
    if dom.startswith("real_excluding:{") and dom.endswith("}"):
        content = dom[len("real_excluding:{"):-1]
        parts = [p.strip() for p in content.split(",") if p.strip()]
        return bool(parts) and all(re.fullmatch(_NUMBER, p) for p in parts)
    return False


def is_integer_domain(dom: str) -> bool:
    """Whether all members of dom are integers."""
    if dom in _INTEGER_DOMAINS or dom.startswith("integer_"):
        return True
    if dom.startswith("finite_set:{") and dom.endswith("}"):
        content = dom[len("finite_set:{"):-1]
        parts = [p.strip() for p in content.split(",") if p.strip()]
        return bool(parts) and all(re.fullmatch(r"[-+]?\d+", p) for p in parts)
    return False


def domain_rank(dom: str) -> int:
    """Specificity order: narrower domains have smaller rank."""
    if dom.startswith("finite_set:"):
        return 0
    if dom.startswith("interval:") or dom.startswith("real_excluding:"):
        return 1
    if dom.startswith("integer_"):
        return 2
    return {"positive_integer": 3, "nonnegative_integer": 4, "integer": 5, "rational": 6, "real": 7, "complex": 8}.get(dom, 99)


def is_proper_subdomain(d1: str, d2: str) -> bool:
    """True if d1 is strictly narrower than d2 (using d2 when d1 is required is illegal domain widening)."""
    if d1 == d2:
        return False
    if d2 == "unspecified":
        return d1 != "unspecified"
    r1, r2 = domain_rank(d1), domain_rank(d2)
    if r1 < r2:
        return True
    if r1 > r2:
        return False
    if d1.startswith("integer_ge_") and d2.startswith("integer_ge_"):
        try:
            return int(d1.split("_ge_")[1]) > int(d2.split("_ge_")[1])
        except Exception:
            return False
    return False


def in_domain(value: sp.Expr, domain: str) -> bool | None:
    """Membership of an exact value; None when it cannot be decided."""
    if domain in ("unspecified", "complex"):
        return bool(value.is_finite) if value.is_finite is not None else None
    if domain == "real":
        return bool(value.is_extended_real and value.is_finite) if value.is_extended_real is not None else None
    if domain == "rational":
        return bool(value.is_rational) if value.is_rational is not None else None
    if domain.startswith("real_excluding:{") and domain.endswith("}"):
        if value.is_extended_real is not True or value.is_finite is not True:
            return False if value.is_extended_real is False or value.is_finite is False else None
        excluded = [safe_parse_expr(p.strip()) for p in domain[len("real_excluding:{"):-1].split(",") if p.strip()]
        if any(sp.simplify(value - ex) == 0 for ex in excluded):
            return False
        return True
    if domain.startswith("interval:"):
        m = _INTERVAL_RE.match(domain[len("interval:"):])
        if not m:
            return None
        left, a_str, b_str, right = m.groups()
        if value.is_extended_real is not True or value.is_finite is not True:
            return False if value.is_extended_real is False or value.is_finite is False else None
        a = safe_parse_expr(a_str) if a_str not in ("-oo", "-inf") else -sp.oo
        b = safe_parse_expr(b_str) if b_str not in ("oo", "inf") else sp.oo
        left_ok = (value >= a) if left == "[" else (value > a)
        right_ok = (value <= b) if right == "]" else (value < b)
        res = sp.simplify(left_ok) and sp.simplify(right_ok)
        return bool(res) if res in (sp.true, sp.false, True, False) else None
    if domain.startswith("finite_set:{") and domain.endswith("}"):
        elements = [safe_parse_expr(p.strip()) for p in domain[len("finite_set:{"):-1].split(",") if p.strip()]
        for elem in elements:
            if sp.simplify(value - elem) == 0:
                return True
        return False if value.is_number else None
    if not value.is_integer:
        return False if value.is_integer is False or value.is_number else None
    v = int(value)
    if domain == "integer":
        return True
    if domain == "nonnegative_integer":
        return v >= 0
    if domain == "positive_integer":
        return v >= 1
    if domain.startswith("integer_ge_"):
        return v >= int(domain.split("_ge_")[1])
    if domain.startswith("integer_gt_"):
        return v > int(domain.split("_gt_")[1])
    if domain.startswith("integer_le_"):
        return v <= int(domain.split("_le_")[1])
    if domain.startswith("integer_lt_"):
        return v < int(domain.split("_lt_")[1])
    return True


def domain_label(domain: str) -> str:
    if domain == "positive_integer":
        return "positive integers"
    if domain == "nonnegative_integer":
        return "nonnegative integers"
    if domain == "integer":
        return "integers"
    if domain == "rational":
        return "rational numbers"
    if domain == "real":
        return "real numbers"
    if domain == "complex":
        return "complex numbers"
    if domain.startswith("integer_ge_"):
        return f"integers >= {domain.split('_ge_')[1]}"
    if domain.startswith("integer_gt_"):
        return f"integers > {domain.split('_gt_')[1]}"
    if domain.startswith("integer_le_"):
        return f"integers <= {domain.split('_le_')[1]}"
    if domain.startswith("integer_lt_"):
        return f"integers < {domain.split('_lt_')[1]}"
    if domain.startswith("finite_set:"):
        return domain[len("finite_set:"):]
    if domain.startswith("interval:"):
        return domain[len("interval:"):]
    if domain.startswith("real_excluding:"):
        return f"real numbers excluding {domain[len('real_excluding:'):]}"
    return "its domain"


# Conditions ------------------------------------------------------------------------------------------------------------

def parse_condition(text: str, param: str) -> tuple[str, str | None] | None:
    """A branch condition phrase -> (condition, domain named in it). condition is "", "otherwise", "even", "odd" or a
    relation such as "t < 0"; None when the phrase is not understood."""
    low = _ascii_rel(text.strip().lower())
    dom = domain_from_words(low)
    if re.fullmatch(r"(?:for\s+|in\s+)?(?:all\s+)?(?:other(?:wise)?|else|elsewhere|all other\s+\w+(?:\s+\w+)?)", low) or low in ("otherwise", "else"):
        return "otherwise", dom
    if re.search(r"\beven\b", low):
        return "even", dom
    if re.search(r"\bodd\b", low):
        return "odd", dom
    m = re.search(rf"\b([a-z])\s*(<=|>=|!=|<|>|=)\s*({_NUMBER})\b", low)
    if m and m.group(1) == param:
        return f"{param} {m.group(2)} {m.group(3)}", dom
    m = re.search(r"\b([a-z])\s+(?:is\s+)?(positive|negative|nonzero|non-zero|zero|nonnegative|non-negative)\b", low)
    if m and m.group(1) == param:
        rel = {"positive": ">", "negative": "<", "nonzero": "!=", "non-zero": "!=", "zero": "=", "nonnegative": ">=", "non-negative": ">="}[m.group(2)]
        return f"{param} {rel} 0", dom
    if dom is not None and re.fullmatch(r"(?:for\s+|on\s+|over\s+)?(?:all\s+|every\s+|each\s+)?(?:the\s+)?[\w\s-]*?(?:\s+[a-z])?", low):
        return "", dom  # "for positive integers n": a domain, no branch condition
    return None


def condition_holds(condition: str, param: str, value: sp.Expr) -> bool | None:
    if condition in ("", "otherwise"):
        return True
    if condition in ("even", "odd"):
        if value.is_integer is not True:
            return False
        return (int(value) % 2 == 0) == (condition == "even")
    m = re.fullmatch(rf"{re.escape(param)}\s*(<=|>=|!=|<|>|=)\s*({_NUMBER})", condition)
    if not m:
        return None
    rhs = safe_parse_expr(m.group(2))
    if m.group(1) in ("=", "!="):
        same = sp.simplify(value - rhs) == 0
        return same if m.group(1) == "=" else not same
    if value.is_extended_real is not True:
        return None
    rel = _REL_OPS[m.group(1)](value, rhs)
    return bool(rel) if rel in (sp.true, sp.false) else None


# Definitions ---------------------------------------------------------------------------------------------------------

_DEF_HEAD_RE = re.compile(r"(?<![\w.'])([A-Za-z][A-Za-z0-9_]{0,15})\s*\(\s*([A-Za-z])\s*\)\s*=(?!=)\s*")
_DECL_RE = re.compile(
    r"(?<![\w.])([A-Za-z][A-Za-z0-9_]{0,15})\s*:\s*"
    r"(\{[^}]*\}|\[[^\]]*\]|\([^)]*\)|[A-Za-z0-9ℝℤℕℚℂ+_{}>=≤≥\s.,\\…-]{1,32}?)\s*"
    r"(?:->|→|\\to\b)\s*"
    r"(\{[^}]*\}|\[[^\]]*\]|\([^)]*\)|[A-Za-z0-9ℝℤℕℚℂ+_{}>=≤≥\s.,\\…-]{1,32})"
)
_DEF_CUE_RE = re.compile(r"\b(?:define|defined|definition|let|where|with|given|suppose|consider|be|by|denote|denotes|set|for)\b|[:\-*•]\s*$", re.I)
_ACTION_RE = re.compile(
    r"\b(?:prove|show|verify|check|disprove|whether|true\s+that|solve|find|compute|evaluate|calculate|determine|what|"
    r"plot|graph|differentiate|integrate|simplify)\b", re.I)
_EXPR_END_RE = re.compile(
    r"\s+(?:for|if|when|whenever|provided|otherwise|else|on)\b|\s*[,;]|\.(?=\s|$)|\s+and\s+(?=[A-Za-z]\w*\s*\()|\n|$")
_COND_END_RE = re.compile(r"\s*[,;]|\.(?=\s|$)|\s+and\s+(?=[A-Za-z]\w*\s*\()|\n|$")


def _sentence_start(text: str, pos: int) -> int:
    cut = max(
        text.rfind(". ", 0, pos),
        text.rfind("? ", 0, pos),
        text.rfind("! ", 0, pos),
        text.rfind("; ", 0, pos),
        text.rfind(";\n", 0, pos),
        text.rfind("\n", 0, pos),
    )
    return cut + 1 if cut >= 0 else 0


def _is_definition_site(text: str, start: int) -> bool:
    """A "NAME(x) = ..." is a definition unless an action verb governs it ("Solve f(x) = 0", "Prove that f(x) = ...")
    with no definition cue after that verb. A second branch after a comma ("h(n) = n/2 for even n, h(n) = 7n - 1
    for odd n") and a statement after a domain sentence ("The domain of q is ... and q(n) = n^2 + 4") are definitions."""
    prefix = text[_sentence_start(text, start):start]
    cue = list(_DEF_CUE_RE.finditer(prefix))
    act = list(_ACTION_RE.finditer(prefix))
    return not (act and (not cue or act[-1].start() > cue[-1].start()))


def _declared_domain(text: str, name: str) -> str | None:
    n = re.escape(name)
    m = re.search(rf"(?<![\w.]){n}\s*:\s*(\{{[^}}]*\}}|\[[^\]]*\]|\([^)]*\)|[^:\n]*?)\s*(?:->|→|\\to\b)", text)
    if m:
        dom = _domain_from_symbol(m.group(1)) or domain_from_words(m.group(1))
        if dom:
            return dom
    for pat in (
        rf"\bdomain\s+of\s+{n}\s+(?:is|=|:)\s*(\{{[^}}]*\}}|\[[^\]]*\]|\([^)]*\)|.+?(?=[.;\n]|\s*,\s*(?:with|where|and)\b|$))",
        rf"(?<![\w.]){n}\s+(?:has|have|with)\s+(?:the\s+)?domain\s*(?:is|=|:)?\s*(\{{[^}}]*\}}|\[[^\]]*\]|\([^)]*\)|.+?(?=[.;\n]|\s*,\s*(?:with|where|and)\b|$))",
        rf"(?<![\w.]){n}\s+(?:is|be)\s+defined\s+on\s+(?:the\s+domain\s+)?(\{{[^}}]*\}}|\[[^\]]*\]|\([^)]*\)|.+?(?=[.;\n]|\s*,\s*(?:with|where|and)\b|$))",
    ):
        m = re.search(pat, text, re.I)
        if m:
            dom = domain_from_words(m.group(1).strip())
            if dom:
                return dom
    return None


def _sentence_domain(text: str, start: int) -> str | None:
    """A number set named in the sentence that contains a definition (and in a short lead-in sentence before it)."""
    s0 = _sentence_start(text, start)
    end = re.search(r"(?<=[^\s.])[.?!](?=\s|$)|\n", text[start:])
    sentence = text[s0: start + (end.start() if end else len(text) - start)]
    prev_start = _sentence_start(text, max(0, s0 - 2))
    lead = text[prev_start:s0] if s0 > 0 and len(text[prev_start:s0]) < 160 else ""
    # Quantified claims ("for every real x") in the same sentence describe a claim, not the function's domain.
    sentence = re.sub(r"(?i)\bfor\s+(?:every|all|each|any)\b[^,.;]*", " ", sentence)
    return domain_from_words(sentence) or (domain_from_words(lead) if re.search(r"(?i)\bfunction|defined|domain\b", lead) else None)


def _find_cond_end(tail: str) -> int:
    """End index of a condition string, avoiding splits on commas inside braces/brackets."""
    depth = 0
    for i, ch in enumerate(tail):
        if i == 0:
            continue
        if ch in "([{":
            depth += 1
        elif ch in ")]}":
            depth = max(0, depth - 1)
        elif depth == 0:
            if ch in ";\n":
                return i
            if ch == "." and (i + 1 == len(tail) or tail[i + 1].isspace()):
                return i
            if ch == "," and not (i + 1 < len(tail) and tail[i + 1].isdigit()):
                return i
            if tail.startswith(" and ", i) and re.match(r"\s+and\s+[A-Za-z]\w*\s*\(", tail[i:]):
                return i
    return len(tail)


def parse_definitions(text: str) -> tuple[list[dict[str, Any]], list[tuple[int, int]], list[str]]:
    """Function definitions stated in the question -> (definitions, their text spans, problems). A definition the parser
    cannot represent faithfully is reported in problems instead of being guessed."""
    defs: dict[str, dict[str, Any]] = {}
    spans: list[tuple[int, int]] = []
    problems: list[str] = []
    declared: dict[str, str] = {}
    for m in _DECL_RE.finditer(text):
        dom = _domain_from_symbol(m.group(2)) or domain_from_words(m.group(2))
        if dom:
            declared[m.group(1)] = dom
            spans.append(m.span())
    for pat in (
        r"\bdomain\s+of\s+([A-Za-z][A-Za-z0-9_]{0,15})\s+(?:is|=|:)\s*(\{[^}]*\}|\[[^\]]*\]|\([^)]*\)|[^\n.;]+)",
        r"(?<![\w.])([A-Za-z][A-Za-z0-9_]{0,15})\s+(?:has|have|with)\s+(?:the\s+)?domain\s*(?:is|=|:)?\s*(\{[^}]*\}|\[[^\]]*\]|\([^)]*\)|[^\n.;]+)",
        r"(?<![\w.])([A-Za-z][A-Za-z0-9_]{0,15})\s+(?:is|be)\s+defined\s+on\s+(?:the\s+domain\s+)?(\{[^}]*\}|\[[^\]]*\]|\([^)]*\)|[^\n.;]+)",
    ):
        for m in re.finditer(pat, text, re.I):
            fn_name = m.group(1)
            dom = domain_from_words(m.group(2).strip())
            if dom:
                declared[fn_name] = dom
                spans.append(m.span())
    first_at: dict[str, int] = {}
    for m in _DEF_HEAD_RE.finditer(text):
        name, param = m.group(1), m.group(2)
        if name == param or not _is_definition_site(text, m.start()):
            continue
        if name in _RESERVED:
            # P(A) = 0.3 is a probability, E(X) an expectation; P(s) = (s - 1/4)(s - 3/4) is a function of s.
            rest_head = re.split(r"[,;.\n]", text[m.end():], maxsplit=1)[0]
            if name not in _NOTATION_NAMES or not re.search(rf"(?<![A-Za-z]){re.escape(param)}(?![A-Za-z])", rest_head):
                continue
        first_at.setdefault(name, m.start())
        rest = text[m.end():]
        end = _EXPR_END_RE.search(rest)
        expr_text = rest[: end.start() if end else len(rest)].strip()
        cond_text, stop = "", m.end() + (end.start() if end else len(rest))
        if end and re.match(r"\s+(?:for|if|when|whenever|provided|otherwise|else|on)\b", end.group(0)):
            tail = rest[end.start():]
            c_stop = _find_cond_end(tail)
            cond_text = tail[:c_stop].strip()
            stop = m.end() + end.start() + c_stop
        if not expr_text:
            continue
        if re.search(rf"(?<![\w.]){re.escape(name)}\s*\(", expr_text):
            problems.append(f"{name} is defined recursively; only explicit definitions are evaluated")
            continue
        try:
            body = safe_parse_expr(_ascii_rel(expr_text), local_dict={param: sp.Symbol(param)})
        except Exception:  # noqa: BLE001 - not a formula: not a definition this module can represent
            continue
        cond = parse_condition(cond_text, param) if cond_text else ("", None)
        if cond is None:
            problems.append(f"the condition {cond_text!r} of {name} is not understood")
            continue
        condition, cond_domain = cond
        entry = defs.setdefault(name, {"name": name, "parameter": param, "domain": None, "branches": []})
        if entry["parameter"] != param:
            body = body.subs(sp.Symbol(param), sp.Symbol(entry["parameter"]))
            condition = condition.replace(param, entry["parameter"]) if condition not in ("even", "odd", "otherwise") else condition
        entry["branches"].append({"expression": sp.sstr(body), "condition": condition})
        if cond_domain:
            entry.setdefault("_domains", []).append(cond_domain)
        spans.append((m.start(), stop))
    out = []
    for name, entry in defs.items():
        branch_domains = set(entry.pop("_domains", []))
        # Priority: a typed declaration or "the domain of q is ..."; a domain named in a branch condition ("for even
        # positive integers"); a domain named in the defining sentence; integers when the branches test parity.
        sentence_dom = _sentence_domain(text, first_at.get(name, 0))
        if name in declared or _declared_domain(text, name):
            entry["domain"] = declared.get(name) or _declared_domain(text, name)
        elif len(branch_domains) == 1:
            entry["domain"] = branch_domains.pop()
        elif sentence_dom:
            entry["domain"] = sentence_dom
        elif any(b["condition"] in ("even", "odd") for b in entry["branches"]):
            entry["domain"] = "integer"
        else:
            entry["domain"] = "unspecified"
        conds = [b["condition"] for b in entry["branches"]]
        if len(conds) > 1 and "" in conds:
            problems.append(f"{name} has several formulas without branch conditions")
            continue
        out.append(entry)
    return out, spans, problems


def function_symbols(defs: list[dict[str, Any]]) -> dict[str, Any]:
    return {d["name"]: sp.Function(d["name"]) for d in defs}


def parse_with_definitions(text: str, defs: list[dict[str, Any]], extra: dict[str, Any] | None = None) -> sp.Expr:
    """Parse an expression in which the defined names are function applications, never products."""
    local = dict(function_symbols(defs))
    local.update(extra or {})
    return safe_parse_expr(_ascii_rel(text), local_dict=local)


def apply_definition(defn: dict[str, Any], value: sp.Expr) -> tuple[sp.Expr, int]:
    """Exact value of a defined function at an exact argument -> (value, index of the branch used)."""
    name, param, domain = defn["name"], defn["parameter"], defn.get("domain") or "unspecified"
    member = in_domain(value, domain)
    if member is False:
        raise DefinitionError(f"{name}({value}) is undefined: {value} is not in the domain of {name} ({domain_label(domain)})")
    x = sp.Symbol(param)
    chosen = [i for i, b in enumerate(defn["branches"]) if b["condition"] != "otherwise" and condition_holds(b["condition"], param, value) is True]
    undecided = [i for i, b in enumerate(defn["branches"]) if condition_holds(b["condition"], param, value) is None]
    if undecided:
        raise DefinitionError(f"cannot decide which branch of {name} applies at {param} = {value}")
    if not chosen:
        chosen = [i for i, b in enumerate(defn["branches"]) if b["condition"] == "otherwise"]
    if not chosen:
        raise DefinitionError(f"no branch of {name} applies at {param} = {value}")
    results = {sp.simplify(safe_parse_expr(defn["branches"][i]["expression"], local_dict={param: x}).subs(x, value)) for i in chosen}
    if len(results) > 1:
        raise DefinitionError(f"branches of {name} disagree at {param} = {value}")
    out = results.pop()
    if out.has(sp.zoo, sp.nan) or out.is_finite is False:
        raise DefinitionError(f"{name}({value}) is undefined (division by zero)")
    return out, chosen[0]


def evaluate(expr: sp.Expr, defs: list[dict[str, Any]], trace: list[dict[str, Any]] | None = None) -> sp.Expr:
    """Replace every application of a defined function by its value, innermost first; record each application."""
    by_name = {d["name"]: d for d in defs}
    for _ in range(200):
        apps = [a for a in expr.atoms(AppliedUndef) if a.func.__name__ in by_name and not a.args[0].atoms(AppliedUndef)]
        if not apps:
            break
        repl = {}
        for app in apps:
            defn = by_name[app.func.__name__]
            arg = app.args[0]
            if arg.free_symbols:
                if len(defn["branches"]) != 1 or defn["branches"][0]["condition"] not in ("", "otherwise"):
                    raise DefinitionError(f"{app} has a symbolic argument and {defn['name']} has several branches")
                x = sp.Symbol(defn["parameter"])
                repl[app] = safe_parse_expr(defn["branches"][0]["expression"], local_dict={x.name: x}).subs(x, arg)
                if trace is not None:
                    trace.append({"function": defn["name"], "argument": sp.sstr(arg), "branch": 0, "value": sp.sstr(repl[app]), "symbolic": True})
                continue
            val, branch = apply_definition(defn, arg)
            repl[app] = val
            if trace is not None:
                trace.append({"function": defn["name"], "argument": sp.sstr(arg), "branch": branch, "value": sp.sstr(val)})
        expr = expr.xreplace(repl)
    return expr


def singular_points(expr_text: str, variable: str) -> list[sp.Expr]:
    """Real points where a written expression is undefined because a written denominator vanishes. SymPy cancels x/x
    to 1 while parsing, so the denominators are read from the text itself."""
    x = sp.Symbol(variable)
    points: set[sp.Expr] = set()
    for m in re.finditer(r"/\s*(\((?:[^()]|\([^()]*\))*\)|[A-Za-z0-9_.^]+)", expr_text):
        try:
            den = safe_parse_expr(m.group(1), local_dict={variable: x})
        except Exception:  # noqa: BLE001
            continue
        if x in den.free_symbols:
            try:
                points.update(r for r in sp.solve(sp.Eq(den, 0), x) if r.is_real)
            except Exception:  # noqa: BLE001
                continue
    return sorted(points, key=lambda v: float(v))


# Task parsing ----------------------------------------------------------------------------------------------------------

# "Case A: n = 40." / "(b) x = 3, y = 4;" -- inline, because normalisation joins the question into one line.
_BINDINGS = rf"(?:[A-Za-z]\w*\s*=\s*{_NUMBER}\s*(?:,|and)?\s*)+?"
_CASE_RE = re.compile(
    rf"(?:\b(?P<word>[Cc]ase)\s+\(?(?P<label>[A-Za-z0-9]{{1,3}})\)?\s*[:.)]|(?:^|(?<=[\s:;]))\((?P<plabel>[A-Za-z0-9]{{1,3}})\))"
    rf"\s*(?P<bindings>{_BINDINGS})(?=\.\s|\.$|;|$|\s*\b[Cc]ase\b|\s*\([A-Za-z0-9]{{1,3}}\))")
_CASES_EXPR_RE = re.compile(
    r"(?i)\b(?:evaluate|compute|calculate|find|determine|work\s+out)\s+(?:the\s+value\s+of\s+)?(?P<expr>.+?)\s+"
    r"(?:in|for|under|across|on)\s+(?:each\s+of\s+)?(?:the\s+)?(?:following\s+)?(?:\w+\s+)?(?:independent\s+|separate\s+|following\s+)?cases?\b")
_ORBIT_RE = re.compile(r"(?i)\b(cycle|orbit|trajectory|sequence|iterates?|iteration)\b")
_ORBIT_START_RE = re.compile(rf"(?i)\b(?:start(?:ing)?|beginning|begin|from)\s+(?:at|from|with)?\s*(?:[a-z]\s*=\s*)?({_NUMBER})\b")
_CLAIM_RE = re.compile(
    r"(?is)\b(?P<verb>prove\s+or\s+disprove|prove|show|verify|disprove|demonstrate|determine\s+whether|check\s+whether|"
    r"decide\s+whether|is\s+it\s+true|is\s+it|is)\s+(?:that\s+)?(?P<stmt>(?:[^.?!;\n]|!=)+?)\s+"
    r"(?P<q>for\s+(?:every|all|each|any)\s+(?:[^.?!;\n]|!=|\.\d)+?)\s*(?:[.?;\n?]|!(?!=)|$)")
_PREDICATE_RE = re.compile(
    r"(?i)^(?P<expr>.+?)\s+is\s+(?:always\s+)?(?:a\s+|an\s+)?(?P<pred>prime|composite|even|odd|positive|negative|"
    r"non-?negative|nonzero|non-zero|integer|perfect\s+square)(?:\s+(?:number|integer))?$")
_DIVISIBLE_RE = re.compile(r"(?i)^(?P<expr>.+?)\s+is\s+(?:always\s+)?divisible\s+by\s+(?P<d>\S+)$")
_EVAL_VERB_RE = re.compile(r"(?i)\b(?:compute|evaluate|calculate|find|determine|give|state|request|get|what\s+(?:is|are))\b")
_NOT_A_VALUE_RE = re.compile(
    r"(?i)\b(?:derivative|integral|limit|roots?|zeros?|solutions?|maximum|minimum|inverse|graph|plot|domain|range|"
    r"period|series|slope|tangent|cycle|orbit|sequence|iterat\w*|whether|prove|show)\b")
_FACTOR_RE = re.compile(r"(?i)\bfactori[sz]ations?\b|\bfactor(?:ed|s|ise|ize)?\b|\bprime\s+factors\b")


def _split_top(text: str) -> list[str]:
    parts, depth, cur = [], 0, ""
    i = 0
    while i < len(text):
        ch = text[i]
        depth += ch in "([{"
        depth -= ch in ")]}"
        if depth == 0 and (ch in ",;" or text.startswith(" and ", i)):
            parts.append(cur)
            cur = ""
            i += 5 if text.startswith(" and ", i) else 1
            continue
        cur += ch
        i += 1
    parts.append(cur)
    return [p.strip(" .?!:") for p in parts if p.strip(" .?!:")]


def _mask(text: str, spans: list[tuple[int, int]]) -> str:
    out = list(text)
    for a, b in spans:
        for i in range(a, min(b, len(out))):
            if out[i] != "\n":
                out[i] = " "
    return "".join(out)


def _application_tasks(text: str, defs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    names = "|".join(re.escape(d["name"]) for d in defs)
    tasks: list[dict[str, Any]] = []
    m_eval_at = re.search(
        r"(?i)\b(?:evaluate|compute|calculate|check)\s+(?:(?:at|for)\s+)?(?:[a-z]\s*=\s*)?((?:\d+(?:\s*,\s*|\s+and\s+)?)+)",
        text,
    )
    if m_eval_at and defs:
        nums = re.findall(r"\d+", m_eval_at.group(1))
        for val in nums:
            for d in defs:
                expr = f"{d['name']}({val})"
                tasks.append({"id": expr, "op": "evaluate", "expression": expr})
    for sentence in re.split(r"(?<=[.?!])\s+|\n+", text):
        verb = _EVAL_VERB_RE.search(sentence)
        if not verb or not re.search(rf"(?<![\w.])(?:{names})\s*\(", sentence):
            continue
        body = sentence[verb.end():]
        if _CLAIM_RE.search(sentence):
            continue
        for piece in _split_top(body):
            piece = re.sub(r"(?i)^(?:also|then|the\s+values?\s+of|the\s+value|values?\s+of|of)\s+", "", piece).strip()
            if _NOT_A_VALUE_RE.search(piece):
                continue
            if not re.search(rf"(?<![\w.])(?:{names})\s*\(", piece):
                try:  # a closed numeric expression in the same request ("h(4) and 3*4 + 2")
                    closed = not parse_with_definitions(piece, defs).free_symbols and re.search(r"\d", piece)
                except Exception:  # noqa: BLE001
                    closed = False
                if closed and not re.search(r"[A-Za-z]{2,}", piece):
                    tasks.append({"id": re.sub(r"\s+", "", piece), "op": "evaluate", "expression": piece})
                continue
            if re.search(r"[A-Za-z]{3,}", re.sub(rf"(?<![\w.])(?:{names})\s*\(", "(", piece)):
                continue  # words around the application: not a bare expression to evaluate
            try:
                parse_with_definitions(piece, defs)
            except Exception:  # noqa: BLE001
                continue
            tasks.append({"id": re.sub(r"\s+", "", piece), "op": "evaluate", "expression": piece})
    return tasks


def _orbit_tasks(text: str, defs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    tasks = []
    for sentence in re.split(r"(?<=[.?!])\s+|\n+", text):
        kind = _ORBIT_RE.search(sentence)
        start = _ORBIT_START_RE.search(sentence)
        if not kind or not start:
            continue
        named = [d["name"] for d in defs if re.search(rf"(?<![\w.]){re.escape(d['name'])}(?![\w(])|(?<![\w.]){re.escape(d['name'])}\s*\(", sentence)]
        fn = named[0] if len(named) == 1 else defs[0]["name"] if len(defs) == 1 else None
        if fn is None:
            continue
        steps = re.search(r"(?i)\b(\d+)\s+(?:times|iterations|steps|applications)\b", sentence)
        mode = "cycle" if re.search(r"(?i)\bcycle\b", sentence) else "steps" if steps else "until_repeat"
        task = {"id": f"{kind.group(1).lower()} from {start.group(1)}", "op": "orbit", "function": fn, "start": start.group(1), "mode": mode}
        if steps:
            task["steps"] = int(steps.group(1))
        tasks.append(task)
    return tasks


def _case_tasks(text: str, defs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    cases = list(_CASE_RE.finditer(text))
    if not cases or not (any(m.group("word") for m in cases) or (len(cases) >= 2 and re.search(r"(?i)\bcases?\b", text))):
        return []
    head = _CASES_EXPR_RE.search(text[: cases[0].start()])
    expr = None
    if head:
        expr = head.group("expr").strip(" :,")
    else:
        tail = _CASES_EXPR_RE.search(text[cases[-1].end():]) or re.search(
            r"(?i)\b(?:evaluate|compute|calculate|find|determine|work\s+out)\s+(?:the\s+value\s+of\s+)?(?P<expr>[^.;:\n]+)",
            text[cases[-1].end():],
        )
        if tail:
            expr = re.sub(
                r"(?i)\s+(?:in\s+each(?:\s+case)?|for\s+each(?:\s+case)?|independently|separately).*$",
                "",
                tail.group("expr"),
            ).strip(" :,")
    if not expr:
        return []
    try:
        parsed = parse_with_definitions(expr, defs)
    except Exception:  # noqa: BLE001
        return []
    factor = bool(_FACTOR_RE.search(text))
    tasks = []
    for m in cases:
        bindings = dict(re.findall(rf"([A-Za-z]\w*)\s*=\s*({_NUMBER})", m.group("bindings")))
        if not set(bindings) & {s.name for s in parsed.free_symbols}:
            return []
        label = f"Case {m.group('label')}" if m.group("word") else f"({m.group('plabel')})"
        tasks.append({"id": label, "op": "evaluate", "expression": expr, "bindings": bindings, "factor": factor})
    return tasks


_INDEPENDENT_EVAL_RE = re.compile(
    r"(?i)\b(?:evaluate|compute|calculate|find|determine|work\s+out)\s+(?:the\s+value\s+of\s+)?(?P<expr>[^.;:\n]+)"
)


def _independent_case_tasks(text: str, defs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Parse independent evaluations with local bindings stated before, within, or around the target expression:
    e.g. 'Three independent calculations, k local to each: k=1, k=3, k=6, evaluate 2k+1.'
    e.g. 'Three independent items: k=1, k=3, k=6; compute 2k+1 in each, with k local to its item.'
    e.g. 'Evaluate 2k+1 for k=1, k=3, and k=6 independently.'
    e.g. 'k=1, k=3, k=6. Evaluate 2k+1 in each.'
    """
    m_eval = _INDEPENDENT_EVAL_RE.search(text)
    if not m_eval:
        return []
    expr_raw = m_eval.group("expr").strip(" :,")
    expr_clean = re.sub(r"(?i)\s+\b(?:for|at|when|where|given)\b.*$", "", expr_raw)
    expr_clean = re.sub(
        r"(?i)\s+(?:in\s+each(?:\s+case|\s+item)?|for\s+each(?:\s+case|\s+item)?|independently|separately|"
        r"with\s+[a-z]\s+local\s+to\s+.*|local\s+to\s+.*).*$",
        "",
        expr_clean,
    ).strip(" :,")
    if not expr_clean:
        return []
    try:
        parsed = parse_with_definitions(expr_clean, defs)
    except Exception:  # noqa: BLE001
        return []
    if not hasattr(parsed, "free_symbols") or isinstance(parsed, tuple):
        return []
    sym_names = {s.name for s in parsed.free_symbols}
    if not sym_names:
        return []

    raw_pairs = re.findall(rf"([A-Za-z]\w*)\s*=\s*({_NUMBER})", text)
    relevant = [(v, val) for v, val in raw_pairs if v in sym_names]
    if len(relevant) < 2:
        return []

    is_independent = bool(re.search(
        r"(?i)\b(?:independent|independently|local to each|in each|for each|separately|separate|cases?)\b",
        text,
    ))
    var_counts = [v for v, _ in relevant]
    has_repeated_var = len(var_counts) > len(set(var_counts))
    if not (is_independent or has_repeated_var):
        return []

    factor = bool(_FACTOR_RE.search(text))
    tasks = []
    for i, (v, val) in enumerate(relevant, 1):
        tasks.append({
            "id": f"{v} = {val}",
            "op": "evaluate",
            "expression": expr_clean,
            "bindings": {v: val},
            "factor": factor,
        })
    return tasks


_SUBSTITUTION_RE = re.compile(
    rf"(?i)\b(?:evaluate|compute|calculate|find|determine|work\s+out)\s+(?:the\s+value\s+of\s+)?(?P<expr>[^.?;]+?)\s+"
    rf"(?:for|at|when|with|if|where|given)\s+(?P<bindings>(?:[A-Za-z]\w*\s*=\s*{_NUMBER}\s*(?:,\s*(?:and\s+)?|\s+and\s+)?)+)"
    rf"(?:\s+(?:independently|separately|in\s+each\s+case))?\s*(?:[.?;]|$)"
)


def _substitution_tasks(text: str, defs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """"Evaluate n^2 + 1 for n = 3", "compute 2x + y at x = 1, y = 4": evaluation tasks with scoped bindings."""
    tasks = []
    for m in _SUBSTITUTION_RE.finditer(text):
        expr = m.group("expr").strip(" :,")
        raw_pairs = re.findall(rf"([A-Za-z]\w*)\s*=\s*({_NUMBER})", m.group("bindings"))
        if not raw_pairs:
            continue
        try:
            parsed = parse_with_definitions(expr, defs)
        except Exception:  # noqa: BLE001
            continue
        if not hasattr(parsed, "free_symbols") or isinstance(parsed, tuple):
            continue
        factor = bool(_FACTOR_RE.search(text))
        var_names = [v for v, _ in raw_pairs]
        if len(var_names) > len(set(var_names)):
            for v, val in raw_pairs:
                if v in {s.name for s in parsed.free_symbols}:
                    tasks.append({
                        "id": f"{v} = {val}",
                        "op": "evaluate",
                        "expression": expr,
                        "bindings": {v: val},
                        "factor": factor,
                    })
        else:
            bindings = dict(raw_pairs)
            if not set(bindings) <= {s.name for s in parsed.free_symbols} or not re.search(r"[-+*/^(]", expr):
                continue
            label = ", ".join(f"{k} = {v}" for k, v in bindings.items())
            tasks.append({
                "id": f"{expr} at {label}",
                "op": "evaluate",
                "expression": expr,
                "bindings": bindings,
                "factor": factor,
            })
    return tasks


def parse_quantifier(text: str, stmt_symbols: set[str]) -> tuple[str | None, str, list[str]] | None:
    """'for every nonnegative integer n' -> ("n", "nonnegative_integer", []); 'for all real x != 0' -> ("x", "real",
    ["x != 0"])."""
    q = _ascii_rel(text)
    dom = domain_from_words(q)
    conds = [f"{v} {op} {num}" for v, op, num in re.findall(rf"\b([a-z])\s*(<=|>=|!=|<|>)\s*({_NUMBER})", q)]
    names = [n for n in re.findall(r"\b([a-z])\b", q) if n in stmt_symbols]
    var = names[-1] if names else (next(iter(stmt_symbols)) if len(stmt_symbols) == 1 else None)
    if var is None:
        return None
    m = re.search(rf"\b{var}\s+in\s+(\S+)", q)
    if m and dom is None:
        dom = _domain_from_symbol(m.group(1)) or domain_from_words(m.group(1))
    if dom is None:
        if not re.search(r"\b(?:every|all|each|any)\s+[a-z]\b", q):
            return None
        dom = "unspecified"
    return var, dom, conds


# "Prove P(1-s) = P(s)" with no "for every": a statement about a defined function, universal over the variable's
# declared domain (the definition's own, e.g. "where s is complex").
_CLAIM_IMPLICIT_RE = re.compile(
    r"(?i)\b(?:prove|show|verify|demonstrate)\s+(?:that\s+)?"
    r"(?P<stmt>[^.?!;\n,]*?[A-Za-z]\w*(?:\s*\([^()]*\))?[^.?!;\n,]*?(?:<=|>=|!=|=|<|>)[^.?!;\n,]+?)"
    r"\s*(?=[,.;?!\n]|\s+and\s+|$)")


def _implicit_claims(text: str, defs: list[dict[str, Any]], taken: list[tuple[int, int]], first_id: int) -> list[dict[str, Any]]:
    tasks: list[dict[str, Any]] = []
    for m in _CLAIM_IMPLICIT_RE.finditer(text):
        if any(a <= m.start() < b for a, b in taken) or re.search(r"(?i)\bfor\s+(?:every|all|each|any)\b", m.group("stmt")):
            continue
        stmt = _ascii_rel(m.group("stmt").strip())
        rel = re.search(r"(<=|>=|!=|<|>|=)", stmt)
        if not rel:
            continue
        lhs, rhs = stmt[: rel.start()].strip(), stmt[rel.end():].strip()
        fnames = {d["name"] for d in defs}
        var = None
        if lhs in fnames and rhs in fnames:
            var = defs[0]["parameter"]
            lhs = f"{lhs}({var})"
            rhs = f"{rhs}({var})"
        elif not any(re.search(rf"(?<![\w.]){re.escape(f)}\s*\(", stmt) for f in fnames):
            continue  # only statements about the question's own definitions
        try:
            symbols = {s.name for side in (lhs, rhs) for s in parse_with_definitions(side, defs).free_symbols}
        except Exception:  # noqa: BLE001
            continue
        if len(symbols) != 1:
            continue
        var = next(iter(symbols))
        owner = next((d for d in defs if d["parameter"] == var), None) or (defs[0] if len(defs) == 1 else None)
        if owner is None:
            continue
        domain = owner.get("domain") or "unspecified"
        if domain == "unspecified":
            m_dom = re.search(r"\b(?:non[\s-]?negative\s+integer|positive\s+integer|integer|natural|real)\b", text, re.I)
            if m_dom:
                d_str = m_dom.group(0).lower().replace(" ", "_").replace("-", "")
                if "nonnegative" in d_str:
                    domain = "nonnegative_integer"
                elif "positive" in d_str:
                    domain = "positive_integer"
                elif "integer" in d_str or "natural" in d_str:
                    domain = "integer"
                elif "real" in d_str:
                    domain = "real"
        n = first_id + len(tasks)
        tasks.append({"id": "claim" if n == 0 else f"claim {n + 1}", "op": "claim", "lhs": lhs, "relation": rel.group(1),
                      "rhs": rhs, "variable": var, "domain": domain, "conditions": [],
                      "statement": f"{stmt} for every {var} in {domain_label(domain) if domain != 'unspecified' else 'its domain'}"})
    return tasks


# "find all its zeros", "determine the roots of P"; a line "Re(s) = 1/2" in the question is checked against them.
_ZEROS_RE = re.compile(
    r"(?i)\b(?:find|determine|compute|give|list|locate)\s+(?:all\s+(?:of\s+)?)?(?:the\s+)?(?:(?:its|their)\s+)?"
    r"(?:real\s+|complex\s+)?(?:zeros|zeroes|roots)\b(?:\s+of\s+(?P<f>[A-Za-z]\w{0,15})(?:\s*\(\s*[a-z]\s*\))?)?")
_LINE_RE = re.compile(r"\bRe\s*\(\s*(?P<v>[a-z])\s*\)\s*=\s*(?P<c>-?\d+(?:\s*/\s*\d+)?(?:\.\d+)?)")


def _zeros_tasks(text: str, defs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    for m in _ZEROS_RE.finditer(text):
        name = m.group("f")
        defn = next((d for d in defs if d["name"] == name), None) if name else (defs[0] if len(defs) == 1 else None)
        if defn is None or len(defn["branches"]) != 1 or defn["branches"][0].get("condition"):
            continue
        task = {"id": f"zeros of {defn['name']}", "op": "zeros", "function": defn["name"], "variable": defn["parameter"],
                "domain": defn.get("domain") or "unspecified"}
        line = _LINE_RE.search(text)
        if line and line.group("v") == defn["parameter"]:
            task["line"] = re.sub(r"\s+", "", line.group("c"))
        return [task]
    return []


def _claim_tasks(text: str, defs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    tasks = _claim_tasks_explicit(text, defs)
    if defs:
        taken = [m.span() for m in _CLAIM_RE.finditer(text)]
        tasks += _implicit_claims(text, defs, taken, len(tasks))
    return tasks


def _claim_tasks_explicit(text: str, defs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    tasks = []
    for m in _CLAIM_RE.finditer(text):
        stmt = _ascii_rel(m.group("stmt").strip())
        claim: dict[str, Any] = {"id": "claim" if not tasks else f"claim {len(tasks) + 1}", "op": "claim"}
        pm, dm = _PREDICATE_RE.match(stmt), _DIVISIBLE_RE.match(stmt)
        if pm:
            claim.update(expression=pm.group("expr").strip(), predicate=re.sub(r"[\s-]+", "_", pm.group("pred").lower()).replace("non_negative", "nonnegative").replace("non_zero", "nonzero"))
            sides = [claim["expression"]]
        elif dm:
            claim.update(expression=dm.group("expr").strip(), predicate="divisible", divisor=dm.group("d").strip(" ."))
            sides = [claim["expression"], claim["divisor"]]
        else:
            rel = re.search(r"(<=|>=|!=|<|>|=)", stmt)
            if not rel:
                continue
            verb = (m.group("verb") or "").lower()
            if not defs and rel.group(1) == "=" and verb in ("is", "is it"):
                continue
            claim.update(lhs=stmt[: rel.start()].strip(), relation=rel.group(1), rhs=stmt[rel.end():].strip())
            sides = [claim["lhs"], claim["rhs"]]
        try:
            symbols = {s.name for side in sides for s in parse_with_definitions(side, defs).free_symbols}
        except Exception:  # noqa: BLE001
            continue
        fnames = {d["name"] for d in defs}
        symbols |= {v for side in sides for v in re.findall(r"(?<![\w.])([a-z])(?![\w(])", side) if v not in fnames}
        quant = parse_quantifier(m.group("q"), symbols)
        if quant is None:
            continue
        claim["variable"], claim["domain"], claim["conditions"] = quant
        claim["statement"] = f"{stmt} {m.group('q').strip()}"
        tasks.append(claim)
    return tasks


# "If n is even, replace it with n/2. If n is odd, replace it with 3n + 1.": a process given as rules is a map.
_PROCESS_RULE_RE = re.compile(
    r"(?i)\bif\s+([a-z])\s+is\s+(even|odd)\s*,?\s*(?:then\s+)?(?:replace|set|change|map|send|turn)\s+(?:it|[a-z])\s+"
    r"(?:with|to|by|into)\s+([^.;\n]+?)\s*(?:[.;]|$)")
# "... this process eventually reaches 1 for every positive integer"
_REACHES_RE = re.compile(
    r"(?i)\b(?:this|the)\s+(?:process|procedure|iteration|sequence|map|rule)\s+(?:will\s+)?(?:always\s+)?(?:eventually\s+)?"
    r"(?:reach(?:es)?|arrives?\s+at|hits?|gets?\s+to|ends?\s+(?:at|in)|terminates?\s+at)\s+(?:the\s+(?:value|number)\s+)?"
    r"(?P<target>-?\d+)\s+(?P<q>for\s+(?:every|all|each|any)\s+[^.?;\n]+)")
PROCESS_NAME = "step"


def _process_definition(text: str) -> dict[str, Any] | None:
    rules = _PROCESS_RULE_RE.findall(text)
    if len(rules) < 2 or len({r[0] for r in rules}) != 1:
        return None
    var = rules[0][0]
    branches = []
    for _, cond, expr in rules:
        try:
            body = safe_parse_expr(expr.strip(), local_dict={var: sp.Symbol(var)})
        except Exception:  # noqa: BLE001 - an unreadable rule: the process is not represented
            return None
        if body.free_symbols - {sp.Symbol(var)}:
            return None
        branches.append({"expression": sp.sstr(body), "condition": cond.lower()})
    return {"name": PROCESS_NAME, "parameter": var, "domain": domain_from_words(text) or "integer", "branches": branches}


def _reaches_tasks(text: str, defs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    proc = next((d for d in defs if d["name"] == PROCESS_NAME), None) or (defs[0] if len(defs) == 1 else None)
    if proc is None:
        return []
    tasks = []
    for m in _REACHES_RE.finditer(text):
        domain = domain_from_words(m.group("q")) or proc.get("domain") or "positive_integer"
        tasks.append({"id": "reaches", "op": "reaches", "function": proc["name"], "target": m.group("target"),
                      "variable": proc["parameter"], "domain": domain,
                      "statement": f"the process reaches {m.group('target')} {m.group('q').strip()}"})
    return tasks


def parse_structured(text: str) -> tuple[dict[str, Any] | None, list[str]]:
    """The structured reading of a question -> (params {"definitions", "tasks"} or None, problems)."""
    defs, spans, problems = parse_definitions(text)
    if not defs:
        proc = _process_definition(text)
        defs = [proc] if proc else []
    rest = _mask(text, spans)
    tasks: list[dict[str, Any]] = []
    if defs:
        tasks += _reaches_tasks(rest, defs)
    tasks += _case_tasks(rest, defs)
    if not tasks:
        tasks += _independent_case_tasks(rest, defs)
    if not tasks:
        tasks += _substitution_tasks(rest, defs)
    tasks += _claim_tasks(rest, defs)
    if defs:
        tasks += _zeros_tasks(rest, defs)
        tasks += _orbit_tasks(rest, defs)
        tasks += _application_tasks(rest, defs)
    seen, unique = set(), []
    for t in tasks:
        key = (t["op"], t["id"])
        if key not in seen:
            seen.add(key)
            unique.append(t)
    if not unique:
        return None, problems
    return {"definitions": defs, "tasks": unique[:_MAX_TASKS]}, problems


# Execution -------------------------------------------------------------------------------------------------------------

def _value_text(v: sp.Expr) -> str:
    return sp.sstr(v)


def factor_text(value: sp.Expr) -> tuple[str, list[int]] | None:
    """'41^2' / '41 * 43' and the prime factors with multiplicity, for a nonzero integer value."""
    if value.is_integer is not True:
        return None
    n = int(value)
    if n == 0:
        return None
    sign = -1 if n < 0 else 1
    fs = sp.factorint(abs(n))
    flat = [p for p, k in sorted(fs.items()) for _ in range(k)]
    if not flat:
        return ("-1" if sign < 0 else "1"), []
    text = " * ".join(f"{p}^{k}" if k > 1 else str(p) for p, k in sorted(fs.items()))
    return ("-" + text if sign < 0 else text), flat


def _predicate(pred: str, value: sp.Expr, divisor: sp.Expr | None = None) -> bool | None:
    if pred in ("prime", "composite", "even", "odd", "perfect_square", "divisible"):
        if value.is_integer is not True:
            return False if value.is_number else None
        n = int(value)
        if pred == "prime":
            return bool(sp.isprime(n))
        if pred == "composite":
            return n > 1 and not sp.isprime(n)
        if pred == "even":
            return n % 2 == 0
        if pred == "odd":
            return n % 2 == 1
        if pred == "perfect_square":
            return n >= 0 and math.isqrt(n) ** 2 == n
        if divisor is None or divisor.is_integer is not True or int(divisor) == 0:
            return None
        return n % int(divisor) == 0
    if pred == "integer":
        return bool(value.is_integer) if value.is_integer is not None else None
    if value.is_extended_real is not True:
        return None
    return {"positive": value > 0, "negative": value < 0, "nonnegative": value >= 0, "nonzero": value != 0}[pred] in (True, sp.true)


def domain_values(domain: str, limit: int = CLAIM_SEARCH_LIMIT) -> list[sp.Expr]:
    if domain == "positive_integer":
        return [sp.Integer(k) for k in range(1, limit + 1)]
    if domain == "nonnegative_integer":
        return [sp.Integer(k) for k in range(limit)]
    if domain.startswith("integer_ge_"):
        k = int(domain.split("_ge_")[1])
        return [sp.Integer(k + i) for i in range(limit)]
    if domain.startswith("integer_gt_"):
        k = int(domain.split("_gt_")[1])
        return [sp.Integer(k + 1 + i) for i in range(limit)]
    if domain.startswith("integer_le_"):
        k = int(domain.split("_le_")[1])
        return [sp.Integer(k - i) for i in range(limit)]
    if domain.startswith("integer_lt_"):
        k = int(domain.split("_lt_")[1])
        return [sp.Integer(k - 1 - i) for i in range(limit)]
    if domain.startswith("finite_set:{") and domain.endswith("}"):
        elems = [safe_parse_expr(p.strip()) for p in domain[len("finite_set:{"):-1].split(",") if p.strip()]
        return elems[:limit]
    if domain == "integer":
        out = [sp.Integer(0)]
        for k in range(1, limit // 2 + 1):
            out += [sp.Integer(k), sp.Integer(-k)]
        return out[:limit]
    # real / rational / unspecified: a fixed grid of exact rationals, symmetric about 0
    grid = {sp.Rational(p, q) for q in (1, 2, 3, 7) for p in range(-12 * q, 12 * q + 1)}
    return sorted(grid, key=lambda v: (abs(v), v))[:limit]


def _pretty(text: str) -> str:
    return str(text).replace("**", "^")


def _residue_proof(task: dict[str, Any], defs: list[dict[str, Any]], var: sp.Symbol, domain: str) -> dict[str, Any] | None:
    """Divisibility and parity of a polynomial over the integers: with D the common denominator of its coefficients,
    D*P(n) has integer coefficients, so D*P(n) mod D*d depends only on n mod D*d. Checking every residue proves (or
    refutes) the claim for all integers, and for the nonnegative or positive integers, which contain every residue."""
    pred = task.get("predicate")
    if pred not in ("divisible", "even", "odd") or domain not in _INTEGER_DOMAINS or task.get("conditions"):
        return None
    try:
        expr = evaluate(parse_with_definitions(task["expression"], defs, {var.name: var}), defs)
        d = 2 if pred != "divisible" else int(safe_parse_expr(str(task["divisor"])))
        poly = sp.Poly(sp.expand(expr), var)
    except Exception:  # noqa: BLE001 - not a polynomial in the variable: no residue argument
        return None
    if d == 0 or poly.free_symbols - {var} or not all(c.is_rational for c in poly.all_coeffs()):
        return None
    den = int(sp.ilcm(*[sp.Rational(c).q for c in poly.all_coeffs()], 1))
    mod = abs(d) * den
    if mod > 100_000:
        return None
    q = sp.Poly(poly.as_expr() * den, var)
    target = den % mod if pred == "odd" else 0
    for r in range(mod):
        if int(q.eval(r)) % mod != target:
            return None  # fails for some residue: the counterexample search below finds the witness
    what = {"divisible": f"divisible by {d}", "even": "even", "odd": "odd"}[pred]
    step = (f"{task['expression']} has {'integer' if den == 1 else 'rational'} coefficients, so "
            f"{'' if den == 1 else f'{den}*('}{task['expression']}{'' if den == 1 else ')'} mod {mod} depends only on {var} mod {mod}; "
            f"all {mod} residues give a value that is {what}")
    return {"status": "proved", "steps": [step], "method": f"exhaustive check of the residues modulo {mod}",
            "text": f"True: {task['statement']}. {step}."}


def _run_claim(task: dict[str, Any], defs: list[dict[str, Any]]) -> dict[str, Any]:
    var = sp.Symbol(task["variable"])
    extra = {var.name: var}
    conds = task.get("conditions") or []
    domain = task.get("domain") or "unspecified"

    # If domain is unspecified, check if any defined function applied to var has a declared domain
    claim_exprs = str(task.get("lhs", "")) + " " + str(task.get("rhs", "")) + " " + str(task.get("expression", ""))
    applied_fns = [d for d in defs if re.search(rf"(?<![\w.]){re.escape(d['name'])}\s*\(\s*{re.escape(task['variable'])}\s*\)", claim_exprs)]
    if domain == "unspecified" and applied_fns:
        for fn in applied_fns:
            fn_dom = fn.get("domain") or "unspecified"
            if fn_dom != "unspecified" and (domain == "unspecified" or is_proper_subdomain(fn_dom, domain)):
                domain = fn_dom

    steps: list[str] = []
    trace: list[dict[str, Any]] = []

    def holds_at(v: sp.Expr) -> tuple[bool | None, str]:
        if task.get("predicate"):
            e = evaluate(parse_with_definitions(task["expression"], defs, extra).subs(var, v), defs)
            d = parse_with_definitions(task["divisor"], defs, extra).subs(var, v) if task.get("divisor") else None
            ok = _predicate(task["predicate"], sp.simplify(e), d)
            detail = f"{task['expression']} = {_value_text(sp.simplify(e))}"
            ft = factor_text(sp.simplify(e)) if task["predicate"] in ("prime", "composite") else None
            if ft and len(ft[1]) > 1:
                detail += f" = {ft[0]}"
            return ok, detail
        lhs = evaluate(parse_with_definitions(task["lhs"], defs, extra).subs(var, v), defs)
        rhs = evaluate(parse_with_definitions(task["rhs"], defs, extra).subs(var, v), defs)
        rel = _REL_OPS[task["relation"]](sp.simplify(lhs), sp.simplify(rhs))
        ok = bool(rel) if rel in (sp.true, sp.false) else None
        return ok, f"{task['lhs']} = {_value_text(sp.simplify(lhs))}, {task['rhs']} = {_value_text(sp.simplify(rhs))}"

    def admissible(v: sp.Expr) -> bool:
        if in_domain(v, domain) is False:
            return False
        if not all(condition_holds(c, var.name, v) is True for c in conds):
            return False
        for fn in applied_fns:
            if in_domain(v, fn.get("domain") or "unspecified") is False:
                return False
        return True

    # Symbolic proof of an equation: substitute the definitions, simplify, then look at points where the written
    # expression is undefined but the quantifier still includes them.
    if task.get("relation") == "=":
        try:
            lhs = evaluate(parse_with_definitions(task["lhs"], defs, extra), defs, trace)
            rhs = evaluate(parse_with_definitions(task["rhs"], defs, extra), defs, trace)
            for t in trace:
                defn = next(d for d in defs if d["name"] == t["function"])
                steps.append(f"{t['function']}({t['argument']}) = {_pretty(t['value'])} by the definition of {defn['name']}")
            diff = sp.simplify(lhs - rhs)
            if diff == 0:
                written = task["lhs"] + " - (" + task["rhs"] + ")"
                bad = [p for p in singular_points(written, var.name) + [p for t in trace for p in singular_points(
                    next(b["expression"] for b in next(d for d in defs if d["name"] == t["function"])["branches"]), t["argument"])
                    if t.get("symbolic")] if admissible(p)]
                if bad:
                    return {"status": "disproved", "counterexample": _value_text(bad[0]), "detail": f"undefined at {var} = {bad[0]} (division by zero)",
                            "steps": steps, "text": f"False as stated: the expression is undefined at {var} = {bad[0]}, which the statement includes."}
                written_lhs = task["lhs"]
                for t in trace:
                    if t.get("symbolic"):
                        written_lhs = re.sub(rf"(?<![\w.]){re.escape(t['function'])}\s*\(\s*{re.escape(t['argument'])}\s*\)",
                                             f"({_pretty(t['value'])})", written_lhs)
                chain = f"{task['lhs']} = {written_lhs} = {_pretty(sp.sstr(sp.simplify(lhs)))}" if written_lhs != task["lhs"] else \
                    f"{task['lhs']} - ({task['rhs']}) simplifies to 0"
                steps.append(chain)
                return {"status": "proved", "steps": steps, "method": "substitution of the definitions and exact simplification",
                        "text": f"True: {task['statement']}. " + "; ".join(_pretty(x) for x in steps) + "."}
        except DefinitionError as exc:
            steps.append(str(exc))
    elif task.get("relation") in ("<", "<=", ">", ">=", "!="):
        try:
            lhs = evaluate(parse_with_definitions(task["lhs"], defs, extra), defs, trace)
            rhs = evaluate(parse_with_definitions(task["rhs"], defs, extra), defs, trace)
            for t in trace:
                defn = next((d for d in defs if d["name"] == t["function"]), None)
                if defn:
                    steps.append(f"{t['function']}({t['argument']}) = {_pretty(t['value'])} by the definition of {defn['name']}")
            diff = sp.simplify(lhs - rhs)
            rel_op = task["relation"]
            proved = False
            if domain == "nonnegative_integer":
                k = sp.Symbol("_k", integer=True, nonnegative=True)
                d_sub = sp.simplify(diff.subs(var, k))
                rel_val = _REL_OPS[rel_op](d_sub, 0)
                if rel_val is sp.true or rel_val is True:
                    proved = True
            elif domain == "positive_integer":
                k = sp.Symbol("_k", integer=True, nonnegative=True)
                d_sub = sp.simplify(diff.subs(var, k + 1))
                rel_val = _REL_OPS[rel_op](d_sub, 0)
                if rel_val is sp.true or rel_val is True:
                    proved = True
            elif domain.startswith("integer_ge_"):
                k_val = int(domain.split("_ge_")[1])
                k = sp.Symbol("_k", integer=True, nonnegative=True)
                d_sub = sp.simplify(diff.subs(var, k + k_val))
                rel_val = _REL_OPS[rel_op](d_sub, 0)
                if rel_val is sp.true or rel_val is True:
                    proved = True
            elif domain == "real":
                rel_val = _REL_OPS[rel_op](diff, 0)
                if rel_val is sp.true or rel_val is True:
                    proved = True
            if proved:
                step_pf = f"For every {var} in {domain_label(domain)}, {task['lhs']} - ({task['rhs']}) = {_pretty(sp.sstr(diff))} {rel_op} 0"
                steps.append(step_pf)
                return {
                    "status": "proved",
                    "steps": steps,
                    "method": "algebraic difference sign analysis",
                    "text": f"True: {task['statement']}. {step_pf}.",
                }
        except DefinitionError as exc:
            steps.append(str(exc))
    proof = _residue_proof(task, defs, var, domain)
    if proof is not None:
        return proof
    for v in domain_values(domain if is_integer_domain(domain) else "real"):
        if not admissible(v):
            continue
        try:
            ok, detail = holds_at(v)
        except DefinitionError:
            continue
        if ok is False:
            witness = {var.name: _value_text(v)}
            sides = [task["expression"]] if task.get("predicate") else [task["lhs"], task["rhs"]]
            for side in sides:
                try:
                    side_value = sp.simplify(evaluate(parse_with_definitions(side, defs, extra).subs(var, v), defs))
                    steps += evaluation_steps({"expression": side, "bindings": witness,
                                               "factor": task.get("predicate") in ("prime", "composite")}, defs, side_value, [])
                except (DefinitionError, ValueError):
                    continue
            what = {"prime": "is not prime", "composite": "is not composite", "even": "is not even", "odd": "is not odd",
                    "divisible": f"is not divisible by {task.get('divisor')}"}.get(str(task.get("predicate")), "violates the relation")
            steps.append(f"So {var} = {_value_text(v)}, which lies in the stated domain, gives a value that {what}: "
                         "one counterexample refutes the universal statement.")
            return {"status": "disproved", "counterexample": _value_text(v), "detail": detail, "steps": steps,
                    "text": f"False: at {var} = {v}, {detail}" + (", which is not prime." if task.get("predicate") == "prime" else ".")}
    searched = f"{domain_label(domain)}" + (f" up to {CLAIM_SEARCH_LIMIT} values" if is_integer_domain(domain) else " on a grid of rational points")
    return {"status": "unresolved", "steps": steps, "searched": searched,
            "text": f"No counterexample among the {searched}; this is evidence, not a proof."}


# Derivation steps ------------------------------------------------------------------------------------------------------
# Every step is generated from the exact computation, never written by a model: which branch applies and why, the
# formula with the value substituted, the terms evaluated, the result. The writer is told to use them verbatim.

def _plug(expr_text: str, values: dict[str, str]) -> str:
    """The written expression with each variable replaced by its value ("n^2 + n + 41" -> "40^2 + 40 + 41")."""
    out = _pretty(expr_text)
    for name, value in values.items():
        shown = f"({value})" if str(value).startswith("-") or "/" in str(value) else str(value)
        # "3n" with n = 1 is 3*1, never "31".
        out = re.sub(rf"(?<=\d){re.escape(name)}(?![\w(])", f"*{shown}", out)
        out = re.sub(rf"(?<![\w.]){re.escape(name)}(?![\w(])", shown, out)
    return out


def _top_level_terms(text: str) -> list[tuple[str, str]]:
    """[(sign, term)] of a written sum at parenthesis depth 0: "n^2 + n + 41" -> [("+","n^2"), ("+","n"), ("+","41")]."""
    terms, depth, cur, sign = [], 0, "", "+"
    for i, ch in enumerate(text):
        depth += ch == "("
        depth -= ch == ")"
        if depth == 0 and ch in "+-" and cur.strip() and not re.search(r"[*/^(]\s*$", cur):
            terms.append((sign, cur.strip()))
            cur, sign = "", ch
            continue
        if depth == 0 and ch in "+-" and not cur.strip() and i == 0:
            sign = ch
            continue
        cur += ch
    if cur.strip():
        terms.append((sign, cur.strip()))
    return terms


def _term_values(expr_text: str, defs: list[dict[str, Any]], values: dict[str, sp.Expr]) -> str | None:
    """'1600 + 40 + 41' for a written sum: each term evaluated, in the question's order; None for a single term."""
    terms = _top_level_terms(expr_text)
    if len(terms) < 2:
        return None
    parts = []
    for sign, term in terms:
        v = parse_with_definitions(term, defs, {k: sp.Symbol(k) for k in values}).xreplace(
            {sp.Symbol(k): val for k, val in values.items()})
        parts.append((sign, _pretty(sp.sstr(sp.simplify(evaluate(v, defs))))))
    out = parts[0][1] if parts[0][0] == "+" else f"-{parts[0][1]}"
    for sign, val in parts[1:]:
        out += f" {sign} {val}"
    return out.replace("+ -", "- ").replace("- -", "+ ")


def _condition_reason(condition: str, param: str, value: sp.Expr) -> str:
    if condition == "even":
        return f"{_pretty(sp.sstr(value))} is even"
    if condition == "odd":
        return f"{_pretty(sp.sstr(value))} is odd"
    if condition == "otherwise":
        return "no other branch applies"
    if condition:
        return condition.replace(param, _pretty(sp.sstr(value)), 1)
    return ""


def application_step(defn: dict[str, Any], value: sp.Expr, branch: int, result: sp.Expr) -> str:
    """"T(1): 1 is odd, so T(1) = 3*1 + 1 = 4" from the branch actually used."""
    b = defn["branches"][branch]
    arg = _pretty(sp.sstr(value))
    plugged = _plug(b["expression"], {defn["parameter"]: sp.sstr(value)})
    reason = _condition_reason(b["condition"], defn["parameter"], value)
    if b["condition"] == "otherwise":
        # Say why the other branches do not apply ("0 < 0 is false"), not only that this one is left.
        failed = []
        for other in defn["branches"]:
            c = other["condition"]
            if c in ("even", "odd"):
                failed.append(f"{arg} is not {c}")
            elif c not in ("", "otherwise"):
                failed.append(f"{c.replace(defn['parameter'], arg, 1)} is false")
        reason = (", ".join(failed) + ", so the remaining branch applies") if failed else reason
    lhs = f"{defn['name']}({arg})"
    body = f"{lhs} = {plugged} = {_pretty(sp.sstr(result))}" if plugged != _pretty(sp.sstr(result)) else f"{lhs} = {plugged}"
    return f"{reason}, so {body}" if reason else body


def evaluation_steps(task: dict[str, Any], defs: list[dict[str, Any]], value: sp.Expr, trace: list[dict[str, Any]]) -> list[str]:
    steps: list[str] = []
    by_name = {d["name"]: d for d in defs}
    for app in trace:
        defn = by_name.get(app["function"])
        if defn is not None and not app.get("symbolic"):
            steps.append(application_step(defn, _exact_value(app["argument"]), app["branch"], _exact_value(app["value"])))
    bindings = {k: str(v) for k, v in (task.get("bindings") or {}).items()}
    if bindings:
        plugged = _plug(task["expression"], bindings)
        terms = _term_values(task["expression"], defs, {k: _exact_value(v) for k, v in bindings.items()})
        chain = [_pretty(task["expression"]), plugged] + ([terms] if terms and terms != plugged else []) + [_pretty(sp.sstr(value))]
        steps.append(f"With {', '.join(f'{k} = {v}' for k, v in bindings.items())}: " + " = ".join(dict.fromkeys(chain)))
    if task.get("factor"):
        ft = factor_text(value)
        if ft is not None:
            primes = sorted(set(ft[1]))
            steps.append(f"{_pretty(sp.sstr(value))} = {ft[0]}" + (
                f", where {', '.join(map(str, primes))} {'is' if len(primes) == 1 else 'are'} prime" if primes else ""))
    return steps


def _run_orbit(task: dict[str, Any], defs: list[dict[str, Any]]) -> dict[str, Any]:
    defn = next(d for d in defs if d["name"] == task["function"])
    value = safe_parse_expr(str(task["start"]))
    seq, branches = [value], []
    limit = min(int(task.get("steps") or ORBIT_LIMIT), ORBIT_LIMIT)
    steps: list[str] = []
    for _ in range(limit):
        prev = value
        value, branch = apply_definition(defn, value)
        seq.append(value)
        branches.append(branch)
        if len(steps) < 40:
            steps.append(application_step(defn, prev, branch, value))
        if task.get("mode") in ("cycle", "until_repeat") and value in seq[:-1]:
            break
    closed = seq[-1] in seq[:-1]
    if closed:
        steps.append(f"{_pretty(sp.sstr(seq[-1]))} appeared before, so the orbit repeats from here: "
                     + " -> ".join(_pretty(sp.sstr(v)) for v in seq[seq.index(seq[-1]):]))
    if task.get("mode") == "cycle" and closed and seq[-1] != seq[0]:
        # The cycle the orbit enters does not pass through the start value: report the cycle itself, separately.
        first = seq.index(seq[-1])
        cycle = seq[first:]
    else:
        cycle = seq if closed else []
    arrow = " -> ".join(map(_value_text, seq))
    text = arrow if not (task.get("mode") == "cycle" and not closed) else f"{arrow} (no repeat within {limit} applications)"
    return {"sequence": [_value_text(v) for v in seq], "branches": branches, "closed": closed, "steps": steps,
            "cycle": [_value_text(v) for v in cycle], "text": text}


def _clean(value: Any) -> Any:
    """Drop unset (None) fields, as a validated tool call carries every optional field."""
    if isinstance(value, dict):
        return {k: _clean(v) for k, v in value.items() if v is not None}
    if isinstance(value, list):
        return [_clean(v) for v in value]
    return value


def axiom_structured(definitions: list[dict[str, Any]] | None = None, tasks: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """Tool entry point (schema: AxiomStructuredInput)."""
    defs = _clean(list(definitions or []))
    for d in defs:
        d.setdefault("domain", "unspecified")
        for b in d["branches"]:
            b.setdefault("condition", "")
            safe_parse_expr(b["expression"], local_dict={d["parameter"]: sp.Symbol(d["parameter"])})  # validates the formula
    return run_structured(defs, _clean(list(tasks or [])))


# "Reaches c for every n": a bounded check that never claims more than it checked, and the lemmas that are provable --

REACH_LIMIT_N = 5000  # start values checked
REACH_MAX_STEPS = 10_000  # applications per start value before it is reported as not reached (not as a counterexample)


def _compile(expr: sp.Expr, var: sp.Symbol) -> Callable[[Fraction], Fraction]:
    """Exact rational evaluation of a validated SymPy expression as nested closures (no eval, no exec)."""
    if expr == var:
        return lambda x: x
    if expr.is_Rational:
        c = Fraction(int(expr.p), int(expr.q))
        return lambda _x: c
    if isinstance(expr, sp.Add):
        parts = [_compile(a, var) for a in expr.args]
        return lambda x: sum((p(x) for p in parts), Fraction(0))
    if isinstance(expr, sp.Mul):
        parts = [_compile(a, var) for a in expr.args]

        def mul(x: Fraction) -> Fraction:
            out = Fraction(1)
            for p in parts:
                out *= p(x)
            return out
        return mul
    if isinstance(expr, sp.Pow) and expr.exp.is_Integer and 0 <= int(expr.exp) <= 64:
        base, k = _compile(expr.base, var), int(expr.exp)
        return lambda x: base(x) ** k
    raise DefinitionError(f"{expr} is not rational arithmetic in {var}")


def _compiled_step(defn: dict[str, Any]) -> Callable[[Fraction], Fraction]:
    var = sp.Symbol(defn["parameter"])
    branches = [(b["condition"], _compile(safe_parse_expr(b["expression"], local_dict={var.name: var}), var))
                for b in defn["branches"]]
    if any(c not in ("even", "odd") for c, _ in branches):
        raise DefinitionError("only parity branches are iterated by the bounded check")
    table = dict(branches)

    def step(x: Fraction) -> Fraction:
        if x.denominator != 1:
            raise DefinitionError(f"{x} is not an integer")
        return table["even" if x.numerator % 2 == 0 else "odd"](x)
    return step


def branch_lemmas(defn: dict[str, Any], domain: str) -> list[str]:
    """What can be proved about each parity branch on its own, for every integer of the domain: whether it lowers
    the value, the parity of its output, and the two-step map when the output parity is fixed. Each statement is
    derived symbolically (n = 2k + r), never sampled."""
    var, k = sp.Symbol(defn["parameter"]), sp.Symbol("k", integer=True, nonnegative=True)
    low = {"positive_integer": 1, "nonnegative_integer": 0}.get(domain)
    out: list[str] = []
    forms: dict[str, sp.Expr] = {}
    for b in defn["branches"]:
        if b["condition"] not in ("even", "odd"):
            continue
        f = safe_parse_expr(b["expression"], local_dict={var.name: var})
        forms[b["condition"]] = f
        r = 0 if b["condition"] == "even" else 1
        on_class = sp.expand(f.subs(var, 2 * k + r))  # the branch on its residue class, k >= 0
        diff = sp.expand(on_class - (2 * k + r))
        shown = _pretty(sp.sstr(f))
        if low is not None and sp.Poly(diff, k).degree() <= 1:
            a, c = sp.Poly(diff, k).all_coeffs() if sp.Poly(diff, k).degree() == 1 else (sp.Integer(0), diff)
            k_min = max(0, -(-(low - r) // 2))  # smallest k with 2k + r >= low
            value_at_min = a * k_min + c
            if a <= 0 and value_at_min < 0:
                out.append(f"Proved: for every {b['condition']} {var} >= {2 * k_min + r} in the domain, {shown} < {var} "
                           f"(on {var} = 2k + {r}: {shown} - {var} = {_pretty(sp.sstr(diff))} < 0), so this rule strictly lowers the value.")
            elif a >= 0 and value_at_min > 0:
                out.append(f"Proved: for every {b['condition']} {var} in the domain, {shown} > {var} "
                           f"({shown} - {var} = {_pretty(sp.sstr(diff))} > 0 on {var} = 2k + {r}), so this rule raises the value.")
        if on_class.is_polynomial(k) and all(c.is_integer for c in sp.Poly(on_class, k).all_coeffs()):
            parities = {int(on_class.subs(k, j)) % 2 for j in (0, 1)}
            coeffs_even = all(int(c) % 2 == 0 for c in sp.Poly(on_class, k).all_coeffs()[:-1])
            if len(parities) == 1 and coeffs_even:
                parity = "even" if parities == {0} else "odd"
                out.append(f"Proved: for {b['condition']} {var} = 2k + {r}, {shown} = {_pretty(sp.sstr(on_class))}, which is "
                           f"always {parity}; so the next rule applied is the {parity} rule.")
                forms[f"{b['condition']}->{parity}"] = forms.get(parity, sp.nan)
    for b in ("even", "odd"):
        nxt = next((key.split("->")[1] for key in forms if key.startswith(f"{b}->")), None)
        if nxt and b in forms and nxt in forms:
            two = sp.simplify(forms[nxt].subs(var, forms[b]))
            if two != forms[b]:
                rel = sp.simplify(two - var)
                trend = "above" if (low is not None and rel.subs(var, max(low, 1)) > 0 and sp.Poly(rel, var).LC() >= 0) else "not always above"
                out.append(f"Consequently two consecutive steps from an {b} value give {_pretty(sp.sstr(two))}, "
                           f"which is {trend} the start: a single monotone argument cannot settle every orbit.")
    return out


def _run_reaches(task: dict[str, Any], defs: list[dict[str, Any]]) -> dict[str, Any]:
    defn = next(d for d in defs if d["name"] == task["function"])
    var, domain = task.get("variable") or defn["parameter"], task.get("domain") or defn.get("domain") or "positive_integer"
    target = Fraction(int(task["target"]))
    step = _compiled_step(defn)
    worst, worst_n, peak, peak_n, not_reached = -1, None, Fraction(0), None, []
    starts = [int(v) for v in domain_values(domain, REACH_LIMIT_N)]
    for n in starts:
        x, steps, seen = Fraction(n), 0, {Fraction(n)}
        while x != target and steps < REACH_MAX_STEPS:
            x = step(x)
            steps += 1
            if x > peak:
                peak, peak_n = x, n
            if x != target and x in seen:
                # A cycle that avoids the target: this start never reaches it, which disproves the claim exactly.
                cycle = [x]
                y = step(x)
                while y != x and len(cycle) < 1000:
                    cycle.append(y)
                    y = step(y)
                text_cycle = " -> ".join(str(v) for v in [*cycle, x])
                return {"status": "disproved", "counterexample": str(n), "cycle": [str(v) for v in cycle],
                        "detail": f"the orbit of {n} enters the cycle {text_cycle}, which does not contain {task['target']}",
                        "steps": [f"Starting at {var} = {n}, the orbit enters the cycle {text_cycle}.",
                                  f"The cycle does not contain {task['target']}, so {var} = {n} never reaches it."],
                        "text": f"False: {var} = {n} never reaches {task['target']} (cycle {text_cycle})."}
            seen.add(x)
        if x != target:
            not_reached.append(n)
        elif steps > worst:
            worst, worst_n = steps, n
    lemmas = branch_lemmas(defn, domain)
    reduction = (f"Reduction (well-ordering): if some {var} never reaches {task['target']}, take the least such {var}; "
                 f"every smaller value reaches {task['target']}, so this least counterexample's orbit never falls below "
                 f"it. It is therefore enough to prove that every {var} > {task['target']} eventually reaches a value "
                 f"smaller than {var}.") if domain in ("positive_integer", "nonnegative_integer") else ""
    evidence = (f"Checked exactly: every {var} from {starts[0]} to {starts[-1]} reaches {task['target']}; the longest "
                f"orbit starts at {worst_n} ({worst} steps), the largest value reached is {peak} (from {peak_n}).")
    if not_reached:
        evidence += f" Not reached within {REACH_MAX_STEPS} steps: {', '.join(map(str, not_reached[:10]))} (undecided, not counterexamples)."
    steps_out = [*lemmas, *([reduction] if reduction else []), evidence,
                 "Status: no proof follows from these facts and no counterexample was found; the claim is not settled here."]
    return {"status": "unresolved", "checked_up_to": starts[-1], "longest": {"start": worst_n, "steps": worst},
            "peak": {"value": str(peak), "start": peak_n}, "not_reached": not_reached[:50], "lemmas": lemmas,
            "reduction": reduction, "steps": steps_out,
            "text": f"Not settled: {evidence} This is evidence, not a proof."}


def _zero_function(task: dict[str, Any], defs: list[dict[str, Any]]) -> tuple[dict[str, Any], sp.Symbol, sp.Expr]:
    defn = next((d for d in defs if d["name"] == task["function"]), None)
    if defn is None or len(defn["branches"]) != 1 or defn["branches"][0].get("condition"):
        raise DefinitionError(f"{task['function']} is not a single-formula definition, so its zeros are not computed")
    var = sp.Symbol(defn["parameter"])
    expr = evaluate(parse_with_definitions(defn["branches"][0]["expression"], defs, {var.name: var}), defs)
    return defn, var, sp.expand(expr)


def _run_zeros(task: dict[str, Any], defs: list[dict[str, Any]]) -> dict[str, Any]:
    """All zeros of a single-formula definition over its domain. For a polynomial the list is complete exactly when
    the roots found, counted with multiplicity, number its degree (a nonzero polynomial of degree d has d complex
    roots with multiplicity). With a line Re(v) = c in the question, each zero's real part is compared with c and the
    zero set is tested for the reflection v -> 2c - v."""
    defn, var, expr = _zero_function(task, defs)
    domain = task.get("domain") or "unspecified"
    written = _pretty(defn["branches"][0]["expression"])
    steps = [f"{defn['name']}({var}) = {written}" + ("" if _pretty(sp.sstr(expr)) == written else f" = {_pretty(sp.sstr(expr))}")]
    if expr == 0:
        return {"status": "unresolved", "steps": steps, "text": f"{task['id']}: {defn['name']} is identically zero"}
    if not expr.is_polynomial(var):
        sset = sp.solveset(expr, var, domain=sp.S.Reals if domain in ("real", "rational") else sp.S.Complexes)
        if not isinstance(sset, sp.FiniteSet):
            return {"status": "unresolved", "steps": steps, "text": f"{task['id']}: the zero set is {sset}, not a finite list"}
        roots, degree, complete = {z: 1 for z in sset}, None, True
        steps.append(f"{defn['name']}({var}) = 0 has exactly the solutions {', '.join(_value_text(z) for z in sset)}")
    else:
        poly = sp.Poly(expr, var)
        degree = poly.degree()
        roots = sp.roots(poly)
        complete = sum(roots.values()) == degree
        factored = sp.factor(expr)
        if factored != expr:
            steps.append(f"{defn['name']}({var}) = {_pretty(sp.sstr(factored))}, and a product is zero exactly when a factor is")
        steps.append(f"degree {degree}; {sum(roots.values())} root(s) counted with multiplicity"
                     + (": all of them" if complete else f": only these were found in closed form, of {degree}"))
    zeros = sorted(roots, key=lambda z: (float(sp.re(z)), float(sp.im(z))))
    kept = [z for z in zeros if in_domain(z, domain) is not False]
    res: dict[str, Any] = {"status": "computed" if complete else "unresolved", "zeros": [_value_text(z) for z in kept],
                           "multiplicities": [int(roots[z]) for z in kept], "degree": degree, "complete": complete,
                           "excluded": [_value_text(z) for z in zeros if z not in kept]}
    listed = ", ".join(f"{var} = {_value_text(z)}" + (f" (multiplicity {roots[z]})" if roots[z] > 1 else "") for z in kept)
    text = f"{task['id']}: {listed}" if kept else f"{task['id']}: none in {domain_label(domain)}"
    if res["excluded"]:
        steps.append(f"outside {domain_label(domain)}: {', '.join(res['excluded'])}")
    if task.get("line") is not None and kept:
        c = _exact_value(str(task["line"]))
        on = [z for z in kept if sp.simplify(sp.re(z) - c) == 0]
        for z in kept:
            steps.append(f"Re({_value_text(z)}) = {_value_text(sp.re(z))}" + (" = " if z in on else " ≠ ") + f"{_value_text(c)}")
        mirrored = {sp.nsimplify(sp.expand(2 * c - z)) for z in kept}
        symmetric = mirrored == {sp.nsimplify(z) for z in kept}
        steps.append(f"the zero set is {'closed' if symmetric else 'not closed'} under {var} ↦ {_value_text(2 * c)} − {var}"
                     + (f" ({' ↔ '.join(_value_text(z) for z in kept)})" if symmetric and len(kept) == 2 else ""))
        res.update(line=_value_text(c), on_line=[_value_text(z) for z in on],
                   off_line=[_value_text(z) for z in kept if z not in on], reflection_symmetric=symmetric)
        where = ("all lie on" if len(on) == len(kept) else "none lies on" if not on else f"{len(on)} of {len(kept)} lie on")
        text += f"; {where} Re({var}) = {_value_text(c)}"
    res.update(steps=steps, text=text)
    return res


def run_structured(definitions: list[dict[str, Any]], tasks: list[dict[str, Any]]) -> dict[str, Any]:
    """Execute every task against the definitions. A task that cannot be carried out reports its reason; it never
    falls back to a different problem."""
    results = []
    for task in tasks[:_MAX_TASKS]:
        res: dict[str, Any] = {"id": task["id"], "op": task["op"]}
        try:
            if task["op"] == "evaluate":
                bindings = {k: safe_parse_expr(str(v)) for k, v in (task.get("bindings") or {}).items()}
                trace: list[dict[str, Any]] = []
                expr = parse_with_definitions(task["expression"], definitions, {k: sp.Symbol(k) for k in bindings})
                value = sp.simplify(evaluate(expr.xreplace({sp.Symbol(k): v for k, v in bindings.items()}), definitions, trace))
                res.update(value=_value_text(value), bindings={k: _value_text(v) for k, v in bindings.items()}, applications=trace)
                label = ", ".join(f"{k} = {v}" for k, v in res["bindings"].items())
                res["text"] = f"{task['id']}" + (f" ({label})" if label and task["id"].lower().startswith("case") else "") + f": {res['value']}" \
                    if bindings else f"{task['expression']} = {res['value']}"
                if task.get("factor"):
                    ft = factor_text(value)
                    if ft is not None:
                        res["factorization"], res["factors"] = ft[0], [str(p) for p in ft[1]]
                        res["text"] += f" = {ft[0]}"
                res["steps"] = evaluation_steps(task, definitions, value, trace)
            elif task["op"] == "orbit":
                res.update(_run_orbit(task, definitions))
            elif task["op"] == "reaches":
                res.update(_run_reaches(task, definitions))
            elif task["op"] == "claim":
                res.update(_run_claim(task, definitions))
            elif task["op"] == "zeros":
                res.update(_run_zeros(task, definitions))
            else:
                raise ValueError(f"unknown task operation {task['op']!r}")
            res["status"] = res.get("status", "computed")
        except DefinitionError as exc:
            # "g(0) is undefined: 0 is not in the domain of g" answers the question that was asked.
            status = "undefined" if task["op"] == "evaluate" else "error"
            msg = str(exc)
            res.update(status=status, error=msg, text=msg if msg.startswith(str(task['id'])) else f"{task['id']}: {msg}")
        results.append(res)
    return {"results": results, "text": "\n".join(r["text"] for r in results)}


def substitute_definitions(text: str) -> tuple[str, list[str]] | None:
    """The question with every application of a single-formula definition replaced by the formula ("the derivative
    of f(x)" with f(x) = x^2 + 1 -> "the derivative of (x**2 + 1)") and the definition statements blanked, so the other
    parsers can read the task. None when a definition has branches or the question defines nothing."""
    defs, spans, problems = parse_definitions(text)
    if not defs or problems or any(len(d["branches"]) != 1 or d["branches"][0]["condition"] not in ("", "otherwise") for d in defs):
        return None
    by_name = {d["name"]: d for d in defs}
    out = _mask(text, spans)
    out = re.sub(r"(?i)\b(?:let|define|suppose|consider|where|given)\b\s*(?:that\s+)?[,.;:]?", " ", out) if spans else out
    notes = []
    for _ in range(20):
        m = re.search(rf"(?<![\w.])({'|'.join(map(re.escape, by_name))})\s*\(", out)
        if not m:
            break
        depth, i = 1, m.end()
        while i < len(out) and depth:
            depth += {"(": 1, ")": -1}.get(out[i], 0)
            i += 1
        if depth:
            return None
        defn = by_name[m.group(1)]
        x = sp.Symbol(defn["parameter"])
        try:
            arg = safe_parse_expr(out[m.end(): i - 1])
            body = safe_parse_expr(defn["branches"][0]["expression"], local_dict={x.name: x}).subs(x, arg)
        except Exception:  # noqa: BLE001
            return None
        out = out[: m.start()] + f"({sp.sstr(body)})" + out[i:]
        notes.append(f"substituted the definition {defn['name']}({defn['parameter']}) = {_pretty(defn['branches'][0]['expression'])}")
    return re.sub(r"[ \t]{2,}", " ", out).strip(), list(dict.fromkeys(notes))


# Independent checks -----------------------------------------------------------------------------------------------------

def misread_functions(text: str, expressions: list[str]) -> list[str]:
    """Names the question defines as functions that a parse does not evaluate through their definition: used as plain
    symbols (T(n) read as T*n) or left as an unknown function application handed to a generic solver."""
    defs, _, _ = parse_definitions(text)
    names = {d["name"] for d in defs}
    if not names:
        return []
    bad = set()
    for e in expressions:
        if not e:
            continue
        for name in names:
            if re.search(rf"(?<![\w.]){re.escape(name)}(?!\w)", e):
                bad.add(name)
    return sorted(bad)


def _exact_value(text: str) -> sp.Expr:
    return safe_parse_expr(str(text))


def _second_route(expr_text: str, defs: list[dict[str, Any]], bindings: dict[str, str]) -> Fraction | None:
    """Recompute a value with rational arithmetic on the branch formulas, application by application, without SymPy's
    simplification of the whole expression. None when the expression is not rational-valued."""
    by_name = {d["name"]: d for d in defs}
    local = {k: sp.Symbol(k) for k in bindings}
    expr = parse_with_definitions(expr_text, defs, local).xreplace({sp.Symbol(k): sp.Rational(v) if re.fullmatch(_NUMBER, str(v)) else safe_parse_expr(str(v)) for k, v in bindings.items()})

    def walk(e: sp.Expr) -> Fraction:
        if isinstance(e, AppliedUndef) and e.func.__name__ in by_name:
            arg = walk(e.args[0])
            defn = by_name[e.func.__name__]
            val = sp.Rational(arg.numerator, arg.denominator)
            if in_domain(val, defn.get("domain") or "unspecified") is False:
                raise DefinitionError(f"{val} is outside {defn['name']} domain")
            branch = None
            for b in defn["branches"]:
                if b["condition"] != "otherwise" and condition_holds(b["condition"], defn["parameter"], val):
                    branch = b
                    break
            branch = branch or next((b for b in defn["branches"] if b["condition"] == "otherwise"), None)
            if branch is None:
                raise DefinitionError("no branch")
            inner = safe_parse_expr(branch["expression"], local_dict={defn["parameter"]: sp.Symbol(defn["parameter"])})
            return walk(inner.xreplace({sp.Symbol(defn["parameter"]): val}))
        if e.is_Rational:
            return Fraction(int(e.p), int(e.q))
        if isinstance(e, sp.Add):
            return sum((walk(a) for a in e.args), Fraction(0))
        if isinstance(e, sp.Mul):
            out = Fraction(1)
            for a in e.args:
                out *= walk(a)
            return out
        if isinstance(e, sp.Pow) and e.exp.is_Integer:
            base = walk(e.base)
            k = int(e.exp)
            if abs(k) > 4096:
                raise ValueError("power too large")
            return base ** k
        raise ValueError(f"not rational arithmetic: {e}")

    try:
        return walk(expr)
    except (ValueError, ZeroDivisionError, DefinitionError):
        return None


# Independent reading of domain restrictions for the domain check: plain patterns over each sentence that mentions the
# function, not the definition parser. A payload that lost "positive integers" fails against this reading.
_RESTRICTIONS = (
    ("positive_integer", re.compile(r"[{(]\s*1\s*,\s*2\b|positive[\s-]+integer|natural[\s-]+number|ℕ(?!\s*(?:_?\{?0|₀|∪))|ℤ\s*(?:\+|⁺)", re.I)),
    ("nonnegative_integer", re.compile(r"[{(]\s*0\s*,\s*1\b|non[\s-]?negative[\s-]+integer|whole[\s-]+number|ℕ\s*(?:_?\{?0|₀|∪)", re.I)),
    ("integer", re.compile(r"\bintegers?\b|ℤ", re.I)),
    ("rational", re.compile(r"\brationals?\b|ℚ", re.I)),
    ("real", re.compile(r"\breals?\b|\breal\s+numbers?\b|ℝ", re.I)),
)


def stated_domains(question: str, names: set[str]) -> dict[str, str]:
    """The narrowest domain the question states for each function, read sentence by sentence or from explicit declarations."""
    out: dict[str, str] = {}
    q = question or ""
    for name in names:
        decl = _declared_domain(q, name)
        if decl:
            out[name] = decl

    for sentence in re.split(r"(?<=[.?!;])\s+|\n+", q):
        clean = re.sub(r"(?i)\bfor\s+(?:every|all|each|any)\b[^,.;]*", " ", sentence)  # a claim's quantifier
        for name in names:
            n = re.escape(name)
            if not re.search(rf"(?<![\w.]){n}\s*(?:\(\s*[A-Za-z]\s*\)\s*=|:|\s+(?:is|be)\s+(?:defined|a\s+function))|\bdomain\s+of\s+{n}\b|\b{n}\s+be\b|\b{n}\s+(?:has|have|with)\b", clean):
                continue
            dom = domain_from_words(clean)
            if dom:
                curr = out.get(name, "unspecified")
                if is_proper_subdomain(dom, curr):
                    out[name] = dom
                continue
            for dom_pat, rx in _RESTRICTIONS:
                if rx.search(clean):
                    curr = out.get(name, "unspecified")
                    if is_proper_subdomain(dom_pat, curr):
                        out[name] = dom_pat
                    break
    return out


def _denominator_vanishes(text: str, variable: str, witness: str) -> bool:
    """Does a denominator written in the text evaluate to zero at the witness? (Direct substitution, a different route
    from singular_points, which solves for the zeros.)"""
    value = _exact_value(witness)
    for m in re.finditer(r"/\s*(\((?:[^()]|\([^()]*\))*\)|[A-Za-z0-9_.^]+)", text):
        try:
            den = safe_parse_expr(m.group(1), local_dict={variable: sp.Symbol(variable)})
        except Exception:  # noqa: BLE001
            continue
        if sp.simplify(den.subs(sp.Symbol(variable), value)) == 0:
            return True
    return False


def check_structured(params: dict[str, Any], data: dict[str, Any], question: str = "") -> list[tuple[str, bool | None, int, str]]:
    """Four separate checks of a structured result: (name, passed, level, detail). With the question, the domain check
    also re-reads each function's stated domain from the question itself (stated_domains), so a payload that lost a
    restriction cannot pass by being checked against itself."""
    defs, tasks = params.get("definitions") or [], params.get("tasks") or []
    results = {r["id"]: r for r in data.get("results") or []}
    out: list[tuple[str, bool | None, int, str]] = []

    from .correspondence import is_tautology_claim
    tautologies = [str(t.get("id") or t) for t in tasks if isinstance(t, dict) and is_tautology_claim(t)]
    out.append(("validity: no trivial tautological claims", not tautologies, 1,
                f"trivial tautology task(s) detected: {', '.join(tautologies)}" if tautologies else "all tasks are non-tautological"))

    names = {d["name"] for d in defs}
    misread = sorted({n for t in tasks for key in ("expression", "lhs", "rhs") if t.get(key)
                      for n in names if re.search(rf"(?<![\w.]){re.escape(n)}(?!\w)(?!\s*\()", t[key])})
    out.append(("interpretation: defined functions are applied, never multiplied", not misread, 1,
                f"{', '.join(misread)} used as a number" if misread else f"{len(names)} definition(s) kept as functions"))

    domain_bad: list[str] = []
    stated = stated_domains(question, names) if question else {}
    for d in defs:
        want = stated.get(d["name"])
        used = d.get("domain") or "unspecified"
        if want and (is_proper_subdomain(want, used) or domain_rank(want) < domain_rank(used)):
            domain_bad.append(f"the question restricts {d['name']} to {domain_label(want)}; the computation used "
                              f"{domain_label(used) if used != 'unspecified' else 'no restriction'}")
    for t in tasks:
        r = results.get(t["id"]) or {}
        if r.get("status") == "undefined":
            continue
        for app in r.get("applications") or []:
            want = stated.get(app.get("function", ""))
            if want and not app.get("symbolic") and in_domain(_exact_value(app["argument"]), want) is False:
                domain_bad.append(f"{app['function']}({app['argument']}) was evaluated although {app['argument']} is not in "
                                  f"{domain_label(want)}")
    for t in tasks:
        r = results.get(t["id"]) or {}
        for app in r.get("applications") or []:
            if app.get("symbolic"):
                continue
            defn = next((d for d in defs if d["name"] == app["function"]), None)
            if defn is None:
                domain_bad.append(f"{app['function']} is not defined")
                continue
            arg = _exact_value(app["argument"])
            if in_domain(arg, defn.get("domain") or "unspecified") is False:
                domain_bad.append(f"{app['function']}({arg}) outside {domain_label(defn['domain'])}")
            holds = [i for i, b in enumerate(defn["branches"]) if b["condition"] not in ("otherwise",) and condition_holds(b["condition"], defn["parameter"], arg)]
            expected = holds[0] if holds else next((i for i, b in enumerate(defn["branches"]) if b["condition"] == "otherwise"), None)
            if len(holds) > 1 or expected != app["branch"]:
                domain_bad.append(f"{app['function']}({arg}) used branch {app['branch']}, expected {expected}")
        if t["op"] == "evaluate" and r.get("status") == "undefined":
            try:
                again = evaluate(parse_with_definitions(t["expression"], defs, {k: sp.Symbol(k) for k in t.get("bindings") or {}})
                                 .xreplace({sp.Symbol(k): _exact_value(v) for k, v in (t.get("bindings") or {}).items()}), defs)
                domain_bad.append(f"{t['id']} was reported undefined but evaluates to {again}")
            except DefinitionError:
                pass  # confirmed: an argument lies outside the domain or no branch applies
        if t["op"] == "claim" and r.get("counterexample") is not None:
            w = _exact_value(r["counterexample"])
            claim_dom = t.get("domain") or "unspecified"
            if in_domain(w, claim_dom) is False or not all(
                    condition_holds(c, t["variable"], w) is True for c in t.get("conditions") or []):
                domain_bad.append(f"witness {t['variable']} = {w} is outside {domain_label(claim_dom)}")
            claim_txt = str(t.get("lhs", "")) + " " + str(t.get("rhs", "")) + " " + str(t.get("expression", ""))
            for d in defs:
                if re.search(rf"(?<![\w.]){re.escape(d['name'])}\s*\(\s*{re.escape(t['variable'])}\s*\)", claim_txt):
                    fn_dom = d.get("domain") or "unspecified"
                    if in_domain(w, fn_dom) is False:
                        domain_bad.append(f"witness {t['variable']} = {w} is outside domain of {d['name']} ({domain_label(fn_dom)})")
                    want_fn = stated.get(d["name"])
                    if want_fn and in_domain(w, want_fn) is False:
                        domain_bad.append(f"witness {t['variable']} = {w} is outside question domain of {d['name']} ({domain_label(want_fn)})")
            if question:
                qm = re.search(rf"\bfor\s+(?:every|all|each|any)\s+([^.?!;\n]+?\b{re.escape(t['variable'])}\b[^.?!;\n]*)", question, re.I)
                if qm:
                    q_dom = domain_from_words(qm.group(1))
                    if q_dom and in_domain(w, q_dom) is False:
                        domain_bad.append(f"witness {t['variable']} = {w} violates question condition {qm.group(0).strip()}")
        if t["op"] == "orbit":
            defn = next((d for d in defs if d["name"] == t["function"]), None)
            if defn is not None:
                for v in r.get("sequence") or []:
                    if in_domain(_exact_value(v), defn.get("domain") or "unspecified") is False:
                        domain_bad.append(f"orbit value {v} outside {domain_label(defn['domain'])}")
    out.append(("domain: arguments and witnesses lie in the stated domain; one branch applies each time", not domain_bad, 1,
                "; ".join(domain_bad)[:400]))

    comp_bad: list[str] = []
    checked = 0
    for t in tasks:
        r = results.get(t["id"]) or {}
        if r.get("status") in ("error", "undefined"):
            continue
        if t["op"] == "evaluate":
            again = _second_route(t["expression"], defs, {k: str(v) for k, v in (t.get("bindings") or {}).items()})
            if again is not None:
                checked += 1
                if Fraction(str(r.get("value"))) != again if re.fullmatch(_NUMBER, str(r.get("value"))) else True:
                    comp_bad.append(f"{t['id']}: recomputed {again}, reported {r.get('value')}")
            if r.get("factors"):
                prod = math.prod(int(p) for p in r["factors"])
                if abs(prod) != abs(int(_exact_value(r["value"]))) or not all(sp.isprime(int(p)) for p in r["factors"]):
                    comp_bad.append(f"{t['id']}: factors {r['factors']} do not multiply to {r['value']} as primes")
        elif t["op"] == "orbit":
            seq = r.get("sequence") or []
            for a, b in zip(seq, seq[1:]):
                again = _second_route(f"{t['function']}({a})", defs, {})
                checked += 1
                if again is None or Fraction(b) != again:
                    comp_bad.append(f"{t['function']}({a}) = {again}, orbit shows {b}")
            if t.get("mode") == "cycle" and r.get("closed") and seq and seq[-1] not in seq[:-1]:
                comp_bad.append("the reported cycle does not close")
        elif t["op"] == "reaches":
            # Recomputed through the definition (SymPy, branch by branch), not the compiled closures that produced it.
            defn = next((d for d in defs if d["name"] == t["function"]), None)
            if defn is None:
                continue
            target = _exact_value(t["target"])
            if r.get("status") == "disproved" and r.get("cycle"):
                cyc = [_exact_value(v) for v in r["cycle"]]
                ok = target not in cyc and all(apply_definition(defn, a)[0] == b for a, b in zip(cyc, [*cyc[1:], cyc[0]]))
                x, steps = _exact_value(r["counterexample"]), 0
                while x not in cyc and steps < REACH_MAX_STEPS:
                    x, steps = apply_definition(defn, x)[0], steps + 1
                checked += 1
                if not ok or x not in cyc:
                    comp_bad.append(f"{t['id']}: the reported cycle does not recompute")
            elif (r.get("longest") or {}).get("start") is not None:
                x, steps = _exact_value(str(r["longest"]["start"])), 0
                while x != target and steps < REACH_MAX_STEPS:
                    x, steps = apply_definition(defn, x)[0], steps + 1
                checked += 1
                if steps != r["longest"]["steps"]:
                    comp_bad.append(f"{t['id']}: orbit of {r['longest']['start']} takes {steps} steps, reported {r['longest']['steps']}")
        elif t["op"] == "claim":
            if r.get("status") == "disproved" and "undefined" in str(r.get("detail")):
                checked += 1
                if not any(_denominator_vanishes(t[k], t["variable"], r["counterexample"]) for k in ("lhs", "rhs", "expression") if t.get(k)):
                    comp_bad.append(f"{t['id']}: no written denominator vanishes at {t['variable']} = {r['counterexample']}")
            elif r.get("status") == "disproved" and r.get("counterexample") is not None:
                checked += 1
                w = r["counterexample"]
                w_val = _exact_value(w)
                claim_dom = t.get("domain") or "unspecified"
                if in_domain(w_val, claim_dom) is False:
                    comp_bad.append(f"{t['id']}: counterexample {t['variable']} = {w} lies outside domain {domain_label(claim_dom)}")
                elif t.get("predicate"):
                    val = _second_route(t["expression"], defs, {t["variable"]: w})
                    div = _second_route(t["divisor"], defs, {t["variable"]: w}) if t.get("divisor") else None
                    still = None if val is None else _predicate(t["predicate"], sp.Rational(val.numerator, val.denominator),
                                                                None if div is None else sp.Rational(div.numerator, div.denominator))
                    if still is not False:
                        comp_bad.append(f"{t['id']}: the counterexample {t['variable']} = {w} does not refute the claim on recomputation")
                else:
                    lv = _second_route(t["lhs"], defs, {t["variable"]: w})
                    rv = _second_route(t["rhs"], defs, {t["variable"]: w})
                    still = None if lv is None or rv is None else bool(_REL_OPS[t["relation"]](sp.Rational(lv.numerator, lv.denominator), sp.Rational(rv.numerator, rv.denominator)))
                    if still is not False:
                        comp_bad.append(f"{t['id']}: the counterexample {t['variable']} = {w} does not refute the claim on recomputation")
            elif r.get("status") == "proved" and t.get("predicate"):
                for v in [v for v in domain_values(t.get("domain") or "integer", 60) if all(
                        condition_holds(c, t["variable"], v) is True for c in t.get("conditions") or [])][:30]:
                    val = _second_route(t["expression"], defs, {t["variable"]: str(v)})
                    div = _second_route(t["divisor"], defs, {t["variable"]: str(v)}) if t.get("divisor") else None
                    if val is None:
                        continue
                    checked += 1
                    if _predicate(t["predicate"], sp.Rational(val.numerator, val.denominator),
                                  None if div is None else sp.Rational(div.numerator, div.denominator)) is not True:
                        comp_bad.append(f"{t['id']}: fails at {t['variable']} = {v}")
                        break
            elif r.get("status") == "proved" and t.get("relation") == "=":
                pts = [v for v in domain_values(t.get("domain") if is_integer_domain(t.get("domain", "")) else "real", 40)
                       if in_domain(v, t.get("domain") or "unspecified") is not False and all(condition_holds(c, t["variable"], v) is True for c in t.get("conditions") or [])]
                for v in pts[:12]:
                    lv = _second_route(t["lhs"], defs, {t["variable"]: str(v)})
                    rv = _second_route(t["rhs"], defs, {t["variable"]: str(v)})
                    if lv is None or rv is None:
                        continue
                    checked += 1
                    if lv != rv:
                        comp_bad.append(f"{t['id']}: differs at {t['variable']} = {v}")
                        break
            elif r.get("status") == "proved" and t.get("relation") in ("<", "<=", ">", ">=", "!="):
                pts = [v for v in domain_values(t.get("domain") if is_integer_domain(t.get("domain", "")) else "real", 40)
                       if in_domain(v, t.get("domain") or "unspecified") is not False and all(condition_holds(c, t["variable"], v) is True for c in t.get("conditions") or [])]
                for v in pts[:12]:
                    lv = _second_route(t["lhs"], defs, {t["variable"]: str(v)})
                    rv = _second_route(t["rhs"], defs, {t["variable"]: str(v)})
                    if lv is None or rv is None:
                        continue
                    checked += 1
                    rel_holds = bool(_REL_OPS[t["relation"]](sp.Rational(lv.numerator, lv.denominator), sp.Rational(rv.numerator, rv.denominator)))
                    if not rel_holds:
                        comp_bad.append(f"{t['id']}: relation {t['relation']} fails at {t['variable']} = {v}")
                        break
    for t in tasks:
        r = results.get(t["id"]) or {}
        if t["op"] != "zeros" or r.get("status") == "error":
            continue
        # Independent of how the zeros were found: each reported zero is substituted back, and for a polynomial the
        # leading coefficient times prod (v - z)^m must rebuild the function exactly (no zero missing or invented).
        try:
            _defn, var, expr = _zero_function(t, defs)
        except DefinitionError:
            continue
        zeros = [_exact_value(z) for z in r.get("zeros") or []]
        mults = r.get("multiplicities") or [1] * len(zeros)
        for z in zeros:
            checked += 1
            if sp.simplify(expr.subs(var, z)) != 0:
                comp_bad.append(f"{t['id']}: {var} = {z} is not a zero")
        if r.get("complete") and expr.is_polynomial(var) and not r.get("excluded"):
            checked += 1
            poly = sp.Poly(expr, var)
            rebuilt = poly.LC() * sp.prod([(var - z) ** int(m) for z, m in zip(zeros, mults, strict=False)])
            if sp.expand(rebuilt - expr) != 0:
                comp_bad.append(f"{t['id']}: the reported zeros do not rebuild {t['function']} (a zero is missing or wrong)")
        if r.get("line") is not None:
            c = _exact_value(str(r["line"]))
            on = {str(_exact_value(z)) for z in r.get("on_line") or []}
            for z in zeros:
                checked += 1
                if (sp.simplify(sp.re(z) - c) == 0) != (str(z) in on):
                    comp_bad.append(f"{t['id']}: Re({z}) compared wrongly with {c}")
    out.append(("computation: every value recomputed by exact rational arithmetic", (not comp_bad) if checked else None, 2,
                "; ".join(comp_bad)[:400] if comp_bad else f"{checked} recomputation(s) agree"))

    missing = [t["id"] for t in tasks if t["id"] not in results or results[t["id"]].get("status") == "error"]  # "undefined" is an answer
    out.append(("coverage: every requested item has a result", not missing, 1,
                ("no result for " + ", ".join(missing)) if missing else f"{len(tasks)} item(s) answered"))
    return out


__all__ = [
    "CLAIM_SEARCH_LIMIT",
    "DOMAINS",
    "DefinitionError",
    "apply_definition",
    "axiom_structured",
    "check_structured",
    "domain_from_words",
    "domain_label",
    "domain_rank",
    "domain_values",
    "evaluate",
    "factor_text",
    "in_domain",
    "is_integer_domain",
    "is_proper_subdomain",
    "is_valid_domain",
    "misread_functions",
    "parse_definitions",
    "parse_structured",
    "parse_with_definitions",
    "run_structured",
    "singular_points",
]
