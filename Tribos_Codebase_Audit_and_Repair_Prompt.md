# Tribos: evaluation report and one-issue-at-a-time repair prompts

Updated: **27 October 2026 (Asia/Dhaka)**. The evaluation is closed: **10 runs in the latest round**, plus the preserved **26-run historical evaluation**. This file contains **21 separately copyable repair prompts** and retains the historical **43 issue reports and 45 regression groups**. The tickets overlap those historical reports; these numbers must not be added as if they were all distinct defects.

**Evidence boundary:** supplied responses, original screenshots/PDFs, traces and the earlier repair summary were examined. The current repository, backend logs, actual tool payloads and stored memory records were not supplied. No application code was edited and no tests were run against Tribos in preparing this report. Proposed code causes remain hypotheses until the implementing agent reproduces them.

**How to use this file**

1. Attach the current repository/source ZIP and this whole Markdown report to your coding agent.
2. Start with **F01**. Copy the entire fenced prompt for that issue from Section 3.
3. Let the agent reproduce, inspect the actual code, implement a general repair and validate it. Review its issue-level result before selecting F02, then continue in order.
4. Reuse the same branch/checkpoint where practical. Preserve earlier passing fixes and rerun affected regressions. Stop after the selected ticket; do not launch all 21 at once.
5. For historical/audit/regression tickets, reproduce first. Record already fixed, not reproduced or blocked honestly instead of manufacturing a patch.

There are no further manual evaluation queries in this round. Regression prompts below are implementation acceptance cases, not requests for another user-run evaluation.

The user wants substantive attempts at difficult/open mathematics: worked arguments, useful lemmas, targeted computations, checks, repairs and exact remaining gaps. Research and formal checking can help when appropriate and permitted. A status-only answer is insufficient for an explicit investigation request; an actual breakthrough is not the pass criterion. Ask for checkable mathematical derivations and evidence, not hidden chain-of-thought.

## 1. Reusable instruction for the selected issue

Use a complete issue prompt in Section 3 whenever possible. This controller is for continuing the sequence with the attached report:

~~~text
Work on F01 only from the attached Tribos evaluation report.

Read the repository's instructions and the selected issue's full brief. Inspect the actual production path and relevant neighboring code. Reproduce the issue with sanitized request/tool/check records, establish the real source files and cause, then implement a general fix. Do not stop at an audit or plan, hardcode the example, weaken checking, or merely hide its warning.

Preserve unrelated changes, user data, model/provider choices and the report's passing controls. Run the selected acceptance cases, held-out variants and the repository's affected checks using its actual documented commands. Distinguish app tests, replay/fault-injection tests and live-provider execution.

For older failures, first determine whether the current code still reproduces them. If a dependency on another ticket is necessary, explain it and make only the bounded shared change needed for this issue. Do not silently expand into every other ticket.

Return the issue ID/status, reproduced evidence, actual root cause and files/symbols, implemented change, exact validation commands/results, before/after behavior and remaining limitations. Provide the reviewable patch/commit or updated source ZIP as the environment permits. Do not deploy or destructively migrate real user data.

Stop after this issue's result is concrete and reviewable. Do not automatically start the next ticket.
~~~

Change F01 to the next selected ID when proceeding. A selected prompt below already includes its own ID, issue report, fix requirements and acceptance checks.

## 2. Latest evaluation: results and interpretation

### 2.1 Final run: 73/100

The final three answer lines correctly compute **3, 7, 13**, obey the requested format, and make no search/formal-proof attempts. However, the mathematics agent returns **no solutions**, then displays **Verified**, **Equations match the problem**, and a successful re-derived zero-solution count.

The request contains three independent calculations, not one simultaneous constraint system. Agreement about an irrelevant or mistranslated system does not verify the original task. Flattening the assignments into one inconsistent system is consistent with the symptom; the exact payload must establish the actual code cause.

| Category | Score |
| --- | ---: |
| Mathematical correctness of final answer | 40/40 |
| Instruction following | 20/20 |
| Verification/status consistency | 0/25 |
| Routing/efficiency | 13/15 |
| Total for this run | 73/100 |

These are diagnostic judgments for individual runs, not calibrated benchmarks, probabilities, release thresholds or a single overall app score. The consistent trust rule is zero verification credit for false certification of an invalid domain or wrong task. Correct final prose retains its mathematical credit.

### 2.2 Latest run register

The normalized requests in Section 4 preserve the mathematics and requested contract; original captures remain authoritative for byte-for-byte wording. All captures show Auto/Ultra with Search available/on; explicit per-request prohibitions still apply. A requested manual-Direct comparison in S02 was not demonstrated by the capture.

| ID | Task | Score | Components: math / instructions / verification / routing | Main outcome |
| --- | --- | ---: | --- | --- |

| S01 | Restricted-domain function evaluation | 43 | 20 / 20 / 0 / 3 | Returns 5,5,7,17 and falsely passes the domain check. The visible delegated task omits the domain. This is an investigation lead, not proof of the source-code cause. Two simplifications returning 5 do not prove cache contamination: r(1)=r(2)=5 under unrestricted substitution. |

| S02 | Same domain query, second run | 43 | 20 / 20 / 0 / 3 | Repeats wrong out-of-domain evaluations and false Domain Pass. axiom_simplify raises AttributeError: 'tuple' object has no attribute 'free_symbols'. Structured rules are unverified, then an LLM result is verified; all four claims receive supported labels. A requested manual-Direct comparison is not established: the capture shows Auto. |

| S03 | Rational identity with excluded point | 98 | 40 / 20 / 25 / 13 | Correct set and proof; explicit independent re-derivation of the infinite set by identity and excluded point. No contradictory no-solutions text. No research or completion error. |

| S04 | Rational equation with excluded candidate | 96 | 40 / 20 / 24 / 12 | Correct empty set and proof; zero-root check. Separate statement-check layer says 0/1 and none decidable; that is a scope-label issue, not a false mathematical answer. No research or completion error. |

| S05 | Polynomial symmetry, roots and RH limitation | 89 | 40 / 20 / 18 / 11 | Complete correct worked proof, including the geometric refinement. Plan nevertheless says 0/4 backed and all open. Claim parser extracts headings/free-variable fragments and malformed LaTeX; benchmark statistic is copied into prose then marked unsupported. Literal ### and a malformed P=P=0 expression appear. Lean not run and non-verification disclosed. |

| S06 | Worked Collatz descent investigation | 75 | 40 / 20 / 10 / 5 | All four final mathematical tasks correct. Checker falsely contradicts k=3,k=6 using k=1, and i=0,1,2 by reading i as imaginary unit. Number-theory strategy reports inconsistent congruences; exact inputs unavailable. Formalization fails with syntax/unknown-tactic errors and a sorry warning, accurately disclosed. Searches and two repair rounds show 0% textual change; this alone does not establish whether provenance changed. Plan counts retrieval as backing; coverage misses visible algebra. |

| S07 | Local bindings plus integer-index inequality | 61 | 40 / 14 / 0 / 7 | Final mathematics correct and rejects invalid witness i=-1/7. Tool nonetheless says False at i=-1/7, a=b=5/7, plus 1=1 and 2=2, and retains Verified/Domain Pass/Coverage Pass. Checker again uses k=1 for other cases and i as imaginary unit; nine contradicted fragments include these false checks and the invalid witness. Lean runs three times despite prohibition. Extra summary/verification prose violates exact body contract. Plan 0/4; requested algebra/checks labelled missing; boxed token unsupported. |

| S08 | Two inequality domains using m | 95 | 40 / 20 / 20 / 15 | Correct two-item answer; no search or formal attempt. Plan incorrectly 0/2/open despite tool result for question 2. Reader labels 5m and 2m as LENGTH quantities. Lean skip reason reports capability rather than user prohibition. Does not clear structured-tool domain bug. |

| S09 | Same inequality domains using i | 96 | 40 / 20 / 21 / 15 | Correct answer and restrictions respected. No imaginary-unit error on this path; does not test explicit i=0,1,2 binding extraction. Plan still 0/2/open; one extracted claim supported is not equivalent to two questions independently checked. Lean skip label remains capability-based. |

| S10 | Three independent k calculations | 73 | 40 / 20 / 0 / 13 | Final three lines correct and restrictions respected. Solver returns no solutions, then Equations match/zero-solutions-rederived/Verified pass for a task that requested three independent evaluations. Consistent with cases being flattened into one inconsistent system; exact payload must establish that cause. No false claim-level contradictions are shown here; the earlier checker symptom is not universally reproduced. |

### 2.3 Confirmed failures, passing controls and limits

**Trust-critical current failures**

- Original domains are lost or ignored, and invalid evaluations/witnesses receive Domain Pass: S01/S02/S07.
- Independent assignments leak or appear as a single system; S10 verifies a no-solutions result for an evaluation task.
- The claim checker reads a declared integer index i as the imaginary unit in S06/S07.
- A corrected final answer can coexist with stale verified evidence and copied assertions that checks passed.

**Other current issues**

- Symbolic tuple handling can fail with free_symbols AttributeError.
- An explicit no-formal-prover restriction is ignored in S07.
- Mathematical claim extraction loses definitions, quantifiers, scopes and presentation syntax.
- Requested-item coverage and plan state disagree with visible completed work.
- Benchmark provenance, ambiguous unit extraction, optional-checker reasons, formatting and unnecessary orchestration need repair or clearer scope.

**Improvements to preserve**

- S03 independently checks the infinite rational solution set R minus {4}; S04 correctly returns the empty set for the excluded candidate.
- S05 provides a complete worked polynomial proof and the correct half-turn/mirror distinction.
- S06 supplies correct descent lemmas, exact counterexample trajectories and the strong-induction gap. The evaluator independently recomputed the examples 3,19,35; this was an oracle check, not execution of Tribos tests.
- S08/S09 produce correct two-domain proofs/solution sets with no research/formal attempts. The inequality engine handles i correctly there.
- S10's final body is exactly the three correct requested lines. Its false certification is a separate failure.
- No completion HTTP 500 is visible in S01-S10. Optional formal failures are disclosed rather than claimed as accepted proofs.
- Historical benchmark scope and non-probability labels are meaningful distinctions; retain them.

**Do not overinterpret the captures**

- Passing S09 does not repair S06/S07's explicit i-assignment checks. Passing one engine does not establish that another engine preserves assumptions.
- A retrieved article or tool ok flag is not automatically a proof certificate.
- Different timing scopes can legitimately differ; 0.0s is rounded display. Token counts are labelled estimates and logical tool rows do not establish actual network requests.
- Two repair rounds reporting 0% text change do not by themselves prove that source mappings/checks were unchanged. Inspect those events before calling the repairs no-ops.
- Source titles, missing Mathlib, compiler failure, a storage warning and a memory-write count each have limited evidential scope.
- The current full sustained RH-investigation path, manual workflow override, actual clipboard/export links, durable history and provider-error root cause remain unverified.

### 2.4 Ordered repair queue

Use one prompt at a time. F01-F14 address current failures or current capability/reporting defects. F15-F18 include older regressions to reproduce, F19-F20 are explicit storage/trust audits, and F21 preserves passing solution-set work while checking broader regressions.

| Order | Issue | Priority | Evidence status | Earlier issue links |
| --- | --- | --- | --- | --- |

| F01 | Preserve domains and validate every counterexample | P0 | Confirmed current failure | I08, I24 |

| F02 | Isolate independent cases and local variable bindings | P0 | Confirmed current failure; exact flattening cause to establish | I09 |

| F03 | Honor declared symbols instead of reserved imaginary constants | P1 | Confirmed path-dependent failure | I08, I13 |

| F04 | Verify correspondence to the original task before certifying results | P0 | Confirmed current false certification | I07, I10, I11 |

| F05 | Normalize symbolic payload shapes and contain tuple failures | P1 | Confirmed runtime failure; exact input unknown | I25, I34 |

| F06 | Enforce explicit prohibitions through every orchestration phase | P1 | Confirmed violation with passing controls | I01, I29, I34 |

| F07 | Parse mathematical claims with their definitions, assumptions and markup | P1 | Confirmed current verification gaps and false fragments | I12, I13, I30 |

| F08 | Make requested-item coverage and task status agree with actual work | P1 | Confirmed current UI/state inconsistency | I14, I39, I42 |

| F09 | Invalidate stale verification after revisions and contradictory evidence | P0 | Confirmed current stale/contradictory certification | I13, I40, I42 |

| F10 | Ground benchmark metadata and keep it separate from current-answer verification | P2 | Confirmed current provenance/reporting issue | I19, I42 |

| F11 | Distinguish declared variables from physical units | P2 | Confirmed current interpretation metadata error | I03, I12 |

| F12 | Make formalization semantically relevant, executable and honestly scoped | P1 | Current compilation failures; historical wrong-target regression | I23, I33 |

| F13 | Route self-contained work efficiently and terminate unproductive repair loops | P1 | Confirmed avoidable-work examples; timings require scoped comparison | I04, I05, I22, I37, I38 |

| F14 | Preserve exact answer contracts and render mathematics cleanly | P1 | Current failure with successful formatting controls | I17, I18, I27 |

| F15 | Interpret task intent, negation and clarification requirements consistently | P1 | Historical failures; recheck before changing current behavior | I01, I02, I03, I35, I36 |

| F16 | Diagnose completion failures and return truthful, correctly formatted fallbacks | P1 | Historical operational failures; not reproduced in latest ten runs | I26, I27, I28, I43 |

| F17 | Align planner schemas, capabilities and tool registry | P1 | Historical schema/registry failures; recheck affected paths | I25, I34 |

| F18 | Preserve research relevance, factual scope and claim-to-source provenance | P1 | Historical source defects plus unnecessary current retrieval | I06, I15, I16, I38, I41 |

| F19 | Audit memory writes and prevent unverified results becoming trusted knowledge | P1 audit | Audit target; stored content and downstream effects uninspected | I21 |

| F20 | Protect saved conversations under quota and write failures | P1 audit | Historical warning; actual durability needs verification | I20 |

| F21 | Preserve solution-set kinds and independent checks across broader regressions | P2 regression | Latest rational controls pass; broader historical failures not all rerun | I31, I32 |

## 3. Copy one complete repair prompt at a time

Each block is an executable instruction to the coding agent. The brief distinguishes observations from suspected causes. If current code already passes a historical reproduction, report that with evidence; do not create an unnecessary rewrite.

The common completion report is: **status; reproduction; real cause and files; change; tests/commands/results; before/after; remaining limits; reviewable patch/checkpoint**. A check that is unavailable is blocked or unsupported at its actual scope, not passed. A failed optional checker alone does not make otherwise correct mathematics false.

### F01. Preserve domains and validate every counterexample

~~~text
Fix F01 only: Preserve domains and validate every counterexample.
Priority: P0. Evidence status: Confirmed current failure. Related historical reports: I08, I24.

ISSUE BRIEF
Restricted r:{2,3,...}->R is evaluated at 1 and 0 and falsely receives Domain Pass. In S07 the structured agent refutes a statement about nonnegative integers using i=-1/7, yet passes its witness-domain check. The writer rejects the witness but the verified card survives.
Observed runs: S01 (run_97105ecab76a46dd; gofullpage-localhost-3000-2026-10-26-22_29_24.pdf); S02 (run_382806eaab614130; gofullpage-localhost-3000-2026-10-26-22_40_16.pdf); S07 (run_685dc1bfcdc94953; gofullpage-localhost-3000-2026-10-27-07_17_25.pdf).

REPRODUCTION
Use r(n)=n²-3n+7 on {2,3,...}; request r(1),r(2),r(0),r(5). Separately, for i in Z>=0, a(i)=16i+3,b(i)=9i+2, prove a(i)>b(i).

EXPECTED BEHAVIOR
Undefined,5,undefined,17 for r. The inequality is true because a-b=7i+1>=1. i=-1/7 is neither an integer nor nonnegative; it cannot refute this claim.

CODEBASE INVESTIGATION
Trace original domain/quantifiers through intent, delegation, tool arguments, symbol assumptions, witness generation, independent checking and the UI result object. The missing domain in S01's displayed delegated task is a lead; do not declare it the sole cause without actual payloads.
Read repository instructions, follow the actual production path and identify real files/symbols. The repository was not inspected for this report; do not present a proposed cause as established.

IMPLEMENT THE GENERAL REPAIR
1. Keep the original domain and side conditions attached to the mathematical task and each result; map them to the solver without silently broadening them.
2. Require witness membership and actual violation of the original predicate before accepting a counterexample. Arithmetic agreement alone cannot certify it.
3. Represent an undefined application as a correct handled result where appropriate. Distinguish input outside the function domain from an incomplete answer.
4. Make domain failure invalidate the overall verification and downstream trusted result; preserve the failed artifact as failed history.

ACCEPTANCE AND REGRESSION CHECKS
1. Restricted r oracle above, paired with an unrestricted integer-domain control giving 5,5,7,17.
2. The a>b claim on nonnegative integers; valid refutation over all integers using i=-1; invalid -1/7 witness rejected on the restricted domain.
3. Held-out finite sets, integer/rational/real domains, strict interval endpoints, denominator exclusions and conditional assumptions.
Run applicable existing checks with the repository's actual documented commands. Add held-out semantic variants; do not use only exact-string success mocks. Preserve passing behavior and unrelated user changes.

COMPLETION BAR
No original-domain mismatch or invalid witness can produce Domain Pass or overall Verified. Supply production-path before/after payloads and domain-specific tests.

Return status (fixed, already fixed, partial, not reproduced, or blocked), reproduced before/after evidence, real cause and changed files/symbols, exact commands/results and remaining limits. Distinguish replay/fault injection from live execution. Implement the fix if reproduced; do not stop at a plan. Preserve user history and model/provider choices. Do not deploy or destructively migrate real data. Stop after this issue; do not automatically start another ticket.
~~~

### F02. Isolate independent cases and local variable bindings

~~~text
Fix F02 only: Isolate independent cases and local variable bindings.
Priority: P0. Evidence status: Confirmed current failure; exact flattening cause to establish. Related historical reports: I09.

ISSUE BRIEF
S06/S07 check k=3 and k=6 with k bound to 1. The isolated final test S10 returns correct prose 3,7,13, while axiom_solve returns no solutions and falsely passes equation matching and solution-count checks.
Observed runs: S06 (run_cfc2ef7ba13b4ed3; gofullpage-localhost-3000-2026-10-27-07_08_23.pdf); S07 (run_685dc1bfcdc94953; gofullpage-localhost-3000-2026-10-27-07_17_25.pdf); S10 (run_72017b4ecc344a97; gofullpage-localhost-3000-2026-10-27-07_28_57.pdf).

REPRODUCTION
Three independent items: k=1, k=3, k=6; compute 2k+1 in each, with k local to its item. Contrast with an explicit simultaneous system k=1 and k=3.

EXPECTED BEHAVIOR
Independent results are 3,7,13, each checked with its own binding. The genuinely simultaneous system has no solution.

CODEBASE INVESTIGATION
Inspect decomposition boundaries, task/case IDs, local symbol tables, equation grouping, tool invocation, claim extraction, mutable state and cache keys. A single inconsistent system is a strong hypothesis for S10, not an observed raw payload.
Read repository instructions, follow the actual production path and identify real files/symbols. The repository was not inspected for this report; do not present a proposed cause as established.

IMPLEMENT THE GENERAL REPAIR
1. Give every independent case an explicit scope and preserve it through all downstream computations and checks.
2. Never merge separate assignments into a conjunction merely because they share a symbol name. Preserve genuine simultaneous systems.
3. Associate checks and cached results with run, case, expression, bindings, domain and definition revision.
4. Make checker diagnostics identify the local case and the substitutions actually used.

ACCEPTANCE AND REGRESSION CHECKS
1. The exact independent/simultaneous contrast above through the production request path.
2. Reverse item order; rename k; use repeated identical expressions with different values and function definitions.
3. Interleave and, where the application supports it, execute cases concurrently and in separate conversations. Confirm no cross-run or cache leakage.
Run applicable existing checks with the repository's actual documented commands. Add held-out semantic variants; do not use only exact-string success mocks. Preserve passing behavior and unrelated user changes.

COMPLETION BAR
All substitutions are scoped correctly; S10 never produces a no-solutions result for independent evaluations. Do not fix this by merely suppressing the contradictory card.

Return status (fixed, already fixed, partial, not reproduced, or blocked), reproduced before/after evidence, real cause and changed files/symbols, exact commands/results and remaining limits. Distinguish replay/fault injection from live execution. Implement the fix if reproduced; do not stop at a plan. Preserve user history and model/provider choices. Do not deploy or destructively migrate real data. Stop after this issue; do not automatically start another ticket.
~~~

### F03. Honor declared symbols instead of reserved imaginary constants

