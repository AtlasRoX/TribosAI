# Tribos: complete evaluation report and codebase repair prompt

Updated: **25 October 2026 (Asia/Dhaka)**. Coverage: **26 observed runs** across the original evaluation, the first retest, and 14 runs following the supplied repair report.

**Use:** attach the current Tribos repository or source ZIP and this entire Markdown file to your coding agent. Copy the short prompt below if you want an instruction block; the rest of this file is its issue report and acceptance specification.

**Evidence boundary:** this is an analysis of supplied responses, screenshots, PDFs, traces, and a repair summary. The current repository and backend logs were not supplied or inspected. File paths quoted from the repair summary are investigation hints, not verified source locations. Proposed causes must be established from code and reproduction. No implementation is claimed in this document.

## 1. Copy-paste repair prompt

~~~text
Audit and repair the complete current Tribos codebase using the attached report.

Read this entire report and the repository's instructions before editing. Inspect the actual request-to-response path across input interpretation, planning, workflow choice, model/provider calls, tool schemas and permissions, mathematical representation, computation, formal checking, evidence retrieval, claim verification, final revisions, frontend state, copying/export, and persistence.

Reproduce the reported issues through production entry points. For each issue I01-I43, record its current status, actual files/symbols, cause, implementation, and validation. Multiple issue reports can share one root cause. Fix those causes generally across supported queries and workflows; do not hardcode the supplied prompts, coefficients, function names, or problem titles. Preserve unrelated user changes, model/provider choices, working features, and saved conversations.

Prioritize:
1. Prevent false mathematical verification: preserve original domains, branches, assumptions, function application, case scope, and denominator exclusions.
2. Ensure a formal theorem encodes the user's actual statement. Never substitute an unrelated True/False goal or assume the conclusion.
3. Diagnose the recurring completion failures from real backend/provider logs and sanitized requests. Distinguish provider errors, request incompatibility, and application errors. Add bounded recovery appropriate to the actual client, without multiplying SDK and application retries.
4. Repair failure handling: return available validated results in the requested format; when no result exists, report the failed stages honestly. Never present an echoed prompt as computed evidence.
5. Correct negated/revoked output constraints and distinguish instructions, quotations, error messages, mathematical assertions, and literature claims.
6. Represent finite, empty, infinite, conditional, and unresolved solution sets correctly; add applicable independent checks for general sets.
7. Reconcile source links, final-answer claims, coverage, verification, and terminal status after every revision.
8. Select workflows from the actual task. A named hypothesis is not automatically a request to generate hypotheses. Preserve explicit requests for substantial mathematical investigation.

The user wants serious attempts on difficult/open mathematics: worked arguments, useful lemmas, targeted computations, appropriate research, checks, repairs, and precise remaining gaps. Research and debate are legitimate when they advance that goal. A status-only answer does not satisfy an explicit research-attempt request. Do not invent a proof, treat finite tests or critic agreement as proof, or promise to resolve an open problem.

Implement the repairs; do not stop at an audit or plan. Validate the regression groups T01-T45, held-out variants, and the repository's relevant tests/build checks. Test healthy and failing provider conditions separately. A failed completion call is an operational failure, not evidence of mathematical inability.

Deliver a reviewable patch/branch or updated source ZIP, plus a report mapping every issue and test group to fixed, already fixed, partial, not reproduced, or blocked status. Include exact commands/results, before/after examples, measured comparable timings, remaining limitations, and recovery/migration notes. Do not close issues by hiding warnings or weakening checks. Do not deploy or destructively migrate real user data.
~~~

## 2. What the accumulated evidence establishes

### 2.1 Highest priorities

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

### 2.2 Improvements that must be preserved

- P01 correctly returns the three supplied lines through a literal-direct route, with no research.
- P02/P05 correctly apply piecewise functions to valid inputs; no case contamination is visible in those runs.
- P06/P07 correctly distinguish real and complex solution sets for `x² + 1 = 0`.
- P08 returns the correct empty set for a rational equation whose apparent candidate is excluded.
- P11 returns the correct mathematical root `x = 2`; its failure is later generation/format/status handling.
- P12 correctly acknowledges the open status and avoids claiming a proof. Its mathematical honesty must be retained.
- P13 executes web searches successfully. Therefore the earlier unregistered-search error is not evidence that all search paths are universally broken.
- Later panels explicitly describe evidence-support scores as not probabilities, and the 98% mathematics badge as a held-out expression benchmark (`n=43`). These are not current-answer confidence.
- Some recent timer differences reconcile exactly: `3.5 + 1.6 = 5.1`, `3.5 + 3.4 = 6.9`, and `3.5 + 5.1 = 8.6` seconds. Different scope is a supported explanation in those runs.

### 2.3 Claims of fixes versus live evidence

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

## 3. Complete observed-run register

Scores are human diagnostic judgments, not calibrated benchmarks, probabilities, release thresholds, or a single app-wide rating. The fixed later rubric is correctness 40, instructions 20, verification/status 25, routing/efficiency 15. The original first five scores were informal. Do not average runs with different prompts/settings into a model capability estimate.

### 3.1 Original evaluation and first retest: B1-B5, R1-R7

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


### 3.2 Runs following the supplied repair report: P01-P14

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

## 4. Earlier issue reports I01-I23, retained with current-status context

The reports below preserve the original reproductions and distinctions. Historical observations are not assertions that every symptom still occurs today. Use Section 2 and the later issues to determine current evidence; reproduce against the attached code before closing an issue.

### I01 — Conflicting intent representations and mishandled negation — P1

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

