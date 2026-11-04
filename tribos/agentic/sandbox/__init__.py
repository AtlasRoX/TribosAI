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

from ...config.settings import get_bool, get_int, get_str

DATASET_ID_RE = re.compile(r"^ds_[0-9a-f]{12}$")
ANALYSABLE_KINDS = ("table", "hdf5", "mat")
_LEGACY_ANALYSABLE_KINDS = ANALYSABLE_KINDS + ("h5ad",)


def sandbox_enabled() -> bool:
    """TRIBOS_SANDBOX=on by default; explicitly setting off/0/false/no disables code execution.

    Read through the settings registry, so the documented default and the runtime default cannot drift apart.
    """
    return get_bool("TRIBOS_SANDBOX")


def sandbox_timeout_s() -> int:
    """The server's wall-clock ceiling for one sandboxed execution (higher inside research_ceiling)."""
    base = get_int("TRIBOS_SANDBOX_TIMEOUT_S")
    research = _RESEARCH_TIMEOUT.get()
    return max(base, int(research)) if research else base


# A research project's experiments (exact counts to 10^6, long sweeps) need more than a chat cell's minute. Only the
# research engine raises the ceiling, for the cells it runs; every other execution keeps TRIBOS_SANDBOX_TIMEOUT_S.
_RESEARCH_TIMEOUT: contextvars.ContextVar[int | None] = contextvars.ContextVar("tribos_research_timeout", default=None)


@contextlib.contextmanager
def research_ceiling(seconds: int | None = None) -> Iterator[int]:
    """Raise the sandbox time ceiling to TRIBOS_RESEARCH_SANDBOX_TIMEOUT_S (or `seconds`) inside this block."""
    value = int(seconds or get_int("TRIBOS_RESEARCH_SANDBOX_TIMEOUT_S"))
    token = _RESEARCH_TIMEOUT.set(value)
    try:
        yield value
    finally:
        _RESEARCH_TIMEOUT.reset(token)


def sandbox_memory_mb() -> int:
    """The server's memory ceiling for one sandboxed execution."""
    return get_int("TRIBOS_SANDBOX_MEMORY_MB")


def sandbox_backend() -> str:
    """Which isolation backend runs model-written code: auto, subprocess or container."""
    return (get_str("TRIBOS_SANDBOX_BACKEND") or "auto").strip().lower()


def sandbox_image() -> str:
    """The container image the container backend runs."""
    return (get_str("TRIBOS_SANDBOX_IMAGE") or "tribos-sandbox:local").strip()


def sandbox_container_engine() -> str:
    """Which container CLI the container backend uses: auto, docker or podman."""
    return (get_str("TRIBOS_SANDBOX_CONTAINER_ENGINE") or "auto").strip().lower()


def sandbox_max_concurrency() -> int:
    """How many sandboxed cells may run at the same time."""
    return get_int("TRIBOS_SANDBOX_MAX_CONCURRENCY")


def sandbox_max_output_kb() -> int:
    """The stdout/stderr cap of one run, in KB."""
    return get_int("TRIBOS_SANDBOX_MAX_OUTPUT_KB")


def sandbox_max_disk_mb() -> int:
    """The write budget of one run, in MB."""
    return get_int("TRIBOS_SANDBOX_MAX_DISK_MB")


def sandbox_max_processes() -> int:
    """The process-count cap of one run."""
    return get_int("TRIBOS_SANDBOX_MAX_PROCESSES")


def sandbox_max_result_bytes() -> int:
    """The aggregate size cap of one run's result payload (result, tables and figures together)."""
    return get_int("TRIBOS_SANDBOX_MAX_RESULT_BYTES")


def sandbox_strict_limits() -> bool:
    """True when a run that cannot enforce its resource limits must fail instead of degrading."""
    return get_bool("TRIBOS_SANDBOX_STRICT_LIMITS")


def sandbox_allow_unisolated() -> bool:
    """True when the operator accepts running model code without an OS-level isolation boundary."""
    return get_bool("TRIBOS_SANDBOX_ALLOW_UNISOLATED")


