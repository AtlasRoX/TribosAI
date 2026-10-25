"""Capability matrix for the answer audit (tribos.verify.math_claims): false alarms on correct answers and detection of
corrupted ones, per kind of mathematics.

Cases are generated from oracle formulas evaluated with Python's `math` (never with the checker), in the shapes writers
produce: inline results, display derivations, and result tables. Each case has a correct answer and corrupted variants
of the kinds seen in practice (a factor of two, a sign flip, a swapped coefficient, a wrong exponent, a re-derived
number). The regression fixture of the captured run lives in tests/fixtures/math and is not part of this matrix.

Run: python -m tribos.evals.math_claims_matrix
"""

from __future__ import annotations

import math
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from ..verify.math_claims import audit_answer


@dataclass
class Case:
    capability: str
    name: str
    question: str
    correct: str
    corrupted: list[str] = field(default_factory=list)


def _f(x: float, places: int = 6) -> str:
    return f"{x:.{places}f}"


def _oscillator(m: float, c: float, k: float, f0: float, w: float) -> Case:
    q = (f"A forced oscillator m x'' + c x' + k x = F0 cos(ω t) has m = {m} kg, c = {c} N·s/m, k = {k} N/m, "
         f"F0 = {f0} N and ω = {w} rad/s. Find the natural frequency, damping ratio, steady-state amplitude and phase.")
    wn = math.sqrt(k / m)
    zeta = c / (2 * math.sqrt(m * k))
    amp = f0 / math.sqrt((k - m * w * w) ** 2 + (c * w) ** 2)
    phi = math.atan2(c * w, k - m * w * w)

    def text(wn_s: float, zeta_s: float, amp_s: float, phi_s: float) -> str:
        return (
            f"The natural frequency is $\\omega_n = \\sqrt{{k/m}} \\approx {_f(wn_s)}\\ \\mathrm{{rad/s}}$ and the damping ratio is "
            f"$\\zeta = \\frac{{c}}{{2\\sqrt{{mk}}}} \\approx {_f(zeta_s)}$.\n\n"
            "| Quantity | Formula | Result |\n|---|---|---|\n"
            f"| Steady-state amplitude | $X = F_0/\\sqrt{{(k-m\\omega^2)^2+(c\\omega)^2}}$ | {_f(amp_s)} |\n"
            f"| Phase lag | $\\phi = \\operatorname{{atan2}}(c\\omega,\\,k-m\\omega^2)$ | {_f(phi_s)} |\n"
        )

    return Case("second-order ODE (forced oscillator)", f"m={m},c={c},k={k},F0={f0},w={w}", q, text(wn, zeta, amp, phi), [
        text(wn, zeta, 2 * amp, phi),
        text(wn, zeta, amp, math.pi - phi),
        text(wn * 1.05, zeta, amp, phi),
        text(wn, zeta * 2, amp, phi),
    ])


def _decay(k: float, y0: float) -> Case:
    q = f"Solve y' = -k y with k = {k} 1/s and y(0) = {y0}, and give the half-life."
    half = math.log(2) / k

    def text(coef: str, half_s: float, deriv: str) -> str:
        return (
            f"$$y(t) = {coef}e^{{-{k}t}}$$\n\nDifferentiating, $$\\dot y(t) = {deriv}e^{{-{k}t}},$$ so the equation holds. "
            f"The half-life is $t_{{1/2}} = \\frac{{\\ln 2}}{{k}} \\approx {_f(half_s, 5)}\\ \\mathrm{{s}}$."
        )

    good_deriv = f"-{k * y0:g}"
    return Case("first-order ODE", f"k={k},y0={y0}", q, text(f"{y0:g}", half, good_deriv), [
        text(f"{y0:g}", half * 2, good_deriv),
        text(f"{y0:g}", half, f"{k * y0:g}"),
        text(f"{y0:g}", math.log(2) * k, good_deriv),
    ])


