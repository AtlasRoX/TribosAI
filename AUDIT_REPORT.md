# Scientific Software Complete Audit Report

## 1. Audit Metadata

| Item | Value |
|---|---|
| Repository | `X:\tribois` (Tribos), package version 1.49.1 (installed `tribos-1.49.1.dist-info`) |
| Branch / HEAD | `feat/agentic-engineering-harness-and-memory` @ `40537ca` |
| Working tree | Clean at the start of the audit. This audit changed only this file |
| Audit date | 2026-11-04 |
| Previous audit | `AUDIT_REPORT.md` of 2026-10-30 @ `16d0302`, preserved in git history (`git show 7eb203a:AUDIT_REPORT.md`). Its 25 findings are re-checked in §12a |
| Auditor | Claude Code (Opus 5.5), one session, no sub-agents. **Independence caveat:** the same assistant wrote the research loop, thesis export, accuracy tools and vision ensemble earlier in this conversation. To offset that, every claim about that code rests on executed probes rather than on reading alone (§48) |
| Runtime | Windows 11 Pro 10.0.26200, Python 3.12 (`.venv`), Node 24.19.0, Lean 4 with Mathlib (`TRIBOS_LEAN_PROJECT` set), Tesseract 5.5.3, no running container runtime (Podman installed, daemon stopped) |
| Finding IDs | This audit uses AUDIT-101 to AUDIT-119. Prior findings are referenced as "prior AUDIT-0xx" |

## 2. Executive Assessment

**What the software is.** Tribos is a multi-agent STEM research assistant. It has:
- a FastAPI backend (106 routes);
- a Next.js web app;
- deterministic scientific engines: constants and units (Physis), symbolic and interval mathematics (Axiom), ODEs and fitting (Dynamis), engineering calculators (engcalc);
- an LLM-driven orchestration layer: chat answers, a math agent, and a research loop that writes a thesis;
- a sandbox that runs model-written Python;
- a Lean 4 formal-proof checker;
- an image-reading ensemble (OCR plus a vision model).

**Answer to the primary question:** *Can this software be trusted to produce correct, reproducible, secure, understandable and scientifically defensible results?*

- **The deterministic engines: yes, on the evidence here.** Every known-answer test run in this audit passed:
  - CODATA constants (7 of 7 exact);
  - unit conversions, including offset temperatures (7 of 7);
  - GUM propagation (6 ± 0.5 exact);
  - ODE against the analytic solution (error 2.3 × 10⁻⁹);
  - curve fitting against closed-form OLS (parameters and standard errors identical);
  - beam deflection (PL³/48EI exact);
  - interval proofs and refutations, counterexample search, and normality tests.
- **The "Lean-verified" label: no.** The formal checker certified `2 + 2 = 5` as `verified` in three different ways (**AUDIT-101, CRITICAL**). No stored proof currently uses the bypass, but the top verification tier cannot be trusted until it is fixed.
- **Model-written code on a host without a container runtime: no.** The sandbox's Python-level guards were escaped in a live test (**AUDIT-102, HIGH**):
  - native Win32 calls through `numpy.ctypeslib`;
  - creating a file outside the work directory through `h5py`;
  - launching an external executable through matplotlib's animation writer.

  The documented Docker deployment refuses unisolated execution by default; the local setup this machine runs does not.
- **The research thesis's verification language overstates what is checked** (AUDIT-104 to AUDIT-107):
  - "number-checked" means each number appears somewhere in the evidence, not that it is attached to the right quantity;
  - "replicated" means the same model re-implemented the test, not an independent implementation;
  - hypothesis verdicts have no tier or direction rule;
  - the `certified` tier can be required but never produced.
- **Security of the API: good.** Bearer authentication fails closed. Cross-tenant probes across projects, members, memory, harness, campaigns, figure files and datasets were all refused with 404. Path traversal on project files is refused. Thesis HTML escapes model text.
- **Reproducibility: partial.** Code, ledger and proofs are exported. There is no environment, version, seed or retrieval-date provenance, and results depend on a non-deterministic LLM (AUDIT-110).
- **Software health:**
  - pytest: **2546 passed, 0 failed, 28 skipped**;
  - web tests: 227/227;
  - tsc: clean; eslint: 0 errors (185 warnings);
  - ruff F/E9: clean;
  - bandit: 0 high;
  - pip-audit: 113 advisories remain in 18 of 245 packages (AUDIT-109);
  - strict mypy: 617 errors (non-blocking by design).

**Fix first:** AUDIT-101 (reject every axiom, and check with `#print axioms`), then AUDIT-102 (refuse unisolated execution by default, or block the escape primitives at runtime).

## 3. Audit Scope and Method

1. **Architecture reconstruction:**
   - entry points (`app/backend/main.py`, the routers, `web/src/app`);
   - an AST scan of every route handler for the authentication dependency (`scratchpad/audit/route_auth.py`);
   - router, store and engine structure, mapped by search.
2. **Re-verification of the previous audit's 25 findings**, against current code, tests and probes (§12a).
3. **Deep review of components added since the previous audit:**
   - research loop (`tribos/agentic/research/`);
   - thesis export (`tribos/export/thesis.py`, `svgchart.py`);
   - accuracy tools (`tribos/axiom/accuracy.py`);
   - campaigns API;
   - Lean import handling;
   - vision ensemble (`tribos/vision/`).
4. **Executed probes.** All ran against the real code. Probes that touch persistent state used throw-away directories:
   - a cross-tenant access probe (two bearer users, TestClient, temp storage);
   - two rounds of sandbox escape canaries (harmless payloads only);
   - a Lean axiom-bypass probe against the installed Lean and Mathlib;
   - three rounds of scientific known-answer tests;
   - number-check binding tests.
5. **Gates:**
   - full pytest;
   - web tests;
   - tsc and eslint;
   - ruff;
   - mypy;
   - bandit (JSON triage);
   - pip-audit;
   - checks on GitHub Action pinning and calibration-hash binding.
6. **Not done:**
   - a full read of all source (about 10% read line by line this session; see §46);
   - container-backend isolation tests (no runtime);
   - npm audit;
   - LLM-driven end-to-end runs during the audit. An earlier Collatz research run exists and was inspected read-only.

## 4. Repository Inventory

| Path | Type | Actual purpose (from code) | Size | Entry/exit role |
|---|---|---|---:|---|
| `app/backend/main.py` | FastAPI app | Middleware (security, CORS), chat and stream, memory, health, router registration | 1,100 lines | HTTP entry |
| `app/backend/routers/*.py` | 14 routers | campaigns, datasets, export/runs, files, feedback, harness, jobs, mcp, a2a, projects, simulate, vision, agent_runs | 3,522 lines | HTTP entry |
| `app/backend/{auth,security,limits}.py` | Security | Bearer auth (static tokens and HS256 JWT); body, Origin and Host checks; per-user 429 limits | 495 lines | Middleware and dependency |
| `tribos/agentic/` | Orchestration | Jobs, campaigns, research loop, math agent, sandbox, formal proof stage | 24,161 lines (57 files) | Core |
| `tribos/agents/` | Answer pipeline | Routing, decomposition, drafting, evidence need, question parsing | 17,242 (32) | Core |
| `tribos/axiom/` | Mathematics | Safe parsing, CAS, verifier, certified critical points, accuracy tools, calibration | 11,740 (18) | Scientific |
| `tribos/verify/` | Verification | Written-answer math claims, Lean runner, statement correspondence | 8,209 (12) | Scientific |
| `tribos/dynamis/` | Numerics | ODE, fitting, PDE, Monte Carlo, equilibrium, optimisation | 3,759 (14) | Scientific |
| `tribos/physis/` | Physical data | CODATA constants, pint units, uncertainty, external clients | 1,750 (6) | Scientific |
| `tribos/engcalc/` | Engineering | Beam, buckling, pressure vessel, shaft, bolt, fatigue, electrical, thermofluid | 1,650 (7) | Scientific |
| `tribos/export/` | Export | PDF, DOCX and notebook renderers, thesis HTML/PDF/DOCX/bundle, SVG charts | 4,118 (11) | Output |
| `tribos/datasets/` | Ingestion | Upload validation and storage (single-cell oriented; AUDIT-108) | 1,607 (7) | Data entry |
| `tribos/vision/` | Image input | Indra OCR, Tesseract, vision model, consensus | 1,223 (6) | Data entry |
| other `tribos/*` | Support | evals, utils (LLM factory, memory stores), extensions (tool registry), writer, archivon (literature), tools, scientific, provenance, memory, harness, config, sources, substrate, files, papers, skills | ~33,000 | Mixed |
| `tests/` | pytest | 157 files | 40,846 | Verification |
| `web/src/` | Next.js and TypeScript | components (16,991), lib (4,457), app (3,770), services (3,168), types (1,312), hooks (283) | 29,981 (152 files) | UI |
| `web/tests/` | node:test | 227 tests | | Verification |
| `.github/workflows/` | CI | 11 workflows; 60 action references, all SHA-pinned | | CI |
| `docker/` | Infrastructure | backend, web and sandbox Dockerfiles; compose | | Deployment |
| `scripts/` | Tooling | start script, environment-reference generator, and others | 1,715 | Ops |
| **Excluded** | `web/node_modules`, `.venv`, `__pycache__`, `.mypy_cache`, `.ruff_cache`, `data/`, `logs/`, `.tribos_*` runtime stores, root archives and PDFs (`*.zip`, `gofullpage-*.pdf`; git-ignored) | Generated, vendored or runtime output | | |

## 5. Technology and Runtime Architecture

- **Backend:**
  - FastAPI with uvicorn, Python 3.12;
  - LangChain-based LLM factory (`tribos/utils/llm/llm_factory.py`), with providers Meta (muse-spark-1.3) and NVIDIA NIM;
  - SQLite stores (jobs, projects, research memory);
  - JSON files (campaigns);
  - filesystem stores (datasets, files, figures).
