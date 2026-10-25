"""Formalise a "prove ..." question in Lean 4 with the model, check it, and repair it on compiler errors.

The model writes the theorem statement and its proof; Lean is the judge. On a compile error the model gets the
messages back, up to TRIBOS_FORMAL_MAX_REPAIRS times. The Lean statement is always returned so the reader can judge
whether it is faithful to the question: a proof of the wrong statement proves nothing about the question.

The outcome is "formally verified (Lean)" only on a clean compile with no sorry, admit or new axiom; otherwise
"formalisation failed" with the last error, or "formal checker unavailable" when Lean is not installed.
"""

from __future__ import annotations

import asyncio
import re
from collections.abc import Awaitable, Callable
from typing import Any

from tribos.config.settings import get_bool, get_int

from .correspondence import needs_library, statement_issues
from .runner import STATUS_TITLES, check_lean, find_lean

FORMALISE_SYSTEM = (
    "You formalise mathematics in Lean 4. Given a statement to prove, reply with exactly one ```lean code block "
    "containing the theorem (faithful to the statement: same hypotheses, same conclusion, no weakening) and a complete "
    "proof. Import Mathlib only if the environment has it (the user says so). Never use sorry, admit or axiom."
)
REPAIR_SYSTEM = (
    "You repair Lean 4 proofs. You get the previous code and Lean's error messages. Reply with exactly one ```lean code "
    "block with the corrected file. Keep the theorem statement unchanged unless it was itself the error; never use "
    "sorry, admit or axiom."
)
_BLOCK_RE = re.compile(r"```(?:lean4?|Lean)?\s*\n(.*?)```", re.S)
_THEOREM_RE = re.compile(r"^\s*(?:theorem|lemma|example)\b.*?(?=:=)", re.S | re.M)
PROVE_RE = re.compile(r"\b(prove|show that|demonstrate that|give a proof|proof that)\b", re.I)


# What core Lean 4 (no Mathlib) offers, so a formalisation is written for the checker that will run it.
CORE_LEAN_ENV = (
    "Mathlib is NOT available: use core Lean 4 only. No import lines. Write Nat and Int (not the Mathlib notation "
    "for them); there is no Real or Rat. Usable tactics: rfl, decide, simp, simp_arith, omega, exact, intro, intros, "
    "apply, refine, constructor, cases, rcases, obtain, induction, show, calc, have, by_cases, contradiction, "
    "exists, unfold. Not available: ring, linarith, nlinarith, norm_num, field_simp, positivity, Mathlib lemmas such "
    "as Nat.odd_iff or Even/Odd predicates (state parity as n % 2 = 1). omega decides linear arithmetic over Nat and "
    "Int, including % and / by numerals."
)


def core_notation(code: str) -> str:
    """Mathlib's notation for the integer types replaced by the core names it abbreviates (no change in meaning)."""
    return re.sub(r"\bimport\s+Mathlib\S*\s*\n", "", code).replace("ℕ", "Nat").replace("ℤ", "Int")


def formal_enabled() -> bool:
    return bool(get_bool("TRIBOS_FORMAL"))


def wants_proof(question: str) -> bool:
    return bool(PROVE_RE.search(question or ""))


def lean_code(reply: str) -> str:
    """The Lean code of a model reply: its first ```lean block, or the whole reply when it has none."""
    m = _BLOCK_RE.search(reply or "")
    return (m.group(1) if m else reply or "").strip()


def lean_statement(code: str) -> str:
    """The theorem statement (up to ':='), for the reader to compare with the question."""
    m = _THEOREM_RE.search(code)
    return re.sub(r"\s+", " ", m.group(0)).strip() if m else ""


Complete = Callable[[str, str], Awaitable[str]]


async def formalise_and_check(question: str, complete: Complete | None, *, mathlib: bool | None = None) -> dict[str, Any]:
    """Formalise, check and repair (see the module docstring). `complete(system, user)` calls the model."""
    if find_lean() is None:
        return {"status": "unavailable", "title": STATUS_TITLES["unavailable"], "attempts": [], "lean_code": "",
                "statement": "", "error": "Lean is not installed (set TRIBOS_LEAN_PATH, or put lean on PATH)."}
    if complete is None:
        return {"status": "failed", "title": STATUS_TITLES["failed"], "attempts": [], "lean_code": "", "statement": "",
                "error": "No model is available to write the formalisation."}
    if mathlib is None:
        from tribos.config.settings import get_str

        mathlib = bool(str(get_str("TRIBOS_LEAN_PROJECT") or "").strip())
    lacking = None if mathlib else needs_library(question)
    if lacking:
        # Audit I33: no substitute proposition over Nat/Int is written to obtain a compile; no model call is spent.
        return {"status": "not_formalizable", "title": STATUS_TITLES["not_formalizable"], "attempts": [],
                "lean_code": "", "statement": "", "repairs": 0, "messages": [],
                "error": f"The statement needs {lacking}, which core Lean 4 cannot express and Mathlib is not "
                         "installed (TRIBOS_LEAN_PROJECT). No formal statement was checked; this says nothing about "
                         "whether the claim is true."}
    env = "Mathlib is available (import Mathlib)." if mathlib else CORE_LEAN_ENV
    max_repairs = int(get_int("TRIBOS_FORMAL_MAX_REPAIRS"))
    attempts: list[dict[str, Any]] = []
    code = lean_code(await complete(FORMALISE_SYSTEM, f"{env}\n\nStatement to prove:\n{question.strip()[:4000]}"))
    result: dict[str, Any] = {}
    issues: list[str] = []
    for attempt in range(max_repairs + 1):
        if not mathlib:
            code = core_notation(code)
        issues = statement_issues(question, lean_statement(code), mathlib=mathlib)
        if issues:
            # The written theorem is not the question's: compiling it would prove something else.
            result = {"status": "mismatch", "error": "The Lean statement does not encode the question: "
                      + "; ".join(issues) + ".", "messages": []}
        else:
            result = await asyncio.to_thread(check_lean, code)  # a subprocess with a timeout: off the event loop
        attempts.append({"attempt": attempt, "status": result["status"], "error": result.get("error"),
                         "code": code})
        if result["status"] in ("verified", "unavailable", "timeout"):
            break
        if attempt == max_repairs:
            break
        errors = str(result.get("error") or "") if issues else (
            "\n".join(f"line {m['line']}: {m['message']}" for m in result.get("messages") or []
                      if m["severity"] == "error") or str(result.get("error") or ""))
        code = lean_code(await complete(REPAIR_SYSTEM, f"{env}\n\nStatement:\n{question.strip()[:2000]}\n\n"
                                                       f"Previous code:\n```lean\n{code}\n```\n\nLean errors:\n{errors[:4000]}"))
    return {
        "status": result.get("status", "failed"),
        "title": STATUS_TITLES.get(result.get("status", "failed"), STATUS_TITLES["failed"]),
        "lean_code": code,
        "statement": lean_statement(code),
        "error": result.get("error"),
        "messages": result.get("messages") or [],
        "output": result.get("output") or "",
        "attempts": attempts,
        "repairs": max(0, len(attempts) - 1),
        "checker": result.get("checker"),
    }


__all__ = ["formal_enabled", "formalise_and_check", "lean_code", "lean_statement", "wants_proof"]