~~~text
Fix F03 only: Honor declared symbols instead of reserved imaginary constants.
Priority: P1. Evidence status: Confirmed path-dependent failure. Related historical reports: I08, I13.

ISSUE BRIEF
S06/S07 explicitly evaluate the nonnegative-integer index i as 0+1i and falsely contradict i=0,1,2. S09 correctly solves an inequality using i, so the defect is not universal across engines.
Observed runs: S06 (run_cfc2ef7ba13b4ed3; gofullpage-localhost-3000-2026-10-27-07_08_23.pdf); S07 (run_685dc1bfcdc94953; gofullpage-localhost-3000-2026-10-27-07_17_25.pdf); S09 (run_8e0b686635b448d6; gofullpage-localhost-3000-2026-10-27-07_25_09.pdf).

REPRODUCTION
Declare i a nonnegative integer; a(i)=16i+3,b(i)=9i+2. Prove a>b and evaluate at i=0,1,2. Repeat with j, and separately with i explicitly defined as the imaginary unit.

EXPECTED BEHAVIOR
Difference 7i+1>=1; checks (3,2),(19,11),(35,20). A declared local variable shadows conventional constant aliases. In the explicit imaginary-unit problem, i²=-1 remains supported.

CODEBASE INVESTIGATION
Trace symbol construction and name resolution separately in axiom_structured, axiom_inequality, expression normalization and claim verification. Check parser defaults and built-in name dictionaries without assuming a particular source library implementation.
Read repository instructions, follow the actual production path and identify real files/symbols. The repository was not inspected for this report; do not present a proposed cause as established.

IMPLEMENT THE GENERAL REPAIR
1. Build typed scoped symbols from declarations before parsing expressions; use one consistent identity in the solver and verifier.
2. Resolve reserved aliases only when the user's binding and mathematical context permit them.
3. Preserve local assignments and quantifiers when checking example rows; do not reinterpret index labels as universal equalities.
4. Keep actual complex arithmetic working; do not globally disable imaginary units or rename only this one example.

ACCEPTANCE AND REGRESSION CHECKS
1. i/j/other symbol variants with the same formulas and explicit assignments.
2. The successful S09 inequality control and genuine imaginary-unit calculations.
3. Mixed real/complex tasks with separate local scopes and repeated names.
Run applicable existing checks with the repository's actual documented commands. Add held-out semantic variants; do not use only exact-string success mocks. Preserve passing behavior and unrelated user changes.

COMPLETION BAR
No integer index is evaluated as the imaginary unit, and both positive and negative semantic controls pass across affected engines.

Return status (fixed, already fixed, partial, not reproduced, or blocked), reproduced before/after evidence, real cause and changed files/symbols, exact commands/results and remaining limits. Distinguish replay/fault injection from live execution. Implement the fix if reproduced; do not stop at a plan. Preserve user history and model/provider choices. Do not deploy or destructively migrate real data. Stop after this issue; do not automatically start another ticket.
~~~

### F04. Verify correspondence to the original task before certifying results

~~~text
Fix F04 only: Verify correspondence to the original task before certifying results.
Priority: P0. Evidence status: Confirmed current false certification. Related historical reports: I07, I10, I11.

ISSUE BRIEF
S10 labels no solutions as Verified for three independent arithmetic evaluations. S07's tool answer includes an invalid counterexample and trivial 1=1,2=2 while tool-match and coverage checks pass. Re-solving a mistranslated task does not validate the user's task.
Observed runs: S07 (run_685dc1bfcdc94953; gofullpage-localhost-3000-2026-10-27-07_17_25.pdf); S10 (run_72017b4ecc344a97; gofullpage-localhost-3000-2026-10-27-07_28_57.pdf).

REPRODUCTION
Use S10's independent calculations. At the integration boundary also provide a solver result for the simultaneous k=1,k=3,k=6 system and try to attach it to those calculations.

EXPECTED BEHAVIOR
The independent request requires case-wise values, not a solution set for a conjunction. The mismatched solver result must be rejected or labelled as irrelevant/interpretation failure.

CODEBASE INVESTIGATION
Inspect original-task representation, translation contracts, result kinds, equation/source matching, independent-check inputs, evidence association, terminal status and badges. Determine whether checks compare only a generated intermediate system to itself.
Read repository instructions, follow the actual production path and identify real files/symbols. The repository was not inspected for this report; do not present a proposed cause as established.

IMPLEMENT THE GENERAL REPAIR
1. Establish a semantic correspondence check that retains operation type, domains, definitions, branches, independent scopes and requested outputs.
2. Keep translation fidelity separate from execution success and local algebra correctness; an ok tool return is not sufficient.
3. Refuse overall Verified when correspondence is failed or unknown. Route to bounded repair or return an honestly unverified result.
4. Preserve valid transformed calculations by retaining a traceable mapping to the original problem, rather than rejecting all transformed expressions.

ACCEPTANCE AND REGRESSION CHECKS
1. Inject the S10 wrong-task result and the earlier scalar interpretation of a defined function application.
2. Positive controls for equivalent factorizations, substituted identities and correct case-wise results.
3. End-to-end checks that the final answer, evidence card and verification record all refer to the same task revision.
Run applicable existing checks with the repository's actual documented commands. Add held-out semantic variants; do not use only exact-string success mocks. Preserve passing behavior and unrelated user changes.

COMPLETION BAR
A wrong-problem certificate cannot receive an original-task Pass, even if two engines agree on the wrong intermediate problem.

Return status (fixed, already fixed, partial, not reproduced, or blocked), reproduced before/after evidence, real cause and changed files/symbols, exact commands/results and remaining limits. Distinguish replay/fault injection from live execution. Implement the fix if reproduced; do not stop at a plan. Preserve user history and model/provider choices. Do not deploy or destructively migrate real data. Stop after this issue; do not automatically start another ticket.
~~~

### F05. Normalize symbolic payload shapes and contain tuple failures

~~~text
Fix F05 only: Normalize symbolic payload shapes and contain tuple failures.
Priority: P1. Evidence status: Confirmed runtime failure; exact input unknown. Related historical reports: I25, I34.

ISSUE BRIEF
axiom_simplify raises AttributeError: 'tuple' object has no attribute 'free_symbols'. The capture does not expose the offending arguments or prove which layer introduced the tuple.
Observed runs: S02 (run_382806eaab614130; gofullpage-localhost-3000-2026-10-26-22_40_16.pdf).

REPRODUCTION
Replay the S02 restricted-domain r task through the current supervisor/simplification path and capture sanitized actual inputs, types and a stack trace.

EXPECTED BEHAVIOR
Supported scalar and structured inputs are processed according to their schema; unsupported shapes return a typed, recoverable failure. No raw attribute access failure or false Verified fallback.

CODEBASE INVESTIGATION
Locate schema validation, deserialization, expression construction, tuple/list handling, free-symbol discovery, batch returns and error normalization. Inspect the installed symbolic library version and actual supported payload forms.
Read repository instructions, follow the actual production path and identify real files/symbols. The repository was not inspected for this report; do not present a proposed cause as established.

IMPLEMENT THE GENERAL REPAIR
1. Define and enforce explicit accepted input/output shapes at the boundary; normalize supported containers before symbolic operations.
2. Apply scalar operations only to compatible scalar objects. Handle collections element-wise only when that matches the task semantics.
3. Return actionable typed errors for unsupported shapes; retain domain/case metadata during recovery.
4. Bound retries and prevent a later fallback from silently certifying the same unresolved interpretation.

ACCEPTANCE AND REGRESSION CHECKS
1. The exact observed failing payload once recovered; relevant scalar, tuple/list, nested and unsupported forms.
2. Check supported symbolic types without inventing an arbitrary universal type allowlist.
3. A fault-injection integration test proving correct recovery/status without a raw AttributeError or false pass.
Run applicable existing checks with the repository's actual documented commands. Add held-out semantic variants; do not use only exact-string success mocks. Preserve passing behavior and unrelated user changes.

COMPLETION BAR
Identify the actual source and fix it generally. If the payload cannot be recovered, report that limit and verify the boundary contract without inventing a cause.

Return status (fixed, already fixed, partial, not reproduced, or blocked), reproduced before/after evidence, real cause and changed files/symbols, exact commands/results and remaining limits. Distinguish replay/fault injection from live execution. Implement the fix if reproduced; do not stop at a plan. Preserve user history and model/provider choices. Do not deploy or destructively migrate real data. Stop after this issue; do not automatically start another ticket.
~~~

### F06. Enforce explicit prohibitions through every orchestration phase

~~~text
Fix F06 only: Enforce explicit prohibitions through every orchestration phase.
Priority: P1. Evidence status: Confirmed violation with passing controls. Related historical reports: I01, I29, I34.

ISSUE BRIEF
S07 runs Lean three times for 15 seconds despite an explicit ban on invoking a formal prover. S08-S10 make zero formal attempts and no web searches, which are positive controls to preserve.
Observed runs: S07 (run_685dc1bfcdc94953; gofullpage-localhost-3000-2026-10-27-07_17_25.pdf); S08 (run_9465302a2375466e; gofullpage-localhost-3000-2026-10-27-07_21_40.pdf); S09 (run_8e0b686635b448d6; gofullpage-localhost-3000-2026-10-27-07_25_09.pdf); S10 (run_72017b4ecc344a97; gofullpage-localhost-3000-2026-10-27-07_28_57.pdf).

REPRODUCTION
Request the S07 four-item task with 'Do not search the web or run a formal prover.' Exercise planner, direct workflow, critic, repair, retry and automatic verification branches.

EXPECTED BEHAVIOR
Zero prohibited tool executions or generation/repair attempts intended to invoke them. Explicit opt-in controls can still use supported tools.

CODEBASE INVESTIGATION
Find where output constraints, tool policy, UI Search state and user prohibitions enter the execution context; trace all dispatch paths and automatic post-answer checks.
Read repository instructions, follow the actual production path and identify real files/symbols. The repository was not inspected for this report; do not present a proposed cause as established.

IMPLEMENT THE GENERAL REPAIR
1. Represent explicit tool restrictions as an enforceable request policy and check it at dispatch, not just in prompt text.
2. Propagate it through follow-up searches, critic rounds, proof generation, repairs, retries and nested agents/workflows.
3. Use precise disabled-by-user state and suppress irrelevant capability warnings for prohibited tools.
4. Preserve precedence when a user later explicitly changes the restriction; do not make a ban permanent across unrelated requests.

ACCEPTANCE AND REGRESSION CHECKS
1. Search-on UI plus explicit no-search/no-formal prompt, across every affected workflow.
2. Positive controls enabling formal proof or research for an appropriate task.
3. Revoked restrictions, quoted prohibitions and conflicting UI/request settings under the documented precedence policy.
Run applicable existing checks with the repository's actual documented commands. Add held-out semantic variants; do not use only exact-string success mocks. Preserve passing behavior and unrelated user changes.

COMPLETION BAR
Prohibited execution counts are zero, the reason is correct, and allowed capabilities remain functional.

Return status (fixed, already fixed, partial, not reproduced, or blocked), reproduced before/after evidence, real cause and changed files/symbols, exact commands/results and remaining limits. Distinguish replay/fault injection from live execution. Implement the fix if reproduced; do not stop at a plan. Preserve user history and model/provider choices. Do not deploy or destructively migrate real data. Stop after this issue; do not automatically start another ticket.
~~~

### F07. Parse mathematical claims with their definitions, assumptions and markup

~~~text
Fix F07 only: Parse mathematical claims with their definitions, assumptions and markup.
Priority: P1. Evidence status: Confirmed current verification gaps and false fragments. Related historical reports: I12, I13, I30.

ISSUE BRIEF
Headings such as Re(z)=1/2 become isolated assertions; valid T expressions lose their definition; pmod/forall/boxed and aligned markup fail parsing; refuted propositions and example assignments become misleading claim fragments.
Observed runs: S05 (run_8393fc2b39324363; gofullpage-localhost-3000-2026-10-26-23_27_38.pdf); S06 (run_cfc2ef7ba13b4ed3; gofullpage-localhost-3000-2026-10-27-07_08_23.pdf); S07 (run_685dc1bfcdc94953; gofullpage-localhost-3000-2026-10-27-07_17_25.pdf); S09 (run_8e0b686635b448d6; gofullpage-localhost-3000-2026-10-27-07_25_09.pdf).

REPRODUCTION
Use S05's polynomial proof, S06's Collatz derivations, and S07's boxed arithmetic/examples. Include a heading naming a line, a quoted false assertion explicitly being refuted, and a genuine false calculation.

EXPECTED BEHAVIOR
Checkable mathematical assertions retain context. Headings, instructions and quoted hypotheses are typed appropriately. Unsupported syntax is unknown/unsupported, never a fabricated contradiction or proof.

CODEBASE INVESTIGATION
Trace Markdown/LaTeX normalization, AST construction, definition registration, quantifier binding, composition versus power, claim deduplication and revision/case association.
Read repository instructions, follow the actual production path and identify real files/symbols. The repository was not inspected for this report; do not present a proposed cause as established.

IMPLEMENT THE GENERAL REPAIR
1. Normalize supported presentation syntax before semantic parsing while preserving exact meaning.
2. Attach domain, quantifiers, branch assumptions, definitions and case identity to claims; handle symbolic variables with suitable checking rather than treating their presence as an error.
3. Distinguish assertions, assumptions, definitions, examples, refuted statements, headings and instructions.
4. Deduplicate repeated statements without collapsing different scopes. Preserve genuine negative findings and honest unsupported states.

ACCEPTANCE AND REGRESSION CHECKS
1. boxed numerals, pmod, forall/exists, aligned equations, Re, functions and iterates T^k(n).
2. Correct and incorrect calculations with identical formatting; headings and quoted false claims should not be asserted as facts.
3. Final-revision extraction and held-out symbol/notation variants. Keep S09's successful path working.
Run applicable existing checks with the repository's actual documented commands. Add held-out semantic variants; do not use only exact-string success mocks. Preserve passing behavior and unrelated user changes.

COMPLETION BAR
The checker processes the supported mathematical language with context and reports precise limits for the rest, without hiding real contradictions.

Return status (fixed, already fixed, partial, not reproduced, or blocked), reproduced before/after evidence, real cause and changed files/symbols, exact commands/results and remaining limits. Distinguish replay/fault injection from live execution. Implement the fix if reproduced; do not stop at a plan. Preserve user history and model/provider choices. Do not deploy or destructively migrate real data. Stop after this issue; do not automatically start another ticket.
~~~

### F08. Make requested-item coverage and task status agree with actual work

~~~text
Fix F08 only: Make requested-item coverage and task status agree with actual work.
Priority: P1. Evidence status: Confirmed current UI/state inconsistency. Related historical reports: I14, I39, I42.

ISSUE BRIEF
Plans say 0/4 or 0/2 backed and leave items open despite visible answers and relevant tool results. Another panel calls the visible algebra missing. S06 can instead mark every item tool-backed using retrieved discussion, without distinguishing that from checking a proof.
Observed runs: S05 (run_8393fc2b39324363; gofullpage-localhost-3000-2026-10-26-23_27_38.pdf); S06 (run_cfc2ef7ba13b4ed3; gofullpage-localhost-3000-2026-10-27-07_08_23.pdf); S07 (run_685dc1bfcdc94953; gofullpage-localhost-3000-2026-10-27-07_17_25.pdf); S08 (run_9465302a2375466e; gofullpage-localhost-3000-2026-10-27-07_21_40.pdf); S09 (run_8e0b686635b448d6; gofullpage-localhost-3000-2026-10-27-07_25_09.pdf).

REPRODUCTION
Use the two independent inequality-domain questions in S08/S09 and S05's four-part polynomial task. Inspect final answer, result mappings, requested-items panel and plan trace.

EXPECTED BEHAVIOR
Every genuine requested item has its own answer/attempt state and its actual evidence/check state. In S08/S09 at least the real-inequality result maps to question 2. A hand proof may be answered without independent machine verification.

CODEBASE INVESTIGATION
Inspect requested-item extraction, IDs, production event handling, direct-workflow completion updates, evidence-to-item mapping, revision IDs and frontend selectors.
Read repository instructions, follow the actual production path and identify real files/symbols. The repository was not inspected for this report; do not present a proposed cause as established.

IMPLEMENT THE GENERAL REPAIR
1. Use structured requested-item IDs instead of extracting arbitrary words such as 'then' or 'not covered' as deliverables.
2. Track answered, checked, supported by retrieval, failed and still-open states separately; derive all panels from consistent records.
3. Map direct-tool results back to their source items and distinguish retrieved context from verified derivations.
4. Judge operation completion correctly for disproofs, undefined inputs and partial open-problem investigations. A checker failure need not erase a complete answer.

ACCEPTANCE AND REGRESSION CHECKS
1. S05's four obligations and S08/S09's two obligations, with per-item assertions in integration/UI tests.
2. Correct answers with optional checking unavailable, actual missing sections, valid disproofs and invalid witnesses.
3. Rendering, reload and final-revision updates; no stale open or false all-backed state.
Run applicable existing checks with the repository's actual documented commands. Add held-out semantic variants; do not use only exact-string success mocks. Preserve passing behavior and unrelated user changes.

COMPLETION BAR
Counts, labels and per-item evidence agree across panels, with scopes that explain legitimate differences.

Return status (fixed, already fixed, partial, not reproduced, or blocked), reproduced before/after evidence, real cause and changed files/symbols, exact commands/results and remaining limits. Distinguish replay/fault injection from live execution. Implement the fix if reproduced; do not stop at a plan. Preserve user history and model/provider choices. Do not deploy or destructively migrate real data. Stop after this issue; do not automatically start another ticket.
~~~

### F09. Invalidate stale verification after revisions and contradictory evidence

~~~text
Fix F09 only: Invalidate stale verification after revisions and contradictory evidence.
Priority: P0. Evidence status: Confirmed current stale/contradictory certification. Related historical reports: I13, I40, I42.

ISSUE BRIEF
The S07 writer explicitly rejects i=-1/7 as out of domain, then repeats that independent domain checks passed. The tool card retains Verified and Domain Pass for the rejected counterexample.
Observed runs: S07 (run_685dc1bfcdc94953; gofullpage-localhost-3000-2026-10-27-07_17_25.pdf).

REPRODUCTION
Generate the S07 invalid-witness result, then revise the final answer to reject it. Also test a revision that changes a domain, numerical value, citation or requested output.

EXPECTED BEHAVIOR
The failed original artifact remains visible as failed historical evidence. It cannot certify the corrected final answer. Claims, checks, source mappings and terminal labels belong to the relevant revision.

CODEBASE INVESTIGATION
Inspect answer/evidence revision identifiers, dependency invalidation, aggregate status calculation, frontend caches, streaming completion and post-critic rewriting.
Read repository instructions, follow the actual production path and identify real files/symbols. The repository was not inspected for this report; do not present a proposed cause as established.

IMPLEMENT THE GENERAL REPAIR
1. Version mathematical tasks, tool results, claims and final answers; invalidate affected certifications when their premises or correspondence change.
2. Recompute aggregate status from the final revision and retain explicit links to historical failed attempts.
3. Do not copy generic verification prose into a corrected answer unless its checks actually apply.
4. Avoid redundant rechecking when a revision is proven irrelevant, but make dependency-based reuse explicit.

ACCEPTANCE AND REGRESSION CHECKS
1. The invalid-witness rejection sequence above; change only wording as a reuse control.
2. Revise a correct answer into an incorrect one and back; alter domains and case bindings.
3. Inspect final body, cards, counters, clipboard/export and restored conversation state.
Run applicable existing checks with the repository's actual documented commands. Add held-out semantic variants; do not use only exact-string success mocks. Preserve passing behavior and unrelated user changes.

COMPLETION BAR
No rejected witness or old claim remains a current verification basis; useful audit history is preserved.

Return status (fixed, already fixed, partial, not reproduced, or blocked), reproduced before/after evidence, real cause and changed files/symbols, exact commands/results and remaining limits. Distinguish replay/fault injection from live execution. Implement the fix if reproduced; do not stop at a plan. Preserve user history and model/provider choices. Do not deploy or destructively migrate real data. Stop after this issue; do not automatically start another ticket.
~~~

### F10. Ground benchmark metadata and keep it separate from current-answer verification

~~~text
Fix F10 only: Ground benchmark metadata and keep it separate from current-answer verification.
Priority: P2. Evidence status: Confirmed current provenance/reporting issue. Related historical reports: I19, I42.

ISSUE BRIEF
The answer repeats a historical 98% expression benchmark with n=43, then its own checker flags the same number as unsupported. The interface correctly says the statistic is historical and support scores are not probabilities; preserve those distinctions. The captures do not prove the benchmark is fabricated.
Observed runs: S05 (run_8393fc2b39324363; gofullpage-localhost-3000-2026-10-26-23_27_38.pdf); S07 (run_685dc1bfcdc94953; gofullpage-localhost-3000-2026-10-27-07_17_25.pdf).