- **Scientific stack:** NumPy, SciPy, SymPy, mpmath (interval arithmetic), pint, pandas, statsmodels, h5py and matplotlib; Lean 4 with Mathlib (subprocess); optional SageMath.
- **Sandbox:**
  - an AST policy (`policy.py`) followed by a subprocess runner with runtime guards (`runner.py`);
  - or a container backend (`container.py`);
  - selected by `gateway._select_backend`.
- **Web:** Next.js (App Router), React, KaTeX.
- **Export:** markdown-it to HTML, then Playwright Chromium to PDF (fpdf2 as fallback); python-docx; pypdf (merging PDFs).
- **Vision:** Indra OCR (ONNX), Tesseract 5 (binary), and the cloud vision model.

## 6. Architecture Reconstruction

- **Boundaries.** The browser calls the API with a bearer token. The API resolves `user_id` (`auth.get_current_user`) and scopes every store call by it; the cross-tenant probes in §25 confirm this. Background work runs as jobs (`tribos/agentic/jobs.py`) and campaigns (`tribos/agentic/campaign.py`). Campaigns are driven by one owner process, under a lock file with heartbeats.
- **Layering.** Scientific engines (Physis, Axiom, Dynamis, engcalc) are pure Python, called through a tool registry (`tribos/extensions/`) by the agent layer. They do not import presentation code. Dependency direction: engines ← tools ← agents ← API. No circular dependency between those layers was found by search; a full import-graph analysis was not run.
- **Leakage.** Dataset ingestion (`tribos/datasets/`) carries a single-cell-transcriptomics domain model into a STEM product (AUDIT-108; prior AUDIT-020).
- **Router isolation.** Routers that fail to import are skipped and listed in `/api/health` (`main.py:172-194`). `TRIBOS_STRICT_ROUTERS=1` makes such a failure fatal.

## 7. Complete Data Flow

1. **Chat question.**
   - Path: UI composer, `POST /api/chat/stream` (`main.py:1031`), security middleware, `get_current_user`, a per-user slot (429), routing and decomposition (`tribos/agents`), tools (engines and sandbox), the draft, the math-claims audit, then SSE back to the UI.
   - Persistence: thread memory, run manifest.
2. **Image question.**
   - Path: UI, `POST /api/vision/read` (auth, Content-Length cap, busy 429), the reader ensemble (Indra and Tesseract, then two vision readings, consensus, coverage gate), a transcription the user can review, then into the chat path.
   - The image is not stored server-side; readings are cached in memory by content hash.
3. **Research project.**
   - Start: `POST /api/campaigns`, then the queue (`TRIBOS_CAMPAIGN_MAX_ACTIVE=1`), then the `ResearchLoop`.
   - Loop: review, charter, then rounds (ready tests run in the sandbox or Lean, plus an optional same-model replication), the findings ledger, analysis, the judge (deterministic rules), and a stop rule.
   - End: the thesis (model chapters plus deterministic tables, figures and theorems, then the number check) and exports.
   - Persistence: campaign JSON (atomic replace), `<id>_files/` figures.
4. **Dataset upload.** `POST /api/datasets` (multipart, provenance JSON required), validators (single-cell oriented), then the store, keeping the sha256 and recording provenance.

## 8. Scientific Processing Pipeline

| Stage | Implementation | Assumptions | Verification in code |
|---|---|---|---|
| Constants | `physis/constants.py` (CODATA via scipy) | CODATA release bundled with SciPy | Exact match (§15) |
| Units | `physis/units.py` (pint) | pint registry definitions | 7 of 7 known answers |
| Uncertainty | `physis/uncertainty.py` (GUM linear and Monte Carlo) | First-order linearisation; correlations as given | GUM exact for x·y |
| ODE | `dynamis/engine.py` (solve_ivp RK45, rtol 1e-8, atol 1e-10) | Smooth right-hand side | Error 2.3e-9 against analytic |
| Fitting | `dynamis/engine.py:612` (curve_fit) | Least squares; SE scaled by residual variance unless `y_sigma` | Identical to closed-form OLS |
| Engineering | `engcalc/structural.py` | Euler–Bernoulli beam, linear elastic | PL³/48EI exact |
| Interval proofs | `axiom/accuracy.py` (mpmath.iv bisection) | Interval arithmetic soundness of mpmath.iv | proved, refuted and enclosure correct |
| Research tiers | `research/runner.py`, `judge.py`, `ledger.py` | The model writes the code, judgements and prose | AUDIT-101, 104 to 107 |
| Formal proofs | `verify/formal/prove.py` and `runner.py` (Lean 4) | The kernel checks the proof; axioms must be rejected | **AUDIT-101** |
| Written-answer audit | `verify/math_claims.py` | Sampled identity checking | AUDIT-111 |

## 9. Feature Inventory

The main features are:
- chat Q&A with tools;
- the math agent;
- the research loop and thesis;
- thesis exports (PDF, DOCX, Markdown, HTML, bundle);
- dataset upload and analysis;
- image and PDF question reading;
- projects, members and memory;
- jobs and run manifests, with re-runs;
- the harness (threads, revisions, sign-off);
- the simulate API;
- the MCP and A2A endpoints;
- the accuracy tools in the tool registry;
- engineering calculators;
- exports of chat answers.

## 10. Feature Status Matrix

| Feature | Status | Evidence |
|---|---|---|
| Auth (static tokens, JWT) | COMPLETE | `auth.py`; 401 and 503 paths; probe |
| Tenant isolation (projects, campaigns, datasets, harness) | COMPLETE | §25 probe: 27 cross-user attempts, all 404 |
| Research loop | PARTIAL | Works end to end (stored Collatz run). Tier semantics defective (AUDIT-104 to 107) |
| Formal verification tier | BROKEN (soundness) | AUDIT-101 |
| Thesis exports | COMPLETE | Collatz PDF, DOCX, MD and bundle exist. Escaping verified |
| Sandbox (subprocess backend) | PARTIAL (not a boundary) | AUDIT-102 |
| Sandbox (container backend) | UNVERIFIED | No container runtime available |
| Accuracy tools | COMPLETE | Known answers pass (§15) |
| Dataset upload | PARTIAL | Rejects two-column and short tables (AUDIT-108) |
| Image reading ensemble | COMPLETE | 12 of 12 benchmark images exact (earlier in this session); probe |
| Engineering calculators | COMPLETE (beam verified; others by tests only) | §15 |
| Math-agent calibrated confidence | DEAD (suppressed) | AUDIT-114 |
| Harness cost ledger | PLACEHOLDER (honestly labelled) | Prior AUDIT-017 |

## 11. Critical Findings

### AUDIT-101 – The Lean checker certifies false theorems that rest on a model-declared axiom

**Severity:** CRITICAL
**Confidence:** CONFIRMED (executed against the installed Lean 4 with Mathlib)
**Category:** Scientific correctness, verification soundness

#### Location
`tribos/verify/formal/runner.py`. Symbols: `_AXIOM_RE` (line 61), `_TRUSTED_FOUNDATIONAL_AXIOMS` (lines 64-72), `uses_unproved` (lines 104-126), `check_lean` (line 218). Consumers:
- `tribos/agentic/research/runner.py:184-186`: tier `formal`;
- `tribos/agentic/research/thesis.py:260`: the "Lean-verified" label;
- `tribos/export/thesis.py:124`;
- `web/src/components/campaigns/ResearchLab.tsx:348`.

#### Problem
A proof counts as `verified` when it compiles and `uses_unproved` finds no `sorry`, `admit` or new axiom. The axiom detection has three gaps:
1. Any axiom whose bare name is in the trusted list (`choice`, `funext`, `propext`, `Quot.lift` and others) is accepted unless its type mentions `False`.
2. The regex requires `axiom` at the start of a line, so `@[simp] axiom` is missed.
3. A namespaced redeclaration (`namespace Foo axiom propext …`) matches the trusted name.

`#print axioms` is never run, so the kernel's own record of a theorem's axioms is never consulted.

#### Evidence
`scratchpad/audit/lean_axiom_probe.py`. Every case proves `(2:Nat) + 2 = 5`:

| Lean code | `uses_unproved` | `check_lean` |
|---|---|---|
| `axiom bogus : … ` (control) | `['axiom bogus']` | `failed` (correct) |
| `axiom choice : (2:Nat) + 2 = 5` | `[]` | **`verified`** |
| `@[simp] axiom helper : …` | `[]` | **`verified`** |
| `namespace Foo axiom propext : … end Foo` | `[]` | **`verified`** |

#### Failure mechanism
1. The model writes the Lean formalisation (`prove.py:143`), which may come from proof search or from injected text.
2. A declaration using one of these spellings passes the text filter.
3. Lean compiles cleanly, because axioms do not produce warnings.
4. The status becomes `verified`, the tier becomes `formal`, and the thesis and UI show **Lean-verified**.

#### Failure scenario
Proof search in the research loop fails to find a real proof and "repairs" the attempt by adding `axiom choice : <goal>`. The theorem enters the thesis as machine-checked.

#### Impact
The strongest verification claim in the product can be attached to a false statement.

**Current data.** The only formal-tier finding in the stored Collatz project (F32) declares no axiom; it was checked read-only. The defect is therefore latent, not yet realised.

#### Root cause
Soundness is checked by pattern-matching the source, with a name-based allowlist, instead of asking the kernel.

#### Recommended fix
- Reject every `axiom` declaration in model-written code, with no allowlist; real foundational axioms are already in Lean core and Mathlib, not in the user file.
- After compiling, run `#print axioms <theorem>` and accept only `propext`, `Classical.choice` and `Quot.sound`.
- Treat `@[…] axiom`, `opaque` and `constant` declarations the same way.

#### Verification
Regression tests with the four probe cases, run against real Lean (skipped when Lean is absent), plus a `#print axioms` assertion test.

#### Related findings
AUDIT-105, AUDIT-107 (tier semantics).

