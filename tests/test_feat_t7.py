"""T7: uploaded papers (PDF): upload validation, extraction with page references, and reproduction of claims."""

from __future__ import annotations

import asyncio
import io

import pytest
from fastapi.testclient import TestClient
from fpdf import FPDF

from tribos.datasets.models import DatasetProvenanceIn

PAGE_1 = [
    "Oscillations of a Mass-Spring System", "Ada Lovelace and Alan Turing", "doi: 10.1234/abcd.5678",
    "1 Introduction", "We study a mass on a spring.", "2 Model", "The period of the oscillator is",
    "T = 2*pi*sqrt(m/k)    (1)", "with mass m = 0.5 kg and stiffness k = 200 N/m.", "The amplitude decays as",
    "dx/dt = -r*x    (2)", "with x(0) = 1 and the rate r = 0.3 1/s.",
]
PAGE_2 = [
    "3 Results", "We obtain T = 0.314 s for the period.", "We find x(2) = 0.5488 after two seconds.",
    "The frequency is", "f = 1/T    (3)", "We obtain f = 9.9 Hz for the frequency.", "The stored energy is",
    "E = k*A^2/2    (4)", "which gives E = 0.25 J.",
]


def _pdf(pages: list[list[str]] = (PAGE_1, PAGE_2), encrypt: bool = False) -> bytes:
    pdf = FPDF()
    pdf.set_font("Helvetica", size=11)
    for lines in pages:
        pdf.add_page()
        for line in lines:
            pdf.cell(0, 8, line, new_x="LMARGIN", new_y="NEXT")
    data = bytes(pdf.output())
    if encrypt:
        from pypdf import PdfReader, PdfWriter

        writer = PdfWriter(clone_from=PdfReader(io.BytesIO(data)))
        writer.encrypt(user_password="secret", algorithm="RC4-128")
        buf = io.BytesIO()
        writer.write(buf)
        data = buf.getvalue()
    return data


@pytest.fixture
def store(tmp_path, monkeypatch):
    from tribos.datasets.store import get_dataset_store, reset_dataset_store

    monkeypatch.setenv("TRIBOS_UPLOAD_ROOT", str(tmp_path / "uploads"))
    reset_dataset_store()
    yield get_dataset_store()
    reset_dataset_store()


def _upload(store, data: bytes, name: str = "paper.pdf"):
    return asyncio.run(store.create_from_stream("alice", [data], name, DatasetProvenanceIn()))


# -- Upload validation ------------------------------------------------------------------------------------------


def test_a_pdf_uploads_as_a_paper(store):
    record = _upload(store, _pdf())
    assert record.kind.value == "paper"
    assert record.validation.format == "pdf" and record.validation.n_pages == 2
    assert record.dims() == "2 pages"


def test_upload_validation_rejects_bad_pdfs(store, monkeypatch):
    from tribos.datasets.store import DatasetStoreError

    with pytest.raises(DatasetStoreError) as fake:
        _upload(store, b"col_a,col_b\n1,2\n")
    assert fake.value.reason_code == "not_pdf"
    with pytest.raises(DatasetStoreError) as locked:
        _upload(store, _pdf(encrypt=True))
    assert locked.value.reason_code == "pdf_encrypted" and "encrypted" in locked.value.detail
    monkeypatch.setenv("TRIBOS_UPLOAD_MAX_PDF_PAGES", "1")
    with pytest.raises(DatasetStoreError) as long:
        _upload(store, _pdf())
    assert long.value.reason_code == "pdf_too_many_pages"
    monkeypatch.setenv("TRIBOS_UPLOAD_MAX_MB_PDF", "0.001")
    with pytest.raises(DatasetStoreError) as big:
        _upload(store, _pdf())
    assert big.value.status_code == 413


def test_the_limits_endpoint_lists_pdf(monkeypatch, tmp_path):
    monkeypatch.setenv("TRIBOS_AUTH_MODE", "disabled")
    monkeypatch.setenv("TRIBOS_UPLOAD_ROOT", str(tmp_path / "uploads"))
    from app.backend.main import app

    with TestClient(app, base_url="http://localhost") as client:
        body = client.get("/api/datasets/limits").json()
    assert body["extensions"][".pdf"] == "paper"
    assert body["max_bytes"]["paper"] == 25 * 1024 * 1024


def test_tabular_paths_ignore_papers(store):
    from tribos.agentic.sandbox import bound_scope, current_scope, resolve_inputs

    record = _upload(store, _pdf())
    with bound_scope("alice", [record.id]):
        inputs, errors = resolve_inputs(current_scope(), [record.id])
    assert inputs == [] and "not an analysable dataset" in errors[0]


# -- Extraction ---------------------------------------------------------------------------------------------------


