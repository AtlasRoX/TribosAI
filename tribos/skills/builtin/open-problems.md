---
name: open-problems
description: Questions about famous open problems or unproved conjectures.
triggers:
  - \b(?:open|unsolved|unresolved)\s+(?:problem|question|conjecture)
  - \bmillennium\b|\bclay\b
  - \bconjecture\b
  - \b(?:riemann hypothesis|navier[- ]stokes|p\s*(?:vs\.?|versus)\s*np|collatz|goldbach|twin prime|hodge|yang[- ]mills)\b
---
1. Open with the status in one sentence: open, solved (by whom, when, where published), or disputed.
2. Separate three kinds of statement and label them: proved theorems (cite the paper), conditional or partial results (state the condition), and unrefereed claims (preprints, deposits): never present the last as settled.
3. When asked to make progress, deliver the strongest result you can actually prove, and name the exact step that fails, as a mathematical statement.
4. Numerical experiments are evidence: say what they show and why they cannot prove the claim.
5. Never claim a proof or counterexample that no checker (Lean, exact computation) confirmed.
