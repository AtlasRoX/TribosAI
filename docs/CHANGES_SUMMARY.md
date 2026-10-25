# Tribos: everything that changed

A plain-language record of all the work done on Tribos in this session: what changed, why, where it lives, and how
it was tested. The detailed engineering report (issue-by-issue evidence, causes and limitations) is
[AUDIT_REPAIR_REPORT.md](AUDIT_REPAIR_REPORT.md).

## At a glance

| Phase | Branch | Commits | Size |
|---|---|---|---|
| 1. Roadmap features T1–T10 | `features-roadmap` (also included in `audit-repair`) | 11 commits, `f350c05` … `cffff9f` | ~13,000 lines added |
| 2. Audit repair (issues I01–I23) | `audit-repair` | `0351306` | 53 files, +3,259 / −150 |
| 3. Follow-up requests (exports, UI, open problems) | `audit-repair` | `37075ce` | 17 files, +582 / −18 |

Nothing was pushed. `.env` was changed locally (Lean path) and is not committed; it is gitignored.

Final checks:
- backend tests: 1536 passed, 17 skipped, 0 failed;
- web: 201/201 tests, typecheck, lint (0 errors) and production build pass;
- ruff, bandit (0 high-severity) and the settings-docs check pass.

---

## Phase 1: Roadmap features (T1–T10)

| Task | What it adds | Main code |
|---|---|---|
| **T8** Reproducible exports | Export an answer as a runnable Jupyter notebook; fixes to the report exports (Word, LaTeX, bundle) | `tribos/export/notebook.py`, `web/src/components/ExportMenu.tsx` |
| **T1** Fit models to data | Fit ODE model parameters to uploaded measurements, with the fit shown in a calibration card | `tribos/dynamis/fitting.py`, `tribos/agentic/fit.py` |
| **T4** Unit consistency | Checks that units in written answers are consistent (e.g. kN·m vs kg) | `tribos/verify/units_audit.py` |
| **T3** Uncertainty propagation | GUM first-order propagation plus Monte Carlo, with a contribution budget and CODATA constants | `tribos/physis/uncertainty.py` |
| **T2** PDE solver | Heat, wave, Poisson, advection-diffusion, Fisher-KPP, Burgers; each solve reports a mesh-convergence study, conservation checks and stability | `tribos/dynamis/pde/` |
| **T9** Engineering calculators | Beam, buckling, pressure vessel (ASME VIII-1), shaft, bolt, fatigue, pipe flow, heat exchanger, wall conduction, with material data, validity checks and references | `tribos/engcalc/` |
| **T6** Interactive simulation | Sliders, phase portraits, vector fields and bifurcation sweeps on simulation cards (`/api/simulate`) | `tribos/dynamis/interactive.py`, simulation card |
| **T7** Read papers | Upload a PDF; Tribos extracts equations, parameters and stated results and tries to reproduce each one | `tribos/papers/` |
| **T5** Formal proofs | Lean 4 checking of "prove …" questions when Lean is installed; never accepts `sorry`/axioms | `tribos/verify/formal/` |
| **T10** Projects and sidebar | Project members (owner/editor/viewer), shared files, reviewed memory facts, activity log; new sidebar and project views; `page.tsx` shrank by about 700 lines | `tribos/agentic/project_memory.py`, `web/src/components/sidebar/`, `web/src/components/projects/` |
| Integration | Fixes found by running the features end to end with the live model | several |

---

## Phase 2: Audit repair (I01–I23)

### 1. Literature search ran on every question and fetched unrelated papers

**Before:**
- Every question that the maths parser could not fully understand triggered a literature search.
- The search text was the raw question, instructions included, so "two independent cases" returned US court cases.
- Irrelevant results were kept to fill a minimum of 3.
- The Search toggle only switched off web search; the scholarly literature APIs still ran.

