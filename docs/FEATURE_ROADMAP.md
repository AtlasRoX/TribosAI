# Feature roadmap: tasks for AI coding agents

Read [../AGENTS.md](../AGENTS.md) first. It has setup, commands, architecture and conventions.

Each task below is self-contained: a goal, where it plugs in, the files to create or own, and acceptance criteria. The tasks can be done in any order and by different agents at the same time, as long as each agent edits only its task's files. The shared files are:

- `tribos/extensions/__init__.py`
- `tribos/config/settings.py`
- `app/backend/main.py` (router list)
- `tribos/agents/stem_evidence.py`
- `web/src/components/artifacts/registry.tsx`

In the shared files, add small entries only. Do not restructure them.

**Status (2026-10-25):** all bugs from [../CODEBASE_AUDIT.md](../CODEBASE_AUDIT.md) are fixed and every test suite is green. The tasks below have **not been started**, except:

- **T6:** `tribos/dynamis/interactive.py` exists (simulation, bifurcation and vector-field helpers; imports and lints clean). It is untested and has no router.
- **T10:** `web/src/services/agentService.ts` and `web/src/types/agentic.ts` contain an unfinished project API client.
- **Infrastructure:** `web/src/components/artifacts/registry.tsx` exists and is wired into `MessageArtifacts.tsx`. Use it.

**Definition of done for every task:**

- New tests pass.
- The full `pytest` suite stays at 0 failures.
- `ruff --select F,E9` and `bandit --severity-level high` are clean.
- Web: `npm run typecheck`, `npx eslint src` (0 errors), `npm test` and `npx next build` all pass.
- `scripts/gen_env_reference.py --check` passes. Run it after adding settings.

---

## T1: Fit ODE models to uploaded data

**Goal.** A user attaches measurements (CSV/XLSX/HDF5/MAT: a time column plus observed state columns) and asks "fit the damped oscillator to my data", or gives ODEs with unknown parameters.

**What to build.**

1. Map dataset columns to the state variables, by name or an explicit mapping. Auto-detect the time column (`t`, `time`, …).
2. Fit with `scipy.optimize.least_squares`, integrating with the Dynamis integrator. Support bounds, multi-start, a robust loss, and optionally fitting the initial conditions.
3. Report:
   - best-fit values, standard errors and 95% CIs, from `cov = s²(JᵀJ)⁻¹`;
   - the correlation matrix;
   - identifiability warnings: near-singular JᵀJ, |corr| > 0.95, or a CI wider than its value;
   - RSS, RMSE, R² per observed variable, AIC and BIC;
   - decimated residuals, and the fitted trajectory against the data.

**Where it plugs in.**
- `tribos/dynamis/engine.py` already has `dynamis_fit_parameters`: extend it rather than duplicate it.
- Wire `tribos/agentic/fit.py` to run the fit whenever a dataset is attached and a system is known. Today it says fitting is not run.
- Register the tools in `tribos/extensions/calibration.py` and `tribos/extensions/dynamis.py`.
- Reuse the artifact key `model_calibration` and upgrade `web/src/components/agentic/CalibrationArtifact.tsx` with: a fit-vs-data plot, a residual plot, a CI table and the warnings.
- Add an evidence renderer in `stem_evidence.py`.

**Also required by T6 and T8.** Add `"spec": {rhs, parameters, initial_state, t_span, method, model_name}` to every `dynamis_simulate_ode` and `dynamis_parameter_scan` result. These are the exact inputs that reproduce the run.

**Accept when:**
- Known parameters of a damped oscillator and of logistic growth are recovered from noisy synthetic data, inside their CIs.
- Correlated parameters raise the warning.
- Column mapping works.
- `spec` is present on simulation results.
- The agentic fit phase runs end to end with an attached dataset, using the test fakes.

## T2: PDE solver

