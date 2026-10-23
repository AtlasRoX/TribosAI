# Tribos Migration Brief: Phronesis → Tribos

*As of 2026-10-23. A copy is also kept as a claude.ai doc, "Tribos Migration Brief". The design plan is in
[tribos-transformation.md](tribos-transformation.md).*

## 1. Summary

Tribos is the Phronesis codebase turned into an engineering and scientific R&D assistant for mathematicians,
physicists, engineers and other researchers. The reasoning framework stays the same. The clinical domain is
replaced by mathematics, physics, engineering, and applied math and CS. Made by ChronoStrider Engineering.

**Where it stands:** 2 of 9 phases are done and committed on the local branch `tribos-transformation`: Phase 0 in
`9740d79` and Phase 1 in `3ed03bd`. Phase 2, the rename from `phronesis` to `tribos`, comes next.

**What stays unchanged:**
- the orchestrator stages, the five reasoning modes and the auto-router;
- every agentic phase;
- budgets, run control, jobs, memory, reliability, provenance, export, evals, MCP and A2A;
- the FastAPI backend and the Next.js UI.

**What is new:**
- five specialist agents: Archivon, Axiom, Dynamis, Calcula and Physis;
- a verifier that checks units, constants and computed results;
- the sandbox, on by default, with SymPy;
- KaTeX maths rendering in the UI, and equations in exports;
- maths, physics and engineering eval suites.

### Roadmap

```
 lead session, in order                                       legend: [x] done  [>] next  [ ] to do
 [x] 0 Clean ──▶ [x] 1 Prune ──▶ [>] 2 Rename ──▶ [ ] 3 Core
     9740d79        3ed03bd       phronesis→tribos   tables, verifier
                                                        │
          ┌──────────────────┬──────────────────┬───────┴──────────┐   parallel subagents
          ▼                  ▼                  ▼                  ▼
 [ ] 4 Agents        [ ] 5 Backend       [ ] 6 Web UI        [ ] 7 Evals, docs
     5 tool packages     API and export      KaTeX, artifacts    suites, mkdocs
          └──────────────────┴─────────┬────────┴──────────────────┘
                                       ▼
                                 [ ] 8 Verify  (tests, merge)
```

Phases 0 to 3 touch the whole codebase, so they run one after another. Phases 4 to 7 each own separate
directories, so they can run side by side before the final verification.

## 2. Decisions made with the owner

All of these were confirmed on 2026-10-23, and they drive every phase below.

| Topic | Decision |
| --- | --- |
| Rename depth | Full. The package `phronesis` becomes `tribos` and `PHRONESIS_*` env vars become `TRIBOS_*`. The CLI is `tribos-eval`, and docker, CI and docs follow. Nothing says Phronesis afterwards. |
| Domains | Pure mathematics, physics, engineering, and applied math and CS. |
| Agents | Five repurposed agents with new names: Archivon (literature), Axiom (symbolic maths), Dynamis (simulation and numerics), Calcula (computation and data), Physis (reference data). Synapta and Lumicell are removed. |
| Compute | The sandbox is on by default, with sympy, mpmath, networkx and pint added. Numeric and symbolic claims are verified against sandbox output. |
| Sources | Free: arXiv, Semantic Scholar, Crossref, OpenAlex, zbMATH Open, OEIS, NIST CODATA, Wikipedia and web search. Keyed: NASA ADS, Wolfram\|Alpha, Materials Project. |
| Maker credit | "Made by ChronoStrider Engineering", with the "Enginnerings" typo fixed. |
| Logos | The owner supplies them. The file slots are kept (section 8). |
| Leftovers | Deleted in phase 0. They can be recovered from commit `c55910c`. |
| Answer shape | Derivation first: Result → Derivation (LaTeX) → Verification → Assumptions & limits → References. |
| Git | Branch `tribos-transformation`, one commit per phase. |
| Repo URL | `github.com/AtlasRoX/trib` |
| Execution | The lead session does phases 0–3. Phases 4–7 go to parallel subagents, each owning separate files. Every phase ends with a review and the test gate. |

## 3. Codebase map

The control plane is domain-generic. The domain knowledge lived in three places, and those are what the migration
replaces:
- the vocabulary tables that drive routing and retrieval;
- the hard-wired Stage 1–2 evidence and compute blocks;
- the identifier and verification layer, which was built around PMID, NCT and ChEMBL ids.

At the start the repo had about 155k lines of Python and 21k lines of TypeScript, in 1,298 files.

**Pipeline**, run by `agents/authoritative_orchestrator.py::_execute_inquiry`:
1. **Stage 0, plan** (`orchestration/plan.py`): parse the question, recall memory, choose the framework, and run the
   agent phases `before_evidence` and `approve`.
2. **Stage 1, gather evidence** (`orchestration/gather.py::run_evidence`): literature, web and the registered
   evidence sources, run in parallel.
