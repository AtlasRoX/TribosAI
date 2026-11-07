# Tribos homepage

The project's homepage (`index.html`) and changelog (`changelog.html`): static HTML, Tailwind CSS v4, KaTeX rendered at
build time, no runtime framework.

## Build

```sh
cd web && npm ci && cd ..   # once: the build uses the Tailwind compiler and KaTeX installed for the web app
node website/build.mjs      # writes website/dist/
```

Open `website/dist/index.html` directly, or serve the folder:

```sh
python -m http.server 8080 --directory website/dist
```

## What the build does

- Fills each page in `src/` with the partials in `src/partials/` (`{{> nav}}`) and its placeholders (`{{version}}`).
- Renders every `<tex>...</tex>` with KaTeX, so formulas need no JavaScript.
- Builds the changelog from the repository's `CHANGELOG.md` (written by python-semantic-release) plus
  `src/unreleased.md`, the changes not yet released. Clear `src/unreleased.md` after a release.
- Compiles `src/styles.css` with Tailwind against the classes the built pages use, inlines the two logo masks and
  minifies the result into `dist/assets/site.css`.
- Copies the images, `site.js` and KaTeX's stylesheet and fonts into `dist/assets/`.

## Deploy

`dist/` is a self-contained static site: publish it with GitHub Pages, Netlify, Cloudflare Pages or any static host.

## Content rules

- Benchmark figures come only from `src/benchmarks.json` (the paired run in
  `docs/benchmarks/2026-11-06-failure-analysis.md`); the build fails if the summary tiles disagree with it. Never show
  GPQA question text.
- Every claim matches the README and the code; the version in the footer comes from `CHANGELOG.md`.
- No model vendor, model name or outside product is named on the site (describe the capability instead: "a formal proof
  checker", "the same language model"). `build.mjs` (`REDACT`) strips such names from older changelog lines.
- Images carry no such names either: the YouTube thumbnail and the README banner do, so the site uses app screenshots.
