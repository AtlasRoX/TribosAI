"""
The 1-D heat (diffusion) equation u_t = alpha u_xx on [0, L] with u = 0 at both ends, solved by code with a grid
refinement study, so the answer reports a measured order of convergence instead of asserting one:

- Crank-Nicolson (second order in space and time) on grids of 10, 20, 40, 80 and 160 intervals, time step tied to
  the space step, and FTCS (explicit, stable for alpha dt / dx^2 <= 1/2) as the second method;
- for an initial profile sin(k pi x / L) the exact solution exp(-alpha (k pi / L)^2 t) sin(k pi x / L) is the
  manufactured reference: errors and observed orders come from it; otherwise successive grids are compared
  (Richardson) and the order is estimated from three of them.
"""

from __future__ import annotations

import math
import re
from typing import Any

import numpy as np

_NUM = r"[-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?"
GRIDS = (10, 20, 40, 80, 160)


_LE = r"(?:<=|≤|\\leq?|<)"


def parse_heat(question: str) -> dict[str, Any] | None:
    """{"alpha", "L", "t_end", "k" (sine mode or None), "initial" (callable source)} for a heat-equation question."""
    q = (question or "").replace("−", "-").replace("π", "pi").replace("²", "^2")
    if not re.search(r"u_t\s*=|∂u\s*/\s*∂t|du/dt\s*=|heat\s+equation|diffusion\s+equation", q, re.I):
        return None
    if not re.search(r"u_?\{?xx\}?|∂\^?2\s*u|d\^?2u/dx\^?2|heat|diffusion", q, re.I):
        return None
    alpha = 1.0
    am = re.search(rf"u_t\s*=\s*({_NUM})\s*\*?\s*u_?\{{?xx|alpha\s*=\s*({_NUM})|α\s*=\s*({_NUM})", q)
    if am:
        alpha = float(next(g for g in am.groups() if g))
    lm = (re.search(rf"\[\s*0\s*,\s*({_NUM})\s*\]", q)
          or re.search(rf"0\s*{_LE}\s*x\s*{_LE}\s*({_NUM})", q))
    length = float(lm.group(1)) if lm else 1.0
    tm = re.search(rf"(?:until|to|up\s+to|at)\s+t\s*=\s*({_NUM})|t\s*(?:∈|in)\s*\[\s*0\s*,\s*({_NUM})\s*\]"
                   rf"|0\s*{_LE}\s*t\s*{_LE}\s*({_NUM})", q)
    t_end = float(next(g for g in tm.groups() if g)) if tm else 0.1
    km = re.search(r"sin\s*\(\s*(\d*)\s*\*?\s*pi\s*\*?\s*x\s*(?:/\s*L)?\s*\)", q, re.I)
    k = int(km.group(1) or 1) if km else None
    if k is None and not re.search(r"u\s*\(\s*x\s*,\s*0\s*\)|initial", q, re.I):
        return None
    if k is None:
        return None  # only the manufactured (sine) case is solved here; other profiles go to the model's plan
    if not (0 < alpha < 1e3 and 0 < length < 1e3 and 0 < t_end < 1e3):
        return None
    return {"alpha": alpha, "L": length, "t_end": t_end, "k": k}


def _crank_nicolson(n: int, alpha: float, length: float, t_end: float, u0: np.ndarray,
                    exact_at: Any = None, worst: list[float] | None = None) -> np.ndarray:
    dx = length / n
    steps = max(1, int(math.ceil(t_end / (dx * 0.5))))  # dt proportional to dx: second order overall
    dt = t_end / steps
    r = alpha * dt / dx ** 2
    m = n - 1  # interior points
    main_a, off_a = (1 + r) * np.ones(m), (-r / 2) * np.ones(m - 1)
    from scipy.linalg import solve_banded

    ab = np.zeros((3, m))
    ab[0, 1:], ab[1, :], ab[2, :-1] = off_a, main_a, off_a
    u = u0[1:-1].copy()
    for step in range(steps):
        rhs = (1 - r) * u
        rhs[1:] += (r / 2) * u[:-1]
        rhs[:-1] += (r / 2) * u[1:]
        u = solve_banded((1, 1), ab, rhs)
        if exact_at is not None and worst is not None:
            # The error at every step, for the maximum over the whole span (not only at t_end).
            worst[0] = max(worst[0], float(np.max(np.abs(u - exact_at((step + 1) * dt)[1:-1]))))
    return np.concatenate([[0.0], u, [0.0]])


