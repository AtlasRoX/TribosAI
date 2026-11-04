# Tribos: remaining verification, coverage and Lean repair prompt

Updated: 27 October 2026 (Asia/Dhaka).

**Use:** attach the current codebase, this file, the repair changelog and the two latest PDF captures. Copy the complete prompt below into your coding agent. It includes the issue brief and acceptance criteria. Work through its phases sequentially and validate the combined result.

**Evidence boundary:** the evaluation inspected responses and traces, not the current repository or real compiler/provider logs. The changelog's fixes, commits and test results are supplied claims. Implementation causes below are investigation targets unless explicitly described as observed behavior.

~~~text
Audit and repair the remaining Tribos issues described below, including the complete Lean/formal-proof integration. Read repository instructions and the supplied audit/changelog first. Inspect actual source code, reproduce the failures, establish their causes, implement general fixes and validate the integrated application. Do not stop at a report or plan.

Work in reviewable phases with logical commits on an integrated branch/checkpoint. Finish the scoped work or report a concrete blocker. Preserve unrelated user changes, saved history, configured model/provider choices and working features. Avoid hardcoding function names, coefficients, variable i, numbered prompts, or the exact sample answers.

1. OBSERVED ISSUE BRIEF

A. False certification of an incomplete/wrong mathematical task
In the numbered proof-and-evaluation run, the final answer is correct, but the verified mathematics card contains only:
    a(i) = 7*i + 4
    1 = 1
    2 = 2
It nevertheless passes "no trivial tautological claims", tool-to-task matching, domain, coverage, and correspondence to the original task. It reports two recomputations and three items answered.

Those displayed results do not establish the universal inequality or provide the six requested function values and three comparisons. Successful execution and correct tautologies are insufficient to verify the user's actual obligations.

B. The unnumbered control reproduces the same failure
Removing the question's "1." and "2." markers leaves the same a(i), 1=1, 2=2 artifact and green certification. The final prose remains correct. Therefore numbered question markers alone cannot explain the defect. Inspect evaluation-list extraction, declared functions, mathematical obligations, task construction and the handoff to the structured engine using actual payloads.

The unnumbered run's planner accurately describes the evaluations and the proof using a(i)-b(i)=3i+2, but the tool result still lacks them. Trace where those obligations disappear. Do not assume a specific code-level cause until reproduced.

C. False missing-work and partial-answer reports
The answer visibly supplies the algebra and all three numerical checks. The requested-items panel labels them missing. The unnumbered run additionally claims the comparison/proof is not addressed and marks the answer Partial, despite its presence in item 1 and explicit comparisons in item 2.

D. Disabled Lean misreported as failure
The execution timeline says "formal prover disabled by user" and "Skipped: prohibited by user request". The formal-proof card nevertheless shows a red "formalisation failed" badge and the timing panel shows a warning. No actual compiler attempt is demonstrated. Repair the state mapping; do not run Lean merely to remove this warning.

E. Passing controls to preserve
- Three independent local k calculations now produce 3,7,13 in both final answer and structured tool evidence.
- For f on {3,4,5,...}, f(n)=n²-2n+6, the answer correctly returns undefined,9,undefined,30 at inputs 2,3,0,6.
- The latest i proof and numerical comparisons are mathematically correct; the former imaginary-unit contradictions are absent in these runs.
- Explicit search/formal restrictions are being respected operationally in the latest captures.

The domain label should describe enforcement and rejected inputs accurately, rather than claiming every submitted argument belongs to the domain.

Sources:
- gofullpage-localhost-3000-2026-10-27-17_56_38.pdf
  run_72e3b9fb3d2444be: numbered task, false certification and missing-work labels.
- gofullpage-localhost-3000-2026-10-27-18_01_19.pdf
  run_3454ae76b5ca4464: unnumbered control, same artifact, false Partial status.
