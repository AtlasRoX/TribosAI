"""Run the Lean 4 checker on a proof, when Lean is installed.

`check_lean(code)` writes the code to a fresh temporary directory and runs `lean <file>` (or `lake env lean <file>`
inside a Mathlib project when TRIBOS_LEAN_PROJECT points to one) with a timeout and, on POSIX, a memory limit. The
status is one of:

- "verified": a clean compile, and the code uses no `sorry`, `admit` or new `axiom`;
- "failed": the compiler reported errors (the messages are parsed), or the code relies on sorry/admit/axioms;
- "timeout": the check ran past TRIBOS_FORMAL_TIMEOUT_S;
- "unavailable": no Lean executable was found (TRIBOS_LEAN_PATH or PATH).

Results are cached by the hash of (code, checker command), so the same proof is checked once.
"""

from __future__ import annotations

import hashlib
import os
import re
import shutil
# subprocess runs only the configured Lean executable, with a list argv and no shell.
import subprocess  # nosec B404
import sys
import tempfile
import threading
from collections import OrderedDict
from typing import Any

from tribos.config.settings import get_float, get_str

STATUS_TITLES = {
    "verified": "formally verified (Lean)",
    "failed": "formalisation failed",
    "timeout": "formalisation failed",
    "unavailable": "formal checker unavailable",
}
MEMORY_LIMIT_MB = 4096
MAX_CODE_CHARS = 50_000
_CACHE: OrderedDict[str, dict[str, Any]] = OrderedDict()
_CACHE_SIZE = 256
_CACHE_LOCK = threading.Lock()

# "file.lean:3:7: error: unknown identifier 'x'" (Lean 4 prints the path it was given, then line:column).
_MESSAGE_RE = re.compile(r"^(?P<file>[^\n]*?):(?P<line>\d+):(?P<col>\d+):\s*(?P<severity>error|warning|info):\s*(?P<text>.*)$")
_SORRY_RE = re.compile(r"(?<![\w.'])(sorry|admit)(?![\w'])")
_AXIOM_RE = re.compile(r"^\s*(?:private\s+|protected\s+)?axiom\s+\S+", re.M)
_COMMENT_RE = re.compile(r"/-.*?-/|--[^\n]*", re.S)


def find_lean() -> dict[str, Any] | None:
    """The checker command: {"argv": [...], "cwd": dir or None, "kind": "lean" | "lake"}, or None when unavailable."""
    configured = str(get_str("TRIBOS_LEAN_PATH") or "").strip()
    project = str(get_str("TRIBOS_LEAN_PROJECT") or "").strip()
    if project and os.path.isdir(project):
        lake = configured if configured and os.path.basename(configured).lower().startswith("lake") else shutil.which("lake")
        if lake:
            return {"argv": [lake, "env", "lean"], "cwd": project, "kind": "lake"}
    exe = configured or shutil.which("lean")
    if exe and os.path.isfile(exe):
        argv = [sys.executable, exe] if exe.endswith(".py") else [exe]
        return {"argv": argv, "cwd": None, "kind": "lean"}
    return None


def parse_messages(output: str) -> list[dict[str, Any]]:
    """Lean's diagnostics as {line, column, severity, message}; continuation lines join the message above."""
    messages: list[dict[str, Any]] = []
    for raw in output.splitlines():
        m = _MESSAGE_RE.match(raw.strip())
        if m:
            messages.append({"line": int(m["line"]), "column": int(m["col"]), "severity": m["severity"],
                             "message": m["text"].strip()})
        elif messages and raw.strip():
            messages[-1]["message"] += "\n" + raw.rstrip()
    return messages


def uses_unproved(code: str) -> list[str]:
    """What makes code not a proof even when it compiles: sorry, admit, or a new axiom (comments ignored)."""
    body = _COMMENT_RE.sub(" ", code)
    found = sorted({m.group(1) for m in _SORRY_RE.finditer(body)})
    found += [f"axiom {m.group(0).split()[-1]}" for m in _AXIOM_RE.finditer(body)]
    return found


def _limit_memory() -> None:  # pragma: no cover - runs in the child on POSIX
    import resource

    limit = MEMORY_LIMIT_MB * 1024 * 1024
    resource.setrlimit(resource.RLIMIT_AS, (limit, limit))


def check_lean(code: str, timeout_s: float | None = None) -> dict[str, Any]:
    """Check one Lean 4 file's worth of code (see the module docstring for the statuses)."""
    if len(code) > MAX_CODE_CHARS:
        return {"status": "failed", "title": STATUS_TITLES["failed"], "messages": [],
                "error": f"The code is longer than {MAX_CODE_CHARS} characters.", "cached": False}
    command = find_lean()
    if command is None:
        return {"status": "unavailable", "title": STATUS_TITLES["unavailable"], "messages": [], "cached": False,
                "error": "Lean is not installed (set TRIBOS_LEAN_PATH, or put lean on PATH)."}
    timeout = float(timeout_s if timeout_s is not None else get_float("TRIBOS_FORMAL_TIMEOUT_S"))
    key = hashlib.sha256(("\0".join(command["argv"]) + "\0" + str(command["cwd"]) + "\0" + code).encode()).hexdigest()
    with _CACHE_LOCK:
        if key in _CACHE:
            _CACHE.move_to_end(key)
            return {**_CACHE[key], "cached": True}

    unproved = uses_unproved(code)
    with tempfile.TemporaryDirectory(prefix="tribos-lean-") as work:
        path = os.path.join(work, "Proof.lean")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(code)
        try:
            # A fixed argv of the configured checker, no shell.
            proc = subprocess.run(  # nosec B603
                # Lean writes UTF-8; the platform default (cp1252 on Windows) would garble "ℕ" in its messages.
                [*command["argv"], path], cwd=command["cwd"] or work, capture_output=True, text=True,
                encoding="utf-8", errors="replace",
                timeout=timeout, preexec_fn=_limit_memory if os.name == "posix" else None,  # noqa: PLW1509
            )
        except subprocess.TimeoutExpired:
            result = {"status": "timeout", "title": STATUS_TITLES["timeout"], "messages": [],
                      "error": f"Lean did not finish within {timeout:g} s."}
            return {**result, "cached": False}
        except OSError as exc:
            return {"status": "unavailable", "title": STATUS_TITLES["unavailable"], "messages": [], "cached": False,
                    "error": f"Lean could not be started ({type(exc).__name__})."}
    output = (proc.stdout or "") + (proc.stderr or "")
    messages = parse_messages(output.replace(path, "Proof.lean"))
    errors = [m for m in messages if m["severity"] == "error"]
    sorry_warning = any("sorry" in m["message"] for m in messages if m["severity"] == "warning")
    if proc.returncode != 0 or errors:
        status, error = "failed", (errors[0]["message"] if errors else f"Lean exited with code {proc.returncode}.")
    elif unproved or sorry_warning:
        status, error = "failed", f"The proof is incomplete: it uses {', '.join(unproved) or 'sorry'}."
    else:
        status, error = "verified", None
    result = {"status": status, "title": STATUS_TITLES[status], "messages": messages[:50], "error": error,
              "unproved": unproved, "output": output.replace(path, "Proof.lean")[-4000:], "checker": command["kind"]}
    with _CACHE_LOCK:
        _CACHE[key] = result
        while len(_CACHE) > _CACHE_SIZE:
            _CACHE.popitem(last=False)
    return {**result, "cached": False}


def clear_cache() -> None:
    with _CACHE_LOCK:
        _CACHE.clear()


__all__ = ["STATUS_TITLES", "check_lean", "clear_cache", "find_lean", "parse_messages", "uses_unproved"]