### I02 — Unnecessary clarification and false missing-input detection — P1

The system asks for ODE equations, initial conditions, a standard physical system, and integration time even though the requested discrete map and universal mathematical question are fully specified.

Clarification should occur only for missing information that materially blocks the actual requested operation. Test legitimate underspecified simulations too; do not globally disable clarification.

### I03 — Incorrect computation gating — P1

R6 explicitly requests numerical evaluations at n=40 and n=41, yet the trace says Calcula is skipped because "no numerical computation requested."

Inspect the actual responsibilities of Calcula/Axiom and the routing explanation. Even if another tool can perform the arithmetic, the recorded intent explanation is inconsistent. Support task-appropriate exact computation and truthful skip reasons.

### I04 — Research is applied to requests that need no external knowledge — P1

**Current-status annotation:** Current evidence: P01-P11 generally skip unnecessary research. Preserve that improvement while repairing mixed-information requests (I38). Search-off enforcement still needs direct testing.

R7 asks only to reproduce two supplied lines. Nevertheless:
- Duration: 18 seconds.
- Steps: 11.
- Literature card: 83 articles.
- An evidence/grounding warning is generated.

R3, R4, R5, and R6 also retrieve literature for supplied arithmetic or definitions. "Direct workflow" does not visibly provide a genuinely lightweight route.

Search availability should permit appropriate research rather than require it. Exact copying, supplied-data transformations, and self-contained arithmetic need no external literature unless the user separately requests it. Enforce Search off on the server and client, and audit all retrieval paths, including academic adapters and follow-up tools.

### I05 — Excessive orchestration, retries, and critic escalation — P1

Observed:
- B2 selects Debate for a status question, reasoning that the user wants new conjectures.
- B3/B4 and R4/R6 use heavyweight planning or repeated mathematical strategies for trivial operations.
- R6 repeats a simplified value through multiple strategy steps.
- Several runs escalate to multiple critics despite straightforward supplied definitions.
- Ultra effort appears alongside these requests, but it has not been established as the cause.

Inspect budgets, retry criteria, progress detection, repeated call deduplication, and workflow selection. High effort should raise an available ceiling, not impose unnecessary minimum work. Enumerating two simple tasks should not automatically require a multi-agent or research workflow. Escalate only when a concrete unresolved issue warrants it.

Do not create unsafe timeouts that truncate genuinely difficult research.

### I06 — Retrieval relevance and query construction fail — P1

Examples visible in the captures:
- R6's "two independent cases" produces US court-case results, including National Federation of Independent Business v. Sebelius.
- B2 includes basic odd/even teaching material.
- R4 lists papers about the Schoenflies theorem, ergodic theory, fixed-point indices, and other subjects unrelated to direct polynomial substitution.
- Some earlier Collatz evidence includes supersymmetric QCD and unrelated mathematical papers.

These observations support poor semantic query construction/relevance filtering. They do not prove every listed paper was newly fetched or every source was irrelevant.

Build queries from the mathematical/scientific entities and actual information need. Filter and rank content for the specific claim, not shared generic words such as "case," "proof," "integer," or "function." Avoid research entirely when there is no external information need.

### I07 — Function application is confused with scalar multiplication — P1

**Current-status annotation:** Current evidence: P02/P05 preserve function application on the tested valid inputs. The earlier representation failures remain regression cases; do not declare every parser path broken today.

Observed:
- B2/B3: the checker assigns T=0.290036 and n=2.557913. Its left-side value is 0.741886854868, which equals T*n.
- B4: the displayed simplification is x(f-x), consistent with simplifying f*x-x^2 instead of using f(x)=x^2+1.
- R3: output is T=1/2, n=-2/5 rather than the requested function values.

Strong inference: function semantics are lost somewhere in parsing, tool argument construction, or mathematical representation. Locate the exact layer.

Preserve declared functions, arity, definitions, substitutions, independent symbols, and application nodes. Do not silently interpret a declared function call as implicit multiplication. Handle alternative notation, renamed functions, Unicode exponents, and equivalent explicit definitions without problem-specific exceptions.

### I08 — Conditional branches and mathematical domains are discarded — P1

**Current-status annotation:** Current evidence: P03/P04 reconfirm domain loss and false certification (I24), even though several valid-input piecewise examples pass.

R3's result exactly matches solving the WRONG simultaneous system:

~~~text
T*n = n/2
T*n = 3*n + 1
~~~

Its solution T=1/2, n=-2/5 violates the requested positive-integer domain. The user supplied conditional branches, not simultaneous equations in two unknown scalars.

Represent piecewise definitions, branch predicates, parity, domains, and quantifiers explicitly. Validate applicability before solving and before accepting a result. A tool output about a mistranslated or out-of-domain problem must not be called a counterexample to the original statement.

### I09 — Independent cases and local bindings are not reliably preserved — P1

B5 and R5:
- A valid example at n=40 is followed by a separate valid example at n=41.
- The verifier labels n=41 contradicted and says n evaluates to 40.

R6:
- User explicitly requests local assignments in two independent cases.
- Final values are correct: 1681 and 1763.
- Both case checks are planned, but the visible mathematical trace repeatedly returns 1681 and does not demonstrate separate validation of 1763.

Hypotheses: global substitution state, overwritten local environments, missing case IDs, incorrectly keyed cache entries, output aggregation selecting one result, or verification using bindings from another claim. Reproduce and localize rather than choosing one explanation without evidence.

Scope definitions and assignments by request, subtask, case, and claim. Preserve those identities through tool calls, caches, synthesis, exports, and verification. Test reversed case order, renamed variables, concurrency, and repeated expressions under different bindings.

