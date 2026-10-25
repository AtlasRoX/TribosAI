"""Evidence-integrity regressions: which evidence may support which claim, figure matching with units, and pooling
of one article's passages. STEM equivalents of the earlier run-review findings E1-E3 (the regulatory, disease and
regimen checks were biomedical and are gone).

Offline: the verifier is exercised directly with hand-built tool results. Hand-built passages are parser and policy
fixtures, not scientific gold.
"""

from __future__ import annotations

from typing import Any

from tribos.tools.registry import ToolResult
from tribos.utils.text import fold_typography, fold_typography_with_map
from tribos.verify import verifier as vmod
from tribos.verify.verifier import ClaimRecord, TribosVerifier, VerificationReport

Q = "Critical temperature of YBCO thin films: measured values and simulations"


def lit(passages: list[dict[str, Any]]) -> ToolResult:
    return ToolResult(success=True, tool_name="archivon_literature_search", data={"ranked_passages": passages})


def tool(name: str, data: dict[str, Any]) -> ToolResult:
    return ToolResult(success=True, tool_name=name, data=data)


def claim_for(report: VerificationReport, needle: str) -> ClaimRecord:
    return next(c for c in report.claims if needle in c.claim_text)


def categories(report: VerificationReport) -> list[str]:
    return [d.category for d in report.defects]


# A measured value needs an observation, not a computation ------------------------------------------------------
MEASURED = "Resistivity experiments measured a critical temperature of 92 K for the YBCO film."
SIMULATION = tool("dynamis_simulate_ode", {
    "model_name": "YBCO film resistivity critical temperature", "description": "ybco film critical temperature 92 K",
})


def test_a_simulation_cannot_support_a_measured_value():
    report = TribosVerifier().verify_response(Q, MEASURED, {"dynamis": SIMULATION})
    c = claim_for(report, "92 K")
    assert c.status == "unsupported" and "predictions, not measurements" in c.reason
    assert not any(e.source_key == "tool:dynamis" for e in c.evidence)


def test_a_paper_reporting_the_measurement_supports_it():
    paper = lit([{"arxiv_id": "2401.00011", "passage_id": "p1", "title": "Transport in YBCO films",
                  "passage_text": "Resistivity measurements of the YBCO film give a critical temperature of 92 K."}])
    report = TribosVerifier().verify_response(Q, MEASURED, {"dynamis": SIMULATION, "archivon": paper})
    c = claim_for(report, "92 K")
    assert c.status == "supported" and c.evidence[0].source_key == "ARXIV:2401.00011"


def test_a_computed_value_may_rest_on_the_simulation():
    computed = "The simulated YBCO film resistivity model gives a critical temperature of 92 K."
    report = TribosVerifier().verify_response(Q, computed, {"dynamis": SIMULATION})
    assert "predictions, not measurements" not in " ".join(c.reason for c in report.claims)


# Cited source that does not support the claim (arXiv keys) -----------------------------------------------------
def test_support_from_another_paper_than_the_cited_one_is_recorded():
    passages = lit([
        {"arxiv_id": "2401.00111", "passage_id": "a", "title": "Growth of YBCO films by pulsed laser deposition",
         "passage_text": "YBCO films were grown on SrTiO3 substrates by pulsed laser deposition."},
        {"arxiv_id": "2401.00222", "passage_id": "b", "title": "Critical currents in YBCO films",
         "passage_text": "The YBCO films reached a critical current density of 3.2 MA/cm^2 at 77 K."},
    ])
    answer = "The YBCO films reached a critical current density of 3.2 MA/cm^2 at 77 K (arXiv:2401.00111)."
    report = TribosVerifier().verify_response(Q, answer, {"lit": passages})
    c = claim_for(report, "3.2 MA")
    assert c.status == "supported" and c.evidence[0].source_key == "ARXIV:2401.00222"
    assert c.cited_source_supported is False and "not by the cited ARXIV:2401.00111" in c.reason
    assert "CITATION_MISMATCH" in categories(report)

    right = answer.replace("2401.00111", "2401.00222v2")  # a version suffix names the same paper
    report = TribosVerifier().verify_response(Q, right, {"lit": passages})
    c = claim_for(report, "3.2 MA")
    assert c.cited_source_supported is True and "CITATION_MISMATCH" not in categories(report)
    assert report.claim_support and report.claim_support[0]["evidence_key"] == "ARXIV:2401.00222"


