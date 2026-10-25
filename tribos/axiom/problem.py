"""
Problem parser and normalizer for the verified mathematics agent.

Turns a question written in prose, LaTeX or Unicode math ("Find all real x with x² − 5x + 6 = 0",
"\\int_0^\\pi \\sin x\\,dx", "y'' + y = 0, y(0) = 1") into a typed ProblemSpec: the task kind, the exact
expression(s) as SymPy-parseable source text, the variable, bounds/points/orders, domain and symbol assumptions.

The verbatim question is always kept next to the parsed form, and anything the parser had to guess is listed in
`ambiguities`, so a parser mistake stays visible instead of silently changing the problem. A question the parser
cannot read gets kind "unknown"; the agent then relies on the model policy, and the verifier can no longer check
semantic alignment against the original (which it reports).
"""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from typing import Any, Literal

import sympy as sp
from sympy.core.function import AppliedUndef

from .engine import safe_parse_equation, safe_parse_expr

TaskKind = Literal[
    "solve", "simplify", "differentiate", "integrate", "limit", "series", "sum", "ode", "linalg", "identity",
    "evaluate", "optimize", "inequality", "tangent", "number_theory", "recurrence", "transform", "vector_calculus",
    "probability", "statistics", "unknown",
]
# Kinds whose inputs live in ProblemSpec.params rather than in a single expression.
PARAM_KINDS = frozenset({"number_theory", "probability", "statistics", "vector_calculus", "recurrence", "transform", "optimize", "tangent"})

LINALG_OPS = ("eigen", "det", "inv", "rref", "svd", "nullspace", "charpoly", "solve")


@dataclass
class ProblemSpec:
    text: str  # the question exactly as asked
    kind: TaskKind = "unknown"
    expression: str | None = None  # main expression, or "lhs = rhs" for solve / ode / identity
    equations: list[str] = field(default_factory=list)  # systems of equations
    variable: str | None = None
    variables: list[str] = field(default_factory=list)
    lower: str | None = None
    upper: str | None = None
    point: str | None = None
    order: int = 1
    matrix: list[list[str]] | None = None
    rhs_vector: list[str] | None = None
    linalg_op: str | None = None
    func: str | None = None  # ODE unknown, e.g. "y(x)"
    ics: dict[str, str] = field(default_factory=dict)
    domain: Literal["real", "complex"] = "complex"
    assumptions: dict[str, str] = field(default_factory=dict)
    form: Literal["simplify", "factor", "expand"] = "simplify"  # requested output form of a simplify task
    params: dict[str, Any] = field(default_factory=dict)  # kind-specific inputs (operation, numbers, distribution, ...)
    ambiguities: list[str] = field(default_factory=list)
    # Parse fidelity: numbers, differentials and meaning-changing words of the question that the parsed problem does
    # not use. Non-empty means the parse may describe a different problem, so no answer can be "verified".
    unaccounted: list[str] = field(default_factory=list)
    handled: set[str] = field(default_factory=set, repr=False)  # modifier words a parser consumed ("twice", "area")

    @property
    def parsed(self) -> bool:
        """True when the verifier can re-derive checks from the original problem."""
        if self.kind == "linalg":
            return self.matrix is not None
        if self.kind in PARAM_KINDS:
            return bool(self.params)
        return self.kind != "unknown" and bool(self.expression or self.equations)

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d.pop("handled", None)
        return d


# Normalization ----------------------------------------------------------------------------------------------------

_UNICODE = {
    "−": "-", "–": "-", "—": "-", "×": "*", "·": "*", "⋅": "*", "÷": "/", "π": "pi", "∞": "oo", "√": "sqrt",
    "²": "^2", "³": "^3", "⁴": "^4", "⁵": "^5", "⁻¹": "^(-1)", "≤": "<=", "≥": ">=", "→": "->", "⟶": "->",
    "∫": r" \int", "∑": r" \sum", "θ": "theta", "α": "alpha", "β": "beta", "γ": "gamma", "λ": "lambda_",
    "μ": "mu", "ω": "omega", "φ": "phi", "σ": "sigma", "τ": "tau", "ε": "epsilon", "δ": "delta",
    "\u2009": " ", "\u00a0": " ", "’": "'", "′": "'", "″": "''",
}
_LATEX_FUNCS = (
    "arcsin", "arccos", "arctan", "sinh", "cosh", "tanh", "sin", "cos", "tan", "cot", "sec", "csc", "exp", "log",
    "ln", "det",
)
_LATEX_SYMBOLS = {
    r"\pi": "pi", r"\infty": "oo", r"\cdot": "*", r"\times": "*", r"\div": "/", r"\to": "->", r"\rightarrow": "->",
    r"\theta": "theta", r"\alpha": "alpha", r"\beta": "beta", r"\gamma": "gamma", r"\lambda": "lambda_",
    r"\mu": "mu", r"\omega": "omega", r"\phi": "phi", r"\sigma": "sigma", r"\tau": "tau", r"\epsilon": "epsilon",
    r"\leq": "<=", r"\geq": ">=", r"\le": "<=", r"\ge": ">=", r"\,": " ", r"\;": " ", r"\!": "", r"\quad": " ",
}
_FRAC_RE = re.compile(r"\\[dt]?frac\s*\{([^{}]*)\}\s*\{([^{}]*)\}")
_SQRT_N_RE = re.compile(r"\\sqrt\s*\[([^\]]*)\]\s*\{([^{}]*)\}")
_SQRT_RE = re.compile(r"\\sqrt\s*\{([^{}]*)\}")
_INT_BOUNDS_RE = re.compile(r"\\int\s*_\s*\{?([^{}\s^]+)\}?\s*\^\s*\{?([^{}\s]+)\}?")
_LIM_RE = re.compile(r"\\?\blim\s*_\s*\{\s*([A-Za-z])\s*(?:\\to|->|\\rightarrow)\s*([^{}]+?)\s*\}")
_SUM_RE = re.compile(r"\\sum\s*_\s*\{\s*([A-Za-z])\s*=\s*([^{}]+?)\s*\}\s*\^\s*\{?([^{}\s]+)\}?")
_DERIV_RE = re.compile(r"\\[dt]?frac\s*\{\s*d(?:\^\{?(\d)\}?)?\s*\}\s*\{\s*d\s*([A-Za-z])(?:\^\{?\d\}?)?\s*\}")
_ABS_RE = re.compile(r"\|([^|]+)\|")
_FACTORIAL_RE = re.compile(r"\b(\d+|[A-Za-z])!(?!=)")
# "2xy", "3ab^2", "xy^2": juxtaposed single-letter symbols that implicit multiplication would read as one name.
# Only runs of 2-3 letters glued to a digit or followed by "^" are split, so prose ("is", "2nd") is untouched.
_JUXTA_RE = re.compile(r"(?<=\d)([a-z]{2,3})\b(?!\s*\()|\b([a-z]{2,3})(?=\^)")
_NOT_PRODUCTS = frozenset({
    "st", "nd", "rd", "th", "pi", "oo", "ln", "dx", "dy", "dt", "dz", "mod", "deg", "inf", "max", "min", "exp", "log",
    "sin", "cos", "tan", "cot", "sec", "csc", "abs", "erf",
})


# UTF-8 bytes decoded as cp1252: "×" arrives as "Ã—", "−" as "âˆ’".
_MOJIBAKE_RE = re.compile(r"[ÃÂâ][\x80-\xbfŒ-™]")


def repair_mojibake(text: str) -> str:
    """Undo one round of UTF-8-read-as-cp1252; text that does not round-trip cleanly is returned unchanged."""
    if not _MOJIBAKE_RE.search(text):
        return text
    try:
        return text.encode("cp1252").decode("utf-8")
    except UnicodeError:
        return text


