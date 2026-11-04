"""Research-loop verification semantics after the audit (AUDIT-104, 106, 107, 110, 112)."""

from __future__ import annotations

import asyncio
import json
import zipfile
from io import BytesIO

from tribos.agentic.research import ledger as lg
from tribos.agentic.research.judge import apply_judgement
from tribos.agentic.research.manifest import environment_manifest, manifest_markdown

LEDGER = [{"id": "F1", "test_id": "T1", "status": "passed", "tier": "replicated",
           "quantities": [{"name": "max_stopping_time", "value": 329}, {"name": "argmax_n", "value": 837799}]}]


# --- AUDIT-104 / 112: numbers bound to their quantities --------------------------------------------------------------

def test_swapped_quantities_are_flagged():
    bad = lg.misattributed_numbers("The maximum stopping time is 837,799 and it occurs at n = 329.", LEDGER)
    assert len(bad) == 1 and bad[0].startswith("837,799") and "argmax_n" in bad[0]


def test_correctly_attributed_numbers_and_sentences_naming_nothing_pass():
    assert lg.misattributed_numbers("The maximum stopping time is 329, attained at argmax n = 837,799.", LEDGER) == []
    assert lg.misattributed_numbers("We ran 837,799 trials in total.", LEDGER) == []


def test_a_grouped_number_followed_by_a_comma_is_one_number():
    ev = lg.evidence_numbers("argmax n = 837,799")
    assert lg.unsupported_numbers("It occurs at n = 837,799, as computed.", ev) == []
    assert lg._NUMBER_RE.findall("1,234,567 and 12,34") == ["1,234,567", "12", "34"]


# --- AUDIT-106: verdicts need relevant, adequate, non-contradictory evidence ----------------------------------------

def _campaign(findings):
    return {"charter": {
        "deliverables": [{"id": "D1", "title": "count", "tier": "computed", "status": "open"},
                         {"id": "D2", "title": "other", "tier": "computed", "status": "open"}],
        "hypotheses": [{"id": "H1", "statement": "h", "verdict": "untested"}],
        "tests": [{"id": "T1", "serves": ["D1"], "hypotheses": ["H1"]}, {"id": "T2", "serves": ["D2"], "hypotheses": []},
                  {"id": "T3", "serves": ["D1"], "hypotheses": ["H1"]}]},
        "ledger": findings}


def test_a_deliverable_is_not_done_on_another_deliverables_finding():
    c = _campaign([{"id": "F2", "test_id": "T2", "status": "passed", "tier": "replicated"}])
    apply_judgement(c, {"deliverables": [{"id": "D1", "status": "done", "evidence": ["F2"]}]})
    d1 = c["charter"]["deliverables"][0]
    assert d1["status"] == "open" and "other deliverables" in d1["note"]
    apply_judgement(c, {"deliverables": [{"id": "D2", "status": "done", "evidence": ["F2"]}]})
    assert c["charter"]["deliverables"][1]["status"] == "done"


def test_supported_cannot_cite_a_refuting_finding_or_rest_on_argument_alone():
    c = _campaign([{"id": "F1", "test_id": "T1", "status": "passed", "tier": "computed"},
                   {"id": "F3", "test_id": "T3", "status": "refuted", "tier": "none"}])
    apply_judgement(c, {"hypotheses": [{"id": "H1", "verdict": "supported", "evidence": ["F1", "F3"]}]})
    h = c["charter"]["hypotheses"][0]
    assert h["verdict"] == "undecided" and "refutes" in h["note"]
    c = _campaign([{"id": "F1", "test_id": "T1", "status": "passed", "tier": "reasoned"}])
    apply_judgement(c, {"hypotheses": [{"id": "H1", "verdict": "supported", "evidence": ["F1"]}]})
    assert c["charter"]["hypotheses"][0]["verdict"] == "undecided"
    c = _campaign([{"id": "F1", "test_id": "T1", "status": "passed", "tier": "computed"}])
    apply_judgement(c, {"hypotheses": [{"id": "H1", "verdict": "supported", "evidence": ["F1"]}]})
    assert c["charter"]["hypotheses"][0]["verdict"] == "supported"
    c = _campaign([{"id": "F3", "test_id": "T3", "status": "refuted", "tier": "none"}])
    apply_judgement(c, {"hypotheses": [{"id": "H1", "verdict": "refuted", "evidence": ["F3"]}]})
    assert c["charter"]["hypotheses"][0]["verdict"] == "refuted"


