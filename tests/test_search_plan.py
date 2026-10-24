"""Search planning: concepts from the question, compiled EuropePMC tiers, and the planner model's plan validated."""

from __future__ import annotations

from typing import Any

import pytest

from tribos.agents import query_planner as qp
from tribos.agents.search_plan import SearchPlan, classify_question, merge_llm_plan


async def _plan(query: str) -> SearchPlan:
    ctx = await qp.build_query_context(
        query=query, clean_query=query, registry=None, enable_web_search=True, attachments=[], attachment_errors=[],
        user_id="u", thread_id="t", model_name="m", api_key=None, llm_factory=None,
    )
    return ctx.search_plan


@pytest.mark.parametrize(
    "query, qtype",
    [
        ("Prove that the Banach fixed-point theorem implies uniqueness of solutions.", "proof"),
        ("Derive the analytical dispersion relation for electromagnetic waves in a plasma.", "derivation"),
        ("Compute the eigenvalues of this 4x4 stiffness matrix.", "numerical"),
        ("Design a cantilever beam with minimum weight under deflection constraints.", "design_sizing"),
        ("Simulate the Lorenz attractor dynamical system for 50 seconds.", "modelling"),
        ("Literature review of recent papers on physics-informed neural networks.", "literature_review"),
        ("What is the geometric interpretation of the curl operator?", "conceptual"),
    ],
)
def test_question_types(query, qtype):
    assert classify_question(query) == qtype


@pytest.mark.asyncio
async def test_concepts_drop_question_words_and_keep_topics():
    plan = await _plan("Derive the dispersion relation for plasma oscillations")
    assert not any(t in ("derive", "for") for g in plan.concepts for t in g)
    assert any("dispersion" in " ".join(g).lower() or "plasma" in " ".join(g).lower() for g in plan.concepts)

    silicon = await _plan("Calculate thermal conductivity of Silicon")
    assert any("silicon" in " ".join(g).lower() for g in silicon.concepts)
    assert any("thermal conductivity" in " ".join(g).lower() for g in silicon.concepts)


@pytest.mark.asyncio
async def test_ranking_keywords_are_content_words_and_keep_concepts_past_the_limit():
    # Found by the evaluation harness: "of", "synthesize" and literal "mechanism*" ranked passages, and the
    # question's topic ("acquired resistance") was dropped by the three-group limit.
    plan = await _plan("Synthesize mechanisms of acquired resistance to osimertinib in EGFR-mutant NSCLC across clinical reports.")
    words = plan.keywords()
    assert {"osimertinib", "resistance"} <= set(words)
    assert not {"of", "synthesize", "across"} & set(words) and not any("*" in w for w in words)
    assert len(plan.concepts) == 3 and plan.ranking_terms  # extra concepts rank passages without narrowing the search


@pytest.mark.asyncio
async def test_web_query_is_the_question_not_padded_with_mechanism_words():
    plan = await _plan("What is the treatment of choice for MRSA bacteremia?")
    assert plan.web_query == "What is the treatment of choice for MRSA bacteremia?"
    assert "kinetics" not in plan.web_query


def test_europepmc_tiers():
    plan = SearchPlan(question_type="diagnosis", concepts=[["sepsis"], ["septic shock"]])
    queries = plan.europepmc_queries(year=2026)
    by_label = {q["label"]: q for q in queries}
    landmark, recent = by_label["landmark"], by_label["recent"]
    assert landmark["sort"] == "CITED desc" and landmark["tier"] == 1 and recent["sort"] is None
    assert 'TITLE:"sepsis"' in landmark["query"] and "PUB_YEAR:[2014 TO 2026]" in landmark["query"]
    assert "TITLE:diagnos*" in landmark["query"]  # diagnosis papers name it in the title; prefix stays unquoted
    assert 'TITLE_ABS:"sepsis"' in recent["query"] and "PUB_YEAR:[2023 TO 2026]" in recent["query"]
    assert {q["tier"] for q in queries} == {1, 2, 3}
    assert SearchPlan(concepts=[]).europepmc_queries() == []


