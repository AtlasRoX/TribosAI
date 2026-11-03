# Pushing Tribos further: a research-based upgrade plan

*Prepared 31 October 2026. Every claim about outside work cites its source; numbers marked "reported" come from
preprints or leaderboards and have not been reproduced here.*

## Status (updated 31 October 2026)

| # | Item | Status | Where |
|---|---|---|---|
| 1 | `stem` eval suite | **Done.** 11 cases: 7 live questions and 4 challenge questions, each with gold values and time limits | [tribos/evals/data/stem.jsonl](../../tribos/evals/data/stem.jsonl) |
| 2 | Simulation intent verification | **Done for stated and named systems.** The equations integrated are parsed from the question and shown; code runs them, not a model-written script. Model-written scripts for unparsed systems are not yet checked against the question's equations. | [system_facts.py](../../tribos/writer/system_facts.py) |
| 3 | Declared-system simulator | **Done** (live run: Robertson, completed in 37 s). See the note below the table. | [system_facts.py](../../tribos/writer/system_facts.py) |
| 4 | Replace debate escalation | **Done.** Debate fires only on contradicting passages or safety-critical questions; the weak triggers are behind `TRIBOS_ESCALATE_ON_WEAK_SIGNALS`. When the math auditor finds a false statement in a first draft that code did not compute, 2 alternatives (4 at ultra or max effort) are drafted in parallel, each is audited, and the draft with the fewest false statements is kept. | [router.py](../../tribos/agentic/router.py), [best_of_n.py](../../tribos/agents/orchestration/best_of_n.py) |
| 5 | Certified roots | **Done.** python-flint (Arb) ball enclosures prove every reported digit, for example Wilkinson's degree-20 polynomial to 30 digits in 0.4 s. | [roots_facts.py](../../tribos/writer/roots_facts.py) |
| 6 | Lean | **Done in part.** The kernel audit now also rejects `native_decide`, `implemented_by`, `@[extern]` and `unsafe`; validity and statement faithfulness are reported separately. Mathlib v4.35.0 is installed (`X:/lean/mathlib_project`, checked through `lake env lean`), with Loogle lemma search, blueprint proving and a lemma library ([tribos-harness-landscape.md](tribos-harness-landscape.md)). Back-translation by a second model family is not built yet. | [runner.py](../../tribos/verify/formal/runner.py) |
| 7 | Exact SOS certificates | **Done.** Gram-matrix SDP (cvxpy, Clarabel), rational rounding with exact projection, exact LDLᵀ PSD proof and a symbolic identity check (live run: section 4's challenge polynomial). | [poly_facts.py](../../tribos/writer/poly_facts.py) |
| 10 | PDE module | **Done for the 1-D heat equation:** manufactured sine solution, Crank–Nicolson and FTCS on five grids, observed order 2.000. Other PDEs are not covered yet. | [pde_facts.py](../../tribos/writer/pde_facts.py) |
| 8 | Calibration | **Tooling done; fitting waits on labels.** Saved runs export to rows a person labels; `calibrate_confidence.py` refuses to fit until about 300 real claims are labelled. | [export_claims_for_labelling.py](../../scripts/export_claims_for_labelling.py) |
| 9 | Full-text verification | **Done for arXiv.** Body paragraphs of the top 3 arXiv hits (arxiv.org/html) are added as "Full text" passages, ranked by overlap with the query (live: 3 paragraphs in 2.5 s). Setting: `TRIBOS_ARCHIVON_FULLTEXT`. Non-arXiv PDFs are not read. | [engine.py](../../tribos/archivon/engine.py) |
| 11–15 | Later items | **Open.** Quarter-scale work | — |

*Item 3 in detail.* Each run:

- parses stated `dx/dt = …` systems, or a named system (Lorenz, Robertson, Van der Pol, Lotka–Volterra);
- detects stiffness from the Jacobian;
- runs two tolerances plus a second method;
- finds linear invariants symbolically;
- flags chaotic systems.

*Section 4 challenge questions:*

| Challenge | Status |
|---|---|
| 2 (SOS), 4 (Robertson), 5 (heat equation), 6 (Wilkinson) | Handled by code |
| 1 (Lean over ℝ) | Mathlib installed; statements over ℝ are formalised and kernel-checked (live: 3 of 3 eval problems) |
| 3 (damped double pendulum) | Handled by code: equations derived from the Lagrangian with SymPy; the energy lost matches the damping work to 4·10⁻¹¹ |
| 7 (construction search) | Item 12 |

## 1. Where Tribos stands

What already works, confirmed on live runs in October 2026:

- **Code computes, the model writes.** For several problem classes the numbers come from Python, each checked a
  second way, before the model drafts anything. Each class below names the module, what it computes, and the
  question that confirmed it:
  - [writer/facts.py](../../tribos/writer/facts.py): ODE initial-value problems. Live: forced resonance, critically
    damped oscillator.
  - [number_facts.py](../../tribos/writer/number_facts.py): finite number theory. Live: Collatz and Goldbach
    to 100,000.
  - [nbody_facts.py](../../tribos/writer/nbody_facts.py): gravitational N-body runs with two integrators. Live:
    three-body figure-eight.
  - [poly_facts.py](../../tribos/writer/poly_facts.py): polynomial nonnegativity and sums of squares. Live: Motzkin
    polynomial.
  - [roots_facts.py](../../tribos/writer/roots_facts.py): exact real-root isolation. Live: x⁵ − 5x + 1 with a Sturm
    sequence.
- **Every sentence is audited.** The math-claims auditor re-evaluates written equalities, the verifier checks
  literature claims against retrieved passages, and the deliverables check confirms each requested item was
  answered.
- **Honest limits.** Open problems are labelled open, finite checks are labelled evidence, and Lean is skipped with
  a reason when Mathlib is missing.

What limits it today, seen on the same runs:

| Limit | Seen in | Consequence |
|---|---|---|
| A problem class without a code module falls back to model reasoning plus a model-written tool plan | x⁵ − 5x + 1 before roots_facts: 94 s plan, two scripts crashing | Slow; values not checked by code |
| Lean has no Mathlib | Motzkin, quintic: "needs real numbers, requires Mathlib" | No formal proof for any statement over ℝ |
| Numerics are floating point | Root intervals, N-body drift | Results are high-precision, not certified (no interval enclosures) |
| Sums of squares are decided only by the Newton-polytope test | Motzkin works; a polynomial that *is* SOS gets "not decided" | Cannot exhibit a certificate |
| The critic debate costs 36–48 s per run | Several runs | Little evidence it adds accuracy (section 2.3) |
| Evaluation suites are clinical and behavioural | [docs/evals.md](../evals.md) | No regression measure for maths, physics or simulation |
| Claim confidence is not calibrated on Tribos's own runs | "Confidence: moderate (set by the automatic checks)" | Bands are heuristics, not guarantees |

## 2. What the research says, area by area

Each area gives the evidence, what Tribos has, and the upgrade it suggests.

### 2.1 Formal proof in Lean 4

**Evidence**

- **miniF2F is effectively saturated** ([summary](https://www.cs.virginia.edu/~rmw7my/Courses/AgenticAISpring2026/Major%20Breakthroughs%20in%20Lean%204-Based%20Auto-Formalized%20Mathematics.html)):
  - an agentic framework, HILBERT, is reported at 99.2%;
  - Seed-Prover is reported at 99.6%.
- **PutnamBench is the current frontier.** HILBERT is reported at 462 of 660 problems (70%) with a large model budget
  ([PutnamBench paper](https://arxiv.org/pdf/2407.11214), [Goedel-Prover](https://arxiv.org/pdf/2502.07640)).
- **General frontier models are now competitive with dedicated provers.** One 2026 evaluation finds this once
  prompts are standardised, and warns that prover scores depend heavily on prompt and sampling budget
  ([Evaluation of LLMs for formalization](https://arxiv.org/html/2606.05632v1)).
- **Compiling is not faithfulness.** A Lean statement can compile while dropping a hypothesis, changing the domain,
  or weakening the conclusion
  ([Beyond Compilation](https://arxiv.org/html/2606.31002v4)). The same paper:
  - requires compilation plus agreement of two judges from different model families;
  - recommends reporting validity and faithfulness separately.
- **Back-translation catches misformalisation.** An agent translates the Lean statement back to prose and compares it
  with the source, catching errors such as "for all primes n > 1" that lets n = 1 through
  ([Beyond the Library](https://arxiv.org/html/2606.31134v1)).
- **Round-trip and repair loops** are an active line of work ([Roundtrip Verification and Repair](https://arxiv.org/pdf/2604.25031),
  [FormalRx](https://arxiv.org/pdf/2607.04655)).
- **Compiler feedback helps.** Feeding compiler output back to the prover improves it
  ([Compile to Compress](https://arxiv.org/pdf/2604.18587)).
- **Draft-sketch-prove is effective again** with reasoning models ([Reviving DSP](https://arxiv.org/pdf/2506.11487)).
- **Proof search needs kernel-level auditing** to stop reward hacking ([Reward-Oracle MCTS](https://arxiv.org/pdf/2608.28639)).
- **Infrastructure:**
  - [Kimina Lean Server](https://github.com/Sequential-Intelligence-Lab/kimina-lean-server) runs many Lean REPLs in
    parallel, with Mathlib import caching (a REST API, Docker, `pip install kimina-ast-server`).
  - [Pantograph](https://github.com/leanprover/Pantograph) exposes Lean proof states to programs.

**Tribos today**

- **What runs:** core Lean only; a statement-correspondence check
  ([verify/formal/correspondence.py](../../tribos/verify/formal/correspondence.py)); up to 2 repair rounds.
- **What happens without Mathlib:** any question over ℝ is now skipped, correctly.

**Upgrade**

1. **Mathlib via Kimina Lean Server**, set by `TRIBOS_LEAN_PROJECT`. It unlocks every statement over ℝ, ℂ,
   analysis and topology. Import caching matters because a cold Mathlib load takes minutes.
2. **Report validity and faithfulness separately.** A green Lean card needs:
   - compilation;
   - the existing correspondence check;
   - a back-translation judged by a second model family.

   The card shows each of the three results.
3. **Draft, sketch, prove.** The writer's informal proof becomes a Lean skeleton with `sorry` gaps. Each gap is
   closed by a prover call or `aesop`/`nlinarith`/`polyrith`, with compiler errors fed back. This matches how the
   Motzkin and Sturm answers are already structured: proved steps, then a conclusion.
4. **Kernel audit.** Reject proofs that use `sorry`, `native_decide`, new axioms or `implemented_by`. Check with
   `#print axioms`.

### 2.2 Spending more compute where it buys accuracy

**Evidence**

- **Code checking beats a bigger model.** Tool-integrated verification, where code execution checks candidate
  solutions, lets a 1B model beat an 8B one on MATH under test-time scaling
  ([T1](https://arxiv.org/html/2504.04718v2)).
- **Better step verifiers.** A generative process reward model that reasons about each step beats discriminative
  reward models in best-of-N and guided search, trained on about 8,000 step labels
  ([ThinkPRM](https://arxiv.org/pdf/2504.16828)).
- **Step-level search.** Verifier-guided search at the level of individual steps (MCTS with a step verifier) combines
  sequential and parallel scaling ([Hybrid TTS, EMNLP 2025](https://arxiv.org/pdf/2507.15512)).
- **Verification as an agent.** Treating verification as a multi-turn, tool-using agent is the newest form of this
  ([AgentV-RL](https://arxiv.org/html/2604.16004v1)).

**Tribos today**

- **One draft per run.** The auditor and verifier check that draft afterwards; nothing compares candidates.
- **The math agent:** for unparsed problems it makes several attempts with SymPy tools.

**Upgrade**

1. **Best-of-N with code verification**, for questions no code module covers:
   - draft N candidate solutions in parallel (N = 3 at medium effort, 5 at Ultra);
   - have the math auditor and Calcula check each;
   - keep the candidate with the most passed and fewest failed checks.

   The auditor already scores statements, so it can act as the verifier with no training.
2. **Step-level checking during drafting**, for long derivations: audit each display equation as it streams and
   regenerate from the first failed step instead of rewriting the whole answer. The streaming hooks exist.

### 2.3 The critic debate: keep or cut

**Evidence**

- **At equal compute, debate rarely wins.** Debate is only slightly better than self-consistency with the same number
  of responses, and worse than majority voting at an equal count
  ([Large Language Models Cannot Self-Correct Reasoning Yet](https://arxiv.org/pdf/2310.01798)).
- **Same accuracy, much higher cost.** At matched budgets debate ties or loses to self-consistency while costing about
  3.4× the tokens ([Beyond Symmetric Agents](https://arxiv.org/pdf/2609.35875)).
- **Same-model debate can hurt.** Debate among identical small models often lowers accuracy
  ([The Cost of Consensus](https://www.alphaxiv.org/abs/2605.00914)).
- **Gains need special set-ups:** different models, role design, or careful aggregation
  ([When and Why Does MAD Fail](https://arxiv.org/html/2510.20963v2)).

**Upgrade**

- **Replace debate escalation with self-consistency plus a verifier** (section 2.2). The debate currently costs 36–48 s
  per run where it fires.
- **Keep debate only for open-ended literature syntheses** where the critics use a different model family, and
  measure it against self-consistency with the eval suite (section 2.9) before keeping it.

### 2.4 Claim checking and calibrated confidence

**Evidence**

- **Atomic-claim checking is the standard.** SAFE, FActScore and MiniCheck all work this way:
  - split the answer into atomic claims;
  - check each one against evidence;
  - report precision and recall.

  Cheaper variants exist: [VeriFastScore](https://arxiv.org/pdf/2505.16973),
  [FastFact](https://aclanthology.org/2025.findings-emnlp.1295.pdf), and
  [FactBench](https://aclanthology.org/2025.acl-long.1587.pdf) for in-the-wild prompts.
- **Conformal factuality gives a statistical guarantee:**
  - calibrate a score threshold on labelled runs;
  - keep only claims above it;
  - the kept set is then correct with a chosen probability.

  Extensions cover multi-step reasoning as a graph of deductions
  ([Conformal Language Model Reasoning, ICLR 2025](https://proceedings.iclr.cc/paper_files/paper/2025/file/679fcceef65c3d855aa885bd024542c1-Paper-Conference.pdf)),
  distribution shift ([CoFact, ICLR 2026](https://iclr.cc/virtual/2026/poster/10008295)), and prompt-adaptive
  thresholds ([Adaptive Conformal Prediction](https://arxiv.org/html/2604.13991v1)).
- **The guarantee is on average.** It holds over many answers, not for each prediction
  ([scoping review](https://doi.org/10.1098/rsta.2026.0061)).

**Tribos today**

- **Per-claim statuses already exist:** supported, unsupported, contradicted, inconclusive.
- **Confidence bands are heuristic**; `load_calibration()` holds fixed weights.

**Upgrade**

1. **Calibrate on Tribos's own runs.**
   - Every saved run already stores claims with statuses.
   - Label about 300 claims (correct or incorrect) from the STEM eval suite.
   - Fit split-conformal thresholds per claim type (status, empirical, mathematical).
   - The confidence line then becomes "at least 90% of the claims shown are correct, calibrated on N labelled
     runs", instead of a heuristic band.
2. **Coherent factuality for derivations.** Treat a derivation's equations as a graph of deductions. A step built on a
   failed step is withheld, not just flagged.

### 2.5 Certified numerics

**Evidence**

- **Ball arithmetic in Python.** python-flint, which absorbed the Arb library, gives arbitrary-precision ball
  arithmetic. It already backs reproducible computer-assisted proofs whose readers re-run the verifier in Python
  ([three-body contact geometry, appendix](https://arxiv.org/pdf/2411.10885);
  [AMSI course](https://ss.amsi.org.au/validated-numerical-proofs/)).
- **Interval arithmetic costs time.** A typical interval-arithmetic run is about 8 times slower than the
  floating-point one ([ICM 2018 panel](https://arxiv.org/pdf/1809.08062)).
- **Exact sum-of-squares certificates.** A numerical semidefinite-programming solution can be rounded to an exact
  rational SOS decomposition
  ([Peyrl & Parrilo](https://www.mit.edu/%7Eparrilo/pubs/files/PeyrlParrilo-ComputingSumOfSquaresDecompositionsWithRationalCoefficients.pdf)).
  Dual approaches avoid high-precision solves
  ([rational dual certificates](https://arxiv.org/pdf/2305.19039)). Boundary cases may have no rational
  certificate.
- **Python tooling.** [SumOfSquares.py](https://pypi.org/project/SumOfSquares/) builds SOS programs on PICOS and SymPy.

**Upgrade**

1. **Interval enclosures in roots_facts:**
   - evaluate p on each isolating interval with python-flint balls;
   - certify the roots with Newton–Krawczyk, so each digit is proved, not only the sign change at the ends;
   - same cost class as now: milliseconds for degree ≤ 40.
2. **SOS certificates in poly_facts:**
   - solve the Gram-matrix SDP (cvxpy with SCS or Clarabel, both pip-installable);
   - round to rationals;
   - check `p − Σ cᵢ qᵢ² = 0` exactly in SymPy.

   A polynomial that *is* a sum of squares then gets an explicit certificate. Motzkin-type cases keep the
   Newton-polytope proof, which already works.
3. **Validated ODE enclosures** (later): Taylor-model or interval Runge–Kutta bounds for the N-body and ODE modules,
   so "return error 4.1×10⁻⁸" becomes a proved bound. python-flint has the primitives; a full validated integrator
   is substantial work (section 3, Later).

### 2.6 Simulation that solves the physics that was asked

**Evidence**

- **Use the solver as the judge.** Build the model in a loop where the simulator, not the runtime alone, decides
  physical validity; use retrieval, static analysis and solver diagnostics
  ([Agentic Scientific Simulation](https://arxiv.org/abs/2603.00214)).
- **Running is not solving.** Generated multiphysics code often runs but solves different physics. The authors check
  it against the intended governing equations ("PDE-grounded intent verification")
  ([Your Simulation Runs but Solves the Wrong Physics](https://arxiv.org/abs/2605.09360)).
- **A benchmark for solver generation.** It turns phenomena into solvers and scores execution, visual fidelity and
  physical plausibility ([WorldSolver, Oct 2026](https://arxiv.org/abs/2610.08720v1)).
- **Units are a free check.** Dimensional type-checking is a cheap, training-free layer; step-aware unit checks caught
  every wrong-unit error that answer-only checks missed ([BioDimBench, ICML 2026](https://icml.cc/virtual/2026/82501)).
  Units are also a distinct error class in physics benchmarks
  ([CMPhysBench](https://arxiv.org/pdf/2508.18124), [TPS-CalcBench](https://arxiv.org/pdf/2604.17966)).

**Tribos today**

- **Fully specified systems run by code:** ODE initial-value problems, gravitational N-body, Dynamis presets, FTCS
  heat.
- **Everything else is model-planned.** Arbitrary systems go through model-written Calcula scripts with no physics
  check.

**Upgrade**

1. **Intent verification for every simulation.** Before running a model-written script:
   - extract the governing equations the code integrates, with SymPy over its right-hand side;
   - compare them with the equations stated or derived in the question;
   - refuse to run, or flag, when they differ.

   This is the single most valuable check for "it must simulate what is asked for".
2. **A conservation and invariant library** applied to any trajectory: energy, momentum, angular momentum, mass,
   charge, the Hamiltonian, and positivity of concentrations. The N-body module proves the value: tolerance changes,
   method agreement and invariant drift turned "the simulation ran" into "the simulation is right".
3. **Generalise nbody_facts into a declared-system simulator.** The question states variables, equations,
   parameters, initial conditions and span; Tribos runs:
   - DOP853 at two tolerances;
   - a second method (symplectic for Hamiltonian systems, Radau for stiff ones);
   - the invariant checks;
   - a convergence study.

   The panel then shows phase portraits, invariants and errors. This covers most textbook mechanics, chemical
   kinetics and circuits without a model-written plan.
4. **PDEs:**
   - the method of manufactured solutions, which proves a PDE code converges at its design order;
   - refinement studies (grid convergence index, already used for ODEs);
   - dimensional type-checking of every boundary condition.

### 2.7 Discovery: search instead of one-shot answers

**Evidence**

- **AlphaEvolve.** It evolves programs scored by an evaluator and improved best-known constructions on several open
  problems ([Georgiev, Gómez-Serrano, Tao & Wagner](https://arxiv.org/html/2511.02864v1);
  [Tao's note](https://terrytao.wordpress.com/2025/11/05/mathematical-exploration-and-discovery-at-scale/)).
- **Open replications:**
  - OpenEvolve, and ShinkaEvolve, which is reported to need about 150 samples where AlphaEvolve needs thousands
    ([overview](https://www.emergentmind.com/topics/alphaevolve-paradigm));
  - [AlphaResearch](https://arxiv.org/pdf/2511.08522), [ThetaEvolve](https://arxiv.org/pdf/2511.23473) and
    [DeltaEvolve](https://arxiv.org/pdf/2602.02919).
- **Where it struggles:** bijection discovery stayed hard ([OpenEvolve study](https://arxiv.org/abs/2511.20987)).
- **Equation discovery.** On LLM-SRBench the best system reaches 31.5% symbolic accuracy across 239 problems
  ([LLM-SRBench, ICML 2025](https://arxiv.org/pdf/2504.10415)). This is a weak area for every system and a chance to
  differentiate.

**Upgrade**

1. **A "construct" mode** for questions such as "find a better packing / a counterexample / an extremal example",
   combining:
   - an evaluator written as code (checked exactly);
   - an evolution loop over candidate programs (OpenEvolve is pip-installable);
   - Tribos's existing sandbox and budget.

   The result is a certified construction plus its evaluator, not a claim.
2. **Equation discovery from uploaded data:**
   - LLM-proposed functional forms;
   - parameter fitting (Calcula);
   - cross-validated error;
   - the existing unit checks.

   Report every candidate with its fit, never only the winner. T1 in [FEATURE_ROADMAP.md](../FEATURE_ROADMAP.md),
   "Fit ODE models to uploaded data", is the natural starting point.

### 2.8 Literature

**Evidence**

- **PaperQA2** ([FutureHouse](https://arxiv.org/abs/2409.13740v2)):
  - full-text retrieval, re-ranking and citation-grounded answers;
  - 85.2% precision on LitQA2;
  - a contradiction-detection mode that found about 2.3 contradictions per biology paper, 70% confirmed by experts.

  The benchmark deliberately puts answers in paper bodies, not abstracts.
- **The open problem is verification.** A 2026 survey of AI-scientist systems names verification the main open
  problem and notes that evaluations often omit harness, cost and reproducibility
  ([Autonomous Research Agents survey](https://arxiv.org/html/2608.05179v1)).

**Tribos today**

- **What it searches:** abstract-level retrieval from arXiv, Semantic Scholar, OpenAlex, Crossref and zbMATH, with a
  relevance floor; excluded papers are now also filtered by relevance.

**Upgrade**

1. **Full text for the top-k papers.** Fetch arXiv HTML or PDF and verify claims against body passages, not
   abstracts. Most status and value claims that fail today fail because the abstract does not state them.
2. **A contradiction pass** for review-type questions: extract each retrieved paper's key claims and report where
   papers disagree.

### 2.9 Measuring it: the missing piece

**Evidence**

- **miniF2F:** saturated (section 2.1).
- **PutnamBench:** formal proof.
- **FrontierMath:** research-level numerical answers.
- **Humanity's Last Exam:** leaderboards disagree across dates and settings
  ([HLE overview](https://en.wikipedia.org/wiki/Humanity%27s_Last_Exam)).
- **SciCode:** scientific code.
- **LLM-SRBench:** equation discovery.
- **WorldSolver:** simulation.

The survey above asks that every reported result state its harness and cost.

**Upgrade**

1. **A `stem` eval suite** in `tribos.evals`, starting from this month's live questions. Each has a known answer, and
   each run records time, model calls and tokens:

   | Case | Gold answer |
   |---|---|
   | Forced resonance ODE | the exact solution, growth rate and energy balance from the saved, verified run |
   | Collatz and Goldbach to 100,000 | 77,031 / 350 / 21,933,016; 810 partitions |
   | Three-body figure-eight | E₀ = −1.287141992, return error under 10⁻⁷ |
   | Motzkin | minimisers (±1, ±1), not SOS |
   | x⁵ − 5x + 1 | 3 roots, Sturm 3 → 0, roots to 12 digits |
   | Markov equation x² + y² + z² = 3xyz | descent proof, no false contradiction |
   | Navier–Stokes status | "open", no simulation claimed |
2. **Gates per case:**
   - gold values present;
   - no contradicted claims;
   - no false "not addressed" items;
   - status "completed";
   - time under budget.

   This turns every fix in this document into a measured regression test.
3. **Public subsets** for headline numbers: 50 PutnamBench statements (once Mathlib is on), 30 LLM-SRBench problems,
   20 SciCode subproblems.

## 3. Prioritised plan

Effort is in focused engineer-days. Impact means how often it changes a real answer.

### Now (next 2–3 weeks): highest impact per day

| # | Upgrade | Section | Effort | Impact | Where |
|---|---|---|---|---|---|
| 1 | `stem` eval suite from the 7 live cases, with gold values and time budgets | 2.9 | 2–3 d | Every later change becomes measurable | `tribos/evals/` |
| 2 | Simulation intent verification (code's equations against the question's) | 2.6 | 3–4 d | Stops "ran but solved the wrong physics" | `tribos/dynamis`, `agentic/plan_execute.py` |
| 3 | Declared-system simulator (generalise nbody_facts) with invariants and two methods | 2.6 | 5–7 d | Most textbook simulations without a model-written plan | new `tribos/writer/system_facts.py` |
| 4 | Replace debate escalation with self-consistency plus auditor selection | 2.2, 2.3 | 3 d | About 40 s saved where debate fires; at least equal accuracy | `agentic/router.py`, draft stage |
| 5 | python-flint interval certification in roots_facts | 2.5 | 1–2 d | Proved digits, not just proved sign changes | `tribos/writer/roots_facts.py` |

### Next (1–2 months)

| # | Upgrade | Section | Effort |
|---|---|---|---|
| 6 | Mathlib via Kimina Lean Server; validity and faithfulness reported separately; kernel audit | 2.1 | 5–8 d plus about 10 GB disk for Mathlib |
| 7 | Exact SOS certificates (cvxpy SDP, rational rounding, exact check) | 2.5 | 3–4 d |
| 8 | Conformal calibration of claim confidence on labelled Tribos runs | 2.4 | 4–6 d plus about 1 d of labelling |
| 9 | Full-text verification for the top literature hits | 2.8 | 4–5 d |
| 10 | PDE module: manufactured solutions, refinement study, unit-checked boundaries | 2.6 | 6–8 d |

### Later (quarter-scale)

| # | Upgrade | Section |
|---|---|---|
| 11 | Draft–sketch–prove Lean pipeline with a prover model | 2.1 |
| 12 | "Construct" mode: evolutionary search over evaluator-checked programs | 2.7 |
| 13 | Equation discovery from uploaded data | 2.7 |
| 14 | Validated ODE enclosures (Taylor models) | 2.5 |
| 15 | Literature contradiction pass | 2.8 |

## 4. How to push the system yourself

These questions sit just past what Tribos covers today. Each has a checkable answer, and each one that fails points
at an item above.

1. **Formal proof (item 6):** "Prove in Lean that the Motzkin polynomial is nonnegative on ℝ²."
   - Pass when the Lean card is green *and* the statement matches.
2. **SOS certificate (item 7):** "Show x⁴ + x²y² − 2x²y + y⁴ + 1 is a sum of squares and give the decomposition."
   - Pass when an explicit decomposition is checked exactly.
3. **Intent verification (items 2–3):** "Simulate a damped double pendulum (m = 1, l = 1, b = 0.1) from θ = (π/2, π/2)
   for 20 s; report energy loss against the damping work."
   - Pass when energy loss equals the damping work, and two methods and two tolerances agree.
4. **Stiff kinetics (item 3):** "Integrate the Robertson stiff chemistry problem to t = 10¹¹."
   - Pass when a stiff solver is chosen, mass is conserved and the reference values match.
5. **PDE (item 10):** "Solve u_t = u_xx on [0, 1] with u = sin(πx), and show second-order convergence."
   - Pass when the observed order is near 2 under refinement.
6. **Certified roots (item 5):** "Isolate the roots of Wilkinson's polynomial of degree 20 to 30 digits."
   - Pass when the roots are certified despite ill-conditioning.
7. **Construction (item 12):** "Find 26 points in the unit square with the largest minimum distance."
   - Pass when the construction is checked and its evaluator is shown.

Run each twice: once at Medium and once at Ultra effort. Record time and status, and add each case to the `stem` suite
once it passes.

## 5. Sources

**Formal proof**

- [Goedel-Prover](https://arxiv.org/pdf/2502.07640)
- [DeepSeek-Prover](https://arxiv.org/pdf/2405.14333)
- [PutnamBench](https://arxiv.org/pdf/2407.11214)
- [Evaluation of LLMs for Mathematical Formalization in Lean](https://arxiv.org/html/2606.05632v1)
- [Lean 4 breakthroughs summary](https://www.cs.virginia.edu/~rmw7my/Courses/AgenticAISpring2026/Major%20Breakthroughs%20in%20Lean%204-Based%20Auto-Formalized%20Mathematics.html)
- [Compile to Compress](https://arxiv.org/pdf/2604.18587)
- [Reviving DSP](https://arxiv.org/pdf/2506.11487)
- [Reward-Oracle MCTS](https://arxiv.org/pdf/2608.28639)
- [Beyond Compilation](https://arxiv.org/html/2606.31002v4)
- [Beyond the Library](https://arxiv.org/html/2606.31134v1)
- [Roundtrip Verification and Repair](https://arxiv.org/pdf/2604.25031)
- [FormalRx](https://arxiv.org/pdf/2607.04655)
- [Robustness of Proof Autoformalization](https://arxiv.org/pdf/2606.14867)
- [Kimina Lean Server](https://github.com/Sequential-Intelligence-Lab/kimina-lean-server)
- [Pantograph](https://github.com/leanprover/Pantograph)

**Test-time compute and verifiers**

- [T1 tool-integrated verification](https://arxiv.org/html/2504.04718v2)
- [ThinkPRM](https://arxiv.org/pdf/2504.16828)
- [Hybrid test-time scaling](https://arxiv.org/pdf/2507.15512)
- [AgentV-RL](https://arxiv.org/html/2604.16004v1)
- [Reward model generalization](https://arxiv.org/pdf/2505.18065)
- [Awesome inference-time scaling](https://github.com/ThreeSR/Awesome-Inference-Time-Scaling)

**Debate**

- [LLMs cannot self-correct reasoning yet](https://arxiv.org/pdf/2310.01798)
- [The Cost of Consensus](https://www.alphaxiv.org/abs/2605.00914)
- [Beyond Symmetric Agents](https://arxiv.org/pdf/2609.35875)
- [When and Why Does MAD Fail](https://arxiv.org/html/2510.20963v2)
- [Single LLM Debate](https://arxiv.org/pdf/2512.23518)

**Factuality and calibration**

- [VeriFastScore](https://arxiv.org/pdf/2505.16973)
- [FastFact](https://aclanthology.org/2025.findings-emnlp.1295.pdf)
- [FactBench](https://aclanthology.org/2025.acl-long.1587.pdf)
- [Fact-checking with LLMs](https://www.arxiv.org/pdf/2601.02574)
- [Conformal LM reasoning](https://proceedings.iclr.cc/paper_files/paper/2025/file/679fcceef65c3d855aa885bd024542c1-Paper-Conference.pdf)
- [CoFact](https://iclr.cc/virtual/2026/poster/10008295)
- [Adaptive conformal factuality](https://arxiv.org/html/2604.13991v1)
- [Differentiable conformal training](https://arxiv.org/html/2604.20098)
- [Conformal prediction review](https://doi.org/10.1098/rsta.2026.0061)

**Certified numerics**

- [Three-body appendix (python-flint)](https://arxiv.org/pdf/2411.10885)
- [AMSI validated numerics](https://ss.amsi.org.au/validated-numerical-proofs/)
- [ICM 2018 machine-assisted proofs](https://arxiv.org/pdf/1809.08062)
- [Peyrl & Parrilo](https://www.mit.edu/%7Eparrilo/pubs/files/PeyrlParrilo-ComputingSumOfSquaresDecompositionsWithRationalCoefficients.pdf)
- [Rational dual SOS certificates](https://arxiv.org/pdf/2305.19039)
- [SOS bounds for dynamical systems](https://arxiv.org/pdf/1512.05599)
- [SumOfSquares.py](https://pypi.org/project/SumOfSquares/)

**Simulation and units**

- [Agentic Scientific Simulation](https://arxiv.org/abs/2603.00214)
- [PDE-grounded intent verification](https://arxiv.org/abs/2605.09360)
- [WorldSolver](https://arxiv.org/abs/2610.08720v1)
- [El Agente Forjador](https://arxiv.org/pdf/2604.14609)
- [BioDimBench](https://icml.cc/virtual/2026/82501)
- [CMPhysBench](https://arxiv.org/pdf/2508.18124)
- [TPS-CalcBench](https://arxiv.org/pdf/2604.17966)
- [DimEval](https://alphaxiv.org/benchmarks/fudan-university/dimeval)

**Discovery**

- [Mathematical exploration and discovery at scale](https://arxiv.org/html/2511.02864v1)
- [Tao on AlphaEvolve](https://terrytao.wordpress.com/2025/11/05/mathematical-exploration-and-discovery-at-scale/)
- [AlphaResearch](https://arxiv.org/pdf/2511.08522)
- [ThetaEvolve](https://arxiv.org/pdf/2511.23473)
- [DeltaEvolve](https://arxiv.org/pdf/2602.02919)
- [OpenEvolve bijections](https://arxiv.org/abs/2511.20987)
- [AlphaEvolve paradigm overview](https://www.emergentmind.com/topics/alphaevolve-paradigm)
- [LLM-SRBench](https://arxiv.org/pdf/2504.10415)

**Literature agents and evaluation**

- [PaperQA2](https://arxiv.org/abs/2409.13740v2)
- [FutureHouse WikiCrow](https://www.futurehouse.org/articles/wikicrow)
- [Autonomous Research Agents survey](https://arxiv.org/html/2608.05179v1)
- [Benchmarking AI scientists](https://arxiv.org/pdf/2607.28631)
- [Humanity's Last Exam](https://en.wikipedia.org/wiki/Humanity%27s_Last_Exam)

**Caveats.** Most 2026 items are preprints. Several figures above come from search summaries and secondary sites,
not the papers themselves. Leaderboard numbers differ by date, prompt and budget. Verify any number against the
original before quoting it outside this plan.
