# Tribos Scientific Execution, Memory & Worker Hardening Report

**Date:** 28 October 2026  
**Scope:** Tribos Scientific Computing Platform, Real Python Execution Worker (Calcula), Mem0 Memory Integration, Multi-Agent Orchestration, Verification Engine, Engineering Calculators, and Next.js Web UI.

---

## 1. Executive Summary & Findings Matrix

Following a comprehensive audit and verification review of Tribos, all 11 problem areas have been addressed with architectural fixes, real tool and phase integration, and verified test suites.

| Section | Area | Identified Problem | Solution Implemented | Verification Result |
|:---|:---|:---|:---|:---:|
| **1** | **Mem0 Save Path** | `ProjectConsolidatePhase` called `enqueue(action=..., content=...)` instead of `operation` and `payload`; called nonexistent `dispatch_pending()`; silent failure. | Corrected consolidation queue interface (`operation="add"`, structured payload with typed provenance). Awaited `process_pending()`. Accurate UI progress (`Mem0: X stored` or `Mem0: X queued`). | **Verified** (`test_consolidation_and_recall_phases_with_mem0`) |
| **2** | **Worker Application Wiring** | `PythonExecutionWorker` implemented but never called by application tool execution. | Routed `_run_python_impl` in `tribos/extensions/sandbox.py` directly through `worker.execute_job_sync()`. Bound authenticated `SandboxScope` (`user_id`, `project_id`, `task_id`, `run_id`). Added `calcula_run_python` and `analysis_run_python` to `TOOL_RENDERERS` in `stem_evidence.py` to deliver outputs and validation status to the answer writer. | **Verified** (`test_worker_tool_execution_integration`, `test_evidence_rendering_includes_validation_and_bundle`) |
| **3** | **Execution Isolation** | `container_engine` was unused; claimed container isolation while running subprocess. | Implemented responsive engine detection (`info` ping). If `docker` or `podman` is explicitly configured but unavailable, worker explicitly returns `status="unavailable"`. Subprocess mode is accurately labeled `isolation="subprocess (development)"` in runtime manifest. | **Verified** (`test_worker_container_engine_refusal_when_unavailable`) |
| **4** | **Scientific Validation** | Scalar results passed required keys; `"garbage"` standard error passed; analytical failure logged warning while validation passed. | Strictly reject non-dicts for required keys; reject non-numeric, non-finite, and negative standard errors; fail analytical reference comparison on tolerance violation or calculation errors; enforce RHS evaluations and initial conditions. | **Verified** (`test_worker_validation_rejections_and_strictness`, `test_worker_endpoint_match_alone_fails_when_rhs_evals_or_initial_conds_violated`) |
| **5** | **Cache Identity & Reuse** | Cache key omitted user, project, contract; hashed artifact IDs instead of contents. | Overhauled `_compute_cache_key()` to hash `user_id`, `project_id`, `code_h`, `params_h`, actual input file SHA-256 byte hashes, `contract_h`, and `runtime_digest`. Unseeded stochastic runs bypass cache. Isolated cached objects via `copy.deepcopy()`. Bounded LRU to 256 entries. | **Verified** (`test_worker_cache_scope_isolation`, `test_worker_changed_file_contents_under_same_id_causes_cache_miss`, `test_worker_cache_mutation_isolation`) |
| **6** | **Downloads & Bundles** | `content_base64` was hex-encoded; bundles wrote original code even when repaired code ran; CSV rounded to 12 digits. | Encoded ZIP bytes via `base64.b64encode().decode("ascii")`. Bundles package `executed_script.py`, `original_script.py` (if repaired), and `repair_log.json`. CSV trajectory exports formatted with full IEEE-754 17-digit precision (`.17g`). | **Verified** (`test_reproducibility_bundle_base64_and_extraction`, `test_worker_targeted_code_repair_and_provenance`) |
| **7** | **Memory Ownership** | Operations allowed omitted user IDs and lacked mandatory project scope checks. | Enforced non-empty `user_id` and `project_id` across `add`, `search`, `get`, `get_all`, `update`, `delete`, `history`, `invalidate`. Cross-user or cross-project access strictly raises `PermissionError`. Validated queue operations. | **Verified** (`test_mem0_user_and_project_isolation`) |
| **8** | **Authoritative Invalidation** | `invalidate()` only updated text in vector DB; invalid memories still returned by search. | Built authoritative SQLite companion store (`companion.db`) tracking lifecycle status (`active`, `invalidated`, `expired`), timestamps, reasons, and supersessions. Automatically filters non-active memories from search and get. | **Verified** (`test_mem0_authoritative_invalidation_and_history`) |
| **9** | **Durable Queue Delivery** | Pending events read without atomic claims; lack of application lifecycle management. | Added transactional leasing (`claim_batch`, `lease_id`, `lease_expires_at`) with lease expiration reclamation in `DurableMemoryQueue`. Integrated background dispatcher startup and shutdown into FastAPI `_lifespan` in `app/backend/main.py`. | **Verified** (`test_durable_queue_outage_buffering_and_atomic_claims`) |
| **10** | **Worker Lifecycle** | Pending submissions were unbounded; cancellation did not terminate process tree. | Implemented admission bounds (`MAX_PENDING_JOBS = 32`) with `status="overloaded"` response. Connected `on_spawn` callback to track active processes; `cancel_job(job_id)` terminates process tree via `_kill_tree()`. Added `shutdown()` to `_lifespan`. | **Verified** (`test_worker_queue_overload_rejection`, `test_worker_running_cancellation`) |
| **11** | **Honest Tests & Configuration** | Production code used `PYTEST_CURRENT_TEST` hacks; accidental external calls to Hugging Face. | Removed implicit test branching from production code. Registered `TRIBOS_MEM0_EMBEDDER_PROVIDER="mock"` and `TRIBOS_MEM0_LLM_PROVIDER="mock"` as safe defaults in `settings.py`. Regenerated documentation with `gen_env_reference.py`. | **Verified** (`gen_env_reference.py --check`, offline test socket guards) |

