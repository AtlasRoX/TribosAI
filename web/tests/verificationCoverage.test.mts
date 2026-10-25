// Run with: node --test web/tests/verificationCoverage.test.mts   (Node 24 strips the TypeScript types)
// Coverage, not a defect-free score, decides how an answer's verification is shown.
import { test } from "node:test";
import assert from "node:assert/strict";
import * as vs from "../src/lib/verificationState.ts";

const { verificationState } = vs;

test("a perfect score over zero evaluated claims is 'not evaluated', never a pass", () => {
  const s = verificationState({
    passed: true,
    verification_score: 1,
    defects: [],
    claims: [],
    fully_verified: false,
    coverage: { extracted: 0, evaluated: 0 },
    status: "not_evaluated",
  });
  assert.equal(s.kind, "not_evaluated");
  assert.match(s.text, /No claims could be checked/);
});

test("claims the checks could not decide are counted but are not findings against the answer", () => {
  const s = verificationState({
    passed: true,
    verification_score: 1,
    defects: [],
    fully_verified: false,
    coverage: { extracted: 3, evaluated: 2, passed: 2, inconclusive: 1 },
    claims: [
      { status: "supported", claim_type: "mathematical" },
      { status: "supported", claim_type: "mathematical" },
      { status: "inconclusive", claim_type: "mathematical" },
    ],
  });
  assert.equal(s.kind, "checked");
  assert.equal(s.counts.inconclusive, 1);
  assert.match(s.text, /2 of 3 claims checked and supported; 1 could not be checked/);
});

test("a contradicted mathematical statement is a problem", () => {
  const s = verificationState({
    passed: false,
    verification_score: 0,
    defects: [{ category: "MATH_CONSISTENCY", description: "X evaluates to 0.46225, not 0.92848" }],
    claims: [{ status: "contradicted", claim_type: "mathematical" }],
    coverage: { extracted: 1, evaluated: 1, failed: 1 },
    status: "failed",
  });
  assert.equal(s.kind, "problems");
  assert.equal(s.counts.contradicted, 1);
});

test("an older report without coverage keeps its previous behaviour", () => {
  const s = verificationState({ passed: true, verification_score: 1, defects: [], claims: [], fully_verified: false, numerical_checks_passed: 0 });
  assert.equal(s.kind, "checked");
});

import * as th from "../src/components/agentic/thoughts.ts";

test("a delayed 'running' update never reopens a step that already finished", () => {
  const done = { id: "agent_node_n1", status: "done", elapsed_seconds: 12 };
  assert.equal(th.mergeThought(done, { id: "agent_node_n1", status: "running", elapsed_seconds: 10 }), done);
  // A step the backend really reopens later replaces it.
  const reopened = { id: "agent_node_n1", status: "running", elapsed_seconds: 40 };
  assert.equal(th.mergeThought(done, reopened), reopened);
  const failed = { id: "x", status: "error", elapsed_seconds: 5 };
  assert.equal(th.mergeThought({ id: "x", status: "running", elapsed_seconds: 3 }, failed), failed);
});
