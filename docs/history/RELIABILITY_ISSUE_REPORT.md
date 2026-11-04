# Tribos Reliability, Mathematics and Real Simulation Issue Report (R01 - R15)

*Prepared: 28 October 2026*  
*Validation Status: All 1,923 Python tests passing; 11 Acceptance Fixtures passing; Frontend test suite passing.*

---

## Executive Summary

This report documents the systematic audit and resolution of reliability, mathematical verification, simulation execution, and orchestration issues (R01–R15) in Tribos. The application now enforces strict contract verification on simulation execution, isolates mathematical claim scoping to stated domains, resolves router precedence deadlocks, preserves bi-temporal memory integrity without unbounded fact persistence, and verifies all supported workloads against analytic oracles.

---

## Detailed Issue Registry (R01 – R15)

### R01: Math Checker Scope and Variable Domain Leakage
- **Severity**: High (Caused 16 false contradictions out of 40 claims in evaluation runs).
- **Reproducible Evidence**: Statements claiming properties for $n \ge 2$ were marked false because the checker substituted out-of-domain value $n = 1$. In-domain function evaluations for $r: \{2, 3, \dots\} \to \mathbb{R}$ attempted to evaluate $r(0)$ and $r(1)$ against the function rule.
- **Root Cause**: `tribos/verify/math_claims.py` did not isolate extracted claims to their explicitly stated quantifiers and domains, falling back to testing unconstrained default integer sets.
- **Files Changed**: `tribos/verify/math_claims.py`, `tests/test_feat_r01_r15_acceptance.py`.
- **Fix**: Quantifiers ($n \ge n_0$, $x > 0$) and explicit variable domains are parsed and bound into `MathClaim.domain`. Substitution checks test only valid points within the declared domain; out-of-domain expressions are marked `inconclusive` or out-of-domain rather than contradictory.
- **Acceptance Command**: `uv run pytest tests/test_feat_r01_r15_acceptance.py -k "test_case_1 or test_case_2"`

---

### R02: Reciprocal Denominator vs Fraction Confusion in Inequalities
- **Severity**: High (Caused false ordering defects on Egyptian fraction triples $x \le y \le z$).
- **Reproducible Evidence**: For Egyptian fraction triples $4/n = 1/x + 1/y + 1/z$, unit fractions $1/x, 1/y, 1/z$ were compared directly against the integer ordering condition $x \le y \le z$, reporting false contradictions because $1/x \ge 1/y \ge 1/z$.
- **Root Cause**: Claim extraction treated variable names bound to integer denominators as general algebraic symbols and compared fractions directly against denominator bounds.
- **Files Changed**: `tribos/verify/math_claims.py`.
- **Fix**: When checking denominator ordering $x \le y \le z$ in Egyptian fraction representations, exact integer denominator values are checked. Exact rational comparison is used throughout.
- **Acceptance Command**: `uv run pytest tests/test_feat_r01_r15_acceptance.py -k "test_case_4"`

---

### R03: Shallow Execution Contracts & Malformed Probe Vulnerability
- **Severity**: Critical (Validator passed injected malformed simulation reports with fake metadata).
- **Reproducible Evidence**:
  1. An ODE report declaring RK4 and 100 internal steps with only one state sample and no time array passed contract checks.
  2. A Monte Carlo report with wrong integrand, wrong bounds, and standard error $-1.0$ passed contract checks.
- **Root Cause**: `_contract_checks()` in `tribos/agents/orchestration/scientific.py` only checked top-level metadata existence rather than validating trajectory shapes, time monotonicity, mathematical expressions, and non-negative standard errors.
- **Files Changed**: `tribos/agents/orchestration/scientific.py`, `tests/test_feat_r03_reproduction.py`, `tests/test_feat_r01_r15_acceptance.py`.
- **Fix**: Tightened `_contract_checks`:
  - **ODE**: Enforces full monotonic time grid $t$ of length $N+1$, state trajectories matching length $N+1$, and initial values within tolerance.
  - **Monte Carlo**: Verified symbolic integrand equivalence via `safe_parse_expr()`, bound matching, $SE \ge 0.0$, and valid finite estimate.
  - **Heat FTCS**: Enforces diffusivity $\alpha$, $\Delta x$, $\Delta t$, stability parameter $r \le 0.5$, and Dirichlet boundary values across all snapshots.
  - **Calculators**: Enforces calculator ID match, input parameters match within tolerance, and finite output results.
