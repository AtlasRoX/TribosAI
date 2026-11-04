# Tribos — Feature Gap Analysis for a World-Class Agentic Engineering R&D Harness

**Date:** 2026-10-26
**Scope:** Codebase audit (`tribos/`, `app/backend/`, `web/`, `tests/`, `docs/`) + internet research into the 2026 agentic-engineering landscape.
**Method:** Two parallel deep-exploration passes over the codebase, a full inventory of registered tools/settings/routes, cross-checking of every claim against the source, plus research into competitor/platform capabilities and the published failure modes of agentic engineering systems.

---

## Context

Tribos is already a substantial, well-engineered multi-agent research assistant: 6 orchestration frameworks, 5 specialist agents, hybrid (BM25 + dense) tool retrieval, a 20-task-kind verified math agent with a zero-false-accept gate, a real sandboxed-code executor, Lean 4 formal verification, bi-temporal project memory, durable SSE job streams, and 55 backend routes with MCP + A2A surfaces. Its verification story is genuinely stronger than most products in the category.

The gap is **not** in agentic plumbing. It is that the agent can reason and compute brilliantly about *text and equations*, but the physical and industrial substrate of engineering R&D is largely absent. An engineer asking "will this bracket survive 500 N at 70 °C?" gets an ODE solver, an engineering formula, and a citation — but no geometry, no stress field, no material database, no standard clause, no BOM, no cost. The product's own name promises *"a worn path, practice, diligent inquiry"* — the inquiry is strong; the practice is thin.

This document lists what would need to exist for Tribos to be a genuinely complete agentic harness for engineering R&D, prioritized by impact, with each item grounded in a verified gap and a named 2026 market/technical reference point.

---

## Part 1 — What Tribos already does well (do not rebuild)

| Area | Implementation | Files |
|:--|:--|:--|
| 6 orchestration frameworks | plan-execute (tool DAG), authoritative React compiler, supervisor (Magentic-One ledger), swarm handoffs, debate personas, auto-router | `tribos/agentic/{plan_execute,runtime,topologies,router}.py` |
| Hybrid tool retrieval | BM25 + optional dense embeddings, RRF fusion, `recall_at_k` metric | `tribos/agentic/tool_retrieval.py` |
| Verified math agent | 20 task kinds, deterministic strategy ladder, independent verifier, typed local repair, honest status (`verified`/`partially_verified`/`unverified`/`failed`) | `tribos/axiom/agent.py`, `tribos/axiom/verifier.py` |
| Answer-level claim auditing | Re-evaluates every equation/table row of the written answer; measures false alarms via `math_claims_matrix` | `tribos/verify/math_claims.py`, `tribos/evals/math_claims_matrix.py` |
| Code sandbox | AST allowlist, isolated `python -I` subprocess, scrubbed env, rlimit caps, no network, figure capture | `tribos/agentic/sandbox/{policy,runner}.py` |
| Formal verification | Lean 4 compile, `sorry`-free gate, correspondence proofs | `tribos/verify/formal/` |
| Memory | BM25 vault + bi-temporal fact graph, Personalized-PageRank recall, recency×importance×relevance | `tribos/utils/memory/{research_memory,project_store}.py` |
| Provenance | Run manifests, tool-mode vs full replay, diffs, upstream source version probing | `tribos/provenance/` |
| HITL | Fail-closed plan + DAG approval, expensive-work gating, steer/skip/cancel, checkpoints | `tribos/agentic/{control,approval}.py` |
| Observability (partial) | Tool-call traces, budgets, token estimation, run manifests | `tribos/agentic/{state,budget}.py` |
| Evaluations | 13 suites (math500, gsm8k, theoremqa, scibench, phybench, engdesign, ugphysics, gpqa…), cassette replay, `--fail-under` gates | `tribos/evals/` |
| Frontend | 14 artifact cards, evidence deck, simulation Explore panel, streaming w/ reconnect, project tabs, exports | `web/src/components/` |

