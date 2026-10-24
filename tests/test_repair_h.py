import pytest

pytest.importorskip('tribos.vivarix', reason='Legacy vivarix package retired')
"""
Workstream H regressions: Synapta graph extraction, GraphRAG, legacy Vivarix tools.
All offline; Milvus, COPASI and LLM calls are faked.
"""

from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest
from tribos.vivarix.tools import parameter_scan as scan_module
from tribos.vivarix.tools import steady_state as steady_module

pytestmark = pytest.mark.unit_mock


def _edges_collection(rows, num_entities, calls):
    """Fake edges collection returning `rows` (any order) for every range query."""

    class FakeEdges:
        def __init__(self, name):
            self.name = name
            self.num_entities = num_entities

        def load(self):
            return None

        def query(self, expr=None, output_fields=None):
            calls.append((expr, tuple(output_fields or ())))
            low = int(expr.split(">=")[1].split("and")[0])
            high = int(expr.split("<")[1])
            return [r for r in rows if low <= r["triplet_index"] < high]

    return FakeEdges


def _cfg(db="primekg", batch=10):
    return SimpleNamespace(milvus_db=SimpleNamespace(database_name=db, query_batch_size=batch))


class _HydraCtx:
    def __init__(self, **_kwargs):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False


def _graphrag_state():
    return {
        "llm_model": object(),
        "embedding_model": object(),
        "uploaded_files": [{"file_type": "drug_data", "file_path": "drug.pdf"}],
        "dic_extracted_graph": [{"name": "subkg_1", "graph_summary": "summary"}],
    }


@pytest.mark.parametrize("code", [steady_module.STEADY_STATE_NOT_FOUND, steady_module.STEADY_STATE_NEGATIVE])
def test_steady_state_rejects_not_found_and_negative(code):
    with pytest.raises(ValueError):
        steady_module.check_steady_state(code, "copasi")


def test_steady_state_rejects_unstable_point(monkeypatch):
    monkeypatch.setattr(
        steady_module.basico.model_info,
        "get_reduced_jacobian_matrix",
        lambda model=None: pd.DataFrame([[0.5, 0.0], [0.0, -1.0]]),
    )
    with pytest.raises(ValueError, match="unstable"):
        steady_module.check_steady_state(steady_module.STEADY_STATE_FOUND, "copasi")


def test_steady_state_accepts_stable_point(monkeypatch):
    monkeypatch.setattr(
        steady_module.basico.model_info,
        "get_reduced_jacobian_matrix",
        lambda model=None: pd.DataFrame([[-0.5, 0.1], [0.0, -1.0]]),
    )
    eigenvalues = steady_module.check_steady_state(steady_module.STEADY_STATE_FOUND, "copasi")
    assert np.all(eigenvalues.real < 0)


def test_parameter_scan_accepts_display_names_and_scans_copies(monkeypatch):
    monkeypatch.setattr(
        scan_module.basico.model_info,
        "get_parameters",
        lambda model=None: pd.DataFrame(index=["(R1).k1"]),
    )
    monkeypatch.setattr(
        scan_module.basico.model_info,
        "get_species",
        lambda model=None: pd.DataFrame({"display_name": ["Mos{cell}"]}, index=["Mos"]),
    )
    updates = []

    class Model:
        copasi_model = "copasi"

        def __init__(self):
            self.simulation_results = None

        def model_copy(self):
            return Model()

        def update_parameters(self, params):
            updates.append(dict(params))

        def simulate(self, duration, interval):
            self.simulation_results = pd.DataFrame({"Time": [0.0, duration], "Mos": [1.0, 2.0]})

    arg_data = SimpleNamespace(
        parameter_scan_data=SimpleNamespace(
            species_parameter_name="Mos{cell}",
            species_parameter_values=[1.0, 2.0],
            species_names=["Mos"],
        )
    )
    original = Model()
    results = scan_module.run_parameter_scan(original, arg_data, {}, 10.0, 2)
    # Display name resolved to the COPASI species name update_parameters() expects
    assert {"Mos": 1.0} in updates and {"Mos": 2.0} in updates
    assert list(results["Mos"].columns) == ["Time", "Mos{cell}_1.0", "Mos{cell}_2.0"]
    assert original.simulation_results is None


def test_parameter_scan_rejects_unknown_name(monkeypatch):
    monkeypatch.setattr(
        scan_module.basico.model_info, "get_parameters", lambda model=None: pd.DataFrame(index=[])
    )
    monkeypatch.setattr(
        scan_module.basico.model_info,
        "get_species",
        lambda model=None: pd.DataFrame({"display_name": ["Mos"]}, index=["Mos"]),
    )
    arg_data = SimpleNamespace(
        parameter_scan_data=SimpleNamespace(
            species_parameter_name="INVALID_PARAM_XYZ",
            species_parameter_values=[1.0],
            species_names=["Mos"],
        )
    )
    with pytest.raises(ValueError, match="INVALID_PARAM_XYZ"):
        scan_module.run_parameter_scan(
            SimpleNamespace(copasi_model="copasi"), arg_data, {}, 10.0, 2
        )
