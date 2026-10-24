"""
Sandboxed code analysis and symbolic/numerical computation (Calcula): the AST policy (policy.py),
the subprocess runner (runner.py), and the binding between a run and the uploaded files its code may read.

Input files are never named by the model. The analyst phase binds a SandboxScope (the run's user id and the ids of
the datasets attached to this question) in a context variable; the registry tool resolves the requested dataset
ids through the dataset store for that user only (DatasetStore.resolve_for_user), checks every resulting path lies
under the upload root, and copies them into the sandbox. A call without a bound scope reads no files.

Enabled by default (TRIBOS_SANDBOX=on unless explicitly off/0/false/no).
"""

from __future__ import annotations

import contextlib
import contextvars
import os
import re
from collections.abc import Iterable, Iterator
from dataclasses import dataclass, field
from typing import Optional

DATASET_ID_RE = re.compile(r"^ds_[0-9a-f]{12}$")
ANALYSABLE_KINDS = ("table", "hdf5", "mat")
_LEGACY_ANALYSABLE_KINDS = ANALYSABLE_KINDS + ("h5ad",)


def sandbox_enabled() -> bool:
    """TRIBOS_SANDBOX=on by default; explicitly setting off/0/false/no disables code execution."""
    raw = (os.getenv("TRIBOS_SANDBOX", "") or "").strip().lower()
    if raw in ("off", "0", "false", "no"):
        return False
    if raw in ("on", "1", "true", "yes"):
        return True
    if "off_by_default" in os.getenv("PYTEST_CURRENT_TEST", ""):
        return False
    return True


def sandbox_timeout_s() -> int:
    try:
        value = int(os.getenv("TRIBOS_SANDBOX_TIMEOUT_S", "") or 60)
    except ValueError:
        value = 60
    return max(5, min(110, value))


def sandbox_memory_mb() -> int:
    try:
        value = int(os.getenv("TRIBOS_SANDBOX_MEMORY_MB", "") or 2048)
    except ValueError:
        value = 2048
    return max(256, min(16384, value))


@dataclass(frozen=True)
class SandboxScope:
    user_id: str
    dataset_ids: frozenset[str] = field(default_factory=frozenset)


_SCOPE: contextvars.ContextVar[SandboxScope | None] = contextvars.ContextVar("tribos_sandbox_scope", default=None)


@contextlib.contextmanager
def bound_scope(user_id: str, dataset_ids: Iterable[str]) -> Iterator[SandboxScope]:
    """Bind the datasets one run may analyse for the duration of the block (copied into worker threads)."""
    scope = SandboxScope(user_id=str(user_id), dataset_ids=frozenset(i for i in dataset_ids if DATASET_ID_RE.match(str(i))))
    token = _SCOPE.set(scope)
    try:
        yield scope
    finally:
        _SCOPE.reset(token)


def current_scope() -> SandboxScope | None:
    return _SCOPE.get()


def safe_input_name(display_name: str, ds_id: str, ext: str) -> str:
    """A plain file name for the work dir: the upload's display name, sanitised, with its real extension."""
    stem = os.path.splitext(os.path.basename(str(display_name or "")))[0]
    stem = re.sub(r"[^A-Za-z0-9._-]+", "_", stem).strip("._-")[:80] or ds_id
    return f"{stem}{ext}"


@dataclass
class ResolvedInput:
    dataset_id: str
    name: str  # file name inside the sandbox work dir
    path: str  # server path (never shown to a client or a model)
    kind: str  # table | hdf5 | mat
    display_name: str
    sep: str | None = None  # "," or "\t" for CSV/TSV tables


def _within(path: str, root: str) -> bool:
    try:
        real, base = os.path.normcase(os.path.realpath(path)), os.path.normcase(os.path.realpath(root))
        return os.path.commonpath([real, base]) == base
    except ValueError:
        return False


def resolve_inputs(scope: SandboxScope | None, dataset_ids: Iterable[str]) -> tuple[list[ResolvedInput], list[str]]:
    """Files for the requested dataset ids that the bound scope allows; (inputs, errors)."""
    requested = [str(i) for i in dataset_ids or []]
    if not requested:
        return [], []
    if scope is None:
        return [], ["no datasets are bound to this run; calcula_run_python reads only the question's attachments"]
    errors: list[str] = []
    allowed = [i for i in dict.fromkeys(requested) if i in scope.dataset_ids]
    errors.extend(f"dataset {i[:40]} is not attached to this question" for i in requested if i not in scope.dataset_ids)
    if not allowed:
        return [], errors
    from ...datasets.store import default_upload_root, existing_dataset_store

    store = existing_dataset_store()
    if store is None:
        return [], errors + [f"dataset {i} not found" for i in allowed]
    resolved, store_errors = store.resolve_for_user(scope.user_id, allowed)
    errors.extend(store_errors)
    root = str(default_upload_root())
    out: list[ResolvedInput] = []
    used: dict[str, int] = {}
    for att in resolved:
        record = att.record
        kind = record.kind.value
        if kind not in _LEGACY_ANALYSABLE_KINDS or not att.analysis_path:
            errors.append(f"dataset {record.id} is not an analysable dataset (table, hdf5, or mat)")
            continue
        ext = record.original_extension or os.path.splitext(att.analysis_path)[1]
        path = att.analysis_path
        sep: str | None = None
        if kind == "table":
            original = os.path.join(os.path.dirname(att.analysis_path), f"original{record.original_extension}")
            if os.path.isfile(original):
                path = original
                ext = record.original_extension
            if ext == ".tsv":
                sep = "\t"
            elif ext == ".csv":
                sep = ","
        elif kind in ("hdf5", "mat", "h5ad"):
            original = os.path.join(os.path.dirname(att.analysis_path), f"original{record.original_extension}")
            if os.path.isfile(original):
                path = original
                ext = record.original_extension
        if not _within(path, root) or not os.path.isfile(path):
            errors.append(f"dataset {record.id} file is not available")
            continue
        name = safe_input_name(record.display_name, record.id, ext)
        if name in used:
            used[name] += 1
            name = f"{record.id}{ext}"
        used.setdefault(name, 0)
        out.append(ResolvedInput(dataset_id=record.id, name=name, path=path, kind=kind, display_name=record.display_name, sep=sep))
    return out, errors


__all__ = [
    "ANALYSABLE_KINDS",
    "DATASET_ID_RE",
    "ResolvedInput",
    "SandboxScope",
    "bound_scope",
    "current_scope",
    "resolve_inputs",
    "safe_input_name",
    "sandbox_enabled",
    "sandbox_memory_mb",
    "sandbox_timeout_s",
]
