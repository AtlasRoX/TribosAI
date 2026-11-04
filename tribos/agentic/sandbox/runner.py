"""
Run one cell of model-written computation or data analysis code in a separate, constrained Python process.

Layers (after the AST policy in policy.py), following the CodeAct action loop (Wang et al., ICML 2024,
arXiv:2402.01030):

1. A fresh temporary directory per run: work/ (the child's cwd, holding read-only copies of the input files only),
   io/ (bootstrap, code, config, captured output) and tmp/ (TEMP for libraries). Everything is deleted afterwards.
2. `sys.executable -I` (isolated mode: no PYTHON* variables, no user site, the script dir is not on sys.path;
   `-S` is not used because the scientific stack lives in site-packages).
3. An environment scrubbed to an allowlist (PATH, SYSTEMROOT/WINDIR, TEMP/TMP, PYTHONHASHSEED and the
   thread/backend settings the runner sets itself), so API keys and tokens never reach the child.
4. A bootstrap that, before user code runs: applies resource limits (POSIX RLIMIT_AS/CPU/NOFILE/FSIZE; on Windows
   a Job Object with a per-process memory, CPU-time and active-process limit, best effort), replaces
   socket.socket/create_connection/getaddrinfo with raising stubs, selects the matplotlib Agg backend, caps
   stdout/stderr, and executes the code with a restricted builtins dict (allowlisted __import__, read-only open()
   inside the work dir, getattr that refuses dunder and banned names, no eval/exec/compile/vars/globals).
5. A wall-clock timeout that kills the whole process tree (taskkill /T on Windows, the process group on POSIX).

The code's `result` variable (JSON-serialisable, else its repr), a `tables` dict of DataFrames and up to three open
matplotlib figures (PNG, base64) are returned. None of this is a security boundary against a determined attacker;
see docs/agentic/sandbox-security.md for the threat model and the container setup production should use.
"""

from __future__ import annotations

import json
import logging
import os
import re
import secrets
import shutil
import stat
import subprocess
import sys
import tempfile
import threading
import time
from typing import Any

from .policy import (
    ALLOWED_MODULE_ROOTS,
    BANNED_ATTRIBUTES,
    BANNED_CALLS,
    BANNED_MODULES,
    BANNED_NAMES,
    READER_FUNCTIONS,
    READER_PATH_KWARGS,
    check_code,
    safe_relative_path,
)
from .process import (
    STDERR_TAIL_BYTES,
    allowlisted_env,
    dir_size_bytes,
    kill_tree,
    process_group_kwargs,
    read_capped,
    rmtree,
)

logger = logging.getLogger(__name__)

MAX_FIGURES = int(os.getenv("TRIBOS_SANDBOX_MAX_FIGURES", "6"))
MAX_TABLES = 5
MAX_TABLE_ROWS = 50
MAX_FIGURE_BYTES = int(os.getenv("TRIBOS_SANDBOX_MAX_FIGURE_BYTES", "3500000"))
_INPUT_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,120}$")
# Kept for backwards compatibility: the allowlist itself now lives in process.py.
_ENV_ALLOWLIST = ("PATH", "SYSTEMROOT", "SystemRoot", "WINDIR", "PATHEXT")

# How long a run waits for a free sandbox slot before it is refused as busy.
queue_timeout_s = 30.0
# The semaphore bounds how many sandboxed cells may run at once, so N cells cannot multiply the memory limit.
_RUN_SLOTS = threading.BoundedSemaphore(max(1, int(os.getenv("TRIBOS_SANDBOX_MAX_CONCURRENCY", "2"))))


def _under_test() -> bool:
    """True while a pytest test is running (the only place the policy escape hatch may be used)."""
    return bool(os.getenv("PYTEST_CURRENT_TEST"))


def run_semaphore() -> threading.BoundedSemaphore:
    """The shared semaphore that bounds concurrent sandboxed runs."""
    return _RUN_SLOTS

