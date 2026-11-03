# The adaptive research loop

A research project in loop mode (`POST /api/campaigns` with `mode: "loop"`, the default in the web app) works on a
goal until it reaches a conclusion, then writes a thesis. Code: `tribos/agentic/research/`.

```
goal ─► literature review ─► charter (deliverables, hypotheses, tests as a dependency graph)
         ┌──────────────────────────── round r ────────────────────────────┐
         │ ready tests run in parallel ─► findings ledger ─► analysis ─► judge │
         └──── judge: what is settled, which tests next, concluded? ───────┘
                    │ concluded · stagnated · nothing left · safety ceiling
                    ▼
              thesis (chapter by chapter, numbers checked) ─► PDF · DOCX · Markdown · HTML · bundle
```

## Phases

| Phase | Module | What happens |
|---|---|---|
| Review | `loop.py` | One research job with search on and memory recall off. If it fails, the plan is made from the goal alone and the thesis says so. |
| Charter | `charter.py` | One model call proposes deliverables, hypotheses and tests. Code validates it: every numbered part of the goal becomes a deliverable, ids are renumbered, dependency cycles are broken, and each deliverable gets at least one test. |
| Tests | `runner.py` | **compute / simulate / estimate:** a CodeAct session in the sandbox, with the research time ceiling. The last cell sets `result`, which holds named quantities and chart series. An independent re-implementation, which never sees the first one's code, is compared quantity by quantity. **prove:** a written proof plus Lean 4 formalisation. **literature:** a cited research job. |
| Ledger | `ledger.py` | One finding per test run: numbers, code, stdout, figures, checks and a verification tier. |
| Judge | `judge.py` | An analysis and a judgement per round. Code accepts only what the evidence supports (see below). |
| Thesis | `thesis.py` | Chapters are written one call each. Tables, figures, proofs, references and appendices are assembled from the ledger. |
| Exports | `tribos/export/thesis.py` | Typeset HTML (Google Sans, KaTeX, Tribos cover), printed to PDF by headless Chromium. DOCX, Markdown, and a reproducibility bundle with code, Lean files and `ledger.json`. |

Tests run over the dependency graph. Up to `TRIBOS_RESEARCH_PARALLEL_TESTS` run at once, and a test whose dependencies
pass during a round starts in the same round. A failed test is retried with its error and a "use a different
method" instruction up to `TRIBOS_RESEARCH_TEST_RETRIES` times, then marked blocked.

## Verification tiers

Strongest first:

1. `formal` (Lean-verified)
2. `certified` (interval or exact arithmetic, exhaustive finite checks)
3. `replicated` (two independent implementations agree on every quantity)
4. `computed` (ran once)
5. `sourced` (cited)
6. `reasoned` (argument only)

Every deliverable states the tier it needs. `formal` meets every requirement.

## The judge's evidence rules (deterministic)

- **done:** a deliverable is "done" only when it cites a finding that exists, passed (not disputed), and meets the
  deliverable's tier. Otherwise it falls back to "partial" (some evidence) or "open".
- **infeasible:** needs a stated reason, for example "open problem".
- **hypothesis verdicts:** "supported" or "refuted" needs cited evidence, else it becomes "undecided".
- **concluded:** holds only when every deliverable is done or infeasible, whatever the model says.

## Stopping

The loop stops at the first of these:
- **concluded**;
- **stagnated:** `TRIBOS_RESEARCH_STAGNATION_ROUNDS` rounds with no deliverable newly settled, no hypothesis newly
  decided and no new finding at replicated or stronger;
- **nothing left to run;**
- a **safety ceiling:** `TRIBOS_RESEARCH_MAX_ROUNDS`, `TRIBOS_RESEARCH_MAX_HOURS` or `TRIBOS_RESEARCH_MAX_TEST_RUNS`.

The ceilings are production guards; projects normally stop on the first two. The hours ceiling counts **active**
time (`loop.active_s`): hours a project sat paused, after an outage or a Stop, do not count. The app and the thesis
cover show that active time. The stop reason is shown in the app and printed in the thesis. **Continue research** turns an instruction into a new deliverable, plans tests for it and runs
the loop again.

