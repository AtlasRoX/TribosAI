// Builds the Tribos homepage and changelog into website/dist.
//
//   node website/build.mjs
//
// Uses the Tailwind CSS v4 compiler and KaTeX already installed for the web app (web/node_modules): no extra install.
// Pages are assembled from website/src (partials, {{placeholders}}), maths in <tex>...</tex> is rendered to KaTeX HTML
// at build time, the changelog comes from CHANGELOG.md plus website/src/unreleased.md, and the CSS is compiled from
// the classes the built pages use, then minified.

import fs from "node:fs";
import path from "node:path";
import { createRequire } from "node:module";
import { fileURLToPath } from "node:url";

const here = path.dirname(fileURLToPath(import.meta.url));
const root = path.resolve(here, "..");
const src = path.join(here, "src");
const dist = path.join(here, "dist");
const webRequire = createRequire(path.join(root, "web", "package.json"));

const { compile } = webRequire("tailwindcss");
const { Scanner } = webRequire("@tailwindcss/oxide");
const lightningcss = webRequire("lightningcss");
const katex = webRequire("katex");

const REPO = "https://github.com/AtlasRoX/TribosAI";

// ---------------------------------------------------------------------------------------------------------------
// Changelog
// ---------------------------------------------------------------------------------------------------------------

/** Releases from python-semantic-release's CHANGELOG.md format: ## vX (date) / ### Section / - **scope**: text. */
function parseChangelog(text) {
  const releases = [];
  let release = null;
  let section = null;
  let item = null;
  const flush = () => {
    if (item && section) section.items.push(finishItem(item));
    item = null;
  };
  for (const raw of text.split(/\r?\n/)) {
    const line = raw.trimEnd();
    const h2 = line.match(/^##\s+(.+?)\s*$/);
    const h3 = line.match(/^###\s+(.+?)\s*$/);
    if (h2) {
      flush();
      const m = h2[1].match(/^v?(\d+\.\d+\.\d+)\s*\((\d{4}-\d{2}-\d{2})\)/);
      release = m ? { version: m[1], date: m[2], sections: [], note: "" } : { version: null, label: h2[1], date: null, sections: [], note: "" };
      releases.push(release);
      section = null;
      continue;
    }
    if (!release) continue;
    if (h3) {
      flush();
      section = { title: h3[1], items: [] };
      release.sections.push(section);
      continue;
    }
    const bullet = line.match(/^-\s+(.*)$/);
    if (bullet) {
      flush();
      if (!section) {
        // "- Initial Release" directly under a version.
        release.note = bullet[1];
        continue;
      }
      item = bullet[1];
      continue;
    }
    if (item !== null && line.trim()) {
      item += " " + line.trim();
    } else if (!line.trim()) {
      flush();
    }
  }
  flush();
  return releases;
}

function finishItem(text) {
  const hash = (text.match(/\(\[`([0-9a-f]{7,40})`\]\([^)]*\)\)/) || [])[1] || null;
  const clean = text.replace(/\s*\(\[`[0-9a-f]{7,40}`\]\([^)]*\)\)\s*/, " ").trim();
  const m = clean.match(/^\*\*([^*]+)\*\*:\s*(.*)$/);
  return { scope: m ? m[1] : null, text: m ? m[2] : clean, hash };
}

const escapeHtml = (s) => s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");

