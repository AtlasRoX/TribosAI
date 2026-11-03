"""Harness upgrades from docs/plans/tribos-harness-landscape.md: CodeAct session, construct mode, Lean premises,
blueprint, lemma library, default Mathlib imports, Poisson FEM, skills, MCP client, PDF full text, reviser."""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

import httpx
import pytest


def test_python_session_keeps_state_and_drops_failed_cells():
    from tribos.agentic.sandbox.session import PythonSession

    s = PythonSession()
    assert s.run("x = 6\nprint('set')").status == "ok"
    b = s.run("print(x * 7)")
    assert b.status == "ok" and b.stdout == "42"
    c = s.run("print(undefined_name)")
    assert c.status != "ok" and "line 1" in c.error and len(s.cells) == 2


def test_codeact_runs_cells_until_the_final_answer():
    from tribos.agentic.codeact import solve

    replies = iter(["```python\nn = 100\ns = sum(k * k for k in range(1, n + 1))\nprint(s)\n```",
                    "```python\nprint(s == n * (n + 1) * (2 * n + 1) // 6)\n```",
                    "FINAL ANSWER: 338350, checked against the closed form."])

    async def ask(_system, _messages):
        return next(replies)

    r = asyncio.run(solve("Sum of the first 100 squares?", ask))
    assert r["final"].startswith("338350") and [c["stdout"] for c in r["cells"]] == ["338350", "True"]


def test_codeact_evidence_says_numerics_are_not_proof():
    from tribos.agents.stem_evidence import render_codeact
    from tribos.tools.registry import ToolResult

    res = ToolResult(success=True, tool_name="codeact", data={"cells": [{"code": "print(1)", "status": "ok",
                                                                         "stdout": "1"}], "final": "one"})
    text = "\n".join(render_codeact(res))
    assert "not a proof" in text and "<output>1</output>" in text


@pytest.mark.parametrize("question,key,known", [
    ("Find the shortest Golomb ruler with 10 marks", "golomb_10", 55),
    ("Construct a large cap set in F_3^4", "cap_set_4", 20),
    ("no-three-in-line on a 10 x 10 grid", "no_three_10", 20),
])
def test_construct_mode_detects_problems_and_seed_programs_are_valid(question, key, known):
    from tribos.agentic.construct import detect_problem, evaluate

    p = detect_problem(question)
    assert p is not None and p.key == key and p.known_best == known
    r = evaluate(p, p.seed)
    assert r["valid"] is True


def test_construct_search_rejects_duplicates_and_rescores_the_best():
    from tribos.agentic.construct import detect_problem, facts, rescore, search

    p = detect_problem("Golomb ruler with 6 marks")
    assert rescore(p, [0, 1, 2, 5, 8])["valid"] is False  # difference 1 repeated
    good = "```python\ndef construct():\n    return [0, 1, 4, 10, 12, 17]\n```"
    bad = "```python\ndef construct():\n    return [0, 1, 2, 3, 4, 5]\n```"
    replies = iter([good, bad, good, bad])

    async def ask(_s, _p):
        return next(replies)

    r = asyncio.run(search(p, ask, candidates=4))
    d = facts(r)
    assert r["best"].value == 17 and r["confirmed"] and r["rejected_duplicates"] == 2
    assert d["verdict"].startswith("matches the best known value 17")


def test_poisson_finite_elements_converge_at_the_theoretical_orders():
    from tribos.writer.pde_facts import compute_pde_facts

    d = compute_pde_facts("Solve the Poisson equation -Δu = f on the unit square with finite elements; show convergence")
    assert d["kind"] == "pde_poisson" and all(c["passed"] for c in d["checks"])
    assert abs(d["refinement"][-1]["l2_order"] - 2) < 0.05 and abs(d["refinement_p2"][-1]["l2_order"] - 3) < 0.1


def test_bare_mathlib_import_is_replaced_by_the_default_set(monkeypatch):
    from tribos.verify.formal.runner import DEFAULT_MATHLIB_IMPORTS, with_default_imports

    out = with_default_imports("import Mathlib\n\ntheorem t : 1 = 1 := rfl\n")
    assert "import Mathlib\n" not in out and all(f"import {m}" in out for m in DEFAULT_MATHLIB_IMPORTS)
    assert with_default_imports("import Mathlib.Tactic.Ring\n") == "import Mathlib.Tactic.Ring\n"
    monkeypatch.setenv("TRIBOS_LEAN_FULL_MATHLIB", "1")
    assert with_default_imports("import Mathlib\n") == "import Mathlib\n"


