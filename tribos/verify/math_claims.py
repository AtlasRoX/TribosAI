"""Deterministic audit of the mathematical statements in an answer.

The writer model produces the prose, derivations and tables; the tools produce the numbers. Nothing guaranteed that
the two agree, so a correct tool result could be restated wrongly (a swapped derivative, an amplitude off by a factor
of two, a phase with the wrong sign) and still pass every other check. This module reads the final answer itself:

1. Extraction. Display and inline LaTeX ($...$, $$...$$, \\[...\\], \\(...\\)) and markdown table rows are split into
   relation chains "T0 = T1 ~ T2 ..." (separators: \\quad, commas and "\\Rightarrow" at depth 0, line breaks).
2. Bindings, in document order. The question's stated values (m = 2 kg, ...) are bound first. A chain whose first term
   is a symbol or a function application f(t) defines it (bound to the last term, the stated result); a restatement
   of a bound name is a check against the earlier statement. Derivatives (\\dot x, x', dx/dt) are never bound: they
   are always computed from the bound function, so a stated derivative is checked, not trusted.
3. Checks per relation: two numbers are compared with the tolerance of the printed precision; two expressions in the
   same free symbols are compared by sampling (an identity); expressions in different symbols are an equation, held
   until its unknowns are bound by a later statement (e.g. "A + 5/13 = 0.1" is checked once "A = -37/130" is stated)
   and left inconclusive if they never are. An identity that fails without referring to anything bound is treated as
   an equation (it may be one to solve), so a check never fails on notation it cannot interpret.
4. Cross-checks against the run's record: a stated value of a quantity a tool computed (same symbol, and the
   statement names the quantity) must match it; the answer's final solution must match a verified solution and
   satisfy the stated equation and initial conditions.
5. Table rows of computed numbers are grounded in tool outputs (each printed value must round from a tool value).

Outcomes per claim: passed | failed | inconclusive | unsupported (a number with no source). Definitions (notation the
answer introduces) are recorded but are not claims. Hypothetical statements ("if c = 0 ...") are skipped.

The checks are independent of how the answer was produced: they re-evaluate the answer's own statements with the
question's values and the tools' structured outputs, never the writer's other prose. A failed claim names the value
the checker computed, which the bounded correction loop sends back to the writer.
"""

from __future__ import annotations

import bisect
import logging
import math
import random
import re
from collections.abc import Iterable
from dataclasses import dataclass, field, replace
from typing import Any

import sympy as sp
from sympy.core.function import AppliedUndef

from .latex_math import (
    INEQUALITIES,
    RELATIONS,
    SEPARATORS,
    ParseContext,
    Tok,
    Unsupported,
    is_unit_word,
    parse_tokens,
    split_deriv,
    tokenize,
)
from .result_record import ResultRecord, canonical_name

logger = logging.getLogger(__name__)

PASSED, FAILED, INCONCLUSIVE, UNSUPPORTED, DEFINITION = "passed", "failed", "inconclusive", "unsupported", "definition"
MAX_STATEMENTS = 400
MAX_TOOL_NUMBERS = 50_000

_CODE_RE = re.compile(r"```.*?```|`[^`\n]*`", re.S)
_SEG_RE = re.compile(
    r"\$\$(?P<d1>.+?)\$\$|\\\[(?P<d2>.+?)\\\]|\\\((?P<i1>.+?)\\\)|(?<![\\$\w])\$(?!\s)(?P<i2>[^$\n]+?)(?<!\s)\$(?!\w)",
    re.S,
)
_HEADING_RE = re.compile(r"^\s{0,3}(?:#{1,6}\s+(.+?)\s*#*\s*$|\*\*(.+?)\*\*\s*$)", re.M)
# A statement about another case than the one solved is not a claim about this problem.
_CONDITIONAL_RE = re.compile(
    r"\b(?:if|suppose|assum\w*|in the limit|limiting case|for example|e\.g\.|would|hypothetical\w*|undamped case|"
    r"without (?:damping|forcing)|general(?:ly)?|in general|for any|for all|typically|standard form|ansatz|seek|"
    r"try|guess)\b",
    re.I,
)
# A value given for a reference condition right before the math ("below resonance ($r = 1$)", "critical damping
# ($\zeta = 1$)", "when $t = 0$"): not a claim about the solved system. Only the few words just before count.
_REFERENCE_CUE_RE = re.compile(r"\b(?:resonan\w*|critical\w*|threshold|when|whenever|near|limit\w*)\b[^$]{0,6}$", re.I)
_NUM_CELL_RE = re.compile(
    r"^\s*\$?\s*(?P<sign>[-−–+]?)\s*(?P<mant>\d+(?:\.\d+)?)\s*(?:(?:\\times|×|x|\\cdot|·)\s*10\s*\^?\s*\{?\s*(?P<exp1>[-−–+]?\d+)\s*\}?"
    r"|[eE](?P<exp2>[-+−]?\d+))?\s*\$?\s*(?P<unit>[A-Za-z°/·^\-\s0-9]*)$"
)
_SUP = str.maketrans("⁰¹²³⁴⁵⁶⁷⁸⁹⁻", "0123456789-")


@dataclass
class Link:
    left: str
    right: str
    relation: str
    status: str
    detail: str = ""
    source: str = "answer"


@dataclass
class MathClaim:
    claim_id: str
    text: str
    context: str
    kind: str  # relation | derivative | table_row | condition | grounding | definition
    status: str
    links: list[Link] = field(default_factory=list)
    detail: str = ""
    defines: str = ""
    position: int = 0
    source_text: str = ""  # the answer text the statement was read from (segment or table row)
    lead: str = ""  # the prose just before it ("... steady-state amplitude"), which names the quantity

    def to_dict(self) -> dict[str, Any]:
        return {
            "claim_id": self.claim_id, "text": self.text, "context": self.context, "kind": self.kind,
            "status": self.status, "detail": self.detail, "defines": self.defines, "source_text": self.source_text[:400],
            "links": [{"left": lk.left, "right": lk.right, "relation": lk.relation, "status": lk.status,
                       "detail": lk.detail, "source": lk.source} for lk in self.links],
        }


@dataclass
class MathAudit:
    claims: list[MathClaim] = field(default_factory=list)
    definitions: list[MathClaim] = field(default_factory=list)
    record_revision: str = ""
    variable: str = "t"

    def counts(self) -> dict[str, int]:
        out = {PASSED: 0, FAILED: 0, INCONCLUSIVE: 0, UNSUPPORTED: 0}
        for c in self.claims:
            out[c.status] = out.get(c.status, 0) + 1
        out["extracted"] = len(self.claims)
        out["evaluated"] = out[PASSED] + out[FAILED]
        return out

    @property
    def failed(self) -> list[MathClaim]:
        return [c for c in self.claims if c.status == FAILED]

    def to_dict(self) -> dict[str, Any]:
        return {"counts": self.counts(), "variable": self.variable, "record_revision": self.record_revision,
                "claims": [c.to_dict() for c in self.claims][:200],
                "definitions": [d.to_dict() for d in self.definitions][:60]}


# -- extraction ---------------------------------------------------------------------------------------------------------
@dataclass
class _Statement:
    tokens: list[Tok]
    text: str
    context: str
    position: int
    kind: str = "relation"  # relation | table_row
    source: str = ""
    lead: str = ""


def _heading_before(md: str, pos: int) -> str:
    last = ""
    for m in _HEADING_RE.finditer(md, 0, pos):
        last = (m.group(1) or m.group(2) or "").strip()
    return last[:120]


def _prefix(md: str, pos: int) -> str:
    start = max(md.rfind("\n\n", 0, pos), md.rfind(". ", 0, pos), pos - 160, 0)
    return md[start:pos]


