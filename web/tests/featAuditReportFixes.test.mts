import { test } from "node:test";
import assert from "node:assert/strict";
import { derivationRunStatus, derivationStepStatus } from "../src/lib/derivationStatus.ts";
import { formatNumber } from "../src/lib/numberFormat.ts";

// AUDIT-006: a math-agent step that merely ran is never labelled "Verified".
const mathAgentPayload = {
  status: "partially_verified",
  answer: { text: "nan" },
  verification: { status: "partially_verified" },
  steps: [
    { tool: "axiom_simplify", status: "ok", output: { simplified: "1/x" } },
    { tool: "axiom_calculus", status: "ok", output: { result: "nan", verified: false } },
  ],
};

test("derivation: the run status is shown, not hidden", () => {
  assert.deepEqual(derivationRunStatus(mathAgentPayload), { label: "Partially verified", tone: "warn" });
  assert.equal(derivationRunStatus({ verification: { status: "failed" } })?.label, "Failed");
  assert.equal(derivationRunStatus({ is_equal: true })?.label, "Verified symbolically");
  assert.equal(derivationRunStatus({}), null);
});

test("derivation: executed steps say Ran; explicit verification decides Verified", () => {
  const [ran, unchecked] = mathAgentPayload.steps.map(derivationStepStatus);
  assert.equal(ran.label, "Ran");
  assert.equal(unchecked.label, "Not verified");
  assert.equal(derivationStepStatus({}).label, "Not checked");
  assert.equal(derivationStepStatus({ verified: true }).label, "Verified");
  assert.equal(derivationStepStatus({ status: "error" }).tone, "warn");
});

// AUDIT-021: small values keep their significant figures.
test("formatNumber keeps significant figures below 1", () => {
  assert.equal(formatNumber(0.0012345), "0.00123");
  assert.equal(formatNumber(0.5), "0.5");
  assert.equal(formatNumber(12.34567), "12.346");
  assert.equal(formatNumber(1e-5), "1.00e-5");
  assert.equal(formatNumber(0), "0");
  assert.equal(formatNumber(-0.0123456, 4), "-0.01235");
});
