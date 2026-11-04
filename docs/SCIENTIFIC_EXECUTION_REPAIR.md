# Tribos scientific execution repair

Date: 28 October 2026. Scope: the uploaded source archive and the supplied math, RC, beam, oscillator, heat and Monte Carlo captures.

This is a tested repair of the concrete failures, not a certification that every scientific question or arbitrary simulation will be correct. The numerical engines already existed; routing, method fidelity, verification, and output generation were preventing them from doing the requested work.

## Confirmed problems and changes

| ID | Finding | Change |
|---|---|---|
| S01 | The direct pipeline only ran Python when code was already supplied; it had no direct execution adapter for the requested heat FTCS or Monte Carlo calculation. Symbolic integration was substituted for Monte Carlo. | Added validated adapters to real numerical tools, a bounded PCG64 Monte Carlo tool, and direct rendering from executed outputs. Numerical requests are offered their relevant numerical tools on the general planning path, and Monte Carlo/heat tasks no longer launch the symbolic math agent as a substitute. |
| S02 | ODE simulations used adaptive RK45 and output samples, ignoring a requested fixed RK4 step/count. Endpoint wording could fall back to a 60-second horizon. | Added actual classical RK4, exact step/count/span validation, endpoint horizon parsing and propagation of method/grid in the general simulation plan. The original 100-step request now runs 100 RK4 steps over 1 second. |
| S03 | A named preset could replace a stated system's coefficients/initial conditions; a (0, 10) interval could become a preset interval. Results were rounded to 8 decimal places, hiding errors near 1e-10. | Prevented preset substitution when explicit values have not been mapped. Preserved the requested span and full float64 trajectory values. Interactive reruns preserve the fixed RK4 method and grid; incompatible exploration is refused instead of silently switching methods. |
| S04 | The checker stripped physical units without preserving their scale. It also treated the coefficient in z = 2(k+1)n as a scalar given z = 2, and interpreted n(n+1) as a function. | Added SI scale conversion during mathematical checking, rejected expression coefficients as scalar givens, and guarded the scalar/function ambiguity. The supplied congruence-family response no longer gets those false contradictions. |
| S05 | The audit cache hashed math spans but omitted table result values and prose assumptions. A changed answer could reuse a prior passing audit. Quantified conclusions could be accepted as new domain assumptions. | Hash the full answer, copy cached verdicts on storage/read, and check supported one-variable quantified conclusions inside their declared domain. Undecidable cases remain undecided. |
| S06 | A writing-model failure or empty reasoning-only response could lose a computed result and trigger long retries. A short endpoint request received an unsolicited long engineering report. | Fully covered supported calculations render directly from tool results with no writing model. The general writer receives its output cap even outside agentic mode, and ODE verification only injects the full report format when requested. |
| S07 | Computation cards and labels could imply more verification than was performed; a beam card could apply an unrequested design/serviceability limit. | Added execution records with exact inputs, checks, hashes, package versions, actual method/count/seed, and downloads. Cached output is distinguished from a new execution. Removed the assumed beam deflection limit unless the caller supplies one. Numerical execution checks are explicitly narrower than full answer verification. |
| S08 | A standalone offline benchmark triggered OpenTargets traffic even with search off. | Traced this to RunRecorder eagerly probing six unrelated upstream services at construction. Removed the automatic probe. Added a regression test for search both on and off. The final benchmark blocks all socket connections and recorded zero network attempts. |

## Implemented capabilities

The fast execution path handles fully specified scalar first/second-order ODE requests using fixed RK4, one-dimensional constant-diffusivity heat requests using uniform-grid FTCS with constant Dirichlet boundaries and a uniform initial interior, crude one-dimensional Monte Carlo integrals with a stated count/seed, ideal RC charging, and rectangular cantilever end-load calculations.

These are parameterised solvers, not stored answers: the tests vary systems, parameters, time grids, random seeds, integrands and bounds. Physical ODE givens supported by the adapter are normalised to SI before their numeric values are substituted. Unsupported forms, broader deliverables, attachments and persistent project instructions remain on the general agent path. Invalid/conflicting grids are rejected without silently changing the request. No arbitrary CFD/FEA or universal problem-solving capability is claimed.

For affine autonomous ODE systems, the independent analytical reference is a matrix-exponential solution evaluated in float64. Nonlinear systems do not receive an invented analytical reference. Stability of an FTCS grid does not establish continuum accuracy. A Monte Carlo standard error is sampling uncertainty, not exactness.

## Executed numerical results

- RC: tau = 1 s; V_C(1) = 7.58544670594 V; I(1) = 0.000441455329406 A; KVL residual is zero at floating-point precision.
- Beam: I = 1.06666666667e-7 m^4; moment = 300 N m; maximum stress = 56.25 MPa; tip deflection = 0.010546875 m; deflection/span = 0.00703125. No yield strength or serviceability limit was invented.
- Oscillator: 100 RK4 steps of 0.01 s; x(1) = -0.0258070261913 m and v(1) = -0.150323100770 m/s. Errors against the separately evaluated matrix-exponential reference are approximately 1.53e-10 m and 3.45e-10 m/s.
- FTCS: r = 0.2; exactly 10 steps of 20 s. Final temperatures in degrees C: [100, 62.61815296, 32.92896256, 14.24275456, 4.96746496, 1.36701952, 0.28883968, 0.04507648, 0.00488448, 0.00032768, 0]. Boundaries were applied at every step.
- Monte Carlo: PCG64 seed 20261028, exactly 100000 samples. Estimate = 0.745408733863; estimated standard error = 0.000635258555290; absolute reference discrepancy / SE = 2.22806751311.