### Prior critical findings
Prior AUDIT-001, 002 and 025 are fixed per their regression tests (§12a).

## 12. High-Severity Findings

### AUDIT-102 – The sandbox's Python-level guards can be escaped; the default `auto` backend runs model code without isolation

**Severity:** HIGH
**Confidence:** CONFIRMED (escape primitives executed). The end-to-end chain from prompt injection to model code is HIGH confidence, not demonstrated.
**Category:** Security

#### Location
- `tribos/agentic/sandbox/gateway.py:94-133` (`_select_backend`: `auto` falls back to `SubprocessBackend` when no container runtime and not strict).
- `tribos/agentic/sandbox/runner.py:326` (`_guard_readers`), `:624` (`_install_io_guard`).
- `tribos/agentic/sandbox/policy.py` (static allowlist).

#### Problem
The static policy blocks literal paths and dangerous names well (18 of 18 first-round payloads refused). The runtime guards only cover Python-level I/O and a list of wrapped readers. C-level file access, native library loading and library features that spawn processes are not covered when the path or name is computed at run time.

#### Evidence
`scratchpad/audit/sandbox_probe.py`, `sandbox_probe2.py` and `sandbox_probe3.py`; backend reported as `{"backend": "subprocess", "os_isolated": false}`:

| Payload (computed names or paths) | Result |
|---|---|
| `numpy.ctypeslib.load_library('kern'+'el32', 'C:/Win'+'dows/System32').GetCurrentProcessId()` | **`ok`, returned 5152**: native Win32 call |
| `h5py.File(<computed path outside the work dir>, 'w')` | **`ok`, file created outside the work directory** (`'w'` truncates an existing file) |
| matplotlib `rcParams['animation.ffmpeg_path'] = 'C:/Windows/System32/' + 'where.exe'` with `FFMpegWriter` | **`Broken pipe`**: the external executable was launched |
| `sympy.utilities.autowrap.autowrap(x**2)` | Spawned an unguarded `python.exe setup.py build_ext` |
| `open`, `np.fromfile`, `pd.read_csv` and `pathlib` with computed paths | Refused at run time (guards work) |

#### Failure mechanism
The model writes code after reading web pages and uploads (indirect prompt injection). Through the primitives above, that code can call any Win32 API as the server user:
- read the repository's `.env`;
- open sockets below the Python-level network stub;
- write or truncate files.

#### Failure scenario
A literature page fetched during a research project contains instructions. The model's analysis cell uses `ctypeslib` to read `.env` and post the keys elsewhere.

#### Impact
API-key theft and code execution on the operator's machine.

**Exposure.** Every host that uses `TRIBOS_SANDBOX_BACKEND=auto` without a running container runtime and without strict mode, which is the default local configuration that this machine runs. The documented compose deployment sets `TRIBOS_SANDBOX_STRICT_LIMITS=1` (`docker/compose.yml:35`) and refuses execution instead (verified in config, not run).

#### Root cause
The default prefers availability (run unisolated, with a log warning) over safety. The runtime guards enumerate Python entry points, while the escape surface lies in native code.

#### Recommended fix
- Make strict mode the default, so that unisolated execution needs an explicit `TRIBOS_SANDBOX_ALLOW_UNISOLATED=1`.
- Add runtime guards for `numpy.ctypeslib.load_library` and `ctypes` (refuse), `h5py.File` with any path outside the work directory, `matplotlib.animation` writers and `rcParams[*_path]`, and `sympy.utilities.autowrap` and `codegen`.
- On POSIX, also drop privileges and use seccomp; on Windows, use AppContainer.

#### Verification
Turn the three payloads into regression tests that must report `policy_violation` or an error, on Windows and Linux.

#### Related findings
AUDIT-103, AUDIT-117; prior AUDIT-008.

## 12a. Status of the Previous Audit's Findings (re-verified 2026-11-04)

| Prior finding | Prior status claim | Current status | Evidence this audit |
|---|---|---|---|
| AUDIT-001 ASME clauses always compliant | Fixed | Fixed per regression tests | `tests/test_feat_audit_report_fixes.py` in the green suite (2546 passed). Not re-derived |
| AUDIT-002 CAD fabricated mass properties | Fixed | Fixed per regression tests | Same |
| AUDIT-003 CAE "14-gate" verdicts | Fixed | Fixed per regression tests | Same |
| AUDIT-004 Harness authorisation | Fixed | **Verified fixed** | Probe: Bob cannot create threads on, or read revisions or spend of, Alice's project (404) |
| AUDIT-005 False real-domain identities passed | Fixed | **Verified: no longer passed**, but labelled inconclusive (AUDIT-111) | Probe on √(x²) = x, \|x\| = x, ln(x²) = 2 ln x |
| AUDIT-006 Derivation "Verified" pills | Fixed | Fixed per web tests | 227/227 web tests |
| AUDIT-007 Curve-fit verified and SE | Fixed | **Verified fixed** | Fit matches closed-form OLS exactly (a = 1.981843, SE = 0.012108); `converged` and `verified` reported |
| AUDIT-008 Sandbox isolation default | Fixed (deployment) | Compose fixed. **The local default remains unisolated, and escapes are confirmed** | AUDIT-102 |
| AUDIT-009 Dependency advisories | Partly fixed | Partly fixed: **113 advisories in 18 of 245 packages** (was 385 in 41) | pip-audit 2.9.0 (AUDIT-109) |
| AUDIT-010 Material properties at temperature | Fixed | Fixed per regression tests | Suite |
| AUDIT-011 Red test suite | Fixed | **Verified**: 2546 passed, 0 failed, 28 skipped | Full run, 730.7 s |
| AUDIT-012 mem0 adapter | Fixed | Fixed per regression tests | Suite |
| AUDIT-013 Stale calibration | Fixed (refit needed) | **Refit still not done**: the file has no `code_sha256`, so calibrated confidence is never shown | AUDIT-114 |
| AUDIT-014 NaN answers partially verified | Fixed | Fixed per regression tests | Suite |
| AUDIT-015 Material substring lookup | Fixed | Fixed per regression tests | Suite |
| AUDIT-016 `factorial` DoS | Fixed | Fixed per regression tests | Suite |
| AUDIT-017 Harness placeholders | Honestly labelled | Unchanged (cost ledger still not fed) | Code reading |
| AUDIT-018 UG-27 applicability | Fixed | Fixed per regression tests | Suite |
| AUDIT-019 Actions tag-pinned | Fixed | **Verified**: 60 of 60 `uses:` pinned to 40-character SHAs | grep |
| AUDIT-020 Biomedical leftovers | Deferred | **Still present, with functional impact** | AUDIT-108 |
| AUDIT-021 Number formatter | Fixed | Fixed per web tests | 227/227 |
| AUDIT-022 Duplicate CODATA | Fixed | Fixed per regression tests; Physis constants verified exact | §15 |
| AUDIT-023 Inequality counterexample inconclusive | Fixed | Fixed per regression tests; the identity analogue remains (AUDIT-111) | Probe |
| AUDIT-024 Repository hygiene | Not changed | Unchanged | AUDIT-116 |
| AUDIT-025 Canned benchmark report | Fixed | Fixed per regression tests | Suite |

## 13. Medium-Severity Findings

### AUDIT-103 – The SageMath engine bypasses strict isolation

**Severity:** MEDIUM. **Confidence:** HIGH (code), exploitation UNVERIFIED (SageMath not installed here). **Category:** Security

#### Location
`tribos/agentic/sandbox/gateway.py:98-100`

#### Problem
`if engine == ENGINE_SAGE: return SageBackend(), None` returns before the strict-mode check. Model-written Sage code runs with the subprocess guards even when `TRIBOS_SANDBOX_STRICT_LIMITS=1`, and Sage widens the import surface (`sage.all`).

#### Evidence
The quoted code. `TRIBOS_SANDBOX_SAGE_ENABLED` defaults to true (`settings.py:376`).

#### Impact
On any host where SageMath is installed, strict mode does not protect Sage executions.

#### Recommended fix
Apply the same strict check, or refuse Sage when strict and no isolating backend can run it.

#### Verification
A unit test: strict mode with engine=sage gives `refused_reason`.

### AUDIT-104 – The thesis "number check" verifies presence, not binding to the right quantity

**Severity:** MEDIUM. **Confidence:** CONFIRMED. **Category:** Scientific correctness, communication

#### Location
`tribos/agentic/research/ledger.py:145` (`evidence_numbers`), `:194` (`unsupported_numbers`). Claims about the check: `tribos/agentic/research/thesis.py:10` ("Every number … is checked against the evidence") and `:373`.

#### Problem
The check extracts the numbers in the text and asks whether each appears anywhere in the evidence set. It does not check what the number is attached to.

#### Evidence
- Evidence: "maximum stopping time 329 at n = 837,799".
- The sentence "The maximum stopping time is 837,799 and it occurs at n = 329." gives `unsupported_numbers` = **`[]`**; the swapped quantities pass.

#### Impact
A model-written chapter can attach correct numbers to the wrong quantities, and the thesis still presents it as number-checked.

#### Recommended fix
- Bind numbers to quantity names: a pattern of quantity name plus number from the ledger's `quantities`, or the stated limitation in the thesis's own text.
- Reword "checked against the evidence" to "each number appears in the evidence".

#### Verification
The swapped-quantity sentence must be flagged.

### AUDIT-105 – "Replicated" means the same model re-implemented the test; the docs and thesis call it independent

**Severity:** MEDIUM. **Confidence:** CONFIRMED (code). **Category:** Scientific validity, labelling

#### Location
`tribos/agentic/research/runner.py:115-138`; `docs/agentic/research-loop.md:38`; `tribos/export/thesis.py:364` ("two independent implementations agree").

#### Problem
The second implementation is produced by the same model, from the same test prompt, with a note not to look at the first one's code. `compare_results` (rtol 1e-6) then decides the tier. Errors that come from a shared misreading of the specification, or from the model's habits, are correlated.

