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
import secrets
import shutil

# subprocess runs only the configured Lean executable, with a list argv and no shell.
import subprocess  # nosec B404
import sys
import tempfile
import threading
import time
from collections import OrderedDict
from typing import Any, cast

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
# Any `axiom` declaration, wherever it stands: after attributes (`@[simp] axiom`), modifiers, other commands on the
# same line, or inside a namespace. Model-written code never needs one: Lean's own axioms are in the library already.
_AXIOM_RE = re.compile(r"(?<![\w.'«])axiom(?![\w'»])\s+([^\s:({\[]+)")
# The only axioms a kernel-checked proof may rest on: Lean's three standard axioms (Mathlib adds none). Checked from
# the kernel's own record (`#print axioms`), never by reading names in the source: a model-declared `axiom choice`
# or `Foo.propext` once passed a name allowlist here and certified 2 + 2 = 5 (audit AUDIT-101).
STANDARD_AXIOMS = frozenset({"propext", "Classical.choice", "Quot.sound"})
_COMMENT_RE = re.compile(r"/-.*?-/|--[^\n]*", re.S)
# Top-level declarations whose axioms are audited, and the scopes that qualify their names.
_ITEM_RE = re.compile(
    r"(?m)^[ \t]*(?:(?P<scope>namespace|section|end)\b[ \t]*(?P<sname>[^\s]*)"
    r"|(?:@\[[^\]]*\]\s*)*(?:(?:private|protected|noncomputable|nonrec)\s+)*(?:theorem|lemma)\s+(?P<name>[^\s:({\[]+))")
_EXAMPLE_RE = re.compile(r"(?m)^([ \t]*(?:@\[[^\]]*\]\s*)*)example(?=[\s({\[:])")
_AXIOM_REPORT_RE = re.compile(r"'(?P<name>[^']+)' (?:depends on axioms: \[(?P<axioms>[^\]]*)\]|does not depend on any axioms)")
AUDIT_MARKER = "-- Tribos axiom audit: the axioms each theorem rests on, as recorded by the kernel"


def declared_theorems(code: str) -> list[str]:
    """Fully qualified names of the theorems and lemmas the code declares (namespaces applied, `_root_.` honoured)."""
    body = _COMMENT_RE.sub(lambda m: "\n" * m.group(0).count("\n"), code)
    scopes: list[tuple[str, str]] = []
    names: list[str] = []
    for m in _ITEM_RE.finditer(body):
        if m.group("scope"):
            if m.group("scope") == "end":
                if scopes:
                    scopes.pop()
            else:
                scopes.append((m.group("scope"), m.group("sname") or ""))
            continue
        name = m.group("name")
        if name.startswith("_root_."):
            names.append(name[len("_root_."):])
        else:
            names.append(".".join([s for kind, s in scopes if kind == "namespace" and s] + [name]))
    return list(dict.fromkeys(names))


def with_axiom_audit(code: str, nonce: str = "") -> tuple[str, list[tuple[str, int]]]:
    """The code to compile: each top-level `example` named (an example leaves no constant to audit), then a marker
    carrying `nonce` and one `#print axioms` per theorem. Returns (code, [(theorem, line of its audit command)]).

    Lean prints the reports as plain lines. Only reports after the marker count: the model's code cannot know the
    nonce, so it can neither print a fake report after the marker nor hide the real ones (`#exit` before the audit
    leaves no marker, and the proof fails as unaudited)."""
    count = 0

    def name_example(m: re.Match[str]) -> str:
        nonlocal count
        count += 1
        return f"{m.group(1)}theorem tribos_example_{count}"

    named = _EXAMPLE_RE.sub(name_example, code).rstrip("\n")
    names = declared_theorems(named)
    if not names:
        return named + "\n", []
    first = named.count("\n") + 5  # the line of the first #print below
    audit = "\n".join(f"#print axioms {n}" for n in names)
    marker = f'#eval IO.println "TRIBOS_AXIOM_AUDIT {nonce}"'
    return f"{named}\n\n{AUDIT_MARKER}\n{marker}\n{audit}\n", [(n, first + i) for i, n in enumerate(names)]


