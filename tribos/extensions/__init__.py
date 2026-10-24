"""
Extension loader for Tribos.

Every feature owns `tribos/extensions/<feature>.py` and registers its sources, hooks, id families and tools there.
`load_extensions()` imports each present module once (absent modules are skipped silently so branches can land
independently); `register_extension_tools(registry)` additionally calls `mod.register_tools(registry)` on any module
that defines it.
"""

from __future__ import annotations

import importlib
import logging
from typing import Any

logger = logging.getLogger(__name__)

# Ordered so foundational features (entities, grading, citations) register before downstream ones.
EXTENSION_MODULES: tuple[str, ...] = (
    "tribos.extensions.entities",
    "tribos.extensions.grading",
    "tribos.extensions.citations",
    "tribos.extensions.archivon",
    "tribos.extensions.axiom",
    "tribos.extensions.dynamis",
    "tribos.extensions.physis",
    "tribos.extensions.uploads",
    "tribos.extensions.export",
    "tribos.extensions.sandbox",
    "tribos.extensions.calibration",
    "tribos.extensions.agentic",
)

_LOADED: list[Any] = []
_DID_LOAD = False


def load_extensions(*, force: bool = False) -> list[Any]:
    """Import every present extension module once and return the loaded module objects."""
    global _DID_LOAD
    if _DID_LOAD and not force:
        return list(_LOADED)
    _LOADED.clear()
    for name in EXTENSION_MODULES:
        try:
            mod = importlib.import_module(name)
        except ModuleNotFoundError as exc:
            if exc.name == name:
                continue  # branch for this feature has not landed yet
            logger.warning("Extension %s failed to import (%s)", name, exc)
            continue
        except Exception as exc:  # noqa: BLE001
            logger.warning("Extension %s failed to load: %s", name, exc)
            continue
        _LOADED.append(mod)
    _DID_LOAD = True
    return list(_LOADED)


def register_extension_tools(registry: Any) -> None:
    """Let loaded extensions add ToolUniverseEntry definitions to a ToolRegistry."""
    for mod in load_extensions():
        fn = getattr(mod, "register_tools", None)
        if callable(fn):
            try:
                fn(registry)
            except Exception as exc:  # noqa: BLE001
                logger.warning("register_tools failed in %s: %s", getattr(mod, "__name__", mod), exc)
