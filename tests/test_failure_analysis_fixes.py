"""Fixes from the 2026-11-06 benchmark failure analysis (docs/benchmarks/2026-11-06-failure-analysis.md).

Each test pins a general behaviour behind one class of failure, written with its own wording rather than a benchmark
item's: field conventions, the evidence gate's reading of incidental words, multiple-choice detection, the simulation
request reader, and the independent cross-check of an answer.
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from tribos.agents.conventions import conventions_for
from tribos.agents.evidence_need import assess_evidence_need
from tribos.agents.orchestration import cross_check as cc
from tribos.agents.query_planner import _requests_simulation
from tribos.agents.question_text import is_choice_question, is_multiple_choice, option_texts


def _keys(q: str) -> list[str]:
    return [c.key for c in conventions_for(q)]


# --- field conventions -------------------------------------------------------------------------------------------

@pytest.mark.parametrize(("question", "key"), [
    ("In how many ways can 6 people be split into 3 non-empty ordered subsets?", "lah_ordered_subsets"),
    ("A 6% coupon bond maturing in 12 years yields 7%. What is the bond's price?", "bond_pricing"),
    ("A European put with strike 40 and three months to expiry costs 2; the three-month risk-free rate is 4%. "
     "Use put-call parity to price the call.", "annualised_term_rates"),
    ("Assume all gases are perfect. 10 g of zinc reacts with dilute acid at 1 atm and 298 K. Calculate the work done "
     "by the system.", "chemistry_work_sign"),
    ("A 1 MB object is fetched over TCP with slow start; the link is 100 Mbps and the RTT is 30 ms. How long does "
     "the transfer take?", "tcp_transfer_latency"),
])
def test_conventions_fire_on_their_field_wording(question: str, key: str) -> None:
    assert key in _keys(question)


@pytest.mark.parametrize("question", [
    "2.0 mol of an ideal gas expands isothermally at 300 K from 1 L to 3 L. How much work is done by the gas?",
    "A zero-coupon bond with face value 1000 matures in 5 years at a 6% yield. What is its price?",
    "A 5% bond pays annual coupons and matures in 8 years; its yield is 6%. Find its price.",
    "How many ordered pairs of subsets (A, B) of a 5-element set are there?",
    "A call option is priced with a monthly rate of 1% per month for two months.",
    "What is the expected number of fixed points of a random permutation of 10 elements?",
])
def test_conventions_stay_silent_outside_their_field(question: str) -> None:
    assert _keys(question) == []


def test_convention_notes_never_carry_a_benchmark_answer() -> None:
    from tribos.agents.conventions import CONVENTIONS

    text = " ".join(c.note for c in CONVENTIONS)
    for value in ("240", "91.17", "2.92", "344", "-1.5"):
        assert value not in text


# --- the evidence gate: incidental words in a problem's story ----------------------------------------------------

@pytest.mark.parametrize("question", [
    "A survey of 200 students found 120 like tea and 90 like coffee; 40 like both. How many like neither?",
    "The window W is adjusted according to TCP Reno. A 400 KB file is sent over a 10 Mbps link with a 30 ms RTT and "
    "20 KB segments. How long (in ms) does the transfer take?",
    "Smith and Jones published tables from which the coefficient is 0.25 K/bar. Compute the temperature change for "
    "a 3.0 bar drop. (Express the final numerical answer in K.)",
    "A recent graduate borrows $50,000 at 6% and pays $600 a month. When will the loan be paid off?",
    "In 1976 a sample was thought to contain element 126. What is the most probable radius of its 1s electron? "
    "(Express the final numerical answer in pm.)",
])
def test_story_words_in_a_closed_problem_do_not_require_sources(question: str) -> None:
    assert assess_evidence_need(question).level != "required"


@pytest.mark.parametrize("question", [
    "What are the latest results on perovskite stability? Cite papers.",
    "Give references for the Joule-Thomson coefficient of R-134a.",
    "As of 2026, what is the record efficiency of a perovskite solar cell?",
    "Summarize recent work on twisted bilayer graphene.",
    "Who first proved the prime number theorem?",
])
def test_explicit_source_and_time_requests_still_require_retrieval(question: str) -> None:
    assert assess_evidence_need(question).level == "required"


def test_data_size_units_count_as_given_quantities() -> None:
    q = "A 2 MB file is sent over a 50 Mbps link in 64 KB segments. How long does it take?"
    assert assess_evidence_need(q).level == "none"


# --- multiple choice and the simulation request reader ------------------------------------------------------------

_CHOICE = ("Compound A reacts to form compound B. B is heated to give D. Identify compound D.\n\nAnswer choices:\n"
           "(A) ethanol\n(B) ethene\n(C) ethyne\n(D) ethane\n\nChoose the single correct option.")
_SUBTASKS = ("Consider the Lorenz system with sigma = 10, rho = 28, beta = 8/3. (a) Simulate it for 20 s from (1, 1, 1). "
             "(b) Plot x(t). (c) Report the largest value of x.")


def test_letters_in_the_stem_are_not_options() -> None:
    assert is_multiple_choice(_CHOICE)
    assert [o[:3] for o in option_texts(_CHOICE)] == ["(A)", "(B)", "(C)", "(D)"]


def test_choose_one_questions_are_told_apart_from_lettered_subtasks() -> None:
    assert is_choice_question(_CHOICE)
    assert is_choice_question("What is 2 + 2?\n(a) 3\n(b) 4\n(c) 5")
    assert is_multiple_choice(_SUBTASKS) and not is_choice_question(_SUBTASKS)


def test_an_option_that_mentions_simulation_is_not_a_request() -> None:
    q = ("Which step matters most before docking a flexible ligand?\n\nAnswer choices:\n(A) Enumerate its tautomers\n"
         "(B) Run molecular dynamics simulations of its ADME behaviour\n(C) Measure its melting point\n"
         "(D) None of these\n\nChoose the single correct option.")
    assert not _requests_simulation(q)


def test_a_lettered_simulation_task_is_still_a_request() -> None:
    assert _requests_simulation(_SUBTASKS)


# --- the independent cross-check: comparing answers ----------------------------------------------------------------

def test_final_answer_reads_the_last_final_line() -> None:
    assert cc.final_answer("work...\nFINAL: 12 m/s\nmore\n**FINAL:** 13.2 m/s") == "13.2 m/s"
    assert cc.final_answer("no marker") == ""


@pytest.mark.parametrize(("final", "draft", "mc", "expected"), [
    ("13.2 m/s", "The minimum speed is $13.2\\ \\mathrm{m\\,s^{-1}}$.", False, True),
    ("13.2 m/s", "The minimum speed is $17.6\\ \\mathrm{m\\,s^{-1}}$.", False, False),
    ("-1.53 kJ", "$w = -1.53\\times 10^{3}$ J of work.", False, True),
    ("-\\frac{4\\sqrt{3}}{9}", "At $t=\\pi/3$ the value is $-4\\sqrt3/9 \\approx -0.770$.", False, True),
    ("71/12", "The trace is $71/12$.", False, True),
    ("15.5%", "About 15.5% of the light emerges.", False, True),
    ("[2, 6, 10]", "The path is [2, 6, 10].", False, True),
    ("[2, 8, 10]", "The path is [2, 6, 10].", False, False),
    ("C", "(C) the larger one.\n\nAnswer: C", True, True),
    ("D", "(C) the larger one.\n\nAnswer: C", True, False),
    ("B", "The product is the endo adduct, option (B).", True, True),
    ("True", "False. Equality is possible.", False, False),
    ("yes", "Yes, it holds.", False, True),
    ("an expression in x", "Anything.", False, None),
])
def test_agrees(final: str, draft: str, mc: bool, expected: bool | None) -> None:
    assert cc.agrees(final, draft, multiple_choice=mc) is expected


@pytest.mark.parametrize(("final", "draft", "expected"), [
    (r"\sqrt{51}", r"The distance is $\sqrt{51}$.", True),
    (r"7.1414", r"The distance is $\sqrt{51}$.", True),
    (r"\frac{8}{15}", r"So $\cos\theta = \frac{8}{15}$.", True),
    (r"\sqrt{50}", r"The distance is $\sqrt{51}$.", False),
    (r"2\sqrt2\sin(\pi/(2\sqrt2))", r"The length is $2\sqrt{2}\sin\!\left(\frac{\pi}{2\sqrt{2}}\right) \approx 2.534$.", True),
])
def test_equivalent_forms_agree_without_adjudication(final: str, draft: str, expected: bool) -> None:
    assert cc.agrees(final, draft, multiple_choice=False) is expected


def test_adjudication_puts_the_burden_of_proof_on_changing_the_draft() -> None:
    prompt = cc._ADJUDICATE_PROMPT
    assert "Solution A stands unless you identify a concrete error" in prompt
    assert "not refuted by a technicality" in prompt and "not refuted by a technicality" in cc._SOLVE_PROMPT


def test_the_article_a_is_not_read_as_option_a() -> None:
    assert cc._draft_option("The answer is a function of the load.\n\nAnswer: C") == "C"
    assert cc._draft_option("The answer is a function of the load.") == ""


# --- the independent cross-check: the stage ----------------------------------------------------------------------

def _run(draft: str, question: str = "A ball is thrown up at 10 m/s. How long (in s) is it in the air?"):
    events: list[tuple] = []

    async def emit(*args, **kwargs):
        events.append(("emit", args, kwargs))

    async def send(msg):
        events.append(("send", msg))

    need = SimpleNamespace(level="none", kind="self_contained")
    run = SimpleNamespace(
        clean_query=question, resolved_query=None, query=question, candidate_response=draft, streamed_draft=draft,
        llm_ok=True, agent_options={}, tool_results={}, ctx=SimpleNamespace(evidence_need=need), execution_artifacts={},
        emit=emit, send=send, system_prompt="sys", synthesis_prompt="prompt", synthesis_model="m", agent_state=None)
    return run, events


def _fake_ask(monkeypatch: pytest.MonkeyPatch, replies: list[str]) -> list[str]:
    from tribos.agents.orchestration import llm_call

    monkeypatch.setenv("TRIBOS_CROSS_CHECK", "1")  # off by default; these tests exercise the stage itself
    prompts: list[str] = []

    async def ask(run, system, messages, **kwargs):
        prompts.append(messages if isinstance(messages, str) else messages[-1][1])
        return replies.pop(0)

    monkeypatch.setattr(llm_call, "ask", ask)
    return prompts


def test_agreement_leaves_the_draft_alone(monkeypatch: pytest.MonkeyPatch) -> None:
    run, _ = _run("The ball is in the air for 2.04 s.")
    prompts = _fake_ask(monkeypatch, ["t = 2v/g\nFINAL: 2.04 s"])
    asyncio.run(cc.cross_check(run))
    assert len(prompts) == 1 and run.candidate_response == "The ball is in the air for 2.04 s."
    assert run.execution_artifacts["cross_check"]["status"] == "agreed"
    assert "the draft" not in prompts[0].lower()  # the second solution never sees the draft


def test_disagreement_adjudicated_against_the_draft_rewrites_it(monkeypatch: pytest.MonkeyPatch) -> None:
    run, events = _run("The ball is in the air for 1.02 s.")
    prompts = _fake_ask(monkeypatch, [
        "FINAL: 2.04 s",
        "A used only the rise time.\nWINNER: B\nFINAL: 2.04 s",
        "The ball is in the air for 2.04 s: up and back down."])
    asyncio.run(cc.cross_check(run))
    assert len(prompts) == 3
    assert run.candidate_response.startswith("The ball is in the air for 2.04 s")
    assert run.execution_artifacts["cross_check"]["status"] == "corrected"
    assert ("send", {"type": "content_reset", "reason": "cross_check"}) in events


def test_adjudication_for_the_draft_keeps_it(monkeypatch: pytest.MonkeyPatch) -> None:
    run, _ = _run("The ball is in the air for 2.04 s.")
    _fake_ask(monkeypatch, ["FINAL: 1.02 s", "B used the rise time only.\nWINNER: A\nFINAL: 2.04 s"])
    asyncio.run(cc.cross_check(run))
    assert run.candidate_response == "The ball is in the air for 2.04 s."
    assert run.execution_artifacts["cross_check"]["status"] == "draft_kept"


def test_a_rewrite_that_misses_the_adjudicated_answer_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    run, _ = _run("The ball is in the air for 1.02 s.")
    _fake_ask(monkeypatch, ["FINAL: 2.04 s", "WINNER: B\nFINAL: 2.04 s", "The ball is in the air for 3.3 s."])
    asyncio.run(cc.cross_check(run))
    assert run.candidate_response == "The ball is in the air for 1.02 s."
    assert run.execution_artifacts["cross_check"]["status"] == "rewrite_rejected"


def test_cross_check_skips_open_questions_and_code_computed_answers(monkeypatch: pytest.MonkeyPatch) -> None:
    prompts = _fake_ask(monkeypatch, [])
    run, _ = _run("Graphene is promising.", question="Why is graphene interesting for batteries?")
    run.ctx.evidence_need = SimpleNamespace(level="optional", kind="open")
    asyncio.run(cc.cross_check(run))
    run2, _ = _run("The answer is 4.")
    run2.agent_options = {"effort_level": "low"}
    asyncio.run(cc.cross_check(run2))
    assert prompts == [] and "cross_check" not in run.execution_artifacts


def test_cross_check_can_be_switched_off(monkeypatch: pytest.MonkeyPatch) -> None:
    prompts = _fake_ask(monkeypatch, [])
    monkeypatch.setenv("TRIBOS_CROSS_CHECK", "0")
    run, _ = _run("The ball is in the air for 1.02 s.")
    asyncio.run(cc.cross_check(run))
    assert prompts == []


def test_cross_check_is_off_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    # Measured on the 2026-11-06 benchmark: 4 answers changed, all from right to wrong, none fixed.
    prompts = _fake_ask(monkeypatch, [])
    monkeypatch.delenv("TRIBOS_CROSS_CHECK", raising=False)
    run, _ = _run("The ball is in the air for 1.02 s.")
    asyncio.run(cc.cross_check(run))
    assert prompts == [] and "cross_check" not in run.execution_artifacts


# --- the claim auditor: no false contradictions -------------------------------------------------------------------

def test_a_congruence_chain_is_read_modulo_n() -> None:
    from tribos.verify.math_claims import audit_answer

    assert not audit_answer(r"So $-1234 \equiv -10 \equiv 8 \pmod{18}$.", "Find -1234 mod 18.").failed
    assert audit_answer(r"So $17 \equiv 4 \equiv 9 \pmod{13}$.", "Reduce 17 mod 13.").failed


def test_a_unitless_side_in_the_stated_unit_is_not_a_contradiction() -> None:
    from tribos.verify.math_claims import audit_answer

    q = "A 340 KB file is sent in 20 KB segments over a 10 Mbps link. How long does transmission take?"
    assert not audit_answer(r"The transmission time is $O/R = 17 \times 16 + 8 = 280\,\mathrm{ms}$.", q).failed
    # Both sides with their units: compared as written.
    assert audit_answer(r"$1\,\mathrm{mm}=1\,\mathrm m$", "Check unit conversions.").failed


def test_values_given_in_grams_and_an_answer_in_kilograms_agree() -> None:
    from tribos.verify.math_claims import audit_answer

    q = r"Two masses $m_1=100 \mathrm{~g}$ and $m_2=200 \mathrm{~g}$ are joined by a spring. Find the reduced mass."
    a = r"$\mu = \frac{m_1 m_2}{m_1 + m_2} = \frac{0.1 \times 0.2}{0.3} = \frac{1}{15}\,\mathrm{kg}$."
    assert not audit_answer(a, q).failed


def test_a_list_of_cases_rebinds_its_label() -> None:
    from tribos.verify.math_claims import audit_answer

    q = "TCP slow start with window W doubling each round; RTT 20 ms, S/R 16 ms. Find the idle time per window."
    a = ("Stall per window:\n\n" + r"- $W=1$: $20\,\text{ms}$" + "\n" + r"- $W=2$: $4\,\text{ms}$" + "\n"
         + r"- $W=4$: $0$" + "\n\n" + r"Total idle $= 24\,\text{ms}$.")
    assert not audit_answer(a, q).failed


# --- real-fluid properties ---------------------------------------------------------------------------------------

def test_fluid_names_resolve_to_coolprop_fluids() -> None:
    from tribos.physis.fluids import resolve_fluid

    assert {resolve_fluid(n) for n in ("R-123", "refrigerant 123", "HCFC-123", "306-83-2")} == {"R123"}
    assert resolve_fluid("steam") == "Water" and resolve_fluid("carbon dioxide") == "CarbonDioxide"
    with pytest.raises(ValueError):
        resolve_fluid("unobtainium")


def test_throttling_uses_the_reference_equation_of_state() -> None:
    from tribos.physis.fluids import fluid_properties

    out = fluid_properties("R134a", "throttle", "40 degC", "5 bar", "1 bar")
    proc = out["process"]
    assert proc["delta_T_K"] < 0 and proc["T2_K"] < proc["T1_K"]
    assert out["eos_reference"] and out["method"].startswith("CoolProp")


def test_saturation_of_water_at_its_normal_boiling_point() -> None:
    from tribos.physis.fluids import fluid_properties

    out = fluid_properties("water", "saturation", temperature="100 C")
    assert out["saturation_pressure_Pa"] == pytest.approx(101_325, rel=0.002)
    assert out["latent_heat_J_per_kg"] == pytest.approx(2.257e6, rel=0.01)


def test_fluid_tool_validates_its_inputs() -> None:
    from tribos.physis.fluids import fluid_properties

    with pytest.raises(ValueError):
        fluid_properties("Water", "throttle", "300 K", "2 bar")  # no final pressure
    with pytest.raises(ValueError):
        fluid_properties("Water", "state", "-5 K", "1 bar")
    with pytest.raises(ValueError):
        fluid_properties("Water", "state", "300 K", "1 bar", outputs=["colour"])


def test_fluid_tool_is_registered_and_routed_only_for_fluid_questions() -> None:
    from tribos.agentic.plan_execute import needs_specialised_tool
    from tribos.tools.registry import get_tool_registry

    reg = get_tool_registry()
    res = asyncio.run(reg.execute("physis_fluid_properties", fluid="Nitrogen", operation="state", temperature="300 K",
                                  pressure="1 bar", outputs=["density"]))
    assert res.success and res.data["state"]["density"]["value"] == pytest.approx(1.123, rel=0.01)

    def routed(q: str) -> bool:
        return needs_specialised_tool(SimpleNamespace(registry=reg, clean_query=q, query=q))

    assert routed("Compute the Joule-Thomson temperature change when R134a is throttled from 8 bar to 2 bar at 30 C.")
    assert not routed("What pressure does a 2 kg mass exert on a 1 m^2 table?")


# --- the grader -----------------------------------------------------------------------------------------------------

def test_grader_reads_negative_thin_space_before_a_command() -> None:
    from tribos.evals import scoring

    value = scoring._parse_numeric_str(r"2\sqrt{2}\sin\!\left(\frac{\pi}{2\sqrt{2}}\right)")
    assert value == pytest.approx(2.534324, rel=1e-6)


def test_grader_evaluates_the_normal_cdf() -> None:
    from tribos.evals import scoring

    assert scoring._parse_numeric_str(r"1-\Phi\left(\frac{2}{\sqrt{5}}\right)") == pytest.approx(0.185547, rel=1e-5)