REPRODUCTION
Render an answer with benchmark metadata enabled, both with and without an actual benchmark record available. Follow it through the claim checker.

EXPECTED BEHAVIOR
A historical metric has traceable dataset/version/measurement provenance and exact scope. It is neither current-answer confidence nor a substitute for verification; unavailable provenance is not silently invented.

CODEBASE INVESTIGATION
Locate benchmark configuration and records, badge rendering, automatic prose templates, internal-metadata claim extraction and evidence associations.
Read repository instructions, follow the actual production path and identify real files/symbols. The repository was not inspected for this report; do not present a proposed cause as established.

IMPLEMENT THE GENERAL REPAIR
1. Attach genuine available benchmark provenance or omit the unsupported quantitative assertion from generated prose.
2. Label measurement scope, sample size, version and limitations using real records; do not invent calibration properties.
3. Keep mathematical validity, formal proof, source support and historical expression accuracy separate.
4. Make unsupported-metadata handling truthful rather than disabling claim checking globally.

ACCEPTANCE AND REGRESSION CHECKS
1. Verified benchmark record, missing record and changed record; each has appropriate UI/prose behavior.
2. Ensure true incorrect mathematics cannot inherit confidence from the 98% badge.
3. Preserve explicit non-probability labels and avoid false warnings caused solely by absent literature for self-contained arithmetic.
Run applicable existing checks with the repository's actual documented commands. Add held-out semantic variants; do not use only exact-string success mocks. Preserve passing behavior and unrelated user changes.

COMPLETION BAR
The app no longer emits an unsupported metric and then contradicts itself about its provenance.

Return status (fixed, already fixed, partial, not reproduced, or blocked), reproduced before/after evidence, real cause and changed files/symbols, exact commands/results and remaining limits. Distinguish replay/fault injection from live execution. Implement the fix if reproduced; do not stop at a plan. Preserve user history and model/provider choices. Do not deploy or destructively migrate real data. Stop after this issue; do not automatically start another ticket.
~~~

### F11. Distinguish declared variables from physical units

~~~text
Fix F11 only: Distinguish declared variables from physical units.
Priority: P2. Evidence status: Confirmed current interpretation metadata error. Related historical reports: I03, I12.

ISSUE BRIEF
The reader tags 5m and 2m as LENGTH quantities in a question explicitly declaring m a mathematical variable. The final mathematics is still correct and no physics analysis runs; do not exaggerate the observed impact.
Observed runs: S08 (run_9465302a2375466e; gofullpage-localhost-3000-2026-10-27-07_21_40.pdf).

REPRODUCTION
S08's inequality in variable m. Contrast with a genuine problem about lengths 5 m and 2 m, and with another declared symbol.

EXPECTED BEHAVIOR
Coefficients times a declared variable remain algebraic expressions. Genuine measurements retain units and dimensional checks.

CODEBASE INVESTIGATION
Inspect the quantity extractor, symbol declaration recognition, unit-token rules, intent metadata and downstream gating; determine whether the false metadata can affect actual computation.
Read repository instructions, follow the actual production path and identify real files/symbols. The repository was not inspected for this report; do not present a proposed cause as established.

IMPLEMENT THE GENERAL REPAIR
1. Resolve scoped declarations and context before assigning unit meaning to ambiguous tokens.
2. Retain an ambiguous state where context truly does not resolve the meaning; clarify only if needed for the task.
3. Preserve real unit handling and avoid a hardcoded exception that always treats m as a variable.
4. Align reader chips and downstream tool arguments with the resolved interpretation.

ACCEPTANCE AND REGRESSION CHECKS
1. Declared m with adjacency 5m/2m; equivalent spaced multiplication; genuine metre measurements.
2. Other ambiguous names/units and mixed algebra-plus-physical quantities.
3. Verify that metadata, routing and computation all use the same interpretation.
Run applicable existing checks with the repository's actual documented commands. Add held-out semantic variants; do not use only exact-string success mocks. Preserve passing behavior and unrelated user changes.

COMPLETION BAR
Reader metadata is correct for both algebra and physical measurements, with no regression to dimensional analysis.

Return status (fixed, already fixed, partial, not reproduced, or blocked), reproduced before/after evidence, real cause and changed files/symbols, exact commands/results and remaining limits. Distinguish replay/fault injection from live execution. Implement the fix if reproduced; do not stop at a plan. Preserve user history and model/provider choices. Do not deploy or destructively migrate real data. Stop after this issue; do not automatically start another ticket.
~~~

### F12. Make formalization semantically relevant, executable and honestly scoped

~~~text
Fix F12 only: Make formalization semantically relevant, executable and honestly scoped.
Priority: P1. Evidence status: Current compilation failures; historical wrong-target regression. Related historical reports: I23, I33.

ISSUE BRIEF
S06 formalization fails with syntax errors, unknown tactics, remaining goals and a sorry warning. S07 has a Nat.mul_le_mul_right argument-type mismatch. Failures are disclosed; they are not proofs of false mathematics. Earlier P12 used the unrelated target 'theorem riemann_hypothesis : False'. S05's categorical claim that Lean cannot express rationals without Mathlib is too broad: current Lean has Init.Data.Rat.
Observed runs: S05 (run_8393fc2b39324363; gofullpage-localhost-3000-2026-10-26-23_27_38.pdf); S06 (run_cfc2ef7ba13b4ed3; gofullpage-localhost-3000-2026-10-27-07_08_23.pdf); S07 (run_685dc1bfcdc94953; gofullpage-localhost-3000-2026-10-27-07_17_25.pdf); S08 (run_9465302a2375466e; gofullpage-localhost-3000-2026-10-27-07_21_40.pdf); S09 (run_8e0b686635b448d6; gofullpage-localhost-3000-2026-10-27-07_25_09.pdf).

REPRODUCTION
When formal proof is permitted, formalize a supported arithmetic/Collatz lemma using the actual configured Lean environment. Separately inject unrelated True/False targets, changed domains and an assumed conclusion.

EXPECTED BEHAVIOR
The theorem and assumptions match the user claim; supported code compiles without proof holes. Unsupported libraries are a scoped capability state. User-prohibited formal work remains governed by F06.

CODEBASE INVESTIGATION
Inspect environment/version/import discovery, theorem construction, semantic comparison, temporary source files, compiler invocation, error locations, repair loop and acceptance criteria.
Read repository instructions, follow the actual production path and identify real files/symbols. The repository was not inspected for this report; do not present a proposed cause as established.

IMPLEMENT THE GENERAL REPAIR
1. Check capability and theorem correspondence before expensive proof generation; generate APIs/tactics valid for the installed environment.
2. Use compiler feedback with bounded repairs and cancellation. Reject sorry/admit and injected conclusion assumptions as proof of the requested result.
3. Do not blanket-ban normal trusted foundational axioms used by Lean/Mathlib.
4. State precisely what was checked and why something was skipped. Do not claim inability of the language from a missing project dependency.

ACCEPTANCE AND REGRESSION CHECKS
1. A compiling supported Nat/rational lemma with applicable dependencies, plus an unavailable-library case.
2. Wrong target/domain/assumption and proof-hole rejection; genuine compiler failures remain unverified.
3. No-formal policy controls; record actual compiler output and attempt counts.
Run applicable existing checks with the repository's actual documented commands. Add held-out semantic variants; do not use only exact-string success mocks. Preserve passing behavior and unrelated user changes.

COMPLETION BAR
Applicable accepted proofs are both semantically relevant and compiled; unsupported/failed attempts never certify the claim.

Return status (fixed, already fixed, partial, not reproduced, or blocked), reproduced before/after evidence, real cause and changed files/symbols, exact commands/results and remaining limits. Distinguish replay/fault injection from live execution. Implement the fix if reproduced; do not stop at a plan. Preserve user history and model/provider choices. Do not deploy or destructively migrate real data. Stop after this issue; do not automatically start another ticket.
~~~

### F13. Route self-contained work efficiently and terminate unproductive repair loops

~~~text
Fix F13 only: Route self-contained work efficiently and terminate unproductive repair loops.
Priority: P1. Evidence status: Confirmed avoidable-work examples; timings require scoped comparison. Related historical reports: I04, I05, I22, I37, I38.

ISSUE BRIEF
Four function evaluations go to Supervisor with eight model calls in S01/S02. The bounded Collatz task uses searches, 18 model calls and 86.7k estimated tokens, with failed formalization and repeated repair rounds. Successful Direct controls finish in seconds. Different outer/inner timer scopes are not by themselves bugs.
Observed runs: S01 (run_97105ecab76a46dd; gofullpage-localhost-3000-2026-10-26-22_29_24.pdf); S02 (run_382806eaab614130; gofullpage-localhost-3000-2026-10-26-22_40_16.pdf); S05 (run_8393fc2b39324363; gofullpage-localhost-3000-2026-10-26-23_27_38.pdf); S06 (run_cfc2ef7ba13b4ed3; gofullpage-localhost-3000-2026-10-27-07_08_23.pdf); S08 (run_9465302a2375466e; gofullpage-localhost-3000-2026-10-27-07_21_40.pdf); S09 (run_8e0b686635b448d6; gofullpage-localhost-3000-2026-10-27-07_25_09.pdf); S10 (run_72017b4ecc344a97; gofullpage-localhost-3000-2026-10-27-07_28_57.pdf).

REPRODUCTION
Profile restricted-domain evaluation, the bounded Collatz task, a status lookup, a legitimate research attempt and S08/S09's self-contained inequalities using comparable settings.

EXPECTED BEHAVIOR
Workflow and retrieval follow actual task needs. Serious research can use a substantial budget when it produces useful work. Small exact tasks avoid irrelevant literature, repeated identical work and unnecessary writer overhead.

CODEBASE INVESTIGATION
Inspect routing features, independent versus dependent subquestions, search gating, critic acceptance/termination, no-progress detection, model/SDK attempts, caching and phase timing definitions.
Read repository instructions, follow the actual production path and identify real files/symbols. The repository was not inspected for this report; do not present a proposed cause as established.

IMPLEMENT THE GENERAL REPAIR
1. Choose the smallest adequate supported workflow while retaining proof and research capabilities.
2. Search for specific external information needs rather than proof-themed keywords or quotas.
3. Terminate or change approach when no usable new evidence/check/argument is produced. Zero textual change alone is not failure if provenance genuinely improves; label that distinction.
4. Measure timings and call counts with event identities and explicit scopes, including retries and cancellation.

ACCEPTANCE AND REGRESSION CHECKS
1. Before/after comparable traces for small tasks and meaningful research; record model/provider/effort/cache conditions.
2. Search required/not-required controls; no-op and provenance-only repair rounds.
3. No invented universal latency targets or inference that a displayed 0.0s means actual zero time.
Run applicable existing checks with the repository's actual documented commands. Add held-out semantic variants; do not use only exact-string success mocks. Preserve passing behavior and unrelated user changes.

COMPLETION BAR
Show measured reductions in avoidable work, without replacing an explicit sustained investigation with a status-only response.

Return status (fixed, already fixed, partial, not reproduced, or blocked), reproduced before/after evidence, real cause and changed files/symbols, exact commands/results and remaining limits. Distinguish replay/fault injection from live execution. Implement the fix if reproduced; do not stop at a plan. Preserve user history and model/provider choices. Do not deploy or destructively migrate real data. Stop after this issue; do not automatically start another ticket.
~~~

### F14. Preserve exact answer contracts and render mathematics cleanly

~~~text
Fix F14 only: Preserve exact answer contracts and render mathematics cleanly.
Priority: P1. Evidence status: Current failure with successful formatting controls. Related historical reports: I17, I18, I27.

ISSUE BRIEF
S07 adds summary/verification prose outside four requested numbered items. S05 visibly retains literal ### markers and a malformed expression in the proof/check display. S03/S04/S08-S10 preserve the requested logical answer structure and must remain working.
Observed runs: S03 (run_e9a14f0c34d64ec3; gofullpage-localhost-3000-2026-10-26-22_50_41.pdf); S04 (run_2f55245b37a74b7e; gofullpage-localhost-3000-2026-10-26-22_59_38.pdf); S05 (run_8393fc2b39324363; gofullpage-localhost-3000-2026-10-26-23_27_38.pdf); S07 (run_685dc1bfcdc94953; gofullpage-localhost-3000-2026-10-27-07_17_25.pdf); S08 (run_9465302a2375466e; gofullpage-localhost-3000-2026-10-27-07_21_40.pdf); S09 (run_8e0b686635b448d6; gofullpage-localhost-3000-2026-10-27-07_25_09.pdf); S10 (run_72017b4ecc344a97; gofullpage-localhost-3000-2026-10-27-07_28_57.pdf).

REPRODUCTION
The S07 four-item contract; the polynomial proof using headings, aligned math and sets; exact two-line/three-line and set-only responses. Include a writer-failure fixture from the historical report.

EXPECTED BEHAVIOR
The final answer body obeys its explicit contract after every rewrite and fallback. Correct Markdown/math renders correctly in the UI, copying and exports. Visual wrapping is not counted as an extra logical line.

CODEBASE INVESTIGATION
Inspect output-contract representation, answer templates, critic rewrites, deterministic renderers, escaping/sanitization, Markdown/KaTeX boundaries, clipboard and export pipelines.
Read repository instructions, follow the actual production path and identify real files/symbols. The repository was not inspected for this report; do not present a proposed cause as established.

IMPLEMENT THE GENERAL REPAIR
1. Validate the final payload after all automatic additions; do not inject summaries, confidence or verification paragraphs forbidden by the contract.
2. Keep process/evidence UI separate from the constrained answer body where appropriate.
3. Repair escaping/rendering at the responsible layer without altering mathematical meaning.
4. Preserve requested notation and line boundaries in fallback paths and native exports.

ACCEPTANCE AND REGRESSION CHECKS
1. Exact logical-line/numbered-item/JSON contracts with unseen text and Unicode.
2. Headings, aligned math, boxed numbers, sets, inequalities and source links in UI/copy/export.
3. Healthy writer, failed writer and post-critic revision controls.
Run applicable existing checks with the repository's actual documented commands. Add held-out semantic variants; do not use only exact-string success mocks. Preserve passing behavior and unrelated user changes.

COMPLETION BAR
No template or revision bypasses the final output contract, and supported mathematical notation renders faithfully.

Return status (fixed, already fixed, partial, not reproduced, or blocked), reproduced before/after evidence, real cause and changed files/symbols, exact commands/results and remaining limits. Distinguish replay/fault injection from live execution. Implement the fix if reproduced; do not stop at a plan. Preserve user history and model/provider choices. Do not deploy or destructively migrate real data. Stop after this issue; do not automatically start another ticket.
~~~

### F15. Interpret task intent, negation and clarification requirements consistently

~~~text
Fix F15 only: Interpret task intent, negation and clarification requirements consistently.
Priority: P1. Evidence status: Historical failures; recheck before changing current behavior. Related historical reports: I01, I02, I03, I35, I36.

ISSUE BRIEF
These older intent failures are retained as regression obligations. The latest bounded proofs and Direct inequalities show useful improvements, but the precise earlier prompts were not rerun in this round.
Historical evidence: B1/R1: a Collatz proof request with negated simulation language becomes an ODE/initial-condition clarification. P13: a short status lookup becomes hypothesis generation. P14: removal of a 150-word limit is ignored and treated as a literature-absence claim.

REPRODUCTION
Replay the original Collatz-with-negated-simulation prompt, RH status lookup, removed-word-limit prompt and their positive simulation/conjecture-generation controls from historical T01/T02/T11/T33/T35.

EXPECTED BEHAVIOR
Proof, status lookup, hypothesis generation and numerical simulation remain distinct operations. Revoked constraints stay revoked. Ask for missing inputs only when genuinely required.

CODEBASE INVESTIGATION
Trace canonical intent, negation/quotation scope, output-constraint precedence, planner representation, selected workflow and clarification templates.
Read repository instructions, follow the actual production path and identify real files/symbols. The repository was not inspected for this report; do not present a proposed cause as established.

IMPLEMENT THE GENERAL REPAIR
1. Unify conflicting intent representations so downstream phases cannot reinterpret the task independently.
2. Honor negated or removed constraints without treating their text as an affirmative instruction or scientific assertion.
3. Use task-specific input requirements; avoid irrelevant initial-condition gates for a discrete proof.
4. Preserve legitimate clarifications and requested long mathematical investigations.

ACCEPTANCE AND REGRESSION CHECKS
1. Historical exact reproductions and held-out wording variants through actual entry points.
2. A fully specified simulation executes; an underspecified simulation asks a relevant question.
3. Explicit short lookup versus substantial investigation; positive and revoked output limits.
Run applicable existing checks with the repository's actual documented commands. Add held-out semantic variants; do not use only exact-string success mocks. Preserve passing behavior and unrelated user changes.

COMPLETION BAR
Reproduce first. If already fixed, document passing controls and preserve behavior instead of rewriting it unnecessarily.

Return status (fixed, already fixed, partial, not reproduced, or blocked), reproduced before/after evidence, real cause and changed files/symbols, exact commands/results and remaining limits. Distinguish replay/fault injection from live execution. Implement the fix if reproduced; do not stop at a plan. Preserve user history and model/provider choices. Do not deploy or destructively migrate real data. Stop after this issue; do not automatically start another ticket.
~~~

### F16. Diagnose completion failures and return truthful, correctly formatted fallbacks

~~~text
Fix F16 only: Diagnose completion failures and return truthful, correctly formatted fallbacks.
Priority: P1. Evidence status: Historical operational failures; not reproduced in latest ten runs. Related historical reports: I26, I27, I28, I43.

ISSUE BRIEF
No completion HTTP 500 is visible in S01-S10. That is a useful observation, not a demonstrated root-cause fix. Do not infer a provider outage or a particular application bug from the generic error.
Historical evidence: P05/P06/P11 show writer HTTP 500; P14 shows planning/formalization/drafting errors and prompt text echoed as computed results. Correct set-format output is lost on some fallbacks.

REPRODUCTION
Use healthy-provider and injected planner/writer/formalizer/stream failures separately. Replay the historical available-result and no-result cases.

EXPECTED BEHAVIOR
Available validated work survives failure in the requested format. No-result runs disclose what failed and what was not achieved; a copied prompt is never computed evidence.

CODEBASE INVESTIGATION
Inspect actual sanitized requests, provider/model/client versions, response/error IDs, streaming handling, SDK retries, application retries, timeouts, cancellation and fallback renderer.
Read repository instructions, follow the actual production path and identify real files/symbols. The repository was not inspected for this report; do not present a proposed cause as established.

IMPLEMENT THE GENERAL REPAIR
1. Establish the actual failure cause before changing provider settings; preserve the user's chosen provider/model.
2. Use bounded compatible recovery without multiplying SDK and application retry loops.
3. Render existing valid results deterministically where appropriate; otherwise give an honest incomplete/failed outcome.
4. Keep operational failure distinct from mathematical inability and from optional verification unavailability.

ACCEPTANCE AND REGRESSION CHECKS
1. Historical set/line-format cases with writer success and failure.
2. Transient/persistent failures, empty evidence, cancellation and stream interruption.
3. Record actual attempts and sanitized diagnostics; never fabricate live success if provider access is blocked.
Run applicable existing checks with the repository's actual documented commands. Add held-out semantic variants; do not use only exact-string success mocks. Preserve passing behavior and unrelated user changes.

COMPLETION BAR
Provide a reproduced diagnosis or a precise blocked status, plus validated recovery behavior. No prompt-as-results or false completed synthesis.

Return status (fixed, already fixed, partial, not reproduced, or blocked), reproduced before/after evidence, real cause and changed files/symbols, exact commands/results and remaining limits. Distinguish replay/fault injection from live execution. Implement the fix if reproduced; do not stop at a plan. Preserve user history and model/provider choices. Do not deploy or destructively migrate real data. Stop after this issue; do not automatically start another ticket.
~~~

### F17. Align planner schemas, capabilities and tool registry

~~~text
Fix F17 only: Align planner schemas, capabilities and tool registry.
Priority: P1. Evidence status: Historical schema/registry failures; recheck affected paths. Related historical reports: I25, I34.

ISSUE BRIEF
The latest tuple exception is handled in F05; this ticket concerns planner-to-tool contracts and capability agreement rather than that object's specific runtime type.
Historical evidence: P04 rejects definitions.0.parameter as missing. P12 rejects four planned web_search calls as unregistered; P13 later executes web searches successfully, so search is not universally broken.
Observed runs: S02 (run_382806eaab614130; gofullpage-localhost-3000-2026-10-26-22_40_16.pdf).

REPRODUCTION
Replay the missing-parameter and unregistered-name records against the actual current schemas. Include a disabled tool, a supported registered tool and a stale schema version.