def test_lean_timeout_kills_the_child_process_that_holds_the_pipes(tmp_path):
    """`lake env lean` runs lean as a child; a timeout that killed only lake left lean running (GBs of Mathlib) and
    the pipes open, so the check hung far past its timeout."""
    import subprocess
    import time

    import psutil

    from tribos.verify.formal.runner import _run_tree

    pid_file = tmp_path / "child.pid"
    parent = tmp_path / "parent.py"
    parent.write_text(
        "import subprocess, sys, time\n"
        f"c = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(120)'])\n"
        f"open(r'{pid_file}', 'w').write(str(c.pid))\n"
        "time.sleep(120)\n", encoding="utf-8")
    t = time.monotonic()
    with pytest.raises(subprocess.TimeoutExpired):
        _run_tree([sys.executable, str(parent)], str(tmp_path), timeout=3)
    assert time.monotonic() - t < 20
    child = int(pid_file.read_text())
    for _ in range(50):
        if not psutil.pid_exists(child) or psutil.Process(child).status() == psutil.STATUS_ZOMBIE:
            break
        time.sleep(0.1)
    assert not psutil.pid_exists(child) or psutil.Process(child).status() == psutil.STATUS_ZOMBIE


def test_premise_hints_look_up_unknown_names_in_loogle(monkeypatch):
    from tribos.verify.formal import premises

    monkeypatch.setenv("TRIBOS_LEAN_PREMISE_SEARCH", "1")

    def handler(request):
        assert request.url.host == "loogle.lean-lang.org"
        return httpx.Response(200, json={"hits": [{"name": "Nat.add_sub_cancel_left", "type": "n + m - n = m",
                                                   "module": "Mathlib"}]})

    errors = "error: unknown identifier 'Nat.add_sub_cancel_left2'"
    assert premises.unknown_names(errors) == ["Nat.add_sub_cancel_left2"]
    hint = premises.premise_hints(errors, transport=httpx.MockTransport(handler))
    assert "Nat.add_sub_cancel_left : n + m - n = m" in hint


def test_lemma_library_remembers_and_recalls_checked_theorems(tmp_path):
    from tribos.verify.formal import premises

    path = tmp_path / "lib.json"
    premises.remember("prove that 2ab <= a^2 + b^2 for real a b", "theorem t (a b : ℝ) : 2*a*b ≤ a^2+b^2",
                      "theorem t ... := by nlinarith", path=path)
    hits = premises.recall("show 2ab <= a^2 + b^2 for reals a and b", path=path)
    assert hits and hits[0]["code"].endswith("nlinarith")
    assert premises.recall("integrate sin over a circle", path=path) == []
    assert "previously proved" in premises.library_hint("prove 2ab <= a^2 + b^2 real", path=path)


def test_blueprint_proves_lemmas_separately_and_checks_the_assembly(monkeypatch):
    from tribos.verify.formal import blueprint

    skeleton = ("import Mathlib\n\nlemma l1 (a b : ℝ) : 0 ≤ (a - b) ^ 2 := by\n  sorry\n\n"
                "theorem main (a b : ℝ) : 2 * a * b ≤ a ^ 2 + b ^ 2 := by\n  nlinarith [l1 a b]\n")
    proved = "lemma l1 (a b : ℝ) : 0 ≤ (a - b) ^ 2 := by\n  positivity\n"
    checked: list[str] = []

    def fake_check(code):
        checked.append(code)
        if "sorry" in code:
            return {"status": "failed", "messages": [{"severity": "warning", "line": 3, "message": "declaration uses 'sorry'"}]}
        return {"status": "verified", "messages": []}

    monkeypatch.setattr(blueprint, "check_lean", fake_check)
    replies = iter([f"```lean\n{skeleton}```", f"```lean\n{proved}```"])

    async def complete(_s, _u):
        return next(replies)

    from tribos.verify.formal.prove import lean_code

    header, decls = blueprint.split_decls(skeleton)
    assert header.startswith("import Mathlib") and [n for n, _ in decls] == ["l1", "main"]
    r = asyncio.run(blueprint.prove_by_blueprint("theorem main (a b : ℝ) : 2 * a * b ≤ a ^ 2 + b ^ 2", "q",
                                                 complete, "env", code_of=lean_code))
    assert r["status"] == "verified" and r["lemmas"] == [{"name": "l1", "proved": True, "repairs": 0}]
    assert "positivity" in r["lean_code"] and "sorry" not in r["lean_code"]


