#!/usr/bin/env python3
"""
The sandbox boundary gate: prove that model-written code cannot reach the host, the network or the server's
credentials, and that a run leaves nothing behind.

This is a release gate, not a unit test. It starts the real container backend against the real image and
asserts the boundary from the outside, the way an attacker would try it:

    docker build -f docker/sandbox.Dockerfile -t tribos-sandbox:local .
    uv run python scripts/verify_sandbox_boundary.py

Exit code 0 means the boundary held. Exit code 1 means it did not, and the output says which check failed.

Without a container runtime the script reports that the boundary could not be verified and exits 2, so a CI
job that requires the gate fails rather than passing silently.
"""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from tribos.agentic.sandbox.backends import ExecutionRequest  # noqa: E402
from tribos.agentic.sandbox.container import ContainerBackend, container_available  # noqa: E402

# A marker file the host creates and the code must not be able to read.
HOST_MARKER = "sandbox-boundary-marker"


class Report:
    """The outcome of the gate: one line per check, and a verdict."""

    def __init__(self) -> None:
        self.checks: list[tuple[str, bool, str]] = []

    def check(self, name: str, ok: bool, detail: str = "") -> bool:
        self.checks.append((name, ok, detail))
        marker = "PASS" if ok else "FAIL"
        print(f"[{marker}] {name}" + (f": {detail}" if detail else ""))
        return ok

    @property
    def failed(self) -> list[tuple[str, bool, str]]:
        return [c for c in self.checks if not c[1]]

    def verdict(self) -> int:
        failed = self.failed
        print()
        if failed:
            print(f"The sandbox boundary did not hold: {len(failed)} check(s) failed.")
            for name, _ok, detail in failed:
                print(f"  - {name}: {detail}")
            return 1
        print(f"The sandbox boundary held: {len(self.checks)} checks passed.")
        return 0


def _run(code: str, timeout_s: float = 60.0) -> dict:
    return ContainerBackend().run(ExecutionRequest(code=code, timeout_s=timeout_s))


