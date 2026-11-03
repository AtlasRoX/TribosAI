"""
Accuracy tools: checks that make a numerical or mathematical claim trustworthy, or show that it is not.

- interval_verify: rigorous enclosure of f over a box, and a proof (or refutation) of f > 0, f >= 0, f < 0, f <= 0 on
  the box by interval branch and bound (mpmath.iv, outward rounding). "proved" is a proof; "undecided" is not.
- precision_check: f at 15, 30, 60 and 120 significant digits and in ordinary float64, with the digits that agree.
  It catches catastrophic cancellation: a float result that has lost most of its digits.
- counterexample_search: tries to falsify a claimed relation or integer property on exact rationals and integers
  (edges, a grid, seeded random samples). It returns a counterexample, or "none found", which is evidence and not
  a proof, unless the stated domain was finite and searched exhaustively.
- compare_results / cross_validate: two independently written implementations, each setting `result`, run in the
  sandbox; every named number is compared within a tolerance. Agreement is what the research ledger calls
  "replicated".
- distribution_tests: normality tests (Shapiro-Wilk, D'Agostino K^2, Anderson-Darling, Kolmogorov-Smirnov against
  the fitted normal), skewness, excess kurtosis, bootstrap confidence intervals and Q-Q plot points.

Every function returns a JSON-safe dict with a `status` and plain-language `note`.
"""

from __future__ import annotations

import math
import random
import re
import time
from fractions import Fraction
from typing import Any

import sympy as sp

from .certified_critical import _interval_fn

MAX_BOXES = 40_000
MAX_SAMPLES = 20_000
_REL_RE = re.compile(r"(<=|>=|==|!=|<|>)")
_PREDICATES = ("isprime", "is_integer", "is_square")
_CLAIMS = {
    "positive": ("> 0", lambda v: v.a > 0, lambda v: v.b <= 0),
    "nonnegative": (">= 0", lambda v: v.a >= 0, lambda v: v.b < 0),
    "negative": ("< 0", lambda v: v.b < 0, lambda v: v.a >= 0),
    "nonpositive": ("<= 0", lambda v: v.b <= 0, lambda v: v.a > 0),
}


def _parse(expression: str) -> sp.Expr:
    from .engine import safe_parse_expr

    expr = safe_parse_expr(str(expression))
    if not isinstance(expr, sp.Expr):
        raise ValueError(f"not a single expression: {expression!r}")
    return expr


def _symbols(expr: sp.Expr, names: list[str]) -> tuple[sp.Symbol, ...]:
    by_name = {s.name: s for s in expr.free_symbols}
    missing = sorted(set(by_name) - set(names))
    if missing:
        raise ValueError(f"no range given for {', '.join(missing)}")
    return tuple(by_name.get(n, sp.Symbol(n)) for n in names)


def _f(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError, OverflowError):
        return float("nan")


# ---------------------------------------------------------------------------------------------------------------
# Interval verification
# ---------------------------------------------------------------------------------------------------------------

