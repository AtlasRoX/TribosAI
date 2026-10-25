"""VERIFY fix regressions: STEM evidence keys in the verifier (audit section 6, SUP-5 / LOG-7) and the STEM export
fields (report model reproducibility rows, simulation section, REPRODUCE.md).

Offline: hand-built tool results and manifests only.
"""

from __future__ import annotations

import io
import zipfile

from tribos.export.bundle import _reproduce_md
from tribos.export.report_model import _reproducibility, build_report_model, simulation_line
from tribos.tools.registry import ToolResult
from tribos.verify import verifier as vmod
from tribos.verify.verifier import TribosVerifier


def _lit(*passages: dict) -> ToolResult:
    return ToolResult(success=True, tool_name="archivon_literature_search", data={"ranked_passages": list(passages)})


# Evidence keys --------------------------------------------------------------------------------------------------
def test_scholarly_keys_drop_the_scheme_inside_the_value():
    assert vmod.scholarly_key("MR", "MR1234567") == "MR:1234567"
    assert vmod.scholarly_key("ZBL", "Zbl 1234.56789") == "ZBL:1234.56789"
    assert vmod.scholarly_key("ARXIV", "arXiv:2312.04511v3") == "ARXIV:2312.04511"
    assert vmod.cited_keys("see arXiv:2312.04511v2, Zbl 1234.56789, MR1234567 and DOI 10.1103/PhysRev.47.777.") == {
        "ARXIV:2312.04511", "ZBL:1234.56789", "MR:1234567", "DOI:10.1103/physrev.47.777"}


def test_a_versioned_arxiv_citation_grounds_in_an_unprefixed_arxiv_id():
    # Before the fix, a passage's arxiv_id ("1602.03837", no "arXiv:" prefix) was never observed, so a correct
    # arXiv citation was a CRITICAL identifier defect and the claim citing it was never checked.
    passage = {"arxiv_id": "1602.03837", "passage_id": "p", "title": "Observation of GW150914",
               "passage_text": "The initial black hole masses are 36 and 29 solar masses; the luminosity distance is 410 Mpc."}
    answer = "The source of GW150914 lies at a luminosity distance of 410 Mpc (arXiv:1602.03837v2)."
    report = TribosVerifier().verify_response("GW150914 distance", answer, {"archivon": _lit(passage)})
    assert not [d for d in report.defects if d.category in ("IDENTIFIER", "CITATION")]
    claim = next(c for c in report.claims if "410 Mpc" in c.claim_text)
    assert claim.claim_type == "empirical" and claim.status == "supported"
    assert claim.evidence[0].source_key == "ARXIV:1602.03837" and claim.cited_source_supported is True
    assert report.claim_support[0]["evidence_key"] == "ARXIV:1602.03837"


def test_zbmath_and_mr_records_ground_their_citations():
    passage = {"zbl_id": "Zbl 0961.11001", "mr_id": "MR1234567", "passage_id": "z",
               "passage_text": "We prove a bound on the class number of imaginary quadratic fields."}
    answer = "The class-number bound is proved in Zbl 0961.11001 and reviewed in MR1234567."
    report = TribosVerifier().verify_response("class number bound", answer, {"archivon": _lit(passage)})
    assert not [d for d in report.defects if d.category in ("IDENTIFIER", "CITATION")]


def test_biomedical_checks_are_gone():
    for name in ("extract_drug_mentions", "regimen_mismatch", "denominator_mismatch", "is_regulatory_doc",
                 "disease_families", "_PROTEIN_CHANGE_RE", "_DISEASE_LEXICON"):
        assert not hasattr(vmod, name), name
    assert "CLINICAL_CLAIM" not in vmod.DEFECT_LABELS and "POPULATION_MISMATCH" not in vmod.DEFECT_LABELS
    # A UniProt-shaped token in a STEM answer is no longer an identifier defect.
    report = TribosVerifier().verify_response("part number", "The bracket P12345 holds the sensor.", {})
    assert not [d for d in report.defects if d.category == "IDENTIFIER"]