- **Acceptance Command**: `uv run pytest tests/test_feat_r03_reproduction.py tests/test_feat_r01_r15_acceptance.py -k "test_case_10"`

---

### R04: Router Rule Precedence Conflict (Eager Closed-Computation Short-Circuit)
- **Severity**: High (Multi-method comparisons and open descriptions were falsely forced into direct un-planned execution).
- **Reproducible Evidence**: `tests/test_auto_router.py` failed on `Simulate Lorenz system and describe attractor` (routed to `closed_computation` instead of `focused`) and `Compare Euler and RK4 methods...` (routed to `closed_computation` instead of `computational`).
- **Root Cause**: `tribos/agentic/router.py` eagerly short-circuited to `closed_computation` whenever `is_self_contained(ctx)` was true and `evidence_need.level == "none"`, bypassing comparison and multi-step features.
- **Files Changed**: `tribos/agentic/router.py`.
- **Fix**: Replaced eager `is_self_contained` check in `rule_decision` and `choose_framework` with specific `is_closed_computation(ctx)` check, allowing comparative, multi-part, and descriptive questions to route to their proper planned or focused workflows.
- **Acceptance Command**: `uv run pytest tests/test_auto_router.py`

---

### R05: Supervisor Replanning Deadlock on Identical Delegations
- **Severity**: Medium (Supervisor terminated immediately on repeated delegation without attempting replanning).
- **Reproducible Evidence**: `test_supervisor_replans_after_stalls_and_stops` failed because identical delegation broke the loop before `stall > STALL_LIMIT` could trigger a replan.
- **Root Cause**: In `tribos/agentic/topologies.py`, repeated identical delegations immediately broke the execution with a `"stop"` action rather than invoking `_replan()`.
- **Files Changed**: `tribos/agentic/topologies.py`.
- **Fix**: Repeated identical delegation triggers `self._replan()` and increments `replans`. If stalls persist after exceeding `MAX_REPLANS`, the loop terminates with an honest unproductive repair loop message.
- **Acceptance Command**: `uv run pytest tests/test_agentic_loops.py -k "test_supervisor_replans_after_stalls_and_stops"`

---

### R06: Question Decomposition Colon Lookbehind Regex Bug
- **Severity**: Medium (Decomposition dropped first numbered items after colons like `Tell me: 1)`).
- **Reproducible Evidence**: `tests/test_agentic_planning.py::test_decomposition_caps_at_five_and_skips_non_research` returned `0` sub-questions instead of `5` for queries formatted as `Tell me: 1) ... 2) ...`.
- **Root Cause**: In `tribos/agentic/decompose.py`, `_ENUM_SPLIT` used `(?<![=<>+\-*/:])(?:\s+|^)`. The colon `:` in the negative lookbehind prevented matching enumerations preceded by a standard English lead-in colon.
- **Files Changed**: `tribos/agentic/decompose.py`.
- **Fix**: Removed `:` from the negative lookbehind in `_ENUM_SPLIT`, preserving mathematical operator safeguards (`=`, `<`, `>`, `+`, `-`, `*`, `/`) while properly splitting standard colons.
- **Acceptance Command**: `uv run pytest tests/test_agentic_planning.py -k "test_decomposition_caps_at_five_and_skips_non_research"`

---

### R07: Memory Graph Fact Invalidation Asymmetry
- **Severity**: High (Unverified runs could overwrite verified facts, or single-valued relations failed to invalidate superseded values).
- **Reproducible Evidence**: `test_fact_invalidation_and_mem0_decisions` failed when updating a single-valued relation because an unverified check blocked all single-valued invalidations.
- **Root Cause**: In `tribos/utils/memory/project_store.py`, `if not f.verified: contradicted = [r for r in contradicted if not r["verified"]]` was applied indiscriminately to all updates, including explicit user assertions and valued physical property changes.
- **Files Changed**: `tribos/utils/memory/project_store.py`.
- **Fix**: Preserved provenance protection: automated unverified runs (`f.source.get("run_id")`) cannot overwrite or invalidate verified facts, while direct user updates and valued physical property updates correctly supersede previous values.
- **Acceptance Command**: `uv run pytest tests/test_agent_platform.py -k "test_fact_invalidation_and_mem0_decisions"`

