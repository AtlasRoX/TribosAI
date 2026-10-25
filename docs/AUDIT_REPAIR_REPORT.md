# Audit repair report (I01–I23, T01–T20)

Branch `audit-repair`, based on `cffff9f` (chore: integration and docs). Written for engineers reviewing the repair.
Everything below was run in this repository on Windows 11 with Python 3.12 and Node 24. Results that could not be
produced are marked **blocked** or **not done**, with the reason.

## 1. Architecture and affected code

A question flows through these components. The ones this repair changed are named, with the defect each one carried.

| Stage | Component | Defects found there |
|---|---|---|
| Output form | **new** `tribos/utils/output_contract.py` | I12, I17, I18: format instructions were never represented. |
| Literal fast path | `tribos/agents/orchestration/plan.py` (`start`) | I04, I17: a copy request ran the full research pipeline. |
| Query understanding | `tribos/agents/query_planner.py` (`_requests_simulation`, `decide_builtin_sources`) | I01, I02: negated mentions counted as requests. I03: misleading skip reason. I04/T08: Search off ignored the literature. |
| Information need | `tribos/agents/evidence_need.py` (`assess_evidence_need`, `external_retrieval_block`) | I04: retrieval ran unless the math parser captured everything. |
| Clarification | `tribos/agentic/clarify.py` (`missing_initial_conditions`) | T11: no clarification when an ODE was given without its initial conditions. |
| Math representation | **new** `tribos/axiom/definitions.py`; `tribos/axiom/problem.py` | I07, I08, I10, I11, I12: `T(n) = n/2` was parsed as the equation `T*n = n/2`. |
| Axiom tool + verifier | `tribos/axiom/schemas.py`, `agent.py`, `verifier.py`, `verifier_ext.py`, `tribos/extensions/axiom.py` | I11: alignment was checked against the same faulty parse. |
| Answer checker | `tribos/verify/math_claims.py`, `tribos/verify/result_record.py` | I09: global first-wins bindings. I10: no question definitions. I13: plain-text math was never checked. |
| Completion graders | `tribos/verify/verifier.py`, `tribos/agents/deliverables.py` | I14: graders did not know the task type. |
| Escalation | `tribos/agentic/router.py` (`escalation_triggers`) | I05: route uncertainty alone escalated self-contained tasks. |
| Writer and revision | `tribos/agents/orchestration/draft.py`, `verify.py`, `finalize.py` | I17, I18: template overrode the requested form; banner written into the answer; failed-model fallback ignored the contract. |
| Retrieval | `tribos/agents/authoritative_orchestrator.py` (`literature_subject`), `tribos/archivon/engine.py` | I06: verbatim instructions as the query; top-3 padding with irrelevant works. |
| Tool layer | `tribos/tools/reliability.py` (`external_retrieval_blocked`) | T08: no single point enforced Search off. |
| Agentic gates | `tribos/agentic/plan_graph.py`, `tribos/agentic/specialists.py`, `tribos/agents/orchestration/gather.py` | T08: the literature and online-database tools ignored Search off. |
| Math card / brief | `tribos/agentic/math_agent.py`, `web/src/components/agentic/MathAgentArtifact.tsx` | I19: benchmark precision shown for unverified answers. |
| Memory | `tribos/agents/orchestration/finalize.py` | I21: the verification banner was stored as answer content. |
| Export | `tribos/export/report_model.py` | I17: only one banner variant was stripped. |
| Web rendering / copy | `web/src/lib/assistantAnswer.ts`, `web/src/lib/verificationState.ts`, `web/src/components/ExportMenu.tsx`, `web/src/app/page.tsx` (4 lines changed, length unchanged) | I13: "All N supported" over undecided claims. I17: `ALPHA\nBETA` rendered as one line; copy included the banner. |
| Browser storage | `web/src/services/localStorageService.ts` | I20: whole conversations were deleted to make room. |

