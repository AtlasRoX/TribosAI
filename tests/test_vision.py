"""Image input: Indra OCR reads a question image, the endpoint guards its upload, and transcriptions join the question."""

from __future__ import annotations

import asyncio
import io

import pytest

from tribos.vision import reader


@pytest.fixture(autouse=True)
def _fresh_reading_cache():
    """Readings are cached by the file's bytes; each test reads its image afresh."""
    reader._CACHE.clear()
    yield
    reader._CACHE.clear()


def _question_png() -> bytes:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig = plt.figure(figsize=(8, 1.6), dpi=150)
    fig.text(0.02, 0.6, "A spring has k = 50 N/m and mass m = 2 kg.", fontsize=14)
    fig.text(0.02, 0.2, "Find the natural frequency.", fontsize=14)
    buf = io.BytesIO()
    fig.savefig(buf, format="png", facecolor="white")
    plt.close(fig)
    return buf.getvalue()


def test_numbers_the_ocr_never_read_are_flagged():
    ocr_text = "with $x ( 0 ) = 0 . 1$ m, k = 50 N/m"
    assert reader.unconfirmed_numbers("k = 50 N/m, x(0) = 0.1 m, c = 3", ocr_text) == ["3"]


def test_a_reading_shows_reading_steps_never_engine_or_model_names(monkeypatch):
    monkeypatch.setenv("TRIBOS_VISION_PROVIDER", "nim")
    monkeypatch.setattr(reader.ocr, "available", lambda: False)

    async def fake_nim(png: bytes, draft: str, model_name: str | None = None) -> tuple[str, str]:
        return "Find $x$.", "vendor/some-vision-model-120b"

    monkeypatch.setattr(reader.vlm, "transcribe_remote", fake_nim)
    shown = str(asyncio.run(reader.read_image(_question_png(), "image/png", "q.png")).to_dict()).lower()
    assert "some-vision-model" not in shown and "vendor" not in shown


def test_image_transcriptions_join_the_question_text():
    block = reader.image_context_block([{"name": "q.png", "text": "Find $x(t)$."}, {"name": "empty", "text": " "}])
    assert block == "Attached image 1 (q.png), transcribed:\nFind $x(t)$."


def test_an_unreadable_upload_is_refused_with_a_reason():
    with pytest.raises(reader.ImageReadError):
        asyncio.run(reader.read_image(b"not an image", "image/png", "x.png"))
    with pytest.raises(reader.ImageReadError):
        asyncio.run(reader.read_image(b"GIF89a", "image/gif", "x.gif"))


@pytest.mark.skipif(not reader.ocr.available(), reason="indra-ocr is not installed")
def test_a_question_image_is_read_by_indra_ocr_alone_in_ocr_mode(monkeypatch):
    monkeypatch.setenv("TRIBOS_VISION_OCR_MATH", "0")  # the text models only: a small download, fast
    monkeypatch.setenv("TRIBOS_VISION_PROVIDER", "ocr")  # the image never leaves the machine
    reading = asyncio.run(reader.read_image(_question_png(), "image/png", "q.png"))
    assert "50" in reading.text and "natural frequency" in reading.text.lower()
    assert reading.engines == ["text recognition"] and not reading.vision_checked
    assert any("Only text recognition read this image" in w for w in reading.warnings)


def test_the_nim_vision_model_corrects_the_ocr_draft_and_unconfirmed_numbers_are_listed(monkeypatch):
    monkeypatch.setenv("TRIBOS_VISION_PROVIDER", "nim")
    monkeypatch.setattr(reader.ocr, "available", lambda: True)

    class FakeResult:
        markdown = "## A spring: mx + kx = 0 with k = 50"
        lines = []
        engine = "Indra OCR test"
        mean_conf = 0.9

    monkeypatch.setattr(reader.ocr, "read", lambda image: FakeResult())
    drafts: list[str] = []

    async def fake_nim(png: bytes, draft: str, model_name=None):
        drafts.append(draft)
        return r"$m\ddot{x} + kx = 0$ with $k = 50$ and $c = 3$", "nvidia/nemotron-3.5-super-vl-120b-a12b"

    monkeypatch.setattr(reader.vlm, "transcribe_remote", fake_nim)
    reading = asyncio.run(reader.read_image(_question_png(), "image/png", "q.png"))
    # The model is called alongside OCR (no draft for an image); the OCR text then checks its numbers.
    assert drafts == [""]
    assert reading.text.startswith(r"$m\ddot{x}") and reading.unconfirmed_numbers == ["3"]
    assert reading.engines == ["text recognition", "vision check"] and reading.vision_checked


