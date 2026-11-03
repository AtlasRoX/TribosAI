"""Check only unit statements whose symbols and quantities can be bound without guessing."""

from __future__ import annotations

import math
import re
from typing import Any

import pint
import sympy as sp

from tribos.axiom.engine import safe_parse_expr
from tribos.physis.units import get_unit_registry

from .latex_math import parse_latex

_CODE = re.compile(r"```.*?```|`[^`\n]*`", re.S)
_LABEL_UNITS = {"pressure": "Pa", "force": "N", "energy": "J", "power": "W", "mass": "kg",
                "distance": "m", "length": "m", "speed": "m/s", "velocity": "m/s", "acceleration": "m/s**2"}
_NUMBER_UNIT = re.compile(r"^([+\-]?(?:\d|\.)[\d.eE+\-*/^{}\s()]*)\s*([A-Za-zµ°Ω][A-Za-zµ°Ω0-9^{}()*./\s+\-]*)$")


class NotEvaluated(ValueError):
    pass


def _clean(text: str) -> str:
    text = re.sub(r"\\(?:mathrm|textrm|text)\{([^{}]*)\}", r"\1", text)
    text = re.sub(r"\\[,;! ]", " ", text)
    text = text.replace("\\times", "*").replace("\\cdot", "*").replace("·", "*")
    return text.replace("−", "-").replace("²", "^2").replace("³", "^3").replace("$", "").strip(" .:")


def _quantity(text: str) -> Any | None:
    cleaned = _clean(text)
    match = _NUMBER_UNIT.fullmatch(cleaned)
    if not match:
        return None
    number, unit = match.groups()
    try:
        scalar = safe_parse_expr(number.replace("{", "(").replace("}", ")"))
        if scalar.free_symbols or not scalar.is_real or not math.isfinite(float(scalar)):
            return None
        units = get_unit_registry().parse_units(unit.replace("{", "").replace("}", ""))
        return get_unit_registry().Quantity(float(scalar), units)
    except (ValueError, TypeError, pint.PintError):
        return None


def _statements(text: str) -> list[list[str]]:
    text = _CODE.sub("", text or "")
    text = re.sub(r"\\(?:quad|qquad)|\\\\|\\\[|\\\]|\\\(|\\\)", ";", text)
    text = text.replace("$$", ";").replace("$", ";")
    text = _clean(text)
    segments = re.split(r"[\n;,|]|\band\b|(?<!\d)\.(?!\d)", text)
    return [[p.strip(" .:") for p in re.split(r"(?<![<>!])=(?!=)", s)] for s in segments if "=" in s][:400]


def _unitless_number(text: str) -> bool:
    """A side that is a pure number however it is typeset ("25", "\\sqrt{\\frac{50}{2}}", "3/(2*sqrt(100))"): a number
    written without its unit may follow an unstated convention, so it is never compared dimensionally."""
    cleaned = _clean(text)
    if re.fullmatch(r"[+\-\d.\s*/^{}()]+", cleaned):
        return True
    if not re.search(r"\d", cleaned) or re.search(r"[A-Za-zµ°Ω]", re.sub(r"\\[A-Za-z]+|\b(?:sqrt|pi)\b", "", cleaned)):
        return False
    try:
        expr = parse_latex(cleaned) if "\\" in cleaned else safe_parse_expr(cleaned)
    except (ValueError, TypeError, SyntaxError):
        return False
    return not getattr(expr, "free_symbols", {1})


def _unit_symbol_clash(text: str, bindings: dict[str, Any]) -> bool:
    """A bound variable name that is also written as a unit after a number ("m = 2 kg" and "0.1 m"): which one is
    meant cannot be decided, so the statement is not evaluated rather than read with the wrong meaning."""
    cleaned = _clean(text)
    ureg = get_unit_registry()
    for name in bindings:
        if re.search(rf"(?:\d|\))\s*{re.escape(name)}\b(?!\s*[(=])", cleaned):
            try:
                ureg.parse_units(name)
                return True
            except (pint.PintError, ValueError, TypeError, AttributeError):
                continue
    return False


def _first(text: str, bindings: dict[str, Any]) -> str:
    text = _clean(text)
    words = text.split()
    if len(words) > 1 and any(w not in bindings for w in words):
        # Prose before a statement, e.g. "the resulting force F = ...".
        last = re.search(r"([A-Za-z][A-Za-z_0-9]*(?:_\{[^}]+\})?)$", text)
        if last and not any(op in text for op in "*/^+"):
            return last[1]
    return text


