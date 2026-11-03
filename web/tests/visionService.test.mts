// Run with: node --test web/tests/   (Node 24 strips the TypeScript types)
import { test } from "node:test";
import assert from "node:assert/strict";
import { imageContext, readingSummary, sentImages, type ComposerImage } from "../src/services/visionService.ts";

const img = (over: Partial<ComposerImage>): ComposerImage => ({
  key: "k", name: "q.png", previewUrl: "blob:x", thumbUrl: "data:image/jpeg;base64,AA", status: "ready", text: "y'' + y = 0", ...over,
});

test("only images that were read and have text go with the question", () => {
  assert.deepEqual(imageContext([img({}), img({ key: "b", status: "reading" }), img({ key: "c", text: "  " })]), [
    { name: "q.png", text: "y'' + y = 0" },
  ]);
  assert.equal(imageContext([img({ status: "error" })]), undefined);
});

test("a sent message keeps the thumbnail, a viewer copy and the text read from it, never the original file", () => {
  const sent = sentImages([img({ viewUrl: "data:image/jpeg;base64,BB" }), img({ key: "b", status: "error" })]);
  assert.equal(sent.length, 1);
  assert.equal(sent[0].name, "q.png");
  assert.equal(sent[0].thumbUrl, "data:image/jpeg;base64,AA");
  assert.equal(sent[0].viewUrl, "data:image/jpeg;base64,BB"); // shown in the in-app viewer
  assert.equal(sent[0].text, "y'' + y = 0"); // what Tribos read, shown beside the image
  assert.ok(!("file" in sent[0]) && !("previewUrl" in sent[0])); // the original file is never stored
});

test("the viewer says in plain words how a reading was checked", () => {
  const all = ["text recognition", "word recognition", "vision check", "vision cross-check"];
  assert.equal(readingSummary({ engines: all, vision_checked: true, consensus: "agreed", differences: [] }),
    "Read by two text recognizers; two independent vision readings agreed");
  assert.equal(readingSummary({ engines: [...all, "vision review"], vision_checked: true, consensus: "settled", differences: ["a _ i | a _ 1"] }),
    "Read by two text recognizers; two vision readings differed in 1 place, settled against the image");
  assert.equal(readingSummary({ engines: ["text recognition"], vision_checked: false, consensus: "" }), "Read by text recognition");
  assert.equal(readingSummary({ engines: ["vision check"], vision_checked: true, consensus: "single" }),
    "Read by the vision model; checked against the image");
  assert.equal(readingSummary(null), "");
  // No engine or model name ever reaches the viewer.
  assert.doesNotMatch(readingSummary({ engines: all, vision_checked: true, consensus: "agreed" }), /indra|tesseract|muse/i);
});
