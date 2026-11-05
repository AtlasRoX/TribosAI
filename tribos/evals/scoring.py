"""
Deterministic scoring: every function takes what a run produced and returns checks and metrics, with no I/O.
LLM-based grading (benchmark labels, rubric judge) lives in grading.py and only adds to these.
"""

from __future__ import annotations

import math
import random
import re
from collections.abc import Iterable, Sequence
from typing import Any

from .schema import (
    AnswerExpect,
    Check,
    ExecutionExpect,
    Fact,
    PlanExpect,
    RetrievalExpect,
    SimulationExpect,
)

# ---------------------------------------------------------------------------------------------------------------
# Plan
# ---------------------------------------------------------------------------------------------------------------

_SOURCE_ALIASES: dict[str, tuple[str, ...]] = {
    "archivon": ("archivon", "lithoscribe"),
    "lithoscribe": ("lithoscribe", "archivon"),
    "dynamis": ("dynamis", "vivarix"),
    "vivarix": ("vivarix", "dynamis"),
    "calcula": ("calcula", "lumicell", "sandbox"),
    "lumicell": ("lumicell", "calcula"),
    "axiom": ("axiom",),
    "physis": ("physis",),
}


def _norm(s: Any) -> str:
    return re.sub(r"[^a-z0-9]+", " ", str(s).lower()).strip()


def _source_ran(src: str, ran: set) -> bool:
    aliases = _SOURCE_ALIASES.get(src.lower(), (src,))
    return src in ran or any(a in ran for a in aliases)


def plan_checks(expect: PlanExpect, observed: dict[str, Any], *, live: bool) -> list[Check]:
    """Scope and question type are checked always; entity and routing checks need the live resolver unless the
    case says they hold offline (plan.offline)."""
    checks: list[Check] = []
    if expect.scope is not None:
        checks.append(Check(name="plan.scope", passed=observed.get("scope") == expect.scope,
                            detail=f"expected {expect.scope}, got {observed.get('scope')}"))
    if expect.simulation is not None:
        checks += simulation_checks(expect.simulation, observed)
    if expect.question_type is not None and observed.get("scope") == "research":
        checks.append(Check(name="plan.question_type", passed=observed.get("question_type") == expect.question_type,
                            detail=f"expected {expect.question_type}, got {observed.get('question_type')}"))
    entity_level = live or expect.offline
    if not entity_level:
        return checks
    names = {_norm(n) for n in observed.get("entity_names", [])}
    if expect.primary_target is not None:
        want = expect.primary_target or None
        got = observed.get("primary_target") or None
        checks.append(Check(name="plan.primary_target", passed=_norm(want or "") == _norm(got or ""),
                            detail=f"expected {want}, got {got}"))
    for ent in expect.entities:
        checks.append(Check(name="plan.entity", passed=_norm(ent) in names, detail=f"{ent} {'found' if _norm(ent) in names else 'missing'}"))
    for ent in expect.not_entities:
        checks.append(Check(name="plan.not_entity", passed=_norm(ent) not in names,
                            detail=f"{ent} {'wrongly recognized' if _norm(ent) in names else 'absent'}"))
    ran = set(observed.get("sources_run", []))
    for src in expect.run:
        hit = _source_ran(src, ran)
        checks.append(Check(name="plan.runs", passed=hit, detail=f"{src} {'runs' if hit else 'does not run'}"))
    for src in expect.skip:
        hit = _source_ran(src, ran)
        checks.append(Check(name="plan.skips", passed=not hit, detail=f"{src} {'wrongly runs' if hit else 'skipped'}"))
    return checks


def _close(a: Any, b: float | None, tol: float = 1e-9) -> bool:
    try:
        return b is not None and abs(float(a) - float(b)) <= tol * max(1.0, abs(float(b)))
    except (TypeError, ValueError):
        return False


def simulation_checks(expect: SimulationExpect, observed: dict[str, Any]) -> list[Check]:
    """The parsed simulation plan: action, scan arguments, overrides kept, durations, and validation errors."""
    plan = observed.get("simulation_plan") or None
    constraints = observed.get("simulation_constraints") or {}
    checks: list[Check] = []
    if expect.forbidden is not None:
        got = bool(constraints.get("simulation_forbidden"))
        checks.append(Check(name="plan.sim_forbidden", passed=got is expect.forbidden, detail=f"expected {expect.forbidden}, got {got}"))
    if expect.action is not None:
        got = (plan or {}).get("action") or ""
        checks.append(Check(name="plan.sim_action", passed=got == expect.action, detail=f"expected {expect.action or 'none'}, got {got or 'none'}"))
    if plan is None:
        wanted = [n for n, v in (("duration_seconds", expect.duration_seconds), ("scan_points", expect.scan_points),
                                 ("validation_error", expect.validation_error)) if v is not None] + (["overrides"] if expect.overrides else [])
        if wanted:
            checks.append(Check(name="plan.sim_plan", passed=False, detail=f"no simulation plan, expected {', '.join(wanted)}"))
        return checks
    for field in ("duration_seconds", "scan_start", "scan_end"):
        want = getattr(expect, field)
        if want is not None:
            checks.append(Check(name=f"plan.sim_{field}", passed=_close(plan.get(field), want), detail=f"expected {want}, got {plan.get(field)}"))
    if expect.scan_points is not None:
        checks.append(Check(name="plan.sim_scan_points", passed=plan.get("scan_points") == expect.scan_points,
                            detail=f"expected {expect.scan_points}, got {plan.get('scan_points')}"))
    if expect.scan_parameter is not None:
        checks.append(Check(name="plan.sim_scan_parameter", passed=plan.get("scan_parameter") == expect.scan_parameter,
                            detail=f"expected {expect.scan_parameter}, got {plan.get('scan_parameter')}"))
    kept = set((plan.get("parameter_overrides") or {}).keys())
    for name in expect.overrides:
        checks.append(Check(name="plan.sim_override_kept", passed=name in kept, detail=f"{name} {'kept' if name in kept else 'dropped'}"))
    codes = [str((e or {}).get("code")) for e in plan.get("validation_errors") or [] if isinstance(e, dict)]
    if expect.validation_error is not None:
        checks.append(Check(name="plan.sim_validation_error", passed=expect.validation_error in codes,
                            detail=f"expected {expect.validation_error}, got {codes or 'none'}"))
    if expect.valid is not None:
        checks.append(Check(name="plan.sim_valid", passed=(not codes) is expect.valid, detail=f"validation errors: {codes or 'none'}"))
    return checks


# ---------------------------------------------------------------------------------------------------------------
# Retrieval
# ---------------------------------------------------------------------------------------------------------------


def _ranked_unique(items: Iterable[Any]) -> list[str]:
    return list(dict.fromkeys(str(i).strip().lower() for i in items if i))


