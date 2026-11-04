# Sandboxed code analysis: threat model, architecture and configuration

Feature 10 lets an agent write Python and run it over a dataset the researcher attached
(CodeAct, Wang et al., ICML 2024, arXiv:2402.01030; Biomni, doi:10.1101/2025.05.30.656746; BixBench,
arXiv:2503.00096; Data Interpreter, arXiv:2402.18679). This page explains what the sandbox defends against,
what it does not, how it is put together, and how to run it in production.

Code:

| Module | Role |
|---|---|
| `tribos/agentic/sandbox/gateway.py` | **The single entry point.** Permission, policy, limits, backend selection, audit. |
| `tribos/agentic/sandbox/backends.py` | The backend protocol and the `ExecutionRequest` / report contract. |
| `tribos/agentic/sandbox/policy.py` | The AST policy, with the `analysis` and `sage` profiles. |
| `tribos/agentic/sandbox/runner.py` | The subprocess backend: bootstrap, runtime guards, resource limits. |
| `tribos/agentic/sandbox/process.py` | Shared primitives: process-tree kill, environment allowlist, capped reads. |
| `tribos/agentic/sandbox/container.py` | The container backend (Docker / Podman): the OS-level boundary. |
| `tribos/agentic/sandbox/__init__.py` | Settings accessors, the request-permission context variable, dataset scoping. |
| `tribos/axiom/sagemath.py` | The SageMath runner, contained by the same policy and limits. |
| `tribos/agentic/analyst.py` | The CodeAct phase, now routed through the gateway. |
| `tribos/extensions/sandbox.py`, `tribos/extensions/axiom.py` | The registry tools (`analysis_run_python`, `calcula_run_python`, `axiom_sagemath`, …). |

## Threat model