New tests: `tests/test_audit_repair.py` (59 backend tests; the 2 real-Lean tests run in live mode only) and
`web/tests/auditOutputContract.test.mts`. The existing `web/tests/localStorageService.test.mts` and
`web/tests/runStatus.test.mts` were extended. Formal checker: `tribos/verify/formal/runner.py` and
`tribos/verify/formal/prove.py` (see §9).

## 2. Finding matrix

Status means: **Fixed** = the cause was removed and a test covers it; **Partly** = the main cause was fixed and the
stated parts remain; **Open** = not changed, scope given; **Blocked** = could not be checked here.

| ID | Sev. | Reproduced? | Actual cause | Change | Tests | Status / remaining |
|---|---|---|---|---|---|---|
| I01 | P1 | Yes (T01: `is_simulation_intent=True`, intent `simulation`, Dynamis 60 s planned) | `_SIMULATION_INTENT_RE` matched "running simulations ... does not establish" with no negation, quotation or conditional scope | `_requests_simulation`: per-sentence scope checks (negation before the verb, quotes, conditional clauses, negated predicate without a directive) | `test_negated_quoted_or_hypothetical_simulation_is_not_a_request` (6 paraphrases), `test_real_simulation_requests_are_still_recognised` | Fixed |
| I02 | P1 | Yes ("Which dynamical system should I simulate?" for T01; offline T01 ended `needs_input`) | Follows from I01 | Follows from I01; new `simulation_missing_initial_conditions` signal for a real gap | `test_proof_requests_need_no_simulation_clarification_or_literature`, `test_fully_specified_simulation_runs_and_missing_initial_condition_asks_once` | Fixed |
| I03 | P1 | Yes (Calcula "no numerical computation requested" for T06) | The reason described Calcula's own data-analysis gate | Truthful reason: "exact computation runs in the verified mathematics agent (Axiom)" | `test_computation_skip_reason_is_truthful` | Fixed |
| I04 | P1 | Yes (offline: 2 external calls with Search on for every prompt; table in §7) | `assess_evidence_need` fell back to "optional" retrieval for anything the math parser could not fully capture | The need is decided from structure: output contract (pure copy), closed or structured computation, mathematics from the question's own definitions, values given in the question, a model stated and simulated, conceptual knowledge. Retrieval stays for literature, current, empirical, entity and open research questions | `test_self_contained_requests_retrieve_nothing` (7), `test_self_contained_requests_make_no_external_retrieval_with_search_on` | Fixed |
| I05 | P1 | Partly (traced, not live-profiled at scale) | `escalation_triggers` escalated on route uncertainty and "sub-questions lack evidence" even when no evidence applies | Self-contained tasks escalate only on a concrete issue (core-step fallback); literal requests skip all phases; structured math answers in one tool call | `test_a_self_contained_task_is_not_escalated_on_route_uncertainty_alone` | Partly: effort-profile minimum work and the router's preference for plan-execute were not changed |
| I06 | P1 | Yes (court-case result for "two independent cases") | Short questions were sent verbatim with their instructions; generic words ("case", "proof", "integer") counted as subject terms; the floor always padded to 3 works; the UI count was every deduplicated record | `literature_subject` (instructions and case lines removed), search plan built on the masked text, generic and instruction words excluded from relevance terms, no padding, no subject terms means keep nothing, `graded_articles` = works actually used | `test_unrelated_keyword_matches_are_dropped_not_padded_to_three`, `test_literature_search_text_is_the_subject_not_the_instructions` | Fixed (lexical relevance; no embedding re-ranker was added) |
| I07 | P1 | Yes (T03 solved for T=1/2, n=-2/5; T04 `f(x)` read as `f*x`) | SymPy's parser treats an undefined name followed by `(` as multiplication; no parser represented definitions | `definitions.py`: definitions are SymPy `Function`s with branches and domains; a guard rejects any other parse that uses a defined name | `test_t03_...`, `test_t04_...`, `test_t15_the_observed_wrong_interpretation_fails_interpretation_not_mathematics` | Fixed |
| I08 | P1 | Yes | Branch conditions and domains were dropped | Branches (`even`, `odd`, relations, `otherwise`), declared or phrase domains, exactly-one-branch rule, undefined outside the domain | `test_t10_branches_application_and_multiplication_generalise`, `test_t10_an_argument_outside_the_domain_is_undefined_not_computed` | Fixed |
| I09 | P1 | Yes ("n=41 failed: n evaluates to 40") | `given_values` kept the first value of a name as a global parameter; restatements were checked against it | Case-local names are never global; a restated case name opens a new scope; case labels bind their case's values; cases carry ids | `test_case_local_bindings_never_contradict_each_other` (4), `test_cases_run_in_parallel_keep_their_own_results` | Fixed |
| I10 | P1 | Yes (T04's correct substitution unmatched) | The checker had no question definitions; the parser could not substitute them | The checker applies question definitions through their branches; single-formula definitions are substituted for other tasks ("derivative of f(x)") with the step recorded | `test_checker_still_catches_a_wrong_value_in_one_case_and_wrong_branch`, `test_t15_format_numerals_are_not_mathematical_inputs` | Fixed |
| I11 | P1 | Yes ("identity matches the problem" Pass on the wrong problem) | L1 alignment compared the call with the same faulty parse | Separate interpretation, domain, computation (exact rational recomputation) and coverage checks; any parse that does not apply a defined function is "refuted" with an interpretation-failure reason, so it never becomes an answer and is never called a disproof | `test_t15_...`, `test_t03_...` | Fixed |
| I12 | P1 | Yes (unaccounted `["4","40"]`, `["50"]`, `["2"]`) | `_fidelity` counted every numeral in the question | Output-format instructions are masked before the count | `test_t15_format_numerals_are_not_mathematical_inputs` | Fixed |
| I13 | P1 | Yes (trace "0 of 2 supported" vs banner "All 2 checked claims supported") | Web `claimSummary` ignored `inconclusive`; the first-pass step called defects "unsupported claims" | Undecided claims are counted; "All ... supported" only when every claim is decided and supported; step label "problem(s) to fix" | `web/tests/runStatus.test.mts` | Partly: `claim_tally` (backend) still merges not-checked and inconclusive; truncation (160 API / 80 export) is unchanged |
| I14 | P1 | Yes ("Not addressed: rigorous proof" on the correct T05 disproof, found live) | Topic-overlap, empty-evidence and deliverables graders did not know the task | Task-aware graders: no empty-evidence or overlap defect for self-contained or strict-form answers; status questions and requested proofs are delivered by a verdict | `test_completion_graders_respect_the_task`, `test_a_disproof_delivers_a_requested_proof_of_a_false_claim` | Fixed for the observed graders. `TaskOutcome.requested_operation` is still "evidence_synthesis" except for literal copies |
| I15 | P1 | Not reproduced as a code defect | The content of research answers comes from the model | Indirect mitigations only: no irrelevant literature in self-contained answers; with Search off the writer may not name papers | Live T01 (§5) | Open: T12 (Tao primary-source check) was not run |
| I16 | P1 | Partly | Relevance as above; acceptance status and argument validity are not separate fields | Relevance only (I06) | I06 tests | Open: T13 (claimed-proof sources, metadata outage) not implemented |
| I17 | P1 | Yes (`ALPHA\nBETA` shown as one line; banner inside copied text) | No contract; CommonMark soft breaks; banner prepended to the answer; template rules in the writer prompt | Contract extraction; deterministic literal path; writer and reviser rule; no banner or confidence-line rewrite in strict-form answers; content-preserving `conform` after the last revision; contract-aware rendering; banner-free copy and export (both variants, backend too); verified-answer fallback when the writer fails | `test_literal_payloads_are_extracted_exactly` (4, incl. Bangla and indentation), `test_t07_...`, `web/tests/auditOutputContract.test.mts`, `tests/test_export_line_breaks.py`, `web/tests/lineBreaks.test.mts` | Fixed in round 2: a written newline is now a line break on screen (`remarkSoftBreaks`), in DOCX (`<w:br/>`), PDF (`breaks: True` → `<br>`), LaTeX (`\`) and rich copy, with code and math untouched. No browser-level DOM or clipboard test was run |
| I18 | P2 | Yes | No final validation of the form | `validate` after the final revision; violations go to the task status (`partial`) | `test_contract_limits_and_json_only` | Partly: a violation is reported, never rewritten by a model |
| I19 | P1 | Yes ("Benchmark precision 25% (n=2)" on an unverified card) | The card and brief showed the benchmark rate of verified answers on every status | Shown, and sent to the writer, only for verified answers; the card title says "Verified" only when verified | `test_benchmark_precision_is_never_attached_to_an_unverified_answer` | Partly: claim-score rounding (0.37 card vs 0.38 trace) and the Verification tab percentage badge are unchanged |
| I20 | P1 | Yes (code: `handleQuotaExceeded` removed other threads' message lists) | Quota fallback deleted whole conversations, oldest first, including pinned or project threads | Never deletes conversation text: reconstructible caches (plots, passage text) are dropped first, then the save reports "not saved" | `a full browser never deletes another investigation's conversation` (fails on the original code, passes now) | Partly: the slimming of other threads is not transactional; the notice is single-slot; threads pruned by older versions still open empty without an explanation |
| I21 | P1 | Partly | The stored excerpt began with the verification banner | Banner stripped from memory writes; literal copies are not stored | Covered indirectly | Open: trust annotation beyond the existing `is_turn_verified` |
| I22 | P2 | Traced (header time stops before the end-of-run bookkeeping; the budget clock starts later; phase sums are disjoint) | Several clocks with different start and end points | None | — | Open (documented here only) |
| I23 | P2 | Checked | Lean was not installed, so the checker reported "unavailable" correctly | Lean 4.35.0 installed (see §8); real-Lean test added | `test_a_real_lean_installation_checks_proofs_and_never_accepts_sorry` (live mode) and the existing `tests/test_feat_t5.py` | Fixed for availability. Mathlib is not installed |

## 3. Repair design

1. **Structured mathematics** (`definitions.py`). The representation holds:
   - function definitions: name, parameter, domain, and branches with conditions;
   - tasks with ids taken from the question: `evaluate`, with optional case-local bindings and factorization; `orbit`; and `claim`, with a predicate or relation, a quantifier domain and conditions.

   The tool `axiom_structured` executes these tasks with exact SymPy arithmetic, through the allowlist parser only. Four checks are reported separately:
   - interpretation: a defined name is always applied, never multiplied;
   - domain: arguments and witnesses lie in the domain, and exactly one branch applies;
   - computation: an independent rational-arithmetic route recomputes every value, factor, orbit arrow and witness;
   - coverage: every requested item has a result.

   Universal claims are proved in three ways: symbolically after substituting the definitions (with written denominators checked for singular points, so `x/x = 1` fails at `x = 0` unless `x ≠ 0` is stated); by an exhaustive residue argument for divisibility and parity of integer polynomials; or refuted by the smallest counterexample. When none of these applies, the claim is reported "unresolved", meaning evidence, not a proof.
2. **Reasoning steps.** Every result carries steps generated from the computation, for example "1 is odd, so T(1) = 3*1 + 1 = 4", "With n = 40: n^2 + n + 41 = 40^2 + 40 + 41 = 1600 + 40 + 41 = 1681", "1763 = 41 * 43, where 41, 43 are prime" and "0 < 0 is false, so the remaining branch applies". The writer receives them as `<math_derivation>` and is told to use them verbatim, so each worked step is one the checker confirmed.
3. **Output contract** (`output_contract.py`). It extracts:
   - a literal payload (LF-normalised, indentation kept);
   - word and line limits, sentence counts;
   - plain-text and JSON-only modes, and "nothing else".

   The contract masks format numerals, adds a final instruction that overrides the report template, suppresses banners and confidence lines in strict-form answers, is enforced after the last revision, and is sent to the web client in `execution_artifacts.output_contract` for rendering.
4. **Information need.** Retrieval follows an identified need, not the availability of Search, in line with the adaptive-retrieval literature. Mallen et al., [ACL 2023](https://arxiv.org/abs/2212.10511), found that retrieval helps with long-tail facts and can mislead on well-known ones; Adaptive-RAG and CRAG respectively skip retrieval for simple queries and discard irrelevant documents. Search off is enforced twice: in the routing decisions, and by a per-run context variable at the tool-execution layer, which refuses every networked (`DIRECT_REST`/GraphQL/MCP) tool before the cache.
5. **Case scope in the checker.** Case-local names are scoped. A restatement opens a new case and drops that case's later bindings; case labels in the answer select the bindings; question definitions are applied through their branches.

## 4. Test commands and results

| Command | Result |
|---|---|
| `uv run pytest -q -p no:cacheprovider` (here: `.venv/Scripts/python.exe -m pytest -q -p no:cacheprovider tests`, `TRIBOS_PLANNER=off`) | Mid-repair: 1441 passed, 24 failed (all triaged, see §9). **Final: 1528 passed, 17 skipped, 0 failed** (4 min 7 s). The 2 extra skips are the real-Lean tests, which run only in live mode |
| `TRIBOS_LIVE_TESTS=1 pytest tests/test_audit_repair.py -k lean` | 3 passed (real Lean 4.35.0) |
| `uv run ruff check tribos app tests scripts --select F,E9` | All checks passed |
| `uv run bandit -c pyproject.toml -r tribos app --severity-level high` | No high-severity issues |
| `uv run python scripts/gen_env_reference.py --check` | Exit 0 |
| `npm run typecheck` | Pass |
| `npx eslint src` | 0 errors, 165 warnings |
| `npm test` | 197 tests, 197 passed, 0 failed |
| `npx next build` | Pass. The first attempt ran out of memory in the TypeScript step while the full pytest suite was running; the rerun passed |
| `TRIBOS_LIVE_TESTS=1 pytest tests/test_audit_repair.py::test_a_real_lean_installation_checks_proofs_and_never_accepts_sorry` | 1 passed (real Lean 4.35.0) |

**Blocked or not done:**
- No browser automation was run, so DOM rendering, clipboard and storage in a real browser were not checked; the corresponding logic is covered by node unit tests.
- T12/T13 research checks were not implemented or run.
- Live model runs depended on the NVIDIA endpoint, which returned HTTP 500 ("Failed to generate completions") for part of the session; affected runs are marked in §5.

## 5. T01–T20 and held-out cases

| Test | Evidence | Result |
|---|---|---|
| T01 | Offline + live: no simulation intent, no clarification, no retrieval. Live answer: "an open problem in mathematics: it has neither been proven nor disproven ... Checking examples or running simulations cannot establish the claim" | Pass |
| T02 | Same intent and need as T01 (`test_proof_requests_...[T02]`), run independently | Pass |
| T03 | Verified: T(1)=4, T(2)=1, T(4)=2, cycle 1→4→2→1. Live: "T(1) = 4, T(2) = 1, T(4) = 2. Cycle: 1 → 4 → 2 → 1." | Pass |
| T04 | Verified f(2)=5 and the identity by substitution, ASCII and Unicode. Live: "f(2) = 2² + 1 = 5. For every real x, f(x) - x² = (x² + 1) - x² = 1" | Pass |
| T05 | Verified disproof, counterexample n=40, 1681 = 41². Live round 1: correct text, but the run was marked partial "Not addressed: rigorous proof". Live round 2, after the I14 fix: completed, "False. For n = 40, n² + n + 41 = 1600 + 40 + 41 = 1681 = 41², which is composite ... one counterexample refutes the universal claim" | Pass |
| T06 | Verified both cases, also reversed and renamed. Live round 1, Search on: the provider's HTTP 500 led to the report fallback and a recorded contract violation (8 lines vs 2). Live round 2, Search on, and round 1, Search off: exactly `Case A (n = 40): 1681 = 41^2` / `Case B (n = 41): 1763 = 41 * 43`, contract met, completed, 0 external calls | Pass |
| T07 | Offline and live, Search on and off: response exactly `ALPHA\nBETA`, 0 tool calls, framework `literal-direct`, 7.2 s and 2.1 s live | Pass |
| T08 | Search off: 0 external calls for every prompt (offline table §7); tool-layer refusal test; a research question with Search off says so | Pass |
| T09 | Three-line indented, Bangla, JSON-only, word limits: extraction, validation and rendering tests | Pass (unit level; no browser) |
| T10 | Piecewise, nested, scalar vs application, negative arguments, positive-integer domain, `x/x` with and without `x ≠ 0`, residues, false inequality | Pass |
| T11 | Full ODE: simulation, no question. Missing `x'(0)`: one clarification naming exactly that condition | Pass |
| T12 | — | Not done |
| T13 | — | Not done |
| T14 | Undecided vs supported counts (web), task-aware graders, contract violations in the task status | Partly |
| T15 | Observed wrong interpretation → interpretation check fails, status refuted with an interpretation-failure reason; out-of-domain witness → domain check fails; format numerals ignored | Pass |
| T16 | Reverse order, parallel runs, separate conversations with the same expression | Pass |
| T17 | Quota test with existing conversations: no deletion, `not_saved` reported, text intact | Pass (node test; no real browser) |
| T18 | §7 measured calls; literal path 2–7 s live | Partly (no cold/warm profiling) |
| T19 | Lean unavailable: existing tests. Lean available: real-Lean tests (proof verified, false theorem rejected, `sorry` never accepted). Live, before the two Lean fixes in §9: the formaliser wrote Mathlib-style code and failed; the answers said so ("the Lean formalisation attempt failed, so this is not formally verified") and kept the SymPy-verified result | Pass; the live formalisation was not re-run after the fixes |
| T20 | Full suites §4/§10; held-out prompts in the tests and §7 | Pass |

## 6. Before / after examples

All of these come from the production components in this repository.

- **T03 parse.** Before: `kind=solve, equations=['T*n = n/2', 'T*n = 3*n + 1']`, answer T = 1/2, n = −2/5, labelled
  Pass. After: `kind=structured`, verified, results `T(1)=4`, `T(2)=1`, `T(4)=2`, orbit `1 -> 4 -> 2 -> 1`; the four
  checks pass. The old parse fed to the verifier now fails "interpretation: defined functions are applied, never
  multiplied" with the reason "interpretation failed: the computation answers a different problem ... says nothing
  about whether the question's own claim is true".
- **T06 checker.** Before: `n = 41` failed with "n evaluates to 40". After: both cases pass in either order, and
  `B: 1763 = 41 * 41` fails with "1763 evaluates to 1763, 41*41 to 1681".
- **T07.** Before: the full research pipeline ran, literature was retrieved, and the CommonMark rendering showed one
  line. After: the payload is returned verbatim, no tool runs, and the client renders two lines through hard breaks.
- **Retrieval.** Before: 2 external calls with Search on and 1 with Search off for every audit prompt. After: 0,
  except for a genuine research question with Search on (2).

## 7. Measured call and retrieval differences

Production orchestrator with the offline recording registry and no model (`measure_calls.py`; the baseline ran from a
detached worktree of `cffff9f`). Columns are tool calls / external retrieval calls.

| Prompt | Before, Search on | Before, Search off | After, Search on | After, Search off |
|---|---|---|---|---|
| T01, T02, T03, T04, T05, T06 | 2 / 2 each | 1 / 1 each | 0 / 0 each | 0 / 0 each |
| T07 (literal) | 2 / 2 | 1 / 1 | 0 / 0, `literal-direct`, completed | 0 / 0, `literal-direct`, completed |
| ODE simulation (full / missing IC) | 3 / 2 | 2 / 1 | 1 / 0 | 1 / 0 |
| Word problem with given values | 2 / 2 | 1 / 1 | 0 / 0 | 0 / 0 |
| "Show that two odd integers sum to even" | 2 / 2 | 1 / 1 | 0 / 0 | 0 / 0 |
| Conceptual (entropy) | 2 / 2 | 1 / 1 | 0 / 0 | 0 / 0 |
| Research (biofilm tolerance) | 2 / 2 | 1 / 1 | 2 / 2 | 0 / 0 |

The "before, Search off" column is the leak: one literature call with Search off. Offline task statuses are mostly
`partial` because no model writes the answer in this mode. In the baseline, T01 ended `needs_input`, the bogus
simulation clarification.

## 8. Storage and the formal checker

- **Browser storage.** No migration is needed: the change only stops future deletions. Conversations already pruned by
  earlier versions are not recoverable from the browser. The server keeps the full answer text per run
  (`run_store`) and a 350-character memory excerpt, but no restore endpoint exists. Follow-up work:
  - make the slimming of other threads transactional;
  - show `messagesPruned` in the sidebar;
  - replace the single-slot notice.
- **Lean.** Drive C: had 0.22 GB free, so the first toolchain download failed and that partial install was removed
  with `elan self uninstall`. elan and Lean 4.35.0 now live in `X:\lean\elan`, installed with `--no-modify-path`, and
  `.env` (gitignored, not committed) sets `TRIBOS_LEAN_PATH=X:/lean/elan/toolchains/leanprover--lean4---v4.35.0/bin/lean.exe`.
  Mathlib is not installed. It is a multi-GB download; set `TRIBOS_LEAN_PROJECT` to a Mathlib project to enable it.

## 9. Additional defects found while repairing

- `evaluate EXPR for n = 3` was parsed as "solve n = 3". It is now a structured evaluation.
- A writer-model failure produced a "Results gathered for ..." report that broke the requested form. A strict-form
  answer now falls back to the verified computation.
- The backend export stripped only the "Scientific Verification Notice" banner variant.
- Prose such as "(N = 102)" would have become checker bindings under plain-text extraction. Plain-text extraction now
  requires an operator or a function application.
- With no subject terms left, the literature relevance floor accepted every work (coverage 1.0). It now keeps only
  pinned identifiers.
- Nine existing tests encoded the Search-off literature leak or the retrieve-everything default. They were switched to
  Search on where literature was their subject, or updated to the new policy, with new tests for the opposite case.
- `tribos/verify/formal/runner.py` decoded Lean's UTF-8 output with the Windows code page, so `ℕ` appeared as `â„•`
  in the errors fed back to the repair loop. It now decodes UTF-8.
- Without Mathlib, the formaliser was told only "use core Lean 4", and wrote Mathlib tactics and notation. It now gets
  the list of core tactics and unavailable ones; `import Mathlib` is dropped and `ℕ`/`ℤ` are renamed to `Nat`/`Int`
  (same meaning) before checking.

## 10. Final summary

**Fixed, with tests:**
- negated and hypothetical intent;
- unnecessary clarification, plus the legitimate missing-input clarification;
- truthful skip reasons;
- need-driven retrieval with Search off enforced at the tool layer;
- relevant literature queries without padding;
- function application, branches and domains;
- case-local bindings;
- separate interpretation, domain, computation and coverage checks;
- format numerals;
- exact literal output and contract-aware rendering, copy and export;
- task-aware graders;
- honest confidence display;
- no deletion of saved conversations;
- checked step-by-step derivations;
- a working Lean checker.

**Remains:**
- T12/T13 research-claim and source-status work;
- browser-level end-to-end tests;
- I22 timing definitions;
- the backend claim-tally wording and truncation;
- transactional storage slimming;
- Mathlib.

**Risks:**
- The evidence-need policy now skips retrieval for conceptual and self-contained questions. A user who wants sources
  for those must say so ("cite", "papers"); the plan step states this.
- The structured parser covers explicit definitions. Recursive or multi-parameter definitions are reported as
  unsupported rather than guessed.

## 11. Round 2 (follow-up requests)

1. **Exports.** One rule everywhere: a single written newline is a line break.
   - On screen: the `remarkSoftBreaks` plugin (no new dependency).
   - DOCX: a run with `"
"` (python-docx writes `<w:br/>`).
   - PDF: markdown-it `breaks: True` gives `<br>`.
   - LaTeX: `\` between consecutive prose lines.
   - Rich copy: the rendered page now carries `<br>`.

   Both verification-banner variants are stripped from every export.

   Tests:
   - `tests/test_export_line_breaks.py`: DOCX paragraph text `A: 1681 = 41 * 41
B: 1763 = 41 * 43` with `<w:br/>`; PDF lines `ALPHA` and `BETA` separate; banner absent.
   - `web/tests/lineBreaks.test.mts`: paragraphs, lists, code and display math unchanged.
2. **Answer first, cards collapsed.**
   - Every result card under an answer starts collapsed, and the supporting-evidence deck starts closed.
   - A collapsed card that holds a warning shows a "needs a look" chip in its header. The existing `artifactDisclosure` analysis now decides only this chip.
   - The writer's format rule is: direct answer (Executive Summary with confidence), then "### Brief analysis" with justified exact steps, then further sections only when asked. Raw tool output is not repeated in the text, since the cards hold it.
3. **Open problems are worked, not only reported.** The approach is general; nothing is specific to one conjecture.
   - Process rules ("If n is even, replace it with …") become a parity map, and "reaches c for every n" becomes a `reaches` task.
   - The tool checks every start value up to 5000 exactly, using compiled rational closures with no eval or exec. A cycle that avoids the target is a rigorous disproof, independently recomputed.
   - The tool derives what is provable per branch: decrease or increase on the residue class, parity of the output, and the two-step map. It adds the least-counterexample reduction.
   - It reports the result as "unresolved", meaning evidence and not a proof, unless it is disproved.
   - Every proof request gets `PROOF_ATTEMPT_NOTE`. It requires trying the standard methods, giving the strongest rigorous partial results, naming where each approach stops, and labelling each statement proved, evidence or open. It forbids passing evidence off as proof or claiming an open problem resolved.
   - Example (T01): the lemmas "n/2 < n for even n ≥ 2" and "3n + 1 = 6k + 4 is always even for odd n", the two-step map (3n+1)/2, the reduction, and "every n from 1 to 5000 reaches 1; longest orbit 3711 (237 steps)". The 3n − 1 variant is disproved by the cycle 5 → 14 → 7 → 20 → 10 → 5.
4. **Checker defects found live in round 2 and fixed.**
   - An answer that writes its own piecewise map branch by branch ("f(n) = n/2 (even n)", "f(n) = 3n+1 (odd n)") was bound to its first branch, so the second branch was reported as a contradiction. Now:
     - an answer function equal to a branch of the question's definition is that definition;
     - a function restated next to branch words (even, odd, otherwise, "if n < ...") is never bound to one branch.
   - The units audit read the variables `n` and `k` as unit symbols ("inconsistent units" on `3n + 1 = 6k + 4`). It now runs only when the question involves physical quantities or units.
   - Test: `test_a_piecewise_map_written_branch_by_branch_is_not_a_contradiction_and_pure_maths_has_no_units`.

**Round 2 results:**
- Backend suite: **1536 passed, 17 skipped, 0 failed**.
- Web: typecheck pass; eslint 0 errors; `npm test` 201/201; `next build` pass.
- Ruff, bandit (0 high) and env-check pass.
- Live T01 (132.6 s, 0 external calls):
  - verification passed, task completed;
  - answer: the exact statement; proved lemmas (even step decreases; odd step increases and is followed by an even step; the two-step map exceeds n, so no monotone descent works); the well-ordering reduction; exact evidence up to 5000 labelled as evidence; status "known open problem", nothing claimed resolved.
- Live T04: 16.8 s, verified. Live T06: 9.9 s, exactly two lines.