def retrieval_scores(
    expect: RetrievalExpect,
    pmids: Sequence[Any],
    dois: Sequence[Any] = (),
    titles: Sequence[Any] = (),
    arxiv_ids: Sequence[Any] = (),
) -> tuple[list[Check], dict[str, Any]]:
    """hit@k (a gold PMID/DOI/arXiv ID, or a title matching a gold pattern, in the top k), recall@k over the listed
    gold papers, and reciprocal rank of the first hit. Rank order is kept; the lists are parallel when given."""
    ranked_p, ranked_d, ranked_a = _ranked_unique(pmids), _ranked_unique(dois), _ranked_unique(arxiv_ids)
    ranked_t = list(dict.fromkeys(str(t) for t in titles if t))
    gold_p = {str(p).strip().lower() for p in expect.gold_pmids}
    gold_d = {str(d).strip().lower() for d in expect.gold_dois}
    gold_a = {re.sub(r"(?:v\d+)?$", "", re.sub(r"^arxiv:\s*", "", str(a).strip().lower())) for a in expect.gold_arxiv_ids}
    patterns = [re.compile(p, re.I) for p in expect.gold_title_patterns]
    n_gold = len(gold_p) + len(gold_d) + len(gold_a)
    if not n_gold and not patterns:
        return [], {"retrieved": len(ranked_p) + len(ranked_d) + len(ranked_a)}
    k = expect.k
    top_p, top_d, top_a, top_t = ranked_p[:k], ranked_d[:k], ranked_a[:k], ranked_t[:k]
    norm_top_a = [re.sub(r"(?:v\d+)?$", "", re.sub(r"^arxiv:\s*", "", a)) for a in top_a]
    found = (gold_p & set(top_p)) | (gold_d & set(top_d)) | (gold_a & set(norm_top_a))
    title_hits = [(i + 1, t) for i, t in enumerate(top_t) if any(p.search(t) for p in patterns)]
    ranks = (
        [i + 1 for i, p in enumerate(top_p) if p in gold_p]
        + [i + 1 for i, d in enumerate(top_d) if d in gold_d]
        + [i + 1 for i, a in enumerate(norm_top_a) if a in gold_a]
        + [r for r, _ in title_hits]
    )
    first = min(ranks) if ranks else None
    hit = bool(found or title_hits)
    metrics = {
        "hit": hit,
        "recall": round(len(found) / n_gold, 3) if n_gold else None,
        "rr": round(1 / first, 3) if first else 0.0,
        "first_gold_rank": first,
        "gold_found": sorted(found),
        "title_matches": [t[:100] for _, t in title_hits][:3],
        "retrieved": len(ranked_p) + len(ranked_d) + len(ranked_a),
        "k": k,
    }
    if found:
        detail = f"found {sorted(found)} at rank {first}"
    elif title_hits:
        detail = f"title match at rank {title_hits[0][0]}: {title_hits[0][1][:90]}"
    else:
        detail = f"none of {sorted(gold_p | gold_d | gold_a)} or the title patterns in top {k} of {len(ranked_p)} items"
    return [Check(name="retrieval.gold_hit", passed=hit, required=expect.required, detail=detail)], metrics


# ---------------------------------------------------------------------------------------------------------------
# Numeric and Symbolic (SymPy / LaTeX) equivalence checks
# ---------------------------------------------------------------------------------------------------------------


def extract_boxed(text: str) -> str | None:
    """Extract the content of the last \\boxed{...} expression in text, handling nested braces."""
    if not text:
        return None
    matches: list[str] = []
    for m in re.finditer(r"\\boxed\s*\{", text):
        start = m.end()
        depth = 1
        i = start
        while i < len(text) and depth > 0:
            if text[i] == "{":
                depth += 1
            elif text[i] == "}":
                depth -= 1
            i += 1
        if depth == 0:
            matches.append(text[start: i - 1].strip())
    return matches[-1] if matches else None


def _replace_latex_fracs(s: str) -> str:
    """Recursively replace \\frac{a}{b} and \\dfrac{a}{b} with ((a)/(b))."""
    pattern = re.compile(r"\\(?:d|t)?frac\s*\{")
    for _ in range(12):
        m = pattern.search(s)
        if not m:
            break
        # parse first brace group
        i = m.end()
        depth = 1
        while i < len(s) and depth > 0:
            depth += (s[i] == "{") - (s[i] == "}")
            i += 1
        if depth != 0:
            break
        num = s[m.end(): i - 1]
        # skip whitespace and expect '{'
        while i < len(s) and s[i].isspace():
            i += 1
        if i >= len(s) or s[i] != "{":
            break
        j = i + 1
        depth = 1
        while j < len(s) and depth > 0:
            depth += (s[j] == "{") - (s[j] == "}")
            j += 1
        if depth != 0:
            break
        den = s[i + 1: j - 1]
        s = s[:m.start()] + f"(({num})/({den}))" + s[j:]
    return s


def _replace_latex_sqrts(s: str) -> str:
    """Replace \\sqrt[n]{x} and \\sqrt{x} with ((x)**(1/(n))) and sqrt(x)."""
    pattern = re.compile(r"\\sqrt\s*(?:\[(?P<root>[^\]]+)\])?\s*\{")
    for _ in range(12):
        m = pattern.search(s)
        if not m:
            break
        root = m.group("root")
        i = m.end()
        depth = 1
        while i < len(s) and depth > 0:
            depth += (s[i] == "{") - (s[i] == "}")
            i += 1
        if depth != 0:
            break
        inner = s[m.end(): i - 1]
        repl = f"(({inner})**(1/({root})))" if root else f"sqrt({inner})"
        s = s[:m.start()] + repl + s[i:]
    return s


_LATEX_GREEK_AND_SYMBOLS: tuple[tuple[str, str], ...] = (
    (r"\\left\s*", ""),
    (r"\\right\s*", ""),
    (r"\\(?:,|;|!|quad|qquad)\b", " "),
    (r"\\cdot\b", "*"),
    (r"\\times\b", "*"),
    (r"\\div\b", "/"),
    (r"\\pi\b", "pi"),
    (r"\\hbar\b", "hbar"),
    (r"\\omega\b", "omega"),
    (r"\\delta\b", "delta"),
    (r"\\eta\b", "eta"),
    (r"\\sigma\b", "sigma"),
    (r"\\alpha\b", "alpha"),
    (r"\\beta\b", "beta"),
    (r"\\gamma\b", "gamma"),
    (r"\\lambda\b", "lam"),
    (r"\\theta\b", "theta"),
    (r"\\mu\b", "mu"),
    (r"\\rho\b", "rho"),
    (r"\\epsilon\b", "epsilon"),
    (r"\\varepsilon\b", "epsilon"),
    (r"\\phi\b", "phi"),
    (r"\\infty\b", "oo"),
    (r"\\sin\b", "sin"),
    (r"\\cos\b", "cos"),
    (r"\\tan\b", "tan"),
    (r"\\sec\b", "sec"),
    (r"\\csc\b", "csc"),
    (r"\\cot\b", "cot"),
    (r"\\arcsin\b", "asin"),
    (r"\\arccos\b", "acos"),
    (r"\\arctan\b", "atan"),
    (r"\\sinh\b", "sinh"),
    (r"\\cosh\b", "cosh"),
    (r"\\tanh\b", "tanh"),
    (r"\\exp\b", "exp"),
    (r"\\ln\b", "log"),
    (r"\\log\b", "log"),
    ("π", "pi"),
    ("ℏ", "hbar"),
    ("ω", "omega"),
    ("δ", "delta"),
    ("η", "eta"),
    ("σ", "sigma"),
)


def latex_to_sympy_str(raw: str) -> str:
    """Convert a LaTeX or plain mathematical expression string into a SymPy-parsable string."""
    s = normalize(raw or "").strip()
    boxed = extract_boxed(s)
    if boxed is not None:
        s = boxed
    s = s.strip("$").strip()
    # Strip leading LHS assignment like "y(x) = " or "\delta = " or "T = " when an '=' is present
    if "=" in s and not any(op in s for op in ("==", "<=", ">=", "!=")):
        s = s.split("=")[-1].strip()
    s = re.sub(r"\\text\s*\{[^}]*\}", "", s)
    s = re.sub(r"\\(?:mathrm|operatorname)\s*\{([^}]*)\}", r"\1", s)  # \operatorname{erf}(1) -> erf(1)
    s = _replace_latex_fracs(s)
    s = _replace_latex_sqrts(s)
    # Subscripts: x_{0} -> x_0
    s = re.sub(r"_\{([A-Za-z0-9]+)\}", r"_\1", s)
    # Superscripts: x^{2n} -> x**(2n)
    for _ in range(8):
        s_new = re.sub(r"\^\s*\{([^{}]+)\}", r"**(\1)", s)
        if s_new == s:
            break
        s = s_new
    for pat, repl in _LATEX_GREEK_AND_SYMBOLS:
        s = re.sub(pat, repl, s)
    s = s.replace("{", "(").replace("}", ")")
    s = s.replace("^", "**")
    return s.strip().rstrip(".,;:")


