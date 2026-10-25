# Designing a Mathematical Reasoning Agent: Patterns from ToRA, ReAct, RAP, Toolformer, and THOR

**Research and implementation recommendation**  
**Research checked:** 24 October 2026  
**Purpose:** Synthesize five research approaches into a practical architecture and staged roadmap for a mathematical reasoning agent that can use tools, recover from errors, and verify results.

---

## Executive recommendation

Build a **single-model, tool-using mathematical agent with structured state, independent verification, bounded recovery, and selective search**. Do not begin with a large multi-agent swarm or reinforcement learning. First build a dependable execution-and-verification loop, then train the model to use it, and only later add reinforcement learning and tree search when measurements show that they improve results.

The most reusable shared pattern across the five papers is:

> **Understand the problem → choose a next step → invoke a typed tool when useful → observe its actual result → verify the step → update the problem state → continue, repair, or backtrack.**

The papers contribute different pieces to this pattern:

- **ReAct** provides the general interaction loop of reasoning, action, and observation.
- **ToRA** shows how to train mathematical models to interleave natural-language reasoning with executable code and computational tools.
- **Toolformer** investigates how a model can learn when to call an API, what arguments to provide, and how to incorporate tool results.
- **RAP** adds explicit search over alternative reasoning paths using Monte Carlo tree search (MCTS).
- **THOR** adds policy-aligned tool-use data generation, trajectory-level and step-level optimization, and local correction after tool failures.

These methods are complementary, not interchangeable. A recommended synthesis is **ReAct for orchestration + ToRA for supervised math/tool-use training + THOR-inspired feedback and repair + Toolformer-inspired tool-selection learning + RAP-style search as an optional escalation path**. Add a separate verifier that checks mathematical validity rather than relying only on the model's confidence or the fact that code executed successfully.

This is an engineering recommendation derived from the papers, not a claim that the combined architecture has already been experimentally validated as one system.

---

## 1. Scope and interpretation

This report focuses on the five selected papers and the implementation patterns that can reasonably be extracted from them. It distinguishes the authors' published methods from recommendations for a new system.

A crucial distinction throughout this report:

- **Execution success** means the tool call ran and returned an output.
- **Mathematical correctness** means the operation and conclusion are valid for the original problem.
- **Proof validity** means the argument meets a formal proof system's rules, when formal proof is applicable.

These are different signals. A Python program can run successfully while implementing the wrong equation; a numerical answer can have a small residual without establishing uniqueness; and a plausible natural-language proof can contain an invalid inference.

The architecture should therefore capture several forms of evidence separately rather than collapse them into one `success` flag.

---

## 2. The five papers: what each one contributes

### 2.1 ToRA — mathematical tool-use behavior learned from trajectories

