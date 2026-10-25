"""The deterministic audit of an answer's mathematical statements (tribos.verify.math_claims).

Oracles are independent of the checker: closed-form values are computed here with `math` from textbook formulas
(steady-state amplitude F0/sqrt((k - m w^2)^2 + (c w)^2), phase atan2(c w, k - m w^2), ...), and the regression
fixtures are the captured answer (transcribed from the 2026-10-24 capture) and the same answer with the reference values
given in the remediation brief. Nothing here asserts a value the checker itself computed.
"""

from __future__ import annotations

import math
import pathlib

import pytest

from tribos.tools.registry import ToolResult
from tribos.verify.math_claims import audit_answer
from tribos.verify.verifier import TribosVerifier

FIX = pathlib.Path(__file__).parent / "fixtures" / "math"
QUESTION = (
    "Investigate a forced damped mass-spring system governed by m x'' + c x' + kx = F0 cos(ωt), with m = 2 kg, "
    "c = 3 N·s/m, k = 50 N/m, F0 = 10 N, ω = 4 rad/s, x(0) = 0.1 m, and x'(0) = 0. Derive the analytical solution, "
    "including transient and steady-state components. Calculate the natural frequency, damping ratio, damped natural "
    "frequency, steady-state amplitude, and phase."
)
# Reference values from the remediation brief (independent of the code).
REF_X = 5 / math.sqrt(117)  # 0.462250164 m
REF_PHI = math.atan2(12, 18)  # 0.588002604 rad


def _failed_texts(audit) -> list[str]:
    return [c.text for c in audit.claims if c.status == "failed"]


def test_reference_values_match_the_brief():
    assert REF_X == pytest.approx(0.462250164, abs=1e-9)
    assert REF_PHI == pytest.approx(0.588002604, abs=1e-9)
    assert math.sqrt(391) / 4 == pytest.approx(4.943429983, abs=1e-9)


def test_the_captured_answer_fails_on_every_wrong_statement():
    md = (FIX / "mass_spring_captured_answer.md").read_text(encoding="utf-8")
    audit = audit_answer(md, QUESTION, {})
    failed = " || ".join(_failed_texts(audit))
    # The amplitude written as 10/sqrt(117) ~ 0.92848 (it is 0.9245, and the formula gives 0.46225).
    assert "10/\\sqrt {117}\\approx 0.92848" in failed
    assert "0.92848 | m" in failed  # the characteristic-parameter table row
    assert "2.55359 | rad" in failed  # phase from atan2(c w, k - m w^2) is 0.588, not 2.55359
    assert "x_p(t)=X\\cos (4t-\\phi )" in failed  # the amplitude-phase form does not reconstruct x_p
    assert any(c.kind == "derivative" and c.status == "failed" for c in audit.claims)  # swapped x_p'
    assert "\\frac {20}{13}=0" in failed  # x'(0) equation with the wrong derivative term
    assert "\\frac {20}{13})\\approx -0.250656440625879" in failed  # B's printed formula gives -0.3544
    # The correct parts hold: natural frequency, damping ratio, damped frequency, final solution, energy terms.
    passed = " || ".join(c.text for c in audit.claims if c.status == "passed")
    for fragment in ("Undamped natural frequency", "Damping ratio", "Damped natural frequency", "$E(20)$",
                     "W_{\\mathrm{in}}"):
        assert fragment in passed


def test_the_corrected_answer_passes_every_checkable_statement():
    md = (FIX / "mass_spring_corrected_answer.md").read_text(encoding="utf-8")
    audit = audit_answer(md, QUESTION, {})
    counts = audit.counts()
    assert counts["failed"] == 0, _failed_texts(audit)
    assert counts["passed"] >= 30
    # Uncheckable notation (the characteristic roots with +-) is reported as such, never as a failure.
    assert counts["inconclusive"] <= 3