def interval_verify(expression: str, bounds: dict[str, list[float]], claim: str = "enclose", *,
                    max_boxes: int = MAX_BOXES, min_width: float = 1e-9, time_limit_s: float = 8.0) -> dict[str, Any]:
    """Enclose f over the box, or prove/refute a sign claim on it by bisection with interval arithmetic."""
    from mpmath import iv

    claim = (claim or "enclose").strip().lower()
    if claim not in _CLAIMS and claim != "enclose":
        raise ValueError(f"claim must be one of enclose, {', '.join(_CLAIMS)}")
    names = list(bounds)
    if not names:
        raise ValueError("give a range [lo, hi] for every variable")
    expr = _parse(expression)
    variables = _symbols(expr, names)
    fn = _interval_fn(expr, variables)
    if fn is None:
        return {"status": "unsupported", "expression": str(expr),
                "note": "The expression uses a function interval arithmetic does not cover here (allowed: sin, cos, tan, "
                        "exp, log, sqrt, sinh, cosh, tanh, atan, powers and arithmetic)."}
    box0 = []
    for n in names:
        lo, hi = (float(v) for v in bounds[n])
        if not lo <= hi:
            raise ValueError(f"empty range for {n}: [{lo}, {hi}]")
        box0.append(iv.mpf([lo, hi]))

    def value(box: list[Any]) -> Any:
        return fn(*box)

    started = time.perf_counter()
    if claim == "enclose":
        # Subdividing tightens the enclosure: the union of the parts' enclosures is still rigorous.
        parts = [box0]
        for _ in range(6):
            nxt = []
            for b in parts:
                k = max(range(len(b)), key=lambda i: float(b[i].delta))
                mid = b[k].mid
                nxt += [b[:k] + [iv.mpf([b[k].a, mid])] + b[k + 1:], b[:k] + [iv.mpf([mid, b[k].b])] + b[k + 1:]]
            parts = nxt
            if len(parts) >= 256:
                break
        vals = [value(b) for b in parts]
        lo, hi = min(_f(v.a) for v in vals), max(_f(v.b) for v in vals)
        return {"status": "enclosed", "expression": str(expr), "bounds": bounds, "enclosure": [lo, hi],
                "boxes": len(parts), "seconds": round(time.perf_counter() - started, 3),
                "note": "Every value of f on the box lies in this interval (outward-rounded interval arithmetic). The "
                        "interval may be wider than the true range; it is never narrower.",
                "certificate": _interval_script(str(expr), names, bounds, "enclose")}
    label, proves, refutes = _CLAIMS[claim]
    stack, proved_boxes, undecided = [box0], 0, []
    while stack:
        if proved_boxes + len(undecided) + len(stack) > max_boxes or time.perf_counter() - started > time_limit_s:
            undecided += stack
            break
        box = stack.pop()
        v = value(box)
        if proves(v):
            proved_boxes += 1
            continue
        mid = [iv.mpf(float(b.mid)) for b in box]
        vm = value(mid)
        if refutes(vm):
            point = {n: float(b.mid) for n, b in zip(names, box, strict=True)}
            return {"status": "refuted", "expression": str(expr), "claim": f"f {label}", "bounds": bounds,
                    "counterexample": point, "value_enclosure": [_f(vm.a), _f(vm.b)],
                    "seconds": round(time.perf_counter() - started, 3),
                    "note": f"f {label} is false: at this point f is rigorously enclosed in the interval shown."}
        if max(float(b.delta) for b in box) < min_width:
            undecided.append(box)
            continue
        k = max(range(len(box)), key=lambda i: float(box[i].delta))
        m = box[k].mid
        stack += [box[:k] + [iv.mpf([box[k].a, m])] + box[k + 1:], box[:k] + [iv.mpf([m, box[k].b])] + box[k + 1:]]
    seconds = round(time.perf_counter() - started, 3)
    if not undecided:
        return {"status": "proved", "expression": str(expr), "claim": f"f {label}", "bounds": bounds,
                "boxes": proved_boxes, "seconds": seconds,
                "note": f"Proved: f {label} on the whole box. Each of the {proved_boxes} sub-boxes has a rigorous interval "
                        "enclosure of f on the required side of 0.",
                "certificate": _interval_script(str(expr), names, bounds, claim)}
    return {"status": "undecided", "expression": str(expr), "claim": f"f {label}", "bounds": bounds,
            "boxes": proved_boxes, "undecided_boxes": len(undecided),
            "example_undecided": {n: [_f(b.a), _f(b.b)] for n, b in zip(names, undecided[0], strict=True)},
            "seconds": seconds,
            "note": "Not proved and not refuted: some boxes stayed undecided (f touches 0 there, or the limits were "
                    "reached). This is not evidence either way."}


def _interval_script(expression: str, names: list[str], bounds: dict[str, list[float]], claim: str) -> str:
    """A standalone mpmath script that repeats the check (the certificate)."""
    args = ", ".join(names)
    box = ", ".join(f"iv.mpf([{float(bounds[n][0])!r}, {float(bounds[n][1])!r}])" for n in names)
    return (
        "# Interval-arithmetic certificate (mpmath.iv, outward rounding). Run: python certificate.py\n"
        "from mpmath import iv\nfrom mpmath.ctx_iv import ivmpf\n"
        "sin, cos, tan, exp, log, sqrt = iv.sin, iv.cos, iv.tan, iv.exp, iv.log, iv.sqrt\n"
        "pi = iv.pi\n\n"
        f"def f({args}):\n    return {expression}\n\n"
        f"CLAIM = {claim!r}\n"
        f"stack = [[{box}]]\nproved = 0\n"
        "while stack:\n"
        "    b = stack.pop()\n"
        "    v = f(*b)\n"
        "    if CLAIM == 'enclose':\n        print('f on the box lies in', v); break\n"
        "    ok = {'positive': v.a > 0, 'nonnegative': v.a >= 0, 'negative': v.b < 0, 'nonpositive': v.b <= 0}[CLAIM]\n"
        "    if ok:\n        proved += 1\n        continue\n"
        "    k = max(range(len(b)), key=lambda i: float(b[i].delta))\n"
        "    if float(b[k].delta) < 1e-9:\n        raise SystemExit('undecided box: ' + str(b))\n"
        "    m = b[k].mid\n"
        "    stack += [b[:k] + [iv.mpf([b[k].a, m])] + b[k+1:], b[:k] + [iv.mpf([m, b[k].b])] + b[k+1:]]\n"
        "else:\n    print('proved on', proved, 'boxes')\n"
    )