def _depth_split(tokens: list[Tok], is_sep: Any) -> list[list[Tok]]:
    out: list[list[Tok]] = [[]]
    depth = 0
    for tok in tokens:
        if tok.kind == "sym" and tok.value in ("(", "[", "{"):
            depth += 1
        elif tok.kind == "sym" and tok.value in (")", "]", "}"):
            depth = max(0, depth - 1)
        if depth == 0 and is_sep(tok):
            out.append([])
            continue
        out[-1].append(tok)
    return [part for part in out if part]


def _join_continuations(tokens: list[Tok]) -> list[Tok]:
    """Lines of an aligned block that carry no relation of their own continue the previous line ("x(t) = {}& (a \\\\
    &\\quad - b) e^{-3t/4} \\\\ &\\quad + c"): they are joined to it, and the alignment spacing after "&" is dropped, so
    a long expression written over several lines is read as one statement. Empty groups "{}" are dropped."""
    lines: list[list[Tok]] = [[]]
    for tok in tokens:
        if tok.kind == "sym" and tok.value == "\\\\":
            lines.append([])
        else:
            lines[-1].append(tok)
    cleaned: list[list[Tok]] = []
    for line in lines:
        out: list[Tok] = []
        i = 0
        while i < len(line):
            tok = line[i]
            if tok.kind == "sym" and tok.value == "{" and i + 1 < len(line) and line[i + 1].kind == "sym" and line[i + 1].value == "}":
                i += 2
                continue
            if tok.kind == "sym" and tok.value == "&":
                i += 1
                while i < len(line) and line[i].kind == "cmd" and line[i].value in ("quad", "qquad"):
                    i += 1
                continue
            out.append(tok)
            i += 1
        cleaned.append(out)

    def has_relation(line: list[Tok]) -> bool:
        depth = 0
        for tok in line:
            if tok.kind == "sym" and tok.value in ("(", "[", "{"):
                depth += 1
            elif tok.kind == "sym" and tok.value in (")", "]", "}"):
                depth -= 1
            elif depth == 0 and ((tok.kind == "sym" and tok.value == "=") or (tok.kind == "cmd" and tok.value in RELATIONS)):
                return True
        return False

    merged: list[list[Tok]] = []
    for line in cleaned:
        if merged and line and not has_relation(line):
            merged[-1].extend(line)
        elif line:
            merged.append(line)
    out_tokens: list[Tok] = []
    for k, line in enumerate(merged):
        if k:
            out_tokens.append(Tok("sym", "\\\\"))
        out_tokens.extend(line)
    return out_tokens


def _is_separator(tok: Tok) -> bool:
    if tok.kind == "sym" and tok.value in (",", ";", "\\\\"):
        return True
    if tok.kind == "cmd" and tok.value in SEPARATORS:
        return True
    if tok.kind == "word":
        w = tok.value.strip()
        return bool(w) and not is_unit_word(w) and not re.fullmatch(r"[A-Za-z]|e|d|atan2|arctan2|sgn|sign|Re|Im", w)
    return False


def _clean_tokens(tokens: list[Tok]) -> list[Tok] | None:
    """Drop alignment marks and environment names; None for content that is never checkable (matrices, cases)."""
    out: list[Tok] = []
    i = 0
    while i < len(tokens):
        tok = tokens[i]
        if tok.kind == "cmd" and tok.value in ("begin", "end"):
            # \begin{aligned}: the environment name is a braced group of letters.
            if i + 1 < len(tokens) and tokens[i + 1].kind == "sym" and tokens[i + 1].value == "{":
                j = i + 2
                name = ""
                while j < len(tokens) and not (tokens[j].kind == "sym" and tokens[j].value == "}"):
                    name += tokens[j].value
                    j += 1
                if name.rstrip("*") in ("pmatrix", "bmatrix", "matrix", "vmatrix", "cases", "array"):
                    return None
                i = j + 1
                continue
        if tok.kind == "sym" and tok.value == "&":
            i += 1
            continue
        out.append(tok)
        i += 1
    while out and out[-1].kind == "sym" and out[-1].value in (".", ",", ";", ":"):
        out.pop()
    return out


def _split_relations(tokens: list[Tok]) -> tuple[list[list[Tok]], list[str]] | None:
    """Terms and the relations between them; None when the statement is an inequality or uses +-."""
    terms: list[list[Tok]] = [[]]
    rels: list[str] = []
    depth = 0
    for tok in tokens:
        if tok.kind == "sym" and tok.value in ("(", "[", "{"):
            depth += 1
        elif tok.kind == "sym" and tok.value in (")", "]", "}"):
            depth = max(0, depth - 1)
        if depth == 0:
            rel = None
            if tok.kind == "sym" and tok.value == "=":
                rel = "eq"
            elif tok.kind == "cmd" and tok.value in RELATIONS:
                rel = RELATIONS[tok.value]
            elif (tok.kind == "sym" and tok.value in INEQUALITIES) or (tok.kind == "cmd" and tok.value in INEQUALITIES):
                return None
            if rel is not None:
                rels.append(rel)
                terms.append([])
                continue
        if tok.kind == "cmd" and tok.value in ("pm", "mp", "cdots", "ldots", "dots", "lim", "to"):
            return None
        terms[-1].append(tok)
    if any(not t for t in terms):
        return None
    return terms, rels


def _strip_unit(term: list[Tok]) -> tuple[list[Tok], str]:
    """A trailing unit ("0.1\\,\\mathrm{m}", "5 rad/s", "33.7^\\circ") is removed from a term."""
    unit = ""
    toks = list(term)
    # A trailing conversion in parentheses ("0.588003 rad (33.690°)", "(about 0.46 m)") is a restatement, not a factor.
    if toks and toks[-1].kind == "sym" and toks[-1].value == ")":
        depth, k = 0, len(toks) - 1
        while k >= 0:
            if toks[k].kind == "sym" and toks[k].value == ")":
                depth += 1
            elif toks[k].kind == "sym" and toks[k].value == "(":
                depth -= 1
                if depth == 0:
                    break
            k -= 1
        inner = toks[k + 1:-1] if k > 0 else []
        if inner and inner[0].kind == "num" and any(
                (t.kind == "cmd" and t.value == "circ") or (t.kind == "word" and is_unit_word(t.value)) for t in inner):
            toks = toks[:k]
    while toks and toks[-1].kind == "word" and is_unit_word(toks[-1].value):
        unit = toks.pop().value.strip() + (" " + unit if unit else "")
    if len(toks) >= 2 and toks[-1].kind == "cmd" and toks[-1].value == "circ" and toks[-2].kind == "sym" and toks[-2].value == "^":
        toks = toks[:-2]
        unit = "deg"
    elif toks and toks[-1].kind == "sym" and toks[-1].value == "°":
        toks = toks[:-1]
        unit = "deg"
    # A number followed only by letters forming a unit: "0.1 m", "2 kg", "4 rad/s".
    num_at = next((k for k, t in enumerate(toks) if t.kind == "num"), None)
    if num_at is not None and num_at <= 1:
        k = num_at + 1
        if k + 2 < len(toks) and toks[k].kind == "cmd" and toks[k].value in ("times", "cdot") and toks[k + 1].value == "10":
            k += 2
            if k < len(toks) and toks[k].kind == "sym" and toks[k].value == "^":
                k += 1
                if k < len(toks) and toks[k].kind == "sym" and toks[k].value == "{":
                    while k < len(toks) and not (toks[k].kind == "sym" and toks[k].value == "}"):
                        k += 1
                    k += 1
                elif k < len(toks):
                    k += 1
                    if k < len(toks) and toks[k].kind == "num" and toks[k - 1].kind == "sym":
                        k += 1
        rest = toks[k:]
        if rest and all(t.kind in ("letter", "num") or (t.kind == "sym" and t.value in ("/", "^", "-", "{", "}"))
                        or (t.kind == "cmd" and t.value == "cdot") for t in rest):
            text = "".join("·" if t.kind == "cmd" else t.value for t in rest)
            if is_unit_word(text) and rest[0].kind == "letter":
                return toks[:k], (text + (" " + unit if unit else "")).strip()
    return toks, unit