@pytest.mark.parametrize("corruption", [
    ("$X = 5/\\sqrt{117} \\approx 0.462250\\ \\mathrm{m}$", "$X = 5/\\sqrt{117} \\approx 0.472250\\ \\mathrm{m}$"),
    ("| 0.588003 | rad |", "| -0.588003 | rad |"),
    ("- \\frac{20}{13}\\sin(4t) + \\frac{40}{39}\\cos(4t).$$", "+ \\frac{20}{13}\\sin(4t) + \\frac{40}{39}\\cos(4t).$$"),
    ("| 4.94343 | rad/s |", "| 4.95343 | rad/s |"),
    ("| 100.210 | J |", "| 101.210 | J |"),
])
def test_one_corrupted_statement_in_a_correct_answer_is_caught(corruption):
    md = (FIX / "mass_spring_corrected_answer.md").read_text(encoding="utf-8")
    old, new = corruption
    assert md.count(old) == 1
    audit = audit_answer(md.replace(old, new), QUESTION, {})
    assert audit.counts()["failed"] >= 1


def _oscillator_answer(m, c, k, f0, w, x_amp, phi, convention="cos"):
    """A short answer in the shape writers produce, with the values to state passed in (correct or not)."""
    form = (
        r"x_p(t) = X\cos(\omega t - \phi)" if convention == "cos" else r"x_p(t) = X\sin(\omega t + \theta)"
    )
    angle = r"\phi" if convention == "cos" else r"\theta"
    return f"""## Steady state

The steady-state response is $x_p(t) = C\\cos(\\omega t) + D\\sin(\\omega t)$ with

$$C = \\frac{{F_0 (k - m\\omega^2)}}{{(k - m\\omega^2)^2 + (c\\omega)^2}}, \\qquad D = \\frac{{F_0 c\\omega}}{{(k - m\\omega^2)^2 + (c\\omega)^2}}.$$

In amplitude-phase form $${form}, \\qquad X = \\frac{{F_0}}{{\\sqrt{{(k - m\\omega^2)^2 + (c\\omega)^2}}}} \\approx {x_amp:.6f}, \\qquad {angle} \\approx {phi:.6f}.$$
"""


PARAMS = [
    (2, 3, 50, 10, 4),  # the captured problem: underdamped, below resonance
    (1, 0.4, 4, 2, 1.5),  # lightly damped, near resonance
    (1, 5, 4, 1, 3),  # overdamped, above resonance
    (3.5, 1.2, 20, 7, 0.5),  # far below resonance
]


@pytest.mark.parametrize("m,c,k,f0,w", PARAMS)
def test_amplitude_and_phase_statements_across_regimes(m, c, k, f0, w):
    q = f"Forced oscillator m x'' + c x' + k x = F0 cos(ω t) with m = {m} kg, c = {c} N·s/m, k = {k} N/m, F0 = {f0} N, ω = {w} rad/s."
    amp = f0 / math.sqrt((k - m * w * w) ** 2 + (c * w) ** 2)  # oracle
    phi = math.atan2(c * w, k - m * w * w)  # oracle, convention X cos(wt - phi)
    good = audit_answer(_oscillator_answer(m, c, k, f0, w, amp, phi), q, {})
    assert good.counts()["failed"] == 0, _failed_texts(good)
    assert good.counts()["passed"] >= 2
    # Twice the amplitude (the captured error) and the atan2 sign error are both contradicted.
    assert audit_answer(_oscillator_answer(m, c, k, f0, w, 2 * amp, phi), q, {}).counts()["failed"] >= 1
    assert audit_answer(_oscillator_answer(m, c, k, f0, w, amp, math.pi - phi), q, {}).counts()["failed"] >= 1


@pytest.mark.parametrize("m,c,k,f0,w", PARAMS[:2])
def test_an_equivalent_sign_convention_passes_and_a_wrong_one_fails(m, c, k, f0, w):
    q = f"m = {m} kg, c = {c} N·s/m, k = {k} N/m, F0 = {f0} N, ω = {w} rad/s."
    amp = f0 / math.sqrt((k - m * w * w) ** 2 + (c * w) ** 2)
    theta = math.atan2(k - m * w * w, c * w)  # oracle for X sin(wt + theta)
    assert audit_answer(_oscillator_answer(m, c, k, f0, w, amp, theta, "sin"), q, {}).counts()["failed"] == 0
    assert audit_answer(_oscillator_answer(m, c, k, f0, w, amp, -theta, "sin"), q, {}).counts()["failed"] >= 1