def parse_sympy_expr(raw: str) -> Any:
    """Parse a mathematical or LaTeX string into a SymPy expression, or return None on failure."""
    cleaned = latex_to_sympy_str(raw)
    if not cleaned:
        return None
    try:
        import sympy
        from sympy.parsing.sympy_parser import (
            convert_xor,
            implicit_multiplication_application,
            standard_transformations,
        )

        from tribos.axiom.safe_expr import parse_math

        local_dict: dict[str, Any] = {
            "pi": sympy.pi,
            "e": sympy.E,
            "E": sympy.Symbol("E"),
            "I": sympy.Symbol("I"),
            "oo": sympy.oo,
            "sqrt": sympy.sqrt,
            "sin": sympy.sin,
            "cos": sympy.cos,
            "tan": sympy.tan,
            "asin": sympy.asin,
            "acos": sympy.acos,
            "atan": sympy.atan,
            "sinh": sympy.sinh,
            "cosh": sympy.cosh,
            "tanh": sympy.tanh,
            "exp": sympy.exp,
            "log": sympy.log,
            "ln": sympy.log,
            "Abs": sympy.Abs,
            "factorial": sympy.factorial,
            # Special functions a closed-form answer may use (named here so they are not split into symbols).
            "erf": sympy.erf,
            "erfc": sympy.erfc,
            "gamma": sympy.gamma,
            "cot": sympy.cot,
            "sec": sympy.sec,
            "csc": sympy.csc,
            "asinh": sympy.asinh,
            "acosh": sympy.acosh,
            "atanh": sympy.atanh,
            "arcsin": sympy.asin,
            "arccos": sympy.acos,
            "arctan": sympy.atan,
            "binomial": sympy.binomial,
        }
        # If 'E' is not used as a variable (like Young's modulus E*I), allow exp(1) when written as 'e'
        transformations = standard_transformations + (implicit_multiplication_application, convert_xor)
        # Candidate answers are model output: the allowlist parser, never a bare parse_expr (which has builtins).
        return parse_math(cleaned, local_dict, transformations)
    except Exception:  # noqa: BLE001
        return None


_FRAC_SHORT_RE = (
    (re.compile(r"\\([dt]?frac)\s*([0-9A-Za-z])\s*([0-9A-Za-z])"), r"\\\1{\2}{\3}"),   # \frac14 -> \frac{1}{4}
    (re.compile(r"\\([dt]?frac)\s*([0-9A-Za-z])\s*\{"), r"\\\1{\2}{"),                  # \frac1{x} -> \frac{1}{x}
    (re.compile(r"\\([dt]?frac)\s*(\{[^{}]*\})\s*([0-9A-Za-z])"), r"\\\1\2{\3}"),       # \frac{a}2 -> \frac{a}{2}
    (re.compile(r"\\sqrt\s*([0-9A-Za-z])"), r"\\sqrt{\1}"),                               # \sqrt2 -> \sqrt{2}
)
_TEXT_WRAP_RE = re.compile(r"\\(?:text|textbf|textit|mathrm|mathbf|operatorname)\s*\{([^{}]*)\}")


def expand_latex_shorthand(expr: str) -> str:
    """Brace-less LaTeX shorthands that answers commonly use, written out (\\frac14 is \\frac{1}{4})."""
    out = expr or ""
    for pattern, repl in _FRAC_SHORT_RE:
        out = pattern.sub(repl, out)
    return out


def _plain_text_answer(expr: str) -> str:
    """A text answer without its LaTeX wrapping: \\text{Evelyn} and Evelyn are the same answer."""
    t = _TEXT_WRAP_RE.sub(r"\1", expr or "")
    t = re.sub(r"\\[,;!: ]|\$|\\left|\\right", "", t)
    return re.sub(r"\s+", " ", t).strip().strip(".").strip()


def symbolic_equivalent(expr_a: str, expr_b: str, *, rtol: float = 1e-5, atol: float = 1e-7) -> bool:
    """Check whether two mathematical/LaTeX expressions are symbolically equivalent using SymPy
    (`sympy.simplify(a - b) == 0`) plus deterministic numeric spot checks."""
    if not expr_a or not expr_b:
        return False
    # Text answers ("\text{Evelyn}" against "Evelyn"): the same words are the same answer. Case is ignored only when
    # the reference is itself text, so variable names stay case-sensitive.
    plain_a, plain_b = _plain_text_answer(expr_a), _plain_text_answer(expr_b)
    if plain_a and plain_a == plain_b:
        return True
    if _TEXT_WRAP_RE.search(expr_b) and plain_a.lower() == plain_b.lower() and plain_a:
        return True
    expr_a, expr_b = expand_latex_shorthand(expr_a), expand_latex_shorthand(expr_b)
    if latex_to_sympy_str(expr_a).replace(" ", "") == latex_to_sympy_str(expr_b).replace(" ", ""):
        return True
    try:
        import sympy
    except ImportError:
        return False

    a = parse_sympy_expr(expr_a)
    b = parse_sympy_expr(expr_b)
    if a is None or b is None:
        return False
    if isinstance(a, (tuple, list, dict, set)) or isinstance(b, (tuple, list, dict, set)):
        return a == b
    try:
        diff = a - b
        if diff == 0 or sympy.simplify(diff) == 0 or sympy.expand(diff) == 0 or sympy.trigsimp(diff) == 0:
            return True
    except Exception:  # noqa: BLE001
        pass

    # Numeric spot checks over free symbols
    try:
        syms = sorted(a.free_symbols | b.free_symbols, key=lambda s: s.name)
        if not syms:
            va = complex(a.evalf())
            vb = complex(b.evalf())
            return abs(va - vb) <= max(atol, rtol * max(1.0, abs(vb)))
        rng = random.Random(42)
        valid_points = 0
        for _ in range(8):
            subs = {s: rng.uniform(0.37, 2.83) for s in syms}
            try:
                va = complex(a.subs(subs).evalf())
                vb = complex(b.subs(subs).evalf())
            except Exception:  # noqa: BLE001
                continue
            if not (math.isfinite(va.real) and math.isfinite(va.imag) and math.isfinite(vb.real) and math.isfinite(vb.imag)):
                continue
            valid_points += 1
            if abs(va - vb) > max(atol, rtol * max(1.0, abs(vb))):
                return False
        return valid_points >= 3
    except Exception:  # noqa: BLE001
        return False


_SCI_NUM_RE = re.compile(
    r"(?<![A-Za-z0-9_])([+-]?(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?|[+-]?\.\d+)"
    r"(?:\s*(?:[eE]|(?:\*|\\times|\\cdot|×)\s*10\s*(?:\^|\*\*)\s*\{?)\s*([+-]?\d+)\}?)?"
)


def _parse_numeric_str(raw: str) -> float | None:
    """Parse a numeric string (plain float, scientific notation, fraction, or constant SymPy expression)."""
    s = normalize(raw or "").strip().strip("$").strip()
    if not s:
        return None
    # LaTeX thousands separators: 10{,}000 and 10\,000 are 10000.
    s = re.sub(r"(?<=\d)(?:\{,\}|\\,|\\ )(?=\d{3})", "", s)
    # Brace-less shorthand and sizing commands: -\frac12 is -1/2, \sin\left(x\right) is \sin(x).
    s = re.sub(r"\\(?:left|right|big|Big|bigl|bigr)\b", "", expand_latex_shorthand(s))
    # "expression \approx 2.534": the stated value is the answer.
    if re.search(r"\\approx|≈", s):
        s = re.split(r"\\approx|≈", s)[-1].strip()
    # Strip trailing units after a number if simple, or try direct float first
    s_clean = s.replace(",", "").strip()
    try:
        val = float(s_clean)
        if math.isfinite(val):
            return val
    except ValueError:
        pass
    # Scientific notation like 1.23 \times 10^{-4}
    m_sci = re.fullmatch(
        r"([+-]?(?:\d+(?:\.\d+)?|\.\d+))\s*(?:[eE]|(?:\*|\\times|\\cdot|×)\s*10\s*(?:\^|\*\*)\s*\{?)\s*([+-]?\d+)\}?",
        s_clean,
    )
    if m_sci:
        try:
            return float(m_sci.group(1)) * (10.0 ** int(m_sci.group(2)))
        except (ValueError, OverflowError):
            pass
    # Try evaluating constant expression via SymPy (e.g. \sqrt{\pi}, \pi^2/6, 3/4)
    expr = parse_sympy_expr(s)
    if expr is not None and not getattr(expr, "free_symbols", True):
        try:
            val = float(expr.evalf())
            if math.isfinite(val):
                return val
        except Exception:  # noqa: BLE001
            pass
    return None


