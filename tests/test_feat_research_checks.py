"""Research-grounded verification of the code-computed results (tribos.writer.analysis): the RK4 convergence study
(observed order of accuracy, Richardson extrapolation and GCI per ASME V&V 20) and the physics consistency checks
(energy balance, stability, amplitude cross-check, limiting cases), and how they reach the writer and the panel."""

from __future__ import annotations

import sympy as sp

from tribos.agents.stem_evidence import render_computed_results
from tribos.tools.registry import ToolResult
from tribos.writer.analysis import physics_checks
from tribos.writer.facts import compute_ode_facts
from tribos.writer.genui import build_answer_ui

OSCILLATOR = ("Solve 2x''(t) + 3x'(t) + 50x(t) = 10cos(4t) with x(0)=0.1 m, x'(0)=0 m/s. "
              "Compute x(t) for t=0,0.5,1,...,5 seconds. Compare with RK4 using step 0.001 s.")


def test_convergence_study_measures_fourth_order():
    conv = compute_ode_facts(OSCILLATOR)["convergence"]
    assert abs(float(conv["observed_order"]) - 4) < 0.1
    assert all(c["passed"] for c in conv["checks"]) and len(conv["checks"]) == 2
    rich = conv["richardson_at_final_time"]
    assert rich["status"] == "monotone convergence" and float(rich["extrapolation_error"]) < 1e-8


def test_convergence_without_an_exact_solution_uses_richardson():
    facts = compute_ode_facts("Solve x''(t) + sin(x(t)) = 0 with x(0)=1, x'(0)=0. Compute x at t=1,2,5 and compare with RK4.")
    conv = facts["convergence"]
    assert "max_error" not in conv["runs"][0]
    assert conv["richardson_at_final_time"]["status"] == "monotone convergence"
    assert [c["passed"] for c in conv["checks"]] == [True]


def test_physics_checks_pass_for_the_true_solution():
    physics = compute_ode_facts(OSCILLATOR)["physics"]
    names = " ".join(c["name"] for c in physics["checks"])
    for word in ("energy balance", "stability", "amplitude of the solved steady-state part", "static limit",
                 "high-frequency limit", "undamped limit"):
        assert word in names
    assert all(c["passed"] for c in physics["checks"])
    q = {x["name"]: x for x in physics["quantities"]}
    assert q["decay time constant"]["exact_latex"] == r"\frac{4}{3}"
    assert q["static deflection F0/k"]["value"] == "0.2"
    assert q["resonance frequency (peak of the amplitude)"]["exact_latex"] == r"\frac{\sqrt{382}}{4}"


def test_energy_balance_rejects_a_wrong_solution():
    t = sp.Symbol("t")
    good = sp.exp(-t) * sp.cos(2 * t)  # solves x'' + 2x' + 5x = 0
    ok = physics_checks([sp.Integer(1), sp.Integer(2), sp.Integer(5)], sp.Integer(0), t, good, None, None, 0, 3, "m", "s")
    bad = physics_checks([sp.Integer(1), sp.Integer(2), sp.Integer(5)], sp.Integer(0), t, good * (1 + t / 50), None, None,
                         0, 3, "m", "s")
    assert ok["checks"][0]["passed"] and not bad["checks"][0]["passed"]


def test_negative_damping_is_reported_unstable():
    t = sp.Symbol("t")
    growing = sp.exp(t / 20) * sp.cos(2 * t)
    res = physics_checks([sp.Integer(1), sp.Rational(-1, 10), sp.Integer(4)], sp.Integer(0), t, growing, None, None,
                         0, 1, "", "")
    stability = next(c for c in res["checks"] if c["name"].startswith("stability"))
    assert not stability["passed"]
    assert not any(q["name"] == "decay time constant" for q in res["quantities"])


def test_panel_and_writer_get_the_new_analysis():
    facts = compute_ode_facts(OSCILLATOR)
    ui = build_answer_ui(facts)
    by_title = {b.get("title", ""): b for b in ui["blocks"]}
    checks = by_title["Independent checks"]
    assert checks["type"] == "checks" and len(checks["items"]) == 8 and all(i["passed"] for i in checks["items"])
    freq = next(b for b in ui["blocks"] if b["type"] == "chart" and b["title"].startswith("Frequency response"))
    assert [m[2] for m in freq["marks"]] == ["forcing", "resonance"]
    conv_chart = next(b for b in ui["blocks"] if b["type"] == "chart" and b["title"].startswith("Convergence"))
    assert conv_chart["x"]["scale"] == "log" and conv_chart["y"]["scale"] == "log"

    text = "\n".join(render_computed_results(ToolResult(success=True, tool_name="computed_results", data=facts)))
    assert "<physics_check passed=\"true\">energy balance" in text
    assert "<convergence_study observed_order=" in text and "frequency_response" not in text


# Run 2026-10-30 (near-resonance oscillator): \operatorname{atan} lost its left side; "~ 1.2" passed for 1.10308 ---
def test_operatorname_function_is_a_function_not_a_word():
    from tribos.verify.math_claims import audit_answer

    q = "Solve x''(t) + 0.4x'(t) + 25x(t) = 8cos(4.9t) with x(0)=0 m, x'(0)=1 m/s."
    claims = audit_answer(r"$$\phi=\operatorname{atan}(1.97980)\approx 1.10308\,\mathrm{rad}\approx 63.2016^{\circ}.$$", q).claims
    assert claims and all(c.status != "failed" for c in claims) and claims[0].text.startswith(r"\phi")


def test_a_printed_value_must_be_a_rounding_or_truncation():
    from tribos.verify.math_claims import audit_answer

    q = "Evaluate the expressions."
    status = {s: [c.status for c in audit_answer(s, q).claims] for s in (
        r"$$\arctan\left(\frac{196}{99}\right)\approx 1.2$$", r"$$\arctan\left(\frac{196}{99}\right)\approx 1.1$$",
        r"$$\sqrt{3}\approx 1.74$$", r"$$\sqrt{3}\approx 1.73$$", r"$$\frac{2}{3}\approx 0.66$$")}
    assert list(status.values()) == [["failed"], ["passed"], ["failed"], ["passed"], ["passed"]]


def test_long_exact_solution_is_split_over_two_lines():
    ui = build_answer_ui(compute_ode_facts(OSCILLATOR))
    eq = next(b for b in ui["blocks"] if b["type"] == "equation")
    assert eq["latex"].startswith(r"\begin{aligned} x(t) &= \underbrace{") and r"_{\text{steady state}}" in eq["latex"]
    stability = next(c for c in compute_ode_facts(OSCILLATOR)["physics"]["checks"] if c["name"].startswith("stability"))
    assert stability["detail"] == r"r = - \frac{3}{4} \pm \frac{\sqrt{391}}{4}\,i"


