"""Certified critical points: every zero of the gradient of f in a box, with a proof that none was missed.

A multistart root finder finds critical points but cannot show it found all of them. This uses interval arithmetic
(mpmath.iv, outward-rounded) on the analytic gradient and Hessian:

1. Branch and bound: a box where some component of the gradient's interval enclosure excludes 0 holds no critical
   point and is discarded.
2. Krawczyk test (Krawczyk 1969; Moore, Kearfott & Cloud, "Introduction to Interval Analysis", 2009, ch. 8):
   K(X) = m - Y g(m) + (I - Y H(X))(X - m), with Y the inverse of the Hessian at the box midpoint. K(X) inside the
   interior of X proves X holds exactly one critical point; K(X) disjoint from X proves it holds none.
3. Otherwise the box is bisected along its widest side, down to a minimum width; a box still undecided there is
   reported, and the search is then not complete.

When every box is discarded or proved, the list is complete: a proof, not a search. Each certified point is refined
by Newton's method, valued, and classified by its Hessian (minimum, maximum, saddle, or degenerate).
"""

from __future__ import annotations

import re
import time
from typing import Any

import sympy as sp

MAX_BOXES = 60_000
MIN_WIDTH = 1e-9
INFLATE_BELOW = 1e-2  # boxes narrower than this that stay undecided are retried epsilon-inflated
SPLIT = 0.4987  # bisection point (fraction of the width), off-centre on purpose
TIME_LIMIT_S = 8.0

_FUNCS = ("sin", "cos", "tan", "exp", "log", "sqrt", "sinh", "cosh", "tanh", "atan")


def _interval_fn(expr: sp.Expr, variables: tuple[sp.Symbol, ...]) -> Any:
    """f as a function of mpmath intervals (None when it uses a function interval arithmetic does not cover here)."""
    from mpmath import iv

    allowed = {getattr(sp, n) for n in _FUNCS}
    for node in sp.preorder_traversal(expr):
        if isinstance(node, sp.Function) and node.func not in allowed:
            return None
    namespace = {n: getattr(iv, n) for n in _FUNCS if hasattr(iv, n)}
    namespace.update({"mpf": iv.mpf, "pi": iv.pi, "E": iv.e})
    return sp.lambdify(variables, expr, modules=[namespace, "mpmath"])


def _contains_zero(value: Any) -> bool:
    return value.a <= 0 <= value.b


def _midpoint(box: list[Any]) -> list[float]:
    return [float(b.mid) for b in box]


def _width(box: list[Any]) -> float:
    return max(float(b.delta) for b in box)


def _krawczyk(box: list[Any], g_iv: list[Any], h_iv: list[list[Any]], h_num: Any, n: int) -> str | None:
    """"unique" (exactly one zero of the gradient in the box), "none" (no zero), or None (undecided)."""
    import numpy as np
    from mpmath import iv

    try:
        m = _midpoint(box)
        y = np.linalg.inv(np.array(h_num(*m), dtype=float))
        # g at the midpoint, enclosed by interval arithmetic (a float value would make the test unrigorous)
        gm = [g(*[iv.mpf(v) for v in m]) for g in g_iv]
        hx = [[h(*box) for h in row] for row in h_iv]
        k = []
        for i in range(n):
            term = iv.mpf(m[i]) - sum(iv.mpf(y[i][j]) * gm[j] for j in range(n))
            for j in range(n):
                ij = (1 if i == j else 0) - sum(iv.mpf(y[i][q]) * hx[q][j] for q in range(n))
                term += ij * (box[j] - iv.mpf(m[j]))
            k.append(term)
    except (np.linalg.LinAlgError, ZeroDivisionError, ValueError, TypeError):
        return None  # a singular midpoint Hessian: undecided, bisect
    if all(k[i].a > box[i].a and k[i].b < box[i].b for i in range(n)):
        return "unique"
    if any(k[i].b < box[i].a or k[i].a > box[i].b for i in range(n)):
        return "none"
    return None