def test_a_failed_nim_call_falls_back_to_a_local_vision_model(monkeypatch):
    monkeypatch.setenv("TRIBOS_VISION_PROVIDER", "nim")
    monkeypatch.setattr(reader.ocr, "available", lambda: False)

    async def failing(*_a, **_k):
        raise TimeoutError("NIM down")

    monkeypatch.setattr(reader.vlm, "transcribe_remote", failing)
    monkeypatch.setattr(reader.vlm, "local_model", lambda: "qwen2.5vl:7b")
    drafts: list[str] = []

    async def fake_transcribe(png: bytes, draft: str, model: str) -> str:
        drafts.append(draft)
        return "```markdown\n$m\\ddot{x} + kx = 0$ with $k = 50$\n```"

    monkeypatch.setattr(reader.vlm, "transcribe_local", fake_transcribe)
    reading = asyncio.run(reader.read_image(_question_png(), "image/png", "q.png"))
    assert reading.text == "$m\\ddot{x} + kx = 0$ with $k = 50$"  # code fences removed
    assert reading.vision_checked and reading.engines == ["vision check"]
    assert any("vision check could not be completed" in w for w in reading.warnings)


def test_the_chat_request_solves_the_message_with_its_image_text():
    from app.backend.main import ChatRequest

    req = ChatRequest(message="Solve the attached problem.", image_context=[{"name": "q.png", "text": "y'' + y = 0"}])
    assert req.full_message == "Solve the attached problem.\n\nAttached image 1 (q.png), transcribed:\ny'' + y = 0"
    assert ChatRequest(message="Hi").full_message == "Hi"


def test_the_read_endpoint_authenticates_and_refuses_non_images_before_reading(monkeypatch):
    from fastapi.testclient import TestClient

    from app.backend.main import app

    monkeypatch.delenv("TRIBOS_AUTH_MODE", raising=False)
    monkeypatch.delenv("TRIBOS_JWT_SECRET", raising=False)
    monkeypatch.setenv("TRIBOS_API_TOKENS", "alice-token:alice")
    client = TestClient(app)
    files = {"file": ("a.txt", b"hello", "text/plain")}
    assert client.post("/api/vision/read", files=files).status_code == 401
    auth = {"Authorization": "Bearer alice-token"}
    res = client.post("/api/vision/read", files=files, headers=auth)
    assert res.status_code == 415 and res.json()["reason"] == "unsupported_type"
    status = client.get("/api/vision/status", headers=auth).json()
    assert status["accepted_types"] and "model" not in str(status).lower()


def test_ocr_layout_headings_are_plain_question_lines():
    assert reader.question_text("## Problem 3. A spring\n\n## $mx = F$\n\nwith k = 50") == "Problem 3. A spring\n\n$mx = F$\n\nwith k = 50"


def test_a_latex_transcription_parses_to_the_same_ode_as_the_typed_question():
    from tribos.axiom.problem import parse_problem

    transcribed = (
        r"$$m\ddot{x} + c\dot{x} + kx = F_0\cos(\omega t)$$ with $m = 2 \text{ kg}, c = 3 \text{ N s/m}, "
        r"k = 50 \text{ N/m}, F_0 = 10 \text{ N}, \omega = 4 \text{ rad/s}$, $x(0) = 0.1 \text{ m and } "
        r"\dot{x}(0) = 0.$ Find the steady-state amplitude."
    )
    q = "Solve the problem in the attached image.\n\n" + reader.image_context_block([{"name": "q.png", "text": transcribed}])
    spec = parse_problem(q)
    assert spec.kind == "ode" and spec.expression == "(2) x'' + (3) x' + (50) x = (10) cos((4) t)"
    assert spec.ics == {"x(0)": "0.1", "x'(0)": "0"} and not spec.unaccounted


_IMO_1960_2 = [
    "IMO 1960 Problem 2\n\nSolve\n\n$$\\frac{4x^2}{(1-\\sqrt{2x+1})^2} < 2x + 9.$$",
    "# IMO 1960 Problem 2\n\nSolve\n\n$$\n\\frac{4x^{2}}{\\left(1-\\sqrt{2x+1}\\right)^{2}}<2x+9.\n$$\n\n"
    "Figure: A logo with four interlocking colored rings and a black infinity symbol.",
    "**IMO 1960, Problem 2.** Solve $\\dfrac{4x^2}{(1-\\sqrt{2x+1})^2} < 2x+9$.",
]


