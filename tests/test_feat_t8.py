"""Export regressions and executable, dependency-free notebook serialization."""

from __future__ import annotations

import io
import json
import subprocess
import sys
import zipfile

import pypdf
from fastapi.testclient import TestClient

from tribos.export import build_report_model, render_bundle, render_markdown, render_pdf


def test_inline_math_survives_docx_endpoint(monkeypatch):
    from app.backend.main import app

    monkeypatch.setenv("TRIBOS_AUTH_MODE", "disabled")
    with TestClient(app, base_url="http://localhost") as client:
        response = client.post("/api/export/docx", json={
            "question": "Equation of motion",
            "message": {"content": r"The equation of motion is $m\ddot{x}=-kx$ with $k=2$."},
        })
    assert response.status_code == 200
    with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
        xml = archive.read("word/document.xml").decode()
    # An inline equation must carry accessible source, not silently disappear.
    assert "m\\ddot{x}=-kx" in xml and "k=2" in xml
    assert "drawing" in xml or "oMath" in xml


def test_pdf_math_unicode_tables_and_code():
    answer = r"""Motion: $F=ma$, $\frac{a}{b}$, α ± 2°.

$$E=mc^2$$

| Quantity | Value |
| --- | --- |
| force | $F=2$ |

- first item
- second item

```python
print('example')
```
""" + "\n| a | b |\n|---|---|\n" + "| row | value |\n" * 65
    report = build_report_model("Motion", {"content": answer})
    text = "\n".join(page.extract_text() for page in pypdf.PdfReader(io.BytesIO(render_pdf(report))).pages)
    assert r"\frac" not in text and "$F" not in text
    assert "first item" in text and "example" in text and "row" in text and "±" in text
    assert answer.strip() in render_markdown(report).decode()


def test_notebook_reproduces_recorded_ode_and_symbolic_result(tmp_path):
    from tribos.dynamis.engine import dynamis_simulate_ode
    from tribos.export import render_notebook

    simulation = dynamis_simulate_ode(rhs={"x": "-k*x"}, initial_state={"x": 2}, parameters={"k": 0.3},
                                      t_span=(0, 2), num_points=20)
    assert simulation["spec"]["rhs"] == {"x": "-k*x"}
    report = build_report_model("Decay", {"content": "The decay is exponential.", "run_manifest": {
        "tool_calls": [
            {"tool_name": "dynamis_simulate_ode", "success": True, "inputs": {}, "output_digest": simulation},
            {"tool_name": "axiom_simplify", "success": True, "inputs": {"expression": "(x+1)**2-x**2"},
             "output_digest": {"simplified": "2*x+1"}},
        ],
    }})
    notebook = json.loads(render_notebook(report))
    assert notebook["nbformat"] == 4 and notebook["nbformat_minor"] >= 5
    assert all(cell["id"] for cell in notebook["cells"])
    code = "\n\n".join("".join(c["source"]) for c in notebook["cells"] if c["cell_type"] == "code")
    path = tmp_path / "reproduce.py"
    path.write_text("import matplotlib\nmatplotlib.use('Agg')\n" + code, encoding="utf-8")
    result = subprocess.run([sys.executable, str(path)], capture_output=True, text=True, timeout=60)
    assert result.returncode == 0, result.stderr
    assert "solve_ivp" in code and "simplify" in code and "assert" in code
    with zipfile.ZipFile(io.BytesIO(render_bundle(report))) as archive:
        assert "report.ipynb" in archive.namelist()


def test_notebook_does_not_export_secrets_or_server_paths():
    from tribos.export import render_notebook

    report = build_report_model("q", {"content": "a", "run_manifest": {"tool_calls": [{
        "tool_name": "unsupported", "inputs": {"api_key": "SECRET", "path": "C:/server/private/data.csv"},
    }]}})
    output = render_notebook(report).decode()
    assert "SECRET" not in output and "C:/server" not in output


def test_notebook_endpoint(monkeypatch):
    from app.backend.main import app

    monkeypatch.setenv("TRIBOS_AUTH_MODE", "disabled")
    with TestClient(app, base_url="http://localhost") as client:
        response = client.post("/api/export/ipynb", json={"question": "q", "message": {"content": "a"}})
    assert response.status_code == 200
    assert response.json()["nbformat"] == 4
