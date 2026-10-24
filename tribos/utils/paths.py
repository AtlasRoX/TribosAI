"""
One data root for Tribos state: TRIBOS_DATA_DIR.

When TRIBOS_DATA_DIR is set, every state directory defaults to a subdirectory of it:

  memory/           clinical memory vault (TRIBOS_MEMORY_DIR wins)
  runs/             run manifests (TRIBOS_RUNS_DIR wins)
  uploads/          uploaded datasets (TRIBOS_UPLOAD_ROOT wins)
  jobs/             background-job SQLite store (TRIBOS_JOBS_DIR, then <TRIBOS_RUNS_DIR>/jobs, win)
  tool_cache/       tool-result SQLite cache (TRIBOS_TOOL_CACHE_DIR, then <TRIBOS_RUNS_DIR>/tool_cache, win)
  biomodels_cache/  downloaded BioModels / COPASI files (default: the system temp directory)

A specific variable always wins over the data root. With nothing set, every store keeps its historical
default (`<workspace>/.tribos_memory`, `.tribos_runs`, `.tribos_uploads`, `data/jobs`, ...).
"""

from __future__ import annotations

import os
from pathlib import Path

DATA_DIR_ENV = "TRIBOS_DATA_DIR"

# <workspace> = the repository root (tribos/utils/paths.py -> parents[2]).
WORKSPACE_ROOT = Path(__file__).resolve().parents[2]


def data_root() -> Path | None:
    """The configured data root (TRIBOS_DATA_DIR, `~` expanded), or None when it is not set."""
    raw = os.getenv(DATA_DIR_ENV, "").strip()
    return Path(os.path.expanduser(raw)) if raw else None


def data_dir(sub: str) -> Path | None:
    """`<TRIBOS_DATA_DIR>/<sub>`, or None when TRIBOS_DATA_DIR is not set (callers keep their default)."""
    root = data_root()
    return root / sub if root is not None else None
