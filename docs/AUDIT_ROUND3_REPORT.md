# Audit round 3 — I24–I43, T21–T45

Branch `audit-repair`. Scope: `Tribos_Codebase_Audit_and_Repair_Prompt (1).md` (runs B1–B5, R1–R7, P01–P14; issues
I01–I43; tests T01–T45). Round 1 (I01–I23) is documented in `docs/AUDIT_REPAIR_REPORT.md`; this report covers what
was re-checked or changed in round 3. Everything below was run in this environment; nothing is inferred from the
supplied captures except where marked "audit evidence".

Environment: Windows 11, Python 3.12 venv, Node 24, Lean 4.35.0 (core, no Mathlib) at `TRIBOS_LEAN_PATH`, provider
NVIDIA NIM `nvidia/nemotron-3.5-super-vl-120b-a12b` for planning, agents and writing (from `.env`; unchanged).

## 1. Data flow (where the repairs sit)

```
question ─▶ output_contract.extract (limits: polarity, scope, precedence)          [I29]
         ─▶ evidence_need (status lookups need a source; derivations do not)       [I38]
         ─▶ router (named conjecture ≠ hypothesis generation)                      [I35]
         ─▶ planner ─▶ plan_graph.validate_plan (registered names, policy)         [I34]
         ─▶ math agent: parse_problem → axiom_structured / axiom_solve
                        → verifier (domain from the question, solution sets,
                          zeros, forged-result rejection)                          [I24 I31 I32 T42]
         ─▶ formal_proof: correspondence check before Lean                         [I33]
         ─▶ draft: render_verified_answer (no writer needed) │ writer │ fallback    [I27 I28]
         ─▶ debate (bounded rounds)                                                [I37]
         ─▶ verifier: statement roles, status claims bound to the cited page      [I30 I41]
         ─▶ math_claims (no units in pure maths, unknowns not bound)               [T34/T42 live]
         ─▶ finalize: counter-evidence bound to the final revision; task status   [I40 I43]
         ─▶ web: scoped summaries, "needs a look" with its reason                  [I39 I42]
provider calls: ChatOpenAI (SDK retries 0) → RetryingAsyncTransport (bounded)     [I26]
```

## 2. Issue table I01–I43

Status vocabulary: Fixed · Already fixed (round 1, re-run green) · Partial · Not reproduced · Blocked.

