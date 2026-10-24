"""The one sentence splitter (tribos.utils.text.sentence_spans) and the one source-name registry
(tribos.sources.names), and the call sites that now use them."""

from __future__ import annotations

from tribos.agentic import nli
from tribos.agentic.counter_evidence import _sentences as counter_sentences
from tribos.agentic.gaps import hedged_sentences
from tribos.agents import citations
from tribos.evals import scoring
from tribos.export.report_model import _reproducibility


def _section_sentences(text_val: str) -> list[str]:
    from tribos.utils import text as text_mod
    return [text_val[s:e].strip() for s, e in text_mod.sentence_spans(text_val) if len(text_val[s:e].split()) >= 5]
from tribos.sources import names
from tribos.utils import text
from tribos.utils.memory.research_memory import classify_instructions
from tribos.verify import verifier


def _cut(t: str):
    return [t[s:e] for s, e in text.sentence_spans(t)]


# --- sentence splitter -------------------------------------------------------------------------------------------

def test_sentence_spans_lives_in_utils_text_and_is_reexported():
    assert verifier.sentence_spans is text.sentence_spans
    assert citations.sentence_spans is text.sentence_spans


def test_sentence_spans_abbreviations_newlines_and_tables():
    assert _cut("Smith et al. found it. Next one, e.g. this. Fig. 2 shows it.") == [
        "Smith et al. found it.", "Next one, e.g. this.", "Fig. 2 shows it.",
    ]
    # "No." ends a sentence unless a number follows.
    assert _cut("It did not. No. 5 did.") == ["It did not.", "No. 5 did."]
    assert _cut("Heading\n\nFirst. Second!") == ["Heading", "First.", "Second!"]
    assert _cut("| a. b | c. d |\nAfter.") == ["| a. b | c. d |", "After."]
    assert text.sentence_spans("") == [] and text.sentence_spans("   \n ") == []


def test_verifier_split_sentences_matches_spans():
    t = "KRAS G12C is common. Sotorasib (e.g. in CodeBreaK) works.\n- A bullet."
    assert verifier.TribosVerifier._split_sentences(t) == [s.strip() for s in _cut(t)]


def test_nli_split_sentences_uses_shared_splitter():
    t = "Response was seen, e.g. in mice. p53 loss followed.\nNew line."
    assert nli.split_sentences(t) == ["Response was seen, e.g. in mice.", "p53 loss followed.", "New line."]
    assert nli.split_sentences(None) == []  # type: ignore[arg-type]


def test_counter_evidence_sentences_keep_five_word_filter_and_abbreviations():
    t = "Too short here. Smith et al. reported a negative phase 3 trial. Another long enough sentence is here."
    assert counter_sentences(t) == [
        "Smith et al. reported a negative phase 3 trial.", "Another long enough sentence is here.",
    ]


def test_hedged_sentences_split_by_shared_splitter():
    draft = "Efficacy is unclear in KRAS mutant tumours, e.g. in PDAC. Sotorasib is approved for NSCLC."
    assert hedged_sentences(draft) == ["Efficacy is unclear in KRAS mutant tumours, e.g. in PDAC."]


def test_section_sentences_filter_and_abbreviations():
    body = "Short one. Smith et al. showed that the inhibitor reduced growth. Another sentence that is long enough."
    assert _section_sentences(body) == [
        "Smith et al. showed that the inhibitor reduced growth.", "Another sentence that is long enough.",
    ]


def test_kept_local_splitters_differ_on_purpose():
    # Memory splits at ';' so each clause is its own instruction with its own scope.
    scopes = dict(classify_instructions("Only use human data; from now on exclude preprints."))
    assert scopes == {"Only use human data;": "current_turn", "from now on exclude preprints.": "investigation"}
    # The refusal check reads across a leading heading line (no newline break).
    assert scoring.opens_with_refusal("## Answer\nNo relevant evidence was retrieved. More text.")


# --- source registry ---------------------------------------------------------------------------------------------

def test_public_names_and_aliases():
    assert names.public_name("synapta") == "OpenTargets/KEGG"
    assert names.public_name("clinical_trials") == names.public_name("clinicaltrials") == "ClinicalTrials.gov"
    assert names.public_name("structure_intel") == names.public_name("structintel") == "AlphaFold DB / RCSB PDB"
    assert names.public_name("chembl") == "ChEMBL"
    assert names.public_name("openfda") == "openFDA"
    assert names.public_name("pubtator") == "PubTator3/LitVar2"
    assert names.public_name("websurfer") == "web search"
    assert names.public_name("nope") is None and names.public_name("nope", "x") == "x"
    assert names.public_name(None) is None
    assert names.agent_label("chembl") == "Synapta" and names.agent_label("openfda") == "Lithoscribe"
    assert names.version_label("clinicaltrials") == "ClinicalTrials.gov data timestamp"
    assert names.description("primekg") == "PrimeKG knowledge-graph analysis"
    assert set(names.INTERNAL_ONLY_KEYS).isdisjoint(names.SOURCE_REGISTRY)


def test_report_reproducibility_labels_unchanged():
    versions = {k: {"value": "v1"} for k in ("opentargets", "kegg", "europepmc", "clinicaltrials", "chembl", "openfda", "other")}
    rows = _reproducibility({"source_versions": versions})
    assert [r[0] for r in rows] == [
        "Open Targets data release", "KEGG last update", "EuropePMC API version", "ClinicalTrials.gov data timestamp",
        "ChEMBL release", "openFDA last updated", "other",
    ]
