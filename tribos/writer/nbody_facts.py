"""
Gravitational N-body problems the question states in full (masses, G, initial positions and velocities), integrated
by code so the answer reports measured trajectories and conservation errors instead of describing them.

What is computed, each by a method stated in the result:

- the equations of motion, r_i'' = G sum_j m_j (r_j - r_i) / |r_j - r_i|^3;
- the trajectories over the requested span (a whole number of the stated period T, or a stated end time), by an
  adaptive 8th-order Runge-Kutta (DOP853) at two tolerances and by a 4th-order symplectic integrator (Yoshida), so
  tolerance refinement and a second method are both reported;
- energy, angular momentum and centre-of-mass drift, and the return error after each period;
- the effect of the rounded initial conditions: every printed coordinate is moved by half a unit of its last printed
  digit and the run repeated, so the answer can say how much of the return error the rounding, not the integrator,
  accounts for.

A run whose two methods or two tolerances disagree beyond the stated thresholds is reported with a failed check, never
silently.
"""

from __future__ import annotations

import math
import re
from typing import Any

import numpy as np

MAX_BODIES = 12
MAX_PERIODS = 50
CURVE_POINTS = 600
SYMPLECTIC_STEPS_PER_PERIOD = 4000

_NUM = r"[-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?"
_WORD_NUMBERS = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9,
                 "ten": 10, "twenty": 20}
_SUBSCRIPTS = str.maketrans("₀₁₂₃₄₅₆₇₈₉", "0123456789")


def _normalise(text: str) -> str:
    return (text or "").translate(_SUBSCRIPTS).replace("−", "-").replace("–", "-").replace(" ", " ")


def _decimals(token: str) -> int:
    m = re.search(r"\.(\d+)", token)
    return len(m.group(1)) if m else 0


# Parsing -----------------------------------------------------------------------------------------------------------
_VEC_ASSIGN_RE = re.compile(
    rf"((?:\b[rvRV]\s*_?\{{?\s*\d{{1,2}}\s*\}}?\s*=\s*)+)\(\s*({_NUM})\s*,\s*({_NUM})(?:\s*,\s*({_NUM}))?\s*\)")
_NAME_RE = re.compile(r"\b([rvRV])\s*_?\{?\s*(\d{1,2})\s*\}?\s*=")


def parse_nbody(question: str) -> dict[str, Any] | None:
    """The bodies, masses, G and time span of a gravitational N-body problem stated in the question, or None."""
    q = _normalise(question)
    if not re.search(r"\b(?:gravit\w*|newtonian|n-body|three-body|two-body|kepler)\b", q, re.I):
        return None
    pos: dict[int, tuple[list[float], list[str]]] = {}
    vel: dict[int, tuple[list[float], list[str]]] = {}
    for m in _VEC_ASSIGN_RE.finditer(q):
        tokens = [t for t in m.groups()[1:] if t is not None]
        vec = [float(t) for t in tokens]
        for name in _NAME_RE.finditer(m.group(1)):
            target = pos if name.group(1).lower() == "r" else vel
            target[int(name.group(2))] = (vec, tokens)
    if len(pos) < 2 or set(pos) != set(vel):
        return None
    ids = sorted(pos)
    if ids != list(range(ids[0], ids[0] + len(ids))) or len(ids) > MAX_BODIES:
        return None
    dim = len(pos[ids[0]][0])
    if any(len(pos[i][0]) != dim or len(vel[i][0]) != dim for i in ids):
        return None

    g_match = re.search(rf"\bG\s*=\s*(?:m\s*=\s*)?({_NUM})", q)
    gravity = float(g_match.group(1)) if g_match else None
    masses: list[float] = []
    for i in ids:
        mi = re.search(rf"\bm\s*_?\{{?\s*{i}\s*\}}?\s*=\s*({_NUM})", q)
        masses.append(float(mi.group(1)) if mi else math.nan)
    if any(math.isnan(x) for x in masses):
        common = re.search(rf"\b(?:G\s*=\s*)?m\s*=\s*(?:G\s*=\s*)?({_NUM})", q)
        if not common:
            return None
        masses = [float(common.group(1)) if math.isnan(x) else x for x in masses]
    if gravity is None or gravity <= 0 or any(x <= 0 for x in masses):
        return None

    period = None
    p_match = re.search(rf"\bT\s*(?:≈|~|=|≃)\s*({_NUM})", q)
    if p_match:
        period = float(p_match.group(1))
    n_periods = 1
    n_match = re.search(r"\b(\d{1,3}|" + "|".join(_WORD_NUMBERS) + r")\s+(?:full\s+)?periods?\b", q, re.I)
    if n_match:
        word = n_match.group(1).lower()
        n_periods = int(word) if word.isdigit() else _WORD_NUMBERS[word]
    t_end = None
    e_match = re.search(rf"\b(?:until|up\s+to|to)\s+t\s*=\s*({_NUM})|\bt\s*(?:∈|in)\s*\[\s*{_NUM}\s*,\s*({_NUM})\s*\]", q)
    if e_match:
        t_end = float(e_match.group(1) or e_match.group(2))
    if period is None and t_end is None:
        return None
    if period is not None:
        n_periods = max(1, min(n_periods, MAX_PERIODS))
        t_end = t_end or period * n_periods
    return {
        "ids": ids, "dim": dim, "G": gravity, "masses": masses,
        "r0": np.array([pos[i][0] for i in ids], float), "v0": np.array([vel[i][0] for i in ids], float),
        "r_decimals": [[_decimals(t) for t in pos[i][1]] for i in ids],
        "v_decimals": [[_decimals(t) for t in vel[i][1]] for i in ids],
        "period": period, "period_decimals": _decimals(p_match.group(1)) if p_match else 0,
        "n_periods": n_periods if period is not None else 0, "t_end": float(t_end),
    }