#### Impact
The `replicated` tier counts as strong progress (`judge.progress_snapshot`) and settles deliverables, yet measures repeatability, not independent replication. It is also the strongest tier the research loop can reach without Lean (AUDIT-107).

#### Recommended fix
- Rename it ("re-implemented, same model") or make it independent: a different model or provider, a different method required (for example exact against floating point), or a deterministic reference such as OEIS or an analytical limit.
- Correct the docs and thesis text.

#### Verification
Assert that the replication request uses a different model or method; update the label tests.

### AUDIT-106 – Judge rules check that evidence exists, not that it is relevant or points the right way

**Severity:** MEDIUM. **Confidence:** HIGH (code reading). **Category:** Scientific correctness

#### Location
`tribos/agentic/research/judge.py:63-107`, especially line 76 (deliverable `done`) and line 96 (hypothesis verdicts).

#### Problem
1. A deliverable becomes `done` with any passed finding at the required tier. The charter's `serves` links between tests and deliverables are not consulted.
2. A hypothesis verdict of `supported` or `refuted` is accepted if any cited finding has status `passed` **or `refuted`**. So "supported" may cite a refuted finding, and no tier minimum applies; a `reasoned` finding, which is model-written argument, is enough.

#### Impact
Verdict stamps in the thesis and UI ("supported", "refuted", "done") can rest on unrelated or contrary evidence, chosen by the LLM judge.

#### Recommended fix
- Require at least one cited finding whose test serves the deliverable or hypothesis.
- Require that `supported` has no cited `refuted` findings.
- Set a minimum tier for decided hypotheses.

#### Verification
Unit tests for each rule, with crafted judge proposals.

### AUDIT-107 – The `certified` tier is offered but never produced, so certified deliverables can never be completed

**Severity:** MEDIUM. **Confidence:** CONFIRMED (code). **Category:** Scientific workflow, documentation

#### Location
- Offered at `tribos/agentic/research/charter.py:18`, `:31` and `:37`.
- Ranked at `ledger.py:22-23`.
- Documented at `docs/agentic/research-loop.md:37` ("interval or exact arithmetic, exhaustive finite checks").
- Only `computed` and `replicated` are assigned (`runner.py:114`, `:138`).

#### Problem
`meets("replicated", "certified")` is false, and `validate_charter` does not lower `certified` requirements. The interval tools exist (`axiom/accuracy.py`) but are not connected to tier assignment.

#### Impact
Rounds are spent on deliverables that cannot close. The project stops by stagnation or a ceiling. The thesis says "not yet at the required 'certified' level", which is honest but means the work cannot finish.

#### Recommended fix
Produce `certified` from interval or exact certificates (`interval_verify` status `proved`, exhaustive integer search), or remove the tier from the charter options and docs.

#### Verification
A charter with a certified deliverable can reach `done` through an interval proof.

### AUDIT-108 – Dataset upload validates every table as a single-cell matrix and rejects common scientific tables

**Severity:** MEDIUM. **Confidence:** CONFIRMED (executed). **Category:** Data ingestion, UI/UX

#### Location
`tribos/datasets/validators.py:17-18` (`MIN_OBS = 5`, `MIN_VARS = 2`), `:54-63` (`_check_dims`); `tribos/datasets/models.py:52-66` (`geo_accession`, `organism`, `irb_protocol_id`, `cells_by_genes`).

#### Evidence
Tenant probe 2:
- a two-column table `x,y` with 6 rows gives `422 "The matrix has 1 genes; at least 2 are needed."`;
- a 2-row table gives `422 "The matrix has 2 cells; at least 5 are needed."`;
- a three-column table with 6 rows is accepted.

#### Impact
The most basic measurement shape (one independent and one dependent variable) cannot be uploaded, and the user is told about "cells" and "genes". This is prior AUDIT-020 with a functional consequence.

#### Recommended fix
A generic tabular validator (rows of at least 1, columns of at least 1). Keep the single-cell rules behind an explicit dataset kind.

#### Verification
An upload test for an `x,y` CSV with any number of rows of at least 1.

### AUDIT-109 – Known advisories remain, including in parsers fed untrusted PDFs

**Severity:** MEDIUM. **Confidence:** CONFIRMED (presence of advisories); exploitability UNVERIFIED. **Category:** Supply chain

#### Evidence
pip-audit 2.9.0 against the `.venv`: 245 packages audited, **18 with advisories, 113 advisories**:
- nltk 3.9.2: 42;
- virtualenv 20.34.0: 16;
- transformers 4.55.2: 10;
- torch 2.8.0: 8;
- **pypdf 6.21.2: 7**;
- langchain-core 0.3.40: 6;
- filelock 3.19.1: 4;
- mem0ai 0.1.116: 4;
- langsmith 0.1.147: 3;
- pymdown-extensions 10.16.1: 3;
- langchain 0.3.7: 2;
- langchain-text-splitters 0.3.6: 2;
- langchain-openai 0.3.0, marshmallow 3.26.1, mkdocs-material 9.6.21, pylint 3.3.8, pytest 8.4.2 and sentence-transformers 3.3.1: 1 each.

pypdf parses untrusted input at three places: uploaded datasets (`tribos/datasets/validators.py:175`), downloaded papers (`tribos/papers/extract.py:93`) and fetched literature (`tribos/archivon/engine.py:379`).

#### Impact
Likely denial of service from crafted PDFs. Each advisory's applicability was not analysed.

#### Recommended fix
- Upgrade pypdf first, since it is on the untrusted-input path.
- Then plan the LangChain 0.3 and transformers or torch majors, as the previous audit noted.

#### Verification
A pip-audit gate (already in CI per the prior audit) with an allowlist of accepted risks.

### AUDIT-110 – Research results are only partially reproducible: no environment or version provenance

**Severity:** MEDIUM. **Confidence:** CONFIRMED (code). **Category:** Reproducibility, provenance

#### Location
`tribos/agentic/research/thesis.py:320` (the run record states the model name and research ID only); `tribos/export/thesis.py:515` (`thesis_bundle` writes `thesis.md`, `code/*.py`, `proofs/*.lean`, `ledger.json` and `README.md`).

#### Problem
The bundle omits:
- the software commit and version;
- Python, NumPy, SciPy and SymPy versions;
- Lean and Mathlib versions;
- the exact model version or date;
- sandbox allowlist and limits;
- random seeds used by cells (not enforced);
- retrieval dates and URLs of web sources.

Model-written charters, judgements and prose are not deterministic.

#### Impact
The numbers in a finding can be recomputed from its code. The thesis as a whole (its plan, verdicts and text) cannot be reproduced, and an environment-sensitive result (floating point, library behaviour) cannot be traced. Classification: **partially reproducible**.

#### Recommended fix
Write a `manifest.json` into the bundle and the thesis appendix: commit, `pip freeze` subset, Lean toolchain and Mathlib revision, model id and provider date, seeds, source URLs with access dates.

#### Verification
The bundle contains the manifest, and a test checks its fields.

## 14. Low-Severity Findings

### AUDIT-111 – A disproved real-domain identity is labelled "inconclusive"
**Severity:** LOW. **Confidence:** CONFIRMED.

**Location:** `tribos/verify/math_claims.py:1404`.

**Evidence:** √(x²) = x, |x| = x and ln(x²) = 2 ln x "for all real x" all return `inconclusive: holds for positive values only; differs at …`.

**Impact:** The claim is false where the checker found a differing point, but the label does not say so. Inequalities were already changed to FAILED (prior AUDIT-023).

**Fix:** Report FAILED with the counterexample when the statement's domain includes it.

### AUDIT-112 – The number check flags correct numbers that are followed by a comma
**Severity:** LOW. **Confidence:** CONFIRMED.

**Location:** `tribos/agentic/research/ledger.py:27` (`_NUMBER_RE`, lookahead `(?![\d,])`).

**Evidence:** "occurs at n = 837,799, as computed" gives unsupported `['837', '799']`, while the evidence contains 837,799.

**Impact:** False "unverified number" notes in the thesis appendix. This erodes trust in the real flags.

**Fix:** Allow a trailing comma followed by whitespace, or a non-digit, in the grouped-number branch.

### AUDIT-113 – (reserved; no finding retained)
This placeholder is kept so that IDs stay stable. The candidate (that `concluded` ignores undecided hypotheses) matches the documented rule (`research-loop.md:51`), so it is not a defect.

### AUDIT-114 – Math-agent calibration is never shown (the refit from the prior audit is still pending)
**Severity:** LOW. **Confidence:** CONFIRMED.

**Location:** `tribos/axiom/agent.py:845-885`; `tribos/axiom/calibration.json` (no `code_sha256`).

**Evidence:** `calibrated_confidence()` returns `None` for a file without a matching hash.

**Impact:** The calibrated accuracy figure promised by the math agent is never shown. This is correct behaviour for stale data, but the feature is effectively dead.

**Fix:** Refit on a frozen-code held-out run with `math_eval --write-calibration`.

### AUDIT-115 – Strict mypy has 617 errors in 133 files; it is non-blocking by design
**Severity:** LOW (INFORMATIONAL for correctness). **Confidence:** CONFIRMED.

**Location:** `pyproject.toml:209-222`; `.github/workflows/tests_scientific_validation.yml:111-128` ("Strict mypy has never been enforced…").

**Impact:** Type errors on scientific paths are not caught statically.

**Fix:** Enforce on new and changed files first.

### AUDIT-116 – Repository root clutter and parallel audit documents
**Severity:** LOW. **Confidence:** CONFIRMED.

**Evidence:** The repository root holds:
- about 20 `.t*-*.log` files;
- two 8.8 MB codebase zips (git-ignored);
- a page-capture PDF;
- several overlapping report documents: `CODEBASE_AUDIT.md`, `ACCURACY_REPORT.md`, `RELIABILITY_ISSUE_REPORT.md`, `Tribos_Scientific_Repair_Report.md`, `TRIBOS_COMPLETE_AUDIT_AND_REPAIR_CHANGELOG.md (1).md`, and two prompt files.

