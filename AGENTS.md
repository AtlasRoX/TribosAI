# AGENTS.md: guide for AI coding agents working on Tribos

Tribos is a multi-agent research assistant for engineering, physics and mathematics:

- **Backend:** a FastAPI app in `app/backend`.
- **Agent pipeline:** `tribos/`, written in Python 3.12.
- **Frontend:** Next.js 16 / React 19 in `web/`. Read [web/AGENTS.md](web/AGENTS.md) before any web work, because this Next.js version differs from older ones.

Work to pick up next is in [docs/FEATURE_ROADMAP.md](docs/FEATURE_ROADMAP.md).

## Setup and commands

```bash
uv sync --extra dev                      # Python deps (.venv); on Windows the interpreter is .venv/Scripts/python.exe
uv run pytest -q -p no:cacheprovider     # full suite, about 4 min; baseline 1326 passed, 15 skipped, 0 failed
uv run ruff check tribos app tests scripts --select F,E9   # blocking CI gate
uv run bandit -c pyproject.toml -r tribos app --severity-level high   # blocking CI gate
uv run python scripts/gen_env_reference.py   # regenerate docs/configuration.md + .env.example after adding settings
uv run python scripts/gen_env_reference.py --check   # CI gate
uvicorn app.backend.main:app --reload    # API on :8000 (TRIBOS_AUTH_MODE=disabled for local dev)

cd web && npm ci
npm run typecheck && npx eslint src && npm test && npx next build   # all must pass (eslint: 0 errors)
npm run dev                              # UI on :3000
```

Never commit `.env`. Tests must not need the network: use the fakes in `tests/fakes.py` and `tests/agentic_fakes.py`.

## Architecture map

- **Tools.** Each extension module in `tribos/extensions/<name>.py` calls `registry.register(...)` (see `dynamis.py`, `axiom.py`, `physis.py`).
  - New modules must be listed in `EXTENSION_MODULES` in `tribos/extensions/__init__.py`.
  - Give a new tool an existing domain so the agentic planner and specialists route it with no extra wiring:

    | Domain | Use it for |
    | :--- | :--- |
    | `dynamis` | numerical work and simulation |
    | `physis` | constants, units, materials, engineering reference |
    | `axiom` | symbolic work and proofs |
    | `archivon` | literature and papers |
    | `analysis` | code execution |

  - Write a precise tool description: the planner and `tribos/agentic/tool_retrieval.py` select tools from it.
- **Specialist engines.**

  | Engine | Package | Built on |
  | :--- | :--- | :--- |
  | Axiom (symbolic) | `tribos/axiom` | SymPy |
  | Dynamis (numerical, ODE) | `tribos/dynamis` | SciPy |
  | Physis (constants, units) | `tribos/physis` | CODATA, Pint |
  | Archivon (literature) | `tribos/archivon` | |
  | Calcula (sandboxed Python) | `tribos/agentic/sandbox` | |

- **Parsing user or model maths.** Always use `tribos/axiom/safe_expr.py` (`parse_math`) or `tribos.axiom.engine.safe_parse_expr`. Never call `eval`, `sympify` or `parse_expr` directly on untrusted strings.
- **Evidence for the answer-writing model.** `tribos/agents/stem_evidence.py` renders STEM tool results into the evidence block, and `tribos/agents/prompts.py` builds the prompts. A new tool needs a renderer here, or the model never sees its result.
- **Response layer.** `tribos/writer/` turns checked results into a readable answer (wired in `tribos/agents/orchestration/presentation.py`):
  - `facts.py` computes requested values by code before drafting (initial-value problems: exact solution checked by substitution, oscillator parameters, values at requested points, RK4 comparison), rendered as `<computed_results>`;
  - `outline.py` reads the user's own numbered tasks, so answers follow the user's numbering;
  - `lint.py` and `editor.py` keep internal ids (q1, req-2), pipeline jargon and raw computer-algebra syntax out of answers. The copy edit is accepted only if it adds no number and drops no citation.
  - Never put internal ids or tool names into writer-facing instructions as heading examples.