3. **Stage 2, compute** (`gather.py::run_computations`): today the Vivarix ODE simulation; it becomes Dynamis and
   Calcula.
4. **Stage 2b, augment** (`agent_rounds.augment`): the plan-execute DAG, supervisor or swarm, hypotheses, analyst,
   counter-evidence and NLI.
5. **Stage 3, prioritise** (`gather.prioritize`): the discovery ranking.
6. **Stage 4, draft** (`orchestration/draft.py`), followed by the `after_draft` rounds: gaps, escalation, debate and
   section repair.
7. **Stage 5, verify** (`orchestration/verify.py`): the verifier plus Reflexion-style correction, then the citation
   map.
8. **Stage 6, finalize**: confidence, memory write-back, the result and the run manifest.

| Module | Verdict | Notes |
| --- | --- | --- |
| `agentic/`: runtime, control, jobs, budget, llm, guardrails, plan_execute, executor, router_store | Keep | Generic. |
| `agentic/`: planner, decompose, clarify, gaps, nli, confidence, counter_evidence, hypothesis, topologies, specialists, tool_retrieval, router | Rewrite tables and prompts | The mechanisms stay; the vocabulary is biomedical. |
| `agents/query_planner.py` (1,868 lines), `query_context.py`, `search_plan.py`, `entity_lexicon.py` | Rewrite | Gene, drug and disease parsing becomes concept, equation and quantity parsing. |
| `agents/prompts.py`, `citations.py`, `discovery.py`, `orchestration/gather.py`, `draft.py` | Rewrite | Hard-coded Synapta, Vivarix and Lumicell evidence blocks. |
| `verify/verifier.py` (2,936 lines, `ClinicalVerifier`) | Split | Keep the grounding and numeric core; replace the clinical checks. |
| `extensions/`: hooks, id_families, export, sandbox, agentic | Keep, with new id families | The plug-in mechanism is generic. |
| `tools/`: registry, reliability, arg_repair, web_search | Keep | Rename `BiomedicalToolRegistry` to `ToolRegistry`. |
| `agentic/sandbox/` | Keep and extend | AST allowlist plus subprocess limits. Add sympy, mpmath, networkx and pint. |
| `export/`, `evals/`, `provenance/`, `datasets/` | Keep and adapt | Branding, maths rendering, new suites and new dataset kinds. |
| `lithoscribe/` (synthesis engine, grading, integrity, identifiers) | Replace with Archivon | Built around EuropePMC. |
| `vivarix/` | Replace with Dynamis | COPASI/SBML is replaced by SciPy. |
| `utils/biocontext/` | Remove along with Lithoscribe | The Lithoscribe engine still uses it. |
| `app/backend` | Adapt | Titles, `/api/agents`, MCP tool names, the A2A card and the GEO route. |
| `web/` | Adapt | Branding, KaTeX, citations, entity chips and artifacts. |

## 4. Progress so far

Phases 0 and 1 are committed. After the prune, the remaining suite is **860 passed, 74 failed**. The original code's
baseline was **1,792 passed, 5 failed**. The 74 failures are generic tests whose fixtures still use removed clinical
tools; phase 3 rewrites them.

| Phase | Commit | Done |
| --- | --- | --- |
| 0 Clean | `9740d79` | Deleted the root audit reports (`AUDIT_*`, `FIXES_*`, `Phronesis_*.md`), old design plans, biomedical notebooks, agent docs and diagrams, the legacy Streamlit apps (`app/frontend`), marker data files, the audit and biomedical scripts, and the stale `.claude/workflows`. Untracked `data/jobs` and `data/router`. Added `docs/plans/tribos-transformation.md`. |
| 1 Prune | `3ed03bd` | Removed `drugintel`, `diseaseintel`, `trials`, `variants`, `structintel`, `kgintel`, `sources_extra`, `tools/biocontext`, `synapta`, `lumicell` and the nested `phronesis/phronesis`. Removed the Lithoscribe langgraph stack (the S2/Zotero/PDF sub-agents and Hydra configs), 9 extensions and the SBML `agentic/calibrate.py` phase. Moved the verifier to `phronesis/verify/verifier.py`. Cut the Synapta and Lumicell stages from `gather.py` and their built-in tools from `tools/registry.py`. Removed 37 settings that were no longer read and regenerated `docs/configuration.md` and `.env.example`. Deleted 23 clinical test files and about 30 clinical test functions. |

**Kept on purpose for now:** `vivarix/`, `lithoscribe/` and `utils/biocontext/`. The orchestrator calls them directly,
so they are removed once Dynamis and Archivon land.

