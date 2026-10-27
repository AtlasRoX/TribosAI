"""
Enforceable request tool policy: explicit restrictions on capabilities (formal proof, search, code execution, simulation).

Enforces user prohibitions across every orchestration phase (router, planner, gather, augment, draft, debate, verify)
and at the lowest dispatch boundary (registry.execute and execute_with_policies).
"""

from __future__ import annotations

import contextlib
import contextvars
import re
from collections.abc import Iterator
from dataclasses import dataclass, field
from typing import Any

# Quoted spans are ignored during prohibition extraction so quoted examples and references
# (e.g. 'explain "do not search the web or run a formal prover"') are not treated as active bans.
_QUOTED_RE = re.compile(r"\"[^\"\n]{1,400}\"|“[^”\n]{1,400}”|‘[^’\n]{1,400}’|`[^`\n]{1,400}`|(?<!\w)'[^'\n]{1,400}'(?!\w)")

# Revocation cues that lift a prior or mentioned prohibition
_REVOCATION_RE = re.compile(
    r"(?i)\b(?:remove|lift|drop|cancel|ignore|disregard|forget|override)\s+(?:the\s+)?(?:previous\s+|earlier\s+|prior\s+)?"
    r"(?:restriction|ban|prohibition|rule|instruction|limit)s?\b"
    r"|\b(?:is|are)\s+now\s+(?:allowed|permitted|enabled|acceptable)\b"
    r"|\b(?:now\s+)?(?:allow|permit|enable)\s+(?:search|formal\s+(?:prover|proof)|lean|code|simulation)\b"
)

# Negative trigger capturing the list of prohibited items/actions
_TRIGGER_RE = re.compile(
    r"(?i)\b(?:do\s*n[o']t|don't|no|without|avoid(?:ing)?|skip(?:ping)?|never)\s+(?P<body>[^.;!?\n]{1,160})"
)

_VERBS = r"(?:run(?:ning)?|use|using|invoke|invoking|call(?:ing)?|attempt(?:ing)?|execute|executing|with|perform(?:ing)?|conduct(?:ing)?)"

_FORMAL_ITEM = re.compile(
    rf"(?i)\b(?:{_VERBS}\s+)?(?:a\s+|any\s+)?(?:formal\s+(?:prover|proof|verification|checker)|lean(?:\s*4)?(?:\s+(?:prover|checker|proof))?|theorem\s+prover|proof\s+assistant)\b"
)
_SEARCH_ITEM = re.compile(
    rf"(?i)\b(?:{_VERBS}\s+)?(?:the\s+web\s+|online\s+|internet\s+)?(?:web\s*search|internet\s+search|online\s+search|literature\s+search|paper\s+retrieval|external\s+search|search)\b"
)
_CODE_ITEM = re.compile(
    rf"(?i)\b(?:{_VERBS}\s+)?(?:code(?:\s+execution)?|python(?:\s+code|\s+execution)?|sandboxed\s+code|scripts?)\b"
)
_SIM_ITEM = re.compile(
    rf"(?i)\b(?:{_VERBS}\s+)?(?:simulations?|odes?|dynamical\s+simulations?)\b"
)

_EXPLICIT_OFF_FORMAL = re.compile(r"(?i)\b(?:formal\s+(?:prover|verification)|lean):\s*(?:off|disabled|no|false|none)\b")
_EXPLICIT_OFF_SEARCH = re.compile(r"(?i)\b(?:web\s*search|search):\s*(?:off|disabled|no|false|none)\b")
_EXPLICIT_OFF_CODE = re.compile(r"(?i)\bcode(?:\s+execution)?:\s*(?:off|disabled|no|false|none)\b")
_EXPLICIT_OFF_SIM = re.compile(r"(?i)\bsimulation:\s*(?:off|disabled|no|false|none)\b")

# Existential / factual statements of absence that MUST NOT be read as user prohibitions
_ABSENCE_EXCLUDE = re.compile(
    r"(?i)\b(?:there\s+(?:is|was|are|were|exists?)\s+no\b|"
    r"\bno\s+(?:accepted|known|published|rigorous|complete|verified)?\s*proof\s+(?:is|was|has\s+been|exists?\b)|"
    r"\b(?:statement|theorem|proposition|claim|conjecture|formula)\s+with\s+no\b|"
    r"\bis\s+called\s+a\b|\bno\s+real\s+solution\b|\bno\s+search\s+results?\s+found\b)"
)

# Explicit opt-in directive for search that overrides default or standing off settings
_SEARCH_OPT_IN_RE = re.compile(
    r"(?i)\b(?:search\s+(?:the\s+web|online|the\s+internet|the\s+literature)|find\s+recent\s+papers?|look\s+up\s+online)\b"
)