**Goal.** Dynamis only handles ODEs. Add `tribos/dynamis/pde/` (numpy/scipy only) and `tribos/extensions/pde.py` (tool `dynamis_solve_pde`, domain `dynamis`).

**Equations, on rectangular domains:**
- heat/diffusion, 1D and 2D;
- wave, 1D and 2D;
- Poisson/Laplace, 1D and 2D;
- advection-diffusion, 1D;
- reaction-diffusion (Fisher-KPP), 1D;
- viscous Burgers, 1D.

**Boundary and initial conditions.** Dirichlet, Neumann and periodic boundary conditions. Initial conditions and sources are expressions in x, y, t, parsed with `safe_expr`.

**Methods.**
- Method of lines with `solve_ivp`, using BDF for stiff cases, or Crank-Nicolson for heat.
- Central or leapfrog for wave, with a CFL check.
- A sparse direct solve for Poisson.
- Refuse or adapt unstable explicit settings, and report the stability number.

**Verification, the core value.**
- A mesh-convergence study at N, 2N and (when cheap) 4N, giving the observed order p, a Richardson error estimate and a "converged" flag.
- Comparison with the analytic solution when one is known.
- Conservation checks: mass for periodic diffusion, energy for wave.

**Output.**
- 1D: about 20 snapshots on the x grid.
- 2D: grids of at most 80×80.
- A convergence table and probe values.
- Caps on grid size and wall time, set through settings.

**UI.**
- Artifact key `pde`, card `web/src/components/artifacts/PdeArtifact.tsx`: a 1D line plot with a time slider, a 2D heatmap with a legend (theme-aware), the convergence table, and stability and verification badges.
- Add an evidence renderer.

**Accept when:**
- 1D heat matches the analytic solution with order ≈ 2.
- 1D wave matches d'Alembert's solution.
- A 2D manufactured Poisson problem is solved.
- Mass is conserved for periodic diffusion.
- A CFL violation is refused or adapted.
- An unsafe expression is rejected.
- The planner selects the tool for "solve the heat equation on [0,1]…".

## T3: Uncertainty propagation

**Goal.** Add `tribos/physis/uncertainty.py` with the tool `physis_propagate_uncertainty` (domain `physis`).

**Inputs.**
- An expression, parsed with `safe_expr`.
- Variables `{name: {value, uncertainty, unit?, distribution: normal|uniform|lognormal}}`.
- Optional correlations.

**Methods.**
- `linear`: first-order GUM, using SymPy partial derivatives, with sensitivity coefficients and each input's percentage contribution.
- `monte_carlo`: vectorised numpy, seedable, giving the mean, std, 95% interval and skewness.
- `both`: runs the two and warns when they disagree, which signals nonlinearity.

**Other requirements.**
- Units through Pint.
- Optionally fill CODATA constants (c, G, h, k_B, e, m_e, N_A, …) with their uncertainties from Physis, and say so in the output.
- Format the result as value ± U with k = 2: the uncertainty to 2 significant figures, and the value rounded to match.
- Artifact key `uncertainty`, card `artifacts/UncertaintyArtifact.tsx`: the result, a budget table with contribution bars, and the Monte Carlo histogram.

**Accept when:**
- Linear propagation for products and quotients adds relative uncertainties in quadrature.
- Monte Carlo agrees with linear propagation for a linear function.
- A nonlinear case produces the warning.
- Units propagate.
- CODATA autofill works.

## T4: Unit checking on every answer

**Goal.** Add `tribos/verify/units_audit.py` and run it automatically inside `math_claims.audit_answer`.

**What to check.** Extract quantity statements and equations with units from both text and LaTeX ("F = 50 N", `$E = mc^2 = 9.0\times10^{16}\,\mathrm{J}$`). Bind symbols to the quantities stated in the question and the answer, then check:

- (a) dimensional consistency, using Pint (`tribos/physis/units.py`);
- (b) that a stated numeric result matches its equation after unit conversion;
- (c) wrong unit labels, for example a pressure given in N.