---

## Part 2 — Gap Inventory

### P0 — The engineering substrate is missing

> Verified by exhaustive regex scan of `tribos/**/*.py`, `app/**/*.py`, `web/src/**`: **zero hits** for `cadquery|freecad|opencascade|three.js|react-three|gmsh|meshio|abaqus|ansys|comsol|slurm`. The single domain hit for "finite element" is a *routing keyword* in `tribos/agentic/decompose.py:44` that steers the question to the computation focus — there is no solver behind it.

**P0.1 — CAD / parametric geometry / 3D (the single largest gap)**
No STEP/IGES/STL/JT import, no solid modelling, no feature tree, no parametric constraints, no 3D viewer (no 3D dependency in `web/package.json` at all). The 2026 market has converged here: text→CAD producing true STEP files is a shipping product category, and CAD agents now parse STEP/IGES/DWG/SolidWorks natively, diff geometry, and apply rules. An engineering R&D assistant that cannot open a drawing is limited to a chat window.
→ **Build:** STEP/IGES/STL ingest, a geometry-inspection tool (bounding box, mass properties, wall-thickness, interference), and a WebGL viewport in `web/`.

**P0.2 — FEA / CAE solver integration**
`dynamis` is ODE/PDE *numerics* (SciPy), not finite-element analysis. No structural, thermal, CFD, or multiphysics solver, no mesh generation, no preprocessor, no boundary-condition library. Agentic FEA is now a well-defined workflow with a canonical stage list (import → cleanup → mesh → material → BCs → solve → post-process → refine → convergence study → interpret → report) and a canonical set of 14 verification gates — Tribos implements *none* of these stages, though it already has the sandbox and the report structure to host them.
→ **Build:** mesh generation, a linear-static/thermal solver path, and a `cae_review` tool implementing the verification gates: reaction-force balance, mesh-convergence study, singularity screening, linear-elastic validity, hand-calculation cross-check.

**P0.3 — Standards & code compliance engine**
This is the clearest competitive differentiator available to Tribos. Standards-driven agentic compliance (ASME VIII Div 1, API 620/650, ISO 9001, Eurocodes, ASME Y14.5, ISO 1101) is now a shipping product category with 50,000+ atomic machine-checkable requirements, NLP discretization into pass/fail criteria, and live drift monitoring. Tribos has `engcalc` (beams, buckling, ASME VIII-1 UG-27 pressure vessels, Goodman fatigue, Colebrook) — real and valuable — but it checks *one formula*, not *a standard's clause set*, and has no requirement-to-design traceability matrix.
→ **Build:** a clause library with structured rule objects (predicate + inputs + tolerance + citation), a compliance agent that emits a traceability matrix, and a standards-drift monitor.

**P0.4 — Materials & physical property database**
Materials Project requires a key and otherwise falls back to a curated **25-material** table. No property database, no phase diagrams, no temperature-dependent properties, no material selection. Every downstream capability (FEA, pressure vessels, fatigue, thermal) needs material data as a first-class input.
→ **Build:** a material property service (temperature-dependent `E`, `ν`, `ρ`, `α`, yield/ultimate, fatigue S-N data) with a CODATA-backed units layer and a MatWeb-class source connector.

**P0.5 — Experimental design & hypothesis generation**
`discovery.py` ranks hypotheses but is framed as **biomedical** (`PrioritizedCandidate`, in-silico testing) — legacy framing for a STEM-only product, and flagged in `docs/history/CODEBASE_AUDIT.md` §6. There is no DOE engine: no D-optimal, Latin hypercube, response-surface, or Taguchi design. An agentic R&D harness's core loop is *propose → design experiment → analyze → iterate*, and Tribos currently has none of the middle.
→ **Build:** a DOE engine (factorial, D-optimal, LHS, response-surface) + a STEM-native hypothesis generator seeded from literature gaps and measured residuals.

