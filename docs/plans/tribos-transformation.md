# Phronesis → Tribos: transformation plan

**Tribos — Engineering Research & Development System.** Made by ChronoStrider Engineering.

Tribos is for scientists, researchers, mathematicians, physicists and engineers. It keeps every part of the
Phronesis reasoning framework:
- the orchestrator stages and the five framework modes plus the auto-router;
- the agentic phases, budgets, run control and jobs;
- project memory, reliability, provenance, export, evals, MCP and A2A;
- the FastAPI backend and the Next.js UI.

What changes is the **domain knowledge**: biomedicine is removed and replaced by mathematics, physics, engineering, and
applied math and CS.

## Decisions (from the owner, 2026-10-23)

| Topic | Decision |
|---|---|
| Rename depth | Full. The Python package `phronesis` becomes `tribos`, `PHRONESIS_*` becomes `TRIBOS_*`, the CLI is `tribos-eval`, and docker, CI and docs follow. Nothing says Phronesis afterwards. |
| Domains | Pure mathematics, physics, engineering, and applied math and CS. |
| Agents | Repurposed, with new names (below). Synapta (knowledge graph) and Lumicell (single-cell) are removed. |
| Compute | The sandbox is **on by default**. Add sympy, mpmath, networkx and pint. Numeric and symbolic claims are verified against sandbox output. |
| Sources | Free core set: arXiv, Semantic Scholar, Crossref, OpenAlex, zbMATH Open, OEIS, NIST CODATA, Wikipedia and web search. Keyed sources: NASA ADS, Wolfram\|Alpha and Materials Project. |
| Maker credit | "Made by ChronoStrider Engineering", with the "Enginnerings" typo fixed. |
| Logos | The owner provides them. File slots are kept and documented (section 9). |
| Leftovers | Deleted: root audit reports, old plans, biomedical notebooks and benchmarks, legacy Streamlit, marker data. They remain in git history at `c55910c`. |
| Answer shape | Derivation first: Result, then Derivation (LaTeX), Verification, Assumptions & limits, and References. |
| Git | Branch `tribos-transformation`, one commit per phase. |
| Repo URL | `github.com/AtlasRoX/trib`. |

## 1. Agents (specialists)

Phronesis had five specialist groups: literature, target, simulation, omics and chemistry. Tribos also has five. Each
name is a branded agent shown in the UI roster, like Vivarix and the others before.

| Agent | Role | Built from | Tools |
|---|---|---|---|
| **Archivon** | Literature | Lithoscribe, reduced (S2, arXiv, Zotero and PDF RAG are kept) | `archivon_literature_search` (arXiv, Semantic Scholar, OpenAlex, Crossref, zbMATH, ADS), `archivon_paper_details`, `archivon_recommend`, the PDF Q&A and Zotero tools |
| **Axiom** | Symbolic mathematics | New, on SymPy | `axiom_simplify`, `axiom_solve` (equations and systems), `axiom_calculus` (diff, integrate, limit, series), `axiom_dsolve`, `axiom_linalg`, `axiom_verify_identity` (symbolic plus random numeric spot checks), `axiom_latex` |
| **Dynamis** | Numerics and simulation | Vivarix's design (simulate, steady state, parameter scan, calibrate), rebuilt on SciPy | `dynamis_simulate_ode` (time course), `dynamis_equilibrium` (fixed points and stability), `dynamis_parameter_scan`, `dynamis_optimize`, `dynamis_fit_parameters`, `dynamis_root_find` |
| **Calcula** | Data analysis and computation | The sandbox analyst (`analysis_run_python`) plus dataset uploads | `calcula_run_python` (sandbox: numpy, scipy, sympy, mpmath, networkx, pint, pandas, matplotlib), `calcula_describe_dataset` |
| **Physis** | Reference data | New | `physis_constants` (CODATA), `physis_units` (pint conversion and dimensional check), `physis_oeis`, `physis_materials` (Materials Project), `physis_wolfram` (Wolfram\|Alpha), `physis_encyclopedia` (Wikipedia) |

Two components keep their roles and get new names:
- **Verifier**, which has no brand name.
- **Discovery** (was BioDiscovery), which ranks hypotheses and approaches.

WebSurfer keeps its name.

Specialist mapping for the supervisor and swarm modes (`agentic/specialists.py`):
- literature → Archivon and web
- symbolic → Axiom
- numerical → Dynamis
- analysis → Calcula
- reference → Physis

## 2. Domain knowledge rewrites (same mechanisms, new tables)