_BOOTSTRAP = r'''
import base64 as _base64
import builtins as _builtins
import io as _io
import json as _json
import math as _math
import os as _os
import sys as _sys
import time as _time
import traceback as _traceback

with open(_sys.argv[1], encoding="utf-8") as _fh:
    _CFG = _json.load(_fh)
_os.remove(_sys.argv[1])
_WORK = _os.path.realpath(_CFG["work_dir"])
# Where the uploaded files live. In the subprocess backend they are copied into the work dir, so the two
# are the same. In the container backend the inputs are a separate read-only mount, so the code can read
# them without being able to change them, while the work dir stays a writable, size-capped tmpfs.
_INPUT_DIR = _os.path.realpath(_CFG.get("input_dir") or _CFG["work_dir"])
_OUT = _CFG["out_path"]
_dumps = _json.dumps
_b64 = _base64.b64encode
_real_open = _builtins.open
_real_import = _builtins.__import__
_real_getattr = _builtins.getattr
_LIMITS = {"memory": "none", "cpu": "none", "processes": "unrestricted", "degraded": False, "degraded_reason": None}


def _posix_limits(memory_mb, cpu_s, max_processes, max_disk_bytes):
    import resource
    mem = int(memory_mb) * 1024 * 1024
    failures = []
    for name, value in (("RLIMIT_AS", mem), ("RLIMIT_CPU", int(cpu_s)), ("RLIMIT_NOFILE", 256),
                        ("RLIMIT_NPROC", int(max_processes)), ("RLIMIT_FSIZE", int(max_disk_bytes))):
        lim = getattr(resource, name, None)
        if lim is None:
            continue
        try:
            resource.setrlimit(lim, (value, value))
        except (ValueError, OSError) as _exc:
            failures.append(f"{name}: {type(_exc).__name__}")
    _LIMITS.update(memory=f"RLIMIT_AS {memory_mb} MB", cpu=f"RLIMIT_CPU {int(cpu_s)} s",
                   processes=f"RLIMIT_NPROC {int(max_processes)}")
    if failures:
        _LIMITS["degraded"] = True
        _LIMITS["degraded_reason"] = "some POSIX limits could not be applied: " + ", ".join(failures)


_JOB = None


def _windows_job(memory_mb, cpu_s, max_processes):
    global _JOB
    import ctypes
    from ctypes import wintypes

    k32 = ctypes.WinDLL("kernel32", use_last_error=True)

    class _Basic(ctypes.Structure):
        _fields_ = [("PerProcessUserTimeLimit", ctypes.c_int64), ("PerJobUserTimeLimit", ctypes.c_int64),
                    ("LimitFlags", wintypes.DWORD), ("MinimumWorkingSetSize", ctypes.c_size_t),
                    ("MaximumWorkingSetSize", ctypes.c_size_t), ("ActiveProcessLimit", wintypes.DWORD),
                    ("Affinity", ctypes.c_size_t), ("PriorityClass", wintypes.DWORD), ("SchedulingClass", wintypes.DWORD)]

    class _IoCounters(ctypes.Structure):
        _fields_ = [(n, ctypes.c_uint64) for n in ("ReadOperationCount", "WriteOperationCount", "OtherOperationCount",
                                                   "ReadTransferCount", "WriteTransferCount", "OtherTransferCount")]

    class _Extended(ctypes.Structure):
        _fields_ = [("BasicLimitInformation", _Basic), ("IoInfo", _IoCounters), ("ProcessMemoryLimit", ctypes.c_size_t),
                    ("JobMemoryLimit", ctypes.c_size_t), ("PeakProcessMemoryUsed", ctypes.c_size_t),
                    ("PeakJobMemoryUsed", ctypes.c_size_t)]

    k32.CreateJobObjectW.restype = wintypes.HANDLE
    k32.CreateJobObjectW.argtypes = [ctypes.c_void_p, ctypes.c_wchar_p]
    k32.SetInformationJobObject.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD]
    k32.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
    k32.GetCurrentProcess.restype = wintypes.HANDLE
    job = k32.CreateJobObjectW(None, None)
    if not job:
        _LIMITS["degraded"] = True
        _LIMITS["degraded_reason"] = "the Windows Job Object could not be created"
        return
    info = _Extended()
    # PROCESS_TIME | ACTIVE_PROCESS | PROCESS_MEMORY
    info.BasicLimitInformation.LimitFlags = 0x00000002 | 0x00000008 | 0x00000100
    info.BasicLimitInformation.PerProcessUserTimeLimit = int(cpu_s * 10_000_000)
    # The active-process cap is the configured one, not a hardcoded 1: the code may start workers of its
    # own (a pool, a helper process), up to the server's process ceiling.
    info.BasicLimitInformation.ActiveProcessLimit = max(1, int(max_processes))
    info.ProcessMemoryLimit = int(memory_mb) * 1024 * 1024
    if not k32.SetInformationJobObject(job, 9, ctypes.byref(info), ctypes.sizeof(info)):
        _LIMITS["degraded"] = True
        _LIMITS["degraded_reason"] = "the Windows Job Object limits could not be set"
        return
    if k32.AssignProcessToJobObject(job, k32.GetCurrentProcess()):
        _JOB = job
        _LIMITS.update(memory=f"job object {memory_mb} MB", cpu=f"job object {int(cpu_s)} s",
                       processes=str(int(max_processes)))
    else:
        _LIMITS["degraded"] = True
        _LIMITS["degraded_reason"] = "the process could not be assigned to the Windows Job Object"


try:
    if _os.name == "posix":
        _posix_limits(_CFG["memory_mb"], _CFG["cpu_s"], _CFG.get("max_processes", 64),
                      _CFG.get("max_disk_bytes", 256 * 1024 * 1024))
    elif _os.name == "nt":
        _windows_job(_CFG["memory_mb"], _CFG["cpu_s"], _CFG.get("max_processes", 64))
except Exception as _limit_exc:
    # A limit that cannot be applied must never be silent: the parent sees the degraded flag and reports it.
    _LIMITS["degraded"] = True
    _LIMITS["degraded_reason"] = f"resource limits could not be applied: {type(_limit_exc).__name__}"


def _block_network():
    import socket as _socket

    def _deny(*_a, **_k):
        raise PermissionError("network access is disabled in the analysis sandbox")

    class _BlockedSocket(_socket.socket):
        def __init__(self, *_a, **_k):
            _deny()

    _socket.socket = _BlockedSocket
    for _name in ("create_connection", "create_server", "getaddrinfo", "gethostbyname", "gethostbyname_ex",
                  "gethostbyaddr", "socketpair", "fromfd"):
        if hasattr(_socket, _name):
            setattr(_socket, _name, _deny)
    try:
        import _socket as _csocket
        if hasattr(_csocket, "socket"):
            setattr(_csocket, "socket", _BlockedSocket)
        for _name in ("getaddrinfo", "gethostbyname", "gethostbyname_ex", "gethostbyaddr", "create_connection"):
            if hasattr(_csocket, _name):
                setattr(_csocket, _name, _deny)
    except Exception:
        pass


_block_network()


def _block_processes():
    """No program may be started: library features that launch one (matplotlib's animation writers run a configurable
    executable, sympy's autowrap runs a compiler) were a way out of the sandbox (audit AUDIT-102)."""
    import subprocess as _subprocess

    def _deny(*_a, **_k):
        raise PermissionError("starting programs is disabled in the analysis sandbox")

    class _BlockedPopen(_subprocess.Popen):
        def __init__(self, *_a, **_k):
            _deny()

    _subprocess.Popen = _BlockedPopen  # run, call, check_output and getoutput are built on Popen
    for _name in ("system", "popen", "startfile", "posix_spawn", "posix_spawnp", "fork", "forkpty", "execv", "execve",
                  "execl", "execle", "execlp", "execlpe", "execvp", "execvpe", "spawnl", "spawnle", "spawnlp", "spawnlpe",
                  "spawnv", "spawnve", "spawnvp", "spawnvpe"):
        if hasattr(_os, _name):
            setattr(_os, _name, _deny)
    for _mod, _fn in (("_winapi", "CreateProcess"), ("_posixsubprocess", "fork_exec")):
        try:
            setattr(__import__(_mod), _fn, _deny)
        except Exception:
            pass



class _Capped(_io.TextIOBase):
    def __init__(self, inner, limit):
        self._inner, self._left, self.truncated = inner, int(limit), False

    def write(self, s):
        s = str(s)
        if self._left <= 0:
            self.truncated = True
            return len(s)
        # The cap is a byte budget (the output file and the server-side cap are measured in bytes), so keep the
        # longest prefix whose UTF-8 encoding fits rather than counting characters.
        data = s.encode("utf-8", "replace")
        if len(data) <= self._left:
            piece = s
            self._left -= len(data)
        else:
            lo, hi = 0, len(s)
            while lo < hi:
                mid = (lo + hi + 1) // 2
                if len(s[:mid].encode("utf-8", "replace")) <= self._left:
                    lo = mid
                else:
                    hi = mid - 1
            piece = s[:lo]
            self._left -= len(piece.encode("utf-8", "replace"))
            self.truncated = True
        self._inner.write(piece)
        return len(s)

    def flush(self):
        self._inner.flush()


_sys.stdout = _Capped(_sys.stdout, _CFG["max_output_bytes"])
_sys.stderr = _Capped(_sys.stderr, _CFG["max_output_bytes"])

_ALLOWED = frozenset(_CFG["allowed_modules"])
_BANNED_ATTRS = frozenset(_CFG["banned_attributes"]) | frozenset(_CFG["banned_names"])
_READ_MODES = frozenset({"r", "rb", "rt", "br", "tr"})


_BANNED_MODULES = tuple(_CFG.get("banned_modules") or ())
_READER_FUNCS = tuple(_CFG.get("reader_functions") or ())
_READER_KWARGS = tuple(_CFG.get("reader_path_kwargs") or ())
_READER_ROOTS = frozenset({"pandas", "numpy", "scipy", "matplotlib", "sklearn", "h5py"})
_READER_WRAPPERS = {}


def _inside_work(path):
    try:
        real = _os.path.realpath(_os.path.join(_WORK, path))
        return _os.path.commonpath([_os.path.normcase(real), _os.path.normcase(_WORK)]) == _os.path.normcase(_WORK)
    except Exception:
        return False


def _inside_input(path):
    """True when the path is inside the work dir or inside the read-only input dir."""
    if _inside_work(path):
        return True
    if _INPUT_DIR == _WORK:
        return False
    try:
        real = _os.path.realpath(_os.path.join(_INPUT_DIR, path))
        return _os.path.commonpath([_os.path.normcase(real), _os.path.normcase(_INPUT_DIR)]) == _os.path.normcase(
            _INPUT_DIR
        )
    except Exception:
        return False


def _reader_target_ok(target):
    if hasattr(target, "__fspath__"):
        target = _os.fspath(target)
    if isinstance(target, bytes):
        target = target.decode("utf-8", "replace")
    if not isinstance(target, str):
        return True  # a file object (opened through the guarded open()), an array, a buffer
    text = target.strip()
    if "://" in text or text.startswith("~") or "\x00" in text:
        return False
    return _inside_input(text)


def _h5_target(name):
    if hasattr(name, "__fspath__"):
        name = _os.fspath(name)
    if isinstance(name, bytes):
        name = name.decode("utf-8", "replace")
    return name


def _harden_h5py():
    """HDF5 opens files in C, past the guarded open(): its file API (h5py.h5f.create/open, which h5py.File itself
    calls) checks the path. Creating or writing a file stays inside the work dir; reading may also use the inputs.
    `h5py.File(<computed path>, 'w')` once created a file outside the work directory (audit AUDIT-102)."""
    h5f = _sys.modules.get("h5py.h5f")
    if h5f is None or getattr(h5f, "_tribos_guarded", False):
        return
    real_create, real_open = h5f.create, h5f.open
    read_only = getattr(h5f, "ACC_RDONLY", 0)

    def create(name, *args, **kwargs):
        target = _h5_target(name)
        if isinstance(target, str) and not _inside_work(target):
            raise PermissionError("h5py may only create files inside the work directory")
        return real_create(name, *args, **kwargs)

    def open(name, flags=None, *args, **kwargs):  # noqa: A001 - the h5f API name
        target = _h5_target(name)
        reading = flags == read_only
        if isinstance(target, str) and not (_reader_target_ok(target) if reading else _inside_work(target)):
            raise PermissionError("h5py may only open files inside the work directory")
        return real_open(name, *args, **kwargs) if flags is None else real_open(name, flags, *args, **kwargs)

    h5f.create, h5f.open = create, open
    h5f._tribos_guarded = True


def _wrap_reader(fn, name):
    def _guarded_reader(*args, **kwargs):
        target = args[0] if args else next((kwargs[k] for k in _READER_KWARGS if k in kwargs), None)
        if target is not None and not _reader_target_ok(target):
            raise PermissionError(f"{name}() may only read files inside the work directory")
        return fn(*args, **kwargs)
    _guarded_reader.__name__ = name
    _guarded_reader.__doc__ = getattr(fn, "__doc__", None)
    _guarded_reader._tribos_guarded = True
    return _guarded_reader


def _guard_readers():
    """Replace the file-reading functions of the loaded scientific modules with path-checking wrappers."""
    for mod_name, mod in list(_sys.modules.items()):
        if mod is None or mod_name.split(".", 1)[0] not in _READER_ROOTS:
            continue
        try:
            ns = vars(mod)
        except TypeError:
            continue
        for attr in _READER_FUNCS:
            fn = ns.get(attr)
            if fn is None or isinstance(fn, type) or not callable(fn) or getattr(fn, "_tribos_guarded", False):
                continue
            if type(fn).__name__ == "module":
                continue
            wrapper = _READER_WRAPPERS.get(id(fn))
            if wrapper is None:
                wrapper = _READER_WRAPPERS[id(fn)] = (_wrap_reader(fn, attr), fn)
            try:
                setattr(mod, attr, wrapper[0])
            except Exception:
                pass


def _banned_module(name):
    return any(name == m or name.startswith(m + ".") for m in _BANNED_MODULES)


def _guarded_import(name, globals=None, locals=None, fromlist=(), level=0):
    if level or str(name).split(".", 1)[0] not in _ALLOWED or _banned_module(str(name)):
        raise ImportError(f"import of '{name}' is not allowed in the analysis sandbox")
    for item in fromlist or ():
        if str(item).startswith("__") or item in _BANNED_ATTRS or _banned_module(f"{name}.{item}"):
            raise ImportError(f"importing '{item}' is not allowed in the analysis sandbox")
    module = _real_import(name, globals, locals, fromlist, level)
    root = str(name).split(".", 1)[0]
    if root == "h5py":
        _harden_h5py()
    if root in _READER_ROOTS:
        _guard_readers()
    if root == "numpy":
        _numpy_compat()
    if root == "sympy":
        _harden_sympy()
    return module


def _numpy_compat():
    """Models write NumPy 2 names; on NumPy 1.x the same functions exist under their old names, so alias them."""
    np = _sys.modules.get("numpy")
    if np is None:
        return
    if not hasattr(np, "trapezoid") and hasattr(np, "trapz"):
        np.trapezoid = np.trapz  # NumPy 2.0 renamed trapz to trapezoid


def _guarded_open(file, mode="r", *args, **kwargs):
    if not isinstance(file, str) or mode not in _READ_MODES:
        raise PermissionError("open() is read-only in the analysis sandbox and takes a file name")
    real = _os.path.realpath(_os.path.join(_WORK, file))
    if not _inside_work(file):
        raise PermissionError("open() may only read files inside the work directory")
    return _real_open(real, mode, *args, **kwargs)


_MISSING = object()


def _guarded_getattr(obj, name, default=_MISSING):
    if not isinstance(name, str) or name.startswith("__") or name in _BANNED_ATTRS:
        raise AttributeError(f"attribute '{name}' is not available in the analysis sandbox")
    if default is _MISSING:
        return _real_getattr(obj, name)
    return _real_getattr(obj, name, default)


def _guarded_hasattr(obj, name):
    try:
        _guarded_getattr(obj, name)
        return True
    except AttributeError:
        return False


def _load_dataset(name=None, **kwargs):
    """Load a bound input dataset (.csv, .tsv, .xlsx, .parquet, .json, .h5/.hdf5, .mat) inside the sandbox."""
    inputs = list(_CFG.get("inputs") or [])
    if name is None:
        if not inputs:
            raise FileNotFoundError("No input dataset files are bound to this sandbox run")
        name = inputs[0]
    elif isinstance(name, str) and name not in inputs and not _os.path.exists(_os.path.join(_WORK, name)):
        for candidate in inputs:
            if candidate == name or _os.path.splitext(candidate)[0] == name or candidate.startswith(f"{name}."):
                name = candidate
                break
    if not isinstance(name, str) or not _inside_input(name):
        raise PermissionError("load_dataset() may only read files inside the work directory")
    # The file may live in the read-only input mount rather than in the work dir, so it is addressed by its
    # absolute path there. The confinement check above has already established that it stays inside.
    source = name
    if not _os.path.exists(_os.path.join(_WORK, name)) and _INPUT_DIR != _WORK:
        source = _os.path.join(_INPUT_DIR, name)
    ext = _os.path.splitext(name)[1].lower()
    if ext == ".csv":
        pd = _guarded_import("pandas")
        return pd.read_csv(source, **kwargs)
    if ext == ".tsv":
        pd = _guarded_import("pandas")
        kwargs.setdefault("sep", "\t")
        return pd.read_csv(source, **kwargs)
    if ext == ".xlsx":
        pd = _guarded_import("pandas")
        return pd.read_excel(source, **kwargs)
    if ext == ".parquet":
        pd = _guarded_import("pandas")
        return pd.read_parquet(source, **kwargs)
    if ext == ".json":
        pd = _guarded_import("pandas")
        return pd.read_json(source, **kwargs)
    if ext in (".h5", ".hdf5"):
        h5py = _guarded_import("h5py")
        return h5py.File(source, "r")
    if ext == ".mat":
        scipy_io = _guarded_import("scipy.io", fromlist=("loadmat",))
        return scipy_io.loadmat(source, **kwargs)
    raise ValueError(f"Unsupported dataset extension {ext!r}")


def _restricted_builtins():
    banned = set(_CFG["banned_calls"]) | {"open", "getattr", "hasattr", "__import__", "__loader__", "__spec__"}
    safe = {k: v for k, v in vars(_builtins).items() if k not in banned}
    safe.update(__import__=_guarded_import, open=_guarded_open, getattr=_guarded_getattr, hasattr=_guarded_hasattr)
    return safe


# --- Process-wide file-access guard (SEC-1/SEC-3) ------------------------------------------------------------------
# The AST policy and the restricted user builtins only guard code the user namespace runs. Library internals and
# SymPy's string parser reach the real builtins.open / io.open / os.open, so a second, process-wide guard allows
# reads only inside a set of trusted roots (the work dir, the scrubbed temp dir and the read-only Python install),
# and writes only inside the work dir and the temp dir. This is the real file-system boundary.
_real_io_open = _io.open
_real_os_open = _os.open
_DISK = {"left": int(_CFG.get("max_disk_bytes") or 0)}


def _norm(path):
    return _os.path.normcase(_os.path.realpath(path))


def _read_roots():
    # The work dir, the scrubbed temp/cache dirs and the read-only Python installation (stdlib under base_prefix,
    # third-party packages under prefix). sys.path is deliberately NOT trusted: an editable install adds the
    # project source root to it, and nothing in work should read the repository.
    roots = {_norm(_WORK)}
    if _INPUT_DIR != _WORK:
        roots.add(_norm(_INPUT_DIR))
    for var in ("TEMP", "TMP", "TMPDIR", "MPLCONFIGDIR", "NUMBA_CACHE_DIR"):
        value = _os.environ.get(var)
        if value:
            roots.add(_norm(value))
    for base in (_sys.base_prefix, _sys.prefix, _sys.exec_prefix, getattr(_sys, "base_exec_prefix", None)):
        if base:
            roots.add(_norm(base))
    return frozenset(roots)


def _write_roots():
    roots = {_norm(_WORK)}
    for var in ("TEMP", "TMP", "TMPDIR", "MPLCONFIGDIR", "NUMBA_CACHE_DIR"):
        value = _os.environ.get(var)
        if value:
            roots.add(_norm(value))
    return frozenset(roots)


_READ_ROOTS = frozenset()
_WRITE_ROOTS = frozenset()


def _under(real, roots):
    nc = _os.path.normcase(real)
    for root in roots:
        try:
            if _os.path.commonpath([nc, root]) == root:
                return True
        except ValueError:
            continue
    return False


def _fspath_str(file):
    if hasattr(file, "__fspath__"):
        file = _os.fspath(file)
    if isinstance(file, bytes):
        return file.decode("utf-8", "replace")
    return file if isinstance(file, str) else None


def _check_access(file, writing):
    text = _fspath_str(file)
    if text is None:
        return  # a file descriptor or buffer, not a path
    try:
        real = _os.path.realpath(text if _os.path.isabs(text) else _os.path.join(_WORK, text))
    except Exception:
        raise PermissionError(f"invalid file path {text!r}")
    roots = _WRITE_ROOTS if writing else _READ_ROOTS
    if not _under(real, roots):
        verb = "write" if writing else "read"
        raise PermissionError(f"file access outside the analysis work directory is not allowed (cannot {verb} {text!r})")


class _CappedHandle:
    """Wraps a writable file handle so the child cannot fill the host disk (Windows has no RLIMIT_FSIZE)."""

    def __init__(self, inner):
        self.__dict__["_inner"] = inner

    def write(self, data):
        size = len(data) if isinstance(data, (bytes, bytearray, memoryview)) else len(str(data).encode("utf-8", "replace"))
        if _DISK["left"] >= 0 and size > _DISK["left"]:
            raise OSError("the analysis sandbox disk-write limit was exceeded")
        _DISK["left"] -= size
        return self._inner.write(data)

    def __getattr__(self, name):
        return getattr(self._inner, name)

    def __setattr__(self, name, value):
        setattr(self._inner, name, value)

    def __iter__(self):
        return iter(self._inner)

    def __enter__(self):
        self._inner.__enter__()
        return self

    def __exit__(self, *exc):
        return self._inner.__exit__(*exc)


def _is_write_mode(mode):
    return any(ch in str(mode) for ch in "wax+")


def _make_open_guard(real_open):
    def guarded(file, mode="r", *args, **kwargs):
        writing = _is_write_mode(mode)
        _check_access(file, writing)
        handle = real_open(file, mode, *args, **kwargs)
        if writing and _DISK["left"] >= 0:
            return _CappedHandle(handle)
        return handle
    return guarded


def _os_open_guard(real_os_open):
    def guarded(path, flags, *args, **kwargs):
        writing = bool(flags & (_os.O_WRONLY | _os.O_RDWR | getattr(_os, "O_CREAT", 0) | getattr(_os, "O_APPEND", 0)))
        _check_access(path, writing)
        return real_os_open(path, flags, *args, **kwargs)
    return guarded


def _make_fileio_guard(real_fileio):
    class _GuardedFileIO(real_fileio):
        def __init__(self, file, mode="r", *args, **kwargs):
            writing = any(ch in str(mode) for ch in "wax+")
            _check_access(file, writing)
            super().__init__(file, mode, *args, **kwargs)
    return _GuardedFileIO


def _os_write_path_guard(real_fn):
    def guarded(path, *args, **kwargs):
        _check_access(path, True)
        return real_fn(path, *args, **kwargs)
    return guarded


def _os_rename_guard(real_fn):
    def guarded(src, dst, *args, **kwargs):
        _check_access(src, True)
        _check_access(dst, True)
        return real_fn(src, dst, *args, **kwargs)
    return guarded


def _os_listdir_guard(real_listdir):
    def guarded(path=".", *args, **kwargs):
        _check_access(path, False)
        return real_listdir(path, *args, **kwargs)
    return guarded


def _os_scandir_guard(real_scandir):
    def guarded(path=".", *args, **kwargs):
        _check_access(path, False)
        return real_scandir(path, *args, **kwargs)
    return guarded


def _install_io_guard():
    global _READ_ROOTS, _WRITE_ROOTS
    _READ_ROOTS, _WRITE_ROOTS = _read_roots(), _write_roots()
    _builtins.open = _make_open_guard(_real_open)
    _io.open = _make_open_guard(_real_io_open)
    c_io = _sys.modules.get("_io")
    if c_io is not None:
        if hasattr(c_io, "open"):
            try:
                c_io.open = _make_open_guard(getattr(c_io, "open"))
            except (AttributeError, TypeError):
                pass
        if hasattr(c_io, "FileIO"):
            try:
                c_io.FileIO = _make_fileio_guard(getattr(c_io, "FileIO"))
            except (AttributeError, TypeError):
                pass
    if hasattr(_io, "FileIO"):
        try:
            _io.FileIO = _make_fileio_guard(getattr(_io, "FileIO"))
        except (AttributeError, TypeError):
            pass
    if hasattr(_io, "open_code"):
        orig_open_code = _io.open_code

        def _guarded_open_code(path):
            _check_access(path, False)
            return orig_open_code(path)
        try:
            _io.open_code = _guarded_open_code
        except (AttributeError, TypeError):
            pass
    _os.open = _os_open_guard(_real_os_open)
    if hasattr(_os, "listdir"):
        _os.listdir = _os_listdir_guard(_os.listdir)
    if hasattr(_os, "scandir"):
        _os.scandir = _os_scandir_guard(_os.scandir)
    for _fn_name in ("remove", "unlink", "rmdir", "mkdir", "makedirs"):
        if hasattr(_os, _fn_name):
            try:
                setattr(_os, _fn_name, _os_write_path_guard(getattr(_os, _fn_name)))
            except (AttributeError, TypeError):
                pass
    for _fn_name in ("rename", "replace"):
        if hasattr(_os, _fn_name):
            try:
                setattr(_os, _fn_name, _os_rename_guard(getattr(_os, _fn_name)))
            except (AttributeError, TypeError):
                pass


# --- SymPy string-parser hardening (SEC-1) -------------------------------------------------------------------------
# sympify / S / parse_expr / parse_latex compile their string argument and eval it with the real builtins, so
# `sympify("__import__('os')")` reaches os. Harden every string entry point to (1) reject dunders after NFKC
# normalisation and (2) eval with a global_dict whose __builtins__ is the restricted set (guarded import/open).
_SYMPY_HARDENED = [False]
_SYMPY_GLOBALS = [None]


def _sympy_eval_globals():
    if _SYMPY_GLOBALS[0] is None:
        g = {}
        exec("from sympy import *", g)  # real builtins here; populates the sympy namespace once
        g["__builtins__"] = _restricted_builtins()
        _SYMPY_GLOBALS[0] = g
    return dict(_SYMPY_GLOBALS[0])


def _reject_dunder(value):
    import unicodedata as _ud
    if isinstance(value, str) and "__" in _ud.normalize("NFKC", value):
        raise ValueError("expressions containing '__' are not allowed in the analysis sandbox")


def _harden_sympy():
    if _SYMPY_HARDENED[0]:
        return
    sp = _sys.modules.get("sympy")
    if sp is None:
        return
    _SYMPY_HARDENED[0] = True
    try:
        parser = _real_import("sympy.parsing.sympy_parser", None, None, ("parse_expr",), 0)
    except Exception:
        parser = None

    if parser is not None:
        _orig_parse_expr = parser.parse_expr

        def _safe_parse_expr(s="", local_dict=None, transformations=parser.standard_transformations,
                             global_dict=None, evaluate=True):
            _reject_dunder(s)
            if global_dict is None:
                global_dict = _sympy_eval_globals()
            elif "__builtins__" not in global_dict:
                global_dict = {**global_dict, "__builtins__": _restricted_builtins()}
            return _orig_parse_expr(s, local_dict=local_dict, transformations=transformations,
                                    global_dict=global_dict, evaluate=evaluate)

        parser.parse_expr = _safe_parse_expr
        if getattr(sp, "parse_expr", None) is _orig_parse_expr:
            sp.parse_expr = _safe_parse_expr

    core = _sys.modules.get("sympy.core.sympify")
    if core is not None and hasattr(core, "sympify"):
        _orig_sympify = core.sympify

        def _safe_sympify(a, *args, **kwargs):
            _reject_dunder(a)
            return _orig_sympify(a, *args, **kwargs)

        core.sympify = _safe_sympify
        sp.sympify = _safe_sympify
        sp.S = core.S if hasattr(core, "S") else sp.S

    if hasattr(sp, "lambdify"):
        _orig_lambdify = sp.lambdify

        def _safe_lambdify(args, expr, *a, **k):
            _reject_dunder(expr)
            return _orig_lambdify(args, expr, *a, **k)

        sp.lambdify = _safe_lambdify


def _scalar(v):
    if isinstance(v, float):
        return v if _math.isfinite(v) else None
    return v


def _jsonable(v, depth=0):
    if depth > 6:
        return repr(v)[:200]
    if v is None or isinstance(v, (bool, int, str)):
        return v[:4000] if isinstance(v, str) else v
    if isinstance(v, float):
        return _scalar(v)
    pd = _sys.modules.get("pandas")
    np = _sys.modules.get("numpy")
    if pd is not None and isinstance(v, pd.DataFrame):
        return {"table": "result", "shape": [int(v.shape[0]), int(v.shape[1])]}
    if pd is not None and isinstance(v, pd.Series):
        return {str(k): _jsonable(x, depth + 1) for k, x in list(v.items())[:MAX_ROWS]}
    max_items = int(_CFG.get("max_array_items", 25000))
    if np is not None and isinstance(v, np.ndarray):
        return _jsonable(v.ravel()[:max_items].tolist() if v.ndim != 1 else v[:max_items].tolist(), depth + 1)
    if np is not None and isinstance(v, np.generic):
        return _jsonable(v.item(), depth + 1)
    if isinstance(v, dict):
        return {str(k): _jsonable(x, depth + 1) for k, x in list(v.items())[:max_items]}
    if isinstance(v, (list, tuple, set, frozenset)):
        return [_jsonable(x, depth + 1) for x in list(v)[:max_items]]
    return repr(v)[:2000]


MAX_ROWS = _CFG["max_table_rows"]


def _table(name, df):
    pd = _sys.modules.get("pandas")
    if pd is None:
        return None
    if isinstance(df, pd.Series):
        df = df.to_frame()
    if not isinstance(df, pd.DataFrame):
        return None
    head = df.head(MAX_ROWS)
    index_name = str(head.index.name or "index")
    columns = [index_name] + [str(c) for c in head.columns]
    rows = []
    for idx, row in zip(head.index, head.itertuples(index=False, name=None)):
        rows.append([_jsonable(idx)] + [_jsonable(x) for x in row])
    return {"name": str(name)[:80], "columns": columns[:60], "rows": [r[:60] for r in rows],
            "n_rows": int(df.shape[0]), "n_columns": int(df.shape[1])}


def _figures(limit):
    plt = _sys.modules.get("matplotlib.pyplot")
    out = []
    warnings = []
    if plt is None:
        return out, warnings
    all_fignums = list(plt.get_fignums())
    if len(all_fignums) > limit:
        warnings.append(f"Generated {len(all_fignums)} figures; limit is {limit}. Figures beyond {limit} were omitted.")
    dpi = _CFG.get("figure_dpi", 120)
    for num in all_fignums[:limit]:
        try:
            fig = plt.figure(num)
            axes_meta = []
            for ax in fig.get_axes():
                axes_meta.append({
                    "title": str(ax.get_title() or ""),
                    "xlabel": str(ax.get_xlabel() or ""),
                    "ylabel": str(ax.get_ylabel() or ""),
                })
            width, height = fig.get_size_inches()

            buf_png = _io.BytesIO()
            fig.savefig(buf_png, format="png", dpi=dpi, bbox_inches="tight")
            png_data = buf_png.getvalue()

            svg_str = None
            try:
                buf_svg = _io.BytesIO()
                fig.savefig(buf_svg, format="svg", bbox_inches="tight")
                svg_data = buf_svg.getvalue()
                if len(svg_data) <= _CFG["max_figure_bytes"] * 2:
                    svg_str = svg_data.decode("utf-8", "replace")
            except Exception:
                pass

            if len(png_data) > _CFG["max_figure_bytes"]:
                warnings.append(f"Figure {num} exceeded size limit ({len(png_data)} > {_CFG['max_figure_bytes']} bytes).")
                continue

            import hashlib as _hl
            f_hash = _hl.sha256(png_data).hexdigest()[:16]
            out.append({
                "figure_id": f"fig_{num}_{f_hash}",
                "name": f"figure_{num}.png",
                "png_base64": _b64(png_data).decode("ascii"),
                "svg": svg_str,
                "dpi": dpi,
                "dimensions": [float(width), float(height)],
                "axes": axes_meta,
                "file_hash": f_hash,
                "bytes": len(png_data),
            })
        except Exception as _ex:
            warnings.append(f"Figure {num} capture failed: {type(_ex).__name__}")
    return out, warnings


def _main():
    with _real_open(_CFG["code_path"], encoding="utf-8") as fh:
        src = fh.read()
    lines = src.splitlines()
    if _CFG.get("install_guards", True):
        _install_io_guard()
        if "sympy" in _sys.modules:
            _harden_sympy()
        if "h5py" in _sys.modules:
            _harden_h5py()
        _block_processes()  # with the other guards: off only in the test-only unsafe mode
    g = {
        "__builtins__": _restricted_builtins(),
        "__name__": "__analysis__",
        "INPUT_FILES": list(_CFG["inputs"]),
        "load_dataset": _load_dataset,
    }
    if _CFG.get("data_path"):
        # Values passed as data (earlier results a plan node refers to), never pasted into the code text.
        with _real_open(_CFG["data_path"], encoding="utf-8") as fh:
            g["inputs"] = _json.load(fh)
    status, error = "ok", None
    t0 = _time.perf_counter()
    try:
        exec(compile(src, "<analysis>", "exec"), g)
    except BaseException as exc:  # noqa: BLE001 - SystemExit/KeyboardInterrupt from user code are failures too
        status = "error"
        frames = [f for f in _traceback.extract_tb(exc.__traceback__) if f.filename == "<analysis>"]
        parts = []
        for f in frames[-3:]:
            text = lines[f.lineno - 1].strip() if f.lineno and 0 < f.lineno <= len(lines) else ""
            parts.append(f"  line {f.lineno}: {text}")
        parts.append("".join(_traceback.format_exception_only(type(exc), exc)).strip())
        error = "\n".join(parts)[-4000:]
    seconds = _time.perf_counter() - t0
    tables, result = [], None
    try:
        pd = _sys.modules.get("pandas")
        raw = g.get("result")
        if pd is not None and isinstance(raw, pd.DataFrame):
            t = _table("result", raw)
            if t:
                tables.append(t)
        result = _jsonable(raw)
        extra = g.get("tables")
        if isinstance(extra, dict):
            for name, df in list(extra.items())[: _CFG["max_tables"]]:
                t = _table(name, df)
                if t and len(tables) < _CFG["max_tables"]:
                    tables.append(t)
    except Exception as exc:  # noqa: BLE001
        result = f"<result could not be serialised: {type(exc).__name__}>"
    figures, fig_warnings = [], []
    try:
        figures, fig_warnings = _figures(_CFG["max_figures"])
    except Exception as _ex:
        fig_warnings.append(f"Figure extraction error: {type(_ex).__name__}")
    payload = {"status": status, "error": error, "result": result, "tables": tables, "figures": figures,
               "warnings": fig_warnings,
               "exec_seconds": round(seconds, 3), "limits": _LIMITS,
               "stdout_truncated": bool(getattr(_sys.stdout, "truncated", False))}
    try:
        text = _dumps(payload, allow_nan=False, default=str)
    except ValueError:
        payload["result"] = repr(result)[:4000]
        text = _dumps(payload, default=str)
    with _real_open(_OUT, "w", encoding="utf-8") as fh:
        fh.write(text)


_main()
'''


