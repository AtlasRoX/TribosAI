"""Context gate (query-focused extractive compression + the Lumo Admission Gate), concise answers, the paradox
guard, and the single-provider catalog (Meta muse only)."""

from __future__ import annotations

import pytest

from tribos.agents import context_gate as cg

JOURNAL = {"evidence_level": "peer-reviewed journal/conference"}
PREPRINT = {"evidence_level": "preprint"}


def _p(text, ident, **kw):
    return {"passage_text": text, "doi": ident, **kw}


def test_only_query_relevant_sentences_are_kept():
    p = _p("Cas9 cleaves DNA three base pairs upstream of the PAM. Off-target cleavage occurs at sites with up to "
           "five mismatches to the guide RNA. The authors thank the funding agency for support. Cells were cultured "
           "in DMEM with ten percent serum.", "10.1/a", **JOURNAL)
    r = cg.gate("Why does Cas9 cleave off-target sites with mismatches?", [p], budget_chars=2000)
    kept = r.texts[0]
    assert "mismatches" in kept and "funding" not in kept and "DMEM" not in kept
    assert r.chars_out < r.chars_in


def test_the_budget_limits_how_much_text_is_admitted():
    long = " ".join(f"Off-target cleavage by Cas9 was measured at site number {i} in this assay." for i in range(60))
    r = cg.gate("off-target cleavage Cas9", [_p(long, "10.1/a", **JOURNAL)], budget_chars=1000)
    assert r.chars_out <= 1000 and r.summary()["saved_pct"] > 50


def test_a_forum_post_is_quarantined_and_never_admitted():
    forum = {"passage_text": "CRISPR off-target edits never happen, trust me, I read it somewhere online.",
             "url": "https://www.reddit.com/r/biology/x"}
    r = cg.gate("Do CRISPR off-target edits happen?", [forum], budget_chars=2000)
    assert r.texts == {} and r.quarantined == 1


def test_a_retracted_paper_is_blocked():
    p = _p("CRISPR off-target edits were eliminated completely by our method.", "10.1/r", retracted=True, **JOURNAL)
    r = cg.gate("CRISPR off-target edits", [p], budget_chars=2000)
    assert r.texts == {} and r.blocked == 1


def test_independent_sources_that_agree_raise_K():
    a = _p("High-fidelity variants such as SpCas9-HF1 reduce off-target activity.", "10.1/a", **PREPRINT)
    b = _p("High-fidelity variants such as SpCas9-HF1 reduce off-target activity.", "10.1/b", **PREPRINT)
    r = cg.gate("How is off-target activity reduced?", [a, b], budget_chars=2000)
    assert [f.K for f in r.facts] == [2, 2]  # a preprint alone is K = 1; corroboration adds the other's weight


def test_two_pages_of_one_source_count_once():
    a = _p("High-fidelity variants such as SpCas9-HF1 reduce off-target activity.", "10.1/a", **PREPRINT)
    r = cg.gate("How is off-target activity reduced?", [a, dict(a)], budget_chars=2000)
    assert all(f.K == 1 for f in r.facts)


def test_equal_sources_that_contradict_are_both_withheld():
    a = _p("The tensile strength of the 7075 aluminium alloy is 450 MPa.", "10.1/a", **JOURNAL)
    b = _p("The tensile strength of the 7075 aluminium alloy is 570 MPa.", "10.1/b", **JOURNAL)
    r = cg.gate("tensile strength of the 7075 aluminium alloy", [a, b], budget_chars=2000)
    assert r.texts == {} and r.quarantined == 2


@pytest.mark.parametrize("a,b,expected", [
    ("Water boils at 100 degrees Celsius at a pressure of 1 atm.", "Water boils at 120 degrees Celsius at a pressure of 2 atm.", "new"),
    ("Water boils at 100 degrees Celsius at a pressure of 1 atm.", "Water boils at 105 degrees Celsius at a pressure of 1 atm.", "conflict"),
    ("The tensile strength of the alloy is 450 MPa.", "The tensile strength of the alloy is 450 MPa.", "same"),
    ("The tensile strength of the alloy is 450 MPa.", "Graphene has a Young's modulus near 1 TPa.", "new"),
])
def test_relate_tells_conflicts_from_different_conditions(a, b, expected):
    assert cg.relate(a, b) == expected


def test_the_evidence_block_carries_only_gated_text(monkeypatch):
    from tribos.agents.prompts import build_evidence_block
    from tribos.tools.registry import ToolResult

    passages = [
        {"passage_text": "Off-target cleavage occurs at sites with up to five mismatches to the guide RNA. The "
                         "authors thank the funding agency.", "doi": "10.1/a", "citation": "A 2020",
         "evidence_level": "peer-reviewed journal/conference"},
        {"passage_text": "Off-target edits never happen.", "url": "https://www.reddit.com/r/x", "citation": "forum"},
    ]
    results = {"archivon": ToolResult(success=True, tool_name="archivon", data={"ranked_passages": passages})}
    report: dict = {}
    block = build_evidence_block(results, "", query="Why does off-target cleavage occur with mismatches?",
                                 gate_report=report)
    assert "five mismatches" in block and "funding agency" not in block and "never happen" not in block
    assert report["admitted"] >= 1 and report["quarantined"] == 1
    monkeypatch.setenv("TRIBOS_CONTEXT_GATE", "0")
    ungated = build_evidence_block(results, "", query="Why does off-target cleavage occur with mismatches?")
    assert "funding agency" in ungated