Unbound or ambiguous symbols are "not evaluated" and are never flagged.

**Output.**
- Results go to `verification_report.units`: `{checked, consistent, inconsistent: [{statement, lhs_dim, rhs_dim, reason}], not_evaluated}`.
- A contradiction becomes a defect that is fed back to the writer, the same way math-claim failures are.
- Web: show a compact "Units: N checked, M inconsistent" line in `web/src/components/VerificationNotice.tsx`.

**Accept when:**
- Wrong dimensions and wrong numeric results are caught.
- Correct physics paragraphs and ambiguous symbols are not flagged.
- LaTeX units (`\mathrm{}`, `\,`) are handled.
- A defect is created and fed back.

## T5: Formal proof checking with Lean, optional

**Goal.** Add `tribos/verify/formal/`, a Lean 4 runner.

**Runner.**
- Find `lean` or `lake` from `TRIBOS_LEAN_PATH` or PATH.
- If `TRIBOS_LEAN_PROJECT` points to a Mathlib project, run `lake env lean file.lean` there.
- Run in a temp directory with a timeout and memory limit.
- Proofs containing `sorry`, `admit` or new axioms are **not** verified.
- Cache results by content hash.

**Math-agent integration** (`tribos/axiom/agent.py`, `tribos/agentic/math_agent.py`).
- For "prove …" questions, the LLM formalises the statement and proof, then repairs it on compiler errors up to `TRIBOS_FORMAL_MAX_REPAIRS` times.
- Show the Lean statement next to the question, so the reader can judge whether it is faithful.
- Status:
  - "formally verified (Lean)" only on a clean compile;
  - otherwise "formalisation failed" with the last error;
  - "formal checker unavailable" when Lean is not installed. In that case nothing else changes.
- This never overrides the existing SymPy checks.

**Plumbing and UI.**
- Tool `axiom_formal_check` (domain `axiom`), classified `executes_code`.
- Settings: `TRIBOS_LEAN_PATH`, `TRIBOS_LEAN_PROJECT`, `TRIBOS_FORMAL_TIMEOUT_S`, `TRIBOS_FORMAL_MAX_REPAIRS`, `TRIBOS_FORMAL`.
- Artifact key `formal_proof`, card `artifacts/FormalProofArtifact.tsx`: the Lean code with a copy button, a status badge and the compiler output.

**Accept when** these work, tested with a **fake `lean` executable** (a Python script that emulates success, error and `sorry`):
- parsing compiler output;
- the timeout;
- rejecting `sorry`;
- the cache;
- the "unavailable" path;
- math-agent integration with a fake LLM.

## T6: Interactive simulation (sliders, phase portraits, bifurcation)

**Started.** `tribos/dynamis/interactive.py` exists: finish it and test it.

**Backend: `app/backend/routers/simulate.py`.** Add the module to the router list in `main.py`. Endpoints:

- `POST /api/simulate` takes `{model_name?, rhs?, parameters?, initial_state?, t_span, num_points<=2000, method?}` and returns the `dynamis_simulate_ode` result shape.
- `POST /api/simulate/bifurcation` takes `{spec, parameter, start, stop, steps<=200, observable, transient_fraction}` and returns `{parameter, values, points:[{value, maxima, minima}]}`.
- Optional: `POST /api/simulate/vector_field` takes `{spec, x_var, y_var, x_range, y_range, n<=25}`.

For all endpoints:
- Authenticate with `get_current_user`, and apply a per-user rate limit.
- Run each call in a thread with a 10 s timeout.
- When there is no `spec` (old messages), resolve `model_name` to a preset in `ODE_PRESETS`.