# Dynamics ----------------------------------------------------------------------------------------------------------
def _accelerations(r: np.ndarray, m: np.ndarray, gravity: float) -> np.ndarray:
    diff = r[None, :, :] - r[:, None, :]  # diff[i, j] = r_j - r_i
    d2 = np.einsum("ijk,ijk->ij", diff, diff)
    np.fill_diagonal(d2, 1.0)
    weight = m[None, :] * d2 ** -1.5
    np.fill_diagonal(weight, 0.0)
    return gravity * np.einsum("ij,ijk->ik", weight, diff)


def _energy(r: np.ndarray, v: np.ndarray, m: np.ndarray, gravity: float) -> float:
    kinetic = 0.5 * float(np.sum(m * np.sum(v * v, axis=-1)))
    potential = 0.0
    for i in range(len(m)):
        for j in range(i + 1, len(m)):
            potential -= gravity * m[i] * m[j] / float(np.linalg.norm(r[j] - r[i]))
    return kinetic + potential


def _angular_momentum(r: np.ndarray, v: np.ndarray, m: np.ndarray) -> np.ndarray:
    if r.shape[1] == 2:
        return np.array([float(np.sum(m * (r[:, 0] * v[:, 1] - r[:, 1] * v[:, 0])))])
    return np.sum(m[:, None] * np.cross(r, v), axis=0)


def _dop853(r0: np.ndarray, v0: np.ndarray, m: np.ndarray, gravity: float, t_eval: np.ndarray,
            rtol: float, atol: float) -> tuple[np.ndarray, np.ndarray]:
    from scipy.integrate import solve_ivp

    n, d = r0.shape

    def rhs(_t: float, y: np.ndarray) -> np.ndarray:
        r = y[: n * d].reshape(n, d)
        return np.concatenate([y[n * d:], _accelerations(r, m, gravity).ravel()])

    sol = solve_ivp(rhs, (0.0, float(t_eval[-1])), np.concatenate([r0.ravel(), v0.ravel()]), method="DOP853",
                    t_eval=t_eval, rtol=rtol, atol=atol)
    if not sol.success:
        raise RuntimeError(sol.message)
    ys = sol.y.T
    return ys[:, : n * d].reshape(-1, n, d), ys[:, n * d:].reshape(-1, n, d)


