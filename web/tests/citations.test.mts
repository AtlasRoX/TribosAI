// Run with: node --test web/tests/citations.test.mts   (Node 24 strips the TypeScript types)
import { test } from "node:test";
import assert from "node:assert/strict";
import * as cite from "../src/lib/citations.ts";

const { CITE_PATTERN, hrefToKey, rehypeCitations, resolveKey, supportFor, toCiteKey } = cite;

type Node = { type: string; tagName?: string; value?: string; properties?: Record<string, unknown>; children?: Node[] };

const text = (value: string): Node => ({ type: "text", value });
const el = (tagName: string, children: Node[] = [], properties: Record<string, unknown> = {}): Node => ({
  type: "element",
  tagName,
  properties,
  children,
});
const root = (...children: Node[]): Node => ({ type: "root", children });

function entry(key: string, url: string, extra: Record<string, unknown> = {}) {
  const [prefix, id] = [key.slice(0, key.indexOf(":")), key.slice(key.indexOf(":") + 1)];
  const type = { ARXIV: "arxiv", DOI: "doi", ZBL: "zbl", MR: "mr", OEIS: "oeis", ADS: "ads", MP: "mp", URL: "url" }[prefix] || "arxiv";
  return { key, id, type, url, source_agent: "Archivon", source_tool: "arxiv", passages: [], verified: true, ...extra };
}

const MAP = {
  version: 1,
  entries: {
    "ARXIV:2309.17452": entry("ARXIV:2309.17452", "https://arxiv.org/abs/2309.17452"),
    "OEIS:A000045": entry("OEIS:A000045", "https://oeis.org/A000045"),
    "DOI:10.1103/physrevlett.130.010401": entry(
      "DOI:10.1103/physrevlett.130.010401",
      "https://doi.org/10.1103/PhysRevLett.130.010401"
    ),
  },
  aliases: { "DOI:10.48550/arxiv.2309.17452": "ARXIV:2309.17452" },
  supports: [
    { key: "ARXIV:2309.17452", occurrence: 0, sentence: "a", highlight: null, shared_terms: [], grounded_by_verifier: false },
    { key: "ARXIV:2309.17452", occurrence: 1, sentence: "b", highlight: "x", shared_terms: ["x"], grounded_by_verifier: false },
  ],
  unverified: ["OEIS:A000046"],
} as any;

function run(tree: Node, map = MAP): Node {
  rehypeCitations({ map })(tree);
  return tree;
}

function anchors(node: Node, out: Node[] = []): Node[] {
  if (node.type === "element" && node.properties && node.properties.dataCiteKey) out.push(node);
  for (const c of node.children || []) anchors(c, out);
  return out;
}

test("a cited arXiv identifier inside a paragraph becomes a citation anchor", () => {
  const p = el("p", [text("ToRA uses tool-integrated reasoning (arXiv:2309.17452).")]);
  run(root(p));
  assert.equal(p.children!.length, 3);
  const [before, a, after] = p.children!;
  assert.equal(before.value, "ToRA uses tool-integrated reasoning (");
  assert.equal(a.tagName, "a");
  assert.deepEqual(a.properties, {
    href: "https://arxiv.org/abs/2309.17452",
    className: ["cite-ref"],
    dataCiteKey: "ARXIV:2309.17452",
    dataCiteOccurrence: "0",
  });
  assert.equal(a.children![0].value, "arXiv:2309.17452");
  assert.equal(after.value, ").");
});

test("text inside code, pre and existing links is never rewritten", () => {
  const code = el("code", [text("arXiv:2309.17452")]);
  const pre = el("pre", [el("code", [text("A000045")])]);
  const link = el("a", [text("arXiv:2309.17452")], { href: "https://example.org/x" });
  const kbd = el("kbd", [text("A000045")]);
  const tree = root(el("p", [code, text(" "), link, kbd]), pre);
  run(tree);
  assert.equal(anchors(tree).length, 0);
  assert.equal(code.children![0].value, "arXiv:2309.17452");
  assert.equal(pre.children![0].children![0].value, "A000045");
  assert.equal(link.children![0].type, "text");
});

