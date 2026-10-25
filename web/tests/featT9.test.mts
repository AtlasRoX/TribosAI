import assert from "node:assert/strict";
import test from "node:test";
import { FEATURE_ARTIFACT_KEYS } from "../src/components/artifacts/artifactKeys.ts";
import {
  calculations,
  citation,
  prettyUnit,
  shownInput,
  shownResult,
  sig,
  utilisationTone,
} from "../src/components/artifacts/engcalcData.ts";

test("T9: the engineering_calc card is registered", () => {
  assert.ok(FEATURE_ARTIFACT_KEYS.includes("engineering_calc"));
  assert.equal(new Set(FEATURE_ARTIFACT_KEYS).size, FEATURE_ARTIFACT_KEYS.length);
});

test("T9: only calculations with results are shown", () => {
  assert.deepEqual(calculations(null), []);
  assert.deepEqual(calculations({ calculations: "x" }), []);
  const list = calculations({ calculations: [{ calculator: "beam", results: [] }, { calculator: "x" }, null] });
  assert.deepEqual(list.map((c) => c.calculator), ["beam"]);
});

test("T9: units read naturally", () => {
  assert.equal(prettyUnit("W/(m^2*K)"), "W/(m²·K)");
  assert.equal(prettyUnit("N*m"), "N·m");
  assert.equal(prettyUnit("degC"), "°C");
  assert.equal(prettyUnit("1"), "");
  assert.equal(prettyUnit("m^4"), "m⁴");
});

test("T9: numbers keep four significant figures, in scientific form when tiny or huge", () => {
  assert.equal(sig(3.0476190476), "3.048");
  assert.equal(sig(126841.089), "126800");
  assert.equal(sig(8.4266e-5), "8.427×10⁻⁵");
  assert.equal(sig(2.1e9), "2.1×10⁹");
  assert.equal(sig(0), "0");
  assert.equal(sig(Number.NaN), "—");
});

test("T9: results show their display unit and the propagated uncertainty", () => {
  assert.deepEqual(shownResult({ value: 0.0030476, unit: "m", display_value: 3.0476, display_unit: "mm" }), {
    value: "3.048",
    unit: "mm",
    uncertainty: null,
  });
  const withU = shownResult({ value: 0.003, unit: "m", display_value: 3, display_unit: "mm", uncertainty: { formatted: "(3.05 ± 0.15) mm" } });
  assert.equal(withU.uncertainty, "(3.05 ± 0.15) mm");
  assert.equal(shownResult({ value: 1.41, unit: "1" }).unit, "");
});

test("T9: inputs show what the reader wrote", () => {
  assert.equal(shownInput({ value: 0.012, unit: "m", given_as: "12 mm" }), "12 mm");
  assert.equal(shownInput({ value: 2.1e11, unit: "Pa", source: "material s355" }), "2.1×10¹¹ Pa");
  assert.equal(shownInput({ value: "simply_supported" }), "simply supported");
  assert.equal(shownInput({ value: [{}, {}] }), "2 items");
});

test("T9: utilisation tone: passes, close to the limit, fails", () => {
  assert.equal(utilisationTone(0.5, true), "ok");
  assert.equal(utilisationTone(0.9, true), "warn");
  assert.equal(utilisationTone(1.4, false), "bad");
  assert.equal(utilisationTone(0.3, false), "bad");
  assert.equal(utilisationTone(null, undefined), "ok");
});

test("T9: the citation joins the source and the section", () => {
  assert.equal(citation({ reference: { source: "ASME BPVC VIII-1", section: "UG-27" } }), "ASME BPVC VIII-1, UG-27");
  assert.equal(citation({}), "");
});