| Mechanism | Phronesis content | Tribos content |
|---|---|---|
| Entity types (`query_context.EntityType`) | gene, drug, disease, variant | concept, equation, quantity, constant, material, system |
| Query intents (`query_planner.INTENTS`) | target, drug, trial, variant… | derive, solve, prove, compute, simulate, design, estimate, explain, literature, data_analysis |
| Question types (`search_plan.QUESTION_TYPES`) | treatment, diagnosis… | proof, derivation, numerical, design/sizing, modelling, conceptual, literature review |
| Router domains | literature, clinical, molecular, computational | literature, symbolic, numerical, reference |
| Stakes regex (router) | patients, dosing, pregnancy | structural safety, pressure, high voltage, aerospace, life-safety, code compliance. These require the caveat "verify against applicable codes / a licensed engineer". |
| Decompose foci | clinical, drug, variant… | math, physics, engineering, computation, literature, data |
| Tool retrieval vocabulary | trial→nct, ic50→chembl… | integral→axiom_calculus, ode→dynamis_simulate_ode, constant→physis_constants, sequence→physis_oeis… |
| Citation ids (`citations._KeySpec`, web `citations.ts`, `extensions/id_families.py`) | PMID, NCT, ChEMBL, ENSG… | arXiv id, DOI, zbMATH (Zbl / zbMATH id), MR number, OEIS A-number, ADS bibcode, Materials Project mp-id, ISBN, OpenAlex W-id, plus computation keys `comp:<n>` for sandbox and tool results |
| Evidence ladder (`prompts.evidence_level`) | guideline > RCT > … > computational | formal proof / textbook theorem > established theory > peer-reviewed result > preprint > verified computation > estimate or heuristic |
| Debate personas | methodologist, clinical skeptic, mechanistic biologist | rigorous mathematician (proof gaps, edge cases), physicist (units, limits, orders of magnitude, conservation laws), practising engineer (assumptions, safety factors, standards, manufacturability) |
| Counter-evidence | "<drug> adverse", failed trials | counterexample search (sandbox brute force or random tests), contradicting results, known errata |
| Hypothesis phase | Vivarix knockdown and overexpression | conjecture testing: numeric experiments over parameter or n ranges, parameter sensitivity on Dynamis models, Elo ranking of approaches |
| Calibrate phase | SBML parameter fitting | fitting model parameters to uploaded data (Dynamis plus SciPy) |
| Synthesis prompt | "You are Phronesis, a biomedical research assistant…" | "You are Tribos, an engineering and scientific R&D assistant…". It keeps the grounding rules and adds math rules: LaTeX output, show the derivation, verify by computation, state assumptions, check units and dimensions, check limiting cases, never invent references or constants. |
| Memory subjects | gene, drug, disease, biomodel | concept, equation, material, system, model |
| Source authority | pharma and FDA hosts | publishers, standards bodies, arXiv, NIST and university hosts |

## 3. The verifier (`ClinicalVerifier` → `TribosVerifier`)

**Kept** (the generic core):
- Identifier grounding: every cited id must appear in the evidence.
- The claim/evidence audit with the NLI judge hook.
- The numeric tolerance check, now against **computation outputs** (sandbox, Axiom, Dynamis, Physis constants)
  rather than simulator species.
- Confidence-line reconciliation, the limitations section, removable defects and date checks.

**Removed:** regimen and monotherapy checks, population and disease mismatch, HR/CI/p-value metric parsing,
primary-trial-report preference, and regulatory-claim checks.

**Added:**
- **Constant check:** a value given for a known physical constant must match CODATA within its uncertainty.
- **Units and dimension check:** quantities with units in the Result section are parsed with pint, and an
  inconsistent dimension is a defect.
- **Computation grounding:** a numeric result presented as computed must match a tool or sandbox output within
  tolerance.
- **Identity spot check:** an equation the answer marks as verified is checked by Axiom's random numeric
  substitution when it can be parsed.

## 4. Sandbox

- Defaults: `TRIBOS_SANDBOX=on`.
- Allowlist: add `sympy`, `mpmath`, `networkx` and `pint`; remove `anndata` and `scanpy`.
- `analyst.py` triggers on any computation intent, not only on an attached dataset.
- Dataset kinds: table (CSV/TSV/XLSX/JSON/Parquet), HDF5 and MAT. Removed: h5ad, SBML, the GEO lookup and consent/IRB.

## 5. Removed