**Web.**
- Add `web/src/components/simulation/*` and `web/src/services/simulateService.ts`, and extend `SimulationArtifact.tsx` and `TrajectoryCharts.tsx`.
- When `data.spec` exists, show an "Explore" panel:
  - a slider and numeric input per parameter (auto range 0–2× the value, or log scale; min and max editable);
  - initial-condition inputs and a t_end input;
  - a 250 ms debounce, aborting any in-flight request;
  - the original run kept as a faint overlay, plus a Reset button.
- Never mutate the stored message.
- Phase-portrait view, with an optional vector field; a bifurcation tab.
- Call through `apiFetch`, so a 401 raises the auth banner. Show readable messages for 429 and timeouts.

**Accept when:**
- Endpoint shapes, caps, the timeout, auth and the preset fallback are tested.
- A bifurcation diagram shows multiple maxima past the threshold (e.g. Rössler).
- Web tests cover range inference, debounce and abort, and data shaping.

## T7: Read uploaded papers and reproduce them

**Upload.**
- `.pdf` becomes dataset kind `paper` in `tribos/datasets` and in `GET /api/datasets/limits`.
- Validate the magic bytes, and enforce a page cap and a size cap (`TRIBOS_UPLOAD_MAX_MB_PDF`, default 25).
- Reject encrypted PDFs with a clear message.
- Tabular-only paths (`sandbox.ANALYSABLE_KINDS`) must ignore papers.

**Extraction: `tribos/papers/`.**
- Text per page with `pypdf`, plus title, authors and DOI or arXiv id, and section boundaries.
- Numbered display equations, converted to SymPy where possible through `safe_expr` and `tribos/verify/latex_math.py`.
- ODE systems ("dx/dt = …").
- Parameter tables ("k = 200 N/m").
- Stated numeric results ("we obtain T = 1.42 s").
- Use OCR (`tribos/vision`) on near-empty pages only if it is available.
- Every extracted item keeps its page number and the verbatim source line.

**Tools (domain `archivon`).**
- `archivon_read_paper {dataset_id}`.
- `archivon_reproduce_paper {dataset_id, targets?}`. It runs Dynamis (`tribos/dynamis/stated_ode.py`) on each extracted ODE system and re-evaluates closed-form claims with SymPy. Each claim gets a status:
  - reproduced;
  - differs, with both values and the relative difference;
  - not reproducible, listing the missing parameters.
- Never report "reproduced" when inputs were guessed.
- Make sure attached papers reach the run as attachments.

**Web.**
- Artifact key `paper_reproduction`, card `artifacts/PaperArtifact.tsx`: metadata, equations rendered with KaTeX, the parameter table, and the reproduction table with page references.
- Accept PDFs in `datasetService.ts`, `types/datasets.ts`, `DatasetLibrary.tsx` and the composer attach components.

**Accept when** these are tested on PDFs generated with fpdf2 inside the tests:
- extraction with page references;
- a correct claim marked reproduced;
- a wrong claim marked differs;
- missing parameters marked not reproducible;
- upload validation;
- the limits endpoint listing `.pdf`.

## T8: Jupyter notebook export, and fixes to the existing exports

**Fixes first.**
- **Known bug:** Word export drops inline math ("The equation of motion is  with ."). Reproduce it by POSTing a message with `$...$` math to `/api/export/docx` through TestClient with `base_url="http://localhost"` and auth disabled.
- Render math as native OMML in DOCX (convert the common LaTeX subset), or at minimum as a mathtext image with the LaTeX as alt text.
- Make sure the PDF (fpdf2) never shows raw `$\frac…`.
- Check the following in PDF, DOCX and MD: display math, tables containing math, code blocks, the reference list, simulation figures, Unicode (Greek, °, ±), long tables, lists.
- Check that the web "Everything" zip (`web/src/lib/zip.ts`, `exportService.ts`) contains what it claims.
- Check that "Copy as LaTeX" (`web/src/lib/markdownToLatex.ts`) compiles, escaping `% & _ #` and producing tabular tables.
- Write one regression test per bug.

