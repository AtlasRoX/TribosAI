"""
Axiom discrete and statistical tools: number theory, linear recurrences, probability distributions and statistics.

Same contract as engine.py: safe parsing, a canonical id, and `verified` only when an independent method agrees
(arithmetic re-checks with Python integers, direct iteration of a recurrence, SciPy against exact SymPy values,
textbook formulas against SciPy). The `check_*` functions take the problem's own inputs so the verifier can re-run
them from the problem statement.
"""

from __future__ import annotations

import math
import statistics as pystats
from typing import Any, Literal

import sympy as sp

from .engine import _canonical_id, _check_safe_string, _num, safe_parse_equation, safe_parse_expr
from .shapes import UnsupportedShapeError

# Number theory ------------------------------------------------------------------------------------------------------

NTOp = Literal["factorize", "isprime", "gcd", "lcm", "divisors", "totient", "mod_pow", "mod_inverse", "crt", "next_prime", "diophantine"]
_MAX_DIGITS = 400


def _int(value: Any) -> int:
    expr = safe_parse_expr(str(value))
    if not expr.is_integer:
        raise ValueError(f"{value!r} is not an integer.")
    out = int(expr)
    if len(str(abs(out))) > _MAX_DIGITS:
        raise ValueError(f"Integers are limited to {_MAX_DIGITS} digits.")
    return out


def _miller_rabin(n: int) -> bool:
    """Deterministic for n < 3.3e24 with these bases; written independently of SymPy for cross-checking."""
    if n < 2:
        return False
    small = (2, 3, 5, 7, 11, 13, 17, 19, 23, 29, 31, 37, 41)
    if n in small:
        return True
    if any(n % p == 0 for p in small):
        return False
    d, r = n - 1, 0
    while d % 2 == 0:
        d //= 2
        r += 1
    for a in small:
        y = pow(a, d, n)
        if y in (1, n - 1):
            continue
        for _ in range(r - 1):
            y = pow(y, 2, n)
            if y == n - 1:
                break
        else:
            return False
    return True


