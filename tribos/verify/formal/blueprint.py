"""
Blueprint proving (docs/plans/tribos-harness-landscape.md item 3; Goedel-Architect).

When a direct Lean proof fails, the model writes a blueprint instead: lemma statements with `sorry` bodies and the main
theorem proved from them. The skeleton must compile (only `sorry` warnings). Each lemma is then proved on its own,
with the usual repair loop, at most LEMMA_CONCURRENCY at a time; the proved lemmas replace their `sorry` bodies and the
assembled file is checked as a whole. The result is "verified" only when that final file compiles with no `sorry`,
`admit` or new axiom: a lemma that cannot be proved leaves the theorem unproved.
"""

from __future__ import annotations

import asyncio
import re
from collections.abc import Awaitable, Callable
from typing import Any

from .runner import check_lean

Complete = Callable[[str, str], Awaitable[str]]
MAX_LEMMAS = 6
LEMMA_CONCURRENCY = 2
_DECL_RE = re.compile(r"^(?:@\[[^\]]*\]\s*)?(?:private\s+)?(?:theorem|lemma)\s+([^\s:({\[]+)", re.M)
_SORRY_RE = re.compile(r"\bsorry\b")

BLUEPRINT_SYSTEM = (
    "You plan Lean 4 proofs as blueprints. Reply with exactly one ```lean block: the imports, then several lemmas whose "
    "proofs are `sorry`, then the main theorem, with its statement exactly as given, proved from the lemmas with no "
    "sorry. Every lemma must be true and much easier than the theorem (one idea each). Use Mathlib names that exist."
)
LEMMA_SYSTEM = (
    "You prove one Lean 4 lemma. Reply with exactly one ```lean block containing only that lemma, its statement "
    "unchanged and a complete proof. Never use sorry, admit or axiom. Earlier lemmas of the file may be used by name."
)


def split_decls(code: str) -> tuple[str, list[tuple[str, str]]]:
    """(header, [(name, block)]) of a Lean file: the text before the first theorem/lemma, then each declaration."""
    starts = [(m.start(), m.group(1)) for m in _DECL_RE.finditer(code)]
    if not starts:
        return code, []
    header = code[: starts[0][0]]
    blocks = []
    for i, (pos, name) in enumerate(starts):
        end = starts[i + 1][0] if i + 1 < len(starts) else len(code)
        blocks.append((name, code[pos:end].rstrip() + "\n"))
    return header, blocks


_IMPORT_LINE_RE = re.compile(r"^\s*import\s+\S.*$", re.M)


def _merge(before: str, code: str) -> str:
    """The file so far plus one more declaration. A model's reply usually repeats the file's imports; Lean accepts
    imports only at the top, so pasted below the earlier lemmas they made every lemma check fail. Imports the file
    lacks move to the top; repeated ones are dropped."""
    own = [line.strip() for line in _IMPORT_LINE_RE.findall(code)]
    body = _IMPORT_LINE_RE.sub("", code).strip("\n")
    have = {line.strip() for line in _IMPORT_LINE_RE.findall(before)}
    new = [line for line in dict.fromkeys(own) if line not in have]
    head = ("\n".join(new) + "\n") if new else ""
    return f"{head}{before.rstrip()}\n\n{body}\n"


def _errors(result: dict[str, Any]) -> str:
    return "\n".join(f"line {m['line']}: {m['message']}" for m in result.get("messages") or [] if m["severity"] == "error") \
        or ("" if result.get("status") == "verified" else str(result.get("error") or ""))


def _compiles_with_sorry(result: dict[str, Any]) -> bool:
    if result.get("status") in ("unavailable", "timeout"):
        return False
    return not any(m["severity"] == "error" for m in result.get("messages") or [])


