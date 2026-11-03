"""The task plan: the parts of a question, the tool for each, the answer in that order, each step closed from artifacts."""

from __future__ import annotations

from tribos.agents.task_plan import build_task_plan, close_plan, needs, writer_note

ODE = ("Solve x'' + 0.4x' + 4x = 0 with x(0)=1, x'(0)=0, plot x(t) for 20 s, prove the energy decays, and verify the "
       "solution numerically in Python.")


def test_each_part_gets_its_tool():
    plan = build_task_plan(ODE)
    assert [s["kind"] for s in plan] == ["solve", "plot", "proof", "code"]
    assert plan[0]["title"] == "Solve x'' + 0.4x' + 4x = 0 with x(0)=1, x'(0)=0"  # the opening clause, whole
    assert needs(plan, "code") and not needs(plan, "formal_proof")


def test_lean_files_and_sources_are_their_own_steps():
    lean = build_task_plan("Find the roots of x^3 - 6x^2 + 11x - 6, prove they are all integers in Lean, and plot the polynomial.")
    assert [s["kind"] for s in lean] == ["solve", "formal_proof", "plot"]
    report = build_task_plan("Derive the period of a pendulum and give me a Word report.")
    assert [s["kind"] for s in report] == ["solve", "file"]
    cited = build_task_plan("Compare explicit and implicit Euler for stiff ODEs, cite papers, and simulate y' = -50y.")
    assert [s["kind"] for s in cited] == ["compare", "sources", "simulate"] and cited[1]["title"] == "Cite papers"


def test_a_single_ask_has_no_plan():
    assert build_task_plan("Solve x^2 - 5x + 6 = 0") == []
    assert build_task_plan("What is 17 times 23?") == []
    assert writer_note([]) == ""


def test_the_writer_answers_in_plan_order():
    note = writer_note(build_task_plan(ODE))
    assert "### 1." in note and note.index("Solve x''") < note.index("Plot x(t)") < note.index("Python (sandbox)")


def test_steps_close_from_the_artifacts_never_by_claim():
    plan = build_task_plan(ODE)
    closed = close_plan(plan, {"math_agent": {"status": "verified"}, "plot": {"figures": [{"png_base64": "x"}]},
                               "codeact": {"ok_cells": 0}}, "answer text")
    status = {s["kind"]: s["status"] for s in closed}
    assert status == {"solve": "verified", "plot": "done", "proof": "done", "code": "failed"}
    nothing = {s["kind"]: s["status"] for s in close_plan(plan, {}, "answer")}
    assert nothing["plot"] == "failed" and nothing["code"] == "not_run"


def test_a_detailed_figure_request_is_one_plot_step(tmp_path):
    q = (r"Plot the function \[ f(x,y)=\frac{x^2}{6} +\frac{y^2}{2} +\sin(x+y-7) \] as a high-resolution, filled "
         r"contour plot over the domain: \[ -3\leq x\leq3,\qquad 0\leq y\leq6 \] Include the following: 1. Draw 20 "
         r"contour levels. 2. Mark the point P = (1.5, 2). 3. Calculate the gradient vector \(\nabla f\) at \(P\). "
         "4. Find the critical points of f in the domain and mark them. 5. Plot includes axis labels, legend, grid.")
    plan = build_task_plan(q)
    assert [s["kind"] for s in plan] == ["plot", "solve", "solve"]
    assert all("\\" not in s["title"] and "$" not in s["title"] for s in plan)  # plain text, no LaTeX
    assert plan[1]["title"] == "Calculate gradient vector ∇ f at P"


def test_a_numbered_question_is_planned_one_step_per_item_with_all_its_tools():
    q = ("A damped oscillator obeys x'' + c x' + k x = 0 with x(0) = 1, x'(0) = 0, k = 4.\n"
         "1. Solve the ODE analytically for c = 0.4 and plot x(t) for 0 <= t <= 20.\n"
         "2. Compute the dissipated energy numerically for c = 0.4.\n"
         "3. Find the damping c in [0.1, 2] that minimises the settling time, subject to the overshoot staying below 0.5.\n"
         "4. Propagate the uncertainty in c to E(c) with 2,000 Monte Carlo samples and plot the histogram.\n")
    plan = build_task_plan(q)
    assert [s["kind"] for s in plan] == ["solve", "code", "optimize", "code"]
    assert plan[0]["tool"] == "SymPy (verified math agent) + matplotlib (sandbox)"
    assert plan[3]["tool"] == "Python (sandbox) + matplotlib (sandbox)"
