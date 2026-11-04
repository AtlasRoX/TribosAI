# Accuracy Report: Forced Mass-Spring Benchmark Question

**Date:** 2026-10-30
**Question:** the 8-task forced damped oscillator problem
`2x'' + 3x' + 50x = 10cos(4t)`, with `x(0) = 0.1 m` and `x'(0) = 0`.
**Method:**
- Every number and formula in the latest answer was re-derived by hand and checked with independent code: SymPy `dsolve` and a separately written RK4.
- The run manifests in `.tribos_runs/` were compared, using the source fingerprint to tell which code produced each run.

## 1. Run-by-run results

| Run (UTC) | Code | Time | LLM calls | Tokens | Verifier result | Shown to the user |
|---|---|---:|---:|---:|---|---|
| `5589e7e9` 10-29 05:44 | before the writer layer | — | — | — | — | `[q1]`–`[q6]` headings, pipeline jargon, tasks 6–7 "not reported" |
| `a4655dfc` 10-30 03:37 | writer layer | 195 s | 11 | 59k | **6 false contradictions** | red "Verification found errors" banner on a correct answer; task 6 "not addressed"; planner crash |
| `98e25d78` 10-30 03:58 | same, served by a stale worker | 262 s | 14 | 90k | **5 false contradictions** | red banner; planner ran for 129 s; style requirements listed as missing |
| `49402b71` 10-30 04:19 | current | **38 s** | **3** | **12k** | **0 defects, passed** | correct answer; status "fallback"; confidence "moderate"; RK4 items "unverified" |

## 2. Accuracy of the latest answer (`49402b71`)

Every result was independently re-checked. **Mathematical accuracy: 100%. No statement is wrong.**

| Task | Answer states | Independent check | Result |
|---|---|---|---|
| 1. Analytical solution | `x = e^{-3t/4}(-37/130 cos(√391 t/4) - 1933√391/152490 sin(√391 t/4)) + 5/13 cos 4t + 10/39 sin 4t` | SymPy `dsolve` with exact ICs; `checkodesol`; `x(0) = 0.1`, `x'(0) = 0` | ✅ exact |
| 1. Intermediate steps | `39B = 10`; `A = 5/13`; `C₁ = 1/10 - 5/13 = -37/130`; `aC₁ - 4B = -1933/1560` | hand arithmetic over the common denominator 1560 | ✅ |
| 2. Transient / steady state | `e^{-3t/4}(…)` and `5/13 cos 4t + 10/39 sin 4t`; time constant `4/3 s` | exact split | ✅ |
| 3. `ω_n`, `ζ`, `ω_d` | `5 rad/s`, `3/20 = 0.15`, `√391/4 ≈ 4.9434 rad/s` | `√(50/2)`, `3/(2√100)`, `5√(1 - 0.0225)` | ✅ |
| 4. Amplitude and phase | `X = 10/√468 = 5√13/39 ≈ 0.46225 m`; `φ = atan(2/3) ≈ 0.58800 rad ≈ 33.69°` | `X cos φ = 5/13` and `X sin φ = 10/39` | ✅ |
| 5. Substitution | both initial conditions; `333 - 1933 + 1600 = 0` | exact | ✅ |
| 6. `x(t)` table (11 points) | 7 significant figures | exact solution evaluated with mpmath | ✅ max difference 4.9 × 10⁻⁸ (display rounding) |
| 7. RK4 comparison | `h = 0.001 s`; max error 8.85 × 10⁻¹² at t ≈ 3.397 s | separately written RK4 | ✅ identical: 8.85 × 10⁻¹² at 3.397 |
| 8. Physical meaning | light damping, amplitude ≈ 0.46 m, lag ≈ 34° | static deflection `F₀/k = 0.2 m`, amplification 2.31×; envelope `e^{-0.75·5} = 2.4%` at 5 s | ✅ consistent |

The wrong results across these runs were all **labels**: the mathematics in the answers was correct. The checker, the coverage report, the confidence line and the run status misdescribed correct answers.

## 3. What was wrong, and the fixes

### Verification accuracy: correct statements reported as contradicted