def normalize_math_text(text: str) -> str:
    """LaTeX and Unicode math to the plain syntax safe_parse_expr reads; prose is left in place."""
    out = repair_mojibake(str(text or ""))
    # "ωt" is omega times t, not a symbol "omegat": a Greek letter followed by a letter or digit gets a space.
    out = re.sub(r"([θαβγλμωφστεδ])(?=[A-Za-z0-9])", r"\1 ", out)
    for a, b in _UNICODE.items():
        out = out.replace(a, b)
    out = re.sub(r"\$+|\\\(|\\\)|\\\[|\\\]", " ", out)
    # Typeset prose and spacing (a transcribed image or a pasted LaTeX question): "\text{ kg}" -> "kg", "\," -> " ".
    out = re.sub(r"\\(?:text|textrm|mathrm|mathsf|mathit|mbox)\s*\{([^{}]*)\}", r" \1 ", out)
    out = re.sub(r"\\[,;:! ]|~", " ", out)
    # Newton's dot notation for time derivatives: \ddot{x} -> x'', \dot{x} -> x'.
    out = re.sub(r"\\dddot\s*\{?\s*([A-Za-z])\s*\}?", r" \1'''", out)
    out = re.sub(r"\\ddot\s*\{?\s*([A-Za-z])\s*\}?", r" \1''", out)
    out = re.sub(r"\\dot\s*\{?\s*([A-Za-z])\s*\}?", r" \1'", out)
    out = _DERIV_RE.sub(lambda m: f" d^{m.group(1)}/d{m.group(2)}^{m.group(1)} " if m.group(1) else f" d/d{m.group(2)} ", out)
    out = re.sub(r"\\[lr]?vert\b|\\[lr]Vert\b|\\mid\b", "|", out)
    out = _INT_BOUNDS_RE.sub(lambda m: f" integrate from {m.group(1)} to {m.group(2)} of ", out)
    out = _LIM_RE.sub(lambda m: f" limit as {m.group(1)} -> {m.group(2)} of ", out)
    out = _SUM_RE.sub(lambda m: f" sum for {m.group(1)} from {m.group(2)} to {m.group(3)} of ", out)
    out = out.replace(r"\int", " integrate ").replace(r"\lim", " limit ").replace(r"\sum", " sum ")
    for _ in range(6):  # nested fractions resolve innermost first
        # "x^{2}" inside a fraction's braces ("\frac{4x^{2}}{...}") would keep _FRAC_RE from matching.
        new = re.sub(r"\^\s*\{([^{}]*)\}", r"^(\1)", out)
        new = _FRAC_RE.sub(r"((\1)/(\2))", new)
        new = _SQRT_N_RE.sub(r"root(\2, \1)", new)
        new = _SQRT_RE.sub(r"sqrt(\1)", new)
        if new == out:
            break
        out = new
    out = re.sub(r"\\(?:left|right|big|Big|bigg|Bigg)\b", "", out)
    for a, b in sorted(_LATEX_SYMBOLS.items(), key=lambda kv: -len(kv[0])):
        out = out.replace(a, b)
    for fn in _LATEX_FUNCS:
        # "F_0\cos(" -> "F_0 cos(": the name must not fuse with the symbol before it.
        out = re.sub(rf"(?<=[\w)])\\{fn}\b", f" {fn}", out)
        out = re.sub(rf"\\{fn}\b", fn, out)
    out = re.sub(r"\\operatorname\{([^{}]*)\}", r"\1", out)
    out = out.replace("{", "(").replace("}", ")")
    for _ in range(3):  # |x - 3| -> Abs(x - 3)
        new = _ABS_RE.sub(r"Abs(\1)", out)
        if new == out:
            break
        out = new
    out = _FACTORIAL_RE.sub(r"factorial(\1)", out)
    out = _JUXTA_RE.sub(lambda m: m.group(0) if m.group(0) in _NOT_PRODUCTS else "*".join(m.group(0)), out)
    # sin x / cos 2x -> sin(x) / cos(2x) when no parenthesis follows the function name
    out = re.sub(
        r"\b(sin|cos|tan|cot|sec|csc|sinh|cosh|tanh|ln|log|exp|arcsin|arccos|arctan)\s+([0-9]*[A-Za-z](?:\^[0-9]+)?)\b",
        r"\1(\2)",
        out,
    )
    return re.sub(r"\s+", " ", out).strip()


# Question framing ---------------------------------------------------------------------------------------------------

# The header the pipeline writes before an attached image's transcription (tribos.vision.reader.image_context_block).
_ATTACHMENT_RE = re.compile(r"Attached image \d+ \([^)\n]*\), transcribed:[ \t]*", re.I)
# A source label, not part of the problem: "IMO 1960 Problem 2", "# Problem 5", "Exercise 3.4:", "Putnam 2019 A1.".
_LABEL = (
    r"(?:[A-Z][\w'&.\-]*\s+){0,4}(?:(?:1[89]|20)\d{2}\s*,?\s+)?"
    r"(?:(?:Problem|Question|Exercise|Example|Task|Q)\s*\.?\s*\d+[a-z]?(?:\.\d+)*|[AB][1-6])"
)
_LABEL_END = r"[ \t]*(?:[.:)](?:\*\*)?|\*\*[ \t]*[.:)]?)"  # "2.", "2:", "2.**", "2**", "2**:"
_LABEL_LINE_RE = re.compile(rf"^[ \t]*#{{0,6}}[ \t]*(?:\*\*)?{_LABEL}(?:{_LABEL_END})?[ \t]*$", re.M)
_LABEL_PREFIX_RE = re.compile(rf"^[ \t]*#{{0,6}}[ \t]*(?:\*\*)?{_LABEL}{_LABEL_END}[ \t]+(?=\S)", re.M)


def strip_question_framing(text: str) -> str:
    """The question without framing that is not part of the problem: attachment headers and source labels. Their
    numbers ("1960", "2", the image index) and words ("transcribed") would otherwise be read as part of the task."""
    out = _ATTACHMENT_RE.sub("", str(text or ""))
    out = _LABEL_LINE_RE.sub("", out)
    return _LABEL_PREFIX_RE.sub("", out)


# Expression extraction ----------------------------------------------------------------------------------------------

_GREEK = frozenset({
    "alpha", "beta", "gamma", "delta", "epsilon", "zeta", "eta", "theta", "iota", "kappa", "lambda_", "mu", "nu",
    "xi", "omicron", "rho", "sigma", "tau", "upsilon", "phi", "chi", "psi", "omega",
})
_NUMBER_WORDS = {"first": 1, "second": 2, "third": 3, "fourth": 4, "fifth": 5, "sixth": 6}
_WORD_INT = {"two": 2, "three": 3, "four": 4, "five": 5, "six": 6}


def plausible_symbol(name: str) -> bool:
    """A free symbol a person would write (x, t, x1, x_0, theta) rather than an English word that implicit
    multiplication turned into a product of symbols ("roots of x" -> roots*of*x)."""
    if len(name) == 1 or name in _GREEK:
        return True
    return bool(re.fullmatch(r"[A-Za-z](?:_?[A-Za-z0-9]{1,3})", name)) and bool(re.search(r"[0-9_]", name))


def _plausible(expr: sp.Basic) -> bool:
    syms = getattr(expr, "free_symbols", set())
    if isinstance(expr, sp.Basic) and expr.atoms(AppliedUndef):
        return False  # "Solve (x^2 - 1)" read as a function named Solve: a word glued to the math, not notation
    return all(plausible_symbol(getattr(s, "name", "")) for s in syms)


_MATH_WORDS = frozenset({
    "sin", "cos", "tan", "cot", "sec", "csc", "asin", "acos", "atan", "sinh", "cosh", "tanh", "exp", "log", "ln",
    "sqrt", "cbrt", "abs", "pi", "oo", "inf", "gamma", "erf", "floor", "ceiling", "factorial", "binomial", "root",
    "arcsin", "arccos", "arctan", "derivative", "integral", "sum", "eq", "max", "min", "sign",
})


def _wordy(token: str) -> bool:
    """A plain English word: never the first or last token of a mathematical span."""
    core = token.strip(".,;:?!()[]{}\"'")
    return len(core) >= 3 and core.isalpha() and core.lower() not in _MATH_WORDS and core not in _GREEK


def _try_parse(text: str, *, equation: bool) -> str | None:
    text = text.strip().strip(".,;:?!").strip()
    if not text or len(text) > 2000 or (equation and "=" not in text):
        return None
    try:
        if equation:
            lhs, rhs, _ = safe_parse_equation(text)
            ok = _plausible(lhs) and _plausible(rhs)
        else:
            if "=" in text.replace("==", "=").replace("<=", "").replace(">=", ""):
                return None
            parsed = safe_parse_expr(text)
            if isinstance(parsed, sp.core.relational.Relational):
                return None  # "a < b" is an inequality (its own task kind), never an expression to solve or simplify
            ok = _plausible(parsed)
    except (ValueError, TypeError, SyntaxError, sp.SympifyError):
        return None
    except Exception:  # noqa: BLE001 - sympy raises assorted errors on prose
        return None
    return text if ok else None


# A sentence ends at ., ?, ! or ; followed by space and a capital ("... - 2^3. Show every step"); a decimal point is
# never followed by a space, so "2.5 x" is not split.
_SENTENCE_END_RE = re.compile(r"(?<=[^\s.])[.?!;]\s+(?=[A-Z])")