# Undamped resonance: no false "unstable" failure, the secular growth verified, and no crash at the infinite amplitude --
def test_undamped_resonance_is_classified_and_its_growth_verified():
    d = compute_ode_facts("Solve x''(t) + 16x(t) = 8sin(4t) + 3cos(2t) with x(0)=1 m, x'(0)=-2 m/s. "
                          "Compute x(t) at t = 0.5, 2, 5, 10 s and compare with RK4 using step 0.001 s.")
    assert [r["x"] for r in d["table"]] == ["-0.1962855", "-0.2288754", "-2.172353", "6.084919"]
    checks = {c["name"].split(":")[0]: c for c in d["physics"]["checks"]}
    assert checks["stability"]["passed"] and "marginally stable" in checks["stability"]["name"]
    assert checks["resonance"]["passed"] and checks["resonance"]["detail"].endswith(" 1")


def test_resonance_check_rejects_the_wrong_growth_rate():
    from tribos.writer.analysis import _resonance_checks

    t = sp.Symbol("t")
    forcing = 8 * sp.sin(4 * t) + 3 * sp.cos(2 * t)
    right = (sp.Rational(3, 4) - t) * sp.cos(4 * t) - sp.sin(4 * t) / 4 + sp.cos(2 * t) / 4
    wrong = (sp.Rational(3, 4) - t / 2) * sp.cos(4 * t) - sp.sin(4 * t) / 4 + sp.cos(2 * t) / 4
    args = (sp.Integer(1), sp.Integer(0), sp.Integer(16), forcing, t)
    assert _resonance_checks(*args, right)[0]["passed"] and not _resonance_checks(*args, wrong)[0]["passed"]


def test_pure_resonance_no_longer_drops_the_computed_results():
    d = compute_ode_facts("Solve x''(t) + 9x(t) = 6cos(3t) with x(0)=0, x'(0)=0. Compute x at t=1,2 and compare with RK4.")
    assert d["exact_solution_latex"] == r"x(t) = t \sin{\left(3 t \right)}"
    assert any(p["name"] == "resonant amplitude growth rate" and p["value"] == "1" for p in d["parameters"])
    assert all(c["passed"] for c in d["physics"]["checks"]) and build_answer_ui(d) is not None


# Hard resonance run (2026-10-30): "12A = 3" read as amperes, value lists split into items, prose items unchecked --------
def test_a_capital_after_a_number_is_a_coefficient_not_a_unit():
    from tribos.verify.math_claims import audit_answer

    q = "Solve x''(t) + 16x(t) = 8sin(4t) + 3cos(2t) with x(0)=1 m, x'(0)=-2 m/s."
    assert [c.status for c in audit_answer(r"Then $12A = 3$ and $A = 1/4$.", q).claims] == ["passed"]
    assert [c.status for c in audit_answer(r"Then $12A=3$, so $A=\frac{1}{3}$.", q).claims] == ["failed"]


def test_a_list_of_values_stays_one_requested_item():
    from tribos.agents.deliverables import requested_items

    assert [i["item"] for i in requested_items("4. Compute x(t) at t = 0.5, 2, 5 and 10 s.")] == ["x(t) at t = 0.5, 2, 5, 10 s"]
    assert [i["item"] for i in requested_items("Find the mean, median and mode.")] == ["mean", "median", "mode"]


def test_energy_growth_and_substitution_items_are_checked_from_computed_results():
    from tribos.agents.deliverables import _computed_item_checked

    facts = compute_ode_facts("Solve x''(t) + 16x(t) = 8sin(4t) + 3cos(2t) with x(0)=1 m, x'(0)=-2 m/s. "
                              "Compute x(t) at t = 0.5, 2, 5, 10 s.")
    answer = ("Substituting back satisfies the equation and both initial conditions. The amplitude grows at 1 m/s. "
              "The forcing does work 690.814 J, equal to the change in mechanical energy 690.814 J.")
    for item in ("it satisfies the equation", "initial conditions", "rate at which the amplitude grows", "work done",
                 "change in mechanical energy"):
        assert _computed_item_checked(item, facts, answer), item
    wrong = answer.replace("690.814", "512.3")  # the computed value appears nowhere
    assert not _computed_item_checked("work done", facts, wrong)
    assert not _computed_item_checked("rate at which the amplitude grows", facts, answer.replace("grows at 1 m/s", "grows at 2 m/s"))


def test_hypotheses_are_skipped_when_code_answered_the_question():
    from types import SimpleNamespace

    from tribos.agentic.hypothesis import HypothesisPhase

    facts = compute_ode_facts("Solve x''(t) + 16x(t) = 8sin(4t) with x(0)=1, x'(0)=0. Compute x at t=1,2.")
    state = SimpleNamespace(ctx=SimpleNamespace(scope="research", excluded_modules=set()), options={},
                            clean_query="Explain why the motion grows and what would happen with damping.", query="",
                            tool_results={"computed_results": ToolResult(success=True, tool_name="computed_results", data=facts)})
    assert HypothesisPhase().applies(state) is False


# Second hard run: "At T = 10 s" after "At T = 5 s", "\frac12 kx(t)^2", "{\rm m/s}" units, "For <ODE>," premises ------------
_HARD_Q = "Solve x''(t) + 16x(t) = 8sin(4t) + 3cos(2t) with x(0)=1 m, x'(0)=-2 m/s."


def _statuses(md: str, q: str = _HARD_Q) -> list[str]:
    from tribos.verify.math_claims import audit_answer

    return [c.status for c in audit_answer(md, q).claims]


def test_a_new_evaluation_point_is_not_a_contradiction():
    assert "failed" not in _statuses(r"At $T=5\ \rm s$ the energy is $E$. Evaluating again at $T=10\ \rm s$ it is larger.")
    assert _statuses(r"Let $T = 5$. Then $T = 10$.") == ["failed"]  # no evaluation cue: a real contradiction
    assert _statuses(r"With $m=2\,\mathrm{kg}$ the mass is heavy.", "A mass m = 1 kg on a spring k = 16 N/m.") == ["failed"]


def test_old_style_units_and_coefficient_products_bind_correctly():
    md = (r"$$x(t)=\left(\frac34-t\right)\cos 4t-\frac{\sin 4t}{4}+\frac{\cos 2t}{4}\ {\rm m}.$$" "\n\n"
          r"$$v(t)=-2\cos 4t-3\sin 4t+4t\sin 4t-\frac12\sin 2t\ {\rm m/s}.$$" "\n\n"
          r"$$E(t)=\frac12 v(t)^{2}+\frac12 kx(t)^{2}=\frac12 v(t)^{2}+8x(t)^{2}\quad{\rm J},$$" "\n\n"
          r"With $k=16$: $E(0)=2+8=10\ \rm J$ and $E(10)\approx 700.814\ \rm J$.")
    assert "failed" not in _statuses(md)
    assert "failed" in _statuses(md.replace(r"E(10)\approx 700.814", r"E(10)\approx 650.814"))


def test_a_differential_equation_after_for_is_a_premise():
    assert _statuses(r"For $m\ddot x+kx=F_{0}\sin\omega_{n}t$, the resonant growth is linear.") == []