### I10 — Valid transformed calculations cannot be linked to the original task — P1

R4 correctly verifies:

~~~text
x^2 + 1 - x^2 = 1
~~~

Yet its panel says the tool call could not be matched to the original problem, despite the supplied definition f(x)=x^2+1. The final answer is correct but its checking provenance is incomplete.

Track a justified dependency from the declared definition to substitution, transformed expression, computed result, and requested claim. Match equivalent expressions using appropriate mathematical reasoning under the original assumptions. Do not demand literal string identity, and do not accept unrelated expressions merely because a local check passes.

### I11 — Independent checks can validate the wrong problem — P1

Observed Pass labels include:
- "Equations match the problem."
- "Identity matches the problem."
- "Each solution satisfies the original equation(s) by substitution."
- "Solution count re-derived from the original system."

Some of these appear beside out-of-domain or incorrectly parsed results. Checking the same mistranslated expression twice is not independent verification of the user's question.

Introduce separate checks for interpretation fidelity, assumption/domain preservation, computational correctness, and coverage of the requested result. Reuse of a parser must not be misrepresented as independent protection against that parser's defects.

### I12 — Coverage scanning confuses formatting instructions with mathematics — P1

The checker reports missing mathematical inputs such as:
- "4, 40" when 4 is a requested function argument and 40 is a word limit.
- Earlier captures similarly mention instruction numbers such as 100.

Understand number roles rather than comparing bags of numerals. Separate mathematical constants/arguments from list indices, word limits, timestamps, and formatting constraints. Missing a requested argument is meaningful; missing a word-limit numeral from a symbolic expression is not.

### I13 — Claim extraction and verification status aggregation are inconsistent — P1

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

### I14 — Completion and grounding graders misunderstand the requested operation — P1

**Current-status annotation:** Goal clarification: a status-only request is fulfilled by an accurate unresolved-status answer. An explicit sustained investigation requires worked approaches/lemmas/checks and a precise gap (Section 6.4 and T34/T42); status-only prose is insufficient for that different request.

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

### I15 — Research claims and mathematical explanations contain substantive errors — P1

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

### I16 — Source acceptance, citation integrity, and evidence grading need repair — P1

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

### I17 — Exact output constraints are not preserved end to end — P1

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

### I18 — Final-answer constraints and template expansion lack consistent enforcement — P2

Trace word counts are sometimes reported before revision. Later responses add executive summaries, evidence limitations, diagnostic commentary, and repeated proof sections.

No universal word-limit violation is asserted from screenshots: mathematical tokenization makes some counts ambiguous. Verify the FINAL serialized response against the requested constraint using a documented counting rule. Validate exact line counts and machine-readable formats deterministically.

Avoid generic academic sections on literal copying or trivial calculation. Do not let internal tool failures dominate an otherwise simple answer. Preserve material limitations when they affect confidence in the answer itself.

### I19 — Confidence and verification signals are poorly separated — P1

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

### I20 — Storage quota handling removes saved conversation content — P1, investigate impact promptly

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

### I21 — Memory writes and cached trust may amplify other failures — P1 audit target

**Current-status annotation:** Current evidence: P13/P14 report ten/five memory nodes written. The content, trust level, quota impact and subsequent reuse were not inspected.

Small requests visibly write approximately five to seven memory nodes. Meanwhile, verification is sometimes wrong or incomplete and storage warnings recur.

Confirmed: writes are reported; storage warnings recur.
Unconfirmed: those memory writes caused the quota issue or stored the erroneous intermediate results as trusted facts.

Inspect memory policy, provenance, size limits, and trust handling. Avoid persisting unverified solver artifacts as established knowledge. Store only useful, appropriately scoped information; preserve verification status and definitions. Invalidate incompatible computed caches after representation changes without deleting user-authored history.

### I22 — Traces, timing, counters, and evidence provenance are difficult to reconcile — P2

**Current-status annotation:** Current evidence: several later outer/inner differences reconcile when the reading phase is included (Section 2.2). The P02 11s/38s observations still need actual run/call correlation. Different clocks and rounding are not automatically defects.

Examples requiring inspection:
- A run header shows a different duration from a run-budget/timing panel.
- Some calls show 0.0 s.
- Some agent budgets show zero tool calls while the UI reports retrieved literature and web results.
- A reading stage remains "not reported as finished" after a clarification is delivered.
- Repeated strategy outputs may lack visible case attribution.
- A literature card's total is easily confused with freshly retrieved or verified sources.

Different accounting boundaries, cache hits, or agent-vs-backend counters may explain some differences. Do not label all differences bugs without checking.

Use documented timing boundaries and request/run/case/claim/tool-call IDs. Attribute retries, cache hits, rejected calls, streaming, and checks accurately. Distinguish retrieved documents from relevant passages, cited documents, and actually supported claims. Make genuine error/terminal states consistent and observable.

### I23 — Optional checker capability and UI presentation require appropriate treatment — P2

**Current-status annotation:** Current evidence: P12 actually invokes Lean and receives compiler output. The current trust-critical failure is the unrelated False target (I33), not mere installation availability. The supplied summary says Mathlib is absent; inspect actual capabilities.

Lean 4 is shown as unavailable because it is not installed/configured. The UI mentions TRIBOS_LEAN_PATH.

Absence of an optional checker is not itself proof that the application is defective, and ordinary arithmetic should not depend on installing Lean. Detect capabilities, report unavailable checks honestly, and avoid claiming a formal proof when none ran.