def extract_math(text: str, *, equation: bool = False, max_trim: int = 10) -> str | None:
    """The longest span of text that parses as an expression (or an 'lhs = rhs' equation) with plausible
    symbols, found by trimming leading and trailing words. Each sentence is tried on its own first, so
    instructions written after the expression ("Show every step, simplify the fraction, ...") never push it
    beyond the trimming limit."""
    sentences = [s for s in _SENTENCE_END_RE.split(text) if s.strip()]
    if len(sentences) > 1:
        for sentence in sentences:
            got = _extract_span(sentence, equation=equation, max_trim=max_trim)
            if got is not None:
                return got
    return _extract_span(text, equation=equation, max_trim=max_trim)


def _extract_span(text: str, *, equation: bool, max_trim: int) -> str | None:
    words = text.split()
    if not words:
        return None
    n = len(words)
    # Spans start and end on math-looking tokens only: "derive the main result" never reaches the parser.
    starts = [i for i in range(min(n, max_trim + 1)) if not _wordy(words[i])]
    ends = [j for j in range(n, max(0, n - max_trim - 1), -1) if not _wordy(words[j - 1])]
    for i in starts:
        for j in ends:
            if j <= i:
                break
            got = _try_parse(" ".join(words[i:j]), equation=equation)
            if got is not None:
                return got
    return None


_STOP_RE = re.compile(
    r"\s(?:with respect to|w\.?r\.?t\.?|from|between|over|as|around|about|near|for|up to|to order|where|given|"
    r"subject to|on the interval|in the interval|if|when|and verify|and check|and show)\s",
    re.I,
)


def _head(text: str) -> str:
    """text up to the first clause keyword (bounds, variables, conditions follow it)."""
    m = _STOP_RE.search(" " + text + " ")
    return text[: max(0, m.start() - 1)] if m else text


def _strip_differential(text: str) -> tuple[str, str | None]:
    m = re.search(r"\s*(?:\*\s*)?\bd\s*([A-Za-z])\s*$", text)
    if m:
        return text[: m.start()], m.group(1)
    return text, None


def _explicit_variable(text: str) -> str | None:
    for pat in (
        r"with respect to\s+([A-Za-z])\b", r"\bw\.?r\.?t\.?\s+([A-Za-z])\b", r"\bd/d([A-Za-z])\b",
        r"\bfor\s+([A-Za-z])\b(?!\s*(?:=|from))", r"\bin\s+([A-Za-z])\b\s*$",
    ):
        m = re.search(pat, text, re.I)
        if m:
            return m.group(1)
    return None


def _pick_variable(source: str, explicit: str | None, spec: ProblemSpec) -> str | None:
    if explicit:
        return explicit
    try:
        if "=" in source:
            lhs, rhs, _ = safe_parse_equation(source)
            syms = sorted({s.name for s in lhs.free_symbols | rhs.free_symbols})
        else:
            syms = sorted(s.name for s in safe_parse_expr(source).free_symbols)
    except Exception:  # noqa: BLE001
        return None
    if len(syms) == 1:
        return syms[0]
    for pref in ("x", "t", "z", "n", "k"):
        if pref in syms:
            spec.ambiguities.append(f"several symbols ({', '.join(syms)}); took {pref} as the variable")
            return pref
    if syms:
        spec.ambiguities.append(f"several symbols ({', '.join(syms)}); took {syms[0]} as the variable")
        return syms[0]
    return None


def _domain_and_assumptions(low: str, spec: ProblemSpec) -> None:
    if re.search(r"\breals?\b|\bin r\b|\bover r\b|ℝ", low):
        spec.domain = "real"
    for m in re.finditer(r"\b([a-z])\s*>\s*0\b", low):
        spec.assumptions[m.group(1)] = "positive"
        spec.domain = "real"
    for m in re.finditer(r"\b([a-z])\s*>=\s*0\b", low):
        spec.assumptions.setdefault(m.group(1), "nonnegative")
    # "for positive x and y", "positive real numbers a, b"
    for m in re.finditer(r"\bpositive\s+(?:real\s+)?(?:numbers?\s+|values?\s+)?([a-z](?:\s*(?:,|and)\s*[a-z]\b)*)", low):
        for name in re.findall(r"\b[a-z]\b", m.group(1)):
            spec.assumptions[name] = "positive"
    for m in re.finditer(r"\b([a-z])\s+(?:is|are)\s+(?:a\s+)?positive\b", low):
        spec.assumptions[m.group(1)] = "positive"
    for m in re.finditer(r"\b([a-z])\s+(?:is|are)\s+(?:an?\s+)?(?:integer|natural)", low):
        spec.assumptions[m.group(1)] = "integer"


# Task parsers ---------------------------------------------------------------------------------------------------

def _parse_matrix(text: str) -> list[list[str]] | None:
    m = re.search(r"\[\s*\[.*?\]\s*\]", text, re.S)
    if m:
        rows = re.findall(r"\[([^\[\]]*)\]", m.group(0))
        out = [[c.strip() for c in row.split(",") if c.strip()] for row in rows]
        if out and all(len(r) == len(out[0]) and r for r in out):
            return out
    m = re.search(r"\[([^\[\]]+;[^\[\]]+)\]", text)  # MATLAB style [1 2; 3 4]
    if m:
        out = [[c for c in re.split(r"[\s,]+", row.strip()) if c] for row in m.group(1).split(";")]
        if out and all(len(r) == len(out[0]) and r for r in out):
            return out
    return None


def _parse_linalg(text: str, low: str, spec: ProblemSpec) -> bool:
    matrix = _parse_matrix(text)
    if matrix is None:
        return False
    spec.kind, spec.matrix = "linalg", matrix
    table = (
        ("charpoly", r"characteristic polynomial"), ("eigen", r"eigen"), ("det", r"determinant|\bdet\b"),
        ("inv", r"inverse|invert"), ("svd", r"singular value|\bsvd\b"), ("nullspace", r"null ?space|kernel"),
        ("rref", r"row.?reduc|echelon|\brref\b|\brank\b"), ("solve", r"\bsolve\b|\bax\s*=\s*b\b"),
    )
    spec.linalg_op = next((op for op, pat in table if re.search(pat, low)), None)
    if spec.linalg_op == "solve" or re.search(r"\bb\s*=\s*\[", low):
        vec = re.search(r"\bb\s*=\s*\[([^\[\]]+)\]", text) or re.search(r"\]\s*\]\s*[^\[]*\[([^\[\]]+)\]", text)
        if vec:
            spec.linalg_op = "solve"
            spec.rhs_vector = [c.strip() for c in re.split(r"[,\s]+", vec.group(1)) if c.strip()]
    if spec.linalg_op is None:
        spec.linalg_op = "eigen"
        spec.ambiguities.append("no matrix operation named; computed eigenvalues and eigenvectors")
    return True


