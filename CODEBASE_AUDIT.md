# Tribos Codebase Audit

**Date:** 2026-10-25 · **Branch:** `tribos-transformation` (includes the uncommitted working tree)

**How this was checked:**
- **Automated checks:** pytest, ruff, mypy, `tsc`, ESLint and the web test suite.
- **Manual review:** a line-by-line review of `tribos/`, `app/backend/`, `web/src/`, CI and Docker.
- **Reproduction:** most items were reproduced by running the code. The rest were confirmed by reading both sides of the code.

Every item has an ID (for example `SEC-1`) so you can track it. Severity levels:
- 🔴 **Critical:** security hole or data loss.
- 🟠 **High:** broken feature or wrong answer.
- 🟡 **Medium:** a feature that works incorrectly in common cases.
- ⚪ **Low:** an edge case, or code hygiene.

---

## ✅ Fix status (2026-10-25)

All items in §1–§4 are fixed. §5–§7 are mostly fixed; the items left open are listed below. Every fix has a regression
test in a `tests/test_fix_*.py` file or in `web/tests/webFixes.test.mts`. Nothing has been committed yet.

**Checks after the fixes:**
- **Python tests:** 1326 passed, 15 skipped, 0 failed (was 1101 passed, 2 failed).
- **CI lint gates:** `ruff --select F,E9` and `bandit --severity-level high` both clean, across `tribos`, `app`, `tests` and `scripts`.
- **Env reference:** `gen_env_reference.py --check` passes.
- **Web:**
  - `tsc` clean.
  - ESLint: 0 errors, 162 warnings (was 209).
  - `npm test`: 142/142 pass.
  - `next build` succeeds.

**New shared modules:**
- `tribos/sources/keys.py`: one evidence-key format (SUP-5).
- `tribos/axiom/safe_expr.py`: the allowlist expression parser (SUP-1).
- `tribos/agents/result_keys.py`: result-key constants (SUP-4).
- `tribos/agents/stem_evidence.py`: STEM evidence renderers (SUP-9).
- `tests/test_no_biomedical_leftovers.py`: the leftover-term guard (SUP-11).

**New bugs found and fixed during the work:**
- `normalize_literature_id` callers unpacked `(kind, id)` in the wrong order, so pinned-paper lookups searched for the literal string "doi".
- `evals/scoring.py` parsed model answers with an unrestricted `parse_expr`, which allowed code execution.
- Literal power towers such as `9^9^9^9` hung the parser; they are now refused before evaluation.
- The sandbox's read allowlist would have exposed the repository through the editable install's `sys.path`.
- The lexicon mapped "damped oscillator" to the undamped preset.
- The `vivarix` fit phase imported a package that no longer exists.

**Still open:**
- Split `web/src/app/page.tsx` (still about 4k lines; skipped to save time).
- Remaining ESLint warnings: about 130 `any`, about 33 React-hooks, and 7 `<img>`.
- SUP-2 (sandbox in a container): only the in-process hardening is done (IO guard, SymPy parser guard, `RLIMIT_NPROC`).
- SUP-6 (generated OpenAPI types): the frontend/backend contracts were aligned by hand, not generated.
- mypy as a CI gate (about 290 typing errors predate this work).
- Biomedical citation specs and the synapta/lumicell memory branches are kept, because stored history and tests still read them.
- Archivon is not passed `year_from`.
- `thinking_budget_tokens` is UI-only.
- Fitting an ODE to data in the agentic fit phase.
- Stale docs: `docs/developer/TESTING_LINTING.md`, `docs/cloud/*`, `SCIENTIFIC_VALIDATION_AND_ARCHITECTURE.md` and the routing examples in `evals.md`.
- CI runs the full test matrix twice (`tests_tribos.yml` and `tests_scientific_validation.yml`).
- Bandit B608 warnings (medium severity, likely false positives) still need `# nosec` with a reason.

---

## 0. Health snapshot (before the fixes)

| Check | Result |
| :--- | :--- |
| `pytest` | **2 failed**, 1101 passed, 14 skipped. Commit `9f591ce` says "100% test pass", which is not true. |
| `ruff check tribos app tests` | 1 unsorted import. The `F`/`B`/`E9` rules report 2 `B008` (FastAPI `Depends`/`Body` defaults, harmless). |
| `mypy tribos app` | 292 errors in 74 files. Mostly typing noise; the real ones are listed below (`BRK-1`, `BRK-6`). |
| `tsc --noEmit` (web) | Clean. |
| ESLint (web) | 0 errors, 209 warnings: 135 `any`, 26 unused vars, 37 React-hooks violations, 7 `<img>`. |
| `npm test` (web) | 124/124 pass. |
| **CI** | **The Python test workflow never runs on real code** (see `CI-1`). |
| Git | 104 modified files (+5.7k lines) and about 60 untracked new modules, all uncommitted. The app cannot start without some of them (see `CI-4`). |

---

## 1. 🔴 Security issues: fix first

