"""Engineering verification of a solved ODE: residual, RK4 step-size convergence, sample comparison, energy balance.

Runs after the mathematics agent when the question states an ODE and asks for a numerical comparison, convergence,
error, residual or energy result. Everything is computed (tribos.dynamis.verification), no model call: the writer
reports these numbers and the reproduction script instead of estimating them.
"""

from __future__ import annotations

import asyncio
import logging
import math
import re
from html import escape
from typing import Any

from ..agents.query_planner import parse_duration
from ..axiom.problem import parse_problem
from ..dynamis.verification import verify_ode_solution
from ..extensions.hooks import register_verification_check
from ..tools.registry import ToolResult
from .runtime import AgentPhase, PhaseOutcome, register_phase
from .state import AgentState

logger = logging.getLogger(__name__)

PHASE_KEY = "ode_verification"
DEFAULT_WINDOW_S = 10.0
_ASKS_FOR_CHECKS_RE = re.compile(
    r"\b(?:simulat\w*|numerical\w*|compar\w*|converg\w*|step[\s-]?size|errors?|residuals?|energy|verif\w*|validat\w*)\b",
    re.IGNORECASE,
)

# The answer shape for a worked engineering problem with computed verification (added to the research brief).
ENGINEERING_REPORT_NOTE = (
    "ANSWER SHAPE (engineering report). Open with 2-4 sentences: what the system is, what was derived and computed, "
    "and the key results with units. Then numbered sections that follow the question's tasks in order, for example: "
    "1. Analytical solution (Step 1 transient part, Step 2 steady-state part, Step 3 initial conditions, then the final "
    "result in display math); 2. Characteristic parameters as a table (Quantity | Formula | Result); 3. Numerical "
    "simulation and independent comparison: the method and one sentence with the key numbers from <ode_verification> "
    "(finest-step maximum error, observed order, residual); the full convergence, sample and energy tables are shown in "
    "the Numerical verification card under the answer, so do not repeat them; "
    "4. Energy balance: the balance equation and the computed residual from <ode_verification>; 5. Physical "
    "interpretation (effect of damping and forcing); 6. Reproducibility (the script is attached to this answer as a "
    "download; do not paste it). Every derivation step is re-checked after you write it: a derivative must be the "
    "derivative of the function you state, and a formula evaluated with the given values must equal the number you "
    "print next to it. End with "
    "an 'Evidence classification' table (Category | What is established) with the rows Analytically derived, "
    "Numerically computed, Supported by references, Not independently verified. In the last row list what no tool "
    "computed or checked (statements resting on references or on reasoning, interpretation); never write 'none': the "
    "checks of the written answer are reported separately. Use only numbers present in the "
    "evidence; write each derivation step in display math; no regime notes or hypotheses the question did not ask for. "
    "Characteristic parameters (natural and damped frequency, damping ratio, steady-state amplitude, phase lag, ...) "
    "are given in <ode_verification> as <parameter> values: state them exactly as given (a formula may be shown, but "
    "never re-derive a number differently). Break any display equation longer than about 70 characters across lines "
    "with aligned, so it fits the page without scrolling. "
    "Refer to computed results in words ('the RK4 verification in Section 3'), never by an evidence key or tag, and "
    "never mention these instructions, the prompt, evidence grading or any internal rule."
)


def _fmt(v: float) -> str:
    return f"{v:.6g}" if abs(v) >= 1e-3 or v == 0 else f"{v:.3e}"