def _parse_ode(text: str, low: str, spec: ProblemSpec) -> bool:
    # Leibniz notation names the independent variable: dy/dt -> y' with t as the variable
    leibniz = re.search(r"\bd\^?\d?\s*[a-z]\s*/\s*d([a-z])\b", text)
    t = re.sub(r"\bd\^?2\s*([a-z])\s*/\s*d([a-z])\^?2", r"\1''", text)
    t = re.sub(r"\bd([a-z])\s*/\s*d([a-z])\b", r"\1'", t)
    fm = re.search(r"\b([a-z])('+)\s*(?:\(\s*([a-z])\s*\))?", t)
    if not fm or ("=" not in t and "differential" not in low):
        return False
    fname = fm.group(1)
    # x(t) is the usual physics notation: an unknown named x with no stated variable depends on t, never on itself.
    var = fm.group(3) or (leibniz.group(1) if leibniz else None) or (
        "t" if re.search(r"\bt\b", t) or fname == "x" else "x"
    )
    pieces = re.split(r"[,;]|\band\b|\bwith\b|\bgiven\b|\bwhere\b|\bsubject to\b", t)
    main = None
    params: dict[str, str] = {}
    for piece in pieces:
        p = piece.strip()
        ic = re.fullmatch(rf"{fname}('*)\s*\(\s*([-+0-9.]+|pi)\s*\)\s*=\s*(.+)", p)
        if ic:
            # "x(0) = 0.1 m": the value, without its unit (a unit read as a symbol would change the condition).
            number = re.match(rf"\s*({_NUM_VALUE})\b(?:\s*[A-Za-z][A-Za-z/*^\d\s.]*)?\s*\.?\s*$", ic.group(3))
            val = number.group(1) if number else (extract_math(ic.group(3)) or ic.group(3).strip(" ."))
            spec.ics[f"{fname}{ic.group(1)}({ic.group(2)})"] = val
            continue
        # "m = 2 kg", "omega = 4 rad/s": a given parameter value, substituted into the equation below.
        given = re.fullmatch(rf"([A-Za-z][A-Za-z0-9_]{{0,7}})\s*=\s*({_NUM_VALUE})(?:\s*[A-Za-z][A-Za-z/*^\d\s.]*)?\.?", p)
        if given and given.group(1) not in (fname, var):
            params[given.group(1)] = given.group(2)
            continue
        if main is None and re.search(rf"\b{fname}'", p):
            words = re.sub(r"^.*?\b(?:solve|equation|ode)\b:?", "", p, flags=re.I).strip()
            main = words or p
    if main is None:
        return False
    main = re.sub(r"^(?:the\s+)?(?:differential\s+)?(?:equation\s+)?", "", main.strip(), flags=re.I)
    # Prose before the equation ("Investigate a forced damped system governed by m x'' + ...") is not part of it.
    main = re.sub(r"^.*?\b(?:governed|given|described|modell?ed|defined)\s+by\b:?", "", main, flags=re.I).strip()
    # A sentence before the equation ("... in the attached image. Attached image 1 (q.png), transcribed: m x'' + ...")
    # ends at its last ". " / ": " before the "=" (a decimal point is never followed by a space).
    breaks = [m.end() for m in re.finditer(r"[.:?!]\s+", main[: main.find("=")] if "=" in main else main)]
    if breaks:
        main = main[breaks[-1]:]
    while re.match(r"^(?:an?|[A-Za-z][A-Za-z\-]+)\s+(?=\S)", main) and not re.match(rf"^{fname}'", main):
        lead = re.match(r"^(\S+)\s+", main)
        if lead is None or lead.group(1) in params or _plausible_coefficient(lead.group(1)):
            break
        main = main[lead.end():]
    for name, value in params.items():
        # "kx" is k times x: split a parameter name from the unknown it multiplies, then substitute the value.
        main = re.sub(rf"(?<![A-Za-z0-9_]){re.escape(name)}(?={fname}(?:\b|'|\())", f"{name} ", main)
        main = re.sub(rf"(?<![A-Za-z0-9_]){re.escape(name)}(?![A-Za-z0-9_])", f"({value})", main)
    if params:
        spec.handled.update(params)
        spec.params = {"given_values": dict(params)}  # recorded for the reader and the fidelity check
    if "=" not in main:
        main = main + " = 0"
    spec.kind, spec.func, spec.variable = "ode", f"{fname}({var})", var
    spec.expression = main.strip(" .")
    return True


_NUM_VALUE = r"[-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][-+]?\d+)?"


def _plausible_coefficient(token: str) -> bool:
    """A leading token that starts the equation rather than the prose before it ("m", "2", "F0", "omega")."""
    return len(token) <= 2 or bool(re.match(r"^[A-Za-z]\d|^\d|^(?:omega|alpha|beta|gamma|zeta|lambda_|mu|tau|theta)$", token))


def _parse_identity(text: str, low: str, spec: ProblemSpec) -> bool:
    # "For which x is x^3 = 8?" and "find x such that ..." ask for solutions, not about an identity.
    if re.search(r"\bfor (?:which|what)\b|\bwhat values?\b|\bfind\b|\bsolve\b|\broots?\b|\bsolutions?\b", low):
        return False
    m = re.search(r"\b(?:prove|show|verify|check|confirm|is it true|determine whether|is)\b(?:\s+(?:that|whether|if))?\s+(.+)", text, re.I)
    if not m or "=" not in m.group(1):
        return False
    body = re.sub(r"\s*\b(?:for|where|when|whenever|if|holds|is an identity|an identity|is true|identically)\b.*$", "", m.group(1), flags=re.I)
    eq = extract_math(body, equation=True)
    if eq is None:
        return False
    spec.kind, spec.expression = "identity", eq
    return True


def _parse_limit(text: str, low: str, spec: ProblemSpec) -> bool:
    if not re.search(r"\blim(?:it)?\b", low):
        return False
    m = re.search(r"\b([a-z])\s*(?:->|tends to|approaches|goes to|to)\s*([-+]?\s*(?:oo|inf(?:inity)?|[0-9.]+|pi|[a-z]))\s*(\+|-|from the right|from the left|from above|from below)?", text, re.I)
    if not m:
        return False
    spec.variable = m.group(1)
    pt = m.group(2).replace(" ", "").lower()
    pt = {"inf": "oo", "infinity": "oo", "+oo": "oo", "+inf": "oo", "-inf": "-oo", "-infinity": "-oo"}.get(pt, pt)
    side = (m.group(3) or "").lower()
    if side in ("+", "from the right", "from above"):
        pt += "+"
    elif side in ("-", "from the left", "from below"):
        pt += "-"
    spec.point = pt
    rest = (text[: m.start()] + " " + text[m.end():]).strip()
    rest = re.sub(r"(?i)\b(?:find|compute|evaluate|calculate|what is|determine)\b|\blim(?:it)?\b|\bas\b|\bof\b|\bthe\b", " ", rest)
    expr = extract_math(rest)
    if expr is None:
        return False
    spec.kind, spec.expression = "limit", expr
    return True


def _parse_series(text: str, low: str, spec: ProblemSpec) -> bool:
    if not re.search(r"taylor|maclaurin|power series|series expansion|\bseries\b|expand .* (?:around|about|near|at)", low):
        return False
    m = re.search(r"\b(?:around|about|near|at)\s+([a-z])?\s*=?\s*([-+]?[0-9.]+|pi|oo)", text, re.I)
    spec.point = m.group(2) if m else "0"
    if not m and "maclaurin" not in low:
        spec.ambiguities.append("no expansion point given; expanded about 0")
    om = re.search(r"(?:order|degree)\s*(\d+)|(\d+)\s*(?:terms|th order)|up to\s+[a-z]\s*\^\s*(\d+)", low)
    if om:
        if om.group(3):
            spec.order = int(om.group(3)) + 1
        elif om.group(2):
            spec.order = int(om.group(2))
        else:
            spec.order = int(om.group(1)) + 1
            spec.ambiguities.append(f"read 'order {om.group(1)}' as terms through power {om.group(1)}")
    else:
        spec.order = 6
    body = re.sub(r"(?i)^.*?\b(?:series|expansion|expand)\b(?:\s+(?:of|for))?", "", text)
    body = re.sub(r"(?i)\b(?:around|about|near|at|up to|to order|of order|order|degree)\b.*$", "", body)
    expr = extract_math(body)
    if expr is None:
        return False
    spec.kind, spec.expression = "series", expr
    spec.variable = _pick_variable(expr, (m.group(1) if m else None) or _explicit_variable(text), spec)
    return True


def _bounds(text: str) -> tuple[str | None, str | None]:
    for pat in (
        r"\bfrom\s+([a-z]\s*=\s*)?(.+?)\s+to\s+(.+?)(?=\s+(?:of|with|dx|dt|for|and)\b|[,.?]?\s*$)",
        r"\bbetween\s+(.+?)\s+and\s+(.+?)(?=\s+(?:of|with|for)\b|[,.?]?\s*$)",
        r"\bover\s+\[\s*([^,\]]+)\s*,\s*([^\]]+)\]",
    ):
        m = re.search(pat, text, re.I)
        if m:
            g = [x for x in m.groups() if x is not None and not re.fullmatch(r"[a-z]\s*=\s*", x)]
            lo, hi = g[-2].strip(" ,."), g[-1].strip(" ,.")
            lo = {"infinity": "oo", "inf": "oo", "-infinity": "-oo", "-inf": "-oo"}.get(lo.lower(), lo)
            hi = {"infinity": "oo", "inf": "oo", "-infinity": "-oo", "-inf": "-oo"}.get(hi.lower(), hi)
            return lo, hi
    return None, None


def _parse_integral(text: str, low: str, spec: ProblemSpec) -> bool:
    area = re.search(r"\barea (?:under|beneath|below)\b(?:\s+the\s+(?:curve|graph))?(?:\s+of)?", low)
    if not (area or re.search(r"\bintegra(?:te|l)\b|antiderivative|\bprimitive\b", low)):
        return False
    spec.lower, spec.upper = _bounds(text)
    if area:
        if spec.lower is None:
            return False
        spec.handled.add("area")
        spec.ambiguities.append("area computed as the definite integral (equal to the geometric area where the curve is above the axis)")
        body = text[area.end():]
        body = re.sub(r"^\s*(?:y|f\s*\(\s*[a-z]\s*\))\s*=", "", body)  # "y = x^3", "f(x) = ..."
    else:
        body = re.sub(r"(?i)^.*?\b(?:integrate|integral|antiderivative|primitive)\b(?:\s+of)?", "", text)
    body = re.sub(r"(?i)\bfrom\b.*?\bof\b", " ", body)  # "from 0 to 1 of f" (LaTeX-normalized form)
    body, dvar = _strip_differential(_head(body).strip(" ,.?"))
    expr = extract_math(body)
    if expr is None:
        return False
    spec.kind, spec.expression = "integrate", expr
    spec.variable = _pick_variable(expr, dvar or _explicit_variable(text), spec)
    return True