def test_extraction_keeps_page_references(tmp_path):
    from tribos.papers import extract_paper

    path = tmp_path / "p.pdf"
    path.write_bytes(_pdf())
    paper = extract_paper(path)
    assert paper["title"] == "Oscillations of a Mass-Spring System"
    assert paper["authors"] == "Ada Lovelace and Alan Turing"
    assert paper["doi"] == "10.1234/abcd.5678"
    assert [s["title"] for s in paper["sections"]] == ["Introduction", "Model", "Results"]
    eq = {e["lhs"]: e for e in paper["equations"]}
    assert eq["T"]["number"] == "1" and eq["T"]["page"] == 1 and eq["T"]["line"].startswith("T = 2*pi*sqrt(m/k)")
    assert eq["T"]["sympy"] == "2*pi*sqrt(m/k)" and eq["E"]["page"] == 2
    assert [(o["state"], o["rhs"], o["page"]) for o in paper["odes"]] == [("x", "-r*x", 1)]
    params = {p["name"]: p for p in paper["parameters"]}
    assert params["k"]["value"] == 200 and params["k"]["unit"] == "N/m" and params["k"]["page"] == 1
    assert "T" not in params and "f" not in params  # "T = 2*pi*..." and "f = 1/T" are equations, not values
    claims = {c["name"]: c for c in paper["claims"]}
    assert claims["T"]["value"] == 0.314 and claims["T"]["page"] == 2


# -- Reproduction -------------------------------------------------------------------------------------------------


def test_reproduction_statuses(tmp_path):
    from tribos.papers import extract_paper, reproduce_paper

    path = tmp_path / "p.pdf"
    path.write_bytes(_pdf())
    result = reproduce_paper(extract_paper(path))
    rows = {r["name"]: r for r in result["claims"]}
    # A correct closed-form claim: 2 pi sqrt(0.5 / 200) = 0.31416 s, stated as 0.314 s.
    assert rows["T"]["status"] == "reproduced" and rows["T"]["computed"] == pytest.approx(0.314159, rel=1e-5)
    # A correct ODE claim: x(2) = exp(-0.6) = 0.54881, from the paper's dx/dt, x(0) and r.
    assert rows["x(2)"]["status"] == "reproduced" and rows["x(2)"]["computed"] == pytest.approx(0.548812, rel=1e-4)
    # A wrong claim: f = 1/T = 3.18 Hz, not 9.9 Hz.
    assert rows["f"]["status"] == "differs"
    assert rows["f"]["computed"] == pytest.approx(1 / 0.314) and rows["f"]["relative_difference"] > 0.5
    # Missing inputs: the paper never states the amplitude A, so E is not reproducible (and A is not guessed).
    assert rows["E"]["status"] == "not_reproducible" and rows["E"]["missing"] == ["A"]
    assert result["counts"] == {"reproduced": 2, "differs": 1, "not_reproducible": 1}
    assert rows["T"]["page"] == 2 and rows["T"]["equation_page"] == 1


def test_targets_limit_the_check(tmp_path):
    from tribos.papers import extract_paper, reproduce_paper

    path = tmp_path / "p.pdf"
    path.write_bytes(_pdf())
    result = reproduce_paper(extract_paper(path), targets=["x"])
    assert [r["name"] for r in result["claims"]] == ["x(2)"]


# -- Tools ----------------------------------------------------------------------------------------------------------


def test_tools_read_only_attached_papers(store):
    from tribos.agentic.sandbox import bound_scope
    from tribos.extensions.papers import _paper_artifact, execute_read_paper, execute_reproduce_paper

    record = _upload(store, _pdf())
    assert not execute_read_paper(record.id).success  # not attached to this run
    with bound_scope("alice", [record.id]):
        read = execute_read_paper(record.id)
        reproduced = execute_reproduce_paper(record.id)
    assert read.success and read.data["n_pages"] == 2 and read.canonical_ids == {"doi": "10.1234/abcd.5678"}
    assert reproduced.success and reproduced.data["counts"]["differs"] == 1
    with bound_scope("bob", [record.id]):
        assert not execute_read_paper(record.id).success  # another user's paper is not found
    card = _paper_artifact({"a": read, "b": reproduced}, None)["paper_reproduction"]
    assert card["paper"]["title"].startswith("Oscillations") and len(card["claims"]) == 4


def test_paper_tools_are_never_replayed():
    from tribos.provenance.rerun import tool_replay_refusal
    from tribos.tools.registry import get_tool_registry

    for name in ("archivon_read_paper", "archivon_reproduce_paper"):
        entry = get_tool_registry().get_entry(name)
        assert entry is not None and tool_replay_refusal(name, entry)