def extract_numeric_answer(text: str) -> float | None:
    """Extract the primary numerical answer from text (prioritizing \\boxed{...}, #### <num>, Result/Answer lines, or final number)."""
    if not text:
        return None
    norm = re.sub(r"(?<=\d)(?:\{,\}|\\,|\\ )(?=\d{3})", "", normalize(text))  # 10{,}000 -> 10000
    boxed = extract_boxed(norm)
    if boxed is not None:
        v = _parse_numeric_str(boxed)
        if v is not None:
            return v
        # If boxed contains "x = 42.5 m", extract number from inside boxed
        m = _SCI_NUM_RE.search(boxed)
        if m:
            base = float(m.group(1).replace(",", ""))
            exp = int(m.group(2)) if m.group(2) else 0
            return base * (10.0 ** exp)
        # The stated answer holds no number (\boxed{Yes}): any other number in the text is not the answer.
        return None
    # GSM8K style: #### 42
    m_hash = re.search(r"####\s*([+-]?[\d,]+(?:\.\d+)?(?:[eE][+-]?\d+)?)", norm)
    if m_hash:
        v = _parse_numeric_str(m_hash.group(1))
        if v is not None:
            return v
    # Explicit Answer / Result line
    for pat in (
        r"(?:final\s+answer|result|answer)\s*(?:is|:|=)\s*\$?([+-]?\d[\d,]*(?:\.\d+)?(?:\s*(?:[eE]|(?:\*|\\times|×)\s*10\^\{?)[+-]?\d+\}?)?)",
        r"=\s*([+-]?\d[\d,]*(?:\.\d+)?(?:\s*(?:[eE]|(?:\*|\\times|×)\s*10\^\{?)[+-]?\d+\}?)?)\s*(?:[A-Za-z/%°Ωμ]+)?\s*[.!\n]*$",
    ):
        matches = list(re.finditer(pat, norm, re.I | re.M))
        if matches:
            v = _parse_numeric_str(matches[-1].group(1))
            if v is not None:
                return v
    all_nums: list[float] = []
    for m in _SCI_NUM_RE.finditer(norm):
        try:
            base = float(m.group(1).replace(",", ""))
            exp = int(m.group(2)) if m.group(2) else 0
            all_nums.append(base * (10.0 ** exp))
        except (ValueError, OverflowError):
            continue
    return all_nums[-1] if all_nums else None


def numeric_within_tolerance(predicted: float | None, expected: float, *, abs_tol: float = 1e-3, rel_tol: float = 1e-2) -> bool:
    if predicted is None or not math.isfinite(predicted):
        return False
    tol = max(abs_tol, rel_tol * abs(expected))
    return abs(predicted - expected) <= tol + 1e-12


def numeric_answer_check(
    expected: float, text: str, *, abs_tol: float = 1e-3, rel_tol: float = 1e-2
) -> tuple[Check, dict[str, Any]]:
    """Deterministic numeric answer check against \\boxed{...} or final extracted numeric value."""
    pred = extract_numeric_answer(text)
    ok = numeric_within_tolerance(pred, expected, abs_tol=abs_tol, rel_tol=rel_tol)
    if not ok and extract_boxed(text) is None:
        # Check if any number in the text (e.g. in the Result section) matches within tolerance
        for m in _SCI_NUM_RE.finditer(normalize(text or "")):
            try:
                cand = float(m.group(1).replace(",", "")) * (10.0 ** (int(m.group(2)) if m.group(2) else 0))
            except (ValueError, OverflowError):
                continue
            if numeric_within_tolerance(cand, expected, abs_tol=abs_tol, rel_tol=rel_tol):
                pred = cand
                ok = True
                break
    detail = f"expected {expected:g} (±max({abs_tol:g}, {rel_tol:.1%})), got {pred:g}" if pred is not None else f"expected {expected:g}, no number found"
    metrics = {"numeric_expected": expected, "numeric_predicted": pred, "numeric_correct": ok}
    return Check(name="answer.numeric", passed=ok, detail=detail), metrics


_YES_NO_RE = re.compile(r"^\W*(yes|true|no|false)\b", re.I)


def yes_no_value(answer: str) -> int | None:
    """1 for a stated yes/true, 0 for no/false (\\text{Yes}, **No**, "True."), else None."""
    s = re.sub(r"\\(?:text|textbf|mathrm|mathbf)\s*\{([^{}]*)\}", r"\1", normalize(answer or "")).strip().strip("$*")
    m = _YES_NO_RE.match(s)
    if not m:
        return None
    return 1 if m.group(1).lower() in ("yes", "true") else 0


def _list_items(answer: str) -> list[str] | None:
    """The items of a stated list answer ("[4, 16, 65536]", "4,\\;16,\\;65536", "(0, 4)"), or None."""
    s = normalize(answer or "")
    boxed = extract_boxed(s)
    if boxed is not None:
        s = boxed
    else:
        lists = re.findall(r"\[([^\[\]]+)\]", s)
        if lists:
            s = lists[-1]
    s = re.sub(r"\\[,;:! ]|\\quad|\\qquad", " ", s).strip().strip("$").strip()
    s = re.sub(r"^\\?[\[\(\{]\s*|\s*\\?[\]\)\}]$", "", s)
    parts = [p.strip() for p in re.split(r",|;|\band\b", s) if p.strip()]
    return parts if len(parts) >= 2 else None


def numeric_list_check(
    expected: Sequence[float], answer: str, *, abs_tol: float = 1e-3, rel_tol: float = 1e-2
) -> tuple[Check, dict[str, Any]]:
    """The stated list matches the expected numbers in order, each within the tolerances."""
    items = _list_items(answer)
    got = [_parse_numeric_str(p) for p in items] if items else []
    ok = (len(got) == len(expected)
          and all(numeric_within_tolerance(g, e, abs_tol=abs_tol, rel_tol=rel_tol) for g, e in zip(got, expected)))
    shown = ", ".join("?" if g is None else f"{g:g}" for g in got) if got else "no list found"
    detail = f"expected [{', '.join(f'{e:g}' for e in expected)}], got [{shown}]"
    return Check(name="answer.numeric_list", passed=ok, detail=detail), {"numeric_list_correct": ok}


def symbolic_answer_check(expected_expr: str, text: str) -> tuple[Check, dict[str, Any]]:
    """Deterministic symbolic / LaTeX equivalence check using SymPy."""
    candidates: list[str] = []
    boxed = extract_boxed(text)
    if boxed is not None:
        candidates.append(boxed)
    for m in re.finditer(r"\$\$(.+?)\$\$|\$([^$\n]+)\$", text or "", re.S):
        cand = (m.group(1) or m.group(2) or "").strip()
        if cand and cand not in candidates:
            candidates.append(cand)
    for m in re.finditer(r"=\s*([^\n.;,]+)", text or ""):
        cand = m.group(1).strip()
        if cand and cand not in candidates:
            candidates.append(cand)
    if text and text.strip() not in candidates:
        candidates.append(text.strip())

    matched: str | None = None
    for cand in candidates:
        if symbolic_equivalent(cand, expected_expr):
            matched = cand
            break
    ok = matched is not None
    detail = (f"equivalent to {expected_expr!r} via {matched[:80]!r}" if ok
              else f"no expression equivalent to {expected_expr!r} (checked {len(candidates)} candidate(s))")
    metrics = {"symbolic_expected": expected_expr, "symbolic_matched": matched, "symbolic_correct": ok}
    return Check(name="answer.symbolic", passed=ok, detail=detail), metrics


# ---------------------------------------------------------------------------------------------------------------
# Answer
# ---------------------------------------------------------------------------------------------------------------

