"""Image reading ensemble: two OCR engines ground the words, two vision readings must agree on the mathematics.

The production failure behind these tests: an olympiad problem with quantifiers, set membership and indexed
congruences. Indra OCR read "(∀)i∈ℕ*" as "(V)ieN*" and "a_i ≡ a_j (mod a_k)" as "a1 = a3 (mod ax)"; the vision model
transcribed it exactly, but the old check counted the garbled OCR tokens as words the transcription had to keep (it
kept 40%), threw the correct transcription away and showed the OCR text.
"""

from __future__ import annotations

import asyncio
import io

import pytest

from tribos.vision import consensus, reader, tesseract, vlm

# What Indra OCR (1.1.2 + math) actually read from the user's image.
INDRA_GARBLED = ("Find all integer sequences (an}nn. defined as follows: (I) (V)ieN*, (3)j, keN*, ixj+kxi, such that "
                 "a1 = a3 (mod ax). (II) (V)icN*, (3)j, keN*, ixjxkzi, such that a3 = ax (mod a1).")
# Tesseract 5.5.3 (eng, best) on the same problem: words with their confidences.
TESS_WORDS = [("Find", 96), ("all", 95), ("integer", 95), ("sequences", 93), ("{a,}", 21), ("e+", 0), ("defined", 95),
              ("as", 96), ("follows:", 96), ("(I)", 76), ("(VENT,", 0), ("(3)j.KELT,", 19), ("ijk,", 15),
              ("such", 96), ("that", 94), ("a;", 93), ("=", 93), ("a;", 81), ("(mod", 94), ("ay).", 83), ("(ID)", 63),
              ("(V)i€lT*,", 0), ("(3)j.kelT*,", 6), ("i#j#k#A,", 9), ("such", 96), ("that", 95), ("=a", 11),
              ("(mod", 92), ("a;).", 91)]
# The vision model's transcription, which is exact.
CORRECT = (r"Find all integer sequences $\{a_n\}_{n\in\mathbb{N}^*}$ defined as follows:" "\n\n"
           r"(I) $(\forall)i\in\mathbb{N}^*$, $(\exists)j,k\in\mathbb{N}^*$, $i\neq j\neq k\neq i$, such that "
           r"$a_i \equiv a_j \pmod{a_k}$." "\n\n"
           r"(II) $(\forall)i\in\mathbb{N}^*$, $(\exists)j,k\in\mathbb{N}^*$, $i\neq j\neq k\neq i$, such that "
           r"$a_j \equiv a_k \pmod{a_i}$.")


def _tess() -> tesseract.TessResult:
    words = [tesseract.TessWord(t, float(c)) for t, c in TESS_WORDS]
    return tesseract.TessResult(text=" ".join(w.text for w in words), words=words, engine="Tesseract test")


@pytest.fixture(autouse=True)
def _isolated(monkeypatch):
    reader._CACHE.clear()
    monkeypatch.setenv("TRIBOS_VISION_PROVIDER", "remote")
    monkeypatch.setenv("TRIBOS_VISION_CROSSCHECK", "1")
    yield
    reader._CACHE.clear()


def _png() -> bytes:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig = plt.figure(figsize=(6, 1), dpi=100)
    fig.text(0.02, 0.4, "Find all integer sequences", fontsize=14)
    buf = io.BytesIO()
    fig.savefig(buf, format="png", facecolor="white")
    plt.close(fig)
    return buf.getvalue()


def _fake_ocr(monkeypatch, text: str = INDRA_GARBLED, tess: tesseract.TessResult | None = None):
    class Result:
        markdown = text
        lines: list = []
        engine = "Indra OCR test"
        mean_conf = 0.89

    monkeypatch.setattr(reader.ocr, "available", lambda: True)
    monkeypatch.setattr(reader.ocr, "read", lambda image: Result())
    monkeypatch.setattr(reader.tesseract, "read", lambda image: tess)


# --- the coverage check counts only words that are surely in the image -------------------------------------------


def test_garbled_ocr_math_no_longer_rejects_an_exact_transcription():
    reference = consensus.reliable_tokens(INDRA_GARBLED, _tess())
    assert {"find", "integer", "sequences", "defined", "follows", "such", "that", "mod"} <= set(reference)
    assert not {"ien", "kxi", "ixj", "ixjxkzi"} & set(reference)
    assert consensus.coverage(CORRECT, reference) == 1.0


def test_without_tesseract_indras_short_garbled_tokens_do_not_count():
    reference = consensus.reliable_tokens(INDRA_GARBLED, None)
    assert consensus.coverage(CORRECT, reference) >= 0.75


def test_a_transcription_that_drops_a_line_still_fails_the_check():
    text = ("Problem 3. A ball is thrown upward at 20 m/s. Find the maximum height reached by the ball. "
            "Then solve the quadratic equation for both roots and verify each one.")
    dropped = "Problem 3. A ball is thrown upward at 20 m/s."
    reference = consensus.reliable_tokens(text, None)
    assert consensus.coverage(dropped, reference) < reader.MIN_COVERAGE
    assert "quadratic" in consensus.missing(dropped, reference)