### SEC-1: Sandbox escape through SymPy string parsing
- **Where:**
  - [tribos/agentic/sandbox/runner.py:359-363](tribos/agentic/sandbox/runner.py#L359-L363)
  - [tribos/agentic/sandbox/policy.py:197-199](tribos/agentic/sandbox/policy.py#L197-L199)
- **Problem:** `sympy.sympify("<string>")` and `sympy.parse_expr` call `eval` with the real `builtins`. The AST policy never inspects string contents.
- **Reproduced:** inside the sandbox, `sympy.sympify("__import__('os').getcwd()")` returned the host path, with zero policy violations. The same route reads any file (`open('pyproject.toml')`) and `os.environ`, which includes API keys.
  - On Windows, only the Job Object's process limit stopped `subprocess`.
  - On Linux there is no `RLIMIT_NPROC`, so this gives full code execution.
- **Fix:**
  - Patch `sympy.parsing.sympy_parser` in the sandbox bootstrap so it uses `_restricted_builtins()`, or ban string arguments to `sympify`, `S`, `parse_expr` and `lambdify`.
  - Add `RLIMIT_NPROC`.
  - In the long term, run the sandbox in a container (see `SUP-2`).

### SEC-2: Expression-parser blacklist bypassed with Unicode (code execution through Axiom and Dynamis tools)
- **Where:** [tribos/axiom/engine.py:32](tribos/axiom/engine.py#L32) (`_FORBIDDEN_RE`) and [tribos/axiom/engine.py:193](tribos/axiom/engine.py#L193) (`safe_parse_expr`).
- **Problem:** the `__|import|eval…` blacklist runs **before** Python's NFKC normalisation. Full-width characters such as `＿＿ｃｌａｓｓ＿＿` pass the check and then evaluate as real dunders.
- **Reproduced:** `safe_parse_expr("Integer(1)._＿ｃｌａｓｓ＿＿")` returns the class object. Walking `__mro__` and `__subclasses__()` from there gives arbitrary code execution. The input is model- or user-controlled (`axiom_solve`, `axiom_simplify`, `dynamis_*` and so on).
- **Fix:** run `unicodedata.normalize("NFKC", s)` before the check, and reject non-ASCII identifiers. Better still, use an AST allowlist parser that forbids attribute access (see `SUP-1`).

### SEC-3: networkx file read/write outside the sandbox work directory
- **Where:** [tribos/agentic/sandbox/policy.py:89-106](tribos/agentic/sandbox/policy.py#L89-L106)
- **Problem:** `WRITER_ATTRIBUTES` and `READER_FUNCTIONS` are fixed lists. `nx.write_edgelist` and `nx.read_adjlist` are not on them.
- **Reproduced:** both wrote and read files at absolute paths outside the work directory.
- **Fix:** default-deny any `write_*`, `to_*`, `save*`, `read_*`, `load*` or `from_file` call. Also hook `io.open` and `os.open` at runtime inside the child process.

### SEC-4: The weak-secret check (SEC-009) is dead and would crash
- **Where:** [app/backend/auth.py:53-59](app/backend/auth.py#L53-L59)
- **Problem:** `secret_strength_problems()` imports `secret_problems` from `tribos.config.settings`, which doesn't exist (`ImportError`, reproduced). Nothing calls it either, including `validate_environment`. The documented "short bearer tokens / HS256 secrets are rejected at startup" protection does not exist.
- **Fix:** implement `secret_problems` in settings, and call it from `validate_environment`.

### SEC-5: Plan-approval gate skips the main code-execution tools
- **Where:** [tribos/agentic/plan_graph.py:415-426](tribos/agentic/plan_graph.py#L415-L426)
- **Problem:** `is_expensive_tool` matches only `vivarix_*`, `calibrat` and `analysis_*`.
- **Effect:** `calcula_run_python`, `calcula_run_sagemath` and the `dynamis_simulate` / `dynamis_parameter_scan` / `dynamis_fit` tools run without the user's approval.
- **Fix:** use registry tags instead of name patterns (see `SUP-3`).

### SEC-6: SageMath code-execution tools can be replayed and are exposed over MCP
- **Where:** `UNSAFE_TOOL_RE` / `tool_replay_refusal` in `tribos/provenance/`
- **Problem:** `tool_replay_refusal('axiom_sagemath', entry)` returns `None`, so `axiom_sagemath` and `calcula_run_sagemath` are treated as safe to replay and to expose over MCP.
- **Fix:** add `sage` to `UNSAFE_TOOL_RE`, or tag these tools `executes_code`.

### SEC-7: Docker Compose publishes on all interfaces
- **Where:** [docker/compose.yml:27-28](docker/compose.yml#L27-L28) and [docker/compose.yml:41-42](docker/compose.yml#L41-L42)
- **Problem:** the ports are `"8000:8000"` and `"3000:3000"`, but the code comments and the auth-disabled warning say "127.0.0.1 only".
- **Effect:** with `TRIBOS_AUTH_MODE=disabled`, the warning tells users to set `TRIBOS_ALLOW_INSECURE=1`, and the unauthenticated API is then reachable from the whole LAN.
- **Fix:** publish as `127.0.0.1:${TRIBOS_API_PORT:-8000}:8000`, and the same for the web port.

---

## 2. 🟠 Broken code: crashes, wrong names, dead paths

| ID | Where | Problem | Fix |
| :--- | :--- | :--- | :--- |
| BRK-1 | [tribos/extensions/archivon.py:112,142,164](tribos/extensions/archivon.py#L112), [tribos/extensions/physis.py:168,201,222,243](tribos/extensions/physis.py#L168) | `ErrorType.UPSTREAM_ERROR` does not exist; the member is `UPSTREAM_API_ERROR`. Every error path raises `AttributeError` inside its `except` block. Upstream outages therefore become `INTERNAL_ERROR`, and are never retried or counted by the circuit breaker. | Rename to `UPSTREAM_API_ERROR`. |
| BRK-2 | [tribos/extensions/archivon.py:151](tribos/extensions/archivon.py#L151) | `recommend_papers(paper_ids=…)` does not match the signature `recommend_papers(seed_identifiers, limit)`, so `archivon_recommend` **always fails** with `TypeError` (hidden by BRK-1). | Pass `seed_identifiers=paper_ids`. |
| BRK-3 | [tribos/agents/orchestration/gather.py:334](tribos/agents/orchestration/gather.py#L334) | It checks for `dynamis_find_equilibrium`, but the tool is `dynamis_equilibrium`, so it always falls back to the `vivarix_compute_steady_state` alias (see LOG-2). The result is also stored as `dynamis_steady`, while the orchestrator and prompts read `dynamis_equilibrium` / `vivarix_steady_state`. | Use the correct tool name, and one result key everywhere (see SUP-4). |
| BRK-4 | [tribos/agentic/confidence.py:360](tribos/agentic/confidence.py#L360) | `from ..lithoscribe.evidence_grading import …`: the module was moved to `tribos/archivon/grading.py`. The `ImportError` is swallowed, so graded documents get the "ungraded" weight 0.25. | Import from `..archivon.grading`. |
| BRK-5 | [tribos/agents/prompts.py:43](tribos/agents/prompts.py#L43) | `SYNTHESIS_SYSTEM_PROMPT = r"""\`: in a **raw** string, a trailing `\` is not a line continuation. The prompt sent to the LLM starts with a backslash and contains **17 literal `\`+newline sequences** (reproduced). | Remove the `r` prefix (and escape any real backslashes), or remove the trailing backslashes. |
| BRK-6 | [tribos/axiom/engine.py:1248](tribos/axiom/engine.py#L1248) | `'\neq'` inside an f-string is a newline followed by `eq`, so non-identity results emit broken LaTeX. | Use `r'\neq'`. |
| BRK-7 | [app/backend/main.py:48](app/backend/main.py#L48) | Imports `tribos.vision.reader` at module level, but `tribos/vision/` and `routers/vision.py` are **untracked**. A clean checkout or CI build fails with `ModuleNotFoundError`. | Commit the files (see CI-4), and import lazily inside the handler. |
| BRK-8 | [web/src/services/agentService.ts:401](web/src/services/agentService.ts#L401) and [ProjectSelector.tsx:248](web/src/components/agentic/ProjectSelector.tsx#L248) vs [routers/projects.py:50](app/backend/routers/projects.py#L50) | The client sends `{invalid: true}` but the server field is `invalidate`. Pydantic drops the unknown key, and the response is a 200 that changes nothing. "Invalidate fact" never works (reproduced). | Send `invalidate`. Add `extra="forbid"` to request models. |
| BRK-9 | web `lookupGeo` → `/api/datasets/geo-lookup` | The endpoint does not exist (405, reproduced), so the ProvenanceForm "Verify" button always fails. It is also a biomedical leftover (GEO). | Remove the GEO verification UI, or replace it with a STEM source check. |
| BRK-10 | [tribos/agentic/executor.py:246-260](tribos/agentic/executor.py#L246-L260) | `_fill_targets` calls `chembl_resolve_drugs`, which is not registered. `run_known_drugs` / `run_known_genes` read result shapes from DGIdb, SynLethDB and ChEMBL. Each attempt uses up a tool-call budget slot. | Delete these paths. |
| BRK-11 | [tribos/agentic/topologies.py:278-401](tribos/agentic/topologies.py#L278-L401) | The supervisor/swarm fallback plans call tools that are not registered (`depmap_*`, `string_*`, `chembl_*`, `openfda_*`, `gtex_*`, `primekg_*`). When the model fails, the "fixed plan" does nothing beyond a literature search. | Write STEM fallback legs (axiom / dynamis / physis calls). |
| BRK-12 | [tests/test_answer_format.py:28](tests/test_answer_format.py#L28), [tests/test_answer_reconcile.py:228](tests/test_answer_reconcile.py#L228) | Two failing tests. They assert clinical prompt rules ("phase III RCT…", "primary report is in `<evidence>`…") that the STEM prompt rewrite removed. | Decide whether the "cite the primary report" rule should come back (it is domain-neutral), then update the tests. |

---

## 3. 🟠 Logic errors and wrong answers

### Answers ignore tool results or use wrong ones

- **LOG-1 (Critical for answer quality): STEM tool results never reach the synthesis model.**
  - **Where:** [tribos/agents/prompts.py:415-562](tribos/agents/prompts.py#L415-L562)
  - **Problem:** `build_evidence_block` renders only `synapta`, `vivarix`, `lumicell`, `lithoscribe` and `websurfer`. No `EvidenceSource` is ever registered (`register_source` has no callers). So Dynamis trajectories, Physis constants, Calcula output and Axiom results are dropped, or rendered as an empty `<vivarix model_id="None">` block. The model answers from memory while the UI shows that the tools succeeded.
  - **Fix:** add `<dynamis>`, `<physis>`, `<calcula>` and `<axiom>` renderers, or register EvidenceSources for them.
- **LOG-2: The `vivarix_*` compatibility aliases return a canned system.**
  - **Where:** [tribos/tools/registry.py:515-587](tribos/tools/registry.py#L515-L587)
  - **Problem:** they ignore `biomodel_id`, `parameter_overrides` and `target_species`, and always simulate or scan a damped oscillator. They still report success.
  - **Example:** "Steady state of Lotka-Volterra" returns the fixed point x=0, v=0 of an oscillator. `hypothesis.py` still drives its in-silico tests through this alias.
  - **Fix:** map the arguments to real Dynamis inputs, or return `VALIDATION_ERROR`.
- **LOG-3: Axiom is selected but never run in the classic pipeline.**
  - **Where:** [authoritative_orchestrator.py:1171-1180](tribos/agents/authoritative_orchestrator.py#L1171-L1180) and [query_planner.py:1316-1325](tribos/agents/query_planner.py#L1316-L1325)
  - **Problem:** `decisions["axiom"]` is set, but no stage starts an Axiom task. "Solve dy/dx + 2y = e^{-x}" gets no symbolic solve under the Classic framework.
  - **Fix:** add an Axiom task to `run_computations`.
- **LOG-4: Calcula runs a placeholder script.**
  - **Where:** [gather.py:161-174](tribos/agents/orchestration/gather.py#L161-L174)
  - **Problem:** `ctx.computation_code` is never set anywhere, so every Calcula run executes `result = {'status': 'completed'}` and reports "Sandboxed Python Computation succeeded".
  - **Fix:** generate the code (planner or LLM), or skip Calcula when there is none.
- **LOG-5: Preset matching uses raw substrings.**
  - **Where:** [gather.py:183-204](tribos/agents/orchestration/gather.py#L183-L204)
  - **Problem:**
    - "damped harmonic oscillator" matches `harmonic_oscillator`.
    - "desired angle" matches `sir`, because "de**sir**ed" contains "sir".
    - Anything unmatched silently runs `damped_oscillator`.
  - **Fix:** match on word boundaries, longest key first. When nothing matches, run nothing and add a scope note.

### Literature and citations

- **LOG-6: A total literature outage is reported as success and cached for 6 h.**
  - **Where:** [archivon/engine.py:368-401](tribos/archivon/engine.py#L368-L401) and [tools/reliability.py:827](tribos/tools/reliability.py#L827)
  - **Problem:** the clients swallow errors and return `[]`. The search then returns success with 0 passages, and the empty result is cached.
  - **Fix:** return an error status per source, and set `partial`/fail when every source failed.
- **LOG-7: arXiv and zbMATH citations are not supported.**
  - **Where:** [agents/citations.py:104-127](tribos/agents/citations.py#L104-L127)
  - **Problem:** `_KEY_SPECS` knows PMID, DOI, NCT and ChEMBL, but not arXiv or Zbl. The prompt tells the model to cite `arXiv:…`, and those citations get no chip or passage.
  - **Related:** debate critiques citing arXiv are thrown away ([topologies.py:870-888](tribos/agentic/topologies.py#L870-L888)).
  - **Fix:** see SUP-5.
- **LOG-8: The planned literature search is computed, then thrown away.**
  - **Where:** [extensions/archivon.py:83](tribos/extensions/archivon.py#L83)
  - **Problem:** `pinned_ids`, `keywords`, `search_queries` and `year_from` end up in `**kwargs` and are ignored. The search-plan queries are EuropePMC Lucene syntax that no Archivon source understands. `retrieval.queries` reports queries that were never run.
- **LOG-9: Pinned IDs are fetched one after another.**
  - **Where:** [archivon/engine.py:356-359](tribos/archivon/engine.py#L356-L359)
  - **Problem:** 4-5 DOIs or arXiv IDs exceed the 30 s tool timeout.
  - **Fix:** use `asyncio.gather` and batch the arXiv ids.
- **LOG-10: Gap and counter-evidence searches pass `max_articles` and `keywords`.**
  - **Where:** [specialists.py:559-563](tribos/agentic/specialists.py#L559-L563)
  - **Problem:** `archivon_literature_search` takes `max_results`, so the extra arguments are silently dropped (a request for 4 articles returns 15).
- **LOG-11: Two incompatible evidence-key formats.**
  - **Where:** [specialists.py:419-436](tribos/agentic/specialists.py#L419-L436) vs [nli.py:638-645](tribos/agentic/nli.py#L638-L645)
  - **Problem:** one side uses `ARXIV:`/`ZBL:`, the other `PMID:`/`DOI:`/`passage:`. The "never re-check a claim against its own source" check misses, and the source-match conflict check never fires.

### Math and physics checking

- **LOG-12: Inverse trig is parsed as a reciprocal.**
  - **Where:** [tribos/verify/latex_math.py](tribos/verify/latex_math.py)
  - **Problem:** `\tan^{-1}(1)` is read as `1/tan(1)`, so a correct `\tan^{-1}(1)=\pi/4` is **flagged as failed** (reproduced). The same happens for sin, cos, sec, csc and cot.
- **LOG-13: `\log` handling.**
  - **Where:** [tribos/verify/latex_math.py](tribos/verify/latex_math.py)
  - **Problem:** `\log` is always the natural log, so `\log 1000 = 3` fails. `\log_{10}` / `\log_2` cannot be parsed at all.
  - **Fix:** support subscript bases, and decide the default base for engineering text.
- **LOG-14: The single-equation dimensional check reads variables as units.**
  - **Where:** [tribos/physis/units.py:149](tribos/physis/units.py#L149)
  - **Problem:** `F = m*a` is reported non-homogeneous (Pint reads F as farad and a as annum). The multi-equation path has an `_is_symbolic_term` guard; this path does not.
- **LOG-15: Inequality constraints crash.**
  - **Where:** `dynamis_optimize` in [tribos/dynamis/engine.py](tribos/dynamis/engine.py)
  - **Problem:** `"x + y >= 1"` contains `=`, so it is split as an equation into `"x + y >"`, which raises a parse error.
  - **Fix:** convert `>=`, `<=`, `>` and `<` to the SLSQP `fun ≥ 0` form.
- **LOG-16: `_is_real_value` returns `True` on any exception.**
  - **Where:** [tribos/axiom/engine.py:316](tribos/axiom/engine.py#L316)
  - **Problem:** a value SymPy cannot evaluate is treated as real, so the real-domain filter can let a complex root through.

### Agent routing and control

- **LOG-17: Clarification stops fully specified ODE questions.**
  - **Where:** [agentic/clarify.py:148-162](tribos/agentic/clarify.py#L148-L162)
  - **Example:** "Simulate dx/dt = -2x + sin(t), x(0)=1" ends the turn with "Which model? Give a **BioModels id**" (reproduced).
  - **Fix:** count equations, systems and `simulation_plan` as a model.
- **LOG-18: Counter-evidence sends drug-safety searches.**
  - **Where:** [counter_evidence.py:173-186](tribos/agentic/counter_evidence.py#L173-L186) and [specialists.py:676-679](tribos/agentic/specialists.py#L676-L679)
  - **Example:** "Navier-Stokes equations adverse events" and "Ti-6Al-4V adverse events" (reproduced).
  - **Fix:** STEM negation queries ("X counterexample", "X limitations").
- **LOG-19: The router's stakes regex fires on ordinary STEM words.**
  - **Where:** [agentic/router.py:165-176](tribos/agentic/router.py#L165-L176)
  - **Problem:** clinical words ("interactions", "children", "dose", "elderly") match "fluid-structure interactions" and "children of a B-tree node". The run is flagged safety-critical and escalated to Debate, which costs extra model calls.
- **LOG-20: The "pure math/physics" skip gates never fire.**
  - **Where:** [gaps.py:353-356](tribos/agentic/gaps.py#L353-L356) and [counter_evidence.py:240-250](tribos/agentic/counter_evidence.py#L240-L250)
  - **Problem:** they read `SubQuestion.domain` (the field is `focus`) and `ctx.subquestions` (it does not exist). The intent names they compare against don't match the planner's intents.
- **LOG-21: The "not requested" gap filter never matches.**
  - **Where:** [gaps.py:97-108](tribos/agentic/gaps.py#L97-L108)
  - **Problem:** the module names were renamed, but `MODULE_PATTERNS` still uses the old keys.
- **LOG-22: The simulation ban and the planner disagree.**
  - **Where:** [plan_graph.py:411-412](tribos/agentic/plan_graph.py#L411-L412)
  - **Problem:** `dynamis_parameter_scan`, `dynamis_equilibrium`, `dynamis_fit_parameters` and `dynamis_optimize` are not classed as simulation tools, so they still run when the user said "no simulation".
- **LOG-23: The planner ignores `evidence_need.skip_retrieval`.**
  - **Where:** [planner.py:161,169](tribos/agentic/planner.py#L161) and [plan_graph.py:455-482](tribos/agentic/plan_graph.py#L455-L482)
  - **Problem:** literature searches still run after the evidence-need decision ruled them out.
- **LOG-24: HDF5 and MAT attachments skip approval and clarification.**
  - **Where:** [approval.py:93](tribos/agentic/approval.py#L93) and [clarify.py:164](tribos/agentic/clarify.py#L164)
  - **Problem:** only the `h5ad` and `table` kinds count.
  - **Fix:** use `ANALYSABLE_KINDS`.
- **LOG-25: The hypothesis direction check only knows "overexpression".**
  - **Where:** [hypothesis.py:939](tribos/agentic/hypothesis.py#L939)
  - **Problem:** the STEM kinds "elevation" and "variation" get their factors forced to wrong values.
- **LOG-26: Effort profile keys don't match.**
  - **Where:** [draft.py:306-312](tribos/agents/orchestration/draft.py#L306-L312)
  - **Problem:** the low-effort profile uses depth `"minimal"` but the dictionary key is `"concise"`, so low effort never gets its instruction. The deep and exhaustive prompts inject "biomarker stratification" and "pharmacokinetic pathway".

### Memory and follow-up questions

- **LOG-27: Follow-up questions resolve to a fake gene.**
  - **Where:** [finalize.py:65-72](tribos/agents/orchestration/finalize.py#L65-L72) and [research_memory.py:41](tribos/utils/memory/research_memory.py#L41)
  - **Problem:** `SUBJECT_KEYS = (gene, drug, disease, biomodel_id)` discards the STEM subject keys.
  - **Example:** "Simulate the Lorenz system", then "now for 50 s", produces a `gene='Lorenz'` entity and runs the wrong preset.
- **LOG-28: Memory consolidation is biomedical-only.**
  - **Where:** [research_memory.py:56-63,765-799](tribos/utils/memory/research_memory.py#L56-L63)
  - **Problem:** entity extraction only knows genes and cancers. Dynamis, Physis, Axiom and Calcula results are stored as "Provisional Literature" with confidence 0.5.
- **LOG-29: Alias keys double-count results.**
  - **Where:** [gather.py:141-142,361-364](tribos/agents/orchestration/gather.py#L141-L142)
  - **Problem:** `lithoscribe` is the same object as `archivon`, and `vivarix` the same as `dynamis`. The "N of M sources", memory storage and failure counts are all doubled.
- **LOG-30: `upsert_facts` reads then writes without a write lock.**
  - **Where:** [project_store.py:358-407](tribos/utils/memory/project_store.py#L358-L407)
  - **Problem:** concurrent runs in one project duplicate facts and miss contradictions.
  - **Fix:** `BEGIN IMMEDIATE`, plus a unique constraint.

### Web UI and backend contract

- **LOG-31 (High): The frontend rewrites "Clinical" in every saved answer.**
  - **Where:** [web/src/app/page.tsx:766-777](web/src/app/page.tsx#L766-L777)
  - **Problem:** `.replace(/\bClinical\b/gi, "Tribos")` runs on the answer text, so "pre-clinical testing" becomes "pre-Tribos testing". It also breaks the export hash check ("content differs from verified run").
  - **Fix:** normalise only `agent` labels.
- **LOG-32 (High): Dataset upload kinds don't match.**
  - **Where:** web [datasetService.ts:9,76-82](web/src/services/datasetService.ts#L9) vs [tribos/datasets/store.py:44-53](tribos/datasets/store.py#L44-L53)
  - **Problem:**
    - The UI accepts `.h5ad`, `.xml` and `.sbml`; the server rejects them with 415.
    - The server accepts `.h5`, `.mat`, `.xlsx`, `.parquet` and `.json`; the UI blocks them.
    - The UI messages still mention cells, genes, AnnData and COPASI.
- **LOG-33: The saved "Nemotron 3 Ultra" model resets on every reload.**
  - **Where:** [page.tsx:300](web/src/app/page.tsx#L300)
  - **Problem:** the migration check `includes("nemotron-3-")` also matches the current Ultra model.
  - **Fix:** list the retired model ids explicitly.
- **LOG-34: The effort level is ignored for the Classic framework.**
  - **Where:** [page.tsx:1172](web/src/app/page.tsx#L1172)
  - **Problem:** `agent_options` is only sent for non-classic frameworks, so Classic plus Ultra runs at medium.
- **LOG-35: The real reason a background job failed is hidden.**
  - **Where:** [page.tsx:1147](web/src/app/page.tsx#L1147) and [agentService.ts:300-318](web/src/services/agentService.ts#L300-L318)
  - **Problem:** an `error` SSE event is treated as a dropped connection. The user sees "stream ended before the answer finished" instead of the server's message.
- **LOG-36: Security-middleware errors look like "backend unreachable".**
  - **Where:** [app/backend/main.py:104-114](app/backend/main.py#L104-L114)
  - **Problem:** `SecurityMiddleware` runs outside CORS, so its 400/403/413 responses have no `Access-Control-Allow-Origin` header. For example, an export over 16 MB shows "Tribos backend is unreachable".
- **LOG-37: Opening a background job that had images duplicates the question bubble.**
  - **Where:** [page.tsx:1421](web/src/app/page.tsx#L1421) vs [routers/jobs.py:65](app/backend/routers/jobs.py#L65)
- **LOG-38: `client_request_id` promises de-duplication the server never does.**
  - **Where:** [page.tsx:1170](web/src/app/page.tsx#L1170)
  - **Problem:** a dropped stream starts a second full run, which takes the user's second chat slot.
- **LOG-39: Legacy datasets (kind `h5ad`/`sbml`) are invisible but still count against quota.**
  - **Where:** [tribos/datasets/store.py:226,351,382](tribos/datasets/store.py#L226)
  - **Problem:** they can't be listed or deleted, so they can fill the 2 GB per-user quota.

---

## 4. 🟡 CI, build and config problems

### CI-1: The Python test workflow never runs on the real code
- **Where:** [.github/workflows/tests_tribos.yml](.github/workflows/tests_tribos.yml)
- **Problem:**
  - The path filters are `tribos/tribos/**`, `tribos/vivarix/**` and `tribos/synapta/**`, and none of those directories exist.
  - pylint, ruff and bandit scan `tribos/tribos` (empty).
  - The tests run `tribos/tribos/tests/`, which doesn't exist; the real tests are in `tests/`.
  - The coverage gate is 2 %.
- **Fix:** filter on `tribos/**`, `app/**` and `tests/**`, scan `tribos app`, run `pytest tests/`, and raise the coverage gate.

### CI-2: The Docker build and release workflows point at Dockerfiles that don't exist
- **Where:** [.github/workflows/docker_build.yml:22-32](.github/workflows/docker_build.yml#L22-L32) and [release.yml:190-195](.github/workflows/release.yml#L190-L195)
- **Problem:** they use `tribos/tribos/Dockerfile` and `tribos/vivarix/Dockerfile`. The real files are `docker/backend.Dockerfile` and `docker/web.Dockerfile`.
- **Related:** [.github/labeler.yml:61](.github/labeler.yml#L61) and `CODEOWNERS` have the same stale paths.

### CI-3: The Docker image sets a variable that no longer exists
- **Where:** [docker/backend.Dockerfile:71](docker/backend.Dockerfile#L71)
- **Problem:** it sets `TRIBOS_PRIMEKG_DIR`, which no setting defines, so every container start logs a config problem. With `TRIBOS_STRICT_CONFIG=1` the backend refuses to start, and the web container (`depends_on: service_healthy`) never comes up.
- **Fix:** remove the line, and remove the PrimeKG comments in the Dockerfile and compose.yml.

### CI-4: Large uncommitted work
- **Problem:** 104 modified files and about 60 untracked new modules (`tribos/axiom/agent.py`, `problem.py`, `verifier.py`, `tribos/vision/`, `tribos/verify/math_claims.py`, the new web components and so on). The API imports some of them at startup (BRK-7).
- **Fix:** commit in logical chunks. Delete or ignore the stray `gofullpage-localhost-*.pdf` and the empty `test_uploads/`.

### CI-5: Settings missing from the registry
- **Problem:** `TRIBOS_MAX_BODY_MB`, `TRIBOS_MAX_EXPORT_BODY_MB` and `TRIBOS_EVAL_JUDGE_MODEL` are read by the code, but are not in the settings registry, `.env.example` or `docs/configuration.md`. Setting any of them triggers an "unknown setting" warning, and strict mode refuses to start.
- **Related:** `TRIBOS_API_PORT` from compose should be listed as an external name.

### CI-6: No rename migration
- **Problem:** nothing migrates the old `phronesis_*` names:
  - **Browser:** the localStorage keys for history, settings, token, backend URL and theme are orphaned, and still use up quota.
  - **Server:** `.phronesis_*` data directories and `PHRONESIS_*` env vars are silently ignored.
- **Fix:** see SUP-8.

### CI-7: No `.gitattributes`
- **Problem:** every file shows LF→CRLF warnings on Windows.
- **Fix:** add `* text=auto eol=lf`.

---

## 5. 🔧 Existing features that need small fixes (polish)

**Backend / agents**
- [ ] `prompts.py:142`: the extra rules are numbered from 9, but `<grounding_rules>` ends at 7.
- [ ] `prompts.py:504-516` and `sources/names.py:35,48`: Archivon passages are labelled "EuropePMC / PubMed", and `lithoscribe` is shown as "Europe PMC". Use each passage's real `source`, and add `arxiv_id`/`zbl_id` attributes.
- [ ] `prompts.py:555`: an empty `<biodiscovery_ranking>` section is always emitted.
- [ ] `CORRECTION_SYSTEM_PROMPT` asks for "species name" and "effect-size context". Rewrite it for STEM.
- [ ] `prompts.py:216` and `evidence_level()`: the evidence scale is still clinical (guideline > phase III RCT > … > in vitro). STEM needs a scale like peer-reviewed > preprint > textbook > web.
- [ ] `plan.py:242,265`: "No biomedical topic found" should be "No scientific or engineering topic found".
- [ ] `llm_factory.py:207-212`: the gpt-4o fallback client has no `timeout` / `max_retries`.
- [ ] `gather.py:31`: `except BaseException` can swallow the outer task's cancellation.
- [ ] `research_memory.py:981-988`: there is no `LIMIT` when scoring the whole thread each turn, and the `contradictions.node_id` index is missing.
- [ ] `project_store.py:454-466`: a verified fact keeps its `"unverified"` tag.
- [ ] `registry.py:186-190`: the `execute` docstring sits after the first statement, so it is not a docstring.
- [ ] `sources/__init__.py:5`: unused `Optional` import.
- [ ] `router._first_json`: the greedy `\{.*\}` breaks on trailing braces.
- [ ] `jobs.JobManager._deleted` grows without bound.
- [ ] `sandbox/runner._Capped` caps characters, not bytes, and Windows has no disk-write cap.
- [ ] `policy.py` allows `import anndata`, but the runtime `_ALLOWED` list doesn't include it.
- [ ] `planner.LITERATURE_TOOL` pins the legacy `lithoscribe_literature_synthesis`, while the rest of the code uses `archivon_literature_search`, so duplicate searches are not deduplicated.
- [ ] `main.py:152`: `_health_cache` / `HEALTH_CACHE_SECONDS` are never used, so the health cache never expires.
- [ ] `/api/vision/read`: one global `Semaphore(1)`, and the 10 MB body is parsed before waiting. Add a per-user slot. Full re-runs (`routers/export.py:224`) bypass `_chat_slots`.
- [ ] `a2a.py`: the Agent Card builds its URLs from the `Host` header. Use the configured public URL.
- [ ] `export/markdown_blocks.py`: `*` and `_` inside `$…$` can become emphasis in the PDF export.
- [ ] `physis/units.py`: `__all__` is incomplete.
- [ ] README: says "Plan-and-Execute (API Default)", but the default is `auto`.

**Web**
- [ ] Split [web/src/app/page.tsx](web/src/app/page.tsx) (4,093 lines) into hooks and components.
- [ ] Fix the 37 React-hooks violations: setState in effects, refs read during render, `Date.now()` in render, and two "used before declared" errors at `page.tsx:330,703`.
- [ ] Remove the 26 unused imports and variables. `FrameworkMenu`, `EffortMenu`, `isFrameworkDropdownOpen` and `activeAgentId` are dead code.
- [ ] Replace the 135 `any` types with real types (generate them; see SUP-6).
- [ ] `MarkdownRenderer.tsx:332`: the `node` prop leaks onto `<code>`.
- [ ] `MarkdownRenderer.tsx:~450`: the `[web]` link replacement doesn't escape `$&` or `)`.
- [ ] `RoutePreviewChip` keeps a stale label after the text changes.
- [ ] `readImage` uses a bare `fetch`, so a 401 never raises the auth banner. Use `apiFetch`.
- [ ] Ctrl+N handler (`page.tsx:820`) is registered with `[]` deps, so new threads get the initial framework and model.
- [ ] Unsent drafts are not deleted or moved when the history setting changes, or when a conversation is deleted or expires.
- [ ] Add `"type": "module"` to `web/package.json` (Node `MODULE_TYPELESS_PACKAGE_JSON` warning).
- [ ] `_ACRONYMS` (`main.py:305`) and `lib/dynamicTitle.ts` still list KRAS, EGFR, NSCLC, PrimeKG and similar.

---

## 6. 🧩 Incomplete or half-removed features (biomedical leftovers)

The phronesis→tribos and biomedical→STEM change left dead code behind. Much of it is not just unused: it actively misroutes STEM questions (see LOG-17 to LOG-28).

- [ ] **`tribos/verify/verifier.py` (3,049 lines) is still the "Clinical Verifier":** PMID/FDA grounding, trial-phase patterns, `_PROTEIN_CHANGE_RE`. `extract_drug_mentions()` is stubbed to return `[]`. Rewrite it for STEM claims, or cut it down.
- [ ] **Hypothesis engine** (`agentic/hypothesis.py`): in-silico testing needs a `BIOMD…` model, and the deterministic hypotheses (OpenTargets, SynLethDB) are all biomedical. STEM questions get no tested hypotheses.
- [ ] **Specialists without tools:** the target, omics (Lumicell) and chemistry (ChEMBL/openFDA) specs remain. "Simulation" is still described as "mechanistic biological models".
- [ ] **Entity lexicon:** `DISEASE_HEAD_WORDS` is empty, and `find_offline_diseases()` / `coordinated_disease_terms()` always return `[]`.
- [ ] **Stub helpers:** `topologies._named_trials` returns `[]`, and `gaps._drugs_in` returns `set()`.
- [ ] **Oncology-only requirement facets:** disease, regimen, line of treatment, FDA/EMA, OS/PFS.
- [ ] **Unused search pipeline:** `search_plan.py` builds a EuropePMC Lucene query plan (and spends an LLM call on it) that is never used for retrieval.
- [ ] **Dead helpers:** `question_trial_names`, `question_disease_words`, `prioritise_question_diseases`, `_BIOMODEL_LITERATURE`, `self.vivarix` dummy, `BioContextMCPClient` stub, and the `"ads_skipped_note": … if False else None` line.
- [ ] **Leftover registry entries:** `plan_graph.TOOL_SOURCES`, `OMICS_TOOL_PREFIXES` and `approval._DOCKING_RE` list unregistered tools.
- [ ] **Leftover labels:** `project_store.SINGLE_VALUED_RELATIONS` (`germline_classification`), and `query_planner._ALLOWLISTS["trials"]` (`clinical_trials`).
- [ ] **Unused effort settings:** `thinking_budget_tokens`, `enable_thinking`, `short_desc` and `badge` are never read by the backend.
- [ ] **Biomedical export:** `export/report_model.py` and `bundle.py` still produce allele frequencies, BioModels reproducibility rows and clinical REPRODUCE text.
- [ ] **Web provenance form:** GEO, IRB and consent fields, `cells_by_genes`, and the geo/cellxgene/biomodels sources. The new backend `DatasetSource` values (experiment, simulation, benchmark…) are not offered.
- [ ] **Leftover wording:** the "Clinical Memory Engine", `"clinical_supervisor_synthesis"` origin, "kinetic simulation" label, `TRIBOS_UPLOAD_MAX_MB_H5AD`, `FRAMEWORK_DESCRIPTIONS[SUPERVISOR]` ("disease targets… omics"), the counter-evidence cue words ("negative trial"), `CLAIM_TYPE_WEIGHTS["clinical"]` and the planner `_ID_FIELDS` (nct_id, chembl_id, ensembl_id).

---

## 7. 🛠 Supporting features that fix whole classes of bugs

Most of the bugs above come from a few patterns: names repeated as string literals, denylists instead of allowlists, and no shared contract between the frontend and backend. These changes remove those patterns.

| ID | Supporting change | Fixes |
| :--- | :--- | :--- |
| **SUP-1** | **One safe expression parser.** An AST allowlist (names, numbers, operators, whitelisted SymPy functions; no attribute access, no dunders) with NFKC normalisation, used by Axiom, Dynamis, Physis and the verifiers. Add a fuzz test with Unicode and known escape payloads. | SEC-2, LOG-15, part of SEC-1 |
| **SUP-2** | **Container-isolated sandbox** (Docker, gVisor or nsjail): no network, a read-only root, a tmpfs work directory, a PID limit, and no environment secrets. Inside the child, patch `builtins.open`, `io.open` and the SymPy parser globals. | SEC-1, SEC-3, the Windows disk-cap gap |
| **SUP-3** | **Tool capability tags in the registry** (`executes_code`, `simulation`, `expensive`, `network`, `replay_unsafe`, `domain`). Approval, the simulation ban, MCP exposure and replay refusal all read the tags instead of regexes on names. | SEC-5, SEC-6, LOG-22, LOG-24 |
| **SUP-4** | **Tool-name and result-key constants** (a `ToolName` enum and a `ResultKey` enum). Ban string literals for tool names outside the registry with a unit test that checks every referenced name is registered. Remove the alias keys from counting. | BRK-3, BRK-10, BRK-11, LOG-29 |
| **SUP-5** | **One evidence-key and citation module.** `normalize_key()` handles DOI, arXiv, Zbl, MR, ADS, OpenAlex and passage keys, and citations, NLI, the verifier, the debate and confidence code all use it. | LOG-7, LOG-11, debate critique loss |
| **SUP-6** | **A generated API contract.** Export FastAPI's OpenAPI schema, then generate the TS types with `openapi-typescript` in CI. Use `extra="forbid"` on request models. Add `GET /api/datasets/limits` so the UI reads the allowed kinds and size caps. | BRK-8, BRK-9, LOG-32, most `any` types |
| **SUP-7** | **A domain-neutral subject model.** Replace `gene/drug/disease/biomodel_id` with `concept/equation/system/material/quantity` in the query context, memory, clarify, counter-evidence and hypotheses. | LOG-17, LOG-18, LOG-27, LOG-28 |
| **SUP-8** | **Rename migration.** A one-time localStorage copy from `phronesis*` to `tribos*`, and startup warnings when `PHRONESIS_*` env vars or `.phronesis_*` directories exist. | CI-6 |
| **SUP-9** | **STEM evidence renderers.** Register `EvidenceSource`s for Dynamis, Physis, Calcula and Axiom so every successful tool reaches the synthesis model, with a test that each registered tool produces non-empty evidence. | LOG-1, LOG-3, LOG-4 |
| **SUP-10** | **Honest upstream failures.** The Archivon clients return a status per source. Don't cache results where every source failed, and count them in the breaker. | BRK-1, LOG-6 |
| **SUP-11** | **A leftover-term guard test.** A pytest that fails if prompts or user-facing strings contain banned biomedical terms (PubMed, BioModels, clinical trial, gene, drug, …), with an explicit allowlist. | Stops regressions in §6 |
| **SUP-12** | **Fixed CI.** Correct the path filters, run `pytest tests/`, `ruff check tribos app` and `mypy` on changed files as gates, set a real coverage gate, run the `gen_env_reference --check` step, and add a check that every `TRIBOS_*` the code reads is a registered setting. | CI-1, CI-2, CI-5, BRK-12 |
| **SUP-13** | **Regression tests for every item above,** written before the fix, especially the reproduced ones: the SEC-1/2/3 escape payloads, `\tan^{-1}`, `F = m*a`, `x+y>=1`, the Lorenz follow-up question, `{invalid:true}`, and the `UPSTREAM_ERROR` paths. | Prevents reintroduction |
| **SUP-14** | **Bind to localhost by default** in compose, and put CORS outermost so security-middleware errors keep their CORS headers. | SEC-7, LOG-36 |

---

## 8. Suggested order of work

1. **Security, same day:** SEC-1, SEC-2, SEC-3, SEC-4, SEC-7. Then SUP-1 and SUP-2.
2. **Make CI real:** CI-1, CI-2, CI-4 (commit the untracked files), BRK-12, SUP-12.
3. **One-line crash fixes:** BRK-1, BRK-2, BRK-3, BRK-4, BRK-5, BRK-6, BRK-8, LOG-31, LOG-33.
4. **Answer correctness:** LOG-1 (via SUP-9), LOG-2, LOG-3, LOG-4, LOG-12, LOG-14, LOG-17.
5. **Structural cleanup:** SUP-3, SUP-4, SUP-5, SUP-6, SUP-7. Then delete the leftovers in §6.
6. **Polish:** §5, and the `page.tsx` split.