def _literal_ulp(term: list[Tok]) -> float | None:
    """For a term that is only a number (optionally signed, optionally x 10^n): one unit in its last printed place."""
    toks = [t for t in term if not (t.kind == "sym" and t.value in ("{", "}"))]
    if toks and toks[0].kind == "sym" and toks[0].value in ("-", "+"):
        toks = toks[1:]
    if not toks or toks[0].kind != "num":
        return None
    mant = toks[0].value
    exp = 0
    rest = toks[1:]
    if rest:
        if (len(rest) >= 3 and rest[0].kind == "cmd" and rest[0].value in ("times", "cdot") and rest[1].value == "10"
                and rest[2].kind == "sym" and rest[2].value == "^"):
            tail = rest[3:]
            sign = -1 if tail and tail[0].kind == "sym" and tail[0].value == "-" else 1
            digits = [t for t in tail if t.kind == "num"]
            if len(digits) != 1 or len(tail) - (1 if sign == -1 else 0) != 1:
                return None
            exp = sign * int(digits[0].value)
        else:
            return None
    decimals = len(mant.split(".")[1]) if "." in mant else 0
    if decimals == 0 and exp == 0:
        return None  # an integer is exact (see _Term.integer_literal for "~ 5")
    return 10.0 ** (exp - decimals)


def _tex(tokens: list[Tok]) -> str:
    parts: list[str] = []
    for t in tokens:
        if t.kind == "cmd":
            parts.append("\\" + t.value + " ")
        elif t.kind == "word":
            parts.append("\\mathrm{" + t.value + "}")
        else:
            parts.append(t.value)
    return re.sub(r"\s+", " ", "".join(parts)).strip()


def _segments(md: str) -> list[tuple[int, str, bool]]:
    """(position, latex, in_table) for every math segment outside code."""
    masked = _CODE_RE.sub(lambda m: " " * len(m.group(0)), md)
    out: list[tuple[int, str, bool]] = []
    for m in _SEG_RE.finditer(masked):
        body = m.group("d1") or m.group("d2") or m.group("i1") or m.group("i2") or ""
        line_start = masked.rfind("\n", 0, m.start()) + 1
        in_table = masked[line_start:m.start()].lstrip().startswith("|")
        out.append((m.start(), body, in_table))
    return out


def _table_rows(md: str) -> list[tuple[int, list[str], list[str], str]]:
    """(position, header cells, row cells, heading) for markdown table data rows."""
    rows: list[tuple[int, list[str], list[str], str]] = []
    lines = md.split("\n")
    pos = 0
    header: list[str] | None = None
    offsets = []
    for line in lines:
        offsets.append(pos)
        pos += len(line) + 1
    for idx, line in enumerate(lines):
        s = line.strip()
        if not (s.startswith("|") and s.count("|") >= 2):
            header = None
            continue
        cells = [c.strip() for c in s.strip("|").split("|")]
        if all(re.fullmatch(r":?-{2,}:?", c or "") for c in cells if c):
            continue
        prev = lines[idx - 1].strip() if idx else ""
        if header is None or not (prev.startswith("|")):
            header = cells
            continue
        rows.append((offsets[idx], header, cells, _heading_before(md, offsets[idx])))
    return rows


def _num_cell(text: str) -> tuple[float, float, str] | None:
    """(value, ulp, unit) of a cell holding one number, else None."""
    t = text.strip().translate(_SUP).replace("−", "-").replace("–", "-")
    t = re.sub(r"\\[,;!:]|\\ ", " ", t)
    t = re.sub(r"\\(?:mathrm|text)\{([^}]*)\}", r" \1", t).strip()
    m = _NUM_CELL_RE.match(t)
    if not m:
        return None
    unit = (m.group("unit") or "").strip()
    if unit and not is_unit_word(unit):
        return None
    mant = m.group("mant")
    exp = int((m.group("exp1") or m.group("exp2") or "0").replace("−", "-").replace("–", "-"))
    sign = -1.0 if m.group("sign") in ("-", "−", "–") else 1.0
    decimals = len(mant.split(".")[1]) if "." in mant else 0
    return sign * float(mant) * 10.0 ** exp, 10.0 ** (exp - decimals), unit


def _cell_math(cell: str) -> str:
    m = re.search(r"\$\$?(.+?)\$?\$", cell)
    return m.group(1) if m else ""


def _cell_label(cell: str) -> str:
    return re.sub(r"\$[^$]*\$", "", cell).strip(" ,:")


# -- evaluation ---------------------------------------------------------------------------------------------------------
class _Env:
    def __init__(self, variable: str, params: dict[str, sp.Expr], functions: set[str]) -> None:
        self.var = sp.Symbol(variable)
        self.params = params
        self.values: dict[str, sp.Expr] = {}
        self.funcs: dict[str, tuple[tuple[sp.Symbol, ...], sp.Expr]] = {}
        self.function_names = {canonical_name(f) for f in functions}
        # A value bound from a rounded literal ("W_in = 104.175") is only that precise: later relations that use it
        # are compared within its last printed place (absolute); a function with printed decimals within their
        # relative precision.
        self.ulps: dict[str, float] = {}
        self.func_rel: dict[str, float] = {}
        self.func_dec: dict[str, list[str]] = {}
        self.bound_heading: dict[str, str] = {}  # symbol -> heading of the statement that bound it

    def precision_of(self, *exprs: sp.Expr | None) -> tuple[float, float]:
        """(absolute, relative) uncertainty inherited from rounded values the expressions refer to, directly or through
        the bodies of the functions they apply ("x_p(t) = X cos(4t - phi)" with X and phi stated to 5-6 places)."""
        abs_u, rel_u = 0.0, 0.0
        seen_syms: set[str] = set()
        seen_funcs: set[str] = set()
        stack = [e for e in exprs if e is not None]
        while stack:
            e = stack.pop()
            for sym in e.free_symbols:
                c = canonical_name(sym.name)  # type: ignore[attr-defined]
                if c not in seen_syms:
                    seen_syms.add(c)
                    abs_u += self.ulps.get(c, 0.0)
            for app in e.atoms(AppliedUndef):
                d = split_deriv(type(app).__name__)
                c = canonical_name(d[0] if d else type(app).__name__)
                if c in seen_funcs:
                    continue
                seen_funcs.add(c)
                rel_u = max(rel_u, self.func_rel.get(c, 0.0))
                if c in self.funcs:
                    stack.append(self.funcs[c][1])
        return abs_u, rel_u

    def bound(self, name: str) -> bool:
        c = canonical_name(name)
        return c in self.values or c in self.params

    def resolve(self, expr: sp.Expr, depth: int = 0) -> sp.Expr:
        if depth > 12:
            raise Unsupported("bindings refer to each other")
        funcs = self.funcs

        def is_bound_app(e: Any) -> bool:
            if not isinstance(e, AppliedUndef):
                return False
            d = split_deriv(type(e).__name__)
            return canonical_name(d[0] if d else type(e).__name__) in funcs

        def apply(e: Any) -> sp.Expr:
            name = type(e).__name__
            d = split_deriv(name)
            base, order = d if d else (name, 0)
            params, body = funcs[canonical_name(base)]
            if order == 0:
                if len(params) != len(e.args):
                    raise Unsupported(f"{base} takes {len(params)} argument(s)")
                return body.xreplace(dict(zip(params, e.args, strict=True)))
            p = params[0]
            inner = self.resolve(body, depth + 1)
            if _has_undefined(inner):
                return e  # the function is built from parts not defined yet: the derivative waits for them
            dbody = sp.diff(inner, p, order)
            return dbody.xreplace({p: e.args[0]})

        out = expr.replace(is_bound_app, apply) if funcs else expr
        subs: dict[sp.Symbol, sp.Expr] = {}
        for s in out.free_symbols:
            if s == self.var:
                continue
            c = canonical_name(s.name)
            if c in self.values:
                subs[s] = self.values[c]  # type: ignore[index]
            elif c in self.params:
                subs[s] = self.params[c]
        if subs:
            out = out.xreplace(subs)
        if out != expr:
            return self.resolve(out, depth + 1)
        return out


