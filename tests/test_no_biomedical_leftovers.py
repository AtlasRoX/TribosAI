"""Guard against biomedical leftovers in what the models and users read (SUP-11).

Tribos is an engineering, physics and mathematics assistant. Its prompts once belonged to a biomedical product, and
stale wording there steers the model (a "phase III RCT" evidence scale, "adverse events" searches, BioModels ids).
Every module-level prompt string is checked here; a term that is legitimately needed goes in ALLOWED with a reason.
"""

from __future__ import annotations

import importlib
import re

import pytest

PROMPT_MODULES = [
    "tribos.agents.prompts",
    "tribos.agents.query_planner",
    "tribos.agents.search_plan",
    "tribos.agentic.planner",
    "tribos.agentic.router",
    "tribos.agentic.clarify",
    "tribos.agentic.counter_evidence",
    "tribos.agentic.gaps",
    "tribos.agentic.hypothesis",
    "tribos.agentic.topologies",
    "tribos.agentic.config",
    "tribos.agentic.nli",
]

BANNED = re.compile(
    r"\b(pubmed|europe ?pmc|biomodels?|chembl|clinicaltrials|clinical trials?|phase (?:i{1,3}|iv|[1-4]) |rct\b|"
    r"adverse events?|pharmacokinetic|biomarker|oncolog\w*|omics|single-cell|gene expression|knockdown|"
    r"in vivo|in vitro|patients?\b|drug-?target|fda\b)",
    re.IGNORECASE,
)

# (module, constant name) pairs allowed to mention a banned term, with the reason.
ALLOWED: dict[tuple[str, str], str] = {}


def _prompt_strings():
    for mod_name in PROMPT_MODULES:
        mod = importlib.import_module(mod_name)
        for name, value in vars(mod).items():
            if not isinstance(value, str) or len(value) < 80 or name.startswith("__"):
                continue
            if re.search(r"(PROMPT|SYSTEM|INSTRUCTION|RULES?|TEMPLATE|GUIDE)$", name):
                yield mod_name, name, value


@pytest.mark.parametrize(("module", "name", "text"), list(_prompt_strings()), ids=lambda v: str(v)[:60])
def test_prompt_has_no_biomedical_wording(module, name, text):
    if (module, name) in ALLOWED:
        pytest.skip(ALLOWED[(module, name)])
    hits = sorted({m.group(0).strip().lower() for m in BANNED.finditer(text)})
    assert not hits, f"{module}.{name} still mentions {hits}"


def test_prompts_have_no_literal_backslash_newlines():
    """A raw string ending a line with a backslash sends '\\' + newline to the model (BRK-5)."""
    for module, name, text in _prompt_strings():
        assert "\\\n" not in text, f"{module}.{name} contains a literal backslash-newline"
