"""
Agent phase: formal proof checking with Lean 4 for "prove ..." questions (optional).

Runs in the augment stage, after the verified mathematics agent. When Lean is installed the planning model
formalises the statement and its proof, Lean checks it, and compiler errors go back to the model for repair (up to
TRIBOS_FORMAL_MAX_REPAIRS). The synthesis may say "formally verified (Lean)" only after a clean compile, and must show
the Lean statement so the reader can judge whether it is faithful to the question. Without Lean the phase records
"formal checker unavailable" and changes nothing else. It never overrides the SymPy checks of the mathematics agent.
"""

from __future__ import annotations

from html import escape
from typing import Any

from ..verify.formal import find_lean, formal_enabled, formalise_and_check, wants_proof
from .runtime import AgentPhase, PhaseOutcome, register_phase
from .state import AgentState

PHASE_KEY = "formal_proof"
RESULT_KEY = "agent.formal_proof.result"
AGENT_NAME = "Axiom"


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
        "</formal_proof>",
    ])


class FormalProofPhase(AgentPhase):
    key = PHASE_KEY
    stage = "augment"
    order = 45  # after the mathematics agent (40)
    frameworks = None
    needs_llm = False  # without a model (or without Lean) the phase still records why nothing was checked

    def applies(self, state: AgentState) -> bool:
        return formal_enabled() and wants_proof(state.clean_query or state.query)

    async def run(self, state: AgentState) -> PhaseOutcome | None:
        question = state.clean_query or state.query
        if find_lean() is None:
            # Lean is optional: record that the formal check could not run, and leave the run otherwise unchanged.
            art = {"status": "unavailable", "title": "formal checker unavailable", "question": question[:2000],
                   "statement": "", "lean_code": "", "attempts": [],
                   "error": "Lean is not installed (set TRIBOS_LEAN_PATH, or put lean on PATH)."}
            state.artifacts["formal_proof"] = art
            state.mark_phase(PHASE_KEY, "skipped", "Lean is not installed")
            return PhaseOutcome(artifacts={"formal_proof": art})

        await state.step("agent_formal", "Formalising the proof in Lean 4", status="running", agent=AGENT_NAME)

        async def complete(system: str, user: str) -> str:
            return await state.llm.complete(system, user, phase=PHASE_KEY)

        art = await formalise_and_check(question, complete if state.llm.available else None)
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
        else:
            state.scope_notes.append(
                f"The Lean formalisation failed ({str(art.get('error') or 'no clean compile')[:200]}); do not claim the "
                "proof is formally verified."
            )
        state.mark_phase(PHASE_KEY, "ok" if verified else "fallback", "" if verified else "formalisation failed")
        await state.step("agent_formal", f"Lean: {art['title']}",
                         f"{len(art.get('attempts') or [])} attempt(s)", status="done" if verified else "error",
                         agent=AGENT_NAME)
        return PhaseOutcome(artifacts={"formal_proof": art})


register_phase(FormalProofPhase())
