"""Fixes from an olympiad proof run (IMO-style "Prove that there exist T and L ..." read from an image):
the number-theory parser computed gcd(1, 1, 1, 1, 2) from subscripts and called it verified, decomposition split the
problem's setup sentences into sub-questions, and the Meta model spent its whole output allocation reasoning because
the reasoning effort never reached it."""

from __future__ import annotations

import asyncio

import pytest

PROBLEM = (
    "Solve the problem in the attached image, showing every step.\n\nAttached image 1 (p6.png), transcribed:\n"
    "**Problem 6**\n\nLet $a_1, a_2, a_3, \\dots$ be an infinite sequence of positive integers greater than 1. "
    "Suppose that for all positive integers $n$, the number $a_{n+1}$ is the smallest positive integer greater than "
    "$a_n$ such that $\\gcd(a_{n+1}, a_i) > 1$ for every $i = 1, 2, \\dots, n$. Prove that there exist positive "
    "integers $T$ and $L$ such that $$a_{n+T} = a_n + L$$ for every positive integer $n$."
)


def test_a_general_proof_is_not_parsed_as_a_gcd_of_its_subscripts():
    from tribos.axiom.problem import parse_problem

    spec = parse_problem(PROBLEM.split("transcribed:\n", 1)[1])
    assert spec.kind != "number_theory"


@pytest.mark.parametrize("question,numbers", [
    ("Find the gcd of 84 and 126", ["84", "126"]),
    ("What is gcd(84, 126, 210)?", ["84", "126", "210"]),
    ("Compute the least common multiple of 4, 6 and 10", ["4", "6", "10"]),
])
def test_gcd_and_lcm_still_read_written_operands(question, numbers):
    from tribos.axiom.problem import parse_problem

    spec = parse_problem(question)
    assert spec.kind == "number_theory" and spec.params["numbers"] == numbers


def test_gcd_without_written_operands_is_not_a_calculation():
    from tribos.axiom.problem import parse_problem

    spec = parse_problem("Suppose gcd(a_{n+1}, a_i) > 1 for i = 1, 2. Find a_3 when a_1 = 2.")
    assert spec.kind != "number_theory" or spec.params["operation"] != "gcd"


def test_a_single_proof_problem_is_not_split_into_sub_questions():
    from tribos.agentic.decompose import is_single_proof_problem

    assert is_single_proof_problem(PROBLEM)
    assert is_single_proof_problem("Determine all functions f: R -> R such that f(x + y) = f(x) + f(y).")
    assert not is_single_proof_problem("What is the boiling point of water? And how does pressure change it?")


def test_the_decompose_phase_leaves_a_proof_problem_whole():
    from tribos.agentic.decompose import DecomposePhase

    class Ctx:
        scope = "research"
        effort_level = "ultra"

    class LLM:
        available = True

        async def json(self, *a, **k):
            raise AssertionError("a proof problem needs no decomposition call")

    class State:
        clean_query = PROBLEM
        query = PROBLEM
        ctx = Ctx()
        effort_level = "ultra"
        sub_questions: list = []
        llm = LLM()
        bag: dict = {}

        async def step(self, *a, **k):
            raise AssertionError("no decomposition step")

    state = State()
    asyncio.run(DecomposePhase().run(state))
    assert state.sub_questions == [] and state.bag["decomposition"]["method"] == "single_problem"


def test_meta_models_receive_the_reasoning_effort(monkeypatch):
    from tribos.utils.llm import llm_factory

    monkeypatch.setenv("META_API_KEY", "configured")
    monkeypatch.setattr(llm_factory, "_usable_key", lambda value: value or None)
    monkeypatch.setattr(llm_factory, "_record_client", lambda **kwargs: None)
    seen: dict = {}

    class FakeChat:
        def __init__(self, **kwargs):
            seen.update(kwargs)

    monkeypatch.setattr(llm_factory, "ChatOpenAI", FakeChat)
    llm_factory.get_llm(model_name="muse-spark-1.3", reasoning_effort="minimal")
    assert seen.get("reasoning_effort") == "minimal"
    seen.clear()
    llm_factory.get_llm(model_name="muse-spark-1.3", reasoning_effort="ultra")
    assert seen.get("reasoning_effort") == "xhigh"
    seen.clear()
    llm_factory.get_llm(model_name="muse-spark-1.3")
    assert "reasoning_effort" not in seen