# --- two readings are compared in canonical form ------------------------------------------------------------------


@pytest.mark.parametrize("first, second", [
    (r"$i \ne j$", r"$i\neq j$"),
    ("{a_n}_{n∈ℕ*}", r"$\{a_n\}_{n\in\mathbb{N}^*}$"),
    (r"$a_{i} \equiv a_j \pmod{a_k}$", r"$a_i\equiv a_j\ (\bmod a_k)$"),
    (r"$\left( x \right) \le 1$", r"$(x)\leq 1$"),
    (r"**(I)** $(\forall) i$", r"(I) $(∀)i$"),
    (r"$$\sum_{i=1}^{n} x_i$$", r"$\sum_{i=1}^n x_{i}$"),
    (r"$x \in \mathbb N$", r"$x\in\mathbb{N}$"),
])
def test_notation_variants_of_one_reading_agree(first, second):
    assert consensus.compare(first, second).agree


@pytest.mark.parametrize("first, second", [
    (r"$a_i \equiv a_j$", r"$a_1 \equiv a_3$"),
    (r"$a_i \equiv a_j$", r"$a_i = a_j$"),
    (r"$(\forall)i$", r"$(V)i$"),
    (r"$i \in \mathbb{N}$", r"$i e N$"),
    (r"$x^2 + 1$", r"$x^3 + 1$"),
])
def test_a_real_difference_in_what_was_read_is_found(first, second):
    agreement = consensus.compare(first, second)
    assert not agreement.agree and agreement.differences


def test_tesseract_tsv_is_parsed_into_lines_and_word_confidences():
    tsv = ("level\tpage_num\tblock_num\tpar_num\tline_num\tword_num\tleft\ttop\twidth\theight\tconf\ttext\n"
           "1\t1\t0\t0\t0\t0\t0\t0\t9\t9\t-1\t\n"
           "5\t1\t1\t1\t1\t1\t0\t0\t9\t9\t96.2\tFind\n"
           "5\t1\t1\t1\t1\t2\t0\t0\t9\t9\t95\tall\n"
           "5\t1\t1\t1\t2\t1\t0\t0\t9\t9\t11\t(V)ieN*,\n")
    text, words = tesseract.parse_tsv(tsv)
    assert text == "Find all\n(V)ieN*,"
    assert [(w.text, w.conf) for w in words] == [("Find", 96.2), ("all", 95.0), ("(V)ieN*,", 11.0)]


def test_tesseract_can_be_turned_off(monkeypatch):
    monkeypatch.setenv("TRIBOS_VISION_TESSERACT", "off")
    assert tesseract.binary() is None and not tesseract.available() and tesseract.read(None) is None


def test_the_prompts_name_the_ocr_confusions_and_keep_indices_as_letters():
    prompt = vlm._prompt("draft")
    assert r"\forall read as V" in prompt and r"\mathbb{N}" in prompt
    assert "a_i, a_j, a_k are never a_1, a_3, a_x" in prompt
    assert vlm.output_budget("") == 4096  # a blind reading of unknown length is never cut off


# --- the ensemble end to end (engines faked) ----------------------------------------------------------------------


def test_the_reported_image_is_read_exactly_when_both_readings_agree(monkeypatch):
    _fake_ocr(monkeypatch, tess=_tess())
    drafts: list[str] = []

    async def vision(png, draft, model_name=None):
        drafts.append(draft)
        return CORRECT, "vision-test"

    monkeypatch.setattr(reader.vlm, "transcribe_remote", vision)
    reading = asyncio.run(reader.read_image(_png(), "image/png", "q.png"))
    assert reading.text == CORRECT and reading.consensus == "agreed" and reading.vision_checked
    assert reading.engines == ["text recognition", "word recognition", "vision check", "vision cross-check"]
    assert not any("left out" in w for w in reading.warnings)
    # One reading from the image alone, one with both OCR drafts.
    assert drafts[0] == "" and "Reading 1 (layout and math)" in drafts[1] and "Reading 2 (words only" in drafts[1]


def test_readings_that_differ_are_settled_by_looking_at_the_image_again(monkeypatch):
    _fake_ocr(monkeypatch, tess=_tess())
    wrong = CORRECT.replace(r"a_i \equiv a_j \pmod{a_k}", r"a_1 \equiv a_j \pmod{a_k}")

    async def vision(png, draft, model_name=None):
        return (CORRECT if draft else wrong), "vision-test"

    seen: dict = {}

    async def review(png, first, second, differences, words=None, model_name=None):
        seen.update(first=first, second=second, differences=differences, words=words)
        return CORRECT, "vision-test"

    monkeypatch.setattr(reader.vlm, "transcribe_remote", vision)
    monkeypatch.setattr(reader.vlm, "review_remote", review)
    reading = asyncio.run(reader.read_image(_png(), "image/png", "q.png"))
    assert reading.text == CORRECT and reading.consensus == "settled" and "vision review" in reading.engines
    assert seen["first"] == CORRECT and seen["second"] == wrong
    assert any("_ i" in a and "_ 1" in b for a, b in seen["differences"])
    assert "sequences" in seen["words"] and reading.differences