def _expression(text: str, bindings: dict[str, Any], ambiguous: set[str]) -> Any:
    quantity = _quantity(text)
    if quantity is not None:
        return quantity
    cleaned = _clean(text)
    calls = re.findall(r"([A-Za-z_][A-Za-z_0-9]*)\s*\(", cleaned)
    if any(name not in ("sqrt", "sin", "cos", "tan", "exp", "log") for name in calls):
        raise NotEvaluated("a function value has not been bound")
    try:
        names = set(re.findall(r"\b[A-Za-z][A-Za-z_0-9]*\b", cleaned))
        local = {n: sp.Symbol(n) for n in names - {"sqrt", "sin", "cos", "tan", "exp", "log", "pi"}}
        expr = safe_parse_expr(cleaned, local_dict=local) if "\\" not in cleaned else parse_latex(cleaned)
        # Plain implicit products such as mc^2 are common in typeset equations.
        if any(str(s) not in bindings for s in expr.free_symbols):
            alternative = parse_latex(cleaned)
            if all(str(s) in bindings for s in alternative.free_symbols):
                expr = alternative
        if any(str(s) not in bindings or str(s) in ambiguous for s in expr.free_symbols):
            raise NotEvaluated("unbound or ambiguous symbols")
    except (ValueError, TypeError, SyntaxError) as exc:
        raise NotEvaluated("unsupported expression") from exc
    ureg = get_unit_registry()

    def evaluate(node: sp.Expr) -> Any:
        if node.is_Number or node in (sp.pi, sp.E):
            return ureg.Quantity(float(node))
        if isinstance(node, sp.Symbol):
            if str(node) not in bindings:
                raise NotEvaluated("unbound symbol")
            return bindings[str(node)]
        functions = {sp.sin: math.sin, sp.cos: math.cos, sp.tan: math.tan, sp.exp: math.exp, sp.log: math.log}
        if not isinstance(node, (sp.Add, sp.Mul, sp.Pow)) and node.func not in functions:
            raise NotEvaluated("unsupported operation")
        args = [evaluate(a) for a in node.args]
        if isinstance(node, sp.Add):
            result = args[0]
            for arg in args[1:]:
                result = result + arg
            return result
        if isinstance(node, sp.Mul):
            result = ureg.Quantity(1)
            for arg in args:
                result = result * arg
            return result
        if isinstance(node, sp.Pow):
            return args[0] ** float(args[1].to("").magnitude)
        if node.func in functions and len(args) == 1:
            return ureg.Quantity(functions[node.func](float(args[0].to("").magnitude)))
        raise NotEvaluated("unsupported operation")
    return evaluate(expr)


def _printed_tolerance(text: str, quantity: Any) -> float:
    match = re.match(r"[+\-]?(\d+(?:\.(\d+))?)(?:[eE]([+\-]?\d+)|\s*\*\s*10\s*\^\{?([+\-]?\d+)\}?)?", _clean(text))
    if match:
        decimals = len(match[2] or "")
        exponent = int(match[3] or match[4] or 0)
        return max(1e-300, 0.51 * 10.0**max(-300, min(300, exponent-decimals)))
    return max(1e-300, abs(float(quantity.magnitude))*1e-8)


def audit_units(answer: str, question: str = "") -> dict[str, Any]:
    bindings: dict[str, Any] = {}
    ambiguous: set[str] = set()
    report: dict[str, Any] = {"checked": 0, "consistent": 0, "inconsistent": [], "not_evaluated": 0}
    statements = _statements(answer)
    for source, items in (("question", _statements(question)), ("answer", statements)):
        for parts in items:
            name = _first(parts[0], bindings)
            value = _quantity(parts[-1])
            if re.fullmatch(r"[A-Za-z][A-Za-z_0-9]*", name) and value is not None:
                if name in bindings:
                    old = bindings[name]
                    if source == "question" and (old.dimensionality != value.dimensionality or
                            not math.isclose(float(old.to_base_units().magnitude), float(value.to_base_units().magnitude))):
                        ambiguous.add(name)
                else:
                    bindings[name] = value

    def compare(left: Any, right: Any, statement: str, tolerance: float = 0) -> None:
        report["checked"] += 1
        if left.dimensionality != right.dimensionality:
            report["inconsistent"].append({"statement": statement, "lhs_dim": str(left.dimensionality),
                "rhs_dim": str(right.dimensionality), "reason": "Inconsistent units: physical dimensions differ."})
        elif abs(float(left.to(right.units).magnitude)-float(right.magnitude)) > max(tolerance, 1e-300):
            report["inconsistent"].append({"statement": statement, "lhs_dim": str(left.dimensionality),
                "rhs_dim": str(right.dimensionality), "reason": f"Unit conversion gives {left.to(right.units):~}; the stated result is {right:~}."})
        else:
            report["consistent"] += 1

    for parts in statements:
        parts[0] = _first(parts[0], bindings)
        if len(parts) > 2 and re.fullmatch(r"[A-Za-z][A-Za-z_0-9]*", parts[0]):
            parts = parts[1:]
        for left, right in zip(parts, parts[1:], strict=False):
            statement = f"{left} = {right}"
            try:
                if any(_unitless_number(side) for side in (left, right)) or _unit_symbol_clash(statement, bindings):
                    # A number without a unit may use an unstated convention; do not infer dimensionlessness. A
                    # name that is both a bound variable and a unit (m) is ambiguous.
                    report["not_evaluated"] += 1
                    continue
                lhs, rhs = _expression(left, bindings, ambiguous), _expression(right, bindings, ambiguous)
                if lhs.dimensionless and rhs.dimensionless:
                    continue
                compare(lhs, rhs, statement, _printed_tolerance(right, rhs))
            except pint.DimensionalityError as exc:
                report["checked"] += 1
                report["inconsistent"].append({"statement": statement, "lhs_dim": str(exc.dim1),
                    "rhs_dim": str(exc.dim2), "reason": "Inconsistent units within the expression."})
            except (NotEvaluated, ValueError, TypeError, OverflowError, ZeroDivisionError, pint.PintError):
                report["not_evaluated"] += 1

    cleaned = _clean(_CODE.sub("", answer or ""))
    labels = "|".join(_LABEL_UNITS)
    for match in re.finditer(rf"\b({labels})\s+(?:is|of|=)\s*([^.;\n]+)", cleaned, re.I):
        value = _quantity(match[2])
        if value is not None:
            expected = get_unit_registry().Quantity(float(value.magnitude), _LABEL_UNITS[match[1].lower()])
            # Semantic labels check dimensions only, never invent a numerical expected value.
            if expected.dimensionality != value.dimensionality:
                compare(expected, value, match[0], math.inf)
            else:
                report["checked"] += 1
                report["consistent"] += 1
    return report