**Paper:** Gou et al., *ToRA: A Tool-Integrated Reasoning Agent for Mathematical Problem Solving*, ICLR 2024.  
**Primary links:** [ICLR proceedings](https://proceedings.iclr.cc/paper_files/paper/2024/hash/d3cf1559a8795eb1ed2b3ad52409ac7d-Abstract-Conference.html) · [Project page](https://microsoft.github.io/ToRA/) · [Code repository](https://github.com/microsoft/ToRA) · [arXiv](https://arxiv.org/abs/2309.17452)

**Core pattern:** interleave mathematical reasoning with code-based tool calls and use the resulting interaction trajectories as supervised training data.

The authors describe a training process with two main stages:

1. **Imitation learning:** create a tool-integrated corpus from mathematical problem datasets, then fine-tune a model to reproduce the reasoning/tool-use format.
2. **Output-space shaping:** sample varied trajectories from the imitation-trained model, retain valid trajectories, correct invalid ones with a stronger teacher model, and fine-tune on the accepted and corrected data together with the seed corpus.

The project's page describes approximately 16,000 tool-integrated annotations created with GPT-4 from the training portions of GSM8K and MATH. It reports results across ten mathematical reasoning datasets. Those numbers belong to the paper's original models, evaluation setup, decoding procedure, and benchmark versions; they should not be treated as directly comparable to results from later systems without matching the settings.

**What to borrow:**

- Use a consistent representation that interleaves reasoning summaries, tool calls, tool outputs, and subsequent steps.
- Begin with supervised fine-tuning (SFT) on high-quality, executable tool-use traces rather than starting with RL.
- Generate additional candidate trajectories, run them through a real executor and independent checks, then keep valid examples and repair suitable failures.
- Keep the actual tool output in the trajectory so the model learns to condition subsequent steps on observations rather than inventing results.

**What not to assume:** a valid execution is not necessarily a valid mathematical step. Your trajectory filter must check that code corresponds to the problem's intended calculation, that outputs satisfy the relevant constraints, and that the final answer answers the original question.

### 2.2 ReAct — an interaction pattern for agent orchestration

**Paper:** Yao et al., *ReAct: Synergizing Reasoning and Acting in Language Models*, 2022.  
**Primary links:** [arXiv](https://arxiv.org/abs/2210.03629) · [Google Research explanation](https://research.google/blog/react-synergizing-reasoning-and-acting-in-language-models/)

**Core pattern:** alternate model-generated reasoning traces with actions and observations from an external environment. Observations update the context available for future decisions.

ReAct is a general paradigm, not a specialized mathematical training recipe. It is valuable because it separates the language model's proposal from the execution environment's response. A mathematical version of the loop might propose a symbolic transformation, execute it in SymPy, inspect the returned expression, and continue based on that output.

**What to borrow:**

- Make the agent a bounded interaction loop rather than a one-shot answer generator.
- Standardize tool actions and observations.
- Preserve state and history so the next decision can respond to actual tool feedback.
- Make the control layer responsible for maximum steps, timeouts, retry limits, and stop conditions.

**What not to assume:** ReAct itself does not guarantee a correct answer, a useful tool selection policy, or recovery from loops. Those need to be built and measured separately.

### 2.3 RAP — deliberate search over alternative reasoning paths

**Paper:** Hao et al., *Reasoning with Language Model is Planning with World Model*, EMNLP 2023.  
**Primary links:** [ACL Anthology](https://aclanthology.org/2023.emnlp-main.507/) · [arXiv](https://arxiv.org/abs/2305.14992)

**Core pattern:** represent reasoning as a sequence of states and candidate actions, use a language model as both a reasoning agent and a world model for predicting possible next states, and guide exploration with MCTS and a task-specific reward.

RAP goes beyond greedily taking the next plausible step. It can build a tree of candidate reasoning paths, balance exploration against exploitation, and use evaluations of intermediate states or steps to guide search. The paper studies planning, math reasoning, and logical inference.

**What to borrow:**

- Represent a problem as a state that can be updated after a step.
- Generate multiple possible next actions when the current problem is difficult or ambiguous.
- Search the alternatives when there is a meaningful way to evaluate them.
- Escalate selectively: use more compute on problems where a simple path is failing or the cost of a wrong answer is high.

**What not to assume:** the model's predicted next state or self-evaluation score is not an oracle. The paper's reward study also shows that reward choices behave differently by task. For mathematical work, prefer verifiable task-specific checks—symbolic equivalence, substitution, constraints, residuals, or formal proof status—over uncalibrated model confidence alone.

### 2.4 Toolformer — learning where API calls belong

**Paper:** Schick et al., *Toolformer: Language Models Can Teach Themselves to Use Tools*, NeurIPS 2023.  
**Primary links:** [NeurIPS proceedings](https://proceedings.nips.cc/paper_files/paper/2023/hash/d842425e4bf79ba039352da0f658a906-Abstract-Conference.html) · [Meta AI research page](https://ai.meta.com/research/publications/toolformer-language-models-can-teach-themselves-to-use-tools/) · [arXiv](https://arxiv.org/abs/2302.04761)

**Core pattern:** use a small number of tool demonstrations to generate candidate API calls, execute the calls, filter them according to whether the results improve the model's next-token prediction, and continue training on the retained examples. The method targets decisions about whether to call a tool, which tool to call, what arguments to provide, and how to use the returned result.

Toolformer is a general language-model method rather than a mathematics-specific agent. Its distinctive contribution is learning tool-call placement and use from automatically filtered examples rather than relying exclusively on manually written rules.

**What to borrow:**

- Treat tool selection as a learnable behavior rather than hardcoding every possible case forever.
- Collect data on when a tool call materially helps, when it is unnecessary, and when it causes harm.
- Train the model to provide structured arguments and integrate returned observations.
- Start with an explicit, safe tool API; make tool routing learnable later, after enough logged examples exist.

**What not to assume:** improved next-token prediction is not the same as improved mathematical correctness. A tool call can make the continuation easier to predict without being the best action for solving a proof. Use downstream task outcomes and independent verification to measure tool-selection quality.

### 2.5 THOR — policy-aligned data, hierarchical optimization, and local repair

**Paper:** Chang et al., *THOR: Tool-Integrated Hierarchical Optimization via RL for Mathematical Reasoning*, ICLR 2026.  
**Primary links:** [ICLR proceedings](https://proceedings.iclr.cc/paper_files/paper/2026/hash/245b7f8357fdc26797ed6714cda5bd94-Abstract-Conference.html) · [arXiv](https://arxiv.org/abs/2509.13761) · [Code repository](https://github.com/JingMog/THOR)

**Core pattern:** construct tool-integrated traces that match the policy model's behavior, optimize whole-problem outcomes and selected tool-generation steps separately, and use immediate execution feedback to repair failed actions during inference.

The paper's TIRGen pipeline has an actor generate a reasoning step and a critic identify operations that can be executed as code. The critic extracts the intended logical part, converts the relevant operation to Python, runs it in a code interpreter, and feeds the observation back into the continuing trajectory. This is designed to reduce reliance on a very strong teacher for every complete trajectory and help keep generated data aligned with the actor's policy.

THOR then combines two optimization levels:

- **Trajectory-level optimization:** optimize the correctness of the final mathematical answer, using a GRPO-based objective in the paper.
- **Step-level optimization:** focus on failed code-generation steps and use execution correctness as a more localized reward. The method regenerates the suffix after a failure rather than necessarily discarding the entire history.

The inference-time correction mechanism backtracks after code invocation failure and explores alternative continuations. The paper evaluates mathematical benchmarks including MATH500, AIME 2024/2025, AMC, Minerva Math, and OlympiadBench, and reports improvements on code benchmarks as well. These are the authors' reported results under their chosen settings, not a guarantee for arbitrary models or tool environments.

**What to borrow:**

- Generate data from the model/policy you intend to improve, not only from a much stronger model with a very different style.
- Separate whole-task success from local tool-use competence.
- Store failure observations and localize retries to the broken step when earlier context remains valid.
- Distinguish failures caused by model-generated code from infrastructure, timeout, dependency, or sandbox errors.
- Add RL only after the reward signals are reliable enough to avoid teaching the model the wrong behavior.

**What not to assume:** execution correctness is a useful local signal for code generation, but it is not sufficient to verify the mathematical meaning of the computation. A wrong formula can be implemented in syntactically valid code and execute perfectly.

---

## 3. The common pattern extracted from all five

The papers can be combined into an architecture with two nested loops: an **outer problem-solving loop** and an **inner tool-execution/repair loop**. Selective planning can branch the outer loop, while training improves the policy used by both loops.

### 3.1 Shared architecture

1. **Parse and represent the problem.** Extract the exact question, variables, constraints, assumptions, target output, and domain. Preserve equations in a structured representation where possible.
2. **Maintain explicit state.** Store known facts, subgoals, chosen assumptions, results already checked, unresolved questions, and remaining budget. Do not rely solely on an undifferentiated chat transcript.
3. **Propose a next step.** The model chooses a proof step, symbolic transformation, calculation, retrieval action, numerical method, or formalization attempt.
4. **Select a tool when useful.** Apply safe routing rules initially. In a later version, learn from data when each tool is beneficial.
5. **Execute a typed action.** Send structured arguments to an isolated tool executor. Never treat generated code as automatically trusted.
6. **Observe the true result.** Append the actual output, error, return code, run time, and relevant metadata to the state.
7. **Validate the step.** Separate syntax/runtime feedback from semantic or mathematical checks.
8. **Update or repair.** If the step is invalid, preserve the confirmed prefix and regenerate a bounded suffix. If the approach itself is unproductive, switch to a different strategy.
9. **Escalate to search when necessary.** Maintain several candidate branches only for hard cases where extra compute is justified and the branch evaluator has a useful signal.
10. **Verify the final answer independently.** Stop only when the task's validation requirements are met, the budget is exhausted, or the system must report uncertainty.
11. **Log the trajectory.** Store the prompt, actions, observations, checks, outcomes, and failure labels for evaluation and future training.

### 3.2 Mapping the research to the architecture

| System component | Primary research inspiration | Role in the proposed agent |
|---|---|---|
| Think–act–observe controller | ReAct | Orchestrate each interaction with external tools. |
| Interleaved math-and-code traces | ToRA | Train the model to use computation as part of reasoning. |
| Seed SFT and accepted/corrected sample expansion | ToRA | Establish tool-use competence before RL. |
| Tool-call placement and argument selection | Toolformer | Learn when a tool call is useful and which action to choose. |
| Explicit reasoning-state tree and MCTS | RAP | Explore alternatives on difficult cases. |
| Policy-aligned actor/critic trace generation | THOR TIRGen | Generate useful tool-integrated training trajectories efficiently. |
| Task-level rewards | THOR | Improve end-to-end problem-solving performance. |
| Local tool-step rewards and suffix regeneration | THOR | Improve code generation and recover from execution errors. |
| Independent mathematical verifier | Engineering recommendation across all papers | Reduce false positives from plausible but invalid tool traces. |
| Bounded retry and compute budget | Engineering recommendation | Avoid infinite retries, excessive search, and runaway cost. |

### 3.3 The key synthesis

The most valuable combination is not to implement every technique everywhere. It is to combine the techniques in a hierarchy:

- **Always on:** structured state, ReAct-style interaction, safe typed tools, explicit stopping conditions, independent validation, and trajectory logging.
- **During initial model training:** ToRA-style supervised tool-use examples and output-space shaping, informed by THOR's policy-aligned data construction.
- **For recovery:** THOR-style localized repair, but with richer error classification than execution success/failure alone.
- **For tool routing:** begin with explicit rules; learn selection in a later phase using Toolformer-inspired data and actual task outcomes.
- **For hard problems:** use bounded candidate generation first; introduce RAP/MCTS only if ablation experiments show gains over simpler methods at a reasonable cost.
- **For training optimization:** begin with SFT and reliable filtering; investigate THOR-style step-level and trajectory-level RL after verifiers and datasets are mature.

---

## 4. Recommended architecture

### 4.1 Logical components

#### A. Problem parser and normalizer

Responsibilities:

- Preserve the problem statement verbatim.
- Extract mathematical expressions, symbols, units, constraints, known values, requested results, and expected output format.
- Detect whether the task asks for a numerical answer, derivation, proof, construction, optimization, simulation, or explanation.
- Avoid silently adding assumptions. If the statement is under-specified, mark the ambiguity in state.

For equations and symbolic expressions, represent both the source text and parsed forms. Never discard the original expression after parsing, because semantic parser mistakes can otherwise become invisible.

#### B. Solver policy / planner

The policy proposes the next move and selects among a short, explicit set of action types, for example:

- `derive_step`
- `run_symbolic_calculation`
- `run_numerical_solver`
- `run_code`
- `retrieve_theorem_or_reference`
- `formalize_or_check_proof`
- `validate_candidate`
- `revise_strategy`
- `finalize`

The policy should not directly execute arbitrary unbounded code. It submits a typed action to a controlled executor. The orchestration layer validates the schema and enforces allowed operations and budgets.

#### C. Tool executor

Start with a small, reliable tool set:

- **Python sandbox** for general calculations and small simulations.
- **SymPy** for symbolic algebra, differentiation, integration, equation solving, simplification, and exact substitutions.
- **NumPy/SciPy** for numerical computation, optimization, and numerical solvers.
- **Unit/dimensional analysis utilities** for physical and engineering quantities.
- **A theorem/reference retrieval layer** for trusted definitions, known results, and source-grounded material.
- **Lean 4/Mathlib** as an optional formal verification path for problems that can be formalized.

Do not add a tool just because it is available. Every tool should have a documented input schema, output schema, supported task range, common failure modes, timeout policy, and validation strategy.

#### D. Independent verifier

This is a required component, not an optional reviewer agent. Use the strongest affordable verifier appropriate to the problem:

| Verification level | Example check | What it can establish | What it cannot establish by itself |
|---|---|---|---|
| Level 0 — execution | Does code parse and run? | Syntax/runtime success. | Correct model of the original problem. |
| Level 1 — local semantics | Reconstruct the expression; check signs, units, dimensions, domains, and constraints. | Some common formulation errors. | Full mathematical validity in every case. |
| Level 2 — independent calculation | Substitute the candidate into the original equations; compare with a second method or solver. | Stronger evidence for numerical/algebraic answers. | A general proof or uniqueness unless the checks cover it. |
| Level 3 — proof checker | Check a Lean proof against the formalized theorem. | Formal validity of the proof of the formal statement. | That the formalized statement faithfully captures the user's intended question. |
| Level 4 — scientific/empirical assessment | Sensitivity analysis, uncertainty estimates, comparison with trusted data or experiments. | Evidence about numerical or empirical adequacy. | Universal truth beyond the assumptions and evidence. |

The verifier must preserve the distinction between a checked result and a merely plausible result. If verification is incomplete, the output should identify what was checked and what remains uncertain.

#### E. State store and trajectory recorder

Store a typed state rather than depending solely on free-form conversation:

- Original question and normalized problem representation.
- Known facts, assumptions, and constraints.
- Subgoals and their current statuses.
- Candidate strategy and branch identifier.
- Actions, arguments, tool versions, outputs, and errors.
- Validation results and their evidence.
- Retry count, search budget, and elapsed time.
- Final-answer status and unresolved limitations.

This record is required for debugging, evaluation, trace replay, dataset generation, and later training.

#### F. Search and recovery manager

Use an escalation ladder:

1. Continue the current path if each step is valid and progress is measurable.
2. Repair the local failed action if the prior state is still trusted.
3. Try a different strategy if repeated local repairs do not advance the problem.
4. Generate multiple candidates and rank them using independent checks.
5. Apply bounded tree search only for hard cases where the reward/checker can distinguish branches.
6. Stop and report uncertainty when the budget is exhausted or the task is not verifiable with available tools.

This avoids using expensive MCTS on simple arithmetic and prevents a weak self-evaluator from controlling large searches.

---

## 5. Concrete control flow

The following is a conceptual control flow, not a claim copied verbatim from any individual paper.

```text
solve(problem, budget):
    state = parse_and_initialize(problem)

    while budget remains:
        action = policy.propose_next_action(state)
        validate_action_schema(action)

        if action.requires_tool:
            observation = sandbox.execute(action)
            state = append_observation(state, action, observation)

            execution_status = classify_execution(observation)
            semantic_status = verifier.check_step(problem, state, action, observation)

            if execution_status == INFRASTRUCTURE_FAILURE:
                retry_with_infrastructure_policy_or_stop()
                continue

            if execution_status == MODEL_ACTION_FAILURE or semantic_status == INVALID:
                state = repair_or_backtrack_to_last_trusted_state(state)
                continue

        else:
            state = append_candidate_step(state, action)
            if verifier.can_check_step(action):
                state = record_check(state, verifier.check_step(problem, state))

        if strategy_is_stalled(state):
            state = change_strategy_or_escalate_to_bounded_search(state)
            continue

        if policy.proposes_final_answer(state):
            final_check = verifier.check_final_answer(problem, state)
            if final_check.is_sufficient:
                return checked_answer_with_evidence(state, final_check)

    return best_supported_partial_result_with_explicit_uncertainty(state)
```

Implementation rules:

- `INFRASTRUCTURE_FAILURE` must not be treated as evidence that the model reasoned incorrectly. For example, a timeout, unavailable package, resource limit, or broken environment is not the same as invalid code.
- A semantic check should compare the action with the original problem, not merely the last generated sentence.
- `is_sufficient` should depend on the problem class. Exact symbolic identity, residual tolerance, uniqueness, and formal theorem validity are different criteria.
- A failed candidate should not erase already verified facts. Backtracking should restore the last trusted state, not blindly restart or preserve invalid assumptions.
- Every loop, branch, retry, and code execution must be bounded.

---

## 6. Training recommendation: stage it instead of starting with RL

### Stage 0 — Establish a benchmark and a baseline

Before modifying the model, create a private, fixed evaluation set stratified by:

- Domain: arithmetic, algebra, calculus, number theory, probability, discrete mathematics, numerical methods, physics/engineering mathematics.
- Difficulty: basic, intermediate, advanced, competition/research-level where relevant.
- Task type: answer extraction, derivation, proof, construction, optimization, numerical computation, dimensional analysis.
- Tool need: no tool, symbolic tool, numerical tool, code execution, retrieval, formal verifier.

Keep evaluation questions separate from training and synthetic-data generation. Record prompt, model version, decoding settings, tool budget, verifier version, accuracy, cost, and latency. A high score on a public benchmark can be misleading if questions overlap with training data or the model has seen common solutions.

### Stage 1 — Build the deterministic tool loop

Use an existing model with a fixed ReAct-style controller. Add typed tool schemas, a sandbox, state tracking, timeouts, and the independent verifier. Do not train anything until this baseline is repeatable.

**Exit criterion:** repeated runs produce traceable outcomes, tool failures are classified correctly, and final-answer checks work on a curated validation set.

### Stage 2 — Build a ToRA-style supervised dataset

Generate or curate high-quality examples that interleave reasoning summaries, tool calls, real outputs, and validation.

A recommended record structure is:

```json
{
  "problem_id": "alg_000123",
  "problem": "Solve x^2 - 5x + 6 = 0.",
  "domain": "algebra",
  "difficulty": "basic",
  "trajectory": [
    {
      "type": "decision",
      "content": "Use symbolic solving and validate the candidate roots."
    },
    {
      "type": "tool_call",
      "tool": "sympy.solve",
      "arguments": {
        "expression": "x**2 - 5*x + 6",
        "variable": "x"
      }
    },
    {
      "type": "observation",
      "content": "[2, 3]",
      "execution_status": "success"
    },
    {
      "type": "verification",
      "method": "substitution_into_original_equation",
      "status": "pass"
    }
  ],
  "final_answer": "x = 2 or x = 3",
  "answer_status": "verified",
  "verification_evidence": ["Both roots make the original polynomial equal zero."],
  "source": "synthetic_or_human_reviewed",
  "split": "train"
}
```

This is an illustrative schema, not a record from the cited papers. In a real implementation, use structured expressions rather than strings where practical, and keep the raw problem source.

Every trajectory should preserve at least:

- The original question and answer target.
- The proposed action and tool arguments.
- The exact observed output, including errors.
- Whether the action was executable.
- Whether it was semantically appropriate for the original question.
- Whether the local result and final answer passed independent verification.
- A source/provenance label, split, license, and any transformation history.

Do not label generated data as verified merely because a teacher model approves it. Use executable checks and manual review for a subset, especially for proof and high-stakes engineering tasks.

### Stage 3 — Imitation learning and output-space shaping

Fine-tune on validated traces using SFT. Then sample candidate trajectories from the current model and categorize them:

- Correct and verified: retain as positive examples.
- Tool call incorrect but repairable: repair and verify the modified trace; retain both failure and repair metadata if useful.
- Executed correctly but solved the wrong problem: reject or label explicitly as a semantic failure.
- Final answer incorrect: reject as a positive example, but potentially retain as a labeled failure for analysis or suitable preference training.
- Infrastructure/tool environment failure: do not count it as a model failure without diagnosis.
- Unsupported or unverifiable claim: mark as uncertain, not positive.

This borrows ToRA's output-space shaping and THOR's preference for policy-aligned trajectory construction. Use deduplication and contamination checks to avoid creating many near-duplicate traces that inflate training metrics.

### Stage 4 — Add local repair examples

Build a repair dataset from real failures. Each example should include the trusted prefix, failed action, failure class, tool observation, corrected continuation, and result of independent verification.

Separate error categories because they require different behavior:

1. Syntax/import/runtime errors.
2. Invalid API schema or tool arguments.
3. Incorrect equation or formula transcription.
4. Tool result misunderstood or ignored.
5. Mathematically invalid derivation.
6. Bad strategy or dead-end exploration.
7. Verifier mismatch or ambiguous problem statement.
8. Infrastructure/resource failure.

Train the model to repair the errors it can actually diagnose. Do not let code-execution reward stand in for mathematical correctness.

### Stage 5 — Learn tool selection

Start with a rules-based router, such as using symbolic tools for exact algebra and numerical tools for approximate systems. Log each decision and its outcome. Later, train a selection model or policy using examples of:

- Tool called and materially helped.
- Tool called but was unnecessary.
- Tool called with incorrect arguments.
- A tool should have been called but was not.
- The chosen tool could not solve the problem and another tool was appropriate.

Toolformer is a useful conceptual starting point, but use task-level evaluation as the objective. The goal is not simply to make tool calls more predictable; it is to improve solution accuracy, reliability, and cost.

### Stage 6 — Consider reinforcement learning

Only move to THOR-style hierarchical RL after all of the following are true:

- The SFT model uses the tools at a useful baseline level.
- The execution environment is deterministic enough to reproduce results.
- The verifier correctly distinguishes positive and negative outcomes on a manually checked set.
- Reward components have been measured for false positives and false negatives.
- The training setup logs trajectories, policy versions, reward values, and failures.
- You have enough compute to compare RL against continued SFT and preference optimization.

Potential reward components should be recorded separately:

- Final answer correctness.
- Local code execution correctness.
- Semantic correspondence between code and intended mathematics.
- Constraint satisfaction or substitution check.
- Formal proof validity, when applicable.
- Excessive or redundant tool calls.
- Budget and latency violations.

Do not combine them into a weighted scalar until you have measured their behavior. A naive reward can encourage reward hacking—for example, short code that runs correctly but solves the wrong equation. Begin with a clear correctness hierarchy and run ablations.

### Stage 7 — Add search only when evidence supports it

First evaluate simpler alternatives:

1. One trajectory with repair.
2. Multiple independent candidates with final-answer verification.
3. Beam search over short, structured actions.
4. RAP/MCTS over a state tree.

Record accuracy per unit of compute, not accuracy alone. MCTS is worth keeping only if it improves held-out performance beyond the simpler strategies at acceptable latency and cost.

---

## 7. Reward and verification design

### 7.1 Use multi-dimensional labels before scalar rewards

A recommended initial evaluation schema has the following separate booleans or graded measures:

| Field | Question it answers |
|---|---|
| `tool_schema_valid` | Did the model produce an allowed action with valid arguments? |
| `execution_success` | Did the sandbox execute it? |
| `semantic_alignment` | Did the action encode the intended mathematical operation from the problem? |
| `local_result_valid` | Does the result pass a problem-specific check? |
| `progress_made` | Did the action reduce a subgoal or resolve an uncertainty? |
| `final_answer_correct` | Does the final response solve the original task? |
| `proof_verified` | Was the claim checked by an appropriate formal proof system? |
| `budget_compliant` | Did the agent respect runtime, call, and search limits? |

These labels can later be converted into reward functions or preferences. Keeping them separate initially makes it possible to spot reward loopholes.

### 7.2 Suggested final-verification rules by problem class

- **Algebraic equation solving:** substitute each candidate into the original equation, check domain restrictions, and check for omitted or extraneous roots.
- **Symbolic identity:** compare simplified differences or use appropriate exact symbolic checks; test values alone do not prove a general identity.
- **Numerical solving:** report residuals, tolerances, convergence status, input domain, conditioning concerns where relevant, and whether uniqueness has been established.
- **Optimization:** check constraints, feasibility, objective value, and conditions appropriate to local or global optimality.
- **Proof problems:** inspect logical dependencies; use Lean/Mathlib or another suitable proof checker for formal claims where feasible. A checker validates the formalized proposition, so validate that formalization too.
- **Physics/engineering:** check units and dimensions, conservation/constraint equations, parameter ranges, sensitivity, and solver assumptions. Numerical agreement is evidence, not automatically a proof of model validity.
- **Retrieval-dependent tasks:** preserve source references and quote only claims supported by sources. Retrieval alone does not establish a theorem or engineering result.

### 7.3 Separate correctness from confidence

The language model's self-evaluation may be one signal, especially for prioritizing candidates, but it should not override a failed independent check. RAP explores reward designs including confidence and self-evaluation and reports that the usefulness of reward combinations differs by task. That is a strong reason to treat the verifier as task-specific infrastructure rather than rely on a universal model-confidence score.

---

## 8. Search strategy: when to use RAP/MCTS

Search should be an escalation mechanism, not the default for every question.

### Recommended escalation policy

- **Easy and well-defined problems:** one solution path with deterministic validation.
- **Moderate problems:** one path plus local repair and at most a few independent candidates.
- **Hard problems with competing approaches:** generate a small number of strategies, score them using verifiable checks, and retain diverse promising candidates.
- **Very hard problems where each action has a structured state and useful reward:** evaluate RAP/MCTS.
- **Problems with no dependable verifier:** keep search shallow; many branches can amplify ungrounded model judgments.

### State design for search

Each node should include a compact structured representation of:

- Established facts and proven/verified steps.
- Current subgoal.
- Candidate next action.
- Tool observations.
- Validation status.
- Cost already spent and remaining budget.
- Parent/branch identifier.

Do not store only a long free-form solution transcript as the search state. That makes duplicate detection and equivalence checking difficult.

### Pruning rules

Prune or deprioritize a branch when:

- A trusted checker rejects a necessary step.
- The branch contradicts an established constraint.
- A tool result is semantically invalid for the requested calculation.
- The branch repeats the same failed action without a meaningful change.
- It exceeds a configured cost or depth limit.

Candidate ranking should reward verified progress and diversity, not simply longer reasoning text or a high self-reported confidence.

---

## 9. Evaluation plan: prove that each component helps

### 9.1 Baseline comparisons

Evaluate these progressively larger configurations on the same frozen test set and model version:

1. Base model, no tools.
2. Base model with a ReAct-style tool loop.
3. Same system with independent verification.
4. SFT model trained on ToRA-style tool-use traces.
5. SFT plus accepted/corrected trajectory expansion.
6. SFT plus THOR-inspired local repair.
7. Learned tool routing.
8. Multiple-candidate search.
9. RAP/MCTS, if justified.
10. RL, only once reward validity is established.

This ablation ladder is essential. If a larger architecture is better, identify which component caused the improvement.

### 9.2 Benchmarks and private evaluation

Use public datasets only as part of the evaluation suite, not as the entire evaluation strategy. The selected THOR paper evaluates MATH500, AIME 2024/2025, AMC, Minerva Math, and OlympiadBench. ToRA includes evaluations across GSM8K, MATH and other math datasets. Keep the benchmarks' own protocols and answer formats intact where possible.

Also construct a private evaluation set that tests:

- Tool errors and misleading tool outputs.
- Sign mistakes, omitted domain restrictions, false assumptions, and incorrect equation transcription.
- Problems where a tool is unnecessary as well as those where it is important.
- Problems that require switching from symbolic to numerical approaches.
- Cases where a successful program returns an answer to the wrong question.
- Cases with multiple valid solutions and cases where uniqueness matters.
- New problem statements with changed numbers, wording, and structure.
- Long solution traces where one early error must be localized and repaired.
- Out-of-distribution domains such as physics and engineering mathematics.

### 9.3 Metrics

Report at least:

- Final answer accuracy under a fixed decoding and tool budget.
- Verification pass rate and false-accept rate of the verifier.
- Tool-call precision: fraction of calls that are useful and semantically appropriate.
- Tool-call necessity/recall on problems that require a tool.
- Repair success rate after a failed action.
- Strategy-switch success rate after a stalled trajectory.
- Accuracy versus inference cost and latency.
- Number of calls, failed calls, branches, and tokens per solved problem.
- Calibration of reported confidence against actual correctness.
- Domain-level results and performance by difficulty.

Averaged accuracy can hide critical failures. Break results down by domain and error type; for engineering use cases, also report tolerances and validation criteria.

### 9.4 Leakage and reproducibility

- Keep test and validation questions out of SFT, synthetic generation, and correction prompts.
- Deduplicate exact and near-duplicate problems across splits.
- Version all model weights, tools, packages, prompts, verifiers, and benchmark data.
- Fix or report decoding temperature, number of candidates, search depth, and timeouts.
- Compare methods under matched inference budgets where possible.
- Publish failure cases and confidence intervals where sample sizes permit.

---

## 10. Engineering, safety, and operational constraints

1. **Sandbox generated code.** Enforce CPU, memory, time, filesystem, process, and network restrictions. Do not run model-generated code in the main application process or with ambient secrets.
2. **Use strict tool schemas.** Validate all arguments before execution. Return structured outputs with status, stderr, runtime, tool version, and typed result fields.
3. **Make executions reproducible.** Pin dependencies; record seeds and environment details where relevant; distinguish stochastic numerical methods from deterministic symbolic calls.
4. **Prevent runaway loops.** Set maximum tool calls, repair attempts, search depth, branches, wall time, and total tokens.
5. **Handle tool errors as data.** Preserve full error metadata and classify environment failures separately from model mistakes.
6. **Avoid prompt injection through retrieved material.** Treat retrieved pages and documents as untrusted data, never as instructions that can override the controller or tool policy.
7. **Keep provenance.** Record sources, licenses, transformations, and verification status for training data.
8. **Use least privilege.** Mathematical execution rarely needs broad filesystem or network access. Grant only the capabilities required by the selected tool.
9. **Audit final claims.** A correct numeric output does not validate every sentence in its explanation. Tie the final conclusion to checked evidence and list assumptions.
10. **Prefer graceful uncertainty to fabricated completion.** When a proof cannot be checked or a numerical method does not converge, report that explicitly.

---

## 11. Implementation roadmap and deliverables

### Phase 1 — Reliable execution baseline

**Build:** problem parser, controller loop, tool schemas, isolated executor, state store, verifier, and trace logger.  
**Read:** ReAct and the ToRA interaction format.  
**Deliverable:** working end-to-end baseline on a small hand-checked suite.  
**Gate:** reproducible traces and a measured verifier false-accept rate.

### Phase 2 — Mathematical tool-use SFT

**Build:** structured trajectory schema, generation pipeline, output filters, dataset deduplication, SFT training, and held-out evaluation.  
**Read:** ToRA in detail.  
**Deliverable:** a model that reliably formats and interprets calls to the supported mathematical tools.  
**Gate:** SFT beats the prompt-only baseline under the same tool budget without worsening severe error types.

### Phase 3 — Failure and repair learning

**Build:** typed failure taxonomy, suffix regeneration, correction examples, and per-error metrics.  
**Read:** THOR's TIRGen, step-level optimization, and self-correction sections.  
**Deliverable:** measurable improvements in repairing common code/tool failures.  
**Gate:** repair beats simple retry and full restart on held-out failures.

### Phase 4 — Tool-selection learning

**Build:** action decision logs, benefit labels, and a routing policy or fine-tuned selector.  
**Read:** Toolformer.  
**Deliverable:** fewer unnecessary calls and more successful calls when tools are needed.  
**Gate:** tool routing improves end-task accuracy or cost-adjusted success, not merely tool-call frequency.

### Phase 5 — Search and planning

**Build:** structured search states, duplicate-state detection, branch budget, heuristic scoring, and candidate verifier.  
**Read:** RAP.  
**Deliverable:** a selective search mode for hard problems.  
**Gate:** demonstrable improvement over independent candidate sampling and local repair at a controlled cost.

### Phase 6 — Reinforcement learning

**Build:** reliable reward signals, trajectory sampling, policy logging, local-step datasets, and training ablations.  
**Read:** THOR and its training setup.  
**Deliverable:** a controlled RL experiment, compared against continued SFT and preference-based baselines.  
**Gate:** improvement on untouched evaluation data, robust reward audits, and no increase in verifier false accepts.

### Suggested sequencing for a small team

Do not implement all phases in parallel. Phases 1 and 2 are the core product. Phase 3 often gives strong practical value because it converts real failures into targeted improvements. Phase 4 and phase 5 should depend on logged evidence. Phase 6 is research-heavy and should be postponed until the system can reliably reward the behavior you want.

---

## 12. Final recommendations ranked by priority

### Priority 1 — Make verification an architectural component

This is the highest-priority recommendation. The model should propose; tools should execute; validators should check. Do not use model self-critique as the sole correctness mechanism.

### Priority 2 — Adopt ToRA's representation and SFT-first training philosophy

High-quality tool-integrated traces are a practical path to teaching a model to use mathematical tools. Start with a small corpus that is rigorously validated rather than a huge automatically generated dataset with uncertain labels.

### Priority 3 — Use ReAct for control, but make state explicit

The core controller should record state, actions, observations, checks, and a budget. This makes the system diagnosable, testable, and easy to extend.

### Priority 4 — Borrow THOR's local repair and separated training signals

Preserve correct prefixes and regenerate failed continuations. Distinguish tool execution from semantic validity and final-answer correctness. If you later use RL, use separate diagnostics for those dimensions.

### Priority 5 — Learn tool routing only after collecting outcome data

A manually specified initial router is easier to debug. Use the resulting logs to train and evaluate learned routing rather than assuming a learned selector is automatically better.

### Priority 6 — Add RAP/MCTS selectively

MCTS is a potentially valuable high-compute mode, not the default path. Add it only where a verifier can rank branches and experiments show a cost-adjusted benefit.

### Priority 7 — Defer RL until the reward is trustworthy

RL can amplify both desired and undesired behaviors. It is risky to optimize execution success if execution success is not equivalent to mathematical correctness. Establish a reliable SFT baseline, verifier, and failure taxonomy first.

### Priority 8 — Evaluate by error category, not just aggregate benchmark score

The important outcome is not merely a higher answer-accuracy score. The system should reduce formula transcription errors, invalid transformations, unnecessary tool calls, repeated failed attempts, and unverified claims while staying within a known inference budget.

---

## 13. Limitations and open questions

The five papers do not answer every design question for a practical mathematical research system.

- **Verifier coverage:** many derivations, physical models, and empirical conclusions cannot be fully checked by a single automatic oracle.
- **Reward design:** execution, semantic correctness, proof validity, and end-task success can disagree; scalar rewards can hide failures.
- **Search scaling:** tree search can become expensive and its quality depends on the state model and reward signal.
- **Training-data quality:** synthetic trajectories can propagate teacher errors, wrong assumptions, or benchmark leakage if not checked.
- **Generalization:** results on competition mathematics do not guarantee reliability on university mathematics, physics, or engineering software tasks.
- **Formalization cost:** Lean verification is powerful for formalizable claims but requires translating the intended problem correctly and may be impractical for many numerical tasks.
- **Tool reliability:** a broken environment can produce misleading reward signals unless infrastructure failures are filtered.
- **Comparability:** the original papers use different models, datasets, budgets, and metrics; their reported headline scores do not provide a clean apples-to-apples ranking.

These gaps should become part of the research plan. The best practical contribution may not be a new general-purpose agent algorithm; it may be an improved verifier, a better failure-labeled dataset, a domain-specific reward signal, or a carefully controlled evaluation showing exactly where each technique helps.

---

## 14. Reading order

1. **ReAct** — understand the interaction loop and state/action/observation model. [Paper](https://arxiv.org/abs/2210.03629)
2. **ToRA** — learn the math-specific tool-use format, SFT, and output-space shaping. [Paper](https://arxiv.org/abs/2309.17452) · [Code](https://github.com/microsoft/ToRA)
3. **THOR** — study policy-aligned data generation, trajectory-/step-level optimization, and error recovery. [Paper](https://arxiv.org/abs/2509.13761) · [Code](https://github.com/JingMog/THOR)
4. **Toolformer** — understand self-supervised tool-call placement and selection. [Paper](https://arxiv.org/abs/2302.04761)
5. **RAP** — study state representation, rewards, and MCTS after the baseline loop works. [Paper](https://aclanthology.org/2023.emnlp-main.507/) · [arXiv](https://arxiv.org/abs/2305.14992)

The order is intentionally different from chronological publication order: it prioritizes implementation dependencies.

---

## References

1. Gou, Z., Shao, Z., Gong, Y., Shen, Y., Yang, Y., Huang, M., Duan, N., & Chen, W. (2024). **ToRA: A Tool-Integrated Reasoning Agent for Mathematical Problem Solving.** International Conference on Learning Representations (ICLR). [Proceedings](https://proceedings.iclr.cc/paper_files/paper/2024/hash/d3cf1559a8795eb1ed2b3ad52409ac7d-Abstract-Conference.html) · [Project](https://microsoft.github.io/ToRA/) · [Repository](https://github.com/microsoft/ToRA) · [arXiv](https://arxiv.org/abs/2309.17452)

2. Yao, S., Zhao, J., Yu, D., Du, N., Shafran, I., Narasimhan, K., & Cao, Y. (2022). **ReAct: Synergizing Reasoning and Acting in Language Models.** [arXiv](https://arxiv.org/abs/2210.03629) · [Google Research overview](https://research.google/blog/react-synergizing-reasoning-and-acting-in-language-models/)

3. Hao, S., Gu, Y., Ma, H., Hong, J., Wang, Z., Wang, D., & Hu, Z. (2023). **Reasoning with Language Model is Planning with World Model.** Proceedings of EMNLP 2023, 8154–8173. [ACL Anthology](https://aclanthology.org/2023.emnlp-main.507/) · [arXiv](https://arxiv.org/abs/2305.14992)

4. Schick, T., Dwivedi-Yu, J., Dessì, R., Raileanu, R., Lomeli, M., Zettlemoyer, L., Cancedda, N., & Scialom, T. (2023). **Toolformer: Language Models Can Teach Themselves to Use Tools.** Advances in Neural Information Processing Systems 36 (NeurIPS 2023). [Proceedings](https://proceedings.nips.cc/paper_files/paper/2023/hash/d842425e4bf79ba039352da0f658a906-Abstract-Conference.html) · [Meta AI](https://ai.meta.com/research/publications/toolformer-language-models-can-teach-themselves-to-use-tools/) · [arXiv](https://arxiv.org/abs/2302.04761)

5. Chang, Q., Zhang, Z., Hu, P., Du, J., Ma, J., Pan, Y., Zhang, J., Liu, Q., & Gao, J. (2026). **THOR: Tool-Integrated Hierarchical Optimization via RL for Mathematical Reasoning.** International Conference on Learning Representations (ICLR 2026). [Proceedings](https://proceedings.iclr.cc/paper_files/paper/2026/hash/245b7f8357fdc26797ed6714cda5bd94-Abstract-Conference.html) · [arXiv](https://arxiv.org/abs/2509.13761) · [Repository](https://github.com/JingMog/THOR)

---

## Bottom line

Use **ReAct to control the loop, ToRA to teach mathematical tool use, THOR to improve local tool reliability and recovery, Toolformer to inform learned tool selection, and RAP to search hard problems selectively**. Put a separate, domain-appropriate verifier between a plausible trajectory and an accepted answer. Train in stages and require every added component to beat a simpler baseline under matched evaluation and compute budgets.