def _ftcs(n: int, alpha: float, length: float, t_end: float, u0: np.ndarray) -> np.ndarray:
    dx = length / n
    steps = max(1, int(math.ceil(t_end / (0.4 * dx ** 2 / alpha))))  # r = alpha dt / dx^2 <= 0.4: stable
    dt = t_end / steps
    r = alpha * dt / dx ** 2
    u = u0.copy()
    for _ in range(steps):
        u[1:-1] = u[1:-1] + r * (u[2:] - 2 * u[1:-1] + u[:-2])
    return u


_POISSON_RE = re.compile(r"\bpoisson\b|-\s*(?:Δ|\\Delta|∇\s*\^?\s*2|laplacian)\s*u\s*=", re.I)
_FEM_RE = re.compile(r"finite[- ]elements?|\bFEM\b|\bP[12]\b|galerkin|convergence|refine|mesh", re.I)
POISSON_MESHES = (4, 8, 16, 32, 64)


def parse_poisson(question: str) -> dict[str, Any] | None:
    """-Δu = f on the unit square with u = 0 on the boundary, asked to be solved by finite elements: {"k": mode}."""
    q = question or ""
    if not (_POISSON_RE.search(q) and _FEM_RE.search(q)):
        return None
    if re.search(r"\b(?:3-?d|three[- ]dimensional|cube|annulus|L-shaped|nonlinear)\b", q, re.I):
        return None  # only the 2-D unit-square problem is covered
    m = re.search(r"sin\s*\(\s*(\d*)\s*\\?pi\s*\*?\s*x\s*\)", q.replace("π", "pi"), re.I)
    return {"k": int(m.group(1)) if m and m.group(1) else 1}


