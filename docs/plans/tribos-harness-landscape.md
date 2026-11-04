# Open-source math and science agent harnesses: what Tribos is missing

Research brief, 31 October 2026. It compares Tribos with the open systems closest to it and lists what to take from each.
Companion to [tribos-research-upgrade-plan.md](tribos-research-upgrade-plan.md); item numbers there are referred to as
"plan item N".

## Implementation status (31 October 2026)

Items refer to the table in section 4.

| # | Status | Where |
|---|---|---|
| 1 | **Done.** Lean 4.35 with Mathlib v4.35.0 at `X:/lean/mathlib_project` (prebuilt cache; about 7 GB). The full `import Mathlib` does not fit in this machine's free memory, so a bare `import Mathlib` is replaced by a tested set of modules (about 20 s per check); `TRIBOS_LEAN_FULL_MATHLIB` turns that off. Tested with an 8–16 GB pagefile: the full import was still loading after 10 minutes at 7.4 GB, so it needs more RAM, not more swap. A timeout now kills `lake` and the `lean` child it starts (before, the orphaned `lean` kept the check waiting and held the memory). Live check: 3 of 3 eval problems verified by the kernel, including a "find all roots" problem. | [runner.py](../../tribos/verify/formal/runner.py), `.env` |
| 2 | **Done.** On Lean errors naming unknown lemmas, Loogle is searched and the real Mathlib names go back with the errors. | [premises.py](../../tribos/verify/formal/premises.py) |
| 3 | **Done.** When the direct proof fails: a blueprint of lemmas with `sorry`, each lemma proved separately (two at a time), then the assembled file checked. | [blueprint.py](../../tribos/verify/formal/blueprint.py) |
| 4 | **Done.** Construct mode: problem library with exact scorers and published values (Golomb rulers, cap sets, no-three-in-line, Sidon sets), tournament selection, novelty rejection, independent re-scoring. | [construct.py](../../tribos/agentic/construct.py) |
| 5 | **Done.** Persistent Python session (replayed cells under the sandbox's limits) and the CodeAct loop before drafting. | [session.py](../../tribos/agentic/sandbox/session.py), [codeact.py](../../tribos/agentic/codeact.py) |
| 6 | **Done.** One or two false statements: the draft is revised; more, or a failed revision: alternative drafts. | [best_of_n.py](../../tribos/agents/orchestration/best_of_n.py) |
| 7 | **Done.** For "find / determine" questions the computed answer is handed to the prover to state and prove. | [formal_proof.py](../../tribos/agentic/formal_proof.py) |
| 8 | **Done.** 12 problems and a runner: `python scripts/eval_formal.py`. | [problems.jsonl](../../tribos/evals/formal/problems.jsonl), [eval_formal.py](../../scripts/eval_formal.py) |
| 9 | **Done for full text.** Open-access PDFs (size-capped) for top papers without arXiv HTML. The existing counter-evidence search does the contradiction check. | [engine.py](../../tribos/archivon/engine.py) |
| 10 | **Done.** stdio MCP client; servers in `TRIBOS_MCP_CLIENT_SERVERS`, tools registered as `mcp_<server>_<tool>`. | [mcp_client.py](../../tribos/tools/mcp_client.py) |
| 11 | **Done.** SKILL.md format; 7 built-in skills; `TRIBOS_SKILLS_DIR` adds your own. | [tribos/skills](../../tribos/skills) |
| 12 | **Done for 2-D Poisson.** P1/P2 finite elements (scikit-fem) with convergence orders. FEniCSx is not installed (no Windows wheels). | [pde_facts.py](../../tribos/writer/pde_facts.py) |
| 13 | **Done.** Kernel-checked theorems saved to `data/lemma_library.json` and offered in later prompts. | [premises.py](../../tribos/verify/formal/premises.py) |
| 14 | **Hook done.** `TRIBOS_LEAN_PROVER_MODEL` sends Lean attempts to another model (for example a served Goedel-Prover). Running one locally needs a GPU. | [formal_proof.py](../../tribos/agentic/formal_proof.py) |
| 15 | **Done.** Research projects: a goal runs through review → hypotheses → experiments → analysis → report, each stage one background job that sees the earlier stages. Projects survive restarts (marked interrupted, resumed at the first unfinished stage), run unattended as background jobs (a failed stage is retried once, projects interrupted by a server stop resume on their own, further projects wait in a queue; one server process drives a project even when two share the store), can be stopped, and download as a Markdown report with an appendix of every stage and the merged sources. Opened from **Research projects** in the sidebar. | [campaign.py](../../tribos/agentic/campaign.py), [campaigns.py](../../app/backend/routers/campaigns.py), [ResearchProjects.tsx](../../web/src/components/campaigns/ResearchProjects.tsx) |
| UI | **Done.** Code opens in a right-hand panel (tabs, line numbers, copy, download, Esc), from any code block, the Python session, construct mode's program and the Lean proof. | [CodePanel.tsx](../../web/src/components/CodePanel.tsx) |

## 1. The short answer

- **Mathematical strength comes from the model.** A harness cannot make a model reason better than it can. What it can
  do is give the model ways to check itself: run code, read the output, search the literature, and have Lean check a
  proof. Every system below that made real progress on open problems works this way.
- **The pattern behind the 2026 results.** The model proposes, a strict checker accepts or rejects, and the loop
  repeats.
  - [AlphaProof Nexus](https://arxiv.org/html/2605.22763v1) resolved 9 of 353 attempted Erdős problems with proofs in Lean.
    Its basic agent, which only alternated model generation with Lean checking, solved the same nine at higher compute.
    The loop matters more than special tricks.
  - [Numina-Lean-Agent](https://arxiv.org/html/2601.14027v1), a general coding agent (Claude Code with Claude Opus 4.5)
    plus Lean tools, solved Putnam 2025 12/12 with no task-specific training. This is the closest template for Tribos.
- **Where Tribos stands today.** Tribos already has the checkers for calculation: exact algebra, certified roots, sum-of-squares certificates,
  two-method simulation. It lacks the two checkers that open problems need: Lean with Mathlib (proofs) and a
  scored search loop (constructions). Coding-agent behaviour, a model that writes, runs and fixes code step by step, is
  also only partly there.

## 2. The systems that matter

### A. Formal proving in Lean

| System | What it is | Open? | What to take |
|---|---|---|---|
| [Numina-Lean-Agent](https://arxiv.org/html/2601.14027v1) | Claude Code + Numina-Lean-MCP (Lean LSP, theorem retrieval, informal prover); Putnam 2025 12/12 | Yes (project-numina/numina-lean-agent) | The whole loop: write Lean, read goals and errors, search Mathlib, patch |
| [lean-lsp-mcp](https://mcpservers.org/servers/oOo0oOo/lean-lsp-mcp) | MCP server giving an agent Lean diagnostics, goals, hover, and search (leansearch, loogle, Lean Finder, state search, hammer premises) | Yes (`uvx lean-lsp-mcp`) | Use as-is: the agent's interface to Lean |
| [LeanExplore](https://arxiv.org/pdf/2506.11085) | Search engine for Lean 4 declarations, with an MCP server | Yes | Premise search: find the Mathlib lemma a step needs |
| [Kimina Lean Server](https://neurips.cc/virtual/2025/131063) | Parallel Lean REPL workers, import cache, batch verify | Yes (`kimina-ast-server` on PyPI) | Fast batch checking of many candidate proofs |
| [Goedel-Architect](https://arxiv.org/pdf/2606.06468) | Blueprint: lemma dependency graph, parallel provers per lemma, graph revised when a lemma fails; 99.2% miniF2F, 75.6% PutnamBench, reported ~$294 | Paper; code release unconfirmed | Blueprint decomposition for long proofs |
| [Discover and Prove](https://arxiv.org/pdf/2604.15839) | Find the answer informally first, rewrite the statement with that answer, then prove it ("Hard Mode") | Yes (liuchengwucn/discover-and-prove) | Discover-then-prove for "find all / determine" questions |
| [Goedel-Prover-V2](https://github.com/Goedel-LM/Goedel-Prover), DeepSeek-Prover-V2, Kimina-Prover, [Seed-Prover](https://arxiv.org/pdf/2512.17260) | Open-weight Lean prover models | Weights open | Optional: a cheap specialised prover per lemma (needs a GPU) |

### B. Discovery: search for better constructions

| System | What it is | Open? | What to take |
|---|---|---|---|
| [OpenEvolve](https://pypi.org/p/openevolve) | Open reimplementation of AlphaEvolve: program database, islands, LLM mutations, evaluator cascade | Yes (Apache 2.0 per listings) | Construct mode (plan item 12): wrap Calcula as its evaluator |
| [ShinkaEvolve](https://alephvc.notion.site/ShinkaEvolve-Evolving-New-Algorithms-with-LLMs-Orders-of-Magnitude-More-Efficiently-27908a4d40668156bdf4c289b45c273d) (Sakana AI) | Sample-efficient evolution (novelty rejection, adaptive parent selection); reports beating AlphaEvolve's circle packing in 150 generations | Yes (Apache 2.0) | Its sample-efficiency tricks keep token cost down |
| [AlphaProof Nexus](https://arxiv.org/html/2605.22763v1) (DeepMind) | Model + Lean proof search on Erdős problems and OEIS conjectures | Results open (google-deepmind/alphaproof-nexus-results); system closed | The evidence that a plain generate-and-check loop works |
| [Aletheia](https://arxiv.org/html/2602.10177v3) (DeepMind) | Generator, Verifier, Reviser loop: correct → output; minor flaw → revise; critical flaw → regenerate; search cuts citation hallucination | Closed; architecture published | The three-way verifier decision for informal proofs |

### C. Tool-integrated math reasoning (the model writes and runs code while reasoning)

| System | What it is | Open? | What to take |
|---|---|---|---|
| [NeMo-Skills / OpenMath-Nemotron](https://arxiv.org/pdf/2504.16891) (NVIDIA) | AIMO-2 winner: chain-of-thought, tool-integrated reasoning (code inside the reasoning) and GenSelect (pick the best of N solutions) | Yes ([docs](https://nvidia.github.io/NeMo-Skills/agentic_inference/tool_calling)) | The tool-calling loop with a code sandbox; GenSelect for best-of-N |
| [AgentMath](https://openreview.net/pdf/167c6240e7f2352d885ac5fa16f70f3ef8b7f499.pdf) | Agent that interleaves reasoning and code execution (ICLR 2026) | Paper | Same pattern |
| [OpenHands](https://www.openhands.dev/blog/openhands-codeact-21-an-open-state-of-the-art-software-development-agent) | Coding agent: CodeAct (each step is code run in a Docker sandbox; the output is the next observation), bash + IPython + browser | Yes (MIT) | A persistent Python kernel the model drives step by step |

### D. Scientific research harnesses

| System | What it is | Open? | What to take |
|---|---|---|---|
| [PaperQA2](https://arxiv.org/html/2409.13740v2) (FutureHouse) | Agentic retrieval over full-text papers; checks claims against the literature for contradictions (70% of found contradictions confirmed by experts) | Yes (licence listed inconsistently; check) | Full-text PDFs, not only arXiv HTML; claim-vs-literature contradiction search |
| [AI-Scientist-v3](https://arxiv.org/pdf/2610.18933) (Sakana), Agent Laboratory, [Co-Scientist reimplementation](https://github.com/Kaimen-Inc/Co-Scientist/wiki) | Idea → experiment → paper; co-scientist hypothesis tournaments | Yes | Long-running project mode (low priority for Tribos) |
| [K-Dense scientific-agent-skills](https://github.com/k-dense-ai/scientific-agent-skills) | 177 science skills, 100+ databases (biology, chemistry, medicine) as agent skills | Yes | A skills format for adding domains without new code paths |
| [PDE-Agents](https://arxiv.org/html/2606.07850), [AutoPDE](https://arxiv.org/pdf/2606.10752) | FEniCSx finite-element agents; explicit solver-strategy library | PDE-Agents yes (MatPro-IFE/pde-agents) | PDEs beyond the 1-D heat equation |

### E. Problem sets and benchmarks

| Source | Use for Tribos |
|---|---|
| [Formal Conjectures](https://arxiv.org/abs/2605.13171) (DeepMind, open) | 2,615 problems stated in Lean, 1,029 of them open conjectures: the target list for the proof loop and for construct mode |
| Erdős problems, OEIS conjectures | Where 2026 systems found real results; each comes with a checkable statement |
| miniF2F, PutnamBench, MiniF2F-Hard / FIMO-Hard ([DAP](https://arxiv.org/pdf/2604.15839)) | Regression suites for the Lean loop |

## 3. What Tribos already has

So the gap list below is fair:

- **Verified computation:** Axiom (SymPy, SageMath, a strategy ladder with independent checks); certified roots
  (Arb); exact sum-of-squares certificates; dynamical systems integrated by two methods with invariants and energy
  balance; heat-equation convergence; number theory.
- **Code execution:** Calcula, a sandboxed Python runner (process or container backend), and plan-and-execute with
  model-written scripts.
- **Literature:** Archivon (arXiv, Semantic Scholar, OpenAlex, Crossref, zbMATH, NASA ADS) with arXiv full text, plus
  web search.
- **Checking answers:** math-statement auditor, NLI claim checks, counter-evidence search, gap-filling retrieval,
  best-of-N drafting, debate, swarm and supervisor topologies.
- **Lean:** a runner with a kernel audit that rejects `sorry`, new axioms, `native_decide` and `unsafe`. Lean is not
  installed and Mathlib is missing.
- **Infrastructure:** project memory, plan approval, budgets, an MCP and A2A *server* endpoint, and eval suites (69
  cases: behaviour, engineering, golden, math, physics, stem).

## 4. What is missing, by priority

| # | Missing | Who has it | What to take | Effort | Priority |
|---|---|---|---|---|---|
| 1 | Lean 4 + Mathlib installed, and Lean errors and goals fed back to the model | Numina-Lean-Agent, lean-lsp-mcp, Kimina server | Install the toolchain; run lean-lsp-mcp or the Kimina server; give the model `check`, `goals` and `search` tools | 2–3 d + about 6–10 GB disk (**your decision**) | Highest |
| 2 | An agentic proof loop: write Lean → compile → read error → patch, with premise search | Numina-Lean-Agent, LeanExplore | The loop and its prompts; leansearch / loogle / LeanExplore as tools | 4–6 d | Highest |
| 3 | Blueprint decomposition: lemma graph, parallel per-lemma provers, revise the graph on failure | Goedel-Architect | The design (code release unconfirmed) | 5–7 d | High |
| 4 | Construct mode: evolutionary program search with an exact scorer | OpenEvolve, ShinkaEvolve | `pip install openevolve`; Calcula as the evaluator; novelty rejection from ShinkaEvolve | 4–6 d | High |
| 5 | A persistent Python kernel the model drives turn by turn (CodeAct / tool-integrated reasoning) | OpenHands, NeMo-Skills | A stateful IPython session in the sandbox; each code cell's output becomes the next observation | 3–5 d | High |
| 6 | Generator–Verifier–Reviser loop for informal proofs (correct / minor fix / regenerate) | Aletheia | Extend best-of-N: a minor flaw is revised, a critical flaw regenerates the draft | 2–3 d | Medium-high |
| 7 | Discover-then-prove for "find all / determine" questions | Discover and Prove | Informal answer, rewrite the statement with it, then the Lean loop | 2–3 d after #2 | Medium |
| 8 | An open-problem eval: a frozen subset of Formal Conjectures plus miniF2F / PutnamBench | Formal Conjectures, DAP | Add a `formal` eval suite; a measured score instead of impressions | 2 d | Medium-high |
| 9 | Full-text PDFs and claim-vs-literature contradiction search | PaperQA2 | PDF parsing for non-arXiv papers; its contradiction mode as a check | 3–4 d | Medium |
| 10 | MCP *client*: consume outside tool servers (Lean, LeanExplore, science databases) | Claude Code, Numina | An MCP client in the tool registry, gated by the existing approval layer | 2–3 d | Medium |
| 11 | A skills library for other sciences (chemistry, biology databases) | K-Dense skills | The skills format and selected skills | 3 d + per skill | Medium |
| 12 | PDEs beyond 1-D heat: finite elements, solver-strategy library | PDE-Agents, AutoPDE | A FEniCSx backend in the sandbox; strategy cards | 5–8 d | Medium |
| 13 | A lemma library that grows across runs (proved lemmas reused) | Seed-Prover 1.5 ("learning from experience") | Store kernel-checked lemmas in project memory; retrieve them as premises | 2–3 d after #2 | Medium |
| 14 | Open-weight prover models as cheap per-lemma workers | Goedel-Prover-V2, DeepSeek-Prover-V2 | Optional local inference | Needs a GPU | Low |
| 15 | Long-running research project mode (idea → experiments → paper) | AI-Scientist-v3, Agent Laboratory | Job-based multi-day runs | Large | Low |

## 5. Suggested order

1. **Proofs:** #1, #2, then #8 to measure. This is the step that lets Tribos claim proofs at all. It needs your
   go-ahead for the disk space.
2. **Coding-agent maths:** #5, then #4. A persistent kernel makes the model work like a coding agent, and construct
   mode turns that into search on open problems with a score.
3. **Proof quality:** #6, #3, #7, #13.
4. **Breadth:** #9, #10, #11, #12.

## 6. Realistic expectations

- **Erdős-scale results are reachable, not deep conjectures.** The 2026 open-problem results are mostly Erdős and OEIS
  problems: short statements, checkable answers. Nothing has settled a problem of the Navier–Stokes kind.
- **Cost depends on decomposition.**
  - Goedel-Architect reports 75.6% on PutnamBench for about $294.
  - A secondary report puts Hilbert at 70.0% for about $170,000. That figure is unverified.
  - Splitting proofs into lemmas, and searching sample-efficiently, is what keeps token use reasonable.
- **Keep the honesty rule.** Nothing is "solved" without Lean's kernel or an exact scorer. Aletheia's authors note that
  search cut invented citations, but subtler misreadings of real papers remained. Human review of anything claimed as
  new stays necessary.

## 7. Reusing their code

Prefer installing and calling these tools over copying source. Licences reported in listings and still to be
confirmed in each repository's LICENSE file:

- OpenEvolve: Apache 2.0
- ShinkaEvolve: Apache 2.0
- OpenHands: MIT
- Goedel-Prover-V2: Apache 2.0
- DeepSeek-Prover-V2: MIT
- PaperQA2: MIT or Apache 2.0 (sources disagree)

The Aletheia paper is CC BY-NC-ND, so take the idea, not text or code.

## Sources

- AlphaProof Nexus: [arXiv 2605.22763](https://arxiv.org/html/2605.22763v1), [WinBuzzer](https://winbuzzer.com/2026/05/26/google-deepmind-says-alphaproof-nexus-is-still-not-agi-xcxwbn/)
- Numina-Lean-Agent: [arXiv 2601.14027](https://arxiv.org/html/2601.14027v1), [ICML 2026](https://icml.cc/virtual/2026/poster/66755)
- lean-lsp-mcp: [mcpservers.org](https://mcpservers.org/servers/oOo0oOo/lean-lsp-mcp); LeanExplore: [arXiv 2506.11085](https://arxiv.org/pdf/2506.11085); LeanSearch v2: [catalyzex](https://www.catalyzex.com/paper/leansearch-v2-global-premise-retrieval-for)
- Kimina Lean Server: [NeurIPS 2025](https://neurips.cc/virtual/2025/131063), [PyPI](https://pypi.org/project/kimina-ast-server/2.1.2/)
- Goedel-Architect: [arXiv 2606.06468](https://arxiv.org/pdf/2606.06468); Goedel-Prover: [GitHub](https://github.com/Goedel-LM/Goedel-Prover)
- Discover and Prove: [arXiv 2604.15839](https://arxiv.org/pdf/2604.15839), [alphaxiv](https://www.alphaxiv.org/abs/2604.15839)
- Seed-Prover 1.5: [arXiv 2512.17260](https://arxiv.org/pdf/2512.17260); prover list: [open-weight-models](https://github.com/xigh/open-weight-models)
- OpenEvolve: [PyPI](https://pypi.org/p/openevolve); ShinkaEvolve: [Aleph summary](https://alephvc.notion.site/ShinkaEvolve-Evolving-New-Algorithms-with-LLMs-Orders-of-Magnitude-More-Efficiently-27908a4d40668156bdf4c289b45c273d)
- Aletheia: [arXiv 2602.10177](https://arxiv.org/html/2602.10177v3), [DeepMind blog](https://deepmind.google/blog/accelerating-mathematical-and-scientific-discovery-with-gemini-deep-think/)
- NeMo-Skills / OpenMath: [arXiv 2504.16891](https://arxiv.org/pdf/2504.16891), [docs](https://nvidia.github.io/NeMo-Skills/agentic_inference/tool_calling); AgentMath: [OpenReview](https://openreview.net/pdf/167c6240e7f2352d885ac5fa16f70f3ef8b7f499.pdf)
- OpenHands: [CodeAct 2.1](https://www.openhands.dev/blog/openhands-codeact-21-an-open-state-of-the-art-software-development-agent)
- PaperQA2: [arXiv 2409.13740](https://arxiv.org/html/2409.13740v2)
- AI-Scientist-v3: [arXiv 2610.18933](https://arxiv.org/pdf/2610.18933); Co-Scientist: [Kaimen-Inc](https://github.com/Kaimen-Inc/Co-Scientist/wiki); research tools list: [Awesome-Auto-Research-Tools](https://github.com/handsome-rich/Awesome-Auto-Research-Tools/wiki)
- K-Dense skills: [GitHub](https://github.com/k-dense-ai/scientific-agent-skills); AIPOCH open-science: [GitHub](https://github.com/aipoch/open-science)
- PDE-Agents: [arXiv 2606.07850](https://arxiv.org/html/2606.07850); AutoPDE: [arXiv 2606.10752](https://arxiv.org/pdf/2606.10752)
- Formal Conjectures: [arXiv 2605.13171](https://arxiv.org/abs/2605.13171)

Several figures (star counts, the Hilbert cost, some licences) come from secondary listings and are marked as such
above.
