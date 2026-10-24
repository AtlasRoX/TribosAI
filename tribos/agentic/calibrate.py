"""Backward-compatible alias for tribos.agentic.fit."""

from __future__ import annotations

from .fit import (
    CALIBRATION_INTENT_RE,
    FIT_INTENT_RE,
    CalibratePhase,
    FitPhase,
    has_calibration_intent,
    has_fit_intent,
)

__all__ = [
    "CALIBRATION_INTENT_RE",
    "CalibratePhase",
    "FIT_INTENT_RE",
    "FitPhase",
    "has_calibration_intent",
    "has_fit_intent",
]