**Now:**
- **Search only when there's a real information need.** Calculations, proofs, copy requests, word problems with given numbers, fully specified simulations and textbook-concept questions search nothing. Research questions, "cite papers", current events and named real materials still search. This follows published findings that retrieval helps with obscure facts but can mislead on well-known ones. (`tribos/agents/evidence_need.py`)
- **Search the subject, not the instructions.** Format instructions, case lines and generic words like "case", "proof" and "integer" are removed from the search and ignored when judging relevance. (`literature_subject` in `tribos/agents/authoritative_orchestrator.py`, `tribos/archivon/engine.py`)
- **Irrelevant papers are dropped, not padded in.** The article count now shows only the papers actually used.
- **Search off really means off.** Literature, web and online-database lookups are all blocked, both when the run is planned and at the tool layer, so no workflow can bypass it. (`tribos/tools/reliability.py`, `tribos/agentic/plan_graph.py`, `tribos/agentic/specialists.py`)

**Measured** (same prompts, offline): external calls went from 2 (Search on) or 1 (Search off, the leak) to **0** for every self-contained prompt. A genuine research question with Search on still makes its 2 calls.

### 2. Misread intent and pointless clarification questions

- "Running simulations does not establish the claim" used to be read as a request to simulate, and the user was asked "Which dynamical system should I simulate?". Negated, quoted and hypothetical mentions no longer count. (`tribos/agents/query_planner.py`)
- A real missing input now gets exactly one question: an equation given without its initial conditions asks only for those (e.g. "What is x'(0)?"). (`tribos/agentic/clarify.py`)
- The "Calcula skipped" reason now tells the truth (the computation runs in the maths agent).

### 3. Mathematics: functions, cases and claims

New module `tribos/axiom/definitions.py` plus a new verified tool `axiom_structured`.

- **Functions are applied, never multiplied.** `T(n) = n/2` used to be solved as the equation `T × n = n/2` (giving the nonsense T = 1/2, n = −2/5). Now T(1) = 4, T(2) = 1, T(4) = 2 and the cycle 1 → 4 → 2 → 1 are computed and verified.
- **Piecewise definitions and domains.** "n/2 for even n, 3n + 1 for odd n", "2t − 3 if t < 0, t² otherwise", functions only on positive integers (g(0) is reported "undefined", not computed).
- **Independent cases** ("Case A: n = 40, Case B: n = 41") each get their own values: 1681 = 41² and 1763 = 41 × 43.
- **Universal claims** are proved, disproved or reported unresolved:
  - proved by substitution (f(x) − x² = 1), by checking all remainders (n³ − n is divisible by 6), or by finding a counterexample (n² + n + 41 at n = 40);
  - x/x = 1 fails at x = 0 unless x ≠ 0 is stated.
- **Four separate checks** on every result: interpretation, domain, independent recomputation, and coverage (every requested item answered).
- **Wrong readings are rejected.** A reading that treats a defined function as a number now fails as "interpretation failed", is never shown as an answer, and is never called a disproof.
- **Format numbers are not maths inputs.** "Answer in at most 40 words" no longer makes 40 look like part of the problem.

### 4. The answer checker

(`tribos/verify/math_claims.py`, `tribos/verify/result_record.py`)
- **Case values stay local.** "n = 41" was reported as an error because n had been fixed at 40 for the whole answer. Each case now keeps its own values, in any order.
- **The question's own definitions are used** to check statements like "T(1) = 4" or "f(2) = 5".
- **Plain-text arithmetic is checked too** ("A: 1681 = 41 * 41"); before, only `$…$` maths was checked.

### 5. Exact output ("Return exactly these two lines…")

New module `tribos/utils/output_contract.py`.
- Copy requests are answered instantly by copying the text, with no research, tools or model call (about 2 s live).
- Word limits, line counts, plain-text and JSON-only requests are passed to the writer, enforced after the final revision, and reported if they are broken.
- Warning banners are no longer written into answers whose format the user fixed, and Copy/Export leave the banner out.
- If the model fails, a verified maths result is used as the answer instead of a raw "Results gathered for…" dump.

### 6. Verification labels and graders

- "All 2 checked claims supported" was shown when nothing had actually been checked; undecided claims are now counted honestly. (`web/src/lib/verificationState.ts`)
- **Task-aware graders.** A correct short answer or a valid disproof is no longer marked "incomplete" or "does not address the question". (`tribos/verify/verifier.py`, `tribos/agents/deliverables.py`)
- "Benchmark precision 25%" is no longer shown on unverified maths answers.
- **No critic debates over route doubt.** Self-contained tasks no longer escalate to critic debates just because the route choice was uncertain.