def _parse_derivative(text: str, low: str, spec: ProblemSpec) -> bool:
    m = re.search(r"\bd\^?(\d)?\s*/\s*d([a-z])\^?(\d)?", text)
    if not (m or re.search(r"\bderivative\b|\bdifferentiate\b|\bderive\b", low)):
        return False
    order = 1
    for word, n in _NUMBER_WORDS.items():
        if re.search(rf"\b{word}\s+(?:order\s+)?derivative", low):
            order = n
    times = re.search(r"\b(twice|thrice|(\d+|two|three|four|five|six)\s+times)\b", low)
    if times:
        order = {"twice": 2, "thrice": 3}.get(times.group(1)) or _WORD_INT.get(times.group(2), 0) or int(times.group(2))
        spec.handled.update({times.group(1), "times"})
    if m and (m.group(1) or m.group(3)):
        order = int(m.group(1) or m.group(3))
    on = re.search(r"\b(\d+)(?:st|nd|rd|th)\s+(?:order\s+)?derivative", low)
    if on:
        order = int(on.group(1))
    spec.order = order
    body = text[m.end():] if m else re.sub(r"(?i)^.*?\b(?:derivative|differentiate|derive)\b(?:\s+of)?", "", text)
    body = re.sub(r"(?i)\s*\b(?:twice|thrice|(?:\d+|two|three|four|five|six)\s+times)\b", "", body)
    body = re.sub(r"^\s*(?:[a-z]\s*\(\s*[a-z]\s*\)\s*=)", "", _head(body).strip(" ,.?"))  # f(x) = ...
    expr = extract_math(body)
    if expr is None:
        return False
    spec.kind, spec.expression = "differentiate", expr
    spec.variable = _pick_variable(expr, (m.group(2) if m else None) or _explicit_variable(text), spec)
    return True


def _parse_sum(text: str, low: str, spec: ProblemSpec) -> bool:
    if not re.search(r"\bsum\b|\bsummation\b|\bseries\b", low):
        return False
    m = re.search(r"\b(?:for\s+)?([a-z])\s*(?:=|from)\s*([-+]?\w+)\s*(?:to|\.\.)\s*([-+]?\w+)", text, re.I)
    if not m:
        return False
    var, lo, hi = m.group(1), m.group(2), m.group(3)
    hi = {"infinity": "oo", "inf": "oo"}.get(hi.lower(), hi)
    rest = (text[: m.start()] + " " + text[m.end():])
    rest = re.sub(r"(?i)\b(?:find|compute|evaluate|calculate|what is|the|sum|summation|of|from|for)\b", " ", rest)
    expr = extract_math(rest)
    if expr is None:
        return False
    spec.kind, spec.expression, spec.variable, spec.lower, spec.upper = "sum", expr, var, lo, hi
    return True


def _parse_solve(text: str, low: str, spec: ProblemSpec) -> bool:
    asks = re.search(r"\bsolve\b|\broots?\b|\bzeros?\b|\bsolutions?\b|\bfind (?:all )?(?:real |complex )?(?:values of )?[a-z]\b", low)
    has_eq = "=" in text.replace("<=", "").replace(">=", "").replace("->", "")
    if not asks and not has_eq:
        return False
    body = re.sub(r"(?i)^.*?\b(?:solve|roots? of|zeros? of|solutions? (?:of|to)|find (?:all )?(?:real |complex )?(?:values of )?[a-z](?: such that| with| for which| if)?)\b:?", "", text)
    body = re.sub(r"(?i)\s+(?:for|in)\s+([a-z](?:\s*(?:,|and)\s*[a-z])*)\s*[.?]?\s*$", "", body)
    body = re.sub(r"(?i)\b(?:where|with|given|subject to|if)\b\s+[a-z]\s*[<>]=?.*$", "", body)
    # inline constraints ("with x > 0 such that ...") are already recorded as assumptions
    body = re.sub(r"(?i)(?:\b(?:with|where|for|and)\s+)?\b[a-z]\s*(?:<=|>=|<|>)\s*[-+]?[\w.]+\s*(?:such that|so that|,)?", " ", body)
    body = re.sub(r"(?i)\b(?:over the reals|in the reals|real|the equation|the system|equations?|system)\b", " ", body)
    parts = [p for p in re.split(r";|,(?![^()\[\]]*[)\]])|\band\b", body) if p.strip()]
    eqs = [e for e in (extract_math(p, equation=True) for p in parts if "=" in p) if e]
    if len(eqs) >= 2:
        spec.kind, spec.equations = "solve", eqs
        vs = re.search(r"(?i)\bfor\s+([a-z](?:\s*(?:,|and)\s*[a-z])+)\s*[.?]?\s*$", text)
        spec.variables = re.findall(r"\b[a-z]\b", vs.group(1)) if vs else []
        return True
    eq = extract_math(body, equation=True) if has_eq else None
    if eq is None and asks:
        eq = extract_math(body)  # "roots of x^2 - 4" means = 0
    if eq is None:
        return False
    spec.kind, spec.expression = "solve", eq
    spec.variable = _pick_variable(eq, _explicit_variable(text), spec)
    if "Abs(" in eq and spec.domain == "complex":
        spec.domain = "real"
        spec.ambiguities.append("absolute values: solved over the real numbers")
    return True


def _parse_simplify(text: str, low: str, spec: ProblemSpec) -> bool:
    if not re.search(r"\bsimplify\b|\bfactor(?:ise|ize)?\b|\bexpand\b|\breduce\b|\bcancel\b", low):
        return False
    body = re.sub(r"(?i)^.*?\b(?:simplify|factor(?:ise|ize)?|expand|reduce|cancel)\b(?:\s+(?:the\s+)?(?:expression|fraction))?", "", text)
    expr = extract_math(_head(body).strip(" ,.?"))
    if expr is None:
        return False
    spec.kind, spec.expression = "simplify", expr
    if re.search(r"\bfactor", low):
        spec.form = "factor"
    elif re.search(r"\bexpand\b", low):
        spec.form = "expand"
    return True


def _parse_evaluate(text: str, low: str, spec: ProblemSpec) -> bool:
    body = re.sub(r"(?i)^.*?\b(?:evaluate|compute|calculate|what is|what's|find the value of|value of)\b", "", text)
    if "=" in body:  # "... in sample = 4" is an assignment, not something to evaluate
        return False
    if "%" in body:  # "15% of 80" -> (15/100)*80
        body = re.sub(r"(\d+(?:\.\d+)?)\s*%\s*of\s+", r"(\1/100)*", body)
        body = re.sub(r"(\d+(?:\.\d+)?)\s*%", r"(\1/100)", body)
        spec.handled.update({"%", "percent"})
    expr = extract_math(body.strip(" ,.?"))
    if expr is None or not re.search(r"[-+*/^!(]", expr.lstrip("-+")):  # a bare number or symbol is not a computation
        return False
    try:
        if safe_parse_expr(expr).free_symbols:
            return False
    except ValueError:
        return False
    spec.kind, spec.expression = "evaluate", expr
    return True


# Extended task kinds ------------------------------------------------------------------------------------------------

_NUM = r"[-+]?\d+(?:\.\d+)?(?:/\d+)?"


def _strip_function_prefix(body: str) -> str:
    """'y = x^3', 'f(x) = sin x', 'the curve y = ...', 'the function ...' -> the expression part."""
    body = re.sub(r"(?i)^\s*(?:the\s+)?(?:curve|graph|function|parabola)?\s*(?:of\s+)?", "", body)
    return re.sub(r"^\s*(?:y|[a-z]\s*\(\s*[a-z]\s*\))\s*=\s*", "", body)


