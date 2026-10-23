"""
Feature extension loader. Each feature registers its hooks, evidence sources and tools from one
module listed in EXTENSION_MODULES; a module that fails to import is logged and skipped.

Keep imports here lazy: registry, verifier and prompts call load_extensions() inside functions only.
"""

from __future__ import annotations

import importlib
import logging
from types import ModuleType
from typing import Any, List

logger = logging.getLogger(__name__)

EXTENSION_MODULES = (
    "tribos.extensions.grading",
    "tribos.extensions.citations",
    "tribos.extensions.uploads",
    "tribos.extensions.export",
    "tribos.extensions.sandbox",
    "tribos.extensions.agentic",
)

_LOADED: List[ModuleType] = []
_LOADED_FLAG = False


def load_extensions() -> List[ModuleType]:
    """Import every extension module once per process and return the ones that loaded."""
    global _LOADED_FLAG
    if _LOADED_FLAG:
        return list(_LOADED)
    _LOADED_FLAG = True
    for name in EXTENSION_MODULES:
        try:
            _LOADED.append(importlib.import_module(name))
        except Exception as exc:  # noqa: BLE001
            logger.warning("Extension %s failed to load and is disabled: %s", name, exc)
    return list(_LOADED)


def register_extension_tools(registry: Any) -> None:
    """Let each loaded extension register its registry tools; a failing extension is skipped."""
    for module in load_extensions():
        fn = getattr(module, "register_tools", None)
        if not callable(fn):
            continue
        try:
            fn(registry)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Extension %s failed to register tools: %s", module.__name__, exc)