**P0.6 — Multiphysics & unit-system integrity in the solve path**
Units are audited on the *written answer* (`tribos/verify/units_audit.py`), but the roadmap's T4 claim is contradicted: `docs/TRIBOS_REMEDIATION.md` §4 states **`physis_units` is not wired into the audit**. There is no dimensional-homogeneity gate *before* a solver call, meaning an equation can be dimensionally wrong and produce a confident, well-formatted, wrong number.
→ **Build:** a pre-flight dimensional check on every tool input, with fail-closed behavior.

---

### P1 — The industrial/commercial layer is missing

**P1.1 — BOM, cost, supplier, and lead-time data**
Zero code hits for `patent|supplier|bom|cost.estimat`. No BOM rollup, no material cost feed, no supplier catalogs, no lead time, no make/buy analysis. The 2026 PLM market has converged on AI BOM agents (Siemens Teamcenter 2606 ships a "Teamcenter AI BOM agent"; PTC Windchill and Aras are agentic). Tribos computes a pressure vessel wall but cannot price it.

**P1.2 — IP / patent / freedom-to-operate**
No USPTO/EPO/WIPO search, no FTO analysis, no claim charting. Patent platforms now use agents to read a technical disclosure, extract distinguishing features, and build parallel patent/non-patent search strategies — exactly the "evidence → synthesis → grounded citations" shape Tribos already has, applied to a domain it does not cover.

**P1.3 — PLM / CAD / ERP integration**
No Siemens NX, SolidWorks, Teamcenter, SAP, Arena connector; no on-prem SFTP/S3/DB connector beyond generic uploads. MCP and A2A surfaces already exist — Tribos is *architecturally ready* to be a PLM citizen; it just has no PLM clients.

**P1.4 — Requirements & traceability management**
No requirement decomposition into atomic, testable, traceable criteria; no requirement→design→verification matrix. This is the connective tissue of engineering R&D and the thing compliance output (P0.3) must hang off.

**P1.5 — LIMS / ELN / lab data ingestion**
No instrument-file ingestion, no LIMS/ELN connector, no calibration provenance, no chain-of-custody. The lab is where engineering R&D meets physical reality; agentic autonomous-lab work is now a live research area. Note the existing upload kinds are only `table | hdf5 | mat | paper` (`web/src/types/datasets.ts:4`).

---

### P2 — Agentic harness maturity gaps

**P2.1 — No OpenTelemetry / GenAI semantic-convention tracing**
Tribos has a tool-call trace, but no hierarchical span model (LLM call, tool invocation, memory operation, handoff, reasoning chain), no `tool_version`/`model_version` span attributes, no per-span token+cost attribution. The 2026 standard is OTel GenAI Semantic Conventions, so a Tribos trace would not be readable by a customer's Datadog/MLflow/Laminar without custom work — a real enterprise blocker.

**P2.2 — No monetary cost ledger**
`agentic/budget.py` enforces token budgets (`RunBudget`, `Allocation`, `estimate_tokens`, final reserve) but there is no token→currency ledger, no per-project spend, no forecast. Cost tracking is a table stakes feature in agent observability.

**P2.3 — No answer versioning, only run rerun**
`RerunDiffPanel` diffs *tool outputs* across a replay (Identical / Upstream drift / Changed). There is no answer version history, no branch, no side-by-side answer diff, no per-answer edit history. The only history is per-*fact* and per-*run-manifest*.

**P2.4 — Chats live in browser localStorage**
`web/src/services/localStorageService.ts` — a project's chats are only those on that one device, so "shared projects" is server-side memory + files but client-side conversation. There is no user directory (members added by raw user id), no live presence, no concurrent editing.

**P2.5 — No first-class run resumption**
`RunControl.checkpoint` and manifest persistence exist, and SSE supports `Last-Event-ID` reconnection, but there is no "resume this run at the interrupted phase" endpoint. Re-running goes through provenance `rerun` (replay or full), which is a different thing.