def test_equivalent_representations_of_one_quantity_agree():
    q = "m = 2 kg, c = 3 N·s/m, k = 50 N/m, F0 = 10 N, ω = 4 rad/s"
    md = r"""
$$\omega_n = \sqrt{k/m} = 5, \qquad \zeta = \frac{c}{2\sqrt{mk}} = 0.15,$$

$$X = \frac{F_0/m}{\sqrt{(\omega_n^2-\omega^2)^2 + (2\zeta\omega_n\omega)^2}} = \frac{F_0}{\sqrt{(k-m\omega^2)^2+(c\omega)^2}} = \frac{5}{\sqrt{117}}.$$
"""
    audit = audit_answer(md, q, {})
    assert audit.counts()["failed"] == 0 and audit.counts()["passed"] >= 3


@pytest.mark.parametrize("md,ok", [
    (r"For $f(x) = x^3 - 2x$, $f'(x) = 3x^2 - 2$ and $f'(2) = 10$.", True),
    (r"For $f(x) = x^3 - 2x$, $f'(x) = 3x^2$ and $f'(2) = 10$.", False),
    (r"$$\int_0^1 x^2\,dx = \frac{1}{3} \approx 0.3333$$", True),
    (r"$$\int_0^1 x^2\,dx = 0.5$$", False),
    (r"$$\sum_{k=1}^{\infty} \frac{1}{2^k} = 1$$", True),
    (r"$$\frac{x^2 - 9}{x + 3} = x - 3$$", True),
    (r"$$\sin^2(x) + \cos^2(x) = 1$$", True),
    (r"$$e^{i\pi} + 1 = 0$$", True),
    (r"$$\frac{\sqrt{12}}{2} = \sqrt{3} \approx 1.7321$$", True),
    (r"$$\frac{\sqrt{12}}{2} = \sqrt{3} \approx 1.7421$$", False),
])
def test_other_mathematics(md, ok):
    audit = audit_answer(md, "", {})
    n = audit.counts()
    assert n["extracted"] >= 1
    assert (n["failed"] == 0) is ok, [c.detail for c in audit.claims]


def test_an_equation_to_solve_is_never_reported_as_a_false_identity():
    md = r"Solve $x^2 = 2x + 1$. The roots are $x = 1 \pm \sqrt{2}$."
    audit = audit_answer(md, "Solve x^2 = 2x + 1", {})
    assert audit.counts()["failed"] == 0


_INEQUALITY_ANSWER = r"""## Executive Summary

The solution set is $$x \in \left[-\tfrac12, 0\right) \cup \left(0, \tfrac{45}{8}\right).$$

Endpoint checks: $x = -1/2$ gives LHS $= 1 < 8 =$ RHS (included); $x = 0$ is undefined (excluded);
$x = 45/8$ gives equality $81/4 = 81/4$ (excluded).

## Substitution

$$t = \sqrt{2x+1}, \quad x = \frac{t^2-1}{2}.$$

$$\frac{4x^2}{(1-\sqrt{2x+1})^2} = \frac{(t^2-1)^2}{(1-t)^2} = (t+1)^2.$$

$$2x + 9 = (t^2 - 1) + 9 = t^2 + 8.$$
"""


@pytest.mark.parametrize("question", [
    "Solve 4x^2/(1-sqrt(2x+1))^2 < 2x+9",
    "",  # unparsed question: "x \in [...]" in the answer still marks x as the unknown
])
def test_roots_and_endpoints_of_the_unknown_are_cases_not_contradictions(question):
    """"x = -1/2 ... x = 0 ... x = 45/8" examines points of the unknown; binding x to the first one reported the others
    as "x evaluates to -0.5, 0 to 0" (contradicted) and made a correct answer low-confidence."""
    audit = audit_answer(_INEQUALITY_ANSWER, question, {})
    assert audit.counts()["failed"] == 0, _failed_texts(audit)
    if question:  # with the unknown known, the substitution identities are checked and hold
        assert audit.counts()["passed"] >= 3