# ---------------------------------------------------------------------------------------------------------------
# Precision check
# ---------------------------------------------------------------------------------------------------------------

def _agree_digits(a: str, b: str) -> int:
    """Significant digits two decimal strings share (0 when they differ in sign or magnitude)."""
    try:
        x, y = sp.Float(a, 200), sp.Float(b, 200)
    except (TypeError, ValueError):
        return 0
    if x == y:
        return 120
    if x == 0 or y == 0 or (x > 0) != (y > 0):
        return 0
    rel = abs((x - y) / y)
    return max(0, int(math.floor(-math.log10(float(rel))))) if rel > 0 else 120


def precision_check(expression: str, values: dict[str, Any] | None = None,
                    digits: list[int] | None = None) -> dict[str, Any]:
    """f at increasing precision and in float64; flags lost digits (cancellation) and instability."""
    values = dict(values or {})
    expr = _parse(expression)
    names = [s.name for s in expr.free_symbols]
    missing = sorted(set(names) - set(values))
    if missing:
        raise ValueError(f"give a value for {', '.join(missing)}")
    exact = {sp.Symbol(k): sp.Rational(str(v)) for k, v in values.items() if k in names}
    precisions = sorted({int(d) for d in (digits or [15, 30, 60, 120]) if 5 <= int(d) <= 500})
    evaluated = []
    for d in precisions:
        v = sp.N(expr.subs(exact), d)
        evaluated.append({"digits": d, "value": str(v)})
    ref = evaluated[-1]["value"]
    stable = _agree_digits(evaluated[-2]["value"], ref) if len(evaluated) > 1 else 0
    try:
        f64 = sp.lambdify(list(exact), expr, modules="math")(*[float(v) for v in exact.values()])
        f64_text = repr(float(f64))
        f64_digits = _agree_digits(f64_text, ref)
    except Exception as exc:  # noqa: BLE001 - a float overflow or domain error is itself the finding
        f64_text, f64_digits = f"error: {type(exc).__name__}", 0
    lost = max(0, 15 - f64_digits)
    status = "unstable" if stable < 10 else ("cancellation" if lost >= 6 else "ok")
    note = {
        "ok": f"Stable: the high-precision values agree to {min(stable, 100)} digits and float64 keeps {f64_digits} correct digits.",
        "cancellation": f"Float64 keeps only {f64_digits} correct significant digits ({lost} lost to cancellation or "
                        "rounding); use exact or high-precision arithmetic, or rewrite the formula.",
        "unstable": "The value changes with the working precision: the expression is ill-conditioned at this point.",
    }[status]
    return {"status": status, "expression": str(expr), "values": {k: str(v) for k, v in values.items()},
            "evaluations": evaluated, "float64": f64_text, "float64_correct_digits": f64_digits,
            "stable_digits": min(stable, 120), "note": note}


# ---------------------------------------------------------------------------------------------------------------
# Counterexample search
# ---------------------------------------------------------------------------------------------------------------