def _has_undefined(expr: sp.Expr) -> bool:
    return any(isinstance(a, AppliedUndef) for a in sp.preorder_traversal(expr))


def _numeric_integrals(expr: sp.Expr) -> sp.Expr:
    """Definite integrals and sums replaced by their numerical values (integrand in the integration variable only)."""

    def integral_value(node: Any) -> sp.Expr:
        (var, lo, hi) = node.limits[0]
        body = node.function
        if body.free_symbols - {var}:
            raise Unsupported("integrand with free parameters")
        import numpy as np
        from scipy import integrate

        f = sp.lambdify(var, body, modules=["numpy"])
        a, b = float(lo), float(hi)
        val, _err = integrate.quad(lambda x: float(np.real(f(x))), a, b, limit=400)
        return sp.Float(val)

    out = expr
    if out.has(sp.Integral):
        out = out.replace(lambda e: isinstance(e, sp.Integral), integral_value)
    if out.has(sp.Sum):
        out = out.replace(lambda e: isinstance(e, sp.Sum), lambda e: sp.N(e.doit(), 20))
    return out


def _as_complex(expr: sp.Expr) -> complex | None:
    try:
        val = complex(sp.N(_numeric_integrals(expr), 20))
    except (TypeError, ValueError, Unsupported, ZeroDivisionError, OverflowError):
        return None
    if math.isnan(val.real) or math.isnan(val.imag) or math.isinf(val.real) or math.isinf(val.imag):
        return None
    return val


def _scale(expr: sp.Expr) -> float:
    """The magnitude of the largest top-level term, so cancellations are compared on the scale of their parts."""
    parts = expr.args if isinstance(expr, sp.Add) else (expr,)
    best = 0.0
    for p in parts:
        v = _as_complex(p)
        if v is not None:
            best = max(best, abs(v))
    return best


def _heading_of(claim: MathClaim) -> str:
    return claim.context.split(" · ")[0]


def _short(text: str, limit: int = 70) -> str:
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _fmt(v: complex | float) -> str:
    if isinstance(v, complex):
        if abs(v.imag) > 1e-12 * max(1.0, abs(v.real)):
            return f"{v.real:.6g}{v.imag:+.6g}i"
        v = v.real
    return f"{v:.6g}"


@dataclass
class _Term:
    expr: sp.Expr | None
    text: str
    ulp: float | None
    decimals: list[str]
    error: str = ""
    refs: bool = False  # refers to a bound or known function by application/derivative
    bare_fn: bool = False
    integer_literal: bool = False
    log10_expr: sp.Expr | None = None  # the term with a base-less \log read as base 10 (None: no bare \log)