def test_hypothetical_statements_are_not_claims_about_this_problem():
    md = "If the damping were removed, $X = 10/18 \\approx 0.5556$ m. With damping, $X = 5/\\sqrt{117} \\approx 0.46225$ m."
    audit = audit_answer(md, "m = 2 kg, c = 3, k = 50, F0 = 10 N, ω = 4", {})
    assert [c.status for c in audit.claims] == ["passed"]


def test_a_prose_only_answer_has_no_claims_and_is_not_evaluated():
    question = "Why does viscous damping limit the response of a forced oscillator?"
    md = ("Viscous damping limits the response of a forced oscillator because the damper removes energy every cycle, "
          "so the transient dies out and the forced response settles where input and dissipation balance.")
    audit = audit_answer(md, question, {})
    assert audit.counts()["extracted"] == 0
    report = TribosVerifier().verify_response(
        query=question, response_markdown=md,
        tool_results={"t": ToolResult(success=True, tool_name="t", data={"note": "anything"})},
    )
    assert report.coverage["evaluated"] == 0
    assert report.status == "not_evaluated"
    assert report.fully_verified is False


def _ode_verification_result():
    """The real ODE verification of the regression IVP (no mocks): parameters with formulas and symbols."""
    from tribos.dynamis.verification import verify_ode_solution

    solution = ("(-0.250656440625879*sin(sqrt(391)*t/4) - 0.284615384615385*cos(sqrt(391)*t/4))*exp(-3*t/4)"
                " + 10*sin(4*t)/39 + 5*cos(4*t)/13")
    rep = verify_ode_solution("(2) x'' + (3) x' + (50) x = (10) cos((4) t)", "x(t)", {"x(0)": "0.1", "x'(0)": "0"},
                              f"x(t) = {solution}", 20.0)
    assert rep is not None
    return ToolResult(success=True, tool_name="ode_verification", data=rep)


def test_a_stated_amplitude_is_cross_checked_against_the_computed_one():
    tools = {"ode_verification": _ode_verification_result()}
    wrong = "The steady-state amplitude is $X \\approx 0.92848\\ \\mathrm{m}$."
    audit = audit_answer(wrong, QUESTION, tools)
    assert audit.counts()["failed"] == 1
    assert "computed X = 0.46225" in audit.claims[0].detail
    right = "The steady-state amplitude is $X \\approx 0.462250\\ \\mathrm{m}$."
    good = audit_answer(right, QUESTION, tools)
    assert good.counts()["failed"] == 0 and good.counts()["passed"] == 1


def test_changing_a_correct_result_in_the_final_answer_fails_verification():
    md = (FIX / "mass_spring_corrected_answer.md").read_text(encoding="utf-8")
    tools = {"ode_verification": _ode_verification_result()}
    ok = TribosVerifier().verify_response(query=QUESTION, response_markdown=md, tool_results=tools)
    assert ok.coverage["failed"] == 0 and ok.coverage["evaluated"] >= 30
    bad = TribosVerifier().verify_response(query=QUESTION, response_markdown=md.replace("| 0.462250 | m |", "| 0.92450 | m |"),
                                           tool_results=tools)
    assert bad.passed is False and bad.status == "failed"
    assert any(d.category == "MATH_CONSISTENCY" for d in bad.defects)


def test_table_numbers_are_grounded_in_tool_outputs():
    tools = {"calc": ToolResult(success=True, tool_name="calcula_run_python",
                                data={"stdout": "h=0.1 err=9.069e-04 order=nan\nh=0.05 err=5.600e-05 order=4.02"})}
    md = """| h | Max error | Order |
|---|---|---|
| 0.1 | $9.069\\times 10^{-4}$ | — |
| 0.05 | $5.600\\times 10^{-5}$ | 4.02 |
| 0.025 | $3.111\\times 10^{-6}$ | 4.01 |
"""
    audit = audit_answer(md, "", tools)
    statuses = [c.status for c in audit.claims if c.kind == "grounding"]
    assert statuses == ["passed", "passed", "unsupported"]


