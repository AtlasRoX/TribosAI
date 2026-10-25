"""Conservative dimensional and numerical checking of the written physics answer."""

from __future__ import annotations

import pytest

from tribos.verify.math_claims import audit_answer, claim_defects


def _units(answer: str, question: str = ""):
    from tribos.verify.units_audit import audit_units
    return audit_units(answer, question)


def test_wrong_dimensions_are_caught():
    report = _units("F = m*a = 6 J", "m = 2 kg; a = 3 m/s^2")
    assert report["checked"] > 0
    assert report["inconsistent"]
    assert report["inconsistent"][0]["lhs_dim"] != report["inconsistent"][0]["rhs_dim"]


def test_wrong_number_after_unit_conversion_is_caught():
    query = "d = 2 m; t = 500 ms"
    assert not _units("v = d/t = 4 m/s", query)["inconsistent"]
    assert _units("v = d/t = 0.004 m/s", query)["inconsistent"]


def test_pressure_with_force_label_is_caught():
    report = _units("The pressure is 50 N.")
    assert report["inconsistent"] and "pressure" in report["inconsistent"][0]["statement"].lower()


def test_small_quantities_and_ambiguous_bindings():
    assert _units("E = h*f = 9e-34 J", "h = 6.62607015e-34 J*s; f = 1 Hz")["inconsistent"]
    ambiguous = _units("F = m*a = 6 N", "m = 2 kg; m = 3 m; a = 3 m/s^2")
    assert not ambiguous["inconsistent"] and ambiguous["not_evaluated"]


def test_correct_latex_physics_and_ambiguous_symbols_are_not_flagged():
    answer = r"The energy is $E = mc^2 = 9.0\times10^{16}\,\mathrm{J}$."
    query = r"$m = 1\,\mathrm{kg}$ and $c = 299792458\,\mathrm{m/s}$."
    report = _units(answer, query)
    assert report["checked"] >= 1 and not report["inconsistent"], report
    ambiguous = _units("F = m*a = 6 N")
    assert not ambiguous["inconsistent"] and ambiguous["not_evaluated"] > 0
    assert not _units("For a different case, F = q*z = 2 N")["inconsistent"]


def test_code_and_unsafe_expressions_do_not_run():
    assert _units("```python\npressure = 50 N\n```")["checked"] == 0
    report = _units("F = __import__('os').system('bad') = 6 N")
    assert not report["inconsistent"]


def test_unit_contradiction_becomes_math_audit_defect():
    audit = audit_answer(r"$F = m a = 6\,\mathrm{J}$", "m = 2 kg; a = 3 m/s^2")
    assert audit.units["inconsistent"]
    assert any("unit" in defect["description"].lower() for defect in claim_defects(audit))


@pytest.mark.asyncio
async def test_unit_defects_reach_the_writer_and_corrected_answer(monkeypatch, tmp_path):
    from tests.agentic_fakes import make_agentic_orchestrator

    correct = r"The force is $F=m a=6\,\mathrm{N}$."
    orch, _, llm = make_agentic_orchestrator(monkeypatch, tmp_path, responses={"correction": correct},
        default_synthesis=r"The force is $F=m a=6\,\mathrm{J}$.")
    result = await orch.execute_inquiry("For m = 2 kg and a = 3 m/s^2, calculate the force F = m*a.",
        user_id="alice", thread_id="units", framework="agentic-plan-execute")
    assert any("unit" in prompt.lower() for prompt in llm.prompts("correction"))
    assert not result.verification_report["units"]["inconsistent"]
