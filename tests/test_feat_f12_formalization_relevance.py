from __future__ import annotations

import asyncio
from typing import Any

from tribos.tools.policy import ToolPolicy, enforce_tool_policy
from tribos.verify.formal import prove, runner
from tribos.verify.formal.correspondence import needs_library, statement_issues
from tribos.verify.formal.runner import uses_unproved


def test_f12_compiling_supported_nat_lemma(monkeypatch):
    """Compiling a supported natural number lemma via core Lean 4."""
    called_code = []

    def mock_check(code: str) -> dict[str, Any]:
        called_code.append(code)
        return {
            "status": "verified",
            "title": runner.STATUS_TITLES["verified"],
            "messages": [],
            "error": None,
            "output": "Proof checked cleanly.",
            "unproved": [],
            "checker": "lean",
        }

    monkeypatch.setattr(prove, "find_lean", lambda: {"argv": ["lean"], "cwd": None, "kind": "lean"})
    monkeypatch.setattr(prove, "check_lean", mock_check)

    replies = [
        "```lean\ntheorem nat_add_zero (n : Nat) : n + 0 = n := by\n  omega\n```"
    ]

    async def mock_complete(system: str, user: str) -> str:
        return replies.pop(0)

    question = "Prove that for every natural number n, n + 0 = n."
    art = asyncio.run(prove.formalise_and_check(question, mock_complete, mathlib=False))

    assert art["status"] == "verified"
    assert "omega" in art["lean_code"]
    assert len(art["attempts"]) == 1
    assert art["attempts"][0]["status"] == "verified"
    assert art["attempts"][0]["output"] == "Proof checked cleanly."


def test_f12_compiling_supported_rational_lemma_without_mathlib(monkeypatch):
    """Rational numbers are supported via Rat in core Lean 4 (Init.Data.Rat) without Mathlib."""
    q_rat = "Prove that for any rational number q, q + 0 = q."
    # Rational numbers do not require Mathlib
    assert needs_library(q_rat) is None

    # Core notation replaces Mathlib notation with core names
    code_with_unicode = "theorem rat_add (q : ℚ) : q + 0 = q := by rfl"
    notated = prove.core_notation(code_with_unicode)
    assert "Rat" in notated
    assert "ℚ" not in notated

    def mock_check(code: str) -> dict[str, Any]:
        return {
            "status": "verified",
            "title": runner.STATUS_TITLES["verified"],
            "messages": [],
            "error": None,
            "output": "Rat proof verified.",
            "unproved": [],
            "checker": "lean",
        }

    monkeypatch.setattr(prove, "find_lean", lambda: {"argv": ["lean"], "cwd": None, "kind": "lean"})
    monkeypatch.setattr(prove, "check_lean", mock_check)

    async def mock_complete(system: str, user: str) -> str:
        return "```lean\ntheorem rat_add (q : ℚ) : q + 0 = q := by rfl\n```"

    art = asyncio.run(prove.formalise_and_check(q_rat, mock_complete, mathlib=False))
    assert art["status"] == "verified"
    assert "Rat" in art["lean_code"]


def test_f12_unavailable_library_scoped_honestly(monkeypatch):
    """A statement needing complex analysis / reals is reported honestly as requiring Mathlib."""
    monkeypatch.setattr(prove, "find_lean", lambda: {"argv": ["lean"], "cwd": None, "kind": "lean"})
    asked: list[str] = []

    async def mock_complete(system: str, user: str) -> str:
        asked.append(user)
        return "```lean\ntheorem riemann_hypothesis : False := by sorry\n```"

    q_complex = (
        "Make a serious attempt to prove the Riemann Hypothesis for the analytically continued "
        "Riemann zeta function with 0 < Re(s) < 1."
    )
    art = asyncio.run(prove.formalise_and_check(q_complex, mock_complete, mathlib=False))

    assert art["status"] == "not_formalizable"
    assert len(asked) == 0  # No model calls spent
    assert "requires the Mathlib library" in art["error"]
    assert "TRIBOS_LEAN_PROJECT is not configured" in art["error"]
    assert "core Lean 4 cannot express" not in art["error"]  # Honest scoping


def test_f12_wrong_target_and_trivial_tautologies_rejected():
    """Unrelated targets, trivial True/False/tautologies must be rejected before compilation."""
    q = "Prove that for every natural number n, n + 0 = n."

    # Unrelated target False without refutation request
    assert statement_issues(q, "theorem t : False", mathlib=False) != []

    # True target
    assert statement_issues(q, "theorem t : True", mathlib=False) != []

    # Trivial 1 = 1 or 0 = 0
    assert statement_issues(q, "theorem t : 1 = 1", mathlib=False) != []
    assert statement_issues(q, "theorem t : 0 = 0", mathlib=False) != []

    # Reflexivity tautology
    assert statement_issues(q, "theorem t (n : Nat) : n = n", mathlib=False) != []

    # Unrelated constants
    q_arith = "Prove that 17 * 23 = 391."
    assert statement_issues(q_arith, "theorem t : 2 + 2 = 4", mathlib=False) != []