_ABSTAIN_RE = re.compile(
    # "No <anything within the sentence> was/were retrieved|found|available|reported|identified"
    r"(\bno\b[^.;]{0,160}?\b(was|were|is|are|has been|have been)\s+(found|retrieved|available|identified|reported|located)\b"
    r"|\bno (peer[- ]reviewed |direct |relevant |published |clinical |scientific |reliable |such )?(evidence|data|information|trials?|"
    r"publications?|studies|records?|papers?)\b[^.;]{0,60}\b(exists?|available|found|retrieved)"
    r"|\bnot (been )?(retrieved|found|identified|available|supported|be verified|be confirmed)"
    r"|could not (find|identify|locate|be (found|verified|confirmed))|couldn.t find"
    r"|cannot (confirm|verify|be (confirmed|verified|stated|determined|provided|answered|given|established|substantiated)|support)"
    r"|does not contain (any )?(information|data|evidence|mention)|\bno basis\b"
    r"|insufficient (evidence|information|data)|unable to (find|identify|confirm|verify|locate)"
    r"|does not (exist|correspond|appear)|no such|not aware of|is hypothetical|appears to be hypothetical|not a recogni[sz]ed)",
    re.I,
)
_PMID_RE = re.compile(r"PMID:?\s*(\d{1,9})", re.I)
# Models write "PD‑L1" with a non-breaking hyphen and "100 %" with a narrow no-break space; patterns use ASCII.
_DASHES = dict.fromkeys(map(ord, "‐‑‒–—―−﹣－"), "-")
_SPACES = dict.fromkeys(map(ord, "      　"), " ")


def normalize(text: str) -> str:
    """Unicode dashes and spaces to ASCII, so regex expectations match what a model writes."""
    return (text or "").translate(_DASHES).translate(_SPACES)


def abstained(text: str) -> bool:
    """The answer says the asked-for evidence or entity does not exist or was not found (anywhere in the text)."""
    return bool(_ABSTAIN_RE.search(normalize(text)))


def opens_with_refusal(text: str) -> bool:
    """The opening sentence says nothing was found: the answer leads with a refusal rather than an answer."""
    head = re.split(r"(?<=[.!?])\s+", normalize(text).strip())[0]
    return abstained(head)


def cited_pmids(text: str) -> list[str]:
    return list(dict.fromkeys(_PMID_RE.findall(text or "")))


def answer_checks(expect: AnswerExpect, observed: dict[str, Any], gold_pmids: Sequence[str] = ()) -> tuple[list[Check], dict[str, Any]]:
    text = normalize(observed.get("response") or "")
    agents = set(observed.get("agents") or [])
    checks: list[Check] = []
    extra_metrics: dict[str, Any] = {}
    for pat in expect.must_mention:
        hit = re.search(pat, text, re.I)
        checks.append(Check(name="answer.mentions", passed=bool(hit), detail=f"/{pat}/ {'found' if hit else 'missing'}"))
    for pat in expect.must_not_mention:
        hit = re.search(pat, text, re.I)
        checks.append(Check(name="answer.avoids", passed=not hit, detail=f"/{pat}/ {'present: ' + hit.group(0) if hit else 'absent'}"))
    # One final answer per response, found the same way for every system (runner._score_answer): the \boxed{} value
    # when there is one, else the grader's reading of the stated final answer. Checked strictly: no number elsewhere
    # in the working can rescue it.
    final = observed.get("final_answer")
    stated = final if isinstance(final, str) and final.strip() else None
    graded_text = f"\\boxed{{{stated}}}" if stated else text
    if expect.numeric_answer in (0.0, 1.0):
        # A yes/no question whose gold is coded 1/0 (TheoremQA): "Yes" and "True" are 1, "No" and "False" are 0.
        yn = yes_no_value(stated if stated else (extract_boxed(text) or ""))
        if yn is not None:
            graded_text = f"\\boxed{{{yn}}}"
    if expect.numeric_list is not None:
        l_check, l_metrics = numeric_list_check(expect.numeric_list, stated if stated else text,
                                                abs_tol=expect.numeric_tolerance, rel_tol=expect.numeric_rel_tol)
        checks.append(l_check)
        extra_metrics.update(l_metrics)
    if expect.numeric_answer is not None:
        n_check, n_metrics = numeric_answer_check(
            expect.numeric_answer, graded_text, abs_tol=expect.numeric_tolerance, rel_tol=expect.numeric_rel_tol
        )
        if not n_check.passed and expect.numeric_scale:
            # The same quantity in base units: 4.8e6 for "4.76, in 10^6" (relative tolerance only).
            scaled = expect.numeric_answer * expect.numeric_scale
            s_check, s_metrics = numeric_answer_check(scaled, graded_text, abs_tol=expect.numeric_tolerance * expect.numeric_scale,
                                                      rel_tol=expect.numeric_rel_tol)
            if s_check.passed:
                n_check = Check(name="answer.numeric", passed=True,
                                detail=f"{s_check.detail} (base units for {expect.numeric_answer:g} in units of {expect.numeric_scale:g})")
                n_metrics = {**s_metrics, "numeric_expected": expect.numeric_answer, "numeric_scale": expect.numeric_scale}
        checks.append(n_check)
        extra_metrics.update(n_metrics)
    if expect.symbolic_answer is not None:
        s_check, s_metrics = symbolic_answer_check(expect.symbolic_answer, graded_text)
        checks.append(s_check)
        extra_metrics.update(s_metrics)
    if expect.abstain is True:
        checks.append(Check(name="answer.abstains", passed=abstained(text), detail="says the evidence is missing" if abstained(text) else "does not abstain"))
    elif expect.abstain is False:
        refused = opens_with_refusal(text)
        # Informational: a good answer may open by noting a gap and still answer from labelled background.
        checks.append(Check(name="answer.answers", passed=not refused, required=False,
                            detail="opens with a refusal" if refused else "answers directly"))
    for a in expect.agents_include:
        checks.append(Check(name="answer.agent_ran", passed=a in agents, detail=f"{a} {'ran' if a in agents else 'did not run'}"))
    for a in expect.agents_exclude:
        checks.append(Check(name="answer.agent_skipped", passed=a not in agents, detail=f"{a} {'wrongly ran' if a in agents else 'not run'}"))
    if expect.framework is not None:
        checks.append(Check(name="answer.framework", passed=observed.get("framework") == expect.framework,
                            detail=f"expected {expect.framework}, got {observed.get('framework')}"))
    if expect.verified is not None:
        ok = observed.get("verified") is expect.verified
        checks.append(Check(name="answer.verified", passed=ok,
                            detail=f"verifier passed={observed.get('verified')}; defects: {'; '.join(observed.get('defects', [])[:3])}"))
    cites = cited_pmids(text)
    all_cites = extract_ids(text)
    resolved = set(observed.get("citation_keys") or [])
    unresolved = [p for p in cites if f"PMID:{p}" not in resolved]
    n_cites = max(len(cites), len(all_cites))
    if expect.min_citations:
        checks.append(Check(name="answer.citations", passed=n_cites >= expect.min_citations, detail=f"{n_cites} citation(s) cited"))
    gold = {str(p) for p in gold_pmids}
    if expect.cite_gold and gold:
        hit = sorted(gold & (set(cites) | {c.split(":", 1)[-1] for c in all_cites}))
        checks.append(Check(name="answer.cites_gold", passed=bool(hit), detail=f"cited gold {hit}" if hit else "no gold id cited"))
    if expect.execution is not None:
        checks += execution_checks(expect.execution, observed)
    if expect.max_latency_s is not None and observed.get("latency_s") is not None:
        checks.append(Check(name="answer.latency", passed=observed["latency_s"] <= expect.max_latency_s,
                            detail=f"{observed['latency_s']:.1f}s (limit {expect.max_latency_s}s)"))
    run = run_metrics(observed)
    for name, limit, key in (("answer.budget_tokens", expect.max_tokens, "tokens_est"),
                             ("answer.budget_llm_calls", expect.max_llm_calls, "llm_calls"),
                             ("answer.budget_tool_calls", expect.max_tool_calls, "tool_calls")):
        if limit is None:
            continue
        got = run.get(key)
        if got is None:
            checks.append(Check(name=name, passed=True, required=False, detail=f"{key} not recorded for this run"))
        else:
            checks.append(Check(name=name, passed=got <= limit, detail=f"{key} {got} (limit {limit})"))
    if expect.min_faithfulness is not None:
        faith = run.get("faithfulness")
        checks.append(Check(name="answer.faithfulness", passed=faith is not None and faith >= expect.min_faithfulness,
                            detail=f"faithfulness {faith} (minimum {expect.min_faithfulness})"))
    f_checks, f_metrics = fact_checks(expect.facts, observed.get("response") or "", min_recall=expect.min_fact_recall)
    checks += f_checks
    checks += gate_checks(observed, query=str(observed.get("query") or ""), skip=expect.skip_gates)
    metrics = {
        "cited_pmids": len(cites),
        "unresolved_citations": len(unresolved),
        "gold_cited": bool(gold & (set(cites) | {c.split(":", 1)[-1] for c in all_cites})) if gold else None,
        # An answer abstains when it leads with "not found / no evidence" (LAB-Bench coverage sense); a full answer
        # that honestly notes one missing piece has not abstained.
        "abstained": opens_with_refusal(text) or (len(text.split()) < 80 and abstained(text)),
        "verified": observed.get("verified"),
        "length_words": len(text.split()),
        **run,
        **f_metrics,
        **extra_metrics,
    }
    return checks, metrics