Likewise, a panel titled "Verified mathematics" should not suggest the entire user question is verified when only an unrelated or unmatched expression has passed a local check. Present the scope and limitations clearly. Avoid tiny or undocumented benchmark samples functioning as trust badges.


## 5. Additional and reconfirmed issue reports I24-I43

These entries extend the earlier findings. They are not necessarily twenty independent root causes.

### I24 — Explicit domains are ignored and falsely verified — P0

**Evidence:** P03 returns h(0)=0 although h is defined only on positive integers. P04 returns q(0)=4 and q(−2)=8 although q has domain {1,2,3,...}. Both display Domain Pass and Verified. P04 confirms the failure without piecewise branches.

**Repair:** enforce membership in the original declared domain before evaluation; preserve it through representation, tool arguments, synthesis, and independent checking. Validate the interpreted domain against the user's definition, not only against the same potentially defective tool payload. A correctly returned “undefined” is a complete answer to an invalid-input evaluation; distinguish “input is valid” from “invalid input was correctly rejected.”

**Acceptance:** T23/T24 and domain-changing controls pass. No valid arithmetic substitution may override an invalid function application. Extends I08/I11.

### I25 — Planner arguments fail a registered tool schema — P1

**Evidence:** P04 shows `definitions.0.parameter: Field required`. The later computation still returns out-of-domain values. The captures do not establish whether the missing parameter caused the domain failure.

**Repair:** locate the actual planner/tool contracts, schema versions, and repair path. Validate definition name, parameter, domain and branches before execution; make a bounded, specific schema repair or return an accurate interpretation failure. Preserve valid definitions during recovery. Do not silently weaken a domain or discard a malformed definition to obtain a successful call.

**Acceptance:** T38 injects missing/renamed fields and proves production recovery or truthful refusal.

### I26 — Recurring completion errors lack a demonstrated diagnosis and resilient execution path — P1

**Evidence:** drafting returns `HTTP 500 / Failed to generate completions` in P05/P06/P11. In P14 the planner fails, and formalization/drafting explicitly report HTTP 500. Other runs succeed, so universal service unavailability is not established. The repair summary also records earlier NVIDIA errors.

**Repair:** correlate actual run IDs with backend logs, provider endpoint/model, redacted request shape/options, request IDs, status/body, streaming phase, timeouts and retry attempts. Replay a minimal request and the sanitized failing request through the same configured client. Distinguish provider/inference faults from request-dependent failures and application exceptions. Generic 500 text does not identify the cause. Preserve provider choice; use another provider only where already configured and authorized.

**Acceptance:** T37/T45 exercise healthy, transient, persistent, streaming and request-specific faults. Avoid multiplied SDK/application retries, unlimited retry loops, or secret logging.

### I27 — Valid computed results depend on a writer and lose output format during fallback — P1

**Evidence:** P05 retains the correct three equalities but labels the answer Partial. P06/P11 retain correct mathematical meaning as “no solutions”/“x=2” but violate requested set notation after writer failure. P02 spends 37 displayed seconds drafting after a 0.02s computation.

**Repair:** provide a deterministic renderer for supported validated result types and output contracts, including sets, undefined inputs, ordered equalities and plain text. Keep writer availability distinct from mathematical correctness and task completion. Mark complete only when the available results actually fulfill the whole request; a mixed request with missing explanation can remain partial.

**Acceptance:** healthy and writer-failing executions produce the same contract-compliant mathematical payload when the tool result is sufficient.

### I28 — Empty-result fallback echoes the prompt as computed evidence — P1

**Evidence:** P14's “Results gathered for…” reproduces the research instructions and says these are “tool results as computed”; no computed mathematical results are shown. The partial-error notice is honest, but the purported results are misleading.

**Repair:** type user input, model output, tool output and diagnostics separately. A request summary may appear as a request, never as evidence or a computed result. If nothing was produced, state which stages failed and that no mathematical result is available. Preserve useful partial work and allow continuation according to existing run architecture.

**Acceptance:** T37 with zero usable results yields an honest failed run, not a prompt echo, fabricated evidence, or an answer fabricated from the question's conjecture.

### I29 — Removed/negated output constraints remain active — P1

**Evidence:** P14 says “There is no 150-word limit.” Tribos reports “Requested format not met: 350 words, at most 150 allowed.”

**Repair:** investigate both negation interpretation and stale inherited contracts. Give constraints explicit scope, source, polarity and revision/precedence. A current instruction removing a prior limit must not become the limit itself. Numerals in examples or quotations must not create constraints.

**Acceptance:** T35 tests no limit, explicit removal, later replacement, quoted limits, multilingual paraphrases, and genuine positive caps. Extends I01/I12/I18.

### I30 — Formatting instructions are treated as literature absence claims — P1

**Evidence:** P14 marks “There is no 150-word limit” unsupported because “a literature-wide absence cannot be established from one search.” It scores the copied instruction as a factual claim despite the generation failure.

**Repair:** identify text origin and role before checking it. Exclude instructions, quoted prompts, formatting metadata and error messages from factual/literature entailment. Distinguish mathematical negation, a historical/acceptance-status claim, and a literature-wide absence claim. Do not apply one rule to every sentence containing “no.”

**Acceptance:** T36 verifies both exclusions and real absence/status claims; do not disable factual verification globally.

### I31 — Empty finite roots are conflated with an empty solution set — P1

**Evidence:** P09 says “no solutions” while showing `Union(Interval.open(-oo,1), Interval.open(1,oo))`. P10 says “no solutions (general solution set: Reals).” Both final sets are mathematically correct.