class _Auditor:
    def __init__(self, query: str, record: ResultRecord | None, tool_numbers: list[float], variable: str,
                 functions: set[str], unknowns: set[str] | None = None) -> None:
        self.query = query
        self.record = record
        self.tool_numbers = tool_numbers
        params: dict[str, sp.Expr] = {}
        if record is not None:
            for cname, p in (record.parameters or {}).items():
                if cname in {canonical_name(f) for f in functions}:
                    continue
                try:
                    params[cname] = sp.Rational(str(p["value"]))
                except (TypeError, ValueError, KeyError):
                    continue
        self.env = _Env(variable, params, functions)
        # The problem's unknowns (solve / inequality / extremum): "x = 0" names a case examined, never binds x.
        self.unknowns = {canonical_name(u) for u in unknowns or ()}
        self.functions = functions
        self.claims: list[MathClaim] = []
        self.definitions: list[MathClaim] = []
        # (claim, link index, a, b, relation, heading, symbols unknown when it was deferred)
        self.pending: list[tuple[MathClaim, int, _Term, _Term, str, str, frozenset[str]]] = []
        self._n = 0

    # -- parsing --------------------------------------------------------------------------------------------------------
    def term(self, toks: list[Tok]) -> _Term:
        toks, unit = _strip_unit(toks)
        ctx = ParseContext(functions=set(self.functions), variable=str(self.env.var))
        text = _tex(toks)
        ulp = _literal_ulp(toks)
        if unit in ("deg", "degree", "degrees", "°"):
            # An angle in degrees is the same angle as its radian value: "0.588003 rad = 33.690°" is one quantity.
            deg = self._term_in(toks, ctx, text, ulp)
            if deg.expr is not None:
                deg.expr = deg.expr * sp.pi / 180
                if deg.log10_expr is not None:
                    deg.log10_expr = deg.log10_expr * sp.pi / 180
                deg.ulp = deg.ulp * math.pi / 180 if deg.ulp is not None else None
                deg.text = text + "°"
            return deg
        return self._term_in(toks, ctx, text, ulp)

    def _term_in(self, toks: list[Tok], ctx: ParseContext, text: str, ulp: float | None) -> _Term:
        try:
            expr = parse_tokens(toks, ctx)
        except (Unsupported, TypeError, ValueError, ZeroDivisionError, AttributeError) as exc:
            return _Term(None, text, ulp, [], error=str(exc)[:120])
        except Exception as exc:  # noqa: BLE001 - SymPy may raise anything on odd input; the term is not checkable
            return _Term(None, text, ulp, [], error=f"{type(exc).__name__}")
        integer = ulp is None and len([t for t in toks if t.kind == "num"]) == 1 and all(
            t.kind == "num" or (t.kind == "sym" and t.value in "+-") for t in toks) and "." not in text
        log10_expr = None
        if ctx.bare_log:
            # "\log" without a base is natural in mathematics and base 10 in much engineering text: read it both ways.
            try:
                log10_expr = parse_tokens(toks, ParseContext(functions=set(ctx.functions), variable=ctx.variable,
                                                             log_base=10))
            except Exception:  # noqa: BLE001 - parsed once already; a failure here only drops the second reading
                log10_expr = None
        return _Term(expr, text, ulp, list(ctx.decimals), refs=ctx.has_function_refs, bare_fn=ctx.bare_function_refs,
                     integer_literal=integer, log10_expr=log10_expr)

    # -- comparison -----------------------------------------------------------------------------------------------------
    def _tolerance(self, a: _Term, b: _Term, rel: str, scale: float, numeric_integral: bool) -> tuple[float, float]:
        """(absolute, relative) tolerance. A printed number is as precise as its last place (one unit, to allow
        truncation); an integer is exact, except "~ 5" which allows half a unit. Decimals printed inside an expression
        (a coefficient 0.284615384615385) bound its relative precision when they carry three or more places; shorter
        ones (0.5, 0.15) are read as exact."""
        abs_tol = 0.0
        for t in (a, b):
            if t.ulp is not None:
                abs_tol = max(abs_tol, t.ulp)
            elif t.integer_literal and rel == "approx":
                abs_tol = max(abs_tol, 0.5)
        rel_tol = 1e-9
        coef_abs = 0.0
        for t in (a, b):
            if t.ulp is not None:
                continue  # a literal's own precision is its absolute tolerance, never a relative one
            for d in t.decimals:
                places = len(d.split(".")[1]) if "." in d else 0
                try:
                    v = abs(float(d))
                except ValueError:
                    continue
                if places >= 3 and v > 0:
                    rel_tol = max(rel_tol, 10.0 ** (-places) / v)
                    # A rounded coefficient moves the value by up to its last place, whatever the value itself is
                    # (terms can cancel to a value far smaller than the coefficients).
                    coef_abs += 10.0 ** (-places)
        floor = (1e-6 if numeric_integral else 1e-9) * max(1.0, scale)
        return max(abs_tol, floor) + coef_abs, rel_tol

    def _inherited_abs(self, a: _Term, b: _Term, base_diff: complex) -> float:
        """How much the comparison can move from rounding in the values it uses that were bound from printed decimals:
        each such value is moved by half its last place and the change of (a - b) is summed."""
        names: set[str] = set()
        stack = [e for e in (a.expr, b.expr) if e is not None]
        seen_funcs: set[str] = set()
        while stack:  # symbols used directly and inside the bodies of the functions applied
            e = stack.pop()
            names |= {canonical_name(s.name) for s in e.free_symbols}  # type: ignore[attr-defined]
            for app in e.atoms(AppliedUndef):
                d = split_deriv(type(app).__name__)
                c = canonical_name(d[0] if d else type(app).__name__)
                if c not in seen_funcs and c in self.env.funcs:
                    seen_funcs.add(c)
                    stack.append(self.env.funcs[c][1])
        total = 0.0
        for c in names:
            u = self.env.ulps.get(c)
            base = self.env.values.get(c)
            if not u or base is None:
                continue
            try:
                self.env.values[c] = base + sp.Float(u / 2)
                moved = _as_complex(self.env.resolve(a.expr) - self.env.resolve(b.expr))  # type: ignore[arg-type]
            except Exception:  # noqa: BLE001
                moved = None
            finally:
                self.env.values[c] = base
            if moved is not None:
                total += abs(moved - base_diff)
        return total

    def compare(self, a: _Term, b: _Term, rel: str) -> tuple[str, str]:
        """(status, detail) for one relation: passed | failed | inconclusive | equation. A relation with a base-less
        log that holds under one convention (natural or base 10) and fails under the other is inconclusive: the base
        was never stated."""
        status, detail = self._compare(a, b, rel)
        if a.log10_expr is None and b.log10_expr is None:
            return status, detail
        alt_a = replace(a, expr=a.log10_expr) if a.log10_expr is not None else a
        alt_b = replace(b, expr=b.log10_expr) if b.log10_expr is not None else b
        alt_status, _alt_detail = self._compare(alt_a, alt_b, rel)
        if {status, alt_status} == {PASSED, FAILED}:
            holds = "base 10, not base e" if alt_status == PASSED else "base e, not base 10"
            return INCONCLUSIVE, rf"\log without a base: holds for {holds}"
        return status, detail

    def _compare(self, a: _Term, b: _Term, rel: str) -> tuple[str, str]:
        if a.expr is None or b.expr is None:
            return INCONCLUSIVE, f"not parsed: {(a.error or b.error)[:80]}"
        try:
            left = self.env.resolve(a.expr)
            right = self.env.resolve(b.expr)
        except Unsupported as exc:
            return INCONCLUSIVE, str(exc)[:100]
        except Exception as exc:  # noqa: BLE001 - SymPy failures make a relation uncheckable, never wrong
            return INCONCLUSIVE, f"could not be evaluated ({type(exc).__name__})"
        if _has_undefined(left) or _has_undefined(right):
            return "equation", "refers to a function not defined yet"
        extra_abs, extra_rel = self.env.precision_of(a.expr, b.expr)
        fl, fr = left.free_symbols, right.free_symbols
        integral = left.has(sp.Integral) or right.has(sp.Integral)
        if fl != fr:
            return "equation", f"unknowns {', '.join(sorted(str(s) for s in (fl ^ fr)))[:80]}"
        if not fl:
            lv, rv = _as_complex(left), _as_complex(right)
            if lv is None or rv is None:
                return INCONCLUSIVE, "could not be evaluated numerically"
            scale = max(abs(lv), abs(rv), _scale(left), _scale(right))
            abs_tol, rel_tol = self._tolerance(a, b, rel, scale, integral)
            abs_tol, rel_tol = abs_tol + self._inherited_abs(a, b, lv - rv), max(rel_tol, extra_rel)
            if abs(lv - rv) <= abs_tol + rel_tol * max(abs(lv), abs(rv)):
                return PASSED, ""
            return FAILED, f"{_short(a.text)} evaluates to {_fmt(lv)}, {_short(b.text)} to {_fmt(rv)}"
        # An identity in the shared free symbols, tested at sample points.
        syms = sorted(fl, key=lambda s: s.name)
        try:
            fa = sp.lambdify(syms, _numeric_integrals(left), modules=["mpmath"])
            fb = sp.lambdify(syms, _numeric_integrals(right), modules=["mpmath"])
        except Exception:  # noqa: BLE001
            return INCONCLUSIVE, "could not be evaluated numerically"
        rng = random.Random(7)
        t_values = [0.37, 1.13, 2.71, 4.4, 6.9, 0.05]
        ok = bad = 0
        worst = ""
        for k in range(6):
            point = []
            for s in syms:
                point.append(t_values[k] if s == self.env.var else rng.uniform(0.35, 2.2))
            try:
                lv, rv = complex(fa(*point)), complex(fb(*point))
            except Exception:  # noqa: BLE001 - a singular sample point is skipped
                continue
            if any(math.isnan(x) or math.isinf(x) for x in (lv.real, lv.imag, rv.real, rv.imag)):
                continue
            abs_tol, rel_tol = self._tolerance(a, b, rel, max(abs(lv), abs(rv)), integral)
            abs_tol, rel_tol = abs_tol + 0.5 * extra_abs, max(rel_tol, extra_rel)
            if abs(lv - rv) <= abs_tol + rel_tol * max(abs(lv), abs(rv)):
                ok += 1
            else:
                bad += 1
                if not worst:
                    at = ", ".join(f"{s}={v:.3g}" for s, v in zip(syms, point, strict=True))
                    worst = f"at {at}: {_fmt(lv)} vs {_fmt(rv)}"
        if bad:
            return FAILED, f"{_short(a.text)} and {_short(b.text)} differ ({worst})"
        if ok >= 3:
            return PASSED, ""
        return INCONCLUSIVE, "too few valid sample points"

    # -- claims ---------------------------------------------------------------------------------------------------------
    def _new_claim(self, st: _Statement, kind: str) -> MathClaim:
        self._n += 1
        return MathClaim(claim_id=f"m{self._n}", text=st.text[:300], context=st.context[:160], kind=kind,
                         status=INCONCLUSIVE, position=st.position, source_text=st.source or st.text, lead=st.lead)

    @staticmethod
    def _settle(claim: MathClaim) -> None:
        statuses = [lk.status for lk in claim.links]
        if FAILED in statuses:
            claim.status = FAILED
            claim.detail = next(lk.detail for lk in claim.links if lk.status == FAILED)
        elif statuses and all(s == PASSED for s in statuses):
            claim.status = PASSED
            claim.detail = ""
        else:
            claim.status = INCONCLUSIVE
            decided = sum(1 for s in statuses if s == PASSED)
            claim.detail = f"{decided} of {len(statuses)} relation(s) checked" + (
                f"; {next((lk.detail for lk in claim.links if lk.status != PASSED and lk.detail), '')}" if statuses else "")

    def _definable(self, term: _Term) -> tuple[str, str, tuple[sp.Symbol, ...]] | None:
        """('symbol'|'function'|'derivative', name, params) when the first term names something to define or check."""
        e = term.expr
        if e is None:
            return None
        if isinstance(e, sp.Symbol):
            if e == self.env.var:
                return None
            return "symbol", e.name, ()
        if isinstance(e, AppliedUndef) and e.args and all(isinstance(x, sp.Symbol) for x in e.args):
            name = type(e).__name__
            d = split_deriv(name)
            if d:
                return "derivative", name, tuple(e.args)  # type: ignore[arg-type]
            return "function", name, tuple(e.args)  # type: ignore[arg-type]
        return None

    def statement(self, st: _Statement) -> None:
        cleaned = _clean_tokens(st.tokens)
        if cleaned is None:
            return
        split = _split_relations(cleaned)
        if split is None:
            return
        term_toks, rels = split
        if not rels:
            return
        terms = [self.term(t) for t in term_toks]
        if terms[0].expr is not None and terms[0].expr == self.env.var:
            return  # "t = 0" says where the next statements are evaluated; it is not a claim
        if isinstance(terms[0].expr, sp.Symbol) and canonical_name(terms[0].expr.name) in self.unknowns:
            return  # "x = 45/8 gives equality": a root, endpoint or test point of the problem's unknown, not a binding
        if terms[0].expr is None and len(terms) >= 3:
            # An unreadable first term ("P(K = 3) = binom(10,3) 0.5^3 ... ~ 0.117") is a label; the relations after it
            # carry the claim.
            terms, rels = terms[1:], rels[1:]
        head = self._definable(terms[0])
        kind = "table_row" if st.kind == "table_row" else ("derivative" if head and head[0] == "derivative" else "relation")
        claim = self._new_claim(st, kind)
        defined: tuple[str, str, tuple[sp.Symbol, ...]] | None = None
        for i, rel in enumerate(rels, start=1):
            a, b = terms[i - 1], terms[i]
            if i == 1 and head and head[0] in ("symbol", "function") and not self._is_bound(head):
                defined = head
                continue
            if i == 1 and head and head[0] in ("symbol", "function") and self._is_bound(head):
                # A restatement: checked against the earlier statement as it was then, then rebound.
                defined = head
                a = self._snapshot(head, a)
            status, detail = self.compare(a, b, rel)
            if status == "equation":
                claim.links.append(Link(a.text[:120], b.text[:120], rel, INCONCLUSIVE, "pending: " + detail))
                self.pending.append((claim, len(claim.links) - 1, a, b, rel, _heading_of(claim), self._unknowns(a, b)))
                continue
            if status == FAILED and not (a.refs or b.refs or i == 1 and defined) and not self._numeric_only(a, b):
                # An identity that fails without referring to anything bound may be an equation to solve.
                claim.links.append(Link(a.text[:120], b.text[:120], rel, INCONCLUSIVE, "pending: possibly an equation"))
                self.pending.append((claim, len(claim.links) - 1, a, b, rel, _heading_of(claim), self._unknowns(a, b)))
                continue
            claim.links.append(Link(a.text[:120], b.text[:120], rel, status, detail))
        if defined is not None:
            # A restatement is checked against the earlier binding, never rebinds it: the first statement is usually
            # the exact one (a later "x_p(t) = X cos(4t - phi)" with rounded X and phi, or a contradicted value, must
            # not replace it). An ansatz with unknown constants resolves as soon as the constants are stated.
            if not self._is_bound(defined):
                self._bind(defined, terms, claim)
            elif not claim.defines:
                claim.defines = defined[1]
        if not claim.links:
            claim.kind = DEFINITION
            claim.status = DEFINITION
            self.definitions.append(claim)
            return
        self._settle(claim)
        self.claims.append(claim)

    @staticmethod
    def _numeric_only(a: _Term, b: _Term) -> bool:
        return a.expr is not None and b.expr is not None and not a.expr.free_symbols and not b.expr.free_symbols

    def _is_bound(self, head: tuple[str, str, tuple[sp.Symbol, ...]]) -> bool:
        kind, name, _ = head
        c = canonical_name(name)
        return c in self.env.funcs if kind == "function" else self.env.bound(name)

    def _snapshot(self, head: tuple[str, str, tuple[sp.Symbol, ...]], term: _Term) -> _Term:
        """The earlier binding of a restated name, frozen (a later rebinding must not change what it is compared to)."""
        kind, name, _params = head
        c = canonical_name(name)
        if kind == "symbol":
            old = self.env.values.get(c, self.env.params.get(c))
            if old is None:
                return term
            return _Term(old, term.text, self.env.ulps.get(c), [], refs=True)
        params, body = self.env.funcs[c]
        args = term.expr.args if term.expr is not None else ()
        if len(args) != len(params):
            return term
        return _Term(body.xreplace(dict(zip(params, args, strict=True))), term.text, None,
                     list(self.env.func_dec.get(c, [])), refs=True)

    def _bind(self, head: tuple[str, str, tuple[sp.Symbol, ...]], terms: list[_Term], claim: MathClaim) -> None:
        kind, name, params = head
        value = next((t for t in reversed(terms[1:]) if t.expr is not None), None)
        if value is None or value.expr is None:
            return
        if claim.links and all(lk.status == PASSED for lk in claim.links):
            # Every relation held: bind the exact form ("sqrt(391)/4", "-37/130", the integral itself) rather than the
            # rounded decimal printed after it, so later statements are checked against the exact value.
            exact = next((t for t in reversed(terms[1:]) if t.expr is not None and t.ulp is None and not t.decimals), None)
            if exact is not None:
                value = exact
        c = canonical_name(name)
        expr = value.expr
        if kind == "symbol":
            if sp.Symbol(name) in expr.free_symbols:
                return  # "X = 2X" defines nothing
            try:
                expr = self.env.resolve(expr)
            except Unsupported:
                return
            self.env.values[c] = expr
            self.env.bound_heading[c] = _heading_of(claim)
            ulp = value.ulp
            long_decimals = [d for d in value.decimals if "." in d and len(d.split(".")[1]) >= 3]
            if ulp is None and long_decimals:
                ulp = max(10.0 ** -len(d.split(".")[1]) for d in long_decimals)
            if ulp:
                self.env.ulps[c] = ulp
            else:
                self.env.ulps.pop(c, None)
            claim.defines = name
            self._record_check(name, expr, value, claim)
        else:
            self.env.funcs[c] = (params, expr)
            self.env.func_dec[c] = list(value.decimals)
            rel = 0.0
            for d in value.decimals:
                places = len(d.split(".")[1]) if "." in d else 0
                if places >= 3 and float(d):
                    rel = max(rel, 10.0 ** -places / abs(float(d)))
            self.env.func_rel[c] = rel
            claim.defines = f"{name}({', '.join(str(p) for p in params)})"
        self._retry_pending()

    def _retry_pending(self) -> None:
        still: list[tuple[MathClaim, int, _Term, _Term, str, str, frozenset[str]]] = []
        changed: set[str] = set()
        for item in self.pending:
            claim, idx, a, b, rel, heading, unknown = item
            # A single-letter symbol is often reused for something else later ("r" for a characteristic root, then
            # for a frequency ratio): a deferred equation is resolved only by unknowns stated under its own heading.
            if any(self.env.bound_heading.get(u, heading) != heading for u in unknown):
                still.append(item)
                continue
            try:
                status, detail = self.compare(a, b, rel)
            except Exception as exc:  # noqa: BLE001 - a re-check never breaks the statement that triggered it
                status, detail = INCONCLUSIVE, f"{type(exc).__name__}"
            if status == "equation":
                still.append(item)
                continue
            if status == FAILED and not self._all_bound(a, b):
                still.append(item)
                continue
            claim.links[idx].status = status
            claim.links[idx].detail = detail
            changed.add(claim.claim_id)
        self.pending = still
        for claim in self.claims:
            if claim.claim_id in changed:
                self._settle(claim)

    def _unknowns(self, a: _Term, b: _Term) -> frozenset[str]:
        """Symbols (not the independent variable, not functions) that are unbound when a relation is deferred."""
        names: set[str] = set()
        for e in (a.expr, b.expr):
            if e is None:
                continue
            for sym in e.free_symbols:
                if sym != self.env.var and not self.env.bound(sym.name):  # type: ignore[attr-defined]
                    names.add(canonical_name(sym.name))  # type: ignore[attr-defined]
        return frozenset(names)

    def _all_bound(self, a: _Term, b: _Term) -> bool:
        """After substitution nothing but the independent variable is free (the equation became checkable)."""
        try:
            left = self.env.resolve(a.expr) if a.expr is not None else None
            right = self.env.resolve(b.expr) if b.expr is not None else None
        except Unsupported:
            return False
        if left is None or right is None:
            return False
        return (left.free_symbols | right.free_symbols) <= {self.env.var}

    def _record_check(self, name: str, expr: sp.Expr, value: _Term, claim: MathClaim) -> None:
        """A stated value of a quantity a tool computed must be that value."""
        if self.record is None or expr.free_symbols:
            return
        v = _as_complex(expr)
        if v is None:
            return
        context = f"{claim.context} {claim.lead} {claim.text}".lower()
        for q in self.record.quantities:
            if not q.symbol or q.convention or canonical_name(q.symbol) != canonical_name(name):
                continue
            if not isinstance(q.value, (int, float)):
                continue
            words = [w for w in q.name_words if w not in ("frequency", "ratio")] or q.name_words
            if not (any(w in context for w in words) or "_" in q.symbol):
                continue
            tol = max(value.ulp or 0.0, 1e-6 * max(1.0, abs(float(q.value))))
            if value.decimals and value.ulp is None:
                tol = max(tol, 4 * 10.0 ** (-max(len(d.split(".")[1]) for d in value.decimals if "." in d)))
            ok = abs(v.real - float(q.value)) <= tol + 1e-9 * abs(float(q.value)) and abs(v.imag) < 1e-9
            claim.links.append(Link(
                f"{name} = {_fmt(v)}", f"{q.symbol} = {float(q.value):.6g} {q.unit}".strip(), "eq",
                PASSED if ok else FAILED,
                "" if ok else f"the run computed {q.symbol} = {float(q.value):.6g} {q.unit} ({q.formula}); the answer states {_fmt(v)}",
                source=f"tool:{q.source}",
            ))
            return

    # -- problem conditions ---------------------------------------------------------------------------------------------
    def problem_checks(self, problem: dict[str, Any]) -> None:
        """The answer's final solution against the stated equation, initial conditions and a verified solution."""
        func = re.sub(r"\(.*$", "", str(problem.get("function") or ""))
        if not func or canonical_name(func) not in self.env.funcs:
            return
        params, body = self.env.funcs[canonical_name(func)]
        try:
            resolved = self.env.resolve(body)
        except Unsupported:
            return
        if resolved.free_symbols - set(params) or _has_undefined(resolved):
            return  # the final solution still has unknown constants: nothing to compare
        st = _Statement([], f"{func}({self.env.var}) as finally stated", "problem conditions", 10**9, "condition")
        # Equation.
        eq_text = str(problem.get("equation") or "")
        if "=" in eq_text and problem.get("kind") == "ode":
            lhs, _, rhs = eq_text.partition("=")
            claim = self._new_claim(st, "condition")
            claim.text = f"{func}({self.env.var}) satisfies {eq_text.strip()}"
            a, b = self.term(tokenize(lhs)), self.term(tokenize(rhs))
            status, detail = self.compare(a, b, "eq")
            claim.links.append(Link(a.text, b.text, "eq", status if status != "equation" else INCONCLUSIVE, detail,
                                    source="problem"))
            self._settle(claim)
            self.claims.append(claim)
        # Initial conditions.
        ics = problem.get("initial_conditions") or {}
        if ics:
            claim = self._new_claim(st, "condition")
            claim.text = "initial conditions " + ", ".join(f"{k} = {v}" for k, v in ics.items())
            for cond, val in ics.items():
                a, b = self.term(tokenize(str(cond))), self.term(tokenize(str(val)))
                status, detail = self.compare(a, b, "eq")
                claim.links.append(Link(a.text, b.text, "eq", status if status != "equation" else INCONCLUSIVE,
                                        detail, source="problem"))
            self._settle(claim)
            self.claims.append(claim)
        # A verified solution from the run.
        for ex in (self.record.expressions if self.record else []):
            if canonical_name(ex.function) != canonical_name(func):
                continue
            try:
                from ..axiom.engine import safe_parse_expr

                tool_expr = safe_parse_expr(ex.text, local_dict={ex.variable: sp.Symbol(ex.variable)})
            except Exception:  # noqa: BLE001
                continue
            tool_expr = tool_expr.xreplace({sp.Symbol(ex.variable): self.env.var})
            claim = self._new_claim(st, "condition")
            claim.text = f"{func}({self.env.var}) matches the {ex.status} solution from the run"
            a = _Term(resolved.xreplace({params[0]: self.env.var}) if params else resolved, f"{func}({self.env.var})", None, [])
            b = _Term(tool_expr, "the run's solution", None, [])
            status, detail = self.compare(a, b, "eq")
            # The answer prints decimals; allow their precision.
            if status == FAILED:
                a.decimals = re.findall(r"\d+\.\d+", st.text)
            claim.links.append(Link(a.text, b.text, "eq", status if status != "equation" else INCONCLUSIVE, detail,
                                    source=f"tool:{ex.source}"))
            self._settle(claim)
            self.claims.append(claim)
            break

    # -- grounding ------------------------------------------------------------------------------------------------------
    def ground_row(self, position: int, label: str, cells: list[tuple[float, float, str]], context: str, text: str) -> None:
        if not self.tool_numbers or not cells:
            return
        given = {round(float(p["value"]), 12) for p in ((self.record.parameters if self.record else {}) or {}).values()
                 if isinstance(p.get("value"), (int, float))}
        checked = [(v, u) for v, u, _unit in cells if round(v, 12) not in given and not float(v).is_integer()]
        if not checked:
            return
        self._n += 1
        claim = MathClaim(claim_id=f"m{self._n}", text=text[:300], context=context[:160], kind="grounding",
                          status=PASSED, position=position, source_text=text)
        missing = []
        for v, ulp in checked:
            if not self._grounded(v, ulp):
                missing.append(v)
        if missing:
            claim.status = UNSUPPORTED
            claim.detail = "no tool output gives " + ", ".join(_fmt(m) for m in missing[:4])
        claim.links.append(Link(label[:80] or "row", f"{len(checked) - len(missing)} of {len(checked)} values in tool outputs",
                                "eq", claim.status, claim.detail, source="tools"))
        self.claims.append(claim)

    def _grounded(self, v: float, ulp: float) -> bool:
        tol = ulp * 1.0001 + 1e-15
        nums = self.tool_numbers
        for target in (v, -v) if v != 0 else (v,):
            i = bisect.bisect_left(nums, target - tol)
            if i < len(nums) and nums[i] <= target + tol:
                return target == v or False
        return False