| ID | Status | Reproduction (this round) | Cause (file / symbol) | Change | Validation |
| --- | --- | --- | --- | --- | --- |
| I01–I04, I06–I12, I17 | Already fixed | Round-1 tests re-run in the full suite | see round-1 report §2 | — | `tests/test_audit_repair.py` (all pass) |
| I05 | Partial | — | effort profile / router preference unchanged | — | round-1 test |
| I13 | Partial | — | `claim_tally` still merges not-checked and inconclusive | — | `web/tests/runStatus.test.mts` |
| I14 | Fixed (residual closed) | Math runs reported `requested_operation: evidence_synthesis` | `_task_outcome` named every non-simulation run "evidence synthesis" | Mathematical requests are `mathematical_answer` | `test_t37_sufficient_validated_results_…` |
| I15, I16 | Partial | T12/T13 not run | — | — | — |
| I18 | Partial | — | a violation is reported, not rewritten | — | round-1 test |
| I19, I20, I21 | Partial | — | see round-1 report | — | — |
| I22 / T44 | Open | not re-measured | several clocks with different boundaries | none this round | — |
| I23 | Already fixed | real Lean tests | — | — | 3 real-Lean tests pass (`TRIBOS_LIVE_TESTS=1`) |
| I24 | Fixed | P03 `h(0)=0`, P04 `q(0)=4` with Domain Pass (reproduced before the fix) | `parse_definitions` lost declared/sentence domains (parity default `integer`); `check_structured` checked the payload against itself | domain priority declared > branch > sentence; `stated_domains(question)` re-reads the restriction from the question; undefined inputs are complete answers | T22–T24 tests, forged-payload test, live P03/P04 |
| I25 | Fixed | live P04: planner call rejected `definition 'q' gives no parameter and its formulas use no variable` | `StructuredDefinition` had no repair for renamed/missing fields | `_repair_parameter`: aliases, single-variable inference, single formula without `branches`, branch formula under `formula/expr/rule/value`, a domain spelled differently (`positive_integers`, `Z+`) read by `domain_from_words`, a missing task `id` taken from the task's own expression; ambiguous or unreadable → specific refusal; domain never widened | `test_t38_a_missing_parameter_…`, `test_t38_a_domain_spelled_…`, `test_t38_a_task_without_an_id_…`; live P04 |
| I26 | Fixed (recovery) · diagnosis partial | Logs: 500s come in bursts across planner, writer, critics, NLI (`backend-main*.log` sequences); replay of minimal and app-shaped requests (11.6k and 69k chars, stream, thinking on/off) all 200 with `nvcf-reqid` | SDK retried once after ~0.4 s, inside the burst; draft and buffered-stream layers retried again (multiplied attempts) | `provider_retry.RetryingAsyncTransport`: ≤ `TRIBOS_LLM_RETRY_ATTEMPTS` (3) per request, backoff + jitter, `Retry-After`, ≤ `TRIBOS_LLM_RETRY_DEADLINE_S` (20 s), retryable statuses only, request ids logged, no bodies or keys; SDK `max_retries=0`; app layers no longer resend errors the transport retried | 4 transport tests; live log: two 500s (`1830316b…`, `84fc8abd…`) then success | 
| I27 | Fixed | P05/P06/P11 partial or wrong form when the writer failed (audit evidence); offline writer-failure run reproduced | the answer existed only through the writer | `axiom/render.py: render_verified_answer` used before the writer and in its fallback | T37 writer-failure tests; live P03–P10 (`synthesis_model: verified_computation`) |
| I28 | Fixed | offline: failed run returned "Results gathered for: <question>" | fallback echoed `clean_query` | results shown as results only; with none, an honest "No answer could be produced…" naming failed stages | `test_t37_zero_results_…` |
| I29 | Fixed | `extract("There is no 150-word limit.")` → `max_words=150` | `_MAX_WORDS_RE` matched with no polarity/quote/example handling; first value won | `_apply_limits`: events in order, later rule wins, removals cancel, quoted/example limits inert, ranges (`min_words`), multilingual removals, `inactive` list kept for transparency | 11 T35 cases + range test |
| I30 | Fixed | "There is no 150-word limit" → literature-wide absence "unsupported" | `_ABSENCE_PATTERN` (`there is no …`) applied to any sentence | `statement_role` (instruction/error/mathematical) before checking; new `status` claim type | T36 tests |
| I31 | Fixed | P09 "no solutions (general solution set: …)", P10 same (reproduced) | empty isolated-root list rendered as "no solutions" | sets rendered as sets (`pretty_set`: ∅, ℝ, ℝ ∖ {1}, {−i, i}) | T26–T31 tests; live P06/P09/P10 |
| I32 | Fixed | forged `solution_set='Reals'` for P09 was silently replaced by the checker's set | tool's set never compared | identity + excluded-point check, and the tool's set must equal the re-derived one | `test_t29_t30_…` |
| I33 | Fixed (core Lean) | the observed `theorem riemann_hypothesis : False` would have gone to Lean | no statement correspondence check | `formal/correspondence.py`: True/False targets, assumed conclusion, missing constants, domain needing ℝ/ℂ/analysis without Mathlib → `not_formalizable` with no model call; mismatch goes back to repair | 7 + 2 T39 tests; live T34/T42: `not formalisable without Mathlib` |
| I34 | Fixed | planner name `web_search` → "not registered", summary "no follow-up calls needed" | `validate_plan` had no capability map; summary ignored rejections | `capability_alias`: runs under the registered tool only if policy allows, else the policy reason; summary "No planned call ran: N rejected (…)" | `test_t38_an_invented_tool_name_…` |
| I35 | Fixed | T32/T33/"Goldbach"/"null hypothesis"/"proposed method" all routed `hypothesis_generation` | `_HYPOTHESIS` matched the bare words; semantic kind "conjecture"; `_explain` defaulted to the hypothesis reason | generation needs a generating verb/adjective; kind "conjecture" no longer counts; neutral reason when chosen otherwise | 8 T32–T34 routing cases |
| I36 | Fixed | hypothesis phase ran for named conjectures; note demanded a dynamical system | `_INTENT_RE` matched `hypothes|conjectur` | same generation pattern; note no longer imposes the prerequisite | `test_fix_agentic2` (updated), routing tests |
| I37 | Fixed | (code) round two always ran; nonresponses unreported; additions under a fixed form accepted | `DebatePhase.run` | round two only for an in-scope concrete issue; abstentions reported; additive critiques dropped under `strict_form` (now includes ≤ 3 sentences) | `test_i37_…`, debate tests |
| I38 | Fixed | T32/T34 `self_contained/none`; "Has … been proved?" `self_contained` | no status-need rule | `_STATUS_NEED_RE`: status only → required; inside a proof/investigation → optional | 4 T38 cases |
| I39 | Partial | sub-question counter "0/4 answered"; "source URL" missing beside a link | counter tracks tool-backed evidence; deliverables used word overlap | label "backed by tool evidence"; a link delivers a URL item; rendered verified answers deliver their items | `test_t43_a_link_…`, live T33 deliverables "addressed". Link destinations are not fetched |
| I40 | Fixed (panel) | live T33: 10 pre-draft rows about other claims | rows never reconciled with the final answer | `CounterEvidenceReconcilePhase`: rows about dropped claims move to labelled `history` | `test_t40_…`; live T33 `history: 10`, `conflicts: 0` |
| I41 | Fixed (verifier) · see §5 | live T33: claim bound to `DOI:10.5281/zenodo.17842806` instead of the cited CMI page | status check took the first record sharing words | `_status_verdict` judges against the cited URL's document when retrieved (a status label anywhere on that page counts); a search snippet is "not checked", not "unsupported"; never rescued by another record | `test_t43_a_status_claim_is_bound_…` |
| I42 | Fixed | "needs a look" on a verified math card; "cited identifiers" on answers citing nothing | attention reused the disclosure policy (always true for `math_agent`); fixed wording | `artifactAttention` with reasons (chip tooltip + "Why flagged" in the card); `checkScope` names only checks that applied | `web/tests/artifactDisclosure.test.mts`, `verificationCoverage.test.mts` |
| I43 | Fixed | offline T34 with all model calls failing → "partial … raw evidence shown"; UI "Completed: evidence synthesis" | `_task_outcome` returned partial for no results + no writer; UI printed the requested operation as completed | failed when nothing was produced; "Ran: <executed>" only; closed computations not downgraded by an unneeded planner phase | T37 tests; live P03 |

