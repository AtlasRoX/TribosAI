# Scientific Software Complete Audit Report

## 1. Audit Metadata

| Item | Value |
|---|---|
| Repository | `X:\tribois` (Tribos), package version 1.49.1 (`pyproject.toml`) |
| Branch / HEAD | `feat/agentic-engineering-harness-and-memory` @ `16d0302` |
| Working tree | ~136 modified or untracked files; **the working tree as on disk was audited**, not HEAD |
| Audit date | 2026-10-30 |
| Auditor | Claude Code (Opus 5.5), single-session audit (no sub-agents completed; see §48) |
| Runtime | Windows 11, Python 3.12 (`.venv`), Node (web `node_modules` present) |
| Application changes | **None.** Only this file was created. Scratch scripts and logs live outside the repository. |

## 2. Executive Assessment

**Can this software be trusted to produce correct, reproducible, secure, understandable and scientifically
defensible results?** *Partially.* The answer differs by subsystem:

- **Trustworthy with evidence:**
  - the core numerical and engineering calculators (`tribos/engcalc`, the Monte Carlo integrator, Physis
    constants and units);
  - authentication and the main data routes;
  - the sandbox's policy layer;
  - run provenance;
  - the math agent's own status labels, in the probes run.
- **Not trustworthy — the engineering "substrate" layer** (`tribos/substrate`, `tribos/memory/semantic.py`,
  `app/backend/routers/harness.py`), added on this branch. Executed evidence shows it:
  - certifies any spherical pressure vessel as ASME-compliant without calculating anything (AUDIT-001);
  - fabricates CAD mass properties (AUDIT-002);
  - reports "FEA results fully verified against 14-gate criteria" for all-zero inputs, with only 5 gates
    implemented (AUDIT-003);
  - exposes every project's threads, revisions, sign-offs and costs to any authenticated user (AUDIT-004).

  Both the REST API and the LLM tool registry can reach these functions.
- **Verification-status integrity has gaps:**
  - the written-answer checker accepts false real-domain identities such as `√(x²) = x` (AUDIT-005);
  - the derivation card labels every *executed* math step "Verified", including a step whose own output says
    `verified: False` (AUDIT-006);
  - curve fits are `verified: true` whenever the RMSE is finite, and report standard error 0 when the
    covariance is undefined (AUDIT-007).
- **Security posture:** sound at the HTTP layer. However:
  - by default, model-written code runs without an OS isolation boundary, including inside the shipped Docker
    API container (AUDIT-008);
  - the locked Python environment carries 385 published advisories across 41 packages, including the parsers
    used on uploads (pypdf, Pillow) and the JWT library (AUDIT-009).
- **Quality gates:** the Python suite is **red: 10 failed, 2142 passed, 28 skipped**. This contradicts the
  AGENTS.md baseline of "0 failed".

**Bottom line:**
- Results from `engcalc`, Dynamis ODE/Monte Carlo, Physis, and math-agent answers marked `verified` are supported
  by evidence.
- Results from the substrate tools (standards compliance, materials at temperature, geometry, CAE review) must not
  be trusted.
- Neither "Verified" pills on derivation steps nor `verified` on fits should be read as independent verification.

## 3. Audit Scope and Method

1. Reconstructed the architecture from AGENTS.md, README, `pyproject.toml`, the router mount list in
   `app/backend/main.py`, and a full file and line inventory (§4).
2. Ran the project's own gates (§47): pytest, ruff, bandit, the env-reference check, web typecheck, eslint, web
   tests, pip-audit and npm audit.
3. Read the highest-risk code: authentication and middleware, every route's authorization, the sandbox
   selection and policy, the engineering substrate, standards and materials, Dynamis fitting, the math-claim
   checker, and the UI status rendering.
4. **Executed** suspected defects against the real functions, with adversarial and known-answer inputs. Every
   CONFIRMED finding below has an executed reproduction or an unambiguous code path.
5. Used repository-wide grep for breadth: callers, dead code, SQLite concurrency controls, XSS sinks, CI gating,
   biomedical leftovers.

The method was deliberately *depth on risk, breadth by grep*. Reading every file in full was not done (see §46
and §48). Findings are limited to what was verified.

## 4. Repository Inventory

Tracked plus untracked source, excluding `.venv`, `node_modules`, caches and binaries. Line counts include
blanks and comments.

| Path | Type | Actual purpose (from code) | Lines | Entry/exit role | Status |
|---|---|---|---:|---|---|
| `app/backend/` | FastAPI | API: chat and streaming, jobs, runs, projects, datasets, export, MCP, A2A, vision, simulate, harness | 4,137 | HTTP entry | COMPLETE (harness: see AUDIT-004/017) |
| `tribos/agentic/` | Python | Router, planner, plan DAG, executor, specialists, topologies, NLI, confidence, jobs, memory adapters, sandbox | 19,995 | Core pipeline | PARTIAL (not read in full) |
| `tribos/agents/` | Python | Classic orchestrator, query planning, evidence rendering, prompts, drafting, verification, finalize | 14,617 | Core pipeline | UNVERIFIED in depth |
| `tribos/axiom/` | Python | Symbolic engine (SymPy), math agent, problem parser, independent verifier | 10,649 | Scientific | COMPLETE (probed) |
| `tribos/verify/` | Python | Citation grounding, math-claim audit, units audit, Lean runner | 7,372 | Verification | PARTIAL (AUDIT-005) |
| `tribos/dynamis/` | Python | ODE/PDE/fit/root/Monte Carlo (SciPy) | 3,684 | Scientific | COMPLETE with defects (AUDIT-007) |
| `tribos/physis/` | Python | CODATA constants (via scipy), Pint units, uncertainty | 1,750 | Scientific | COMPLETE |
| `tribos/engcalc/` | Python | Structural, fatigue, thermofluid, electrical calculators with validity checks | 1,650 | Scientific | COMPLETE |
| `tribos/scientific/` | Python | Scientific execution contracts, worker, assembly | 2,454 | Scientific | UNVERIFIED |
| `tribos/substrate/` + `tribos/memory/semantic.py` | Python | Materials catalogue, ASME clause check, STL inspector, CAE gates | ~600 | REST + LLM tool | **BROKEN / MOCKED** (AUDIT-001/002/003/010) |
| `tribos/harness/` | Python | Checkpoints, cost ledger, HITL sign-off, tracing | 748 | REST only | **PLACEHOLDER** (AUDIT-017) |
| `tribos/memory/` | Python | Threads, turns, revisions, episodic/semantic memory | 1,398 | REST only | BACKEND-ONLY |
| `tribos/archivon/`, `tribos/sources/`, `tribos/papers/` | Python | Literature clients, identifiers, retraction status, paper extraction | ~3,900 | Data ingestion | UNVERIFIED in depth |
| `tribos/provenance/` | Python | Run manifest, run store, source versions, rerun | 2,150 | Provenance | COMPLETE |
| `tribos/export/` | Python | PDF/DOCX/notebook/bundle export | 3,370 (+fonts) | Output | UNVERIFIED |
| `tribos/evals/` | Python | Eval harness, cassettes, scoring | 4,947 | Dev tooling | UNVERIFIED |
| `tribos/utils/`, `tribos/datasets/`, `tribos/tools/` | Python | HTTP, LLM factory, project and research stores, dataset store/validators, tool registry | ~8,800 | Infrastructure | PARTIAL |
| `web/src/` | Next.js 16 / React 19 | Chat UI, result cards, services, local persistence | ~25,000 | UI | PARTIAL (AUDIT-006) |
| `tests/` | pytest | ~170 test files | 35,937 | Verification | 10 failing (AUDIT-011) |
| `web/tests/` | node:test | 31 files | — | Verification | 209/209 pass |
| `.github/workflows/` | CI | 11 workflows | 1,193 | CI/CD | PARTIAL (AUDIT-019) |
| `docker/` | Infrastructure | API, web and sandbox images; compose | 324 | Deployment | PARTIAL (AUDIT-008) |
| `scripts/` | Python/PS | Env-doc generator, calibration, sandbox boundary check, archive | 1,306 | Tooling | UNVERIFIED |

## 5. Technology and Runtime Architecture

- **Backend:**
  - Python ≥3.12, FastAPI 0.143, uvicorn, Pydantic 2.11.
  - Scientific stack: SymPy 1.14, SciPy 1.16.2, NumPy 1.26.4, Pint 0.26.2, mpmath.
  - Models: LangChain 0.3 / OpenAI SDK, torch 2.8, transformers 4.55 (NLI and embeddings), mem0ai with embedded
    Qdrant.
  - Storage: SQLite.
- **Frontend:** Next.js ^16.4, React 19.3, react-markdown 10, KaTeX 0.19 / rehype-katex.
- **Isolation:** container backend (docker/podman, `--network none`, non-root) *or* subprocess backend (AST
  policy, scrubbed environment, Windows Job Object or POSIX rlimits). Optional SageMath and Lean.
- **Pinning:** Python dependencies are exact-pinned in `pyproject.toml` with `uv.lock`; the web uses caret
  ranges with `package-lock.json`.

## 6. Architecture Reconstruction

```text
Browser (web/src/app/page.tsx, 3,381 lines) ── fetch/SSE + Bearer ──▶ SecurityMiddleware ▶ CORS ▶ FastAPI routes
  main.py: /api/chat, /api/chat/stream, /api/memory/*, /api/route/preview ...
  routers: jobs, agent_runs, projects (RBAC), datasets, export/runs (rerun), mcp, a2a, vision, simulate, harness
        │
        ▼
Framework router (tribos/agentic/router.py) ─▶ classic orchestrator (tribos/agents/*) or agentic topologies
        │                                       (plan-execute, supervisor, swarm, debate)
        ▼
Tool registry (tribos/tools/registry.py) ─▶ engines: axiom | dynamis | physis | engcalc | archivon | sandbox | substrate
        │
        ▼
Evidence renderer (tribos/agents/stem_evidence.py) ─▶ LLM synthesis ─▶ verification (verify/verifier.py, math_claims.py)
        │
        ▼
execution_artifacts{key: payload} ─▶ web result cards (web/src/components/**) ; RunRecorder ─▶ run manifest (provenance)
```

Architectural observations:

- **Parallel, divergent engineering stacks.** `tribos/engcalc` (validity ranges, steel-only rules enforced,
  warnings) and `tribos/substrate` + `tribos/memory/semantic.py` (no validity checks, default-to-pass) both
  compute engineering quantities. Both are registered as tools. Only the second is used by the harness API.
- **Unintegrated subsystem.** The harness API (`app/backend/routers/harness.py`) is mounted, but it is neither
  wired into the pipeline nor used by the web UI (AUDIT-017). Its `project_id` namespace is separate from the
  RBAC project store (AUDIT-004).
- **Two parallel persistence systems for conversations.** `tribos/utils/memory/research_memory.py` is
  user-scoped and used by `/api/memory/*`. `tribos/memory/engine.py` is unscoped and used by
  `/api/harness/threads/*`.

## 7. Complete Data Flow

**User question to answer (classic path):**
1. `page.tsx` builds a request with the Bearer token.
2. `POST /api/chat/stream` (`main.py:933`) passes through `SecurityMiddleware` (`security.py:157`):
   loopback/Host/Origin checks and body limits.