def _tool_numbers(tool_results: dict[str, Any]) -> list[float]:
    """Every number in the successful tool outputs (short arrays and text included; long series excluded)."""
    out: list[float] = []

    def walk(value: Any, depth: int = 0) -> None:
        if len(out) >= MAX_TOOL_NUMBERS or depth > 8:
            return
        if isinstance(value, bool):
            return
        if isinstance(value, (int, float)):
            if math.isfinite(float(value)):
                out.append(float(value))
            return
        if isinstance(value, str):
            for m in re.finditer(r"[-+]?\d+\.\d+(?:[eE][-+]?\d+)?|[-+]?\d+[eE][-+]?\d+", value[:20000]):
                try:
                    out.append(float(m.group(0)))
                except ValueError:
                    continue
            return
        if isinstance(value, dict):
            for k, v in value.items():
                if str(k) in ("plot_base64_png", "script", "code"):
                    continue
                walk(v, depth + 1)
            return
        if isinstance(value, (list, tuple)):
            if len(value) > 64 and all(isinstance(x, (int, float)) for x in value[:64]):
                return  # a long series (trajectory samples) matches anything by chance
            for v in value:
                walk(v, depth + 1)

    for res in (tool_results or {}).values():
        if res is not None and getattr(res, "success", False):
            walk(getattr(res, "data", None))
    return sorted(out)