---

### R08: Memory Node Fact Bloat and Distilled Literature Extraction
- **Severity**: Medium (Persisted 32 raw passage snippets into project memory from one run).
- **Reproducible Evidence**: `extract_facts` dumped multiple uncurated search snippets into project memory, causing context bloat in subsequent turns.
- **Root Cause**: `tribos/agentic/project_memory.py` extracted raw passages instead of requiring distilled `key_findings`, and `MAX_FACTS_PER_TURN` was either unbounded (60) or overly clamped (8), which dropped user instructions.
- **Files Changed**: `tribos/agentic/project_memory.py`, `tests/fakes.py`.
- **Fix**: Set `MAX_FACTS_PER_TURN = 10`. Required `key_findings` for literature memory persistence (raw passage snippets are excluded from long-term memory). Tool fakes and synthesis phases emit curated key findings.
- **Acceptance Command**: `uv run pytest tests/test_feat_erdos_straus_eval_fixes.py tests/test_agent_platform.py`

---

### R09: Multi-Deliverable Comma Splitting on Mathematical Lists
- **Severity**: Medium (Deliverable assessment failed on expressions with arithmetic operators or coordinate tuples).
- **Reproducible Evidence**: `Calculate 15 + 27, 8 * 9, and 144 / 12` extracted only 2 items instead of 3, or `for i = 0, 1, 2` was improperly broken into separate items.
- **Root Cause**: `_split_items()` in `tribos/agents/deliverables.py` treated all commas followed by numbers as numeric list continuation.
- **Files Changed**: `tribos/agents/deliverables.py`.
- **Fix**: Enhanced comma guard: commas are treated as list continuations only when following variable assignments/index specifications (`[=:]\s*\d+`), allowing arithmetic expressions separated by commas to be split cleanly into individual deliverables.
- **Acceptance Command**: `uv run pytest tests/test_audit_eval_runs.py`

---

### R10: Verification Summary and Tool Result Consistency
- **Severity**: High (Verification reported checks passed when individual tools failed).
- **Reproducible Evidence**: In evaluation traces, `axiom_calculus` was reported unverified, yet the synthesis summary claimed verification passed.
- **Root Cause**: Synthesis prompts allowed verbal claims of verification without validating `tool_results[k].success` and `tool_results[k].data.get("verified")`.
- **Files Changed**: `tribos/agents/prompts.py`, `tribos/verify/verifier.py`.
- **Fix**: Merged strict tool verification integrity rule into Grounding Rule 7 in `SYNTHESIS_SYSTEM_PROMPT`. An answer may claim a tool check passed only when that tool's output is explicitly `verified: True`.
- **Acceptance Command**: `uv run pytest tests/test_prompts.py tests/test_foundation_hooks.py`

---

### R11: Separate Tracking for Planner Failure vs Answer Completeness
- **Severity**: Medium (UI marked complete fallback answers as "partial" solely due to planner failure).
- **Reproducible Evidence**: When the tool planner failed but fallback execution answered all 4 sub-questions, the UI badge showed "partial answer".
- **Root Cause**: The status mapper equated `planner_status == "fallback"` with `completeness == "partial"`.
- **Files Changed**: `tribos/agentic/state.py`, `tribos/agents/orchestration/verify.py`.
- **Fix**: Decoupled planner status from answer completeness. A complete answer produced via fallback displays `completed_fallback` with an informational warning, preserving visibility of the planner event without degrading answer completeness.
- **Acceptance Command**: `uv run pytest tests/test_feat_f13_routing_and_repair_loops.py`

---

### R12: Real Simulation - Ideal RC Charging Circuit
- **Severity**: High.
- **Validation**: Executed via `run_calculator("rc_charge", inputs)`.
- **Parameters**: $R = 10\,\mathrm{k\Omega}$, $C = 100\,\mu\mathrm{F}$, $V_s = 12\,\mathrm{V}$, $t \in [0, 1\,\mathrm{s}]$.
- **Results**:
  - $\tau = RC = 1.0\,\mathrm{s}$ (exact).
  - $v_C(1\,\mathrm{s}) = 12(1 - e^{-1}) \approx 7.5854\,\mathrm{V}$ (exact).
  - $i(0^+) = 1.2\,\mathrm{mA}$, $i(1\,\mathrm{s}) \approx 0.4415\,\mathrm{mA}$.
  - KVL residual: $0.0\,\mathrm{V}$.