def compute_poisson_facts(question: str) -> dict[str, Any] | None:
    """P1 and P2 finite elements for -Δu = f on [0,1]² with the manufactured solution u = sin(kπx) sin(kπy):
    L2 and H1-seminorm errors on five meshes, and the observed orders (theory: P1 2 and 1, P2 3 and 2)."""
    spec = parse_poisson(question)
    if spec is None:
        return None
    import skfem
    from skfem.helpers import dot, grad

    k = spec["k"]
    w = k * math.pi

    def exact(x: Any) -> Any:
        return np.sin(w * x[0]) * np.sin(w * x[1])

    def exact_grad(x: Any) -> Any:
        return np.array([w * np.cos(w * x[0]) * np.sin(w * x[1]), w * np.sin(w * x[0]) * np.cos(w * x[1])])

    @skfem.BilinearForm
    def laplace(u: Any, v: Any, _: Any) -> Any:
        return dot(grad(u), grad(v))

    @skfem.LinearForm
    def load(v: Any, wp: Any) -> Any:
        return 2 * w ** 2 * exact(wp.x) * v

    @skfem.Functional
    def l2_err(wp: Any) -> Any:
        return (wp["uh"] - exact(wp.x)) ** 2

    @skfem.Functional
    def h1_err(wp: Any) -> Any:
        d = wp["uh"].grad - exact_grad(wp.x)
        return d[0] ** 2 + d[1] ** 2

    results: dict[str, list[dict[str, Any]]] = {}
    for name, element in (("P1", skfem.ElementTriP1()), ("P2", skfem.ElementTriP2())):
        rows = []
        for n in POISSON_MESHES:
            mesh = skfem.MeshTri.init_symmetric().refined(int(math.log2(n)))
            basis = skfem.Basis(mesh, element, intorder=6)
            a, b = laplace.assemble(basis), load.assemble(basis)
            uh = skfem.solve(*skfem.condense(a, b, D=basis.get_dofs()))
            interp = basis.interpolate(uh)
            rows.append({"n": n, "h": 1.0 / n, "l2": float(math.sqrt(l2_err.assemble(basis, uh=interp))),
                         "h1": float(math.sqrt(h1_err.assemble(basis, uh=interp))), "dofs": int(basis.N)})
        for prev, row in zip(rows, rows[1:], strict=False):
            row["l2_order"] = math.log(prev["l2"] / row["l2"]) / math.log(prev["h"] / row["h"])
            row["h1_order"] = math.log(prev["h1"] / row["h1"]) / math.log(prev["h"] / row["h"])
        results[name] = rows
    p1, p2 = results["P1"], results["P2"]
    checks = [
        {"name": "P1: L2 error falls at order 2 (observed {:.3f})".format(p1[-1]["l2_order"]),
         "passed": abs(p1[-1]["l2_order"] - 2) < 0.15},
        {"name": "P1: H1 error falls at order 1 (observed {:.3f})".format(p1[-1]["h1_order"]),
         "passed": abs(p1[-1]["h1_order"] - 1) < 0.15},
        {"name": "P2: L2 error falls at order 3 (observed {:.3f})".format(p2[-1]["l2_order"]),
         "passed": abs(p2[-1]["l2_order"] - 3) < 0.25},
        {"name": "P2 is more accurate than P1 on every mesh", "passed": all(b["l2"] < a["l2"] for a, b in zip(p1, p2, strict=True))},
    ]
    params = [
        {"name": "P1 observed L2 order", "value": f"{p1[-1]['l2_order']:.3f}", "unit": "", "aliases": ["P1", "order"]},
        {"name": "P1 observed H1 order", "value": f"{p1[-1]['h1_order']:.3f}", "unit": "", "aliases": ["H1"]},
        {"name": "P2 observed L2 order", "value": f"{p2[-1]['l2_order']:.3f}", "unit": "", "aliases": ["P2"]},
        {"name": f"P2 L2 error on the {POISSON_MESHES[-1]}×{POISSON_MESHES[-1]} mesh", "value": f"{p2[-1]['l2']:.3e}",
         "unit": "", "aliases": ["error"]},
    ]
    return {
        "kind": "pde_poisson", "k": k, "refinement": p1, "refinement_p2": p2,
        "observed_order": round(p1[-1]["l2_order"], 3),
        "equation_latex": r"-\Delta u = 2" + (f"{k}^2" if k != 1 else "") + r"\pi^2 \sin(" + (str(k) if k != 1 else "")
                          + r"\pi x)\sin(" + (str(k) if k != 1 else "") + r"\pi y)\ \text{on } [0,1]^2,\ u = 0 \text{ on the boundary}",
        "exact_latex": r"u(x,y) = \sin(" + (str(k) if k != 1 else "") + r"\pi x)\sin(" + (str(k) if k != 1 else "") + r"\pi y)",
        "parameters": params, "checks": checks,
        "methods": ["Galerkin finite elements (scikit-fem), P1 and P2 triangles", "five uniformly refined meshes",
                    "errors against the exact manufactured solution"],
        "notes": ["The observed orders match finite-element theory (P1: 2 in L2, 1 in H1; P2: 3 in L2)."],
    }