**Tests still failing after phase 1** (phase 3 fixes them by switching the fixtures to Tribos tools):
- `test_agentic_planning` (15), `test_agentic_loops` (7), `test_agent_platform` (4), `test_tool_retrieval` (2) and
  `test_agentic_foundation` (2). These cover the DAG, executor, supervisor, swarm, debate, MCP and tool retrieval, and
  their fixtures use ChEMBL, PrimeKG or Synapta tool names.
- `test_auto_router`, `test_evals`, `test_integration`, `test_prompts` and `test_retrieval_obligations`, which use
  clinical routing fixtures.
- `test_settings_registry::test_secret_values_are_never_logged`, which uses the removed `MILVUS_PORT`. Switch it to
  `PHRONESIS_MAX_RUNS` (default 500).
- The 5 baseline failures already failed before the migration, so they are not regressions.

**Dropped from the old system** (candidates for follow-up work): Zotero library sync and PDF question-answering
(RAG). Both lived only in the unused Lithoscribe langgraph stack and were never wired into the main app.

## 5. Phase 2: the rename

This is one scripted pass over every tracked text file, followed by a lock refresh and a test run. Replacement order
matters: the longer, more specific strings go first.

1. Move the package: `git mv phronesis tribos`.
2. Rename these files:
    - `.github/workflows/tests_phronesis.yml` becomes `tests_tribos.yml`.
    - `export/assets/phronesis-mark.png` and `phronesis-wordmark.png` become `tribos-*.png`.
    - `utils/memory/clinical_memory.py` becomes `research_memory.py`.
    - Delete `evals/data/clinical.jsonl`; phase 7 adds the new suites.
    - Untrack `utils/memory/clinical_memory.db`, which is runtime state.
3. Apply these text replacements, in this order:

| From | To |
| --- | --- |
| `AtlasRoX/phronesis-CS`, `ChronoStrider/Phronesis` | `AtlasRoX/trib` |
| `ChronoStrider Engineering (ChronoStrider Enginnerings)`, then `ChronoStrider Enginnerings` | `ChronoStrider Engineering` |
| `BiomedicalToolRegistry` | `ToolRegistry` |
| `register_default_biomedical_tools` | `register_default_tools` |
| `ClinicalMemoryEngine`, `get_clinical_memory_engine`, `_GLOBAL_CLINICAL_MEMORY`, `clinical_memory` | `ResearchMemoryEngine`, `get_research_memory_engine`, `_GLOBAL_RESEARCH_MEMORY`, `research_memory` |
| `ClinicalVerifier` | `TribosVerifier` |
| `BioDiscoveryEngine`, `BioDiscoveryAgent`, then `BioDiscovery` | `DiscoveryEngine`, `DiscoveryAgent`, `Discovery` |
| `AIAGENTS4PHARMA_LLM_MODEL` | `TRIBOS_LLM_MODEL` |
| `ClinicalRDAssistant` (web `page.tsx`) | `TribosAssistant` |
| `PHRONESIS` | `TRIBOS` |
| `Phronesis` | `Tribos` |
| `phronesis` | `tribos` |

4. Skip binary files, `.git`, `.venv` and `node_modules`. `uv.lock` and `web/package-lock.json` are text files, so the
   pass covers them too; the lock is regenerated in step 7 anyway.
5. In `pyproject.toml`:
    - Set `name = "tribos"`.
    - Set the description to "Engineering and scientific R&D assistant for mathematics, physics and engineering."
    - Entry point: `tribos-eval = tribos.evals.cli:main`.
    - Delete the `phronesis-primekg` entry point.
6. Update the dependencies:
    - **Remove** (nothing imports them any more):
      - Scientific and ML libraries: cell2sentence, einops, gseapy, igraph, joblib, pcst_fast, pubchempy,
        pygeneconverter, scanpy, torch_geometric, umap-learn.
      - LangChain and LLM extras: langchain-milvus, langchain-nvidia-ai-endpoints, langchain_ollama,
        langgraph_supervisor, ollama.
      - UI and plotting: gravis, plotly, plotly-express, seaborn, streamlit, streamlit-feedback.
      - Storage, scraping and integrations: gdown, nbformat, pymilvus, pyzotero, python-magic, datasets,
        cloudscraper, azure-identity, duckduckgo-search.
      - From the docs extras: mkdocs-jupyter.
    - **Keep until phase 4:**
      - copasi_basico, hydra-core, langgraph, langchain-community and langchain-experimental (used by Vivarix);
      - anndata and h5py (used by datasets).
    - **Keep:**
      - torch, transformers and sentence_transformers, for the NLI cross-encoder;
      - langchain-openai, for the LLM factory;
      - openpyxl, tabulate and pyarrow, for pandas I/O;
      - python-docx, fpdf2 and markdown-it-py, for export.
    - **Add:** sympy, mpmath, networkx and pint.
7. Run `uv lock`, then `uv sync --extra dev --python 3.12`.
8. Run `.venv/Scripts/python.exe scripts/gen_env_reference.py`, then run it again with `--check`.
9. Run `pytest tests -q -p no:cacheprovider`. Expect the same pass count as after phase 1.
10. Commit with the message `refactor(tribos): phase 2 - rename phronesis to tribos`.