# Yoshida's 4th-order composition of the leapfrog (Yoshida 1990, Phys. Lett. A 150, 262).
_W1 = 1.0 / (2.0 - 2.0 ** (1.0 / 3.0))
_W0 = -(2.0 ** (1.0 / 3.0)) * _W1
_C = (_W1 / 2, (_W0 + _W1) / 2, (_W0 + _W1) / 2, _W1 / 2)
_D = (_W1, _W0, _W1)


def _yoshida(r0: np.ndarray, v0: np.ndarray, m: np.ndarray, gravity: float, t_eval: np.ndarray,
             steps_per_unit: float) -> tuple[np.ndarray, np.ndarray]:
    """Symplectic 4th-order integration, sampled at t_eval (each sample reached by whole steps of equal size)."""
    r, v = r0.copy(), v0.copy()
    rs, vs = [r.copy()], [v.copy()]
    t = 0.0
    for t_next in t_eval[1:]:
        steps = max(1, int(math.ceil((t_next - t) * steps_per_unit)))
        h = (t_next - t) / steps
        for _ in range(steps):
            for k in range(3):
                r = r + _C[k] * h * v
                v = v + _D[k] * h * _accelerations(r, m, gravity)
            r = r + _C[3] * h * v
        t = t_next
        rs.append(r.copy())
        vs.append(v.copy())
    return np.array(rs), np.array(vs)


def _fmt(x: float, sig: int = 6) -> str:
    if x == 0 or not math.isfinite(x):
        return "0" if x == 0 else str(x)
    if abs(x) < 1e-3 or abs(x) >= 1e6:
        return f"{x:.{max(1, sig - 1)}e}"
    return f"{x:.{sig}g}"