def test_nvidia_models_are_not_in_the_catalog():
    from tribos.utils.llm.llm_factory import SUPPORTED_MODELS

    ids = [m["id"] for m in SUPPORTED_MODELS]
    assert ids and not any(i.startswith("nvidia/") or "nemotron" in i for i in ids)


def test_image_reading_uses_the_meta_model_by_default(monkeypatch):
    from tribos.vision import vlm

    monkeypatch.delenv("TRIBOS_VISION_PROVIDER", raising=False)
    monkeypatch.delenv("TRIBOS_VISION_MODEL", raising=False)
    assert vlm.provider() == "remote" and vlm.nim_model() == "muse-spark-1.3"
    monkeypatch.setenv("TRIBOS_VISION_PROVIDER", "nim")  # the older name still means the cloud model
    assert vlm.provider() == "remote"


def test_agent_json_calls_on_meta_models_reason_minimally():
    from tribos.agentic.llm import agent_model_kwargs

    assert agent_model_kwargs("muse-spark-1.3") == {"reasoning_effort": "minimal"}


def test_deep_reasoning_waits_longer_for_the_first_byte(monkeypatch):
    from tribos.utils.llm import llm_factory

    monkeypatch.setenv("META_API_KEY", "configured")
    monkeypatch.setattr(llm_factory, "_usable_key", lambda value: value or None)
    monkeypatch.setattr(llm_factory, "_record_client", lambda **kwargs: None)
    seen: dict = {}

    class FakeChat:
        def __init__(self, **kwargs):
            seen.update(kwargs)

    monkeypatch.setattr(llm_factory, "ChatOpenAI", FakeChat)
    llm_factory.get_llm(model_name="muse-spark-1.3", reasoning_effort="high")
    assert seen["timeout"] >= 600
    llm_factory.get_llm(model_name="muse-spark-1.3", reasoning_effort="minimal")
    assert seen["timeout"] == llm_factory.DEFAULT_LLM_TIMEOUT_S
    llm_factory.get_llm(model_name="muse-spark-1.3", reasoning_effort="high", timeout=30)
    assert seen["timeout"] == 30  # an explicit timeout wins


def test_dsolve_rejects_an_equation_without_a_derivative():
    from tribos.axiom.engine import axiom_dsolve
    from tribos.axiom.shapes import UnsupportedShapeError

    with pytest.raises(UnsupportedShapeError, match="no derivative"):
        axiom_dsolve("n = 0", func="s(x)")
    assert "exp" in str(axiom_dsolve("y' = y", func="y(x)"))  # a real ODE still solves: y = C1*exp(x)


def test_a_tool_whose_verification_is_a_sentence_does_not_crash_the_verifier():
    """The axiom analysis tools report "verification" as a sentence; the verifier assumed a dict of checks and the
    whole answer failed with AttributeError ('str' object has no attribute 'get')."""
    from tribos.tools.registry import ToolResult
    from tribos.verify.verifier import TribosVerifier

    results = {
        "axiom_analysis": ToolResult(success=True, tool_name="axiom_analysis",
                                     data={"verification": "dense sampling of f agrees with the extrema"}),
        "axiom_other": ToolResult(success=True, tool_name="axiom_other",
                                  data={"verification": {"checks": ["not-a-dict", {"name": "domain", "passed": True}]}}),
    }
    report = TribosVerifier().verify_response("Largest band size?", "The largest number of members is 98.", results)
    assert report is not None


def test_a_single_word_problem_is_not_split_into_sub_questions():
    """A word problem asking one thing was split into 3 sub-questions and reported "1 of 3 answered" although its
    answer (98) was complete."""
    from tribos.agentic.decompose import is_single_proof_problem

    band = ("A particular band has less than 100 band members. The director arranges them in a rectangular formation "
            "with two members left over. If he increases the number of members in each row by 1 and reduces the "
            "number of rows by 2, there are exactly enough places. What is the largest number of members the band "
            "could have?")
    assert is_single_proof_problem(band)
    assert not is_single_proof_problem("Compare the density of aluminium and steel and explain why titanium is used.")
    assert not is_single_proof_problem("What causes CRISPR off-target edits? How are they reduced?")