def _quadratic(a: int, b: int, c: int) -> Case:
    q = f"Solve {a}x^2 + {b}x + {c} = 0."
    disc = b * b - 4 * a * c
    r1, r2 = (-b + math.sqrt(disc)) / (2 * a), (-b - math.sqrt(disc)) / (2 * a)

    def text(d: float, x1: float, x2: float) -> str:
        return (f"The discriminant is $\\Delta = b^2 - 4ac = ({b})^2 - 4\\cdot {a}\\cdot ({c}) = {d:g}$. "
                f"The roots are $x_1 = \\frac{{-{b} + \\sqrt{{{disc}}}}}{{2\\cdot {a}}} \\approx {_f(x1, 5)}$ and "
                f"$x_2 = \\frac{{-{b} - \\sqrt{{{disc}}}}}{{2\\cdot {a}}} \\approx {_f(x2, 5)}$.")

    return Case("algebra", f"{a},{b},{c}", q, text(disc, r1, r2), [
        text(disc + 4, r1, r2), text(disc, -r1, r2), text(disc, r1, r2 * 2),
    ])


def _calculus(p: int, a: float, b: float) -> Case:
    q = f"For f(x) = x^{p} sin(x), find f'(x) and the integral of x^{p} from {a} to {b}."
    integral = (b ** (p + 1) - a ** (p + 1)) / (p + 1)

    def text(deriv: str, value: float) -> str:
        return (f"For $f(x) = x^{p}\\sin(x)$ the product rule gives $$f'(x) = {deriv}.$$\n\n"
                f"$$\\int_{{{a}}}^{{{b}}} x^{p}\\,dx = \\frac{{{b}^{{{p + 1}}} - {a}^{{{p + 1}}}}}{{{p + 1}}} \\approx {_f(value, 5)}$$")

    good = f"{p}x^{{{p - 1}}}\\sin(x) + x^{p}\\cos(x)"
    return Case("calculus", f"p={p},[{a},{b}]", q, text(good, integral), [
        text(f"{p}x^{{{p - 1}}}\\cos(x) + x^{p}\\sin(x)", integral),
        text(good, integral * 1.1),
        text(f"x^{{{p - 1}}}\\sin(x) + x^{p}\\cos(x)", integral),
    ])


def _series(r: float) -> Case:
    q = f"Sum the geometric series of r^k for k from 1 to infinity with r = {r}."
    s = r / (1 - r)

    def text(v: float) -> str:
        return f"$$\\sum_{{k=1}}^{{\\infty}} {r}^k = \\frac{{{r}}}{{1 - {r}}} \\approx {_f(v, 5)}$$"

    return Case("series", f"r={r}", q, text(s), [text(1 / (1 - r)), text(s * 1.5)])


def _determinant(a: int, b: int, c: int, d: int) -> Case:
    q = f"Find the determinant and trace of the matrix [[{a}, {b}], [{c}, {d}]]."

    def text(det: float, tr: float) -> str:
        return (f"$$\\det A = ad - bc = {a}\\cdot {d} - {b}\\cdot {c} = {det:g}, \\qquad \\operatorname{{tr}} A = {a} + {d} = {tr:g}$$")

    return Case("linear algebra", f"[[{a},{b}],[{c},{d}]]", q, text(a * d - b * c, a + d), [
        text(a * d + b * c, a + d), text(a * d - b * c, a - d),
    ])


def _binomial(n: int, k: int, p: float) -> Case:
    q = f"A fair process succeeds with p = {p}. In n = {n} trials, what is the probability of exactly k = {k} successes?"
    prob = math.comb(n, k) * p ** k * (1 - p) ** (n - k)

    def text(v: float, expo: int) -> str:
        return (f"$$P(K = {k}) = \\binom{{{n}}}{{{k}}} {p}^{{{k}}} (1 - {p})^{{{expo}}} \\approx {_f(v, 6)}$$")

    return Case("probability", f"n={n},k={k},p={p}", q, text(prob, n - k), [
        text(prob * 2, n - k), text(prob, n - k + 1),
    ])


def _projectile(v: float, theta_deg: float, g: float = 9.81) -> Case:
    q = f"A projectile is launched at v = {v} m/s and θ = {theta_deg} degrees with g = {g} m/s^2. Find its range and flight time."
    th = math.radians(theta_deg)
    rng = v * v * math.sin(2 * th) / g
    tf = 2 * v * math.sin(th) / g

    def text(r: float, t: float) -> str:
        return (f"The range is $R = \\frac{{v^2\\sin(2\\cdot {theta_deg}\\pi/180)}}{{g}} \\approx {_f(r, 4)}\\ \\mathrm{{m}}$ "
                f"and the flight time is $T = \\frac{{2v\\sin({theta_deg}\\pi/180)}}{{g}} \\approx {_f(t, 4)}\\ \\mathrm{{s}}$.")

    return Case("physics formulas", f"v={v},θ={theta_deg}", q, text(rng, tf), [text(rng * 2, tf), text(rng, tf / 2)])


