"""
Shape classification, container normalization, and element-wise dispatch for symbolic payloads (F05).

Provides:
- PayloadShape enum (SCALAR, TUPLE, LIST, SET, UNSUPPORTED)
- UnsupportedShapeError for typed, actionable shape validation failures
- normalize_symbolic_container for canonical conversion of Python collections to SymPy containers
- apply_elementwise for robust element-wise dispatch of scalar operations
"""

from __future__ import annotations

from enum import Enum
from typing import Any, Callable

import sympy as sp


class PayloadShape(str, Enum):
    SCALAR = "scalar"
    TUPLE = "tuple"
    LIST = "list"
    SET = "set"
    UNSUPPORTED = "unsupported"


class UnsupportedShapeError(ValueError):
    """Raised when a symbolic operation receives an unsupported payload shape."""

    def __init__(self, message: str, shape: PayloadShape | str = PayloadShape.UNSUPPORTED, details: Any = None) -> None:
        super().__init__(message)
        self.shape = str(shape)
        self.details = details


def classify_shape(obj: Any) -> PayloadShape:
    """Classify an object into its canonical PayloadShape."""
    if isinstance(obj, (tuple, sp.Tuple)):
        return PayloadShape.TUPLE
    if isinstance(obj, (list, sp.Matrix)):
        return PayloadShape.LIST
    if isinstance(obj, (set, frozenset, sp.FiniteSet)):
        return PayloadShape.SET
    if isinstance(obj, (sp.Expr, sp.Symbol, sp.Number, sp.Boolean, int, float, complex)):
        return PayloadShape.SCALAR
    if isinstance(obj, dict):
        return PayloadShape.UNSUPPORTED
    return PayloadShape.SCALAR if hasattr(obj, "free_symbols") else PayloadShape.UNSUPPORTED


def to_sympy_container(val: Any) -> sp.Basic:
    """Recursively convert Python native collections (tuple, list) into SymPy containers (sp.Tuple)."""
    if isinstance(val, (sp.Basic, sp.Symbol, sp.Expr)):
        return val
    if isinstance(val, (int, float, complex)):
        return sp.sympify(val)
    if isinstance(val, (tuple, list)):
        return sp.Tuple(*(to_sympy_container(x) for x in val))
    if isinstance(val, set):
        return sp.FiniteSet(*(to_sympy_container(x) for x in val))
    raise UnsupportedShapeError(
        f"Unsupported payload type {type(val).__name__}: expected mathematical scalar or sequence",
        shape=PayloadShape.UNSUPPORTED,
    )


def extract_free_symbols(obj: Any) -> list[str]:
    """Safely extract and union all free symbol names from scalars or arbitrary nested containers."""
    if hasattr(obj, "free_symbols"):
        return sorted(str(s) for s in obj.free_symbols)
    if isinstance(obj, (tuple, list, set)):
        syms: set[str] = set()
        for item in obj:
            syms.update(extract_free_symbols(item))
        return sorted(syms)
    return []


def apply_elementwise(func: Callable[[sp.Expr], Any], container: Any) -> Any:
    """
    Apply a scalar symbolic function element-wise across supported containers,
    preserving the container structure (tuple or list).
    """
    if isinstance(container, (tuple, sp.Tuple)):
        return tuple(apply_elementwise(func, item) for item in container)
    if isinstance(container, list):
        return [apply_elementwise(func, item) for item in container]
    return func(container)


__all__ = [
    "PayloadShape",
    "UnsupportedShapeError",
    "apply_elementwise",
    "classify_shape",
    "extract_free_symbols",
    "to_sympy_container",
]
