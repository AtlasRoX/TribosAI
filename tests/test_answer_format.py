"""
Offline tests for the expert-brief answer format: the output rules in the synthesis prompt, the evidence level
each literature document carries, and the retrieval date that time-sensitive facts are dated with.
"""

import re
import time
from datetime import date

import pytest

from tests import fakes
from tests.test_audit_regressions import offline_orchestrator  # noqa: F401  (fixture)
from tribos.agents import authoritative_orchestrator as orch_module
from tribos.agents.prompts import (
    CORRECTION_SYSTEM_PROMPT,
    SYNTHESIS_SYSTEM_PROMPT,
    build_evidence_block,
    build_synthesis_request,
    evidence_level,
)
from tribos.tools.registry import ToolResult


def test_prompt_carries_the_expert_brief_rules():
    p = SYNTHESIS_SYSTEM_PROMPT
    # 1. fixed STEM evidence-level scale, in words, after literature claims; never upgraded
    assert ("peer-reviewed journal/conference > preprint > textbook/reference work > technical report/standard > "
            "web/other") in p
    assert '"(arXiv:2312.04511; preprint)"' in p and "never upgrade it" in p
    # 2. the primary report is cited for its own results
    assert "primary report is in <evidence>, cite that report for its results" in p
    # 3. values with SI units, significant figures and validity regimes
    assert "with their units (SI units) and significant figures" in p and "valid governing regimes" in p
    # 4. executive summary with calibrated confidence
    assert "Executive Summary" in p and "confidence (high, moderate, or low)" in p
    # 5. gaps stated, never filled
    assert "Evidence limitations" in p and "Never fabricate experimental measurements" in p
    # 6. no literal backslash line continuations reach the model (BRK-5); LaTeX examples stay intact
    assert "\\\n" not in p and not p.startswith("\\")
    assert "\\begin{aligned}" in p and "\\frac{\\mathrm{d}^2 x}{\\mathrm{d}t^2}" in p


def test_correction_prompt_keeps_the_same_format_rules():
    assert "same grounding, scope, and format rules" in CORRECTION_SYSTEM_PROMPT
    assert "evidence levels" in CORRECTION_SYSTEM_PROMPT and '"as of" dates' in CORRECTION_SYSTEM_PROMPT
    assert "species name" not in CORRECTION_SYSTEM_PROMPT and "effect-size" not in CORRECTION_SYSTEM_PROMPT


@pytest.mark.parametrize(
    "passage, level",
    [
        ({"evidence_grade": {"study_type": "peer_reviewed"}}, "peer-reviewed journal/conference"),
        ({"evidence_grade": {"study_type": "conference"}}, "peer-reviewed journal/conference"),
        ({"evidence_grade": {"study_type": "theorem_proof"}}, "peer-reviewed journal/conference"),
        ({"evidence_grade": {"study_type": "preprint"}}, "preprint"),
        ({"evidence_grade": {"study_type": "peer_reviewed", "is_preprint": True}}, "preprint"),
        ({"evidence_grade": {"study_type": "monograph_standard"}}, "textbook/reference work"),
        ({"evidence_grade": {"study_type": "book_chapter"}}, "textbook/reference work"),
        ({"evidence_grade": {"study_type": "technical_report"}}, "technical report/standard"),
        ({"evidence_grade": {"study_type": "numerical_simulation", "confidence": "low", "basis": "text_heuristic"}},
         "peer-reviewed journal/conference (type inferred from wording, unverified)"),
        ({"evidence_grade": {"study_type": "unclassified"}}, "unclassified"),
        ({"evidence_grade": {"study_type": "rct"}, "title": "A phase 3 trial"}, "unclassified"),  # legacy clinical grade
        ({"experimental_setting": "in-vivo"}, "unclassified"),  # ungraded
        ({}, "unclassified"),
    ],
)
def test_evidence_level_uses_the_fixed_scale(passage, level):
    assert evidence_level(passage) == level


def test_graded_passage_renders_its_level_without_duplicate_attributes():
    passage = {
        "arxiv_id": "2312.04511", "doi": "10.48550/arXiv.2312.04511", "year": "2023", "source": "arxiv",
        "title": "Terminal velocity of small spheres", "passage_text": "The drag coefficient follows Stokes' law for Re < 1.",
        "evidence_grade": {"study_type": "preprint", "label": "Preprint"}, "grade_label": "Preprint",
    }
    block = build_evidence_block({"archivon": ToolResult(success=True, tool_name="archivon_literature_search", data={"ranked_passages": [passage]})}, "ranking")
    doc = re.search(r"<document [^>]*>", block).group(0)
    assert 'evidence_level="preprint"' in doc and 'arxiv_id="2312.04511"' in doc and 'source="arXiv"' in doc
    assert '<literature source="arXiv">' in block and "EuropePMC" not in block
    names = re.findall(r'\s([\w-]+)="', doc)
    assert len(names) == len(set(names))
    # Ungraded passages keep the legacy rendering (the foundation golden is byte-identical without extensions).
    ungraded = build_evidence_block({"lithoscribe": ToolResult(success=True, tool_name="l", data={"ranked_passages": [{"pmid": "1", "passage_text": "x"}]})}, "r")
    assert "evidence_level" not in ungraded


def test_synthesis_request_is_dated():
    req = build_synthesis_request("<evidence></evidence>", "<tool_status></tool_status>", "none", "q", retrieval_date="2026-10-16")
    assert "<retrieval_date>2026-10-16</retrieval_date>" in req
    assert req.index("<retrieval_date>") < req.index("<user_query")
    default = build_synthesis_request("<evidence></evidence>", "<tool_status></tool_status>", "none", "q")
    assert f"<retrieval_date>{date.today().isoformat()}</retrieval_date>" in default


@pytest.mark.asyncio
async def test_orchestrator_sends_date_and_evidence_levels(offline_orchestrator, monkeypatch):  # noqa: F811
    orch, _calls = offline_orchestrator
    original = fakes._fake_output

    def graded(tool_name, kwargs):
        if tool_name in ("lithoscribe_literature_synthesis", "archivon_literature_search"):
            return {"ranked_passages": [
                {"pmid": "123456", "title": "A phase III randomized trial of KRAS inhibition", "year": "2023",
                 "passage_text": "KRAS signaling in pancreatic cancer.", "evidence_grade": {"study_type": "peer_reviewed", "label": "Journal article"},
                 "grade_label": "Journal article"},
                {"pmid": "234567", "passage_text": "KRAS mutant xenografts regressed.",
                 "evidence_grade": {"study_type": "preprint", "label": "Preprint"}},
            ]}
        return original(tool_name, kwargs)

    monkeypatch.setattr(fakes, "_fake_output", graded)
    captured = {}

    class FakeLLM:
        async def ainvoke(self, messages):
            captured["messages"] = messages

            class R:
                content = "KRAS signaling in pancreatic cancer is reported (PMID: 123456; phase III RCT)."

            return R()

    monkeypatch.setattr(orch_module, "get_llm", lambda *a, **k: FakeLLM())
    await orch.execute_inquiry("Find KRAS papers only.", thread_id="t-format", enable_web_search=True)
    _system, human = captured["messages"]
    assert f"<retrieval_date>{time.strftime('%Y-%m-%d')}</retrieval_date>" in human.content
    assert 'evidence_level="peer-reviewed journal/conference"' in human.content
    assert 'evidence_level="preprint"' in human.content
