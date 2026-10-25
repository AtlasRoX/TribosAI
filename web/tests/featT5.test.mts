import assert from "node:assert/strict";
import test from "node:test";
import { FEATURE_ARTIFACT_KEYS } from "../src/components/artifacts/artifactKeys.ts";
import { compilerLines, formalBadge, formalData } from "../src/components/artifacts/formalData.ts";

test("T5: the formal_proof card is registered", () => {
  assert.ok(FEATURE_ARTIFACT_KEYS.includes("formal_proof"));
  assert.equal(new Set(FEATURE_ARTIFACT_KEYS).size, FEATURE_ARTIFACT_KEYS.length);
});

test("T5: only a clean compile is formally verified", () => {
  assert.deepEqual(formalBadge({ status: "verified" }), { tone: "ok", text: "formally verified (Lean)" });
  assert.deepEqual(formalBadge({ status: "failed" }), { tone: "bad", text: "formalisation failed" });
  assert.equal(formalBadge({ status: "timeout" }).text, "formalisation failed (timeout)");
  assert.deepEqual(formalBadge({ status: "unavailable" }), { tone: "neutral", text: "formal checker unavailable" });
  assert.equal(formalData({ nothing: 1 }), null);
});

test("T5: compiler messages list errors first", () => {
  const lines = compilerLines({
    messages: [
      { line: 5, column: 2, severity: "warning", message: "unused variable" },
      { line: 3, column: 8, severity: "error", message: "unknown identifier 'x'" },
    ],
  });
  assert.deepEqual(lines, ["3:8 error: unknown identifier 'x'", "5:2 warning: unused variable"]);
});
