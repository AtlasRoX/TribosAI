"""
Tests for Feature F16: Diagnose completion failures and return truthful, correctly formatted fallbacks.

Covers:
- Bounded transient provider recovery (RetryingAsyncTransport, Retry-After, attempt bounding).
- Prevention of multiplied application retries (SDK retry disabled, already_retried checks).
- Preservation of validated computed mathematical work when writer fails (rendered_fallback in requested format).
- Truthful reporting on complete failures: never echoes prompt instructions as computed evidence.
"""

from __future__ import annotations

from typing import Any

import httpx
import pytest

from tribos.axiom.definitions import axiom_structured
from tribos.axiom.engine import axiom_solve
from tribos.axiom.schemas import AxiomSolveInput, AxiomStructuredInput
from tribos.utils.llm.llm_factory import get_llm
from tribos.utils.llm.provider_retry import RetryingAsyncTransport, already_retried


def _real_axiom_tools() -> dict[str, Any]:
    return {
        "axiom_structured": (AxiomStructuredInput, lambda kw: axiom_structured(**kw)),
        "axiom_solve": (AxiomSolveInput, lambda kw: axiom_solve(**kw)),
    }


# ---------------------------------------------------------------------------
# 1. Bounded Transient Provider Recovery
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize("statuses, final, attempts", [
    ([500, 500, 200], 200, 3),  # burst of 500s recovers on 3rd attempt
    ([400], 400, 1),            # client 400 is not retried
    ([500, 500, 500, 500], 500, 3),  # bounded to at most 3 attempts
])
async def test_f16_transient_provider_faults_retried_within_bounds(statuses, final, attempts):
    sent: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        sent.append(1)
        code = statuses[min(len(sent), len(statuses)) - 1]
        return httpx.Response(code, headers={"nvcf-reqid": f"req-{len(sent)}"})

    transport = RetryingAsyncTransport(httpx.MockTransport(handler), attempts=3, deadline_s=5.0, base_delay_s=0.01)
    async with httpx.AsyncClient(transport=transport) as client:
        res = await client.post("https://integrate.api.nvidia.com/v1/chat/completions", json={"m": 1})
    assert res.status_code == final
    assert len(sent) == attempts


def test_f16_sdk_retry_disabled_and_application_layers_do_not_multiply_attempts(monkeypatch):
    monkeypatch.setenv("TRIBOS_ALLOWED_MODELS", "nvidia/nemotron-3.5-super-vl-120b-a12b")  # NVIDIA is off the catalog; the NIM path stays for operators who allow a model
    monkeypatch.setenv("NVIDIA_API_KEY", "nvapi-test-dummy-key")
    llm = get_llm(model_name="nvidia/nemotron-3.5-super-vl-120b-a12b")
    # SDK retry must be 0 so the transport's bounded retry governs
    assert llm.max_retries == 0
    assert llm.http_async_client is not None

    status_error = type("InternalServerError", (Exception,), {})()
    mid_stream = type("ReadError", (Exception,), {})()
    assert already_retried(llm, status_error) is True
    assert already_retried(llm, mid_stream) is False


# ---------------------------------------------------------------------------
# 2. Validated Work Survives Failing Writer in Requested Format
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize("question, expected", [
    ("Solve x^2 + 1 = 0 over the real numbers. Give the solution set on one line.", "∅"),
    ("Solve (x^2 - 1)/(x - 1) = x + 1 over the real numbers. Give the solution set on one line.", "ℝ ∖ {1}"),
])
async def test_f16_validated_results_survive_failing_writer_in_requested_format(monkeypatch, tmp_path, question, expected):
    from tests.test_audit_repair import make_offline_orchestrator

    # Offline orchestrator where all LLM calls fail with HTTP 500
    orch, _calls = make_offline_orchestrator(monkeypatch, tmp_path, extra_tools=_real_axiom_tools())
    res = await orch.execute_inquiry(question, thread_id="t-f16-survive", enable_web_search=False, framework="auto")

    assert res.response == expected
    assert res.task_status["task_status"] == "completed"
    assert res.task_status["requested_operation"] == "mathematical_answer"
    assert res.execution_artifacts["output_contract"]["violations"] == []


# ---------------------------------------------------------------------------
# 3. Truthful Reporting on Complete Failure (Never Echoes Prompt as Results)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_f16_zero_results_fails_honestly_without_prompt_echo(monkeypatch, tmp_path):
    from tests.test_audit_repair import make_offline_orchestrator

    t34_query = (
        "Conduct a sustained investigation of the Riemann Hypothesis. Develop approach candidates, "
        "formulate intermediate lemmas, identify the exact proof obstacle, and verify critical identities. "
        "There is no 150-word limit."
    )
    orch, _calls = make_offline_orchestrator(monkeypatch, tmp_path)
    res = await orch.execute_inquiry(t34_query, thread_id="t-f16-no-results", enable_web_search=False, framework="auto")

    assert res.task_status["task_status"] == "failed"
    assert "No answer could be produced" in res.response
    # Prompt text is NEVER echoed as tool/computed results
    assert "Riemann" not in res.response
    assert "sustained investigation" not in res.response
    # Revoked word limit is not enforced
    assert not (res.execution_artifacts.get("output_contract") or {}).get("max_words")