3. `get_current_user` (`auth.py:98`) resolves the user.
4. The `ChatRequest` validators run (`main.py:282-311`).
5. The orchestrator plans the query and gathers evidence (`orchestration/gather.py`). STEM tools run through the
   registry with per-tool timeouts. Results are rendered as XML evidence (`stem_evidence.py`).
6. The LLM drafts the answer. `math_claims.audit_answer` re-checks the equations; section repair and finalize
   follow.
7. The result is streamed as SSE: text plus `execution_artifacts`.
8. The browser persists the chat in localStorage (`localStorageService.ts`). The server writes a run manifest.

**Uploads:**
1. `POST /api/datasets` streams the file, enforcing size and extension limits (`datasets.py:75-123`).
2. Validators run; NaN or infinite values are rejected (`validators.py:438`).
3. The dataset store hashes and stores the file.
4. The sandbox can read it only through a user-scoped binding (`sandbox/__init__.py` docstring,
   `resolve_for_user`).

**Harness:** client → `/api/harness/*` → `tribos/memory/engine.py` SQLite (no user scoping) and the
substrate functions. Results go directly back to the caller.

## 8. Scientific Processing Pipeline

| Stage | Inputs | Algorithm | Output | Verification |
|---|---|---|---|---|
| Problem parse | prose/LaTeX | `axiom/problem.py` → `ProblemSpec` | typed spec + ambiguities | parse-fidelity rule |
| Symbolic solve | spec | SymPy strategy ladder | answer + steps | `axiom/verifier.py` level 1 (encodes the question) + level 2 (independent check) |
| ODE simulation | RHS, initial conditions, parameters | `solve_ivp` rtol 1e-8 / atol 1e-10, or fixed RK4 | trajectories, extrema | success flag + optional invariant drift ≤ 1e-4·max(1, \|I₀\|) (`dynamis/engine.py:259-266`) |
| Curve fit | x, y, model | `scipy.optimize.curve_fit` (unweighted) | parameters, SE, R² | `verified = isfinite(rmse)` (**AUDIT-007**) |
| Monte Carlo | integrand, bounds, seed | crude MC, PCG64 | estimate ± SE (ddof = 1) | reference z-score |
| Constants | name | `scipy.constants` (CODATA 2022) | value, unit, uncertainty | n/a |
| Engineering calculators | typed inputs (SI) | textbook correlations | results + validity checks + warnings | built-in range checks |
| Substrate | free numbers | ad-hoc formulas | compliant / verified booleans | **none effective** (AUDIT-001..003) |
| Written-answer audit | final Markdown | numeric comparison; identities sampled at 6 points | passed / failed / inconclusive per statement | **AUDIT-005** |

## 9. Feature Inventory

Chat Q&A (classic + 5 agentic frameworks), the verified math agent, ODE/PDE simulation with an interactive
simulator, curve fitting, Monte Carlo integration, constants and units, engineering calculators, literature
search and citation grounding, retraction status, sandboxed code (Calcula), SageMath, Lean proofs, dataset
uploads, paper reproduction, image/OCR input, report export (PDF/DOCX/notebook/bundle), run manifests and
reruns, background jobs with SSE, HITL approval/steer/skip/cancel, projects (RBAC, memory, files, activity),
MCP server, A2A agent card, and the harness (threads, revisions, checkpoints, sign-off, cost, substrate tools).

## 10. Feature Status Matrix

| Feature | Status | Evidence |
|---|---|---|
| Auth (static tokens / JWT / disabled-loopback) | COMPLETE | `auth.py`, `security.py` read in full |
| Run control (approve/steer/skip/cancel) | COMPLETE | `agent_runs.py:45-49` scopes by owner |
| Jobs | COMPLETE (logic not deeply audited) | `jobs.py:120-144` scope by `user_id` |
| Projects (RBAC) | COMPLETE | `projects.py` role model; app-level cascade delete (`project_store.py:424-428`) |
| Research memory `/api/memory/*` | COMPLETE | `main.py:738-792`, all user-scoped |
| Math agent | COMPLETE | 10 adversarial probes: no false `verified` (§45) |
| Written-answer math audit | PARTIAL | false identity passes (AUDIT-005) |
| ODE simulation | COMPLETE | `engine.py:146-151` rejects failed or non-finite solves |
| Curve fitting | PARTIAL | AUDIT-007 |
| Monte Carlo | COMPLETE | `monte_carlo.py` read in full |
| Physis constants and units | COMPLETE | CODATA 2022 values confirmed; offset units correct |
| engcalc | COMPLETE | formulas checked against textbook forms (§15) |
| Sandbox (Calcula) | PARTIAL | policy works; isolation silently degraded (AUDIT-008) |
| SageMath | UNVERIFIED | not installed; tests skipped |
| Lean formal proofs | UNVERIFIED | Lean not installed; 2 tests skipped |
| Container sandbox | UNVERIFIED | no runtime; 5 tests skipped |
| Uploads / datasets | COMPLETE | streamed limits, NaN rejection |
| Literature / retraction | UNVERIFIED (code exists) | `archivon/integrity.py` uses Crossref `updated-by` + OpenAlex; not exercised offline |
| Provenance / manifests | COMPLETE | `run_manifest.py:940-1010` |
| Export | UNVERIFIED | not audited in depth |
| Harness: threads/revisions | BACKEND-ONLY, insecure | AUDIT-004; no web caller |
| Harness: checkpoints / resume | PLACEHOLDER | `save_checkpoint` has 0 callers |
| Harness: cost ledger | PLACEHOLDER | `CostLedger.record_usage` has 0 callers |
| Harness: HITL sign-off | PARTIAL | unkeyed hash, no artifact binding (AUDIT-017) |
| Substrate: standards check | BROKEN | AUDIT-001, AUDIT-018 |
| Substrate: materials | BROKEN | AUDIT-010, AUDIT-015 |
| Substrate: geometry | MOCKED | AUDIT-002 |
| Substrate: CAE review | BROKEN | AUDIT-003 |
| Mem0 memory | PARTIAL | single-process lock (AUDIT-012) |

## 11. Critical Findings

### AUDIT-001 – Spherical (and every non-cylindrical) ASME clause is always reported "compliant"

**Severity:** CRITICAL · **Confidence:** CONFIRMED · **Category:** Scientific Correctness / Safety

**Location:** `tribos/memory/semantic.py`, `StandardClause.evaluate_compliance`, lines 142-175 (fall-through at
171-175). Reached from:
- `tribos/substrate/standards/__init__.py:12-18`;
- `app/backend/routers/harness.py:330-342` (`POST /api/harness/substrate/standards/check`);
- the LLM tool `substrate_standards_check` (`tribos/tools/registry.py:724-740`).

**Problem:** Only `ASME_VIII_1_UG27_CYL` is evaluated. Any other clause, including the catalogued
`ASME_VIII_1_UG27_SPH` (whose `formula_latex` shows `t = PR/(2SE − 0.2P)`), returns `{"compliant": True}`
without computing anything.

**Evidence:**
```python
        return {
            "compliant": True,
            "clause": self.clause_ref,
            "note": "Standard clause evaluation completed",
        }
```

Executed: `check_asme_compliance({'pressure_mpa':50,'radius_mm':1000,'allowable_stress_mpa':100,'joint_efficiency':1,'wall_thickness_mm':0.001}, clause_id='ASME_VIII_1_UG27_SPH')`
returned `{'compliant': True, 'clause': 'ASME BPVC VIII-1 UG-27(d)', 'note': 'Standard clause evaluation completed'}`.

**Failure mechanism:** default-to-pass `else` branch.

**Failure scenario:** a 1 µm-thick sphere of 1 m radius at 50 MPa is certified compliant with UG-27(d).

**Impact:** a pressure-vessel safety determination is fabricated. The tool description also advertises
"API 650", which has no clause at all.

**Root cause:** stub implementation shipped as a real check; no negative tests (§31).

**Recommended fix:**
- Implement UG-27(d), or return `compliant: None` / `status: "not_evaluated"` for unknown or unimplemented
  clauses.
- Remove the API 650 claim.

**Verification:**
- Known-answer tests: sphere P = 1 MPa, R = 1000 mm, S = 138 MPa, E = 1 → t_req = 1000/(276 − 0.2) mm.
- A negative test asserting an unimplemented clause is never `True`.

**Related:** AUDIT-018, AUDIT-003.

### AUDIT-002 – CAD geometry tool fabricates mass properties and returns a default part for missing input

**Severity:** CRITICAL · **Confidence:** CONFIRMED · **Category:** Mock data / Scientific Correctness

**Location:**
- `tribos/substrate/cad/inspector.py`, `GeometryInspector.inspect_stl_ascii`, lines 90-101 (default geometry)
  and 112-118 (estimates);
- LLM tool `substrate_geometry_inspect`, `tribos/tools/registry.py:742-759`; its schema says
  "ASCII STL geometry content **or filepath**" (`registry.py:488`).

**Problem:**
- With no parsable vertices (empty input, a file path, a binary STL), the tool returns a hard-coded
  100×50×20 mm part (volume 100,000 mm³, area 16,000 mm²).
- With real vertices, it reports volume = 70% of the bounding box ("typical bracket topology"), surface area =
  the area of the bounding box, and centre of gravity = the centre of the bounding box.
- Nothing in the output marks these as estimates or defaults. The tool description says it is "calculating
  … volume, surface area, mass, and center of gravity".

**Evidence:**
- `GeometryInspector.inspect_stl_ascii('/etc/passwd')` → `{'dimensions_mm': {'length': 100.0, 'width': 50.0, 'height': 20.0}, 'volume_mm3': 100000.0, 'mass_kg': 0.27, ...}`.
- A single right triangle with 10 mm legs (true area 50 mm²) → `surface_area_mm2: 200.0`.

**Failure scenario:** the LLM passes a file path; the user receives a confident mass of 0.27 kg for a part that
was never read.

**Impact:** fabricated engineering data presented as measurement.

**Root cause:** test-fixture behaviour left in production code. The test (`tests/test_harness_and_memory.py:478-481`)
asserts the fabricated 100/50/20 dimensions.

**Recommended fix:**
- Return an error when no geometry is parsed.
- Compute area and volume from facets (divergence theorem) and the centroid from the tetrahedral decomposition.
- Never accept paths from the model.

**Verification:** known-answer tests on a unit cube (V = 1000 mm³ for 10 mm sides, A = 600 mm²) and a
tetrahedron.

**Related:** AUDIT-003.

### AUDIT-025 – A canned benchmark report is appended to unrelated answers, with hard-coded fallback numbers

**Severity:** CRITICAL · **Confidence:** CONFIRMED · **Category:** Mock data / Scientific integrity

*Found during remediation, 2026-10-30; it was not in the original audit.*

**Location:**
- `tribos/scientific/assembly.py`: `assemble_eight_part_answer` (untracked file), and
  `check_and_repair_truncation`.
- Callers: `tribos/agents/orchestration/draft.py` (around lines 340-348 and 572-576) and
  `tribos/agents/orchestration/scientific.py`.