# Export ---------------------------------------------------------------------------------------------------------
STEM_MANIFEST = {
    "tool_calls": [
        {"seq": 1, "tool_name": "dynamis_simulate_ode", "success": True,
         "inputs": {"model_name": "lorenz", "t_span": [0.0, 100.0], "method": "RK45", "parameters": {"sigma": 10}},
         "output_digest": {"solver": {"method": "RK45", "rtol": 1e-8, "atol": 1e-10}}},
        {"seq": 2, "tool_name": "calcula_run_python", "success": True, "inputs": {"code": "print(2 + 2)"}},
        {"seq": 3, "tool_name": "physis_constants", "success": True, "inputs": {"query": "G"}},
        {"seq": 4, "tool_name": "archivon_literature_search", "success": True, "inputs": {"query": "lorenz"},
         "output_digest": {"arxiv_ids": ["2312.04511"], "dois": ["10.1175/1520-0469(1963)020<0130:dnf>2.0.co;2"]}},
    ],
    # An old manifest's BioModels pin is read without error and not listed.
    "biomodels": [{"accession": "BIOMD0000000010", "latest_revision": 3}],
}


def test_reproducibility_rows_are_stem():
    rows = dict(_reproducibility(STEM_MANIFEST, {"physis": {"constants": [{"source": "NIST CODATA 2022"}]}}))
    sim = rows["Simulation (call 1, dynamis_simulate_ode)"]
    assert "lorenz" in sim and "RK45" in sim and "rtol 1e-08" in sim and "atol 1e-10" in sim and "[0, 100]" in sim
    assert rows["Sandbox code (call 2)"].startswith("sha256 ")
    assert "CODATA" in rows["Reference constants (call 3)"]
    assert "arXiv:2312.04511" in rows["Literature identifiers (call 4)"]
    assert not any("BioModels" in k for k in rows)


def test_old_vivarix_messages_and_manifests_still_export():
    msg = {"content": "x ended at 3.2", "run_manifest": STEM_MANIFEST,
           "execution_artifacts": {"vivarix": {"final_concentrations": {"Mos": 34.13}, "initial_concentrations": {"Mos": 100.0}}}}
    report = build_report_model("q", msg)
    assert report.simulation is not None and report.simulation.rows[0].variable == "Mos"
    assert not any("BioModels" in r[0] for r in report.reproducibility)


def test_simulation_section_carries_system_and_solver():
    dyn = {"model_name": "lorenz", "t_span": [0.0, 100.0], "summary": {"x": {"initial": 1.0, "final": 2.0}},
           "solver": {"method": "RK45", "rtol": 1e-8, "atol": 1e-10, "t_span": [0.0, 100.0]}}
    report = build_report_model("q", {"content": "a", "execution_artifacts": {"dynamis": dyn}})
    line = simulation_line(report.simulation)
    assert line == "System: lorenz; integrator RK45, rtol 1e-08, atol 1e-10, t from 0 to 100"


def test_reproduce_md_is_stem():
    report = build_report_model("q", {"content": "a", "run_manifest": STEM_MANIFEST})
    text = _reproduce_md(report, STEM_MANIFEST, [])
    assert "BioModels" not in text and "retract" not in text.lower() and "clinical" not in text.lower()
    for word in ("Dynamis", "rtol", "Calcula", "CODATA", "arXiv"):
        assert word in text
    from tribos.export.bundle import render_bundle

    names = zipfile.ZipFile(io.BytesIO(render_bundle(report))).namelist()
    assert "REPRODUCE.md" in names


def test_run_manifest_records_solver_tolerances_and_codata_source():
    from tribos.dynamis.engine import dynamis_simulate_ode
    from tribos.provenance.run_manifest import _DIGESTERS

    sim = _DIGESTERS["dynamis_simulate_ode"](dynamis_simulate_ode(model_name="lorenz", t_span=(0, 1), num_points=20))
    assert sim["model_name"] == "lorenz"
    assert sim["solver"]["rtol"] == 1e-8 and sim["solver"]["atol"] == 1e-10 and sim["solver"]["method"]
    consts = _DIGESTERS["physis_constants"](
        {"constants": [{"name": "speed of light in vacuum", "symbol": "c", "value": 299792458.0, "unit": "m s^-1",
                        "uncertainty": 0.0, "source": "NIST CODATA 2022"}]}
    )
    assert consts["source"] == ["NIST CODATA 2022"] and consts["constants"][0]["symbol"] == "c"
    lit = _DIGESTERS["archivon_literature_search"]({"ranked_passages": [{"zbl_id": "1234.56789", "mr_id": "1234567"}]})
    assert lit["zbl_ids"] == ["1234.56789"] and lit["mr_ids"] == ["1234567"]
