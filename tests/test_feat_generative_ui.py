"""Generative UI (tribos.writer.genui): the results panel built from code-computed results, and the ```ui blocks the
writer may embed, which are kept only when valid and carrying no number outside the evidence."""

from __future__ import annotations

import json

from tribos.writer.facts import compute_ode_facts
from tribos.writer.genui import SPEC_VERSION, build_answer_ui, sanitize_ui_blocks, validate_ui_block

QUESTION = (
    "Solve 2x''(t) + 3x'(t) + 50x(t) = 10cos(4t) with x(0)=0.1 m, x'(0)=0 m/s. "
    "Tasks: 1. Derive x(t). 2. Evaluate x(t) at t = 0.5, 1, 2 s. 3. Compare with RK4 using step 0.01 s."
)


def test_results_panel_from_computed_facts():
    facts = compute_ode_facts(QUESTION)
    ui = build_answer_ui(facts)
    assert ui is not None and ui["version"] == SPEC_VERSION and ui["source"] == "computed"
    kinds = [b["type"] for b in ui["blocks"]]
    assert kinds[0] == "stats" and "equation" in kinds and "chart" in kinds and "table" in kinds
    eq = next(b for b in ui["blocks"] if b["type"] == "equation")
    assert eq["checks"] and all(c["passed"] for c in eq["checks"])
    chart = next(b for b in ui["blocks"] if b["type"] == "chart")
    assert len(chart["series"][0]["points"]) > 100 and chart["marks"]
    assert chart["series"][0]["points"][0][0] == 0.0 and chart["series"][0]["points"][-1][0] == 2.0
    json.dumps(ui)  # the panel travels as JSON


def test_no_panel_without_checked_results():
    assert build_answer_ui(None) is None
    assert build_answer_ui({"kind": "ode_initial_value_problem", "exact_solution_latex": "x",
                            "checks": [{"name": "ODE", "passed": False}]}) is None


def test_validate_ui_block_shapes():
    assert validate_ui_block({"type": "callout", "text": "Underdamped.", "tone": "loud"})["tone"] == "info"
    assert validate_ui_block({"type": "callout"}) is None
    assert validate_ui_block({"type": "script", "text": "x"}) is None
    stats = validate_ui_block({"type": "stats", "items": [{"label": "ω", "value": "5"}, {"label": ""}]})
    assert stats is not None and len(stats["items"]) == 1
    assert validate_ui_block({"type": "table", "columns": ["a", "b"], "rows": [["1"]]}) is None


def test_sanitize_keeps_backed_blocks_and_removes_others():
    good = '```ui\n{"type":"stats","items":[{"label":"natural frequency","value":"5","unit":"rad/s"}]}\n```'
    bad = '```ui\n{"type":"stats","items":[{"label":"peak","value":"0.98765"}]}\n```'
    broken = "```ui\n{not json\n```"
    answer = f"The natural frequency is 5 rad/s.\n\n{good}\n\n{bad}\n\n{broken}\n"
    out, removed = sanitize_ui_blocks(answer, "omega_n = 5")
    assert '"natural frequency"' in out and "0.98765" not in out and "not json" not in out
    assert len(removed) == 2 and any("0.98765" in r for r in removed)


def test_curve_samples_are_not_evidence_for_the_editor():
    from tribos.writer.editor import accept_edit, guard_view

    facts = compute_ode_facts(QUESTION)
    assert "curve" in facts and "curve" not in guard_view(facts)
    # A value that only the dense plot samples contain must not pass the copy-edit number check.
    sample = facts["curve"]["x"][37]
    draft = "x(t) is given above. " * 10
    ok, _ = accept_edit(QUESTION, draft, draft + f" Peak near {sample:.6f}.", facts)
    assert not ok


# Run 2026-10-30 (forced oscillator, 8 tasks): false contradictions and unchecked items --------------------------------
def test_inline_math_ending_in_a_spacing_command_is_read_whole():
    from tribos.verify.math_claims import audit_answer

    q = "Solve 2x''(t) + 3x'(t) + 50x(t) = 10cos(4t) with x(0)=0.1 m, x'(0)=0 m/s."
    a = audit_answer(r"In particular $x_{p}(0)=5/13\approx 0.384615\,$m.", q)
    assert all(c.status != "failed" for c in a.claims) and all("(0)=5/13" != c.text for c in a.claims)
    wrong = audit_answer(r"In particular $x_{p}(0)=5/12\approx 0.384615\,$m.", q)
    assert any(c.status == "failed" for c in wrong.claims)


def test_braced_unit_is_not_a_variable():
    from tribos.verify.math_claims import audit_answer

    q = "Solve 2x''(t) + 3x'(t) + 50x(t) = 10cos(4t) with x(0)=0.1 m, x'(0)=0 m/s."
    a = audit_answer(r"$$X=\frac{10}{6\sqrt{13}}=\frac{5\sqrt{13}}{39}\approx 0.46225\ {\rm m},$$", q)
    assert [c.status for c in a.claims] == ["passed"]


def test_computed_parameters_check_the_requested_items():
    from tribos.agents.deliverables import _computed_item_checked

    facts = compute_ode_facts(QUESTION)
    answer = (r"The natural frequency is $\omega_n = 5$ rad/s and the damping ratio is $\zeta = 0.15$; "
              "the damped natural frequency is 4.9434 rad/s, the steady-state amplitude 0.46225 m and the phase "
              "shift 0.588003 rad.")
    for item in ("natural frequency", "damping ratio", "damped natural frequency", "steady-state amplitude",
                 "phase shift"):
        assert _computed_item_checked(item, facts, answer), item
    assert not _computed_item_checked("damping ratio", facts, answer.replace("0.15", "0.25"))
    assert not _computed_item_checked("physical meaning in simple language", facts, answer)


def test_run_in_summary_label_becomes_a_heading():
    from tribos.writer.lint import clean_presentation

    assert clean_presentation("Executive Summary: the system is underdamped.\n\n### 1. Derive").startswith(
        "### Executive Summary\n\nThe system is underdamped.")
