import { test } from "node:test";
import assert from "node:assert/strict";
import { cleanStepText, decodeEntities, DEFECT_LABELS } from "../src/lib/entities.ts";
import type { QueryEntityType } from "../src/types/queryPlan.ts";

test("decodeEntities decodes abstract entities", () => {
  assert.equal(decodeEntities("p &lt;0.001 &amp; T&nbsp;300K"), "p <0.001 & T 300K");
  assert.equal(decodeEntities(null), "");
});

test("cleanStepText replaces stored defect tags from older runs", () => {
  assert.equal(
    cleanStepText("[CONSTANT_MISMATCH] - Planck constant differs from CODATA"),
    "Physical constant does not match CODATA: Planck constant differs from CODATA"
  );
  assert.equal(
    cleanStepText("[DIMENSION_MISMATCH] - Power instead of energy in expression"),
    "Dimensional mismatch: Power instead of energy in expression"
  );
  assert.equal(
    cleanStepText("[UNVERIFIED_IDENTITY] - LHS equals RHS identity failed"),
    "Mathematical identity not verified: LHS equals RHS identity failed"
  );
  assert.equal(
    cleanStepText("[UNSUPPORTED_CLAIM] - Damping ratio is 0.05"),
    "Not found in the evidence: Damping ratio is 0.05"
  );
  assert.equal(
    cleanStepText("[CLAIM_CONTRADICTED] There is no stable equilibrium"),
    "Contradicted by a source: There is no stable equilibrium"
  );
  assert.equal(cleanStepText("Checked 3 claim(s) [not a tag]"), "Checked 3 claim(s) [not a tag]");
});

test("Tribos STEM entity defect categories are defined", () => {
  assert.equal(DEFECT_LABELS.CONSTANT_MISMATCH, "Physical constant does not match CODATA:");
  assert.equal(DEFECT_LABELS.DIMENSION_MISMATCH, "Dimensional mismatch:");
  assert.equal(DEFECT_LABELS.UNVERIFIED_IDENTITY, "Mathematical identity not verified:");
  assert.equal(DEFECT_LABELS.COMPUTATION_MISMATCH, "Computation does not match the evidence:");
  assert.equal(DEFECT_LABELS.UNSUPPORTED_CLAIM, "Not found in the evidence:");
  assert.equal(DEFECT_LABELS.CLAIM_CONTRADICTED, "Contradicted by a source:");
});

test("Tribos STEM entity categories (concept, equation, quantity, constant, material, system)", () => {
  const stemEntityTypes: QueryEntityType[] = [
    "concept",
    "equation",
    "quantity",
    "constant",
    "material",
    "system",
  ];
  assert.equal(stemEntityTypes.length, 6);
  assert.deepEqual(stemEntityTypes, ["concept", "equation", "quantity", "constant", "material", "system"]);
});
