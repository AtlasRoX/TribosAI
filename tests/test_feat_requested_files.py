"""Files a question asks for (Word, PDF, Markdown, notebook, Python, CSV, Excel, JSON, PNG), built from the answer,
stored per user and served by GET /api/files/{id}."""

from __future__ import annotations

import io
import json
import zipfile

import pytest

from tribos import files as tf
from tribos.files.store import FileStore

ANSWER = """The beam's deflection grows with load.

| Load [kN] | Deflection [mm] |
|---|---|
| 1 | 0.5 |
| 2 | 1.0 |

```python
import numpy as np
loads = np.array([1, 2])
print(loads * 0.5)
```

```ui
{"type":"chart","title":"Deflection","x":{"label":"Load","unit":"kN"},"y":{"label":"Deflection","unit":"mm"},"series":[{"name":"d","points":[[1,0.5],[2,1.0]]}]}
```
"""


@pytest.mark.parametrize("question,kinds", [
    ("Compute the beam deflection and give it as a Word document", ["docx"]),
    ("Give me the Python script and a CSV of the values", ["py", "csv"]),
    ("Put the results in an Excel spreadsheet and a PDF", ["pdf", "xlsx"]),
    ("Make a downloadable report of the analysis", ["docx"]),
    ("Save the plot as an image", ["png"]),
    ("What is the deflection of the beam?", []),
])
def test_requested_files_are_detected(question, kinds):
    assert tf.requested_files(question) == kinds


def test_the_writer_is_told_which_files_to_fill():
    note = tf.writer_note(["py", "csv"])
    assert "Python script" in note and "runnable code" in note and "Markdown tables" in note
    assert "never say that files cannot be created" in note
    assert tf.writer_note([]) == ""


def test_tables_and_code_are_read_from_the_answer():
    assert tf.markdown_tables(ANSWER) == [[["Load [kN]", "Deflection [mm]"], ["1", "0.5"], ["2", "1.0"]]]
    assert "loads * 0.5" in tf.python_code(ANSWER, {})
    cells = {"codeact": {"cells": [{"code": "x = 2\nprint(x)", "status": "ok"}, {"code": "boom(", "status": "error"}]}}
    assert tf.python_code("No code here.", cells).strip() == "x = 2\nprint(x)"


def test_every_kind_builds_a_valid_file():
    files, notes = tf.build_files("Beam deflection under load", ANSWER,
                                  ["docx", "md", "py", "csv", "xlsx", "json", "png"])
    by_kind = {k: (name, data) for k, name, data in files}
    assert not notes and set(by_kind) == {"docx", "md", "py", "csv", "xlsx", "json", "png"}
    assert zipfile.is_zipfile(io.BytesIO(by_kind["docx"][1]))  # a real .docx is a zip package
    assert zipfile.is_zipfile(io.BytesIO(by_kind["xlsx"][1]))
    assert by_kind["png"][1][:8] == b"\x89PNG\r\n\x1a\n"
    assert by_kind["csv"][1].decode("utf-8-sig").splitlines()[1] == "1,0.5"
    assert json.loads(by_kind["json"][1])[0][0] == {"Load [kN]": "1", "Deflection [mm]": "0.5"}
    assert by_kind["py"][0] == "beam-deflection-under-load.py"
    from openpyxl import load_workbook

    ws = load_workbook(io.BytesIO(by_kind["xlsx"][1])).active
    assert ws["B3"].value == 1.0  # numbers are numbers, not text


def test_a_kind_with_nothing_to_build_from_is_reported_not_invented():
    files, notes = tf.build_files("Explain beams", "Beams bend under load.", ["py", "csv", "png"])
    assert files == [] and len(notes) == 3 and "no Python code" in notes[0]


def test_files_belong_to_the_user_who_asked(tmp_path):
    store = FileStore(str(tmp_path))
    entries = tf.save_files("alice", [("py", "a.py", b"print(1)\n")], store=store)
    fid = entries[0]["id"]
    assert entries[0]["text"] == "print(1)\n" and entries[0]["url"] == f"/api/files/{fid}"
    assert store.load("alice", fid)[0].read_bytes() == b"print(1)\n"
    assert store.load("bob", fid) is None
    assert store.load("alice", "../../etc/passwd") is None


def test_the_download_endpoint_serves_only_the_owner(monkeypatch, tmp_path):
    from fastapi.testclient import TestClient

    from app.backend import main as backend_main
    from tribos.files import store as store_mod

    monkeypatch.setenv("TRIBOS_FILES_DIR", str(tmp_path))
    monkeypatch.delenv("TRIBOS_AUTH_MODE", raising=False)
    monkeypatch.delenv("TRIBOS_JWT_SECRET", raising=False)
    monkeypatch.setenv("TRIBOS_API_TOKENS", "alice-token:alice,bob-token:bob")
    store_mod._STORE = None
    fid = tf.save_files("alice", [("csv", "values.csv", b"a,b\n1,2\n")])[0]["id"]
    with TestClient(backend_main.app) as api:
        ok = api.get(f"/api/files/{fid}", headers={"Authorization": "Bearer alice-token"})
        assert ok.status_code == 200 and ok.content == b"a,b\n1,2\n"
        assert "attachment" in ok.headers["content-disposition"] and "values.csv" in ok.headers["content-disposition"]
        inline = api.get(f"/api/files/{fid}?inline=1", headers={"Authorization": "Bearer alice-token"})
        assert inline.headers["content-disposition"].startswith("inline")
        assert api.get(f"/api/files/{fid}", headers={"Authorization": "Bearer bob-token"}).status_code == 404
    store_mod._STORE = None


def test_a_revision_cannot_flatten_the_drafts_code():
    from tribos.agents.orchestration.verify import preserve_code_blocks

    draft = "Script:\n\n```python\nwith open('f') as f:\n    for t in x:\n        print(t)\n```\n\nConfidence: low."
    flattened = "Script:\n\n```python\nwith open('f') as f:\n for t in x:\n print(t)\n```\n\nConfidence: moderate."
    fixed = preserve_code_blocks(draft, flattened)
    assert "    for t in x:\n        print(t)" in fixed and fixed.endswith("Confidence: moderate.")
    changed = "```python\nprint(2)\n```"
    assert preserve_code_blocks(draft, changed) == changed  # different code is left as the revision wrote it