def _parse_optimize(text: str, low: str, spec: ProblemSpec) -> bool:
    cue = re.search(r"\b(maximum|minimum|maximi[sz]e|minimi[sz]e|largest value|smallest value|greatest value|least value|extrem(?:a|um|e values?)|absolute (?:max|min)\w*|global (?:max|min)\w*)\b", low)
    if not cue:
        return False
    word = cue.group(1)
    goal = "max" if re.search(r"max|largest|greatest", word) else "min" if re.search(r"min|smallest|least", word) else "both"
    if re.search(r"\bmaximum and minimum\b|\bminimum and maximum\b|\bextrem", low):
        goal = "both"
    lower = upper = None
    lo_open = hi_open = False
    iv = re.search(r"\[\s*([^,\[\]]+?)\s*,\s*([^\[\]]+?)\s*\]", text)
    rng = re.search(rf"({_NUM}|pi)\s*(<=|<)\s*([a-z])\s*(<=|<)\s*({_NUM}|pi)", text)
    one = re.search(rf"\b([a-z])\s*(>=|>|<=|<)\s*({_NUM})", text)
    if iv:
        lower, upper = iv.group(1), iv.group(2)
    elif rng:
        lower, upper, lo_open, hi_open = rng.group(1), rng.group(5), rng.group(2) == "<", rng.group(4) == "<"
    elif one:
        if one.group(2).startswith(">"):
            lower, lo_open = one.group(3), one.group(2) == ">"
        else:
            upper, hi_open = one.group(3), one.group(2) == "<"
    body = text[cue.end():]
    body = re.sub(r"(?i)^\s*(?:value|values|point|points)?\s*(?:of)?\s*", "", body)
    body = re.split(r"(?i)\s+(?:on|over|in|for|where|when|subject to|with)\b|\s*\[|\s*,", body)[0]
    expr = extract_math(_strip_function_prefix(body).strip(" ,.?"))
    if expr is None:
        return False
    spec.kind, spec.expression = "optimize", expr
    spec.variable = _pick_variable(expr, None, spec) or "x"
    spec.lower, spec.upper = lower, upper
    spec.params = {"goal": goal, "lower_open": lo_open, "upper_open": hi_open}
    spec.assumptions = {}  # the interval carries the constraint
    spec.handled.update({"maximum", "minimum", "maximi", "minimi", "extrem"})
    return True


def _parse_inequality(text: str, low: str, spec: ProblemSpec) -> bool:
    if not re.search(r"(?<![-<>])(<=|>=|<|>)(?!-)", text) or re.search(r"(?<![<>!])=(?!=)", text.replace("<=", "").replace(">=", "")):
        return False
    body = re.sub(r"(?i)^.*?\b(?:for (?:which|what)(?: real)?(?: values? of)?\s+[a-z]\s+(?:is|are|does|do)\b|solve|find all|find|when is|where is|determine where|values? of [a-z] (?:for which|such that|with))\b", "", text)
    body = re.sub(r"(?i)\b(?:the inequality|values? of [a-z]|real numbers?|is|are|such that|satisfy|satisfying|holds?)\b", " ", body)
    words = body.split()
    from .analysis import parse_inequality

    n = len(words)
    rel_at = [k for k, w in enumerate(words) if re.search(r"<=|>=|<|>", w)]
    if not rel_at:
        return False
    first, last = rel_at[0], rel_at[-1]
    # Spans start near the body's start or shortly before the relation, and end near the body's end or shortly after
    # it: a heading or sentence before the inequality ("Attached image 1 ... Solve") never pushes it out of reach.
    starts = sorted({*range(min(n, 8)), *range(max(0, first - 16), first + 1)})
    ends = sorted({*range(n, max(0, n - 8), -1), *range(min(n, last + 17), last, -1)}, reverse=True)
    for i in starts:
        if i > first or (_wordy(words[i]) and not re.search(r"<|>", words[i])):
            continue
        for j in ends:
            if j <= last:
                break
            cand = " ".join(words[i:j]).strip(" ,.?")
            if not re.search(r"<=|>=|<|>", cand):
                continue
            try:
                rel, x = parse_inequality(cand)
            except Exception:  # noqa: BLE001
                continue
            if _plausible(rel.lhs) and _plausible(rel.rhs):
                spec.kind, spec.expression, spec.variable = "inequality", cand, x.name
                spec.domain, spec.assumptions = "real", {}
                return True
    return False


def _parse_tangent(text: str, low: str, spec: ProblemSpec) -> bool:
    cue = re.search(r"\b(tangent(?: line)?|normal line|slope|rate of change|derivative)\b", low)
    at = re.search(rf"\bat\s+(?:the\s+point\s+)?(?:\(\s*({_NUM}|pi)\s*,[^)]*\)|(?:[a-z]\s*=\s*)?({_NUM}|pi(?:/\d+)?|e)\b)", text)
    if not cue or not at:
        return False
    if cue.group(1) == "derivative" and re.search(r"\b(second|third|twice|\d+(?:st|nd|rd|th))\b", low):
        return False  # higher derivatives at a point: not a tangent question
    want = "normal" if "normal" in low else "slope" if re.search(r"\bslope|rate of change|derivative", low) else "line"
    body = text[: at.start()]
    body = re.sub(r"(?i)^.*?\b(?:tangent(?: line)?|normal line|slope|rate of change|derivative)\b(?:\s+(?:line|of the tangent))?\s*(?:to|of)?\s*(?:the\s+(?:curve|graph|function)\s+)?", "", body)
    expr = extract_math(_strip_function_prefix(body).strip(" ,.?"))
    if expr is None:
        return False
    spec.kind, spec.expression = "tangent", expr
    spec.variable = _pick_variable(expr, None, spec) or "x"
    spec.point = at.group(1) or at.group(2)
    spec.params = {"want": want, "point": spec.point}
    spec.handled.update({"tangent", "slope", "normal line", "rate of change"})
    return True


def _parse_number_theory(text: str, low: str, spec: ProblemSpec) -> bool:
    ints = re.findall(r"(?<![\w.^])-?\d+(?![\w.])", text)
    op: str | None = None
    numbers: list[str] = []
    modulus: Any = None
    congr = re.findall(r"\b[a-z]\s*(?:≡|==?)\s*(\d+)\s*\(?\s*mod(?:ulo)?\s*(\d+)\s*\)?", text)
    m_pow = re.search(r"(\d+)\s*\^\s*(\d+)\s*(?:mod(?:ulo)?|%)\s*(\d+)", text) or re.search(r"remainder (?:when|of)\s+(\d+)\s*\^\s*(\d+)\s+(?:is\s+)?divided by\s+(\d+)", low)
    m_inv = re.search(r"inverse of\s+(\d+)\s+mod(?:ulo)?\s+(\d+)", low) or re.search(r"(\d+)\s*\^\s*\(?-1\)?\s*mod(?:ulo)?\s+(\d+)", text)
    dioph = re.search(r"(-?\d+)\s*\*?\s*x\s*([+-])\s*(\d+)\s*\*?\s*y\s*=\s*(-?\d+)", text)
    if len(congr) >= 2:
        op, numbers, modulus = "crt", [c[0] for c in congr], [c[1] for c in congr]
    elif m_pow:
        op, numbers, modulus = "mod_pow", [m_pow.group(1), m_pow.group(2)], m_pow.group(3)
    elif m_inv:
        op, numbers, modulus = "mod_inverse", [m_inv.group(1)], m_inv.group(2)
    elif dioph and re.search(r"\binteger", low):
        a, sign, b, c = dioph.groups()
        op, numbers = "diophantine", [a, ("-" if sign == "-" else "") + b, c]
    elif re.search(r"\b(?:gcd|greatest common divisor|highest common factor|hcf)\b", low) and len(ints) >= 2:
        op, numbers = "gcd", ints
    elif re.search(r"\b(?:lcm|least common multiple|lowest common multiple)\b", low) and len(ints) >= 2:
        op, numbers = "lcm", ints
    elif re.search(r"\b(?:totient|phi|φ)\b", low) and ints:
        op, numbers = "totient", ints[:1]
    elif re.search(r"\bnext prime\b|\bsmallest prime (?:greater|larger|bigger) than\b|\bfirst prime after\b", low) and ints:
        op, numbers = "next_prime", ints[:1]
    elif re.search(r"\bprime\b", low) and re.search(r"\bis\b|\bcheck\b|\bwhether\b", low) and len(ints) == 1 and not re.search(r"factori", low):
        op, numbers = "isprime", ints
    elif re.search(r"\bdivisors\b|\ball (?:the )?factors\b", low) and len(ints) == 1:
        op, numbers = "divisors", ints
    elif re.search(r"\bprime factori[sz]ation\b|\bfactori[sz]e\b|\bfactor\b", low) and len(ints) == 1 and re.search(r"(?:of|factor|factori[sz]e)\s+" + re.escape(ints[0]) + r"\b", low):
        op, numbers = "factorize", ints
    if op is None:
        return False
    spec.kind = "number_theory"
    spec.params = {"operation": op, "numbers": numbers, "modulus": modulus}
    spec.expression = f"{op}({', '.join(numbers)})"
    spec.handled.update({"mod", "modulo", "gcd", "lcm", "%"})
    return True


