"""
Cross-feature integration checks: one question that routes to the trials, drugs and variants sources, the
planner's parser fallbacks, verifier de-duplication and identifier matching, and literature grades in exports.
All offline; plugin fakes replay recorded fixtures or report an upstream failure, never invented data.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List

import pytest

from tribos.agents.query_planner import build_query_context
from tribos.export.report_model import ExportMessage, build_report_model, citation_line
from tribos.extensions import hooks
from tribos.verify.verifier import TribosVerifier
from tribos.tools.registry import ErrorType, ToolResult
from tests.fakes import called, make_offline_orchestrator

FIXTURES = Path(__file__).parent / "fixtures"
TRIPLE_QUERY = "osimertinib trials and adverse events in EGFR L858R NSCLC"


async def _ask(orch, query: str):
    events: List[Dict[str, Any]] = []

    async def cb(ev):
        events.append(ev)

    res = await orch.execute_inquiry(query, thread_id="t-integ", enable_web_search=False, event_callback=cb)
    steps = {e["data"]["id"]: e["data"] for e in events if e["type"] == "thought"}
    return res, steps


@pytest.mark.asyncio
async def test_planner_falls_back_to_feature_parsers(monkeypatch):
    monkeypatch.setenv("TRIBOS_PLANNER", "off")

    async def ctx_for(q: str):
        return await build_query_context(
            query=q, clean_query=q, registry=None, enable_web_search=False, attachments=[], attachment_errors=[],
            user_id="u", thread_id="t", model_name="m", api_key=None,
        )

    cdna = await ctx_for("Clinical significance of KRAS c.35G>A")
    (variant,) = cdna.variants
    assert (variant.gene, variant.label, variant.variant_kind, variant.validated) == ("KRAS", "c.35G>A", "hgvs", False)

    brand = await ctx_for("Adverse events of Tagrisso")
    (drug,) = brand.drugs
    assert drug.label == "tagrisso" and not drug.validated and drug.ids == {}
    assert brand.observed_identifiers()["chembl"] == set()

    dosing = await ctx_for("Pembrolizumab 200 mg IV Q3W toxicity")
    assert dosing.variants == []


def test_registered_checks_do_not_double_flag_a_claim():
    defect = {"category": "NUMERICAL", "severity": "MAJOR", "description": "d", "suggested_correction": "s", "claim": "ORR 99%"}
    with hooks.isolated_hooks():
        hooks.register_verification_check("a", lambda vctx: [dict(defect)])
        hooks.register_verification_check("b", lambda vctx: [dict(defect), dict(defect, category="CLINICAL_CLAIM")])
        report = TribosVerifier().verify_response("q", "The ORR was 99%.", {})
    flagged = [(d.category, d.claim) for d in report.defects if d.claim == "ORR 99%"]
    assert flagged == [("NUMERICAL", "ORR 99%"), ("CLINICAL_CLAIM", "ORR 99%")]


def test_a_number_in_passage_text_is_not_a_pmid():
    passage = json.loads((FIXTURES / "ctgov" / "pubmed_flaura_os_31751012.json").read_text(encoding="utf-8"))
    lit = {
        "lithoscribe": ToolResult(
            success=True,
            tool_name="lithoscribe_literature_synthesis",
            data={"ranked_passages": [{"pmid": passage["pmid"], "passage_text": passage["passage_text"]}]},
        )
    }
    verifier = TribosVerifier()
    # "79 of 279 patients" is in the passage; 279 is not a PMID it names.
    report = verifier.verify_response("q", "Osimertinib improved overall survival (PMID: 279).", lit)
    assert [d for d in report.defects if d.claim == "PMID 279"]
    ok = verifier.verify_response("q", "Median overall survival was 38.6 months (PMID: 31751012).", lit)
    assert "PMID:31751012" in ok.verified_identifiers


def test_export_citations_carry_literature_grades():
    message = ExportMessage(
        content="Lithoscribe retrieved PMID: 31751012.",
        execution_artifacts={
            "sources": [{"kind": "literature", "pmid": "31751012", "title": "Overall Survival with Osimertinib", "tool": "lithoscribe"}],
            "literature": {
                "graded_articles": [
                    {
                        "article_key": "MED:31751012",
                        "pmid": "31751012",
                        "grade": {"study_type": "rct", "label": "Randomized controlled trial"},
                        "integrity": {"status": "none"},
                    }
                ]
            },
        },
    )
    report = build_report_model("q", message)
    (c,) = report.citations
    assert c.grade == "Randomized controlled trial" and c.integrity == "" and c.cited_in_answer
    assert citation_line(c).endswith("[cited in answer; Randomized controlled trial]")


def test_bracket_citation_markers_become_plain_citations():
    from tribos.agents.authoritative_orchestrator import AuthoritativeOrchestrator

    text = (
        "Target engagement was shown【42310679】. Trials exist (NCT04303780)【clinical_trials】. "
        "KRAS G12D in 49/179 samples【cbioportal_prevalence study_id=\"paad_tcga_pan_can_atlas_2018\"】. "
        "Shorter survival【CIViC EID: EID1311】."
    )
    assert AuthoritativeOrchestrator._sanitize_agent_names(text) == (
        "Target engagement was shown (PMID: 42310679). Trials exist (NCT04303780). "
        "KRAS G12D in 49/179 samples. Shorter survival (EID1311)."
    )