## 3. Test mapping T01–T45

| Group | Coverage | Result |
| --- | --- | --- |
| T01–T11, T14–T20 | round-1 tests (`tests/test_audit_repair.py`, export/line-break tests) | pass |
| T12, T13 | not run (need live claimed-proof sources) | open |
| T21 | `test_t07_literal_copy…`, `web/tests/auditOutputContract.test.mts` | pass |
| T22–T25 | `test_t22_t25_…`, `test_t25_…order`, forged-domain test; live P03/P04 | pass |
| T26–T31 | `test_t26_t31_…` (7 sets), `test_t29_t30_…` (forged sets); live P06/P09/P10 | pass |
| T32–T34 | routing/need tests; live T33, T34 (healthy) and offline T34 (all model calls failing) | pass; see §5 |
| T35 | 11 contract cases + range | pass |
| T36 | statement roles (6) + echo test | pass |
| T37 | writer failure (3 prompts), zero results | pass (planner/critic/retrieval failures not injected one by one) |
| T38 | schema repair, tool alias Search on/off | pass |
| T39 | correspondence (7), no-model `not_formalizable`, mismatch → repair | pass |
| T40 | reconcile test; live T33 | pass |
| T41 | out-of-domain witness, undefined input | pass |
| T42 | symmetry/zeros/line, forged zeros, `4s−3=0` regression; live T42 | pass |
| T43 | link deliverable, status claim bound to cited page | pass (DOM href / clipboard / native export not browser-tested) |
| T44 | — | open |
| T45 | transport tests, SDK retries off, no double retry; live runs §5 | pass |

## 4. Commands and results