**P2.6 — No HITL at the artifact/claim level**
Approval is plan- and DAG-level. A domain expert workflow (the published pattern: *"a qualified engineer remains responsible for acceptance and release"*) needs per-artifact review: sign off a specific result, annotate a claim, request rework on one step, escalate a singular peak. `RunControl.request_skip` exists but there is no "approve this artifact" primitive.

**P2.7 — Agentic design-space exploration (the missing "optimize" verb)**
Tribos has `dynamis_parameter_scan` (1-D sweep) and `axiom_optimize` (single-objective). There is no multi-objective Pareto search with an LLM proposer–critic loop, no surrogate models, no convergence criteria on hypervolume. The 2026 reference pattern is precise: LLM proposes candidates, a critic analyzes intermediate physical evidence (not just final scores), Pareto dominance + hypervolume retain non-dominated designs, termination on quantitative convergence. This is the natural "agentic" upgrade over brute-force sweeps and it maps directly onto Tribos's existing strengths (it already renders intermediate physical evidence).

**P2.8 — Evaluation maturity**
`tribos/evals/cli.py` is genuinely strong (13 suites, cassette replay, `--fail-under` gates). Missing: (a) no *agentic-trajectory* eval — no measure of plan quality, tool-selection precision/recall, or cost-per-solved-problem; `tool_retrieval.recall_at_k` exists but isn't gated in CI; (b) no GPQA/DocVQA-style engineering-document reasoning suite; (c) no human-preference or rubric-similarity-to-expert-answer metric for engineering answers; (d) `scripts/calibrate_confidence.py` fits on *human-labelled* claims — there is no pipeline to produce those labels, and no calibrated probability for whole answers (stated in `docs/TRIBOS_REMEDIATION.md` §4).

**P2.9 — Browser E2E or contract testing**
`web/tests/*.test.mts` are pure unit tests via `node --test` — no DOM, no Playwright/Cypress. There is no generated OpenAPI type sync (SUP-6 open: "frontend/backend contracts aligned by hand"), which is precisely the bug class that breaks when the 55-route API grows to 150+.

---

### P3 — Correctness, hygiene, and trust gaps

These are cheap, high-leverage, and they directly affect the "be honest by design" promise.

| # | Issue | Evidence |
|:--|:--|:--|
| P3.1 | **README/docs state the wrong default framework.** "Plan-and-Execute (API Default)" — actual default is `auto`. | `README.md`, `docs/index.md`; flagged in `docs/history/CODEBASE_AUDIT.md` §5 |
| P3.2 | **`physis_units` is not wired into the unit audit**, contradicting roadmap T4's "DONE". | `docs/TRIBOS_REMEDIATION.md` §4 |
| P3.3 | **Biomedical leftovers in a STEM-only product**: `tribos/verify/verifier.py` is still a 3,049-line "Clinical Verifier"; `discovery.py` is biomedical-framed; `research_memory.py` keeps biomedical regexes; `SPECIALIST_SPECS` has domain-only specialists (simulation/omics/chemistry) that are never instantiated. | `docs/history/CODEBASE_AUDIT.md` §6; `tribos/agents/discovery.py`; `tribos/agentic/specialists.py` |
| P3.4 | **Aspirational dead settings group**: "Milvus and the PrimeKG vector dump" — a settings group with no settings and no module. | `tribos/config/settings.py` |
| P3.5 | **`web/src/app/page.tsx` is 3,311 lines** with ~130 `any`, ~33 React-hooks warnings, 7 `<img>` warnings. | `docs/history/CODEBASE_AUDIT.md` "Still open" |
| P3.6 | **Sandbox hardening is in-process only** (SUP-2) — no container isolation, no Windows memory-limit enforcement for Lean. | `docs/history/CODEBASE_AUDIT.md`; `docs/TRIBOS_REMEDIATION.md` |
| P3.7 | **mypy is not a CI gate** (~290 pre-existing errors). | `docs/history/CODEBASE_AUDIT.md` |
| P3.8 | **Legacy alias sprawl** (`vivarix_*`, `lithoscribe_*`) risks double-counting tools and confusing the planner's tool description. | `tribos/extensions/`, `tribos/tools/registry.py` |
| P3.9 | **CI runs the full test matrix twice**; Bandit B608 medium warnings still need `# nosec` with reasons. | `docs/history/CODEBASE_AUDIT.md`; `docker/backend.Dockerfile` still says "Tribos Clinical R&D API" |
| P3.10 | **No documented confidence for a whole answer** — confidence is per-claim; a reader can mistake "98% on the expression" for "98% on the answer". | `docs/TRIBOS_REMEDIATION.md` §4 |

