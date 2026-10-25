// Run with: node --test web/tests/   (Node 24 strips the TypeScript types)
import { test } from "node:test";
import assert from "node:assert/strict";
import { imageContext, sentImages, type ComposerImage } from "../src/services/visionService.ts";

const img = (over: Partial<ComposerImage>): ComposerImage => ({
  key: "k", name: "q.png", previewUrl: "blob:x", thumbUrl: "data:image/jpeg;base64,AA", status: "ready", text: "y'' + y = 0", ...over,
});

test("only images that were read and have text go with the question", () => {
  assert.deepEqual(imageContext([img({}), img({ key: "b", status: "reading" }), img({ key: "c", text: "  " })]), [
    { name: "q.png", text: "y'' + y = 0" },
  ]);
  assert.equal(imageContext([img({ status: "error" })]), undefined);
});

test("a sent message keeps names and thumbnails, never the full image", () => {
  assert.deepEqual(sentImages([img({}), img({ key: "b", status: "error" })]), [{ name: "q.png", thumbUrl: "data:image/jpeg;base64,AA" }]);
});
