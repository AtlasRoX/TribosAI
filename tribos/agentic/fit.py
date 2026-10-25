"""Parameter fitting and model calibration phase for Tribos STEM and dynamical models.

Supports:
1. Dynamic model calibration on uploaded time-course datasets using COPASI / Basico (vivarix_calibrate_parameters).
2. Nonlinear parameter fitting on uploaded tabular datasets using Dynamis / SciPy (dynamis_fit_parameters).

Provides both `FitPhase` and its backward-compatible alias `CalibratePhase`.
Writes the artifact "model_calibration" and a <model_calibration> evidence section.
"""

from __future__ import annotations

import logging
import math
import re
from dataclasses import dataclass, field
from html import escape
from typing import Any

from .budget import BudgetExhausted
from .guardrails import SPOTLIGHT_RULE, neutralise
from .hypothesis import _mentions, simulation_block_reason
from .llm import AgentLLMUnavailable
from .runtime import AgentPhase, register_phase
from .state import AgentState

logger = logging.getLogger(__name__)

PHASE = "calibrate"
TOOL = "vivarix_calibrate_parameters"
LIST_TOOL = "vivarix_list_parameters"
DYNAMIS_FIT_TOOL = "dynamis_fit_parameters"
MAX_PICK = 3
FALLBACK_K = 2
_MIN_SECONDS_LEFT = 30.0

CALIBRATION_INTENT_RE = re.compile(
    r"\bcalibrat(?:e|es|ed|ing|ion)\s+(?:the\s+|my\s+|this\s+|a\s+|its\s+|our\s+)?(?:[\w-]+\s+)?"
    r"(?:model|parameters?|ode|kinetics?|rate\s+constants?|sbml|biomd\w*)\b"
    r"|\b(?:model|parameter|kinetic|ode)\s+calibration\b"
    r"|\bcalibrat\w*\b(?=.{0,60}\b(?:against|to)\s+(?:my|the|this|our)\s+(?:\w+\s+)?(?:data|time[- ]course|measurements))"
    r"|\bfit (?:the |my |this )?(?:model|parameters?)|parameter estimation|estimate (?:the |its |model )?parameters?",
    re.I,
)
FIT_INTENT_RE = CALIBRATION_INTENT_RE


# -----------------------------------------------------------------------------
# Kinetic (SBML) models for vivarix_calibrate_parameters
# -----------------------------------------------------------------------------

@dataclass
class ModelRef:
    biomodel_id: str
    label: str
    sim_kwargs: dict[str, Any] = field(default_factory=dict)  # sbml_path, model_label, model_provenance


@dataclass
class ModelInfo:
    species: dict[str, float | None] = field(default_factory=dict)  # name -> initial concentration
    parameters: dict[str, dict[str, Any]] = field(default_factory=dict)  # name -> {value, short, reaction}
    reactions: list[tuple[str, list[str], list[str]]] = field(default_factory=list)  # (name, substrates, products)
    source: str = "none"  # list_tool | none

    def short_names(self) -> dict[str, list[str]]:
        out: dict[str, list[str]] = {}
        for full, meta in self.parameters.items():
            out.setdefault(str(meta.get("short") or full).lower(), []).append(full)
        return out

    def resolve(self, name: str | None) -> tuple[str, str] | None:
        """(name, 'species'|'parameter') for a species/parameter name as written, or None."""
        if not name:
            return None
        n = str(name).strip()
        if n in self.species:
            return n, "species"
        if n in self.parameters:
            return n, "parameter"
        lower = n.lower()
        sp = [s for s in self.species if s.lower() == lower]
        if len(sp) == 1:
            return sp[0], "species"
        full = [p for p in self.parameters if p.lower() == lower]
        if len(full) == 1:
            return full[0], "parameter"
        short = self.short_names().get(lower, [])
        return (short[0], "parameter") if len(short) == 1 else None


def _num(value: Any) -> float | None:
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    return out if math.isfinite(out) else None


def _scheme_sides(scheme: str) -> tuple[list[str], list[str]]:
    body = str(scheme or "").split(";", 1)[0]
    parts = re.split(r"->|=", body, maxsplit=1)
    if len(parts) != 2:
        return [], []

    def names(side: str) -> list[str]:
        return [t for t in (re.sub(r"^\s*\d+(?:\.\d+)?\s*\*?\s*", "", term).strip() for term in side.split("+")) if t]

    return names(parts[0]), names(parts[1])


def kinetic_model_in_play(ctx: Any) -> ModelRef | None:
    """The SBML model a calibration runs on: an uploaded SBML model or a typed BioModels accession."""
    att = getattr(ctx, "model_attachment", None)
    if att is not None and getattr(att, "model_path", None):
        return ModelRef(
            biomodel_id=att.id,
            label=att.display_name or att.id,
            sim_kwargs={"sbml_path": att.model_path, "model_label": att.display_name,
                        "model_provenance": dict(att.public_provenance or {})},
        )
    bm = getattr(ctx, "biomodel_id", None)
    return ModelRef(biomodel_id=str(bm), label=str(bm)) if bm else None