@dataclass
class ToolPolicy:
    """Enforceable tool restriction policy for a request."""

    prohibit_search: bool = False
    search_reason: str = ""
    search_source: str = "default"  # prompt | ui_setting | standing_instruction | default

    prohibit_formal: bool = False
    formal_reason: str = ""
    formal_source: str = "default"  # prompt | standing_instruction | default

    prohibit_code: bool = False
    code_reason: str = ""
    code_source: str = "default"

    prohibit_simulation: bool = False
    simulation_reason: str = ""
    simulation_source: str = "default"

    prohibited_tools: set[str] = field(default_factory=set)

    @property
    def active(self) -> bool:
        return any((self.prohibit_search, self.prohibit_formal, self.prohibit_code,
                    self.prohibit_simulation, bool(self.prohibited_tools)))

    def is_tool_prohibited(self, tool_name: str, entry: Any = None) -> tuple[bool, str]:
        """Check if executing tool_name (with optional ToolUniverseEntry) is prohibited by this policy."""
        name = str(tool_name or "").lower()
        if name in self.prohibited_tools:
            return True, f"Tool '{tool_name}' disabled by user request"

        # 1. Formal prover check (Lean 4, axiom_formal_check, etc.)
        if self.prohibit_formal:
            if name == "axiom_formal_check":
                return True, self.formal_reason or "Formal prover disabled by user request"
            if entry is not None:
                domain = str(getattr(entry, "domain", "") or "").lower()
                tags = {str(t).lower() for t in (getattr(entry, "tags", None) or [])}
                if domain == "formal" or tags & {"lean", "formal_verification", "proof_checker", "theorem_prover"}:
                    return True, self.formal_reason or "Formal prover disabled by user request"

        # 2. Search & external retrieval check
        if self.prohibit_search:
            if name.startswith(("websurfer", "archivon", "lithoscribe")):
                return True, self.search_reason or "Search disabled by user request"
            if entry is not None:
                domain = str(getattr(entry, "domain", "") or "").lower()
                tags = {str(t).lower() for t in (getattr(entry, "tags", None) or [])}
                adapter = str(getattr(entry, "adapter_type", "") or "")
                if domain in ("websurfer", "archivon", "lithoscribe") or tags & {"search", "literature", "retrieval", "web"}:
                    return True, self.search_reason or "Search disabled by user request"
                if "DIRECT_REST" in adapter or "DIRECT_GRAPHQL" in adapter:
                    return True, self.search_reason or "Search disabled by user request"

        # 3. Code execution check
        if self.prohibit_code:
            if entry is not None:
                tags = {str(t).lower() for t in (getattr(entry, "tags", None) or [])}
                if "executes_code" in tags:
                    return True, self.code_reason or "Code execution disabled by user request"

        # 4. Simulation check
        if self.prohibit_simulation:
            if name.startswith(("dynamis", "vivarix")):
                return True, self.simulation_reason or "Simulation disabled by user request"
            if entry is not None:
                domain = str(getattr(entry, "domain", "") or "").lower()
                if domain in ("dynamis", "vivarix"):
                    return True, self.simulation_reason or "Simulation disabled by user request"

        return False, ""