- TRIBOS_COMPLETE_AUDIT_AND_REPAIR_CHANGELOG.md: reported implementation and test claims.
Use the previous full audit for historical regressions; reproduce older concerns before treating them as current failures.

2. EXACT REPRODUCTION AND MATHEMATICAL ORACLE

Run this through the production request path with the same supported model/provider/settings as the captures:

Let i be a nonnegative integer. Define
a(i) = 7i + 4 and b(i) = 4i + 2.

Prove or disprove that a(i) > b(i) for every allowed i.

Evaluate a(i) and b(i) separately for i = 0, 1, 2, and check each comparison.

Any proposed counterexample must be a nonnegative integer.

Return exactly two numbered items. Show the algebra and all three numerical checks. Add nothing else. Do not search the web or invoke a formal prover.

Repeat with "1." before the proof request and "2." before the evaluation request. Both variants must work.

Oracle:
- a(i)-b(i)=(7i+4)-(4i+2)=3i+2>=2>0 on nonnegative integers.
- i=0: a=4,b=2,4>2.
- i=1: a=11,b=6,11>6.
- i=2: a=18,b=10,18>10.
- i=-2/3 gives equality but is outside the declared domain; it is not a valid counterexample.
- The output has two numbered items, with the proof and all checks included.
- No search, formal generation, formal repairs or compiler execution is allowed by this request.

3. PHASE A: REPAIR MATHEMATICAL TASK CONSTRUCTION AND CERTIFICATION

Capture sanitized request interpretation, definitions, domains, quantifiers, task/case IDs, generated tool arguments, raw results, correspondence checks, final claim checks and UI state. Find the exact first point where the task diverges.

Inspect the actual equivalents of these changelog paths if present:
- tribos/axiom/definitions.py, problem.py, schemas.py, correspondence.py, verifier.py
- tribos/verify/result_record.py, math_claims.py, verifier.py
- tribos/agentic/math_agent.py

Required behavior:
- Represent the proof obligation and numerical evaluations explicitly. Definitions are context, not automatically fulfilled proof requests.
- Separate task-list labels, output-format counts and evaluation lists from mathematical assertions.
- Preserve declared symbols, local bindings, original function domains and quantifiers throughout the pipeline.
- Require tool-to-original-task correspondence before task-level certification. Comparing a mistranslated intermediate task with itself is insufficient.
- A tool result may be useful but partial. Certify only its actual supported scope; do not require every optional tool to prove every obligation.
- Never count irrelevant 1=1 or 2=2 as evidence of the requested proof/evaluations. However, legitimate requested tautologies, identities and numeric equalities must remain supported. Reject irrelevance, not equality itself.
- An "ok" execution, two recomputations, a correct writer response or a benchmark badge cannot promote irrelevant tool evidence to Verified.
- Retain rejected attempts as explicitly historical/unverified evidence and attempt bounded semantic repair where appropriate.
- For universal claims, distinguish a proof from sampling. A genuine in-domain counterexample can refute a universal statement. Failed parsing, unknown status or unsuccessful search cannot.
- Keep final-answer claim checks distinct from tool-task certification. "13/13 claims supported" must state its actual scope and cannot repair a different malformed tool result by implication.
- Validate counterexamples against every applicable domain and assumption before acceptance.

4. PHASE B: REPAIR COVERAGE, REVISION STATE AND OUTPUT CONTRACTS

Inspect actual equivalents of:
- tribos/agents/deliverables.py
- tribos/agents/orchestration/finalize.py and verify.py
- tribos/agentic/state.py
- web/src/components/agentic/AgentRunPanel.tsx
- web/src/components/VerificationNotice.tsx and relevant shared types/selectors

