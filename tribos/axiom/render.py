"""
The answer rendered straight from a verified computation, when that computation already is the whole requested answer
in the requested form (audit I27).

"Evaluate h(0), h(1), h(6). Return exactly three lines, one result per input" and "Give the complete solution set on
one line in set notation" are answered completely by the checked tool result. Rendering it deterministically gives the
same contract-compliant payload whether or not a writer model is healthy, and spends no model call on copying values.
Anything that asks for prose (explain, prove, derive, show, why, ...) or does not match the contract exactly is left to
the writer.
"""

from __future__ import annotations

import re
from typing import Any

from ..utils.output_contract import Contract, mask_instructions, validate

# Requests that need a written argument or explanation, not just the computed values.
_PROSE_RE = re.compile(
    r"\b(?:explain|explanation|why|prove|proof|justify|justification|derive|derivation|show\s+(?:that|how|why|your)|"
    r"describe|discuss|compare|interpret|reason(?:ing)?|steps?|working|analy[sz]e|comment)\b", re.I)
_SET_REQUEST_RE = re.compile(r"\bset[\s-]+notation\b|\bsolution\s+set\b|\bas\s+a\s+set\b", re.I)


def render_verified_answer(question: str, math_artifact: dict[str, Any] | None, contract: Contract | None) -> str | None:
    """The requested answer as text, or None when the verified result is not by itself the full answer."""
    if not math_artifact or math_artifact.get("status") != "verified" or math_artifact.get("invalidated") or contract is None or not contract.strict_form:
        return None
    if contract.literal is not None or contract.json_only:
        return None
    asked = mask_instructions(question or "")
    if _PROSE_RE.search(asked):
        return None
    answer = math_artifact.get("answer") or {}
    results = answer.get("results")
    if results:
        if any(r.get("op") in ("claim", "reaches", "orbit") for r in results) or any(not r.get("text") for r in results):
            return None
        lines = [str(r["text"]).strip() for r in results]
    elif answer.get("set_text") and _SET_REQUEST_RE.search(question or ""):
        lines = [str(answer["set_text"])]
    elif answer.get("factored"):
        lines = [str(answer["factored"]).strip()]
    elif answer.get("text") and not _SET_REQUEST_RE.search(question or ""):
        lines = [str(answer["text"]).strip()]
    else:
        return None
    # The requested line count must be exactly the results' ("on one line" is exact_lines=1 in the contract).
    if contract.exact_lines is not None:
        if contract.exact_lines != len(lines):
            return None
    elif not (contract.no_extra and len(lines) == 1):
        return None
    text = "\n".join(lines)
    return None if validate(text, contract) else text


__all__ = ["render_verified_answer"]