```
.venv/Scripts/python.exe -m pytest -q -p no:cacheprovider tests/test_audit_round3.py      # 77 passed
.venv/Scripts/python.exe -m pytest -q -p no:cacheprovider tests/                          # see §4.1
TRIBOS_LIVE_TESTS=1 .venv/Scripts/python.exe -m pytest -q tests/test_audit_repair.py -k lean   # 3 passed (real Lean)
.venv/Scripts/python.exe -m ruff check --select F,E9 tribos app tests scripts             # All checks passed
.venv/Scripts/python.exe -m bandit -q -r tribos app -lll                                  # no findings
.venv/Scripts/python.exe scripts/gen_env_reference.py --check                             # exit 0 (2 settings added)
cd web && npx tsc --noEmit                                                                # exit 0
cd web && node --test "tests/*.test.mts"                                                  # 203 passed
cd web && npx eslint src                                                                  # 0 errors (existing no-explicit-any warnings)
```

### 4.1 Full suite

First full run: 1604 passed, 3 failed. Two were caused by this round and fixed: `test_feat_t5::test_the_repair_loop_feeds_errors_back`
fed an unrelated theorem (`n + 0 = n` for "2 + 2 = 4"), which the I33 check now rejects before Lean; the test now uses a
faithful statement with a broken proof, which keeps its purpose (compiler errors reach the repair).
`test_foundation_hooks::…fallback_markdown…` expected the closing "Evidence limitations" note, restored without the
question echo. The third, `test_evals_cassette::test_normalize_replaces_volatile_substrings_only`, failed because the
run crossed midnight (its `TODAY` was computed on the 25th, `normalize` ran on the 26th); it passes on rerun.
Final full run (`pytest_round3c`): 1612 passed, 17 skipped, 2 failed. The two failures are
`test_answer_format::test_synthesis_request_is_dated` and `…::test_orchestrator_sends_date_and_evidence_levels`: the
evidence block is dated with `utc_today()` (unchanged from HEAD) and the tests compare with the local date; at the time
of the run UTC was 2026-10-25 and local (UTC+6) 2026-10-26. They are unrelated to this round and pass when both dates
agree. Files edited after that run started were re-tested on the final code: 207 passed (round-3, audit, capability
matrix, math claims, citations, verifier, structured, schema and Axiom tests).

## 5. Live runs (configured provider, `POST /api/chat`, framework auto)

Each row is one `POST /api/chat` with the response and records as returned (`live_checks3.py`). Times are the
client's wall-clock seconds. Rows marked "after" ran after the fix named in them.

| Prompt | Search | Seconds | Task status | Answer (verbatim, shortened) | Records |
| --- | --- | --- | --- | --- | --- |
| P03 | off | 14.0 | partial | `h(0) is undefined: 0 is not in the domain of h (positive integers)` / `h(1) = 6` / `h(6) = 3` | rendered from the verified computation; status partial only because the planner phase failed → fixed (I43) |
| P03 after | off | 25.3 | completed | same three lines | `synthesis_model: verified_computation`, verification verified |
| P04 | off | 7.5 / 11.7 / 9.2 | completed | `q(0) is undefined …` / `q(-2) is undefined …` / `q(3) = 13` | the planner's own call was rejected each time (missing `parameter`; domain spelled `positive_integers`-style; missing task `id`); each shape now repaired (I25). The last repair (task id) was not re-run live |
| P06 | off | 6.0 | completed | `∅` | |
| P09 | off | 5.9 | completed | `ℝ ∖ {1}` | |
| P10 | off | 5.8 | completed | `ℝ` | |
| T33 | on | 50.9 | completed | "The Riemann Hypothesis remains unsolved according to the Clay Mathematics Institute's official page: https://www.claymath.org/millennium/riemann-hypothesis" | claim typed `status` (I30); 10 stale counter-evidence rows moved to history (I40); claim bound to a Zenodo record → defect found (I41) |
| T33 after | on | 93.7 / 329.9 / 75.5 | completed | same content, CMI URL | claim now judged against the cited CMI page. Last run: "the cited page was read and does not state this status" although the answer quotes an "Unsolved" label; the page-label check was added after that run and is covered by tests, not by a further live run. The 51–330 s spread for one sentence was not investigated (T44 open) |
| T42 | on | 127.0 | completed | correct proof, zeros 1/4 and 3/4 with checks, correct scope about ζ | banner "2 statements do not hold" on `4s − 3 = 0`, `4s − 1 = 0` (false: s read as seconds) → fixed |
| T42 after | on | 75.9 | completed | same mathematics | verified math agent, 0 defects |
| T34 | on | 344.4 | partial | ~2,085 words: precise statement, Euler product, functional equation and zero symmetry, zero-free region, argument-principle reduction to the unproved lemma N₀(T) = N(T), numerical checks with stated limits; Lean `not_formalizable`; no word cap | 6 false statement failures (`s = 1` bound from the pole; `\dots` read as ṡ; σ, t bound from prose) → fixed; re-auditing this same answer offline now gives 0 failed. Not re-run live |
| T34 (all model calls failing, offline) | off | — | failed | "No answer could be produced. The writing model failed (…), and no tool produced a result …" | no prompt echo, no cap, honest status |