Full-precision data, exact input specifications, result hashes and reproduction recipes are in scientific_execution_results.json. A downloadable recipe is not described as independently executed; the registered numerical tool itself was executed.

## Offline timing measurement

These measurements are local application-path wall times in this workspace, with the writing/planning model forbidden, caching disabled, memory persistence disabled and socket connections blocked. They include the numerical computation and result assembly. They are not deployed-service latency guarantees or a controlled comparison with the user's machine.

| Request | Local wall time (s) | Result |
|---|---:|---|
| RC | 0.419938 | completed |
| Beam | 0.009730 | completed |
| RK4 | 0.127786 | completed |
| FTCS | 0.013659 | completed |
| Monte Carlo | 0.010320 | completed |

Network attempts: 0. Model calls: 0 for each of these five supported requests. The first request includes cold initialisation.

## Validation

- 260 targeted scientific/math/verification/execution tests passed in the combined validation run.
- 54 numerical execution, no-implicit-probe, provenance/export and claim tests passed after the network-probe repair; 30 final smoke tests passed, including unstable-grid rejection and honest partial status when an analytical reference is unavailable.
- 209 frontend tests passed; TypeScript, ESLint (0 errors; existing warnings), and production build passed.
- Ruff F/E9, Bandit high-severity check, generated configuration check, and diff whitespace check passed.
- The broad Python regression run recorded 1879 passed, 18 failed and 22 skipped. Every one of those failing test IDs also failed against the untouched uploaded source in the baseline comparison. This report does not label the repository release-ready while those failures remain. The untouched baseline also had math-verifier failures repaired by this patch.
- No live provider evaluation, authenticated production deployment, or browser interaction test was performed. Model performance on unsupported/general requests remains to be evaluated.

### Remaining broad-suite failures

- `tests/test_agent_platform.py::test_fact_invalidation_and_mem0_decisions`
- `tests/test_agent_platform.py::test_consolidation_extracts_facts_and_recall_injects_them`
- `tests/test_agent_platform.py::test_project_memory_through_the_orchestrator`
- `tests/test_agentic_loops.py::test_supervisor_replans_after_stalls_and_stops`
- `tests/test_agentic_planning.py::test_decomposition_caps_at_five_and_skips_non_research`
- `tests/test_audit_fix_hermeticity.py::test_http_clients_fail_fast_offline`
- `tests/test_auto_router.py::test_engineering_questions_take_the_cheapest_adequate_approach[Simulate the Lorenz system for 50 s and ]`
- `tests/test_auto_router.py::test_engineering_questions_take_the_cheapest_adequate_approach[Compare the Euler and RK4 methods for y']`
- `tests/test_citations.py::test_orchestrator_result_and_stream_carry_citations`
- `tests/test_datasets.py::test_size_cap_while_streaming_leaves_no_part_file`
- `tests/test_feat_remaining_issues_and_lean.py::test_phase_b_requested_items_and_deliverables_assessment`
- `tests/test_feat_t5.py::test_math_agent_integration_with_a_fake_model`
- `tests/test_feat_t5.py::test_without_lean_the_phase_changes_nothing_else`
- `tests/test_foundation_hooks.py::test_synthesis_system_prompt_composition`
- `tests/test_prompts.py::test_composed_prompt_is_numbered_and_bounded`
- `tests/test_sandbox.py::test_child_env_is_scrubbed_and_network_blocked`
- `tests/test_search_plan.py::test_concepts_drop_question_words_and_keep_topics`
- `tests/test_search_plan.py::test_web_query_is_the_question_not_padded_with_mechanism_words`

Some remaining tests still target old biomedical behaviour, while other failures concern memory, router expectations, coverage extraction, sandbox environment expectations and offline test setup. They need separate diagnosis; they were not deleted or weakened to produce a passing total.

## How to apply

1. Keep your current project and configuration under version control or back it up.
2. The archive contains the complete patched source in tribos/. Dependencies, caches, Git history and local secrets are not included.
3. Either compare/merge that source into your checkout, or apply repair.patch at the repository root after running git apply --check repair.patch. The patch is against the exact uploaded source, so check compatibility before applying it to a newer checkout.
4. Preserve your existing .env. This repair does not require a different model for the five supported execution paths and adds no production dependency.
5. Run the commands below, then repeat the same five requests in your local UI and inspect the Scientific execution card and downloaded inputs/results.

```bash
uv sync --extra dev
uv run pytest -q -p no:cacheprovider tests/test_feat_scientific_execution.py tests/test_feat_scientific_claims.py tests/test_feat_no_implicit_probes.py tests/test_math_agent.py
uv run ruff check tribos app tests scripts --select F,E9
uv run bandit -c pyproject.toml -r tribos app --severity-level high
uv run python scripts/gen_env_reference.py --check
cd web
npm ci
npm run typecheck
npm test
npx eslint src
npm run build
```

## Prompt for the remaining work

```text
Continue from the scientific-execution repair. Reproduce the remaining test failures listed in docs/SCIENTIFIC_EXECUTION_REPAIR.md, one cluster at a time. Separate obsolete biomedical expectations from real STEM application regressions. Fix the root cause or update an obsolete test to the current documented product contract; do not remove accuracy, provenance or no-network checks to obtain a green total.

Then evaluate broader numerical requests outside the deterministic adapters. A numerical task must execute its requested method, parameters, units, grid, duration and random generator through the registered tools. Compare the actual executed specification with the user's requirements before reporting completion. An analytic solution, an interpolated adaptive trajectory, a different preset or an illustrative chart must never stand in for an explicitly requested simulation.

Keep the numerical tests and zero-false-accept math gate passing. Report exact test outcomes and remaining limitations. Do not promise perfect answers or mark unsupported computations as executed.
```