---

## Part 3 — Proposed Target Feature Set

### Tier 0 — Engineering substrate (P0)

| ID | Feature | Concrete deliverables | Agentic value |
|:--|:--|:--|:--|
| F-01 | **CAD & geometry intelligence** | STEP/IGES/STL/DWG ingest; geometry inspection tool (bounding box, mass properties, wall thickness, interference, feature recognition); 3D viewer in `web/`; CAD agent that answers "what changed between rev A and rev B" | Opens the door to everything physical |
| F-02 | **FEA / CAE toolchain** | Mesh generation; linear-static + thermal solver path; `cae_solve` + `cae_review` tools; implement the 14 published verification gates (reaction balance, mesh convergence, singularity screen, validity, hand-calc cross-check) | Turns "the bracket fails" into "here is why, and here is the proof" |
| F-03 | **Standards & compliance engine** | Clause library (ASME VIII-1, API 620/650, ISO 9001, Eurocodes, ASME Y14.5, ISO 1101) as structured rules; NLP discretization to atomic pass/fail; traceability matrix output; drift monitor | Highest commercial differentiation; also a natural HITL gate |
| F-04 | **Materials & property database** | Temperature-dependent properties, phase diagrams, material selection, MatWeb/MP connectors, S-N fatigue curves | Unblocks F-02 and every mechanical calculation |
| F-05 | **DOE + hypothesis engine (STEM-native)** | Factorial/D-optimal/LHS/response-surface design; hypothesis generation seeded from literature gaps + measured residuals; replaces biomedical `discovery.py` | Adds the missing *learn* loop |
| F-06 | **Pre-flight dimensional analysis** | Wire `physis_units` into the audit; dimensional-homogeneity gate before every solver call; fail-closed | Prevents confident-wrong-numbers |
| F-07 | **Multiphysics composition** | Couple thermal→structural→FEA chains in the plan DAG (with node references already supported by `plan_graph.py`) | Enables real system-level analysis |

### Tier 1 — Industrial layer (P1)

| ID | Feature | Concrete deliverables |
|:--|:--|:--|
| F-08 | **BOM, cost, supplier, lead-time** | BOM rollup from geometry+materials, cost model, supplier catalog connector, make/buy view |
| F-09 | **IP: patent search + FTO** | USPTO/EPO/WIPO connectors, claim charting, FTO report; reuses the existing grounding/verifier machinery |
| F-10 | **Requirements & traceability** | Requirement decomposition → atomic testable criteria → traceable to design, analysis, and evidence; RTM export |
| F-11 | **PLM/CAD/ERP integration** | Teamcenter/NX/SolidWorks/SAP connectors over the existing MCP + A2A surfaces; file-watch on project folders |
| F-12 | **LIMS/ELN + instrument data** | Instrument file ingestion, LIMS/ELN connectors, calibration provenance, chain-of-custody |
| F-13 | **Lab/field experiment planning** | Turn F-05 designs into instrument-ready procedures with uncertainty budgets |

### Tier 2 — Harness maturity (P2)

