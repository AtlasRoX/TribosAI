// Run with: node --test web/tests/featLegacyToolLabels.test.mts   (Node 24 strips the TypeScript types)
import { test } from "node:test";
import assert from "node:assert/strict";
import { legacyToolLabel } from "../src/lib/legacyNames.ts";

const RETIRED_PRODUCT_NAMES = /\b(?:Synapta|Vivarix|Lumicell|Lithoscribe)\b/i;

test("aliases the server still runs are labelled with the engine that serves them", () => {
  assert.equal(legacyToolLabel("vivarix_simulate_time_course"), "Dynamis time course");
  assert.equal(legacyToolLabel("vivarix_compute_steady_state"), "Dynamis steady state");
  assert.equal(legacyToolLabel("vivarix_parameter_scan"), "Dynamis parameter scan");
  assert.equal(legacyToolLabel("lithoscribe_literature_synthesis"), "Archivon literature search");
});

test("tools that no longer exist read as retired, and no label names a retired product", () => {
  for (const name of ["synapta_opentargets_search", "synapta_opentargets_associations", "synapta_kegg_pathways",
    "lumicell_analyze_single_cell"]) {
    const label = legacyToolLabel(name);
    assert.match(label, /^Retired tool \(.+\)$/, name);
    assert.doesNotMatch(label, RETIRED_PRODUCT_NAMES, name);
  }
});

test("current and unknown tool names are shown as recorded", () => {
  assert.equal(legacyToolLabel("dynamis_simulate_ode"), "dynamis_simulate_ode");
  assert.equal(legacyToolLabel("websurfer_search"), "WebSurfer search");
  assert.equal(legacyToolLabel("constructor"), "constructor");
});