| # | Defect | Effect | Fix |
|---|---|---|---|
| V1 | `m = 2 kg` bound the symbol `m`, so every metre (`0.1 m`, `5/13 m`) was read as "× 2 kg" | `0.1 m − 5/13 m = −37/130 m` "inconsistent units" | `units_audit.py`: a name that is both a bound variable and a unit after a number is ambiguous, so it is not evaluated |
| V2 | A unit-free numeric side typeset in LaTeX (`\sqrt{\frac{50}{2}}`) was compared dimensionally | `√(k/m) = √(50/2)` "dimensions differ" | `units_audit.py`: any purely numeric side, however typeset, is never unit-checked |
| V3 | `x(0)` parsed as the product `x · 0` | `x(0) = C₁ + A = 0.1` "x(0) evaluates to 0" | `latex_math.py`: a single letter applied to a number or the variable is a function value |
| V4 | "At t = 0" / "setting t = 0" bound `t = 0` for the rest of the answer | every later formula in t evaluated only at t = 0; 5 false contradictions in run `98e25d78` | `math_claims.py`: arguments of function applications (`t` in `x(t)`) are never bound by a point evaluation |

On the two real answers, false failures went from 6 and 5 to **0**. The detection benchmark (`python -m tribos.evals.math_claims_matrix`) is unchanged: **0 false alarms, every corrupted claim caught (69/69)** across 9 capability groups.

### Coverage report

| # | Defect | Fix |
|---|---|---|
| C1 | A table with an `x(t)` column covering the requested points did not count as answering "compute x(t) for t = 0, 0.5, …, 5" | `deliverables.py`: a table covering every requested point counts |
| C2 | "Show intermediate calculations, preserve units, use LaTeX, state assumptions, verify final results" were tracked as deliverables and reported missing | `deliverables.py`: presentation requirements are not deliverables |
| C3 | The RK4 comparison and maximum error were always "unverified" | `deliverables.py`: checked when the answer states the code-computed value |

### Status and confidence labels

| # | Defect | Fix |
|---|---|---|
| L1 | The planner skipped by design was reported as "completed with fallback: plan & execute did not run (it was not reached)" | the phase records `not_needed`; status and UI treat it as normal |
| L2 | Confidence fell back to the claim-support heuristic ("moderate", plus a 5 s model call), because prose sentences count as unchecked | results checked by code use the computational-verification confidence path, as a verified math-agent answer does |
| L3 | The reconciled confidence note read "(computed from claim support)" | now reads "(set by the automatic checks)" |

### Speed

| # | Cause | Saving | Fix |
|---|---|---:|---|
| S1 | "fourth-order Runge" forced the planner to schedule a Dynamis run (129 s; it crashed in one run) | ~43–129 s | skipped when the code already computes the RK4 comparison |
| S2 | The math agent re-solved an ODE already solved exactly by code (4 calls) | ~60 s | skipped when the code-computed solution passed substitution and IC checks and covers every requested table and comparison |
| S3 | An LLM decomposition re-split the user's numbered tasks | ~12 s | numbered tasks become the sub-questions directly |
| S4 | False contradictions forced a revision rewrite | ~30–40 s | removed by V1–V4 |
| S5 | Planner replies lost to LaTeX backslashes or truncation | — | JSON repair for both cases, plus a logged excerpt when a reply is still unusable |

The result: **262 s → 38 s; 14 → 3 LLM calls; 90k → 12k tokens**, with higher measured accuracy.

### Operations

- The `--reload` backend on port 8001 stopped reloading because its worker never exited. A run was then served by stale code (`98e25d78`).
- The backend now runs without `--reload` and is restarted after each change.
- The `source_fingerprint` in each run manifest shows which code produced a run.

## 4. Regression tests

- `tests/test_feat_run_a465_fixes.py` (13 tests) and `tests/test_feat_run_98e2_speed_and_accuracy.py` (8 tests) use statements taken verbatim from these runs.
- Full suite after this round: **2244 passed, 0 failed**, 28 skipped. Web: 212/212 tests and the typecheck pass.

## 5. Remaining limits

- The code-computed results and the math-agent skip cover **ODE initial-value problems**. Other mathematics still goes through the math agent.
- Without the LLM, the math agent misreads prime notation (`x''(t)`). The code path does not depend on it, but the agent's own parser is unchanged.
- Prose (task 8, "physical meaning") cannot be machine-checked. It was reviewed by hand here and is reported as "addressed", not "checked".
- `tribos/axiom/calibration.json` must be refitted before the math agent's measured precision is shown again (it is tied to a code hash).