Domain packages:
- `drugintel`, `diseaseintel`, `trials`, `variants`, `structintel`, `kgintel` (PrimeKG)
- `sources_extra/*`, `tools/biocontext`, `utils/biocontext`
- `synapta`, `lumicell`, `vivarix` (replaced by Dynamis)
- the nested `phronesis/phronesis` supervisor (its verifier moves to `tribos/verify/`)

Extensions: entities (rewritten), trials, drugs, disease_targets, primekg, variants, structure, omics_sources and
calibration (rewritten).

Other code and files:
- Legacy Streamlit apps (`app/frontend`).
- Clinical web artifacts: DrugSafety, Trials, Variants, DiseaseTargets, PrimeKG, SingleCell, Omics and Structure.
- The biomedical `scripts/` and dependencies: anndata, cell2sentence, copasi_basico, gseapy, scanpy, pubchempy,
  pygeneconverter, pcst_fast, torch_geometric, umap-learn, pymilvus and langchain-milvus. The last two are removed
  only if PDF RAG does not need them.
- `data/` marker files, biomedical notebooks and benchmarks, root audit reports, the old `docs/plans` and the
  stale `.claude/workflows`.

## 6. UI (web/)

- Branding: Tribos everywhere. The maker is credited in the layout metadata. `localStorage` keys become `tribos-*` with
  no migration, since this is a fresh product.
- **Math rendering:** `remark-math` and `rehype-katex` with KaTeX CSS; the sanitizer allowlist is updated so KaTeX output survives.
- New citation grammar (section 2), entity chips and defect labels.
- Agent roster: Archivon, Axiom, Dynamis, Calcula and Physis, each with an icon and colour.
- Artifacts:
  - kept and generalised: Simulation (Dynamis ODE plots), Sandbox (code, output and figures), Hypotheses, Plan graph,
    Jobs and Projects;
  - new: Derivation steps, Reference data (constants and materials) and Literature;
  - clinical ones removed.
- Copy: the hero text "What shall we work out today?", placeholders and settings labels. `dynamicTitle.ts` uses
  math and physics acronyms (FEM, PDE, ODE, FFT, CFD…).

## 7. Backend, export, evals, docs

- **Backend:**
  - API title "Tribos Engineering R&D API".
  - `/api/agents` returns the new roster, and the title prompt is rewritten.
  - The MCP tool is `tribos_research`, and the A2A card is renamed.
  - The GEO route is removed.
- **Export:**
  - Tribos branding and logo slots.
  - **Equations** are rendered in PDF and DOCX through matplotlib mathtext, so no new dependency is needed.
  - Report tables cover computations, constants and references.
- **Evals:**
  - The harness is kept.
  - New suites: `math.jsonl`, `physics.jsonl`, `engineering.jsonl` and `behavior.jsonl` (rewritten).
  - Public benchmark loaders (MATH-500, GSM8K, TheoremQA and others, after their licences are checked) replace
    PubMedQA, LitQA2 and BioASQ.
  - Scoring gains a numeric-answer and LaTeX-equivalence check through sympy.
- **Docs:**
  - README, mkdocs (with arithmatex and MathJax), per-agent docs, agentic docs relabelled.
  - `configuration.md` and `.env.example` regenerated.

## 8. Phases (one commit each; the test suite must be green at each phase's end)

0. **Clean**: delete leftovers.
1. **Prune**: remove the clinical packages and extensions, cut the hard imports (registry, orchestrator, agentic
   phases, query planner), and delete the clinical tests. The core must import and the remaining tests must pass.
2. **Rename**: run a scripted `phronesis` → `tribos` rename across the package, imports, env prefix, settings registry,
   docker, CI, sonar and pyproject. Regenerate the env reference.
3. **Domain core**: rewrite section 2's tables, the prompts and the verifier (section 3), and adapt the tests.
4. **Agents and tools**: build Archivon, Axiom, Dynamis, Calcula and Physis, plus the sources and the sandbox
   defaults, with unit tests using recorded fixtures.
5. **Backend and export**.
6. **Web UI**.
7. **Evals and docs**.
8. **Final verification**: full pytest, ruff, web typecheck/test/build, a live smoke run of a math, a physics and
   an engineering question when an LLM key is available, and a final grep for zero "phronesis" or "clinical" hits.

**Execution.** I do phases 0–3 myself, because they cut across the whole codebase and must happen in sequence. In
phases 4–7, independent pieces go to parallel subagents with disjoint file ownership: each agent and tool family, the
web app, export, evals and docs. Each phase ends with a review pass and the test gate before its commit.

