# Tools to add or strengthen (November 2026)

What Tribos has today: 59 registered tools (21 SymPy math tools, 8 SciPy simulation tools, sandboxed Python and
SageMath, Lean 4 with Mathlib, OEIS, Wolfram, units and constants, materials and standards, scholarly and web search),
plus the plot stage (matplotlib in the sandbox) and the task plan (one step per part of the question, each with its
tool). This note ranks what to add next by value for a STEM research assistant and by effort.

## Ranked candidates

| # | Tool | What it adds | Plugs in as | Effort | Value |
|---|------|--------------|-------------|--------|-------|
| 1 | **Plot as a registry tool** | The plan-and-execute planner can call plotting like any other tool, several times per question (one figure per part) | `plot_matplotlib` executor wrapping `plot_stage` | S | High |
| 2 | **Z3 (SMT solver, `z3-solver`)** | Decides integer, real and bit-vector constraints: proves an inequality or finds a counterexample in milliseconds; checks "for all n ≤ N" claims exactly. The model writes constraints, Z3 checks them, errors go back for repair (the solver-in-the-loop pattern of arXiv:2412.06512) | `axiom_smt_check` tool; a task-plan step for "prove/disprove" over integers or finite domains | M | High |
| 3 | **Interactive figures (Plotly)** | Zoom, hover values, sliders for parameters; the plot stage emits Plotly JSON next to the PNG. The generate–execute–repair loop is the same one plotly-agent and similar projects use | plot stage option; `PlotArtifact` renders the JSON | M | High (the interactive simulations asked for earlier) |
| 4 | **LeanSearch (natural-language Mathlib search)** | Finds the Mathlib lemmas a proof needs from a plain-English description; Tribos already queries Loogle (structural search) for premise hints. LeanSearch v2 reports 46% of the needed premise groups in its top 10 on research-level theorems | second premise source in `tribos/verify/formal/premises.py` | S | Medium–high for Lean steps |
| 5 | **NetworkX** | Graph theory questions (shortest paths, colourings, spanning trees, flows, isomorphism) computed exactly instead of reasoned | `axiom_graph` tool; allow `networkx` in the sandbox | S | Medium |
| 6 | **CVXPY** | Convex optimisation with certified optimality (duality gap), beside the existing `axiom_optimize`/`dynamis_optimize` | `dynamis_convex_optimize` tool | M | Medium |
| 7 | **Manim animations** | Animated explanations (a geometric construction, a wave evolving). Research systems (Manimator, ICML 2025; LLM2Manim) work, but code errors are common and rendering takes minutes to hours | background job producing an MP4 file | L | Low for now |

S = under a day, M = a few days, L = a week or more.

## Orchestration improvements (same goal: many tools per question)

1. **Done:** task plan (parts → tools → checklist → answer in plan order), plot stage, Python session and plot running
   at the same time.
2. **Next:** run every independent step of the plan concurrently (the mathematics agent, Lean, simulation and
   literature search are still sequential stages), and let a failed step retry once with its error, as the plot stage
   does.
3. **Next:** a plan step can name a specific tool (`plot_matplotlib`, `axiom_smt_check`, `axiom_formal_check`) so the
   direct workflow calls it without going through the planner model.

## Sources

- ToRA, tool-integrated reasoning with Python/SymPy (ICLR 2024): https://www.microsoft.com/en-us/research/?p=1016043
- InternLM-Math (Lean generation and step provers): https://github.com/internlm/InternLM-Math
- LLMs and formal methods roadmap, solver-in-the-loop (arXiv:2412.06512): https://arxiv.org/pdf/2412.06512
- Z3 as an LLM tool (GenAIScript): https://microsoft.github.io/genaiscript/reference/scripts/z3
- LeanSearch v2, global premise retrieval: https://chatpaper.com/paper/280424
- Lean LSP MCP (LeanSearch, Loogle, premise search wrappers): https://mcpservers.org/servers/oOo0oOo/lean-lsp-mcp
- Manimator (ICML 2025): https://arxiv.org/abs/2507.14306
- PhysicsSolutionAgent, multimodal explanations: https://arxiv.org/pdf/2601.13453
- plotly-agent (generate, execute, repair): https://pypi.org/project/plotly-agent