**Problem:**
- `check_and_repair_truncation` ran on every drafted answer whenever the run held *any* `execution_artifacts`. It
  appended whichever "### Section 1-8" blocks of a fixed eight-part benchmark report the answer lacked:
  "2k+1 for k ∈ {1,3,6}", RC circuit, cantilever beam, oscillator, FTCS heat, Monte Carlo, references.
- Every number in those blocks had a hard-coded default (for example `rc.get("time_constant", 1.034)`,
  `beam.get("max_deflection", 0.00768)`, `mc.get("estimate", 0.5921…)`).
- The assembler read only the keys `"oscillator"` and `"heat"`, while the composite run stores `"ode_rk4"` and
  `"heat_ftcs"`. So the ODE and heat sections always showed the stored example values, even on the intended path.

**Evidence:** `tests/test_streaming.py` ("Find KRAS papers only.") streamed
"…### Section 1: Arithmetic &…adaptive Gauss-Kronrod quadrature…". The appended text then triggered a revision,
which in turn caused four of the ten red tests (AUDIT-011).

**Impact:** fabricated scientific content, presented as computed results, on arbitrary questions.

**Status:** Fixed (§50).

## 12. High-Severity Findings

### AUDIT-003 – CAE review reports "fully verified against 14-gate criteria" for meaningless inputs; only 5 gates exist

**Severity:** HIGH · **Confidence:** CONFIRMED · **Category:** Scientific Correctness / UI-claim integrity

**Location:**
- `tribos/substrate/cae/review.py`: docstring line 1; zero-denominator guards at lines 39, 59, 113;
  verdict at lines 158-160.
- `tribos/tools/registry.py:762-772`: `stress_gradient_ratio` defaults to 1.8 and is absent from
  `SubstrateCAEInput` (`registry.py:493-499`).

**Problem:**
- Each guard `... if denominator else 0.0` turns a zero denominator into a 0% deviation, which passes.
- The verdict string claims 14 gates; 5 exist.
- The singularity gate always receives 1.8 (≤ 3.0) through the tool path, so it always passes.

**Evidence:** `run_full_cae_audit(applied_load_n=0, reaction_force_n=1e9, coarse_stress_mpa=0, fine_stress_mpa=0, yield_strength_mpa=250, analytical_stress_mpa=0)`
→ `cae_verified: True`, `verdict: "FEA results fully verified against 14-gate criteria"`.

**Impact:**
- False assurance that an FEA model is in equilibrium and mesh-converged.
- The equilibrium gate passes with an unbalanced reaction of 1e9 N.

**Fix:**
- Treat zero or invalid denominators as `not_evaluable`.
- Require `stress_gradient_ratio`, or mark the singularity gate not evaluated.
- Make the verdict state the number of gates actually run.

**Verification:** property tests: any zero or negative load or stress → `cae_verified` must not be `True`.

**Related:** AUDIT-001, AUDIT-002.

### AUDIT-004 – Harness API has no ownership or authorization checks (cross-tenant read/write)

**Severity:** HIGH · **Confidence:** CONFIRMED (code path) · **Category:** Authorization

**Location:** `app/backend/routers/harness.py:98-298` — all 17 routes. The file has 18 `get_current_user`
dependencies and **0** uses of the user id for scoping.

**Problem:** every route authenticates and then ignores the identity. Any authenticated user can:
- list or create threads and append turns in any `project_id` / `thread_id` (`:98-146`);
- create and list answer revisions with a free-text `author` field (`:150-201`);
- read any run's checkpoints, including `state_payload` through `/resume` (`:205-235`);
- sign off any artifact for any project (`:239-259`);
- read any run's or project's spend (`:285-298`).

The project RBAC in `routers/projects.py` (non-member → 404) is bypassed, because this router uses a separate
store (`tribos/memory/engine.py`) keyed only by the caller-supplied `project_id`.

**Evidence:**
```python
async def list_threads(project_id: str, user: str = Depends(get_current_user)) -> dict[str, Any]:
    threads = _mem_engine.list_project_threads(project_id)
```

**Failure scenario:**
1. User B (a valid token) calls `GET /api/harness/threads/<thread_id>/turns` and reads user A's conversation.
2. User B posts an `approved` sign-off on user A's artifact.

**Impact:** confidentiality and integrity of engineering records and sign-offs. In `TRIBOS_AUTH_MODE=disabled`
there is only one user, so the risk applies to bearer deployments.

**Root cause:** the router was added without adopting the project-store membership checks.

**Fix:** resolve `project_id` through `get_project_store()` with role checks, store `user_id` on threads,
revisions, reviews, checkpoints and cost rows, and filter every query by it.

**Verification:** a TestClient security test with two tokens asserting 404/403 across all 17 routes.

**Related:** AUDIT-017.

### AUDIT-005 – Written-answer checker passes false real-domain identities (`√(x²) = x`, `ln(x²) = 2 ln x`, `|x| = x`)

**Severity:** HIGH · **Confidence:** CONFIRMED · **Category:** Scientific Correctness / Verification

**Location:** `tribos/verify/math_claims.py`, identity sampling at lines 1247-1341. The sample points come from
`t_values = [... 0.37, 1.13, 2.71, 4.4, 6.9, 0.05]` (line 1279), and other symbols use
`rng.uniform(max(0.35, b_low), …)` (line 1292). PASSED is returned when ≥ 3 samples agree (line 1339).

**Problem:** identities are tested only at positive points, regardless of the stated domain.

**Evidence (executed):** answer text "For every real number $x$ … $\sqrt{x^2}=x$ … $\ln(x^2)=2\ln(x)$ … $|x|=x$",
with query "Simplify sqrt(x^2) for real x", produced:
`4 mathematical statement(s): 3 passed, 1 not checkable`, and each false identity has status `passed`.

**Impact:** the README states that "a contradicted statement fails verification". Here false statements are
reported as passed checks and counted in the verification coverage shown to users.

**Root cause:** the sampling domain is fixed and positive, ignoring the problem's domain and the absence of
`positive=True` assumptions.

**Fix:**
- Include negative and complex-boundary points when the domain is real or unspecified.
- Only report PASSED for identities proven by `simplify` under the declared assumptions; label sampled agreement
  "agrees at N points".

**Verification:** regression tests with the three identities above plus `x/x = 1` near 0, `sqrt(a*b) = sqrt(a)*sqrt(b)`.

### AUDIT-006 – Derivation card labels every executed math-agent step "Verified" and hides the run status

**Severity:** HIGH · **Confidence:** HIGH (backend payload executed; UI path traced in code, not rendered in a
browser) · **Category:** UI/UX scientific trust

**Location:**
- `web/src/components/DerivationArtifact.tsx:161`: `const ok = step.verified ?? (step.status ? step.status === "ok" : true);`
- `DerivationArtifact.tsx:168`: renders the "Verified" pill.
- `DerivationArtifact.tsx:47,74-75`: the header reads `data.verified` / `data.is_equal` only.
- Classic path wiring: `web/src/components/MessageArtifacts.tsx:86-87,193-195` (`artifacts.axiom`) and
  `tribos/agents/orchestration/gather.py:219-228`.

**Problem:**
- Math-agent steps carry `status: "ok"`, which means the tool executed. The card maps that to **"Verified"**.
- A step with no status at all defaults to `true`.
- The agent's run-level status (`verified` / `partially_verified` / `unverified` / `failed`) lives in
  `status` / `verification.status`. The card never reads it, so no status pill is shown for the run.

**Evidence:** `solve_problem_tool('Compute the integral of 1/x from -1 to 1')` returns `status: partially_verified`
and `answer.text: "nan"`. Its steps have `status: 'ok'`, and the `axiom_calculus` step output contains
`'verified': False`. Each of these steps would render a green "Verified" pill.

**Impact:** users see per-step "Verified" badges for unchecked or failed computations, which is the
"makes preliminary results look final" failure mode.

**Fix:**
- Rename the step pill to "Ran", or derive it from the step output's `verified` field.
- Default unknown to "Not checked".
- Show `data.status` / `data.verification.status` in the header.

**Verification:** a web unit test rendering the payload above and asserting no "Verified" text.

**Related:** AUDIT-014.

### AUDIT-007 – Curve fit: `verified` = "RMSE is finite", `converged` hard-coded, undefined covariance reported as SE = 0

**Severity:** HIGH · **Confidence:** CONFIRMED · **Category:** Numerical / Uncertainty

**Location:**
- `tribos/dynamis/engine.py`, `dynamis_fit_parameters`: lines 629-634 (SE), 650 (`"converged": True`),
  651 (`"verified": bool(math.isfinite(rmse))`).
- The values reach the LLM via `tribos/agents/stem_evidence.py:192-199`.

**Evidence (executed):**
- Zero degrees of freedom (`a + b*x`, 2 points) → `std_errors {'a': 0.0, 'b': 0.0}`, `verified True`.
- Model `a*x` fitted to `sin(3x)` → `R² = -0.005`, `verified True`, `converged True`.
- Unidentifiable `a*b*x` → `verified True` (SE ≈ 4e6, correctly huge).

**Problem:**
- `pcov` is `inf` when the parameters are not estimable; the code substitutes 0.0. That turns "unknown
  uncertainty" into "exact".
- A failed or meaningless fit is labelled verified.
- Fits are unweighted, with no `sigma` / `absolute_sigma`, so measurement uncertainty is ignored.

**Impact:** fitted parameters are presented to the writer model with zero uncertainty, together with a
"verified" flag.

**Fix:**
- Report `None` / "not estimable" for non-finite variances.
- Set `converged` from the optimiser's `ier`.
- Derive `verified` from goodness-of-fit plus degrees of freedom > 0, or rename it.
- Accept `sigma`.

**Verification:** known-answer tests: an exact-linear dataset with noise (analytic SE formula); zero-dof → SE not
estimable; a poor model → not verified.

### AUDIT-008 – Model-written code runs without OS isolation by default, including inside the API container

**Severity:** HIGH · **Confidence:** CONFIRMED · **Category:** Security / Infrastructure

**Location:**
- `tribos/agentic/sandbox/gateway.py:119-128` (auto mode falls back to `SubprocessBackend` unless
  `STRICT_LIMITS` **and** not `ALLOW_UNISOLATED`);
- defaults `TRIBOS_SANDBOX=True`, `TRIBOS_SANDBOX_STRICT_LIMITS=False` (`tribos/config/settings.py:304,324`);
- `docker/compose.yml` (the backend service has no container runtime or socket);
- `docker/backend.Dockerfile:43` ("This image is the API … it must never run model-written code").

**Evidence (executed, default settings):** `container_available()` → `(False, 'the podman.EXE daemon is not running')`,
and `_select_backend('python')` → `SubprocessBackend None`.

**Problem:**
- In the documented compose deployment, the backend cannot reach a container runtime, so every Calcula
  execution runs as a subprocess of the API container, which holds the LLM credentials (`env_file: ../.env`).
- The setting `TRIBOS_SANDBOX_ALLOW_UNISOLATED=false` reads as if it forbids this, but it only applies in strict
  mode.
- The docs (`docs/agentic/sandbox-operations.md:73`) do say "falls back silently".

**Mitigations verified:**
- The AST policy blocked the escapes tried (ctypes, `os` via attributes, dunder chains, absolute-path readers,
  `pandas.eval`).