# --- AUDIT-107: certified is reachable (exact integers reproduced exactly) -------------------------------------------

def test_exact_integer_results_reproduced_exactly_are_certified_and_floats_stay_replicated(monkeypatch, tmp_path):
    from tribos.agentic.research import runner

    def fake_codeact(results):
        calls = iter(results)

        async def codeact(model, prompt, *, quantities, steps, effort, timeout_s, replicate, on_cell):
            res = next(calls)
            return {"cells": [{"code": "result = ...", "stdout": "", "status": "ok"}], "ok_cells": 1}, res, []
        return codeact

    test = {"id": "T1", "title": "count records", "kind": "compute", "objective": "count", "tier": "replicated", "quantities": ["n_records", "mean_value"]}
    kw = {"goal": "g", "context": "", "finding_id": "F1", "files_dir": str(tmp_path), "steps": 2, "effort": "low",
          "timeout_s": 30, "cross_check": True}
    monkeypatch.setattr(runner, "_codeact", fake_codeact([{"n_records": 44}, {"n_records": 44}]))
    test_int = {**test, "quantities": ["n_records"]}
    f = asyncio.run(runner.run_compute(object(), test_int, **kw))
    assert f["tier"] == "certified" and any(c["name"] == "exact arithmetic" for c in f["checks"])
    assert f["replication"]["same_model"] is True
    monkeypatch.setattr(runner, "_codeact", fake_codeact([{"mean_value": 39.889}, {"mean_value": 39.889}]))
    f = asyncio.run(runner.run_compute(object(), {**test, "quantities": ["mean_value"]}, **kw))
    assert f["tier"] == "replicated"


# --- AUDIT-110: the environment manifest ----------------------------------------------------------------------------

def test_the_manifest_records_versions_models_sandbox_and_limits():
    m = environment_manifest({"campaign_id": "cmp_x", "model": "muse-spark-1.3", "review": {"finished_at": 1.7e9}},
                             [{"title": "Lagarias 1985", "url": "https://example.org/p"}])
    assert m["software"]["python"] and m["libraries"]["numpy"] and m["models"]["research"] == "muse-spark-1.3"
    assert m["sources"][0]["retrieved_at"].startswith("2023-") and "language model" in m["limits"]
    assert "backend" in m["sandbox"] or "error" in m["sandbox"]
    text = manifest_markdown(m)
    assert "Libraries:" in text and "Limits of the automatic checks" in text


def test_the_bundle_carries_manifest_json(tmp_path):
    from tribos.export.thesis import thesis_bundle

    campaign = {"campaign_id": "cmp_x", "goal": "g", "charter": {}, "ledger": [], "rounds": [],
                "thesis": {"markdown": "# t", "environment": {"software": {"tribos": "1"}, "limits": "x"}}}
    with zipfile.ZipFile(BytesIO(thesis_bundle(campaign, str(tmp_path)))) as z:
        assert json.loads(z.read("manifest.json"))["software"]["tribos"] == "1"
        assert "manifest.json" in z.read("README.md").decode()


# --- AUDIT-111: a refuted identity over all reals is FAILED, not inconclusive ----------------------------------------

def test_an_identity_claimed_for_all_reals_that_fails_at_a_negative_value_is_failed():
    from tribos.verify.math_claims import audit_answer

    for text in (r"Therefore $\sqrt{x^2} = x$ for all real $x$.", r"Hence $|x| = x$ for all real $x$.",
                 r"So $\sqrt{x^2} = x$ for $x \in \mathbb{R}$."):
        statuses = [c.status for c in audit_answer(text).claims]
        assert "failed" in statuses, (text, statuses)
    # With no stated domain the variable may be a positive quantity (a length): not refuted, only undecided.
    statuses = [c.status for c in audit_answer(r"Therefore $\sqrt{x^2} = x$.").claims]
    assert "failed" not in statuses and "passed" not in statuses, statuses