def compute_nbody_facts(question: str) -> dict[str, Any] | None:
    """Integrated trajectories and conservation diagnostics for a gravitational N-body problem, or None."""
    spec = parse_nbody(question)
    if spec is None:
        return None
    m = np.array(spec["masses"], float)
    gravity, r0, v0, t_end = spec["G"], spec["r0"], spec["v0"], spec["t_end"]
    period, n_periods = spec["period"], spec["n_periods"]
    n, d = r0.shape
    marks = [period * k for k in range(1, n_periods + 1)] if period else []
    t_eval = np.unique(np.concatenate([np.linspace(0.0, t_end, CURVE_POINTS), marks or [t_end]]))
    at = {round(float(t), 12): i for i, t in enumerate(t_eval)}
    idx = lambda t: at[round(float(t), 12)]  # noqa: E731

    r_a, v_a = _dop853(r0, v0, m, gravity, t_eval, rtol=1e-10, atol=1e-12)
    r_t, v_t = _dop853(r0, v0, m, gravity, t_eval, rtol=1e-13, atol=1e-15)
    steps_per_unit = SYMPLECTIC_STEPS_PER_PERIOD / (period or max(t_end, 1.0))
    r_y, v_y = _yoshida(r0, v0, m, gravity, t_eval, steps_per_unit)

    e0 = _energy(r0, v0, m, gravity)
    l0 = _angular_momentum(r0, v0, m)
    p0 = np.sum(m[:, None] * v0, axis=0)
    com0 = np.sum(m[:, None] * r0, axis=0) / m.sum()

    def diagnostics(rs: np.ndarray, vs: np.ndarray) -> dict[str, Any]:
        energy = np.array([_energy(r, v, m, gravity) for r, v in zip(rs, vs, strict=True)])
        ang = np.array([_angular_momentum(r, v, m) for r, v in zip(rs, vs, strict=True)])
        com = np.sum(m[None, :, None] * rs, axis=1) / m.sum()
        com_expected = com0[None, :] + (p0 / m.sum())[None, :] * t_eval[:, None]
        rel_e = np.abs(energy - e0) / abs(e0)
        return {"rel_energy": rel_e, "max_rel_energy": float(rel_e.max()),
                "max_ang": float(np.max(np.linalg.norm(ang - l0[None, :], axis=-1))),
                "max_com": float(np.max(np.linalg.norm(com - com_expected, axis=-1)))}

    da, dt_, dy = diagnostics(r_a, v_a), diagnostics(r_t, v_t), diagnostics(r_y, v_y)

    # Return errors after each period (positions and velocities, worst body), from the tight run.
    returns = []
    for k, t_k in enumerate(marks, start=1):
        i = idx(t_k)
        returns.append({
            "period": k, "t": t_k,
            "position_error": float(np.max(np.linalg.norm(r_t[i] - r0, axis=-1))),
            "velocity_error": float(np.max(np.linalg.norm(v_t[i] - v0, axis=-1))),
            "rel_energy_error": float(dt_["rel_energy"][i]),
        })
    end = len(t_eval) - 1
    tol_change = float(np.max(np.linalg.norm(r_a[end] - r_t[end], axis=-1)))
    method_gap = float(np.max(np.linalg.norm(r_y[end] - r_t[end], axis=-1)))

    # Rounded initial conditions: each printed value moved by half a unit of its last digit, alternating in sign.
    # A value written without decimals ("r3 = (0, 0)") is exact, not rounded.
    signs = np.where(np.arange(n * d).reshape(n, d) % 2 == 0, 1.0, -1.0)
    r_dec, v_dec = np.array(spec["r_decimals"], float), np.array(spec["v_decimals"], float)
    half_r = np.where(r_dec > 0, 0.5 * 10.0 ** -r_dec, 0.0)
    half_v = np.where(v_dec > 0, 0.5 * 10.0 ** -v_dec, 0.0)
    r_p, _v_p = _dop853(r0 + signs * half_r, v0 - signs * half_v, m, gravity, t_eval, rtol=1e-13, atol=1e-15)
    divergence = np.max(np.linalg.norm(r_p - r_t, axis=-1), axis=-1)
    period_rounding = 0.5 * 10.0 ** -spec["period_decimals"] * float(np.max(np.linalg.norm(v0, axis=-1))) if period else 0.0

    checks = [
        {"name": f"energy conserved by DOP853 (rtol 1e-10): max |ΔE/E0| = {_fmt(da['max_rel_energy'], 3)}",
         "passed": da["max_rel_energy"] < 1e-7},
        {"name": f"tolerance refinement (rtol 1e-10 → 1e-13) moves the final positions by {_fmt(tol_change, 3)}",
         "passed": tol_change < 1e-6},
        {"name": f"second method (4th-order symplectic Yoshida, {SYMPLECTIC_STEPS_PER_PERIOD} steps per period) agrees "
                 f"with DOP853 to {_fmt(method_gap, 3)} in position at t = {_fmt(t_end, 8)}",
         "passed": method_gap < 1e-5},
        {"name": f"angular momentum conserved: max |ΔL| = {_fmt(dt_['max_ang'], 3)}", "passed": dt_["max_ang"] < 1e-9},
        {"name": f"centre of mass moves only with the total momentum: max drift {_fmt(dt_['max_com'], 3)}",
         "passed": dt_["max_com"] < 1e-9},
    ]
    params: list[dict[str, Any]] = [
        {"name": "total energy E0", "value": _fmt(e0, 10), "unit": "", "aliases": ["total energy", "energy"]},
        {"name": "angular momentum L0", "value": _fmt(float(np.linalg.norm(l0)), 6) if np.linalg.norm(l0) > 1e-12 else "0",
         "unit": "", "aliases": ["angular momentum"]},
        {"name": "max relative energy drift (DOP853, rtol 1e-10)", "value": _fmt(da["max_rel_energy"], 3), "unit": "",
         "aliases": ["energy drift", "energy error"]},
        {"name": "max relative energy drift (DOP853, rtol 1e-13)", "value": _fmt(dt_["max_rel_energy"], 3), "unit": "",
         "aliases": ["tighter tolerance", "tighter integration tolerances"]},
        {"name": "max relative energy drift (symplectic Yoshida)", "value": _fmt(dy["max_rel_energy"], 3), "unit": "",
         "aliases": ["second method", "symplectic"]},
        {"name": "max angular-momentum drift", "value": _fmt(dt_["max_ang"], 3), "unit": "",
         "aliases": ["angular-momentum drift", "angular momentum drift"]},
        {"name": "max centre-of-mass drift", "value": _fmt(dt_["max_com"], 3), "unit": "",
         "aliases": ["center-of-mass drift", "centre-of-mass drift", "center of mass drift"]},
    ]
    if returns:
        params.append({"name": "return error after one period (position)", "value": _fmt(returns[0]["position_error"], 3),
                       "unit": "", "aliases": ["return error", "return error after one period"]})
        params.append({"name": "return error after one period (velocity)", "value": _fmt(returns[0]["velocity_error"], 3),
                       "unit": "", "aliases": []})
    params.append({"name": f"divergence at t = {_fmt(t_end, 8)} from rounding the initial conditions",
                   "value": _fmt(float(divergence[-1]), 3), "unit": "",
                   "aliases": ["rounded initial conditions", "rounding"]})

    notes = []
    if returns:
        i1 = idx(marks[0])
        ret = returns[0]["position_error"]
        tol_at_t = float(np.max(np.linalg.norm(r_a[i1] - r_t[i1], axis=-1)))
        rounding_at_t = float(divergence[i1])
        # Which source the one-period return error is of the size of: integration (the tolerance change), the
        # rounded initial conditions, or the rounded period.
        sources = sorted([("integration error", tol_at_t, "the change from tightening the tolerance"),
                          ("the rounded initial conditions", rounding_at_t, "each printed value moved by half its last digit"),
                          ("the rounded period", period_rounding, "half the last digit of T times the largest speed")],
                         key=lambda s: -s[1])
        listed = ", ".join(f"{name} about {_fmt(size, 2)} ({how})" for name, size, how in sources)
        notes.append(
            f"After one period the bodies return to within {_fmt(ret, 3)} of their start. At that time the "
            f"contributions are: {listed}. {sources[0][0][0].upper() + sources[0][0][1:]} set the size of the return "
            "error; the tight integration is far more accurate than the precision of the stated initial conditions.")
    growth = [float(divergence[idx(t)]) for t in marks] if marks else []
    if len(growth) >= 2 and growth[0] > 0:
        notes.append(f"The rounding-induced deviation grows from {_fmt(growth[0], 3)} after one period to "
                     f"{_fmt(growth[-1], 3)} after {len(growth)}, about {_fmt((growth[-1] / growth[0]) ** (1 / (len(growth) - 1)), 3)}x "
                     "per period.")

    step = max(1, len(t_eval) // 300)
    return {
        "kind": "nbody_gravity",
        "n_bodies": n, "dimension": d, "G": gravity, "masses": spec["masses"],
        "equation_latex": r"\ddot{\mathbf r}_i = G\sum_{j\neq i} m_j\,\frac{\mathbf r_j-\mathbf r_i}"
                          r"{\lVert\mathbf r_j-\mathbf r_i\rVert^{3}},\qquad i = "
                          + (", ".join(str(k) for k in range(1, n + 1)) if n <= 4 else rf"1,\dots,{n}"),
        "period": period, "n_periods": n_periods, "t_end": t_end,
        "parameters": params, "checks": checks, "notes": notes, "returns": returns,
        "methods": [
            {"name": "DOP853 (adaptive 8th-order Runge-Kutta)", "rtol": 1e-10, "atol": 1e-12},
            {"name": "DOP853, tighter tolerances", "rtol": 1e-13, "atol": 1e-15},
            {"name": f"Yoshida 4th-order symplectic, {SYMPLECTIC_STEPS_PER_PERIOD} fixed steps per period"},
        ],
        "trajectories": [[[round(float(x), 6) for x in r_t[k, b, :2]] for k in range(0, len(t_eval), step)]
                         for b in range(n)],
        "energy_error": {"t": [round(float(t), 5) for t in t_eval[::step]],
                         "DOP853 rtol 1e-10": [float(max(x, 1e-17)) for x in da["rel_energy"][::step]],
                         "DOP853 rtol 1e-13": [float(max(x, 1e-17)) for x in dt_["rel_energy"][::step]],
                         "symplectic Yoshida": [float(max(x, 1e-17)) for x in dy["rel_energy"][::step]]},
        "divergence": {"t": [round(float(t), 5) for t in t_eval[::step]],
                       "values": [float(max(x, 1e-17)) for x in divergence[::step]]},
        "final_positions": [[_fmt(float(x), 9) for x in r_t[end, b]] for b in range(n)],
    }


__all__ = ["compute_nbody_facts", "parse_nbody"]