def test_skills_match_questions_and_build_a_prompt_section():
    from tribos.skills import select_skills, skills_prompt

    assert [s.name for s in select_skills("Find a Golomb ruler construction with 10 marks")] == ["constructions"]
    assert "open-problems" in [s.name for s in select_skills("Make progress on the Navier-Stokes open problem")]
    assert skills_prompt("What is the capital of France?") == ""
    assert "Skill: proof-writing" in skills_prompt("Prove that sqrt(2) is irrational")


def test_mcp_client_registers_and_calls_a_stdio_server(tmp_path, monkeypatch):
    from tribos.tools.mcp_client import _CLIENTS, register_mcp_tools
    from tribos.tools.registry import AdapterType, ToolRegistry

    server = tmp_path / "server.py"
    server.write_text(
        "import json, sys\n"
        "for line in sys.stdin:\n"
        "    m = json.loads(line)\n"
        "    if 'id' not in m: continue\n"
        "    if m['method'] == 'initialize': r = {'protocolVersion': '2025-06-18', 'capabilities': {}}\n"
        "    elif m['method'] == 'tools/list': r = {'tools': [{'name': 'echo'}]}\n"
        "    else: r = {'content': [{'type': 'text', 'text': 'echo:' + json.dumps(m['params']['arguments'])}]}\n"
        "    print(json.dumps({'jsonrpc': '2.0', 'id': m['id'], 'result': r}), flush=True)\n", encoding="utf-8")
    monkeypatch.setenv("TRIBOS_MCP_CLIENT_SERVERS", json.dumps({"t": {"command": [sys.executable, str(server)],
                                                                      "tools": ["echo"]}}))
    _CLIENTS.pop("t", None)
    reg = ToolRegistry()
    assert register_mcp_tools(reg) == ["mcp_t_echo"]
    assert reg.get_entry("mcp_t_echo").adapter_type == AdapterType.REMOTE_MCP

    async def go():
        try:
            return await reg._executors["mcp_t_echo"](arguments={"x": 1})
        finally:
            await _CLIENTS["t"].close()

    res = asyncio.run(go())
    assert res.success and res.data["text"] == 'echo:{"x": 1}'


def test_pdf_paragraphs_are_extracted_and_ranked(monkeypatch):
    from tribos.archivon import engine as eng

    monkeypatch.setattr(eng, "_pdf_paragraphs", lambda data: [
        "The blow-up criterion for Navier-Stokes solutions is shown " + "in detail " * 30,
        "Acknowledgements " + "thanks " * 50])

    def handler(request):
        return httpx.Response(200, content=b"%PDF-1.4", headers={"content-type": "application/pdf"})

    monkeypatch.setenv("TRIBOS_ARCHIVON_PDF_FULLTEXT", "1")
    e = eng.ArchivonEngine(transport=httpx.MockTransport(handler), check_integrity=False)
    passages = [{"title": "Paper A", "passage_id": "p1", "score": 1.0}]
    out = asyncio.run(e._pdf_passages(passages, ["navier", "stokes"], {"Paper A": "https://x.org/a.pdf"}))
    assert len(out) == 1 and out[0]["section"] == "Full text (PDF)" and "blow-up" in out[0]["passage_text"]


def test_construction_and_poisson_results_have_panels_and_evidence():
    from tribos.agents.stem_evidence import render_computed_results
    from tribos.tools.registry import ToolResult
    from tribos.writer.genui import build_answer_ui
    from tribos.writer.pde_facts import compute_pde_facts

    d = compute_pde_facts("Poisson equation on the unit square by finite elements: mesh convergence")
    assert [b["type"] for b in build_answer_ui(d)["blocks"]] == ["stats", "equation", "chart", "table", "checks"]
    text = "\n".join(render_computed_results(ToolResult(success=True, tool_name="computed_results", data=d)))
    assert "l2_order" in text


def test_settings_reference_lists_the_new_settings():
    text = Path(".env.example").read_text(encoding="utf-8")
    for name in ("TRIBOS_CODEACT", "TRIBOS_CONSTRUCT", "TRIBOS_LEAN_PREMISE_SEARCH", "TRIBOS_FORMAL_BLUEPRINT",
                 "TRIBOS_MCP_CLIENT_SERVERS", "TRIBOS_SKILLS_DIR", "TRIBOS_ARCHIVON_PDF_FULLTEXT"):
        assert name in text