EXPECTED BEHAVIOR
Planner proposals use current names and argument schemas and respect request policy. Missing fields receive bounded actionable repair rather than domain loss or invented success.

CODEBASE INVESTIGATION
Locate registry construction, schema generation/versioning, planner prompts, preflight validation, dispatch aliases, permission checks and tool-error repair.
Read repository instructions, follow the actual production path and identify real files/symbols. The repository was not inspected for this report; do not present a proposed cause as established.

IMPLEMENT THE GENERAL REPAIR
1. Expose the same current capability/schema view to planning, execution and recovery.
2. Validate proposed arguments before execution and preserve mathematical semantics while repairing syntax/fields.
3. Represent unavailable, prohibited, invalid and failed tools distinctly.
4. Do not silently substitute a different tool or provider in a way that changes the task or bypasses restrictions.

ACCEPTANCE AND REGRESSION CHECKS
1. Missing definitions.parameter, invalid/valid names and schema changes.
2. Search enabled/disabled, successful web-search control and bounded invalid-plan repair.
3. No duplicate execution during validation/retry and no verified result for an unexecuted proposal.
Run applicable existing checks with the repository's actual documented commands. Add held-out semantic variants; do not use only exact-string success mocks. Preserve passing behavior and unrelated user changes.

COMPLETION BAR
Actual current schemas are enforced consistently. Document already-working paths and reproduce failures before modifying them.

Return status (fixed, already fixed, partial, not reproduced, or blocked), reproduced before/after evidence, real cause and changed files/symbols, exact commands/results and remaining limits. Distinguish replay/fault injection from live execution. Implement the fix if reproduced; do not stop at a plan. Preserve user history and model/provider choices. Do not deploy or destructively migrate real data. Stop after this issue; do not automatically start another ticket.
~~~

### F18. Preserve research relevance, factual scope and claim-to-source provenance

~~~text
Fix F18 only: Preserve research relevance, factual scope and claim-to-source provenance.
Priority: P1. Evidence status: Historical source defects plus unnecessary current retrieval. Related historical reports: I06, I15, I16, I38, I41.

ISSUE BRIEF
Research is useful when it advances the requested mathematics. A keyword match, a proof-claiming title, a preprint label or retrieved text alone does not establish the validity of a theorem.
Historical evidence: Earlier captures retrieve US legal cases for arithmetic, overstate Tao's theorem, reverse the Collatz cycle, and lose source mappings after revision. P13 has a CMI-labelled source but the raster capture cannot establish the actual href.
Observed runs: S06 (run_cfc2ef7ba13b4ed3; gofullpage-localhost-3000-2026-10-27-07_08_23.pdf).

REPRODUCTION
Use historical T12/T13/T33/T40/T43, including an official status lookup, the precise Tao result, an irrelevant keyword match and a controlled claimed breakthrough.

EXPECTED BEHAVIOR
Relevant primary evidence supports the precise final claim and survives revisions. Correct cycle is 1->4->2->1; Tao's logarithmic-density almost-bounded-minimum theorem does not establish almost-all convergence to 1.

CODEBASE INVESTIGATION
Inspect query construction, entity sense, relevance filters, metadata versus passage content, acceptance-status claims, final source links, counter-evidence targeting and revision associations.
Read repository instructions, follow the actual production path and identify real files/symbols. The repository was not inspected for this report; do not present a proposed cause as established.

IMPLEMENT THE GENERAL REPAIR
1. Construct searches from actual external information needs and retain passage-level support and canonical URLs.
2. Distinguish mathematical argument validity from publication/preprint/acceptance status; neither automatically validates or invalidates a proof.
3. Check exact theorem hypotheses and limitations and mark inferences as such.
4. Preserve final-version claim-source links through rewriting, copying and export; inspect actual hrefs when available.

ACCEPTANCE AND REGRESSION CHECKS
1. Primary-source status/Tao controls and unrelated legal-case retrieval.
2. A proof-claiming source with a flawed argument, a source outage and genuinely supporting material.
3. Final-answer rewrite retaining support and rejecting orphan or irrelevant citations.
Run applicable existing checks with the repository's actual documented commands. Add held-out semantic variants; do not use only exact-string success mocks. Preserve passing behavior and unrelated user changes.

COMPLETION BAR
A reviewer can trace each external final claim to appropriate evidence. If the link target cannot be inspected, report that limitation rather than guessing.

Return status (fixed, already fixed, partial, not reproduced, or blocked), reproduced before/after evidence, real cause and changed files/symbols, exact commands/results and remaining limits. Distinguish replay/fault injection from live execution. Implement the fix if reproduced; do not stop at a plan. Preserve user history and model/provider choices. Do not deploy or destructively migrate real data. Stop after this issue; do not automatically start another ticket.
~~~

### F19. Audit memory writes and prevent unverified results becoming trusted knowledge

~~~text
Fix F19 only: Audit memory writes and prevent unverified results becoming trusted knowledge.
Priority: P1 audit. Evidence status: Audit target; stored content and downstream effects uninspected. Related historical reports: I21.

ISSUE BRIEF
The UI reports memory writes even in runs containing failed or wrong-task math results (17 nodes in S06, 15 in S07, 5 in S10). These counts do not establish that incorrect conclusions were stored or reused; inspect the actual memory schema/content before alleging contamination.
Observed runs: S06 (run_cfc2ef7ba13b4ed3; gofullpage-localhost-3000-2026-10-27-07_08_23.pdf); S07 (run_685dc1bfcdc94953; gofullpage-localhost-3000-2026-10-27-07_17_25.pdf); S10 (run_72017b4ecc344a97; gofullpage-localhost-3000-2026-10-27-07_28_57.pdf).

REPRODUCTION
In a test profile, run a failed-witness task and S10's wrong-task solver outcome, inspect the stored records, then ask a related fresh question.

EXPECTED BEHAVIOR
Errors may be retained as audit history, but unverified or rejected conclusions never silently become trusted mathematical facts. Case/run/domain/revision provenance survives retrieval.

CODEBASE INVESTIGATION
Inspect memory extractors, trust flags, write ordering, cache keys, retrieval filters, user versus assistant assertions, update/invalidation rules and cross-conversation reuse.
Read repository instructions, follow the actual production path and identify real files/symbols. The repository was not inspected for this report; do not present a proposed cause as established.

IMPLEMENT THE GENERAL REPAIR
1. Make stored epistemic status and provenance explicit; prevent automatic trust promotion from a tool ok flag, historical benchmark or correct-looking prose.
2. Separate user premises, conjectures, failed attempts and checked conclusions.
3. Invalidate superseded mathematical knowledge and retain useful failed-attempt history with truthful status.
4. Keep test data and cleanup isolated from the user's real saved conversations.

ACCEPTANCE AND REGRESSION CHECKS
1. Rejected witness, wrong-task result, valid checked lemma and later correction.
2. Fresh-conversation retrieval with changed definitions/domains and concurrent cases.
3. Record actual storage/retrieval evidence; a visible write count alone is insufficient.
Run applicable existing checks with the repository's actual documented commands. Add held-out semantic variants; do not use only exact-string success mocks. Preserve passing behavior and unrelated user changes.

COMPLETION BAR
Either demonstrate existing protection or implement the missing trust boundary; report findings without inventing stored contents.

Return status (fixed, already fixed, partial, not reproduced, or blocked), reproduced before/after evidence, real cause and changed files/symbols, exact commands/results and remaining limits. Distinguish replay/fault injection from live execution. Implement the fix if reproduced; do not stop at a plan. Preserve user history and model/provider choices. Do not deploy or destructively migrate real data. Stop after this issue; do not automatically start another ticket.
~~~

### F20. Protect saved conversations under quota and write failures

~~~text
Fix F20 only: Protect saved conversations under quota and write failures.
Priority: P1 audit. Evidence status: Historical warning; actual durability needs verification. Related historical reports: I20.

ISSUE BRIEF
No visible quota warning in the latest round establishes neither success nor failure of persistence. This ticket requires controlled storage/recovery tests, not a destructive experiment on real history.
Historical evidence: An early warning says old conversation text was removed. Later warnings say the new run was not saved. Those messages show changing disclosure, not proven permanent loss or proven durability.

REPRODUCTION
Use an isolated test profile with existing conversations. Inject quota exhaustion, interrupted writes, reloads, failed transactions and oversized reconstructible caches.

EXPECTED BEHAVIOR
Existing user history remains intact; failed new writes are explicit and recoverable where supported. Cache eviction does not silently delete canonical conversation text.

CODEBASE INVESTIGATION
Inspect local/server storage ownership, transactional writes, quota accounting, cache eviction, serialization, reload/recovery, export and migration code.
Read repository instructions, follow the actual production path and identify real files/symbols. The repository was not inspected for this report; do not present a proposed cause as established.

IMPLEMENT THE GENERAL REPAIR
1. Separate canonical user records from evictable derived caches and use atomic/recoverable persistence appropriate to the backend.
2. Detect failed writes and preserve the in-memory result or export/retry path honestly.
3. Avoid automatic destructive migrations or history trimming as an error-recovery shortcut.
4. Use reversible, documented migrations only where necessary.

ACCEPTANCE AND REGRESSION CHECKS
1. Quota/write/reload/export/recovery controls in isolated profiles.
2. Existing records before/after, partial new records and concurrent writes.
3. Ensure warnings describe actual persistence outcome rather than inferred loss.
Run applicable existing checks with the repository's actual documented commands. Add held-out semantic variants; do not use only exact-string success mocks. Preserve passing behavior and unrelated user changes.

COMPLETION BAR
Demonstrate integrity with actual stored records and recovery tests; do not claim permanent loss or durability based on UI wording alone.

Return status (fixed, already fixed, partial, not reproduced, or blocked), reproduced before/after evidence, real cause and changed files/symbols, exact commands/results and remaining limits. Distinguish replay/fault injection from live execution. Implement the fix if reproduced; do not stop at a plan. Preserve user history and model/provider choices. Do not deploy or destructively migrate real data. Stop after this issue; do not automatically start another ticket.
~~~

### F21. Preserve solution-set kinds and independent checks across broader regressions

~~~text
Fix F21 only: Preserve solution-set kinds and independent checks across broader regressions.
Priority: P2 regression. Evidence status: Latest rational controls pass; broader historical failures not all rerun. Related historical reports: I31, I32.

ISSUE BRIEF
S03 now correctly re-derives R\{4} using an identity and excluded point. S04 correctly returns the empty set for the excluded apparent root. Preserve these improvements; do not classify them as still failing or rebuild a working path without evidence.
Historical evidence: P09/P10 display no solutions alongside an infinite general set and lack an applicable independent set check.
Observed runs: S03 (run_e9a14f0c34d64ec3; gofullpage-localhost-3000-2026-10-26-22_50_41.pdf); S04 (run_2f55245b37a74b7e; gofullpage-localhost-3000-2026-10-26-22_59_38.pdf).

REPRODUCTION
Replay the rational pair from S03/S04 and historical T26-T31: real/complex x²+1=0, a polynomial identity, its inconsistent control, and sqrt(x+2)=x.

EXPECTED BEHAVIOR
Finite, empty, infinite, conditional and unresolved results remain distinct. An empty finite root list is not sufficient evidence that a general solution set is empty.

CODEBASE INVESTIGATION
Inspect result schemas, solver adapters, independent set verification, original-domain exclusions, branch handling, answer formatting and fallback behavior.
Read repository instructions, follow the actual production path and identify real files/symbols. The repository was not inspected for this report; do not present a proposed cause as established.

IMPLEMENT THE GENERAL REPAIR
1. If missing, preserve a typed result-kind contract through tools, checking and rendering.
2. Use applicable independent reasoning for identities/general sets and preserve denominator exclusions.
3. Distinguish sampled-point evidence from a rigorous completeness certificate; report the check's true scope.
4. Keep finite/empty controls, exact notation and successful infinite-set checks working.

ACCEPTANCE AND REGRESSION CHECKS
1. R\{4} and empty-set controls, plus held-out coefficients and exclusions.
2. All-real identity versus contradiction; real versus complex roots; extraneous square-root candidate.
3. Unknown/conditional solver output and writer-failure formatting.
Run applicable existing checks with the repository's actual documented commands. Add held-out semantic variants; do not use only exact-string success mocks. Preserve passing behavior and unrelated user changes.

COMPLETION BAR
Mark already fixed where current evidence and tests support it. Repair only remaining generalization or result-kind failures and retain honest unsupported states.

Return status (fixed, already fixed, partial, not reproduced, or blocked), reproduced before/after evidence, real cause and changed files/symbols, exact commands/results and remaining limits. Distinguish replay/fault injection from live execution. Implement the fix if reproduced; do not stop at a plan. Preserve user history and model/provider choices. Do not deploy or destructively migrate real data. Stop after this issue; do not automatically start another ticket.
~~~

## 4. Latest reproductions, oracles and evidence inventory

### 4.1 Reproduction records

These ten runs close this evaluation. Their prompts are implementation regression cases, not a request for further user-run queries. Source files are original attachments. The additional screenshots expose expanded panels; they are not additional independent runs.

#### S01: Restricted-domain function evaluation

**Run:** run_97105ecab76a46dd. **Date:** 2026-10-26 (Asia/Dhaka). **Score:** 43/100.

**Routing/accounting:** Auto -> Supervisor; 8 model calls; 4 tool calls; 12.1k estimated tokens. **Displayed timing:** Header 3m20s; supervisor 3m11s.

**Reproduction:** Let r have domain {2,3,4,...}, with r(n)=n²-3n+7. Evaluate r(1),r(2),r(0),r(5). Return exactly four lines in that order; add nothing else.

**Oracle:** r(1) undefined; r(2)=5; r(0) undefined; r(5)=17.

**Observed:** Returns 5,5,7,17 and falsely passes the domain check. The visible delegated task omits the domain. This is an investigation lead, not proof of the source-code cause. Two simplifications returning 5 do not prove cache contamination: r(1)=r(2)=5 under unrestricted substitution.

**Original supporting attachment(s):**

- gofullpage-localhost-3000-2026-10-26-22_29_24.pdf
- {B79CD8B8-06B0-46F1-A54C-933B7F7A4760}.png
- {091F1D47-75D8-4717-AAB0-66AF85B606EE}.png

#### S02: Same domain query, second run

**Run:** run_382806eaab614130. **Date:** 2026-10-26 (Asia/Dhaka). **Score:** 43/100.

**Routing/accounting:** Still Auto -> Supervisor; 8 model calls; 3 tool calls; 10.1k estimated tokens. **Displayed timing:** Header 1m10s; inner trace 1m7s; supervisor 55s.

**Reproduction:** Same restricted-domain r query as S01.

**Oracle:** Undefined,5,undefined,17, preserving the requested order.

**Observed:** Repeats wrong out-of-domain evaluations and false Domain Pass. axiom_simplify raises AttributeError: 'tuple' object has no attribute 'free_symbols'. Structured rules are unverified, then an LLM result is verified; all four claims receive supported labels. A requested manual-Direct comparison is not established: the capture shows Auto.

**Original supporting attachment(s):**

- gofullpage-localhost-3000-2026-10-26-22_40_16.pdf
- {1A33BD9D-166A-40A5-91D7-807CDDC473B1}.png

#### S03: Rational identity with excluded point

**Run:** run_e9a14f0c34d64ec3. **Date:** 2026-10-26 (Asia/Dhaka). **Score:** 98/100.

**Routing/accounting:** Auto -> Direct; one axiom_solve call; two model calls. **Displayed timing:** Header 11s; math 0.48s; drafting 6.3s.

**Reproduction:** Solve (x²-16)/(x-4)=x+4 over the reals. Exactly two lines: complete solution set, then rigorous one-sentence justification. Add nothing else.

**Oracle:** R\{4}; factor the numerator and preserve x!=4.

**Observed:** Correct set and proof; explicit independent re-derivation of the infinite set by identity and excluded point. No contradictory no-solutions text. No research or completion error.

**Original supporting attachment(s):**

- gofullpage-localhost-3000-2026-10-26-22_50_41.pdf

#### S04: Rational equation with excluded candidate

**Run:** run_2f55245b37a74b7e. **Date:** 2026-10-26 (Asia/Dhaka). **Score:** 96/100.

**Routing/accounting:** Auto -> Direct; one axiom_solve call; two model calls. **Displayed timing:** Header 22s; math 0.03s; drafting 18s.

**Reproduction:** Solve (x²-16)/(x-4)=8 over the reals. Exactly two lines: complete solution set, then rigorous one-sentence justification. Add nothing else.

**Oracle:** Empty set: the only simplified candidate is excluded x=4.

**Observed:** Correct empty set and proof; zero-root check. Separate statement-check layer says 0/1 and none decidable; that is a scope-label issue, not a false mathematical answer. No research or completion error.

**Original supporting attachment(s):**

- gofullpage-localhost-3000-2026-10-26-22_59_38.pdf

#### S05: Polynomial symmetry, roots and RH limitation

**Run:** run_8393fc2b39324363. **Date:** 2026-10-26 (Asia/Dhaka). **Score:** 89/100.

**Routing/accounting:** Auto -> Direct; one axiom_structured call; two model calls; 12.9k estimated tokens. **Displayed timing:** Header 1m37s; drafting 1m34s; structured math about 0.1s.

**Reproduction:** For P(z)=(z-1/3)(z-2/3), z complex: prove P(1-z)=P(z); find/check all zeros; decide whether symmetry forces zeros onto Re(z)=1/2; explain why this does not decide RH. Show derivations and separate proved conclusions from non-conclusions.

**Oracle:** P=z²-z+2/9; roots 1/3,2/3; symmetry alone insufficient; no RH conclusion. Distinguish half-turn z->1-z from true mirror z->1-conjugate(z).

**Observed:** Complete correct worked proof, including the geometric refinement. Plan nevertheless says 0/4 backed and all open. Claim parser extracts headings/free-variable fragments and malformed LaTeX; benchmark statistic is copied into prose then marked unsupported. Literal ### and a malformed P=P=0 expression appear. Lean not run and non-verification disclosed.

**Original supporting attachment(s):**

- gofullpage-localhost-3000-2026-10-26-23_27_38.pdf

#### S06: Worked Collatz descent investigation

**Run:** run_cfc2ef7ba13b4ed3. **Date:** 2026-10-27 (Asia/Dhaka). **Score:** 75/100.

**Routing/accounting:** Auto -> Plan & execute; 7 tool calls; 18 model calls; 86.7k estimated tokens. **Displayed timing:** Header 5m10s; trace 5m7s; formalization 1m47s; first draft 1m36s.

**Reproduction:** Standard positive-integer Collatz T. Prove three-step descent for n>1, n=1 mod4; prove/refute five-step descent for every n=3 mod4; prove another odd descent class with examples; state the exact strong-induction gap. Separate lemmas, refutation, gap; no literature needed; do not invent executed code.

**Oracle:** T³(n)=(3n+1)/4<n on 1 mod4. n=3 refutes five-step claim. n=16i+3 gives six steps ending 9i+2<n. Examples 3->2,19->11,35->20 after six steps. Universal first descent remains necessary.

**Observed:** All four final mathematical tasks correct. Checker falsely contradicts k=3,k=6 using k=1, and i=0,1,2 by reading i as imaginary unit. Number-theory strategy reports inconsistent congruences; exact inputs unavailable. Formalization fails with syntax/unknown-tactic errors and a sorry warning, accurately disclosed. Searches and two repair rounds show 0% textual change; this alone does not establish whether provenance changed. Plan counts retrieval as backing; coverage misses visible algebra.

**Original supporting attachment(s):**

- gofullpage-localhost-3000-2026-10-27-07_08_23.pdf
- {299F8A20-41B9-4AE1-A44F-533C496E2A83}.png
- {83C693B9-89BA-4E35-859D-C93CDD415782}.png
- {DE1A3B0D-5D87-442E-9A14-1E5B09BA18A3}.png
- {990F1F98-302B-4854-8BE1-CB23355A8C64}.png
- {6F578DBF-E89F-409E-A65D-D38DFD2B1141}.png
- {8A0E6C87-9115-402B-9535-BCC9C39CFA12}.png

#### S07: Local bindings plus integer-index inequality

**Run:** run_685dc1bfcdc94953. **Date:** 2026-10-27 (Asia/Dhaka). **Score:** 61/100.

**Routing/accounting:** Auto -> Direct; one axiom_structured call; six model calls; 19.8k estimated tokens. **Displayed timing:** Header 50s; trace 46s; formalization 15s; drafting 25s.

**Reproduction:** Four independent items: k=1,k=3,k=6, compute 2k+1 in each; for nonnegative integer i, a(i)=16i+3,b(i)=9i+2, prove a>b and check i=0,1,2. Exactly four numbered items; no web search or formal prover.

**Oracle:** 3,7,13. a-b=7i+1>=1; checks (3,2),(19,11),(35,20).