---

## 2. Actual Application Execution Paths Changed

1. **Calcula Tool Path (`tribos/extensions/sandbox.py`):**
   - `_run_python_impl()` now resolves authenticated `SandboxScope` (`user_id`, `project_id`, `task_id`, `run_id`).
   - Delegates directly to `get_python_worker().execute_job_sync()`.
   - Injects execution results, structured tables, Matplotlib figures, downloads, reproducibility bundle, and independent validation report into `ToolResult.data`.
2. **Evidence & Prompting Path (`tribos/agents/stem_evidence.py`):**
   - Registered `"calcula_run_python"` and `"analysis_run_python"` in `TOOL_RENDERERS`.
   - In `render_calcula()`, added XML evidence nodes for `<validation>` and `<reproducibility_bundle>` so the answer writing model receives execution outcomes and verification checks directly.
3. **Sandbox Scope (`tribos/agentic/sandbox/__init__.py` & `runner.py`):**
   - Extended `SandboxScope` and `bound_scope` with `project_id`, `task_id`, and `run_id`.
   - Added `on_spawn` callback hook to `run_code()` for process tracking and cancellation propagation.
4. **Backend Application Lifecycle (`app/backend/main.py`):**
   - `_lifespan()` starts the background memory queue dispatcher (`queue.start_background_dispatcher(interval_s=2.0)`) on startup.
   - On shutdown, gracefully stops the dispatcher (`queue.stop_background_dispatcher(timeout_s=3.0)`) and shuts down the Python execution worker (`worker.shutdown()`).
5. **Memory Consolidation Phase (`tribos/agentic/project_memory.py`):**
   - Corrected interface to `DurableMemoryQueue.enqueue()` (`operation="add"`, `payload={"content": ..., "provenance": ...}`).
   - Dispatches pending events via `process_pending()`.
   - Emits accurate UI step details and artifact statuses.

---

## 3. Test Execution Summary