**Check:** `git grep -il phronesis` should list nothing except the migration plan and this brief.

## 6. Phase 3: the domain core

Phase 3 keeps every mechanism and replaces its biomedical content. The paths below are the ones after the rename
(`tribos/…`).

| Mechanism | File | Phronesis content | Tribos content |
| --- | --- | --- | --- |
| Entity types | `agents/query_context.py` `EntityType` | gene, drug, disease, variant | concept, equation, quantity, constant, material, system |
| Query intents | `agents/query_planner.py` `INTENTS` | target, drug, trial, variant | derive, solve, prove, compute, simulate, design, estimate, explain, literature, data_analysis |
| Question types | `agents/search_plan.py` `QUESTION_TYPES` | treatment, diagnosis | proof, derivation, numerical, design/sizing, modelling, conceptual, literature review |
| Research-scope test | `query_planner._BIOMED_VOCAB_RE` | biomedical vocabulary | maths, physics and engineering vocabulary, plus LaTeX/equation detection |
| Router domains and stakes | `agentic/router.py` | domains: literature, clinical, molecular, computational. Stakes: patients, dosing | domains: literature, symbolic, numerical, reference. Stakes: structural, pressure, high-voltage, aerospace, life-safety |
| Decompose foci | `agentic/decompose.py` `FOCI` | clinical, drug, variant | math, physics, engineering, computation, literature, data |
| Tool vocabulary | `agentic/tool_retrieval.py` `DOMAIN_INTENTS`, `TOOL_INTENTS`, `QUERY_EXPANSIONS` | trial→nct, ic50→chembl | integral→axiom_calculus, ode→dynamis_simulate_ode, constant→physis_constants, sequence→physis_oeis |
| Specialists | `agentic/specialists.py` `SPECIALIST_SPECS` | literature, target, simulation, omics, chemistry | literature (Archivon and web), symbolic (Axiom), numerical (Dynamis), analysis (Calcula), reference (Physis) |
| Hard policy | `agentic/plan_graph.py`, `approval.py` | vivarix, lumicell, clinical_trials | dynamis (expensive), calcula (sandbox), archivon (always on) |
| Debate personas | `agentic/topologies.py` `PERSONAS` | methodologist, clinical skeptic, mechanistic biologist | rigorous mathematician; physicist (units, limits, conservation); practising engineer (assumptions, safety factors, standards) |
| Counter-evidence | `agentic/counter_evidence.py` | "<drug> adverse", failed trials | counterexample search in the sandbox; contradicting results; errata |
| Hypotheses | `agentic/hypothesis.py` | Vivarix knockdown and overexpression | conjecture tests over n or parameter ranges; Dynamis sensitivity; Elo ranking of approaches |
| Calibration | new `agentic/fit.py` (replaces the deleted `calibrate.py`) | SBML fitting | `dynamis_fit_parameters` against an uploaded table |
| Citation ids | `agents/citations.py` `_KeySpec`, `extensions/id_families.py` `FAMILIES`, web `lib/citations.ts` | PMID, NCT, ChEMBL, ENSG… | arXiv id, DOI, Zbl, MR, OEIS A-number, ADS bibcode, mp-id, ISBN, OpenAlex W-id, plus `comp:<n>` computation keys |
| Evidence ladder | `agents/prompts.py` `evidence_level` | guideline > RCT > … > computational | formal proof or textbook theorem > established theory > peer-reviewed > preprint > verified computation > estimate |
| Evidence XML | `prompts.build_evidence_block` | `<synapta>`, `<vivarix>`, `<lumicell>` | `<literature>`, `<computation>`, `<reference_data>`, `<simulation>` |
| Memory subjects | `utils/memory/research_memory.py` | gene, drug, disease, biomodel | concept, equation, material, system, model |
| Source authority | `utils/source_authority.py` | pharma and FDA hosts | publishers, standards bodies, arXiv, NIST, university hosts |
| Gather stages | `orchestration/gather.py` | Synapta, BioModels, Vivarix, Lumicell | Stage 1: Archivon, WebSurfer and Physis lookups. Stage 2: Calcula PAL-style compute (the LLM writes SymPy or NumPy code and the sandbox runs it), plus Dynamis when a model is given. |

**Synthesis prompt** (`agents/prompts.py` `SYNTHESIS_SYSTEM_PROMPT`). It opens with "You are Tribos, an engineering
and scientific R&D assistant…" and keeps the grounding and citation-audit rules. It adds these rules:
- write maths in LaTeX (`$…$` and `$$…$$`) and show the derivation;
- verify by computation and state the assumptions;
- check units, dimensions and limiting cases;
- cite only ids that appear in the evidence;
- never invent constants: take them from Physis/CODATA;
- for safety-critical design, add a caveat to check the applicable code or standard.