# Third hard run: "5 and 10 s" lost the 10, "on [0, 10] s" ignored, physics negation read as literature absence -------
def test_value_lists_with_and_and_named_intervals_set_the_computed_range():
    from tribos.writer.facts import _time_points, parse_ode_problem

    assert _time_points("Compute x(t) at t = 0.5, 2, 5 and 10 s.", "t") == [0.5, 2.0, 5.0, 10.0]
    assert _time_points("x at t = 1, 2, and 3", "t") == [1.0, 2.0, 3.0]
    p = parse_ode_problem("Solve x''(t) + x(t) = 0 with x(0)=1, x'(0)=0 and compare with RK4 on [0, 20].")
    assert p is not None and p.end_time(0.0) == 20.0
    d = compute_ode_facts("Solve x''(t) + 16x(t) = 8sin(4t) + 3cos(2t), x(0) = 1 m, x'(0) = -2 m/s. "
                          "Compute x(t) at t = 0.5, 2, 5 and 10 s. Compute the work done by the forcing over [0, 10] s.")
    assert d["table"][-1] == {"t": "10", "x": "6.084919"}
    assert {q["name"]: q["value"] for q in d["physics"]["quantities"]}["work done by the forcing"] == "690.814"


def test_physics_negation_is_not_a_literature_absence():
    from tribos.verify.verifier import _ABSENCE_PATTERN

    assert not _ABSENCE_PATTERN.search("There is no damping loss, so the free oscillation neither decays nor grows.")
    assert not _ABSENCE_PATTERN.search("there is no real solution")
    assert _ABSENCE_PATTERN.search("There are no published studies on this alloy.")


def test_working_instructions_are_not_deliverables():
    from tribos.agents.deliverables import requested_items

    items = [i["item"] for i in requested_items("Compute x(1). Show intermediate steps, keep units, and verify every "
                                                "final number independently.")]
    assert "keep units" not in items and not any("every final number" in i for i in items)


def test_brace_exponents_and_decaying_forcing_terms():
    d = compute_ode_facts("Solve x''(t) + 6x'(t) + 9x(t) = 50t e^{-3t} + 18cos(3t), x(0) = 0 m, x'(0) = 2 m/s. "
                          "Compute x(t) at t = 0.5, 1, 2 and 6 s.")
    assert d is not None and d["steady_state_latex"] == r"\sin{\left(3 t \right)}"
    assert [r["x"] for r in d["table"]] == ["1.118357", "0.5062252", "-0.1191229", "-0.7509599"]
    params = {p["name"]: p for p in d["parameters"]}
    assert params["steady-state amplitude"]["value"] == "1" and params["phase lag of the response behind the forcing"]["value_degrees"] == "90"
    assert all(c["passed"] for c in d["physics"]["checks"])


# Fourth hard run: an asymptotic "x ~ sin 3t" read as a pointwise identity, and one claim charged to four tasks -------
def test_an_asymptotic_approximation_is_checked_as_a_limit():
    q = "Solve x''(t) + 6x'(t) + 9x(t) = 50t e^(-3t) + 18cos(3t), x(0) = 0 m, x'(0) = 2 m/s."
    pre = r"$$x(t)=e^{-3t}\left(\frac{25t^3}{3}-t\right)+\sin(3t).$$" "\n\n"
    assert _statuses(pre + r"For large $t$ the transient dies out and $x\approx \sin 3t$.", q)[0] == "passed"
    assert _statuses(pre + r"For large $t$, $x\approx 2\sin 3t$.", q)[0] == "failed"


def test_a_claim_under_one_task_heading_is_not_charged_to_other_tasks():
    from tribos.agents.deliverables import _claim_in_item_section

    claim = r"5. Find the time and value of the largest x(t) on [0, 6] s.: x\approx \sin 3t"
    assert _claim_in_item_section(claim, "value of the largest x(t) on [0, 6] s")
    for other in ("exact solution x(t)", "x(t) at t = 0.5, 1, 2, 6 s",
                  "why the 50t e^{-3t} term needs a t^2 factor in its trial solution"):
        assert not _claim_in_item_section(claim, other), other
    assert _claim_in_item_section("x = 3", "exact solution x(t)")  # no heading: symbols decide, as before


# Open problems (Collatz, Goldbach): no formal-proof attempt, no false alarms on the conjecture or a described count -----
def test_famous_open_problems_skip_the_formal_prover():
    from types import SimpleNamespace

    from tribos.agentic.formal_proof import FAMOUS_OPEN_PROBLEM_RE, FormalProofPhase

    state = SimpleNamespace(clean_query="Prove the Collatz conjecture and Goldbach's conjecture.", query="", bag={})
    assert FormalProofPhase().applies(state) is False and "formal_skipped" in state.bag
    assert FAMOUS_OPEN_PROBLEM_RE.search("Is P vs NP solved?")
    assert not FAMOUS_OPEN_PROBLEM_RE.search("Prove that the square root of 2 is irrational.")
    assert not FAMOUS_OPEN_PROBLEM_RE.search("Prove Fermat's Last Theorem for n = 3.")


def test_a_conjecture_and_a_described_count_are_not_false_contradictions():
    q = "Prove Goldbach's conjecture."
    assert _statuses(r"$$\forall n \text{ even},\ n\ge 4,\ \exists \text{ primes } p,q \text{ such that } n=p+q.$$", q) == []
    assert _statuses(r"$$\text{number of unordered Goldbach partitions of }1000 = 28.$$", q) == []
    assert _statuses(r"$$100 = 3 + 97 = 11 + 89$$", q) == ["passed"]
    assert _statuses(r"$$100 = 3 + 96$$", q) == ["failed"]


# Finite number theory run by code (tribos.writer.number_facts) --------------------------------------------------------
def test_number_facts_are_computed_and_double_checked():
    from tribos.writer.number_facts import compute_number_facts

    d = compute_number_facts("For Collatz: compute the total stopping time and the largest value reached for n = 27, and "
                             "find the starting value below 1000 with the longest stopping time. For Goldbach: list "
                             "every way to write 100 as a sum of two primes, count the ways for 1000, and verify the "
                             "conjecture for every even number from 4 to 10000.")
    values = {p["name"]: p["value"] for p in d["parameters"]}
    assert values["total stopping time of 27"] == "111" and values["largest value reached from 27"] == "9232"
    assert values["start below 1000 with the longest stopping time"] == "871" and values["its total stopping time"] == "178"
    assert values["number of ways to write 100 as a sum of two primes"] == "6"
    assert values["number of ways to write 1000 as a sum of two primes"] == "28"
    assert all(c["passed"] for c in d["checks"]) and len(d["checks"]) == 5
    assert d["partitions"][0]["pairs"][0] == (3, 97) and "remain open" in d["notes"][0]
    assert compute_number_facts("Solve x^2 = 4") is None
    tw = compute_number_facts("How many twin prime pairs are there below 1000, and how many primes below 1000?")
    assert {p["name"]: p["value"] for p in tw["parameters"]}["twin-prime pairs below 1000"] == "35"


def test_number_facts_reach_the_panel_writer_and_item_check():
    from tribos.agents.deliverables import _computed_item_checked
    from tribos.writer.number_facts import compute_number_facts

    d = compute_number_facts("Count the ways to write 1000 as a sum of two primes (Goldbach), and the twin prime pairs "
                             "below 1000.")
    ui = build_answer_ui(d)
    assert [b["type"] for b in ui["blocks"]][:3] == ["stats", "callout", "checks"]
    text = "\n".join(render_computed_results(ToolResult(success=True, tool_name="computed_results", data=d)))
    assert 'value="28"' in text and "instances, not proofs" in text
    assert _computed_item_checked("count the ways for 1000", d, "There are 28 ways to write 1000.")
    assert not _computed_item_checked("count the ways for 1000", d, "There are 29 ways to write 1000.")
    assert _computed_item_checked("twin prime pairs below 1000", d, "There are 35 twin prime pairs below 1000.")