### Feature Test Suites
- **Python Execution Worker (`tests/test_feat_python_worker.py`):** **15 passed in 14.16s**
  - Runtime metadata verification & deterministic digest.
  - Scientific execution with Matplotlib figure capture (PNG and SVG).
  - Classical RK4 damped oscillator acceptance demonstration (201 time levels, 800 evaluations, analytical match).
  - Validation strictness (scalar rejection on required keys, invalid/negative SE, analytical error).
  - Expected RHS evaluations and initial conditions verification.
  - Cache scope isolation (user, project, contract, input content, stochastic bypass).
  - File content hash change causing cache miss under same ID.
  - Cache result mutation isolation.
  - Queue admission bound overload rejection (`MAX_PENDING_JOBS = 32`).
  - Active process cancellation (`cancel_job`).
  - Reproducibility bundle Base64 decoding, ZIP extraction, and full precision.
  - Code repair provenance tracking (`executed_script.py`, `original_script.py`, `repair_log.json`).
  - Container engine availability check and explicit refusal when unavailable.
  - Application tool execution integration via `run_calcula_python`.
  - Evidence XML rendering with validation and bundle metadata.
- **Mem0 Integration (`tests/test_feat_mem0_integration.py`):** **5 passed in 6.87s**
  - Full CRUD lifecycle and persistence.
  - Cross-user and cross-project isolation (`PermissionError`).
  - Authoritative companion store invalidation filtering from search/get.
  - Durable queue persistence, transactional leasing, and dispatcher thread lifecycle.
  - End-to-end `ProjectConsolidatePhase` and `ProjectRecallPhase` execution demonstrating durable event delivery and recall across sessions in the same project.
- **Combined Feature Run:** **20 passed in 17.63s**
- **Web Frontend Suite (`cd web && npm test`):** **209 passed in 1.64s**

### CI Blocking Gates
- `uv run ruff check tribos app tests scripts --select F,E9`: **Passed** (0 errors in 0.5s).
- `uv run bandit -c pyproject.toml -r tribos app --severity-level high`: **Passed** (0 high-severity issues across 81,170 lines in 12s).
- `uv run python scripts/gen_env_reference.py --check`: **Passed** (181 variables documented and synchronized).
- `cd web && npm run typecheck`: **Passed** (0 TypeScript errors).
- `cd web && npx eslint src`: **Passed** (0 errors).
- `cd web && npx next build`: **Passed** (Next.js 16.4.3 production build succeeded in 3.1s).

---

## 4. Configuration & Startup Instructions

### Configuration Settings
Set these environment variables (or configure in `.env`):

```bash
# Python Execution Worker (Calcula)
TRIBOS_PYTHON_WORKER_CONCURRENCY=4          # Maximum concurrent execution jobs
TRIBOS_PYTHON_WORKER_TIMEOUT_S=60.0         # Default job execution timeout in seconds
TRIBOS_PYTHON_WORKER_MEMORY_MB=2048         # Memory budget per job in MB
TRIBOS_PYTHON_WORKER_CONTAINER_ENGINE=auto  # auto, subprocess, docker, podman

# Mem0 Memory Integration
TRIBOS_MEM0_ENABLED=1                       # 1 = enabled, 0 = disabled
TRIBOS_MEM0_STORAGE_DIR=.tribos_memory/mem0 # Local storage root for Qdrant and SQLite
TRIBOS_MEM0_EMBEDDER_PROVIDER=mock          # mock (default, offline safe), huggingface, openai, gemini
TRIBOS_MEM0_LLM_PROVIDER=mock               # mock (default, offline safe), openai, gemini, langchain
```

### Starting the Services

```bash
# 1. Python Backend
uv sync --extra dev
uv run uvicorn app.backend.main:app --host 127.0.0.1 --port 8000 --reload

# 2. Frontend UI
cd web
npm install
npm run dev    # UI available on http://localhost:3000
```

---

## 5. Remaining Limitations

1. **Container Daemon Requirement for Production Isolation:** On host systems where Docker or Podman CLI binaries are present but the daemon/VM is stopped (e.g., WSL2 Podman VM inactive), `container_engine=auto` automatically falls back to isolated subprocess mode labeled `"subprocess (development)"`. For strict production container enforcement, configure `TRIBOS_PYTHON_WORKER_CONTAINER_ENGINE=docker` or `podman`; the worker will reject execution if the daemon is unavailable.
2. **Third-Party Model Embeddings in Air-Gapped Environments:** Live Mem0 embedding providers (`huggingface`, `openai`) require external network connectivity or local model weights. The default provider is pinned to `"mock"`, which operates hermetically and deterministically in offline environments.