_SIM_TOOLS = (
    "dynamis_simulate_ode", "dynamis_equilibrium", "dynamis_parameter_scan",
    "dynamis_optimize", "dynamis_fit_parameters", "dynamis_root_find",
    "vivarix_simulate_time_course", "vivarix_compute_steady_state", "vivarix_parameter_scan",
)


def execution_checks(expect: ExecutionExpect, observed: dict[str, Any]) -> list[Check]:
    """The execution contract: what ran with which arguments, the task status, and the evidence ids. Wording that
    admits a failure does not pass these; the requested operation must actually have run (or been rejected)."""
    task = observed.get("task_status") or {}
    calls = [c for c in observed.get("tool_calls") or [] if isinstance(c, dict)]
    checks: list[Check] = []
    for field in ("task_status", "requested_operation", "executed_operation"):
        want = getattr(expect, field)
        if want is not None:
            got = task.get(field) or ""
            checks.append(Check(name=f"exec.{field}", passed=got == want, detail=f"expected {want or 'none'}, got {got or 'none'}"))
    if expect.request_match is not None:
        got = task.get("request_match")
        checks.append(Check(name="exec.request_match", passed=got is expect.request_match, detail=f"expected {expect.request_match}, got {got}"))
    called = {c.get("tool_name") for c in calls}
    for tool in expect.tools_called:
        checks.append(Check(name="exec.tool_called", passed=tool in called, detail=f"{tool} {'called' if tool in called else 'not called'}"))
    for tool in expect.tools_not_succeeded:
        ok = [c for c in calls if c.get("tool_name") == tool and c.get("success")]
        checks.append(Check(name="exec.no_substitute", passed=not ok,
                            detail=f"{tool} {'succeeded ' + str(len(ok)) + 'x (substituted result)' if ok else 'did not succeed'}"))
    reported = {str(c.get("error_type")) for c in calls if c.get("error_type")}
    reason = f"{task.get('reason') or ''} {task.get('error_type') or ''}"
    for code in expect.error_types:
        hit = code in reported or code in reason
        checks.append(Check(name="exec.error_type", passed=hit, detail=f"{code} {'reported' if hit else 'not reported'} ({sorted(reported) or 'none'})"))
    scans = [c for c in calls if c.get("tool_name") in ("dynamis_parameter_scan", "vivarix_parameter_scan")]
    if expect.scan_points is not None or expect.scan_bounds or expect.scan_duration_s is not None:
        if not scans:
            checks.append(Check(name="exec.scan_ran", passed=False, detail="parameter_scan was not called"))
        for c in scans[:1]:
            inputs = c.get("inputs") or {}
            if expect.scan_points is not None:
                pts = inputs.get("num_steps") if "num_steps" in inputs else inputs.get("points")
                checks.append(Check(name="exec.scan_points", passed=pts == expect.scan_points,
                                    detail=f"expected {expect.scan_points}, got {pts}"))
            if expect.scan_bounds:
                lo, hi = (expect.scan_bounds + [None, None])[:2]
                s_val = inputs.get("start_val") if "start_val" in inputs else inputs.get("start")
                e_val = inputs.get("end_val") if "end_val" in inputs else inputs.get("end")
                ok = _close(s_val, lo) and _close(e_val, hi)
                checks.append(Check(name="exec.scan_bounds", passed=ok,
                                    detail=f"expected {expect.scan_bounds}, got [{s_val}, {e_val}]"))
            if expect.scan_duration_s is not None:
                checks.append(Check(name="exec.scan_duration", passed=_close(inputs.get("duration"), expect.scan_duration_s),
                                    detail=f"expected {expect.scan_duration_s}s, got {inputs.get('duration')}"))
    if expect.overrides_forwarded:
        sims = [c for c in calls if c.get("tool_name") in _SIM_TOOLS]
        for c in sims:
            got = (c.get("inputs") or c.get("raw_inputs") or {}).get("parameter_overrides") or (c.get("inputs") or {}).get("parameters") or {}
            missing = [n for n in expect.overrides_forwarded if n not in got]
            # A successful run without the requested override is an unchanged simulation, not the experiment asked for.
            ok = not missing or not c.get("success")
            checks.append(Check(name="exec.overrides_forwarded", passed=ok,
                                detail=f"{c.get('tool_name')}: " + (f"missing {missing} (overrides={got or None})" if missing else "forwarded")))
    ids = {str(i).upper() for i in observed.get("evidence_ids") or []}
    for want in expect.evidence_ids:
        checks.append(Check(name="exec.evidence_id", passed=want.upper() in ids, detail=f"{want} {'present' if want.upper() in ids else 'missing'}"))
    for bad in expect.prohibited_evidence_ids:
        checks.append(Check(name="exec.prohibited_evidence", passed=bad.upper() not in ids,
                            detail=f"{bad} {'wrongly present' if bad.upper() in ids else 'absent'}"))
    keys = set(observed.get("artifact_keys") or [])
    for key in expect.artifacts:
        checks.append(Check(name="exec.artifact", passed=key in keys, detail=f"{key} {'present' if key in keys else 'missing'}"))
    for key in expect.no_artifacts:
        checks.append(Check(name="exec.no_artifact", passed=key not in keys, detail=f"{key} {'wrongly present' if key in keys else 'absent'}"))
    return checks


# ---------------------------------------------------------------------------------------------------------------
# Golden facts (SAFE-style fact recall)
# ---------------------------------------------------------------------------------------------------------------

_DECIMAL_DOT = re.compile("(?<=\\d)[\u00b7\u22c5\u2219](?=\\d)")  # "0·30" (Lancet style) is 0.30
_NUM = r"\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?|\.\d+"
_NUMBER_RE = re.compile(rf"(?<![A-Za-z0-9.])(?:(?<![A-Za-z0-9])(-))?({_NUM})(?![\d])")
_RANGE_RE = re.compile(rf"(?<![A-Za-z0-9.])(-?(?:{_NUM}))\s*(?:-|to|,|;)\s*(-?(?:{_NUM}))(?![\d])", re.I)
_MONTHS = ("January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December")


def _fact_text(text: str) -> str:
    return _DECIMAL_DOT.sub(".", normalize(text or ""))


def _to_float(raw: str) -> float | None:
    try:
        return float(raw.replace(",", ""))
    except ValueError:
        return None


def numbers(text: str) -> list[tuple[float, int, int]]:
    """(value, start, end) of every number in already-normalized text."""
    out = []
    for m in _NUMBER_RE.finditer(text):
        v = _to_float(m.group(2))
        if v is not None:
            out.append((-v if m.group(1) else v, m.start(), m.end()))
    return out