The answer format is Result → Derivation → Verification → Assumptions & limits → References, with confidence shown
per claim. About 20 phase prompts tagged `[phase:x]` need the same treatment. Keep those markers, because
`ScriptedLLM` routes on them.

**Verifier** (`verify/verifier.py`, where `ClinicalVerifier` becomes `TribosVerifier`):
- **Keep:**
  - identifier grounding;
  - the claim and NLI audit;
  - the numeric tolerance check, now against computation outputs;
  - confidence-line reconciliation, the limitations section, removable defects and date checks.
- **Remove:** the regimen and monotherapy checks, population and disease mismatch, HR/CI/p-value parsing, the
  primary-trial preference and regulatory claims.
- **Add:**
  - a check of constants against CODATA, within their uncertainty;
  - a units and dimension check with pint;
  - a check that computed results match within tolerance;
  - an identity spot check by Axiom random substitution.

**Tests:** rewrite the fixtures in `tests/fakes.py` and `agentic_fakes.py`, and the 74 failing tests, to use Tribos
tool names and physics or maths questions. Fakes return trimmed real responses only.

## 7. Phase 4: agents and tools

Each agent is a leaf package. It registers its tools through an extension module, `tribos/extensions/<agent>.py`,
which defines `register_tools(registry)`. The agents can be built in parallel because they share only the registry
interface (`ToolUniverseEntry`, `ToolResult`, `ErrorType`), which does not change. Every tool has:
- a Pydantic input schema;
- a timeout;
- a domain and tags;
- a `ToolResult` return value whose `data` carries citable ids.

| Agent | Package | Tools | Backend | Replaces |
| --- | --- | --- | --- | --- |
| Archivon (literature) | `tribos/archivon/` | `archivon_literature_search` (fans out across the sources and deduplicates by DOI/arXiv id), `archivon_paper_details`, `archivon_recommend` | httpx clients for arXiv, Semantic Scholar, OpenAlex, Crossref, zbMATH and ADS | `lithoscribe/`, `utils/biocontext/`, `lithoscribe_literature_synthesis` |
| Axiom (symbolic maths) | `tribos/axiom/` | `axiom_simplify`, `axiom_solve`, `axiom_calculus` (diff, integrate, limit, series), `axiom_dsolve`, `axiom_linalg`, `axiom_verify_identity`, `axiom_latex` | SymPy, run in the sandbox subprocess with a timeout | (new) |
| Dynamis (numerics and simulation) | `tribos/dynamis/` | `dynamis_simulate_ode`, `dynamis_equilibrium` (fixed points and Jacobian stability), `dynamis_parameter_scan`, `dynamis_optimize`, `dynamis_fit_parameters`, `dynamis_root_find` | SciPy `solve_ivp`, `optimize` and `fsolve`; models are given as a dict of equations that SymPy parses | `vivarix/` (COPASI/BioModels) and the `vivarix_*` tools |
| Calcula (computation and data) | `tribos/extensions/sandbox.py` plus `agentic/analyst.py` | `calcula_run_python` (was `analysis_run_python`), `calcula_describe_dataset` | the existing sandbox | the analyst CodeAct phase, which now triggers on any computation intent |
| Physis (reference data) | `tribos/physis/` | `physis_constants`, `physis_units`, `physis_oeis`, `physis_materials`, `physis_wolfram`, `physis_encyclopedia` | `scipy.constants` (CODATA 2022, offline), pint, OEIS, Materials Project, Wolfram LLM API, Wikipedia REST | (new) |

**Sandbox** (`agentic/sandbox/policy.py`, `__init__.py`):
- Allow `sympy`, `mpmath`, `networkx`, `pint`, `fractions`, `decimal` and `cmath`. Remove `anndata` and `scanpy`.
- Default to `TRIBOS_SANDBOX=on`.
- Keep the limits: timeout 5–110 s (default 60), memory 256–16384 MB (default 2048).
- Set `ANALYSABLE_KINDS` to `table`, `hdf5` and `mat`.

**Datasets** (`tribos/datasets/`):
- Supported kinds become table (CSV, TSV, XLSX, JSON, Parquet), HDF5 and MAT.
- Remove h5ad, SBML, the GEO lookup (`geo.py` and the `/geo-lookup` route) and consent/IRB.

**Keyed sources** read `TRIBOS_S2_API_KEY`, `TRIBOS_OPENALEX_API_KEY`, `TRIBOS_ADS_API_TOKEN`,
`TRIBOS_WOLFRAM_APPID` and `TRIBOS_MP_API_KEY`. `TRIBOS_CONTACT_EMAIL` supplies the Crossref mailto and the
Wikipedia/OEIS User-Agent. Without its key, a source is skipped and the answer says so. Register every variable in
`config/settings.py`.