None of this contains secrets (the archive name scan found no `.env` or key files).

**Impact:** Contradictory status claims across documents; confusion about which is authoritative. This report replaces only `AUDIT_REPORT.md`.

**Fix:** Move historical reports to `docs/history/` and delete the logs.

### AUDIT-117 – Long-running research compute has no per-user queue cap (UNVERIFIED) and a raised timeout ceiling
**Severity:** LOW. **Confidence:** MEDIUM.

**Location:** `tribos/agentic/sandbox/__init__.py:38-58` (the `research_ceiling` raises the per-cell timeout to `TRIBOS_RESEARCH_SANDBOX_TIMEOUT_S`, up to 1,800 s, above the 110 s maximum of `TRIBOS_SANDBOX_TIMEOUT_S`); `campaign.py` (`TRIBOS_CAMPAIGN_MAX_ACTIVE=1` per process). No per-user limit on queued projects was found by search.

**Impact:** One user can occupy the research queue for everyone. Each project runs for hours of model and sandbox time.

**Fix:** A per-user queued and active cap, and a 429 on `POST /api/campaigns`.

### AUDIT-118 – The vision cross-check uses the same model for both readings and for the review (INFORMATIONAL)
**Location:** `tribos/vision/reader.py` (`_settle`), `tribos/vision/vlm.py`.

Agreement between two readings from one model is self-consistency, not independent confirmation. The real independence comes from the two OCR engines, which are used for the word-coverage gate. This is documented in `docs/agentic/image-reading.md`. The consensus labels ("two independent vision readings agreed") slightly overstate the independence.

### AUDIT-119 – Model-written content in research outputs (INFORMATIONAL)
Charters, analyses, judgements and thesis prose are written by an LLM. Code checks numbers (AUDIT-104) and evidence existence (AUDIT-106) only. Readers should treat the prose as unreviewed scientific writing. The thesis states its tiers, but not this limitation in general.

## 15. Scientific Correctness Findings

Known-answer tests executed in this audit (`scratchpad/audit/science_kat*.py`):

| Component | Test | Reference | Result |
|---|---|---|---|
| CODATA constants | c, h, k_B, N_A, G, e, m_e | `scipy.constants` (CODATA 2022) | 7 of 7 exact (relative difference below 1e-9) |
| Units | atm to Pa, °C to K, °F to K, mile to m, kWh to J, psi to kPa, rad to deg | Exact definitions | 7 of 7 |
| GUM | x·y, x = 2 ± 0.1, y = 3 ± 0.2 | 6 ± 0.5 | Exact |
| ODE | y′ = −0.5y, y(0) = 1, t in [0, 4] | e^(−t/2) | max error 2.31e-9 |
| Fit | a·t + b on 21 noisy points | Closed-form OLS | a and SE(a) identical to 6 digits |
| Beam | Simply supported, centre load | PL³/48EI = 2.000e-4 m | Exact; section I exact |
| Interval | x²+1 > 0 on [−10, 10]; x²−1 > 0 on [−2, 2]; enclosure of sin on [0, π] | Analytic | proved; refuted at x = 0; [0, 1] |
| Precision | (1 − cos x)/x² at x = 1e-8 | 0.5; float64 cancels | `status: cancellation` |
| Counterexample | n²+n+41 prime for n ≤ 100 | Fails at n = 40 | n = 40 |
| Distribution | N(5, 2) against Exp(1), n = 400 | Normality holds or is rejected | consistent (Shapiro p = 0.57) / rejected (p = 3e-21) |
| Lean | 2+2 = 5 via axiom spellings | Must fail | **verified (AUDIT-101)** |
| Number check | Swapped quantities | Must flag | **not flagged (AUDIT-104)** |

**Implementation, numerical and scientific validity, separated:**
- **The engines above** are correct in implementation and numerically sound on the tested cases. Validity depends on users choosing the models within their stated assumptions (linear elasticity, first-order GUM).
- **The research tier system** has implementation defects (AUDIT-101, 107) and validity defects in its labels (AUDIT-104 to 106).

**Scientific invariant matrix**

| Invariant | Expected | Where enforced | Tested | Violation possible | Evidence |
|---|---|---|---|---|---|
| Formal proof uses no new axioms | Always | `runner.uses_unproved` | Partly | **Yes** | AUDIT-101 |
| A number in the thesis is the evidence's value for that quantity | Always | `unsupported_numbers` (presence only) | No | **Yes** | AUDIT-104 |
| A deliverable is done only on relevant evidence at its tier | Always | `apply_judgement` (tier yes, relevance no) | Partly | **Yes** | AUDIT-106 |
| Sandbox writes stay in the work directory | Always | Policy and runtime guards | Literal paths yes | **Yes (h5py)** | AUDIT-102 |
| Dimensional homogeneity of stated equations | When checked | `physis/units.check_dimensional_homogeneity` | Tests in suite | Not probed | Unverified here |
| p-values in [0, 1]; tests consistent | Always | SciPy | Probe | No | §15 |
| Tier ranking is monotone | Always | `ledger.TIER_RANK` | Code | No | `ledger.py:22` |

## 16. Numerical Computing Findings

No verified numerical defect in the tested engines:
- the ODE solver uses rtol 1e-8 and atol 1e-10 (reported in the result);
- the fit reports `std_error_basis`, degrees of freedom and maximum parameter correlation;
- `precision_check` detects cancellation;
- interval tools use mpmath.iv with a box cap and a time limit (`accuracy.py:73`).

`compare_results` uses rtol 1e-6 and atol 1e-9 for replication. That is reasonable for double-precision recomputation, but no scale analysis is documented.

## 17. Scientific Data Findings

- AUDIT-108: generic tables are rejected by the single-cell validator.
- Uploads keep a sha256 and require a provenance object (verified: a missing `provenance` gives 422).

**Data lineage matrix**

| Data/product | Source | Version | Units | Time standard | Processing | Quality flags | Provenance | Confidence |
|---|---|---|---|---|---|---|---|---|
| Physical constants | scipy.constants | CODATA bundled with the installed SciPy | SI, from the CODATA table | n/a | Lookup | Uncertainty from CODATA | Name and value returned | HIGH |
| Uploaded datasets | User | sha256 per file | `units` dict in provenance (optional) | Not normalised | Validators, then store | PHI column warnings (single-cell era) | Provenance JSON required | HIGH (storage); data semantics UNVERIFIED |
| Research findings | Sandbox runs of model code | None (AUDIT-110) | From quantity names only | Run timestamps (epoch) | `quantities_from_result` | Tier, status, replication | Code stored; no environment | MEDIUM |
| Literature | arXiv and others via archivon | Mutable; no retrieval date in the thesis | n/a | n/a | Parsers (pypdf; AUDIT-109) | None | URL | LOW |
| Image readings | User upload (not stored) | Content hash in memory | n/a | n/a | OCR, vision, consensus | consensus, unconfirmed_numbers, warnings | Engines named in the log | HIGH |

## 18. Units / Dimensions / Coordinates / Time Findings

- **Units:** pint conversions verified, including the affine temperature scales (§15).
- **Coordinates and CRS:** not applicable. The repository has no geospatial processing (search found no CRS or projection code paths).
- **Time:** campaign timing uses epoch seconds (`time.time()`), with active time tracked separately (`loop.active_s`). No timezone-sensitive computation was found on scientific paths.

No verified finding identified in this category beyond those already listed.

## 19. Statistical / ML Findings

- `distribution_tests` behaves correctly on the probe samples.
- The fit's SE uses residual-variance scaling unless `y_sigma` is given. That is standard, and documented in the docstring.
- No ML training pipeline is present; the models are inference-only (OCR, embeddings).

No verified finding identified in this category.

## 20. Reproducibility Findings

See AUDIT-110.

| Question | Answer |
|---|---|
| Can a result be reproduced? | A finding's numbers: yes, from its code (`bundle/code`). The thesis as a whole: no (LLM) |
| Can the processing history be reconstructed? | Partly: the round, test and finding records are kept in the campaign JSON |
| Can the dataset version be identified? | Uploads: yes (sha256). Web sources: no |
| Can the algorithm version be identified? | No commit is recorded |
| Can parameters be recovered? | Code contains them; sandbox limits are not recorded |
| Can the environment be reconstructed? | No |

Classification: **partially reproducible**.

## 21. Provenance Findings

The chain from input to output is preserved up to the finding's code and its stdout, the plots and the replication code (`ledger.json`). Missing: the software version, library versions, model version, and source retrieval dates (AUDIT-110).

## 22. Scientific Visualization Findings

- Thesis charts (`tribos/export/svgchart.py`):
  - a single y-axis;
  - ×10ⁿ tick labels;
  - escaped labels (`escape()` on every model-provided label; line 138 interpolates a constant);
  - figures are captioned and numbered.
- Plots from the sandbox are kept as PNGs, with duplicates removed by hash.
- No verified finding identified (the charts were not audited against their data point by point).

## 23. UI/UX Findings

**Scientific trust matrix**

| Workflow | User sees | Actual state | Meaning clear? | Uncertainty clear? | Provenance clear? | Risk |
|---|---|---|---|---|---|---|
| Research lab, Proofs | "Lean-verified" seal | Can rest on a model-declared axiom (AUDIT-101) | No | n/a | Lean code shown | **High** |
| Research lab, Findings | "Replicated" seal | Same-model re-implementation (AUDIT-105) | Overstated | Rows of agreement shown | Code shown | Medium |
| Thesis, numbers | "Numbers … the automatic check could not match" | Presence-only check (AUDIT-104) | Overstated | n/a | Ledger | Medium |
| Hypothesis cards | supported / refuted stamps | Evidence relevance and direction not enforced (AUDIT-106) | Overstated | n/a | Evidence IDs shown | Medium |
| Image viewer | "two independent vision readings agreed" | Same model twice, plus two OCR engines | Slightly overstated | Unconfirmed numbers shown | Engines summarised | Low |
| Dataset upload | "matrix has 1 genes" | Generic table rejected (AUDIT-108) | Misleading | n/a | n/a | Medium |
| Math agent | No calibrated confidence | Calibration stale (AUDIT-114) | Yes | Not shown | n/a | Low |