def _parse_recurrence(text: str, low: str, spec: ProblemSpec) -> bool:
    # a_{n-1} -> a(n-1); (?<![A-Za-z]) rather than \b so "3a_{n-1}" (coefficient glued to the name) converts too
    t = re.sub(r"(?<![A-Za-z])([A-Za-z])_\(?\s*([a-z](?:\s*[-+]\s*\d+)?|\d+)\s*\)?", r"\1(\2)", text)
    m = re.search(r"(?<![A-Za-z])([A-Za-z])\(\s*n\s*(?:[-+]\s*\d+)?\s*\)\s*=\s*[^,;]*(?<![A-Za-z])\1\(\s*n\s*-\s*\d+\s*\)", t)
    if not m:
        return False
    fname = m.group(1)
    initial: dict[str, str] = {}
    main = None
    for piece in re.split(r"[,;]|\band\b|\bwith\b|\bgiven\b|\bwhere\b", t):
        p = piece.strip(" .")
        ic = re.fullmatch(rf".*?(?<![A-Za-z]){fname}\(\s*(\d+)\s*\)\s*=\s*({_NUM})", p)
        if ic and "n" not in p.split("=")[0]:
            initial[f"{fname}({ic.group(1)})"] = ic.group(2)
        elif main is None and re.search(rf"(?<![A-Za-z]){fname}\(\s*n", p) and "=" in p:
            main = re.sub(r"(?i)^.*?\b(?:solve|recurrence|relation|sequence|defined by)\b:?\s*", "", p)
    if main is None or not initial:
        return False
    eq = extract_math(main, equation=True) if extract_math(main, equation=True) else main
    spec.kind, spec.expression, spec.variable = "recurrence", eq, "n"
    spec.params = {"recurrence": eq, "initial": initial, "function": fname, "variable": "n"}
    return True


def _parse_transform(text: str, low: str, spec: ProblemSpec) -> bool:
    m = re.search(r"\b(inverse laplace|laplace|fourier)(?: transform)?\b", low)
    if not m:
        return False
    kind = {"inverse laplace": "inverse_laplace", "laplace": "laplace", "fourier": "fourier"}[m.group(1)]
    body = re.sub(r"(?i)^\s*(?:transform)?\s*(?:of)?\s*", "", text[m.end():])
    body = re.sub(r"^\s*(?:[a-zA-Z]\s*\(\s*[a-z]\s*\)\s*=)", "", body)
    expr = extract_math(body.strip(" ,.?"))
    if expr is None:
        return False
    var = {"laplace": "t", "inverse_laplace": "s", "fourier": "x"}[kind]
    spec.kind, spec.expression, spec.variable = "transform", expr, var
    spec.params = {"transform": kind}
    return True


def _parse_vector_calculus(text: str, low: str, spec: ProblemSpec) -> bool:
    m = re.search(r"\b(gradient|divergence|curl|laplacian|hessian|jacobian)\b", low)
    if not m:
        return False
    op = m.group(1)
    rest = text[m.end():]
    vec = re.search(r"[\[(<]\s*([^\[\]()<>]+(?:\([^()]*\)[^\[\]()<>]*)*)\s*[\])>]", rest)
    params: dict[str, Any] = {"operation": op}
    if op in ("divergence", "curl", "jacobian"):
        if not vec or "," not in vec.group(1):
            return False
        comps = [c.strip() for c in re.split(r",(?![^()]*\))", vec.group(1))]
        if not all(_try_parse(c, equation=False) for c in comps):
            return False
        params["components"] = comps
        names = sorted({s.name for c in comps for s in safe_parse_expr(c).free_symbols})
    else:
        body = re.sub(r"(?i)^\s*(?:of)?\s*(?:the\s+)?(?:scalar\s+)?(?:field|function)?\s*", "", rest)
        body = re.sub(r"^\s*(?:[a-zA-Z]\s*(?:\([^)]*\))?\s*=)", "", body)
        expr = extract_math(_head(body).strip(" ,.?"))
        if expr is None:
            return False
        params["expression"] = expr
        names = sorted(s.name for s in safe_parse_expr(expr).free_symbols)
    order = [v for v in ("x", "y", "z") if v in names] or names
    if op == "curl":
        order = ["x", "y", "z"]
    elif len(order) < 2:
        order = ["x", "y", "z"][: max(2, len(order))]
    params["variables"] = order
    spec.kind, spec.params = "vector_calculus", params
    spec.expression = params.get("expression") or ", ".join(params["components"])
    spec.handled.update({"gradient", "divergence", "curl"})
    return True


_DIST_PATTERNS = (
    ("normal", rf"\b(?:normal|gaussian|N)\s*\(\s*({_NUM})\s*,\s*({_NUM})\s*\)"),
    ("normal", rf"\bnormal(?:ly distributed| distribution)?\b.*?\bmean\s*(?:=|of|is)?\s*({_NUM}).*?\b(?:standard deviation|sd|sigma)\s*(?:=|of|is)?\s*({_NUM})"),
    ("binomial", rf"\b(?:binomial|B|Bin)\s*\(\s*(\d+)\s*,\s*({_NUM})\s*\)"),
    ("binomial", rf"\bbinomial\b.*?\bn\s*=\s*(\d+).*?\bp\s*=\s*({_NUM})"),
    ("binomial", rf"\b(\d+)\s+(?:independent\s+)?trials\b.*?\b(?:p\s*=|probability(?: of success)?\s*(?:=|of|is)?)\s*({_NUM})"),
    ("poisson", rf"\bpoisson\s*\(\s*({_NUM})\s*\)"),
    ("poisson", rf"\bpoisson\b.*?\b(?:mean|rate|lambda|λ)\s*(?:=|of|is)?\s*({_NUM})"),
    ("exponential", rf"\b(?:exponential|exp)\s*\(\s*({_NUM})\s*\)"),
    ("exponential", rf"\bexponential\b.*?\b(?:rate|lambda|λ)\s*(?:=|of|is)?\s*({_NUM})"),
    ("uniform", rf"\b(?:uniform|U)\s*\(\s*({_NUM})\s*,\s*({_NUM})\s*\)"),
    ("uniform", rf"\buniform(?:ly distributed)?\b.*?\[\s*({_NUM})\s*,\s*({_NUM})\s*\]"),
    ("geometric", rf"\bgeometric\s*\(\s*({_NUM})\s*\)"),
    ("bernoulli", rf"\bbernoulli\s*\(\s*({_NUM})\s*\)"),
)


def _parse_probability(text: str, low: str, spec: ProblemSpec) -> bool:
    dist, params = None, []
    for name, pat in _DIST_PATTERNS:
        m = re.search(pat, text, re.I)
        if m:
            dist, params = name, list(m.groups())
            break
    if dist is None:
        return False
    q: dict[str, Any] = {"distribution": dist, "parameters": params}
    rel = re.search(rf"\bP\s*\(\s*X\s*(<=|>=|<|>|=)\s*({_NUM})\s*\)", text)
    between = re.search(rf"\bP\s*\(\s*({_NUM})\s*(<=|<)\s*X\s*(<=|<)\s*({_NUM})\s*\)", text)
    words = re.search(rf"\b(at most|at least|more than|greater than|fewer than|less than|exactly|no more than|no fewer than)\s+({_NUM})", low)
    btw = re.search(rf"\bbetween\s+({_NUM})\s+and\s+({_NUM})", low)
    if between:
        q.update(query="probability", lower=between.group(1), upper=between.group(4), lower_inclusive=between.group(2) == "<=", upper_inclusive=between.group(3) == "<=")
    elif rel:
        op, v = rel.group(1), rel.group(2)
        q.update(query="probability", **{
            "<=": {"upper": v}, "<": {"upper": v, "upper_inclusive": False}, ">=": {"lower": v},
            ">": {"lower": v, "lower_inclusive": False}, "=": {"lower": v, "upper": v},
        }[op])
    elif words:
        w, v = words.group(1), words.group(2)
        q.update(query="probability", **{
            "at most": {"upper": v}, "no more than": {"upper": v}, "at least": {"lower": v}, "no fewer than": {"lower": v},
            "more than": {"lower": v, "lower_inclusive": False}, "greater than": {"lower": v, "lower_inclusive": False},
            "fewer than": {"upper": v, "upper_inclusive": False}, "less than": {"upper": v, "upper_inclusive": False},
            "exactly": {"lower": v, "upper": v},
        }[w])
    elif btw:
        q.update(query="probability", lower=btw.group(1), upper=btw.group(2))
    elif re.search(r"\b(?:expected value|expectation|mean|average)\b", low):
        q["query"] = "mean"
    elif re.search(r"\bvariance\b", low):
        q["query"] = "variance"
    elif re.search(r"\bstandard deviation\b", low):
        q["query"] = "std"
    elif (qm := re.search(rf"\b({_NUM})(?:st|nd|rd|th)?\s*(?:percentile|%\s*quantile)", low)) or (qm := re.search(rf"\bquantile\s+(?:at\s+)?({_NUM})", low)):
        v = float(sp.Rational(qm.group(1)))
        q.update(query="quantile", value=str(v / 100 if v > 1 else v))
    else:
        return False
    spec.kind, spec.params = "probability", q
    spec.expression = f"{dist}({', '.join(params)}).{q['query']}"
    spec.handled.update({"probability", "expected value", "percent", "%"})
    return True