async def fetch_model_info(state: AgentState, model: ModelRef, phase: str) -> ModelInfo:
    """The model's species, parameters and reactions (vivarix_list_parameters); empty when it cannot be listed."""
    info = ModelInfo()
    if state.registry.get_entry(LIST_TOOL) is None:
        return info
    kwargs: dict[str, Any] = {"biomodel_id": model.biomodel_id}
    if model.sim_kwargs.get("sbml_path"):
        kwargs.update(sbml_path=model.sim_kwargs["sbml_path"], model_label=model.sim_kwargs.get("model_label"))
    res = await state.call_tool(LIST_TOOL, phase=phase, purpose=f"list the parameters of {model.label}", store=False, **kwargs)
    data = res.data if getattr(res, "success", False) and isinstance(getattr(res, "data", None), dict) else {}
    if not data:
        return info
    info.source = "list_tool"
    for s in data.get("species") or []:
        if isinstance(s, dict) and s.get("name"):
            info.species[str(s["name"])] = _num(s.get("initial_concentration"))
    for g in data.get("global_parameters") or []:
        if isinstance(g, dict) and g.get("name"):
            info.parameters[str(g["name"])] = {"value": _num(g.get("value")), "short": str(g["name"]), "reaction": ""}
    for p in data.get("reaction_parameters") or []:
        if not isinstance(p, dict) or not p.get("name"):
            continue
        mapped = p.get("mapped_to")
        if mapped and mapped in info.parameters:
            info.parameters[mapped].setdefault("reactions", []).append(str(p.get("reaction") or ""))
            continue
        info.parameters[str(p["name"])] = {"value": _num(p.get("value")), "short": str(p.get("short_name") or p["name"]),
                                           "reaction": str(p.get("reaction") or "")}
    for r in data.get("reactions") or []:
        if isinstance(r, dict) and r.get("name"):
            subs, prods = _scheme_sides(str(r.get("scheme") or ""))
            info.reactions.append((str(r["name"]), subs, prods))
    return info


def has_calibration_intent(text: str) -> bool:
    return bool(CALIBRATION_INTENT_RE.search(text or ""))


def has_fit_intent(text: str) -> bool:
    return has_calibration_intent(text)


def _table_attachment(ctx: Any) -> tuple[Any | None, str | None]:
    from ..extensions.calibration import attachment_table_path

    for att in getattr(ctx, "attachments", None) or []:
        if getattr(att, "kind", None) == "table":
            path = attachment_table_path(att)
            if path:
                return att, path
    return None, None


def _data_columns(path: str) -> list[str]:
    import pandas as pd

    sep = "\t" if path.lower().endswith(".tsv") else ","
    try:
        cols = [str(c).strip() for c in pd.read_csv(path, sep=sep, nrows=0).columns]
    except Exception:  # noqa: BLE001
        return []
    return [c for c in cols if c.lower() not in ("time", "t") and not c.lower().startswith("sd_")]


