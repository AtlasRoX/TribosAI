# Tribos — Complete Codebase Audit and Repair Prompt

Prepared: 25 October 2026. Scope: all 12 observed evaluation runs in this conversation, including the seven runs after the user reported changes.

**How to use:** Attach the CURRENT Tribos source repository or ZIP and give the coding agent this entire document. Original screenshots/PDFs are useful supporting evidence, but the observations and reproduction prompts below are self-contained.

**Important evidence boundary:** The evaluator inspected the application's responses, screenshots, PDFs, and visible traces. The application's current source code was NOT inspected. Observed behavior is evidence; proposed implementation causes are hypotheses until reproduced and traced to code. Do not invent file paths, line numbers, source contents, tool executions, or test results.

---

## BEGIN PROMPT

You are responsible for auditing and repairing the current Tribos codebase as a complete application. Act as a senior engineer working across orchestration, mathematical computation, evidence retrieval, verification, frontend rendering, and persistence.

Analyze the actual repository, identify the causes of the failures below, implement general fixes, and verify them. Do not stop after producing an audit or a plan. Preserve working functionality and user configuration while completing the implementation.

The goal is reliable behavior across the application's supported requests, providers, tools, and workflows. The examples below are regression cases, not an answer bank. Do not special-case Collatz, particular coefficients, ALPHA/BETA, or these exact prompt strings. A fix that only recognizes these examples is unacceptable.

### 1. Working instructions and scope

1. Read the repository's instructions, architecture, manifests, configuration, and existing tests. Identify the real entry points, supported platforms, provider interfaces, workflows, frontend framework, mathematical backends, storage mechanisms, and export paths. Do not assume a stack or repository layout from this report.
2. If supplied a ZIP, extract safely into an isolated working directory, preserving the original. If supplied a repository, preserve unrelated changes and work on an isolated branch or checkout where appropriate.
3. Inspect all first-party subsystems sufficiently to understand their responsibilities and connections. Trace every failure across request parsing, task classification, routing, tool arguments, tool execution, checking, synthesis, event reporting, rendering, and persistence. Read dependencies selectively where behavior requires it.
4. For each issue, document the actual source location, reproduction, cause, proposed repair, implemented change, and validation result. Distinguish confirmed defects, likely causes, unavailable evidence, and issues that cannot be reproduced.
5. Continue beyond the reported symptoms when the same defective component affects other request types. Audit adjacent reliability and security concerns found in the actual implementation, but do not describe hypothetical risks as confirmed vulnerabilities.
6. Preserve the user's model/provider choice and legitimate search, computation, research, simulation, and agent workflows. Do not repair this by globally disabling tools, deleting the verifier, hiding failures, or weakening checks.
7. Keep user-facing responses focused on what was requested. Keep detailed diagnostics available in truthful, appropriately scoped UI panels.
8. Do not perform production deployment, publish secrets, or destructively migrate real user history. Implement and test repairs in an isolated environment; preserve recoverable data and document any remaining deployment or migration work.
9. Do not ask routine implementation questions when the repository resolves them. Report genuine blockers precisely and continue independent authorized work.

### 2. Evidence quality and interpretation

All durations, step counts, article counts, and scores in this report were read from the application's UI or recorded during the conversation. They are not independent server profiling measurements.

A literature card listing 83 articles does not prove 83 new network requests occurred. Some results may be cached, shared, or accumulated. Inspect the actual query execution and result provenance.

A visible one-line answer establishes a rendered-output failure when two lines were requested. Screenshots alone cannot distinguish a missing newline in the generated response from newline loss during streaming, Markdown rendering, CSS layout, copying, or export.

An "Unverified" badge or an unavailable optional checker is not itself a defect when accurately reported. The problems are wrong calculations, wrong problem interpretations, false Pass labels, missing checks for supported operations, misleading aggregation, and unnecessary checks.

The Search-off follow-up was proposed but NOT run before evaluation stopped. All observed latest runs showed Search on. Do not claim the toggle was proven to be ignored. Test and inspect its enforcement.

One post-change comparison was run in the SAME conversation as the earlier prompt. This limits causal claims about wording changes because conversation history also changed. Fresh-chat tests can still share global memory or caches; inspect those separately.

Do not assume source citations displayed by Tribos are genuine, relevant, read in full, or correctly classified. Verify them before using them as evidence.

### 3. Complete observed-run register

The first five scores were informal provisional judgments. The later seven used a fixed rubric: correctness 40, instruction following 20, verification/status consistency 25, routing/efficiency 15. These human judgments are not calibrated benchmark scores or release criteria.

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