def test_the_open_problem_note_names_the_ranges_verified():
    """Live run: "verified to 100000; Goldbach remains open" was judged unsupported against a note that named no range,
    and the writer said "proved for n < 100000"."""
    from tribos.writer.number_facts import compute_number_facts

    d = compute_number_facts("Find the starting value below 1000 with the longest Collatz stopping time, verify "
                             "Goldbach's conjecture for every even number from 4 to 2000, and count the twin primes "
                             "below 500. Is the twin prime conjecture proven?")
    note = d["notes"][0]
    assert "every Collatz starting value below 1000" in note and "every even number from 4 to 2000" in note
    assert "primes below 500" in note and "remain open, not proved" in note
    text = "\n".join(render_computed_results(ToolResult(success=True, tool_name="computed_results", data=d)))
    assert "never that it was proved" in text and "remain open, not proved" in text


def test_code_checked_number_theory_skips_the_agents_that_would_recompute_it(monkeypatch):
    """Live run: the tool plan (34 s, then a failed reply) and the mathematics agent (26 s) recomputed what code had
    already checked, and the failed plan escalated to a 48 s critic debate."""
    monkeypatch.setenv("TRIBOS_ESCALATE_ON_WEAK_SIGNALS", "1")  # the trigger logic itself is under test
    from types import SimpleNamespace

    from tribos.agentic import math_agent
    from tribos.agentic.math_agent import MathAgentPhase
    from tribos.agentic.plan_execute import PlanExecutePhase
    from tribos.agents.orchestration.presentation import (
        computations_cover_question,
        facts_cover_question,
    )
    from tribos.writer.number_facts import compute_number_facts

    d = compute_number_facts("Give the total stopping time of n = 97 for the Collatz map.")
    results = {"computed_results": ToolResult(success=True, tool_name="computed_results", data=d)}
    assert computations_cover_question(results) and not facts_cover_question(results)
    failed = {**d, "checks": [{"name": "x", "passed": False}]}
    assert not computations_cover_question({"computed_results": ToolResult(success=True, tool_name="computed_results",
                                                                           data=failed)})
    state = SimpleNamespace(tool_results=results, bag={}, options={}, ctx=SimpleNamespace(scope="research"),
                            clean_query="Collatz n = 97", query="Collatz n = 97", framework="auto")
    assert PlanExecutePhase().applies(state) is False and "plan_execute" in state.bag["not_needed_phases"]
    monkeypatch.setattr(math_agent, "math_agent_available", lambda _state: True)
    assert MathAgentPhase().applies(state) is False and "verified twice" in state.bag["math_agent_skipped"]

    # Sub-questions are marked answered after the draft: before it, "open" ones are not missing evidence.
    from tribos.agentic.router import escalation_triggers

    subs = [SimpleNamespace(text="Is the twin prime conjecture proven?", status="open"),
            SimpleNamespace(text="What do the counts above show?", status="open")]
    covered = SimpleNamespace(**vars(state), sub_questions=subs, artifacts={})
    assert not any("lack evidence" in t for t in escalation_triggers(covered))
    uncovered = SimpleNamespace(**{**vars(covered), "tool_results": {}})
    assert any("lack evidence" in t for t in escalation_triggers(uncovered))


def test_the_questions_prohibition_is_not_echoed_as_the_answers_last_sentence():
    """Live run: the answer ended "... infinitely many twin primes. Do not claim a proof that does not exist." """
    from tribos.writer.lint import clean_presentation

    q = "Is the twin prime conjecture proven?\n\nDo not claim a proof that does not exist."
    out = clean_presentation("Open: infinitely many twin primes. Do not claim a proof that does not exist.\n", q)
    assert out == "Open: infinitely many twin primes.\n"
    kept = "We do not claim a proof here.\n\n```\nDo not claim a proof that does not exist.\n```"
    assert clean_presentation(kept, q) == kept


def test_an_answer_cases_definition_checks_each_collatz_step():
    """Live run: C(97) = 3·97 + 1 = 292 and seven more steps stayed inconclusive ("a function not defined yet")
    although the answer defined C with a cases environment."""
    from tribos.verify.math_claims import audit_answer

    md = ("Define the Collatz map\n\n$$\nC(n)=\\begin{cases}\nn/2, & n\\text{ even},\\\\\n3n+1, & n\\text{ odd},\n"
          "\\end{cases}\n$$\n\n$97$ is odd, so $C(97)=3\\cdot 97+1=292$; $292$ is even, so $C(292)=292/2=146$; "
          "$73$ is odd, so $C(73)=73/2=110$.\n")
    claims = {c.text: c for c in audit_answer(md, "Collatz map: total stopping time of n = 97").claims}
    assert claims["C(97)=3\\cdot 97+1=292"].status == "passed"
    assert claims["C(292)=292/2=146"].status == "passed"
    assert claims["C(73)=73/2=110"].status == "failed"


# The 1,000,000-scale live run (Ultra) ------------------------------------------------------------------------------
_MIXED = ("1. How many primes are there below 1000000, and how many twin-prime pairs are there below 50000?\n"
          "2. For the Collatz map, find the starting value below 500000 with the longest total stopping time, its number "
          "of steps and the largest value its orbit reaches. Also give the total stopping time of n = 871.\n"
          "3. Verify Goldbach's conjecture for every even number from 4 to 200000, and give the number of ways to write "
          "200000 as a sum of two primes.\n4. Has the Collatz conjecture been proven? What do these checks show and not "
          "show?\n\nDo not claim a proof that does not exist.")


def test_a_question_naming_no_paper_never_needs_the_paper_tools():
    """Live run: "verify ... has it been proven?" ranked archivon_reproduce_paper among the top tools, which made the
    question "need a specialised tool" and ran a 23 s tool plan beside code that had computed everything."""
    from types import SimpleNamespace

    from tribos.agentic.plan_execute import needs_specialised_tool
    from tribos.tools.registry import get_tool_registry

    state = SimpleNamespace(registry=get_tool_registry(), clean_query=_MIXED, query=_MIXED)
    assert needs_specialised_tool(state) is False


def test_mixed_bounds_and_the_twin_prime_note():
    from tribos.writer.number_facts import compute_number_facts

    d = compute_number_facts(_MIXED)
    values = {p["name"]: p["value"] for p in d["parameters"]}
    assert values["number of primes below 1000000"] == "78498" and values["twin-prime pairs below 50000"] == "705"
    assert values["start below 500000 with the longest stopping time"] == "410011"
    assert values["its total stopping time"] == "448" and values["total stopping time of 871"] == "178"
    assert values["number of ways to write 200000 as a sum of two primes"] == "1417"
    # Twin primes were counted ("twin-prime pairs"): the note names the twin prime conjecture as open as well.
    assert "the twin prime conjecture" in d["notes"][0] and "primes below 50000 (twin primes)" in d["notes"][0]


