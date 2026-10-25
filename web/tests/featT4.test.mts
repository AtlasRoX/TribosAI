import assert from "node:assert/strict";
import test from "node:test";
import { unitsSummary } from "../src/lib/unitsSummary.ts";

test("T4: the unit summary reports actual coverage, including zero", () => {
  assert.equal(unitsSummary(undefined), "");
  assert.equal(unitsSummary({}), "");
  assert.equal(unitsSummary({ checked: 0, consistent: 0, inconsistent: [], not_evaluated: 3 }), "Units: 0 checked, 0 inconsistent");
  assert.equal(unitsSummary({ checked: 4, consistent: 3, inconsistent: [{ statement: "pressure = 2 N" }], not_evaluated: 1 }),
    "Units: 4 checked, 1 inconsistent");
});
