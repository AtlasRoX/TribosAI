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

import contextlib
import hashlib
import os
import re
import shutil

# subprocess runs only the configured Lean executable, with a list argv and no shell.
import subprocess  # nosec B404
import sys
import tempfile
import threading
import time
from collections import OrderedDict
from typing import Any

from tribos.config.settings import get_bool, get_float, get_str

STATUS_TITLES = {
    "verified": "formally verified (Lean)",
    "failed": "formalisation failed",
    "timeout": "formalisation failed",
    "unavailable": "formal checker unavailable",
    "disabled": "formal prover disabled by user",
    "disabled_by_user": "formal prover disabled by user",
    # Audit I33: the written theorem does not state the question (True/False target, assumed conclusion, changed
    # domain), or the question cannot be stated in the installed Lean environment.
    "mismatch": "formal statement does not match the question",
    "not_formalizable": "not formalisable without Mathlib",
}
MEMORY_LIMIT_MB = 4096
MAX_CODE_CHARS = 50_000
# One Lean process at a time (each loads Mathlib), and a check whose library could not be loaded is retried, then
# reported as unavailable: it is never a verdict on the proof.
_LEAN_SLOTS = threading.BoundedSemaphore(1)
ENVIRONMENT_RETRIES = 2
_ENVIRONMENT_ERROR_RE = re.compile(r"failed to read file '[^']*\.(?:olean|ilean|ir)\w*'|could not find native implementation"
                                   r"|unknown package '[^']+'|object file .{0,200} does not exist", re.I)
_CACHE: OrderedDict[str, dict[str, Any]] = OrderedDict()
_CACHE_SIZE = 256
_CACHE_LOCK = threading.Lock()

# "file.lean:3:7: error: unknown identifier 'x'" (Lean 4 prints the path it was given, then line:column).
_MESSAGE_RE = re.compile(r"^(?P<file>[^\n]*?):(?P<line>\d+):(?P<col>\d+):\s*(?P<severity>error|warning|info):\s*(?P<text>.*)$")
_SORRY_RE = re.compile(r"(?<![\w.'])(sorry|admit)(?![\w'])")
_AXIOM_RE = re.compile(r"^\s*(?:private\s+|protected\s+)?axiom\s+([A-Za-z0-9_.]+)", re.M)

# Trusted foundational axioms of Lean/Mathlib that should not be blanket-banned as cheat axioms
_TRUSTED_FOUNDATIONAL_AXIOMS = frozenset({
    "propext",
    "Classical.choice",
    "Quot.sound",
    "funext",
    "choice",
    "Quot.lift",
    "Quot.ind",
})
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
    for m in _AXIOM_RE.finditer(body):
        ax_name = m.group(1).strip()
        if ax_name not in _TRUSTED_FOUNDATIONAL_AXIOMS:
            found.append(f"axiom {ax_name}")
            continue
        tail = body[m.end():]
        colon = tail.find(":")
        if colon != -1:
            end_line = tail.find("\n", colon)
            ax_type = tail[colon + 1:end_line if end_line != -1 else len(tail)].strip()
            if re.search(r"\bFalse\b", ax_type):
                found.append(f"axiom {ax_name} (asserts False)")
    # Escape hatches that make the kernel trust compiled code instead of checking a proof term (reward hacking in
    # proof search; docs/plans/tribos-research-upgrade-plan.md 2.1): not a kernel-checked proof.
    for pattern, label in ((r"\bnative_decide\b", "native_decide"), (r"\bimplemented_by\b", "implemented_by"),
                           (r"@\[\s*extern\b", "@[extern]"), (r"(?m)^\s*(?:private\s+|protected\s+)?unsafe\b", "unsafe"),
                           (r"\bLean\.ofReduceBool\b", "Lean.ofReduceBool")):
        if re.search(pattern, body):
            found.append(label)
    return sorted(found)


def _limit_memory() -> None:  # pragma: no cover - runs in the child on POSIX
    import resource

    limit = MEMORY_LIMIT_MB * 1024 * 1024
    resource.setrlimit(resource.RLIMIT_AS, (limit, limit))


# Loading all of Mathlib (`import Mathlib`) takes several GB of memory; this set covers most competition and textbook
# statements (tactics, real powers, logs, trigonometry, primes, square roots, classical inequalities) in about 20 s.
DEFAULT_MATHLIB_IMPORTS = (
    "Mathlib.Tactic.Linarith", "Mathlib.Tactic.Positivity", "Mathlib.Tactic.Ring", "Mathlib.Tactic.FieldSimp",
    "Mathlib.Tactic.NormNum", "Mathlib.Tactic.NormNum.Prime", "Mathlib.Tactic.IntervalCases",
    "Mathlib.Analysis.SpecialFunctions.Pow.Real", "Mathlib.Analysis.SpecialFunctions.Log.Basic",
    "Mathlib.Analysis.SpecialFunctions.Trigonometric.Basic", "Mathlib.Data.Nat.Prime.Basic",
    "Mathlib.Analysis.Real.Sqrt", "Mathlib.Algebra.Order.Chebyshev",
)
_BARE_MATHLIB_RE = re.compile(r"^\s*import\s+Mathlib\s*$", re.M)


def with_default_imports(code: str) -> str:
    """A bare `import Mathlib` replaced by DEFAULT_MATHLIB_IMPORTS, unless TRIBOS_LEAN_FULL_MATHLIB is set."""
    if get_bool("TRIBOS_LEAN_FULL_MATHLIB") or not _BARE_MATHLIB_RE.search(code):
        return code
    return _BARE_MATHLIB_RE.sub("\n".join(f"import {m}" for m in DEFAULT_MATHLIB_IMPORTS), code, count=1)