async def prove_by_blueprint(statement: str, question: str, complete: Complete, env: str, *, max_repairs: int = 2,
                             code_of: Callable[[str], str], hints: Callable[[str], str] = lambda e: "",
                             on_step: Callable[[str], Awaitable[None]] | None = None) -> dict[str, Any]:
    """Blueprint, prove each lemma, assemble, check. `code_of(reply)` extracts the Lean block from a reply."""
    async def note(text: str) -> None:
        if on_step is not None:
            await on_step(text)

    skeleton = code_of(await complete(BLUEPRINT_SYSTEM, f"{env}\n\nQuestion:\n{question[:3000]}\n\nMain theorem "
                                                        f"(keep this statement exactly):\n{statement}"))
    result = await asyncio.to_thread(check_lean, skeleton)
    if not _compiles_with_sorry(result):
        errors = _errors(result)
        skeleton = code_of(await complete(BLUEPRINT_SYSTEM, f"{env}\n\nThe blueprint below does not compile. Fix it "
                                                            f"(lemma bodies stay sorry).\n```lean\n{skeleton}\n```\n\n"
                                                            f"Lean errors:\n{errors[:3000]}\n{hints(errors)}"))
        result = await asyncio.to_thread(check_lean, skeleton)
        if not _compiles_with_sorry(result):
            return {"status": "failed", "error": "the blueprint did not compile: " + _errors(result)[:500],
                    "lean_code": skeleton, "lemmas": []}
    header, decls = split_decls(skeleton)
    lemmas = [(n, b) for n, b in decls if _SORRY_RE.search(b)][:MAX_LEMMAS]
    if not lemmas:
        return {"status": "failed", "error": "the blueprint has no lemma to prove", "lean_code": skeleton, "lemmas": []}
    await note(f"blueprint compiled with {len(lemmas)} lemma(s)")
    gate = asyncio.Semaphore(LEMMA_CONCURRENCY)

    async def prove(name: str, block: str) -> tuple[str, str | None, int]:
        before = skeleton[: skeleton.index(block)]
        attempt_code, tries = block, 0
        async with gate:
            reply = await complete(LEMMA_SYSTEM, f"{env}\n\nThe file so far:\n```lean\n{before}\n```\n\nProve:\n"
                                                 f"```lean\n{block}\n```")
            attempt_code = code_of(reply)
            for tries in range(max_repairs + 1):
                if _SORRY_RE.search(attempt_code):
                    errors = "the proof still contains sorry"
                else:
                    r = await asyncio.to_thread(check_lean, _merge(before, attempt_code))
                    errors = _errors(r)
                    if not errors:
                        return name, attempt_code, tries
                if tries == max_repairs:
                    break
                attempt_code = code_of(await complete(LEMMA_SYSTEM, f"{env}\n\nThe file so far:\n```lean\n{before}\n"
                                                                    f"```\n\nYour proof:\n```lean\n{attempt_code}\n```"
                                                                    f"\n\nLean errors:\n{errors[:3000]}\n{hints(errors)}"))
        return name, None, tries

    proved = await asyncio.gather(*(prove(n, b) for n, b in lemmas))
    lemma_report = [{"name": n, "proved": code is not None, "repairs": t} for n, code, t in proved]
    await note(f"{sum(1 for r in lemma_report if r['proved'])} of {len(lemmas)} lemma(s) proved")
    assembled = skeleton
    for (_name, block), (_, code, _t) in zip(lemmas, proved, strict=True):
        if code is not None:
            assembled = assembled.replace(block, code.rstrip() + "\n\n", 1)
    if any(code is None for _, code, _t in proved):
        missing = ", ".join(n for n, code, _t in proved if code is None)
        return {"status": "failed", "error": f"lemma(s) not proved: {missing}", "lean_code": assembled,
                "lemmas": lemma_report}
    # Proved lemmas were spliced in with the imports their replies repeated: all imports go back to the top.
    imports = list(dict.fromkeys(line.strip() for line in _IMPORT_LINE_RE.findall(assembled)))
    assembled = "\n".join(imports) + "\n\n" + _IMPORT_LINE_RE.sub("", assembled).strip("\n") + "\n"
    final = await asyncio.to_thread(check_lean, assembled)
    return {"status": final.get("status", "failed"), "error": final.get("error"), "lean_code": assembled,
            "messages": final.get("messages") or [], "lemmas": lemma_report, "checker": final.get("checker")}


__all__ = ["prove_by_blueprint", "split_decls"]