def _claim_checker(claim: str) -> tuple[Any, str]:
    """A function point -> True (holds) / False (fails) / None (undecidable here), and the claim's normal form."""
    text = str(claim or "").strip()
    pred = re.fullmatch(r"(isprime|is_integer|is_square)\s*\((.*)\)", text, re.S)
    if pred:
        name, inner = pred.group(1), _parse(pred.group(2))

        def check_pred(sub: dict[sp.Symbol, Any]) -> bool | None:
            v = sp.nsimplify(inner.subs(sub))
            if not v.is_Rational:
                return None
            if name == "is_integer":
                return bool(v.is_Integer)
            if not v.is_Integer:
                return False
            n = int(v)
            if name == "isprime":
                return bool(sp.isprime(n))
            return n >= 0 and math.isqrt(n) ** 2 == n

        return check_pred, f"{name}({inner})"
    parts = _REL_RE.split(text, maxsplit=1)
    if len(parts) != 3:
        raise ValueError("state the claim as 'lhs <op> rhs' (op one of <, <=, >, >=, ==, !=) or isprime(...), "
                         "is_integer(...), is_square(...)")
    lhs, op, rhs = _parse(parts[0]), parts[1], _parse(parts[2])
    diff = sp.simplify(lhs - rhs) if op in ("==", "!=") else lhs - rhs

    def check_rel(sub: dict[sp.Symbol, Any]) -> bool | None:
        d = diff.subs(sub)
        if d.has(sp.zoo, sp.nan, sp.oo, -sp.oo):
            return None
        dv = sp.nsimplify(d) if d.is_number and not d.is_Rational else d
        if dv.is_Rational:
            q = Fraction(int(dv.p), int(dv.q))
        else:
            val = sp.N(d, 60)
            if not val.is_real:
                return None
            if abs(val) < sp.Float("1e-45", 60):
                q = Fraction(0)
            else:
                q = Fraction(str(val))
        return {"<": q < 0, "<=": q <= 0, ">": q > 0, ">=": q >= 0, "==": q == 0, "!=": q != 0}[op]

    return check_rel, f"{lhs} {op} {rhs}"