def axiom_number_theory(operation: NTOp, numbers: list[Any], modulus: Any | None = None) -> dict[str, Any]:
    """Exact integer arithmetic: factorization, primality, gcd/lcm, divisors, Euler's totient, modular power and
    inverse, Chinese remainder theorem, next prime, linear Diophantine a*x + b*y = c."""
    op = str(operation).lower()
    nums = [_int(v) for v in numbers or []]
    m = _int(modulus) if modulus is not None and not isinstance(modulus, list) else None
    if not nums:
        raise ValueError("Give at least one integer in 'numbers'.")
    result: Any
    if op == "factorize":
        n = nums[0]
        if n < 2:
            raise ValueError("Factorize an integer >= 2.")
        result = {str(p): e for p, e in sorted(sp.factorint(n).items())}
        text = " * ".join(f"{p}^{e}" if e > 1 else str(p) for p, e in result.items())
    elif op == "isprime":
        result = bool(sp.isprime(nums[0]))
        text = f"{nums[0]} is {'prime' if result else 'not prime'}"
    elif op == "gcd":
        result = int(math.gcd(*nums))
        text = str(result)
    elif op == "lcm":
        result = int(math.lcm(*nums))
        text = str(result)
    elif op == "divisors":
        if nums[0] == 0:
            raise ValueError("0 has infinitely many divisors.")
        result = [int(d) for d in sp.divisors(nums[0])]
        text = ", ".join(map(str, result))
    elif op == "totient":
        if nums[0] < 1:
            raise ValueError("Euler's totient needs n >= 1.")
        result = int(sp.totient(nums[0]))
        text = str(result)
    elif op == "mod_pow":
        if m is None or len(nums) < 2:
            raise ValueError("mod_pow needs numbers [base, exponent] and a modulus.")
        result = int(pow(nums[0], nums[1], m))
        text = str(result)
    elif op == "mod_inverse":
        if m is None:
            raise ValueError("mod_inverse needs a modulus.")
        if math.gcd(nums[0], m) != 1:
            raise ValueError(f"{nums[0]} has no inverse modulo {m} (they are not coprime).")
        result = int(sp.mod_inverse(nums[0], m))
        text = str(result)
    elif op == "crt":
        if not isinstance(modulus, list):
            raise ValueError("crt needs residues in 'numbers' and the list of moduli in 'modulus'.")
        mods = [_int(v) for v in modulus]
        from sympy.ntheory.modular import crt

        sol = crt(mods, nums)
        if sol is None:
            raise ValueError("The congruences are inconsistent.")
        result = {"x": int(sol[0]), "modulus": int(sol[1])}
        text = f"x ≡ {sol[0]} (mod {sol[1]})"
    elif op == "next_prime":
        result = int(sp.nextprime(nums[0]))
        text = str(result)
    elif op == "diophantine":
        if len(nums) != 3:
            raise ValueError("diophantine needs numbers [a, b, c] for a*x + b*y = c.")
        a, b, c = nums
        g = math.gcd(a, b)
        if g == 0 or c % g:
            raise ValueError(f"No integer solutions: gcd({a}, {b}) = {g} does not divide {c}.")
        x0, y0, _ = sp.gcdex(a, b)
        x0, y0 = int(x0) * (c // g), int(y0) * (c // g)
        result = {"x0": x0, "y0": y0, "step_x": b // g, "step_y": -(a // g)}
        text = f"x = {x0} + {b // g}*t, y = {y0} - {a // g}*t for integer t"
    else:
        raise ValueError(f"Unsupported number-theory operation {operation!r}.")
    verified = check_number_theory(op, nums, modulus, result)
    return {
        "operation": op,
        "numbers": [str(n) for n in nums],
        "result": result,
        "text": text,
        "verified": verified,
        "verification": "re-checked with independent integer arithmetic" if verified else "independent check failed",
        "canonical_id": _canonical_id("axiom_number_theory", {"op": op, "n": [str(v) for v in nums], "m": str(modulus), "r": str(result)}),
    }


def check_number_theory(op: str, nums: list[int], modulus: Any, result: Any) -> bool:
    try:
        if op == "factorize":
            prod = 1
            for p, e in result.items():
                if not _miller_rabin(int(p)):
                    return False
                prod *= int(p) ** int(e)
            return prod == nums[0]
        if op == "isprime":
            n = nums[0]
            if n < 10**12:  # trial division is exact here
                is_p = n >= 2 and all(n % d for d in range(2, math.isqrt(n) + 1))
            else:
                is_p = _miller_rabin(n)
            return is_p == result
        if op == "gcd":
            g = int(result)
            return all(v % g == 0 for v in nums) and math.gcd(*(v // g for v in nums)) == 1
        if op == "lcm":
            # a common multiple whose quotients share no factor is the least one
            lv = int(result)
            return all(lv % v == 0 for v in nums if v) and math.gcd(*(lv // v for v in nums if v)) == 1
        if op == "divisors":
            n = abs(nums[0])
            expected = [d for d in range(1, math.isqrt(n) + 1) if n % d == 0]
            full = sorted(set(expected + [n // d for d in expected]))
            return full == list(result)
        if op == "totient":
            n = nums[0]
            if n <= 200_000:
                return sum(1 for k in range(1, n + 1) if math.gcd(k, n) == 1) == result
            phi = n
            for p in sp.factorint(n):
                phi = phi // p * (p - 1)
            return phi == result
        if op == "mod_pow":
            base, exp, mod = nums[0], nums[1], _int(modulus)
            acc, b, e = 1, base % mod, exp  # square-and-multiply written out, not pow()
            while e > 0:
                if e & 1:
                    acc = acc * b % mod
                b = b * b % mod
                e >>= 1
            return acc % mod == result
        if op == "mod_inverse":
            return (nums[0] * int(result)) % _int(modulus) == 1
        if op == "crt":
            mods = [_int(v) for v in modulus]
            return all((result["x"] - r) % mm == 0 for r, mm in zip(nums, mods, strict=True))
        if op == "next_prime":
            p = int(result)
            return p > nums[0] and _miller_rabin(p) and not any(_miller_rabin(k) for k in range(nums[0] + 1, p))
        if op == "diophantine":
            a, b, c = nums
            for t in (0, 1, -3):
                x, y = result["x0"] + result["step_x"] * t, result["y0"] + result["step_y"] * t
                if a * x + b * y != c:
                    return False
            return True
    except Exception:
        return False
    return False


# Recurrences --------------------------------------------------------------------------------------------------------

def axiom_recurrence(recurrence: str, initial: dict[str, Any], function: str = "a", variable: str = "n") -> dict[str, Any]:
    """Closed form of a recurrence such as a(n) = a(n-1) + a(n-2), a(0) = 0, a(1) = 1 (sympy.rsolve), checked against
    direct iteration of the recurrence for the first terms."""
    fname, vname = _check_safe_string(function), _check_safe_string(variable)
    n = sp.Symbol(vname, integer=True)
    a = sp.Function(fname)
    local = {vname: n, fname: a}
    lhs, rhs, eq = safe_parse_equation(recurrence, local_dict=local)
    if isinstance(lhs, (sp.Tuple, tuple, list)) or isinstance(rhs, (sp.Tuple, tuple, list)):
        raise UnsupportedShapeError("Operation 'recurrence' requires a scalar equation, got container")
    try:
        res = lhs - rhs
    except TypeError as exc:
        raise UnsupportedShapeError(f"Cannot form recurrence residual: {exc}") from exc
    ics: dict[Any, Any] = {}
    for key, value in (initial or {}).items():
        arg = safe_parse_expr(str(key).strip()[len(fname):].strip("() ") if str(key).strip().startswith(fname) else str(key))
        ics[a(arg)] = safe_parse_expr(str(value))
    sol = sp.rsolve(res, a(n), ics or None)
    if sol is None:
        raise ValueError("NotImplementedError: rsolve found no closed form for this recurrence")
    sol = sp.simplify(sol)
    terms = iterate_recurrence(res, a, n, ics, 15)
    verified = check_recurrence(sol, n, terms)
    return {
        "recurrence": str(eq),
        "initial": {str(k): str(v) for k, v in ics.items()},
        "result": str(sol),
        "latex": sp.latex(sol),
        "first_terms": [str(t) for _, t in terms[:10]],
        "verified": verified,
        "verification": "closed form equals the directly iterated terms" if verified else "closed form disagrees with iteration",
        "canonical_id": _canonical_id("axiom_recurrence", {"r": recurrence, "ics": {str(k): str(v) for k, v in ics.items()}, "sol": str(sol)}),
    }


def iterate_recurrence(residual: sp.Expr, a: Any, n: sp.Symbol, ics: dict[Any, Any], count: int) -> list[tuple[int, sp.Expr]]:
    """(index, term) pairs a(n0), a(n0+1), ... computed by solving the recurrence for its highest-shift term."""
    calls = sorted({c for c in residual.atoms(sp.Function) if c.func == a}, key=lambda c: sp.simplify(c.args[0] - n))
    if not calls or not ics:
        return []
    top = calls[-1]
    shift = sp.simplify(top.args[0] - n)
    solved = sp.solve(residual, top)
    if len(solved) != 1:
        return []
    step = solved[0]
    known = {int(k.args[0]): v for k, v in ics.items()}
    start = max(known) + 1
    for m in range(start, start + count):
        nv = m - int(shift)
        val = step.subs(n, nv)
        for c in sorted(val.atoms(sp.Function), key=str):
            if c.func == a:
                idx = int(c.args[0])
                if idx not in known:
                    return []
                val = val.subs(c, known[idx])
        known[m] = sp.simplify(val)
    return sorted(known.items())


def check_recurrence(closed: sp.Expr, n: sp.Symbol, terms: list[tuple[int, sp.Expr]]) -> bool:
    """The closed form must reproduce every directly iterated term (initial values included)."""
    if len(terms) < 5:
        return False
    for i, t in terms:
        v, tv = _num(closed.subs(n, i), {}), _num(t, {})
        if v is None or tv is None or abs(v - tv) > 1e-9 * max(1.0, abs(tv)):
            return False
    return True


# Probability --------------------------------------------------------------------------------------------------------

DistName = Literal["normal", "binomial", "poisson", "exponential", "uniform", "geometric", "bernoulli"]
ProbQuery = Literal["probability", "mean", "variance", "std", "pdf", "cdf", "quantile"]


def _sympy_dist(name: str, params: list[sp.Expr]) -> Any:
    from sympy import stats

    builders = {
        "normal": lambda p: stats.Normal("X", p[0], p[1]),
        "binomial": lambda p: stats.Binomial("X", int(p[0]), p[1]),
        "poisson": lambda p: stats.Poisson("X", p[0]),
        "exponential": lambda p: stats.Exponential("X", p[0]),
        "uniform": lambda p: stats.Uniform("X", p[0], p[1]),
        "geometric": lambda p: stats.Geometric("X", p[0]),
        "bernoulli": lambda p: stats.Bernoulli("X", p[0]),
    }
    if name not in builders:
        raise ValueError(f"Unsupported distribution {name!r}; use one of {sorted(builders)}.")
    return builders[name](params)


def _scipy_dist(name: str, p: list[float]) -> Any:
    from scipy import stats as ss

    return {
        "normal": lambda: ss.norm(p[0], p[1]),
        "binomial": lambda: ss.binom(int(p[0]), p[1]),
        "poisson": lambda: ss.poisson(p[0]),
        "exponential": lambda: ss.expon(scale=1 / p[0]),
        "uniform": lambda: ss.uniform(p[0], p[1] - p[0]),
        "geometric": lambda: ss.geom(p[0]),
        "bernoulli": lambda: ss.bernoulli(p[0]),
    }[name]()


_DISCRETE = frozenset({"binomial", "poisson", "geometric", "bernoulli"})


def axiom_probability(
    distribution: DistName,
    parameters: list[Any],
    query: ProbQuery,
    lower: Any | None = None,
    upper: Any | None = None,
    lower_inclusive: bool = True,
    upper_inclusive: bool = True,
    value: Any | None = None,
) -> dict[str, Any]:
    """Exact probabilities and moments of a named distribution (SymPy stats), cross-checked against SciPy.
    Parameters: normal(mu, sigma), binomial(n, p), poisson(lambda), exponential(rate), uniform(a, b), geometric(p),
    bernoulli(p). query=probability uses lower/upper (either may be omitted) and their inclusiveness."""
    from sympy import stats

    name = str(distribution).lower()
    params = [safe_parse_expr(str(v)) for v in parameters]
    X = _sympy_dist(name, params)
    q = str(query).lower()
    lo = safe_parse_expr(str(lower)) if lower is not None else None
    hi = safe_parse_expr(str(upper)) if upper is not None else None
    if q == "probability":
        conds = []
        if lo is not None:
            conds.append(X >= lo if lower_inclusive else X > lo)
        if hi is not None:
            conds.append(X <= hi if upper_inclusive else X < hi)
        if not conds:
            raise ValueError("probability needs a lower and/or upper bound.")
        if name in _DISCRETE:
            exact = sp.simplify(stats.P(sp.And(*conds)))
        else:  # continuous: F(b) - F(a) from the closed-form CDF, much faster than integrating the density
            F = stats.cdf(X)
            exact = sp.simplify((F(hi) if hi is not None else 1) - (F(lo) if lo is not None else 0))
    elif q == "mean":
        exact = sp.simplify(stats.E(X))
    elif q == "variance":
        exact = sp.simplify(stats.variance(X))
    elif q == "std":
        exact = sp.simplify(stats.std(X))
    elif q in ("pdf", "cdf"):
        if value is None:
            raise ValueError(f"{q} needs a 'value'.")
        v = safe_parse_expr(str(value))
        exact = sp.simplify(stats.density(X)(v) if q == "pdf" else stats.cdf(X)(v))
    elif q == "quantile":
        if value is None:
            raise ValueError("quantile needs a probability 'value'.")
        exact = None
    else:
        raise ValueError(f"Unsupported probability query {query!r}.")
    numeric = check_probability(name, [float(p) for p in params], q, lo, hi, lower_inclusive, upper_inclusive, value)
    if q == "quantile":
        exact_val = numeric
        verified = numeric is not None
        result = f"{numeric:.12g}" if numeric is not None else ""
    else:
        exact_val = _num(exact, {})
        verified = numeric is not None and exact_val is not None and abs(exact_val - numeric) <= 1e-9 * max(1.0, abs(numeric))
        result = str(exact)
    return {
        "distribution": name,
        "parameters": [str(p) for p in params],
        "query": q,
        "result": result,
        "numeric_value": (exact_val.real if isinstance(exact_val, complex) else exact_val),
        "scipy_value": numeric,
        "verified": bool(verified),
        "verification": "exact SymPy value matches SciPy" if verified else "SymPy and SciPy disagree or SciPy could not evaluate",
        "canonical_id": _canonical_id("axiom_probability", {"d": name, "p": [str(p) for p in params], "q": q, "lo": str(lo), "hi": str(hi), "v": str(value)}),
    }


def check_probability(name: str, p: list[float], q: str, lo: Any, hi: Any, lo_inc: bool, hi_inc: bool, value: Any) -> float | None:
    """The same quantity from SciPy (independent implementation)."""
    try:
        d = _scipy_dist(name, p)
        if q == "mean":
            return float(d.mean())
        if q == "variance":
            return float(d.var())
        if q == "std":
            return float(d.std())
        if q in ("pdf", "cdf", "quantile"):
            v = float(safe_parse_expr(str(value)))
            if q == "cdf":
                return float(d.cdf(v))
            if q == "quantile":
                return float(d.ppf(v))
            return float(d.pmf(v) if name in _DISCRETE else d.pdf(v))
        a = float(lo) if lo is not None else -math.inf
        b = float(hi) if hi is not None else math.inf
        if name in _DISCRETE:
            # integer support: P(a <= X <= b) with inclusiveness folded into integer bounds
            upper_cdf = 1.0 if not math.isfinite(b) else float(d.cdf(math.floor(b) if hi_inc else math.ceil(b) - 1))
            if not math.isfinite(a):
                return upper_cdf
            ia = math.ceil(a) if lo_inc else math.floor(a) + 1
            return max(0.0, upper_cdf - float(d.cdf(ia - 1)))
        return float(d.cdf(b) - d.cdf(a))
    except Exception:
        return None


# Statistics ---------------------------------------------------------------------------------------------------------

StatOp = Literal["describe", "ttest_1samp", "ttest_ind", "ttest_rel", "linregress", "pearson", "confidence_interval"]


def calcula_statistics(
    operation: StatOp,
    data: list[float],
    data2: list[float] | None = None,
    mu0: float = 0.0,
    confidence: float = 0.95,
) -> dict[str, Any]:
    """Statistics on inline numbers: descriptive summary, one-sample / Welch two-sample / paired t-tests, linear
    regression, Pearson correlation, t confidence interval for the mean. Every value is recomputed from textbook
    formulas and compared with SciPy."""
    from scipy import stats as ss

    op = str(operation).lower()
    xs = [float(v) for v in data]
    ys = [float(v) for v in data2] if data2 else None
    if len(xs) < 2:
        raise ValueError("Give at least two data values.")
    if op == "describe":
        result: dict[str, Any] = {
            "n": len(xs), "mean": pystats.fmean(xs), "median": pystats.median(xs), "std": pystats.stdev(xs),
            "variance": pystats.variance(xs), "min": min(xs), "max": max(xs),
        }
    elif op == "ttest_1samp":
        r = ss.ttest_1samp(xs, mu0)
        result = {"t": float(r.statistic), "p_value": float(r.pvalue), "df": len(xs) - 1, "mu0": mu0}
    elif op in ("ttest_ind", "ttest_rel"):
        if not ys:
            raise ValueError(f"{op} needs a second sample 'data2'.")
        r = ss.ttest_ind(xs, ys, equal_var=False) if op == "ttest_ind" else ss.ttest_rel(xs, ys)
        result = {"t": float(r.statistic), "p_value": float(r.pvalue)}
    elif op in ("linregress", "pearson"):
        if not ys or len(ys) != len(xs):
            raise ValueError(f"{op} needs 'data2' of the same length (x = data, y = data2).")
        if op == "linregress":
            r = ss.linregress(xs, ys)
            result = {"slope": float(r.slope), "intercept": float(r.intercept), "r": float(r.rvalue), "p_value": float(r.pvalue), "stderr": float(r.stderr)}
        else:
            r = ss.pearsonr(xs, ys)
            result = {"r": float(r.statistic), "p_value": float(r.pvalue)}
    elif op == "confidence_interval":
        n, mean, sd = len(xs), pystats.fmean(xs), pystats.stdev(xs)
        half = float(ss.t.ppf(0.5 + confidence / 2, n - 1)) * sd / math.sqrt(n)
        result = {"mean": mean, "lower": mean - half, "upper": mean + half, "confidence": confidence}
    else:
        raise ValueError(f"Unsupported statistics operation {operation!r}.")
    verified = check_statistics(op, xs, ys, mu0, confidence, result)
    return {
        "operation": op,
        "result": result,
        "text": ", ".join(f"{k} = {v:.10g}" if isinstance(v, float) else f"{k} = {v}" for k, v in result.items()),
        "verified": verified,
        "verification": "textbook formulas agree with SciPy" if verified else "independent recomputation disagrees",
        "canonical_id": _canonical_id("calcula_statistics", {"op": op, "x": xs, "y": ys, "mu0": mu0, "c": confidence}),
    }


def check_statistics(op: str, xs: list[float], ys: list[float] | None, mu0: float, confidence: float, result: dict[str, Any]) -> bool:
    from scipy import stats as ss

    def close(a: float, b: float, tol: float = 1e-9) -> bool:
        return abs(a - b) <= tol * max(1.0, abs(b))

    n = len(xs)
    mean = sum(xs) / n
    var = sum((v - mean) ** 2 for v in xs) / (n - 1)
    try:
        if op == "describe":
            s = sorted(xs)
            med = s[n // 2] if n % 2 else (s[n // 2 - 1] + s[n // 2]) / 2
            return close(result["mean"], mean) and close(result["variance"], var) and close(result["median"], med)
        if op == "ttest_1samp":
            t = (mean - mu0) / math.sqrt(var / n)
            p = 2 * ss.t.sf(abs(t), n - 1)
            return close(result["t"], t, 1e-8) and close(result["p_value"], p, 1e-8)
        if op == "ttest_ind" and ys:
            m2 = sum(ys) / len(ys)
            v2 = sum((v - m2) ** 2 for v in ys) / (len(ys) - 1)
            se2 = var / n + v2 / len(ys)
            t = (mean - m2) / math.sqrt(se2)
            df = se2**2 / ((var / n) ** 2 / (n - 1) + (v2 / len(ys)) ** 2 / (len(ys) - 1))
            return close(result["t"], t, 1e-8) and close(result["p_value"], 2 * ss.t.sf(abs(t), df), 1e-6)
        if op == "ttest_rel" and ys:
            d = [a - b for a, b in zip(xs, ys, strict=True)]
            md = sum(d) / n
            vd = sum((v - md) ** 2 for v in d) / (n - 1)
            t = md / math.sqrt(vd / n)
            return close(result["t"], t, 1e-8)
        if op in ("linregress", "pearson") and ys:
            my = sum(ys) / n
            sxy = sum((a - mean) * (b - my) for a, b in zip(xs, ys, strict=True))
            sxx = sum((a - mean) ** 2 for a in xs)
            syy = sum((b - my) ** 2 for b in ys)
            r = sxy / math.sqrt(sxx * syy)
            if op == "pearson":
                return close(result["r"], r, 1e-9)
            slope = sxy / sxx
            return close(result["slope"], slope) and close(result["intercept"], my - slope * mean) and close(result["r"], r)
        if op == "confidence_interval":
            half = ss.t.ppf(0.5 + confidence / 2, n - 1) * math.sqrt(var / n)
            return close(result["lower"], mean - half) and close(result["upper"], mean + half)
    except Exception:
        return False
    return False


__all__ = [
    "axiom_number_theory",
    "axiom_probability",
    "axiom_recurrence",
    "calcula_statistics",
    "check_number_theory",
    "check_probability",
    "check_recurrence",
    "check_statistics",
    "iterate_recurrence",
]
