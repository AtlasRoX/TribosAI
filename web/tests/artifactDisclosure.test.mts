// Run with: node --test web/tests/artifactDisclosure.test.mts   (Node 24 strips the TypeScript types)
import { test } from "node:test";
import assert from "node:assert/strict";
import * as ad from "../src/lib/artifactDisclosure.ts";

const { artifactDisclosure, questionRequests, exclusionClauses } = ad;

const STEM_EXCLUSION_QUERY =
  "Retrieve arXiv:2309.17452 by exact identifier. If your tool cannot do exact lookup, say so and try one primary-source " +
  "alternative.\nKeep the answer under 400 words.\nNo symbolic derivation, simulation, physical constants or hypothesis generation is " +
  "needed. Do not rewrite the answer without new evidence.";

test("plan review, sandbox analysis and calibration open whenever present", () => {
  const open = artifactDisclosure({
    question: "anything",
    artifacts: { plan_approval: {}, sandbox_analysis: { status: "ok" }, model_calibration: {} },
  });
  assert.deepEqual(open, { plan_approval: true, sandbox_analysis: true, model_calibration: true });
});

test("the literature list opens when the question asks for literature, and stays a summary line otherwise", () => {
  const arithmetic = artifactDisclosure({ question: "Evaluate 3/4 + 2 - 8 exactly", artifacts: { literature: {}, archivon: {} } });
  assert.deepEqual(arithmetic, { literature: false, archivon: false });
  const review = artifactDisclosure({ question: "Which papers report the drag coefficient of a sphere?", artifacts: { literature: {} } });
  assert.equal(review.literature, true);
});

test("domain cards open only when the question asks for that evidence", () => {
  const arts = { derivation: {}, dynamis: {}, reference_data: {}, hypotheses: {} };
  const open = artifactDisclosure({ question: "Derive the closed-form solution and check physical constants.", artifacts: arts });
  assert.equal(open.derivation, true);
  assert.equal(open.reference_data, true);
  assert.equal(open.dynamis, false);
  assert.equal(open.hypotheses, false);
});

test("explicit exclusion clauses keep excluded analyses compact", () => {
  assert.equal(questionRequests("dynamis", "Run an ODE simulation of the damped harmonic oscillator."), true);
  assert.equal(questionRequests("dynamis", "Summarize the literature. No simulation needed."), false);
  assert.equal(questionRequests("derivation", "Summarize the literature. No symbolic derivation needed."), false);
  assert.equal(questionRequests("reference_data", "Summarize the literature. No physical constants needed."), false);
  assert.equal(questionRequests("literature", "Summarize the literature. No simulation needed."), true);
  // The list form of the diagnostic query excludes derivation, simulation, constants and hypotheses together.
  for (const key of ["derivation", "dynamis", "reference_data", "hypotheses"]) {
    assert.equal(questionRequests(key, STEM_EXCLUSION_QUERY), false, key);
  }
  assert.equal(questionRequests("dynamis", "Simulate the Lorenz attractor without running a parameter scan."), true);
  assert.equal(questionRequests("reference_data", "Report CODATA constants; do not run a simulation."), true);
  assert.equal(questionRequests("dynamis", "Report CODATA constants; do not run a simulation."), false);
  assert.equal(questionRequests("dynamis", "Simulation is not needed; prove the identity."), false);
});

test("a plain 'no' inside other wording is not an exclusion", () => {
  assert.deepEqual(exclusionClauses("If no exact lookup works, try one alternative."), []);
  assert.equal(questionRequests("literature", "If no preprint is available, cite the journal paper."), true);
});

test("failed analyses open even when the question did not ask for them", () => {
  const open = artifactDisclosure({
    question: "Summarize the literature",
    artifacts: { dynamis: { success: false, error: "solver failed" }, derivation: { status: "error" }, reference_data: { error: "" } },
  });
  assert.equal(open.dynamis, true);
  assert.equal(open.derivation, true);
  assert.equal(open.reference_data, false);
});

