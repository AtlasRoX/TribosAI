"""T5: optional Lean 4 proof checking, tested with a fake `lean` executable (a Python script)."""

from __future__ import annotations

import asyncio
import textwrap
from pathlib import Path
from types import SimpleNamespace

import pytest

FAKE_LEAN = textwrap.dedent('''
    import pathlib, sys, time
    path = sys.argv[-1]
    code = pathlib.Path(path).read_text(encoding="utf-8")
    log = pathlib.Path(__file__).with_suffix(".calls")
    log.write_text(str(int(log.read_text() or 0) + 1) if log.exists() else "1")
    if "SLEEP" in code:
        time.sleep(10)
    if "bad_lemma" in code:
        print(f"{path}:3:8: error: unknown identifier 'bad_lemma'")
        print("  in the proof of foo")
        print(f"{path}:5:2: warning: unused variable 'h'")
        sys.exit(1)
    if "sorry" in code:
        print(f"{path}:2:8: warning: declaration uses 'sorry'")
    sys.exit(0)
''')

GOOD = "theorem two_add_two : 2 + 2 = 4 := by\n  rfl\n"
BAD = "theorem foo (n : Nat) : n + 0 = n := by\n  intro h\n  exact bad_lemma n\n"
SORRY = "theorem foo (n : Nat) : n + 0 = n := by\n  sorry\n"


@pytest.fixture
def lean(tmp_path, monkeypatch) -> Path:
    from tribos.verify.formal import clear_cache

    script = tmp_path / "lean.py"
    script.write_text(FAKE_LEAN, encoding="utf-8")
    monkeypatch.setenv("TRIBOS_LEAN_PATH", str(script))
    monkeypatch.delenv("TRIBOS_LEAN_PROJECT", raising=False)
    clear_cache()
    yield script
    clear_cache()


def _calls(script: Path) -> int:
    log = script.with_suffix(".calls")
    return int(log.read_text()) if log.exists() else 0


def test_a_clean_compile_is_formally_verified(lean):
    from tribos.verify.formal import check_lean

    result = check_lean(GOOD)
    assert result["status"] == "verified" and result["title"] == "formally verified (Lean)" and result["messages"] == []


def test_compiler_output_is_parsed(lean):
    from tribos.verify.formal import check_lean, parse_messages

    result = check_lean(BAD)
    assert result["status"] == "failed" and result["title"] == "formalisation failed"
    assert result["error"].startswith("unknown identifier 'bad_lemma'")
    errors = [m for m in result["messages"] if m["severity"] == "error"]
    assert errors[0]["line"] == 3 and errors[0]["column"] == 8 and "in the proof of foo" in errors[0]["message"]
    assert parse_messages("X.lean:1:2: info: hello")[0] == {"line": 1, "column": 2, "severity": "info", "message": "hello"}
    assert "Proof.lean" in result["output"] and str(lean.parent) not in result["output"]  # no server paths


def test_sorry_admit_and_axioms_are_never_verified(lean):
    from tribos.verify.formal import check_lean, uses_unproved

    assert check_lean(SORRY)["status"] == "failed"
    assert check_lean("theorem t : False := by\n  admit\n")["status"] == "failed"
    axiom = check_lean("axiom cheat : False\ntheorem t : False := cheat\n")
    assert axiom["status"] == "failed" and "axiom cheat" in axiom["error"]
    assert uses_unproved("-- sorry in a comment\ntheorem t : True := trivial") == []


def test_the_timeout(lean, monkeypatch):
    from tribos.verify.formal import check_lean

    monkeypatch.setenv("TRIBOS_FORMAL_TIMEOUT_S", "1")
    result = check_lean("-- SLEEP\ntheorem t : True := trivial\n")
    assert result["status"] == "timeout" and result["title"] == "formalisation failed" and "1 s" in result["error"]


def test_results_are_cached_by_content(lean):
    from tribos.verify.formal import check_lean

    first = check_lean(GOOD)
    second = check_lean(GOOD)
    assert not first["cached"] and second["cached"] and second["status"] == "verified"
    assert _calls(lean) == 1
    check_lean(GOOD + "\n-- changed\n")
    assert _calls(lean) == 2


def test_without_lean_the_checker_is_unavailable(monkeypatch, tmp_path):
    from tribos.verify.formal import check_lean, formalise_and_check

    monkeypatch.setenv("TRIBOS_LEAN_PATH", str(tmp_path / "missing-lean"))
    monkeypatch.setenv("PATH", str(tmp_path))
    assert check_lean(GOOD)["status"] == "unavailable"
    called = []

    async def model(system: str, user: str) -> str:
        called.append(user)
        return GOOD

    result = asyncio.run(formalise_and_check("Prove that 2 + 2 = 4.", model))
    assert result["title"] == "formal checker unavailable" and called == []  # no model call is spent


