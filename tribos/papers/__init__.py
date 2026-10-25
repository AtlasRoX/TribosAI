"""Uploaded papers: extraction (tribos.papers.extract) and reproduction of their stated results (reproduce)."""

from __future__ import annotations

from .extract import extract_paper
from .reproduce import reproduce_paper

__all__ = ["extract_paper", "reproduce_paper"]