**Then the notebook.**
- New format `ipynb`: `POST /api/export/ipynb`, included in the bundle, with an ExportMenu entry "Jupyter notebook (.ipynb)".
- Build valid nbformat-4 JSON by hand, with no new dependency. Cells, in order:
  1. title and metadata;
  2. the question;
  3. the answer as markdown;
  4. per recorded tool call, a runnable cell using plain libraries:
     - SymPy for Axiom;
     - `solve_ivp` with the exact spec for Dynamis (from the `spec` added in T1, falling back to the manifest digest);
     - the verbatim Python code for Calcula;
     - constants with their uncertainty and source for Physis;
  5. a plot cell;
  6. a references cell;
  7. a versions cell;
  8. an assertion cell checking that the re-run matches the recorded values within tolerance.
- Never include secrets or absolute paths.

**Accept when:**
- The DOCX contains OMML (or images) for inline math.
- The PDF text has no raw LaTeX.
- The notebook JSON is valid.
- The concatenated code cells run in a subprocess and reproduce a Dynamis result and an Axiom result.

## T9: Engineering calculators backed by standards and material data

**Goal.** Add `tribos/engcalc/` with tools `physis_engineering_calc {calculator, inputs, material?}` and `physis_list_calculators` (domain `physis`).

**Each calculator has:**
- unit-validated inputs (Pint), with optional uncertainties that flow through T3;
- its formulas;
- results with units;
- an explicit safety factor or utilisation;
- its assumptions and validity limits (for example, thin-wall only when t < r/10, and Euler only above the transition slenderness);
- the reference it follows, with the section, e.g. Roark, Shigley, ASME BPVC VIII-1 UG-27, Incropera, Colebrook.

**Calculators:**
- beam deflection and bending stress: simply supported and cantilever, under a point load and a UDL;
- Euler/Johnson buckling;
- thin-wall pressure vessel: hoop and longitudinal stress, and required thickness with joint efficiency;
- shaft torsion, plus combined bending and torsion with von Mises;
- bolt preload and torque;
- fatigue: Basquin, Goodman/Gerber/Soderberg, Miner;
- pipe pressure drop: Darcy-Weisbach with Colebrook/Swamee-Jain;
- heat exchanger: LMTD and ε-NTU;
- layered-wall conduction.

**Materials.**
- A built-in table: S235, S355, A36, 304, 316, Al 6061-T6, Al 7075-T6, Ti-6Al-4V, copper, concrete, PEEK.
- Properties: E, ν, yield, UTS, density, k, CTE, plus a source column.
- Label the values as typical properties, not design allowables.

**UI.** Artifact key `engineering_calc`, card `artifacts/EngineeringCalcArtifact.tsx`: inputs, results, a utilisation bar, warnings and the citation.

**Accept when:**
- Each calculator matches a textbook value (e.g. cantilever tip deflection PL³/3EI).
- Validity warnings fire.
- Input units are converted.
- An unknown calculator returns an error.
- The planner selects the tools for relevant questions.

## T10: Shared projects with review, and the ChatGPT-style sidebar

### Backend contract

All endpoints are under `/api/projects`, require auth and use JSON.

**Project object:**
`{id, name, description, instructions, icon, color, owner_id, role ("owner"|"editor"|"viewer"), member_count, fact_count, invalid_fact_count, pending_review_count, file_count, created_at, updated_at}`

**Projects:**
- `POST ""` with `{name, description?, instructions?, icon?, color?}`.
- `GET ""` returns `{projects}`: both owned and shared projects.
- `GET /{id}`, `PATCH /{id}` and `DELETE /{id}`. PATCH needs owner or editor; DELETE is owner only.

**Members:**
- `GET /{id}/members` returns `{members:[{user_id, role, added_at, added_by}]}`.
- `POST /{id}/members` with `{user_id, role}` (owner only).
- `PATCH /{id}/members/{user_id}` with `{role}` (owner only).
- `DELETE /{id}/members/{user_id}`: the owner, or members removing themselves (leaving).
- Insufficient role returns 403. A non-member gets 404, which never reveals that the project exists.