def test_the_repair_loop_feeds_errors_back(lean, monkeypatch):
    from tribos.verify.formal import formalise_and_check

    monkeypatch.setenv("TRIBOS_FORMAL_MAX_REPAIRS", "2")
    prompts: list[str] = []
    replies = iter([f"```lean\n{BAD}```", f"Here is the fix:\n```lean\n{GOOD}```"])

    async def model(system: str, user: str) -> str:
        prompts.append(user)
        return next(replies)

    result = asyncio.run(formalise_and_check("Prove that 2 + 2 = 4.", model))
    assert result["status"] == "verified" and result["repairs"] == 1
    assert "unknown identifier 'bad_lemma'" in prompts[1] and "Mathlib is NOT available" in prompts[0]
    assert result["statement"] == "theorem two_add_two : 2 + 2 = 4"


def test_the_repair_budget_ends_with_the_last_error(lean, monkeypatch):
    from tribos.verify.formal import formalise_and_check

    monkeypatch.setenv("TRIBOS_FORMAL_MAX_REPAIRS", "1")

    async def model(system: str, user: str) -> str:
        return f"```lean\n{BAD}```"

    result = asyncio.run(formalise_and_check("Prove that n + 0 = n.", model))
    assert result["status"] == "failed" and len(result["attempts"]) == 2 and "bad_lemma" in result["error"]


def _state(question: str, reply: str | None):
    async def complete(system, user, phase="agent"):
        return reply

    async def step(*args, **kwargs):
        return None

    results: dict = {}
    return SimpleNamespace(
        clean_query=question, query=question, artifacts={}, evidence_sections=[], brief_notes=[], scope_notes=[],
        llm=SimpleNamespace(available=reply is not None, complete=complete), step=step, bag={},
        add_result=lambda key, res, **kw: results.setdefault(key, res), results=results,
        mark_phase=lambda key, status, reason="": results.setdefault("_mark", (status, reason)),
    )


def test_math_agent_integration_with_a_fake_model(lean):
    from tribos.agentic.formal_proof import FormalProofPhase

    phase = FormalProofPhase()
    state = _state("Prove that 2 + 2 = 4.", f"```lean\n{GOOD}```")
    assert phase.applies(state)
    outcome = asyncio.run(phase.run(state))
    art = outcome.artifacts["formal_proof"]
    assert art["status"] == "verified" and art["statement"].startswith("theorem two_add_two")
    assert "<formal_proof status=\"verified\"" in state.evidence_sections[0]
    assert "formally verified by Lean" in state.brief_notes[0] and not state.scope_notes
    assert state.results["agent.formal_proof.result"].tool_name == "axiom_formal_check"

    failing = _state("Prove that n + 0 = n.", f"```lean\n{SORRY}```")
    art = asyncio.run(phase.run(failing)).artifacts["formal_proof"]
    assert art["title"] == "formalisation failed" and "do not claim" in failing.scope_notes[0]
    assert not phase.applies(_state("What is 2 + 2?", None))


def test_without_lean_the_phase_changes_nothing_else(monkeypatch, tmp_path):
    from tribos.agentic.formal_proof import FormalProofPhase

    monkeypatch.setenv("TRIBOS_LEAN_PATH", str(tmp_path / "none"))
    monkeypatch.setenv("PATH", str(tmp_path))
    state = _state("Prove that 2 + 2 = 4.", GOOD)
    art = asyncio.run(FormalProofPhase().run(state)).artifacts["formal_proof"]
    assert art["title"] == "formal checker unavailable"
    assert state.evidence_sections == [] and state.brief_notes == [] and state.scope_notes == []


def test_the_tool_executes_code_and_is_never_replayed(lean):
    from tribos.agentic.plan_graph import executes_code
    from tribos.extensions.formal import execute_formal_check
    from tribos.provenance.rerun import tool_replay_refusal
    from tribos.tools.registry import get_tool_registry

    entry = get_tool_registry().get_entry("axiom_formal_check")
    assert entry is not None and executes_code(entry) and tool_replay_refusal("axiom_formal_check", entry)
    res = execute_formal_check(GOOD)
    assert res.success and res.data["status"] == "verified" and res.data["statement"].startswith("theorem")
