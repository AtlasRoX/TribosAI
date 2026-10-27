"""
Tests for F06: Enforce explicit prohibitions through every orchestration phase.

Verifies:
1. Extraction of explicit tool prohibitions (formal proof, search, code, simulation) from queries across semantic variants.
2. Negative controls (absence claims, math statements, quotes) are NOT read as prohibitions.
3. Precedence rules: explicit prompt directive overrides UI settings and standing instructions.
4. Revocations: explicit permission restores tools.
5. FormalProofPhase skips with precise disabled-by-user state and suppresses capability warnings.
6. Dispatch boundary hard-blocks prohibited tools at registry.execute and execute_with_policies.
7. Plan validation and specialist routing reject prohibited tools.
8. Allowed capabilities (symbolic math solver Axiom) remain functional when search/formal are prohibited.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from tribos.agentic.formal_proof import FormalProofPhase
from tribos.agentic.plan_graph import PlanGraph, PlanNode, policy_violation, validate_plan
from tribos.agentic.specialists import tool_allowed
from tribos.agents.query_context import QueryContext
from tribos.agents.query_planner import decide_builtin_sources
from tribos.extensions.formal import execute_formal_check
from tribos.tools.policy import (
    ToolPolicy,
    enforce_tool_policy,
    extract_tool_policy,
)
from tribos.tools.registry import ErrorType, ToolRegistry, ToolUniverseEntry
from tribos.verify.formal.prove import formalise_and_check

# ---------------------------------------------------------------------------------------------------------
# 1. Extraction of explicit tool prohibitions and semantic variants
# ---------------------------------------------------------------------------------------------------------

@pytest.mark.parametrize(
    "query, expected_search, expected_formal, expected_code",
    [
        # S07 reproduction prompt
        ("Four items: k=1,3,6; for i>=0, a=16i+3, b=9i+2, prove a>b. No web search or formal prover.", True, True, False),
        ("Do not search the web or run a formal prover.", True, True, False),
        ("no search or formal prover", True, True, False),
        ("without web search or a formal prover", True, True, False),
        ("no search, code execution, or formal prover", True, True, True),
        # Formal prover variants
        ("Prove that n^2+n is even. Do not run a formal prover.", False, True, False),
        ("Prove a > b without a formal prover.", False, True, False),
        ("Prove x^2 >= 0. Do not use Lean.", False, True, False),
        ("Prove the identity. Skip formal verification.", False, True, False),
        ("Prove the theorem; no theorem prover please.", False, True, False),
        ("formal prover: off", False, True, False),
        # Search variants
        ("Evaluate the integral. Do not search the web.", True, False, False),
        ("Solve the equation. No web search.", True, False, False),
        ("without search", True, False, False),
        ("no literature search or paper retrieval", True, False, False),
        ("web search: disabled", True, False, False),
        # Code execution variants
        ("Calculate 2+2 without running code.", False, False, True),
        ("No code execution.", False, False, True),
    ],
)
def test_f06_extract_tool_policy_semantic_variants(
    query: str, expected_search: bool, expected_formal: bool, expected_code: bool
):
    pol = extract_tool_policy(query)
    assert pol.prohibit_search == expected_search
    assert pol.prohibit_formal == expected_formal
    assert pol.prohibit_code == expected_code


# ---------------------------------------------------------------------------------------------------------
# 2. Negative controls: factual claims, definitions, and quoted prohibitions
# ---------------------------------------------------------------------------------------------------------

@pytest.mark.parametrize(
    "query",
    [
        "There is no formal proof known for the Riemann Hypothesis.",
        "No accepted proof of the Collatz conjecture exists in the literature.",
        "There is no real solution of x^2 + 1 = 0.",
        "There are no published studies of this alloy at 4 K.",
        "A statement with no formal proof is called a conjecture.",
        "There is no search result matching the query.",
    ],
)
def test_f06_factual_absence_claims_are_not_prohibitions(query: str):
    pol = extract_tool_policy(query)
    assert not pol.prohibit_search, f"False search prohibition on: {query}"
    assert not pol.prohibit_formal, f"False formal prohibition on: {query}"


@pytest.mark.parametrize(
    "query",
    [
        'Explain the prompt instruction "do not search the web or run a formal prover".',
        "Classify the rule 'no formal prover' as an orchestration constraint.",
        'A paper titled "No Search Needed: Direct Math Solvers" discusses neural theorem proving.',
    ],
)
def test_f06_quoted_prohibitions_are_ignored(query: str):
    pol = extract_tool_policy(query)
    assert not pol.prohibit_search
    assert not pol.prohibit_formal


# ---------------------------------------------------------------------------------------------------------
# 3. Precedence rules and revocations
# ---------------------------------------------------------------------------------------------------------

def test_f06_prompt_no_search_overrides_ui_search_on():
    # UI toggle says enable_web_search=True, but prompt explicitly forbids search
    pol = extract_tool_policy("Calculate eigenvalues. Do not search the web.", enable_web_search=True)
    assert pol.prohibit_search is True
    assert pol.search_source == "prompt"


def test_f06_prompt_explicit_search_overrides_ui_search_off():
    # UI toggle says enable_web_search=False, but user explicitly asks to search the web
    pol = extract_tool_policy("Search the web for the latest status of ITER.", enable_web_search=False)
    assert pol.prohibit_search is False
    assert pol.search_source == "prompt"


def test_f06_revocation_lifts_earlier_prohibition():
    # In-prompt revocation
    query = "Previously I said no web search, but search is now allowed. Search the web for latest findings."
    pol = extract_tool_policy(query, enable_web_search=True)
    assert pol.prohibit_search is False


def test_f06_standing_instructions_precedence():
    # Standing instruction forbids formal prover
    pol = extract_tool_policy("Prove a > b", standing_instructions=["From now on, no formal prover."])
    assert pol.prohibit_formal is True
    assert pol.formal_source == "standing_instruction"

    # Current turn overrides standing instruction
    pol2 = extract_tool_policy("Verify in Lean: allow formal prover for this theorem.",
                               standing_instructions=["From now on, no formal prover."])
    assert pol2.prohibit_formal is False


# ---------------------------------------------------------------------------------------------------------
# 4. FormalProofPhase skips with precise disabled-by-user state (suppresses capability warnings)
# ---------------------------------------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_f06_formal_proof_phase_reports_user_disabled_not_capability():
    phase = FormalProofPhase()
    query = "Prove a > b for a=16i+3, b=9i+2. Do not run a formal prover."
    pol = extract_tool_policy(query)

    async def dummy_step(*args, **kwargs):
        pass

    state = SimpleNamespace(
        query=query,
        clean_query=query,
        tool_policy=pol,
        ctx=SimpleNamespace(tool_policy=pol),
        artifacts={},
        phases={},
        brief_notes=[],
        scope_notes=[],
        evidence_sections=[],
        llm=SimpleNamespace(available=False),
        mark_phase=lambda key, status, reason: state.phases.setdefault(key, {"status": status, "reason": reason}),
        step=dummy_step,
        add_result=lambda *args, **kwargs: None,
    )

    outcome = await phase.run(state)
    assert outcome is not None
    art = outcome.artifacts["formal_proof"]
    # Precise disabled-by-user state
    assert art["status"] == "disabled"
    assert art["title"] == "formal prover disabled by user"
    assert "user request" in art["error"].lower()
    # Suppress capability warning: skip reason MUST report user prohibition, NOT "Lean is not installed"
    skip_record = state.phases["formal_proof"]
    assert skip_record["status"] == "skipped"
    assert "disabled by user" in skip_record["reason"]
    assert "not installed" not in skip_record["reason"].lower()
    assert art["attempts"] == []


# ---------------------------------------------------------------------------------------------------------
# 5. Dispatch boundary hard-blocks prohibited tools
# ---------------------------------------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_f06_dispatch_boundary_blocks_formal_tool():
    reg = ToolRegistry()
    from tribos.extensions.formal import register_tools
    register_tools(reg)

    policy = ToolPolicy(prohibit_formal=True, formal_reason="Formal prover disabled by user request")
    with enforce_tool_policy(policy):
        # 1. registry.execute
        res = await reg.execute("axiom_formal_check", lean_code="theorem test : True := trivial")
        assert not res.success
        assert res.error_type == ErrorType.VALIDATION_ERROR
        assert "disabled by user" in res.error.lower()
        assert res.metadata.get("skipped_by_policy") == "disabled_by_user"

        # 2. direct execute_formal_check
        res2 = execute_formal_check("theorem test : True := trivial")
        assert not res2.success
        assert res2.error_type == ErrorType.VALIDATION_ERROR

        # 3. formalise_and_check
        res3 = await formalise_and_check("prove a > b", None)
        assert res3["status"] == "disabled"
        assert res3["title"] == "formal prover disabled by user"
        assert res3["attempts"] == []


@pytest.mark.asyncio
async def test_f06_dispatch_boundary_blocks_search_tools():
    reg = ToolRegistry()
    from pydantic import BaseModel, Field

    class SearchInput(BaseModel):
        query: str = Field(...)

    reg.register(
        ToolUniverseEntry(
            name="websurfer_search",
            description="Web search",
            domain="websurfer",
            adapter_type="DIRECT_REST",
            input_schema=SearchInput,
        ),
        executor=lambda query: {"results": []},
    )

    policy = ToolPolicy(prohibit_search=True, search_reason="Search disabled by user request")
    with enforce_tool_policy(policy):
        res = await reg.execute("websurfer_search", query="Riemann Hypothesis")
        assert not res.success
        assert res.error_type == ErrorType.VALIDATION_ERROR
        assert "disabled by user" in res.error.lower()


# ---------------------------------------------------------------------------------------------------------
# 6. Plan validation and specialist gating
# ---------------------------------------------------------------------------------------------------------

def test_f06_plan_graph_and_specialists_respect_policy():
    reg = ToolRegistry()
    from tribos.extensions.formal import register_tools
    register_tools(reg)

    policy = ToolPolicy(prohibit_formal=True, formal_reason="Formal prover disabled by user request")
    ctx = SimpleNamespace(tool_policy=policy, enable_web_search=True, extras={}, decisions={})

    # policy_violation
    entry = reg.get_entry("axiom_formal_check")
    assert policy_violation(entry, ctx) == "Formal prover disabled by user request"

    # tool_allowed
    allowed, reason = tool_allowed(ctx, entry)
    assert not allowed
    assert "Formal prover disabled" in reason

    # validate_plan
    graph = PlanGraph(nodes=[PlanNode(id="n1", tool="axiom_formal_check", args={"lean_code": "theorem t : True := trivial"})])
    validated = validate_plan(graph, reg, ctx)
    assert len(validated.nodes) == 0
    assert len(validated.rejected) == 1
    assert "Formal prover disabled" in validated.rejected[0]["reason"]


# ---------------------------------------------------------------------------------------------------------
# 7. S07 reproduction: full QueryContext, routing, and allowed math capabilities
# ---------------------------------------------------------------------------------------------------------

def test_f06_s07_query_context_and_routing():
    query = (
        "Four independent items: k=1,k=3,k=6, compute 2k+1 in each; for nonnegative integer i, "
        "a(i)=16i+3,b(i)=9i+2, prove a>b and check i=0,1,2. Exactly four numbered items; no web search or formal prover."
    )
    pol = extract_tool_policy(query, enable_web_search=True)
    assert pol.prohibit_search is True
    assert pol.prohibit_formal is True

    ctx = QueryContext(
        raw_query=query,
        clean_query=query,
        enable_web_search=not pol.prohibit_search,
        tool_policy=pol,
    )
    ctx.intents.add("prove")
    decide_builtin_sources(ctx)

    # Search and formal decisions are disabled
    assert ctx.decisions["archivon"].run is False
    assert "disabled by user" in ctx.decisions["archivon"].reason.lower()
    assert ctx.decisions["websurfer"].run is False
    assert "disabled by user" in ctx.decisions["websurfer"].reason.lower()
    assert ctx.decisions["formal_proof"].run is False
    assert "disabled by user" in ctx.decisions["formal_proof"].reason.lower()

    # Symbolic mathematics (Axiom) remains enabled and functional!
    assert ctx.decisions["axiom"].run is True
    assert "symbolic reasoning requested" in ctx.decisions["axiom"].reason


# ---------------------------------------------------------------------------------------------------------
# 8. Positive control: appropriate tasks enable formal proof and search
# ---------------------------------------------------------------------------------------------------------

def test_f06_positive_control_proof_and_search_enabled():
    proof_query = "Prove that for all positive integers n, n^2 + n is even."
    pol_proof = extract_tool_policy(proof_query, enable_web_search=True)
    assert pol_proof.prohibit_formal is False
    assert pol_proof.prohibit_search is False

    ctx_proof = QueryContext(raw_query=proof_query, clean_query=proof_query, enable_web_search=True, tool_policy=pol_proof)
    ctx_proof.intents.add("prove")
    decide_builtin_sources(ctx_proof)
    assert ctx_proof.decisions["axiom"].run is True
    assert "formal_proof" not in ctx_proof.decisions or ctx_proof.decisions["formal_proof"].run is True

    search_query = "What are the latest clinical trial results for mRNA-4157 in melanoma?"
    pol_search = extract_tool_policy(search_query, enable_web_search=True)
    assert pol_search.prohibit_search is False
    ctx_search = QueryContext(raw_query=search_query, clean_query=search_query, enable_web_search=True, tool_policy=pol_search)
    decide_builtin_sources(ctx_search)
    assert ctx_search.decisions["archivon"].run is True
    assert ctx_search.decisions["websurfer"].run is True