### 4. Consolidated issue reports

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

Observed:
- B2/B3: the checker assigns T=0.290036 and n=2.557913. Its left-side value is 0.741886854868, which equals T*n.
- B4: the displayed simplification is x(f-x), consistent with simplifying f*x-x^2 instead of using f(x)=x^2+1.
- R3: output is T=1/2, n=-2/5 rather than the requested function values.

Strong inference: function semantics are lost somewhere in parsing, tool argument construction, or mathematical representation. Locate the exact layer.

Preserve declared functions, arity, definitions, substitutions, independent symbols, and application nodes. Do not silently interpret a declared function call as implicit multiplication. Handle alternative notation, renamed functions, Unicode exponents, and equivalent explicit definitions without problem-specific exceptions.

#### I08 — Conditional branches and mathematical domains are discarded — P1

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
https://arxiv.org/abs/1909.03562
Author's explanation:
https://terrytao.wordpress.com/2019/09/10/almost-all-collatz-orbits-attain-almost-bounded-values/

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

Small requests visibly write approximately five to seven memory nodes. Meanwhile, verification is sometimes wrong or incomplete and storage warnings recur.

Confirmed: writes are reported; storage warnings recur.
Unconfirmed: those memory writes caused the quota issue or stored the erroneous intermediate results as trusted facts.

Inspect memory policy, provenance, size limits, and trust handling. Avoid persisting unverified solver artifacts as established knowledge. Store only useful, appropriately scoped information; preserve verification status and definitions. Invalidate incompatible computed caches after representation changes without deleting user-authored history.

#### I22 — Traces, timing, counters, and evidence provenance are difficult to reconcile — P2

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

Lean 4 is shown as unavailable because it is not installed/configured. The UI mentions TRIBOS_LEAN_PATH.

Absence of an optional checker is not itself proof that the application is defective, and ordinary arithmetic should not depend on installing Lean. Detect capabilities, report unavailable checks honestly, and avoid claiming a formal proof when none ran.

Likewise, a panel titled "Verified mathematics" should not suggest the entire user question is verified when only an unrelated or unmatched expression has passed a local check. Present the scope and limitations clearly. Avoid tiny or undocumented benchmark samples functioning as trust badges.

### 5. Source-code investigation plan

Start with actual symbols and UI strings, not invented filenames. Search for:

~~~text
Which dynamical system should I simulate
A simulation was requested
no numerical computation requested
Read as a proof question
No claims could be checked
could not be matched
Verified mathematics
Benchmark precision
Browser storage was full
axiom_solve
axiom_simplify
axiom_verify_identity
TRIBOS_LEAN_PATH
~~~

Also inspect the actual implementations of:
- Search permission propagation and retrieval/tool scheduling.
- Task/intent classification and all clarification gates.
- Workflow choice, effort budgets, fallback, and critic escalation.
- Mathematical parsing, SymPy transformations, domain assumptions, function declarations, and bindings.
- Case/claim IDs, tool argument schemas, caches, and aggregation.
- Verification/coverage/completion state and final revision handling.
- Citation normalization, evidence support, confidence, and calibration.
- Streaming output, Markdown/math rendering, copying, and export.
- Conversation storage, localStorage/IndexedDB/backend persistence, cache eviction, and memory writes.

Map the request's complete data flow before changing interfaces. Inspect stored schemas and migrations before modifying persistent records.

### 6. Required implementation principles

#### 6.1 Task-appropriate execution

Build on the existing architecture where sound. Make the information need, required tools, applicable checks, and output contract explicit.

Expected behavior by task:
- Literal copying/formatting: direct response or a safe deterministic transformation, with exact output checks; no external research or factual-grounding grader.
- Supplied-data arithmetic: exact computation and relevant checks; no literature unless separately requested.
- Mathematical proof/status: preserve definitions and quantifiers; distinguish a requested proof, an open status, a false claim, an attempted argument, and a valid counterexample.
- Literature/current-fact research: targeted source retrieval with claim-level support.
- Actual simulation: appropriate computation with valid equations, parameters, and initial/boundary conditions; clarify only genuinely missing required input.
- Mixed requests: apply each policy to the relevant subtask without contaminating the others.

Do not use an unvalidated keyword-only allowlist as the complete solution. Honor explicit user instructions and configured tool availability consistently across all workflows.

#### 6.2 Mathematical representation and checking

