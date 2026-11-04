"""The Lean stage: only the formal part of a numbered question, and blueprint files with their imports at the top."""

from __future__ import annotations

from tribos.agentic.formal_proof import formal_part
from tribos.verify.formal.blueprint import _merge

QUESTION = (
    "Let f(x,y) = x^3 - 3x + y^2 on the domain -2 <= x <= 2.\n\n"
    "1. Find all critical points of f in the domain.\n"
    "2. Plot f as a filled contour plot.\n"
    "3. Prove in Lean that for all natural numbers n, n^3 - n is divisible by 3.\n"
)


def test_only_the_lean_part_reaches_the_prover():
    assert formal_part(QUESTION) == "Prove in Lean that for all natural numbers n, n^3 - n is divisible by 3."
    assert formal_part("Prove in Lean that 2 + 2 = 4.") == "Prove in Lean that 2 + 2 = 4."  # not numbered: unchanged


def test_a_lemma_reply_with_its_own_imports_makes_a_valid_file():
    before = "import Mathlib.Tactic\n\nlemma a : True := sorry\n"
    reply = "import Mathlib.Tactic\nimport Mathlib.Data.ZMod.Basic\n\nlemma b : True := trivial\n"
    merged = _merge(before, reply)
    lines = [line for line in merged.splitlines() if line.strip()]
    assert lines[:2] == ["import Mathlib.Data.ZMod.Basic", "import Mathlib.Tactic"]
    assert not any(line.startswith("import") for line in lines[2:])  # no import after a declaration


def test_the_lean_phase_runs_in_the_background_and_joins_before_the_answer(monkeypatch):
    import asyncio
    from types import SimpleNamespace

    from tribos.agentic import formal_proof as fp

    async def fake_formalise(question, complete, **_kw):
        await asyncio.sleep(0.05)
        return {"status": "verified", "title": "verified", "statement": "theorem t : True", "lean_code": "",
                "attempts": [{}], "messages": [], "output": ""}

    monkeypatch.setattr(fp, "formalise_and_check", fake_formalise)
    monkeypatch.setattr(fp, "find_lean", lambda: {"argv": ["lean"]})
    steps: list[str] = []

    async def step(*args, **_kw):
        steps.append(args[1])

    state = SimpleNamespace(clean_query="Prove in Lean that 1 = 1.", query="", artifacts={}, evidence_sections=[],
                            brief_notes=[], scope_notes=[], bag={}, step=step, tool_policy=None,
                            llm=SimpleNamespace(available=True, complete=None),
                            add_result=lambda *a, **k: None, mark_phase=lambda *a, **k: None)
    run = SimpleNamespace(agent_state=state, execution_artifacts={})

    async def go():
        outcome = await fp.FormalProofPhase().run(state)
        assert outcome.artifacts == {} and "formal_task" in state.bag  # started, not awaited
        return await fp.await_formal_proof(run)

    art = asyncio.run(go())
    assert art["status"] == "verified" and run.execution_artifacts["formal_proof"] is art
    assert "formal_task" not in state.bag and "formally verified by Lean" in state.brief_notes[0]
