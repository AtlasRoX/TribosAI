"""Tool retrieval (F18): recall@k on a labelled query set over the real default registry (ToolRet-style
evaluation, arXiv:2503.01763), plus the retrieve_tools contract other packages rely on."""

from __future__ import annotations

import socket

import pytest

from tests.fakes import build_recording_registry
from tribos.agentic.tool_retrieval import (
    expand_query,
    rank_tools,
    recall_at_k,
    retrieve_tools,
    tokenize,
    tool_card,
    tool_document,
)

# (query, the tool a planner needs for it). Cases whose tool is not registered in this checkout are dropped,
# so tools other packages add later do not break the measurement.
LABELLED = [
    # Tribos STEM labelled query set
    ("Search arXiv and zbMATH for papers on Navier-Stokes", "archivon_literature_search"),
    ("Find paper details and citation metrics for arXiv:1706.03762", "archivon_paper_details"),
    ("Simplify and factor this polynomial expression", "axiom_simplify"),
    ("Solve this system of nonlinear algebraic equations", "axiom_solve"),
    ("Differentiate this function and compute its definite integral", "axiom_calculus"),
    ("Solve this ordinary differential equation symbolically", "axiom_dsolve"),
    ("Compute the eigenvalues and eigenvectors of this matrix", "axiom_linalg"),
    ("Verify identity equivalence between LHS and RHS symbolically", "axiom_verify_identity"),
    ("Simulate time course trajectory for this ODE system", "dynamis_simulate_ode"),
    ("Find equilibrium fixed points and evaluate Jacobian stability", "dynamis_equilibrium"),
    ("Scan parameter across range and evaluate system response", "dynamis_parameter_scan"),
    ("Fit ODE model parameters to experimental calibration data", "dynamis_fit_parameters"),
    ("Look up CODATA 2022 recommended value for Planck constant", "physis_constants"),
    ("Convert units from electron-volts to Joules and check dimensional homogeneity", "physis_units"),
    ("Look up integer sequence in OEIS by initial terms", "physis_oeis"),
    ("Search crystal structure and band gap in Materials Project", "physis_materials"),
    ("Execute sandboxed Python script with NumPy and SciPy", "calcula_run_python"),
    ("Inspect schema and summary statistics of attached dataset", "calcula_describe_dataset"),
    ("Search the web for news about latest advances", "websurfer_search"),
]


@pytest.fixture(scope="module")
def default_registry():
    """The real default registry (builtin + extension tools), built with outbound connections blocked."""
    from tribos.tools.registry import ToolRegistry, register_default_tools

    real_connect = socket.socket.connect

    def blocked(self, *args, **kwargs):
        raise OSError("network disabled in tool-retrieval tests")

    socket.socket.connect = blocked  # type: ignore[method-assign]
    try:
        reg = ToolRegistry()
        register_default_tools(reg)
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"default registry could not be built offline: {exc}")
    finally:
        socket.socket.connect = real_connect  # type: ignore[method-assign]
    return reg


def _cases(reg):
    names = {e.name for e in reg.list_tools()}
    return [(q, t) for q, t in LABELLED if t in names]


def test_recall_at_k_on_default_registry(default_registry):
    cases = _cases(default_registry)
    assert len(cases) >= 12  # the builtin tools alone cover more than half of the set
    assert recall_at_k(default_registry, cases, k=1) >= 0.85
    assert recall_at_k(default_registry, cases, k=3) >= 0.95
    assert recall_at_k(default_registry, cases, k=5) == 1.0


def test_every_registered_tool_is_retrievable_by_its_own_description(default_registry):
    tools = default_registry.list_tools()
    cases = [((e.description or e.name)[:200], e.name) for e in tools]
    assert recall_at_k(default_registry, cases, k=3) >= 0.9


def test_recording_registry_recall():
    reg, _ = build_recording_registry()
    cases = [(q, t) for q, t in LABELLED if reg.get_entry(t) is not None]
    assert recall_at_k(reg, cases, k=3) == 1.0


def test_retrieve_tools_contract():
    reg, _ = build_recording_registry()
    names = [e.name for e in retrieve_tools(reg, "simulate the model", k=2, always=["lithoscribe_literature_synthesis"])]
    assert names[0] == "lithoscribe_literature_synthesis" and len(names) == 2 and names[1].startswith(("dynamis_", "vivarix_"))
    assert all(e.domain in ("axiom", "symbolic") for e in retrieve_tools(reg, "algebra", k=5, domains=["axiom"]))
    assert "axiom_simplify" not in [e.name for e in retrieve_tools(reg, "simplify expression", k=9, exclude=["axiom_simplify"])]
    assert len(retrieve_tools(reg, "anything", k=0)) == len(reg.list_tools())
    assert retrieve_tools(reg, "x", domains=["nope"]) == []
    assert retrieve_tools(reg, "always registered", k=3, always=["not_a_tool"])  # unknown always-names are ignored
    ranked = rank_tools(reg, "parameter scan sensitivity")
    assert ranked[0][0].name in ("vivarix_parameter_scan", "dynamis_parameter_scan") and ranked[0][1] >= ranked[-1][1]


def test_query_expansion_and_tokenizer():
    assert tokenize("What are the KRAS_G12C papers?") == ["kras", "g12c", "papers"]
    terms, weights = expand_query("solve differential equation")
    assert weights["solve"] == 1.0 and any("axiom" in k or "dynamis" in k for k in weights)
    assert len(terms) == len(weights)


def test_tool_card_and_document_are_schema_accurate():
    reg, _ = build_recording_registry()
    card = tool_card(reg.get_entry("axiom_simplify"))
    assert card["name"] == "axiom_simplify"
    assert card["args"]["expression"]["required"] is True
    doc = tool_document(reg.get_entry("axiom_simplify"))
    assert "expression" in doc and "algebraic" in doc