| ID | Feature | Concrete deliverables |
|:--|:--|:--|
| F-14 | **OpenTelemetry GenAI tracing** | Span-per-agent-step model (LLM call / tool / memory / handoff / reasoning), OTel GenAI semantic attributes, OTLP export, `tool_version` + `model_version` on every span |
| F-15 | **Monetary cost ledger** | Token→currency per run/user/project; spend dashboard; forecast; budget alerts |
| F-16 | **Answer versioning & diff** | Immutable answer versions, branch, side-by-side diff, per-answer edit history, "what changed since I last asked" |
| F-17 | **Server-side conversations** | Move chats from localStorage to the project store; user directory; cross-device history; presence + concurrent-edit safety |
| F-18 | **First-class run resumption** | Resume-at-phase endpoint; checkpoint/restore a multi-agent run; a real workflow engine (Temporal/Dagster) behind the existing job event log |
| F-19 | **Artifact-level HITL** | Per-artifact sign-off, annotation, rework request, escalation; `RunControl` gains approve-artifact; compliance sign-off workflow |
| F-20 | **Agentic design-space exploration** | LLM proposer–critic loop, Pareto + hypervolume retention, surrogate models, quantitative convergence termination |
| F-21 | **Agentic trajectory evaluation** | Plan quality, tool-selection precision/recall@k, cost-per-solved-problem, retry/error-rate metrics; gate `recall_at_k` in CI; human-preference rubric for engineering answers |
| F-22 | **Browser E2E + contract testing** | Playwright suite over the real stack; OpenAPI-generated TypeScript types (closes SUP-6) |
| F-23 | **Container-isolated sandbox** | Docker/gVisor/Firecracker for code + Lean execution; closes SUP-2 |

### Tier 3 — Trust & hygiene (P3)

| ID | Feature | Action |
|:--|:--|:--|
| F-24 | Docs truthfulness | Fix "Plan-and-Execute (API Default)" → `auto` in `README.md` + `docs/index.md` |
| F-25 | Wire `physis_units` | Close the T4 contradiction; add pre-flight dimensional gate |
| F-26 | Purge biomedical leftovers | Rewrite the "Clinical Verifier", `discovery.py`, memory regexes, dead specialists; enforce via `test_no_biomedical_leftovers.py` |
| F-27 | Remove aspirational dead code | Delete the Milvus/PrimeKG settings group, legacy aliases, dead specialists |
| F-28 | Frontend decomposition | Split `page.tsx` (3,311 lines); eliminate `any`; enable mypy gate |
| F-29 | CI hygiene | Single test matrix; Bandit `# nosec` with reasons; Dockerfile naming |
| F-30 | Answer-level confidence | Report a calibrated whole-answer status with scope and n, not just per-claim |

---

## Part 4 — Sequenced roadmap

**Wave 1 (Trust, ~1 sprint) — F-24…F-30.** Cheap, and every wave below depends on a truthful codebase. F-25 and F-26 in particular protect the product's core promise.

**Wave 2 (Geometry, ~2 sprints) — F-01 + F-04.** CAD ingest + geometry inspection + materials database. These are prerequisites for F-02 and unblock most mechanical work. Highest value-per-effort in the whole plan.

**Wave 3 (Analysis, ~2 sprints) — F-02 + F-06 + F-07.** Mesh + solver + the verification gates. This is where Tribos's existing verification DNA pays off most: Tribos can do what almost nobody does — *prove the FEA run was valid*.

**Wave 4 (Compliance & IP, ~2 sprints) — F-03 + F-10 + F-09.** The strongest commercial differentiation, and it reuses the grounding/verifier machinery Tribos already has.

**Wave 5 (Industrial, ~2 sprints) — F-08 + F-11 + F-12.** BOM/cost/supplier, PLM connectors, lab data.

**Wave 6 (Learn loop, ~1 sprint) — F-05 + F-20.** DOE + hypotheses + agentic DSE. Completes the research cycle.

**Wave 7 (Harness, ~2 sprints) — F-14…F-19 + F-22 + F-23.** Observability, cost, versioning, resumption, artifact HITL, E2E.

---

## Part 5 — Risks & non-goals