test("counter-evidence opens for contradictions or heuristic-only classification", () => {
  const q = "x";
  assert.equal(artifactDisclosure({ question: q, artifacts: { evidence_conflicts: { classifier: "nli", conflicts: [{ label: "contradicts" }] } } }).evidence_conflicts, true);
  assert.equal(artifactDisclosure({ question: q, artifacts: { evidence_conflicts: { classifier: "heuristic", conflicts: [{ label: "neutral" }] } } }).evidence_conflicts, true);
  assert.equal(artifactDisclosure({ question: q, artifacts: { evidence_conflicts: { classifier: "nli", conflicts: [{ label: "supports" }] } } }).evidence_conflicts, false);
});

test("claim-support scores open for a low-support claim or overall support below 0.6", () => {
  const conf = (c: Record<string, unknown>) => artifactDisclosure({ artifacts: { claim_confidence: c } }).claim_confidence;
  assert.equal(conf({ answer_confidence: 0.55, claims: [] }), true);
  assert.equal(conf({ answer_confidence: 0.8, claims: [{ band: "low" }] }), true);
  assert.equal(conf({ answer_confidence: 0.8, claims: [{ band: "high", confidence: 0.9 }] }), false);
});

test("the agent run and plan open for unfinished or failed work and stay compact otherwise", () => {
  const run = (r: Record<string, unknown>, taskStatus?: Record<string, unknown>) =>
    artifactDisclosure({ taskStatus, artifacts: { agent_run: r } }).agent_run;
  assert.equal(run({ sub_questions: [{ status: "answered" }], trace: [{ success: true }], phases: [{ status: "ok" }] }), false);
  assert.equal(run({ sub_questions: [{ status: "partial" }] }), true);
  assert.equal(run({ budget: { exhausted: true } }), true);
  assert.equal(run({ trace: [{ success: false }] }), true);
  assert.equal(run({ phases: [{ status: "error" }] }), true);
  assert.equal(run({}, { task_status: "partial" }), true);
  assert.equal(run({}, { task_status: "completed", unresolved: ["q2"] }), true);
  const plan = (p: Record<string, unknown>) => artifactDisclosure({ artifacts: { agent_plan: p } }).agent_plan;
  assert.equal(plan({ planner: "llm", nodes: [{ status: "done" }] }), false);
  assert.equal(plan({ planner: "llm", nodes: [{ status: "error" }] }), true);
  assert.equal(plan({ planner: "llm", rejected: [{ reason: "policy" }] }), true);
  assert.equal(plan({ planner: "none" }), true);
});

test("routine dialogue and project memory stay collapsed", () => {
  const open = artifactDisclosure({ question: "Use project memory and show the agent dialogue", artifacts: { agent_dialogue: {}, project_memory: {} } });
  assert.deepEqual(open, { agent_dialogue: false, project_memory: false });
});

test("a card is flagged only for an actual warning, with its reason (audit I42)", () => {
  const { artifactAttention } = ad;
  const ok = artifactAttention({ artifacts: { math_agent: { status: "verified" }, agent_plan: { planner: "llm", nodes: [], rejected: [] } } });
  assert.deepEqual(ok, {}); // a verified computation is open-worthy, never a warning
  const warn = artifactAttention({
    taskStatus: { task_status: "partial", incomplete_reasons: ["Requested format not met: 2 non-empty lines, 3 required."] },
    artifacts: {
      math_agent: { status: "partially_verified" },
      agent_plan: { rejected: [{ node: "n1", reason: "tool 'web_search' is not registered" }] },
      agent_run: {},
      formal_proof: { status: "not_formalizable", error: "needs complex numbers" },
    },
  });
  assert.equal(warn.math_agent, "The mathematics is partially verified");
  assert.equal(warn.agent_plan, "1 planned call rejected");
  assert.equal(warn.agent_run, "Requested format not met: 2 non-empty lines, 3 required.");
  assert.equal(warn.formal_proof, undefined); // not formalisable is a scope statement, not a failure
});
