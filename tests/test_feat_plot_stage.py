"""Plot requests: detected, drawn by a model-written matplotlib script in the sandbox, repaired once, attached as files."""

from __future__ import annotations

import asyncio
import base64
from types import SimpleNamespace
from typing import Any

import pytest

from tribos.agents.orchestration import plot_stage


@pytest.mark.parametrize("question, wanted", [
    ("Plot f(x) = (x^4 + 50)/6 for x from -3 to 3 and mark x = 2", True),
    ("Plot f(x, y) = (x^4 + 2y^2)/6 as a contour plot", True),
    ("Draw the graph of y = sin(x)/x", True),
    ("Visualize the phase portrait of the Van der Pol oscillator", True),
    ("How many edges does a complete bipartite graph K_{3,4} have?", False),
    ("Explain the plot of Hamlet", True),  # caught by the word; the plot stage only runs for research questions
    ("What is 17 times 23?", False),
])
def test_plot_requests_are_recognised(question, wanted):
    assert bool(plot_stage.PLOT_REQUEST_RE.search(question)) is wanted


def _run(question: str) -> Any:
    events: list[tuple[str, str]] = []

    async def emit(kind: str, title: str, text: str = "", status: str = "done", **_k: Any) -> None:
        events.append((title, status))

    run = SimpleNamespace(clean_query=question, query=question, ctx=SimpleNamespace(scope="research"),
                          execution_artifacts={}, scope_notes=["earlier note"], agent_state=None, emit=emit)
    run.events = events
    return run


GOOD = "```python\nimport numpy as np\nimport matplotlib.pyplot as plt\nx = np.linspace(-3, 3, 50)\nfig, ax = plt.subplots()\nax.plot(x, x**2)\nprint('f(2) = 4')\nplt.show()\n```"
BAD = "```python\nimport numpy as np\nraise ValueError('broken')\n```"


def test_a_failed_script_is_repaired_once_and_the_figure_attached(monkeypatch):
    from tribos.agents.orchestration import llm_call

    replies = iter([BAD, GOOD])
    seen: list[Any] = []

    async def fake_ask(_run: Any, _system: str, messages: Any, **_k: Any) -> str:
        seen.append(list(messages))
        return next(replies)

    monkeypatch.setattr(llm_call, "ask", fake_ask)
    run = _run("Plot y = x^2 for x from -3 to 3")
    asyncio.run(plot_stage.run_plot(run))
    art = run.execution_artifacts["plot"]
    assert art["figures"] and art["figures"][0]["png_base64"] and "plt.show" not in art["code"]
    assert "f(2) = 4" in art["stdout"]
    assert "failed" in seen[1][-1][1] and "broken" in seen[1][-1][1]  # the error went back to the model
    assert run.scope_notes[0] == "earlier note" and "figure" in run.scope_notes[-1]

    files = plot_stage.plot_files("Plot y = x^2 for x from -3 to 3", art)
    kinds = [k for k, _n, _d in files]
    assert kinds == ["png", "py"]
    assert files[0][2][:8] == base64.b64decode(art["figures"][0]["png_base64"])[:8] == b"\x89PNG\r\n\x1a\n"
    assert files[1][2].decode().rstrip().endswith("plt.show()")


def test_no_plot_stage_for_a_non_plot_question(monkeypatch):
    from tribos.agents.orchestration import llm_call

    async def fake_ask(*_a: Any, **_k: Any) -> str:
        raise AssertionError("no model call")

    monkeypatch.setattr(llm_call, "ask", fake_ask)
    run = _run("What is 17 times 23?")
    asyncio.run(plot_stage.run_plot(run))
    assert "plot" not in run.execution_artifacts


def test_a_stated_value_the_function_does_not_give_is_reported():
    from tribos.agents.orchestration.plot_stage import stated_value_mismatches

    q = "Mark the point P=(2,5), verifying that f(2,5)=11."
    assert stated_value_mismatches(q, "f(2, 5) = 8\nmax = 3") == [{"stated": "f(2, 5) = 11", "computed": "f(2, 5) = 8"}]
    assert stated_value_mismatches(q, "f(2, 5) = 11.0000000") == []
    assert stated_value_mismatches(q, "nothing printed about f") == []


def test_broken_fractions_are_reported_and_valid_latex_is_not():
    from tribos.utils.latex_check import malformed_latex

    assert malformed_latex(r"f(x,y)=\frac6" "\n" r"+\frac2" "\n" r"+\sin(x+y-7)")
    assert malformed_latex(r"\frac{x^4+2y^2}{6} + \frac12 + \dfrac{a}{b} and \(x\)") == []
    assert "unbalanced" in malformed_latex(r"\frac{a}{b")[0]


def test_a_figure_whose_numbers_blew_up_is_repaired(monkeypatch):
    from tribos.agents.orchestration import llm_call

    blown = ("```python\nimport numpy as np\nimport matplotlib.pyplot as plt\nfig, ax = plt.subplots()\n"
             "ax.plot([0, 1], [0, 1])\nprint('heat max error at t=2 = nan')\n```")
    replies = iter([blown, GOOD])
    seen: list[Any] = []

    async def fake_ask(_run: Any, _system: str, messages: Any, **_k: Any) -> str:
        seen.append(list(messages))
        return next(replies)

    monkeypatch.setattr(llm_call, "ask", fake_ask)
    run = _run("Plot the heat equation solution u(x, t) for 0 <= t <= 2")
    asyncio.run(plot_stage.run_plot(run))
    assert "non-finite" in seen[1][-1][1]  # the nan went back to the model
    assert "nan" not in run.execution_artifacts["plot"]["stdout"]  # the repaired figure is the one shown