Required behavior:
- Track the two parent requests and their proof/evaluation/comparison obligations with stable IDs. Additional subrequirements may be represented, but panel counts must explain their scope.
- Separate answered/missing, tool checked, checked by another verifier, retrieval supported, unverified, rejected, failed and historical states.
- Associate a tool result with the correct original item and revision. Do not infer completion just from keyword overlap or a count of generated tasks.
- Recognize the actual algebra and numerical checks in the final answer, including equivalent notation and reordered clauses.
- A complete correct answer with an unavailable optional check may be complete but not independently verified. Do not manufacture a Partial/missing warning.
- Genuine omissions and wrong checks must still be detected; do not fix this by suppressing warnings.
- Invalidate affected checks after changes to domains, definitions, bindings, claims or evidence. All current badges/prose must refer to the relevant revision.
- Audit the reported cache key (record.revision, mathematical-content hash). Establish whether revision already binds the full semantic context. If not, include canonical task/domain/definitions/bindings/checker context to prevent cross-question reuse.
- Preserve exactly two numbered answer items after every rewrite. Process/evidence UI can remain outside the constrained answer body.
- Validate the displayed answer, tool cards, coverage, copy/export and restored conversation state together.

5. PHASE C: REPAIR THE COMPLETE LEAN INTEGRATION

This includes real execution and proof trust when enabled, not only badge text.

Policy and state:
- Enforce explicit no-formal restrictions before proof generation, repair or compiler dispatch, including nested workflows and cached-result presentation.
- Use typed states that distinguish disabled_by_user, not_applicable, unavailable, running, verified, failed and cancelled as appropriate to the existing architecture.
- A disabled request must show "Skipped: disabled by user", with zero new formal model/compiler attempts, no failure badge and no warning counted as a failed proof.
- Map states consistently through backend serialization, frontend types, cards, timelines, summaries, reloads and exports.
- Treat cached certificates as records of their original execution, not a new execution or a fresh verification.

Environment and execution:
- Inspect the actual Lean executable/path, version/toolchain, project configuration, imports and Mathlib availability.
- Make supported formal tasks executable where the environment permits, with compatible pinned configuration and setup instructions.
- Distinguish missing dependencies from unsupported mathematics and compiler failure. Describe the installed environment precisely; do not claim a language cannot express something merely because a project library is absent.
- Use APIs/tactics supported by the actual installed versions; consult official documentation when needed.
- Retain the exact generated theorem, source, toolchain/import context, compiler stdout/stderr, exit status and attempt history.
- Bound repair attempts/time and support cancellation. A failed compile establishes neither the truth nor falsity of the mathematical claim.
- If real compiler execution is unavailable, report that specific blocker. Do not label mocked tests as real compilation.

Semantic correspondence:
- Check that the elaborated theorem and assumptions entail the user's actual statement, preserving operations, functions, quantifiers, domains and exclusions.
- Reject unrelated True/False goals, arbitrary numerical identities or assumed conclusions substituted for a harder requested theorem.
- Do not blanket-ban True, reflexivity, P->P, or tautologies when they are genuinely the requested claim.
- Allow a stronger lemma or a broader-domain proof only with a checked mapping that entails the original goal; a binder-name regex alone is insufficient.
- A theorem named riemann_hypothesis is not evidence that its type encodes RH. Never certify a known-open target using an unrelated compiled statement.

Trust:
- Reject sorry/admit/proof holes and user-injected assumptions that assume the requested conclusion.
- Preserve ordinary trusted Lean/Mathlib foundations.
- Do not trust an arbitrary new axiom merely because its name resembles propext, choice, funext or another trusted declaration.
- Inspect actual declaration/dependency provenance and signatures, using Lean's declaration/axiom information where available. Document accepted additional trust assumptions.
- Add an adversarial fresh-namespace trusted-looking axiom asserting False; it must not certify an unrelated user theorem even if Lean accepts code using that assumption.
- A trusted-name allowlist or source-text regex is not by itself a semantic proof-trust boundary.

6. PHASE D: NEGATIVE CONTROLS AND GENERALIZATION