**Tests:**
- Each package gets offline tests with recorded fixtures under `tests/fixtures/<agent>/` and fake httpx transports.
  They never use the live network.
- Live tests are marked `@pytest.mark.network` and gated by `TRIBOS_LIVE_TESTS`.

**Then delete:**
- `vivarix/`, `lithoscribe/`, `utils/biocontext/` and `datasets/geo.py`;
- the dependencies copasi_basico, hydra-core, langgraph, langchain-community, langchain-experimental and anndata.

## 8. Phases 5–8: backend, UI, export, evals, docs, verification

These phases split cleanly by directory, so they suit parallel workers once phase 4 has fixed the tool names.

**Phase 5: backend** (`app/backend/`):
- Set the API title to "Tribos Engineering R&D API", and use the same service name in `/api/health`.
- `/api/agents` (`main.py`, around line 563) returns the Archivon, Axiom, Dynamis, Calcula and Physis roster plus
  "Tribos Orchestrator".
- Titles:
  - Remove the gene-acronym title heuristic (around line 312).
  - The title prompt becomes "You are an engineering research assistant".
  - The fallback title is "New investigation".
- `routers/mcp.py`:
  - The tool is `tribos_research`.
  - Remove `lithoscribe_clinical_trials_search` and `primekg_query`.
  - The server title is "Tribos engineering research", and the A2A card is renamed.
- Remove `/api/datasets/geo-lookup`.

**Phase 5: export** (`tribos/export/`):
- Use Tribos branding in the header, footer and `set_author`.
- Equations: `$…$` and `$$…$$` are rendered to PNG with matplotlib mathtext and embedded in PDF (fpdf2) and DOCX
  (python-docx). This needs no new dependency.
- The `report_model.py` tables become references, computations, constants and simulations. Remove the trial, ClinVar,
  ChEMBL and FAERS tables and the matching checks in `provenance_check.py`.

**Phase 6: web UI** (`web/`):
- Maths rendering:
  - `npm i remark-math rehype-katex katex`, and import `katex/dist/katex.min.css` in `layout.tsx`.
  - Add the plugins in `components/MarkdownRenderer.tsx`.
  - Allowlist KaTeX output (`math`, `semantics`, `annotation`, the `katex*` classes) in `lib/markdownSafety.ts`. Its
    strip list currently removes `math`.
- Citations and labels:
  - Put the new citation grammar from section 6 in `lib/citations.ts`. Link out to arxiv.org/abs, doi.org,
    zbmath.org, oeis.org, ui.adsabs.harvard.edu and next-gen.materialsproject.org.
  - Entity types go in `types/queryPlan.ts`, and defect labels in `lib/entities.ts`.
- The agent roster lives in `page.tsx` (around lines 808–846). Use the lucide icons BookOpen, Sigma, Activity,
  Calculator and Atom.
- Artifacts:
  - Delete DiseaseTargets, DrugSafety, PrimeKG, SingleCell, TrialLandscape, Variant, Omics and Structure, along with
    their types and libs.
  - Generalise SimulationArtifact for Dynamis.
  - Add Derivation, ReferenceData and Literature artifacts.
- Copy:
  - Hero: "What shall we work out today?"
  - Placeholder: "Ask a maths, physics or engineering question, or attach data…"
  - Replace every "Clinical" label.
  - `lib/dynamicTitle.ts` switches to FEM, PDE, ODE, FFT, CFD and similar.
- localStorage keys become `tribos-*`, with no migration.
- Gate: `npm run typecheck`, `npm test` and `npm run build` must pass.

**Phase 7: evals** (`tribos/evals/`):
- Keep the harness: schema, runner, scoring, cassette, baseline and report.
- Add new suites in `data/`: `math.jsonl`, `physics.jsonl`, `engineering.jsonl`, and a rewritten `behavior.jsonl`.
- Benchmark loaders in `datasets.py` (section 9) replace PubMedQA, LitQA2 and BioASQ.
- Scoring adds a numeric-answer check and a SymPy LaTeX-equivalence check.
- Re-record the golden cassette with a physics question.

**Phase 7: docs:**
- `README.md`.
- `mkdocs.yml`: site_name Tribos, repo AtlasRoX/trib, and `pymdownx.arithmatex` plus MathJax.
- `docs/index.md`, one page per agent, the agentic docs relabelled, and the developer docs.
- Regenerate `configuration.md` and `.env.example`.

**Phase 8: final verification checklist:**
- [ ] `pytest tests -q` is all green, with the 5 baseline failures either fixed or documented.
- [ ] `ruff check tribos app tests` is clean.
- [ ] `npm run typecheck && npm test && npm run build` passes in `web/`.
- [ ] `gen_env_reference.py --check` passes.
- [ ] Live smoke runs pass for a maths, a physics and an engineering question in all five frameworks (this needs an
      LLM key). Check that the LaTeX renders and the verification section is there.