## Time estimate

`estimate.py`: the remaining tests, spread over the parallel lanes, plus analysis, judging and the thesis. Test
durations come from medians measured on this project's tests, then other projects' tests, then priors. Before the plan
exists the estimate is labelled rough (`POST /api/campaigns/estimate`).

## Model-service outages

Research model calls retry transient provider failures (dropped connection, timeout, rate limit, 5xx) with
backoff: 5 s, 20 s, then 60 s. If the service stays unreachable, the project **pauses**, with a resumable error,
instead of recording a wrong result:
- a test that failed only for that reason keeps its retries and is not blocked;
- a round whose judge could not be reached stays open.

On **Resume**:
- tests blocked by an outage run again;
- a proof whose Lean check said nothing about the proof gets another formal attempt, at most two. This covers a
  check cut off by an outage and one where Lean could not load its library.

Before every Lean check, imports of Mathlib modules that the installed Mathlib does not have are removed, and the
check records which ones (`dropped_imports`). An example is `Mathlib.Tactic.Omega`: `omega` is now part of Lean core.
Otherwise Lean fails to load a file that does not exist, which reads like a broken installation and is never repaired.

The thesis is never written over a broken judgement.

## Isolation and durability

- **No memory:** research jobs run with `recall_memory=False` and `persist_memory=False`. A user's other
  conversations once leaked a Lorenz simulation into a Collatz project.
- **Durable state:** the loop is a state machine over the stored campaign record. After a restart or a Stop and
  Resume it continues where it was; finished work is never redone.

## Accuracy tools

These are available to every agent, registered in `tribos/extensions/axiom.py` and implemented in
`tribos/axiom/accuracy.py`:

| Tool | Use |
|---|---|
| `axiom_interval_verify` | Rigorous enclosure of f over a box, or a proof that f > 0 on it (or a refuting point), with a re-runnable certificate. |
| `axiom_precision_check` | f at 15–120 digits and in float64; flags cancellation and ill-conditioning. |
| `axiom_counterexample_search` | Falsifies identities, inequalities and integer properties in exact arithmetic; exhaustive on small finite domains. |
| `calcula_cross_validate` | Runs two independent implementations in the sandbox and compares every quantity. |
| `calcula_distribution_tests` | Shapiro–Wilk, D'Agostino, Anderson–Darling, KS, moments, bootstrap CIs, Q-Q points. |

## API

| Route | Purpose |
|---|---|
| `POST /api/campaigns {goal, mode: "loop"}` | Start a project. |
| `GET /api/campaigns/{id}` | The full record: charter, ledger, rounds, dashboard, estimate, activity. |
| `GET /api/campaigns/{id}/thesis?format=pdf\|docx\|md\|html\|bundle` | The thesis. |
| `GET /api/campaigns/{id}/files/{name}` | A figure. Only plain `.png` and `.svg` names inside the project's folder. |
| `POST /api/campaigns/{id}/continue {instruction}` | Another round of research. |

## Settings

| Setting | Default |
|---|---|
| `TRIBOS_RESEARCH_SANDBOX_TIMEOUT_S` | 300 |
| `TRIBOS_RESEARCH_MAX_ROUNDS` | 12 |
| `TRIBOS_RESEARCH_MAX_HOURS` | 8 |
| `TRIBOS_RESEARCH_MAX_TEST_RUNS` | 120 |
| `TRIBOS_RESEARCH_PARALLEL_TESTS` | 2 |
| `TRIBOS_RESEARCH_CODEACT_STEPS` | 10 |
| `TRIBOS_RESEARCH_TEST_RETRIES` | 2 |
| `TRIBOS_RESEARCH_STAGNATION_ROUNDS` | 2 |
| `TRIBOS_RESEARCH_CROSS_CHECK` | on |
| `TRIBOS_THESIS_PDF_ENGINE` | `auto` (`chromium`, or the `fpdf` fallback) |

Details are in [configuration.md](../configuration.md).
