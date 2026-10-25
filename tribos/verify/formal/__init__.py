"""Optional formal proof checking with Lean 4 (runner) and the model-driven formalisation loop (prove)."""

from __future__ import annotations

from .prove import formal_enabled, formalise_and_check, lean_code, lean_statement, wants_proof
from .runner import STATUS_TITLES, check_lean, clear_cache, find_lean, parse_messages, uses_unproved

__all__ = [
    "STATUS_TITLES",
    "check_lean",
    "clear_cache",
    "find_lean",
    "formal_enabled",
    "formalise_and_check",
    "lean_code",
    "lean_statement",
    "parse_messages",
    "uses_unproved",
    "wants_proof",
]
