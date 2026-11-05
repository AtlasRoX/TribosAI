# Tribos Documentation

<p align="center">
  <img src="assets/logo.png" alt="Tribos Logo" width="140" />
</p>

> **Tribos Engineering & Scientific R&D Assistant**  
> **Made by ChronoStrider Engineering**

**Tribos** (*τρίβος* — "a worn path, practice, diligent inquiry") is an authoritative multi-agent scientific discovery platform for **Engineering, Physics, and the Mathematical Sciences**, engineered by **ChronoStrider Engineering**.

Tribos combines a 5-stage deterministic-and-agentic reasoning pipeline with five specialized computational engines for exact symbolic mathematics, dynamical systems simulation, sandboxed experimental data computation, physical constants & metrology, and scholarly literature synthesis.

---

## Specialist Agents

Every scientific query in Tribos is decomposed and routed to domain-specialized agents equipped with validated toolsets:

| Specialist Agent | Domain Role | Core Tools & Key Capabilities |
| :--- | :--- | :--- |
| **[Archivon](archivon/index.md)** | Scientific Literature & Citations | `archivon_literature_search`, `archivon_paper_details`, `archivon_recommend`<br>Federated multi-source search across arXiv, zbMATH Open, Crossref, OpenAlex, Semantic Scholar, and NASA ADS; reciprocal rank fusion (RRF), cross-encoder reranking, claim-level citation grounding, and retraction verification. |
| **[Axiom](axiom/index.md)** | Symbolic Mathematics & Formal Verification | `axiom_simplify`, `axiom_solve`, `axiom_calculus`, `axiom_dsolve`, `axiom_linalg`, `axiom_verify_identity`, `axiom_latex`<br>Exact computer algebra via SymPy: closed-form equation solving, calculus (differentiation, integration, limits, series), ODE `dsolve`, exact linear algebra, and dual symbolic/mpmath identity verification. |
| **[Dynamis](dynamis/index.md)** | Dynamical Systems & Simulation | `dynamis_simulate_ode`, `dynamis_equilibrium`, `dynamis_parameter_scan`, `dynamis_optimize`, `dynamis_fit_parameters`, `dynamis_root_find`<br>SciPy numerical computing: initial value problem (IVP) integration (`RK45`, `DOP853`, `Radau`, `BDF`), fixed-point search, Jacobian eigenvalue stability classification, parameter sensitivity scans, nonlinear curve fitting, and optimization. |
| **[Calcula](calcula/index.md)** | Sandboxed Computation & Data Analysis | `calcula_run_python`, `calcula_describe_dataset`<br>Isolated subprocess Python sandbox (no network, strict memory & time limits) running NumPy, SciPy, SymPy, Pandas, Pint, Matplotlib, NetworkX, mpmath, and statsmodels; automatic dataset inspection (`CSV`, `TSV`, `HDF5`, `MAT`). |
| **[Physis](physis/index.md)** | Physical Constants, Units & Reference | `physis_constants`, `physis_units`, `physis_oeis`, `physis_materials`, `physis_wolfram`, `physis_encyclopedia`<br>NIST CODATA 2022 fundamental physical constants, Pint unit conversions and equation dimensional homogeneity checks ($[M^a L^b T^c I^d \Theta^e N^f J^g]$), OEIS integer sequences, Materials Project crystal data, and Wikipedia scientific definitions. |

---

## Five Interchangeable Orchestration Frameworks

Tribos supports five interchangeable multi-agent orchestration frameworks configurable per-request via `framework` or globally with `TRIBOS_DEFAULT_FRAMEWORK` (with automatic query routing via `auto`):

1. **Plan-and-Execute (`agentic-plan-execute`)** *(API Default)*: Decomposes the research question, executes an LLM-planned tool DAG in parallel, performs gap-driven re-retrieval (Self-RAG), conducts counter-evidence search (PaperQA2/ContraCrow), and calculates calibrated claim confidence scores.
2. **Authoritative ReAct Compiler (`authoritative-react-compiler`)**: Structured deterministic pipeline executing parallel Stage 1 evidence gathering followed by Stage 2 numerical/symbolic computation and Reflexion auditing.
3. **Centralized Supervisor (`multi-agent-supervisor`)**: Magentic-One-style progress ledger delegating subtasks dynamically to Archivon, Axiom, Dynamis, Calcula, and Physis.
4. **Specialist Swarm (`multi-agent-swarm`)**: Peer-to-peer delegation where specialist agents directly hand off context and intermediate findings to each other until synthesis is complete.
5. **Multi-Agent Debate (`multi-agent-debate`)**: Multi-agent peer debate where mathematical, physical, and computational claims undergo rigorous cross-agent critique before finalizing the derivation.

---

## Derivation-First Structure & KaTeX Math Rendering

Scientific responses emitted by Tribos adhere strictly to a derivation-first structure:
- **Result**: Immediate, unambiguous answer to the inquiry with dimensional units.
- **Derivation**: Step-by-step mathematical derivation formatted in LaTeX notation, rendered on the frontend via KaTeX and documented via MathJax.
- **Verification**: Exact symbolic back-substitution, dimensional homogeneity verification ($LHS \equiv RHS$), or numerical simulation checks.
- **Assumptions & Limits**: Physical regimes of validity (e.g., non-relativistic, laminar, low Reynolds number, ideal gas).
- **References**: Inline grounded citations to preprints (`arXiv:`), journals (`doi:`), theorem databases (`zbl:`), or constants (`nist:`).

---

## Quick Links

- [Agentic System Architecture](agentic/README.md)
- [Evaluation Harness (`python -m tribos.evals`)](evals.md)
- [Configuration Reference](configuration.md)
- [Contributing Guide](CONTRIBUTING.md)
