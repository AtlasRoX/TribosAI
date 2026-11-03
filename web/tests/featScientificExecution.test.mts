import { test } from "node:test";
import assert from "node:assert/strict";
import { scientificExecution, executionLabel } from "../src/components/artifacts/scientificExecutionData.ts";
import { verificationState } from "../src/lib/verificationState.ts";
import { exploredSpec } from "../src/lib/simulationExplore.ts";

test("an executed result, a cache reuse and an unsuccessful run have distinct labels", () => {
  const record = scientificExecution({ status: "executed", tool: "dynamis_simulate_ode", request_match: true, checks: [{ name: "grid", passed: true }] });
  assert.ok(record);
  assert.equal(executionLabel(record), "Executed · request matched");
  assert.equal(executionLabel({ ...record, status: "reused" }), "Reused computed result");
  assert.equal(executionLabel({ ...record, status: "failed", request_match: false }), "Execution incomplete");
  assert.equal(scientificExecution({ tool: "x" }), null);
});

test("numeric execution checks have scoped wording without a claim of universal verification", () => {
  const state = verificationState({ passed: true, status: "checked", claims: [], numerical_execution_checks: [{ name: "grid", passed: true }] });
  assert.equal(state.kind, "checked");
  assert.match(state.text, /numerical execution checks/);
  assert.match(state.text, /does not certify/);
  assert.equal(state.counts.supported, 0);
  assert.notEqual(verificationState({ passed: false, numerical_execution_checks: [{ name: "grid", passed: false }] }).kind, "checked");
});

test("exploring a fixed-step result keeps its method and recomputes the count when the end time changes", () => {
  const base = { method: "RK4", step_size: 0.01, num_steps: 100, t_span: [0, 1] };
  const changed = exploredSpec(base, {}, {}, 2);
  assert.equal(changed.method, "RK4");
  assert.equal(changed.step_size, 0.01);
  assert.equal(changed.num_steps, 200);
  assert.equal(base.num_steps, 100);
});