Provider recovery in these runs (`backend-main6.log`): `Provider transient failure … attempt 1 status=500 request_id=1830316b-047f-4c0a-af3a-78becaa4f4d1 … attempt 2 status=500 request_id=84fc8abd-9332-46aa-8789-bb5c101c6414 … retrying in 3.3s`, then the request succeeded; likewise `b79c1a7e…` (one retry) and `6bc34e88…`/`f7431c3a…` (two retries).

## 6. Before / after

| Case | Before | After |
| --- | --- | --- |
| P03 (T23) | `h(0) = 0`, Domain Pass (audit evidence; reproduced) | `h(0) is undefined: 0 is not in the domain of h (positive integers)` / `h(1) = 6` / `h(6) = 3`, verified |
| P04 (T24) | `q(0) = 4`, `q(−2) = 8`, Domain Pass | both undefined, `q(3) = 13`; integer-domain control gives 4, 8, 13 |
| P09 (T29) | "no solutions (general solution set: Union(Interval.open(-oo, 1), Interval.open(1, oo)))" | `ℝ ∖ {1}` (identity and excluded point checked; a forged `Reals` is refuted) |
| P10 (T30) | "no solutions (general solution set: Reals)" | `ℝ`; the inconsistent control gives `∅` |
| P12 (T39) | `theorem riemann_hypothesis : False` sent to Lean | `not_formalizable` before any model call: "needs complex numbers, complex analysis (the zeta function) … No formal statement was checked; this says nothing about whether the claim is true." |
| P14 (T34, provider failing) | "Results gathered for: <prompt>", 150-word cap enforced, instruction scored as a literature claim, "Completed: evidence synthesis" | `failed`: "No answer could be produced. The writing model failed (…), and no tool produced a result …"; no cap; no instruction claim |
| T42 | parsed as an equation, `s = 0`, unverified | claim proved by substitution; zeros 1/4, 3/4 complete (factor reconstruction); none on Re(s) = 1/2; zero set symmetric |

## 7. Provider diagnosis (I26)

* Logs (`backend-main*.log`): NVIDIA statuses in order, `.` = 200, `X` = 500 — e.g. `........XX...XXXXXXXXXX.XXXX......…`.
  Failures cluster in bursts across unrelated callers and request shapes, between long healthy stretches.
* Replay through the same endpoint/model/key with SDK retries off (`provider_diag.py`): minimal (non-stream and stream),
  app-shaped 11.6k chars (thinking off and on) and 69k chars all returned 200 with `nvcf-reqid` (e.g.
  `66bd883c-4541-445f-ab10-c908025851e0`). No request-specific failure was found; the 500 body carries no cause.
* Conclusion: consistent with transient provider-side episodes. Not proven: the provider's internal cause is not
  observable from here. Provider and model choice unchanged; no fallback provider added.

## 8. Limitations and next steps

* Mathlib is not installed: real/complex statements are reported `not_formalizable`, never substituted.
* Statement correspondence is a deterministic screen (constants, True/False, assumed conclusion, domain); it cannot
  prove a formal statement faithful. The Lean statement is still shown for the reader to judge.
* Link destinations are not fetched to confirm they resolve (I39); browser-level DOM/clipboard/export checks for
  T43 were not run.
* T12, T13, T44 not run; I05, I13, I15, I16, I18–I22 remain as in round 1.
* Per-stage failure injection for planner, formalizer, critic and retrieval was not added (only writer and all-model
  failure).
* Recovery note: no data migration was performed; no stored conversations were touched.