def sagemath_enabled() -> bool:
    """Whether the SageMath tools may be offered at all."""
    return sandbox_enabled() and get_bool("TRIBOS_SANDBOX_SAGE_ENABLED")


def sagemath_timeout_s() -> int:
    """The wall-clock ceiling of one SageMath execution."""
    return get_int("TRIBOS_SANDBOX_SAGE_TIMEOUT_S")


def sagemath_allow_wsl() -> bool:
    """Whether SageMath may run inside WSL, where the Python-level guards do not apply."""
    return get_bool("TRIBOS_SANDBOX_SAGE_ALLOW_WSL")


@dataclass(frozen=True)
class SandboxScope:
    user_id: str
    dataset_ids: frozenset[str] = field(default_factory=frozenset)
    # dataset id -> owner, for project files other members shared (readable through project membership)
    owners: dict[str, str] = field(default_factory=dict)
    project_id: str | None = None
    task_id: str | None = None
    run_id: str | None = None

    def owner_of(self, dataset_id: str) -> str:
        return self.owners.get(dataset_id, self.user_id)


_SCOPE: contextvars.ContextVar[SandboxScope | None] = contextvars.ContextVar("tribos_sandbox_scope", default=None)


@contextlib.contextmanager
def bound_scope(
    user_id: str,
    dataset_ids: Iterable[str],
    owners: dict[str, str] | None = None,
    project_id: str | None = None,
    task_id: str | None = None,
    run_id: str | None = None,
) -> Iterator[SandboxScope]:
    """Bind the datasets one run may analyse for the duration of the block (copied into worker threads)."""
    ids = frozenset(i for i in dataset_ids if DATASET_ID_RE.match(str(i)))
    scope = SandboxScope(
        user_id=str(user_id),
        dataset_ids=ids,
        owners={k: str(v) for k, v in (owners or {}).items() if k in ids},
        project_id=project_id,
        task_id=task_id,
        run_id=run_id,
    )
    token = _SCOPE.set(scope)
    try:
        yield scope
    finally:
        _SCOPE.reset(token)


def current_scope() -> SandboxScope | None:
    return _SCOPE.get()


# Whether this request may execute model-written code at all. The frontend option ("Allow code analysis on
# datasets") sets it to False; the gateway refuses every execution path when it is False, so a direct tool call
# cannot slip past the planner's filter. Context vars propagate into the worker threads the registry tools run in,
# the same way bound_scope does.
_EXECUTION_ALLOWED: contextvars.ContextVar[bool] = contextvars.ContextVar(
    "tribos_sandbox_execution_allowed", default=True
)


@contextlib.contextmanager
def execution_permitted(allowed: bool = True) -> Iterator[bool]:
    """Allow or forbid model-written execution for the duration of the block (copied into worker threads)."""
    token = _EXECUTION_ALLOWED.set(bool(allowed))
    try:
        yield bool(allowed)
    finally:
        _EXECUTION_ALLOWED.reset(token)


def execution_permitted_now() -> bool:
    """False when this request forbids server-side Python and SageMath execution."""
    return bool(_EXECUTION_ALLOWED.get())


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
    resolved, store_errors = [], []
    for owner in dict.fromkeys(scope.owner_of(i) for i in allowed):
        found, missing = store.resolve_for_user(owner, [i for i in allowed if scope.owner_of(i) == owner])
        resolved.extend(found)
        store_errors.extend(missing)
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
    "execution_permitted",
    "execution_permitted_now",
    "resolve_inputs",
    "safe_input_name",
    "sagemath_allow_wsl",
    "sagemath_enabled",
    "sagemath_timeout_s",
    "sandbox_allow_unisolated",
    "sandbox_backend",
    "sandbox_enabled",
    "sandbox_image",
    "sandbox_max_concurrency",
    "sandbox_max_disk_mb",
    "sandbox_max_output_kb",
    "sandbox_max_processes",
    "sandbox_max_result_bytes",
    "sandbox_memory_mb",
    "sandbox_strict_limits",
    "sandbox_timeout_s",
]