def counterexample_search(claim: str, domain: dict[str, dict[str, Any]], *, samples: int = 4000,
                          seed: int = 0) -> dict[str, Any]:
    """Search for a point where the claim fails. Integer domains small enough are searched exhaustively."""
    check, normal = _claim_checker(claim)
    names = list(domain)
    if not names:
        raise ValueError("give a domain for every variable, e.g. {'n': {'type': 'integer', 'min': 0, 'max': 1000}}")
    samples = max(10, min(int(samples), MAX_SAMPLES))
    rng = random.Random(seed)
    axes: list[list[Any]] = []
    sizes = []
    for n in names:
        spec = domain[n] or {}
        kind = str(spec.get("type", "real")).lower()
        lo, hi = spec.get("min", -10), spec.get("max", 10)
        if kind == "integer":
            lo_i, hi_i = int(lo), int(hi)
            if hi_i < lo_i:
                raise ValueError(f"empty range for {n}")
            sizes.append(hi_i - lo_i + 1)
            axes.append(["int", lo_i, hi_i])
        else:
            lo_q, hi_q = Fraction(str(lo)), Fraction(str(hi))
            if hi_q < lo_q:
                raise ValueError(f"empty range for {n}")
            sizes.append(None)
            axes.append(["rat", lo_q, hi_q])
    finite = all(s is not None for s in sizes)
    total = math.prod(s for s in sizes if s is not None) if finite else None
    exhaustive = bool(finite and total is not None and total <= samples)
    syms = [sp.Symbol(n) for n in names]

    def points() -> Any:
        if exhaustive:
            import itertools

            yield from itertools.product(*[range(a[1], a[2] + 1) for a in axes])
            return
        edge_lists = []
        for a in axes:
            if a[0] == "int":
                edge_lists.append(sorted({a[1], a[2], max(a[1], min(a[2], 0)), max(a[1], min(a[2], 1)),
                                          max(a[1], min(a[2], -1))}))
            else:
                edge_lists.append(sorted({a[1], a[2], max(a[1], min(a[2], Fraction(0))),
                                          max(a[1], min(a[2], Fraction(1))), (a[1] + a[2]) / 2}))
        import itertools

        for p in itertools.islice(itertools.product(*edge_lists), samples // 4):
            yield p
        while True:
            p = []
            for a in axes:
                if a[0] == "int":
                    p.append(rng.randint(a[1], a[2]))
                else:
                    den = rng.choice((1, 2, 3, 4, 7, 10, 64, 1000))
                    p.append(a[1] + Fraction(rng.randint(0, den), den) * (a[2] - a[1]))
            yield tuple(p)

    checked, undecidable = 0, 0
    started = time.perf_counter()
    for p in points():
        if checked >= samples or time.perf_counter() - started > 20:
            break
        checked += 1
        sub = {s: (sp.Integer(v) if isinstance(v, int) else sp.Rational(v.numerator, v.denominator))
               for s, v in zip(syms, p, strict=True)}
        ok = check(sub)
        if ok is None:
            undecidable += 1
            continue
        if not ok:
            point = {n: (v if isinstance(v, int) else str(v)) for n, v in zip(names, p, strict=True)}
            return {"status": "counterexample", "claim": normal, "counterexample": point, "checked": checked,
                    "note": "The claim is false: it fails at this point (checked in exact arithmetic)."}
    if exhaustive and checked >= (total or 0) and undecidable == 0:
        return {"status": "verified_exhaustively", "claim": normal, "checked": checked, "exhaustive": True,
                "note": f"The claim holds at every one of the {checked} points of the stated finite domain (exhaustive "
                        "check in exact arithmetic): for this domain, a proof by enumeration."}
    return {"status": "none_found", "claim": normal, "checked": checked, "undecidable_points": undecidable,
            "exhaustive": False,
            "note": f"No counterexample in {checked} points (edges, then seeded random samples). This is evidence, not a "
                    "proof: the claim may still fail elsewhere."}


# ---------------------------------------------------------------------------------------------------------------
# Cross-validation of two implementations
# ---------------------------------------------------------------------------------------------------------------

def _flatten(value: Any, prefix: str = "", out: dict[str, Any] | None = None, limit: int = 2000) -> dict[str, Any]:
    out = {} if out is None else out
    if len(out) >= limit:
        return out
    if isinstance(value, dict):
        for k, v in value.items():
            _flatten(v, f"{prefix}.{k}" if prefix else str(k), out, limit)
    elif isinstance(value, (list, tuple)):
        for i, v in enumerate(value[:500]):
            _flatten(v, f"{prefix}[{i}]", out, limit)
    else:
        out[prefix or "result"] = value
    return out


def _as_number(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(Fraction(value.strip())) if re.fullmatch(r"\s*-?\d+(/\d+)?\s*", value) else float(value)
        except (ValueError, ZeroDivisionError, OverflowError):
            return None
    return None


def compare_results(a: Any, b: Any, *, rtol: float = 1e-9, atol: float = 1e-12,
                    keys: list[str] | None = None) -> dict[str, Any]:
    """Compare two `result` values quantity by quantity. Integers must match exactly; floats within tolerance."""
    fa, fb = _flatten(a), _flatten(b)
    names = list(keys or sorted(set(fa) | set(fb)))
    rows, agree, disagree, missing = [], 0, 0, 0
    for k in names:
        if k not in fa or k not in fb:
            missing += 1
            rows.append({"quantity": k, "a": fa.get(k), "b": fb.get(k), "agree": False, "why": "missing in one result"})
            continue
        va, vb = fa[k], fb[k]
        na, nb = _as_number(va), _as_number(vb)
        if na is not None and nb is not None:
            both_int = isinstance(va, int) and isinstance(vb, int) and not isinstance(va, bool)
            if both_int:
                ok = va == vb
            elif math.isnan(na) or math.isnan(nb):
                ok = math.isnan(na) and math.isnan(nb)
            else:
                ok = math.isclose(na, nb, rel_tol=rtol, abs_tol=atol)
            row = {"quantity": k, "a": va, "b": vb, "agree": ok}
            if not ok and not both_int:
                row["relative_difference"] = abs(na - nb) / max(abs(na), abs(nb), 1e-300)
        else:
            ok = str(va) == str(vb)
            row = {"quantity": k, "a": va, "b": vb, "agree": ok}
        agree += ok
        disagree += not ok
        rows.append(row)
    status = "agree" if names and disagree == 0 else ("disagree" if names else "empty")
    return {"status": status, "compared": len(names), "agree": agree, "disagree": disagree, "missing": missing,
            "rtol": rtol, "atol": atol, "rows": rows[:200],
            "note": {"agree": f"All {len(names)} quantities agree between the two independent implementations.",
                     "disagree": f"{disagree} of {len(names)} quantities differ: at least one implementation is wrong.",
                     "empty": "Neither implementation set `result`; nothing was compared."}[status]}


def cross_validate(code_a: str, code_b: str, *, rtol: float = 1e-9, atol: float = 1e-12,
                   keys: list[str] | None = None, timeout_s: float | None = None) -> dict[str, Any]:
    """Run two independent implementations in the sandbox (each must set `result`) and compare them."""
    from tribos.agentic.sandbox.gateway import execute

    reports = [execute(code, timeout_s=timeout_s) for code in (code_a, code_b)]
    failed = [i for i, r in enumerate(reports) if r.get("status") != "ok"]
    if failed:
        return {"status": "error",
                "errors": {("a", "b")[i]: str(reports[i].get("error") or reports[i].get("stderr") or
                                              reports[i].get("status"))[:600] for i in failed},
                "note": "An implementation failed to run, so nothing was compared."}
    out = compare_results(reports[0].get("result"), reports[1].get("result"), rtol=rtol, atol=atol, keys=keys)
    out["seconds"] = [r.get("seconds") for r in reports]
    return out


# ---------------------------------------------------------------------------------------------------------------
# Distribution tests
# ---------------------------------------------------------------------------------------------------------------

def distribution_tests(data: list[float], *, alpha: float = 0.05, bootstrap: int = 2000,
                       seed: int = 0) -> dict[str, Any]:
    """Normality tests, moments, bootstrap confidence intervals and Q-Q points for one sample."""
    import numpy as np
    from scipy import stats

    x = np.asarray([v for v in data if v is not None and math.isfinite(float(v))], dtype=float)
    n = int(x.size)
    if n < 8:
        raise ValueError("need at least 8 finite values")
    rng = np.random.default_rng(seed)
    mean, sd = float(x.mean()), float(x.std(ddof=1))
    tests: dict[str, Any] = {}
    sw_sample = x if n <= 5000 else rng.choice(x, 5000, replace=False)
    w, p = stats.shapiro(sw_sample)
    tests["shapiro_wilk"] = {"statistic": float(w), "p_value": float(p), "n_used": int(sw_sample.size),
                             "rejects_normality": bool(p < alpha)}
    if n >= 20:
        k2, p2 = stats.normaltest(x)
        tests["dagostino_k2"] = {"statistic": float(k2), "p_value": float(p2), "rejects_normality": bool(p2 < alpha)}
    ad = stats.anderson(x, dist="norm")
    level = min(range(len(ad.significance_level)), key=lambda i: abs(ad.significance_level[i] - alpha * 100))
    tests["anderson_darling"] = {"statistic": float(ad.statistic),
                                 "critical_value": float(ad.critical_values[level]),
                                 "significance_percent": float(ad.significance_level[level]),
                                 "rejects_normality": bool(ad.statistic > ad.critical_values[level])}
    if sd > 0:
        d, p3 = stats.kstest(x, "norm", args=(mean, sd))
        tests["kolmogorov_smirnov"] = {"statistic": float(d), "p_value": float(p3),
                                       "rejects_normality": bool(p3 < alpha),
                                       "caveat": "parameters estimated from the data: this p-value is conservative "
                                                 "(Lilliefors)"}
    boots = max(200, min(int(bootstrap), 20000))
    sample = x if n <= 20000 else rng.choice(x, 20000, replace=False)
    idx = rng.integers(0, sample.size, size=(boots, sample.size))
    bmeans = sample[idx].mean(axis=1)
    bmeds = np.median(sample[idx], axis=1)
    lo_q, hi_q = 100 * alpha / 2, 100 * (1 - alpha / 2)
    qq_n = min(n, 200)
    probs = (np.arange(1, qq_n + 1) - 0.5) / qq_n
    ordered = np.quantile(x, probs)
    theo = stats.norm.ppf(probs, loc=mean, scale=sd if sd > 0 else 1.0)
    rejected = [k for k, t in tests.items() if t.get("rejects_normality")]
    status = "normal_rejected" if len(rejected) >= 2 else ("mixed" if rejected else "consistent_with_normal")
    return {
        "status": status, "n": n, "mean": mean, "std": sd, "median": float(np.median(x)),
        "skewness": float(stats.skew(x)), "excess_kurtosis": float(stats.kurtosis(x)),
        "tests": tests, "alpha": alpha,
        "bootstrap": {"resamples": boots, "mean_ci": [float(np.percentile(bmeans, lo_q)), float(np.percentile(bmeans, hi_q))],
                      "median_ci": [float(np.percentile(bmeds, lo_q)), float(np.percentile(bmeds, hi_q))],
                      "level": 1 - alpha},
        "qq": {"theoretical": [float(v) for v in theo], "sample": [float(v) for v in ordered]},
        "note": {"normal_rejected": f"Normality is rejected at alpha={alpha} by {len(rejected)} tests ({', '.join(rejected)}).",
                 "mixed": f"The tests disagree: only {', '.join(rejected)} rejects normality at alpha={alpha}.",
                 "consistent_with_normal": f"No test rejects normality at alpha={alpha}; that does not prove the data "
                                           "are normal, only that these tests found no departure."}[status],
    }


__all__ = ["compare_results", "counterexample_search", "cross_validate", "distribution_tests", "interval_verify",
           "precision_check"]
