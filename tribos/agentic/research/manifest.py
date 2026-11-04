"""What a thesis was produced with: the record another researcher needs to reproduce or audit it (audit AUDIT-110).

The bundle already holds each finding's code, the separate re-implementation and the Lean sources. This adds the
environment those ran in: the Tribos version and commit, Python and the scientific libraries, the Lean toolchain and
Mathlib revision, the research and replication models, the sandbox backend and limits, and the sources with the time
they were retrieved. Model-written parts (plan, judgements, prose) are not reproducible bit for bit; the manifest says
so, together with what the automatic checks do and do not cover.
"""

from __future__ import annotations

import json
import os
import platform
import subprocess  # nosec B404 - runs `git rev-parse` with a fixed argument list, no shell
import sys
import time
from importlib import metadata
from pathlib import Path
from typing import Any

LIBRARIES = ("numpy", "scipy", "sympy", "mpmath", "pandas", "matplotlib", "statsmodels", "networkx", "pint", "h5py",
             "scikit-learn")

LIMITS_NOTE = (
    "The plan, the judgements and the prose of the chapters are written by a language model and are not reproducible "
    "bit for bit. Automatic checks cover: every number in the chapters must appear in the evidence, and a number "
    "attached to a different quantity than the one it is the value of is flagged; verdicts on deliverables and "
    "hypotheses need findings of their own tests at the required level; a Lean proof counts only when the kernel "
    "reports no axioms beyond Lean's standard three. The reasoning in the prose is not checked."
)


def _version(name: str) -> str | None:
    try:
        return metadata.version(name)
    except metadata.PackageNotFoundError:
        return None


def _git_commit() -> str | None:
    root = Path(__file__).resolve().parents[3]
    if not (root / ".git").exists():
        return None
    try:
        out = subprocess.run(["git", "rev-parse", "HEAD"], cwd=root, capture_output=True, text=True, timeout=10,  # nosec B603 B607
                             check=False)
    except (OSError, subprocess.SubprocessError):
        return None
    sha = (out.stdout or "").strip()
    return sha if len(sha) == 40 else None


def _lean() -> dict[str, Any] | None:
    from ...config.settings import get_str

    project = str(get_str("TRIBOS_LEAN_PROJECT") or "").strip()
    if not project or not os.path.isdir(project):
        return None
    info: dict[str, Any] = {}
    toolchain = Path(project) / "lean-toolchain"
    if toolchain.is_file():
        info["toolchain"] = toolchain.read_text(encoding="utf-8").strip()
    manifest = Path(project) / "lake-manifest.json"
    if manifest.is_file():
        try:
            packages = json.loads(manifest.read_text(encoding="utf-8")).get("packages") or []
            info["packages"] = {str(p.get("name")): str(p.get("rev") or "")[:40] for p in packages if p.get("name")}
        except (ValueError, OSError):
            pass
    return info or None


def _sandbox() -> dict[str, Any]:
    try:
        from ..sandbox import sandbox_memory_mb, sandbox_timeout_s
        from ..sandbox.gateway import isolation_status
        from ..sandbox.policy import ALLOWED_MODULE_ROOTS

        return {**isolation_status(), "timeout_s": sandbox_timeout_s(), "memory_mb": sandbox_memory_mb(),
                "allowed_modules": sorted(ALLOWED_MODULE_ROOTS)}
    except Exception as exc:  # noqa: BLE001 - the manifest never fails the thesis
        return {"error": type(exc).__name__}


def environment_manifest(campaign: dict[str, Any], refs: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """The manifest saved with the thesis and written into the bundle as manifest.json."""
    from ...config.settings import get_str
    from ...utils.llm.llm_factory import DEFAULT_ORCHESTRATOR_MODEL

    review = campaign.get("review") or {}
    retrieved = review.get("finished_at") or review.get("updated_at")
    return {
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "research_id": campaign.get("campaign_id"),
        "software": {"tribos": _version("tribos"), "commit": _git_commit(), "python": sys.version.split()[0],
                     "platform": platform.platform()},
        "libraries": {name: _version(name) for name in LIBRARIES},
        "lean": _lean(),
        "models": {"research": campaign.get("model") or DEFAULT_ORCHESTRATOR_MODEL,
                   "replication": str(get_str("TRIBOS_RESEARCH_REPLICATION_MODEL") or "").strip() or "same as research"},
        "sandbox": _sandbox(),
        "randomness": "Sandbox cells choose their own seeds; a cell that draws random numbers without a seed is not "
                      "reproducible to the digit (its code is in the bundle).",
        "sources": [{"title": r.get("title"), "url": r.get("url"),
                     "retrieved_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(float(retrieved))) if retrieved else None}
                    for r in (refs or [])[:80]],
        "limits": LIMITS_NOTE,
    }


def manifest_markdown(manifest: dict[str, Any]) -> str:
    """A short summary for the run record."""
    sw = manifest.get("software") or {}
    libs = ", ".join(f"{k} {v}" for k, v in (manifest.get("libraries") or {}).items() if v)
    lean = manifest.get("lean") or {}
    mathlib = (lean.get("packages") or {}).get("mathlib")
    sandbox = manifest.get("sandbox") or {}
    lines = [
        f"Software: Tribos {sw.get('tribos') or '?'}" + (f" (commit `{sw['commit'][:12]}`)" if sw.get("commit") else "")
        + f", Python {sw.get('python')}, {sw.get('platform')}.",
        f"Libraries: {libs}.",
    ]
    if lean:
        lines.append(f"Lean: {lean.get('toolchain') or '?'}" + (f", Mathlib `{mathlib[:12]}`" if mathlib else "") + ".")
    models = manifest.get("models") or {}
    lines.append(f"Models: research {models.get('research')}; replication {models.get('replication')}.")
    if sandbox and "error" not in sandbox:
        lines.append(f"Sandbox: {sandbox.get('backend')} backend"
                     + (" (OS-isolated)" if sandbox.get("os_isolated") else " (not OS-isolated)")
                     + f", {sandbox.get('timeout_s')} s and {sandbox.get('memory_mb')} MB per cell.")
    lines += ["", f"Limits of the automatic checks: {manifest.get('limits')}",
              "", "The full record is `manifest.json` in the reproducibility bundle."]
    return "\n".join(lines)