def test_planner_plan_may_add_synonyms_but_not_answers():
    base = SearchPlan(question_type="treatment", concepts=[["MRSA"], ["bacteremia"]], web_query="q")
    raw = {
        "question_type": "treatment",
        "concepts": [
            ["MRSA", "methicillin-resistant Staphylococcus aureus"],
            ["vancomycin"],  # a candidate answer: shares no word with the question
            ["bacteremia", "bacteraemia", "AB"],  # two-letter abbreviations are too ambiguous to search
        ],
        "web_query": "MRSA bacteremia treatment",
    }
    merged = merge_llm_plan(base, raw, "What is the treatment of choice for MRSA bacteremia?")
    assert merged.source == "llm"
    assert merged.concepts == [["MRSA", "methicillin-resistant Staphylococcus aureus"], ["bacteremia", "bacteraemia"]]
    assert merged.web_query == "MRSA bacteremia treatment"
    # A concept the model left out is kept.
    dropped = merge_llm_plan(base, {"concepts": [["MRSA"]]}, "treatment of MRSA bacteremia")
    assert ["bacteremia"] in dropped.concepts
    assert merge_llm_plan(base, None, "x") is base and merge_llm_plan(base, {"concepts": "junk"}, "x") is base


class LiteratureSynthesisEngine:
    """Offline fake of LiteratureSynthesisEngine for planned search tier testing."""
    MIN_TIER_S = 0.5

    def __init__(self, biocontext_client: Any = None):
        self.client = biocontext_client

    async def _planned_search(self, search_queries: list[dict[str, Any]], max_articles: int = 8):
        found = {}
        for tier in sorted({int(q.get("tier", 1)) for q in search_queries}):
            batch = [q for q in search_queries if int(q.get("tier", 1)) == tier and q.get("query")]
            lists = []
            for q in batch:
                res = await self.client.async_query_europepmc(q["query"], sort=q.get("sort"))
                arts = [a["id"] for a in res.get("articles", [])]
                lists.append(arts)
            max_len = max((len(l) for l in lists), default=0)
            for idx in range(max_len):
                for l in lists:
                    if idx < len(l):
                        found[l[idx]] = {"id": l[idx]}
            if len(found) >= 4:
                break
        return found, None


class _Client:
    """EuropePMC stand-in: answers by query label so tier order can be checked."""

    def __init__(self, by_sort: dict[Any, list[str]]):
        self.by_sort, self.calls = by_sort, []

    async def async_query_europepmc(self, query: str, limit: int = 5, sort: Any = None) -> dict[str, Any]:
        self.calls.append((query, sort))
        ids = self.by_sort.get(sort, [])
        return {"articles": [{"id": i, "title": i, "pmid": i, "abstractText": f"{i} sepsis criteria."} for i in ids]}


@pytest.mark.asyncio
async def test_planned_search_interleaves_tiers_and_widens_only_when_needed():
    plan = SearchPlan(question_type="diagnosis", concepts=[["sepsis"]])
    client = _Client({"CITED desc": ["L1", "L2", "L3"], None: ["R1", "R2"]})
    engine = LiteratureSynthesisEngine(biocontext_client=client)
    found, err = await engine._planned_search(plan.europepmc_queries(year=2026), max_articles=8)
    assert list(found)[:4] == ["L1", "R1", "L2", "R2"] and err is None
    assert {sort for _, sort in client.calls} == {"CITED desc", None} and len(client.calls) == 2  # tier 1 sufficed

    sparse = _Client({})
    await LiteratureSynthesisEngine(biocontext_client=sparse)._planned_search(plan.europepmc_queries(year=2026), 8)
    assert len(sparse.calls) == len(plan.europepmc_queries(year=2026))  # nothing found: every tier was tried