def _parse_statistics(text: str, low: str, spec: ProblemSpec) -> bool:
    if not re.search(r"\b(?:mean|average|median|standard deviation|variance|t-?test|regression|line of best fit|correlation|confidence interval|statistics|summary)\b", low):
        return False
    lists = [[v for v in re.split(r"[,\s;]+", g.strip()) if v] for g in re.findall(r"\[([^\[\]]+)\]", text)]
    if not lists:
        m = re.search(rf"(?:of|for|data|values|sample|numbers)\s*:?\s*((?:{_NUM}\s*,\s*){{2,}}{_NUM})", text)
        lists = [[v.strip() for v in m.group(1).split(",")]] if m else []
    try:
        data = [[float(sp.Rational(v)) for v in lst] for lst in lists]
    except Exception:  # noqa: BLE001
        return False
    if not data or len(data[0]) < 2:
        return False
    params: dict[str, Any] = {"data": data[0]}
    if re.search(r"\bregression|line of best fit|fit a line\b", low) and len(data) >= 2:
        params.update(operation="linregress", data2=data[1])
    elif re.search(r"\bcorrelation\b", low) and len(data) >= 2:
        params.update(operation="pearson", data2=data[1])
    elif re.search(r"\bpaired\b", low) and len(data) >= 2:
        params.update(operation="ttest_rel", data2=data[1])
    elif re.search(r"\bt-?test\b", low) and len(data) >= 2:
        params.update(operation="ttest_ind", data2=data[1])
    elif re.search(r"\bt-?test\b", low):
        mu = re.search(rf"(?:mu|μ|mean(?: of)?|against|equal to|=)\s*({_NUM})\b(?![^\[]*\])", text)
        params.update(operation="ttest_1samp", mu0=float(sp.Rational(mu.group(1))) if mu else 0.0)
    elif re.search(r"\bconfidence interval\b", low):
        c = re.search(r"(\d+(?:\.\d+)?)\s*%", text)
        params.update(operation="confidence_interval", confidence=float(c.group(1)) / 100 if c else 0.95)
    else:
        params["operation"] = "describe"
        params["want"] = next((w for w in ("median", "standard deviation", "variance", "mean", "average") if w in low), "summary")
    spec.kind, spec.params = "statistics", params
    spec.expression = f"{params['operation']}({len(data[0])} values)"
    spec.handled.update({"%", "percent", "average"})
    return True


_PARSERS = (
    _parse_linalg, _parse_recurrence, _parse_probability, _parse_statistics, _parse_number_theory, _parse_transform,
    _parse_vector_calculus, _parse_optimize, _parse_tangent, _parse_ode, _parse_limit, _parse_series, _parse_integral,
    _parse_derivative, _parse_sum, _parse_inequality, _parse_identity, _parse_simplify, _parse_solve, _parse_evaluate,
)


# Words that change what is being asked; a parse that ignores one answers a different question.
_MODIFIERS = (
    "twice", "thrice", "times", "area", "volume", "average", "mean value", "maximum", "minimum", "maximi", "minimi",
    "extrem", "critical point", "inflection", "tangent", "normal line", "percent", "%", "modulo", " mod ", "gcd", "lcm",
    "probability", "expected value", "arc length", "perimeter", "slope", "rate of change", "concav", "increasing",
    "decreasing", "inverse function", "partial derivative", "gradient", "divergence", "curl",
)


# A simulation time span ("over 0-20 s", "for 10 s"): it belongs to the simulation task, not to the problem parsed here.
_TIME_SPAN_RE = re.compile(
    rf"\b(?:over|for|from|during|between)\s+\[?\s*(?:{_NUM_VALUE}\s*(?:-|–|—|to|and|,)\s*)?{_NUM_VALUE}\s*\]?\s*"
    r"(?:ms|s|secs?|seconds?|min|minutes?|h|hours?)\b",
    re.I,
)


# "Report the maximum absolute error / mean residual": how results are compared, not what is solved, so these words do
# not count as meaning-changing modifiers ("find the maximum of x(t)" still does).
_ERROR_REPORT_RE = re.compile(
    r"\b(?:maximum|minimum|max|min|mean|average)\s+(?:absolute\s+|relative\s+|numerical\s+|global\s+|local\s+)?"
    r"(?:errors?|residuals?|deviations?|differences?|discrepanc(?:y|ies))\b",
    re.I,
)


def _fidelity(spec: ProblemSpec, norm: str, low: str) -> list[str]:
    """Tokens of the question that the parsed problem does not account for (see ProblemSpec.unaccounted)."""
    norm = _TIME_SPAN_RE.sub(" ", norm)
    low = _ERROR_REPORT_RE.sub(" ", low)
    parts = [spec.expression or "", *spec.equations, spec.lower or "", spec.upper or "", spec.point or "", spec.func or "",
             str(spec.order), str(spec.order - 1)]
    parts += [f"{k} {v}" for k, v in spec.ics.items()]
    parts += [" ".join(r) for r in spec.matrix or []] + [" ".join(spec.rhs_vector or [])]
    parts += [json.dumps(spec.params, default=str)]
    def canon(n: str) -> str:  # compare numbers by value: "2" and "2.0" are the same number
        return repr(float(n))

    covered = {canon(n) for n in re.findall(r"\d+(?:\.\d+)?", " ".join(parts))}
    percents = set(re.findall(r"(\d+(?:\.\d+)?)\s*%", norm))  # "95%" is covered by 0.95
    missing = [
        n for n in re.findall(r"(?<![\w.])\d+(?:\.\d+)?(?![\w.])", norm)
        if canon(n) not in covered and not (n in percents and repr(float(n) / 100) in covered)
    ]
    fname = (spec.func or "y(").split("(")[0]
    if spec.kind in ("differentiate", "integrate", "ode", "series", "limit") and spec.variable:
        missing += [f"d{v}" for v in re.findall(r"\bd([a-z])\b", norm) if v not in (spec.variable, fname)]
    missing += [w.strip() for w in _MODIFIERS if w in low and w.strip() not in spec.handled]
    return list(dict.fromkeys(missing))


def parse_problem(text: str) -> ProblemSpec:
    """Parse a question into a ProblemSpec (kind "unknown" when no parser recognises it)."""
    spec = ProblemSpec(text=str(text or ""))
    norm = normalize_math_text(strip_question_framing(spec.text))
    if not norm or len(norm) > 2000:  # a concrete math task is stated concisely; essays go to the model
        return spec
    low = norm.lower()
    _domain_and_assumptions(low, spec)
    for parser in _PARSERS:
        trial = ProblemSpec(text=spec.text, domain=spec.domain, assumptions=dict(spec.assumptions))
        try:
            if parser(norm, low, trial):
                trial.unaccounted = _fidelity(trial, norm, low)
                return trial
        except Exception:  # noqa: BLE001 - one parser's failure must not hide the others
            continue
    return spec


_MATH_INTENT_RE = re.compile(
    r"\b(?:solve|roots?|zeros?|simplify|factori[sz]e|derivative|differentiate|integra(?:te|l)|antiderivative|"
    r"limit|taylor|maclaurin|series|summation|eigen\w*|determinant|matrix|inverse|identity|prove|evaluate|"
    r"differential equation|ode|maxim\w*|minim\w*|extrem\w*|inequalit\w*|tangent|slope|gcd|lcm|prime|modulo|"
    r"divisors?|totient|recurrence|laplace|fourier|gradient|divergence|curl|laplacian|hessian|jacobian|"
    r"probability|distribution|binomial|poisson|variance|standard deviation|regression|correlation|t-?test|"
    r"confidence interval|percent)\b",
    re.I,
)


def has_math_intent(text: str) -> bool:
    return bool(_MATH_INTENT_RE.search(text or "")) or bool(re.search(r"[=^∫∑√]|\\frac|\\int", text or ""))


__all__ = [
    "LINALG_OPS",
    "ProblemSpec",
    "TaskKind",
    "extract_math",
    "has_math_intent",
    "normalize_math_text",
    "parse_problem",
    "plausible_symbol",
    "strip_question_framing",
]