**Files:**
- `GET /{id}/files` returns `{files:[{dataset_id, name, kind, size_bytes, added_at, added_by}]}`.
- `POST /{id}/files` with `{dataset_id}`. The dataset must belong to the caller.
- `DELETE /{id}/files/{dataset_id}`.
- Owner or editor only.

**Memory:**
- `GET /{id}/memory` takes an optional `?review_status=` filter.
- Each fact gains `review_status` (pending|approved|rejected), `reviewed_by`, `reviewed_at` and `review_note`.
- `POST /{id}/memory` with `{subject, relation, object, confidence?, note?}` adds a fact that starts approved.
- `POST /{id}/memory/{fact_id}/review` with `{decision: approve|reject, note?}`. Rejecting a fact invalidates it.
- `GET /{id}/memory/{fact_id}/history` returns `{versions}`, oldest first.
- Facts written by runs start as "pending".

**Activity:**
- `GET /{id}/activity?limit=50` returns `{events:[{id, at, actor, action, target_type, target_id, summary}]}`.
- Actions: project.created/updated, member.added/removed/role_changed, file.added/removed, fact.added/edited/invalidated/approved/rejected/deleted, run.completed.

**Schema migration.** Existing SQLite databases must upgrade in place, as follows:
- The owner becomes a member.
- Verified facts become approved, and all other facts become pending.
- Cap the size of the activity log.

**Runs.** For a chat or job request with `project_id`, where the caller is a member:
- inject the project's instructions as a delimited, spotlighted block of user-authored guidance;
- auto-attach the project's files, in addition to any `dataset_ids`;
- exclude rejected facts from recall.

Members may use project files owned by other members, with read-only access checked through membership. Everything else stays isolated per user.

### Web

**Sidebar.** Extract the sidebar from `web/src/app/page.tsx` (inline from about line 1737) into `web/src/components/sidebar/*`, redesigned like ChatGPT's:
- brand plus a collapse toggle, collapsing to an icon rail with tooltips;
- New chat;
- Search chats, extending `CommandPalette.tsx`;
- a Projects section: "New project", projects with emoji and colour, expandable to their chats, with shared projects marked;
- history grouped as Today, Yesterday, Previous 7 days, Previous 30 days, then by month, with pinned chats on top;
- a row "…" menu on each chat: Rename (inline), Pin, Move to project, Export, Delete (with confirmation);
- a profile menu at the bottom that keeps all existing settings reachable;
- a mobile drawer with a focus trap, closed with Esc;
- the collapsed state persisted;
- light and dark themes from the existing CSS variables;
- every existing sidebar feature kept working.

**Projects UI.**
- Chats carry `thread.projectId` in localStorage. Migrate existing threads unchanged. Deleting a project asks whether to keep or delete its chats.
- Chats inside a project send `project_id`.
- A project view, `web/src/components/projects/*`, with tabs:
  - Chats;
  - Instructions;
  - Files;
  - Memory: search, a review filter, approve/reject with a note, edit/invalidate/delete, add a fact, and a history drawer per fact;
  - Members;
  - Activity.
- Viewers see a read-only version.
- A create/edit dialog with an emoji picker and colour swatches.
- Detect missing endpoints and hide those parts gracefully.
- Move logic into hooks (`web/src/hooks/useThreads.ts`, `useProjects.ts`, …) so `page.tsx` gets **smaller** (it is about 4k lines today).

**Accept when:**
- Backend: tests cover migration from the old schema, the role rules (403/404), members, files, review, history, activity, and the run integration (instructions in the context, files attached).
- Web: tests cover recency grouping across day boundaries, pin ordering, moving chats and the migration, API error handling, and search.