def _energy(m: float, k: float, x0: float) -> Case:
    q = f"An undamped spring-mass system has m = {m} kg, k = {k} N/m and x(0) = {x0} m, x'(0) = 0. Find the energy."
    w = math.sqrt(k / m)
    e0 = 0.5 * k * x0 * x0

    def text(e: float) -> str:
        return (f"$$x(t) = {x0}\\cos({_f(w, 10)}t)$$\n\nThe energy is $E(t) = \\frac{{1}}{{2}}m\\dot x^2 + \\frac{{1}}{{2}}kx^2$, "
                f"so $E(0) = {_f(e, 6)}\\ \\mathrm{{J}}$ and $E(3) = {_f(e, 6)}\\ \\mathrm{{J}}$ (conserved).")

    return Case("energy and integrals", f"m={m},k={k},x0={x0}", q, text(e0), [text(e0 * 2), text(0.5 * m * x0 * x0)])


def build_cases() -> list[Case]:
    cases: list[Case] = []
    for params in [(2, 3, 50, 10, 4), (1, 0.4, 4, 2, 1.5), (1, 5, 4, 1, 3), (3.5, 1.2, 20, 7, 0.5), (0.5, 0.1, 8, 1, 4.2)]:
        cases.append(_oscillator(*params))
    cases += [_decay(0.3, 5), _decay(1.7, 0.25), _decay(0.05, 120)]
    cases += [_quadratic(1, -5, 6), _quadratic(2, 3, -2), _quadratic(1, 2, -9)]
    cases += [_calculus(2, 0, 1), _calculus(3, 1, 2), _calculus(4, 0.5, 1.5)]
    cases += [_series(0.5), _series(0.2), _series(0.9)]
    cases += [_determinant(3, 1, 4, 2), _determinant(-2, 5, 1, 7)]
    cases += [_binomial(10, 3, 0.5), _binomial(8, 2, 0.3)]
    cases += [_projectile(20, 30), _projectile(15.5, 60)]
    cases += [_energy(2, 50, 0.1), _energy(0.5, 200, 0.03)]
    return cases


def run_matrix(cases: list[Case] | None = None,
               audit: Callable[[str, str], Any] | None = None) -> dict[str, dict[str, Any]]:
    """Per capability: correct answers with any failed claim (false alarms), corrupted answers caught."""
    run = audit or (lambda text, question: audit_answer(text, question, {}))
    rows: dict[str, dict[str, Any]] = {}
    for case in cases or build_cases():
        row = rows.setdefault(case.capability, {"cases": 0, "false_alarms": 0, "corrupted": 0, "caught": 0,
                                                "claims_checked": 0, "missed": [], "alarms": []})
        row["cases"] += 1
        good = run(case.correct, case.question)
        n = good.counts()
        row["claims_checked"] += n["evaluated"]
        if n["failed"]:
            row["false_alarms"] += 1
            row["alarms"].append(f"{case.name}: {[c.detail for c in good.claims if c.status == 'failed'][:2]}")
        for i, bad_text in enumerate(case.corrupted):
            row["corrupted"] += 1
            if run(bad_text, case.question).counts()["failed"]:
                row["caught"] += 1
            else:
                row["missed"].append(f"{case.name} #{i + 1}")
    return rows


def main() -> None:
    rows = run_matrix()
    print(f"{'capability':38} {'cases':>5} {'false alarms':>12} {'corrupted':>9} {'caught':>6} {'checked claims':>14}")
    for cap, r in rows.items():
        print(f"{cap:38} {r['cases']:>5} {r['false_alarms']:>12} {r['corrupted']:>9} {r['caught']:>6} {r['claims_checked']:>14}")
        for m in r["missed"]:
            print(f"    missed: {m}")
        for a in r["alarms"]:
            print(f"    false alarm: {a}")


if __name__ == "__main__":
    main()