- The runtime refused SymPy string `__` payloads.
- The child environment is an allowlist (`process.py:28-34`).

**Residual risk:** native code inside allowed packages can bypass Python-level guards (acknowledged in
`backends.py:9-11`). The same uid can read the parent's `/proc/<pid>/environ` on Linux (UNVERIFIED exploit
path).

**Fix:**
- Default `STRICT_LIMITS=1` in production profiles, or make `ALLOW_UNISOLATED=false` effective in auto mode.
- Run the sandbox as a sidecar service in compose.
- Surface the active backend in `/api/health`.

**Verification:** a deployment test asserting the selected backend is `ContainerBackend` in compose.

### AUDIT-009 – 385 published advisories in 41 locked Python packages, including untrusted-input parsers and the JWT library

**Severity:** HIGH · **Confidence:** CONFIRMED (advisories exist per pip-audit; exploitability per advisory
UNVERIFIED) · **Category:** Dependencies / Supply chain

**Evidence:** `python -m pip_audit -l` on `.venv`:

| Package | Version | Advisories |
|---|---|---:|
| pypdf | 6.1.1 | 59 |
| pillow | 11.3.0 | 56 |
| nltk | 3.9.2 | 42 |
| aiohttp | 3.12.15 | 40 |
| gitpython | 3.1.45 | 34 |
| authlib | 1.6.1 | 17 |
| pyjwt | 2.10.1 | 17 |
| tornado | 6.5.2 | 17 |
| virtualenv | 20.34.0 | 16 |
| transformers | 4.55.2 | 10 |
| torch | 2.8.0 | 8 |
| cryptography | 45.0.6 | 7 |
| urllib3 | 2.5.0 | 6 |

…41 packages in total. The environment includes dev extras.

Runtime use on untrusted input:
- `pypdf` in `tribos/papers/extract.py` and `tribos/datasets/validators.py` (uploaded papers);
- `PIL` in `tribos/vision/reader.py` (uploaded images);
- `jwt` in `app/backend/auth.py` (every bearer request).

`npm audit --omit=dev`: 0 vulnerabilities.

**Root cause:** exact pins with no refresh. CI's pip-audit gate does block (see the AUDIT-019 correction), so the
security workflow was failing rather than silently passing.

**Fix:** upgrade the runtime packages to fixed versions (watch the numpy 1.26 pin constraint noted in
`pyproject.toml`), and make pip-audit blocking for runtime dependencies.

**Verification:** a pip-audit gate with an explicit, reviewed ignore list.

### AUDIT-010 – Material property model at temperature is unsourced and unbounded

**Severity:** HIGH · **Confidence:** HIGH (code CONFIRMED; the magnitude comparison relies on external
handbook data, flagged for domain review) · **Category:** Scientific validity

**Location:** `tribos/memory/semantic.py:33-43` (`e_at_temp`, `yield_at_temp`) and catalogue lines 59-130.
Exposed through `/api/harness/substrate/materials/lookup` and the tool `substrate_material_lookup`.

**Problem:**
- Yield is derated by a single factor `1 − 0.0006·ΔT` (floor 0.2) for **all** alloys.
- E is linear with a per-alloy coefficient.
- There is no source, no valid temperature range, and no warning. Cold temperatures are never adjusted.

**Evidence (executed):** Al 6061-T6 at 260 °C → yield 236.3 MPa, E 60.6 GPa. Published elevated-temperature
data for precipitation-hardened 6061-T6 show a much larger strength loss in this range (ASM-type handbook data;
external — requires domain verification). The code's 0.0006/°C factor cannot represent alloy-specific
overaging.

**Impact:** unconservative strength values feed into design checks.

**Fix:**
- Use tabulated, cited property-versus-temperature data with validity ranges.
- Refuse extrapolation.
- Include the source in the output.

**Verification:** reference-dataset tests against the cited tables.

## 13. Medium-Severity Findings

### AUDIT-011 – Python test suite is red (10 failures), contradicting the documented baseline

**Severity:** MEDIUM · **Confidence:** CONFIRMED · **Category:** Testing

**Evidence:** `pytest -q -p no:cacheprovider -rs` → **10 failed, 2142 passed, 28 skipped in 570.70 s**.
`AGENTS.md:15` claims "baseline 1326 passed, 15 skipped, 0 failed".

Application failures (5), consistent with the uncommitted edits to `tribos/agents/prompts.py` and the agentic
modules:
- `tests/test_agentic_loops.py::test_gap_loop_retrieves_resynthesizes_and_stops` — 2 prompts instead of 1;
- `tests/test_foundation_hooks.py::test_synthesis_system_prompt_composition`;
- `tests/test_prompts.py::test_composed_prompt_is_numbered_and_bounded` — rule numbering `[10,11,12]` instead
  of `[8,9,10]`;
- `tests/test_prompts.py::test_orchestrator_sends_structured_prompt`;
- `tests/test_streaming.py::test_orchestrator_streams_reasoning_answer_and_real_steps` — an extra `---` block
  appended.

Environment/test-design failures (5), in `tests/test_feat_mem0_integration.py`: Qdrant lock on
`C:\Users\ghotc\.mem0\migrations_qdrant` (see AUDIT-012).

**Fix:** reconcile the prompt changes with the tests (or the reverse), and make the mem0 tests use a temporary
`HOME` / `MEM0_DIR`.

### AUDIT-012 – Mem0 adapter: embedded single-process Qdrant, writes to `~/.mem0`, global env mutation at import

**Severity:** MEDIUM · **Confidence:** CONFIRMED · **Category:** Concurrency / Reliability

**Location:** `tribos/agentic/mem0_adapter.py`: line 24 (`os.environ["MEM0_TELEMETRY"] = "False"` at import),
lines 111-120 (embedded Qdrant path).