@pytest.mark.parametrize("transcribed", _IMO_1960_2)
def test_an_image_of_a_labelled_inequality_is_solved_as_that_inequality(transcribed):
    """"solve" + an image of "IMO 1960 Problem 2 / Solve 4x^2/(1-sqrt(2x+1))^2 < 2x+9": the heading's numbers and the
    attachment header are framing, not part of the problem (they made the parser solve "1960", skip the inequality and
    send the run to literature search)."""
    from tribos.agents.deliverables import requested_items
    from tribos.agents.evidence_need import assess_evidence_need
    from tribos.axiom.agent import solve_math_problem
    from tribos.axiom.problem import parse_problem

    q = "solve\n\n" + reader.image_context_block([{"name": "image.png", "text": transcribed}])
    spec = parse_problem(q)
    assert spec.kind == "inequality" and spec.variable == "x" and not spec.unaccounted, spec.to_dict()
    assert assess_evidence_need(q).kind == "closed_computation"  # no literature or web search for it
    assert not any("transcribed" in i["item"] for i in requested_items(q))
    run = asyncio.run(solve_math_problem(q))
    assert run.status == "verified"
    assert run.answer["solution_set"] == "Union(Interval.Ropen(-1/2, 0), Interval.open(0, 45/8))"


@pytest.mark.skipif(not reader.ocr.available(), reason="indra-ocr is not installed")
def test_a_two_page_pdf_is_read_page_by_page(monkeypatch):
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.backends.backend_pdf import PdfPages

    monkeypatch.setenv("TRIBOS_VISION_OCR_MATH", "0")
    monkeypatch.setenv("TRIBOS_VISION_PROVIDER", "ocr")
    buf = io.BytesIO()
    with PdfPages(buf) as pdf:
        for line in ("A spring has stiffness k = 50 N/m.", "Find the period for a mass of 2 kg."):
            fig = plt.figure(figsize=(7, 1.2))
            fig.text(0.03, 0.4, line, fontsize=16)
            pdf.savefig(fig)
            plt.close(fig)
    reading = asyncio.run(reader.read_image(buf.getvalue(), "application/pdf", "sheet.pdf"))
    assert reading.pages == 2
    assert "**Page 1**" in reading.text and "**Page 2**" in reading.text
    assert "50" in reading.text and "period" in reading.text.lower()


def test_a_transcription_that_drops_lines_is_replaced_by_the_ocr_reading(monkeypatch):
    """The vision model once returned only the first question of three; no line may be lost silently."""
    monkeypatch.setenv("TRIBOS_VISION_PROVIDER", "nim")
    monkeypatch.setattr(reader.ocr, "available", lambda: True)

    class FakeResult:
        markdown = ("Problem 3. A ball is thrown upward at 20 m/s.\nFind the maximum height. Use g = 9.81 m/s^2.\n"
                    "Solve x^2 - 5x + 6 = 0 for x.")
        lines = []
        engine = "Indra OCR test"
        mean_conf = 0.96

    monkeypatch.setattr(reader.ocr, "read", lambda image: FakeResult())

    async def dropping_nim(png: bytes, draft: str, model_name=None):
        return "Problem 3. A ball is thrown upward at 20 m/s.", "nim"

    monkeypatch.setattr(reader.vlm, "transcribe_remote", dropping_nim)
    reading = asyncio.run(reader.read_image(_question_png(), "image/png", "q.png"))
    assert "Solve x^2 - 5x + 6 = 0" in reading.text and not reading.vision_checked
    assert any("left out part of the text" in w for w in reading.warnings)
    # A faithful LaTeX transcription (the model's real output for this image) keeps the draft's words and numbers.
    full = ("Problem 3. A ball is thrown upward at 20 m/s.\nFind the maximum height. Use $g = 9.81 \\text{ m/s}^2$.\n"
            "Solve $x^2 - 5x + 6 = 0$ for $x$.")
    assert reader.coverage(full, FakeResult.markdown) >= 0.95
    assert reader.coverage("Problem 3. A ball is thrown upward at 20 m/s.", FakeResult.markdown) < 0.75