**Repair:** represent no solutions, finite solutions, infinite/parametric families, conditional sets and unresolved results distinctly. An empty list of isolated roots does not by itself establish an empty solution set. Inspect the actual solver's return semantics and conversion paths rather than guessing a particular implementation.

**Acceptance:** T26-T31 and held-out identities/contradictions have consistent tool, final-answer and export descriptions.

### I32 — Independent checking does not cover supported infinite sets — P1

**Evidence:** P09/P10 only establish equation matching and explicitly report no independent result check. The partial-verification label is appropriate; the missing coverage is the issue.

**Repair:** add sound checks where feasible: original-domain preservation, symbolic identity under assumptions, exclusions, and equivalence between the proposed set and the original equation. Finite sample substitution is insufficient for completeness of an infinite set. Retain unavailable/unsupported states when no sound checker exists.

**Acceptance:** T29/T30 check ℝ∖{1} and ℝ independently; wrong excluded points, endpoints and conditions are rejected.

### I33 — Formal proof target does not encode the mathematical claim — P0

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

### I34 — Planner/tool availability and recovery disagree — P1

**Evidence:** P12 wants four searches but rejects all with `tool 'web_search' is not registered`, while the summary says no follow-up calls were needed. P13 executes three follow-up searches successfully under an explicit website lookup.

**Repair:** give the planner an accurate typed registry for the run's enabled capabilities. Validate names/schemas and distinguish disabled-by-user, unavailable, unknown, rejected, attempted and completed. Recover from an invalid planned name only within already-authorized capabilities. Do not bypass Search off by registering a blocked tool.

**Acceptance:** T38 tests the same need across search settings and workflow boundaries; a rejected necessary plan cannot be reported as unnecessary.

### I35 — Named mathematical hypotheses trigger conjecture-generation intent — P1

**Evidence:** B2 and P12/P13 select Debate on the rationale that the user asks for new hypotheses. P13 asks only for current accepted status and a URL.

**Repair:** separate entity names from requested actions. Classify status lookup, proof, disproof, proposed-method critique, generation of conjectures, and sustained investigation. Debate can be appropriate for a serious investigation; the problem is the incorrect stated intent and unrelated work.

**Acceptance:** T32-T34 plus held-out named conjectures and nonmathematical “hypothesis” uses preserve the requested operation.

### I36 — Mathematical exploration is subjected to an irrelevant dynamics prerequisite — P1

**Evidence:** P12-P14 say no testable hypotheses could be formed because there is no dynamical system with parameters to perturb. P13 spends 2m3s in that phase for a one-sentence status lookup.

**Repair:** use domain-appropriate requirements. Mathematical conjectures, proof strategies and counterexamples do not universally require an ODE or perturbable physical parameters. Skip unrequested phases, and require only inputs genuinely needed by the selected operation.

**Acceptance:** status lookup skips hypothesis generation; mathematical investigation can pursue lemmas; actual simulations still enforce their legitimate required inputs.

### I37 — Critic work does not reliably terminate on useful acceptance — P1

**Evidence:** P12 records accept verdicts from two responding critics in round one and again in round two; a physicist has no usable reply. Debate takes 3m1s. P13 critics request additions about numerical verification despite a one-sentence status/URL task.

**Repair:** define acceptance, material criticism, abstention/failure, required coverage and stop conditions. Additional rounds need an unresolved concrete issue. Evaluate critic suggestions against user scope and mathematics. Agreement is not proof; a nonresponse is not an acceptance.

**Acceptance:** bounded critic fixtures test early acceptance, useful revision, failed critics and contradictory advice without removing debate from legitimate research.

### I38 — Mixed mathematical and external-information needs are not handled coherently — P1

**Evidence:** P12 declares web search unnecessary, while its planner explicitly needs current status and partial-result references. P13's explicit source request enables search. The repair summary's broad claim that proofs need no search is too coarse for mixed tasks.

**Repair:** evaluate need per subtask: supplied-data derivation may be self-contained; current acceptance status, literature attribution, novelty checking and use of unstated specialist results may require retrieval. Respect Search off and label unverified external claims. A mathematical topic alone neither mandates research nor forbids it.

**Acceptance:** T12/T13/T32-T34 exercise status-only, derivation-only and mixed research with both search settings.

### I39 — Coverage/status summaries do not reflect the requested operation or final answer — P1

**Evidence:** P12 reports 0/4 subquestions answered while final prose addresses the four planned topics. P13 marks the source URL unaddressed alongside a visible source label. The actual URI is not recoverable from the PDF, so its validity is unresolved.

**Repair:** separate execution of planned tools, completion of user deliverables, and verification of answers. Model dependencies and evaluate final output, including actual link destinations. If a counter tracks only tool-backed subtasks, label that scope instead of saying none were answered.

**Acceptance:** T40/T43 distinguish complete-but-unverified answers, unavailable checks, genuinely missing deliverables, and valid rendered links.

### I40 — Counter-evidence is attached to a claim absent from the final revision — P1

**Evidence:** P13's final answer is a short RH status statement; its counter-evidence panel repeatedly checks a different claim about prime distributions and structured/random characteristics.

**Repair:** bind claims, passages, check results and warnings to answer revisions. After rewriting, re-extract/reconcile claims and invalidate stale associations. Historical checks may be retained in a clearly labelled history, not attributed to the current answer.

**Acceptance:** T40 changes claim content after critique and proves final panels, exports and counts refer to the final version.

### I41 — Retrieved sources are not associated with the final sourced claim — P1