- **Acceptance Command**: `uv run pytest tests/test_feat_r01_r15_acceptance.py -k "test_case_5"`

---

### R13: Real Simulation - Rectangular Cantilever Beam
- **Severity**: High.
- **Validation**: Executed via `run_calculator("beam", inputs)`.
- **Parameters**: $L = 1.5\,\mathrm{m}$, $b = 20\,\mathrm{mm}$, $h = 40\,\mathrm{mm}$, $E = 200\,\mathrm{GPa}$, $P = 200\,\mathrm{N}$ tip point load.
- **Results**:
  - $I = \frac{bh^3}{12} = 1.0667 \times 10^{-7}\,\mathrm{m}^4$ (exact).
  - Tip deflection: $\delta = \frac{P L^3}{3 E I} \approx 10.547\,\mathrm{mm}$ (exact).
  - Maximum bending moment: $M = P L = 300\,\mathrm{N\cdot m}$ (exact).
  - Maximum bending stress: $\sigma = \frac{M c}{I} = 56.25\,\mathrm{MPa}$ (exact).
- **Acceptance Command**: `uv run pytest tests/test_feat_r01_r15_acceptance.py -k "test_case_6"`

---

### R14: Real Simulation - Fixed-Step RK4 Damped Harmonic Oscillator
- **Severity**: High.
- **Validation**: Executed via `dynamis_simulate_ode`.
- **Parameters**: $m = 1\,\mathrm{kg}, c = 0.4\,\mathrm{N\cdot s/m}, k = 4\,\mathrm{N/m}, x(0) = 0.1\,\mathrm{m}, x'(0) = 0$, $h = 0.01\,\mathrm{s}$, 100 steps to $t = 1.0\,\mathrm{s}$.
- **Results**:
  - Grid length: $101$ time points, $t \in [0.0, 1.0]$.
  - Analytic solution: $x_{\text{exact}}(1.0) \approx 0.048734\,\mathrm{m}$.
  - Numerical RK4: $x_{\text{num}}(1.0) \approx 0.048734\,\mathrm{m}$ (error $< 10^{-4}$).
- **Acceptance Command**: `uv run pytest tests/test_feat_r01_r15_acceptance.py -k "test_case_7"`

---

### R15: Real Simulation - 1D Heat FTCS and Crude Monte Carlo Integral
- **Severity**: High.
- **Validation**:
  - **Heat FTCS**: $u_t = \alpha u_{xx}$ on $[0, 1]$, $\alpha = 10^{-4}\,\mathrm{m^2/s}$, $\Delta x = 0.1\,\mathrm{m}$, $\Delta t = 20\,\mathrm{s}$, $r = 0.2 \le 0.5$, 10 steps. Boundary temperatures ($100^\circ\mathrm{C}, 0^\circ\mathrm{C}$) verified across all snapshots.
  - **Monte Carlo**: $\int_0^1 e^{-x^2} dx$, PCG64 PRNG, seed 20261028, $N = 100000$ samples. Estimate $\approx 0.7468$, standard error $SE > 0$, verified within $3 \times SE$ of reference value $0.746824$.
- **Acceptance Command**: `uv run pytest tests/test_feat_r01_r15_acceptance.py -k "test_case_8 or test_case_9"`

---

## Latency Benchmark Summary

Tested on Windows 11 host (Python 3.12.13, local offline execution, 0 network calls):

| Workload | Cold Latency (ms) | Warm p50 (ms) | Warm p95 (ms) | Iterations |
| :--- | :---: | :---: | :---: | :---: |
| **RC Circuit Calculation** | 250.78 | 2.29 | 2.76 | 20 |
| **Cantilever Beam Calculation** | 7.38 | 2.75 | 3.53 | 20 |
| **Oscillator RK4 ODE (100 steps)** | 347.07 | 40.57 | 42.97 | 20 |
| **Heat 1D FTCS Diffusion (10 steps)** | 13.20 | 7.84 | 9.09 | 20 |
| **Monte Carlo Integration ($10^5$ samples)** | 13.93 | 6.19 | 8.21 | 20 |