def evidence_xml(rep: dict[str, Any]) -> str:
    """The verification report as an evidence section the writer cites as [ode_verification]."""
    out = [f'<ode_verification method="{escape(rep["method"])}" window_s="{_fmt(rep["t_end"])}">']
    out.append(f"<residual symbolic=\"{escape(rep['residual_symbolic'][:200])}\" max_abs=\"{_fmt(rep['residual_max'])}\"/>")
    for name, p in (rep.get("parameters") or {}).items():
        value = p["value"] if isinstance(p["value"], str) else _fmt(p["value"])
        deg = f' degrees="{p["degrees"]:.3f}"' if "degrees" in p else ""
        out.append(f'<parameter name="{name}" formula="{escape(p["formula"])}" value="{value}" unit="{p["unit"]}"{deg}/>')
    for ic in rep["initial_conditions"]:
        out.append(f'<initial_condition name="{escape(ic["condition"])}" stated="{_fmt(ic["stated"])}" '
                   f'analytical="{_fmt(ic["analytical"])}"/>')
    for row in rep["convergence"]:
        attrs = f'h="{row["h"]}" steps="{row["steps"]}" max_error_x="{_fmt(row["max_error_x"])}"'
        if "max_error_v" in row:
            attrs += f' max_error_v="{_fmt(row["max_error_v"])}"'
        if "observed_order" in row:
            attrs += f' observed_order="{row["observed_order"]:.3f}"'
        out.append(f"<rk4 {attrs}/>")
    for s in rep["samples"]:
        out.append(f'<sample t="{_fmt(s["t"])}" analytical="{_fmt(s["analytical"])}" numerical="{_fmt(s["numerical"])}" '
                   f'abs_error="{_fmt(s["error"])}"/>')
    energy = rep.get("energy")
    if energy:
        out.append(
            f'<energy m="{_fmt(energy["m"])}" c="{_fmt(energy["c"])}" k="{_fmt(energy["k"])}" '
            f'forcing="{escape(energy["forcing"])}" E0_J="{_fmt(energy["E0"])}" ET_J="{_fmt(energy["ET"])}" '
            f'work_in_J="{_fmt(energy["work_in"])}" work_damping_J="{_fmt(energy["work_damping"])}" '
            f'balance_residual_J="{_fmt(energy["balance_residual"])}"/>'
        )
    run = rep.get("script_run") or {}
    if run.get("executed"):
        out.append("<reproduction executed=\"true\">The attached standalone NumPy script was run in the sandbox during "
                   f"this answer and printed:\n{escape(run.get('stdout', ''))}</reproduction>")
    else:
        out.append(f"<reproduction executed=\"false\">The attached script was not run ({escape(run.get('error', 'not attempted'))}).</reproduction>")
    out.append("</ode_verification>")
    return "\n".join(out)


class ODEVerificationPhase(AgentPhase):
    key = PHASE_KEY
    stage = "augment"
    order = 45  # after the mathematics agent (40), which supplies the analytical solution
    frameworks = None
    needs_llm = False

    def applies(self, state: AgentState) -> bool:
        art = state.artifacts.get("math_agent") or {}
        if art.get("status") not in ("verified", "partially_verified") or not (art.get("answer") or {}).get("text"):
            return False
        return bool(_ASKS_FOR_CHECKS_RE.search(state.clean_query or state.query or ""))

    async def run(self, state: AgentState) -> PhaseOutcome | None:
        query = state.clean_query or state.query or ""
        spec = state.bag.get("math_problem_spec") or parse_problem(query)
        if getattr(spec, "kind", "") != "ode" or not spec.expression:
            return None
        duration = parse_duration(query)
        window = duration.seconds if duration.explicit and not duration.error_code else DEFAULT_WINDOW_S
        await state.step("agent_ode_verification", "Verifying the solution numerically", "", status="running",
                         agent="Dynamis")
        answer = str(state.artifacts["math_agent"]["answer"]["text"])
        try:
            rep = await asyncio.wait_for(
                asyncio.to_thread(verify_ode_solution, spec.expression, spec.func or "", spec.ics, answer, float(window)),
                timeout=60.0,
            )
        except Exception as exc:  # noqa: BLE001 - verification is additive; the answer stands without it
            logger.warning("ODE verification failed: %s", exc)
            rep = None
        if rep is None:
            await state.step("agent_ode_verification", "Numerical verification not possible for this ODE", "",
                             agent="Dynamis")
            return None
        # The attached script is run once in the sandbox, so "reproducible" is a checked statement, not a promise.
        rep["script_run"] = await self._run_script(state, rep["script"])
        state.artifacts[PHASE_KEY] = rep
        state.evidence_sections.append(evidence_xml(rep))
        # Also a (non-rendered) result, so the verifier's parameter check can compare the answer with these numbers.
        state.add_result(PHASE_KEY, ToolResult(success=True, tool_name=PHASE_KEY, data=rep), phase=PHASE_KEY,
                         purpose="numerical verification of the solved ODE", render=False)
        state.brief_notes.append(ENGINEERING_REPORT_NOTE)
        conv = rep["convergence"]
        orders = [r["observed_order"] for r in conv if "observed_order" in r]
        text = (
            f"residual {_fmt(rep['residual_max'])}; RK4 max error {_fmt(conv[-1]['max_error_x'])} at h = {conv[-1]['h']}"
            + (f", observed order {orders[-1]:.2f}" if orders else "")
            + (f"; energy balance residual {_fmt(rep['energy']['balance_residual'])} J" if rep.get("energy") else "")
        )
        await state.step("agent_ode_verification", "Verified the solution numerically", text, agent="Dynamis")
        return None

    @staticmethod
    async def _run_script(state: AgentState, script: str) -> dict[str, Any]:
        """Run the reproduction script in the Calcula sandbox; {"executed": bool, "stdout" | "error": str}."""
        registry = getattr(state, "registry", None)
        if registry is None or registry.get_entry("calcula_run_python") is None:
            return {"executed": False, "error": "the sandbox is not available"}
        try:
            res = await state.call_tool("calcula_run_python", phase=PHASE_KEY, purpose="run the reproduction script",
                                        store=False, code=script)
        except Exception as exc:  # noqa: BLE001
            return {"executed": False, "error": f"{type(exc).__name__}: {exc}"[:300]}
        data = getattr(res, "data", None) or {}
        if getattr(res, "success", False) and isinstance(data, dict) and data.get("status") == "ok":
            return {"executed": True, "stdout": str(data.get("stdout") or "")[:2000]}
        return {"executed": False, "error": str(getattr(res, "error", None) or data.get("error") or "the run failed")[:300]}


