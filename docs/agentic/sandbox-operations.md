# Sandbox operations runbook

The operational companion to `docs/agentic/sandbox-security.md`. That page describes what the sandbox defends
against and how it is built. This one covers running it: building and pinning the executor image, choosing an
isolation layer, reading the degraded flag, and what to do when a limit fails.

## 1. The shape of a deployment

Two containers, never one:

```
┌───────────────────────────┐        ┌────────────────────────────────────┐
│ backend (the API)         │        │ sandbox image (the executor)       │
│                           │        │                                    │
│ holds the credentials     │        │ holds only the scientific stack    │
│ serves the API            │        │ runs model-written code            │
│ NEVER runs model code ────┼──never─▶  --network none, read-only root    │
└───────────────────────────┘        └────────────────────────────────────┘
```

The API process holds the API keys, the upload store and the user's sessions. It must never execute
model-written code. `docker/compose.yml` expresses this: the `backend` service is hardened (`read_only`,
tmpfs writable paths, `cap_drop: [ALL]`, `no-new-privileges`, a PID limit, memory and CPU limits), and a
separate `sandbox-image` service builds the executor image.

```bash
docker compose build sandbox-image
docker compose up -d backend web
```

## 2. Building and pinning the executor image

The image is built from `docker/sandbox.Dockerfile` against `docker/sandbox-requirements.txt`: the scientific
stack only (numpy, pandas, scipy, sympy, matplotlib, h5py, pyarrow, networkx, mpmath, pint). It deliberately
does **not** contain fastapi, uvicorn, openai, httpx, torch, transformers or langchain — the executor has no
business talking to a model or an API, and a smaller image is a smaller attack surface. It has no shell
tooling either (no curl, wget, git or ssh).

```bash
docker build -f docker/sandbox.Dockerfile -t tribos-sandbox:local .
```

**Pin it by digest in production.** A tag is mutable; a digest is not.

```bash
docker inspect --format='{{index .RepoDigests 0}}' tribos-sandbox:local
# tribos-sandbox@sha256:8f2c...
```

```bash
TRIBOS_SANDBOX_IMAGE=tribos-sandbox@sha256:8f2c...
```

Rebuild on a schedule (monthly is a reasonable default) to pick up upstream security fixes, and re-run the
boundary gate against the new digest before promoting it:

```bash
docker build -f docker/sandbox.Dockerfile -t tribos-sandbox:staged .
TRIBOS_SANDBOX_IMAGE=tribos-sandbox:staged uv run python scripts/verify_sandbox_boundary.py
```

**Rebuild and re-verify whenever** `docker/sandbox-requirements.txt`, `uv.lock` or the Dockerfile changes. The
CI `sandbox-boundary` job does exactly this on every change under `docker/**`.

## 3. Choosing the isolation layer

`TRIBOS_SANDBOX_BACKEND` selects the backend:

| Value | Use when | Fails when |
|---|---|---|
| `container` | Production. The code must not share a trust domain with the host. | The runtime or the image is missing: the run is refused. |
| `subprocess` | Local development on a machine without a container runtime. | Never fails, but **is not a boundary**. |
| `auto` | The default. Container when usable, otherwise the subprocess backend. | Falls back silently to the subprocess backend. |

`auto` is a convenience, not a policy. **Set `TRIBOS_SANDBOX_BACKEND=container` in production** so that a
missing runtime is a hard, visible failure instead of a quiet downgrade to an unisolated backend.

### gVisor

gVisor (`runsc`) puts a user-space kernel between the container and the host, which cuts the syscalls a
compromised native extension can make. It is the single highest-value hardening step after the container itself.

```bash
docker run --runtime=runsc --rm hello-world
```

Configure the daemon so the sandbox images use it by default, or set the runtime per invocation. The
container backend invokes the `docker`/`podman` CLI, so the runtime has to be the daemon's default rather than a
per-run flag.

### nsjail

nsjail is a namespace- and seccomp-based jail for a single process rather than a container runtime. It is a
good fit when you want a boundary without a container daemon, but it needs its own integration: the container
backend does not drive nsjail today. Use it behind a custom backend, not as a drop-in.

### On macOS and Windows

Container runtimes are a Linux feature. On macOS, Docker Desktop provides them through its VM. On Windows,
they need WSL2. Where no runtime is available the subprocess backend is the fallback, and the SageMath WSL
mode (`TRIBOS_SANDBOX_SAGE_ALLOW_WSL`) is a separate concern entirely — see the security page.

### SageMath through WSL

On Windows, SageMath is often installed inside WSL rather than natively. That is a **separate kernel**: the
AST policy, the environment scrub and the network guard are applied by a Python process on the Windows side,
and they do not reach into WSL. The WSL SageMath path is therefore **off by default**, and
`TRIBOS_SANDBOX_SAGE_ALLOW_WSL=1` is the explicit acceptance of that risk.

Discovery follows the same rule: with the opt-in off, a WSL-only SageMath is reported as unavailable, so the
tools are not offered and then refused on every call. If you turn the opt-in on, treat the WSL SageMath path
as an unisolated execution path and do not expose it on a shared host.