def _document_functions(md: str, problem_function: str) -> tuple[set[str], str]:
    """Names used as functions (x(t), x_p(t), E(0), \\dot x) and the independent variable."""
    names: set[str] = set()
    var_counts: dict[str, int] = {}
    for _pos, raw, _t in _segments(md):
        body = re.sub(r"\\(?:rm|mathrm|text|textrm|operatorname)\s*\{([^{}]*)\}", r"\1", raw)
        body = re.sub(r"\\rm\s+", "", body)
        for m in re.finditer(r"(?<![\\A-Za-z])([A-Za-z])(?:_\{?([A-Za-z0-9]+)\}?)?\s*\(\s*([A-Za-z]|[-\d.]+)\s*\)", body):
            base = m.group(1) + (f"_{m.group(2)}" if m.group(2) else "")
            if base in ("e", "d", "i"):
                continue
            names.add(base)
            if re.fullmatch(r"[A-Za-z]", m.group(3)):
                var_counts[m.group(3)] = var_counts.get(m.group(3), 0) + 1
        for m in re.finditer(r"\\d?dot\s*\{?\s*([A-Za-z])", body):
            names.add(m.group(1))
    if problem_function:
        names.add(problem_function)
    variable = max(var_counts, key=lambda k: var_counts[k]) if var_counts else "t"
    return names, variable