The code is untrusted even though our own model writes it. The model reads text it did not write: the question,
column names and cell values of the uploaded file, earlier tool output, and retrieved papers and web pages. Any
of these can carry instructions aimed at the model. This is indirect prompt injection (Greshake et al. 2023,
AISec '23, arXiv:2302.12173). An injected instruction could ask the model to write code that reads secrets,
calls out to the network, or reads another user's files.

Assets we protect:
- server secrets: API keys and tokens in the process environment;
- other users' uploads, and anything else on the server's disk;
- the network position of the server (no outbound calls from analysis code);
- the availability of the API process (no runaway CPU, memory, disk or output).

Out of scope: the integrity of the analysis itself. Code can compute a wrong number, and the model can misread
it. That risk is handled by showing the code, its output and the dataset with the answer, by the verifier, and
by allowing "insufficient information" as an answer.

## The invariant

> **Model-written code never runs in the API process, and every run passes one decision point.**

That is the whole design. The API container holds the credentials; it never executes model-written code. The
execution paths (analyst phase, planner DAG, direct registry calls, SageMath) all call
`tribos.agentic.sandbox.gateway.execute()`. There is no second, unguarded way in: the gateway owns the decision
"may this run?", and a backend is only reached after it says yes.

The gateway decides, in this order:

1. **Permission.** The server-wide switch (`TRIBOS_SANDBOX`) and the per-request switch (the "Allow code analysis
   on datasets" option) must both allow execution. When either forbids it, **no backend is called** and the
   report says why (`disabled` or `forbidden`).
2. **Policy.** The AST policy (`policy.py`) rejects the code before anything runs, against the engine's profile.
3. **Limits.** The effective timeout, memory, output, disk and process caps are resolved from the caller's request
   and the server's settings. **A caller may only lower a limit, never raise it.**
4. **Backend selection.** `auto`, `subprocess` or `container` (see *Backend modes*).
5. **Audit.** One structured log line per execution: engine, backend, status, duration and the effective limits.
   Never the code, never a secret.

The request-level permission travels in a `contextvars.ContextVar`
(`tribos.agentic.sandbox.execution_permitted`), which propagates into the `asyncio.to_thread` workers the registry
tools run in — exactly like the existing dataset `bound_scope`. That is what makes the per-request toggle
authoritative for direct tool calls that never went through the planner.

## The layers

Inside the child, the layers below still apply. **None of them is a security boundary on its own.** A Python
process with numpy, pandas and scipy loaded has a very large attack surface, and pure-Python sandboxes have a
long history of escapes. They are defence in depth *underneath* the container boundary, not a substitute for it.

1. **Spotlighting of untrusted text** (Hines et al. 2024, arXiv:2403.14720). The dataset preview, previous
   outputs and the question reach the model inside `<untrusted_data>` blocks, with instruction-like spans
   neutralised (`tribos/agentic/guardrails.py`). The system prompt says this text is data.
2. **AST policy** (`policy.py`), applied before anything runs:
   - an import allowlist: numpy, pandas, scipy, sklearn, matplotlib, anndata, scanpy, statsmodels (if
     installed), math, statistics, json, re, collections, itertools, functools, typing, datetime;
   - banned names, and the same names as attributes (`pandas.io.common.os`): os, sys, subprocess, socket,
     shutil, ctypes, importlib, builtins, pickle, marshal, pathlib;
   - banned calls: eval, exec, compile, `__import__`, globals, locals, vars, setattr, delattr, breakpoint, input;
     getattr and hasattr only with a plain, non-dunder string literal;
   - any name or attribute starting with `__`, frame, generator and traceback internals (`gi_frame`,
     `f_globals`, `tb_frame`, ...), and format strings that reach dunders;
   - `open()` only in read mode, on a relative path inside the work directory (the input files, by name);
   - file writers (`to_csv`, `savefig`, `np.save`, `write_h5ad`, ...) only to a literal relative path inside the
     work directory, never over an input file;
   - pickle-based I/O (`read_pickle`, `to_pickle`, `allow_pickle=True`), which runs code on load.
   - submodules that load native code, compile or launch programs, whatever the import spelling
     (`BANNED_MODULES`: `numpy.ctypeslib`, `numpy.f2py`, `sympy.utilities.autowrap`, `sympy.printing.preview`,
     the pandas clipboard, ...), and the matching names and attributes (`load_library`, `CDLL`, `ctypes`,
     `autowrap`, `preview`, `Popen`, `startfile`, the HDF5 low-level `h5f` API, ...). The 2026-11-04 audit
     (AUDIT-102) loaded kernel32 through `import numpy.ctypeslib as c` with a computed library name.
3. **A separate process.** `sys.executable -I` (isolated mode: PYTHON* variables ignored, no user site-packages,
   the script directory not on `sys.path`). `-S` is not used because the scientific stack lives in
   site-packages. The working directory is a fresh temporary `work/` folder that holds only read-only copies of
   the attached files. The bootstrap, code and output files live in a sibling folder the code cannot name
   (the policy rejects `..`). Everything is deleted afterwards.
4. **Runtime guards in the child**, installed by the bootstrap before user code runs: user code executes with a
   restricted builtins dict. That dict has an `__import__` that re-checks the allowlist, a read-only `open()`
   confined to the work directory (this catches computed paths the AST cannot see), a `getattr` that refuses
   dunder and banned names, and no eval, exec, compile, vars or globals. stdout and stderr are capped.
   Two further guards close the escapes the audit found: **no program can be started** (`subprocess.Popen`,
   `os.system`/`popen`/`spawn*`/`exec*`/`startfile`, `_winapi.CreateProcess` and `_posixsubprocess.fork_exec`
   raise; matplotlib's animation writers once launched a configurable executable), and **HDF5 opens files only
   inside the work directory** (h5py's C-level `h5f.create`/`h5f.open`, which `h5py.File` calls, check the path;
   `h5py.File(<computed path>, 'w')` once created a file outside it). `tests/test_fix_audit_102_sandbox_escapes.py`
   replays the audit's payloads.
5. **No secrets in the environment.** The child's environment is built from an allowlist: PATH,
   SYSTEMROOT/WINDIR, PATHEXT, TEMP/TMP (pointing into the run's own temp folder), PYTHONHASHSEED, and the
   thread and backend settings the runner sets itself (MPLBACKEND=Agg, MPLCONFIGDIR, NUMBA_CACHE_DIR, *_NUM_THREADS=1).
   API keys and tokens are never copied. `tests/test_feat_sandbox_runtime.py` checks this.
6. **No network.** Before user code runs, `socket.socket` is replaced by a subclass whose constructor raises,
   and `create_connection`, `getaddrinfo`, `gethostbyname` and related functions raise `PermissionError`. This is a
   monkeypatch inside the interpreter, and it is the weakest layer. Native extensions that open sockets
   themselves are not covered. In the container backend the network is also cut at the OS level
   (`--network none`), which is what actually holds.
7. **Limits.** A wall-clock timeout (default 60 s) kills the whole process tree (`taskkill /T` on Windows, the
   process group on POSIX, `SIGTERM` then `SIGKILL` on POSIX). On POSIX the bootstrap sets RLIMIT_AS
   (default 2048 MB), RLIMIT_CPU, RLIMIT_NOFILE, RLIMIT_FSIZE and RLIMIT_NPROC. On Windows it assigns itself to a
   Job Object with a per-process memory limit, a CPU-time limit and an active-process limit of
   `TRIBOS_SANDBOX_MAX_PROCESSES` (default 64) — so the code may start workers of its own, up to that ceiling.
   This step is **best effort**: if it fails the run continues with only the timeout, and the report says so
   (see *Degraded mode*). Output is capped (256 KB stdout by default, 6 figures).
8. **Dataset scoping.** The model never names a path. The analyst phase binds a scope that holds the run's user
   id and the ids of the datasets attached to this question. The tool resolves the requested ids through
   `DatasetStore.resolve_for_user` for that user only, checks that each path lies under the upload root, and
   copies the files in. A call with no bound scope reads no files. The planner cannot use the tool to reach
   another user's upload or a server path.
9. **On by default, but never implicit.** `TRIBOS_SANDBOX` defaults to **on**. When it is off, every
   model-written execution path is closed: the tools are not registered, the gateway returns `disabled`, and
   direct calls refuse. The per-request "Allow code analysis on datasets" option is the narrower switch: with it
   off, that request cannot run Python or SageMath at all, whatever the planner asks for.

### The SageMath path

Under strict isolation (`TRIBOS_SANDBOX_STRICT_LIMITS=1`) SageMath is refused unless `TRIBOS_SANDBOX_ALLOW_UNISOLATED=1`, like the subprocess backend: the container backend does not carry it (AUDIT-103).

SageMath used to bypass the sandbox entirely: model-written Sage ran through a bare `subprocess.run` with no
policy, no network block, no resource caps and a timeout that did not kill descendants. It is now contained:

- the same gateway owns it (`execute(code, engine="sage")`);
- the AST policy runs with the `sage` profile, which widens the allowed module roots to include `sage` and
  `sagemath` and nothing else — the banned names, the dunder ban and the write restrictions are identical;
- the child runs in its own process group / Job Object with the memory, CPU, process and output caps applied;
- the socket and DNS guard is prepended to the submitted code, before the model's own code;
- the environment is an allowlist, and `HOME` points at the sandbox's scratch directory — never the server
  user's home, which holds the credentials;
- `TRIBOS_SANDBOX_SAGE_ENABLED=off` removes the tools entirely, and `TRIBOS_SANDBOX=off` overrides it;
- the Sage registry entries carry the `executes_code` capability tag, so approval, planner filtering and the
  request-level toggle treat them as code execution by tag, not by name;
- WSL mode is **off by default** (`TRIBOS_SANDBOX_SAGE_ALLOW_WSL=on` to opt in): WSL is a separate kernel, so
  the Python-level guards do not reach into it. Discovery and execution agree: a SageMath that is only
  reachable through WSL is reported as *unavailable* unless the opt-in is set, so the tools are never offered
  and then refused on every call.

### Per-run caches, not shared ones

Each run gets its **own** `MPLCONFIGDIR` inside its own temporary directory. A shared font cache was a
cross-run poisoning path: one run could leave a file the next run read. The per-run directory is removed with
the rest of the run directory.

## Backend modes

`TRIBOS_SANDBOX_BACKEND` chooses how the code runs:

| Mode | What it does | Boundary |
|---|---|---|
| `container` | Runs the code in `TRIBOS_SANDBOX_IMAGE` via Docker or Podman. | **OS-level boundary.** Fails closed when no runtime is available. |
| `subprocess` | Runs the code in a hardened child process on the host. | Defence in depth only. Not a boundary against a determined attacker. |
| `auto` (default) | Container when a runtime and the image are available, otherwise the subprocess backend. | Depends on the host. |

The container backend (`tribos/agentic/sandbox/container.py`) starts each run with:

```
--network none
--read-only
--tmpfs /tmp:rw,nosuid,nodev,size=<tmp_mb>m
--tmpfs /work:rw,nosuid,nodev,size=<work_mb>m
--memory <memory_mb>m
--cpus 1.0
--pids-limit <max_processes>
--cap-drop ALL
--security-opt no-new-privileges
--user 65534:65534
--mount type=bind,src=<inputs>,dst=/inputs,readonly
--mount type=bind,src=<io>,dst=/io,readonly
--mount type=bind,src=<out>,dst=/out
```

The inputs are mounted read-only, so the code can read the attached files but cannot change them; the work
directory is a tmpfs with a size quota, so the write budget is enforced by the kernel rather than by a check.
The child runs as uid 65534 (nobody), which is not the owner of anything on the host.

The host-to-container channel is split in three, each with its own trust level:

| Mount | Direction | Mode |
|---|---|---|
| `/inputs` | host → container | read-only: the attached files. |
| `/io` | host → container | read-only: the bootstrap, the config and the submitted code cell. The code cannot rewrite its own policy or its own source. |
| `/out` | container → host | the only writable mount: the result file. |

Only `/out` is writable by the container's uid, and it is a fresh directory inside the run's own temporary
tree, removed with the run.

In `auto` mode the runtime probe is cached. When the subprocess backend is used because no container runtime was
found, the run is still bounded by the in-process limits — but it is **not** an OS-level boundary, and in
production it should not be relied on.

### Strict mode and degraded mode

- **Strict mode** (`TRIBOS_SANDBOX_STRICT_LIMITS=1`): a run whose resource limits could not be applied **fails**
  instead of continuing. It also refuses the subprocess backend unless
  `TRIBOS_SANDBOX_ALLOW_UNISOLATED=1` is set explicitly.
- **Degraded mode**: when a limit cannot be applied — a Job Object that could not be assigned, an `RLIMIT` that
  could not be set — the run continues with the limits it *did* get, and the report says so in
  `report["limits"]["degraded"]` (a boolean) and `report["limits"]["degraded_reason"]` (a string). The run is
  never silently unbounded: it is always at least bounded by the timeout, the output cap and the process-tree
  kill. Watch this flag in production; a run that reports `degraded` did not get every cap it asked for.

## Production setup

Use the container backend. Any one of these works for the isolation layer:

- **A container** per run (Docker or Podman) — this is what `tribos/agentic/sandbox/container.py` does, with
  `--network none`, `--read-only`, a tmpfs work directory, the dataset mounted read-only, `--memory`/`--cpus`/
  `--pids-limit`, `--cap-drop ALL`, `--security-opt no-new-privileges` and a non-root user. This matches the
  BixBench harness, which runs its agent in a Docker image.
- **gVisor** (`runsc`) as the container runtime, which adds a user-space kernel between the code and the host.
- **firejail** or **bubblewrap** on a single Linux host: `--net=none`, a private /tmp, read-only binds of the
  input files, and seccomp.

Keep the in-process layers as well. They give useful errors back to the model and cut the attack surface.

`docker/compose.yml` keeps the API and the executor separate: the `backend` service holds the credentials and
never executes model-written code; the `sandbox-image` service builds the executor image. The API service itself
is hardened with `read_only`, tmpfs writable paths, `cap_drop: [ALL]`, `no-new-privileges`, a PID limit and
memory/CPU limits.

See `docs/agentic/sandbox-operations.md` for the operational runbook: building and pinning the image, gVisor and
nsjail, interpreting the degraded flag, and what to do when a limit fails.

## Configuration

The server-wide ceilings (all in the `Code sandbox` group of the settings registry, `tribos/config/settings.py`):

| Variable | Default | Meaning |
|---|---|---|
| `TRIBOS_SANDBOX` | `on` | Master switch. `off` closes every model-written execution path. |
| `TRIBOS_SANDBOX_TIMEOUT_S` | 60 | Wall-clock limit per cell, seconds (5–110). |
| `TRIBOS_SANDBOX_MEMORY_MB` | 2048 | Memory limit per cell, MB (256–16384). |
| `TRIBOS_SANDBOX_MAX_OUTPUT_KB` | 256 | Cap on stdout and stderr of one run, KB (16–4096). |
| `TRIBOS_SANDBOX_MAX_DISK_MB` | 256 | Write budget of one run, MB (16–4096). |
| `TRIBOS_SANDBOX_MAX_PROCESSES` | 64 | Process-count cap of one run (1–512). |
| `TRIBOS_SANDBOX_MAX_CONCURRENCY` | 2 | How many sandboxed executions may run at once (1–32). |
| `TRIBOS_SANDBOX_MAX_RESULT_BYTES` | 3000000 | Aggregate cap on one run's result payload (result, tables, figures), bytes. |
| `TRIBOS_SANDBOX_MAX_FIGURES` | 6 | Maximum number of Matplotlib figures captured from one run. |
| `TRIBOS_SANDBOX_BACKEND` | `auto` | `auto`, `subprocess` or `container`. |
| `TRIBOS_SANDBOX_IMAGE` | `tribos-sandbox:local` | The container image to run code in. Pin by digest in production. |
| `TRIBOS_SANDBOX_STRICT_LIMITS` | `false` | Fail a run whose limits could not be applied. |
| `TRIBOS_SANDBOX_ALLOW_UNISOLATED` | `false` | Allow the subprocess backend in strict mode. Development only. |
| `TRIBOS_SANDBOX_SAGE_ENABLED` | `true` | Offer the SageMath tools. `TRIBOS_SANDBOX=off` overrides this. |
| `TRIBOS_SANDBOX_SAGE_TIMEOUT_S` | 120 | Wall-clock limit of one SageMath execution, seconds (10–600). |
| `TRIBOS_SANDBOX_SAGE_ALLOW_WSL` | `false` | Allow SageMath inside WSL, where the Python-level guards do not apply. |

Plus the per-request switch:

| Variable | Default | Meaning |
|---|---|---|
| `agent_options.enable_code_analysis` | `true` | A per-request switch. When false, that request runs **no** server-side Python or SageMath: the planner excludes the code tools, and the gateway refuses direct calls with `forbidden`. |

Values outside the documented range are clamped by the settings registry rather than trusted. `.env.example` and
`docs/configuration.md` are generated from the same registry by `scripts/gen_env_reference.py`.

The analyst phase also needs an agentic framework, a CSV/TSV/h5ad attachment, and a question with analysis
intent (analyse, compute, statistic, correlate, regress, differential, survival, plot, distribution, compare
groups, test whether). When no model is available it does not run model-written code. Instead it runs a fixed
descriptive-statistics script (describe, plus group summaries when a grouping column is obvious). That script
passes the same policy.

## Verification

Two gates prove the boundary from the outside, the way an attacker would try it:

```bash
docker build -f docker/sandbox.Dockerfile -t tribos-sandbox:local .
uv run python scripts/verify_sandbox_boundary.py
```

The script starts the real container backend against the real image and asserts: the code runs, there is no
network route, no name resolution, no host filesystem read, no host secret inside the container, a minimal
environment, a non-root uid, the process cap, the memory cap, the timeout, no leftover directory and no orphan
process. Exit code 0 means the boundary held, 1 means it did not, and **2 means it could not be verified** (no
container runtime) — so a CI job that requires the gate fails rather than passing silently.

`tests/test_feat_sandbox_container.py` covers the same boundary in the test suite, and
`tests/test_feat_sandbox_limits.py`, `tests/test_feat_sandbox_runtime.py`,
`tests/test_feat_sagemath_sandbox.py`, `tests/test_feat_execution_gateway.py` and
`tests/test_feat_sandbox_toggle.py` cover the gateway, the runtime hardening, the Sage path, the request toggle
and the limits. `tests/test_fix_sec.py` carries the `SEC-8` … `SEC-15` regression ledger for the new invariants.

## Known gaps

- Native code in allowed packages (numpy, scipy, h5py, numba) can do anything the OS lets the process do. In
  the subprocess backend that is still the host's OS.
- A library function that writes files internally, or that evaluates strings, is outside what the AST can see.
- The SageMath backend runs in the subprocess backend; the container image does not yet carry SageMath.
- Memory and CPU limits are best effort on Windows when the Job Object cannot be assigned. The run reports
  `degraded` in that case; strict mode turns it into a failure.

## References

- Greshake, K. et al. 2023. Not What You've Signed Up For: Compromising Real-World LLM-Integrated Applications
  with Indirect Prompt Injection. AISec '23. arXiv:2302.12173, doi:10.1145/3605764.3623985.
- Hines, K. et al. 2024. Defending Against Indirect Prompt Injection Attacks With Spotlighting. arXiv:2403.14720.
- Wang, X. et al. 2024. Executable Code Actions Elicit Better LLM Agents (CodeAct). ICML 2024. arXiv:2402.01030.
- Huang, K. et al. 2025. Biomni: A General-Purpose Biomedical AI Agent. bioRxiv. doi:10.1101/2025.05.30.656746.
- Mitchener, L. et al. 2025. BixBench. arXiv:2503.00096.
- Hong, S. et al. 2024. Data Interpreter: An LLM Agent For Data Science. arXiv:2402.18679.