def test_the_audit_is_fast_enough_for_every_answer():
    import time

    md = (FIX / "mass_spring_corrected_answer.md").read_text(encoding="utf-8")
    t0 = time.perf_counter()
    audit_answer(md, QUESTION, {})
    assert time.perf_counter() - t0 < 15.0


def test_superscript_digits_in_a_table_never_stop_the_audit():
    """Live-run regression: a units cell "s⁻¹" made the tokenizer fail and the whole audit was skipped."""
    md = r"""| Quantity | Formula | Result | Units |
|---|---|---|---|
| Decay rate | $\sigma = c/(2m)$ | 0.75 | s⁻¹ |
| Damping ratio | $\zeta = c/(2\sqrt{mk})$ | 0.15 | — |
"""
    audit = audit_answer(md, "m = 2 kg, c = 3 N·s/m, k = 50 N/m", {})
    assert audit.counts()["passed"] == 2


def test_a_symbol_reused_later_does_not_resolve_an_unrelated_equation():
    """Live-run regression: "r" was a characteristic root in one section and the frequency ratio in another."""
    md = r"""### Transient part

The characteristic equation is $$r^2 + \frac{3}{2}r + 25 = 0.$$

### Characteristic parameters

| Quantity | Formula | Result |
|---|---|---|
| Frequency ratio | $r = \omega/\omega_n$ | 0.8 |
"""
    audit = audit_answer(md, "m = 2 kg, c = 3 N·s/m, k = 50 N/m, F0 = 10 N, ω = 4 rad/s, ω_n = 5 rad/s", {})
    assert audit.counts()["failed"] == 0


@pytest.mark.parametrize("name", ["mass_spring_live_answer.md", "mass_spring_live_answer_2.md", "mass_spring_live_answer_3.md",
                                  "mass_spring_live_answer_4.md"])
def test_real_writer_answers_raise_no_false_alarms(name):
    """Two answers the live application wrote for the regression question (2026-10-25), both mathematically correct.
    Before the fixes they produced false contradictions: rounded X and phi inside x_p, a reused "r", an angle written
    in degrees ("0.588003 rad = 33.690°"), and a reference condition ("below resonance (r = 1)")."""
    md = (FIX / name).read_text(encoding="utf-8")
    audit = audit_answer(md, QUESTION, {})
    n = audit.counts()
    assert n["failed"] == 0, _failed_texts(audit)
    assert n["passed"] >= 40


def test_an_angle_in_degrees_is_the_same_angle_in_radians():
    md = r"$$\phi = \operatorname{atan2}(12, 18) = 0.588003\,\mathrm{rad} = 33.690^\circ$$ and later $\phi \approx 33.69°$."
    audit = audit_answer(md, "", {})
    assert audit.counts()["failed"] == 0 and audit.counts()["passed"] == 2
    wrong = r"$$\phi = \operatorname{atan2}(12, 18) = 0.588003\,\mathrm{rad} = 36.690^\circ$$"
    assert audit_answer(wrong, "", {}).counts()["failed"] == 1


def test_an_expression_continued_over_aligned_lines_is_one_statement():
    md = r"""$$\begin{aligned}
x(t) = {}& \Big(-0.250656440625879\sin\big(\tfrac{\sqrt{391}}{4}t\big) \
&\quad - 0.284615384615385\cos\big(\tfrac{\sqrt{391}}{4}t\big)\Big)e^{-3t/4} \
&\quad + \frac{10}{39}\sin(4t) + \frac{5}{13}\cos(4t)
\end{aligned}$$

$$x(0) = 0.1, \qquad \dot x(0) = 0$$
"""
    audit = audit_answer(md, QUESTION, {})
    assert audit.counts()["failed"] == 0
    assert [d.defines for d in audit.definitions] == ["x(t)"]
    assert audit.counts()["passed"] >= 2  # the initial conditions are checked against the joined solution
