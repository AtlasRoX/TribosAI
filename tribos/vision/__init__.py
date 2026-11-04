"""Image input: questions given as photos, scans or screenshots are read into text before they are solved.

An ensemble (see reader.py):
- Indra OCR (Datalab, ONNX Runtime on the CPU): line detection and recognition, its math models writing formulas
  as LaTeX; and Tesseract (tesseract.py), a second recognizer whose high-confidence words, where Indra read them
  too, are the words surely in the image.
- The vision model reads the image twice, once alone and once with the OCR drafts; the readings are compared in
  canonical form (consensus.py) and any difference is settled by a further look at the image. A transcription must
  keep the surely-read words, and numbers that no OCR engine read are flagged for review.
"""

from . import consensus, tesseract
from .reader import ImageReading, read_image, vision_status

__all__ = ["ImageReading", "consensus", "read_image", "tesseract", "vision_status"]
