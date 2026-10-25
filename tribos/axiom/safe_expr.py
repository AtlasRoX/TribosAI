"""
The one safe parser for mathematical text written by users and models (SUP-1).

SymPy's parse_expr turns text into Python code and evaluates it, so a blacklist alone is not a boundary: Python
NFKC-normalises identifiers, and "Integer(1)._＿ｃｌａｓｓ＿＿" (full-width letters) reaches a real dunder. Here the text
is normalised first, non-ASCII is rejected, and the generated code is checked against an AST allowlist before it is
evaluated: names, numbers, arithmetic, comparisons, tuples and lists, and calls to whitelisted SymPy constructors and
functions. No attribute access, no names starting with "_", no lambda, comprehension, f-string or dict, and string
literals only as the name of a Symbol or Function or the digits of a number.
"""

from __future__ import annotations

import ast
import math
import re
import unicodedata
from typing import Any

import sympy as sp
from sympy.core.function import FunctionClass
from sympy.matrices import MatrixBase
from sympy.parsing.sympy_parser import (
    convert_xor,
    eval_expr,
    implicit_multiplication,
    null,
    standard_transformations,
    stringify_expr,
)

TRANSFORMATIONS = standard_transformations + (
    implicit_multiplication,
    convert_xor,
)

MAX_EXPRESSION_LENGTH = 8000

# Defence in depth on the normalised text; the AST check below is the boundary.
FORBIDDEN_RE = re.compile(r"__|import|eval|exec|getattr|setattr|delattr|globals|locals|open|os\.|sys\.|subprocess", re.I)

SAFE_NAMES: dict[str, Any] = {
    # Constants
    "pi": sp.pi,
    "E": sp.E,
    "e": sp.E,
    "I": sp.I,
    "oo": sp.oo,
    "inf": sp.oo,
    "infinity": sp.oo,
    "GoldenRatio": sp.GoldenRatio,
    "EulerGamma": sp.EulerGamma,
    "Catalan": sp.Catalan,
    # Elementary functions
    "sin": sp.sin,
    "cos": sp.cos,
    "tan": sp.tan,
    "cot": sp.cot,
    "sec": sp.sec,
    "csc": sp.csc,
    "asin": sp.asin,
    "acos": sp.acos,
    "atan": sp.atan,
    "atan2": sp.atan2,
    "acot": sp.acot,
    "asec": sp.asec,
    "acsc": sp.acsc,
    "arcsin": sp.asin,
    "arccos": sp.acos,
    "arctan": sp.atan,
    "sinh": sp.sinh,
    "cosh": sp.cosh,
    "tanh": sp.tanh,
    "coth": sp.coth,
    "asinh": sp.asinh,
    "acosh": sp.acosh,
    "atanh": sp.atanh,
    "exp": sp.exp,
    "log": sp.log,
    "ln": sp.log,
    "sqrt": sp.sqrt,
    "cbrt": sp.cbrt,
    "root": sp.root,
    "Abs": sp.Abs,
    "abs": sp.Abs,
    "sign": sp.sign,
    "floor": sp.floor,
    "ceiling": sp.ceiling,
    "ceil": sp.ceiling,
    "re": sp.re,
    "im": sp.im,
    "conjugate": sp.conjugate,
    "arg": sp.arg,
    # Combinatorics & special functions
    "factorial": sp.factorial,
    "binomial": sp.binomial,
    "gamma": sp.gamma,
    "loggamma": sp.loggamma,
    "digamma": sp.digamma,
    "polygamma": sp.polygamma,
    "beta": sp.beta,
    "erf": sp.erf,
    "erfc": sp.erfc,
    "erfi": sp.erfi,
    "zeta": sp.zeta,
    "besselj": sp.besselj,
    "bessely": sp.bessely,
    "besseli": sp.besseli,
    "besselk": sp.besselk,
    "legendre": sp.legendre,
    "hermite": sp.hermite,
    "chebyshevt": sp.chebyshevt,
    "chebyshevu": sp.chebyshevu,
    "laguerre": sp.laguerre,
    "Heaviside": sp.Heaviside,
    "DiracDelta": sp.DiracDelta,
    "LambertW": sp.LambertW,
    # Calculus & algebra constructors
    "Derivative": sp.Derivative,
    "diff": sp.diff,
    "Integral": sp.Integral,
    "integrate": sp.integrate,
    "Sum": sp.Sum,
    "summation": sp.summation,
    "Product": sp.Product,
    "Limit": sp.Limit,
    "limit": sp.limit,
    "Function": sp.Function,
    "Symbol": sp.Symbol,
    "Number": sp.Number,
    "Rational": sp.Rational,
    "Integer": sp.Integer,
    "Float": sp.Float,
    "Matrix": sp.Matrix,
    "CRootOf": sp.CRootOf,
    "RootOf": sp.CRootOf,
    "Eq": sp.Eq,
    "Piecewise": sp.Piecewise,
    "Max": sp.Max,
    "Min": sp.Min,
}