def test_a_doi_alias_of_the_passage_counts_as_citing_it():
    passages = lit([{"arxiv_id": "2401.00333", "doi": "10.1103/PhysRevB.99.000001", "passage_id": "d",
                     "passage_text": "The YBCO film showed a critical temperature of 91.5 K in resistivity measurements."}])
    answer = "Resistivity measurements gave a critical temperature of 91.5 K for the YBCO film (DOI 10.1103/PhysRevB.99.000001)."
    report = TribosVerifier().verify_response(Q, answer, {"lit": passages})
    c = claim_for(report, "91.5 K")
    assert c.status == "supported" and c.cited_source_supported is True
    assert c.evidence[0].source_key == "DOI:10.1103/physrevb.99.000001"


# Figures are matched with their units ---------------------------------------------------------------------------
ABSTRACT = {
    "arxiv_id": "2401.00444", "passage_id": "abs", "section": "abstract",
    "title": "Synthetic 2024: transport in a YBCO film",
    "passage_text": "The film shows a critical temperature of 92·1 K (95% CI 91·8–92·4) and a gap of 20 meV, while the "
                    "control film reached 88 K.",
}


def test_middle_dot_decimals_and_units_are_supported():
    claim = "Experiments measured a critical temperature of 92.1 K (95% CI 91.8–92.4) for the YBCO film (arXiv:2401.00444)."
    report = TribosVerifier().verify_response(Q, claim, {"lit": lit([ABSTRACT])})
    c = claim_for(report, "92.1 K")
    assert c.status == "supported", c.reason
    assert c.cited_source_supported is True


def test_the_right_number_with_the_wrong_unit_is_not_supported():
    for wrong in ("a gap of 20 K", "a critical temperature of 92.1 mK"):
        claim = f"Experiments measured {wrong} for the YBCO film (arXiv:2401.00444)."
        report = TribosVerifier().verify_response(Q, claim, {"lit": lit([ABSTRACT])})
        assert next(c for c in report.claims if c.claim_type == "empirical").status == "unsupported", wrong
    # Unambiguous SI prefixes are scaled to the base unit; "m" (milli or mega once lower-cased) is compared as written.
    metrics = TribosVerifier._claim_metrics("a gap of 20 keV and 92 K")
    assert [(m.unit, m.scale) for m in metrics if m.kind == "qty"] == [("ev", 1e3), ("k", 1.0)]


def test_a_derived_figure_is_not_a_figure_from_the_source():
    metrics = TribosVerifier._claim_metrics("Using g = 9.81 m/s^2 (arXiv:2401.00444), T = 2π√(L/g) = 2.006 s.")
    assert [m.label for m in metrics if m.kind == "qty"] == ["9.81 m/s^2"]


def test_figures_split_across_two_passages_of_one_article_are_supported():
    passages = lit([
        {"arxiv_id": "2401.00555", "passage_id": "p1", "title": "YBCO film transport",
         "passage_text": "Resistivity measurements give a critical temperature of 92 K for the film."},
        {"arxiv_id": "2401.00555", "passage_id": "p2", "title": "YBCO film transport",
         "passage_text": "Tunnelling spectroscopy of the same film shows a superconducting gap of 20 meV."},
    ])
    answer = "The measured critical temperature of the film is 92 K with a superconducting gap of 20 meV (arXiv:2401.00555)."
    report = TribosVerifier().verify_response(Q, answer, {"lit": passages})
    assert claim_for(report, "92 K").status == "supported"
    # Passages of a different article never pool with this one.
    other = lit([dict(passages.data["ranked_passages"][0]),
                 dict(passages.data["ranked_passages"][1], arxiv_id="2401.00666")])
    report = TribosVerifier().verify_response(Q, answer, {"lit": other})
    assert claim_for(report, "92 K").status == "unsupported"


def test_unit_written_once_after_an_interval_an_uncertainty_or_a_comparator():
    assert vmod.attach_units("92 (95% ci 90-94) K") == "92 K (95% ci 90-94)"
    assert vmod.attach_units("88 vs 92 K") == "88 K vs 92 K"
    assert vmod.attach_units("92 ± 2 K") == "92 K ± 2 K"
    assert vmod.attach_units("10.2 (95% ci 8.1-12.0) months") == "10.2 months (95% ci 8.1-12.0)"
    doc = vmod._Doc("ARXIV:2401.00777", "the film's critical temperature was 92 (95% ci 90-94) k.", None, "")
    status = TribosVerifier()._empirical_verdict(
        "The film's critical temperature was 92 K (arXiv:2401.00777).", {"ARXIV:2401.00777"}, [doc]
    )
    assert status[0] == "supported"


def test_middle_dot_decimals_fold_only_between_digits():
    assert fold_typography("10·2 K · 8 passages") == "10.2 K · 8 passages"
    folded, offsets = fold_typography_with_map("a 1·5 b")
    assert folded == "a 1.5 b" and len(offsets) == len(folded) + 1