**Evidence:** P13 performs several searches and displays a CMI-labelled final source, yet the support panel reports `N sources: 0`, `Supporting sources: 0` and no NLI check.

**Repair:** trace source IDs through retrieval, canonical URLs, passages, draft citations, revision and claim extraction. Verify the actual official passage supports the statement. Metadata or a source label alone is not support. A sourced historical/status statement must not inherit a broken claim-source mapping. An official page classifying a problem as “Unsolved” can support a qualified report of accepted status; it does not establish that a proof is impossible or that no proof could exist.

**Acceptance:** T33/T40/T43 preserve a correct link and supporting passage through rewriting, copying and export; wrong or unrelated links fail accurately.

### I42 — Verification summaries and warning badges obscure check scope — P2

**Evidence:** P01 talks about cited identifiers on a copy task. P02/P04 combine “retrieved evidence” wording with a no-search mathematical route. Several correct mathematical answers say no claims could be checked globally while the math card shows successful checks. A “needs a look” badge appears without an explained warning in the expanded view.

**Repair:** derive scoped summaries from applicable checks. No literature claims is normal for self-contained mathematics. Distinguish mathematical verification, source support, formatting and optional-check availability; expose an actual reason for a warning badge. Preserve the correctly explained benchmark/support-score distinctions.

**Acceptance:** T14/T21/T26/T43 ensure truthful summaries without falsely upgrading unchecked results or hiding real failures.

### I43 — A failed run is labelled completed evidence synthesis — P1

**Evidence:** P14 honestly reports planner/writer failures and that Debate was not reached, yet also says “Completed: evidence synthesis”; its answer mostly echoes instructions. P05/P06/P11 show the converse problem: useful complete mathematical results are broadly called Partial because writing failed.

**Repair:** separate stage status, answer sufficiency, applicable verification, provider health and run termination. Complete, partial, failed, unavailable and cancelled states need actual completed work behind them. A stage label must not imply the user's task succeeded.

**Acceptance:** T37 covers zero results, sufficient validated results, incomplete mixed deliverables and later recovery; every UI/export/report uses consistent state.

## 6. Actual codebase investigation and implementation

### 6.1 Locate the real production path

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

### 6.2 Repair the shared contracts

Adapt these concepts to native types instead of imposing a new architecture without inspection:

- **Request:** operation and subtasks, input/quoted text roles, definitions, domains, quantifiers, case scope, information needs, search permission, output constraints and their origin/revision.
- **Mathematical result:** original problem ID, preserved assumptions/exclusions, interpreted expression, result kind, set or values, case bindings, completeness claim and justification.
- **Tool attempt:** registered capability/schema version, permission result, logical call ID, actual HTTP attempts, arguments, result/error, execution stage, timing scope and provenance.
- **Check:** exact statement/target, assumptions, result/answer revision, whether applicable and executed, outcome and limitations. Distinguish checking an interpretation from checking its arithmetic.
- **Evidence:** source/passage IDs, canonical URL, retrieval/read scope, claim ID, answer revision, relevance and support. A model-generated summary is not a retrieved primary source.
- **Answer/run:** available validated artifacts, output-contract result, requested deliverables fulfilled, failed stages and truthful terminal status. UI, clipboard/export and persistence consume the same final state.

Do not force a particular enum vocabulary, but preserve differences among valid, invalid, unknown, unsupported, unavailable, not applicable, not requested and interpretation failure. Invalid input can still receive the correct complete answer “undefined.”

### 6.3 Provider diagnosis and failure containment

1. Reproduce with actual configured model/endpoint/settings. Save redacted diagnostic information and provider request IDs; do not print or export credentials.
2. Compare a minimal completion and the failing request. A minimal success with a request-specific failure narrows the cause; it does not by itself prove the application or provider is at fault.
3. Inspect unsupported options, context/token limits, structured output/tool schemas, streaming and message conversion against the actual provider contract. Verify effective options, not just configuration labels.
4. Implement bounded transient-error recovery with a total deadline. Respect existing SDK retries and provider guidance; classify non-retryable failures. Do not silently switch the user's provider or model.
5. Preserve completed work and safely resume/re-run appropriate stages without duplicating results or treating errors as evidence.
6. For sufficient validated mathematics, render the answer deterministically in the required format. For no usable result, disclose failure with no fabricated mathematical output. For incomplete mixed tasks, report actual partial progress.
7. Exercise failure at each stage, including after partial streaming. A successful HTTP response, a completed stage or a critic verdict does not alone establish a correct final answer.

### 6.4 Serious mathematical investigation: the user's primary goal

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

### 6.5 Persistence, exports and instrumentation

Preserve core conversations and essential provenance. Separate disposable/rebuildable caches from durable records; use controlled quota-failure tests on test data. Inspect memory contents/trust before asserting that memory caused quota exhaustion or trusted erroneous facts.

Validate final answer text, stream assembly, rendered output, clipboard, stored answer and supported exports. Browser full-page screenshot PDFs do not establish whether Tribos's own PDF exporter preserves links or formatting; test that exporter directly.

Correlate timers and counters by run/case/claim/call ID. Label outer elapsed time, orchestration/model/tool/check time, cache use and reading/streaming boundaries. Report small rounded times honestly; 0.0s is not proof of zero latency. Resolve the unexplained P02 mismatch without labelling all later reconciled times defective.

## 7. Regression and acceptance plan

Use the actual production components and request flow. Deterministic external-boundary fixtures are appropriate; replacing the faulty interpreter/verifier with a success stub is not a regression test. Use independent mathematical oracles and metamorphic tests where useful. Do not mirror implementation logic as the oracle.