def certify_critical_points(expr: sp.Expr, variables: tuple[sp.Symbol, ...], bounds: list[tuple[float, float]]
                            ) -> dict[str, Any]:
    """Every critical point of `expr` in the box `bounds` (one (lo, hi) per variable), certified by interval
    arithmetic. status: complete | incomplete (undecided boxes remain) | unsupported (the function cannot be enclosed)."""
    import numpy as np
    from mpmath import iv

    n = len(variables)
    grad = [sp.diff(expr, v) for v in variables]
    hess = [[sp.diff(g, v) for v in variables] for g in grad]
    g_iv = [_interval_fn(g, variables) for g in grad]
    h_iv = [[_interval_fn(h, variables) for h in row] for row in hess]
    if any(f is None for f in g_iv) or any(f is None for row in h_iv for f in row):
        return {"status": "unsupported", "points": [], "reason": "the function uses an operation interval arithmetic "
                "does not enclose here"}
    g_num = sp.lambdify(variables, grad, "numpy")
    h_num = sp.lambdify(variables, hess, "numpy")
    f_num = sp.lambdify(variables, expr, "numpy")

    stack = [[iv.mpf([lo, hi]) for lo, hi in bounds]]
    certified: list[list[Any]] = []
    undecided: list[list[Any]] = []
    examined, started = 0, time.perf_counter()
    while stack:
        if examined >= MAX_BOXES or time.perf_counter() - started > TIME_LIMIT_S:
            undecided.extend(stack)
            break
        box = stack.pop()
        examined += 1
        try:
            if not all(_contains_zero(g(*box)) for g in g_iv):
                continue  # the gradient cannot vanish here
        except (ZeroDivisionError, ValueError, TypeError):
            pass
        verdict = _krawczyk(box, g_iv, h_iv, h_num, n)
        if verdict == "unique":
            certified.append(box)  # exactly one critical point in this box
            continue
        if verdict == "none":
            continue  # no critical point in this box
        if _width(box) < INFLATE_BELOW:
            # A critical point on (or next to) the box's edge never lies strictly inside any box of the subdivision,
            # so the test above cannot succeed. Epsilon-inflation: a slightly larger box around this one that provably
            # holds exactly one critical point accounts for every critical point of this box.
            grown = [iv.mpf([b.a - 0.5 * b.delta - 1e-12, b.b + 0.5 * b.delta + 1e-12]) for b in box]
            if _krawczyk(grown, g_iv, h_iv, h_num, n) == "unique":
                certified.append(grown)
                continue
        if _width(box) < MIN_WIDTH:
            undecided.append(box)
            continue
        widest = max(range(n), key=lambda i: float(box[i].delta))
        # Split a little off-centre: exact points such as x = 1 then rarely fall on a box edge.
        cut = box[widest].a + SPLIT * box[widest].delta
        for half in (iv.mpf([box[widest].a, cut]), iv.mpf([cut, box[widest].b])):
            stack.append([half if i == widest else box[i] for i in range(n)])

    points = []
    for box in certified:
        p = np.array(_midpoint(box))
        for _ in range(50):  # Newton refinement inside the certified box
            step = np.linalg.solve(np.array(h_num(*p), dtype=float), np.array(g_num(*p), dtype=float))
            p = p - step
            if np.max(np.abs(step)) < 1e-15:
                break
        # An inflated box can reach past the domain (its one critical point is then outside: the domain has none
        # there) and neighbouring boxes can certify the same point: keep each point inside the domain once.
        if any(not (lo - 1e-12 <= v <= hi + 1e-12) for v, (lo, hi) in zip(p, bounds, strict=False)):
            continue
        if any(np.max(np.abs(p - np.array(q["point"]))) < 1e-8 for q in points):
            continue
        h = np.array(h_num(*p), dtype=float)
        eig = np.linalg.eigvalsh((h + h.T) / 2)
        kind = ("local minimum" if np.all(eig > 0) else "local maximum" if np.all(eig < 0)
                else "saddle point" if np.any(eig > 0) and np.any(eig < 0) else "degenerate (second-derivative test inconclusive)")
        points.append({
            "point": [round(float(v), 10) for v in p],
            "enclosure": [[float(b.a), float(b.b)] for b in box],
            "value": float(f_num(*p)),
            "hessian": [[round(float(v), 10) for v in row] for row in h],
            "hessian_det": float(np.linalg.det(h)),
            "classification": kind,
        })
    points.sort(key=lambda d: d["point"])
    return {
        "status": "complete" if not undecided else "incomplete",
        "points": points,
        "undecided_boxes": [[[float(b.a), float(b.b)] for b in box] for box in undecided[:10]],
        "undecided_count": len(undecided),
        "boxes_examined": examined,
        "domain": [list(b) for b in bounds],
        "variables": [str(v) for v in variables],
        "method": "interval branch-and-bound on the analytic gradient with the Krawczyk uniqueness test (mpmath.iv)",
    }


# --- end of the certification engine ---

# The line above ends the part certificate_script copies (split in two here, so this line does not match).
_SPLIT_MARK = "# --- end of the " + "certification engine ---"