def _date_regex(iso: str) -> str:
    y, mo, d = (int(x) for x in iso.split("-"))
    month = _MONTHS[mo - 1]
    names = rf"(?:{month}|{month[:3]}\.?)"
    return (rf"{iso}|{names}\s+0?{d}(?:st|nd|rd|th)?,?\s+{y}|0?{d}(?:st|nd|rd|th)?\s+{names},?\s+{y}"
            rf"|0?{mo}/0?{d}/{y}|{y}/0?{mo}/0?{d}")


def _near(pattern: str | None, text: str, start: int, end: int, window: int) -> bool:
    return pattern is None or bool(re.search(pattern, text[max(0, start - window): end + window], re.I))


def _within(x: float, want: float, tol: float) -> bool:
    return abs(x - want) <= tol + 1e-9


def match_fact(fact: Fact, text: str) -> str | None:
    """The matched snippet when the (normalized) text states the fact, else None."""
    if fact.any_of:
        for alt in fact.any_of:
            hit = match_fact(alt, text)
            if hit is not None:
                return hit
        return None
    if fact.pattern is not None or fact.date is not None:
        regex = fact.pattern if fact.pattern is not None else _date_regex(fact.date or "")
        for m in re.finditer(regex, text, re.I):
            if _near(fact.context, text, m.start(), m.end(), fact.window):
                return m.group(0)[:80]
        return None
    want = float(fact.value or 0.0)
    ci_tol = fact.tolerance if fact.ci_tolerance is None else fact.ci_tolerance
    for v, start, end in numbers(text):
        if not _within(v, want, fact.tolerance) or not _near(fact.context, text, start, end, fact.window):
            continue
        if fact.ci is None:
            return text[max(0, start - 30): end + 10].strip()
        lo, hi = fact.ci
        for r in _RANGE_RE.finditer(text[end: end + fact.window]):
            a, b = _to_float(r.group(1)), _to_float(r.group(2))
            if a is not None and b is not None and _within(a, lo, ci_tol) and _within(b, hi, ci_tol):
                return text[max(0, start - 30): end + r.end() + 2].strip()
    return None


def _fact_label(fact: Fact) -> str:
    if fact.pattern is not None:
        return f"/{fact.pattern}/"
    if fact.date is not None:
        return fact.date
    if fact.value is not None:
        return f"{fact.value}±{fact.tolerance}" + (f" CI {fact.ci}" if fact.ci else "")
    return f"any of {[a.id for a in fact.any_of]}"


def fact_checks(facts: Sequence[Fact], response: str, *, min_recall: float | None = None) -> tuple[list[Check], dict[str, Any]]:
    """One check per fact (informational when min_recall decides), fact_recall over the required facts and the
    ids of the required facts that are missing."""
    if not facts:
        return [], {}
    text = _fact_text(response)
    checks: list[Check] = []
    found: dict[str, bool] = {}
    for fact in facts:
        hit = match_fact(fact, text)
        found[fact.id] = hit is not None
        checks.append(Check(name="answer.fact", passed=hit is not None, required=fact.required and min_recall is None,
                            detail=f"{fact.id}: " + (f"found ({hit})" if hit is not None else f"missing {_fact_label(fact)}")))
    required = [f for f in facts if f.required]
    recall = round(sum(found[f.id] for f in required) / len(required), 3) if required else None
    metrics = {
        "fact_recall": recall,
        "facts_found": sum(found.values()),
        "facts_total": len(facts),
        "facts_missing": [f.id for f in required if not found[f.id]],
        "facts_optional_missing": [f.id for f in facts if not f.required and not found[f.id]],
    }
    if min_recall is not None:
        checks.append(Check(name="answer.fact_recall", passed=recall is not None and recall >= min_recall,
                            detail=f"fact recall {recall} (minimum {min_recall}); missing {metrics['facts_missing'] or 'none'}"))
    return checks, metrics


# ---------------------------------------------------------------------------------------------------------------
# Identifiers, hard gates and run metrics
# ---------------------------------------------------------------------------------------------------------------

GATES = ("answer.citations_in_evidence", "answer.no_internal_leak", "answer.no_crash")

_ID_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("PMID", re.compile(r"\bPMIDs?\s*[:#]?\s*(\d{1,9}(?:\s*(?:,|;|and)\s*(?:PMID\s*:?\s*)?\d{1,9})*)", re.I)),
    ("PMID", re.compile(r"pubmed\.ncbi\.nlm\.nih\.gov/(\d{1,9})", re.I)),
    ("ARXIV", re.compile(r"\barXiv:\s*(\d{4}\.\d{4,5}(?:v\d+)?)\b", re.I)),
    ("ZBL", re.compile(r"\bZbl\s*:?\s*(\d{4}\.\d{5})\b", re.I)),
    ("MR", re.compile(r"\bMR\s*:?\s*(\d{6,8})\b", re.I)),
    ("NCT", re.compile(r"\bNCT\s?(\d{8})\b", re.I)),
    ("CHEMBL", re.compile(r"\bCHEMBL\s?(\d{1,9})\b", re.I)),
    ("FDA", re.compile(r"\b(A?NDA|BLA)\s*(?:#|No\.?|number)?\s*:?\s*(\d{6})\b")),
)


def extract_ids(text: str) -> list[str]:
    """Canonical identifiers in text: arXiv:<id>, Zbl <id>, MR<id>, PMID:<n>, NCT<8>, CHEMBL<n>, NDA/BLA."""
    text = normalize(text or "")
    out: list[str] = []
    for kind, rx in _ID_PATTERNS:
        for m in rx.finditer(text):
            if kind == "PMID":
                out += [f"PMID:{int(n)}" for n in re.findall(r"\d{1,9}", m.group(1))]
            elif kind == "ARXIV":
                out.append(f"arXiv:{m.group(1)}")
            elif kind == "ZBL":
                out.append(f"Zbl {m.group(1)}")
            elif kind == "MR":
                out.append(f"MR{m.group(1)}")
            elif kind == "FDA":
                out.append(f"{m.group(1).upper()}{m.group(2)}")
            elif kind == "NCT":
                out.append(f"NCT{m.group(1)}")
            else:
                out.append(f"CHEMBL{int(m.group(1))}")
    return list(dict.fromkeys(out))


_NON_EVIDENCE_ARTIFACTS = {"claim_confidence", "agent_run", "agent_plan", "agent_dialogue", "hypotheses", "model_calibration",
                           "plan_approval", "project_memory"}


def _walk_ids(node: Any, key: str, out: set, depth: int = 0) -> None:
    if depth > 12:
        return
    if isinstance(node, dict):
        for k, v in node.items():
            out.update(extract_ids(str(k)))
            _walk_ids(v, str(k), out, depth + 1)
    elif isinstance(node, (list, tuple)):
        for v in node:
            _walk_ids(v, key, out, depth + 1)
    elif node is not None and not isinstance(node, bool):
        value = str(node)
        out.update(extract_ids(value))
        if "pmid" in key.lower():
            out.update(f"PMID:{int(n)}" for n in re.findall(r"(?<![\w.])\d{1,9}(?![\w.])", value))
        if "arxiv" in key.lower():
            out.update(f"arXiv:{m}" for m in re.findall(r"\b\d{4}\.\d{4,5}(?:v\d+)?\b", value))


def collect_evidence_ids(payload: dict[str, Any]) -> list[str]:
    """Every identifier the run's evidence holds, canonicalized as extract_ids does."""
    out: set = set()
    manifest = payload.get("run_manifest") or {}
    for call in manifest.get("tool_calls") or []:
        if isinstance(call, dict) and call.get("success") is not False:
            _walk_ids(call.get("canonical_ids") or {}, "", out)
            _walk_ids(call.get("output_digest") or {}, "", out)
    _walk_ids((manifest.get("synthesis") or {}).get("scope_notes") or [], "", out)
    citations = payload.get("citations") or {}
    _walk_ids(citations.get("entries") or {}, "", out)
    _walk_ids(citations.get("aliases") or {}, "", out)
    _walk_ids((payload.get("verification_report") or {}).get("verified_identifiers") or [], "", out)
    artifacts = payload.get("execution_artifacts") or {}
    _walk_ids({k: v for k, v in artifacts.items() if k not in _NON_EVIDENCE_ARTIFACTS}, "", out)
    return sorted(out)