### 7. Browser storage

When browser storage filled up, Tribos used to **delete whole old conversations**. Now it only drops rebuildable extras (plots, quoted passages) and, if space still runs out, says "not saved". Conversation text is never deleted. (`web/src/services/localStorageService.ts`; a test proves the old code deleted conversations and the new code does not.)

---

## Phase 3: Your follow-up requests

### PDF / Word / LaTeX exports

A line break you see in the answer is now a line break everywhere:
- on screen;
- in Word;
- in PDF;
- in LaTeX;
- in "Copy for Word".

Before, lines were merged ("ALPHA BETA"). Code and equations are untouched. (`web/src/lib/markdownSafety.ts`, `tribos/export/markdown_blocks.py`, `web/src/lib/markdownToLatex.ts`; real DOCX and PDF files are generated and checked in `tests/test_export_line_breaks.py`)

### Answer first, cards collapsed

- Answers open with the direct answer, then a short **"Brief analysis"** where every step says why it holds. (`tribos/agents/prompts.py`)
- **All result cards start collapsed**, and the supporting-evidence tabs start closed.
- A collapsed card that contains a warning shows a small **"needs a look"** tag. (`web/src/components/MessageArtifacts.tsx`, `web/src/components/agentic/ui.tsx`)

### Working on unsolved maths problems

- Proof questions now get a real attempt rather than just "this is an open problem". The answer tries the standard methods, proves the strongest partial results, shows exactly where each approach gets stuck, and labels every statement **proved**, **evidence** or **open**. It never passes evidence off as proof or claims an open problem is solved.
- Processes written as rules ("If n is even, replace it with n/2 …") are now understood. Tribos automatically:
  - proves facts about each rule (e.g. "an even number always gets smaller"; "3n + 1 is always even when n is odd");
  - reduces the problem to its smallest possible counterexample;
  - checks every start value up to 5000 exactly.
- A loop that avoids the target disproves the claim, and that disproof is checked. For example, with 3n − 1 the loop 5 → 14 → 7 → 20 → 10 → 5 never reaches 1.
- Live Collatz result: full worked attempt, verification passed, no literature searched.

### Checker fixes found during the live runs

- An answer that writes a rule in two parts (one formula for even n, one for odd n) is no longer flagged as contradicting itself.
- In pure maths, the letters `n` and `k` are no longer mistaken for units of measurement.

---

## Lean (formal proof checker)

- Your **C: drive is almost full (about 0.2 GB free)**, so the first install failed. That partial install was removed.
- **Lean 4.35.0** is installed at `X:\lean\elan`, without changing your PATH.
- `.env` now contains `TRIBOS_LEAN_PATH=X:/lean/elan/toolchains/leanprover--lean4---v4.35.0/bin/lean.exe`.
- Two Lean bugs were fixed:
  - error messages were garbled on Windows;
  - the AI wrote proof code that needs Mathlib, which isn't installed. It now writes core-Lean code, and Mathlib-style notation is converted automatically.
- Not installed: **Mathlib**, a multi-GB download. To add it, set `TRIBOS_LEAN_PROJECT` to a Mathlib project.

---

## Tests added

| File | Covers |
|---|---|
| `tests/test_audit_repair.py` | 64 tests: intent and negation, structured maths (T03–T06, held-out variants), wrong-interpretation defence, case isolation, output contracts, Search off at the tool layer, literature relevance, graders, reasoning steps, open-problem attempts, Lean (real Lean in live mode) |
| `tests/test_export_line_breaks.py` | Real Word, PDF and Markdown exports keep lines and drop the banner |
| `web/tests/auditOutputContract.test.mts` | Contract-aware rendering, banner-free copy |
| `web/tests/lineBreaks.test.mts` | On-screen line breaks; LaTeX export |
| `web/tests/localStorageService.test.mts` (extended) | Storage never deletes conversations |
| `web/tests/runStatus.test.mts` (extended) | Undecided claims are never summarised as supported |