/** Inline markdown: `code`, **bold**, and quotes, on escaped text. */
function inline(s) {
  return escapeHtml(s)
    .replace(/`([^`]+)`/g, "<code>$1</code>")
    .replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>");
}

const SECTION_STYLE = {
  "Features": "text-mint",
  "Bug Fixes": "text-ember",
  "Performance Improvements": "text-iris",
  "Documentation": "text-iris",
  "Testing": "text-dust",
  "Refactoring": "text-dust",
  "Build System": "text-dust",
  "Chores": "text-dust",
};

// The site names no model vendor or outside product: older changelog lines that did are shown without it.
const REDACT = [
  [/,?\s*and Meta Muse Spark overview/gi, ""],
  [/\bMeta Muse Spark\b/gi, "the model"],
  [/\bMuse Spark\b/gi, "the model"],
];
const redact = (s) => REDACT.reduce((acc, [re, to]) => acc.replace(re, to), s);

const anchor = (r) => (r.version ? "v" + r.version.replace(/\./g, "-") : "unreleased");
const title = (r) => (r.version ? "v" + r.version : r.label || "Unreleased");

function formatDate(iso) {
  if (!iso) return "Next release";
  const d = new Date(iso + "T00:00:00Z");
  return d.toLocaleDateString("en-GB", { day: "numeric", month: "long", year: "numeric", timeZone: "UTC" });
}

const badgeFor = (r, latestVersion) =>
  !r.version ? '<span class="chip chip-bad">in progress</span>' : r.version === latestVersion ? '<span class="chip chip-ok">latest</span>' : "";

function renderRelease(r, latestVersion) {
  const sections = r.sections
    .filter((s) => s.items.length)
    .map((s) => {
      const items = s.items
        .map((it) => {
          const scope = it.scope ? `<span class="mr-2 rounded-md bg-cream/[0.07] px-1.5 py-0.5 font-mono text-[0.72rem] text-iris">${escapeHtml(it.scope)}</span>` : "";
          const hash = it.hash ? ` <span class="ml-1 font-mono text-[0.7rem] text-dust">${it.hash.slice(0, 7)}</span>` : "";
          return `<li class="log-item leading-relaxed text-cream/90">${scope}${inline(redact(it.text))}${hash}</li>`;
        })
        .join("\n");
      return `<div class="mt-6"><h3 class="font-mono text-xs font-medium tracking-[0.14em] uppercase ${SECTION_STYLE[s.title] || "text-dust"}">${escapeHtml(s.title)}</h3><ul class="mt-3 space-y-2.5 text-[0.98rem]">${items}</ul></div>`;
    })
    .join("\n");
  const note = r.note ? `<p class="mt-4 text-sand">${inline(redact(r.note))}</p>` : "";
  const empty = !sections && !note ? '<p class="mt-4 text-sand">Release with no user-facing changes listed.</p>' : "";
  return `      <li id="${anchor(r)}" class="reveal relative scroll-mt-28 pb-14 pl-8 sm:pl-12">
        <span class="absolute top-2 -left-[7px] size-3.5 rounded-full ${r.version ? "border-2 border-iris bg-coal shadow-[0_0_14px_rgb(174_159_255/.6)]" : "bg-ember shadow-[0_0_16px_rgb(255_138_76/.8)]"}"></span>
        <div class="flex flex-wrap items-baseline gap-x-4 gap-y-2">
          <h2 class="display text-4xl">${escapeHtml(title(r))}</h2>
          <time class="font-mono text-xs text-dust" ${r.date ? `datetime="${r.date}"` : ""}>${formatDate(r.date)}</time>
          ${badgeFor(r, latestVersion)}
        </div>
        ${note}${sections}${empty}
      </li>`;
}

function renderTeaser(releases, latestVersion) {
  return releases
    .slice(0, 3)
    .map((r) => {
      const items = r.sections.flatMap((s) => s.items.map((it) => ({ ...it, section: s.title })));
      const dot = (s) => (s === "Bug Fixes" ? "bg-ember" : s === "Features" ? "bg-mint" : "bg-iris");
      const top = items.slice(0, 3).map((it) => `<li class="flex gap-2.5"><span class="mt-2 size-1.5 shrink-0 rounded-full ${dot(it.section)}"></span><span>${inline(redact(it.text))}</span></li>`).join("");
      const more = items.length > 3 ? `<p class="mt-4 font-mono text-xs text-dust">+ ${items.length - 3} more</p>` : "";
      const body = top ? `<ul class="mt-5 space-y-2.5 text-[0.93rem] leading-snug text-sand">${top}</ul>${more}` : `<p class="mt-5 text-[0.93rem] text-sand">${inline(redact(r.note || "Maintenance release."))}</p>`;
      return `      <a href="changelog.html#${anchor(r)}" class="spot block p-6">
        <div class="flex items-center justify-between gap-3"><span class="display text-3xl">${escapeHtml(title(r))}</span>${badgeFor(r, latestVersion)}</div>
        <time class="mt-1 block font-mono text-xs text-dust">${formatDate(r.date)}</time>
        ${body}
      </a>`;
    })
    .join("\n");
}

// ---------------------------------------------------------------------------------------------------------------
// Benchmarks
// ---------------------------------------------------------------------------------------------------------------

// A validated pair on the white surface (dataviz palette checks: lightness band, chroma, colour-blind separation,
// 3:1 contrast): the same model alone in ochre, Tribos in indigo.
const BASE_COLOUR = "#b8892f";
const TRIBOS_COLOUR = "#4a56c9";
const SURFACE = "#ffffff";
const AXIS_MIN = 80;

const pct = (k, n) => (100 * k) / n;
const fmt = (v) => (Math.abs(v - Math.round(v)) < 0.05 ? `${Math.round(v)}%` : `${v.toFixed(1)}%`);
const axis = (v) => Math.max(0, Math.min(100, ((v - AXIS_MIN) / (100 - AXIS_MIN)) * 100));

function benchmarkRow(name, what, n, base, tribos, total = false) {
  const b = pct(base, n);
  const t = pct(tribos, n);
  // The difference of the values as shown (97.5% - 94.5% reads +3.0, not the unrounded +2.9).
  const delta = Math.round(t * 10) / 10 - Math.round(b * 10) / 10;
  const deltaHtml = Math.abs(delta) >= 0.05
    ? `<span class="ml-1.5 font-mono text-xs ${delta > 0 ? "text-mint" : "text-rose"}">${delta > 0 ? "+" : "−"}${Math.abs(delta).toFixed(1)}</span>`
    : "";
  const [lo, hi] = [Math.min(axis(b), axis(t)), Math.max(axis(b), axis(t))];
  const label = `${name}: same model alone ${fmt(b)} (${base} of ${n}), Tribos ${fmt(t)} (${tribos} of ${n})`;
  const grid = [25, 50, 75].map((x) => `<span class="absolute inset-y-0 w-px bg-cream/[0.07]" style="left:${x}%"></span>`).join("");
  const ring = `box-shadow:0 0 0 2px ${SURFACE}`;
  const dot = (v, colour, who, k) =>
    `<span class="absolute top-1/2 size-3 -translate-x-1/2 -translate-y-1/2 rounded-full" style="left:${axis(v)}%;background:${colour};${ring}" title="${who}: ${fmt(v)} (${k} of ${n})"></span>`;
  // A tie is one split dot, so neither system's mark hides under the other's.
  const dots = base === tribos
    ? `<span class="absolute top-1/2 size-3.5 -translate-x-1/2 -translate-y-1/2 rounded-full" style="left:${axis(t)}%;background:linear-gradient(90deg, ${BASE_COLOUR} 50%, ${TRIBOS_COLOUR} 50%);${ring}" title="Both: ${fmt(t)} (${tribos} of ${n})"></span>`
    : dot(b, BASE_COLOUR, "Same model, alone", base) + dot(t, TRIBOS_COLOUR, "Tribos", tribos);
  return `          <tr class="${total ? "border-t border-cream/15 bg-cream/[0.03]" : ""}">
            <th scope="row" class="px-5 py-4 font-normal sm:px-6"><span class="block ${total ? "font-semibold" : "font-medium"}">${escapeHtml(name)}</span><span class="block text-sm text-dust">${escapeHtml(what)}</span></th>
            <td class="hidden px-3 py-4 text-right font-mono text-sm text-dust sm:table-cell">${n}</td>
            <td class="px-3 py-4 text-right tabular-nums text-sand">${fmt(b)}</td>
            <td class="py-4 pr-5 pl-3 text-right tabular-nums whitespace-nowrap sm:pr-3 ${total ? "font-semibold" : "font-medium"}">${fmt(t)}${deltaHtml}</td>
            <td class="hidden py-4 pr-5 pl-6 sm:pr-6 md:table-cell">
              <span class="relative block h-6" role="img" aria-label="${escapeHtml(label)}">${grid}
                <span class="absolute top-1/2 h-0.5 -translate-y-1/2 rounded-full bg-cream/25" style="left:${lo}%;width:${hi - lo}%"></span>
                ${dots}
              </span>
            </td>
          </tr>`;
}

function renderBenchmarks(data, page) {
  const rows = data.suites.map((s) => benchmarkRow(s.name, s.what, s.n, s.base, s.tribos));
  const n = data.suites.reduce((a, s) => a + s.n, 0);
  const base = data.suites.reduce((a, s) => a + s.base, 0);
  const tribos = data.suites.reduce((a, s) => a + s.tribos, 0);
  rows.push(benchmarkRow("All five", "paired, same problems for both", n, base, tribos, true));
  // The summary tiles are written in index.html: they must agree with the data.
  for (const expected of [`${tribos} of ${n}`, `${base} of ${n}`, fmt(pct(tribos, n)), fmt(pct(base, n)), `p = ${data.mcnemar_p}`]) {
    if (!page.includes(expected)) throw new Error(`benchmark tiles disagree with benchmarks.json: "${expected}" not on the page`);
  }
  return rows.join("\n");
}

// ---------------------------------------------------------------------------------------------------------------
// Pages
// ---------------------------------------------------------------------------------------------------------------

function renderTex(html) {
  return html.replace(/<tex>([\s\S]*?)<\/tex>/g, (_, tex) =>
    katex.renderToString(tex.replace(/&amp;/g, "&").replace(/&lt;/g, "<").replace(/&gt;/g, ">"), {
      throwOnError: true,
      output: "html",
    }),
  );
}

function fill(template, vars, partials) {
  let out = template.replace(/\{\{>\s*([\w-]+)\s*\}\}/g, (_, name) => {
    if (!(name in partials)) throw new Error(`unknown partial ${name}`);
    return partials[name];
  });
  out = out.replace(/\{\{\s*([\w-]+)\s*\}\}/g, (m, name) => {
    if (!(name in vars)) throw new Error(`unknown placeholder ${m}`);
    return vars[name];
  });
  return out;
}

function copyDir(from, to, filter = () => true) {
  fs.mkdirSync(to, { recursive: true });
  for (const entry of fs.readdirSync(from, { withFileTypes: true })) {
    const a = path.join(from, entry.name);
    const b = path.join(to, entry.name);
    if (entry.isDirectory()) copyDir(a, b, filter);
    else if (filter(entry.name)) fs.copyFileSync(a, b);
  }
}

async function buildCss(pages) {
  const input = fs.readFileSync(path.join(src, "styles.css"), "utf8");
  const tailwindDir = path.dirname(webRequire.resolve("tailwindcss/package.json"));
  const compiler = await compile(input, {
    base: src,
    // "tailwindcss" is the package's index.css; its own imports ("./theme.css") resolve next to it.
    loadStylesheet: async (id, base) => {
      const file = id === "tailwindcss" ? path.join(tailwindDir, "index.css") : path.resolve(base, id);
      return { path: file, base: path.dirname(file), content: fs.readFileSync(file, "utf8") };
    },
  });
  const scanner = new Scanner({
    sources: [
      { base: dist, pattern: "*.html", negated: false },
      { base: path.join(dist, "assets"), pattern: "site.js", negated: false },
    ],
  });
  const candidates = scanner.scan();
  let css = compiler.build(candidates);
  // Masks fetched from a file:// page are blocked, so the logo masks travel inside the CSS.
  for (const name of ["mark.png", "wordmark.png"]) {
    const data = fs.readFileSync(path.join(src, "assets", name)).toString("base64");
    css = css.split(`url("${name}")`).join(`url("data:image/png;base64,${data}")`);
  }
  const { code } = lightningcss.transform({
    filename: "site.css",
    code: Buffer.from(css),
    minify: true,
    targets: { chrome: 111 << 16, firefox: 128 << 16, safari: (16 << 16) | (4 << 8) },
  });
  fs.writeFileSync(path.join(dist, "assets", "site.css"), code);
  return { candidates: candidates.length, bytes: code.length, pages };
}

async function main() {
  fs.rmSync(dist, { recursive: true, force: true });
  fs.mkdirSync(path.join(dist, "assets"), { recursive: true });

  const releases = [
    ...parseChangelog(fs.readFileSync(path.join(src, "unreleased.md"), "utf8")),
    ...parseChangelog(fs.readFileSync(path.join(root, "CHANGELOG.md"), "utf8")),
  ].filter((r) => r.version || r.sections.some((s) => s.items.length));
  const latest = releases.find((r) => r.version);
  const version = latest ? latest.version : "0.0.0";

  const partials = Object.fromEntries(
    fs.readdirSync(path.join(src, "partials")).map((f) => [path.basename(f, ".html"), fs.readFileSync(path.join(src, "partials", f), "utf8")]),
  );
  const common = { version };
  const pages = [
    {
      file: "index.html",
      vars: {
        ...common,
        title: "Tribos · Hard questions, checked answers",
        description: "Tribos is a research partner for engineering, physics and mathematics. It does the work with real tools, then shows which claims were checked, and how.",
        changelog_teaser: renderTeaser(releases, version),
        benchmark_rows: renderBenchmarks(
          JSON.parse(fs.readFileSync(path.join(src, "benchmarks.json"), "utf8")),
          fs.readFileSync(path.join(src, "index.html"), "utf8"),
        ),
      },
    },
    {
      file: "changelog.html",
      vars: {
        ...common,
        title: "Changelog · Tribos",
        description: "What changed in Tribos, release by release.",
        changelog: releases.map((r) => renderRelease(r, version)).join("\n"),
        version_links: releases
          .map((r) => `        <a href="#${anchor(r)}" class="filter !text-sm">${escapeHtml(title(r))}</a>`)
          .join("\n"),
      },
    },
  ];
  for (const page of pages) {
    // Partials are filled with the page's own variables (the title in <head>, the version in the footer).
    const filledPartials = Object.fromEntries(Object.entries(partials).map(([k, v]) => [k, fill(v, page.vars, {})]));
    const html = renderTex(fill(fs.readFileSync(path.join(src, page.file), "utf8"), page.vars, filledPartials));
    fs.writeFileSync(path.join(dist, page.file), html);
  }

  copyDir(path.join(src, "assets"), path.join(dist, "assets"), (name) => !["mark.png", "wordmark.png"].includes(name));
  fs.copyFileSync(path.join(src, "site.js"), path.join(dist, "assets", "site.js"));
  const katexDist = path.dirname(webRequire.resolve("katex/dist/katex.min.css"));
  fs.mkdirSync(path.join(dist, "assets", "katex", "fonts"), { recursive: true });
  fs.copyFileSync(path.join(katexDist, "katex.min.css"), path.join(dist, "assets", "katex", "katex.min.css"));
  copyDir(path.join(katexDist, "fonts"), path.join(dist, "assets", "katex", "fonts"), (n) => n.endsWith(".woff2"));

  const css = await buildCss(pages.map((p) => p.file));
  console.log(`built ${pages.length} pages, ${releases.length} changelog entries, ${css.candidates} class candidates, site.css ${(css.bytes / 1024).toFixed(1)} KB -> ${path.relative(root, dist)}`);
}

main().catch((err) => {
  console.error(err);
  process.exit(1);
});