- **Scope.** This is a multi-year platform plan, not a sprint list. Waves 1–3 are the honest core; a plausible "complete agentic engineering R&D harness" is Waves 1–5.
- **CAD/CAE licensing.** F-01/F-02 can start with open kernels (OpenCascade, gmsh) and open solvers; commercial solver integration (Abaqus/Ansys) is a later commercial tier and may be better served via MCP servers the customer runs themselves — which the existing MCP/A2A surfaces already support.
- **Verification must lead, not follow.** Every new capability (F-01, F-02, F-05, F-20) must ship with an independent verification path in the same release, or it violates "be honest by design." This is the codebase's own established pattern and its single strongest asset.
- **Do not rebuild what exists.** Hybrid retrieval, budget enforcement, provenance replay, the sandbox, the evidence deck, and the export stack are all real. Extend them; do not replace them.
- **The published failure modes apply to Tribos too:** false completion (a solver that runs but produces physically wrong results), compounded chain errors (bad cleanup → bad mesh → confident downstream result), hidden geometry changes (an agent deleting a stress-controlling fillet), singularity peaks, and agent drift on long runs. F-02's verification gates and F-16/F-18 are the direct countermeasures.

---

## Verification of this analysis

- Every absence claim was checked by regex scan over `tribos/**/*.py`, `app/**/*.py`, `web/src/**/*.ts*` — CAD/FEA/mesh/HPC: 0 real hits. The one "finite element" hit is a routing keyword in `tribos/agentic/decompose.py:44`.
- Patent/supplier/BOM/DOE/LIMS: 0 hits in `tribos/` and `app/` (two "supplier" hits are a materials reference table and a math-eval prompt).
- `web/package.json` confirmed to contain no 3D dependency.
- Upload kinds confirmed as `table | hdf5 | mat | paper` (`web/src/types/datasets.ts:4`).
- Backend confirmed live with 55 routes; `GET /api/health` → `{"status":"healthy", ...}`; `GET /api/frameworks` → default `auto`.
- All feature claims above are sourced from the code paths and doc sections cited inline.

---

## Sources

Research conducted 2026-10-26.

