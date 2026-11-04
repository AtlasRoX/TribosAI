"""The direct baseline (`--system direct`): the same model answers alone, with no tools, and is graded identically."""

from __future__ import annotations

import asyncio
from typing import Any

from tribos.evals.runner import DIRECT_SYSTEM_PROMPT, Evaluator, RunConfig
from tribos.evals.schema import AnswerExpect, EvalCase


class _Reply:
    def __init__(self, content: str) -> None:
        self.content = content
        self.usage_metadata = {"total_tokens": 321}


class _FakeLLM:
    def __init__(self, seen: dict[str, Any]) -> None:
        self.seen = seen

    async def ainvoke(self, messages: list[Any]) -> _Reply:
        self.seen["messages"] = messages
        return _Reply("<think>scratch</think>Each box holds 12, so 4 boxes hold 48.\n\\boxed{48}")


class _NoOrchestrator:
    async def execute_inquiry(self, *_a: Any, **_k: Any) -> Any:
        raise AssertionError("the direct baseline must not run the Tribos pipeline")


def _case() -> EvalCase:
    return EvalCase(id="gsm-x", suite="gsm8k", category="arithmetic_reasoning", query="4 boxes of 12 eggs: how many eggs?",
                    answer=AnswerExpect(answer_type="numeric", numeric_answer=48.0, numeric_tolerance=1e-3, verified=None))


def test_the_direct_baseline_calls_the_model_once_with_no_pipeline_and_is_graded(monkeypatch):
    from tribos.utils.llm import llm_factory

    seen: dict[str, Any] = {}

    def fake_get_llm(**kwargs: Any) -> _FakeLLM:
        seen["kwargs"] = kwargs
        return _FakeLLM(seen)

    monkeypatch.setattr(llm_factory, "get_llm", fake_get_llm)
    ev = Evaluator(RunConfig(levels=["answer"], system="direct", model_name="muse-spark-1.3"),
                   orchestrator=_NoOrchestrator(), run_id="t")
    [res] = asyncio.run(ev.run([_case()]))
    assert res.passed and res.metrics["numeric_correct"] is True
    assert res.observed["response"].startswith("Each box") and "<think>" not in res.observed["response"]
    assert res.observed["framework"] == "direct" and res.observed["tokens_est"] == 321
    assert seen["kwargs"]["model_name"] == "muse-spark-1.3" and seen["kwargs"]["temperature"] == 0.0
    system, user = seen["messages"]
    assert system.content == DIRECT_SYSTEM_PROMPT and user.content == _case().query
    assert ev.meta(["gsm8k"], 1)["system"] == "direct"


def test_the_cli_passes_the_system_choice_to_the_run_config(monkeypatch, tmp_path):
    from tribos.evals import cli

    captured: dict[str, Any] = {}

    class _Stop(Exception):
        pass

    real = cli.RunConfig

    def spy(**kwargs: Any) -> Any:
        captured.update(kwargs)
        raise _Stop

    monkeypatch.setattr(cli, "RunConfig", spy)
    try:
        cli.main(["run", "--suite", "math", "--level", "answer", "--system", "direct", "--out", str(tmp_path)])
    except _Stop:
        pass
    finally:
        monkeypatch.setattr(cli, "RunConfig", real)
    assert captured.get("system") == "direct"
