import assert from "node:assert/strict";
import test from "node:test";
import { calibrationResiduals } from "../src/lib/calibration.ts";

test("T1: residual plots use observed minus fitted values and keep zero residuals", () => {
  assert.deepEqual(calibrationResiduals({ time: [0, 1, 2], observed: [1, 3, null], simulated: [1, 2, 4] }),
    [{ x: 0, y: 0 }, { x: 1, y: 1 }]);
});