def _unknowns(md: str, problem: dict[str, Any]) -> set[str]:
    """The problem's unknowns: from the parsed question, and any symbol the answer ranges over a set ("x \\in [a, b)"),
    which is a variable even when the question could not be parsed."""
    out = {str(u) for u in problem.get("unknowns") or []}
    for _pos, body, _t in _segments(md):
        out.update(re.findall(r"(?<![\\A-Za-z])([A-Za-z])\s*\\in\b", body))
    return out


def audit_answer(
    response: str,
    query: str = "",
    tool_results: dict[str, Any] | None = None,
    record: ResultRecord | None = None,
) -> MathAudit:
    """Check every mathematical statement in `response` (see the module docstring)."""
    from .result_record import build_result_record

    tool_results = tool_results or {}
    if record is None:
        record = build_result_record(query, tool_results)
    md = response or ""
    problem = record.problem or {}
    func = re.sub(r"\(.*$", "", str(problem.get("function") or ""))
    functions, variable = _document_functions(md, func)
    if problem.get("variable"):
        variable = str(problem.get("variable"))
    auditor = _Auditor(query, record, _tool_numbers(tool_results), variable, functions, _unknowns(md, problem))

    statements: list[_Statement] = []
    for pos, body, in_table in _segments(md):
        if in_table:
            continue
        prefix = _prefix(md, pos)
        if _CONDITIONAL_RE.search(prefix) or _REFERENCE_CUE_RE.search(prefix[-28:]):
            continue
        heading = _heading_before(md, pos)
        try:
            tokens = _join_continuations(tokenize(body))
        except Exception:  # noqa: BLE001
            continue
        for part in _depth_split(tokens, _is_separator):
            statements.append(_Statement(part, _tex(part), heading, pos, source=body, lead=prefix[-160:]))

    row_items: list[tuple[int, str, list[tuple[float, float, str]], str, str]] = []
    for pos, _header, cells, heading in _table_rows(md):
        try:
            _table_statement(pos, cells, heading, statements, row_items)
        except Exception as exc:  # noqa: BLE001 - one unreadable row never stops the audit
            logger.debug("Table row skipped (%s): %s", exc, " | ".join(cells)[:120])

    statements.sort(key=lambda s: s.position)
    for st in statements[:MAX_STATEMENTS]:
        try:
            auditor.statement(st)
        except Exception as exc:  # noqa: BLE001 - one unreadable statement never stops the audit
            logger.debug("Math statement skipped (%s): %s", exc, st.text[:120])
    # Equations whose unknowns were never stated stay inconclusive (already marked).
    for claim in auditor.claims:
        auditor._settle(claim)
    try:
        auditor.problem_checks(problem)
    except Exception as exc:  # noqa: BLE001
        logger.debug("Problem condition checks skipped: %s", exc)
    for pos, label, cells, context, text in row_items:
        try:
            auditor.ground_row(pos, label, cells, context, text)
        except Exception as exc:  # noqa: BLE001
            logger.debug("Row grounding skipped: %s", exc)
    auditor.claims.sort(key=lambda c: c.position)
    return MathAudit(claims=auditor.claims, definitions=auditor.definitions, record_revision=record.revision,
                     variable=variable)


def _table_statement(pos: int, cells: list[str], heading: str, statements: list[_Statement],
                     row_items: list[tuple[int, str, list[tuple[float, float, str]], str, str]]) -> None:
    """A table row as a relation chain (a formula or math label with one result cell), or as numbers to ground."""
    label = _cell_label(cells[0]) if cells else ""
    nums = [(c, _num_cell(c)) for c in cells]
    numeric = [(c, n) for c, n in nums if n is not None]
    formula_cell = next((c for c in cells if (m := _cell_math(c)) and re.search(r"=|\\approx", m)), None)
    label_math = _cell_math(cells[0]) if cells else ""
    row_text = " | ".join(cells)
    context = f"{heading} · {label}".strip(" ·")
    if formula_cell is not None and len(numeric) == 1:
        toks = tokenize(_cell_math(formula_cell)) + [Tok("cmd", "approx")] + tokenize(numeric[0][0].replace("$", ""))
        statements.append(_Statement(_strip_unit_tail(toks), row_text, context, pos, "table_row", row_text))
    elif label_math and len(numeric) == 1 and not re.search(r"=|\\approx", label_math):
        toks = tokenize(label_math) + [Tok("cmd", "approx")] + tokenize(numeric[0][0].replace("$", ""))
        statements.append(_Statement(_strip_unit_tail(toks), row_text, context, pos, "table_row", row_text))
    elif numeric:
        row_items.append((pos, label, [n for _c, n in numeric if n is not None], context, row_text))


def _strip_unit_tail(toks: list[Tok]) -> list[Tok]:
    out, _unit = _strip_unit(toks)
    return out


def claim_defects(audit: MathAudit, limit: int = 12) -> list[dict[str, Any]]:
    """Verifier defects for the failed claims (one per claim), with what the checker computed."""
    out: list[dict[str, Any]] = []
    for c in audit.failed[:limit]:
        where = f" ({c.context})" if c.context else ""
        out.append({
            "category": "MATH_CONSISTENCY",
            "severity": "CRITICAL",
            "description": f"Mathematical statement{where} does not hold: {c.detail}"[:600],
            "suggested_correction": (
                "Restate this result from the computed values (the tool outputs in the evidence) and re-derive the "
                f"step; the check found: {c.detail}"
            )[:600],
            "claim": c.text[:300],
        })
    return out


def summary_line(audit: MathAudit) -> str:
    n = audit.counts()
    if not n["extracted"]:
        return "no mathematical statements found"
    parts = [f"{n['passed']} passed"]
    if n["failed"]:
        parts.append(f"{n['failed']} failed")
    if n["inconclusive"]:
        parts.append(f"{n['inconclusive']} not checkable")
    if n["unsupported"]:
        parts.append(f"{n['unsupported']} without a source")
    return f"{n['extracted']} mathematical statement(s): " + ", ".join(parts)


def iter_failed_texts(audit: MathAudit) -> Iterable[str]:
    for c in audit.failed:
        yield c.text


__all__ = [
    "FAILED",
    "INCONCLUSIVE",
    "PASSED",
    "UNSUPPORTED",
    "Link",
    "MathAudit",
    "MathClaim",
    "audit_answer",
    "claim_defects",
    "summary_line",
]