## 9. Logo slots (the owner supplies these)

| File | Use | Suggested size |
|---|---|---|
| `web/public/icon.png` | favicon, hero and avatars | 512×512 square, transparent |
| `web/public/icon-tight.png` | compact icon | 256×256 |
| `web/public/logo-tight.png` | sidebar wordmark | about 600×160, transparent |
| `tribos/export/assets/tribos-mark.png` | PDF/DOCX header mark | 256×256 |
| `tribos/export/assets/tribos-wordmark.png` | PDF/DOCX cover | about 1200×300 |
| `docs/assets/logo.png` | mkdocs logo | 256×256 |

Until replacements arrive, the current images stay in these slots under the new file names.

## 10. External API notes (verified live 2026-10-23)

| Source | Endpoint | Auth | Limits and gotchas |
|---|---|---|---|
| arXiv | `export.arxiv.org/api/query` (Atom) | none | At most 1 request every 3 s and one connection. A space in `search_query` means OR, so join terms with `AND` or quote phrases. |
| Semantic Scholar | `api.semanticscholar.org/graph/v1/paper/search` | `x-api-key` (`TRIBOS_S2_API_KEY`) | The keyless shared pool returned 429 constantly, so in practice a key is needed. Back off on 429. |
| OpenAlex | `api.openalex.org/works?search=` | `api_key` (`TRIBOS_OPENALEX_API_KEY`) | Freemium: $0.10/day per IP without a key, $1/day with a free one. A search costs about $0.001. |
| Crossref | `api.crossref.org/works?query=` | none; send `mailto` | 1 req/s without `mailto`, 3 req/s with it. |
| zbMATH Open | `api.zbmath.org/v1/document/_search?search_string=` | none | Fields: `identifier` (Zbl), `msc`, `links[doi]`, review text. |
| OEIS | `oeis.org/search?q=…&fmt=json` | none | Returns a **bare JSON array** (the old wrapper is gone). Keep the request rate low and send a User-Agent. |
| CODATA | `scipy.constants` (CODATA 2022), offline | none | Remote fallback is `physics.nist.gov/cuu/Constants/Table/allascii.txt` (fixed-width; remove the spaces between digit groups). |
| Wikipedia | `en.wikipedia.org/api/rest_v1/page/summary/{t}` and `w/rest.php/v1/search/page?q=` | none | A User-Agent with contact details is required. Global rate limiting has applied since 2026-03. |
| NASA ADS | `api.adsabs.harvard.edu/v1/search/query` | `Authorization: Bearer` (`TRIBOS_ADS_API_TOKEN`) | 5000 requests/day. |
| Wolfram\|Alpha | `www.wolframalpha.com/api/v1/llm-api?input=&appid=` | AppID (`TRIBOS_WOLFRAM_APPID`) | 2000 calls/month on the free tier. A bad key returns 401 and an input it can't interpret returns 501. Full Results `v2/query` is the fallback. |
| Materials Project | `api.materialsproject.org/materials/summary/` (no `/v3`) | `X-API-KEY` (`TRIBOS_MP_API_KEY`) | Query params `formula`, `material_ids`, `_fields`, `_limit`. |

Keyed sources are skipped, with a note in the answer, until their key is set. This is the same pattern Phronesis used for
its local-file sources.

**Eval benchmarks** (Hugging Face datasets-server):

| Benchmark | Dataset | Licence |
|---|---|---|
| MATH-500 | `HuggingFaceH4/MATH-500` | MIT |
| GSM8K | `openai/gsm8k` | MIT |
| TheoremQA | `TIGER-Lab/TheoremQA` | MIT |
| SciBench | `xw27/scibench` | MIT |
| PHYBench | `Eureka-Lab/PHYBench` | MIT |
| EngDesign | `opt1zer/EngDesign` | MIT |
| UGPhysics | `UGPhysics/ugphysics` | CC-BY-NC-SA, so opt-in only |
| GPQA | `Idavidrein/gpqa` | gated; needs an HF token |

**Verification design** follows PAL (2211.10435), Program-of-Thoughts (2211.12588), ToRA (2309.17452) and code-based
self-verification (2308.07921):
- compute in the sandbox;
- compare symbolically (`simplify(a-b)==0`) plus random-point numeric checks;
- substitute the solution back into the original equations;
- check units with pint;
- feed execution errors back to the model, with bounded retries;
- mark a result "verified" only when an independent check passes.
