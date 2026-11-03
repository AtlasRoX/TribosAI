"""
A persistent Python session for step-by-step work (CodeAct, docs/plans/tribos-harness-landscape.md item 5).

Each cell sees the variables, functions and imports of the cells before it, as in a notebook. The session does not
keep a long-lived interpreter: that would sit outside the sandbox's per-run limits and guards. Instead every cell runs
as one ordinary sandboxed execution (gateway.execute) that first replays the session's earlier successful cells with
their output discarded, then runs the new cell. State is therefore rebuilt exactly, every cell is checked by the same
AST policy and resource limits, and a failed cell never enters the history.

Replaying costs the time of the earlier cells, so the history is capped (MAX_CELLS, MAX_HISTORY_CHARS); code that
draws random numbers should seed them, or a replay produces different values.
"""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass, field
from typing import Any

MAX_CELLS = 16
MAX_HISTORY_CHARS = 24_000
_LINE_RE = re.compile(r'(File "<analysis>", line |line )(\d+)')


@dataclass
class CellResult:
    code: str
    status: str  # ok | error | timeout | policy_violation | failed | disabled | forbidden | busy
    stdout: str = ""
    error: str = ""
    seconds: float = 0.0
    result: Any = None
    # Matplotlib figures the cell drew ({name, png_base64, axes, ...}); kept out of to_dict (they are large).
    figures: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {"code": self.code, "status": self.status, "stdout": self.stdout, "error": self.error,
                "seconds": round(self.seconds, 3), "figures": len(self.figures)}


@dataclass
class PythonSession:
    """Cells run in order; a successful cell's definitions are visible to every later cell."""

    timeout_s: float | None = None
    cells: list[str] = field(default_factory=list)
    history: list[CellResult] = field(default_factory=list)

    def _prelude(self) -> str:
        return "\n".join(self.cells)

    def run(self, code: str) -> CellResult:
        from .gateway import execute

        code = str(code or "").strip("\n")
        if not code.strip():
            cell = CellResult(code=code, status="error", error="empty cell")
            self.history.append(cell)
            return cell
        marker = f"__TRIBOS_CELL_{uuid.uuid4().hex[:12]}__"
        prelude = self._prelude()
        # The prelude's own prints are discarded: only what follows the marker belongs to this cell.
        source = (prelude + "\n" if prelude else "") + f"print({marker!r})\n" + code
        offset = (prelude.count("\n") + 1 if prelude else 0) + 1
        report = execute(source, timeout_s=self.timeout_s)
        stdout = str(report.get("stdout") or "").replace("\r\n", "\n")
        if marker in stdout:
            stdout = stdout.split(marker, 1)[1].strip("\n")
        elif report.get("status") == "ok":
            stdout = "(output truncated before this cell's output)"
        else:
            stdout = ""  # the failure happened while replaying the earlier cells
        error = "\n".join(str(x) for x in (report.get("error"), report.get("stderr")) if x).strip()
        # Line numbers refer to the replayed source; shift them back to the cell's own lines.
        error = _LINE_RE.sub(lambda m: f"{m.group(1)}{max(1, int(m.group(2)) - offset)}", error)
        if report.get("violations"):
            error = (error + "\n" + "; ".join(str(v) for v in report["violations"])[:600]).strip()
        cell = CellResult(code=code, status=str(report.get("status") or "failed"), stdout=stdout, error=error[:4000],
                          seconds=float(report.get("seconds") or 0.0), result=report.get("result"),
                          figures=[f for f in (report.get("figures") or []) if isinstance(f, dict)])
        self.history.append(cell)
        if cell.status == "ok":
            self.cells.append(code)
            while len(self.cells) > MAX_CELLS or len(self._prelude()) > MAX_HISTORY_CHARS:
                self.cells.pop(0)
        return cell


__all__ = ["CellResult", "MAX_CELLS", "PythonSession"]