def test_f12_domain_mismatch_rejected():
    """Changing domain from Nat to Real/Int or Int to Nat is rejected as a domain mismatch."""
    q_nat = "Prove that for every natural number n, n + 0 = n."
    # Changed to Real
    issues_real = statement_issues(q_nat, "theorem t (n : Real) : n + 0 = n", mathlib=True)
    assert any("domain mismatch" in issue for issue in issues_real)

    # Changed to Int
    issues_int = statement_issues(q_nat, "theorem t (n : Int) : n + 0 = n", mathlib=False)
    assert any("domain mismatch" in issue for issue in issues_int)

    # Question over integer changed to Nat
    q_int = "Prove that for every integer n, n - n = 0."
    issues_nat = statement_issues(q_int, "theorem t (n : Nat) : n - n = 0", mathlib=False)
    assert any("domain mismatch" in issue for issue in issues_nat)


def test_f12_assumed_conclusion_rejected():
    """Injected conclusion assumption in binders or implications is rejected."""
    q = "Prove that for every natural number n, n + 0 = n."

    # In binders
    issues_binder = statement_issues(q, "theorem t (n : Nat) (h : n + 0 = n) : n + 0 = n", mathlib=False)
    assert any("conclusion is assumed as a hypothesis" in issue for issue in issues_binder)

    # In top-level implication
    issues_impl = statement_issues(q, "theorem t (n : Nat) : (n + 0 = n) -> (n + 0 = n)", mathlib=False)
    assert any("hypothesis assumes its target" in issue for issue in issues_impl)

    # Chained implication P -> Q -> P
    issues_chained = statement_issues(q, "theorem t (n : Nat) : (n + 0 = n) → (n = n) → (n + 0 = n)", mathlib=False)
    assert any("hypothesis assumes its target" in issue for issue in issues_chained)


def test_f12_proof_holes_and_cheat_axioms_rejected():
    """Proof holes (sorry, admit) and injected cheat axioms are rejected."""
    code_sorry = "theorem t (n : Nat) : n + 0 = n := by sorry"
    assert "sorry" in uses_unproved(code_sorry)

    code_admit = "theorem t (n : Nat) : n + 0 = n := by admit"
    assert "admit" in uses_unproved(code_admit)

    code_cheat = "axiom cheat : False\ntheorem t : False := cheat"
    unproved = uses_unproved(code_cheat)
    assert "axiom cheat" in unproved


def test_f12_trusted_foundational_axioms_permitted():
    """Normal trusted foundational axioms used by Lean/Mathlib are not blanket-banned."""
    code_propext = "axiom propext {p q : Prop} : (p ↔ q) → p = q\ntheorem t : True := trivial"
    assert "axiom propext" not in uses_unproved(code_propext)

    code_choice = "axiom Classical.choice {α : Sort u} : Nonempty α → α"
    assert "axiom Classical.choice" not in uses_unproved(code_choice)

    code_quot = "axiom Quot.sound {α : Sort u} : Quot.sound"
    assert "axiom Quot.sound" not in uses_unproved(code_quot)


def test_f12_no_formal_policy_controls(monkeypatch):
    """User policy prohibiting formal verification returns status='disabled'."""
    monkeypatch.setattr(prove, "find_lean", lambda: {"argv": ["lean"], "cwd": None, "kind": "lean"})

    called = False

    async def mock_complete(system: str, user: str) -> str:
        nonlocal called
        called = True
        return "theorem t : True := trivial"

    pol = ToolPolicy(prohibit_formal=True, formal_reason="User banned formal proof")
    with enforce_tool_policy(pol):
        art = asyncio.run(prove.formalise_and_check("Prove 1 = 1", mock_complete))
        assert art["status"] == "disabled"
        assert not called
        assert "User banned formal proof" in art["error"]
        assert art["attempts"] == []


def test_f12_compiler_failure_recorded_and_repaired(monkeypatch):
    """Compiler errors are recorded with attempt count and output; repair loop triggers."""
    monkeypatch.setattr(prove, "find_lean", lambda: {"argv": ["lean"], "cwd": None, "kind": "lean"})
    monkeypatch.setattr(prove, "get_int", lambda name: 2)

    call_count = 0

    def mock_check(code: str) -> dict[str, Any]:
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return {
                "status": "failed",
                "title": runner.STATUS_TITLES["failed"],
                "messages": [{"line": 2, "column": 5, "severity": "error", "message": "type mismatch at argument 2"}],
                "error": "type mismatch at argument 2",
                "output": "line 2:5 error: type mismatch at argument 2",
                "unproved": [],
                "checker": "lean",
            }
        return {
            "status": "verified",
            "title": runner.STATUS_TITLES["verified"],
            "messages": [],
            "error": None,
            "output": "Clean compilation.",
            "unproved": [],
            "checker": "lean",
        }

    monkeypatch.setattr(prove, "check_lean", mock_check)

    replies = [
        "```lean\ntheorem t (n : Nat) : n + 0 = n := by\n  apply Nat.mul_le_mul_right\n```",
        "```lean\ntheorem t (n : Nat) : n + 0 = n := by\n  omega\n```",
    ]

    async def mock_complete(system: str, user: str) -> str:
        return replies.pop(0)

    question = "Prove that for every natural number n, n + 0 = n."
    art = asyncio.run(prove.formalise_and_check(question, mock_complete, mathlib=False))

    assert art["status"] == "verified"
    assert len(art["attempts"]) == 2
    assert art["attempts"][0]["status"] == "failed"
    assert "type mismatch" in art["attempts"][0]["error"]
    assert "type mismatch" in art["attempts"][0]["output"]
    assert art["attempts"][1]["status"] == "verified"
    assert art["repairs"] == 1