- [ ] `git grep -il "phronesis\|clinical\|biomedical"` shows only intended hits.
- [ ] The logos are in their slots:

      | File | Size |
      | --- | --- |
      | `web/public/icon.png` | 512² |
      | `web/public/icon-tight.png` | 256² |
      | `web/public/logo-tight.png` | about 600×160 |
      | `tribos/export/assets/tribos-mark.png` | 256² |
      | `tribos/export/assets/tribos-wordmark.png` | about 1200×300 |
      | `docs/assets/logo.png` | 256² |

- [ ] `tribos-transformation` is merged into `main`.

## 9. External API reference

Every endpoint below was called on 2026-10-23. Two of them effectively need a key, even though both are nominally
free:
- **Semantic Scholar:** keyless calls returned 429.
- **OpenAlex:** the keyless budget is about $0.10 a day per IP.

| Source | Endpoint | Auth | Limits and gotchas |
| --- | --- | --- | --- |
| [arXiv](https://info.arxiv.org/help/api/user-manual.html) | `export.arxiv.org/api/query` (Atom XML) | none | 1 request every 3 s, one connection at a time. A space in `search_query` means OR, so join terms with `AND` or quote phrases (`ti:%22navier+stokes%22`). |
| [Semantic Scholar](https://api.semanticscholar.org/api-docs/graph) | `api.semanticscholar.org/graph/v1/paper/search?query=&fields=` | `x-api-key` | The keyless shared pool returned 429 every time; back off on 429. |
| [OpenAlex](https://docs.openalex.org) | `api.openalex.org/works?search=&select=` | `api_key` param or Bearer | Freemium: $0.10/day per IP without a key, $1/day with a free key. A search costs about $0.001; single lookups are free. |
| [Crossref](https://api.crossref.org) | `api.crossref.org/works?query=&rows=&mailto=` | none | 1 req/s without `mailto`, 3 req/s with it. |
| [zbMATH Open](https://api.zbmath.org/v1) | `api.zbmath.org/v1/document/_search?search_string=&results_per_page=` | none | Useful fields: `identifier` (the Zbl number), `msc`, `links[doi]`, and the review text. |
| [OEIS](https://oeis.org) | `oeis.org/search?q=1,1,2,3,5,8&fmt=json` | none | Returns a **bare JSON array**; the old wrapper object is gone. Send a User-Agent and keep the request rate low. |
| [NIST CODATA](https://physics.nist.gov/cuu/Constants/) | `scipy.constants` offline (CODATA 2022); fallback `physics.nist.gov/cuu/Constants/Table/allascii.txt` | none | The fallback is a fixed-width text file; remove the spaces between digit groups before parsing. |
| [Wikipedia](https://en.wikipedia.org/api/rest_v1/) | `en.wikipedia.org/api/rest_v1/page/summary/{title}`, `w/rest.php/v1/search/page?q=` | none | A User-Agent with contact details is required. Global rate limiting has applied since 2026-03. |
| [NASA ADS](https://ui.adsabs.harvard.edu/help/api/) | `api.adsabs.harvard.edu/v1/search/query?q=&fl=` | `Authorization: Bearer` | 5,000 requests/day. |
| [Wolfram\|Alpha](https://products.wolframalpha.com/llm-api/documentation) | `www.wolframalpha.com/api/v1/llm-api?input=&appid=` | AppID | 2,000 calls/month on the free tier. A bad key returns 401; input it can't interpret returns 501. Fallback: `api.wolframalpha.com/v2/query`. |
| [Materials Project](https://api.materialsproject.org/docs) | `api.materialsproject.org/materials/summary/?formula=&_fields=` | `X-API-KEY` | No `/v3` prefix. Legacy paths return 403. |

**Eval benchmarks:** fetch all of these through
`datasets-server.huggingface.co/rows?dataset=ID&config=C&split=S`.

| Benchmark | Dataset id | Licence | Note |
| --- | --- | --- | --- |
| MATH-500 | `HuggingFaceH4/MATH-500` | MIT | `hendrycks/competition_math` is disabled; use this or `EleutherAI/hendrycks_math`. |
| GSM8K | `openai/gsm8k` | MIT | Config `main`. |
| TheoremQA | `TIGER-Lab/TheoremQA` | MIT | |
| SciBench | `xw27/scibench` | MIT | |
| PHYBench | `Eureka-Lab/PHYBench` | MIT | |
| EngDesign | `opt1zer/EngDesign` | MIT | Often graded by simulation rather than by answer matching. |
| UGPhysics | `UGPhysics/ugphysics` | CC-BY-NC-SA | Opt-in only, because the licence is non-commercial. |
| GPQA | `Idavidrein/gpqa` | CC-BY-4.0 | Gated; needs an HF token. |

**How answers get verified**, following [PAL](https://arxiv.org/abs/2211.10435),
[Program-of-Thoughts](https://arxiv.org/abs/2211.12588), [ToRA](https://arxiv.org/abs/2309.17452) and
[code-based self-verification](https://arxiv.org/abs/2308.07921):
- compute in the sandbox and interleave tool calls with the reasoning;
- compare expressions with `simplify(a-b)==0` plus random-point numeric checks;
- substitute solutions back into the original equations;
- check units with pint;
- feed errors back to the model, with bounded retries;
- mark a result "verified" only when an independent check passes.

## 10. Environment setup and gotchas

Use **Python 3.12** exactly. Python 3.13 fails on numpy 1.26.4 (no wheels), and 3.14 fails on torch 2.8.0.

```bash
git clone <repo> && cd <repo> && git checkout tribos-transformation
uv sync --extra dev --frozen --python 3.12     # after phase 2 the lock changes: drop --frozen once
cp .env.example .env                          # TRIBOS_AUTH_MODE=disabled for local single-user work
.venv/Scripts/python.exe -m pytest tests -q -p no:cacheprovider          # Windows; .venv/bin/python on Linux/macOS
.venv/Scripts/python.exe scripts/gen_env_reference.py --check
uv run uvicorn app.backend.main:app --host 127.0.0.1 --port 8000
cd web && npm ci && npm run dev               # http://localhost:3000, needs Node 22+
```

**Gotchas met so far:**
- **CRLF line endings.** The repo has `core.autocrlf=true`, so a Windows checkout uses CRLF. Scripted edits that
  match multi-line text fail silently on CRLF files. The working tree was normalised to LF; git shows no diff,
  because it stores LF anyway. Use `git -c core.safecrlf=false …` to silence the warnings.
- **`git rm` refuses files touched in the working tree.** Use `git rm -f`.
- **Test timing and flags.** The suite takes about 2 minutes after the prune (about 5 before). There is no
  `pytest-timeout` or `xdist`, so don't pass `-n` or `--timeout`.
- **The settings registry is strict.** Every env var the code reads must be declared in `config/settings.py`.
  `test_settings_registry` and `gen_env_reference.py --check` fail on drift in either direction.
- **`tests/fakes.py` is the shared offline registry.** Most orchestrator tests go through
  `build_recording_registry()` and `make_offline_orchestrator()`, so change tool names there first.
- **Agentic prompts must start with `[phase:<key>]`.** `tests/agentic_fakes.ScriptedLLM` routes by that marker.
- **Extensions load lazily.** They are listed in `tribos.extensions.EXTENSION_MODULES`, and a module that fails to
  import is only logged. After adding one, check the log for "failed to load".

**Helper scripts.** These lived in the session scratchpad; copy them into `scripts/migration/` if you want them in
the repo.
- `prune_tests.py MODULE_REGEX FILE…`: removes the imports of a module and every top-level test or helper that uses
  them. Review what it removed, because the removal cascades through shared helpers.
- `drop_tests.py FILE NAME…`: deletes the named test functions.
- `drop_settings.py LIST settings.py`: removes `Setting(...)` entries by name.
- `pyedit.py replace-def|delete-def|sub`: edits whole functions in a source file.

## 11. How to continue from anywhere

Until it is pushed, the work exists only on this machine's local branch. Push it once, and any machine or cloud
session can pick it up.

1. On this machine, push the branch: `git push -u origin tribos-transformation`. It has not been pushed yet.
2. Elsewhere, clone the repo, check out `tribos-transformation`, and follow section 10.
3. Start Claude Code in the repo (CLI, desktop, IDE or claude.ai/code) and paste the resume prompt below.
4. Keep this brief and `tribos-transformation.md` up to date. After each commit, tick the phase 8 checklist and add a
   row to the progress table.

**Resume prompt (paste as is):**

```text
Continue the Phronesis → Tribos transformation on branch tribos-transformation.
Read docs/plans/tribos-migration-brief.md and docs/plans/tribos-transformation.md first.
Done: phase 0 (9740d79) and phase 1 (3ed03bd). Next: phase 2 rename exactly as the brief specifies
(replacement table + dependency list), then phase 3 domain core, phase 4 agents
(Archivon, Axiom, Dynamis, Calcula, Physis), phases 5-8.
Rules: Python 3.12; one commit per phase; run the full pytest suite before each commit;
never invent data in fixtures; keep [phase:<key>] prompt markers; register every env var in config/settings.py.
Use parallel subagents with disjoint file ownership for phases 4-7. Work fast.
```

**Open questions for the owner:**
- Should Zotero sync and PDF question-answering come back as Archivon tools?
- When will the logo files arrive? Until then, the current images stay in the slots under their new names.
- Which LLM key should the phase 8 live smoke runs use: NVIDIA NIM or OpenAI?
