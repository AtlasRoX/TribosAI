"""
Tests for Feature F17: Align planner schemas, capabilities and tool registry.

Covers:
- P04: Missing parameter schema repair in AxiomStructuredInput definitions.
  - Parameter aliases (variable, var, param, arg) and single-variable inference.
  - Ambiguous variable rejection without domain guessing.
  - Formula aliases (formula, expr, rule, value) and word-based domain normalization.
- P12: Unregistered tool alias mapping (web_search -> websurfer_search).
  - Proper execution under registered name when enabled.
  - Explicit policy rejection when search is disabled.
  - Distinct representation for unregistered, disabled, and policy-forbidden tools.
"""

from __future__ import annotations

from types import SimpleNamespace

import pydantic
import pytest

from tribos.agentic.plan_graph import PlanGraph, PlanNode, validate_plan
from tribos.axiom.schemas import AxiomStructuredInput, StructuredDefinition
from tribos.tools.registry import get_tool_registry

# ---------------------------------------------------------------------------
# 1. P04: Missing Parameter Schema Repair & Field Aliases
# ---------------------------------------------------------------------------


def test_f17_missing_parameter_and_alias_repair():
    task = {"id": "t(1)", "op": "evaluate", "expression": "t(1)"}

    # Case 1: Parameter given via alias "variable"
    input_var = {
        "name": "t",
        "domain": "positive_integer",
        "variable": "n",
        "branches": [{"expression": "3*n + 1", "condition": "odd"}, {"expression": "n/2", "condition": "even"}],
    }
    parsed_var = AxiomStructuredInput(definitions=[input_var], tasks=[task])
    assert parsed_var.definitions[0].parameter == "n"

    # Case 2: Parameter given via alias "var" or "param"
    input_param = {
        "name": "f",
        "domain": "real",
        "param": "x",
        "branches": [{"expression": "x**2 + 1", "condition": ""}],
    }
    parsed_param = AxiomStructuredInput(definitions=[input_param], tasks=[task])
    assert parsed_param.definitions[0].parameter == "x"

    # Case 3: No parameter field at all; inferred from single formula variable
    input_inferred = {
        "name": "g",
        "domain": "real",
        "branches": [{"expression": "z**3 - 2*z", "condition": ""}],
    }
    parsed_inferred = AxiomStructuredInput(definitions=[input_inferred], tasks=[task])
    assert parsed_inferred.definitions[0].parameter == "z"

    # Case 4: Ambiguous variables -> must fail with clear validation error rather than guessing
    input_ambiguous = {
        "name": "h",
        "domain": "real",
        "branches": [{"expression": "x + y", "condition": ""}],
    }
    with pytest.raises(pydantic.ValidationError, match="state the parameter"):
        AxiomStructuredInput(definitions=[input_ambiguous], tasks=[task])


def test_f17_formula_aliases_and_domain_normalization():
    # Single formula given under key "formula" without explicit branches list
    raw_def = {
        "name": "p",
        "domain": "positive integers",  # word form
        "formula": "k**2 + 41",
    }
    d = StructuredDefinition.model_validate(raw_def)
    assert d.parameter == "k"
    assert d.domain == "positive_integer"
    assert len(d.branches) == 1
    assert d.branches[0].expression == "k**2 + 41"


# ---------------------------------------------------------------------------
# 2. P12: Unregistered Tool Alias Mapping & Policy Enforcement
# ---------------------------------------------------------------------------


def test_f17_unregistered_web_search_maps_to_registered_tool_when_enabled():
    registry = get_tool_registry()
    ctx_enabled = SimpleNamespace(
        enable_web_search=True,
        evidence_need=None,
        excluded_modules=set(),
        extras={},
        decisions={},
        source_allowlist=None,
    )

    graph = PlanGraph(nodes=[PlanNode(id="n1", tool="web_search", args={"query": "Riemann Hypothesis CMI status"})])
    validated = validate_plan(graph, registry, ctx_enabled)

    assert len(validated.nodes) == 1
    assert validated.nodes[0].tool == "websurfer_search"
    assert any("tool 'web_search' → registered 'websurfer_search'" in a for a in validated.nodes[0].adjusted)


def test_f17_unregistered_web_search_rejected_when_search_disabled():
    registry = get_tool_registry()
    ctx_disabled = SimpleNamespace(
        enable_web_search=False,
        evidence_need=None,
        excluded_modules=set(),
        extras={},
        decisions={},
        source_allowlist=None,
    )

    graph = PlanGraph(nodes=[PlanNode(id="n1", tool="web_search", args={"query": "Riemann Hypothesis CMI status"})])
    validated = validate_plan(graph, registry, ctx_disabled)

    assert len(validated.nodes) == 0
    assert len(validated.rejected) == 1
    assert "Search is off" in validated.rejected[0]["reason"]


def test_f17_completely_unknown_tool_rejected_distinctly():
    registry = get_tool_registry()
    ctx = SimpleNamespace(
        enable_web_search=True,
        evidence_need=None,
        excluded_modules=set(),
        extras={},
        decisions={},
        source_allowlist=None,
    )

    graph = PlanGraph(nodes=[PlanNode(id="n1", tool="invented_oracle_tool", args={"x": 1})])
    validated = validate_plan(graph, registry, ctx)

    assert len(validated.nodes) == 0
    assert len(validated.rejected) == 1
    assert "is not registered (no registered tool provides it)" in validated.rejected[0]["reason"]