## 24. Security Findings

- AUDIT-102 (HIGH): sandbox escapes.
- AUDIT-103 (MEDIUM): Sage engine bypasses strict mode.
- AUDIT-109 (MEDIUM): dependency advisories.

Bandit: 0 high. The 15 medium findings were triaged:
- **B608 ×10:** SQL built from fixed column tuples with parameterised values (`project_store.py:413`, `jobs.py:263-318`, `research_memory.py:663`); false positives.
- **B314 ×1:** `ET.fromstring` on arXiv Atom (`archivon/clients.py:157`). Python 3.12 expat limits entity amplification, and etree does not resolve external entities; low.
- **B108 ×1:** the `--tmpfs` flag string in `container.py:164`; false positive.
- **B615 ×3:** Hugging Face downloads without a pinned revision; locations not individually triaged (UNVERIFIED).

**Verified controls:**
- Markdown is rendered with `html: False` (`export/thesis.py:43`).
- Figures in exports resolve only to local files.
- The campaign file route uses a realpath containment check, and traversal names are refused (4 of 4 in the probe).
- Unauthenticated routes are limited to health, metadata and 405 stubs (11 of 106).

## 25. Authentication and Authorization Findings

- **Authentication** (`app/backend/auth.py`):
  - static tokens compared with `hmac.compare_digest`;
  - HS256 JWT with `exp` and `sub` required and a fixed algorithm list;
  - 503 when no credential source is configured;
  - `TRIBOS_AUTH_MODE=disabled` is restricted to loopback clients by `SecurityMiddleware` (observed: non-loopback TestClient refused with 403).
- **Authorization probe** (`scratchpad/audit/tenant_probe.py`, `tenant_probe2.py`; two bearer users; temp storage). Every attempt by user B on user A's resources was refused (404), and A kept access:
  - projects: get, patch, delete;
  - members: list, self-add as editor;
  - memory: get, post;
  - project files;
  - harness: threads, revisions, spend;
  - campaigns: get, report, thesis, file, delete;
  - datasets: get, patch provenance, delete;
  - attaching A's dataset to B's project or to A's project;
  - unknown job, run and file IDs.

No verified finding identified in this category.

## 26. API Findings

- 106 routes; request models have length limits; campaign IDs are regex-checked.
- `/api/health` exposes the auth mode and provider availability as booleans only (by design, SEC-005).

No verified finding identified beyond AUDIT-117 (no per-user research-queue cap, UNVERIFIED).

## 27. Database Findings

SQLite stores use parameterised queries; dynamic SQL is limited to fixed column names (bandit triage). Campaigns are JSON documents written atomically (temp file plus `os.replace` under a lock; `campaign.py:288-292`). Schema constraints and migrations were not reviewed in depth (§44).

No verified finding identified.

## 28. Concurrency and State Findings

- Campaign ownership uses a process token, pid and start time, with heartbeats. A dead owner's project is resumed (`campaign.py:70-80`, `:361-370`).
- The sandbox concurrency semaphore is `TRIBOS_SANDBOX_MAX_CONCURRENCY=2`.
- Vision readings are cached by content hash plus provider, and only complete readings are cached.

No verified race was found; concurrency was not stress-tested.

## 29. Reliability and Error Handling

- Provider outages pause a research project with a resumable error.
- A disabled router is reported, not fatal.
- A failed vision call falls back (other reading, local model, or OCR with a warning).
- A repaired Lean import is recorded as `dropped_imports`.

No verified finding identified.

## 30. Performance Findings

- Each research project runs for hours of model and sandbox time (AUDIT-117).
- Image reading takes 3.5 to 8 s with the cross-check, measured earlier in this session.

No benchmark was run in this audit.

## 31. Testing Findings

- **pytest:** 2546 passed, 28 skipped, 0 failed (730.7 s).
- **Web:** 227/227. **tsc:** clean.
- **Scientific known-answer coverage** exists for the engines. The missing tests, each of which matches a finding here:
  - Lean axiom bypasses (AUDIT-101);
  - native-code and C-level sandbox escapes (AUDIT-102);
  - number-quantity binding (AUDIT-104);
  - judge relevance and direction (AUDIT-106);
  - generic two-column uploads (AUDIT-108).

## 32. Dependency / Supply-Chain Findings

See AUDIT-109. GitHub Actions are SHA-pinned (60 of 60). `uv.lock` pins the Python dependencies. npm audit was not run.

## 33. Configuration / Infrastructure Findings

- The compose file sets strict sandbox limits, binds to 127.0.0.1, and uses a read-only root filesystem and `cap_drop` (`docker/compose.yml`).
- The backend image now installs `tesseract-ocr`.
- The defaults that matter for safety are `TRIBOS_SANDBOX_BACKEND=auto` together with `TRIBOS_SANDBOX_STRICT_LIMITS=false` (AUDIT-102).
- The environment reference is generated and checked (`scripts/gen_env_reference.py --check` clean).

## 34. Technical Debt

- Single-cell domain model in data ingestion (AUDIT-108).
- Strict typing not enforced (AUDIT-115).
- Two tier vocabularies, one of which has an unreachable level (AUDIT-107).
- Overlapping report documents at the root (AUDIT-116).
- `mkdocs` and docs dependencies carry advisories (AUDIT-109).

## 35. Dead Code / Placeholder / Mock Findings

- `calibration.json` is effectively dead (AUDIT-114).
- The harness cost ledger is honestly labelled but not fed (prior AUDIT-017).
- `tribos/verify/formal/correspondence.py` is **live**: it is used by `prove.py:22` and `:122-150`. An initial search suggested otherwise; that was corrected.

No mocked scientific results were found on production paths (prior AUDIT-025 fixed per tests).

## 36. Documentation Inconsistencies

| Document | Claim | Code | Finding |
|---|---|---|---|
| `docs/agentic/research-loop.md:37` | `certified` from interval or exact arithmetic | Never assigned | AUDIT-107 |
| `docs/agentic/research-loop.md:38`, `export/thesis.py:364` | Replicated means "two independent implementations" | Same model | AUDIT-105 |
| `research/thesis.py:10` | "Every number … is checked against the evidence" | Presence only | AUDIT-104 |
| `verify/formal/runner.py:7` | "verified": no sorry, admit or **new axiom** | Axioms with trusted names pass | AUDIT-101 |
| `sandbox/policy.py:20-22` | "defence in depth, not a boundary" | Accurate; the default still runs it as the only boundary | AUDIT-102 |

## 37. Root-Cause Analysis

1. **Verification by text pattern instead of by the authority.**
   - Lean axioms are found by regex rather than by `#print axioms` (AUDIT-101).
   - Numbers are matched by presence rather than by quantity (AUDIT-104).
   - Consequence: the strongest labels can be produced by inputs the patterns don't anticipate.
2. **Availability defaults over safety defaults.** `auto` runs unisolated with only a log warning (AUDIT-102), and the Sage engine skips the strict check (AUDIT-103). Consequence: the local deployment executes untrusted code with the operator's privileges.
3. **Labels that are stronger than the mechanism.** "Independent" means the same model (AUDIT-105); "certified" is unreachable (AUDIT-107); "supported" has no direction check (AUDIT-106). Consequence: readers overestimate the evidence.
4. **A domain carry-over** (single-cell biology) in data ingestion (AUDIT-108).

## 38. Security Control Matrix

| Control | Present | Verified how | Gaps |
|---|---|---|---|
| Authentication | Yes | Code and probe | none found |
| Per-resource authorization | Yes | 27-case probe | none found |
| Path-traversal guard (files) | Yes | 4-case probe | none found |
| Output escaping (thesis HTML, SVG) | Yes | Code | none found |
| Sandbox static policy | Yes | 18-payload probe | Computed names and paths (AUDIT-102) |
| Sandbox runtime guards | Partial | Probe | ctypes, h5py, spawning libraries (AUDIT-102) |
| OS isolation of model code | Container backend only | Config | Not default; Sage bypass (AUDIT-102, 103) |
| Rate and concurrency limits | Chat, re-run, simulate, vision | Code | Research queue per user (AUDIT-117) |
| Dependency scanning | pip-audit | Executed | 113 advisories (AUDIT-109) |
| CI supply chain | SHA-pinned actions | grep | none found |
| Secrets in logs | None found by search | grep | Not exhaustive |

## 39. Scientific Validation Matrix

| Component | Algorithm/model | Inputs | Units | Assumptions | Validation evidence | Tests | Risk | Confidence |
|---|---|---|---|---|---|---|---|---|
| Constants | CODATA lookup | Name | SI | Bundled CODATA | Exact against scipy | Suite and probe | Low | HIGH |
| Units | pint | Value, units | Any | pint definitions | 7 known answers | Suite and probe | Low | HIGH |
| Uncertainty | GUM linear and Monte Carlo | Expression, σ | Propagated by pint | First order | x·y exact | Suite and probe | Low | HIGH |
| ODE | RK45 | Right-hand side, initial state | User | Smooth | Analytic, 2e-9 | Suite and probe | Low | HIGH |
| Fit | curve_fit | x, y, σ | User | Gaussian errors | OLS-identical | Suite and probe | Low | HIGH |
| Beam | Euler–Bernoulli | L, E, I, P | SI | Linear elastic, small deflection | PL³/48EI | Suite and probe | Low | HIGH |
| Interval verify | mpmath.iv bisection | Expression, box | n/a | mpmath.iv soundness | 3 cases | Suite and probe | Low | HIGH |
| Counterexample | Exhaustive or sampled | Claim, domain | n/a | Search is not proof (stated) | n²+n+41 | Suite and probe | Low | HIGH |
| Distribution tests | Shapiro–Wilk, D'Agostino, Anderson–Darling, KS, bootstrap | Sample | n/a | i.i.d. | Normal against exponential | Suite and probe | Low | HIGH |
| Identity audit | Sampled equality | Text | n/a | Domain from the text | Not passed; labelled inconclusive | Suite and probe | Low | HIGH |
| **Lean formal** | Lean 4 kernel plus text filter | Model code | n/a | No new axioms | **False theorem verified** | Partial | **Critical** | CONFIRMED |
| **Replication tier** | Same-model re-implementation | Test prompt | n/a | Independence (not met) | Code | Suite | Medium | CONFIRMED |
| **Number check** | Presence matching | Thesis text | n/a | Binding (not met) | Swapped-quantity probe | Partial | Medium | CONFIRMED |
| Vision ensemble | Two OCR engines plus 2× VLM plus review | Image | n/a | Same model twice | 12 benchmark images exact | 30 tests | Low | HIGH |