# The constructors stringify_expr emits ("x" -> Symbol('x'), "2" -> Integer(2), "f(x)" -> Function('f')(x)); present
# in every environment so a caller's own name table does not have to list them.
_CONSTRUCTORS = {name: SAFE_NAMES[name] for name in ("Symbol", "Function", "Integer", "Float", "Rational")}
_SAFE_CALLABLE_IDS = frozenset(id(v) for v in SAFE_NAMES.values() if callable(v))

# Calls whose first argument may be a string literal, and what the string may look like. None of these evaluate it.
_NAME_STRING = re.compile(r"(?!.*__)[A-Za-z_][A-Za-z0-9_]*")  # no dunder, even as a name
_NUMBER_STRING = re.compile(r"[0-9.eE+\- /]+")
_STRING_ARG = {"Symbol": _NAME_STRING, "Function": _NAME_STRING, "Integer": _NUMBER_STRING,
               "Float": _NUMBER_STRING, "Rational": _NUMBER_STRING}

# Greek letters and a few operators written as Unicode: their ASCII names, so "ω t" still reads omega*t once
# non-ASCII text is refused. "λ" is "lamda" (SymPy's spelling) because lambda is a Python keyword.
_UNICODE_NAMES = {
    "α": "alpha", "β": "beta", "γ": "gamma", "δ": "delta", "ε": "epsilon", "ζ": "zeta", "η": "eta",
    "θ": "theta", "ι": "iota", "κ": "kappa", "λ": "lamda", "μ": "mu", "ν": "nu", "ξ": "xi", "ο": "omicron",
    "ρ": "rho", "σ": "sigma", "ς": "sigma", "τ": "tau", "υ": "upsilon", "φ": "phi", "χ": "chi", "ψ": "psi",
    "ω": "omega", "Γ": "Gamma", "Δ": "Delta", "Θ": "Theta", "Λ": "Lamda", "Ξ": "Xi", "Π": "Pi", "Σ": "Sigma",
    "Υ": "Upsilon", "Φ": "Phi", "Ψ": "Psi", "Ω": "Omega", "π": "pi", "∞": "oo",
}
_UNICODE_OPERATORS = {"−": "-", "–": "-", "×": "*", "·": "*", "⋅": "*", "÷": "/", "≤": "<=", "≥": ">=", "≠": "!="}

_ALLOWED_NODES = (
    ast.Expression, ast.BinOp, ast.UnaryOp, ast.Compare, ast.Call, ast.Name, ast.Load, ast.Constant, ast.Tuple,
    ast.List, ast.keyword, ast.Subscript, ast.Slice,
    ast.Add, ast.Sub, ast.Mult, ast.Div, ast.Pow, ast.Mod, ast.FloorDiv, ast.USub, ast.UAdd, ast.Not,
    ast.Lt, ast.LtE, ast.Gt, ast.GtE, ast.Eq, ast.NotEq,
)


def normalize_math_text(text: str) -> str:
    """NFKC-normalise (what Python does to identifiers), spell Greek letters and Unicode operators in ASCII, and
    refuse any other non-ASCII character, so what is checked is exactly what would be evaluated."""
    s = unicodedata.normalize("NFKC", text)
    s = "".join(_UNICODE_NAMES.get(ch, _UNICODE_OPERATORS.get(ch, ch)) for ch in s)
    bad = next((ch for ch in s if ord(ch) > 127), None)
    if bad is not None:
        raise ValueError(f"Expression contains the non-ASCII character {bad!r} (U+{ord(bad):04X}).")
    return s


def check_math_text(text: str) -> str:
    """The normalised, stripped text, or ValueError when it is empty, too long or uses a forbidden token."""
    if not isinstance(text, str) or not text.strip():
        raise ValueError("Expression must be a non-empty string.")
    if len(text) > MAX_EXPRESSION_LENGTH:
        raise ValueError(f"Expression exceeds maximum length ({MAX_EXPRESSION_LENGTH} characters).")
    s = normalize_math_text(text)
    if FORBIDDEN_RE.search(s):
        raise ValueError("Expression contains forbidden tokens or dunder attributes.")
    return s.strip()


def is_safe_identifier(name: str) -> bool:
    return bool(re.fullmatch(r"[A-Za-z][A-Za-z0-9_]*", name or ""))


def _safe_callable(value: Any) -> bool:
    if id(value) in _SAFE_CALLABLE_IDS or isinstance(value, FunctionClass):
        return True  # whitelisted SymPy functions, and defined or undefined SymPy function classes (Function('y'))
    return isinstance(value, type) and issubclass(value, (sp.Basic, MatrixBase))


def _reject(node: ast.AST, why: str) -> None:
    raise ValueError(f"Expression is not plain mathematics ({why}: {type(node).__name__}).")


# An exact integer power is computed eagerly by SymPy: 9**9**9**9 would never finish. A literal power whose result
# would have more than MAX_POWER_DIGITS decimal digits is refused before evaluation.
MAX_POWER_DIGITS = 100_000


def _int_literal(node: ast.AST) -> int | None:
    """The value of an integer literal, Integer(n), or a negated one; None for anything else."""
    if isinstance(node, ast.Constant) and isinstance(node.value, int) and not isinstance(node.value, bool):
        return node.value
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.USub):
        inner = _int_literal(node.operand)
        return -inner if inner is not None else None
    if (isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "Integer"
            and len(node.args) == 1 and not node.keywords):
        return _int_literal(node.args[0])
    return None