Run fresh-context tests and deliberate history/cache tests separately. Record actual model/provider/settings and cold/warm/cache state. Preserve successful features and include real legitimate research/simulation, not only tests that skip tools.

### 7.1 Original regression groups T01-T20

These preserve the earlier reproduction prompts. For an explicit sustained research request, apply T34/T42 as well: a correct open-status sentence alone is not acceptance for that request.

### T01 — Original Collatz proof request with negative simulation wording

~~~text
Start with any positive integer n. Repeatedly apply these rules:

- If n is even, replace it with n/2.
- If n is odd, replace it with 3n + 1.

Prove or disprove that this process eventually reaches 1 for every positive integer.

Give a rigorous mathematical justification. Checking examples, running simulations, or assuming that the sequence eventually decreases does not establish the claim for every positive integer.
~~~

Acceptance: recognizes the proof/status task; no ODE/simulation clarification; no invented universal proof or counterexample; accurate open-status explanation and limits of numerical evidence.

### T02 — Controlled wording variant

Use T01 with only its last sentence removed, retaining "Give a rigorous mathematical justification."

Acceptance: materially consistent intent and mathematical status. Run independently from T01 and record memory/cache state. Add paraphrases with negation, quotations, and hypothetical mentions to prevent brittle keyword fixes.

### T03 — Short Collatz evaluation and cycle

~~~text
Define T(n) = n/2 for even positive integers and T(n) = 3n + 1 for odd positive integers.

Compute T(1), T(2), and T(4).

Then write the cycle starting at 1, with each arrow representing exactly one application of T.

Answer in at most 40 words.
~~~

Acceptance: T(1)=4, T(2)=1, T(4)=2; cycle 1 -> 4 -> 2 -> 1. No solving for a scalar T, no negative/fractional starting-value "solution," no proof/literature pipeline needed.

### T04 — Function definition and substitution proof

~~~text
Let f: R -> R be defined by f(x) = x^2 + 1.

1. Compute f(2).
2. Prove that f(x) - x^2 = 1 for every real x.

Answer in at most 50 words.
~~~

Acceptance: f(2)=5 and the justified identity. Both requested claims can be checked from the given definition. No x(f-x) result, undefined-function error, or unmatched correct substitution. Repeat with the original Unicode notation as well.

### T05 — False universal claim

~~~text
Prove that n^2 + n + 41 is prime for every nonnegative integer n.

Give a rigorous proof in at most 80 words.
~~~

Acceptance: explains the claim is false with n=40 giving 1681=41^2, or another valid integer counterexample. Disproof is completed, not a failure to deliver an impossible proof. If n=41 is also used, its local assignment must be evaluated independently.

### T06 — Independent bindings and exact two-line answer

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

### T07 — Literal output with Search on

~~~text
Return exactly the following two lines as plain text. Preserve the newline and add nothing else:

ALPHA
BETA
~~~

Acceptance: exact LF-normalized payload "ALPHA\nBETA", visible as two lines, without extra content. No literature, factual NLI, math solver, critic debate, or grounding warning. Verify raw text, stream assembly, DOM rendering, clipboard, stored response, and export.

### T08 — Search-off enforcement

Repeat T07 with Search off. Also exercise a self-contained numerical request and all applicable workflow entry points.

Acceptance: no external retrieval calls, including academic adapters and automatic follow-ups. Cached results must not be presented as fresh research or accidentally attached from another run. Document behavior for a genuine research request while search is disabled rather than silently ignoring the setting.

### T09 — Format controls and structured responses

Use new literal strings, three-line text, preserved indentation, valid JSON-only output, and short word limits. Include Bangla or other supported Unicode text.

Acceptance: validate the exact requested contract after the final revision and after rendering/export. Do not satisfy tests by hardcoding ALPHA/BETA.

### T10 — Function/branch/domain generalization

Use renamed functions, different polynomials, explicit scalar multiplication, piecewise definitions, negative/zero inputs where allowed, and positive-integer-only functions.

Acceptance: preserve application versus multiplication and respect branch/domain conditions. Reject unsupported interpretations rather than solving a different problem. Include domain-sensitive expressions such as x/x with and without x != 0.

### T11 — Legitimate simulation and legitimate clarification

Supply a real, fully specified simulation request, then an underspecified version missing a required initial condition.

Acceptance: the first executes the relevant computation; the second asks a minimal relevant clarification. A proof question merely mentioning simulation is not routed into this workflow.

### T12 — Genuine primary-source research

Ask for the precise statement and limitation of Tao's Collatz theorem using the primary paper.

Acceptance: appropriate relevant retrieval, faithful logarithmic-density/almost-boundedness statement, no claim of convergence to 1 from that theorem, and source-linked support. Do not use an unrelated paper or title alone as proof.

### T13 — Unsupported claimed proofs and source failures

Use controlled retrieved material that claims a breakthrough without a valid derivation, an unrelated but keyword-matching source, and an unavailable metadata service.

Acceptance: source relevance, acceptance status, and argument validity remain distinct. No fabricated citations, blanket acceptance of a "proof" title, or blanket rejection based only on preprint status. Unavailability is reported at its actual scope.

### T14 — Verification states and final revision

Exercise valid, invalid, unavailable, not-applicable, unsupported, and interpretation-failed checks. Revise an answer after a real failed check.

Acceptance: consistent counts and labels everywhere; no stale findings; no "all supported" banner when checks are undecidable; no "contradicted by sources" label for a differently scoped substitution failure.