def test_a_status_sentence_without_a_subject_is_not_checked_against_the_record():
    """Live run: "It has not been proven." matched the code's note through the word "not" and was then judged
    unsupported."""
    from tribos.agents.result_keys import COMPUTED_RESULTS
    from tribos.verify.verifier import TribosVerifier
    from tribos.writer.number_facts import compute_number_facts

    d = compute_number_facts(_MIXED)
    report = TribosVerifier().verify_response(
        _MIXED, "### 4. Has the Collatz conjecture been proven?\n\nStatus: open. It has not been proven.\n",
        {COMPUTED_RESULTS: ToolResult(success=True, tool_name=COMPUTED_RESULTS, data=d)})
    claim = next(c for c in report.claims if c.claim_text.startswith("It has not been proven"))
    assert claim.status == "not_checked"


def test_writer_blocks_that_repeat_the_results_panel_are_removed():
    """Live run: the answer carried a "Verified finite counts" stats card and a "Finite checks are not proofs" callout
    under a panel showing the same values and note."""
    import json

    from tribos.writer.genui import sanitize_ui_blocks
    from tribos.writer.number_facts import compute_number_facts

    d = compute_number_facts(_MIXED)
    panel = build_answer_ui(d)
    stats = {"type": "stats", "title": "Verified finite counts",
             "items": [{"label": "primes < 1000000", "value": "78498"}, {"label": "twin pairs", "value": "705"}]}
    callout = {"type": "callout", "tone": "warning", "title": "Finite checks are not proofs",
               "text": "The universal statements remain open."}
    answer = "There are 78498 primes and 705 twin pairs.\n\n" + "".join(
        f"```ui\n{json.dumps(b)}\n```\n" for b in (stats, callout))
    text, removed = sanitize_ui_blocks(answer, json.dumps(d), panel)
    assert "```ui" not in text and len(removed) == 2
    kept, _ = sanitize_ui_blocks(answer, json.dumps(d))  # without a panel the blocks are the only display
    assert kept.count("```ui") == 2


def test_number_theory_confidence_is_computational_not_literature_support():
    """Live run: "Confidence: low (set by the automatic checks), because each finite count was ... re-checked": the
    literature-support score of the computed values overrode the computation's own basis."""
    from tribos.agentic.confidence import code_computation_confidence
    from tribos.writer.number_facts import compute_number_facts

    art = code_computation_confidence(compute_number_facts(_MIXED))
    assert art["answer_confidence"] is None and art["method"] == "computational_verification"
    assert "second, independent method" in art["calibration"]["note"]


def test_citation_labels_say_each_identifier_once_and_drop_unclassified():
    """Live answer: "[Getachew et al., 2025 | DOI:10.1109/x] (DOI:10.1109/x; unclassified)" showed the identifier twice
    and a label that carries no information."""
    from tribos.writer.lint import clean_presentation

    md = ("It is open [Getachew et al., 2025 | DOI:10.1109/access.2025.3548031] (DOI:10.1109/access.2025.3548031; "
          "unclassified). It is unproven [Bruschi et al., 2023 | arXiv:2303.08141] (arXiv:2303.08141; preprint). "
          "A note (DOI:10.5937/x-1; unclassified, preprint). Math stays $f(x; unclassified)$.")
    out = clean_presentation(md)
    assert "[Getachew et al., 2025 | DOI:10.1109/access.2025.3548031]." in out
    assert "[Bruschi et al., 2023 | arXiv:2303.08141] (preprint)" in out
    assert "(DOI:10.5937/x-1; preprint)" in out and "$f(x; unclassified)$" in out
    assert out.count("unclassified") == 1


def test_a_bare_executive_summary_line_becomes_a_heading():
    from tribos.writer.lint import clean_presentation

    assert clean_presentation("Executive Summary\nThe value is 2.").startswith("### Executive Summary\n")
    assert clean_presentation("**Executive Summary**\nok").startswith("### Executive Summary\n")


# Live runs: the three-body figure-eight, Navier-Stokes status, Vieta descent --------------------------------------
_FIGURE_EIGHT = """Simulate three equal point masses under Newtonian gravity with G = m = 1. Use:

r₁ = (−0.97000436, 0.24308753)
r₂ = ( 0.97000436,−0.24308753)
r₃ = (0,0)

v₁ = v₂ = (0.4662036850, 0.4323657300)
v₃ = (−0.93240737,−0.86473146)

Derive the equations of motion and integrate for five periods, using T ≈ 6.32591398 as the reference period. Report the
trajectories, energy and angular-momentum drift, center-of-mass drift, and return error after one period. Repeat with
tighter integration tolerances or a second method, and explain how the rounded initial conditions affect the result."""


def test_a_fully_stated_three_body_problem_is_parsed_not_questioned():
    """Live run: "A simulation was requested but no equations or named system were given" for the figure-eight."""
    from types import SimpleNamespace

    from tribos.agentic.clarify import names_dynamical_system
    from tribos.writer.nbody_facts import parse_nbody

    spec = parse_nbody(_FIGURE_EIGHT)
    assert spec["ids"] == [1, 2, 3] and spec["G"] == 1.0 and spec["masses"] == [1.0, 1.0, 1.0]
    assert spec["v0"][1].tolist() == [0.466203685, 0.43236573] and spec["n_periods"] == 5
    assert abs(spec["t_end"] - 5 * 6.32591398) < 1e-12
    assert spec["r_decimals"][2] == [0, 0]  # "(0,0)" is exact, never perturbed as rounded
    assert names_dynamical_system(SimpleNamespace(), _FIGURE_EIGHT)
    assert parse_nbody("Simulate the Lorenz system for 50 s.") is None


def test_the_figure_eight_is_integrated_by_two_methods_with_conservation_checks():
    from tribos.agents.orchestration.presentation import computations_cover_question
    from tribos.writer.nbody_facts import compute_nbody_facts

    d = compute_nbody_facts(_FIGURE_EIGHT)
    values = {p["name"]: p["value"] for p in d["parameters"]}
    assert values["total energy E0"].startswith("-1.28714199")  # the figure-eight's known energy
    assert values["angular momentum L0"] == "0"
    assert all(c["passed"] for c in d["checks"]) and len(d["checks"]) == 5
    assert len(d["returns"]) == 5 and d["returns"][0]["position_error"] < 1e-6
    assert d["returns"][0]["rel_energy_error"] < 1e-11
    assert "rounded initial conditions" in d["notes"][0]
    ui = build_answer_ui(d)
    kinds = [b["type"] for b in ui["blocks"]]
    assert kinds[:3] == ["stats", "equation", "chart"] and ui["blocks"][2]["parametric"] is True
    assert len(ui["blocks"][2]["series"]) == 3
    text = "\n".join(render_computed_results(ToolResult(success=True, tool_name="computed_results", data=d)))
    assert "<equations_of_motion>" in text and "<return_after_period k=\"1\"" in text
    assert computations_cover_question({"computed_results": ToolResult(success=True, tool_name="computed_results",
                                                                      data=d)})