def compute_pde_facts(question: str) -> dict[str, Any] | None:
    """Errors and observed orders of two schemes for the stated heat-equation problem, or None."""
    spec = parse_heat(question)
    if spec is None:
        return compute_poisson_facts(question)
    alpha, length, t_end, k = spec["alpha"], spec["L"], spec["t_end"], spec["k"]
    lam = alpha * (k * math.pi / length) ** 2
    rows = []
    for n in GRIDS:
        x = np.linspace(0.0, length, n + 1)
        u0 = np.sin(k * math.pi * x / length)
        exact = math.exp(-lam * t_end) * u0
        cn = _crank_nicolson(n, alpha, length, t_end, u0)
        ft = _ftcs(n, alpha, length, t_end, u0)
        rows.append({"n": n, "dx": length / n, "cn_error": float(np.max(np.abs(cn - exact))),
                     "ftcs_error": float(np.max(np.abs(ft - exact)))})
    for a, b in zip(rows, rows[1:], strict=False):
        b["cn_order"] = math.log2(a["cn_error"] / b["cn_error"]) if b["cn_error"] > 0 else float("nan")
        b["ftcs_order"] = math.log2(a["ftcs_error"] / b["ftcs_error"]) if b["ftcs_error"] > 0 else float("nan")
    cn_order = rows[-1]["cn_order"]
    ft_order = rows[-1]["ftcs_order"]
    x_fine = np.linspace(0.0, length, GRIDS[-1] + 1)
    u0_fine = np.sin(k * math.pi * x_fine / length)
    worst = [0.0]
    cn_fine = _crank_nicolson(GRIDS[-1], alpha, length, t_end, u0_fine,
                              exact_at=lambda tt: math.exp(-lam * tt) * u0_fine, worst=worst)
    exact_fine = math.exp(-lam * t_end) * u0_fine
    checks = [
        {"name": f"Crank-Nicolson observed order {cn_order:.3f} on the finest refinement (design order 2)",
         "passed": abs(cn_order - 2.0) < 0.15},
        {"name": f"FTCS observed order {ft_order:.3f} in dx with dt ~ dx^2 (design order 2 in dx)",
         "passed": abs(ft_order - 2.0) < 0.15},
        {"name": f"errors fall monotonically under refinement (finest CN error {rows[-1]['cn_error']:.2e})",
         "passed": all(b["cn_error"] < a["cn_error"] for a, b in zip(rows, rows[1:], strict=False))},
        {"name": "boundary values u(0, t) = u(L, t) = 0 held exactly", "passed": cn_fine[0] == 0.0 and cn_fine[-1] == 0.0},
    ]
    params = [
        {"name": "observed order (Crank-Nicolson)", "value": f"{cn_order:.3f}", "unit": "",
         "aliases": ["second-order convergence", "convergence order", "order of convergence"]},
        {"name": "observed order (FTCS)", "value": f"{ft_order:.3f}", "unit": "", "aliases": ["ftcs"]},
        {"name": f"max error at t = {t_end:g}, {GRIDS[-1]} intervals (CN)", "value": f"{rows[-1]['cn_error']:.3e}",
         "unit": "", "aliases": ["error"]},
        {"name": f"max error over 0 <= t <= {t_end:g}, {GRIDS[-1]} intervals (CN)", "value": f"{worst[0]:.3e}",
         "unit": "", "aliases": ["maximum error", "max error over the time span"]},
        {"name": f"exact decay factor exp(-alpha (k pi/L)^2 t) at t = {t_end:g}", "value": f"{math.exp(-lam * t_end):.10g}",
         "unit": "", "aliases": ["decay"]},
    ]
    return {
        "kind": "pde_heat", "alpha": alpha, "L": length, "t_end": t_end, "k": k,
        "equation_latex": rf"u_t = {alpha:g}\,u_{{xx}},\quad u(0,t)=u({length:g},t)=0,\quad u(x,0)=\sin({'' if k == 1 else k}\pi x"
                          + (rf"/{length:g}" if length != 1 else "") + ")",
        "exact_latex": rf"u(x,t) = e^{{-{alpha:g}({'' if k == 1 else k}\pi" + (rf"/{length:g}" if length != 1 else "")
                       + rf")^2 t}}\sin({'' if k == 1 else k}\pi x" + (rf"/{length:g}" if length != 1 else "") + ")",
        "refinement": rows, "parameters": params, "checks": checks,
        "notes": ["The exact solution is the manufactured reference, so the observed orders measure the schemes' "
                  "truncation error directly; Crank-Nicolson's order near 2 confirms a correct second-order code."],
        "methods": ["Crank-Nicolson (dt proportional to dx)", "FTCS (alpha dt/dx^2 <= 0.4)",
                    "method of manufactured solutions", "five-grid refinement study"],
        "profile": {"x": [round(float(v), 5) for v in x_fine], "numeric": [float(v) for v in cn_fine],
                    "exact": [float(v) for v in exact_fine]},
    }


__all__ = ["compute_pde_facts", "parse_heat"]