_IMPORT_LINE_RE = re.compile(r"^[ \t]*import[ \t]+(Mathlib(?:\.[A-Za-z0-9_']+)+)[ \t]*$", re.M)


def drop_missing_imports(code: str, project_dir: str | None) -> tuple[str, list[str]]:
    """Remove `import Mathlib.X.Y` lines naming modules the installed Mathlib does not have.

    Models write imports of modules that were moved or retired (Mathlib.Tactic.Omega: `omega` is part of Lean core
    now). Lean then fails to load a library file that does not exist, which reads like a broken installation and is
    never repaired. Without the import the proof usually compiles; if a lemma really is missing, Lean says so in an
    ordinary error the repair loop can act on. Returns (code, dropped module names)."""
    if not project_dir:
        return code, []
    lib = os.path.join(project_dir, ".lake", "packages", "mathlib", ".lake", "build", "lib", "lean")
    if not os.path.isdir(os.path.join(lib, "Mathlib")):
        return code, []
    dropped: list[str] = []

    def keep(m: re.Match[str]) -> str:
        module = m.group(1)
        if os.path.exists(os.path.join(lib, *module.split(".")) + ".olean"):
            return m.group(0)
        dropped.append(module)
        return f"-- import {module}  (not in this Mathlib; removed)"

    return _IMPORT_LINE_RE.sub(keep, code), dropped


def _kill_tree(pid: int) -> None:
    """Kill a process and every descendant. `lake env lean` starts lean as a child: killing only lake leaves lean
    running (several GB with Mathlib loaded) and holding the output pipes open, so the caller would wait forever."""
    try:
        import psutil

        parent = psutil.Process(pid)
        procs = [*parent.children(recursive=True), parent]
    except Exception:  # noqa: BLE001 - psutil missing or the process already gone
        procs = []
    for p in procs:
        with contextlib.suppress(Exception):
            p.kill()
    # No "taskkill /T" when the process is gone: /T would kill every process whose recorded parent id equals the
    # (possibly recycled) pid, which is how unrelated servers were killed.


def _run_tree(argv: list[str], cwd: str, timeout: float) -> subprocess.CompletedProcess[str]:
    """subprocess.run with capture, except that a timeout kills the whole process tree before reading the pipes."""
    # A fixed argv of the configured checker, no shell.
    with subprocess.Popen(  # nosec B603
        # Lean writes UTF-8; the platform default (cp1252 on Windows) would garble "ℕ" in its messages.
        argv, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding="utf-8",
        errors="replace", preexec_fn=_limit_memory if os.name == "posix" else None,  # noqa: PLW1509
    ) as proc:
        try:
            stdout, stderr = proc.communicate(timeout=timeout)
        except subprocess.TimeoutExpired:
            _kill_tree(proc.pid)
            with contextlib.suppress(subprocess.TimeoutExpired):
                proc.communicate(timeout=10)
            raise
        return subprocess.CompletedProcess(argv, proc.returncode, stdout, stderr)


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

    dropped: list[str] = []
    if command["kind"] == "lake":
        code = with_default_imports(code)
        code, dropped = drop_missing_imports(code, command.get("cwd"))
    unproved = uses_unproved(code)
    with tempfile.TemporaryDirectory(prefix="tribos-lean-") as work:
        path = os.path.join(work, "Proof.lean")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(code)
        for attempt in range(ENVIRONMENT_RETRIES + 1):
            try:
                # One Lean at a time: each loads Mathlib (GBs); several at once ran the machine out of memory, and
                # Lean then reported "failed to read file" for library files, which the repair loop took for a proof
                # error.
                with _LEAN_SLOTS:
                    proc = _run_tree([*command["argv"], path], command["cwd"] or work, timeout)
            except subprocess.TimeoutExpired:
                result = {"status": "timeout", "title": STATUS_TITLES["timeout"], "messages": [],
                          "error": f"Lean did not finish within {timeout:g} s."}
                return {**result, "cached": False}
            except OSError as exc:
                return {"status": "unavailable", "title": STATUS_TITLES["unavailable"], "messages": [], "cached": False,
                        "error": f"Lean could not be started ({type(exc).__name__})."}
            output = (proc.stdout or "") + (proc.stderr or "")
            if not _ENVIRONMENT_ERROR_RE.search(output):
                break
            if attempt == ENVIRONMENT_RETRIES:
                # Never a verdict on the proof: the library could not be loaded.
                return {"status": "unavailable", "title": STATUS_TITLES["unavailable"], "messages": [], "cached": False,
                        "error": "Lean could not load its library (" + _ENVIRONMENT_ERROR_RE.search(output).group(0)[:160]
                                 + "); likely too little free memory. This says nothing about the proof."}
            time.sleep(2.0 * (attempt + 1))
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
              "unproved": unproved, "output": output.replace(path, "Proof.lean")[-4000:], "checker": command["kind"],
              "dropped_imports": dropped}
    with _CACHE_LOCK:
        _CACHE[key] = result
        while len(_CACHE) > _CACHE_SIZE:
            _CACHE.popitem(last=False)
    return {**result, "cached": False}


def clear_cache() -> None:
    with _CACHE_LOCK:
        _CACHE.clear()


__all__ = ["STATUS_TITLES", "check_lean", "clear_cache", "find_lean", "parse_messages", "uses_unproved"]
