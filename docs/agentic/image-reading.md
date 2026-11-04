# Reading question images

A question sent as a photo, scan, screenshot or PDF is turned into Markdown with LaTeX before it is solved
(`POST /api/vision/read`, `tribos/vision/`). Mathematics is where single engines fail. OCR reads `(∀)i∈ℕ*` as
`(V)ieN*` and `a_i ≡ a_j (mod a_k)` as `a1 = a3 (mod ax)`, and a vision model on its own sometimes drops a line or
misreads an index. So images are read by an ensemble, and every engine's output is checked against the others.

## The pipeline

| Step | Engine | What it contributes |
| --- | --- | --- |
| 1a | **Indra OCR** (`ocr.py`; local CPU, ONNX) | Layout and lines, with formulas as LaTeX drafts |
| 1b | **Tesseract** (`tesseract.py`; local) | Plain words, each with a confidence (printed words 90+, garbled math near 0) |
| 2a | **Vision reading, image only** (`vlm.transcribe_remote`) | Started at once, alongside OCR |
| 2b | **Vision reading, with both OCR drafts** | A second reading by the same model with different input: it catches many of 2a's slips, but the two are not independent |
| 3 | **Agreement** (`consensus.compare`) | The two readings are compared in canonical form |
| 4 | **Review** (`vlm.review_remote`) | Only when the readings differ: the model looks at the image again at each listed difference |
| 5 | **Coverage gate and repair** (`consensus.coverage`, `vlm.repair_remote`) | The result must keep the words that are surely in the image |

**Canonical form.** Unicode math becomes LaTeX commands (`∀` → `\forall`), aliases get one spelling (`\ne` →
`\neq`, `\le` → `\leq`, `\bmod`/`\pmod{m}` → `(mod m)`), and grouping braces, spacing, `\left`/`\right`,
`\text{}` wrappers and Markdown emphasis are dropped. Set braces count only where they are printed: `{a_n}` in text
equals `\{a_n\}` in math. What still differs after this is a real difference in what was read (`a_i` against `a_1`,
`\equiv` against `=`).

**Words surely in the image.** These are the words Tesseract read with confidence ≥ 80 that Indra also read; when
there are too few of them, Tesseract's confident words alone, then Indra's words of four letters or more. Digits
glued to letters (`a1`, a misread subscript) and garbled tokens never count. A transcription has to keep at least
75% of these words. One that keeps fewer is read again once, and the model is told which words are missing. If the
second reading still misses them, the OCR text is shown with a warning, so no line is lost silently. Before this
gate existed, garbled OCR tokens counted as required words, and an exact transcription was rejected because it
"kept 40%".

**Independence.** Both vision readings and the review come from one model, so their agreement is self-consistency, not independent confirmation. The independent evidence is the two OCR engines, which the coverage gate uses.

**Outcome.** Each reading reports `consensus`:
- `agreed`: the two readings (same model, different inputs) matched;
- `settled`: they differed, and a look at the image decided each place;
- `unsettled`: the review was unusable, so the reader is warned;
- `single`: there was only one usable reading.

The reading also lists the `differences` that were found, and the `unconfirmed_numbers` that no OCR engine read. The
image viewer in the composer shows these.

**Small images.** An image whose long side is under 1000 px is enlarged for the vision model, by up to 3x to at
most 1280 px. A vision encoder samples its input at a fixed resolution. Before this change, a 464×50 screenshot gave
each glyph a few pixels, and the two readings misread different symbols (`x_i^n` for `x_i`, `+\infty` for `\infty`).
With the enlargement, the same images read exactly. The OCR engines upscale small images for the same reason.

**Latency** (measured on this machine against the cloud model):
- Indra takes about 0.3 s and Tesseract about 0.5 s, in parallel threads.
- A reading takes 3.5 to 7 s when the two readings agree.
- Settling a difference adds 3 to 8 s.
- The first image after a restart also loads Indra's models, which takes about 2 s.

`TRIBOS_VISION_CROSSCHECK=0` turns off the second reading and the review.

## Settings

| Variable | Default | Purpose |
| --- | --- | --- |
| `TRIBOS_VISION_PROVIDER` | `remote` | `remote` (the full ensemble), `ollama` (one local model reading), `ocr` (OCR only; the image stays on the machine) |
| `TRIBOS_VISION_MODEL` | `muse-spark-1.3` | The cloud vision model |
| `TRIBOS_VISION_CROSSCHECK` | `true` | The second reading and the review |
| `TRIBOS_VISION_TESSERACT` | unset | The Tesseract executable. It is found on PATH, in Scoop or in Program Files when unset; `off` disables it |
| `TRIBOS_VISION_TESSERACT_LANG` | `eng` | Tesseract language models, for example `eng+deu` |
| `TRIBOS_VISION_OCR_MATH` | `true` | Indra's math models |

## Installing Tesseract

Tesseract is optional: without it, the gate falls back to Indra's longer words. With it, the gate is far more
reliable.

- **Windows:** run `scoop install tesseract`. Then put `eng.traineddata` from
  [tessdata_best](https://github.com/tesseract-ocr/tessdata_best) in `~/scoop/persist/tesseract/tessdata/`.
  Alternatively, `winget install UB-Mannheim.TesseractOCR` installs it to `C:\Program Files\Tesseract-OCR`.
- **Debian/Ubuntu:** run `apt-get install tesseract-ocr tesseract-ocr-eng`. The backend Docker image already
  includes these.
- **macOS:** run `brew install tesseract`.

`GET /api/vision/status` reports `word_recognition: true` once Tesseract and its language model are found.

## Tests

- `tests/test_feat_vision_ensemble.py` covers the reported failure, using the real OCR output. It also covers
  canonical agreement and real differences, the review and its guard, the repair, and partial failures.
- `tests/test_vision.py` covers the endpoint, the PDFs, the cache and the fallbacks.