## 4. Strict mode

```bash
TRIBOS_SANDBOX_STRICT_LIMITS=1
```

Two things change:

1. A run whose resource limits could not be applied **fails** instead of continuing degraded.
2. The subprocess backend is **refused**, unless `TRIBOS_SANDBOX_ALLOW_UNISOLATED=1` is set explicitly. That
   override exists for development only; in production, treat it as a configuration error.

## 5. Reading the degraded flag

Every report carries the limits that actually applied:

```json
{
  "status": "ok",
  "limits": {
    "backend": "container",
    "engine": "python",
    "timeout_s": 60,
    "memory_mb": 2048,
    "max_output_kb": 256,
    "max_disk_mb": 256,
    "max_processes": 64,
    "degraded": false,
    "degraded_reason": ""
  }
}
```

`degraded: true` means **at least one limit was not applied**. The usual causes:

| Symptom | Cause | Response |
|---|---|---|
| `degraded` on Windows, `memory` missing | The Job Object could not be assigned to the child (usually a session or privilege boundary). | Run the API under a job-object-capable service account, or accept the timeout and the output cap as the only bounds. In production prefer the container backend, where the limit is a cgroup limit and cannot fail this way. |
| `degraded` on Linux, `memory` missing | `RLIMIT_AS` was refused by the kernel or the rlimit was already lower. | Check `/proc/<pid>/limits`. The container backend makes this moot: the memory limit there is a cgroup limit. |
| `degraded`, `max_processes` missing | `RLIMIT_NPROC` is per-uid, so it counts every process of the uid, not just the sandbox's. | Expected when the API and the sandbox share a uid. The container backend's `--pids-limit` is per-container. |

Alert on `degraded: true`. A degraded run is still bounded by the timeout, the output cap and the process-tree
kill, but a memory or process cap that did not apply is a real gap.

The gateway log line carries the same information:

```
Sandbox execution: engine=python backend=container status=ok seconds=1.204 timeout_s=60 memory_mb=2048
```

It never carries the code and never carries a secret.

## 6. When a limit fails

The order of response, from cheapest to most drastic:

1. **A single run reports `degraded`.** Nothing to do for one run; check the table above. If it recurs across
   runs, the deployment is misconfigured — fix it before it becomes a pattern.
2. **Runs start hitting the timeout.** Check whether the workload really needs longer (`TRIBOS_SANDBOX_TIMEOUT_S`,
   max 110 s) or whether the model is looping. The analyst phase has a bounded loop of its own; a timeout storm
   usually means the model's plan is not converging, not that the limit is too tight.
3. **The memory cap trips repeatedly.** Raise `TRIBOS_SANDBOX_MEMORY_MB` for a specific workload, but check
   first whether the code is loading a whole dataset into a DataFrame when it could stream it. The dataset
   preview is already row- and column-bounded.
4. **The disk budget trips.** The write budget is real: the code is producing more than it should. Raise
   `TRIBOS_SANDBOX_MAX_DISK_MB` only with a reason.
5. **The concurrency ceiling is hit.** `TRIBOS_SANDBOX_MAX_CONCURRENCY` (default 2) bounds how many runs may be
   in flight; the next one reports `busy` rather than queueing without bound. Raise it if the host has the
   memory for it: each concurrent run can take the full `TRIBOS_SANDBOX_MEMORY_MB`.

The container backend enforces the memory, disk and process limits in the kernel, so those cannot be "failed"
the way an in-process `setrlimit` can — the container simply dies, and the report says the run ended without a
result.

## 7. The release gate

```bash
docker build -f docker/sandbox.Dockerfile -t tribos-sandbox:local .
uv run python scripts/verify_sandbox_boundary.py
```

Exit codes:

| Code | Meaning |
|---|---|
| 0 | The boundary held. Every check passed. |
| 1 | The boundary did not hold. The output names the check that failed. |
| 2 | The boundary could not be verified (no container runtime, or the image is missing). |

Run it before every release that changes the image, the Dockerfile, the requirements, the bootstrap or the
container backend. Exit code 2 must fail a CI job that requires the gate — a missing runtime is not a pass.

## 8. Routine checklist

- [ ] `TRIBOS_SANDBOX_BACKEND=container` in production.
- [ ] `TRIBOS_SANDBOX_IMAGE` pinned by digest.
- [ ] `TRIBOS_SANDBOX_STRICT_LIMITS=1`, and `TRIBOS_SANDBOX_ALLOW_UNISOLATED` unset.
- [ ] The API service has no route to the executor's writable paths, and the executor has no credentials.
- [ ] `verify_sandbox_boundary.py` runs in CI and exits 0.
- [ ] Alerts on `degraded: true`.
- [ ] The image is rebuilt and re-verified on a schedule.
- [ ] `TRIBOS_SANDBOX_SAGE_ALLOW_WSL=off` unless the WSL SageMath path is deliberately wanted.