Use a structured mathematical representation or equivalent well-defined contracts that retain:
- Function declarations and application.
- Domains, quantifiers, assumptions, and branch predicates.
- Case-local assignments and variable scope.
- Definitions and justified substitution steps.
- Problem/claim/case IDs and source locations.
- Requested outputs and formatting constraints in a separate representation.

Ensure tool parsing is safe for user-supplied input; do not introduce unrestricted eval/exec as a shortcut.

Before accepting a tool result, check that it answers the intended problem under the intended assumptions. Then check the calculation. Keep those checks distinct.

#### 6.3 Case-safe execution and result provenance

Each independent case needs its own environment and result identity. Prevent shared mutable bindings, cache collisions, wrong-case aggregation, or a "first successful result" replacing other results.

A synthesized answer should retain dependencies on specific tool outputs and definitions. A correct equivalent transformation must be matchable; an irrelevant true identity must not be promoted to an answer.

#### 6.4 Coherent verification and completion

Model applicable checks explicitly. Failure to interpret a request is not mathematical disproof. No external evidence required is not the same as evidence missing.

A final revision must trigger necessary rechecking and invalidate stale findings. All claim counts, warnings, badges, exports, and completion states should reflect the same final version.

Multiple critics agreeing is not independent proof. Keep escalation bounded and evidence-driven.

#### 6.5 Relevant retrieval and honest scientific claims

Retrieve only for an identified information need. Respect Search off across all external retrieval adapters. When Search is on, skip it where it adds no useful evidence.

For genuine research, use targeted queries, deduplicate appropriately, inspect relevant text, and attach citations to the exact claims supported. Preserve differences between an accepted theorem, an unreviewed claim, a heuristic, and numerical evidence.

Do not conflate "not proven" with "false," "impossible," or "independent." Check mathematical explanations against authoritative primary sources when needed.

#### 6.6 Output contracts and rendering

Carry the output contract through generation, revision, streaming, rendering, copy, export, and persistence. Validate final response text and rendered behavior.

The exact-copy path must work without response templates, academic sections, evidence warnings, or accidental Markdown whitespace collapse. The same support should extend to JSON, code, indentation, short answers, and multilingual text as appropriate to the application.

Do not solve this by displaying every answer as a code block.

#### 6.7 Persistence and observability

Use a safe durability/cache policy suited to the existing architecture. Preserve user history, annotate trust, and test failure/recovery scenarios.

Instrument actual execution sufficiently to attribute latency and call counts. Do not add unnecessary permanent telemetry or store secrets. Traces should describe real actions and results, including limitations, without fabricated verification events.

### 7. Regression and acceptance suite

Implement meaningful tests against the production components and data flow. Do not merely test helper functions that duplicate the implementation, stub the broken component into success, or check that a failure message contains a reassuring word.

Use deterministic fixtures for repeatability and provider mocks only at appropriate external boundaries. Add controlled live integration checks when credentials/tools are available; otherwise mark those checks blocked rather than inventing results. Use fresh contexts for comparisons and also test persistent-memory/cache influence deliberately.

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

### 8. Completion requirements and deliverables

Produce the implemented changes plus an engineering report in the repository's existing documentation structure. A combined report is fine if clearly organized.

Include:
1. Repository architecture and the actual affected files/symbols.
2. A finding matrix covering I01-I23: evidence, reproduction status, severity, actual cause, change, tests, and remaining limitations.
3. A prioritized repair plan and a description of the final implemented design.
4. Exact test commands and truthful results, including blocked checks and reasons.
5. Regression results for T01-T20 and held-out cases.
6. Before/after examples using raw response text, relevant tool I/O, final verification state, and rendered/exported behavior.
7. Measured execution/call/retrieval differences for comparable configurations.
8. Storage preservation/migration/recovery findings and any necessary follow-up.
9. Any additional codebase defects actually discovered, with evidence and scope.
10. A concise final summary of what is fixed, what remains, and material risks.

If the input is a ZIP and the environment supports delivery, provide a runnable updated source ZIP with the repaired code and documentation, excluding secrets, dependency directories, temporary caches, and irrelevant generated files. Otherwise provide a reviewable patch/branch according to the repository workflow.

Do not claim all issues are fixed because a few prompts produce correct prose. The mathematical interpretation, execution, checking, UI state, formatting, and persistence must work together. Do not mark an unresolved issue closed merely because its warning was hidden.

Proceed now: inspect the actual codebase, reproduce the failures, identify their causes, implement the repairs, and validate the resulting application.

## END PROMPT