def test_a_forbidden_claim_about_a_simulation_is_not_a_simulation_request():
    """Live run (Navier-Stokes status): "Do not claim a proof or imply that a numerical simulation settles the
    theorem" made the run report "Requested time course; ran nothing"."""
    from tribos.agents.query_planner import _requests_simulation

    assert not _requests_simulation("Do not claim a proof or imply that a numerical simulation settles the theorem.")
    assert _requests_simulation("Do not claim anything; simulate the Lorenz system for 50 s.")
    assert _requests_simulation("Simulate three equal point masses under Newtonian gravity.")


def test_one_value_of_a_disjunction_does_not_bind_the_variable():
    """Live run (Markov equation): "so $z = 1$ or $2$ ... $z = 2$" was flagged contradicted: z evaluates to 1."""
    from tribos.verify.math_claims import audit_answer

    q = "Find and prove all positive integer solutions (x,y,z) to x^2 + y^2 + z^2 = 3xyz."
    md = r"(1) becomes $2 + z^2 = 3z$, so $z = 1$ or $2$. Since $z > 1$, $z = 2$."
    assert not [c for c in audit_answer(md, q).claims if c.status == "failed"]
    wrong = audit_answer(r"Let $a = 3$. Then $a^2 = 9$ and $a = 4$.", q).claims
    assert [c.text for c in wrong if c.status == "failed"] == ["a=4"]


# Live run: the Motzkin polynomial -----------------------------------------------------------------------------------
_MOTZKIN = """Classify the task, give a short plan, and state assumptions. For numerical work, run real Python and report its
outputs. Show the key equations, verify the result independently, and keep the answer focused.

Analyze the Motzkin polynomial

M(x,y) = x⁴y² + x²y⁴ + 1 − 3x²y².

Prove that M(x,y) ≥ 0 for all real x,y and find every equality case. Then determine whether M can be written as a sum
of squares of real polynomials. Give a rigorous proof of your conclusion; numerical sampling alone is not sufficient."""


def test_the_motzkin_polynomial_is_analysed_by_python_with_a_newton_polytope_certificate():
    """Live run: "run real Python and report its outputs" ran no code (0 tool calls; the item was "missing")."""
    from tribos.agents.orchestration.presentation import computations_cover_question
    from tribos.writer.poly_facts import compute_poly_facts

    d = compute_poly_facts(_MOTZKIN)
    values = {p["name"]: p["value"] for p in d["parameters"]}
    assert values["points where the minimum is attained (exact)"] == "(-1, -1), (-1, 1), (1, -1), (1, 1)"
    assert values["smallest value of M found (sampling and minimisation)"] == "0"
    assert values["lattice points of the half Newton polytope"] == "(0, 0), (1, 1), (1, 2), (2, 1)"
    assert values["sum-of-squares test"].startswith("not a sum of squares")
    assert d["certificate"]["coefficient"] == "-3" and d["certificate"]["only_from"] == "x y"
    assert all(c["passed"] for c in d["checks"])
    assert computations_cover_question({"computed_results": ToolResult(success=True, tool_name="computed_results",
                                                                      data=d)})
    ui = build_answer_ui(d)
    assert [b["type"] for b in ui["blocks"]][:3] == ["stats", "equation", "chart"]
    # A polynomial that is a sum of squares gets no certificate and says the test did not decide it.
    sos = compute_poly_facts("Is P(x,y) = x^2 - 2xy + y^2 + 1 nonnegative, and is it a sum of squares?")
    # A polynomial that is a sum of squares gets an exact certificate (SDP, rational rounding, symbolic identity check).
    assert sos["certificate"] is None and sos["sos_decomposition"] is not None
    assert {p["name"]: p["value"] for p in sos["parameters"]}["sum-of-squares test"].startswith("a sum of squares")
    challenge = compute_poly_facts("Show that P(x,y) = x^4 + x^2y^2 - 2x^2y + y^4 + 1 is a sum of squares.")
    assert challenge["sos_decomposition"] is not None and all(c["passed"] for c in challenge["checks"])


def test_the_motzkin_preamble_yields_real_deliverables_only():
    """Live run: "keep the answer focused" was a "not addressed" item and M(x,y) was split at its comma."""
    from tribos.agents.deliverables import _computed_item_checked, requested_items
    from tribos.writer.poly_facts import compute_poly_facts

    items = [i["item"] for i in requested_items(_MOTZKIN)]
    assert "keep the answer focused" not in items and "result independently" not in items
    assert any(i.startswith("Motzkin polynomial M(x,y) = ") for i in items)
    assert not any(i.startswith("y)") for i in items)
    d = compute_poly_facts(_MOTZKIN)
    # The live answer's own wording: its notation differs from the code's, its numbers do not.
    reported = (r"Grid sampling over $[-3,3]^2$ with NumPy, $801^2$ points: smallest value $7.46\times 10^{-5}$. "
                r"Multi-start minimisation with SciPy BFGS, 160 starts.")
    assert _computed_item_checked("outputs", d, reported)
    assert not _computed_item_checked("outputs", d, "Python found the minimisers (-1, -1) and (1, 1).")


def test_a_question_over_the_reals_is_not_sent_to_core_lean():
    """Live run: three Lean attempts (86 s) for "for all real x,y" with no Mathlib, none with a theorem statement."""
    from tribos.verify.formal.correspondence import needs_library

    assert needs_library("Prove that M(x,y) >= 0 for all real x,y.") == "real numbers"
    assert needs_library("Is M a sum of squares of real polynomials?") == "real numbers"
    assert needs_library("Prove there are infinitely many primes.") is None


def test_an_explicit_request_to_run_python_is_recognised():
    from tribos.agents.query_planner import PYTHON_REQUEST_RE

    assert PYTHON_REQUEST_RE.search("For numerical work, run real Python and report its outputs.")
    assert PYTHON_REQUEST_RE.search("Write and run a Python script to sample the function.")
    assert not PYTHON_REQUEST_RE.search("Prove that the polynomial is nonnegative.")


# Live run: real roots of x^5 - 5x + 1 --------------------------------------------------------------------------------
_QUINTIC = """Classify the task, give a short plan, and state assumptions. For numerical work, run real Python and report its
outputs. Show the key equations, verify the result independently, and keep the answer focused.

Find every real root of p(x) = x⁵ − 5x + 1 to at least 12 significant digits.

Prove how many real roots exist using an exact Sturm sequence with rational arithmetic. Give disjoint rational intervals
of width at most 10⁻¹⁰, each containing exactly one root, and verify the reported decimal approximations and residuals."""