test("a table cell with two ids yields two anchors with per-key occurrence counters", () => {
  const td1 = el("td", [text("arXiv:2309.17452 and A000045")]);
  const td2 = el("td", [text("again arXiv:2309.17452")]);
  const tree = root(el("table", [el("tr", [td1, td2])]));
  run(tree);
  const found = anchors(tree).map((a) => [a.properties!.dataCiteKey, a.properties!.dataCiteOccurrence]);
  assert.deepEqual(found, [
    ["ARXIV:2309.17452", "0"],
    ["OEIS:A000045", "0"],
    ["ARXIV:2309.17452", "1"],
  ]);
});

test("ids not in map.entries stay text; rejected ids get a plain dotted marker", () => {
  const p = el("p", [text("Zbl 9999.99999 is unknown; A000046 was rejected.")]);
  run(root(p));
  assert.equal(anchors(p).length, 0);
  const span = p.children!.find((c) => c.tagName === "span")!;
  assert.equal(span.children![0].value, "A000046");
  assert.equal(span.properties!.title, "Not verified against the retrieved evidence");
  assert.ok(!("href" in span.properties!));
  assert.ok(p.children!.some((c) => c.type === "text" && c.value!.startsWith("Zbl 9999.99999 is unknown")));
});

test("DOIs are normalized (case, trailing punctuation) and resolved through aliases", () => {
  assert.equal(toCiteKey("doi 10.1103/PhysRevLett.130.010401."), "DOI:10.1103/physrevlett.130.010401");
  assert.equal(toCiteKey("(10.1016/s0140-6736(97)11096-0)"), "DOI:10.1016/s0140-6736(97)11096-0");
  assert.equal(resolveKey(MAP, "DOI:10.48550/arxiv.2309.17452"), "ARXIV:2309.17452");
  const p = el("p", [text("Reviewed in (10.48550/arXiv.2309.17452). Published: 10.1103/PhysRevLett.130.010401.")]);
  run(root(p));
  const found = anchors(p);
  assert.deepEqual(
    found.map((a) => a.properties!.dataCiteKey),
    ["ARXIV:2309.17452", "DOI:10.1103/physrevlett.130.010401"]
  );
  assert.equal(found[0].children![0].value, "10.48550/arXiv.2309.17452");
  assert.equal(found[1].children![0].value, "10.1103/PhysRevLett.130.010401");
});

test("an existing link to a known entry is annotated in place and counted in document order", () => {
  const link = el("a", [text("Fibonacci sequence")], { href: "https://oeis.org/A000045", className: ["x"] });
  const p = el("p", [text("Sequence A000045 "), link, text(" and A000045")]);
  run(root(p));
  assert.equal(link.properties!.dataCiteKey, "OEIS:A000045");
  assert.equal(link.properties!.dataCiteOccurrence, "1");
  assert.deepEqual(link.properties!.className, ["x", "cite-ref"]);
  assert.deepEqual(
    anchors(p).map((a) => a.properties!.dataCiteOccurrence),
    ["0", "1", "2"]
  );
});

test("hrefToKey maps database link-outs and plain web links", () => {
  assert.equal(hrefToKey("https://arxiv.org/abs/2309.17452"), "ARXIV:2309.17452");
  assert.equal(hrefToKey("https://doi.org/10.1103/PhysRevLett.130.010401"), "DOI:10.1103/physrevlett.130.010401");
  assert.equal(hrefToKey("https://zbmath.org/?q=an:1234.56789"), "ZBL:1234.56789");
  assert.equal(hrefToKey("https://mathscinet.ams.org/mathscinet-getitem?mr=1234567"), "MR:1234567");
  assert.equal(hrefToKey("https://oeis.org/A000045"), "OEIS:A000045");
  assert.equal(hrefToKey("https://ui.adsabs.harvard.edu/abs/2023ApJ...123..456A"), "ADS:2023ApJ...123..456A");
  assert.equal(hrefToKey("https://next-gen.materialsproject.org/materials/mp-149"), "MP:mp-149");
  assert.equal(hrefToKey("https://example.org/page/#frag"), "URL:https://example.org/page");
  assert.equal(hrefToKey("javascript:alert(1)"), null);
  assert.equal(hrefToKey("#section"), null);
});

