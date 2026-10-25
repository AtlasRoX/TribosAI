# Tribos

> **Tribos** — Engineering, Physics & Mathematical Sciences Discovery Platform  
> **Made by ChronoStrider Engineering**

[![Tests](https://github.com/AtlasRoX/trib/actions/workflows/tests_tribos.yml/badge.svg)](https://github.com/AtlasRoX/trib/actions/workflows/tests_tribos.yml)
[![Web](https://github.com/AtlasRoX/trib/actions/workflows/tests_web.yml/badge.svg)](https://github.com/AtlasRoX/trib/actions/workflows/tests_web.yml)
[![Evals](https://github.com/AtlasRoX/trib/actions/workflows/evals.yml/badge.svg)](https://github.com/AtlasRoX/trib/actions/workflows/evals.yml)
[![Docs](https://github.com/AtlasRoX/trib/actions/workflows/mkdocs_deploy.yml/badge.svg)](https://github.com/AtlasRoX/trib/actions/workflows/mkdocs_deploy.yml)

**Tribos** (*τρίβος* — "a worn path, practice, diligent inquiry") is an authoritative multi-agent scientific discovery platform for **Engineering, Physics, and the Mathematical Sciences**, engineered by **ChronoStrider Engineering**.

Tribos answers advanced engineering and physical inquiries by decomposing questions into structured tool DAGs, coordinating five domain-specialist agents, and returning derivation-first answers with exact LaTeX equations, numerical simulations, sandboxed code execution, and peer-reviewed literature citations (arXiv, DOI, zbMATH, CODATA).

---

## Architecture & Technology Stack

- **Backend Platform:** FastAPI (`app/backend/main.py`), with the multi-agent orchestrator, specialist engines, and verification pipeline in `tribos/`.
- **Frontend Application:** Next.js (`web/`) with full mathematical typesetting powered by KaTeX (`rehype-katex`), streaming SSE reasoning tokens, and responsive run inspectors.
- **Five Specialist Agents** (`tribos/`):
  - **Archivon** (`tribos/archivon/`): Literature synthesis and citation grounding across arXiv, zbMATH Open, Crossref, OpenAlex, Semantic Scholar, and NASA ADS with retraction verification.
  - **Axiom** (`tribos/axiom/`): Exact symbolic computer algebra via SymPy: closed-form equation solving, calculus (differentiation, integration, limits, series), ODE `dsolve`, exact linear algebra, and dual symbolic/mpmath identity verification.
  - **Dynamis** (`tribos/dynamis/`): Numerical simulation of dynamical systems with SciPy: ODE/IVP solvers (`RK45`, `DOP853`, `Radau`, `BDF`), fixed-point equilibrium and Jacobian eigenvalue stability analysis, parameter continuation scans, nonlinear curve fitting, and optimization.
  - **Calcula** (`tribos/extensions/sandbox.py`): Isolated subprocess Python sandbox running NumPy, SciPy, SymPy, Pandas, Pint, Matplotlib, NetworkX, mpmath, and statsmodels; automatic schema and statistical profiling of experimental datasets (`CSV`, `TSV`, `HDF5`, `MAT`, `Parquet`, `XLSX`).
  - **Physis** (`tribos/physis/`): Physical reference metrology: NIST CODATA 2022 fundamental physical constants, Pint unit conversions and equation dimensional homogeneity verification ($[M^a L^b T^c I^d \Theta^e N^f J^g]$), OEIS integer sequences, Materials Project crystal data, and Wikipedia scientific concepts.

---

## Agent Orchestration Frameworks

Choose an orchestration backend per request with `framework`, or configure a global default with `TRIBOS_DEFAULT_FRAMEWORK`. A request that names no framework (and no default is configured) uses **Auto** routing. `GET /api/frameworks` lists available modes and reports the active default:

| Mode | `framework` | Architectural Description |
| :--- | :--- | :--- |
| **Auto** *(API Default)* | `auto` | Reads each question and routes it to the architecture that fits (`tribos/agentic/router.py`): closed computations and fully specified problems run the direct workflow with the mathematics agent, open questions go to one of the agentic frameworks below, and critics debate the draft when the evidence conflicts. |
| **Plan-and-Execute** | `agentic-plan-execute` | Decomposes the inquiry into an LLM-planned tool DAG executed concurrently (LLMCompiler). Performs Self-RAG gap-driven re-retrieval, ContraCrow counter-evidence search, NLI claim audits, and calibrated confidence scoring. |
| **Authoritative ReAct Compiler** | `authoritative-react-compiler` | Structured deterministic pipeline executing parallel Stage 1 evidence gathering followed by Stage 2 numerical/symbolic computation and Reflexion auditing. |
| **Centralized Supervisor** | `multi-agent-supervisor` | Magentic-One-style progress ledger delegating subtasks dynamically to Archivon, Axiom, Dynamis, Calcula, and Physis. |
| **Specialist Swarm** | `multi-agent-swarm` | Peer-to-peer delegation where specialist agents directly hand off context and intermediate findings to each other until synthesis is complete. |
| **Multi-Agent Debate** | `multi-agent-debate` | Multi-agent peer debate where mathematical, physical, and computational claims undergo rigorous cross-agent critique before finalizing the derivation. |

All frameworks share:
- Strict tool reliability policies: retries, persistent result caching, and circuit breakers.
- Human-in-the-loop controls: clarifying questions, plan approval, steering, and cancellation.
- Background jobs with reconnectable SSE streams.
- Thread-scoped persistent memory vault (Mem0 SQLite store with Okapi BM25 scoring).
- Subprocess code execution sandbox (on by default; `TRIBOS_SANDBOX=off` disables it).
- Model Context Protocol server (`POST /mcp`) and Agent-to-Agent card (`/.well-known/agent-card.json`).

---

## Verified Mathematics Agent

Concrete mathematical tasks are solved by a bounded ReAct controller over the Axiom tools (`tribos/axiom/agent.py`), following the patterns in `math_agent_research_recommendations.md` (ReAct, ToRA, THOR, Toolformer, RAP). It covers 20 task kinds, each with its own independent check:

| Area | Tools | Independent check |
| :--- | :--- | :--- |
| Algebra | `axiom_solve`, `axiom_nsolve`, `axiom_inequality`, `axiom_simplify` | back-substitution, root counting (Sturm / square-free degree), sampled interval membership |
| Calculus | `axiom_calculus`, `axiom_tangent`, `axiom_optimize`, `axiom_nintegrate` | numeric derivatives, quadrature, one-sided limits, O(hⁿ) truncation, dense sampling for global extrema, two quadrature rules |
| Differential equations and transforms | `axiom_dsolve`, `axiom_transform`, `axiom_recurrence` | `checkodesol` + initial conditions, the defining Laplace/Fourier integral, direct iteration |
| Linear algebra and vector calculus | `axiom_linalg`, `axiom_vector_calculus` | second algorithms, Cayley–Hamilton, finite-difference partial derivatives |
| Discrete mathematics | `axiom_number_theory`, `axiom_verify_identity` | independent integer arithmetic (Miller–Rabin, square-and-multiply), exact counterexamples |
| Probability and statistics | `axiom_probability`, `calcula_statistics` | exact SymPy against SciPy, textbook formulas against SciPy |

- **Parse, never rewrite.** `tribos/axiom/problem.py` turns prose, LaTeX or Unicode math into a typed `ProblemSpec` (kind, expression, variable, bounds, domain, assumptions) and keeps the verbatim question; anything it had to guess is listed as an ambiguity.
- **Rules first, model on escalation.** A deterministic strategy ladder per task kind runs at zero model cost (e.g. exact solve → numeric interval scan); the planning model chooses steps only when the rules reach no checked answer.
- **Independent verifier.** `tribos/axiom/verifier.py` re-derives every check from the *original* problem, never from the agent's arguments: level 1 confirms the tool call encodes the question asked (same equation up to a nonzero factor, same integrand and bounds, same matrix); level 2 checks the answer by a second method (back-substitution, differentiation, quadrature, numeric limits, Cayley–Hamilton, `checkodesol`, exact counterexamples).
- **Typed failures and local repair.** Schema, argument, semantic-mismatch, cannot-solve, no-progress and infrastructure failures are classified separately; repairs are local (at most `TRIBOS_MATH_AGENT_MAX_REPAIRS`, default 4), identical failed calls are never re-run, and infrastructure faults are never charged to the policy.
- **Honest status.** Every answer is `verified`, `partially_verified` (e.g. a periodic root family, or numeric roots whose completeness cannot be proven), `unverified` or `failed`, with the passing checks and the open gaps. The synthesis is told to report exactly that.
- **Trajectories as data.** Set `TRIBOS_MATH_TRAJECTORY_DIR` to append each run as a JSONL record with interleaved decision / tool_call / observation / verification events and per-step labels (`tool_schema_valid`, `execution_success`, `semantic_alignment`, `local_result_valid`, `progress_made`), ready for evaluation and SFT.

- **Parse fidelity.** Every number, differential and meaning-changing word in the question ("twice", "area", "maximum", ...) must be used by the parsed problem; otherwise the answer can never be `verified`, because it may answer a different question.
- **Measured and calibrated.** `python -m tribos.axiom.math_eval` runs a stratified benchmark (development set and three held-out sets, 268 problems; prose, LaTeX and Unicode phrasing) graded against gold answers, independently of the verifier, plus an adversarial suite of known-wrong candidates. It reports accuracy, verified precision and coverage, false accepts and rejects, cross-fitted ECE/Brier and latency. `tribos/axiom/calibration.json` holds P(correct | status), fitted on the third held-out set with the code frozen (verified: 43/43, Laplace estimate 0.98, Wilson 95% lower bound 0.92). That figure describes the agent's final answer expression only and is shown with its scope and n; the written answer around it is checked statement by statement (see below), never covered by it.
- **The written answer is checked too.** `tribos/verify/math_claims.py` re-evaluates every equation, derivation step and result-table row of the final answer with the question's values and the tools' structured outputs (arithmetic, identities by sampling, derivatives of the stated functions, deferred equations, amplitude-phase reconstruction, tool-value cross-checks, grounding of table numbers). A contradicted statement fails verification and goes back to the writer with the computed value; coverage (how many statements were evaluated) is reported apart from the result, and an answer with nothing checkable is "not evaluated". `python -m tribos.evals.math_claims_matrix` measures false alarms and detection across nine kinds of mathematics. See docs/TRIBOS_REMEDIATION.md.

It runs as the `math_agent` phase of every agentic framework and is available to planners as the `axiom_solve_problem` tool. `tests/test_math_agent.py` holds the Phase 1 gate: zero false accepts on every benchmark set and on the adversarial suite.

---

## Data & Computation Sources

| Domain | Integrated Sources & Solvers |
| :--- | :--- |
| **Scholarly Literature** | arXiv (`math.*`, `physics.*`, `cs.*`, `eess.*`), zbMATH Open, Crossref, OpenAlex, Semantic Scholar, NASA ADS |
| **Symbolic Mathematics** | SymPy (algebra, calculus, ODEs, linear algebra), mpmath (arbitrary-precision numerical verification) |
| **Numerical Dynamics** | SciPy `integrate.solve_ivp`, `optimize.minimize`, `optimize.root`, `optimize.curve_fit` |
| **Data Computation** | Isolated Python Subprocess (NumPy, SciPy, Pandas, Pint, Matplotlib, NetworkX, statsmodels, h5py) |
| **Physical Metrology** | NIST CODATA 2022 fundamental physical constants, Pint dimensional unit system |
| **Integer Sequences** | OEIS (On-Line Encyclopedia of Integer Sequences REST API) |
| **Materials Science** | Materials Project API v2 and curated 25-material solid-state engineering reference table |
| **Web & Encyclopedia** | Wikipedia scientific concept API, DuckDuckGo / Tavily web search (`TAVILY_API_KEY`) |

---

## Derivation-First Answer Structure

Scientific responses emitted by Tribos adhere strictly to a derivation-first structure:
1. **Result**: Immediate, unambiguous answer to the inquiry with dimensional units.
2. **Derivation**: Step-by-step mathematical derivation formatted in LaTeX notation, rendered on the frontend via KaTeX and documented via MathJax.
3. **Verification**: Exact symbolic back-substitution, dimensional homogeneity verification ($LHS \equiv RHS$), or numerical simulation checks.
4. **Assumptions & Limits**: Physical regimes of validity (e.g., non-relativistic, laminar, low Reynolds number, ideal gas).
5. **References**: Inline grounded citations to preprints (`arXiv:`), journals (`doi:`), theorem databases (`zbl:`), or constants (`nist:`).

---

## Quick Start

### Prerequisites

- Python 3.12+
- [uv](https://docs.astral.sh/uv/) (fast Python package manager)
- Node.js 22+

### Setup

```sh
# 1. Clone the repository
git clone https://github.com/AtlasRoX/trib && cd trib

# 2. Install Python dependencies
uv sync --extra dev --frozen

# 3. Configure environment
cp .env.example .env        # uncomment and configure your API keys (e.g. OPENAI_API_KEY)
```

### Running the Services

```sh
# Terminal 1: Backend API on http://127.0.0.1:8000
uv run uvicorn app.backend.main:app --host 127.0.0.1 --port 8000

# Terminal 2: Next.js Web App with KaTeX frontend on http://localhost:3000
cd web && npm ci && npm run dev
```

The web application connects to `NEXT_PUBLIC_API_URL` (default `http://127.0.0.1:8000`). Validate frontend integrity with:
```sh
cd web && npm run typecheck && npm test && npm run build
```

### Docker

```sh
docker compose -f docker/compose.yml up --build
```

This builds `docker/backend.Dockerfile` (context: the repository root) and `docker/web.Dockerfile` (context: `web/`), reads secrets from `.env`, keeps all backend state on the `tribos-data` volume, and publishes both ports on `127.0.0.1` only (see the header of `docker/compose.yml` to expose them behind a TLS proxy).

---

## Configuration Reference

Every environment variable is documented in [docs/configuration.md](docs/configuration.md), detailing its type, default value, and where it is read in the codebase. [`.env.example`](.env.example) provides a commented configuration template.

Both files are maintained by `scripts/gen_env_reference.py`. Run `--check` to verify zero drift:
```sh
uv run python scripts/gen_env_reference.py --check
```

### Data Storage & Retention

When `TRIBOS_DATA_DIR` is set, state is consolidated under a single directory containing:
- `memory/` (SQLite research vault)
- `runs/` (persisted agent execution manifests)
- `uploads/` (attached user datasets)
- `jobs/` (background execution queues)
- `tool_cache/` (cached tool responses)

Retention policies:
- Expired tool-cache rows are automatically purged.
- Completed background jobs are pruned after `TRIBOS_JOB_TTL_DAYS` (default: 30 days).
- Up to `TRIBOS_MAX_RUNS` run manifests are retained (default: 500).

---

## Evaluation Harness

Tribos includes an offline and online evaluation framework (`python -m tribos.evals`) to benchmark intent routing, tool retrieval, and derivation accuracy:

```sh
# Fast offline routing and tool planning check
uv run python -m tribos.evals run --level plan

# Full derivation and synthesis evaluation with rubric judge
uv run python -m tribos.evals run --level answer --judge

# Compare two evaluation runs
uv run python -m tribos.evals compare eval_runs/<run_a> eval_runs/<run_b>
```

See [docs/evals.md](docs/evals.md) for benchmark suites and CI integration details.

---

## Development & Testing

```sh
# Run backend test suite
uv run pytest -q tests/

# Run code linters (the CI gate: pyflakes and syntax errors; the full rule set still reports legacy findings)
uv run ruff check --select F,E9 tribos app tests
uv run bandit -c pyproject.toml -r tribos app --severity-level high

# Build and verify documentation site
uv run mkdocs build --strict
```

- [Developer Setup & Architecture](docs/developer/README.md)
- [Scientific Validation & Architecture](docs/SCIENTIFIC_VALIDATION_AND_ARCHITECTURE.md)
- [Contributing Guide](docs/CONTRIBUTING.md)

---

## Acknowledgements & Credits

- **Engineering & Architecture:** **ChronoStrider Engineering**.
