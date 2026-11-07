"""
Extension module for the agentic layer: imports every agent-phase module so each registers its phases.

A phase module that fails to import is logged and skipped; the others still load. Phases only run for
agentic frameworks (tribos.agentic.config), so the classic pipeline is unaffected by anything here.
"""

from __future__ import annotations

import importlib
import logging
from types import ModuleType

logger = logging.getLogger(__name__)

AGENT_PHASE_MODULES = (
    "tribos.agentic.clarify",  # 15 human in the loop: clarifying questions (before_evidence)
    "tribos.agentic.project_memory",  # 16 project memory recall (before_evidence) and consolidation (finalize)
    "tribos.agentic.decompose",  # 3 question decomposition (before_evidence)
    "tribos.agentic.approval",  # 15 plan approval (approve)
    "tribos.agentic.plan_execute",  # 1 LLM-planned tool DAG (augment; agentic + debate)
    "tribos.agentic.topologies",  # 4 supervisor / swarm (augment) and debate (after_draft)
    "tribos.agentic.router",  # Auto escalation to the critic debate (after_draft, before the debate)
    "tribos.agentic.math_agent",  # verified mathematics agent: tool loop + independent verifier (augment)
    "tribos.agentic.chem_agent",  # chemistry agent: reaction as SMILES, structures and options checked by code (augment)
    "tribos.agentic.formal_proof",  # optional Lean 4 formalisation and check of "prove ..." questions (augment)
    "tribos.agentic.ode_verification",  # residual, RK4 convergence and energy balance of a solved ODE (augment)
    "tribos.agentic.hypothesis",  # 6 hypothesis -> in-silico experiment loop (augment)
    "tribos.agentic.analyst",  # 10 sandboxed code analysis of attached data (augment)
    "tribos.agentic.fit",  # ODE fitting against attached measurements (augment)
    "tribos.agentic.counter_evidence",  # 7 contradiction search (augment)
    "tribos.agentic.nli",  # 8 NLI entailment judge for the verifier (augment)
    "tribos.agentic.gaps",  # 2 gap-driven re-retrieval (after_draft)
    "tribos.agentic.confidence",  # 9 calibrated per-claim confidence (finalize)
)

LOADED: list[ModuleType] = []

for _name in AGENT_PHASE_MODULES:
    try:
        LOADED.append(importlib.import_module(_name))
    except ModuleNotFoundError as _exc:
        if _exc.name == _name:
            logger.debug("Agent phase module %s not present", _name)
        else:
            logger.warning("Agent phase module %s failed to load: %s", _name, _exc)
    except Exception as _exc:  # noqa: BLE001
        logger.warning("Agent phase module %s failed to load: %s", _name, _exc)