## 40. Feature / Workflow Failure Matrix

| Workflow | Invalid input | External API down | Computation fails | Repeat / concurrent | Dangerous scientific failure |
|---|---|---|---|---|---|
| Chat with tools | 422 or refusals | Provider error, retry | Tool error surfaced | Per-user slot, 429 | Model prose not fully checked |
| Research loop | Charter validated | Pauses, resumable | Test retried, then blocked | One active per process | AUDIT-101, 104 to 107 |
| Thesis export | n/a | n/a | Chromium missing: fpdf fallback | n/a | AUDIT-104 labels |
| Dataset upload | 4xx with reason | n/a | n/a | n/a | AUDIT-108 rejects valid data |
| Image reading | 4xx | Fallbacks, warning | OCR text with warning | 429 busy | Mis-transcription reduced by consensus |
| Sandbox | Policy violation | n/a | Error or timeout | Semaphore | AUDIT-102 escapes |

## 41. Risk Summary

| Category | Critical | High | Medium | Low |
|---|---:|---:|---:|---:|
| Scientific Correctness | 1 | 0 | 4 | 2 |
| Numerical | 0 | 0 | 0 | 0 |
| Data Integrity | 0 | 0 | 1 | 0 |
| Reproducibility | 0 | 0 | 1 | 0 |
| Security | 0 | 1 | 2 | 0 |
| UI/UX | 0 | 0 | 0 | 0 (overstatements counted under Scientific) |
| Architecture | 0 | 0 | 0 | 0 |
| Reliability | 0 | 0 | 0 | 0 |
| Performance | 0 | 0 | 0 | 1 |
| Testing | 0 | 0 | 0 | 1 |
| Technical Debt | 0 | 0 | 0 | 2 |

The rows come from:
- Scientific Correctness: 101 / 104, 105, 106, 107 / 111, 112.
- Data Integrity: 108.
- Reproducibility: 110.
- Security: 102 / 103, 109.
- Performance: 117.
- Testing: 114.
- Technical Debt: 115, 116.
- Informational, not counted: 118, 119.

## 42. Remediation Priorities

- **P0, before trusting results or running research locally:**
  - AUDIT-101: the false "Lean-verified" label is a direct scientific-integrity failure.
  - AUDIT-102: untrusted code with the operator's privileges on the default configuration.
- **P1, before a research or production release:**
  - AUDIT-103 (strict-mode bypass);
  - AUDIT-104, 105, 106 (verification labels the thesis presents as facts);
  - AUDIT-107 (unreachable tier);
  - AUDIT-109 (pypdf on untrusted input first);
  - AUDIT-110 (reproducibility manifest).
- **P2, important improvements:**
  - AUDIT-108 (generic uploads);
  - AUDIT-111 and 112 (label and parse accuracy);
  - AUDIT-114 (calibration refit);
  - AUDIT-117 (per-user research quota).
- **P3, cleanup:** AUDIT-115, 116, 118, 119.

## 43. Verification Plan

| Finding | Method |
|---|---|
| AUDIT-101 | Regression tests with the four Lean probe cases plus a `#print axioms` assertion (real Lean, skipped if absent) |
| AUDIT-102 | Sandbox regression tests: ctypeslib, h5py computed path, matplotlib writer path, autowrap must fail; run on Windows and Linux CI |
| AUDIT-103 | Unit test: strict mode with engine=sage refuses |
| AUDIT-104 | Known-answer test: swapped-quantity sentence flagged |
| AUDIT-105 | Test that the replication request differs in model or method; label test |
| AUDIT-106 | Unit tests on `apply_judgement` with irrelevant, contrary and reasoned-only evidence |
| AUDIT-107 | Integration test: a certified deliverable closes via an interval proof |
| AUDIT-108 | Upload tests: x,y CSV with 1 to 6 rows |
| AUDIT-109 | pip-audit gate; pypdf upgrade plus fuzz smoke test on malformed PDFs |
| AUDIT-110 | Bundle manifest field test |
| AUDIT-111, 112 | Unit tests on the quoted inputs |
| AUDIT-114 | Calibration file carries the current code hash after a refit |
| AUDIT-117 | API test: second queued project for the same user gets 429 |

## 44. Unverified Items

- Container backend isolation; no runtime was available.
- Exploitability of the 113 advisories, pypdf included.
- B615 locations (Hugging Face downloads without a pinned revision).
- A per-user research queue cap (none found by search).
- Prior fixes for AUDIT-001, 002, 003, 010, 012, 014, 015, 016, 018, 021, 022, 023 and 025: verified by their regression tests only.
- Engineering calculators other than the beam.
- PDE, Monte Carlo and optimisation engines.
- Database schemas and migrations.
- Frontend behaviour beyond the code paths and earlier screenshots in this session.
- npm audit.
- End-to-end prompt-injection exploitation of AUDIT-102.

## 45. What Is Working

The following are supported by executed evidence in this audit:
- authentication and per-resource authorization (27 probes);
- path-traversal guards;
- escaping of HTML and SVG exports;
- the sandbox's static policy (18 of 18 literal-path, native and network payloads refused) and its Python-level runtime guards on computed `open`, `np.fromfile`, `pd.read_csv` and `pathlib` paths;
- CODATA constants, units, GUM, ODE, curve fitting, the beam calculator, interval proofs, precision check, counterexample search and distribution tests (§15);
- the identity audit no longer passing false identities;
- the full Python suite green, and web tests and tsc green;
- 60 of 60 CI actions SHA-pinned;
- atomic campaign writes;
- the vision ensemble reading the reported problem exactly.

## 46. Repository Coverage Matrix

| Path/directory | Inspected | Findings | Excluded | Reason |
|---|---|---|---|---|
| `app/backend/auth.py` | Full read | none | | |
| `app/backend/routers/campaigns.py` | Full read | none (probe verified) | | |
| `app/backend/main.py` | Partial (routes, middleware, health) | none | | Size |
| `app/backend/routers/*` (other 13) | AST route scan, signatures, probe | none | | Probed dynamically |
| `tribos/agentic/sandbox/` | gateway (select and execute), policy header, runner function map, probes | 102, 103, 117 | | |
| `tribos/verify/formal/` | runner (unproved detection), prove (attempt loop), correspondence (use) | 101 | | |
| `tribos/agentic/research/` | judge (`apply_judgement`), runner (compute and prove tiering), charter (tiers), ledger (numbers), thesis (claims); authored earlier in this session | 104 to 107, 110, 112 | | |
| `tribos/export/thesis.py`, `svgchart.py` | Escaping, Chromium use, bundle | none (110 for the bundle) | | |
| `tribos/axiom/accuracy.py` | Signatures and probe | none | | |
| `tribos/physis/`, `tribos/dynamis/engine.py`, `tribos/engcalc/structural.py` | Function maps, beam formula, probes | none | | |
| `tribos/verify/math_claims.py` | `audit_answer` probe | 111 | | |
| `tribos/datasets/` | validators header and dimensions, models, probe | 108 | | |
| `tribos/vision/` | Full read (authored this session), probes | 118 | | |
| `tribos/axiom/agent.py` (calibration) | Targeted | 114 | | |
| `tribos/agents/`, `writer/`, `archivon/`, `extensions/`, `utils/`, `evals/`, `scientific/`, `provenance/`, `memory/`, `harness/`, `substrate/`, `papers/`, `sources/`, `files/`, `skills/`, `tools/` | Search only (bandit, pip-audit, targeted grep) | 109 (pypdf call sites) | | Not read line by line |
| `web/src/` | Targeted (ComposerImages, visionService, ResearchLab wording); tsc and eslint | Trust matrix (§23) | | Not read in full |
| `tests/`, `web/tests/` | Executed in full | §31 | | |
| `.github/workflows/` | Pinning, mypy step | 115 | | |
| `docker/` | compose (sandbox, bind), backend Dockerfile | 102 context | | |
| `node_modules`, `.venv`, caches, `data/`, `logs/`, root archives | | | Yes | Vendored, generated or runtime |

**Honest coverage estimate.** About 10% of the source lines were read line by line in this session. Full test execution, the AST route scan, bandit, pip-audit and targeted searches covered the remainder by survey. Dynamic probes were concentrated on the highest-risk surfaces.

## 47. Commands and Tools Executed