def axiom_reports(output: str, audited: list[tuple[str, int]], nonce: str = "") -> dict[str, list[str] | None]:
    """{theorem: the axioms the kernel reports for it}, read in command order after the audit marker; None for a
    theorem whose report is missing."""
    marker = f"TRIBOS_AXIOM_AUDIT {nonce}"
    at = output.rfind(marker)
    reports = list(_AXIOM_REPORT_RE.finditer(output[at + len(marker):])) if at >= 0 else []
    out: dict[str, list[str] | None] = {}
    for i, (name, _line) in enumerate(audited):
        if i < len(reports):
            out[name] = [a.strip() for a in (reports[i].group("axioms") or "").split(",") if a.strip()]
        else:
            out[name] = None
    return out


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
    # Every axiom declaration, whatever its name: `axiom choice : 2 + 2 = 5` is a new axiom, not Classical.choice.
    found += sorted({f"axiom {m.group(1).strip()}" for m in _AXIOM_RE.finditer(body)})
    # Escape hatches that make the kernel trust compiled code instead of checking a proof term (reward hacking in
    # proof search; docs/plans/tribos-research-upgrade-plan.md 2.1): not a kernel-checked proof.
    for pattern, label in ((r"\bnative_decide\b", "native_decide"), (r"\bimplemented_by\b", "implemented_by"),
                           (r"@\[\s*extern\b", "@[extern]"), (r"(?m)^\s*(?:private\s+|protected\s+)?unsafe\b", "unsafe"),
                           (r"\bLean\.ofReduceBool\b", "Lean.ofReduceBool")):
        if re.search(pattern, body):
            found.append(label)
    return sorted(found)


def _limit_memory() -> None:  # pragma: no cover - runs in the child on POSIX
    # The platform check is for the type checker (resource is POSIX-only): this function is the preexec_fn only
    # where os.name == "posix", so the check always holds when it runs.
    if sys.platform != "win32":
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
    nonce = secrets.token_hex(8)
    checked, audited = with_axiom_audit(code, nonce)
    with tempfile.TemporaryDirectory(prefix="tribos-lean-") as work:
        path = os.path.join(work, "Proof.lean")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(checked)
        for attempt in range(ENVIRONMENT_RETRIES + 1):
            try:
                # One Lean at a time: each loads Mathlib (GBs); several at once ran the machine out of memory, and
                # Lean then reported "failed to read file" for library files, which the repair loop took for a proof
                # error.
                with _LEAN_SLOTS:
                    proc = _run_tree([*command["argv"], path], command["cwd"] or work, timeout)
            except subprocess.TimeoutExpired:
                result: dict[str, Any] = {"status": "timeout", "title": STATUS_TITLES["timeout"], "messages": [],
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
                        "error": "Lean could not load its library ("
                                 + cast(re.Match[str], _ENVIRONMENT_ERROR_RE.search(output)).group(0)[:160]
                                 + "); likely too little free memory. This says nothing about the proof."}
            time.sleep(2.0 * (attempt + 1))
    output = (proc.stdout or "") + (proc.stderr or "")
    messages = parse_messages(output.replace(path, "Proof.lean"))
    errors = [m for m in messages if m["severity"] == "error"]
    sorry_warning = any("sorry" in m["message"] for m in messages if m["severity"] == "warning")
    reports = axiom_reports(output.replace(path, "Proof.lean"), audited, nonce)
    extra = {n: sorted(set(a) - STANDARD_AXIOMS) for n, a in reports.items() if a is not None and set(a) - STANDARD_AXIOMS}
    audit_lines = {line for _, line in audited}
    if proc.returncode != 0 or errors:
        first = errors[0] if errors else None
        if first is not None and first["line"] in audit_lines:
            error = f"The axiom check could not run ({first['message'][:200]})."
        else:
            error = first["message"] if first else f"Lean exited with code {proc.returncode}."
        status = "failed"
    elif unproved or sorry_warning:
        status, error = "failed", f"The proof is incomplete: it uses {', '.join(unproved) or 'sorry'}."
    elif not audited:
        status, error = "failed", "The code states no theorem, lemma or example, so it proves nothing."
    elif any(a is None for a in reports.values()):
        missing = [n for n, a in reports.items() if a is None]
        status, error = "failed", f"Lean reported no axioms for {', '.join(missing[:5])}, so the proof could not be audited."
    elif extra:
        sorry_only = all(set(a) <= {"sorryAx"} for a in extra.values())
        listed = "; ".join(f"{n}: {', '.join(a)}" for n, a in list(extra.items())[:5])
        status, error = "failed", (f"The proof is incomplete: it uses sorry ({listed})." if sorry_only else
                                   f"The proof rests on axioms beyond Lean's standard three ({listed}).")
    else:
        status, error = "verified", None
    # The audit's own reports are in `axioms`; the messages shown to the reader are the proof's.
    messages = [m for m in messages if m["line"] not in audit_lines or m["severity"] == "error"]
    result = {"status": status, "title": STATUS_TITLES[status], "messages": messages[:50], "error": error,
              "unproved": unproved, "axioms": reports, "output": output.replace(path, "Proof.lean")[-4000:],
              "checker": command["kind"], "dropped_imports": dropped}
    with _CACHE_LOCK:
        _CACHE[key] = result
        while len(_CACHE) > _CACHE_SIZE:
            _CACHE.popitem(last=False)
    return {**result, "cached": False}


def clear_cache() -> None:
    with _CACHE_LOCK:
        _CACHE.clear()


__all__ = ["STANDARD_AXIOMS", "STATUS_TITLES", "axiom_reports", "check_lean", "clear_cache", "declared_theorems",
           "find_lean", "parse_messages", "uses_unproved", "with_axiom_audit"]