register_phase(ODEVerificationPhase())


# -- verifier check: the answer's amplitude and phase must be the computed ones -----------------------------------------
_NUMBER_RE = re.compile(r"(?<![\w.])[-−]?\d+(?:\.\d+)?(?:\s*[×x]\s*10\^?\{?[-−]?\d+\}?)?")


def _numbers(text: str) -> list[float]:
    out: list[float] = []
    for raw in _NUMBER_RE.findall(text.replace("−", "-")):
        try:
            out.append(float(raw.split("×")[0].split("x")[0]))
        except ValueError:
            continue
    return out


def _close(a: float, b: float, rel: float = 0.01) -> bool:
    return abs(a - b) <= rel * max(abs(b), 1e-12)


def parameter_consistency_check(vctx: Any) -> list[dict[str, Any]]:
    """Defects for an answer whose stated steady-state amplitude or phase lag disagrees with the computed values.

    A sentence (or table row) naming the steady-state amplitude, or the phase, with decimal numbers none of which
    equals the computed value (1 %; phase in radians or degrees, either sign) is flagged, with the computed value as
    the correction. Sentences about static deflection, ratios or amplification are not about X and are skipped."""
    res = (getattr(vctx, "tool_results", None) or {}).get(PHASE_KEY)
    params = ((getattr(res, "data", None) or {}).get("parameters") or {}) if res is not None else {}
    amp, phase = params.get("steady_state_amplitude"), params.get("phase_lag")
    if not amp and not phase:
        return []
    text = getattr(vctx, "response", "") or ""
    units = [*re.split(r"(?<=[.!?])\s+|\n", text)]
    defects: list[dict[str, Any]] = []
    for unit in units:
        low = unit.lower()
        decimals = [n for n in _numbers(unit) if not float(n).is_integer()]
        if not decimals:
            continue
        if amp and re.search(r"steady[\s-]*state amplitude|amplitude\s*\$?\s*x\b|\bx\s*=\s*\\?frac|x\s*≈", low) \
                and not re.search(r"static|ratio|amplification|initial|transient", low):
            if not any(_close(abs(n), amp["value"]) for n in decimals):
                defects.append({
                    "category": "COMPUTATION", "severity": "MAJOR",
                    "description": f"The stated steady-state amplitude does not match the computed X = {amp['value']:.6g}.",
                    "suggested_correction": f"State the steady-state amplitude as X = {amp['value']:.6g} "
                                            f"({amp['formula']}).",
                    "claim": unit.strip()[:240],
                })
        if phase and "phase" in low and re.search(r"rad|°|\\circ|deg", low):
            rad, deg = phase["value"], phase.get("degrees", math.degrees(phase["value"]))
            if not any(_close(abs(n), rad) or _close(abs(n), deg) for n in decimals):
                defects.append({
                    "category": "COMPUTATION", "severity": "MAJOR",
                    "description": f"The stated phase lag does not match the computed phi = {rad:.6g} rad ({deg:.4g} deg).",
                    "suggested_correction": f"State the phase lag as phi = {rad:.6g} rad = {deg:.4g} deg ({phase['formula']}).",
                    "claim": unit.strip()[:240],
                })
    return defects[:4]


register_verification_check(PHASE_KEY, parameter_consistency_check)