class FitPhase(AgentPhase):
    key = PHASE
    stage = "augment"
    order = 55
    frameworks = None  # every agentic framework

    def applies(self, state: AgentState) -> bool:
        if getattr(state.ctx, "scope", "research") != "research":
            return False
        return has_calibration_intent(state.clean_query or state.query or "")

    async def run(self, state: AgentState) -> None:
        ctx = state.ctx
        block = simulation_block_reason(ctx)
        model = kinetic_model_in_play(ctx)
        att, data_path = _table_attachment(ctx)
        reason = ""
        if block:
            reason = f"Model calibration was not run: {block}."
        elif model is None:
            reason = ("Model calibration needs a kinetic model (an uploaded SBML file); fitting an ODE system's parameters "
                      "to data is not run by this phase.")
        elif data_path is None:
            reason = "Model calibration needs an attached time-course table (CSV/TSV with a 'time' column and species columns)."
        elif state.registry.get_entry(TOOL) is None and state.registry.get_entry(DYNAMIS_FIT_TOOL) is None:
            reason = "The calibration tool is not available on this server."
        elif state.budget.remaining_seconds() < _MIN_SECONDS_LEFT:
            reason = "Model calibration was skipped: the run's time budget is nearly used."

        if reason:
            state.artifacts["model_calibration"] = {
                "model_id": model.biomodel_id if model else None,
                "dataset": att.display_name if att else None,
                "backend": None,
                "status": "skipped",
                "reason": reason,
            }
            state.scope_notes.append(reason + " Do not report fitted parameter values.")
            await state.step("agent_calibrate", "Model calibration not run", reason, status="error", agent="Vivarix")
            return

        assert model is not None and att is not None and data_path is not None
        info = await self._model_info(state, model)
        names, selection = await self._select_parameters(state, info, data_path)
        if not names:
            reason = "No model parameter to calibrate could be identified; name the parameters (e.g. 'fit k1 and k2')."
            state.artifacts["model_calibration"] = {
                "model_id": model.biomodel_id,
                "dataset": att.display_name,
                "backend": None,
                "status": "skipped",
                "reason": reason,
                "parameter_selection": selection,
            }
            state.scope_notes.append(reason)
            await state.step("agent_calibrate", "Model calibration not run", reason, status="error", agent="Vivarix")
            return

        kwargs: dict[str, Any] = {
            "biomodel_id": model.biomodel_id,
            "data_path": data_path,
            "parameter_names": names,
            "profile": True,
            "profile_points": 7,
            "dataset_label": att.display_name,
        }
        if model.sim_kwargs.get("sbml_path"):
            kwargs.update(
                sbml_path=model.sim_kwargs["sbml_path"],
                model_label=model.sim_kwargs.get("model_label"),
            )
        await state.step(
            "agent_calibrate",
            f"Calibrating {', '.join(names)} of {model.label}",
            "least squares + profile likelihood",
            status="running",
            agent="Vivarix",
        )
        res = await state.call_tool(
            TOOL,
            phase=PHASE,
            purpose=f"calibrate {', '.join(names)} of {model.label} against {att.display_name}",
            store=False,
            **kwargs,
        )
        key = state.add_result(state.next_key(PHASE, TOOL), res, phase=PHASE, purpose="model calibration", render=False)
        data = res.data if isinstance(getattr(res, "data", None), dict) else {}
        if not getattr(res, "success", False):
            err = str(getattr(res, "error", "") or "calibration failed")[:300]
            state.artifacts["model_calibration"] = {
                **{k: data.get(k) for k in ("model_id", "dataset", "backend") if k in data},
                "model_id": data.get("model_id") or model.biomodel_id,
                "dataset": att.display_name,
                "status": "error",
                "error": err,
                "parameter_selection": selection,
                "result_key": key,
            }
            state.scope_notes.append(f"Model calibration failed ({err}); report no fitted parameter values.")
            await state.step("agent_calibrate", "Model calibration failed", err, status="error", agent="Vivarix")
            return

        artifact = self._artifact(data, model, att, selection, key)
        state.artifacts["model_calibration"] = artifact
        state.evidence_sections.append(self._evidence_xml(artifact))
        state.brief_notes.append(
            "Model calibration: report each estimate with its 95% profile-likelihood interval and identifiability "
            "class exactly as given in <model_calibration>, plus chi2 and RMSE. A parameter with an open interval or a "
            "non-identifiable class is not determined by the data; say so instead of quoting it as a measured value."
        )
        summary = "; ".join(
            f"{p['name']}={p.get('estimate')} ({str(p.get('identifiability')).replace('_', ' ')})"
            for p in artifact["parameters"][:5]
        )
        await state.step(
            "agent_calibrate",
            f"Calibrated {len(artifact['parameters'])} parameter(s) (status {artifact['status']})",
            summary,
            agent="Vivarix",
        )

    # -- parameters -----------------------------------------------------------------------------------------
    async def _model_info(self, state: AgentState, model: ModelRef) -> ModelInfo:
        return await fetch_model_info(state, model, PHASE)

    async def _select_parameters(
        self, state: AgentState, info: ModelInfo, data_path: str
    ) -> tuple[list[str], dict[str, Any]]:
        question = state.clean_query or state.query or ""
        named: list[tuple[int, str]] = []
        shorts = info.short_names()
        for full, meta in info.parameters.items():
            for cand in dict.fromkeys([full, str(meta.get("short") or "")]):
                if not cand:
                    continue
                pos = _mentions(question, cand)
                if pos is not None and (cand == full or len(shorts.get(cand.lower(), [])) == 1):
                    named.append((pos, full))
                    break
        if named:
            names = list(dict.fromkeys(n for _p, n in sorted(named)))[:5]
            return names, {"source": "question", "names": names}

        if info.parameters and state.llm.available:
            try:
                picked = await self._llm_pick(state, question, info, data_path)
                if picked:
                    return picked, {"source": "llm", "names": picked}
            except (AgentLLMUnavailable, BudgetExhausted, ValueError) as exc:
                logger.info("Calibration parameter choice failed: %s", exc)

        observed = [c for c in _data_columns(data_path) if info.resolve(c) and info.resolve(c)[1] == "species"]
        mentioned = [s for s in info.species if _mentions(question, s) is not None]
        focus = list(dict.fromkeys(mentioned + observed))
        picks: list[str] = []
        for rname, subs, prods in info.reactions:
            if not any(s in subs or s in prods for s in focus):
                continue
            for full, meta in info.parameters.items():
                if (meta.get("reaction") == rname or rname in (meta.get("reactions") or [])) and full not in picks:
                    picks.append(full)
        picks = picks[:FALLBACK_K]
        return picks, {"source": "species", "names": picks, "species": focus[:10]}

    async def _llm_pick(self, state: AgentState, question: str, info: ModelInfo, data_path: str) -> list[str]:
        system = (
            "[phase:calibrate] You choose which kinetic parameters to estimate from a time-course data set. Pick at "
            f"most {MAX_PICK} parameters from the model's parameter list that the observed species constrain best. "
            + SPOTLIGHT_RULE
            + " Reply with JSON only: {\"parameters\": [exact names from the list], \"reason\": str}."
        )
        user = "\n".join(
            [
                f"Question: {neutralise(question)[:800]}",
                "Observed species (data columns): " + ", ".join(_data_columns(data_path)[:20]),
                "Model parameters: " + ", ".join(f"{n}={meta.get('value')}" for n, meta in list(info.parameters.items())[:60]),
                "Reactions: " + "; ".join(f"{r}: {' + '.join(s)} -> {' + '.join(p)}" for r, s, p in info.reactions[:30]),
            ]
        )
        reply = await state.llm.json(system, user, phase=PHASE)
        raw = reply.get("parameters") if isinstance(reply, dict) else None
        out: list[str] = []
        for name in raw or []:
            r = info.resolve(str(name))
            if r and r[1] == "parameter" and r[0] not in out:
                out.append(r[0])
        return out[:MAX_PICK]

    # -- output ---------------------------------------------------------------------------------------------
    @staticmethod
    def _artifact(
        data: dict[str, Any], model: ModelRef, att: Any, selection: dict[str, Any], key: str
    ) -> dict[str, Any]:
        fit = {}
        for sp, curve in list((data.get("fit") or {}).items())[:20]:
            if isinstance(curve, dict):
                fit[sp] = {k: list(curve.get(k) or [])[:200] for k in ("time", "observed", "simulated")}
        return {
            "model_id": data.get("model_id") or model.biomodel_id,
            "model_name": data.get("model_name") or model.label,
            "dataset": att.display_name,
            "dataset_id": att.id,
            "backend": data.get("backend"),
            "status": data.get("status"),
            "objective": data.get("objective") or {},
            "parameters": list(data.get("parameters") or [])[:5],
            "profiles": {k: list(v)[:15] for k, v in (data.get("profiles") or {}).items()},
            "profile_details": data.get("profile_details") or {},
            "fit": fit,
            "threshold": data.get("threshold"),
            "optimizer": data.get("optimizer"),
            "units": data.get("units"),
            "notes": list(data.get("notes") or [])[:10],
            "parameter_selection": selection,
            "result_key": key,
            "seconds": data.get("seconds"),
        }

    @staticmethod
    def _evidence_xml(a: dict[str, Any]) -> str:
        def attr(v: Any) -> str:
            return escape("" if v is None else str(v), quote=True)

        obj = a.get("objective") or {}
        head = (
            f'<model_calibration model="{attr(a.get("model_name") or a.get("model_id"))}" dataset="{attr(a.get("dataset"))}" '
            f'backend="{attr(a.get("backend"))}" status="{attr(a.get("status"))}" chi2="{attr(obj.get("chi2"))}" '
            f'rmse="{attr(obj.get("rmse"))}" n_points="{attr(obj.get("n_points"))}" ci="95% profile likelihood, delta chi2 3.84" '
            f'result_key="{attr(a.get("result_key"))}">'
        )
        rows = []
        for p in a.get("parameters") or []:
            ci_low = p.get("ci_low") if p.get("ci_low") is not None else "open"
            ci_high = p.get("ci_high") if p.get("ci_high") is not None else "open"
            rows.append(
                f'<parameter name="{attr(p.get("name"))}" initial="{attr(p.get("initial"))}" estimate="{attr(p.get("estimate"))}" '
                f'ci_low="{attr(ci_low)}" ci_high="{attr(ci_high)}" identifiability="{attr(p.get("identifiability"))}" '
                f'at_bound="{"true" if p.get("at_bound") else "false"}"/>'
            )
        sigma = obj.get("sigma_rule") or {}
        note = "sigma per species: " + "; ".join(f"{k}: {v}" for k, v in list(sigma.items())[:10]) if sigma else ""
        return "\n".join([head, *rows, f"<note>{escape(note, quote=False)}</note>" if note else "", "</model_calibration>"])


CalibratePhase = FitPhase

register_phase(FitPhase())

__all__ = [
    "CALIBRATION_INTENT_RE",
    "CalibratePhase",
    "FIT_INTENT_RE",
    "FitPhase",
    "has_calibration_intent",
    "has_fit_intent",
]