**Observed:** Final mathematics correct and rejects invalid witness i=-1/7. Tool nonetheless says False at i=-1/7, a=b=5/7, plus 1=1 and 2=2, and retains Verified/Domain Pass/Coverage Pass. Checker again uses k=1 for other cases and i as imaginary unit; nine contradicted fragments include these false checks and the invalid witness. Lean runs three times despite prohibition. Extra summary/verification prose violates exact body contract. Plan 0/4; requested algebra/checks labelled missing; boxed token unsupported.

**Original supporting attachment(s):**

- gofullpage-localhost-3000-2026-10-27-07_17_25.pdf
- {059BA1C4-BF44-4E04-9CB4-79AE5D70BD45}.png
- {05421E90-8489-4018-B001-E59B2FB2CC40}.png

#### S08: Two inequality domains using m

**Run:** run_9465302a2375466e. **Date:** 2026-10-27 (Asia/Dhaka). **Score:** 95/100.

**Routing/accounting:** Auto -> Direct; one axiom_inequality call; two model calls; 4.9k estimated tokens. **Displayed timing:** Header/trace 5.3s; math 0.7s; drafting 2.9s.

**Reproduction:** Two independent domains: prove/disprove 5m+4>2m+1 for every nonnegative integer m, requiring any witness in-domain; solve same inequality over reals. Exactly two numbered items with algebra, nothing else; no search or formal prover.

**Oracle:** True on nonnegative integers because difference 3(m+1)>=3; real set (-1,infinity).

**Observed:** Correct two-item answer; no search or formal attempt. Plan incorrectly 0/2/open despite tool result for question 2. Reader labels 5m and 2m as LENGTH quantities. Lean skip reason reports capability rather than user prohibition. Does not clear structured-tool domain bug.

**Original supporting attachment(s):**

- gofullpage-localhost-3000-2026-10-27-07_21_40.pdf
- {3DE7DBF9-0903-4EFD-8435-60474AC51396}.png

#### S09: Same inequality domains using i

**Run:** run_8e0b686635b448d6. **Date:** 2026-10-27 (Asia/Dhaka). **Score:** 96/100.

**Routing/accounting:** Auto -> Direct; one axiom_inequality call; two model calls; 4.8k estimated tokens. **Displayed timing:** Header 12s; inner trace 8.3s; math 0.6s; drafting 6.6s.

**Reproduction:** Identical to S08, changing only variable m to i.

**Oracle:** Same proof and (-1,infinity), with i a declared real/integer variable in its respective item.

**Observed:** Correct answer and restrictions respected. No imaginary-unit error on this path; does not test explicit i=0,1,2 binding extraction. Plan still 0/2/open; one extracted claim supported is not equivalent to two questions independently checked. Lean skip label remains capability-based.

**Original supporting attachment(s):**

- gofullpage-localhost-3000-2026-10-27-07_25_09.pdf

#### S10: Three independent k calculations

**Run:** run_72017b4ecc344a97. **Date:** 2026-10-27 (Asia/Dhaka). **Score:** 73/100.

**Routing/accounting:** Auto -> Direct; one axiom_solve call; two model calls; 3.9k estimated tokens. **Displayed timing:** Header 8.3s; inner trace 6.3s; math 0.1s; drafting 5.5s.

**Reproduction:** Three independent calculations, k local to each: k=1,k=3,k=6, evaluate 2k+1. Exactly three numbered lines with substitution/result; nothing else; no search or formal prover.

**Oracle:** 2(1)+1=3; 2(3)+1=7; 2(6)+1=13, one item per line.

**Observed:** Final three lines correct and restrictions respected. Solver returns no solutions, then Equations match/zero-solutions-rederived/Verified pass for a task that requested three independent evaluations. Consistent with cases being flattened into one inconsistent system; exact payload must establish that cause. No false claim-level contradictions are shown here; the earlier checker symptom is not universally reproduced.

**Original supporting attachment(s):**

- gofullpage-localhost-3000-2026-10-27-07_28_57.pdf

### 4.2 Mathematical oracle details

- Restricted function: r(n)=n²-3n+7 on {2,3,...}. Inputs 1 and 0 are undefined even though unrestricted substitution yields 5 and 7.
- Counterexample validation: for a(i)=16i+3,b(i)=9i+2, a-b=7i+1>0 on nonnegative integers. i=-1/7 gives equality 5/7=5/7 but is outside that domain. Over all integers i=-1 is a valid counterexample to the universal inequality.
- Independent k calculations: 2(1)+1=3, 2(3)+1=7, 2(6)+1=13. A deliberately simultaneous k=1 and k=3 system has no solution; that negative control must not be conflated with independent cases.
- Two inequality domains: 5v+4>2v+1 iff v>-1 over the reals; all nonnegative integers satisfy it because 3(v+1)>=3. The oracle is unchanged if v is named m or i.
- Rational identity: (x²-16)/(x-4)=x+4 for all real x except 4. Equating it to 8 instead gives only the excluded candidate 4, hence the empty set.
- Polynomial: P(z)=z²-z+2/9, P(1-z)=P(z), roots exactly 1/3 and 2/3. The map z->1-z is a half-turn, not the mirror map z->1-conjugate(z). Real coefficients preserve conjugate zeros; the example has mirror symmetry but off-line roots. No conclusion about the zeta zeros follows from this polynomial alone.
- Collatz on positive integers: n>1, n=1 mod4 gives n -> 3n+1 -> (3n+1)/2 -> (3n+1)/4 < n.
- The five-step assertion fails at n=3: 3,10,5,16,8,4,2,1. The first value below 3 is at step 6.
- For n=16j+3, j>=0, six steps are 48j+10,24j+5,72j+16,36j+8,18j+4,9j+2. Their parity justifies every branch; 9j+2<16j+3. Checks: 3->10->5->16->8->4->2; 19->58->29->88->44->22->11; 35->106->53->160->80->40->20.
- Strong induction still requires first descent for every starting n>1. The displayed lemmas cover even numbers, 1 mod4 and 3 mod16; 7,11,15 mod16 remain uncovered by those lemmas. This is a partial investigation, not a proof of Collatz.

The ordinary inequality card explicitly says its independent check samples points. That is a useful scoped check, not by itself a universal completeness proof. The exact algebra above supplies the simple oracle.

### 4.3 Additional primary reference