def test_real_roots_are_counted_and_isolated_exactly_in_python():
    """Live run: the tool plan (94 s, two scripts failing) and the mathematics agent (68 s) did what exact rational
    arithmetic does in a fraction of a second, and the roots item was reported "not addressed"."""
    from tribos.agents.deliverables import _computed_item_checked
    from tribos.agents.orchestration.presentation import computations_cover_question
    from tribos.writer.roots_facts import compute_roots_facts

    d = compute_roots_facts(_QUINTIC)
    assert d["sturm_latex"] == ["x^{5} - 5 x + 1", "5 x^{4} - 5", "4 x - 1", r"\frac{1275}{256}"]
    assert d["signs_minus_inf"] == [-1, 1, -1, 1] and d["signs_plus_inf"] == [1, 1, 1, 1] and d["count"] == 3
    assert d["digits"] == 12 and d["width"] == "1/10000000000"
    assert [r["root"] for r in d["roots"]] == ["-1.54165168410", "0.200064102630", "1.44050039734"]
    assert all(r["sign_a"] * r["sign_b"] < 0 for r in d["roots"]) and all(c["passed"] for c in d["checks"])
    assert computations_cover_question({"computed_results": ToolResult(success=True, tool_name="computed_results",
                                                                      data=d)})
    item = "every real root of p(x) = x⁵ − 5x + 1 to at least 12 significant digits"
    reported = r"$r_1 \approx -1.54165168410452$, $r_2 \approx 0.200064102629975$, $r_3 \approx 1.44050039734156$"
    assert _computed_item_checked(item, d, reported)
    assert not _computed_item_checked(item, d, r"$r_1 \approx -1.5416$")
    assert [b["type"] for b in build_answer_ui(d)["blocks"]][:3] == ["stats", "equation", "table"]


def test_a_script_reading_inputs_gets_the_results_it_depends_on():
    """Live run: "for s in inputs['roots']" stopped with NameError because the planner passed no `inputs`."""
    from types import SimpleNamespace

    from tribos.agentic.executor import PlanExecutor

    ex = PlanExecutor.__new__(PlanExecutor)
    ex.results = {"n3": SimpleNamespace(data={"result": {"roots": ["-1.54", "0.20", "1.44"]}})}
    node = SimpleNamespace(tool="calcula_run_python", depends_on=["n3"])
    wired = ex._wire_script_inputs(node, {"code": "approx = [float(s) for s in inputs['roots']]"})
    assert wired["inputs"]["roots"] == ["-1.54", "0.20", "1.44"] and wired["inputs"]["n3"]["roots"]
    given = {"code": "x = inputs['a']", "inputs": {"a": 1}}
    assert ex._wire_script_inputs(node, given) is given  # an explicit argument is kept
    assert "inputs" not in ex._wire_script_inputs(node, {"code": "result = 1"})


def test_debate_escalates_only_on_a_concrete_conflict_by_default():
    """Matched-compute studies find debate rarely beats self-consistency; the weak signals no longer cost a debate."""
    from types import SimpleNamespace

    from tribos.agentic.router import escalation_triggers

    weak = SimpleNamespace(ctx=SimpleNamespace(scope="research"), bag={"routing": {"confidence": 0.1}}, artifacts={},
                           sub_questions=[SimpleNamespace(text="Which papers?", status="open")] * 3, tool_results={})
    assert escalation_triggers(weak) == []
    conflict = SimpleNamespace(**{**vars(weak), "artifacts": {"evidence_conflicts": {"conflicts": [
        {"label": "contradicts", "classifier": "nli"}]}}})
    assert any("contradicting" in t for t in escalation_triggers(conflict))


def test_stated_and_named_systems_are_integrated_with_invariants():
    """Plan item 3: Robertson (stiff, mass conserved), Lorenz (chaotic) and a stated linear system run by code."""
    from tribos.writer.system_facts import compute_system_facts

    rob = compute_system_facts("Integrate the Robertson stiff chemistry problem to t = 1e11 and check mass conservation.")
    assert rob["stiff"] and [i["label"] for i in rob["invariants"]] == ["y1 + y2 + y3"]
    assert all(c["passed"] for c in rob["checks"]) and rob["invariants"][0]["max_drift"] < 1e-10
    lin = compute_system_facts("Simulate dx/dt = -2x + y, dy/dt = x - 3y with x(0) = 1, y(0) = 0 until t = 5.")
    assert not lin["stiff"] and all(c["passed"] for c in lin["checks"])
    assert [b["type"] for b in build_answer_ui(lin)["blocks"]][:4] == ["stats", "equation", "chart", "chart"]
    assert compute_system_facts("Solve x'' + x = 0 with x(0)=1, x'(0)=0.") is None  # one unknown: the ODE module


def test_roots_are_certified_by_ball_arithmetic_and_sos_certificates_are_exact():
    """Plan items 5 and 7: every reported root digit proved with python-flint; an SOS polynomial gets a certificate."""
    import sympy as sp

    from tribos.writer.poly_facts import compute_poly_facts
    from tribos.writer.roots_facts import compute_roots_facts

    w = compute_roots_facts("Isolate the real roots of W(x) = (x-1)(x-2)(x-3)(x-4)(x-5)(x-6)(x-7)(x-8)(x-9)(x-10)"
                            "(x-11)(x-12)(x-13)(x-14)(x-15)(x-16)(x-17)(x-18)(x-19)(x-20) to 30 significant digits.")
    assert w["count"] == 20 and all(c["passed"] for c in w["checks"])
    assert any("certified by ball arithmetic" in c["name"] for c in w["checks"])
    p = compute_poly_facts("Is Q(x,y) = x^2 - 2xy + 2y^2 nonnegative, and is it a sum of squares?")
    x, y = sp.symbols("x y")
    total = sum(sp.Rational(d) * sp.sympify(l, locals={"x": x, "y": y}) ** 2 for d, l in p["sos_decomposition"]["terms"])
    assert sp.expand(total - (x**2 - 2*x*y + 2*y**2)) == 0


def test_the_heat_equation_converges_at_its_design_order():
    """Plan item 10: manufactured solution, Crank-Nicolson and FTCS on five grids, observed order 2."""
    from tribos.agents.orchestration.presentation import computations_cover_question
    from tribos.writer.pde_facts import compute_pde_facts

    d = compute_pde_facts("Solve u_t = u_xx on [0, 1] with u = sin(πx), and show second-order convergence.")
    assert abs(d["refinement"][-1]["cn_order"] - 2.0) < 0.05 and all(c["passed"] for c in d["checks"])
    assert [b["type"] for b in build_answer_ui(d)["blocks"]] == ["stats", "equation", "chart", "chart", "table", "checks"]
    assert computations_cover_question({"computed_results": ToolResult(success=True, tool_name="computed_results",
                                                                      data=d)})
    text = "\n".join(render_computed_results(ToolResult(success=True, tool_name="computed_results", data=d)))
    assert "<exact_solution>" in text and 'intervals="160"' in text