def test_a_pdf_with_a_text_layer_skips_ocr_and_uses_the_layer_as_the_draft(monkeypatch):
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.backends.backend_pdf import PdfPages

    monkeypatch.setenv("TRIBOS_VISION_PROVIDER", "nim")

    def no_ocr(image):
        raise AssertionError("OCR must not run on a page that has a text layer")

    monkeypatch.setattr(reader.ocr, "read", no_ocr)
    drafts: list[str] = []

    async def fake_nim(png: bytes, draft: str, model_name=None):
        drafts.append(draft)
        return draft.replace("k = 50", "$k = 50$"), "nim"

    monkeypatch.setattr(reader.vlm, "transcribe_remote", fake_nim)
    buf = io.BytesIO()
    with PdfPages(buf) as pdf:
        for line in ("A spring has stiffness k = 50 N/m and a mass of 2 kg attached.",
                     "Find the period of oscillation and the maximum speed of the mass."):
            fig = plt.figure(figsize=(8, 1.2))
            fig.text(0.03, 0.4, line, fontsize=14)
            pdf.savefig(fig)
            plt.close(fig)
    reading = asyncio.run(reader.read_image(buf.getvalue(), "application/pdf", "sheet.pdf"))
    assert reading.pages == 2 and len(drafts) == 2
    assert any("stiffness" in d for d in drafts) and "$k = 50$" in reading.text
    assert "text layer" in reading.engines and "text recognition" not in reading.engines


def test_the_vision_model_transcribes_with_thinking_off(monkeypatch):
    """With thinking on, the model spent 75 s reasoning and returned nothing; transcription needs no reasoning."""
    from tribos.utils.llm import llm_factory
    from tribos.vision import vlm

    seen: dict = {}

    class FakeLLM:
        async def ainvoke(self, messages):
            class R:
                content = "text"
            return R()

    def fake_get_llm(**kwargs):
        seen.update(kwargs)
        return FakeLLM()

    monkeypatch.setattr(llm_factory, "get_llm", fake_get_llm)
    out, _ = asyncio.run(vlm.transcribe_remote(b"png", "a short draft"))
    assert out == "text" and seen["reasoning_effort"] == "minimal" and 1024 <= seen["max_tokens"] <= 4096


@pytest.mark.parametrize("noise", ["Figure: None", "Figure: The image contains only text; there is no figure, diagram, graph, or table.",
                                   "**Figure:** none", "Figure: There is no figure."])
def test_an_empty_figure_section_is_dropped(noise):
    assert reader._strip_fences(f"Q1. Find x.\n\n{noise}") == "Q1. Find x."
    kept = "Q1. Find x.\n\nFigure: a right triangle with legs 3 and 4."
    assert reader._strip_fences(kept) == kept


def test_a_second_read_of_the_same_image_comes_from_the_cache(monkeypatch):
    monkeypatch.setenv("TRIBOS_VISION_PROVIDER", "nim")
    monkeypatch.setattr(reader.ocr, "available", lambda: False)
    calls: list[int] = []

    async def fake_nim(png: bytes, draft: str, model_name=None):
        calls.append(1)
        return "A spring has $k = 50$ N/m.", "nim"

    monkeypatch.setattr(reader.vlm, "transcribe_remote", fake_nim)
    png = _question_png()
    first = asyncio.run(reader.read_image(png, "image/png", "a.png"))
    second = asyncio.run(reader.read_image(png, "image/png", "b.png"))
    assert len(calls) == 1 and second.text == first.text and second.filename == "b.png"


def test_ocr_and_the_vision_model_run_at_the_same_time(monkeypatch):
    import time as _time

    monkeypatch.setenv("TRIBOS_VISION_PROVIDER", "nim")
    monkeypatch.setattr(reader.ocr, "available", lambda: True)

    class FakeResult:
        markdown = "A spring has k = 50 N/m."
        lines = []
        engine = "Indra OCR test"
        mean_conf = 0.9

    def slow_ocr(image):
        _time.sleep(0.4)
        return FakeResult()

    async def slow_nim(png: bytes, draft: str, model_name=None):
        await asyncio.sleep(0.4)
        return "A spring has $k = 50$ N/m.", "nim"

    monkeypatch.setattr(reader.ocr, "read", slow_ocr)
    monkeypatch.setattr(reader.vlm, "transcribe_remote", slow_nim)
    t0 = _time.perf_counter()
    reading = asyncio.run(reader.read_image(_question_png(), "image/png", "q.png"))
    assert _time.perf_counter() - t0 < 0.75  # about 0.4 s, not 0.8 s
    assert reading.vision_checked and reading.text == "A spring has $k = 50$ N/m."
