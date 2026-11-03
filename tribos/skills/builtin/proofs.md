---
name: proof-writing
description: Requests to prove or disprove a statement.
triggers:
  - \bprove\b|\bshow that\b|\bproof\b|\bdisprove\b
  - \blemma\b|\btheorem\b
---
1. Restate the claim precisely: quantifiers, domain, hypotheses. If the statement is false as written, say so first and give the smallest counterexample.
2. Name the strategy in one line (induction on n, contradiction, a known inequality, compactness), then give the proof in numbered steps; each step cites what it uses.
3. Check the edge cases the hypotheses allow (n = 0, equality cases, empty sets, boundary points).
4. If a formal (Lean) check ran, report its status exactly: "formally verified" only when Lean accepted it, and quote the Lean statement so the reader can confirm it is the same claim.
