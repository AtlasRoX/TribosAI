"""Verifier grounding regressions from Tribos_Source_Audit_2026-10-18.md (findings F6-F9) and operational claims.

The FDA eligibility (F6) and disease-population (F7) checks were biomedical and are gone; the source-authority policy
they relied on is still checked here.
F8: numbers are grounded as relationships (which case, condition or regime owns a figure); an explicit relational
judge verdict is honoured.
F9: the PMID 39369609 positive control uses the real, provenance-tracked abstract (tests/fixtures/primary/).
Operational sentences (a lookup failed, a record was not retrieved) are grounded in the run's tool outcomes, never in
a scientific citation.

Offline: no network requests are made; the reserved example hosts below are only input strings.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import pytest

from tribos.tools.registry import ToolResult
from tribos.utils import source_authority as sa
from tribos.verify.verifier import (
    ClaimRecord,
    TribosVerifier,
    VerificationReport,
)

Q = "KRAS G12C inhibitors in NSCLC and colorectal cancer: FDA-approved indications and clinical evidence"
FIXTURE = Path(__file__).parent / "fixtures" / "primary" / "pmid_39369609.json"


def tool(name: str, data: dict[str, Any]) -> ToolResult:
    return ToolResult(success=True, tool_name=name, data=data)


def lit(passages: list[dict[str, Any]]) -> ToolResult:
    return tool("lithoscribe_literature_synthesis", {"ranked_passages": passages})


def claim_for(report: VerificationReport, needle: str) -> ClaimRecord:
    return next(c for c in report.claims if needle in c.claim_text)


def categories(report: VerificationReport) -> list[str]:
    return [d.category for d in report.defects]


# Source authority policy (record origin, not a quoted link) ------------------------------------------------------
SNIPPET = "Sotorasib accelerated approval for KRAS G12C-mutated NSCLC."


def test_one_authority_policy_is_shared():
    from tribos.agents import prompts
    from tribos.agents.citations import source_authority as cite_authority

    assert prompts.source_authority is sa.source_authority and cite_authority is sa.source_authority
    assert sa.source_authority("https://www.fda.gov.example.test/fake") == "web"
    assert sa.source_authority("https://fda.gov@evil.example.test") == "web"
    assert sa.source_authority("https://www.prnewswire.com/news/x") in ("vendor", "manufacturer")


# F8 (STEM): numbers are grounded as relationships (which case or condition owns a figure) -------------------------
TC_PASSAGE = {
    "arxiv_id": "2401.01234", "passage_id": "r", "title": "Synthetic: pressure dependence of Tc in a hydride film",
    "passage_text": "At ambient pressure the film has a critical temperature of 39 K; under 2 GPa the critical "
                    "temperature measured in the same cell is 41 K.",
}
WRONG_CASE = "Under 2 GPa, experiments measured a critical temperature of 39 K for the hydride film (arXiv:2401.01234)."
RIGHT_CASE = WRONG_CASE.replace("39 K", "41 K")


def _condition_judge(claim: str, passages: list[dict[str, str]]) -> dict[str, str]:
    if "39 K" in claim:
        return {"status": "unsupported",
                "reason": "condition mismatch: 39 K refers to ambient pressure, not the 2 GPa case"}
    return {"status": "supported", "reason": "matches"}


def _inconclusive_judge(claim: str, passages: list[dict[str, str]]) -> dict[str, str]:
    return {"status": "unsupported", "reason": "the excerpt does not clearly state this"}


def test_an_explicit_condition_error_from_the_judge_is_not_overridden_by_matching_numbers():
    report = TribosVerifier().verify_response(Q, WRONG_CASE, {"lit": lit([TC_PASSAGE])})
    assert claim_for(report, "39 K").status == "supported"  # the figure occurs: the deterministic check passes
    report = TribosVerifier().verify_response(Q, WRONG_CASE, {"lit": lit([TC_PASSAGE])}, entailment_judge=_condition_judge)
    c = claim_for(report, "39 K")
    assert c.status == "unsupported" and "ambient pressure" in c.reason
    assert "NUMERIC_RELATION_MISMATCH" in categories(report)
    assert c.cited_source_supported is not True


def test_an_inconclusive_judge_does_not_overturn_matching_numbers():
    report = TribosVerifier().verify_response(Q, WRONG_CASE, {"lit": lit([TC_PASSAGE])}, entailment_judge=_inconclusive_judge)
    assert claim_for(report, "39 K").status == "supported"
    assert "NUMERIC_RELATION_MISMATCH" not in categories(report)


@pytest.mark.parametrize("judge", [None, _condition_judge, _inconclusive_judge])
def test_the_correct_case_still_passes(judge):
    report = TribosVerifier().verify_response(Q, RIGHT_CASE, {"lit": lit([TC_PASSAGE])}, entailment_judge=judge)
    c = claim_for(report, "41 K")
    assert c.status == "supported", c.reason
    assert "NUMERIC_RELATION_MISMATCH" not in categories(report)


# F9: the real PMID 39369609 abstract as a provenance-tracked positive control --------------------------------------
def _fixture() -> dict[str, Any]:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def test_the_primary_fixture_is_intact_and_honest_about_the_correction():
    fx = _fixture()
    assert fx["pmid"] == "39369609" and fx["doi"] == "10.1016/j.lungcan.2024.107960"
    for line in ("2L", "2L+"):
        ex = fx["excerpts"][line]
        assert hashlib.sha256(ex["text"].encode("utf-8")).hexdigest() == ex["sha256"]
        text = ex["text"].replace(" ", " ")
        res = fx["results"][line]
        for arm in ("sotorasib", "docetaxel"):
            assert f"(N={res[arm]['n']})" in text
        assert f"{res['mortality_hr']} ({res['hr_ci'][0]}-{res['hr_ci'][1]})" in text
    assert fx["correction"]["exists"] and not fx["correction"]["content_retrieved"] and not fx["correction"]["applied"]


def _primary_passage() -> dict[str, Any]:
    fx = _fixture()
    return {"pmid": fx["pmid"], "passage_id": "abstract", "section": "abstract", "title": fx["title"],
            "passage_text": fx["excerpts"]["2L"]["text"] + " " + fx["excerpts"]["2L+"]["text"]}


def test_correct_claims_from_the_real_abstract_are_supported():
    passages = {"lit": lit([_primary_passage()])}
    claims = [
        "In the 2L setting, median overall survival was 10.2 months (95% CI 7.6-16.3) with sotorasib (N=102) versus "
        "6.0 months (95% CI 4.2-11.0) with docetaxel (N=58), mortality HR 0.62 (95% CI 0.41-0.93) (PMID: 39369609).",
        "In the 2L+ setting, median overall survival was 10.2 months (95% CI 8.0-14.6) with sotorasib (N=164) versus "
        "7.2 months (95% CI 5.1-10.6) with docetaxel (N=116), mortality HR 0.65 (95% CI 0.49-0.87) (PMID: 39369609).",
    ]
    for answer in claims:
        report = TribosVerifier().verify_response(Q, answer, passages)
        c = claim_for(report, "median overall survival")
        assert c.status == "supported", (answer, c.reason)


# Operational status sentences ------------------------------------------------------------------------------------
def test_a_failed_lookup_is_grounded_in_the_tool_outcome_not_in_a_paper():
    failed = ToolResult(success=False, tool_name="lithoscribe_literature_synthesis",
                        error="No peer-reviewed publications found in this search for: 'PMID:39369609'")
    answer = "The exact-identifier search for PMID 39369609 failed in this run."
    report = TribosVerifier().verify_response(Q, answer, {"lit": failed, "lit2": lit([_primary_passage()])})
    c = claim_for(report, "search for PMID 39369609 failed")
    assert c.claim_type == "operational"
    assert all(not (e.source_key or "").startswith(("PMID:", "DOI:")) for e in c.evidence)
    assert c.status == "supported" and c.evidence and c.evidence[0].source_key.startswith("trace:")


def test_an_operational_sentence_without_a_matching_tool_event_is_not_checked():
    answer = "The full correction document was not retrieved, so corrected content could not be applied."
    report = TribosVerifier().verify_response(Q, answer, {"lit": lit([_primary_passage()])})
    c = claim_for(report, "correction document was not retrieved")
    assert c.claim_type == "operational" and c.status == "not_checked" and "operational status" in c.reason
    assert not c.evidence


def test_surf_url_records_the_final_url_and_redirect_hops(monkeypatch):
    import asyncio

    import httpx

    from tribos.tools import web_search as ws

    async def public(_url):
        return None

    monkeypatch.setattr(ws, "_check_public_url", public)
    monkeypatch.setattr(ws, "_check_connected_peer", lambda resp, url: None)

    def handle(request: httpx.Request) -> httpx.Response:
        if request.url.host == "example.test":
            return httpx.Response(301, headers={"location": "https://www.fda.gov/drugs/sotorasib"})
        return httpx.Response(200, headers={"content-type": "text/html"},
                              text="<html><title>FDA</title><body><p>" + SNIPPET + "</p></body></html>")

    client = ws.FreeWebSearchClient(transport=httpx.MockTransport(handle))
    page = asyncio.run(client.surf_url("https://example.test/go"))
    assert page["requested_url"] == "https://example.test/go"
    assert page["final_url"] == "https://www.fda.gov/drugs/sotorasib" and page["redirects"] == [page["final_url"]]
    assert sa.source_authority(sa.record_url(page)) == "regulatory"


# Live regression (18 Oct 2026, Tribos_Next_Test_Query.txt): the answer was right but scored 0.15 because the
# retrieved erratum's PMID was "not found", the correction-status sentences were judged against the paper, and the
# "Source: abstract of PMID ...; URL: ..." lines were audited as claims. The answer text is the live run's own.
LIVE_ANSWER = Path(__file__).parent / "fixtures" / "primary" / "live_answer_pmid_39369609.md"


def _live_literature_result() -> ToolResult:
    fx = json.loads(FIXTURE.read_text(encoding="utf-8"))
    passages = [
        {"pmid": fx["pmid"], "title": fx["title"], "passage_id": f"abs-{k}", "section": "abstract", "passage_text": e["text"]}
        for k, e in fx["excerpts"].items()
    ]
    passages.append({
        "pmid": fx["pmid"], "title": fx["title"], "passage_id": "abs-design", "section": "abstract",
        "passage_text": "Observational comparative effectiveness study of pretreated KRAS G12C-mutated advanced NSCLC patients "
                        "in a US-based electronic health record-derived de-identified database, using overlap weighting "
                        "propensity score methods.",
    })
    retrieval = {"pinned": [{
        "id": fx["pmid"], "normalized": fx["pmid"], "kind": "pmid", "status": "found", "via": "europepmc",
        "corrections": [{"id": fx["correction"]["pmid"], "type": fx["correction"]["type"], "retrieved": True,
                         "content_available": False, "applied": False}],
    }]}
    return tool("lithoscribe_literature_synthesis", {"ranked_passages": passages, "retrieval": retrieval})


def test_live_answer_correction_and_source_lines_are_not_false_findings():
    answer = LIVE_ANSWER.read_text(encoding="utf-8")
    report = TribosVerifier().verify_response("Retrieve PMID 39369609", answer, {"lit": _live_literature_result()})
    descriptions = " ".join(d.description for d in report.defects)
    assert "39984314" not in descriptions  # the retrieved erratum is a retrieved record
    assert not any(c.claim_text.lstrip("*_ ").lower().startswith("source") for c in report.claims)
    corrections = [c for c in report.claims if "correction" in c.claim_text.lower()]
    assert corrections and all(c.claim_type == "operational" and c.status == "supported" for c in corrections)
    numeric = [c for c in report.claims if "102" in c.claim_text or "164" in c.claim_text]
    assert numeric and all(c.status == "supported" for c in numeric)
    assert not [c for c in report.claims if c.status in ("unsupported", "contradicted")]


LIVE_ANSWER_2 = Path(__file__).parent / "fixtures" / "primary" / "live_answer2_pmid_39369609.md"


def test_second_live_answer_erratum_linkage_and_figure_provenance_are_not_false_findings():
    # The second matched run: "A correction (erratum) exists for PMID X (linked erratum PMID Y)" is record linkage the
    # exact lookup reports, and "*All figures are taken verbatim from the abstract ...*" only locates the numbers.
    report = TribosVerifier().verify_response("Retrieve PMID 39369609", LIVE_ANSWER_2.read_text(encoding="utf-8"),
                                                {"lit": _live_literature_result()})
    erratum = claim_for(report, "erratum) exists")
    assert erratum.claim_type == "operational" and erratum.status == "supported"
    assert not any("taken verbatim" in c.claim_text for c in report.claims)
    numeric = [c for c in report.claims if "102" in c.claim_text or "164" in c.claim_text]
    assert all(c.status == "supported" for c in numeric)


def test_third_live_answer_has_no_false_findings():
    # The final matched run: its only remaining findings were "**Article:** <URL>" and "Erratum notice: PMID ..."
    # location lines. Every evidence claim in it is supported by the real abstract.
    answer = (Path(__file__).parent / "fixtures" / "primary" / "live_answer3_pmid_39369609.md").read_text(encoding="utf-8")
    report = TribosVerifier().verify_response("Retrieve PMID 39369609", answer, {"lit": _live_literature_result()})
    assert not [c for c in report.claims if c.status in ("unsupported", "contradicted")], [
        (c.status, c.claim_text[:80]) for c in report.claims if c.status != "supported"]
    assert not any(c.claim_text.lstrip("*_- ").startswith(("Article", "Erratum notice")) for c in report.claims)