| Command | Purpose | Result | Exit | Cause of any failure |
|---|---|---|---|---|
| `pytest tests -q` | Python suite | 2546 passed, 28 skipped, 0 failed (730.7 s) | 0 | n/a |
| `npm test` (web) | Web unit tests | 227 passed | 0 | n/a |
| `npx tsc --noEmit` | Type check | Clean | 0 | n/a |
| `npx eslint src` | Lint | 0 errors, 185 warnings | 0 | n/a |
| `ruff check --select F,E9 tribos tests app scripts` | Lint gate | Clean | 0 | n/a |
| `mypy tribos app` | Strict types | 617 errors in 133 files | 1 | Application (non-blocking by policy) |
| `bandit -r tribos app -f json` | SAST | 0 high, 15 medium (triaged) | 0 | n/a |
| `pip-audit -f json` | Advisories | 113 in 18 of 245 packages | 0 | Application dependencies |
| `route_auth.py` | Route auth scan | 106 routes, 11 open (benign) | 0 | n/a |
| `tenant_probe.py`, `tenant_probe2.py` | Authorization | All cross-user attempts 404 | 0 | First run 403: `.env` sets auth disabled (environment) |
| `sandbox_probe.py`, `sandbox_probe2.py`, `sandbox_probe3.py` | Sandbox escapes | 3 escape primitives confirmed | 0 | Application |
| `lean_axiom_probe.py` | Formal soundness | 3 bypasses confirmed | 0 | Application |
| `science_kat.py`, `science_kat2.py`, `science_kat3.py` | Known answers | All engine checks pass; number-binding fails | 0 | Early errors were harness call-signature mistakes (fixed in rounds 2 and 3) |
| grep: actions pinning; calibration hash | Prior findings 019 and 013 | 60/60 pinned; hash absent | 0 | n/a |

All probe scripts are in the session scratchpad (`…/scratchpad/audit/`), outside the repository. Probes with side effects used temporary data directories; the one file created outside the sandbox work directory by the h5py probe was in the scratchpad and was deleted.

## 48. Audit Limitations

- **Single session, no sub-agents** (the user's standing instruction). Depth was focused on security- and science-critical paths (§46).
- **Independence.** The auditor wrote the research loop, thesis export, accuracy tools and vision ensemble earlier in this conversation. Claims about them rest on executed probes. Readers may want an independent review of `tribos/agentic/research/` and `tribos/vision/`.
- No container runtime: container-backend isolation is not verified.
- LLM-driven workflows were not run end to end during the audit. The stored Collatz project was inspected read-only.
- No load or concurrency stress tests.

## 49. Final Engineering and Scientific Assessment

- **What the software is:** a STEM research assistant with real, well-tested deterministic engines, an LLM orchestration layer, a research loop that produces theses, and strong API security.
- **What works:** authentication and tenant isolation; the scientific engines (all known-answer tests pass); the exports; the image reader; a green test suite.
- **What cannot be trusted yet:**
  - the "Lean-verified" label (AUDIT-101);
  - running model-written code on a host without container isolation (AUDIT-102);
  - the thesis's verification wording: number-checked, replicated, supported, certified (AUDIT-104 to 107);
  - dataset upload for generic tables (AUDIT-108).
- **What cannot be reproduced:** a thesis as a whole (AUDIT-110). A finding's numbers can be reproduced from its stored code.
- **What must be fixed first:** AUDIT-101, then AUDIT-102.

A technically competent engineer can trust Tribos's deterministic scientific engines on this evidence. A domain expert should not take its research-loop verification labels at face value until AUDIT-101 and AUDIT-104 to AUDIT-107 are fixed.

## 50. Remediation Log (2026-11-04)

Applied after this audit, on the same branch. Each fix has a regression test built from the probe that exposed it.

| Finding | Status | Change | Verification |
|---|---|---|---|
| AUDIT-101 | Fixed | `verify/formal/runner.py`:<br>- every `axiom` declaration is refused, whatever its name, attributes or namespace (no allowlist);<br>- after compiling, `#print axioms` runs for every theorem (top-level `example`s are named for this), and only Lean's three standard axioms are accepted;<br>- the reports are read after a random per-check marker, so model code can neither forge one nor hide one with `#exit` | The audit probe against the installed Lean: all three bypasses `failed`; true theorems, including `Classical.em`, `verified` with their axioms listed; a macro-generated axiom and a spoofed report plus `#exit` `failed`. `tests/test_fix_audit_101_lean_axioms.py` |
| AUDIT-102 | Fixed (Python-level layers) | Policy:<br>- a `BANNED_MODULES` list (`numpy.ctypeslib`, `numpy.f2py`, `sympy.utilities.autowrap`, `sympy.printing.preview`, the pandas clipboard, …);<br>- native-loader, compiler, launcher and HDF5 low-level names banned.<br><br>Runtime:<br>- the same module check on import;<br>- no program can be started (`subprocess.Popen`, `os.system`/`spawn*`/`exec*`/`startfile`, `_winapi.CreateProcess`);<br>- h5py's C-level `h5f.create`/`open` check paths | All the audit's escape payloads now fail (sandbox probes 2 and 3 re-run). `tests/test_fix_audit_102_sandbox_escapes.py`. **Remaining:** the subprocess backend is still not an OS boundary. Shared deployments should use the container backend or strict mode, as the compose file does |
| AUDIT-103 | Fixed | `gateway.py`: SageMath is refused under strict isolation unless `TRIBOS_SANDBOX_ALLOW_UNISOLATED=1` | Unit test |
| AUDIT-104 | Fixed | `ledger.misattributed_numbers`: a number that is one ledger quantity's value, in a sentence naming another quantity, is flagged. It feeds the chapter repair call and the unverified list; the wording of the claims was corrected | The swapped-quantity sentence is flagged; correct and unnamed sentences pass |
| AUDIT-105 | Fixed (labelling and an option) | "Replicated" now says what it is: a separately written re-implementation with a different algorithm. `TRIBOS_RESEARCH_REPLICATION_MODEL` runs it on a second model, and the finding records the model and `same_model`. Docs, thesis and UI wording corrected | Tests on the recorded fields |
| AUDIT-106 | Fixed | `judge.apply_judgement`:<br>- evidence must come from a test planned for that deliverable or hypothesis;<br>- decided verdicts need `sourced` or stronger;<br>- "supported" may not cite a refuting finding;<br>- the reason is written to the note | Unit tests for each rule; research-loop fixtures updated to plan their evidence |
| AUDIT-107 | Fixed | `certified` is assigned when every compared quantity is an exact integer that the re-implementation reproduces exactly. The charter prompt and docs say so | Integer results certified, floats replicated (test). The stored Collatz-style end-to-end test now reaches `certified` for its integer test |
| AUDIT-108 | Fixed | CSV and TSV are ordinary tables (1 row and 1 column minimum; text columns allowed; empty cells reported, not refused) unless an expression-matrix orientation is declared, or 5 or more gene-like labels are recognised | `x,y` and short tables accepted; declared and recognisable matrices keep the matrix checks. `tests/test_fix_audit_108_tables.py` |
| AUDIT-109 | Partly fixed | 113 → **41** advisories (installed environment, pip-audit):<br>- pypdf 6.21.4 (7 fixed);<br>- nltk 3.10.4 (42);<br>- langsmith, langchain 0.3.30, langchain-core 0.3.86, torch 2.10.0, filelock, mkdocs-material, pymdown-extensions, marshmallow, virtualenv | **Remaining 41** need major upgrades: transformers 5, langchain 1.x, mem0 1.x, sentence-transformers 5, pytest 9 (with pytest-asyncio 1.x), and virtualenv 21 (blocked by the langchain-core 0.3 `packaging<26` pin) |
| AUDIT-110 | Fixed | `research/manifest.py`. The thesis records:<br>- Tribos version and commit;<br>- Python and library versions;<br>- Lean toolchain and Mathlib revision;<br>- models;<br>- sandbox backend and limits;<br>- sources with retrieval times;<br>- the limits of the checks.<br>It is summarised in the run record and written to the bundle as `manifest.json` (theses written earlier get one recorded at export) | Tests on the manifest and the bundle |
| AUDIT-111 | Fixed | An identity stated over all reals ("for all real x", "x ∈ ℝ") that fails at a negative value is FAILED. With no stated domain it stays inconclusive | Tests on the audit's three identities |
| AUDIT-112 | Fixed | A grouped number followed by a prose comma is one number | Test |
| AUDIT-114 | Fixed | Calibration refitted on HOLDOUT3 with the axiom code frozen at `40537ca`: n = 44 verified, all correct; confidence 0.978; lower 95% bound 0.920; rule-based solver, no model calls. `fitted_on` states it is a re-measurement on a set the developers have seen | `calibrated_confidence("verified")` returns the figure again; the test reads n from the file |
| AUDIT-115 | Fixed (gate on changed modules) | A blocking CI step runs strict mypy on the research, vision, accuracy, thesis export, SVG chart, Lean runner and sandbox policy/gateway modules (type-only changes) | `mypy --follow-imports=silent …`: no issues in 23 files. The rest of the codebase stays report-only |
| AUDIT-116 | Fixed (tracked files) | Six historical reports and prompts moved to `docs/history/`, with an index; links updated | The owner's ignored local files (logs, zips, the page PDF) were left in place |
| AUDIT-117 | Fixed | `TRIBOS_CAMPAIGN_MAX_PER_USER` (default 3): submit, resume or continue beyond it is refused with 429 before anything is written | `tests/test_fix_audit_117_campaign_quota.py` (6 tests, including the API) |
| AUDIT-118 | Fixed | The vision wording says "separate" readings; the docs state that both readings and the review are one model, and that the independent evidence is the two OCR engines | Web test updated |
| AUDIT-119 | Fixed | The thesis run record and the bundle state that the plan, judgements and prose are model-written, and exactly what the automatic checks cover | Manifest test |
| AUDIT-113 | n/a | Reserved; no finding | |

**Gates after remediation:**
- **Web:** 227/227 tests; tsc clean; eslint 0 errors.
- **ruff F/E9:** clean, and the changed files are clean.
- **Strict mypy gate:** clean.
- **`gen_env_reference --check`:** clean.
- **pip-audit:** 41 advisories.
- **Full pytest:** 2,587 passed, 33 skipped, 3 failed in the full run; the 3 were old tests that encoded the axiom allowlist (AUDIT-101) or spawned a process in the test-only unsafe mode. They were updated or fixed, and the affected files reran with 101 passed. Net: **2,590 passed, 0 failed**.