Nine older tests were updated because they assumed the old leaks (literature running with Search off, or every question searching). Each one now tests the intended behaviour, with a matching test for the opposite case.

## Live results (your NVIDIA model, through the real API)

| Question | Result |
|---|---|
| Return "ALPHA / BETA" exactly | Exact two lines, 0 tools, 2–7 s |
| T03 function values and cycle | `T(1) = 4, T(2) = 1, T(4) = 2. Cycle: 1 → 4 → 2 → 1`, verified |
| T04 f(2) and identity | f(2) = 5 and the substitution proof, verified |
| T05 "n² + n + 41 is always prime" | Disproved at n = 40 (1681 = 41²), completed |
| T06 two cases, two lines | `Case A (n = 40): 1681 = 41^2` / `Case B (n = 41): 1763 = 41 * 43` |
| T01 Collatz | Full worked attempt (lemmas, reduction, evidence to 5000), verification passed, 0 literature calls |

For part of the session the NVIDIA service returned server errors (HTTP 500). Those runs are marked in the detailed report.

## Still open

- Checks against primary research papers and against sources that claim breakthrough proofs (audit items T12/T13).
- Browser-level end-to-end tests: the new layout and collapsed cards are covered by unit tests and the build, but haven't been checked by eye in a browser.
- The different timing numbers shown in the UI (header vs budget vs phase chart) still use different clocks.
- Some backend claim-count wording and truncation (160/80 claims) is unchanged.
- Mathlib for Lean.

## Running it

```bash
# backend (port 8000)
TRIBOS_AUTH_MODE=disabled .venv/Scripts/python.exe -m uvicorn app.backend.main:app --reload --port 8000
# web (port 3000)
cd web && npm run dev
# tests
.venv/Scripts/python.exe -m pytest -q -p no:cacheprovider tests
cd web && npm run typecheck && npx eslint src && npm test && npx next build
```

---

## Round 3 (second audit prompt, I24–I43)

Full detail, evidence and the issue-by-issue table: [AUDIT_ROUND3_REPORT.md](AUDIT_ROUND3_REPORT.md).

- **Domains are enforced.** "Defined only for positive integers" or `q: {1, 2, 3, ...} → ℤ` now makes `h(0)` /
  `q(-2)` "undefined", and the checker re-reads the domain from your question, so it cannot pass a payload that lost it.
- **Solution sets are sets.** `∅`, `{−i, i}`, `ℝ ∖ {1}`, `ℝ`, `{2}` — never "no solutions" for an infinite set; a wrong
  set from the tool is rejected.
- **Answers survive a failing writer model.** When the verified computation already is the requested answer (three
  lines, one-line set notation), it is written directly, in your format, with or without the model.
- **Failed runs say so.** No more "Results gathered for: <your question>"; nothing computed → status "failed" with the
  reason.
- **"There is no 150-word limit" works.** Removed, negated, replaced, quoted and example limits are handled; ranges such
  as 220–250 words are enforced on both sides.
- **Instructions and error text are not checked as literature claims;** "remains unsolved" is a status claim checked
  against the page you cite.
- **Lean never proves a different statement.** `theorem … : False`, `True`, assumed conclusions and statements over the
  wrong numbers are rejected; questions needing ℝ/ℂ say "not formalisable without Mathlib" (Mathlib is not installed).
- **Routing.** "the Riemann Hypothesis" / "Goldbach's conjecture" are subjects, not requests to invent hypotheses;
  status questions now look up a source.
- **Provider errors.** The NVIDIA 500s come in bursts; one bounded retry policy (3 attempts, 20 s, request ids logged)
  replaced the multiplied retries. Live runs show it recovering.
- **New maths:** "Prove P(1−s) = P(s), find all zeros" is proved, solved and checked (T42).
- **Checker false alarms fixed** (found live): `4s − 3 = 0` with s read as seconds; `\dots` read as a derivative.
- **UI:** "needs a look" now shows its reason; summaries only mention checks that ran; counter-evidence about claims
  the final answer no longer makes is shown as history.

Tests: `tests/test_audit_round3.py` (77). Full suite 1612 passed; 2 date-boundary failures explained in the report.