test("supportFor returns the exact occurrence and falls back when counts drift", () => {
  assert.equal(supportFor(MAP, "ARXIV:2309.17452", 0)!.sentence, "a");
  assert.equal(supportFor(MAP, "DOI:10.48550/arxiv.2309.17452", 1)!.sentence, "b");
  assert.equal(supportFor(MAP, "ARXIV:2309.17452", 7)!.sentence, "b");
  assert.equal(supportFor(MAP, "OEIS:A000045", 0), null);
});

test("an empty map leaves the tree untouched", () => {
  const p = el("p", [text("arXiv:2309.17452")]);
  run(root(p), { version: 1, entries: {}, aliases: {}, supports: [], unverified: [] } as any);
  assert.equal(p.children!.length, 1);
});

test("identifier grammar matches Tribos STEM identifiers", () => {
  const cases = [
    { text: "arXiv:2309.17452 and arXiv:hep-th/9901001", keys: ["ARXIV:2309.17452", "ARXIV:hep-th/9901001"] },
    { text: "See Zbl 1234.56789 and Zbl:5678.12345", keys: ["ZBL:1234.56789", "ZBL:5678.12345"] },
    { text: "MR1234567 and MR:2345678", keys: ["MR:1234567", "MR:2345678"] },
    { text: "Fibonacci sequence is A000045 or OEIS:A000045", keys: ["OEIS:A000045", "OEIS:A000045"] },
    { text: "Astrophysics paper 2023ApJ...123..456A or ADS:2024MNRAS.500..100B", keys: ["ADS:2023ApJ...123..456A", "ADS:2024MNRAS.500..100B"] },
    { text: "Material silicon is mp-149 and MP:mp-1234", keys: ["MP:mp-149", "MP:mp-1234"] },
    { text: "Review (doi: 10.1103/PhysRevLett.130.010401).", keys: ["DOI:10.1103/physrevlett.130.010401"] },
    { text: "Computation comp:axiom_solve:1 and dataset ds_0123456789ab", keys: ["COMP:axiom_solve:1", "DATASET:ds_0123456789ab"] },
    { text: "No ids: NCT03600883, BIOMD0000000010, ENSG00000133703, rs121913529", keys: [] },
  ];
  for (const c of cases) {
    const keys = [...String(c.text).matchAll(CITE_PATTERN)].map((m) => toCiteKey(m[0])).filter(Boolean);
    assert.deepEqual(keys, c.keys, c.text);
  }
});

test("an author-year citation with its identifier becomes one chip named by the authors", () => {
  // Live answer: "[Bruschi et al., 2023 | arXiv:2309.17452]" showed raw brackets around an identifier chip.
  const p = el("p", [text("It is as yet unproven [Bruschi et al., 2023 | arXiv:2309.17452], and (arXiv:2309.17452) agrees.")]);
  run(root(p));
  const chips = anchors(p);
  assert.equal(chips.length, 2);
  assert.equal(chips[0].children![0].value, "Bruschi et al., 2023");
  assert.equal(chips[0].properties!.dataCiteOccurrence, "0");
  assert.equal(chips[1].properties!.dataCiteOccurrence, "1");
  assert.equal(p.children![0].value, "It is as yet unproven ");
  assert.ok(!JSON.stringify(p).includes("[Bruschi"));
});

test("an author-year bracket with an unknown identifier is left as written", () => {
  const p = el("p", [text("See [Someone, 2020 | arXiv:1111.11111] here.")]);
  run(root(p));
  assert.equal(anchors(p).length, 0);
  assert.equal(p.children![0].value, "See [Someone, 2020 | arXiv:1111.11111] here.");
});