def test_nothing_relevant_falls_back_to_the_excerpted_passages():
    from tribos.agents.prompts import build_evidence_block
    from tribos.tools.registry import ToolResult

    passages = [{"passage_text": "Graphene is a two-dimensional carbon allotrope with high conductivity.",
                 "doi": "10.1/g", "citation": "G", "evidence_level": "peer-reviewed journal/conference"}]
    results = {"archivon": ToolResult(success=True, tool_name="archivon", data={"ranked_passages": passages})}
    report: dict = {}
    block = build_evidence_block(results, "", query="zzz qqq", gate_report=report)
    assert "two-dimensional carbon" in block and report.get("fallback")


def test_concise_answers_are_the_default(monkeypatch):
    from tribos.agents.prompts import answer_style, build_synthesis_request

    monkeypatch.delenv("TRIBOS_ANSWER_STYLE", raising=False)
    assert answer_style() == "concise"
    req = build_synthesis_request("<evidence/>", "<tool_status/>", "", "What is g?", answer_style="concise")
    assert "Answer exactly what the question asks" in req and req.index("answer_length") < req.index("<user_query")
    full = build_synthesis_request("<evidence/>", "<tool_status/>", "", "What is g?", answer_style="full")
    assert "answer_length" not in full
    monkeypatch.setenv("TRIBOS_ANSWER_STYLE", "full")
    assert answer_style() == "full"


@pytest.mark.parametrize("query,expected", [
    ("This statement is false.", True),
    ("Will you answer 'no' to this question?", True),
    ("Is this statement about CRISPR off-target edits true?", False),
    ("Why is the liar paradox neither true nor false?", False),
])
def test_the_paradox_guard(query, expected):
    assert cg.is_self_referential(query) is expected


def test_a_paradox_gets_the_fixed_K0_reply():
    from tribos.agents.authoritative_orchestrator import PARADOX_REPLY, _non_research_reply

    assert _non_research_reply("This statement is false.", "paradox") == PARADOX_REPLY
    assert "K = 0" in PARADOX_REPLY


def test_the_catalog_offers_only_meta_muse():
    from tribos.utils.llm.llm_factory import SUPPORTED_MODELS, fallback_enabled

    assert [m["id"] for m in SUPPORTED_MODELS] == ["muse-spark-1.3"]
    assert not fallback_enabled()  # no silent gpt-4o substitution


@pytest.mark.parametrize("question,runs", [
    ("Prove that the sum of two odd integers is even.", False),
    ("Give a formal proof in Lean that the sum of two odd integers is even.", True),
    ("Prove, machine-checked, that 2 + 2 = 4.", True),
    ("Formally verify that sqrt(2) is irrational.", True),
])
def test_lean_runs_only_when_a_formal_proof_is_asked_for(monkeypatch, question, runs):
    from types import SimpleNamespace

    from tribos.agentic import formal_proof

    monkeypatch.delenv("TRIBOS_FORMAL_MODE", raising=False)
    monkeypatch.setattr(formal_proof, "formal_enabled", lambda: True)
    state = SimpleNamespace(clean_query=question, query=question, bag={})
    assert formal_proof.FormalProofPhase().applies(state) is runs
    if not runs:
        assert "not asked for" in state.bag["formal_skipped"]
    monkeypatch.setenv("TRIBOS_FORMAL_MODE", "auto")
    assert formal_proof.FormalProofPhase().applies(state) is True


def test_the_writer_may_draw_charts_and_equations_from_the_evidence():
    from tribos.writer.genui import sanitize_ui_blocks

    chart = ('```ui\n{"type":"chart","title":"Speed","x":{"label":"t","unit":"s"},"y":{"label":"v","unit":"m/s"},'
             '"series":[{"name":"v","points":[[0,0],[1,9.81],[2,19.62]]}]}\n```')
    evidence = "t = 0 s: v = 0; t = 1 s: v = 9.81; t = 2 s: v = 19.62"
    out, removed = sanitize_ui_blocks("The speed grows linearly.\n\n" + chart, evidence)
    assert '"type": "chart"' in out and not removed
    invented = chart.replace("19.62", "25.5")
    out, removed = sanitize_ui_blocks("The speed grows linearly.\n\n" + invented, evidence)
    assert '"type": "chart"' not in out and "numbers not in the evidence" in removed[0]
    eq = '```ui\n{"type":"equation","title":"Kinetic energy","latex":"E = \\frac{1}{2} m v^2"}\n```'
    out, removed = sanitize_ui_blocks("The energy is quadratic in v.\n\n" + eq, "E = 1/2 m v^2")
    assert '"type": "equation"' in out and '"checks": []' in out


def test_the_answer_instructions_offer_every_block_type():
    from tribos.agents.prompts import SYNTHESIS_SYSTEM_PROMPT

    for kind in ("stats", "steps", "table", "chart", "equation", "callout"):
        assert f'"type":"{kind}"' in SYNTHESIS_SYSTEM_PROMPT