Run meaningful production-path/integration/UI checks, with actual code paths rather than only prepared success mocks:

A. Both exact reproductions above, plus proof-only and evaluation-only controls.
B. Rename i to j and another declared symbol; change coefficients and evaluation points.
C. Genuine imaginary-unit calculations remain correct. Declared integer i remains a variable.
D. Remove, reorder and vary wording of question numbering and output-contract counts.
E. Explicit a(0),b(0),... applications versus "evaluate separately for i=0,1,2".
F. A valid counterexample on an allowed integer domain and an invalid fractional/negative witness on a restricted domain.
G. Inject the observed a(i),1=1,2=2 result: correspondence and full-coverage certification must fail.
H. Legitimate requested 1=1/reflexivity identities must still pass.
I. Delete the proof or one numerical comparison from a fixture: coverage must detect the real omission.
J. Revise a correct claim/domain into an incorrect one; ensure old certificates are invalidated.
K. Reuse identical answer text with different domains/definitions/bindings at the same revision number; prove cache isolation.
L. Sample trap: H(n)=1-[n(n-1)(n-2)(n-3)(n-4)(n-5)]² on nonnegative integers. H(0)...H(5)=1, but H(6)=-518399. Sampling the first six values cannot prove H(n)>0 universally.
M. A quoted false statement, an explicit universal refutation, an existential claim and an unsupported parse. Check each according to its logical role; do not blindly invert every FAILED state into a proved refutation.
N. Formal proof prohibited: assert zero generation/repair/compiler calls and consistent disabled UI state.
O. Formal proof enabled: run real supported Nat and rational lemmas, and appropriate Mathlib-dependent controls when configured. Prove the actual requested statement.
P. Formal compilation failure, unavailable executable/library, timeout and cancellation remain accurately scoped.
Q. Unrelated goals, changed assumptions, conclusion-axiom cheats, proof holes and trusted-looking injected axiom names are rejected.
R. Valid foundational dependencies and genuine requested tautologies are accepted.
S. Preserve independent k results 3,7,13 and the restricted f results undefined,9,undefined,30.
T. Preserve rational identity/excluded-root, real/complex and exact-output regressions from the original report.
U. Browser-level checks for badges, counts, disabled/failed distinction, copy/export and reloads.

Run the repository's relevant Python tests, frontend tests, type checks, lint and production build with its actual documented commands. Clearly distinguish mocked/fault-injection tests, real compiler tests and live provider runs. Do not claim unavailable checks passed.

7. PHASE E: RECONCILE THE CHANGELOG AND DELIVER THE PATCH

- Record one final integrated commit/HEAD and demonstrate all intended changes are present there.
- Resolve the ledger/detail commit mismatch for F01-F13; if caused by rebasing or cherry-picking, document the mapping.
- Correct the historical examples: original r(1)=5 under unrestricted substitution, original S07 difference 7i+1, and standard Collatz T²(1)=2. Clearly label exponential variants as separate controls.
- A sample threshold n>=10 is not evidence of statistical significance or current-answer correctness. Keep benchmark provenance and scope accurate.
- List the real commands/results and skipped checks at the final integrated state. Do not use a changelog headline or test count as evidence of live behavior.
- Report older F01-F21 issues as fixed/already fixed/partial/not reproduced/blocked based on current evidence; preserve passing controls.
- Do not deploy or destructively migrate actual user history.

Deliver:
1. Reviewable patch/commits or updated source ZIP.
2. An issue-to-root-cause-to-file/symbol-to-test table.
3. Before/after raw task and tool records for both reproductions, with final answer and UI states.
4. Real Lean environment/compiler evidence where available, policy-enforcement evidence, and remaining blockers.
5. Final integrated HEAD, exact test/build results and corrected changelog.

The completion condition is truthful task-scoped verification and working relevant formal checking. Correct-looking final prose, hidden warnings, disabled checkers or green badges alone are insufficient.
~~~