def _canonical_evidence(ids: Iterable[Any]) -> set:
    """Stored evidence ids in canonical form; bare numbers count as PMIDs, bare YYMM.NNNNN as arXiv IDs."""
    out: set = set()
    for raw in ids or []:
        s = str(raw).strip()
        if s.isdigit():
            out.add(f"PMID:{int(s)}")
        elif re.fullmatch(r"\d{4}\.\d{4,5}(?:v\d+)?", s):
            out.add(f"arXiv:{s}")
        else:
            out.update(extract_ids(s))
    return out


_LEAK_RE = re.compile(
    r"(?i:\b(?:Lithoscribe|Synapta|Vivarix|Lumicell|Discovery(?:Agent)?)\b)"
    r"|\bagent\.[a-z_]+\.[\w.-]*\w"
    r"|\b(?:structure_intel|variant_intel|drug_intel|omics_intel|clinical_trials|total_reports|serious_reports|tool_status"
    r"|label_set_id|evidence_sufficiency|ranked_passages|canonical_ids|output_digest)\b"
    r"|\[(?:[A-Z]+_)+[A-Z]+\]"
)
_CODE_OR_URL_RE = re.compile(r"```.*?```|`[^`\n]*`|https?://[^\s)>\]]+|\]\([^)\s]*\)", re.S)


def internal_leaks(text: str) -> list[str]:
    return list(dict.fromkeys(m.group(0) for m in _LEAK_RE.finditer(_CODE_OR_URL_RE.sub(" ", normalize(text or "")))))


def gate_checks(observed: dict[str, Any], *, query: str = "", skip: Sequence[str] = ()) -> list[Check]:
    """Deterministic hard gates (required checks), computed from stored observations only."""
    checks: list[Check] = []
    response = observed.get("response")
    if "answer.no_crash" not in skip:
        ok = isinstance(response, str) and bool(response.strip()) and not observed.get("transport_error")
        checks.append(Check(name="answer.no_crash", passed=ok,
                            detail="answer returned" if ok else f"no answer ({observed.get('transport_error') or 'empty response'})"))
    if "answer.citations_in_evidence" not in skip and "evidence_ids" in observed:
        cited = extract_ids(response or "")
        allowed = _canonical_evidence(observed.get("evidence_ids") or []) | set(extract_ids(query))
        missing = [i for i in cited if i not in allowed]
        checks.append(Check(name="answer.citations_in_evidence", passed=not missing,
                            detail=f"{len(cited)} ids cited, all in the evidence" if not missing
                            else f"not in the evidence: {', '.join(missing[:10])}"))
    if "answer.no_internal_leak" not in skip and observed.get("framework") != "conversational-direct":
        leaks = internal_leaks(response or "")
        checks.append(Check(name="answer.no_internal_leak", passed=not leaks,
                            detail="no internal names" if not leaks else f"leaked: {', '.join(leaks[:8])}"))
    return checks


def run_metrics(observed: dict[str, Any]) -> dict[str, Any]:
    counts = observed.get("claim_counts") or {}
    checked = sum(int(counts.get(k, 0)) for k in ("supported", "unsupported", "contradicted"))
    return {
        "faithfulness": round(int(counts.get("supported", 0)) / checked, 3) if checked else None,
        "claims_checked": checked,
        "steps_failed": observed.get("steps_failed"),
        "llm_calls": observed.get("llm_calls"),
        "tool_calls": observed.get("tool_calls_n"),
        "tokens_est": observed.get("tokens_est"),
        "latency_s": observed.get("latency_s"),
    }


# ---------------------------------------------------------------------------------------------------------------
# Benchmark labels (deterministic parts; grading.py adds a model-based extractor)
# ---------------------------------------------------------------------------------------------------------------


def heuristic_yesno(text: str, options: Sequence[str] = ("yes", "no", "maybe")) -> str | None:
    """An explicit opening verdict ("Yes. ...", "No, ...", "**No** - ..."), else None for the model grader to decide."""
    head = re.sub(r"^[\s*_#>]+", "", normalize(text).strip())[:40].lower()
    m = re.match(r"^(yes|no)\**\s*[,.;:!—–-]", head)
    return m.group(1) if m and m.group(1) in options else None


_CHOICE_LETTER_RE = re.compile(
    # Keywords in any case; the letter itself must be a capital, so "the answer is a reaction" is not option (A).
    r"(?:(?i:answer)\s*(?i:is)?\s*[:=]?\s*\**\(?([A-Z])\)?\**(?![A-Za-z])|\\boxed\{\s*\(?([A-Z])\)?\s*\}"
    r"|\b(?i:option|choice)\s*\(?([A-Z])\)(?![A-Za-z]))")


def heuristic_choice(text: str, options: Sequence[str]) -> str | None:
    """The single option the answer names (ignoring the insufficient-information option), else None.

    Lettered options ((A) ... (D), in the order of `options`): the last "Answer: B", \\boxed{B} or "option (B)" in the
    answer picks options[1]."""
    letters = [next(g for g in m.groups() if g) for m in _CHOICE_LETTER_RE.finditer(normalize(text or ""))]
    if letters and 1 < len(options) <= 26:
        index = ord(letters[-1]) - 65
        if 0 <= index < len(options):
            return options[index]
    low = normalize(text).lower()
    named = [o for o in options if not o.lower().startswith("insufficient") and re.search(rf"(?<!\w){re.escape(o.lower())}(?!\w)", low)]
    if len(named) == 1:
        return named[0]
    insufficient = [o for o in options if o.lower().startswith("insufficient")]
    if not named and insufficient and abstained(text):
        return insufficient[0]
    return None


def label_checks(expect: AnswerExpect, predicted: str | None) -> tuple[list[Check], dict[str, Any]]:
    if expect.label is None:
        return [], {}
    gold = expect.label.strip().lower()
    pred = (predicted or "").strip().lower() or None
    insufficient = bool(pred and pred.startswith("insufficient"))
    correct = pred == gold
    metrics = {"label": gold, "predicted": pred, "correct": correct, "answered": pred is not None and not insufficient}
    return [Check(name="answer.label", passed=correct, detail=f"expected {gold}, got {pred}")], metrics


def exact_checks(expect: AnswerExpect, text: str) -> tuple[list[Check], dict[str, Any]]:
    """Factoid: any synonym of any group named (lenient accuracy). List: share of groups named (>= 50% passes)."""
    if not expect.exact:
        return [], {}
    low = normalize(text).lower()
    named = [any(re.search(rf"(?<!\w){re.escape(s.lower())}(?!\w)", low) for s in g) for g in expect.exact]
    if expect.answer_type == "list":
        recall = sum(named) / len(named)
        return [Check(name="answer.list_recall", passed=recall >= 0.5, detail=f"{sum(named)}/{len(named)} items named")], {"list_recall": round(recall, 3)}
    return [Check(name="answer.factoid", passed=any(named), detail="named" if any(named) else "not named")], {"factoid_correct": any(named)}


__all__ = [
    "GATES",
    "abstained",
    "answer_checks",
    "cited_pmids",
    "collect_evidence_ids",
    "exact_checks",
    "execution_checks",
    "extract_boxed",
    "extract_ids",
    "extract_numeric_answer",
    "fact_checks",
    "gate_checks",
    "heuristic_choice",
    "heuristic_yesno",
    "internal_leaks",
    "label_checks",
    "latex_to_sympy_str",
    "match_fact",
    "normalize",
    "numbers",
    "numeric_answer_check",
    "numeric_within_tolerance",
    "opens_with_refusal",
    "parse_sympy_expr",
    "plan_checks",
    "retrieval_scores",
    "run_metrics",
    "simulation_checks",
    "symbolic_answer_check",
    "symbolic_equivalent",
]