**Evidence:** the test failures above (`portalocker.exceptions.AlreadyLocked`, "Storage folder … is already
accessed by another instance of Qdrant client").

**Impact:**
- Multiple uvicorn workers or processes sharing `TRIBOS_DATA_DIR` will fail on memory writes.
- Tests leak state into the user's home directory.

**Fix:** use a Qdrant server or per-process paths, and document single-worker operation.

### AUDIT-013 – Math-agent calibration is stale relative to the code it describes

**Severity:** MEDIUM · **Confidence:** CONFIRMED · **Category:** Statistical validity / Reproducibility

**Location:** `tribos/axiom/calibration.json` (`fitted_at 2026-10-24T10:20`, n = 48, verified 43/43, p 0.978);
`tribos/axiom/agent.py:852-880`.

**Problem:**
- The file's own note says "refit after changing the parser, policy or verifier".
- `git log` shows 10 commits since the fit touching `problem.py`, `agent.py` and `verifier.py`, plus uncommitted
  changes (8 files, +349/−75 in `tribos/axiom/`).
- `calibrated_confidence()` emits p_correct = 0.978 with no code-hash check.

**Fix:** store the code hash of the axiom package in the calibration file and suppress the figure on mismatch.

### AUDIT-014 – NaN / divergent answers receive `partially_verified`

**Severity:** MEDIUM · **Confidence:** CONFIRMED · **Category:** Verification semantics

**Location:** `tribos/axiom/verifier.py` (status assignment around line 195).

**Evidence:** `∫₋₁¹ 1/x dx` → `status partially_verified`, `answer "nan"`. The checks were only "tool executed",
"expression matches the problem" and "correspondence" (all level 0-1); the level-2 check was `null`.

**Impact:** the word "partially verified" attached to an undefined answer for a divergent integral (where the
principal value is 0).

**Fix:** treat non-finite answers as `failed` or `unverified`, and state "diverges".

### AUDIT-015 – Material lookup uses substring matching and silently returns the wrong alloy

**Severity:** MEDIUM · **Confidence:** CONFIRMED · **Category:** Data integrity

**Location:** `tribos/substrate/materials/__init__.py:6-13` (duplicated in `semantic.py:225-232`).

**Evidence:** `get_material('a')` → "Aluminum 6061-T6"; `get_material('steel')` → "AISI 4140 …" (the first
match in dict order; 316L is also steel).

**Fix:** use exact keys or aliases only; return candidates for ambiguous queries.

### AUDIT-016 – Expression parser evaluates `factorial(10**7)` eagerly (CPU denial of service)

**Severity:** MEDIUM · **Confidence:** HIGH (the parse hang is CONFIRMED; the route impact is inferred from
code) · **Category:** Security / Availability

**Location:** `tribos/axiom/safe_expr.py:95` (`"factorial": sp.factorial` allowed); the power guard at
`safe_expr.py:238-276` covers only integer powers. `/api/simulate` uses `run_in_executor` + `wait_for`
(`app/backend/routers/simulate.py:100-125`), so on timeout the thread keeps running.

**Evidence:** `safe_parse_expr('factorial(10**7)')` did not return within 20 s (killed). Power towers are
rejected in about 2 s with "Expression is too large…".

**Fix:** bound the arguments of `factorial`, `binomial`, `gamma` and similar functions, or parse with
`evaluate=False`.

### AUDIT-017 – Harness durability, cost and sign-off features are placeholders

**Severity:** MEDIUM · **Confidence:** CONFIRMED · **Category:** Dead code / Misleading feature

**Evidence:**
- `DurableExecutionHarness.save_checkpoint`: 0 call sites. `/runs/{id}/resume` returns `{"status": "resumed", ...}`
  but executes nothing (`harness.py:226-235`, `durable.py:147-159`).
- `CostLedger.record_usage`: 0 call sites. The pipeline's `budget.record_usage` is a different class, so spend
  endpoints always report empty totals. The `MODEL_PRICING` table (`cost_ledger.py:20-27`) lists older model
  names and charges unknown models at the "default" rate.
- The HITL `signature_hash` is `sha256(f"{artifact_id}:{reviewer_id}:{action}:{now}")` (`hitl.py:91-92`). It is
  unkeyed and does not include artifact content, so it neither authenticates the reviewer nor binds the approval
  to what was approved.
- No web code calls `/api/harness/*`.

**Fix:** wire the features in, or remove or label them experimental. Use an HMAC over a content hash.

### AUDIT-018 – ASME UG-27(c)(1) check ignores the clause's applicability limits and the longitudinal check

**Severity:** MEDIUM · **Confidence:** CONFIRMED · **Category:** Scientific validity

**Location:** `tribos/memory/semantic.py:144-170`.

**Problem:**
- The circumferential formula `t = PR/(SE − 0.6P)` is implemented correctly.
- Not implemented: the UG-27(c)(1) applicability limits (t ≤ R/2, P ≤ 0.385·S·E) and the (c)(2)
  longitudinal-stress requirement.
- Inputs are unvalidated: zero or negative values, and `joint_efficiency` > 1, are accepted.

**Evidence:** P = 60 MPa, S = 138 MPa, E = 1 (P > 0.385·SE = 53.1 MPa) → `compliant: True` with no warning.

**Fix:** enforce or flag the limits, and validate inputs (P > 0, 0 < E ≤ 1, R > 0).

### AUDIT-019 – GitHub Actions are tag-pinned only (dependency-gate claim corrected)

**Severity:** MEDIUM · **Confidence:** CONFIRMED · **Category:** CI/CD supply chain

**Correction (2026-10-30):** the original claim that CI never blocks on vulnerable dependencies was **wrong**.
`security_audit.yml` has a blocking "Fail on vulnerabilities" step that reads the pip-audit JSON report, after the
`|| true` report steps quoted below. Only the action-pinning part of this finding stands.

**Evidence (original, partly superseded):**
- `.github/workflows/security_audit.yml:48-49` (`pip-audit … || true`) and `:63` (`safety`,
  `continue-on-error: true`).
- `tests_tribos.yml:58,62,69`: full ruff, pylint and all-severity bandit are report-only.
- None of the ~60 `uses:` references is SHA-pinned. `release.yml` publishes to PyPI and container registries
  using tag-pinned third-party actions.

**Fix:** add a blocking runtime pip-audit and pin actions by commit SHA.

## 14. Low-Severity Findings

### AUDIT-020 – Biomedical leftovers remain in production code despite the STEM-only policy

**Confidence:** CONFIRMED.

grep finds references to `lumicell|vivarix|primekg|biomodels|KRAS|leiden|n_cells` in at least 12 production
modules, for example:
- `tribos/tools/registry.py` (38 occurrences; `vivarix_*` aliases at 640-686);
- `tribos/agents/authoritative_orchestrator.py` (30; "lumicell … Leiden clusters" at 784-787);
- `tribos/provenance/run_manifest.py` (20; `biomodels`, `primekg_version` at 396-397);
- `tribos/datasets/validators.py:455-485` (AnnData "cells by genes" path).

The test fixture in `test_agentic_loops.py` still asks about KRAS. Ten tests are skipped as "Legacy … retired"
or "Clinical trial … pruned". This contradicts AGENTS.md "don't reintroduce any"; `test_no_biomedical_leftovers.py`
evidently guards a narrower set.

### AUDIT-021 – UI number formatter uses decimal places, not significant figures

**Confidence:** CONFIRMED.

`web/src/components/agentic/ui.tsx:32-37`: for 1e-3 ≤ |v| < 1e5 it renders `toFixed(3)`, so 0.0012345 → "0.001"
(one significant figure). The constants card is not affected (`ReferenceDataArtifact.tsx:87` uses
`toExponential(6)`).

### AUDIT-022 – Duplicate CODATA table diverges from Physis

**Confidence:** CONFIRMED.

`tribos/memory/semantic.py:210-219` hard-codes constants without uncertainties and truncates the gas constant
(8.314462618 vs the exact 8.31446261815324 J/(mol·K)). Physis uses `scipy.constants` (CODATA 2022, verified:
electron mass 9.1093837139e-31 kg).

### AUDIT-023 – An inequality disproved by a counterexample returns INCONCLUSIVE, not FAILED

**Confidence:** CONFIRMED (code).

`tribos/verify/math_claims.py:1334-1336`: a sampled counterexample to `≤`, `<` or `≠` yields "undecided" even
though a single valid counterexample refutes a universal inequality.

### AUDIT-024 – Repository hygiene and maintainability

**Confidence:** CONFIRMED.

- In the root, all git-ignored and untracked: two 8.8 MB zips, a 6.9 MB screenshot PDF, ~20 `.log` files,
  `.coverage`, and five large audit/prompt Markdown files.
- `web/src/app/page.tsx` is a 3,381-line component.
- Non-gating lint debt: ruff 145 issues, eslint 167 warnings (0 errors).

## 15. Scientific Correctness Findings

- **CRITICAL/HIGH:** AUDIT-001, AUDIT-002, AUDIT-003, AUDIT-005, AUDIT-010.
- **MEDIUM:** AUDIT-014, AUDIT-018.

Implementation verified correct against textbook forms (code read):

- **Fatigue** (`tribos/engcalc/fatigue.py`):
  - Gerber equivalent stress σa/(1 − (σm/Sut)²) (lines 22-29);
  - the Gerber factor of safety (Shigley form, line 38);
  - Soderberg and Goodman (lines 40-41);
  - Se′ = 0.5·Sut ≤ 1400 MPa else 700 MPa, refused for non-steels (lines 48-58);
  - Basquin constants a = (f·Sut)²/Se, b = −log₁₀(f·Sut/Se)/3 (lines 64-65).
- **Thermofluid** (`tribos/engcalc/thermofluid.py`):
  - Colebrook by Newton iteration on 1/√f, with Swamee–Jain seed and range check (lines 15-32, 55-56);
  - laminar f = 64/Re below 2300, with a transitional warning;
  - ε-NTU parallel and counterflow, including the Cr = 1 case (lines 121-125);
  - LMTD with the equal-ΔT limit (line 175).

Three separate questions, for the main engines:

| Engine | Implementation correctness | Numerical correctness | Scientific validity |
|---|---|---|---|
| engcalc | Matches textbook forms (read) | Newton iteration converges to 1e-12 relative | Validity ranges checked and warned |
| Dynamis ODE | `solve_ivp`, rejects failed or non-finite solves | Tight tolerances; invariant drift check | Problem-dependent; stiffness left to the method choice |
| Dynamis fit | Correct `curve_fit` call | SE wrong when covariance undefined (AUDIT-007) | Unweighted; no dof check |
| Monte Carlo | Correct | SE with ddof = 1; seeded PCG64 | Accuracy note disclaims exactness |
| Substrate | Stubbed / fabricated | Zero-guard passes | Not valid (AUDIT-001..003, 010) |

## 16. Numerical Computing Findings

- AUDIT-007 (undefined covariance → 0), AUDIT-014 (NaN accepted as partially verified), AUDIT-016 (unbounded
  factorial), AUDIT-003 (division-by-zero guards turned into passes).
- Working:
  - ODE results are rejected when `success=False`, when the shape mismatches, or when output is non-finite
    (`dynamis/engine.py:151`);
  - Monte Carlo rejects non-finite samples and complex values (`monte_carlo.py:45-51`);
  - the power-tower guard works.
- Tolerances: ODE rtol 1e-8 / atol 1e-10 (fixed, documented in the output); invariant drift 1e-4 relative
  (`engine.py:265`); math-claim tolerance derived from printed precision (`math_claims.py:1071-1099`). These are
  documented in place. Their scale-appropriateness for very large or very small magnitudes is UNVERIFIED.

## 17. Scientific Data Findings

- Uploads: tables with NaN or infinite values are rejected outright (`datasets/validators.py:438`). There is no
  silent fill, which is the conservative behaviour, but there is also no missing-value-aware analysis option.
- Material catalogue: 5 alloys with single-point properties and no source citations (AUDIT-010, AUDIT-015).
- External literature data (Crossref / OpenAlex retraction flags in `archivon/integrity.py:1-49`): implemented,
  UNVERIFIED at runtime (offline audit).

## 18. Units / Dimensions / Coordinates / Time Findings

- Pint offset units are handled correctly (executed): 100 degC → 212 degF (shown as 211.99999999999991, float
  noise); 0 degC → 273.15 K; 10 delta_degC → 10 K; degC/s → K/s.
- Substrate APIs encode units in field names (`_mpa`, `_mm`, `_celsius`) with no validation; there is no Pint
  use in `semantic.py`.
- engcalc works in SI internally with declared `Param` units (`thermofluid.py:104`, `Result(..., "Pa", "kPa")`).
- Coordinates and geospatial: **not applicable**; no CRS or geospatial code was found.
- Time: run manifests use `utc_now()` (`run_manifest.py:996`); no scientific time series were found. No verified
  finding identified in this category.

## 19. Statistical / ML Findings

- AUDIT-013 (stale calibration), AUDIT-007 (fit statistics).
- `tribos/config/confidence_calibration.json` honestly declares `"status": "heuristic"`, hand-set weights,
  `n_claims: 0`, and records that an earlier in-sample fit on 25 synthetic claims was withdrawn. This is good
  practice. Whether the UI labels that score "heuristic" everywhere is UNVERIFIED.
- Math calibration: Laplace-smoothed P(correct | status) with a Wilson lower bound, n = 48 on a held-out set. The
  sample is small (43 verified), and the file reports it honestly.
- NLI and embedding models (transformers, sentence-transformers): model version pinning is UNVERIFIED (not
  audited).

## 20. Reproducibility Findings

| Question | Answer | Evidence |
|---|---|---|
| Can the result be reproduced? | Tool computations: yes. LLM text: no (no seed recorded; temperature recorded) | `run_manifest.py:981-993` |
| Can the processing history be reconstructed? | Yes: ordered tool calls, steps, routing, verification | `run_manifest.py:999-1010` |
| Can the dataset version be identified? | Yes: dataset hashes | `run_manifest.py:442+` |
| Can the algorithm version be identified? | Yes: code-tree sha256, git commit, app version | `run_manifest.py:140-146` |
| Can parameters be recovered? | Yes: validated tool inputs | manifest `tool_calls` |
| Can the environment be reconstructed? | Partially: `uv.lock` sha256; web lockfile not hashed | `run_manifest.py:146` |
| Can another researcher get the same result? | Numerics yes (seeded MC, fixed tolerances). The verdicts depend on the live LLM and live literature APIs | — |

Calibration provenance is weaker than run provenance (AUDIT-013). The test suite is not hermetic (AUDIT-012).

## 21. Provenance Findings

Run provenance is strong:
- requested **and actually served** models, and whether a fallback was used (`run_manifest.py:981-993`);
- source-version probes;
- `query_sha256` and `response_sha256`.

Gaps:
- Harness sign-offs are not bound to artifact content (AUDIT-017).
- Substrate outputs carry no source for their material data or formulas (AUDIT-010).
- The manifest schema still carries `biomodels` / `primekg` fields (AUDIT-020).

## 22. Scientific Visualization Findings

- AUDIT-006 (status pills), AUDIT-021 (formatting).
- `SimulationArtifact` / `TrajectoryCharts` make no "verified" claim.
- Chart axis, unit and log-scale correctness was not audited: UNVERIFIED.

## 23. UI/UX Findings

- AUDIT-006 is the material one. The `artifactAttention` mechanism (`MessageArtifacts.tsx:80-84`) flags cards
  that need a look; whether it considers `partially_verified` axiom results is UNVERIFIED.
- Every card starts collapsed so the written answer is read first (`MessageArtifacts.tsx:81-84`). This puts more
  weight on the text verification (AUDIT-005).

## 24. Security Findings

AUDIT-004, AUDIT-008, AUDIT-009, AUDIT-016, AUDIT-019.

Verified controls:
- **SecurityMiddleware** (`security.py:153-214`): loopback-only when auth is disabled; Host allow-list
  (DNS-rebinding defence); Origin check on state-changing methods; body-size limits for both declared and
  chunked bodies.
- **CORS** drops wildcards (`security.py:61-73`).
- **XSS:** KaTeX runs with `trust:false` (`PaperArtifact.tsx:26-28`); markdown URLs go through a scheme
  allow-list (`markdownSafety.ts:127,223`); the only other `dangerouslySetInnerHTML` is a static theme script
  (`layout.tsx:58-66`).
- **Bearer token** kept in sessionStorage unless the user opts in to "remember" (`page.tsx:322-326`).
- **Caller LLM key:** placeholder keys are refused (`main.py:334-341`); the key is stripped before jobs are
  persisted (`jobs.py:515`); manifests store only `api_key_supplied: bool`.

## 25. Authentication and Authorization Findings

- **Authentication** (`app/backend/auth.py`, read in full):
  - static tokens compared with `hmac.compare_digest`;
  - HS256 JWT with `exp` and `sub` required, plus optional `aud`/`iss`;
  - 503 when nothing is configured (fail-closed);
  - JWT error details are logged, not echoed to the client.
- **Authorization:**
  - correct for run control (`agent_runs.py:45-49`), jobs (`jobs.py:120-144`), research memory
    (`main.py:738-792`), projects (RBAC), datasets (user-scoped resolve) and export runs (`_load_owned`);
  - **missing for the harness router** (AUDIT-004).

## 26. API Findings

The unauthenticated routes are `/api/health*`, the A2A card, and `GET`/`DELETE /mcp` and `GET /a2a`, which
return only 405. The harness API accepts unvalidated scientific inputs: negative pressures, `joint_efficiency`
above 1, temperatures outside any range (AUDIT-018, AUDIT-010).

## 27. Database Findings

| Store | WAL | Locks | Foreign keys | Notes |
|---|---|---|---|---|
| `utils/memory/project_store.py` | yes | yes | none (app-level cascade, `:424-428`) | unique current-fact index (`:266`) |
| `utils/memory/research_memory.py` | yes | — | none | user-scoped queries |
| `agentic/jobs.py`, `agentic/router_store.py` | yes | yes | none | — |
| `provenance/run_store.py`, `datasets/store.py` | no | yes | none | — |
| `memory/session.py`, `memory/episodic.py`, `harness/*.py` | no | no | `session.py` only | unscoped by user (AUDIT-004) |

bandit flags 10 B608 (string-built SQL) at medium severity. Two that were inspected (`project_store.py:310,428`)
interpolate constant table and column names. The rest are UNVERIFIED individually.

## 28. Concurrency and State Findings

- AUDIT-012 (mem0 lock).
- The harness stores open a new SQLite connection per call with `timeout=10.0` and no WAL. Concurrent writers
  serialize, and under load this could produce "database is locked" (UNVERIFIED under load).
- `/api/simulate` per-user slots prevent thread pile-up per user, but CPU-bound work continues after a 504
  (AUDIT-016).
- Run recorder: ContextVar per inquiry (`run_manifest.py:4-5`). Not stress-tested.

## 29. Reliability and Error Handling

- Default-to-pass patterns are the recurring scientific failure mode:
  - `review.py` zero guards;
  - `semantic.py` `else → compliant`;
  - `inspector.py` fallback geometry;
  - `DerivationArtifact.tsx` `?? true`.
- Router import failures are logged and the router is disabled unless `TRIBOS_STRICT_ROUTERS=1`
  (`main.py:150-169`). That is visible in `/api/health`.
- The tool registry retries partial registration at most once per minute (`registry.py:794-813`).

## 30. Performance Findings

- The full test suite takes 9.5 minutes, versus the ~4 minutes claimed in AGENTS.md (this machine).
- Unbounded `factorial` (AUDIT-016).
- No benchmark numbers were measured; no other verified finding identified in this category.

## 31. Testing Findings

- **Gates:** pytest red (AUDIT-011); web tests 209/209; typecheck clean; ruff F/E9 clean; bandit high clean;
  `gen_env_reference --check` clean.
- **Skipped (28), meaning unvalidated in this environment:**
  - Lean (2), container sandbox (5), SageMath (3), Windows/POSIX limit variants (3);
  - ~15 legacy biomedical tests.
- **Test quality on the defective code** (`tests/test_harness_and_memory.py`):
  - ASME is tested only for one cylindrical pass/fail pair (`:252,265`);
  - geometry asserts the fabricated 100/50/20 box and `mass_kg > 0` (`:478-481`);
  - CAE asserts `cae_verified is True` for one input (`:521`).

  These tests confirm the code returns *something*; none would catch AUDIT-001/002/003.
- **Strong scientific tests do exist elsewhere:** the zero-false-accept gate for the math agent
  (`tests/test_math_agent.py`, per the README), and "verify numerics against analytic results" is a stated
  convention. They were not inspected individually in this audit.
- **Missing tests:** UG-27(d) known answer, STL known-volume, CAE zero inputs, negative-domain identities,
  zero-dof fit SE, harness two-user authorization, DerivationArtifact status rendering.

## 32. Dependency / Supply-Chain Findings

AUDIT-009, AUDIT-019. `npm audit --omit=dev`: 0. The `vision` extra pins opencv below 4.11 because of the numpy
1.26 pin, which itself blocks many upgrades (`pyproject.toml:80-84`).

## 33. Configuration / Infrastructure Findings

- AUDIT-008.
- The compose file hardens both services: `read_only`, `cap_drop: ALL`, `no-new-privileges`, pids/mem/cpu limits,
  ports bound to 127.0.0.1 by default.
- The backend image runs as non-root uid 10001 (`backend.Dockerfile:50-60`).
- `.env` exists locally and is git-ignored (`.gitignore:134`); it is not tracked. Its contents were not read.

## 34. Technical Debt

- Duplicated scientific logic of divergent quality (engcalc vs substrate; Physis vs `semantic.py` constants).
- A god component (`page.tsx`).
- Biomedical residue (AUDIT-020).
- Placeholder harness features (AUDIT-017).
- Calibration not bound to code (AUDIT-013).
- 167 eslint warnings (mostly `no-explicit-any`).

## 35. Dead Code / Placeholder / Mock Findings

- **MOCKED:** STL default geometry (AUDIT-002).
- **PLACEHOLDER:** checkpoints/resume, cost ledger, HITL signature (AUDIT-017); unimplemented ASME clauses
  (AUDIT-001).
- **DEAD:** `vivarix_*` aliases, lumicell/AnnData paths, `primekg`/`biomodels` manifest fields (AUDIT-020).

## 36. Documentation Inconsistencies

| Claim | Where | Reality | Evidence |
|---|---|---|---|
| "baseline 1326 passed, 15 skipped, 0 failed", ~4 min | `AGENTS.md:15` | 2142 passed, **10 failed**, 28 skipped, 9.5 min | §47 |
| "14 Published Verification Gates" / "fully verified against 14-gate criteria" | `cae/review.py:1,158` | 5 gates | AUDIT-003 |
| Standards check covers "ASME … UG-27, API 650" | `registry.py:732` | Cylinder only; sphere stubbed; no API 650 | AUDIT-001 |
| Geometry tool "calculating volume, surface area, mass, and center of gravity" | `registry.py:751` | Bounding-box heuristics or a fixed default | AUDIT-002 |
| Material tool returns "fatigue properties" | `registry.py:714` | Output contains no fatigue fields | `registry.py:697-709` |
| API image "must never run model-written code" | `backend.Dockerfile:43` | Auto mode runs it there when no runtime is present | AUDIT-008 |
| "A contradicted statement fails verification" | README §Verified Mathematics Agent | False identities pass | AUDIT-005 |
| Calibration "verified 43/43 … 0.98" | README | Fitted before 10+ later commits to the measured code | AUDIT-013 |
| "Thread-scoped persistent memory vault (Mem0 SQLite store…)" | README | Mem0 uses embedded Qdrant (single process) | `mem0_adapter.py:111-120` |

## 37. Root-Cause Analysis

```text
RC-1 Unreviewed bolt-on subsystem (substrate + harness on this branch)
  ↓ written without engcalc's validity conventions, project RBAC, or pipeline wiring
  ↓ defects: AUDIT-001/002/003/004/010/015/017/018
  ↓ affected: harness REST API, three LLM tools
  ↓ consequence: fabricated or unchecked engineering verdicts; cross-tenant data access

RC-2 Conflating "executed" with "verified"
  ↓ step status "ok", isfinite(rmse), level-1 checks all surface as "verified"
  ↓ defects: AUDIT-006/007/014
  ↓ consequence: users and the writer model over-trust results

RC-3 Default-to-pass on missing or degenerate input
  ↓ zero-denominator → 0% error; unknown clause → compliant; no vertices → default part; unknown step → Verified
  ↓ defects: AUDIT-001/002/003/006

RC-4 Happy-path tests on new code; red suite tolerated; non-blocking security gates
  ↓ defects: AUDIT-009/011/019 allowed the above to merge unnoticed
```

## 38. Security Control Matrix

| Control | Where implemented | Server-side enforced | Tested | Gaps |
|---|---|---|---|---|
| Bearer authentication | `auth.py:98-129` | Yes | Yes (suite) | — |
| Fail-closed when unconfigured | `auth.py:105-112` | Yes | — | — |
| Loopback-only when auth disabled | `security.py:165-171` | Yes | Yes | `ALLOW_INSECURE` overrides |
| Host allow-list | `security.py:87-97,173-176` | Yes | Yes | — |
| Origin check (CSRF) | `security.py:178-181` | Yes | Yes | — |
| Body limits | `security.py:183-214` | Yes | Yes | — |
| Per-resource ownership | runs, jobs, memory, projects, datasets, export | Yes | Partly | **harness: none** (AUDIT-004) |
| Sandbox AST policy | `sandbox/policy.py` | Yes | Yes (+ probes here) | Native-code bypass (documented) |
| OS isolation | `gateway.py:94-128` | Optional | Container tests skipped | Silent fallback (AUDIT-008) |
| Expression-parser limits | `safe_expr.py` | Partial | Yes (powers) | factorial (AUDIT-016) |
| XSS | `markdownSafety.ts`, KaTeX `trust:false` | Client | Yes (web tests) | — |
| Dependency scanning | `security_audit.yml` | **Non-blocking** | — | AUDIT-009/019 |
| Secrets | `.env` ignored; env allowlist for children; caller key stripped | Yes | — | — |

## 39. Scientific Validation Matrix

| Scientific component | Algorithm/model | Inputs | Units | Assumptions | Validation evidence | Tests | Risk | Confidence |
|---|---|---|---|---|---|---|---|---|
| Math agent | Rule ladder + LLM + independent verifier | Problem text | — | Parse fidelity | 10 probes, no false `verified`; calibration n = 48 (stale) | `test_math_agent.py` gate | Low-Med | HIGH |
| Written-answer audit | Numeric compare + 6-point sampling | Answer Markdown | — | Positive sample domain | False passes confirmed | `test_math_claims.py` | **High** | CONFIRMED |
| ODE | `solve_ivp`, RK4 | RHS, IC | User-declared | Smoothness | Failure/non-finite rejection; invariant drift | `test_dynamis.py` | Low | HIGH |
| Curve fit | Least squares | x, y | — | Unweighted, iid | SE / verified defects | `test_dynamis.py` | **High** | CONFIRMED |
| Monte Carlo | Crude MC | f, [a,b], N, seed | — | Finite variance | Correct SE, seeded | MC tests | Low | CONFIRMED |
| Constants | `scipy.constants` | name | SI | CODATA 2022 | Electron mass value matches 2022 | `test_physis.py` | Low | CONFIRMED |
| Units | Pint | value, units | any | — | Offset units correct | `test_physis.py` | Low | CONFIRMED |
| Pipe flow | Colebrook / Swamee–Jain / 64/Re | D, L, ρ, μ, ε, Q | SI | Developed flow | Range checks, warnings | engcalc tests (not inspected) | Low | HIGH |
| Fatigue | Goodman/Gerber/Soderberg, Basquin | Sut, Sy, σa, σm | Pa | Steels for Se′ | Steel-only enforced | engcalc tests (not inspected) | Low | HIGH |
| Heat exchanger | ε-NTU, LMTD | NTU, Cr, temperatures | SI | — | Forms correct | engcalc tests (not inspected) | Low | HIGH |
| ASME UG-27 | t = PR/(SE − 0.6P); sphere stub | P, R, S, E, t | MPa, mm | Thin shell | Sphere always passes; limits absent | 1 pass/fail pair | **Critical** | CONFIRMED |
| Material at T | Linear derating | name, T | °C | Generic | Unsourced | none meaningful | **High** | HIGH |
| STL mass properties | Bounding-box heuristics | STL text | mm | "bracket topology" | Fabricated | Asserts fabricated values | **Critical** | CONFIRMED |
| CAE gates | 5 threshold gates | 6 numbers | N, MPa | — | Zero inputs pass | 1 happy path | **High** | CONFIRMED |
| Lean / Sage / container | External tools | — | — | Installed | Not installed | Skipped | Unknown | UNVERIFIED |

**Scientific invariant matrix:**

| Invariant | Expected | Where enforced | Tested | Violation possible | Evidence |
|---|---|---|---|---|---|
| Unverified ≠ verified | Strict | Math agent statuses | Yes | **Yes, in UI and fit** | AUDIT-006/007 |
| Non-negative SE / uncertainty is defined | SE > 0 or "not estimable" | — | No | Yes (SE = 0) | AUDIT-007 |
| Finite answers only certified | Yes | ODE, MC | Partly | Yes (math NaN) | AUDIT-014 |
| Static equilibrium ΣF ≈ 0 | Yes | CAE gate 1 | No | Yes (applied = 0) | AUDIT-003 |
| Dimensional homogeneity | Yes | `physis/units.py:58` | Yes | Substrate bypasses Pint | §18 |
| Physical bounds (t > 0, 0 < E ≤ 1) | Yes | — | No | Yes | AUDIT-018 |

**Data lineage matrix:**

| Data/Product | Source | Version | Units | Processing | Quality flags | Provenance | Confidence |
|---|---|---|---|---|---|---|---|
| Physical constants | scipy.constants | CODATA 2022 (scipy 1.16.2) | SI + uncertainty | none | uncertainty kept | Source label | CONFIRMED |
| Material properties | hard-coded catalogue | none | MPa, GPa, °C | linear derating | none | **none** | CONFIRMED |
| Literature records | Crossref, OpenAlex, arXiv, … | probed per run (`source_versions`) | — | normalisation, integrity | retraction flags | manifest | UNVERIFIED (runtime) |
| User datasets | upload | sha256 | user-declared | validators (NaN reject) | rejection reasons | manifest hashes | HIGH |
| Math calibration | `math_eval` holdout3 | `fitted_at` 2026-10-24 | probability | Laplace / Wilson | n per status | no code hash | CONFIRMED |

## 40. Feature / Workflow Failure Matrix

| Workflow | Invalid / missing input | Degenerate numbers | External failure | Concurrent use | Scientifically dangerous? |
|---|---|---|---|---|---|
| Standards check | Unknown clause → compliant | Zero thickness passes for sphere | — | — | **Yes** |
| Geometry | Path/empty → default part | Flat mesh → area wrong | — | — | **Yes** |
| CAE review | — | Zeros → verified | — | — | **Yes** |
| Curve fit | n = p → SE 0, verified | inf pcov → 0 | — | — | **Yes** |
| Math agent | Misparse → `unverified` (honest) | NaN → `partially_verified` | LLM off → rules only | — | Moderate |
| Simulate | 422 on bad spec | factorial blow-up → 504, thread continues | — | per-user slot | Availability |
| Mem0 memory | — | — | — | **Lock failure** | No |
| Harness threads | Any id accepted | — | — | Other users' data | Integrity |

## 41. Risk Summary

| Category | Critical | High | Medium | Low |
|---|---:|---:|---:|---:|
| Scientific Correctness | 2 | 3 | 2 | 1 |
| Numerical | 0 | 1 | 1 | 0 |
| Data Integrity | 0 | 0 | 1 | 1 |
| Reproducibility | 0 | 0 | 1 | 0 |
| Security | 0 | 3 | 2 | 0 |
| UI/UX | 0 | 1 | 0 | 1 |
| Architecture | 0 | 0 | 1 | 0 |
| Reliability | 0 | 0 | 1 | 0 |
| Performance | 0 | 0 | 0 | 0 |
| Testing | 0 | 0 | 1 | 0 |
| Technical Debt | 0 | 0 | 0 | 2 |

**Row mapping:**
- Scientific Correctness: 001, 002; 003, 005, 010; 014, 018; 023.
- Numerical: 007; 016.
- Data Integrity: 015; 022.
- Reproducibility: 013.
- Security: 004, 008, 009; 019, and 016 also counted for availability.
- UI/UX: 006; 021.
- Architecture: 017.
- Reliability: 012.
- Testing: 011.
- Technical Debt: 020, 024.

## 42. Remediation Priorities

**P0 – Must fix before trusting results**

- AUDIT-001, AUDIT-002, AUDIT-003: they fabricate or falsely certify engineering safety results. Alternatively,
  unregister the three substrate tools and the harness substrate routes until fixed.
- AUDIT-004: cross-tenant read/write.
- AUDIT-005, AUDIT-006: the verification signals users rely on are wrong.

**P1 – Must fix before production or research release**

- AUDIT-007, AUDIT-010: wrong uncertainty and unsourced properties.
- AUDIT-008, AUDIT-009: isolation and known CVEs on the input parsers and auth.
- AUDIT-011: the suite is red.
- AUDIT-013, AUDIT-014: calibration and status semantics.

**P2 – Important improvements**

AUDIT-012, 015, 016, 017, 018, 019: reliability, input validation, DoS, placeholder features, CI gating.

**P3 – Cleanup**

AUDIT-020 to 024.

## 43. Verification Plan

| Finding | Method |
|---|---|
| 001, 018 | Known-answer tests for UG-27(c)(1), (c)(2) and (d), including limit violations; negative test for unimplemented clauses |
| 002 | Known-answer tests: cube and tetrahedron volume, area and centroid; missing input → error |
| 003 | Property test: zero, negative or non-finite inputs never yield `cae_verified: True` |
| 004 | Security integration test with two bearer tokens across all 17 harness routes |
| 005, 023 | Regression tests for negative-domain identities and inequality counterexamples |
| 006 | Web rendering test on a recorded math-agent payload |
| 007 | Analytic linear-regression SE comparison; zero-dof and poor-fit tests |
| 008 | Deployment test of backend selection in compose; strict-mode default test |
| 009, 019 | Blocking pip-audit in CI with a reviewed ignore list |
| 010, 015 | Reference-table tests with cited sources; exact-key lookup tests |
| 011, 012 | Green full suite with temporary `HOME` / `MEM0_DIR`; multi-process memory write test |
| 013 | Calibration code-hash check test |
| 014 | NaN and divergent-integral status tests |
| 016 | Parser time-bound test for `factorial` / `gamma` / `binomial` with huge arguments |
| 017 | Wiring tests (checkpoint saved per phase; cost recorded per LLM call) or removal |

None of these verifications has been performed; they are proposals.

## 44. Unverified Items

- Not audited in depth:
  - `tribos/agents/**` orchestration internals (prompt-injection resistance, coverage reconciliation);
  - `tribos/agentic/**` topologies, NLI and counter-evidence;
  - `tribos/scientific/**`, `tribos/export/**`, `tribos/evals/**`, `tribos/archivon/**`;
  - `tribos/verify/verifier.py` citation grounding;
  - most web components.
- Lean, SageMath and the container sandbox: not installed, so their tests were skipped.
- Exploitability of the individual pip-audit advisories; the 10 bandit B608 SQL sites beyond the two inspected.
- Whether the "heuristic" confidence label is shown consistently in the UI; chart axis and units correctness.
- Retraction and literature behaviour against live APIs.
- The handbook magnitude comparison in AUDIT-010 requires domain review.

## 45. What Is Working

- **Authentication and HTTP hardening** (§24-25). All routes outside the harness enforce ownership.
- **Math agent honesty in probes.** For the questions "x²=4", "√x=−1", "sin x=2", "∫₋₁¹1/x", "lim sin(1/x)",
  "n²+n+41 prime", "x⁵−x+1=0", "max x·e^(−x)", "Σ1/n" and "simplify √(x²)":
  - correct `verified` answers where expected;
  - `unverified` or `failed` otherwise;
  - **no false `verified`** (only the NaN `partially_verified` case, AUDIT-014).
- **Sandbox policy.** Of 11 escape attempts, 10 were rejected statically. The remaining one (string-based
  SymPy evaluation, plus two variants) was rejected at runtime with "expressions containing '__' are not
  allowed".
- **engcalc** formulas and validity handling. **Monte Carlo** (seeded, correct SE). **Physis** CODATA 2022
  values with uncertainties. **Pint** offset-unit handling.
- **ODE** rejects failed or non-finite integrations.
- **Run provenance:** code hash, git commit, lockfile hash, served models, tool input/output hashes.
- **Uploads:** streamed limits, extension checks, NaN rejection.
- **Frontend:** XSS controls; token in sessionStorage. Web gates pass (typecheck, 0 eslint errors, 209/209 tests).
- **Honest heuristic-confidence declaration** in `config/confidence_calibration.json`.

## 46. Repository Coverage Matrix

| Path/Directory | Inspected | Findings | Excluded | Reason |
|---|---|---|---|---|
| `app/backend/auth.py`, `security.py`, `routers/harness.py` | Read in full | 004 | — | — |
| `app/backend/main.py`, `routers/agent_runs.py`, `mcp.py`, `a2a.py`, `simulate.py`, `datasets.py` | Read in part (routes, auth, validators) | 016 | — | — |
| `app/backend/routers/projects.py`, `jobs.py`, `export.py` | Grep plus excerpts | — | — | — |
| `tribos/memory/semantic.py`, `tribos/substrate/**` | Read in full (inspector lines 70-158) | 001-003, 010, 015, 018, 022 | — | — |
| `tribos/harness/**` | Excerpts plus caller grep | 017 | — | — |
| `tribos/agentic/sandbox/**` | `__init__`, gateway, backends, process env, policy entry; executed | 008 | — | — |
| `tribos/agentic/mem0_adapter.py` | Excerpts | 012 | — | — |
| `tribos/agentic/**` (other) | Grep only | — | Partial | Depth was budgeted to higher-risk areas |
| `tribos/axiom/**` | Agent calibration section; executed probes | 013, 014, 016 | Partial | — |
| `tribos/verify/math_claims.py` | Lines 1247-1341; executed | 005, 023 | Partial | — |
| `tribos/verify/verifier.py`, `latex_math.py`, `formal/**` | Not inspected | — | Yes | Budget |
| `tribos/dynamis/engine.py`, `monte_carlo.py` | Fit/ODE sections; MC in full; executed | 007 | Partial | — |
| `tribos/engcalc/fatigue.py`, `thermofluid.py` | Formula sections | — | Partial | — |
| `tribos/physis/constants.py`, `units.py` | Excerpts; executed | — | Partial | — |
| `tribos/tools/registry.py` | Lines 478-499, 640-814 | 001-003, 020 | Partial | — |
| `tribos/agents/**`, `tribos/scientific/**`, `tribos/export/**`, `tribos/evals/**`, `tribos/archivon/**` | Grep only | 020 | Yes (depth) | Budget |
| `tribos/provenance/run_manifest.py` | Lines 940-1010 plus grep | — | Partial | — |
| `tribos/datasets/validators.py`, `utils/memory/project_store.py` | Excerpts plus grep | — | Partial | — |
| `web/src/components/DerivationArtifact.tsx`, `MessageArtifacts.tsx`, `artifacts/PaperArtifact.tsx`, `agentic/ui.tsx`, `ReferenceDataArtifact.tsx` | Relevant sections | 006, 021 | Partial | — |
| `web/src/app/page.tsx`, `layout.tsx`, `lib/markdownSafety.ts` | Grep plus excerpts | — | Partial | — |
| `web/src/**` (other ~140 files) | Grep only (XSS, auth, verified) | — | Yes (depth) | Budget |
| `tests/**` | Executed in full; `test_harness_and_memory.py` assertions read | 011 | — | — |
| `.github/workflows/**`, `docker/**` | Grep plus compose read in full | 008, 019 | — | — |
| `docs/**`, README, AGENTS.md | Targeted sections | §36 | Partial | — |
| `.venv`, `web/node_modules`, `.next`, `__pycache__`, `.mypy_cache`, `.ruff_cache` | — | — | Yes | Third-party or generated |
| `*.zip`, `*.pdf`, fonts, PNGs, `.coverage`, `*.log`, `.tribos_*` runtime data | Listed only | 024 | Yes | Binaries or runtime data |
| `.env` | Existence and ignore status only | — | Yes | Secrets; never read |

**Complete coverage is not claimed.**

## 47. Commands and Tools Executed

| Command | Purpose | Result | Exit | Failure cause |
|---|---|---|---|---|
| `.venv/Scripts/python.exe -m pytest -q -p no:cacheprovider -rs` | Full test suite | 10 failed, 2142 passed, 28 skipped, 570.7 s | 1 | 5 application, 5 environment/test design |
| `ruff check tribos app tests scripts --select F,E9` | Blocking lint gate | All checks passed | 0 | — |
| `ruff check tribos app tests scripts` | Full lint (report) | 145 issues (W605 ×10, B905 ×6, …) | 1 | Application (non-gating) |
| `bandit -c pyproject.toml -r tribos app --severity-level high` | Security gate | No high issues printed | 0 | — |
| `bandit … --severity-level medium` | Report | 10× B608, 1× B108 | — | Not individually verified |
| `python scripts/gen_env_reference.py --check` | Settings/docs drift | Clean | 0 | — |
| `npm run typecheck` (web) | TypeScript | Clean | 0 | — |
| `npx eslint src` | Web lint | 0 errors, 167 warnings | 0 | — |
| `npm test` (web) | Web unit tests | 209 pass / 0 fail | 0 | — |
| `python -m pip_audit -l` (text and JSON) | Python CVEs | 385 advisories, 41 packages | 1 | Dependency |
| `npm audit --omit=dev` | JS CVEs | 0 vulnerabilities | 0 | — |
| Scratch Python probes | Reproduce AUDIT-001/002/003/005/007/008/014/015/016; sandbox escapes; units; constants; math agent | Outputs quoted in findings | — | — |
| `git log`, `git diff --stat`, `git check-ignore`, `git ls-files` | Calibration staleness, hygiene | See AUDIT-013, AUDIT-024 | 0 | — |

## 48. Audit Limitations

- **Single-session audit.** Ten parallel sub-auditors were started, then stopped at the user's request to save
  tokens; none of their partial work is used. The audit therefore prioritised depth on the highest-risk areas
  and breadth by grep. Roughly 15-20% of the source was read directly; the rest was surveyed by targeted search
  (§46).
- No browser rendering was performed. UI findings are traced in code against real backend payloads.
- Offline: live literature APIs and the LLM were not exercised; agent probes ran with the rule policy.
- Lean, SageMath and container runtimes were unavailable.
- The working tree contains uncommitted changes, so findings may differ from HEAD `16d0302`.

## 49. Final Engineering and Scientific Assessment

- **What the software is:** a multi-agent STEM research assistant with real symbolic, numerical and engineering
  engines, strong provenance, and an unusually explicit honesty policy.
- **What works:** authentication, the main data APIs, the math agent's own status labels, ODE and Monte Carlo
  numerics, constants and units, the engcalc calculators, the sandbox policy layer, and run manifests. Each is
  supported by executed evidence above.
- **What cannot be trusted:**
  - everything produced by the engineering-substrate layer (ASME compliance, materials at temperature, STL mass
    properties, CAE "14-gate" verdicts);
  - harness data isolation;
  - "Verified" pills on derivation steps;
  - `verified` and standard errors on curve fits;
  - "passed" on sampled identities over real domains.
- **What must be fixed first:** AUDIT-001 to AUDIT-006 (P0), then the isolation default, the dependency
  advisories and the red test suite.

A technically competent engineer can trust Tribos's core computational engines on the evidence here. They
should not yet trust its engineering-standards and CAE outputs, nor take its verification badges at face value
outside the math agent's own run status.

## 50. Remediation Log (2026-10-30)

Applied in the working tree after the audit. Nothing has been committed. Every fix has a regression test, mainly in
`tests/test_feat_audit_report_fixes.py` (49 tests) and `web/tests/featAuditReportFixes.test.mts`.

| Finding | Status | Change |
|---|---|---|
| AUDIT-001 | Fixed | `memory/semantic.py`: UG-27(d) sphere implemented; an unknown or unimplemented clause, or invalid input, returns `compliant: None` with a status, never `True` |
| AUDIT-002 | Fixed | `substrate/cad/inspector.py`: exact facet area; divergence-theorem volume and centroid for closed meshes only; no default part; text without facets raises an error; the tool no longer accepts paths |
| AUDIT-003 | Fixed | `substrate/cae/review.py`: gates are pass, fail or not evaluable; verified only when all 5 are evaluated and passed; the singularity ratio is required (no hidden 1.8); the "14-gate" wording is removed |
| AUDIT-004 | Fixed | `routers/harness.py`: project membership (owner/editor to write) and run ownership on all routes; the revision author is the authenticated user |
| AUDIT-005 | Fixed | `verify/math_claims.py`: identities are also sampled at negative values for unbounded real variables; positive-only agreement is inconclusive, not passed |
| AUDIT-006 | Fixed | `web/src/lib/derivationStatus.ts` and `DerivationArtifact.tsx`: steps show "Ran" or "Not checked" unless explicitly verified; the run status appears in the header |
| AUDIT-007 | Fixed | `dynamis/engine.py`: standard error is None when not estimable; identifiability check on parameter correlation; `converged` comes from the optimiser; `verified` needs convergence, estimable errors and R² > 0; optional `y_sigma` (absolute errors); fit issues reach the evidence block |
| AUDIT-008 | Fixed (deployment) | compose sets `TRIBOS_SANDBOX_STRICT_LIMITS=1`; a one-time warning on unisolated fallback; `os_isolated` in reports; sandbox isolation in `/api/health/details`; setting text corrected |
| AUDIT-009 | Partly fixed | Upgraded pypdf 6.21.2, PyJWT 2.15.0, requests 2.33.0, pyarrow 23.0.1, Pillow 13, aiohttp, urllib3 2.8, cryptography 50, tornado 6.6 and others via `[tool.uv] constraint-dependencies`. **Remaining:** langchain 0.3, transformers 4.55, sentence-transformers 3.3, torch 2.8, mem0ai 0.1, nltk, marshmallow 3, plus the dev-only filelock and virtualenv. These need major or API-breaking upgrades, or a NumPy 2 move |
| AUDIT-010 | Fixed | Properties are reported only at room temperature (15-25 °C), with a data note; other temperatures return None with a limitation. No unsourced derating |
| AUDIT-011 | Fixed | Root cause was AUDIT-025 plus non-hermetic mem0 tests; the rule-numbering tests were updated for grounding rules 8-9 |
| AUDIT-012 | Fixed | mem0's directory is the adapter's storage (no `~/.mem0`, no cross-instance lock); telemetry is set with `setdefault` |
| AUDIT-013 | Fixed | Calibration is bound to `calibrated_code_sha256()`; a stale file is not shown; `math_eval --write-calibration` records the hash. **Action needed:** refit `tribos/axiom/calibration.json` on a frozen-code held-out run to restore the figure |
| AUDIT-014 | Fixed | `axiom/verifier.py`: NaN or complex-infinity answers are `unverified` with the reason |
| AUDIT-015 | Fixed | Exact key, name or alias lookup only |
| AUDIT-016 | Fixed | `safe_expr.py`: combinatorial functions refuse integer arguments over 4 digits |
| AUDIT-017 | Fixed (honest labelling) | The resume endpoint returns `checkpoint_loaded`, `executed: false`; cost endpoints state what is counted; sign-off uses a keyed HMAC over all fields plus an optional `content_sha256`, verified on read. The cost ledger is still not fed by the pipeline |
| AUDIT-018 | Fixed | UG-27(c)(1) and (c)(2) both computed; applicability limits enforced; inputs validated; optional corrosion allowance |
| AUDIT-019 | Fixed | All 60 action references pinned to commit SHAs (tag kept as a comment). The blocking pip-audit gate already existed (see correction) |
| AUDIT-020 | **Deferred** | Single-cell/biomedical code spans approval, plan graph, specialists, state and name sanitizing; removal is a cross-cutting refactor |
| AUDIT-021 | Fixed | `web/src/lib/numberFormat.ts`: significant figures kept below 1 |
| AUDIT-022 | Fixed | `semantic.py` constants read from `scipy.constants` |
| AUDIT-023 | Fixed | An inequality counterexample inside declared domains is FAILED |
| AUDIT-024 | **Not changed** | Local zips, PDFs and logs are the owner's ignored files; the `page.tsx` split and lint auto-fix are large diffs, left for a dedicated change |
| AUDIT-025 | Fixed | Truncation repair applies only to an actual composite eight-part draft; hard-coded fallbacks removed (`MissingScientificResult`); correct result keys; the composite path reports missing results instead of inventing them |

**Gates after remediation:**

| Gate | Result |
|---|---|
| pytest | 2199 passed, 0 failed, 28 skipped (the full run reported 4 `cv2` errors because `uv sync` had dropped the vision extra; restored, and `tests/test_vision.py` reran 15/15) |
| ruff F/E9 | Clean |
| bandit (high) | Clean |
| `gen_env_reference --check` | Clean |
| web typecheck | Clean |
| eslint | 0 errors |
| web tests | 212/212 |
