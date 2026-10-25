"""Image input: questions given as photos, scans or screenshots are read into text before they are solved.

Two local stages (see reader.py):
- Indra OCR (Datalab, ONNX Runtime on the CPU): fast line detection and recognition, with its math models writing
  formulas as LaTeX. It is the grounded first read: every line carries a box and a confidence.
- A vision-language model, local through Ollama (or, only when allowed, the configured remote model): it corrects the
  OCR draft against the image (accents such as dots for time derivatives, subscripts, fraction bars, diagrams) and
  returns the question as Markdown with LaTeX. Numbers it writes that the OCR never read are flagged for review.
"""

from .reader import ImageReading, read_image, vision_status

__all__ = ["ImageReading", "read_image", "vision_status"]