def sandbox_python() -> str:
    return sys.executable


def _child_env(root: str, tmp: str) -> dict[str, str]:
    """The child's whole environment: an allowlist, never API keys or tokens.

    MPLCONFIGDIR points inside this run's own directory: a shared, writable font cache would let one run (or one
    user) alter the next run's cache.
    """
    return allowlisted_env(root, tmp, mpl_config_dir=os.path.join(tmp, "mpl"))


def _rmtree(path: str) -> None:
    rmtree(path)


def _kill_tree(proc: subprocess.Popen[bytes]) -> None:
    kill_tree(proc)


def _read_capped(path: str, limit: int, tail: bool = False) -> str:
    return read_capped(path, limit, tail=tail)


def _empty(status: str, error: str | None, **extra: Any) -> dict[str, Any]:
    out: dict[str, Any] = {
        "status": status,
        "stdout": "",
        "stderr": "",
        "result": None,
        "figures": [],
        "tables": [],
        "seconds": 0.0,
        "error": error,
        "violations": [],
        "limits": {},
    }
    out.update(extra)
    return out


def run_code(
    code: str,
    input_files: dict[str, str] | None = None,
    timeout_s: float = 60,
    max_output_kb: int = 256,
    memory_mb: int = 2048,
    *,
    max_figures: int = MAX_FIGURES,
    data: dict[str, Any] | None = None,
    _unsafe_skip_policy: bool = False,
    on_spawn: Any = None,
    max_disk_mb: int = 256,
    max_processes: int = 64,
    strict_limits: bool = False,
    semaphore: Any = None,
) -> dict[str, Any]:
    """
    Execute one analysis/computation cell. input_files maps the name the code reads (a plain file name) to a server path
    the caller has already validated; each is copied read-only into the work dir. Returns
    {status: ok|error|timeout|policy_violation|failed, stdout, stderr, result, figures[{name,png_base64}], tables,
    seconds, error, violations, limits}. `data` (JSON-serialisable) is available to the code as the variable `inputs`.

    _unsafe_skip_policy (tests only) disables the AST policy and the runtime import/builtins guards so a test can
    inspect the child's environment; the subprocess, env scrubbing and network stub still apply. It is refused
    outside a test run, and it never disables the network stub.
    """
    if _unsafe_skip_policy and not _under_test():
        return _empty("failed", "the test-only sandbox escape hatch is not available in a production run")
    inputs = dict(input_files or {})
    for name in inputs:
        if not _INPUT_NAME_RE.match(str(name)) or not safe_relative_path(str(name)):
            return _empty("failed", f"invalid input file name {str(name)[:60]!r}")
    if not _unsafe_skip_policy:
        violations = check_code(code, inputs.keys())
        if violations:
            return _empty("policy_violation", "the code was rejected by the sandbox policy", violations=violations)
    timeout_s = max(1.0, float(timeout_s))
    max_bytes = max(1, int(max_output_kb)) * 1024
    max_disk_bytes = max(0, int(max_disk_mb)) * 1024 * 1024
    max_processes = max(1, int(max_processes))

    root = tempfile.mkdtemp(prefix="tribos-sbx-")
    work, io_dir, tmp = (os.path.join(root, d) for d in ("work", "io", "tmp"))
    t0 = time.perf_counter()
    if semaphore is not None:
        acquired = semaphore.acquire(timeout=queue_timeout_s)
        if not acquired:
            return _empty("busy", "the sandbox is busy; try again in a moment",
                          seconds=round(time.perf_counter() - t0, 3))
    try:
        for d in (work, io_dir, tmp):
            os.makedirs(d, exist_ok=True)
        for name, src in inputs.items():
            if not src or not os.path.isfile(src):
                return _empty("failed", f"input file {name} is not available")
            dst = os.path.join(work, name)
            shutil.copyfile(src, dst)
            os.chmod(dst, stat.S_IREAD | stat.S_IRGRP | stat.S_IROTH)

        token = secrets.token_hex(8)
        code_path = os.path.join(io_dir, f"cell_{token}.py")
        boot_path = os.path.join(io_dir, f"bootstrap_{token}.py")
        cfg_path = os.path.join(io_dir, f"config_{token}.json")
        out_path = os.path.join(io_dir, f"out_{token}.json")
        with open(code_path, "w", encoding="utf-8") as fh:
            fh.write(code)
        boot = _BOOTSTRAP
        if _unsafe_skip_policy:
            boot = boot.replace('"__builtins__": _restricted_builtins(),', '"__builtins__": _builtins,')
        with open(boot_path, "w", encoding="utf-8") as fh:
            fh.write(boot)
        data_path = ""
        if data is not None:
            data_path = os.path.join(io_dir, f"data_{token}.json")
            with open(data_path, "w", encoding="utf-8") as fh:
                json.dump(data, fh, default=str)
        cfg = {
            "data_path": data_path,
            "work_dir": work,
            "input_dir": work,
            "out_path": out_path,
            "code_path": code_path,
            "inputs": sorted(inputs),
            "memory_mb": int(memory_mb),
            "cpu_s": int(timeout_s) + 5,
            "max_output_bytes": max_bytes,
            "install_guards": not _unsafe_skip_policy,
            # The write budget is enforced on every platform: the open guard counts bytes written and refuses once
            # the budget is spent. RLIMIT_FSIZE additionally caps a single file on POSIX.
            "max_disk_bytes": max_disk_bytes,
            "max_processes": max_processes,
            "max_array_items": int(os.getenv("TRIBOS_SANDBOX_MAX_ARRAY_ITEMS", "25000")),
            "max_figures": max(0, int(max_figures)),
            "figure_dpi": int(os.getenv("TRIBOS_SANDBOX_FIGURE_DPI", "120")),
            "max_figure_bytes": MAX_FIGURE_BYTES,
            "max_tables": MAX_TABLES,
            "max_table_rows": MAX_TABLE_ROWS,
            "allowed_modules": sorted(ALLOWED_MODULE_ROOTS),
            "banned_attributes": sorted(BANNED_ATTRIBUTES),
            "banned_modules": list(BANNED_MODULES),
            "banned_names": sorted(BANNED_NAMES),
            "banned_calls": sorted(BANNED_CALLS),
            "reader_functions": sorted(READER_FUNCTIONS),
            "reader_path_kwargs": list(READER_PATH_KWARGS),
        }
        with open(cfg_path, "w", encoding="utf-8") as fh:
            json.dump(cfg, fh)

        stdout_path, stderr_path = os.path.join(io_dir, "stdout.txt"), os.path.join(io_dir, "stderr.txt")
        kwargs: dict[str, Any] = dict(process_group_kwargs())
        timed_out = False
        proc: subprocess.Popen[Any] | None = None
        try:
            with open(stdout_path, "wb") as out_fh, open(stderr_path, "wb") as err_fh:
                proc = subprocess.Popen(
                    [sandbox_python(), "-I", boot_path, cfg_path],
                    cwd=work,
                    env=_child_env(root, tmp),
                    stdin=subprocess.DEVNULL,
                    stdout=out_fh,
                    stderr=err_fh,
                    **kwargs,
                )
                if on_spawn is not None:
                    try:
                        on_spawn(proc)
                    except Exception:
                        pass
                try:
                    proc.wait(timeout=timeout_s)
                except subprocess.TimeoutExpired:
                    timed_out = True
                    _kill_tree(proc)
        finally:
            # The child and every descendant must be gone before the run directory is removed, even when the
            # parent raised between Popen and wait.
            if proc is not None and proc.poll() is None:
                _kill_tree(proc)
        seconds = round(time.perf_counter() - t0, 3)
        stdout = _read_capped(stdout_path, max_bytes)
        stderr = _read_capped(stderr_path, STDERR_TAIL_BYTES, tail=True)
        if timed_out:
            return _empty("timeout", f"the analysis exceeded the {timeout_s:g} s time limit and was stopped",
                          stdout=stdout, stderr=stderr, seconds=seconds)
        # The parent's backstop against a write budget the child could not enforce itself.
        written = dir_size_bytes(work)
        if max_disk_bytes > 0 and written > max_disk_bytes:
            return _empty("error",
                          f"the analysis wrote {written} bytes, over the {max_disk_bytes} byte budget",
                          stdout=stdout, stderr=stderr, seconds=seconds,
                          limits={"disk_bytes": written, "max_disk_bytes": max_disk_bytes})
        try:
            with open(out_path, encoding="utf-8") as fh:
                payload = json.load(fh)
        except (OSError, ValueError):
            tail = stderr.strip().splitlines()[-1:] if stderr.strip() else []
            reason = tail[0][:300] if tail else f"exit code {proc.returncode if proc is not None else 'unknown'}"
            rc = proc.returncode if proc is not None else None
            killed = rc is not None and (rc < 0 or rc in (137, 3221225477, 3221225540, -1073741756))
            if killed:
                reason = f"the process was killed (exit code {rc}); it may have exceeded the memory limit"
            return _empty("error", f"the analysis process ended without a result: {reason}",
                          stdout=stdout, stderr=stderr, seconds=seconds)
        limits = dict(payload.get("limits") or {})
        limits["disk_bytes"] = written
        if limits.get("degraded"):
            reason = str(limits.get("degraded_reason") or "some resource limits could not be applied")
            if strict_limits:
                return _empty("failed", f"the sandbox could not enforce its resource limits: {reason}",
                              stdout=stdout, stderr=stderr, seconds=seconds, limits=limits)
            logger.warning("Sandbox run was degraded: %s", reason)
        return {
            "status": "ok" if payload.get("status") == "ok" else "error",
            "stdout": stdout,
            "stderr": stderr,
            "result": payload.get("result"),
            "figures": list(payload.get("figures") or [])[:MAX_FIGURES],
            "tables": list(payload.get("tables") or [])[:MAX_TABLES],
            "seconds": seconds,
            "error": payload.get("error"),
            "violations": [],
            "limits": limits,
        }
    except Exception as exc:  # noqa: BLE001
        logger.warning("Sandbox run failed: %s", exc, exc_info=True)
        return _empty("failed", f"{type(exc).__name__}: {str(exc)[:200]}", seconds=round(time.perf_counter() - t0, 3))
    finally:
        _rmtree(root)
        if semaphore is not None:
            try:
                semaphore.release()
            except Exception:  # noqa: BLE001
                pass


__all__ = ["MAX_FIGURES", "run_code", "sandbox_python"]