def _power_parts(node: ast.AST) -> tuple[ast.AST, ast.AST] | None:
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Pow):
        return node.left, node.right
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "Pow" and len(node.args) == 2:
        return node.args[0], node.args[1]
    return None


def _literal_power_digits(node: ast.AST) -> float | None:
    """Approximate decimal digits of a literal integer (or literal power tower), without computing it; None when
    the node is not built from integer literals only. inf when the size itself is too large to represent."""
    value = _int_literal(node)
    if value is not None:
        return math.log10(abs(value)) if abs(value) > 1 else 0.0
    parts = _power_parts(node)
    if parts is None:
        return None
    base, exp = parts
    base_val = _int_literal(base)
    if base_val is not None and abs(base_val) <= 1:
        return 0.0  # 0, 1 and -1 to any power stay small
    base_digits = _literal_power_digits(base)
    exp_digits = _literal_power_digits(exp)
    if base_digits is None or exp_digits is None:
        return None
    if exp_digits > 15:
        return math.inf
    exp_val = _int_literal(exp)
    exponent = float(exp_val) if exp_val is not None else 10.0**exp_digits
    if exponent <= 0:
        return 0.0
    return base_digits * exponent


def validate_code(code: str, env: dict[str, Any]) -> None:
    """Check the Python code stringify_expr generated against the allowlist; ValueError when anything else is used."""
    try:
        tree = ast.parse(code, mode="eval")
    except SyntaxError as exc:
        raise ValueError(f"invalid syntax: {exc.msg}") from exc
    allowed_strings: set[int] = set()
    for node in ast.walk(tree):  # breadth-first: a call is seen before its arguments
        if not isinstance(node, _ALLOWED_NODES):
            _reject(node, "construct not allowed")
        if _power_parts(node) is not None:
            digits = _literal_power_digits(node)
            if digits is not None and digits > MAX_POWER_DIGITS:
                raise ValueError(
                    f"Expression is too large to evaluate exactly (an integer power with more than {MAX_POWER_DIGITS} "
                    "digits); use floating point or a symbolic exponent."
                )
        if isinstance(node, ast.Name):
            if node.id.startswith("_") or node.id not in env:
                _reject(node, f"unknown name {node.id!r}")
        elif isinstance(node, ast.keyword):
            if node.arg is None or node.arg.startswith("_"):
                _reject(node, "keyword argument not allowed")
            if not (isinstance(node.value, ast.Constant) and isinstance(node.value.value, (bool, int, float))):
                _reject(node, f"keyword {node.arg!r} must be a number or True/False")
        elif isinstance(node, ast.Call):
            func = node.func
            if isinstance(func, ast.Name):
                if not _safe_callable(env.get(func.id)):
                    _reject(node, f"call to {func.id!r} not allowed")
                pattern = _STRING_ARG.get(func.id) if env.get(func.id) is SAFE_NAMES.get(func.id) else None
                first = node.args[0] if node.args else None
                if pattern is not None and isinstance(first, ast.Constant) and isinstance(first.value, str):
                    if not pattern.fullmatch(first.value):
                        _reject(node, f"string argument {first.value!r} not allowed")
                    allowed_strings.add(id(first))
            elif not (isinstance(func, ast.Call) and isinstance(func.func, ast.Name)
                      and env.get(func.func.id) is sp.Function):
                _reject(node, "only named functions may be called")  # Function('f')(x) is the one nested form
        elif isinstance(node, ast.Constant):
            v = node.value
            if isinstance(v, str):
                if id(node) not in allowed_strings:
                    _reject(node, "string literal not allowed")
            elif not (v is None or isinstance(v, (bool, int, float, complex))):
                _reject(node, "constant not allowed")


def parse_math(
    text: str,
    env: dict[str, Any] | None = None,
    transformations: tuple[Any, ...] = TRANSFORMATIONS,
) -> Any:
    """Parse mathematical text into a SymPy object with the names in `env` (SAFE_NAMES when None). The text is
    normalised and checked, the generated code is validated, and only then evaluated, with no builtins."""
    cleaned = check_math_text(text)
    local_dict: dict[str, Any] = {**_CONSTRUCTORS, **(SAFE_NAMES if env is None else env)}
    global_dict: dict[str, Any] = {"__builtins__": {}}
    code = stringify_expr(cleaned, local_dict, global_dict, transformations)
    validate_code(code, local_dict)
    try:
        return eval_expr(code, local_dict, global_dict)
    finally:
        # parse_expr's bookkeeping for names it bound to Symbol/Function while transforming
        for name in local_dict.pop(null, ()):
            local_dict[name] = null


__all__ = [
    "FORBIDDEN_RE",
    "MAX_EXPRESSION_LENGTH",
    "SAFE_NAMES",
    "TRANSFORMATIONS",
    "check_math_text",
    "is_safe_identifier",
    "normalize_math_text",
    "parse_math",
    "validate_code",
]
