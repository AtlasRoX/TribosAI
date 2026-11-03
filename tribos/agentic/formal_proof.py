"""
Agent phase: formal proof checking with Lean 4 for "prove ..." questions (optional).

Runs in the augment stage, after the verified mathematics agent. When Lean is installed the planning model
formalises the statement and its proof, Lean checks it, and compiler errors go back to the model for repair (up to
TRIBOS_FORMAL_MAX_REPAIRS). The synthesis may say "formally verified (Lean)" only after a clean compile, and must show
the Lean statement so the reader can judge whether it is faithful to the question. Without Lean the phase records
"formal checker unavailable" and changes nothing else. It never overrides the SymPy checks of the mathematics agent.
"""

from __future__ import annotations

import asyncio
import logging
import re
from html import escape
from typing import Any

from ..verify.formal import find_lean, formal_enabled, formalise_and_check, wants_proof
from .runtime import AgentPhase, PhaseOutcome, register_phase
from .state import AgentState

logger = logging.getLogger(__name__)

PHASE_KEY = "formal_proof"
# Famous problems that are open (no accepted proof or disproof): a formal proof attempt cannot succeed. Solved ones
# (Poincaré, Fermat's Last Theorem) and disputed ones (abc) are deliberately absent.
FAMOUS_OPEN_PROBLEM_RE = re.compile(
    r"(?i)\b(?:collatz|goldbach|twin[- ]prime\s+conjecture|riemann\s+hypothesis|p\s*(?:vs\.?|versus|=|!=|≠)\s*np\b|"
    r"navier[- ]stokes\s+(?:existence|smoothness|regularity)|hodge\s+conjecture|birch\s+and\s+swinnerton|"
    r"swinnerton[- ]dyer|yang[- ]mills\s+(?:existence|mass\s+gap)|odd\s+perfect\s+numbers?|legendre'?s\s+conjecture)"
)
RESULT_KEY = "agent.formal_proof.result"
AGENT_NAME = "Axiom"


def _lemma_summary(lemmas: list[dict[str, Any]]) -> str:
    return ", ".join(f"{b.get('name')}: {'proved' if b.get('proved') else 'not proved'}" for b in lemmas)


def evidence_xml(art: dict[str, Any]) -> str:
    def esc(value: Any, limit: int = 4000) -> str:
        text = str(value if value is not None else "")
        return escape(text[:limit], quote=False)

    return "\n".join([
        f'<formal_proof status="{escape(str(art.get("status")), quote=True)}" '
        f'title="{escape(str(art.get("title")), quote=True)}" repairs="{art.get("repairs", 0)}" '
        'note="checked by the Lean 4 compiler; say formally verified only when status is verified, and show the Lean '
        'statement so the reader can judge its faithfulness; this never replaces the SymPy checks">',
        f"<lean_statement>{esc(art.get('statement'), 1500)}</lean_statement>",
        f"<lean_code>{esc(art.get('lean_code'))}</lean_code>",
        f"<lean_error>{esc(art.get('error'), 1500)}</lean_error>" if art.get("error") else "",
        f"<blueprint_lemmas>{esc(_lemma_summary(art['blueprint']), 800)}</blueprint_lemmas>" if art.get("blueprint") else "",
        "</formal_proof>",
    ])


_FIND_RE = re.compile(r"\b(?:find|determine|compute|what is|how many|which)\b", re.I)


def _answer_hint(state: AgentState) -> str:
    """For a "find / determine" question: the values code already computed, to be stated and proved in Lean."""
    question = state.clean_query or state.query or ""
    if not _FIND_RE.search(question):
        return ""
    res = (getattr(state, "tool_results", None) or {}).get("computed_results")
    data = getattr(res, "data", None) if res is not None and getattr(res, "success", False) else None
    if not isinstance(data, dict):
        return ""
    params = [f"{p.get('name')} = {p.get('value')}" for p in data.get("parameters") or [] if isinstance(p, dict)]
    return "; ".join(params)[:800]



# "a formal proof", "machine-checked", "in Lean", "formally verify", "verified proof": asks for Lean, not a written proof.
FORMAL_REQUEST_RE = re.compile(
    r"\b(?:formal(?:ly)?\s+(?:proof|prove|proved|verif\w*|check\w*)|formalis\w*|formaliz\w*|machine[- ]checked|"
    r"lean\s*4?\b|in\s+lean|mathlib|proof\s+assistant|verified\s+proof|kernel[- ]checked)", re.I)


_NUMBERED_PART_RE = re.compile(r"(?m)^\s*\d{1,2}[.)]\s+(\S.+)$")