### T15 — Incorrect-translation defense

Feed the mathematical integration layer the observed incorrect scalar/branch interpretation and out-of-domain witness.

Acceptance: interpretation fidelity fails. Local algebra success cannot produce a Pass for the original function task. Word-limit/list numerals do not become mathematical inputs.

### T16 — Case/run/cache isolation

Execute cases in reverse order and in parallel, and execute separate conversations with the same expression but different bindings and function definitions.

Acceptance: no wrong-case result reuse, scope leakage, shared state mutation, or accidental evidence/claim association.

### T17 — Storage quota, persistence, and recovery

Inject quota/write failures and oversized reconstructible caches into test profiles with existing conversations.

Acceptance: core user history survives; incomplete new writes are detected; cache eviction is controlled; reload/export/recovery behavior is correct. Never test destructively against the user's real history.

### T18 — Latency, unnecessary work, and bounded retries

Profile representative copying, arithmetic, proof/status, simulation, and research requests with comparable model/provider/settings. Record cold/warm/cache behavior and phase timings.

Acceptance: self-contained copying and arithmetic trigger no automatic research. Simple operations avoid pointless critic rounds and repeated identical tool calls. Genuine research retains needed capabilities. Report measured baseline/after values without inventing universal latency promises.

### T19 — Optional checker availability

Run with the formal checker unavailable and, if feasible, available.

Acceptance: no fabricated formal verification; ordinary applicable symbolic/arithmetic checks remain usable; N/A/unavailable is not treated as a mathematical contradiction.

### T20 — Application-wide regression and held-out cases

Run the repository's relevant unit/integration/UI/build/lint/type checks. Exercise all actual supported workflows and provider interfaces affected by the changes.

Add held-out mathematical and nonmathematical prompts with different wording, symbols, values, output formats, and information needs. Demonstrate that the repair generalizes beyond the examples in this document.


### 7.2 Additional regression groups T21-T45

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

### 7.3 Exact sustained-investigation reproduction for T34

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

### 7.4 Bounded proof-execution control for T42

~~~text
Let P(s) = (s - 1/4)(s - 3/4), where s is complex.

Prove P(1-s) = P(s), find all its zeros, and determine whether reflection symmetry about Re(s)=1/2 alone forces every zero onto that line.

Give the derivations and check the roots. Explain precisely what this establishes about a symmetry-only argument and what it does not establish about the Riemann zeta function.
~~~

Oracle: `P(s)=s²−s+3/16`; `P(1−s)=P(s)`; roots `1/4` and `3/4` are off the line. This disproves the proposed sufficiency of symmetry alone; P is not the Riemann zeta function, so it does not disprove RH. Formal checking, if used, must match these polynomial statements.

## 8. Required verification evidence and deliverables

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

## 9. Evidence inventory and reading boundaries

This report is self-contained for reproduction. The following exact filenames identify the original supporting attachments. They are evidence captures, not source-code files.

### 9.1 Historical captures

The B/R register above identifies twelve primary captures and two supplementary screenshots. The six-page R2 capture contains an earlier answer; it is not an additional independent run.

### 9.2 Post-repair image captures

| Run | Original supporting filename(s) |
| --- | --- |
| P01 | `{ED2EE526-62D5-472E-B90E-F4C35CF42B20}.png` |
| P02 | `{2261FD1D-FCE3-4778-8C03-B425C69EABB3}.png`; `{25127AB7-C8CE-4791-A302-BC3789C7BE74}.png`; `image(20261025-121227).png`; `{FEE308BB-3C64-49F3-A1D1-E2FFAA442845}.png`; `{5F3B0DD1-0AD9-4323-A75D-FB09EF2EC552}.png`; `{FD6E95E1-FD0C-44A2-876F-1F02F910FA01}.png` |
| P03 | `{3B178E2C-FCFB-49E0-ACBE-8175386345D1}.png`; `{E6D71CB5-E2BD-427A-8B59-5FD82AE27AD0}.png`; `{500DCF88-6286-47D5-B1FB-9003064E3B30}.png` |
| P04 | `{85A93279-9E6A-4BD4-B8D3-6421A9E6865D}.png`; `{FDB7A11E-274E-4053-A052-CC25F8DE19B4}.png`; `{01E9C2CD-B3AB-45A7-8551-DFB5C818AA86}.png` |

### 9.3 Post-repair PDF captures

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

### 9.4 Primary references used to check mathematical/status semantics

- [Clay Mathematics Institute: Riemann Hypothesis](https://www.claymath.org/millennium/riemann-hypothesis/) — official open-status statement checked during this evaluation.
- [Tao: Almost all orbits of the Collatz map attain almost bounded values](https://arxiv.org/abs/1909.03562) — precise limitation of the earlier claimed “almost all reach 1” result.
- [Tao's accompanying explanation](https://terrytao.wordpress.com/2019/09/10/almost-all-collatz-orbits-attain-almost-bounded-values/).
- [Lean: False and foundational propositions](https://lean-lang.org/doc/api/Init/Prelude) and [tactic reference](https://lean-lang.org/doc/reference/latest/Tactic-Proofs/Tactic-Reference) — False is a contradiction proposition; a theorem name does not encode RH.
- [RFC 9110: HTTP 500](https://www.rfc-editor.org/rfc/rfc9110.html#section-15.6.1) — internal error semantics; the observed generic response does not diagnose its origin.

Check any changing status or provider contract again when implementing. Bibliographic labels, numerical demonstrations, compiler rejection and critic consensus have different evidential roles.
