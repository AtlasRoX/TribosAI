# Context gate, the Lumo Admission Gate and concise answers

What reaches the answer model, how long the answer is, and what is never sent at all. Code:
[context_gate.py](../../tribos/agents/context_gate.py), wired in [prompts.py](../../tribos/agents/prompts.py)
(`build_evidence_block`, `CONCISE_ANSWER_RULE`) and [plan.py](../../tribos/agents/orchestration/plan.py) (stage 0.12).

## 1. Query-focused extractive compression

Retrieved literature passages are split into sentences, ranked by BM25 against the question across all retrieved
sentences, and only the most relevant ones are kept (at most 6 per passage, `TRIBOS_CONTEXT_GATE_CHARS` in total,
default 6000), in their original order. Nothing is paraphrased, so citations stay exact.

Why: extractive compression of retrieved documents keeps question-answering accuracy at a fraction of the tokens
(RECOMP, Xu, Shi & Choi, ICLR 2024; here the scorer is lexical BM25, Robertson & Zaragoza 2009, so it needs no
model); long contexts also degrade use of what is in them ("Lost in the Middle", Liu et al., TACL 2024).

When no sentence matches the question, the passages are excerpted as before, so an answer never loses its evidence.

## 2. The Lumo Admission Gate

Standalone package: [Lumo-GATE](https://github.com/AtlasRoX/Lumo-GATE). Every kept sentence gets an integer
admission score K:

| Source class | Weight | Tribos sources |
|---|---|---|
| official | +3 | technical reports and standards; standards and regulatory hosts |
| internal | +2 | peer-reviewed journals and conferences, textbooks and reference works; repository, publisher and university hosts |
| external | +1 | preprints; other web pages |
| unverified | 0 | forums and social media |
| false | −3 | retracted papers |

K = the sentence's own weight + the weight of every other independent source stating the same fact − the weight of
every reliable source stating a conflicting value. Only **K ≥ 1** is admitted; K = 0 is quarantined and K ≤ −1 blocked
(counted in the run trace, never shown to the model). Two pages of one source count once.

For scientific text, the word-overlap relation needs 80% shared words for a conflict, and
when sentences carry several numbers, some must be shared (the conditions) while others differ. "100 °C at 1 atm"
and "120 °C at 2 atm" are different conditions, not a conflict; "100 °C at 1 atm" and "105 °C at 1 atm" are.

Honest limits: K is only as good as the source classes behind it, and the word-overlap relation is crude. What the
gate implements is source-weighted corroboration with abstention, in line with grounding research (attributable
answers, ALCE, Gao et al., EMNLP 2023). Claim-level checking of the written answer stays with the existing verifier.

## 3. The paradox guard

A self-referential statement ("this statement is false") has no grounding context (K = 0) and is answered at once with
a fixed explanation, before the planner, any source, tool or model call: 0 model requests, about 1 s.

## 4. Concise answers

`TRIBOS_ANSWER_STYLE=concise` (the default) asks the writer for the direct answer first and only the steps, values and
evidence that support it; a requested proof or derivation is still given in full. `full` restores the longer report
format. Asking for brevity cuts output without losing accuracy on reasoning tasks (Nayab et al., "Concise Thoughts",
arXiv:2407.19825, 2024).

## 5. Do what was asked, no more

- **Lean only on request.** `TRIBOS_FORMAL_MODE=explicit` (default): a machine-checked Lean proof is attempted when the
  question asks for one ("formal proof", "in Lean", "machine-checked", "formally verify"); "prove that ..." gets a
  written proof. `auto` restores Lean for every proof question.
- **Rewrite rounds stop when the answer has converged**: a round that changed less than 5% of the text ends the loop
  (measured on a comparison question: rounds changed 14%, then 3%, each resending ~30k characters). In concise mode,
  medium effort allows at most 1 rewrite round and high 2.
- **Generative UI.** The writer picks the form that shows the answer best: prose for a one-line answer; otherwise up to
  three blocks: stats (headline numbers), steps (a procedure or short derivation), table (a comparison), chart (a
  trend whose points are in the computed results or evidence), equation (the key formula) and callout (one caveat).
  Every number in a block must appear in the answer or the evidence, or the block is removed; a writer's equation
  never carries "passed" checks (only computed results do).

Measured on "Compare the density, Young's modulus and yield strength of aluminium 6061, steel S355 and titanium
Ti-6Al-4V" (medium): 196 s → 104 s, 394 → 267 words, no rewrite round needed, 2 of 2 checked claims supported.

## 6. Prompt caching

The answer instructions (about 2,270 tokens) are a fixed prefix of every answer call, so Meta's API caches them
(measured: 2,161 of 2,271 prompt tokens cached on a repeat). Keep anything that varies per question after the fixed
instructions, never before them.

## Measured (medium effort, muse-spark-1.3, `scripts/measure_tokens.py`)

| Question | Answer words | Time | Characters sent |
|---|---|---|---|
| Boiling point of water at 2 atm | 137 → 15 | 13.5 → 9.6 s | 13,000 → 13,700 |
| How CRISPR-Cas9 causes off-target edits and how they are reduced | 1,001 → 442 | 50.7 → 31.8 s | 37,600 → 27,000 |
| Solve x² − 5x + 6 = 0 | 78 → 66 | 11.2 → 10.9 s | 14,000 → 14,600 |

On the literature question the gate kept 35 of 105 sentences (66% less evidence text) and all 6 checked claims were
supported. Run `python scripts/measure_tokens.py --out after.json --compare before.json` to repeat the comparison.