def test_best_of_n_keeps_the_draft_with_fewest_false_statements(monkeypatch):
    """Plan item 4: a draft with a false statement is replaced by an audited alternative with none."""
    import asyncio
    from types import SimpleNamespace

    from tribos.agents.orchestration import best_of_n as bon

    sent, events = [], []

    async def send(msg):
        sent.append(msg)

    async def emit(*a, **k):
        events.append(a)

    good = r"Since $2 + 2 = 4$ and $3 \cdot 3 = 9$, the claim holds."
    reply = SimpleNamespace(content=good)

    class Llm:
        async def ainvoke(self, _messages):
            return reply

    from tribos.agents.orchestration import llm_call

    fake = SimpleNamespace(get_llm=lambda **k: Llm(), _edit_llm_kwargs=lambda m: {})
    monkeypatch.setattr(bon, "orchestrator_module", lambda: fake)
    monkeypatch.setattr(llm_call, "orchestrator_module", lambda: fake)
    run = SimpleNamespace(candidate_response="Since $2 + 2 = 5$, the claim holds.", llm_ok=True, synthesis_prompt="p",
                          system_prompt="s", synthesis_model="m", model_name="m", api_key=None, tool_results={},
                          clean_query="2+2?", resolved_query="", query="", agent_options={"effort_level": "medium"},
                          agent_state=None, execution_artifacts={}, streamed_draft="", send=send, emit=emit)
    asyncio.run(bon.best_of_n(run))
    # One false statement: the reviser fixes it, so no alternative drafts are written (Aletheia's minor-fix path).
    assert run.candidate_response == good and run.execution_artifacts["best_of_n"]["replaced"] is True
    assert run.execution_artifacts["best_of_n"]["mode"] == "revised" and run.execution_artifacts["best_of_n"]["candidates"] == 2
    assert run.execution_artifacts["best_of_n"]["kept"]["failed"] == 0 and sent[0]["type"] == "content_reset"
    # Many false statements: alternatives are drafted and the best one kept.
    many = "Since $2 + 2 = 5$, $3 + 3 = 7$ and $4 + 4 = 9$, the claim holds."
    run3 = SimpleNamespace(**{**vars(run), "candidate_response": many, "execution_artifacts": {}})
    asyncio.run(bon.best_of_n(run3))
    assert run3.execution_artifacts["best_of_n"]["mode"] == "best_of_n" and run3.candidate_response == good
    # A draft with no false statement is left alone and costs nothing.
    run2 = SimpleNamespace(**{**vars(run), "candidate_response": good, "execution_artifacts": {}})
    asyncio.run(bon.best_of_n(run2))
    assert run2.execution_artifacts == {}


def test_the_damped_double_pendulum_balances_energy_and_damping_work():
    """Challenge 3: equations derived from the Lagrangian; energy loss equals the damping work."""
    from tribos.writer.system_facts import compute_system_facts

    d = compute_system_facts("Simulate a damped double pendulum (m = 1, l = 1, b = 0.1) from θ = (π/2, π/2) for 20 s; "
                             "report energy loss against the damping work.")
    values = {p["name"]: p["value"] for p in d["parameters"]}
    assert values["initial mechanical energy E(0)"] == "0"
    assert abs(float(values["energy lost over 20 s"]) - float(values["work done by damping"])) < 1e-6
    assert all(c["passed"] for c in d["checks"])


def test_archivon_reads_full_text_paragraphs_of_arxiv_papers(monkeypatch):
    """Plan item 9: body paragraphs of an arXiv paper become "Full text" passages, most relevant first."""
    import asyncio

    import httpx

    from tribos.archivon.engine import ArchivonEngine

    monkeypatch.setenv("TRIBOS_ARCHIVON_FULLTEXT", "1")
    filler = " and further discussion of the setting" * 6
    html = ("<html><body><section><p>The blow-up criterion for Navier-Stokes solutions is shown here" + filler
            + ".</p><p>Unrelated acknowledgements paragraph" + " thanking colleagues" * 12 + ".</p></section></body></html>")

    def handler(request):
        assert request.url.host == "arxiv.org" and request.url.path == "/html/2401.00001"
        return httpx.Response(200, text=html, headers={"content-type": "text/html"})

    engine = ArchivonEngine(transport=httpx.MockTransport(handler), check_integrity=False)
    passages = [{"arxiv_id": "2401.00001", "passage_id": "p1", "score": 1.0}, {"passage_id": "p2"}]
    out = asyncio.run(engine._full_text_passages(passages, ["navier", "stokes", "blow-up"]))
    assert len(out) == 1 and out[0]["section"] == "Full text" and "blow-up criterion" in out[0]["passage_text"]
    monkeypatch.setenv("TRIBOS_ARCHIVON_FULLTEXT", "0")
    assert asyncio.run(engine._full_text_passages(passages, ["navier"])) == []


def test_lean_kernel_audit_rejects_native_decide_and_unsafe_escapes():
    """Plan item 6: a proof that leans on the compiler or an unsafe escape is not a kernel-checked proof."""
    from tribos.verify.formal.runner import uses_unproved

    assert uses_unproved("theorem t : 2 + 2 = 4 := by native_decide")
    assert uses_unproved("@[implemented_by foo] def bar : Nat := 0")
    assert uses_unproved("unsafe def f : Nat := 0")
    assert not uses_unproved("theorem t : 2 + 2 = 4 := by decide")


def test_claims_export_writes_unlabelled_rows_once_per_claim(tmp_path):
    """Plan item 8: saved runs export to rows a person labels for calibrate_confidence.py."""
    import importlib.util
    import json

    spec = importlib.util.spec_from_file_location("export_claims", "scripts/export_claims_for_labelling.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    claim = {"text": "x = 2", "claim_type": "numeric", "features": {"support": 1.0}}
    result = {"run_id": "r1", "query": "q", "response": "a",
              "execution_artifacts": {"claim_confidence": {"claims": [claim, claim, {"text": "no features"}]}}}
    src = tmp_path / "run.json"
    src.write_text(json.dumps({"type": "done", "result": result}), encoding="utf-8")
    out = tmp_path / "claims.jsonl"
    assert mod.main([str(src), "--out", str(out)]) == 0
    rows = [json.loads(line) for line in out.read_text(encoding="utf-8").splitlines()]
    assert len(rows) == 1 and rows[0]["label"] is None and rows[0]["answer_id"] == "r1"


def test_a_permitted_simulation_is_not_a_required_one():
    """"Use numerical simulation only to explore examples" permits a run; none running is not a failed request."""
    from tribos.agents.query_planner import _requests_simulation

    assert not _requests_simulation("Use Python or numerical simulation only to explore examples or test conjectures.")
    assert not _requests_simulation("Use a numerical simulation if helpful.")
    assert _requests_simulation("Simulate the Lorenz system only for 10 s.")
    assert _requests_simulation("Run a simulation of the damped oscillator.")


def test_dynamis_reports_finite_time_blow_up_instead_of_failing():
    """y' = y^3 from y(0) = 1 blows up at t = 1/2: the singularity is the result, not a solver failure."""
    from tribos.dynamis.engine import dynamis_simulate_ode

    r = dynamis_simulate_ode(rhs={"y": "y**3"}, initial_state={"y": 1.0}, t_span=(0, 2))
    assert abs(r["blow_up"]["t_blow_up_estimate"] - 0.5) < 1e-6 and r["t_span"][1] < 0.5
    assert "blow_up" not in dynamis_simulate_ode(rhs={"y": "-y"}, initial_state={"y": 1.0}, t_span=(0, 2))


def test_a_dimension_label_is_not_a_math_expression():
    """"the 3D Navier-Stokes problem" must not become the expression 3*D for the math agent."""
    from tribos.axiom.problem import parse_problem

    assert not parse_problem("Locate the supercritical gap and limit steps in the 3D Navier-Stokes problem").parsed
    assert parse_problem("Find the derivative of x^3 + 2x").expression == "x^3 + 2x"