- **Result keys.** Result-key constants live in `tribos/agents/result_keys.py`. Evidence keys (arXiv, DOI, zbMATH, MR, ADS) are normalised only through `tribos/sources/keys.py`.
- **Result cards in the UI.**
  - A tool result reaches the browser as `execution_artifacts[<key>]`.
  - Classic path: `tribos.extensions.hooks.register_artifact_builder`. Agentic phases write `execution_artifacts` directly.
  - Web cards go in `web/src/components/artifacts/<Card>.tsx`, with one entry added to `web/src/components/artifacts/registry.tsx` (`{ key, Component }`). `MessageArtifacts.tsx` renders every registered card automatically.
- **Verification.**
  - `tribos/verify/verifier.py` grounds citations and checks claims.
  - `tribos/verify/math_claims.py` re-evaluates the answer's equations.
  - The math agent (`tribos/axiom/agent.py`) has a zero-false-accept gate in `tests/test_math_agent.py`, which must stay green.
  - The chemistry agent Chemeia (`tribos/agentic/chem_agent.py`, `TRIBOS_CHEM_AGENT`) runs on organic-chemistry
    questions:
    - the model writes each intermediate and the target compound as SMILES;
    - RDKit checks every structure and matches the target to the answer options (`tribos/physis/chemistry.py`,
      `tribos/physis/names.py`);
    - a mismatch gets one repair round.

    Its evidence says that code checked the structures, not the chemistry.
- **Sandbox.** `tribos/agentic/sandbox/runner.py` and `policy.py` provide a runtime IO guard, SymPy parser hardening and resource limits. Any tool that executes code must be:
  - classified `executes_code` in `tribos/agentic/plan_graph.tool_capabilities`;
  - refused for replay in `tribos/provenance/rerun.py` (`UNSAFE_TOOL_RE`).
- **Settings.** Every `TRIBOS_*` env var must be a `Setting(...)` in `tribos/config/settings.py`. Then regenerate the docs with `gen_env_reference.py`; CI checks that they match.
- **API routers.** Optional routers go in the router list in `app/backend/main.py` (around line 125). Use `get_current_user` for auth and the per-user limits in `app/backend/limits.py`.
- **Research projects.** `tribos/agentic/campaign.py` stores and drives them. Loop mode (the default in the app) is `tribos/agentic/research/`: charter, parallel tests with independent replication, findings ledger, a judge with deterministic evidence rules, adaptive stopping, time estimate and a thesis. Thesis exports (Chromium PDF, DOCX, bundle) are `tribos/export/thesis.py`; the web view is `web/src/components/campaigns/ResearchLab.tsx`. See [docs/agentic/research-loop.md](docs/agentic/research-loop.md).
- **Projects.** The store is `tribos/utils/memory/project_store.py` (SQLite) and the API is `app/backend/routers/projects.py`. Facts extracted from runs come from `tribos/agentic/project_memory.py`. In the browser, chats live in localStorage (`web/src/services/localStorageService.ts`).

## Conventions

- Match the surrounding code: comment density, naming, idiom, and a line length of 120.
- Python uses type hints and `from __future__ import annotations`. TypeScript has no new `any`.
- Every fix or feature gets a test, in a new file `tests/test_feat_<name>.py` or `web/tests/feat<Name>.test.mts`. Verify numerics against analytic results.
- Avoid new dependencies. Available already: numpy, scipy, sympy, pint, pandas, matplotlib, pypdf, python-docx, fpdf2, h5py.
- The product is STEM only. Biomedical leftovers are guarded by `tests/test_no_biomedical_leftovers.py`; don't reintroduce any.
- Be honest by design: report results as unverified, partial or unavailable rather than guessing or claiming success.