def formal_part(question: str) -> str:
    """The part of a numbered question that asks for the formal proof (the one naming Lean or a formal proof), with
    the question's opening context; the whole question when there is no such single part."""
    parts = _NUMBERED_PART_RE.findall(question or "")
    formal = [p for p in parts if FORMAL_REQUEST_RE.search(p)]
    if len(parts) < 2 or len(formal) != 1:
        return question
    first = _NUMBERED_PART_RE.search(question)
    preamble = question[: first.start()].strip() if first else ""
    # The opening context matters only when the part refers to it ("prove that f ..."); a self-contained part does not.
    return f"{preamble}\n\n{formal[0]}".strip() if preamble and re.search(r"\b(?:f|g|it|this|the\s+function)\b", formal[0]) \
        else formal[0].strip()


def formal_mode() -> str:
    """TRIBOS_FORMAL_MODE: explicit (default; Lean only when a formal proof is asked for) or auto (every proof)."""
    import os

    value = (os.getenv("TRIBOS_FORMAL_MODE") or "explicit").strip().lower()
    return value if value in ("explicit", "auto") else "explicit"

class FormalProofPhase(AgentPhase):
    key = PHASE_KEY
    stage = "augment"
    order = 45  # after the mathematics agent (40)
    frameworks = None
    needs_llm = False  # without a model (or without Lean) the phase still records why nothing was checked

    def applies(self, state: AgentState) -> bool:
        question = state.clean_query or state.query
        if FAMOUS_OPEN_PROBLEM_RE.search(question or ""):
            # A proof of a famous open problem cannot be formalised here; attempting one only costs time (about a
            # minute of prover calls). The answer states the problem's status instead.
            state.bag["formal_skipped"] = "the question names a famous open problem"
            return False
        if not formal_enabled():
            return False
        if FORMAL_REQUEST_RE.search(question or ""):
            return True  # "a formal proof in Lean", "formally verify": asked for, whatever the wording of the claim
        if not wants_proof(question):
            return False
        if formal_mode() == "explicit":
            # Not every proof question needs a machine-checked proof: a written proof answers "prove that ...".
            # Lean runs when it is asked for (TRIBOS_FORMAL_MODE=auto runs it for every proof question).
            state.bag["formal_skipped"] = "a formal (machine-checked) proof was not asked for"
            return False
        return True

    async def run(self, state: AgentState) -> PhaseOutcome | None:
        question = state.clean_query or state.query
        from ..tools.policy import active_tool_policy

        policy = (
            getattr(state, "tool_policy", None)
            or getattr(getattr(state, "ctx", None), "tool_policy", None)
            or active_tool_policy()
        )
        if policy is not None and policy.prohibit_formal:
            art = {
                "status": "disabled",
                "title": "formal prover disabled by user",
                "question": question[:2000],
                "statement": "",
                "lean_code": "",
                "attempts": [],
                "error": policy.formal_reason or "Formal prover disabled by user request.",
            }
            state.artifacts["formal_proof"] = art
            state.mark_phase(PHASE_KEY, "skipped", "formal prover disabled by user")
            if hasattr(state, "step"):
                res_step = state.step("agent_formal", "Lean: formal prover disabled by user",
                                      "Skipped: prohibited by user request", status="done", agent=AGENT_NAME)
                if hasattr(res_step, "__await__"):
                    await res_step
            return PhaseOutcome(artifacts={"formal_proof": art})

        if find_lean() is None:
            # Lean is optional: record that the formal check could not run, and leave the run otherwise unchanged.
            art = {"status": "unavailable", "title": "formal checker unavailable", "question": question[:2000],
                   "statement": "", "lean_code": "", "attempts": [],
                   "error": "Lean is not installed (set TRIBOS_LEAN_PATH, or put lean on PATH)."}
            state.artifacts["formal_proof"] = art
            state.mark_phase(PHASE_KEY, "skipped", "Lean is not installed")
            return PhaseOutcome(artifacts={"formal_proof": art})

        await state.step("agent_formal", "Formalising the proof in Lean 4", status="running", agent=AGENT_NAME)

        llm = state.llm
        from ..config.settings import get_str

        prover_model = str(get_str("TRIBOS_LEAN_PROVER_MODEL") or "").strip()
        if prover_model and getattr(llm, "_factory", None) is not None:
            # A specialised prover (e.g. a served Goedel-Prover) writes the Lean; it shares the run budget.
            from .llm import AgentLLM

            llm = AgentLLM(llm._factory, prover_model, llm._api_key, llm.budget, llm.timeout_seconds)

        async def complete(system: str, user: str) -> str:
            return await llm.complete(system, user, phase=PHASE_KEY)

        async def on_step(text: str) -> None:
            await state.step("agent_formal", f"Lean: {text}", status="running", agent=AGENT_NAME)

        async def work() -> dict[str, Any]:
            from ..config.settings import get_float

            budget_s = float(get_float("TRIBOS_FORMAL_BUDGET_S"))
            progress: list[dict[str, Any]] = []
            part = formal_part(question)
            try:
                # Only the part of the question that asks for the formal proof ("5. Prove in Lean that ..."), and a time
                # budget for the whole stage: each Lean check loads Mathlib (tens of seconds), and the repair and lemma
                # rounds held a five-part question for six minutes.
                art = await asyncio.wait_for(
                    formalise_and_check(part, complete if llm.available else None,
                                        # Values computed for the other parts (a heat-equation error, an order of
                                        # convergence) are no hint for this one: they were padded into the theorem.
                                        answer_hint=_answer_hint(state) if part == question else "",
                                        on_step=on_step, progress=progress),
                    timeout=budget_s,
                )
            except TimeoutError:
                art = {"status": "timeout", "title": f"Lean proof not finished within {budget_s:.0f} s", "statement": "",
                       "lean_code": (progress[-1].get("code") or "") if progress else "", "attempts": progress,
                       "messages": [], "output": "",
                       "error": f"the formal proof was not completed within the {budget_s:.0f} s budget "
                                "(TRIBOS_FORMAL_BUDGET_S); nothing about the claim follows from that"}
            art["question"] = question[:2000]
            state.artifacts["formal_proof"] = art

            from ..tools.registry import ErrorType, ToolResult

            verified = art["status"] == "verified"
            state.add_result(
                RESULT_KEY,
                ToolResult(success=True, tool_name="axiom_formal_check", data=art, metadata={"formal_status": art["status"]},
                           error_type=None if verified else ErrorType.VALIDATION_ERROR),
                phase=PHASE_KEY, purpose="Lean 4 formal proof check", render=False,
            )
            state.evidence_sections.append(evidence_xml(art))
            if verified:
                state.brief_notes.append(
                    "The proof was formally verified by Lean 4 (see <formal_proof>). Say so in the Verification section, "
                    "quote the Lean statement so the reader can check it says what the question asks, and keep the SymPy "
                    "checks as they are."
                )
            elif art.get("status") == "disabled":
                pass
            elif art["status"] == "not_formalizable":
                state.scope_notes.append(
                    f"No formal check was possible ({str(art.get('error') or '')[:240]}). Say that no formal check was run; "
                    "never present a Lean theorem for this question, and draw no conclusion about the claim from this."
                )
            else:
                state.scope_notes.append(
                    f"The Lean formalisation failed ({str(art.get('error') or 'no clean compile')[:200]}); do not claim the "
                    "proof is formally verified, and a failed formalisation establishes nothing about the claim."
                )
            state.mark_phase(PHASE_KEY, "ok" if verified else "fallback", "" if verified else str(art.get("title") or "formalisation failed"))
            await state.step("agent_formal", f"Lean: {art['title']}",
                             f"{len(art.get('attempts') or [])} attempt(s)", status="done" if verified else "error",
                             agent=AGENT_NAME)
            return art

        from ..config.settings import get_bool

        if state.bag is not None and get_bool("TRIBOS_FORMAL_BACKGROUND"):
            # Lean needs only the question: it runs beside the rest of the run (critical points, plots, Python), and
            # the answer waits for it only when it is about to be written (await_formal_proof). Run first and alone,
            # it held every later step for minutes.
            state.bag["formal_task"] = asyncio.ensure_future(work())
            return PhaseOutcome()
        art = await work()
        return PhaseOutcome(artifacts={"formal_proof": art})


register_phase(FormalProofPhase())


async def await_formal_proof(run: Any) -> dict[str, Any] | None:
    """Wait for a formal proof started in the background (its own budget bounds the wait) and add its artifact to the
    run, just before the answer is written. None when no formal proof was started."""
    state = getattr(run, "agent_state", None)
    task = (state.bag.pop("formal_task", None) if state is not None and state.bag is not None else None)
    if task is None:
        return None
    try:
        art = await task
    except Exception as exc:  # noqa: BLE001 - a failed formal check never costs the answer
        logger.warning("Formal proof task failed: %s", exc)
        return None
    run.execution_artifacts["formal_proof"] = art
    return art