**Agentic engineering platforms & long-horizon agents**
- [Synopsys Powers Autonomous Engineering with a Broad Portfolio of Long-Horizon Agents and Autopilot Platform](https://news.synopsys.com/2026-09-28-Synopsys-Powers-Autonomous-Engineering-with-a-Broad-Portfolio-of-Long-Horizon-Agents-and-Autopilot-Platform)
- [AI Agents for Mechanical Engineering: A Practical Guide (2026)](https://skill-lync.com/blogs/ai-agents-for-mechanical-engineering) — canonical agentic-FEA stage list, 14 verification gates, published failure modes
- [Best AI Simulation Tools for Mechanical Engineers (2026) — CoLab](https://www.colabsoftware.com/guides/ai-powered-simulation-tools-smarter-faster-design-validation)
- [Best AI Tools for FEA Analysis: 2026 Market Report — Energent.ai](https://www.energent.ai/use-cases/en/compare/ai-tools-for-fea-analysis)
- [Top 6 AI tools for mechanical engineers in 2026 — Neural Concept](https://www.neuralconcept.com/post/ai-tools-for-mechanical-engineers)
- [Agentic AI for laboratory workflows: LabVantage CORTEX](https://www.labvantage.com/labvantagecortex/)
- [Towards Human-Led, Agent-Driven Autonomous Laboratories](https://www.preprints.org/manuscript/202608.0273)

**CAD, geometry & drawings**
- [AI Agent CAD Management: 2026 Guide — Fastio](https://fast.io/resources/ai-agent-cad-management/) — STEP/IGES/DWG/SolidWorks parsing, geometry diffing
- [Best 8 AI CAD Tools 2026 we tested — RapidDirect](https://www.rapiddirect.com/blog/best-ai-cad-tools-review/) — text→CAD producing true STEP files
- [7 Best AI-Powered CAD Tools in 2026 — Leo AI](https://www.getleo.ai/blog/7-best-ai-powered-cad-tools-in-2026)
- [CAD-LLM: Large Language Model for CAD Generation — Autodesk Research](https://www.research.autodesk.com/publications/ai-lab-cad-llm/)
- [AI for CAD Drawings: What It Can Do in 2026 — DAC.digital](https://dac.digital/ai-for-cad-drawings-what-it-can-do-in-2026/)
- [AI Product Design with Embedded AI Tools — SOLIDWORKS](https://www.solidworks.com/product/solidworks-design/ai-overview)

**Standards & compliance**
- [Compliance Standards — ENGAINEER.ORG](https://engaineer.org/standards/) — ASME/API/ISO/Eurocodes, 50,000+ atomic requirements, NLP discretization, drift monitoring
- [Automating Design Code Compliance Using Agentic AI — Autodesk University](https://www.autodesk.com/autodesk-university/class/Automating-Design-Code-Compliance-Using-Agentic-AI-and-Autodesk-Technology-2025)
- [AI Tools for CAD Standards Enforcement (2026) — CoLab](https://www.colabsoftware.com/guides/ai-tools-for-cad-standards-enforcement-your-complete-guide-to-automated-compliance-2026)
- [Engineering AI Assistants & Agents — EMU Group](https://emugtech.com/ai-and-intelligent-automation-services/engineering-ai-assistants-agents/)

**PLM, BOM & IP**
- [Introducing Teamcenter 2606 — Siemens](https://blogs.sw.siemens.com/teamcenter/teamcenter-2606/) — "Teamcenter AI BOM agent"
- [Best PLM Software 2026 — Demystifying PLM](https://www.demystifyingplm.com/best-plm-software-2026)
- [Best 7 Patent Search Platforms in 2026 — Patsnap](https://www.patsnap.com/resources/blog/articles/best-patent-search-platforms-2026/) — disclosure→feature extraction→dual search strategy
- [FTO Patent Search Software — Cypris](https://cypris.ai/insights/fto-patent-search-software-how-to-run-an-ai-powered-freedom-to-operate-report-in-2026)

**Observability & evaluation**
- [What Is Agent Observability? A 2026 Developer Guide — MLflow](https://mlflow.org/articles/what-is-agent-observability-a-2026-developer-guide/) — OTel GenAI semantic conventions, span model, eval hooks
- [Best AI Agent Observability Tools in 2026 — Laminar](https://laminar.sh/article/top-6-agent-observability-platforms)
- [Tracing Agent Harness Behavior with NVIDIA NeMo Relay](https://developer.nvidia.com/blog/tracing-agent-harness-behavior-with-nvidia-nemo-relay/) — Agent Trajectory Observability Format (ATOF)

**Agentic optimization**
- [Agentic Design Space Exploration for Joint Hardware Configuration — arXiv 2610.07191](https://arxiv.org/html/2610.07191v1) — LLM proposer–critic loop, Pareto + hypervolume, convergence criteria
- [AI-aided design optimization and topology optimization — Sage Journals](https://journals.sagepub.com/doi/pdf/10.1177/16878132261489711)
- [Simcenter HEEDS — Siemens](https://www.siemens.com/en-us/products/simcenter/integration-solutions/heeds/) — DSE interfacing CAD/CAE tools

**Lab & data**
- [LIMS, ELN, and the Rise of API-First Platforms — QPillars](https://qpillars.com/blog/laboratory-automation-software-comparison)
- [Lab Instrument Integration Architecture: SiLA 2 — IntuitionLabs](https://intuitionlabs.ai/articles/lab-instrument-integration-sila-2-allotrope-lims)
- [Five Steps to Smooth Agentic AI Adoption — Pharm Outsourcing](https://www.pharmoutsourcing.com/Featured-Articles/626512-Five-Steps-to-Smooth-Agentic-AI-Adoption/)
