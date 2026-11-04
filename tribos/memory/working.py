"""Working Memory: Tier 1 runtime state and context window management for Tribos.

Maintains:
- In-flight task DAG and sub-question status ledger
- Unit and dimensional registry
- Shared inter-agent specialist scratchpad
- Dynamic compaction and context budget-capped paging (CoALA / Letta architecture)
"""

from __future__ import annotations

import copy
from dataclasses import dataclass, field
from typing import Any


@dataclass
class WorkingGoal:
    id: str
    text: str
    focus: str = "general"
    status: str = "open"  # open | in_progress | answered | failed
    depends_on: list[str] = field(default_factory=list)
    results: dict[str, Any] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)


@dataclass
class WorkingMemory:
    """Active working memory scratchpad for an agentic run."""

    query: str
    goals: dict[str, WorkingGoal] = field(default_factory=dict)
    variables: dict[str, Any] = field(
        default_factory=dict
    )  # numeric/symbolic results shared across specialists
    units: dict[str, str] = field(
        default_factory=dict
    )  # variable_name -> dimension/unit string (e.g. 'F_load' -> 'N')
    scratchpad: list[str] = field(default_factory=list)  # chronological thought/execution notes
    active_assumptions: list[str] = field(default_factory=list)
    max_scratchpad_tokens: int = 1500

    def add_goal(
        self, goal_id: str, text: str, focus: str = "general", depends_on: list[str] | None = None
    ) -> WorkingGoal:
        goal = WorkingGoal(id=goal_id, text=text, focus=focus, depends_on=list(depends_on or []))
        self.goals[goal_id] = goal
        return goal

    def update_goal(self, goal_id: str, status: str, result: Any = None, note: str = "") -> None:
        if goal_id in self.goals:
            g = self.goals[goal_id]
            g.status = status
            if result is not None:
                g.results["latest"] = result
            if note:
                g.notes.append(note)

    def set_variable(self, name: str, value: Any, unit: str = "") -> None:
        """Store a verified calculation result or parameter available to all specialists."""
        self.variables[name] = value
        if unit:
            self.units[name] = unit

    def get_variable(self, name: str) -> Any:
        return self.variables.get(name)

    def append_note(self, note: str) -> None:
        """Add an execution or reasoning observation, applying dynamic compaction if over budget."""
        self.scratchpad.append(note.strip())
        self._compact_if_needed()

    def add_assumption(self, assumption: str) -> None:
        if assumption not in self.active_assumptions:
            self.active_assumptions.append(assumption.strip())

    def _compact_if_needed(self) -> None:
        """Compact older scratchpad items into a consolidated summary if token budget exceeded."""
        total_chars = sum(len(n) for n in self.scratchpad)
        # Approximate 4 chars per token
        if total_chars > self.max_scratchpad_tokens * 4:
            # Retain the 4 most recent notes, summarize older notes
            older = self.scratchpad[:-4]
            recent = self.scratchpad[-4:]
            condensed = (
                f"[Compacted {len(older)} earlier reasoning steps: {'; '.join(older[:2])}...]"
            )
            self.scratchpad = [condensed] + recent

    def render_context(self) -> str:
        """Render a dense, structured context block ready for injection into prompt."""
        lines = ["<working_memory>"]
        if self.active_assumptions:
            lines.append("  <assumptions>")
            for a in self.active_assumptions:
                lines.append(f"    - {a}")
            lines.append("  </assumptions>")

        if self.goals:
            lines.append("  <goals>")
            for g in self.goals.values():
                res_str = f" => {g.results.get('latest')}" if "latest" in g.results else ""
                lines.append(f"    - [{g.status.upper()}] {g.id}: {g.text}{res_str}")
            lines.append("  </goals>")

        if self.variables:
            lines.append("  <variables>")
            for k, v in self.variables.items():
                u = f" ({self.units[k]})" if k in self.units else ""
                lines.append(f"    - {k}{u} = {v}")
            lines.append("  </variables>")

        if self.scratchpad:
            lines.append("  <scratchpad>")
            for s in self.scratchpad:
                lines.append(f"    - {s}")
            lines.append("  </scratchpad>")

        lines.append("</working_memory>")
        return "\n".join(lines)

    def to_dict(self) -> dict[str, Any]:
        return {
            "query": self.query,
            "goals": {
                gid: {"text": g.text, "status": g.status, "results": g.results}
                for gid, g in self.goals.items()
            },
            "variables": copy.deepcopy(self.variables),
            "units": copy.deepcopy(self.units),
            "scratchpad": list(self.scratchpad),
            "active_assumptions": list(self.active_assumptions),
        }