def certificate_script(function: str, variables: list[str], bounds: list[list[float]]) -> str:
    """A standalone Python file that re-runs the certification for this function and domain: the engine above, copied
    verbatim, plus the problem. Anyone can check the result without Tribos (needs sympy, mpmath and numpy)."""
    from pathlib import Path

    source = Path(__file__).read_text(encoding="utf-8")
    engine = source.split(_SPLIT_MARK, 1)[0].rstrip()
    names = ", ".join(variables)
    return (
        f"{engine}\n\n\n"
        "if __name__ == '__main__':\n"
        "    import json\n\n"
        f"    {names} = sp.symbols({' '.join(variables)!r})\n"
        f"    f = sp.sympify({function!r}, locals={{{', '.join(f'{v!r}: {v}' for v in variables)}}})\n"
        f"    result = certify_critical_points(f, ({names},), {[tuple(b) for b in bounds]!r})\n"
        "    print('f =', f)\n"
        "    print('status:', result['status'], '| boxes examined:', result['boxes_examined'],\n"
        "          '| undecided regions:', result['undecided_count'])\n"
        "    for p in result['points']:\n"
        "        print('critical point', p['point'], 'f =', p['value'], '-', p['classification'])\n"
        "    if not result['points']:\n"
        "        print('no critical points in the domain')\n"
        "    print(json.dumps({k: result[k] for k in ('status', 'points', 'domain', 'method')}, indent=2))\n"
    )


def certificate_files(question: str, result: Any) -> list[tuple[str, str, bytes]]:
    """[(kind, filename, bytes)]: the re-runnable certification script and its result as JSON."""
    import json

    if not isinstance(result, dict) or result.get("status") not in ("complete", "incomplete") or not result.get("function"):
        return []
    from ..files import _slug

    base = _slug((question or "critical points").split("\n", 1)[0])
    script = certificate_script(result["function"], result["variables"], result["domain"])
    record = {k: result.get(k) for k in ("function", "variables", "domain", "status", "points", "undecided_count",
                                          "boxes_examined", "method")}
    return [("py", f"{base}_critical_points_proof.py", script.encode("utf-8")),
            ("json", f"{base}_critical_points.json", json.dumps(record, indent=2).encode("utf-8"))]


# "f(x,y) = <expr>" up to the end of the display block, the line, or "over/on the domain".
_FUNCTION_RE = re.compile(
    r"\b([a-zA-Z])\s*\(\s*([a-z])\s*,\s*([a-z])\s*\)\s*=\s*(.+?)(?=\\\]|\$\$|\n\s*\n|\bover\b|\bon\b|\bfor\b|$)",
    re.S,
)
_REL = r"(?:\\leq?|\\le|<=|≤|<)"
_NUMBER = r"(-?\s*\d+(?:\.\d+)?(?:\s*\\?pi)?)"


def _number(text: str) -> float:
    t = text.replace(" ", "").replace("\\pi", "pi")
    return float(sp.sympify(t.replace("pi", "*pi") if re.match(r"-?\d", t) and "pi" in t else t))


def extract_problem(question: str) -> tuple[sp.Expr, tuple[sp.Symbol, sp.Symbol], list[tuple[float, float]]] | None:
    """(f, (x, y), [(x_lo, x_hi), (y_lo, y_hi)]) from a question that defines f(x,y) and bounds both variables."""
    from ..verify.latex_math import parse_latex

    m = _FUNCTION_RE.search(question or "")
    if not m:
        return None
    xs, ys = m.group(2), m.group(3)
    body = m.group(4).strip().rstrip(".,;").replace("\n", " ")
    try:
        expr = parse_latex(body)
    except Exception:  # noqa: BLE001 - an expression the parser cannot read is not certified
        return None
    x, y = sp.Symbol(xs), sp.Symbol(ys)
    expr = expr.subs({s: (x if s.name == xs else y) for s in expr.free_symbols if s.name in (xs, ys)})
    if not expr.free_symbols <= {x, y}:
        return None
    bounds = []
    for var in (xs, ys):
        b = re.search(rf"{_NUMBER}\s*{_REL}\s*{var}\s*{_REL}\s*{_NUMBER}", question)
        if not b:
            return None
        try:
            lo, hi = _number(b.group(1)), _number(b.group(2))
        except (sp.SympifyError, TypeError, ValueError):
            return None
        if not lo < hi:
            return None
        bounds.append((lo, hi))
    return expr, (x, y), bounds


__all__ = ["certify_critical_points", "extract_problem"]
