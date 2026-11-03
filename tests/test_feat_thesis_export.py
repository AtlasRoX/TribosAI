"""Thesis exports (tribos.export.thesis): typeset HTML and PDF, DOCX, the reproducibility bundle, the fpdf2
fallback, and the API's file guard."""

from __future__ import annotations

import asyncio
import io
import os
import time
import zipfile
from typing import Any

import pytest

from tests.test_feat_research_loop import GOAL, FakeModel, _result
from tribos.agentic import campaign as cmod
from tribos.agentic import jobs as jobs_mod
from tribos.export import thesis as tx


@pytest.fixture(scope="module")
def finished(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("thesis")
    from tribos.verify.formal import prove as prove_mod

    async def fake_formal(statement, complete, **kw):
        return {"status": "verified", "title": "Formally verified (Lean)", "lean_code": "theorem t : True := trivial",
                "statement": "theorem t : True"}

    original = prove_mod.formalise_and_check
    prove_mod.formalise_and_check = fake_formal

    async def runner(request, *, user_id, event_callback, run_control, api_key=None):
        return _result("The formula $S(N)=N(N+1)(2N+1)/6$ is classical [1].")

    async def go():
        jm = jobs_mod.JobManager(jobs_mod.JobStore(str(tmp / "jobs")), runner=runner, workers=2)
        m = cmod.CampaignManager(cmod.CampaignStore(str(tmp / "campaigns")), jobs=jm)
        m.research_model = lambda c: FakeModel()
        c = await m.submit("alice", GOAL, mode="loop")
        deadline = time.monotonic() + 120
        while m.store.get(c["campaign_id"])["status"] in cmod.RUNNING and time.monotonic() < deadline:
            await asyncio.sleep(0.1)
        return m, m.store.get(c["campaign_id"])

    try:
        m, c = asyncio.run(go())
    finally:
        prove_mod.formalise_and_check = original
    assert c["status"] == "succeeded"
    return c, os.path.join(m.store.storage_dir, f"{c['campaign_id']}_files")


def test_the_html_thesis_is_standalone_with_title_page_contents_figures_and_math(finished):
    c, files = finished
    html = tx.thesis_html(c, files)
    assert "Research thesis" in html and 'class="toc"' in html and "data:image/png;base64," in html
    # SVG figures are inlined (set in Google Sans, like the text); the fonts and the Tribos marks are embedded.
    assert '<div class="art svg"><svg' in html and "<figure" in html and "auto-render.min.js" in html
    assert "font-family: 'Google Sans'" in html and html.count("data:font/ttf;base64,") >= 4
    assert 'class="cover"' in html and 'alt="Tribos"' in html and "Phronesis" not in html
    assert "src=\"files/" not in html  # every figure is embedded


def test_the_pdf_is_typeset_by_chromium_or_falls_back_to_fpdf(finished, monkeypatch):
    c, files = finished
    pdf, engine = tx.thesis_pdf(c, files)
    assert pdf.startswith(b"%PDF") and engine in ("chromium", "fpdf")
    monkeypatch.setenv("TRIBOS_THESIS_PDF_ENGINE", "fpdf")
    plain, engine2 = tx.thesis_pdf(c, files)
    assert plain.startswith(b"%PDF") and engine2 == "fpdf"


def test_docx_and_bundle_carry_the_figures_code_and_ledger(finished):
    c, files = finished
    docx = tx.thesis_docx(c, files)
    with zipfile.ZipFile(io.BytesIO(docx)) as z:
        assert any(n.startswith("word/media/") for n in z.namelist())
    with zipfile.ZipFile(io.BytesIO(tx.thesis_bundle(c, files))) as z:
        names = z.namelist()
        assert "thesis.md" in names and "ledger.json" in names and "files/design.svg" in names
        assert any(n.startswith("code/") and n.endswith(".py") for n in names)
        assert any(n.startswith("proofs/") for n in names)


def test_the_api_serves_the_thesis_and_only_files_inside_the_project(finished, monkeypatch):
    from fastapi.testclient import TestClient

    from app.backend.main import app

    c, files = finished
    store = cmod.CampaignStore(os.path.dirname(files))
    manager = cmod.CampaignManager(store)
    cmod.set_campaign_manager(manager)
    try:
        uid = c["user_id"]
        from app.backend import auth

        app.dependency_overrides[auth.get_current_user] = lambda: uid
        client = TestClient(app)
        cid = c["campaign_id"]
        r = client.get(f"/api/campaigns/{cid}/thesis?format=md")
        assert r.status_code == 200 and "## 5 Results" in r.text
        fig = next(f for f in c["ledger"] if f.get("figures"))["figures"][0]["name"]
        assert client.get(f"/api/campaigns/{cid}/files/{fig}").status_code == 200
        assert client.get(f"/api/campaigns/{cid}/files/..%2F{cid}.json").status_code == 404
        assert client.get(f"/api/campaigns/{cid}/files/x.json").status_code == 404
        est = client.post("/api/campaigns/estimate", json={"goal": GOAL}).json()
        assert est["rough"] and est["remaining_s"] > 0
        listed = client.get("/api/campaigns").json()["campaigns"][0]
        assert listed["mode"] == "loop" and "ledger" not in listed
    finally:
        app.dependency_overrides.clear()
        cmod.set_campaign_manager(None)


def _unused(_: Any) -> None:  # keeps the import of Any meaningful for type checkers
    return None