[Lean Init.Data.Rat.Basic](https://lean-lang.org/doc/api/Init/Data/Rat/Basic.html) documents the Rat structure in Lean's Init library. It supports correcting a blanket claim that rational numbers cannot be expressed without Mathlib. It does not establish the installed version or capabilities of the user's environment.

### 4.4 Implementation handoff checklist

For each selected F-ticket, record:

| Field | Required result |
| --- | --- |
| Status | Fixed; already fixed with evidence; partial; not reproduced; blocked with reason |
| Reproduction | Input, actual settings, original semantic task, tool/check records and observed result |
| Cause | Actual source file/symbol and demonstrated mechanism, with hypotheses labelled |
| Change | General implementation and affected neighboring behavior |
| Verification | Applicable tests, exact commands/results, held-out controls and any live limits |
| Review | Before/after, patch/checkpoint, remaining risks and limitations |

A ticket is not fixed by hiding its warning, marking everything Verified, weakening a domain, dropping hard claims, disabling useful mathematical work, or training on only the exact example. Conversely, preserve working behavior and do not force speculative changes for an uninspected historical concern.

## 5. Preserved historical report

This appendix retains the earlier 26-run evidence, 43 issue reports and 45 regression groups. It supplies the detailed older reproductions needed by F15-F21 and the cross-cutting tickets. Historical failures are not automatically assertions about the current build.

The earlier bulk implementation plan is reference material. The active work instruction is to complete **one selected F-ticket at a time**. Internal historical section references are prefixed H below.

### H2. What the accumulated evidence establishes

#### H2.1 Highest priorities

| Priority | Evidence-backed problem | Required outcome |
| --- | --- | --- |
| P0 | Out-of-domain function evaluations are numerically computed and falsely certified as domain-valid: P03/P04. | Correctly reject invalid inputs and prevent a green verification of a different problem. |
| P0 | Lean is given `theorem riemann_hypothesis : False`: P12. | Check semantic correspondence before presenting a formal attempt as relevant to the requested theorem. |
| P1 | Completion failures affect drafting and, in P14, planning/formalization; fallback echoes instructions as “results.” | Diagnose the actual API/client fault, recover within budget, and report precisely what was accomplished. |
| P1 | Explicit removal of a 150-word cap is ignored; the instruction is then treated as a literature-wide absence claim: P14. | Correct instruction interpretation, constraint replacement, and typed claim extraction. |
| P1 | Infinite solution sets are accompanied by “no solutions,” with verification limited to equation matching: P09/P10. | Preserve solution-set semantics and verify applicable set identities/domains. |
| P1 | Existing-hypothesis status lookup is misrouted into hypothesis generation/Debate: B2, P12, P13. | Distinguish lookup, proof request, conjecture generation, and serious investigation. |
| P1 | Search planning, source association, final revision checks, and coverage disagree. | Maintain final-version provenance and truthful tool/claim/result state. |
| P2 | Timers and badges lack clear scope; simple validated outputs can still wait on a writer. | Explain accounting boundaries and remove avoidable work while retaining meaningful research. |

P0 here means a trust-critical repair priority, not a claim of a security vulnerability. The observed Lean failure was rejected; the report does not claim Lean accepted a false theorem.

#### H2.2 Improvements that must be preserved

- P01 correctly returns the three supplied lines through a literal-direct route, with no research.
- P02/P05 correctly apply piecewise functions to valid inputs; no case contamination is visible in those runs.
- P06/P07 correctly distinguish real and complex solution sets for `x² + 1 = 0`.
- P08 returns the correct empty set for a rational equation whose apparent candidate is excluded.
- P11 returns the correct mathematical root `x = 2`; its failure is later generation/format/status handling.
- P12 correctly acknowledges the open status and avoids claiming a proof. Its mathematical honesty must be retained.
- P13 executes web searches successfully. Therefore the earlier unregistered-search error is not evidence that all search paths are universally broken.
- Later panels explicitly describe evidence-support scores as not probabilities, and the 98% mathematics badge as a held-out expression benchmark (`n=43`). These are not current-answer confidence.
- Some recent timer differences reconcile exactly: `3.5 + 1.6 = 5.1`, `3.5 + 3.4 = 6.9`, and `3.5 + 5.1 = 8.6` seconds. Different scope is a supported explanation in those runs.

#### H2.3 Claims of fixes versus live evidence

The supplied `Pasted markdown(3).md` reports commits `0351306` and `37075ce`, 1,536 backend tests passing/17 skipped, and 201 web tests passing, plus build/type/lint checks. Those are supplied claims, not independently executed checks.

| Claimed repair | Subsequent observed status |
| --- | --- |
| Literal output and no research for copying | Supported by P01 for one prompt; broader export/clipboard behavior remains to be tested. |
| Defined functions and independent cases | Supported for the valid-input examples P02/P05; retain adversarial and held-out checks. |
| Positive-integer domains, including zero rejection | Contradicted by P03/P04 and their false Domain Pass labels. |
| Formatting preserved when the writer fails | P06/P11 preserve the mathematical value but lose required set notation. |
| No raw “Results gathered for…” fallback | Contradicted by P14 when no usable mathematical result exists. |
| Negation-aware intent and output contracts | P14 ignores the explicit removal of the word limit; P13 still misclassifies a status lookup. |
| Serious work on open problems | Not demonstrated by P14 because generation fails before mathematical work is delivered. |
| Lean installed and usable | P12 reaches an actual compiler rejection; the major observed defect is semantic misformalization. Mathlib availability remains a configuration claim to inspect. |
| History is preserved under quota pressure | Later warnings say the current run was not saved, rather than that old text was removed. This supports improved disclosure, not verified durability. No warning is visible in P13/P14; persistence was not demonstrated by that absence. |
| Search off is enforced everywhere | Claimed in the repair summary; not established by the visible post-repair screenshots, which show Search on. Test it directly. |

**Interpretation corrections:** do not treat all timer differences as bugs; do not interpret zero literature claims as failure for exact mathematics; do not penalize an accurately unavailable optional checker; do not infer permanent history loss from a warning without checking recoverable storage; do not treat HTTP 500 as proof of either a provider outage or a particular application bug.

The user's clarified goal matters: meaningful research can be lengthy. Judge its mathematical progress, check quality, and resource use against the actual request. A short status lookup and a sustained proof attempt have different completion requirements.

### H3. Complete observed-run register

Scores are human diagnostic judgments, not calibrated benchmarks, probabilities, release thresholds, or a single app-wide rating. The fixed later rubric is correctness 40, instructions 20, verification/status 25, routing/efficiency 15. The original first five scores were informal. Do not average runs with different prompts/settings into a model capability estimate.

#### H3.1 Original evaluation and first retest: B1-B5, R1-R7

| Run | Evidence filename | Visible duration / steps | Recorded score | Main observations |
| --- | --- | --- | --- | --- |
| B1 | gofullpage-localhost-3000-2026-10-25-14_12_40.png | 15 s / 4 | 20/100 | Original Collatz proof request becomes an ODE/simulation clarification. Planner recognizes Collatz. No mathematical answer is delivered. |
| B2 | gofullpage-localhost-3000-2026-10-25-14_16_08.pdf | 52 s / 24 | 50/100 | Short status question correctly answered "open"; Auto chooses Debate for allegedly requesting new hypotheses. Math checker uses free scalar T and noninteger n. Irrelevant retrieval, malformed citation marker, and incorrect completion warning. |
| B3 | gofullpage-localhost-3000-2026-10-25-14_21_34.pdf | 49 s / 22 | 55/100 | Final T(3), T(4), odd/all-domain answers are correct and reject the invalid noninteger witness. Checker still tests the wrong statement and shows misleading Pass/partial-verification labels. |
| B4 | gofullpage-localhost-3000-2026-10-25-14_27_00.pdf | 84 s / 19 | 50/100 | Correct final f(2)=5 and substitution proof. Math panel selects x(f-x); a later tool step returns 1. Function definition is reported missing; claim-support and coverage statuses disagree. |
| B5 | gofullpage-localhost-3000-2026-10-25-14_30_44.pdf | 45 s / 11 | 60/100 | Correctly rejects the prime-polynomial claim. Verifier rejects the separate n=41 example using n=40. Valid disproof is labeled incomplete. |
| R1 | gofullpage-localhost-3000-2026-10-25-14_41_20.pdf | 7.3 s / 4 | 10/100 | After changes, original Collatz request still triggers the same simulation clarification. Trace also explicitly says it read a proof question. |
| R2 | gofullpage-localhost-3000-2026-10-25-14_52_53.pdf | 209 s / 16 | 55/100 | Follow-up without the sentence about simulations answers Collatz, but reverses the cycle, overstates almost-all convergence, and asserts inability to prove/disprove. Same-chat confound; seven of nine claims unchecked. |
| R3 | gofullpage-localhost-3000-2026-10-25-15_00_43.pdf | 26 s / 11 | 70/100 | Correct short cycle answer. Axiom instead solves for T=1/2, n=-2/5, outside the requested domain, and presents Pass labels for a different system. |
| R4 | gofullpage-localhost-3000-2026-10-25-15_04_45.pdf | 51 s / 14 | 75/100 | Correct function answer and correct substituted-identity check; source-to-result match is still not established. Claim-level report says no claims checked. |
| R5 | gofullpage-localhost-3000-2026-10-25-15_08_58.pdf | 45 s / 11 | 75/100 | Correct polynomial disproof and completed-request status. Separate n=41 example still falsely contradicted. |
| R6 | gofullpage-localhost-3000-2026-10-25-15_14_17.pdf | 30 s / 19 | 60/100 | Correct two-case arithmetic rendered on one line. Planned checks cover both cases, but visible math outputs repeatedly show 1681. Search returns US court cases. |
| R7 | {87C385AF-E28A-4739-A666-770110F6FFD7}.png | 18 s / 11 | 50/100 | Literal two-line copying renders as ALPHA BETA. 83 literature entries appear; generic evidence grader flags failure to address the inquiry. |

Additional screenshots duplicate R3 and R4:
- {C6052CDE-869F-428A-B1C4-940516B7E74C}.png
- {FF8F976B-199B-4DD9-BA17-4D231C3F2202}.png

The six-page R2 PDF also contains the earlier R1 conversation. Do not count the earlier answer as another independent run.


#### H3.2 Runs following the supplied repair report: P01-P14

| Run | Request and expected result | Observed result / material trace | Recorded score |
| --- | --- | --- | --- |
| P01 | Copy CEDAR-17, MAPLE-42, WILLOW-08 on three lines. | Exact output; literal-direct, one step, displayed 0.0s. Generic cited-identifier verification text is inapplicable. | 98 |
| P02 | Positive-integer `g(n)=n/2` even, `5n+3` odd; evaluate 3,8,11. Expected 18,4,58. | All correct; structured tool/checks pass. Header 11s versus expanded trace 38s including 37s drafting; unexplained “needs a look” badge. Final score revised after trace review. | 92 (initially 94) |
| P03 | Positive-integer-only `h(n)=n/2` even, `7n−1` odd; evaluate 0,1,6. Expected undefined,6,3. | Returns `h(0)=0`,6,3. Domain Pass and Verified falsely certify the invalid evaluation. | 58 |
| P04 | `q:{1,2,3,...}`, `q(n)=n²+4`; evaluate 0,−2,3. Expected undefined,undefined,13. | Returns 4,8,13; all three “supported,” Domain Pass/Verified. Planner also rejects `definitions.0.parameter: Field required`. Header 34s, inner trace 30s/26s drafting. | 43 |
| P05 | Positive-integer Collatz map; T(40),T(41),T(42). Expected 20,124,21. | Values and exact three-line body correct. Drafting HTTP 500; fallback retains values but labels a complete mathematical answer “Partial.” Header 6.5s; inner 5.3s. | 92 |
| P06 | `x²+1=0` over reals; one-line set notation. Expected `∅`. | Correct meaning “no solutions”; requested set notation missing after drafting HTTP 500. Math card independently counts zero real roots. | 80 |
| P07 | Same equation over complexes. Expected `{−i,i}`. | Correct final set and two-root checks; writer succeeds. Generic summary says no claims checked. Header 5.1s, read 3.5s, inner 1.6s. | 95 |
| P08 | `(x²−1)/(x−1)=2` over reals. Expected `∅`. | Correct empty set; no HTTP 500. Math 0.06s, drafting 3.2s; read 3.5s + inner 3.4s = header 6.9s. | 95 |
| P09 | `(x²−1)/(x−1)=x+1` over reals. Expected `ℝ∖{1}`. | Final set correct; tool says “no solutions” alongside a nonempty general set; only equation matching verified, independent general-set check unavailable. 9s, 2 model calls. | 88 |
| P10 | `(x−2)²=x²−4x+4` over reals. Expected `ℝ`. | Final set correct; repeats “no solutions (general solution set: Reals).” Partial verification honestly reports no independent result check. Math 0.02s; drafting 7.6s. | 87 |
| P11 | `sqrt(x+2)=x` over reals; one-line set. Expected `{2}`. | Correct root and original-equation/substitution/solveset checks; drafting HTTP 500. Fallback `x=2` loses set notation and receives Partial status. | 80 |
| P12 | RH proof/disproof, honest open-status fallback, under 150 words. | Correct open-status prose; Auto Debate misclassifies existing hypothesis; three solver calls have no recognized variables; four searches rejected as unregistered; Lean goal is False. 4m29s, 15 model calls, 18.4k estimated tokens, 3m1s debate; progress 0/4. | 70 |
| P13 | Current RH status from CMI, one sentence with source URL. | Correct status sentence/source label. Auto Debate takes 4m1s/26 steps, including 2m3s hypothesis phase. Three follow-up web searches execute. Final claim has zero mapped sources/no NLI check; counter-evidence concerns a different, absent claim. | 75, provisional source-link assessment |
| P14 | Serious sustained RH investigation with approaches, lemmas, checks and precise gap; explicitly no 150-word cap. | Planner fails; formalization and drafting report HTTP 500. No mathematical argument is produced. Fallback echoes prompt as results. Enforces a nonexistent 150-word cap and marks its removal an unsupported literature absence. 15s/11 steps. | 10 for task delivery; mathematical ability unassessed |

P14's component scores were 0/40 delivery of a mathematical answer, 0/20 requested work, 5/25 verification/status, 5/15 routing/recovery. This does not mean the underlying model scored zero on a mathematical reasoning benchmark: no usable response was produced.

The P13 capture displays a CMI-labelled source, but its raster PDF contains no URI annotations. The actual link target cannot be verified from that capture. Do not assert that the URL is definitely broken or definitely correct.

### H4. Earlier issue reports I01-I23, retained with current-status context

The reports below preserve the original reproductions and distinctions. Historical observations are not assertions that every symptom still occurs today. Use historical Section H2 and the later issues to determine current evidence; reproduce against the attached code before closing an issue.

#### I01 — Conflicting intent representations and mishandled negation — P1

Observed in B1 and R1:
- User asks for a universal proof/disproof and supplies both Collatz update rules.
- A sentence explains that simulations do not establish the universal claim.
- Final response asks: "Which dynamical system should I simulate?"
- Clarification reason: "A simulation was requested but no equations or named system were given."
- The plan correctly names Collatz and constructs appropriate mathematical questions.
- R1 additionally says: "Read as a proof question (semantic + keyword signals)."

Confirmed: stages disagree about intent, supplied input, and the response required.
Hypotheses: keyword matches ignore negation; incompatible intent flags coexist; a clarification gate reads stale/partial state; generic simulation handling overrides the proof classification.

Trace all these possibilities. Establish a consistent semantic request representation. Explicit instructions, negation, task scope, and supplied definitions must survive every stage. Do not patch only the word "simulation."

#### I02 — Unnecessary clarification and false missing-input detection — P1

The system asks for ODE equations, initial conditions, a standard physical system, and integration time even though the requested discrete map and universal mathematical question are fully specified.

Clarification should occur only for missing information that materially blocks the actual requested operation. Test legitimate underspecified simulations too; do not globally disable clarification.

#### I03 — Incorrect computation gating — P1

R6 explicitly requests numerical evaluations at n=40 and n=41, yet the trace says Calcula is skipped because "no numerical computation requested."

Inspect the actual responsibilities of Calcula/Axiom and the routing explanation. Even if another tool can perform the arithmetic, the recorded intent explanation is inconsistent. Support task-appropriate exact computation and truthful skip reasons.

#### I04 — Research is applied to requests that need no external knowledge — P1

**Current-status annotation:** Current evidence: P01-P11 generally skip unnecessary research. Preserve that improvement while repairing mixed-information requests (I38). Search-off enforcement still needs direct testing.

R7 asks only to reproduce two supplied lines. Nevertheless:
- Duration: 18 seconds.
- Steps: 11.
- Literature card: 83 articles.
- An evidence/grounding warning is generated.

R3, R4, R5, and R6 also retrieve literature for supplied arithmetic or definitions. "Direct workflow" does not visibly provide a genuinely lightweight route.

Search availability should permit appropriate research rather than require it. Exact copying, supplied-data transformations, and self-contained arithmetic need no external literature unless the user separately requests it. Enforce Search off on the server and client, and audit all retrieval paths, including academic adapters and follow-up tools.

#### I05 — Excessive orchestration, retries, and critic escalation — P1

Observed:
- B2 selects Debate for a status question, reasoning that the user wants new conjectures.
- B3/B4 and R4/R6 use heavyweight planning or repeated mathematical strategies for trivial operations.
- R6 repeats a simplified value through multiple strategy steps.
- Several runs escalate to multiple critics despite straightforward supplied definitions.
- Ultra effort appears alongside these requests, but it has not been established as the cause.

Inspect budgets, retry criteria, progress detection, repeated call deduplication, and workflow selection. High effort should raise an available ceiling, not impose unnecessary minimum work. Enumerating two simple tasks should not automatically require a multi-agent or research workflow. Escalate only when a concrete unresolved issue warrants it.

Do not create unsafe timeouts that truncate genuinely difficult research.

#### I06 — Retrieval relevance and query construction fail — P1

Examples visible in the captures:
- R6's "two independent cases" produces US court-case results, including National Federation of Independent Business v. Sebelius.
- B2 includes basic odd/even teaching material.
- R4 lists papers about the Schoenflies theorem, ergodic theory, fixed-point indices, and other subjects unrelated to direct polynomial substitution.
- Some earlier Collatz evidence includes supersymmetric QCD and unrelated mathematical papers.

These observations support poor semantic query construction/relevance filtering. They do not prove every listed paper was newly fetched or every source was irrelevant.

Build queries from the mathematical/scientific entities and actual information need. Filter and rank content for the specific claim, not shared generic words such as "case," "proof," "integer," or "function." Avoid research entirely when there is no external information need.

#### I07 — Function application is confused with scalar multiplication — P1

**Current-status annotation:** Current evidence: P02/P05 preserve function application on the tested valid inputs. The earlier representation failures remain regression cases; do not declare every parser path broken today.

Observed:
- B2/B3: the checker assigns T=0.290036 and n=2.557913. Its left-side value is 0.741886854868, which equals T*n.
- B4: the displayed simplification is x(f-x), consistent with simplifying f*x-x^2 instead of using f(x)=x^2+1.
- R3: output is T=1/2, n=-2/5 rather than the requested function values.

Strong inference: function semantics are lost somewhere in parsing, tool argument construction, or mathematical representation. Locate the exact layer.

Preserve declared functions, arity, definitions, substitutions, independent symbols, and application nodes. Do not silently interpret a declared function call as implicit multiplication. Handle alternative notation, renamed functions, Unicode exponents, and equivalent explicit definitions without problem-specific exceptions.

#### I08 — Conditional branches and mathematical domains are discarded — P1

**Current-status annotation:** Current evidence: P03/P04 reconfirm domain loss and false certification (I24), even though several valid-input piecewise examples pass.

R3's result exactly matches solving the WRONG simultaneous system:

~~~text
T*n = n/2
T*n = 3*n + 1
~~~

Its solution T=1/2, n=-2/5 violates the requested positive-integer domain. The user supplied conditional branches, not simultaneous equations in two unknown scalars.

Represent piecewise definitions, branch predicates, parity, domains, and quantifiers explicitly. Validate applicability before solving and before accepting a result. A tool output about a mistranslated or out-of-domain problem must not be called a counterexample to the original statement.

#### I09 — Independent cases and local bindings are not reliably preserved — P1

B5 and R5:
- A valid example at n=40 is followed by a separate valid example at n=41.
- The verifier labels n=41 contradicted and says n evaluates to 40.

R6:
- User explicitly requests local assignments in two independent cases.
- Final values are correct: 1681 and 1763.
- Both case checks are planned, but the visible mathematical trace repeatedly returns 1681 and does not demonstrate separate validation of 1763.

Hypotheses: global substitution state, overwritten local environments, missing case IDs, incorrectly keyed cache entries, output aggregation selecting one result, or verification using bindings from another claim. Reproduce and localize rather than choosing one explanation without evidence.

Scope definitions and assignments by request, subtask, case, and claim. Preserve those identities through tool calls, caches, synthesis, exports, and verification. Test reversed case order, renamed variables, concurrency, and repeated expressions under different bindings.

#### I10 — Valid transformed calculations cannot be linked to the original task — P1

R4 correctly verifies:

~~~text
x^2 + 1 - x^2 = 1
~~~

Yet its panel says the tool call could not be matched to the original problem, despite the supplied definition f(x)=x^2+1. The final answer is correct but its checking provenance is incomplete.

Track a justified dependency from the declared definition to substitution, transformed expression, computed result, and requested claim. Match equivalent expressions using appropriate mathematical reasoning under the original assumptions. Do not demand literal string identity, and do not accept unrelated expressions merely because a local check passes.

#### I11 — Independent checks can validate the wrong problem — P1

Observed Pass labels include:
- "Equations match the problem."
- "Identity matches the problem."
- "Each solution satisfies the original equation(s) by substitution."
- "Solution count re-derived from the original system."

Some of these appear beside out-of-domain or incorrectly parsed results. Checking the same mistranslated expression twice is not independent verification of the user's question.

Introduce separate checks for interpretation fidelity, assumption/domain preservation, computational correctness, and coverage of the requested result. Reuse of a parser must not be misrepresented as independent protection against that parser's defects.

#### I12 — Coverage scanning confuses formatting instructions with mathematics — P1

The checker reports missing mathematical inputs such as:
- "4, 40" when 4 is a requested function argument and 40 is a word limit.
- Earlier captures similarly mention instruction numbers such as 100.

Understand number roles rather than comparing bags of numerals. Separate mathematical constants/arguments from list indices, word limits, timestamps, and formatting constraints. Missing a requested argument is meaningful; missing a word-limit numeral from a symbolic expression is not.

#### I13 — Claim extraction and verification status aggregation are inconsistent — P1

B4 shows:
- Trace: "0 of 2 supported."
- Banner: "All 2 checked claims supported by the evidence."
- Details: both statements are "NOT CHECKABLE."

Other captures combine:
- Correct expression-level checks.
- A message saying no claims could be checked.
- Partial-verification badges.
- An assertion that the original problem was checked.
- A warning that the tool call could not be matched to that problem.

Distinct layers may legitimately have different results. The defect is reporting them without a coherent explanation and sometimes with mutually incompatible counts.

Use explicit typed states and stable claim IDs. Distinguish checked-valid, checked-invalid, insufficient evidence, unsupported operation, interpretation failure, unavailable checker, not requested, and not applicable. Define aggregation rules and ensure all UI panels, exports, and logs derive from consistent final data.

Refresh claims, bindings, findings, counts, and coverage after answer revision. Never reuse a stale finding without confirming it still applies to the revised final text.

#### I14 — Completion and grounding graders misunderstand the requested operation — P1

**Current-status annotation:** Goal clarification: a status-only request is fulfilled by an accurate unresolved-status answer. An explicit sustained investigation requires worked approaches/lemmas/checks and a precise gap (historical Section H6.4 and T34/T42); status-only prose is insufficient for that different request.

Observed:
- Correctly saying Collatz is open triggers "whether the claim is proved" not addressed.
- A rigorous counterexample to the false polynomial claim is labeled incomplete in B5.
- B4's direct answers trigger "does not appear to address the primary focus."
- R7's literal copying triggers an academic evidence/grounding warning.

Grade completion against the actual task:
- An open problem should receive an accurate account of its unresolved status, not a fabricated proof.
- A false universal statement is resolved by a valid counterexample.
- A copying request is checked against the requested text and formatting.
- A supplied-data calculation is checked against that calculation.
- A research claim needs suitable external evidence.

Do not treat absence of citations as a defect for nonfactual or self-contained tasks.

#### I15 — Research claims and mathematical explanations contain substantive errors — P1

R2 correctly identifies Collatz as open but includes these defects:

1. It writes the forward cycle as 1 -> 2 -> 4 -> 1. Under the supplied map, the correct forward cycle is 1 -> 4 -> 2 -> 1.
2. It asserts that almost all starting integers, in natural density, are known to reach 1. This overstates the standard partial results. Tao's theorem establishes almost-bounded orbit minima for logarithmic-density almost all starts; that is not convergence to 1.
3. It says the problem "cannot be proved or disproved with current mathematics." No known accepted proof/disproof does not establish impossibility or independence.
4. It also says neither a proof nor disproof exists. Use "is known" or "is accepted" where discussing open status.

Primary reference for the precise Tao result:
[Primary paper](https://arxiv.org/abs/1909.03562)
Author's explanation:
[Author explanation](https://terrytao.wordpress.com/2019/09/10/almost-all-collatz-orbits-attain-almost-bounded-values/)

As described in the paper, for every function f(N) tending to positive infinity, the minimum of the Collatz orbit is at most f(N) for logarithmic-density almost all N. A constant target f(N)=1 does not satisfy the hypothesis.

Also audit, without assuming confirmed errors:
- The use of "conjugate" for the accelerated odd-to-odd map versus an induced/first-return description.
- The distinction between logarithmic/geometric drift and an arithmetic average contraction.
- The claimed refutation of a source using only 6 -> 3. That step alone does not refute eventual arrival at a power of two under the FULL Collatz iteration: 6 -> 3 -> 10 -> 5 -> 16. The validity of the criticism depends on the source's exact statement.

Do not transfer the open-problem wording rule blindly to false claims. Once a statement is rigorously disproved by a counterexample, saying no sound proof of that universal statement exists is justified.

#### I16 — Source acceptance, citation integrity, and evidence grading need repair — P1

Observed:
- Purported Collatz proofs and unrelated papers appear in evidence.
- A displayed citation marker is malformed, resembling "[; unclassified]."
- Source titles sometimes expose raw mathematical markup.
- Evidence classifications and metadata-check badges are used prominently.

Required behavior:
- Inspect the actual relevant passages before claiming support or contradiction.
- Do not treat a paper title containing "proof," metadata integrity, or a publication-type classifier as proof of mathematical validity.
- Do not reject an argument solely because it is a preprint. Separate publication/acceptance status, relevance, content, and correctness.
- Distinguish abstract-level retrieval from full-paper review.
- Validate citation targets and claim-to-source support.
- Degrade honestly when Crossref or another adapter is unavailable; lack of a service is not proof that all other retrieval failed.
- Clearly distinguish external-source contradiction from a local substitution checker rejecting an expression.

Do not invent papers, authors, DOIs, accepted proofs, or source passages.

#### I17 — Exact output constraints are not preserved end to end — P1

**Current-status annotation:** Current evidence: P01 renders three supplied lines correctly. P06/P11 expose a different surviving issue: fallback loses required set notation (I27). Native export and clipboard claims still require direct tests.

R6 requests exactly two lines. The browser displays both cases on one line.
R7 requests exactly:

~~~text
ALPHA
BETA
~~~

The browser displays:

~~~text
ALPHA BETA
~~~

Inspect raw model text, stream chunks, accumulated state, Markdown processing, whitespace handling, DOM output, clipboard output, and exports. Locate where the newline is lost. Ordinary Markdown soft breaks are a candidate, not a confirmed root cause.

Preserve explicit plain-text, newline, indentation, JSON, and "nothing else" constraints. Do not add headings, citations, warnings inside the answer text, code fences, or boilerplate when the output contract forbids them. Keep necessary diagnostics in separate UI state, with task-appropriate relevance.

Test the literal expected LF-normalized string "ALPHA\nBETA" and its visible two-line rendering. Define trailing-newline behavior explicitly. Do not silently trim meaningful whitespace.

#### I18 — Final-answer constraints and template expansion lack consistent enforcement — P2

Trace word counts are sometimes reported before revision. Later responses add executive summaries, evidence limitations, diagnostic commentary, and repeated proof sections.

No universal word-limit violation is asserted from screenshots: mathematical tokenization makes some counts ambiguous. Verify the FINAL serialized response against the requested constraint using a documented counting rule. Validate exact line counts and machine-readable formats deterministically.

Avoid generic academic sections on literal copying or trivial calculation. Do not let internal tool failures dominate an otherwise simple answer. Preserve material limitations when they affect confidence in the answer itself.

#### I19 — Confidence and verification signals are poorly separated — P1

**Current-status annotation:** Current evidence: a later panel explicitly identifies 98% (n=43) as a held-out mathematics-expression benchmark, and support panels explicitly say “not a probability.” Preserve those distinctions. Neither this benchmark nor the 27%/40%/41% support displays is current-answer correctness confidence.

Observed:
- Correct definitional arithmetic receives 0.38/0.40 support scores and "no NLI check."
- Final answers describe low/moderate confidence computed from claim support.
- UI labels include routing relative scores, evidence-support percentages, and "Benchmark precision 25% (n=2)" / "67% (n=1)."
- One panel explicitly explains that support is not a probability of truth; other labels make the distinction less clear.

Audit the actual calculations and any supplied calibration artifacts. Do not assume the displayed benchmark percentages are mathematically impossible; their denominators and aggregation are not established from the captures.

Separate:
- Routing preference.
- Retrieval relevance.
- Source reliability.
- Claim/source entailment.
- Exact mathematical correctness.
- Interpretation fidelity.
- Coverage of requested claims.
- Formal-proof checker status.
- Empirically calibrated answer confidence, if a real calibration exists.

Do not substitute literature support for arithmetic certainty or display a probability-like trust score without appropriate evidence. Show unavailable/uncalibrated states honestly.

#### I20 — Storage quota handling removes saved conversation content — P1, investigate impact promptly

**Current-status annotation:** Current evidence: the repair summary claims history deletion was removed. Later captures instead warn that the current run is not saved; P13/P14 show no such banner. Verify actual durability/eviction with controlled data; do not assert ongoing deletion or proven recovery from these observations alone.

Repeated warnings say the browser storage was full and saved messages from an older investigation were removed. Another capture mentions removing plots and citation passages. These are different actions; inspect the real eviction behavior.

The captures do not establish whether server-side copies or recoverable archives survive. Determine that before claiming permanent loss or successful recovery.

Requirements:
- Preserve core conversation text, user inputs, settings, and essential provenance.
- Separate reconstructible caches/media from durable records.
- Bound cache growth and handle quota exceptions transactionally.
- Avoid partial or silent writes and cross-conversation deletion.
- Do not delete core user history merely to make room for new retrieval results.
- Provide truthful failure/recovery states and explicit destructive-action controls.
- Back up or preserve affected data before migration.
- Test quota saturation, reload, failed writes, and recovery.

#### I21 — Memory writes and cached trust may amplify other failures — P1 audit target

**Current-status annotation:** Current evidence: P13/P14 report ten/five memory nodes written. The content, trust level, quota impact and subsequent reuse were not inspected.

Small requests visibly write approximately five to seven memory nodes. Meanwhile, verification is sometimes wrong or incomplete and storage warnings recur.

Confirmed: writes are reported; storage warnings recur.
Unconfirmed: those memory writes caused the quota issue or stored the erroneous intermediate results as trusted facts.

Inspect memory policy, provenance, size limits, and trust handling. Avoid persisting unverified solver artifacts as established knowledge. Store only useful, appropriately scoped information; preserve verification status and definitions. Invalidate incompatible computed caches after representation changes without deleting user-authored history.

#### I22 — Traces, timing, counters, and evidence provenance are difficult to reconcile — P2

**Current-status annotation:** Current evidence: several later outer/inner differences reconcile when the reading phase is included (historical Section H2.2). The P02 11s/38s observations still need actual run/call correlation. Different clocks and rounding are not automatically defects.

Examples requiring inspection:
- A run header shows a different duration from a run-budget/timing panel.
- Some calls show 0.0 s.
- Some agent budgets show zero tool calls while the UI reports retrieved literature and web results.
- A reading stage remains "not reported as finished" after a clarification is delivered.
- Repeated strategy outputs may lack visible case attribution.
- A literature card's total is easily confused with freshly retrieved or verified sources.

Different accounting boundaries, cache hits, or agent-vs-backend counters may explain some differences. Do not label all differences bugs without checking.

Use documented timing boundaries and request/run/case/claim/tool-call IDs. Attribute retries, cache hits, rejected calls, streaming, and checks accurately. Distinguish retrieved documents from relevant passages, cited documents, and actually supported claims. Make genuine error/terminal states consistent and observable.

#### I23 — Optional checker capability and UI presentation require appropriate treatment — P2

**Current-status annotation:** Current evidence: P12 actually invokes Lean and receives compiler output. The current trust-critical failure is the unrelated False target (I33), not mere installation availability. The supplied summary says Mathlib is absent; inspect actual capabilities.

Lean 4 is shown as unavailable because it is not installed/configured. The UI mentions TRIBOS_LEAN_PATH.

Absence of an optional checker is not itself proof that the application is defective, and ordinary arithmetic should not depend on installing Lean. Detect capabilities, report unavailable checks honestly, and avoid claiming a formal proof when none ran.

Likewise, a panel titled "Verified mathematics" should not suggest the entire user question is verified when only an unrelated or unmatched expression has passed a local check. Present the scope and limitations clearly. Avoid tiny or undocumented benchmark samples functioning as trust badges.


### H5. Additional and reconfirmed issue reports I24-I43

These entries extend the earlier findings. They are not necessarily twenty independent root causes.

#### I24 — Explicit domains are ignored and falsely verified — P0

**Evidence:** P03 returns h(0)=0 although h is defined only on positive integers. P04 returns q(0)=4 and q(−2)=8 although q has domain {1,2,3,...}. Both display Domain Pass and Verified. P04 confirms the failure without piecewise branches.

**Repair:** enforce membership in the original declared domain before evaluation; preserve it through representation, tool arguments, synthesis, and independent checking. Validate the interpreted domain against the user's definition, not only against the same potentially defective tool payload. A correctly returned “undefined” is a complete answer to an invalid-input evaluation; distinguish “input is valid” from “invalid input was correctly rejected.”

**Acceptance:** T23/T24 and domain-changing controls pass. No valid arithmetic substitution may override an invalid function application. Extends I08/I11.

#### I25 — Planner arguments fail a registered tool schema — P1

**Evidence:** P04 shows `definitions.0.parameter: Field required`. The later computation still returns out-of-domain values. The captures do not establish whether the missing parameter caused the domain failure.

**Repair:** locate the actual planner/tool contracts, schema versions, and repair path. Validate definition name, parameter, domain and branches before execution; make a bounded, specific schema repair or return an accurate interpretation failure. Preserve valid definitions during recovery. Do not silently weaken a domain or discard a malformed definition to obtain a successful call.

**Acceptance:** T38 injects missing/renamed fields and proves production recovery or truthful refusal.

#### I26 — Recurring completion errors lack a demonstrated diagnosis and resilient execution path — P1

**Evidence:** drafting returns `HTTP 500 / Failed to generate completions` in P05/P06/P11. In P14 the planner fails, and formalization/drafting explicitly report HTTP 500. Other runs succeed, so universal service unavailability is not established. The repair summary also records earlier NVIDIA errors.

**Repair:** correlate actual run IDs with backend logs, provider endpoint/model, redacted request shape/options, request IDs, status/body, streaming phase, timeouts and retry attempts. Replay a minimal request and the sanitized failing request through the same configured client. Distinguish provider/inference faults from request-dependent failures and application exceptions. Generic 500 text does not identify the cause. Preserve provider choice; use another provider only where already configured and authorized.

**Acceptance:** T37/T45 exercise healthy, transient, persistent, streaming and request-specific faults. Avoid multiplied SDK/application retries, unlimited retry loops, or secret logging.

#### I27 — Valid computed results depend on a writer and lose output format during fallback — P1

**Evidence:** P05 retains the correct three equalities but labels the answer Partial. P06/P11 retain correct mathematical meaning as “no solutions”/“x=2” but violate requested set notation after writer failure. P02 spends 37 displayed seconds drafting after a 0.02s computation.

**Repair:** provide a deterministic renderer for supported validated result types and output contracts, including sets, undefined inputs, ordered equalities and plain text. Keep writer availability distinct from mathematical correctness and task completion. Mark complete only when the available results actually fulfill the whole request; a mixed request with missing explanation can remain partial.

**Acceptance:** healthy and writer-failing executions produce the same contract-compliant mathematical payload when the tool result is sufficient.

#### I28 — Empty-result fallback echoes the prompt as computed evidence — P1

**Evidence:** P14's “Results gathered for…” reproduces the research instructions and says these are “tool results as computed”; no computed mathematical results are shown. The partial-error notice is honest, but the purported results are misleading.

**Repair:** type user input, model output, tool output and diagnostics separately. A request summary may appear as a request, never as evidence or a computed result. If nothing was produced, state which stages failed and that no mathematical result is available. Preserve useful partial work and allow continuation according to existing run architecture.

**Acceptance:** T37 with zero usable results yields an honest failed run, not a prompt echo, fabricated evidence, or an answer fabricated from the question's conjecture.

#### I29 — Removed/negated output constraints remain active — P1

**Evidence:** P14 says “There is no 150-word limit.” Tribos reports “Requested format not met: 350 words, at most 150 allowed.”

**Repair:** investigate both negation interpretation and stale inherited contracts. Give constraints explicit scope, source, polarity and revision/precedence. A current instruction removing a prior limit must not become the limit itself. Numerals in examples or quotations must not create constraints.

**Acceptance:** T35 tests no limit, explicit removal, later replacement, quoted limits, multilingual paraphrases, and genuine positive caps. Extends I01/I12/I18.

#### I30 — Formatting instructions are treated as literature absence claims — P1

**Evidence:** P14 marks “There is no 150-word limit” unsupported because “a literature-wide absence cannot be established from one search.” It scores the copied instruction as a factual claim despite the generation failure.

**Repair:** identify text origin and role before checking it. Exclude instructions, quoted prompts, formatting metadata and error messages from factual/literature entailment. Distinguish mathematical negation, a historical/acceptance-status claim, and a literature-wide absence claim. Do not apply one rule to every sentence containing “no.”

**Acceptance:** T36 verifies both exclusions and real absence/status claims; do not disable factual verification globally.

#### I31 — Empty finite roots are conflated with an empty solution set — P1

**Evidence:** P09 says “no solutions” while showing `Union(Interval.open(-oo,1), Interval.open(1,oo))`. P10 says “no solutions (general solution set: Reals).” Both final sets are mathematically correct.

**Repair:** represent no solutions, finite solutions, infinite/parametric families, conditional sets and unresolved results distinctly. An empty list of isolated roots does not by itself establish an empty solution set. Inspect the actual solver's return semantics and conversion paths rather than guessing a particular implementation.

**Acceptance:** T26-T31 and held-out identities/contradictions have consistent tool, final-answer and export descriptions.

#### I32 — Independent checking does not cover supported infinite sets — P1

**Evidence:** P09/P10 only establish equation matching and explicitly report no independent result check. The partial-verification label is appropriate; the missing coverage is the issue.

**Repair:** add sound checks where feasible: original-domain preservation, symbolic identity under assumptions, exclusions, and equivalence between the proposed set and the original equation. Finite sample substitution is insufficient for completeness of an infinite set. Retain unavailable/unsupported states when no sound checker exists.

**Acceptance:** T29/T30 check ℝ∖{1} and ℝ independently; wrong excluded points, endpoints and conditions are rejected.

#### I33 — Formal proof target does not encode the mathematical claim — P0

**Evidence:** P12 shows:

~~~lean
theorem riemann_hypothesis : False := by
  intro h
  exact h
~~~

The name does not encode RH. The displayed theorem has an unconditional False target and no RH statement or assumptions. Lean rejects it; this is not a relevant formal attempt on RH.

**Repair:** validate natural-language-to-formal statement correspondence before tactic repair/checking. Preserve quantifiers, objects, domains and assumptions. Reject unrelated True/False substitutes, an assumed conclusion, or an irrelevant proved lemma presented as the target theorem. Genuine contradiction proofs remain legitimate when their assumptions and connection to the original goal are explicit.

Do not convert unsupported mathematical notation into a different core-Lean proposition merely to obtain compilation. Detect libraries/capabilities honestly. Reject `sorry` and untrusted axioms that assert the conclusion; distinguish these from documented trusted foundational axioms used by Lean/Mathlib.

**Acceptance:** T39 tests semantic mismatch even when unrelated code compiles, plus valid supported lemmas. Lack of Mathlib is not itself a defect or permission to misstate the theorem.

#### I34 — Planner/tool availability and recovery disagree — P1

**Evidence:** P12 wants four searches but rejects all with `tool 'web_search' is not registered`, while the summary says no follow-up calls were needed. P13 executes three follow-up searches successfully under an explicit website lookup.

**Repair:** give the planner an accurate typed registry for the run's enabled capabilities. Validate names/schemas and distinguish disabled-by-user, unavailable, unknown, rejected, attempted and completed. Recover from an invalid planned name only within already-authorized capabilities. Do not bypass Search off by registering a blocked tool.

**Acceptance:** T38 tests the same need across search settings and workflow boundaries; a rejected necessary plan cannot be reported as unnecessary.

#### I35 — Named mathematical hypotheses trigger conjecture-generation intent — P1

**Evidence:** B2 and P12/P13 select Debate on the rationale that the user asks for new hypotheses. P13 asks only for current accepted status and a URL.

**Repair:** separate entity names from requested actions. Classify status lookup, proof, disproof, proposed-method critique, generation of conjectures, and sustained investigation. Debate can be appropriate for a serious investigation; the problem is the incorrect stated intent and unrelated work.

**Acceptance:** T32-T34 plus held-out named conjectures and nonmathematical “hypothesis” uses preserve the requested operation.

#### I36 — Mathematical exploration is subjected to an irrelevant dynamics prerequisite — P1

**Evidence:** P12-P14 say no testable hypotheses could be formed because there is no dynamical system with parameters to perturb. P13 spends 2m3s in that phase for a one-sentence status lookup.

**Repair:** use domain-appropriate requirements. Mathematical conjectures, proof strategies and counterexamples do not universally require an ODE or perturbable physical parameters. Skip unrequested phases, and require only inputs genuinely needed by the selected operation.

**Acceptance:** status lookup skips hypothesis generation; mathematical investigation can pursue lemmas; actual simulations still enforce their legitimate required inputs.

#### I37 — Critic work does not reliably terminate on useful acceptance — P1

**Evidence:** P12 records accept verdicts from two responding critics in round one and again in round two; a physicist has no usable reply. Debate takes 3m1s. P13 critics request additions about numerical verification despite a one-sentence status/URL task.

**Repair:** define acceptance, material criticism, abstention/failure, required coverage and stop conditions. Additional rounds need an unresolved concrete issue. Evaluate critic suggestions against user scope and mathematics. Agreement is not proof; a nonresponse is not an acceptance.

**Acceptance:** bounded critic fixtures test early acceptance, useful revision, failed critics and contradictory advice without removing debate from legitimate research.

#### I38 — Mixed mathematical and external-information needs are not handled coherently — P1

**Evidence:** P12 declares web search unnecessary, while its planner explicitly needs current status and partial-result references. P13's explicit source request enables search. The repair summary's broad claim that proofs need no search is too coarse for mixed tasks.

**Repair:** evaluate need per subtask: supplied-data derivation may be self-contained; current acceptance status, literature attribution, novelty checking and use of unstated specialist results may require retrieval. Respect Search off and label unverified external claims. A mathematical topic alone neither mandates research nor forbids it.

**Acceptance:** T12/T13/T32-T34 exercise status-only, derivation-only and mixed research with both search settings.

#### I39 — Coverage/status summaries do not reflect the requested operation or final answer — P1

**Evidence:** P12 reports 0/4 subquestions answered while final prose addresses the four planned topics. P13 marks the source URL unaddressed alongside a visible source label. The actual URI is not recoverable from the PDF, so its validity is unresolved.

**Repair:** separate execution of planned tools, completion of user deliverables, and verification of answers. Model dependencies and evaluate final output, including actual link destinations. If a counter tracks only tool-backed subtasks, label that scope instead of saying none were answered.

**Acceptance:** T40/T43 distinguish complete-but-unverified answers, unavailable checks, genuinely missing deliverables, and valid rendered links.

#### I40 — Counter-evidence is attached to a claim absent from the final revision — P1

**Evidence:** P13's final answer is a short RH status statement; its counter-evidence panel repeatedly checks a different claim about prime distributions and structured/random characteristics.

**Repair:** bind claims, passages, check results and warnings to answer revisions. After rewriting, re-extract/reconcile claims and invalidate stale associations. Historical checks may be retained in a clearly labelled history, not attributed to the current answer.

**Acceptance:** T40 changes claim content after critique and proves final panels, exports and counts refer to the final version.

#### I41 — Retrieved sources are not associated with the final sourced claim — P1

**Evidence:** P13 performs several searches and displays a CMI-labelled final source, yet the support panel reports `N sources: 0`, `Supporting sources: 0` and no NLI check.

**Repair:** trace source IDs through retrieval, canonical URLs, passages, draft citations, revision and claim extraction. Verify the actual official passage supports the statement. Metadata or a source label alone is not support. A sourced historical/status statement must not inherit a broken claim-source mapping. An official page classifying a problem as “Unsolved” can support a qualified report of accepted status; it does not establish that a proof is impossible or that no proof could exist.

**Acceptance:** T33/T40/T43 preserve a correct link and supporting passage through rewriting, copying and export; wrong or unrelated links fail accurately.

#### I42 — Verification summaries and warning badges obscure check scope — P2

**Evidence:** P01 talks about cited identifiers on a copy task. P02/P04 combine “retrieved evidence” wording with a no-search mathematical route. Several correct mathematical answers say no claims could be checked globally while the math card shows successful checks. A “needs a look” badge appears without an explained warning in the expanded view.

**Repair:** derive scoped summaries from applicable checks. No literature claims is normal for self-contained mathematics. Distinguish mathematical verification, source support, formatting and optional-check availability; expose an actual reason for a warning badge. Preserve the correctly explained benchmark/support-score distinctions.

**Acceptance:** T14/T21/T26/T43 ensure truthful summaries without falsely upgrading unchecked results or hiding real failures.

#### I43 — A failed run is labelled completed evidence synthesis — P1

**Evidence:** P14 honestly reports planner/writer failures and that Debate was not reached, yet also says “Completed: evidence synthesis”; its answer mostly echoes instructions. P05/P06/P11 show the converse problem: useful complete mathematical results are broadly called Partial because writing failed.

**Repair:** separate stage status, answer sufficiency, applicable verification, provider health and run termination. Complete, partial, failed, unavailable and cancelled states need actual completed work behind them. A stage label must not imply the user's task succeeded.

**Acceptance:** T37 covers zero results, sufficient validated results, incomplete mixed deliverables and later recovery; every UI/export/report uses consistent state.

### H6. Actual codebase investigation and implementation

#### H6.1 Locate the real production path

Read repository instructions, manifests and architecture. Preserve unrelated modifications; use an isolated branch/checkout and keep the original ZIP unchanged if supplied. Trace these observed strings to actual code:

~~~text
Which dynamical system should I simulate
The question asks for new conjectures or hypotheses
no dynamical system with parameters to perturb
definitions.0.parameter
tool 'web_search' is not registered
Failed to generate completions
Model unavailable; showing the raw evidence instead
Results gathered for
at most 150 allowed
a literature-wide absence cannot be established
no solutions (general solution set:
theorem riemann_hypothesis
No claims could be checked
Completed: evidence synthesis
needs a look
~~~

The following paths are **reported in the supplied change summary, not inspected here**. Confirm existence, current ownership and call sites before editing.

| Area | Reported paths / discovery targets |
| --- | --- |
| Intent and information need | `tribos/agents/query_planner.py`; `tribos/agents/evidence_need.py`; `tribos/agents/authoritative_orchestrator.py` |
| Planning, permissions, clarification | `tribos/agentic/plan_graph.py`; `tribos/agentic/specialists.py`; `tribos/agentic/clarify.py`; `tribos/tools/reliability.py` |
| Structured mathematics | `tribos/axiom/definitions.py`; implementation/registration of `axiom_structured`, `axiom_solve`, `axiom_nsolve` |
| Claim/result verification | `tribos/verify/math_claims.py`; `tribos/verify/result_record.py`; `tribos/verify/verifier.py` |
| Output and delivery | `tribos/utils/output_contract.py`; `tribos/agents/deliverables.py`; `tribos/agents/prompts.py` |
| Formal proof | `tribos/verify/formal/`; Lean project/library capability detection and statement generator |
| Retrieval | `tribos/archivon/engine.py`; actual web adapter, registry and claim-source association |
| Model calls | Discover actual provider/client factory, request builders, stream consumer, exception translation, timeout/retry policy and stage callers |
| UI and status | `web/src/lib/verificationState.ts`; `web/src/components/MessageArtifacts.tsx`; `web/src/components/agentic/ui.tsx` |
| Storage and memory | `web/src/services/localStorageService.ts`; `tribos/agentic/project_memory.py`; actual durable/backend stores and caches |
| Rendering and export | `web/src/lib/markdownSafety.ts`; `tribos/export/markdown_blocks.py`; `web/src/lib/markdownToLatex.ts`; actual clipboard/PDF/DOCX/notebook paths |
| Existing claimed regression tests | `tests/test_audit_repair.py`; `tests/test_export_line_breaks.py`; `web/tests/auditOutputContract.test.mts`; `web/tests/runStatus.test.mts`; `web/tests/localStorageService.test.mts` |

Do not assume these modules contain the root cause. Follow the live call graph and data records. Do not introduce unrestricted eval/exec to parse user mathematics.

#### H6.2 Repair the shared contracts

Adapt these concepts to native types instead of imposing a new architecture without inspection:

- **Request:** operation and subtasks, input/quoted text roles, definitions, domains, quantifiers, case scope, information needs, search permission, output constraints and their origin/revision.
- **Mathematical result:** original problem ID, preserved assumptions/exclusions, interpreted expression, result kind, set or values, case bindings, completeness claim and justification.
- **Tool attempt:** registered capability/schema version, permission result, logical call ID, actual HTTP attempts, arguments, result/error, execution stage, timing scope and provenance.
- **Check:** exact statement/target, assumptions, result/answer revision, whether applicable and executed, outcome and limitations. Distinguish checking an interpretation from checking its arithmetic.
- **Evidence:** source/passage IDs, canonical URL, retrieval/read scope, claim ID, answer revision, relevance and support. A model-generated summary is not a retrieved primary source.
- **Answer/run:** available validated artifacts, output-contract result, requested deliverables fulfilled, failed stages and truthful terminal status. UI, clipboard/export and persistence consume the same final state.

Do not force a particular enum vocabulary, but preserve differences among valid, invalid, unknown, unsupported, unavailable, not applicable, not requested and interpretation failure. Invalid input can still receive the correct complete answer “undefined.”

#### H6.3 Provider diagnosis and failure containment

1. Reproduce with actual configured model/endpoint/settings. Save redacted diagnostic information and provider request IDs; do not print or export credentials.
2. Compare a minimal completion and the failing request. A minimal success with a request-specific failure narrows the cause; it does not by itself prove the application or provider is at fault.
3. Inspect unsupported options, context/token limits, structured output/tool schemas, streaming and message conversion against the actual provider contract. Verify effective options, not just configuration labels.
4. Implement bounded transient-error recovery with a total deadline. Respect existing SDK retries and provider guidance; classify non-retryable failures. Do not silently switch the user's provider or model.
5. Preserve completed work and safely resume/re-run appropriate stages without duplicating results or treating errors as evidence.
6. For sufficient validated mathematics, render the answer deterministically in the required format. For no usable result, disclose failure with no fabricated mathematical output. For incomplete mixed tasks, report actual partial progress.
7. Exercise failure at each stage, including after partial streaming. A successful HTTP response, a completed stage or a critic verdict does not alone establish a correct final answer.

#### H6.4 Serious mathematical investigation: the user's primary goal

Build a workflow that can turn a difficult problem into concrete, checkable work:

- Establish the mathematical goal and assumptions; distinguish a status lookup from an explicit attempt.
- Compare plausible approaches and pursue at least one beyond a list of method names when the model/tools are healthy.
- Develop explicit intermediate claims; provide proofs or clearly mark their unresolved premises.
- Use computations for bounded questions and counterexample searches, with method, precision, range and limitations.
- Critique candidate steps for circularity, hidden equivalent assumptions, domain changes and unjustified analytic operations; attempt meaningful repair or an alternative route.
- Use research for an identified need, such as an unstated theorem, current acceptance status or novelty attribution. Read relevant primary material instead of collecting generic keyword matches.
- Formalize suitable supported lemmas accurately and state the scope actually checked. Formal verification of an unrelated theorem does not validate the main argument.
- Finish with the strongest established result and an exact remaining gap. Distinguish a re-derived known result from a novel result, and an argument proved in the response from something merely proposed.

Do not require a breakthrough to pass an investigation-quality test. Do require meaningful mathematical work when the request explicitly asks for it and execution succeeds. Status-only prose, repeated failed solver calls and prompt echoes do not fulfill that goal. Failed API runs are assessed separately as availability/recovery tests.

#### H6.5 Persistence, exports and instrumentation

Preserve core conversations and essential provenance. Separate disposable/rebuildable caches from durable records; use controlled quota-failure tests on test data. Inspect memory contents/trust before asserting that memory caused quota exhaustion or trusted erroneous facts.

Validate final answer text, stream assembly, rendered output, clipboard, stored answer and supported exports. Browser full-page screenshot PDFs do not establish whether Tribos's own PDF exporter preserves links or formatting; test that exporter directly.

Correlate timers and counters by run/case/claim/call ID. Label outer elapsed time, orchestration/model/tool/check time, cache use and reading/streaming boundaries. Report small rounded times honestly; 0.0s is not proof of zero latency. Resolve the unexplained P02 mismatch without labelling all later reconciled times defective.

### H7. Regression and acceptance plan

Use the actual production components and request flow. Deterministic external-boundary fixtures are appropriate; replacing the faulty interpreter/verifier with a success stub is not a regression test. Use independent mathematical oracles and metamorphic tests where useful. Do not mirror implementation logic as the oracle.

Run fresh-context tests and deliberate history/cache tests separately. Record actual model/provider/settings and cold/warm/cache state. Preserve successful features and include real legitimate research/simulation, not only tests that skip tools.

#### H7.1 Original regression groups T01-T20

These preserve the earlier reproduction prompts. For an explicit sustained research request, apply T34/T42 as well: a correct open-status sentence alone is not acceptance for that request.

#### T01 — Original Collatz proof request with negative simulation wording

~~~text
Start with any positive integer n. Repeatedly apply these rules:

- If n is even, replace it with n/2.
- If n is odd, replace it with 3n + 1.

Prove or disprove that this process eventually reaches 1 for every positive integer.

Give a rigorous mathematical justification. Checking examples, running simulations, or assuming that the sequence eventually decreases does not establish the claim for every positive integer.
~~~

Acceptance: recognizes the proof/status task; no ODE/simulation clarification; no invented universal proof or counterexample; accurate open-status explanation and limits of numerical evidence.

#### T02 — Controlled wording variant

Use T01 with only its last sentence removed, retaining "Give a rigorous mathematical justification."

Acceptance: materially consistent intent and mathematical status. Run independently from T01 and record memory/cache state. Add paraphrases with negation, quotations, and hypothetical mentions to prevent brittle keyword fixes.

#### T03 — Short Collatz evaluation and cycle

~~~text
Define T(n) = n/2 for even positive integers and T(n) = 3n + 1 for odd positive integers.

Compute T(1), T(2), and T(4).

Then write the cycle starting at 1, with each arrow representing exactly one application of T.

Answer in at most 40 words.
~~~

Acceptance: T(1)=4, T(2)=1, T(4)=2; cycle 1 -> 4 -> 2 -> 1. No solving for a scalar T, no negative/fractional starting-value "solution," no proof/literature pipeline needed.

#### T04 — Function definition and substitution proof

~~~text
Let f: R -> R be defined by f(x) = x^2 + 1.

1. Compute f(2).
2. Prove that f(x) - x^2 = 1 for every real x.

Answer in at most 50 words.
~~~

Acceptance: f(2)=5 and the justified identity. Both requested claims can be checked from the given definition. No x(f-x) result, undefined-function error, or unmatched correct substitution. Repeat with the original Unicode notation as well.

#### T05 — False universal claim

~~~text
Prove that n^2 + n + 41 is prime for every nonnegative integer n.

Give a rigorous proof in at most 80 words.
~~~

Acceptance: explains the claim is false with n=40 giving 1681=41^2, or another valid integer counterexample. Disproof is completed, not a failure to deliver an impossible proof. If n=41 is also used, its local assignment must be evaluated independently.

#### T06 — Independent bindings and exact two-line answer

~~~text
Evaluate n^2 + n + 41 in two independent cases:

Case A: n = 40.
Case B: n = 41.

Keep each assignment local to its case.

Answer in exactly two lines, giving the value and a factorization for each case.
~~~

Acceptance:
~~~text
A: 1681 = 41 * 41
B: 1763 = 41 * 43
~~~

Equivalent correct factorizations are acceptable, but the visible final answer must have exactly two requested lines and no extra answer text. Independently validate both values with case-aware evidence. Reverse case order and rename n in additional cases.

#### T07 — Literal output with Search on

~~~text
Return exactly the following two lines as plain text. Preserve the newline and add nothing else:

ALPHA
BETA
~~~

Acceptance: exact LF-normalized payload "ALPHA\nBETA", visible as two lines, without extra content. No literature, factual NLI, math solver, critic debate, or grounding warning. Verify raw text, stream assembly, DOM rendering, clipboard, stored response, and export.

#### T08 — Search-off enforcement

Repeat T07 with Search off. Also exercise a self-contained numerical request and all applicable workflow entry points.

Acceptance: no external retrieval calls, including academic adapters and automatic follow-ups. Cached results must not be presented as fresh research or accidentally attached from another run. Document behavior for a genuine research request while search is disabled rather than silently ignoring the setting.

#### T09 — Format controls and structured responses

Use new literal strings, three-line text, preserved indentation, valid JSON-only output, and short word limits. Include Bangla or other supported Unicode text.

Acceptance: validate the exact requested contract after the final revision and after rendering/export. Do not satisfy tests by hardcoding ALPHA/BETA.

#### T10 — Function/branch/domain generalization

Use renamed functions, different polynomials, explicit scalar multiplication, piecewise definitions, negative/zero inputs where allowed, and positive-integer-only functions.

Acceptance: preserve application versus multiplication and respect branch/domain conditions. Reject unsupported interpretations rather than solving a different problem. Include domain-sensitive expressions such as x/x with and without x != 0.

#### T11 — Legitimate simulation and legitimate clarification

Supply a real, fully specified simulation request, then an underspecified version missing a required initial condition.

Acceptance: the first executes the relevant computation; the second asks a minimal relevant clarification. A proof question merely mentioning simulation is not routed into this workflow.

#### T12 — Genuine primary-source research

Ask for the precise statement and limitation of Tao's Collatz theorem using the primary paper.

Acceptance: appropriate relevant retrieval, faithful logarithmic-density/almost-boundedness statement, no claim of convergence to 1 from that theorem, and source-linked support. Do not use an unrelated paper or title alone as proof.

#### T13 — Unsupported claimed proofs and source failures

Use controlled retrieved material that claims a breakthrough without a valid derivation, an unrelated but keyword-matching source, and an unavailable metadata service.

Acceptance: source relevance, acceptance status, and argument validity remain distinct. No fabricated citations, blanket acceptance of a "proof" title, or blanket rejection based only on preprint status. Unavailability is reported at its actual scope.

#### T14 — Verification states and final revision

Exercise valid, invalid, unavailable, not-applicable, unsupported, and interpretation-failed checks. Revise an answer after a real failed check.

Acceptance: consistent counts and labels everywhere; no stale findings; no "all supported" banner when checks are undecidable; no "contradicted by sources" label for a differently scoped substitution failure.

#### T15 — Incorrect-translation defense

Feed the mathematical integration layer the observed incorrect scalar/branch interpretation and out-of-domain witness.

Acceptance: interpretation fidelity fails. Local algebra success cannot produce a Pass for the original function task. Word-limit/list numerals do not become mathematical inputs.

#### T16 — Case/run/cache isolation

Execute cases in reverse order and in parallel, and execute separate conversations with the same expression but different bindings and function definitions.

Acceptance: no wrong-case result reuse, scope leakage, shared state mutation, or accidental evidence/claim association.

#### T17 — Storage quota, persistence, and recovery

Inject quota/write failures and oversized reconstructible caches into test profiles with existing conversations.

Acceptance: core user history survives; incomplete new writes are detected; cache eviction is controlled; reload/export/recovery behavior is correct. Never test destructively against the user's real history.

#### T18 — Latency, unnecessary work, and bounded retries

Profile representative copying, arithmetic, proof/status, simulation, and research requests with comparable model/provider/settings. Record cold/warm/cache behavior and phase timings.

Acceptance: self-contained copying and arithmetic trigger no automatic research. Simple operations avoid pointless critic rounds and repeated identical tool calls. Genuine research retains needed capabilities. Report measured baseline/after values without inventing universal latency promises.

#### T19 — Optional checker availability

Run with the formal checker unavailable and, if feasible, available.

Acceptance: no fabricated formal verification; ordinary applicable symbolic/arithmetic checks remain usable; N/A/unavailable is not treated as a mathematical contradiction.

#### T20 — Application-wide regression and held-out cases

Run the repository's relevant unit/integration/UI/build/lint/type checks. Exercise all actual supported workflows and provider interfaces affected by the changes.

Add held-out mathematical and nonmathematical prompts with different wording, symbols, values, output formats, and information needs. Demonstrate that the repair generalizes beyond the examples in this document.


#### H7.2 Additional regression groups T21-T45

For T22-T31, unless otherwise specified, use the exact contract: **“Return exactly three lines, one result per input in the requested order. Add nothing else.”** Use one line containing the complete solution set for the equation-solving cases.

| ID | Reproduction / variation | Expected behavior and checks |
| --- | --- | --- |
| T21 | Copy exactly three lines: CEDAR-17 / MAPLE-42 / WILLOW-08; repeat with unseen strings and Unicode. | Exact LF-normalized payload `CEDAR-17\nMAPLE-42\nWILLOW-08`; no model/research/math/NLI requirement. Keep P01's successful path. |
| T22 | Positive-integer `g(n)=n/2` if even, `5n+3` if odd; evaluate 3,8,11. | `g(3)=18`; `g(8)=4`; `g(11)=58`; preserve branches/application and independent inputs. |
| T23 | Positive-integer-only `h(n)=n/2` if even, `7n−1` if odd; evaluate 0,1,6. | h(0) undefined/outside domain; h(1)=6; h(6)=3. No false “all arguments in domain” Pass. |
| T24 | Domain {1,2,3,...}, `q(n)=n²+4`; evaluate 0,−2,3. Then change only the domain to integers. | Restricted: undefined,undefined,13. Integer-domain control:4,8,13. Reject fractional arguments only where the domain requires integers. |
| T25 | Positive-integer Collatz map; evaluate 40,41,42 independently. | 20,124,21. Repeat with reverse order, different definitions and caches. |
| T26 | `x²+1=0` over real numbers; exact one-line set notation. | `∅` or equivalent valid empty-set notation. Correct meaning plus required format survives writer failure. |
| T27 | Same equation over complex numbers. | `{−i,i}`; correct domain and completeness checks. |
| T28 | `(x²−1)/(x−1)=2` over reals. | `∅`; retain the original exclusion x≠1 and reject the apparent candidate. |
| T29 | `(x²−1)/(x−1)=x+1` over reals. | `ℝ∖{1}`; infinite set never described as “no solutions”; check original domain and identity. |
| T30 | `(x−2)²=x²−4x+4` over reals; pair with an inconsistent identity. | `ℝ` for the identity; empty set for the contradiction. A zero residual and a nonzero constant residual have different semantics. |
| T31 | `sqrt(x+2)=x` over reals; exact one-line set. | `{2}`; reject −1 against the original equation; preserve format on fallback. |
| T32 | Earlier short RH prompt: prove/disprove, acknowledge accepted status if unresolved, distinguish evidence, under 150 words. | Accurate scope, no invented proof, no variableless numerical scans, no unrelated Lean target. |
| T33 | “What is the current accepted status of the Riemann Hypothesis? Check Clay Mathematics Institute's official website. Answer in one sentence and include the source URL.” | Targeted official-source lookup, correct support/link, no conjecture-generation phase; no extra irrelevant literature to fill a quota. |
| T34 | Sustained research-attempt prompt below, under a healthy provider and separately under failure injection. | Healthy: worked mathematical investigation with checked partial results/gaps. Failed: truthful operational outcome; do not infer mathematical ability or fabricate work. |
| T35 | “There is no 150-word limit”; “remove the previous 150-word limit”; an explicit 220-250-word requirement after removing it; quoted/example word limits. | No invented 150-word cap; documented precedence and word-count policy; genuine positive limits still enforced. |
| T36 | Contrast formatting instructions, quoted user premises, tool errors, “No accepted proof is known,” and mathematical claims with negation. | Only applicable statements become factual claims; no literature-absence warning on formatting instructions; valid mathematical/source checks retained. |
| T37 | Fail planner, writer, formalizer, stream, critic, retrieval and optional checker independently; test transient recovery and persistent failure. | Preserve available validated work, correct formats and honest state; no prompt-as-results fallback, stale support or false completed run. |
| T38 | Missing `definitions.0.parameter`; invalid schema version/name; unavailable/disabled search; planner proposes an unregistered search name. | Specific bounded repair within permissions; consistent registry/capability view; no silent domain loss or Search-off bypass. |
| T39 | Give the formal pipeline an unrelated True theorem, False target, assumed conclusion, changed domain and a valid supported lemma. | Semantic mismatch is rejected even if unrelated code compiles. Valid supported proofs get scoped credit; trusted foundations distinguished from an injected conclusion axiom. |
| T40 | Revise a draft from prime-distribution prose into a status sentence; alter mathematical assumptions after a failed check. | Final claims/checks/sources/counts/coverage use the final revision; history is explicitly historical. |
| T41 | Valid disproofs, invalid out-of-domain “counterexamples,” and correct declarations that an input is undefined. | Correctly distinguish completed disproof, invalid witness, and correctly handled invalid input. |
| T42 | Bounded mathematical argument below about reflection symmetry, with a proof and explicit limitation. | Delivers actual derivations and checks; does not claim this disproves RH. Useful controlled test of proof execution. |
| T43 | A sourced status claim after retrieval and rewriting; inspect DOM href, clipboard and native exports. | Valid canonical source URL and exact supporting passage remain attached. No zero-source orphan claim when valid support exists. |
| T44 | Reproduce outer/inner timer examples with event IDs; include cache hits, invalid plans and SDK retries. | Accounting boundaries are explained/reconciled; actual attempts distinguished from logical model calls; no fabricated precision. |
| T45 | Live smoke tests with the user's configured provider, plus offline fixtures and held-out tasks. | Record actual successes/errors; blocked live execution remains blocked. Test-supported claims are not substituted for actual evidence of a live fix. |

#### H7.3 Exact sustained-investigation reproduction for T34

~~~text
Make a serious, sustained attempt to prove or disprove the Riemann Hypothesis:

Every zero s of the analytically continued Riemann zeta function with 0 < Re(s) < 1 satisfies Re(s) = 1/2.

Briefly acknowledge its accepted mathematical status, then devote the response to an actual mathematical investigation. Do not stop at “this is unsolved.”

1. Establish the precise statement, definitions, assumptions, and what would constitute a valid proof or counterexample.
2. Develop two or three distinct possible approaches. Explain the mathematical mechanism and main obstacle of each. Select one and pursue it beyond an outline.
3. Present a worked argument with explicit intermediate claims and derivations. Try to prove useful lemmas. Clearly distinguish known results, results proved within your response, conditional statements, and unsupported conjectures. Do not claim novelty without checking.
4. Use computation where it answers a specific mathematical question: checking an identity, testing a proposed inequality, or searching for counterexamples to an intermediate claim. Report the method, precision, range, and limitations. Finite numerical agreement cannot establish the universal claim; a suspected counterexample requires rigorous certification.
5. Check the strongest argument for circular reasoning, hidden assumptions equivalent to the original hypothesis, domain errors, and unjustified analytic operations. If a step fails, explain exactly why and attempt a repair or another approach.
6. Use formal verification for suitable intermediate statements when available. The encoded theorem and assumptions must match the mathematical claim. A failed formalization establishes no conclusion about the hypothesis.
7. Finish with your strongest supported result and the exact remaining gap. State precisely which additional lemma would complete the argument and whether you established it.

Use the configured resource budget for meaningful derivations and checks. If you cannot complete a proof, return a substantial, carefully checked partial attempt.

Provide enough detail to assess the mathematics. There is no 150-word limit.
~~~

This is the actual failed P14 task. Do not replace it with a status lookup and claim the research feature is repaired.

#### H7.4 Bounded proof-execution control for T42

~~~text
Let P(s) = (s - 1/4)(s - 3/4), where s is complex.

Prove P(1-s) = P(s), find all its zeros, and determine whether reflection symmetry about Re(s)=1/2 alone forces every zero onto that line.

Give the derivations and check the roots. Explain precisely what this establishes about a symmetry-only argument and what it does not establish about the Riemann zeta function.
~~~

Oracle: `P(s)=s²−s+3/16`; `P(1−s)=P(s)`; roots `1/4` and `3/4` are off the line. This disproves the proposed sufficiency of symmetry alone; P is not the Riemann zeta function, so it does not disprove RH. Formal checking, if used, must match these polynomial statements.

### H8. Required verification evidence and deliverables

For every issue I01-I43, deliver a row containing:

| Field | Required content |
| --- | --- |
| Status | Fixed; already fixed with evidence; partial; not reproduced; or blocked with reason |
| Reproduction | Exact request, settings, response and relevant stage/tool I/O |
| Cause | Actual source file/symbol and explanation, distinguished from hypotheses |
| Change | General repair and affected adjacent workflows/providers |
| Validation | Test IDs, commands, truthful outcomes, held-out controls and live/replay evidence |
| Remaining limits | Unavailable tools/libraries/provider checks; unsupported mathematics; unresolved data or UI behavior |

Also provide:

1. A short architecture/data-flow map and the implementation plan actually followed.
2. Implemented source changes and a complete issue-to-test mapping for T01-T45.
3. Tests that exercise real contracts and failure paths, not only exact strings or mocked success.
4. Browser-level checks for the relevant answer body, warnings, final revision state, clipboard, links, storage and native exports.
5. Before/after raw response text and representative tool/check records, including P03/P04, P09/P10, P12 and P14.
6. Comparable measured call counts, retrieval work and scoped timing. Keep difficult research capabilities; do not impose arbitrary fast-response promises.
7. Provider failure diagnosis or precise evidence of what remains blocked; preserve model choice and retry limits.
8. History-preservation, quota/reload/recovery tests and any necessary reversible migration plan.
9. A reviewable patch/branch or runnable source ZIP as the environment permits. Exclude credentials, environment secrets, dependency folders and irrelevant caches.
10. A concise final summary of what is fixed, what remains unverified and the next concrete steps.

Use the repository's actual documented commands and supported platform. The supplied repair summary mentions pytest, Ruff, Bandit, web tests, type checking, ESLint and a Next build; confirm the current commands rather than assuming those paths or counts still apply.

**Completion bar:** a correct-looking final sentence is not sufficient if the system checked the wrong mathematical problem, lost an output constraint, attributed stale evidence, misreported completion, or failed to preserve data. Conversely, honest unknown/unavailable states are preferable to false certification and must not be “repaired” by hiding them.

### H9. Evidence inventory and reading boundaries

This report is self-contained for reproduction. The following exact filenames identify the original supporting attachments. They are evidence captures, not source-code files.

#### H9.1 Historical captures

The B/R register above identifies twelve primary captures and two supplementary screenshots. The six-page R2 capture contains an earlier answer; it is not an additional independent run.

#### H9.2 Post-repair image captures

| Run | Original supporting filename(s) |
| --- | --- |
| P01 | `{ED2EE526-62D5-472E-B90E-F4C35CF42B20}.png` |
| P02 | `{2261FD1D-FCE3-4778-8C03-B425C69EABB3}.png`; `{25127AB7-C8CE-4791-A302-BC3789C7BE74}.png`; `image(20261025-121227).png`; `{FEE308BB-3C64-49F3-A1D1-E2FFAA442845}.png`; `{5F3B0DD1-0AD9-4323-A75D-FB09EF2EC552}.png`; `{FD6E95E1-FD0C-44A2-876F-1F02F910FA01}.png` |
| P03 | `{3B178E2C-FCFB-49E0-ACBE-8175386345D1}.png`; `{E6D71CB5-E2BD-427A-8B59-5FD82AE27AD0}.png`; `{500DCF88-6286-47D5-B1FB-9003064E3B30}.png` |
| P04 | `{85A93279-9E6A-4BD4-B8D3-6421A9E6865D}.png`; `{FDB7A11E-274E-4053-A052-CC25F8DE19B4}.png`; `{01E9C2CD-B3AB-45A7-8551-DFB5C818AA86}.png` |

#### H9.3 Post-repair PDF captures

| Run | Original supporting filename |
| --- | --- |
| P05 | `gofullpage-localhost-3000-2026-10-25-18_47_38.pdf` |
| P06 | `gofullpage-localhost-3000-2026-10-25-18_54_08.pdf` |
| P07 | `gofullpage-localhost-3000-2026-10-25-18_56_30.pdf` |
| P08 | `gofullpage-localhost-3000-2026-10-25-19_02_25.pdf` |
| P09 | `gofullpage-localhost-3000-2026-10-25-19_08_27.pdf` |
| P10 | `gofullpage-localhost-3000-2026-10-25-21_50_38.pdf` |
| P11 | `gofullpage-localhost-3000-2026-10-25-21_57_51.pdf` |
| P12 | `gofullpage-localhost-3000-2026-10-25-22_09_03.pdf` |
| P13 | `gofullpage-localhost-3000-2026-10-25-22_22_51.pdf` |
| P14 | `gofullpage-localhost-3000-2026-10-25-22_24_55.pdf` |

Additional supplied document: `Pasted markdown(3).md`, the implementation/change summary. Treat its fixes, commits and test counts as claims to validate.

Do not use assistant-generated screenshot annotations as primary evidence; an earlier annotation altered a timing label. Original captures and actual backend/raw records take precedence. Screenshots cannot establish actual network-request counts, true end-to-end timings, cache origin, hidden link targets or source-code causes by themselves.

#### H9.4 Primary references used to check mathematical/status semantics

- [Clay Mathematics Institute: Riemann Hypothesis](https://www.claymath.org/millennium/riemann-hypothesis/) — official open-status statement checked during this evaluation.
- [Tao: Almost all orbits of the Collatz map attain almost bounded values](https://arxiv.org/abs/1909.03562) — precise limitation of the earlier claimed “almost all reach 1” result.
- [Tao's accompanying explanation](https://terrytao.wordpress.com/2019/09/10/almost-all-collatz-orbits-attain-almost-bounded-values/).
- [Lean: False and foundational propositions](https://lean-lang.org/doc/api/Init/Prelude) and [tactic reference](https://lean-lang.org/doc/reference/latest/Tactic-Proofs/Tactic-Reference) — False is a contradiction proposition; a theorem name does not encode RH.
- [RFC 9110: HTTP 500](https://www.rfc-editor.org/rfc/rfc9110.html#section-15.6.1) — internal error semantics; the observed generic response does not diagnose its origin.

Check any changing status or provider contract again when implementing. Bibliographic labels, numerical demonstrations, compiler rejection and critic consensus have different evidential roles.
