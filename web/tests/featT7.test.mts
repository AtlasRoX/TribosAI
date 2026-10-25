import assert from "node:assert/strict";
import test from "node:test";
import { FEATURE_ARTIFACT_KEYS } from "../src/components/artifacts/artifactKeys.ts";
import { arxivUrl, claimDetail, countsLine, doiUrl, equationTex, pageRef, paperData, statusTone } from "../src/components/artifacts/paperData.ts";
import { DEFAULT_DATASET_LIMITS, acceptAttr, dimsOf, kindForFile, normalizeDatasetLimits, precheckFile } from "../src/services/datasetService.ts";

test("T7: the paper card is registered", () => {
  assert.ok(FEATURE_ARTIFACT_KEYS.includes("paper_reproduction"));
});

test("T7: PDFs are accepted as papers with a 25 MB cap", () => {
  assert.equal(kindForFile("Smith2020.PDF"), "paper");
  assert.match(acceptAttr(), /\.pdf/);
  assert.equal(DEFAULT_DATASET_LIMITS.max_bytes.paper, 25 * 1024 * 1024);
  const big = { name: "p.pdf", size: 30 * 1024 * 1024 } as File;
  assert.match(String(precheckFile(big)), /25 MB/);
  const limits = normalizeDatasetLimits({ extensions: { ".pdf": "paper", ".csv": "table" }, max_bytes: { paper: 1000, table: 5 } });
  assert.equal(limits.extensions[".pdf"], "paper");
  assert.equal(limits.max_bytes.paper, 1000);
});

test("T7: a paper's size reads in pages", () => {
  const record = { id: "ds_000000000000", kind: "paper", display_name: "p.pdf", validation: { format: "pdf", n_pages: 12 } };
  assert.equal(dimsOf(record as never), "12 pages");
});

test("T7: claims read as reproduced, differs or not reproducible", () => {
  assert.equal(statusTone("reproduced"), "ok");
  assert.equal(statusTone("differs"), "bad");
  assert.equal(statusTone("not_reproducible"), "warn");
  assert.equal(countsLine({ reproduced: 3, differs: 0, not_reproducible: 2 }), "3 reproduced · 2 not reproducible");
  assert.equal(claimDetail({ status: "not_reproducible", missing: ["m", "k"] }), "The paper gives no value for m, k.");
  assert.equal(claimDetail({ status: "differs", computed: 3.18471337, relative_difference: 0.678 }), "Recomputed 3.1847 (SI) (68% apart)");
  assert.equal(pageRef({ page: 3, ocr: true }), "p. 3 (OCR)");
});

test("T7: equations render as LaTeX when converted, verbatim otherwise", () => {
  assert.deepEqual(equationTex({ lhs: "T", rhs: "2*pi*sqrt(m/k)", latex: "2 \\pi \\sqrt{\\frac{m}{k}}" }), {
    tex: "T = 2 \\pi \\sqrt{\\frac{m}{k}}",
    converted: true,
  });
  assert.deepEqual(equationTex({ state: "x", rhs: "-r*x", latex: null }), { tex: "dx/dt = -r*x", converted: false });
});

test("T7: identifiers link only when well formed", () => {
  assert.equal(doiUrl("10.1234/abcd.5678"), "https://doi.org/10.1234/abcd.5678");
  assert.equal(doiUrl("javascript:alert(1)"), null);
  assert.equal(arxivUrl("2101.01234v2"), "https://arxiv.org/abs/2101.01234v2");
  assert.equal(paperData({ nope: 1 }), null);
});
