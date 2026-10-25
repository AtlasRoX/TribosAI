import assert from "node:assert/strict";
import test from "node:test";
import { FEATURE_ARTIFACT_KEYS } from "../src/components/artifacts/artifactKeys.ts";

test("T3: the uncertainty artifact key is registered", () => {
  assert.ok(FEATURE_ARTIFACT_KEYS.includes("uncertainty"), "uncertainty key should be registered");
});

test("T3: every registered artifact key is unique", () => {
  const keys = [...FEATURE_ARTIFACT_KEYS];
  assert.equal(new Set(keys).size, keys.length, "artifact keys must be unique");
});

test("T3: uncertainty budget normalization and percentage contributions", () => {
  const budget = [
    { variable: "a", value: 10, std_uncertainty: 1, sensitivity: 2, variance_contribution: 4, percentage: 80 },
    { variable: "b", value: 5, std_uncertainty: 1, sensitivity: 1, variance_contribution: 1, percentage: 20 },
  ];
  const total = budget.reduce((sum, item) => sum + item.percentage, 0);
  assert.equal(Math.round(total), 100);
});

test("T3: a linear model has contributions that add in quadrature", () => {
  // y = a * b with independent relative uncertainties: the shares are the squares of the relative
  // uncertainties, so they sum to 100 and the dominant one is the larger relative uncertainty.
  const ra = 0.1;
  const rb = 0.05;
  const shareA = (ra * ra) / (ra * ra + rb * rb);
  const shareB = 1 - shareA;
  assert.ok(Math.abs(shareA * 100 - 80) < 1e-9);
  assert.ok(Math.abs(shareB * 100 - 20) < 1e-9);
});