def main() -> int:
    print("Tribos sandbox boundary gate")
    print("=" * 60)

    available, reason = container_available(refresh=True)
    if not available:
        print(f"[SKIP] the container backend is not available: {reason}")
        print("The boundary could not be verified. Build the image and install a runtime first:")
        print("  docker build -f docker/sandbox.Dockerfile -t tribos-sandbox:local .")
        return 2

    report = Report()

    # --- the code runs at all -------------------------------------------------------------------------
    result = _run("result = 6 * 7\n")
    report.check(
        "the container runs model-written code",
        result.get("status") == "ok" and result.get("result") == 42,
        f"status={result.get('status')} result={result.get('result')}",
    )

    # --- no network -----------------------------------------------------------------------------------
    result = _run("import socket\nsocket.socket()\nresult = 1\n")
    report.check(
        "the code has no network route",
        result.get("status") != "ok",
        f"status={result.get('status')}",
    )

    result = _run("import socket\nsocket.getaddrinfo('example.com', 80)\nresult = 1\n")
    report.check(
        "the code cannot resolve a name",
        result.get("status") != "ok",
        f"status={result.get('status')}",
    )

    # --- no host filesystem ---------------------------------------------------------------------------
    # The check is not "can it open /etc/passwd": inside the container that is the container's own passwd
    # file, and the AST policy blocks absolute paths anyway, so such a test would pass for the wrong reason.
    # The real question is whether a file that exists ONLY on the host is reachable from inside. A marker
    # file is created on the host, outside any run directory, and the code tries to read it by its path.
    marker_path = Path(tempfile.gettempdir()) / f"{HOST_MARKER}.txt"
    marker_path.write_text("host-only-marker", encoding="utf-8")
    try:
        result = _run(f"result = open({str(marker_path)!r}).read()\n")
        report.check(
            "the code cannot read a host-only file",
            result.get("status") != "ok" and "host-only-marker" not in str(result.get("result")),
            f"status={result.get('status')}",
        )

        # And a relative path must not escape the sandbox either.
        result = _run("result = open('../host-only-marker.txt').read()\n")
        report.check(
            "the code cannot escape its work directory",
            result.get("status") != "ok" and "host-only-marker" not in str(result.get("result")),
            f"status={result.get('status')}",
        )
    finally:
        marker_path.unlink(missing_ok=True)

    # --- the code cannot rewrite its own policy ------------------------------------------------------------------------
    # The bootstrap, the config and the submitted code cell are mounted read-only, so the code cannot rewrite
    # the policy it is checked against, nor the cell it is running from.
    result = _run(
        "import os, glob\n"
        "hits = [p for p in glob.glob('/io/*') if os.path.exists(p)]\n"
        "written = []\n"
        "for p in hits:\n"
        "    try:\n"
        "        open(p, 'a').write('x')\n"
        "        written.append(p)\n"
        "    except OSError:\n"
        "        pass\n"
        "result = written\n"
    )
    report.check(
        "the code cannot rewrite the channel it was given",
        result.get("status") == "ok" and result.get("result") == [],
        f"status={result.get('status')} written={result.get('result')}",
    )

    # --- no secrets -----------------------------------------------------------------------------------
    os.environ["TRIBOS_BOUNDARY_TEST_SECRET"] = "must-never-appear-inside"
    try:
        result = _run("import os\nresult = os.environ.get('TRIBOS_BOUNDARY_TEST_SECRET', '')\n")
    finally:
        os.environ.pop("TRIBOS_BOUNDARY_TEST_SECRET", None)
    report.check(
        "no host secret reaches the container",
        "must-never-appear-inside" not in str(result.get("result")),
        f"result={str(result.get('result'))[:60]}",
    )

    result = _run("import os\nresult = sorted(os.environ)\n")
    env_names = result.get("result") if isinstance(result.get("result"), list) else []
    report.check(
        "the container environment is minimal",
        set(env_names) <= {
            "PATH",
            "PYTHONHASHSEED",
            "MPLBACKEND",
            "TMPDIR",
            "HOME",
            "LANG",
            "PYTHONIOENCODING",
            "PYTHONDONTWRITEBYTECODE",
            "MPLCONFIGDIR",
            "HOSTNAME",
            "PWD",
            "SHLVL",
            "_",
            "PYTHONHOME",
            "PYTHONPATH",
            "LC_ALL",
            "TZ",
            "TMP",
            "TEMP",
            "PYTHONNOUSERSITE",
        },
        f"environment={env_names}",
    )

    # --- no privileges -------------------------------------------------------------------------------
    result = _run("import os\nresult = os.getuid()\n")
    report.check(
        "the code runs as a non-root user",
        result.get("result") not in (0, None),
        f"uid={result.get('result')}",
    )

    # --- the process cap -----------------------------------------------------------------------------
    result = _run("import subprocess, sys\nsubprocess.Popen([sys.executable, '-c', 'pass'])\nresult = 1\n")
    report.check(
        "the process cap is enforced",
        result.get("status") != "ok",
        f"status={result.get('status')}",
    )

    # --- the memory cap ------------------------------------------------------------------------------
    result = _run("x = bytearray(2000 * 1024 * 1024)\nresult = len(x)\n", timeout_s=90)
    report.check(
        "the memory cap is enforced",
        result.get("status") != "ok",
        f"status={result.get('status')}",
    )

    # --- the timeout ---------------------------------------------------------------------------------
    started = time.perf_counter()
    result = _run("import time\ntime.sleep(600)\n", timeout_s=6)
    elapsed = time.perf_counter() - started
    report.check(
        "a hanging run is stopped",
        result.get("status") == "timeout" and elapsed < 60,
        f"status={result.get('status')} elapsed={elapsed:.1f}s",
    )

    # --- nothing is left behind ----------------------------------------------------------------------
    before = {p for p in os.listdir(tempfile.gettempdir()) if p.startswith("tribos-sbx-")}
    _run("result = 1\n")
    after = {p for p in os.listdir(tempfile.gettempdir()) if p.startswith("tribos-sbx-")}
    report.check(
        "a run leaves no directory behind",
        after <= before,
        f"left={sorted(after - before)}",
    )

    # --- no orphan processes -------------------------------------------------------------------------
    if os.name == "posix":
        listing = subprocess.run(
            ["ps", "-eo", "args"],
            capture_output=True,
            text=True,
            timeout=20,
        ).stdout
        orphans = [line for line in listing.splitlines() if "tribos-sbx-" in line and "ps -eo" not in line]
        report.check(
            "a run leaves no orphan process behind",
            not orphans,
            f"orphans={orphans[:3]}",
        )

    return report.verdict()


if __name__ == "__main__":
    raise SystemExit(main())