def extract_tool_policy(
    query: str,
    *,
    enable_web_search: bool = True,
    standing_instructions: list[str] | None = None,
) -> ToolPolicy:
    """Extract enforceable ToolPolicy from user query, UI settings, and standing instructions with precedence rules."""
    policy = ToolPolicy()

    # Step 1: Baseline from UI settings
    if not enable_web_search:
        policy.prohibit_search = True
        policy.search_reason = "Search switched off in settings"
        policy.search_source = "ui_setting"

    # Step 2: Apply standing instructions if present
    for standing in (standing_instructions or []):
        if not isinstance(standing, str) or not standing.strip():
            continue
        s_unquoted = _QUOTED_RE.sub(" ", standing)
        for m in _TRIGGER_RE.finditer(s_unquoted):
            span_all = s_unquoted[max(0, m.start() - 30):min(len(s_unquoted), m.end() + 40)]
            if _ABSENCE_EXCLUDE.search(span_all):
                continue
            body = m.group("body")
            for item in re.split(r"[,;]|\b(?:or|nor|and)\b", body):
                item = item.strip()
                if not item:
                    continue
                if _FORMAL_ITEM.search(item):
                    policy.prohibit_formal = True
                    policy.formal_reason = "Formal prover disabled by standing instruction"
                    policy.formal_source = "standing_instruction"
                if _SEARCH_ITEM.search(item):
                    policy.prohibit_search = True
                    policy.search_reason = "Search disabled by standing instruction"
                    policy.search_source = "standing_instruction"
                if _CODE_ITEM.search(item):
                    policy.prohibit_code = True
                    policy.code_reason = "Code execution disabled by standing instruction"
                    policy.code_source = "standing_instruction"
                if _SIM_ITEM.search(item):
                    policy.prohibit_simulation = True
                    policy.simulation_reason = "Simulation disabled by standing instruction"
                    policy.simulation_source = "standing_instruction"

    # Step 3: Parse current turn query (highest precedence)
    unquoted = _QUOTED_RE.sub(" ", query or "")

    # Check for revocations first
    revoked_formal = bool(_REVOCATION_RE.search(unquoted) and re.search(r"(?i)\b(?:formal|lean)\b", unquoted))
    revoked_search = bool(_REVOCATION_RE.search(unquoted) and re.search(r"(?i)\bsearch\b", unquoted))

    if revoked_formal:
        policy.prohibit_formal = False
        policy.formal_reason = ""
    if revoked_search:
        policy.prohibit_search = False
        policy.search_reason = ""

    # Check explicit key:value flags
    if not policy.prohibit_formal and not revoked_formal and _EXPLICIT_OFF_FORMAL.search(unquoted):
        policy.prohibit_formal = True
        policy.formal_reason = "Formal prover disabled by user request"
        policy.formal_source = "prompt"
    if not policy.prohibit_search and not revoked_search and _EXPLICIT_OFF_SEARCH.search(unquoted):
        policy.prohibit_search = True
        policy.search_reason = "Search disabled by user request"
        policy.search_source = "prompt"
    if not policy.prohibit_code and _EXPLICIT_OFF_CODE.search(unquoted):
        policy.prohibit_code = True
        policy.code_reason = "Code execution disabled by user request"
        policy.code_source = "prompt"
    if not policy.prohibit_simulation and _EXPLICIT_OFF_SIM.search(unquoted):
        policy.prohibit_simulation = True
        policy.simulation_reason = "Simulation disabled by user request"
        policy.simulation_source = "prompt"

    # Parse trigger phrases and coordinated lists
    trigger_found_search = False
    for m in _TRIGGER_RE.finditer(unquoted):
        span_all = unquoted[max(0, m.start() - 30):min(len(unquoted), m.end() + 40)]
        if _ABSENCE_EXCLUDE.search(span_all):
            continue
        body = m.group("body")
        items = re.split(r"[,;]|\b(?:or|nor|and)\b", body)
        for item in items:
            item = item.strip()
            if not item:
                continue
            if not policy.prohibit_formal and not revoked_formal and _FORMAL_ITEM.search(item):
                policy.prohibit_formal = True
                policy.formal_reason = "Formal prover disabled by user request"
                policy.formal_source = "prompt"
            if not revoked_search and _SEARCH_ITEM.search(item):
                trigger_found_search = True
                policy.prohibit_search = True
                policy.search_reason = "Search disabled by user request"
                policy.search_source = "prompt"
            if not policy.prohibit_code and _CODE_ITEM.search(item):
                policy.prohibit_code = True
                policy.code_reason = "Code execution disabled by user request"
                policy.code_source = "prompt"
            if not policy.prohibit_simulation and _SIM_ITEM.search(item):
                policy.prohibit_simulation = True
                policy.simulation_reason = "Simulation disabled by user request"
                policy.simulation_source = "prompt"

    # If no trigger prohibited search in this prompt, check explicit opt-in (e.g. "search the web for X" when UI was off)
    if not trigger_found_search and _SEARCH_OPT_IN_RE.search(unquoted):
        policy.prohibit_search = False
        policy.search_reason = ""
        policy.search_source = "prompt"

    return policy


# ContextVar holding active tool policy for the running async execution context
_ACTIVE_TOOL_POLICY: contextvars.ContextVar[ToolPolicy | None] = contextvars.ContextVar(
    "tribos_active_tool_policy", default=None
)


def active_tool_policy() -> ToolPolicy | None:
    """Return the active ToolPolicy for the current execution context, if any."""
    return _ACTIVE_TOOL_POLICY.get()


@contextlib.contextmanager
def enforce_tool_policy(policy: ToolPolicy | None) -> Iterator[None]:
    """Context manager setting the active ToolPolicy across all nested calls and dispatch paths."""
    token = _ACTIVE_TOOL_POLICY.set(policy)
    try:
        yield
    finally:
        _ACTIVE_TOOL_POLICY.reset(token)


__all__ = [
    "ToolPolicy",
    "active_tool_policy",
    "enforce_tool_policy",
    "extract_tool_policy",
]