def test_a_review_that_strays_from_both_readings_is_not_used(monkeypatch):
    _fake_ocr(monkeypatch, tess=_tess())
    wrong = CORRECT.replace("a_i", "a_1")

    async def vision(png, draft, model_name=None):
        return (CORRECT if draft else wrong), "vision-test"

    async def review(*_a, **_k):
        return "The answer is 42.", "vision-test"

    monkeypatch.setattr(reader.vlm, "transcribe_remote", vision)
    monkeypatch.setattr(reader.vlm, "review_remote", review)
    reading = asyncio.run(reader.read_image(_png(), "image/png", "q.png"))
    assert reading.text == CORRECT and reading.consensus == "unsettled"
    assert any("could not be settled" in w for w in reading.warnings)


def test_a_reading_that_drops_lines_gives_way_to_the_complete_one(monkeypatch):
    _fake_ocr(monkeypatch, tess=_tess())
    first_line = CORRECT.split("\n\n")[0]

    async def vision(png, draft, model_name=None):
        return (first_line if draft else CORRECT), "vision-test"

    async def review(*_a, **_k):
        raise AssertionError("no review is needed when one reading left out words")

    monkeypatch.setattr(reader.vlm, "transcribe_remote", vision)
    monkeypatch.setattr(reader.vlm, "review_remote", review)
    reading = asyncio.run(reader.read_image(_png(), "image/png", "q.png"))
    assert reading.text == CORRECT and reading.consensus == "single"


def test_a_transcription_missing_words_is_read_again_before_falling_back(monkeypatch):
    _fake_ocr(monkeypatch, tess=_tess())
    first_line = CORRECT.split("\n\n")[0]
    asked: dict = {}

    async def vision(png, draft, model_name=None):
        return first_line, "vision-test"

    async def repair(png, previous, missing, draft, model_name=None):
        asked.update(previous=previous, missing=missing)
        return CORRECT, "vision-test"

    monkeypatch.setattr(reader.vlm, "transcribe_remote", vision)
    monkeypatch.setattr(reader.vlm, "repair_remote", repair)
    reading = asyncio.run(reader.read_image(_png(), "image/png", "q.png"))
    assert reading.text == CORRECT and "vision repair" in reading.engines and reading.vision_checked
    assert asked["previous"] == first_line and "such" in asked["missing"]


def test_a_failed_second_reading_leaves_the_first(monkeypatch):
    _fake_ocr(monkeypatch, tess=_tess())

    async def vision(png, draft, model_name=None):
        if draft:
            raise TimeoutError("provider timeout")
        return CORRECT, "vision-test"

    monkeypatch.setattr(reader.vlm, "transcribe_remote", vision)
    reading = asyncio.run(reader.read_image(_png(), "image/png", "q.png"))
    assert reading.text == CORRECT and reading.consensus == "single" and reading.vision_checked


def test_the_cross_check_can_be_turned_off(monkeypatch):
    monkeypatch.setenv("TRIBOS_VISION_CROSSCHECK", "0")
    _fake_ocr(monkeypatch, tess=_tess())
    calls: list[str] = []

    async def vision(png, draft, model_name=None):
        calls.append(draft)
        return CORRECT, "vision-test"

    monkeypatch.setattr(reader.vlm, "transcribe_remote", vision)
    reading = asyncio.run(reader.read_image(_png(), "image/png", "q.png"))
    assert calls == [""] and reading.text == CORRECT and reading.consensus == "single"


def test_a_small_screenshot_is_enlarged_for_the_vision_model_and_a_large_one_reduced():
    import cv2
    import numpy as np

    def side(png: bytes) -> tuple[int, int]:
        h, w = cv2.imdecode(np.frombuffer(png, dtype=np.uint8), cv2.IMREAD_COLOR).shape[:2]
        return w, h

    # A 464x50 screenshot: two readings misread different symbols until it was enlarged.
    assert side(reader._png(np.full((50, 464, 3), 255, dtype=np.uint8))) == (1280, 137)
    assert side(reader._png(np.full((40, 200, 3), 255, dtype=np.uint8))) == (600, 120)  # at most 3x
    assert side(reader._png(np.full((1000, 3000, 3), 255, dtype=np.uint8))) == (1280, 426)
    assert side(reader._png(np.full((800, 1100, 3), 255, dtype=np.uint8))) == (1100, 800)  # left as it is


@pytest.mark.skipif(not tesseract.available(), reason="Tesseract is not installed")
def test_tesseract_reads_printed_words_with_high_confidence():
    import cv2
    import numpy as np

    image = cv2.imdecode(np.frombuffer(_png(), dtype=np.uint8), cv2.IMREAD_COLOR)
    result = tesseract.read(image)
    assert result is not None
    assert {"Find", "integer", "sequences"} <= set(result.confident_words())
