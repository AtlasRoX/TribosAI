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

Choose an orchestration backend per request with `framework`, or configure a global default with `TRIBOS_DEFAULT_FRAMEWORK`. `GET /api/frameworks` lists available modes:

| Mode | `framework` | Architectural Description |
| :--- | :--- | :--- |
| **Plan-and-Execute** *(API Default)* | `agentic-plan-execute` | Decomposes the inquiry into an LLM-planned tool DAG executed concurrently (LLMCompiler). Performs Self-RAG gap-driven re-retrieval, ContraCrow counter-evidence search, NLI claim audits, and calibrated confidence scoring. |
| **Authoritative ReAct Compiler** | `authoritative-react-compiler` | Structured deterministic pipeline executing parallel Stage 1 evidence gathering followed by Stage 2 numerical/symbolic computation and Reflexion auditing. |
| **Centralized Supervisor** | `multi-agent-supervisor` | Magentic-One-style progress ledger delegating subtasks dynamically to Archivon, Axiom, Dynamis, Calcula, and Physis. |
| **Specialist Swarm** | `multi-agent-swarm` | Peer-to-peer delegation where specialist agents directly hand off context and intermediate findings to each other until synthesis is complete. |
| **Multi-Agent Debate** | `multi-agent-debate` | Multi-agent peer debate where mathematical, physical, and computational claims undergo rigorous cross-agent critique before finalizing the derivation. |

All frameworks share:
- Strict tool reliability policies: retries, persistent result caching, and circuit breakers.
- Human-in-the-loop controls: clarifying questions, plan approval, steering, and cancellation.
- Background jobs with reconnectable SSE streams.
- Thread-scoped persistent memory vault (Mem0 SQLite store with Okapi BM25 scoring).
- Subprocess code execution sandbox (`TRIBOS_SANDBOX=on` by default).
- Model Context Protocol server (`POST /mcp`) and Agent-to-Agent card (`/.well-known/agent-card.json`).

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

# Run code linters
uv run ruff check tribos app tests

# Build and verify documentation site
uv run mkdocs build --strict
```

- [Developer Setup & Architecture](docs/developer/README.md)
- [Scientific Validation & Architecture](docs/SCIENTIFIC_VALIDATION_AND_ARCHITECTURE.md)
- [Contributing Guide](docs/CONTRIBUTING.md)

---

## Acknowledgements & Credits

- **Engineering & Architecture:** **ChronoStrider Engineering**.
