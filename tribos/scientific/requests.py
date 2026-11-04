"""Conservative natural-language adapters to existing numerical tools.

These adapters extract inputs, never answers. Unrecognised equations, output requirements or units stay on the
general agent path. Recognised but incomplete requests carry missing inputs and never run a default model.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from typing import Any

from tribos.axiom.engine import safe_parse_expr
from tribos.physis.units import get_unit_registry

NUMBER = r"[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?(?:\s*[×*]\s*10\s*\^\s*[+-]?\d+)?"
TIME_UNIT = r"milliseconds?|ms|seconds?|secs?|s|minutes?|min|hours?|h"


@dataclass
class ScientificRequest:
    kind: str
    tool: str
    args: dict[str, Any]
    items: int
    errors: list[str] = field(default_factory=list)
    context: dict[str, Any] = field(default_factory=dict)


@dataclass
class CompositeScientificRequest:
    kind: str
    tool: str
    tasks: list[ScientificRequest]
    items: int
    errors: list[str] = field(default_factory=list)
    context: dict[str, Any] = field(default_factory=dict)


def _number(raw: str) -> float:
    value = float(safe_parse_expr(raw.replace("×", "*")))
    if not math.isfinite(value):
        raise ValueError("A finite number is required.")
    return value


def _quantity(number: str, unit: str, target: str) -> float:
    unit = unit.replace("Ω", "ohm").replace("μ", "u").replace("µ", "u").replace("·", "*")
    unit = {
        "seconds": "s",
        "second": "s",
        "sec": "s",
        "secs": "s",
        "milliseconds": "ms",
        "millisecond": "ms",
    }.get(unit, unit)
    return float(get_unit_registry().Quantity(_number(number), unit).to(target).magnitude)


def _assigned(q: str, names: str, units: str, target: str) -> float | None:
    m = re.search(rf"(?<!\w)(?:{names})\s*=\s*({NUMBER})\s*({units})(?![\w/])", q)
    return _quantity(m[1], m[2], target) if m else None


def _time_at(q: str) -> list[float]:
    return sorted(
        {
            _quantity(m[1], m[2], "s")
            for m in re.finditer(rf"(?<!\w)t\s*=\s*({NUMBER})\s*({TIME_UNIT})(?!\w)", q, re.I)
        }
    )


def _steps(q: str) -> int | None:
    m = re.search(r"\b(?:exactly\s+)?(\d+)\s+(?:time\s+)?steps\b", q, re.I)
    return int(m[1]) if m else None


def _monte_carlo(q: str) -> ScientificRequest | None:
    if not re.search(r"\bMonte[ -]Carlo\b", q, re.I) or not re.search(r"\bintegral\b", q, re.I):
        return None
    if re.search(
        r"importance|stratif|quasi|Sobol|antithetic|control variate|multiple integrals?|double\s+integral|triple\s+integral|multi[ -]dimensional",
        q,
        re.I,
    ):
        return None
    m = re.search(
        rf"integral\s+of\s+(.+?)\s+from\s+(?:([a-z])\s*=\s*)?({NUMBER})\s+to\s+({NUMBER})(?!\w)",
        q,
        re.I,
    )
    n = re.search(r"\b(\d+)\s+(?:independent\s+)?(?:uniform\s+)?samples\b", q, re.I)
    seed = re.search(r"\bseed\s*(?:=|of|:)?\s*(\d+)\b", q, re.I)
    reference = re.search(rf"\breference(?:\s+value)?\s*(?:=|of|:)?\s*({NUMBER})", q, re.I)
    errors = [
        label
        for ok, label in [
            (m, "integrand and finite bounds"),
            (n, "sample count"),
            (seed, "random seed"),
        ]
        if not ok
    ]
    if re.search(r"\b(?:MT19937|Philox|SFC64|PCG64DXSM)\b", q):
        return None
    if errors:
        return None  # unparsed input is not proof that the user's input was missing
    args = (
        {
            "expression": m[1].strip().rstrip(","),
            "variable": m[2] or "x",
            "lower": _number(m[3]),
            "upper": _number(m[4]),
            "num_samples": int(n[1]),
            "seed": int(seed[1]),
            "generator": "PCG64",
            "reference": _number(reference[1]) if reference else None,
        }
        if not errors
        else {}
    )
    return ScientificRequest("monte_carlo", "dynamis_monte_carlo_integrate", args, 3, errors)


def _heat(q: str) -> ScientificRequest | None:
    if not re.search(r"heat\s+equation", q, re.I) or not re.search(r"FTCS", q, re.I):
        return None
    if re.search(
        r"two[ -]dimensional|2[ -]?D|source\s*(?:term)?\s*=|Neumann|periodic|nonlinear", q, re.I
    ):
        return None
    alpha = _assigned(q, r"alpha|α", r"m\^2/s|m2/s", "m^2/s")
    domain = re.search(rf"({NUMBER})\s*(?:≤|<=)\s*x\s*(?:≤|<=)\s*({NUMBER})\s*m\b", q)
    nodes = re.search(r"\b(\d+)\s+(?:equally\s+spaced\s+)?nodes\b", q, re.I)
    dt = _assigned(q, r"Δt|delta\s*t|dt", TIME_UNIT, "s")
    dx = _assigned(q, r"Δx|delta\s*x|dx", r"m", "m")
    steps = _steps(q)
    boundaries = list(
        re.finditer(rf"T\(\s*({NUMBER})\s*,\s*t\s*\)\s*=\s*({NUMBER})\s*(°?C|K)\b", q)
    )
    initial = re.search(
        rf"initially\b[^.;]*?interior\s+nodes\s+(?:to|at|are|=)\s*({NUMBER})\s*(°?C|K)\b", q, re.I
    )
    errors = [
        label
        for ok, label in [
            (alpha is not None, "thermal diffusivity alpha"),
            (domain, "spatial interval"),
            (nodes, "node count"),
            (dt is not None, "time step"),
            (steps is not None, "number of steps"),
            (len(boundaries) == 2, "two Dirichlet boundary values"),
            (initial, "uniform initial interior temperature"),
        ]
        if not ok
    ]
    if errors:
        return None
    assert (
        domain and nodes and initial and dt is not None and alpha is not None and steps is not None
    )
    low, high, count = _number(domain[1]), _number(domain[2]), int(nodes[1])
    bc = {_number(b[1]): (_number(b[2]), b[3]) for b in boundaries}
    if low not in bc or high not in bc or any(b[3] != initial[2] for b in boundaries):
        errors.append(
            "Boundary coordinates and temperature units must match the stated interval and initial data."
        )
    if high <= low or count < 5 or count > 401 or not 1 <= steps <= 199:
        return None
    if (
        not errors
        and dx is not None
        and not math.isclose(dx, (high - low) / (count - 1), rel_tol=1e-10)
    ):
        errors.append(
            "Node count, interval and stated space step disagree; no grid was substituted."
        )
    args = (
        {}
        if errors
        else {
            "equation": "heat",
            "dimension": 1,
            "domain": [[low, high]],
            "parameters": {"alpha": alpha},
            "initial_condition": str(_number(initial[1])),
            "boundary": "dirichlet",
            "boundary_values": {"x0": bc[low][0], "x1": bc[high][0]},
            "t_span": [0.0, dt * steps],
            "num_points": count,
            "num_times": steps + 1,
            "method": "explicit",
            "dt": dt,
            "on_unstable": "refuse",
            "convergence_levels": 2,
        }
    )
    return ScientificRequest(
        "heat_ftcs",
        "dynamis_solve_pde",
        args,
        3,
        errors,
        {"steps": steps, "temperature_unit": initial[2]},
    )


def _ode(q: str) -> ScientificRequest | None:
    if not re.search(r"RK4|fourth[ -]order\s+Runge[ -]Kutta|classical\s+Runge[ -]Kutta", q, re.I):
        return None
    if re.search(
        r"step[ -]halv|convergence\s+study|energy\s+balance|parameter\s+(?:scan|sweep)|natural\s+frequency|damping\s+ratio|maximum|minimum|bifurcat",
        q,
        re.I,
    ):
        return None
    from tribos.axiom.problem import parse_problem
    from tribos.dynamis.stated_ode import stated_ode_system

    # Physical scalar givens must be converted before the symbolic parser substitutes their numbers.
    unit_pattern = r"N[·*]?s/m|(?:kN|N)/m|m/s\^2|m/s|kg/s\^2|kg/s|kg|mg|g|mm|cm|m|ms|s|kN|N|rad|deg"

    def si_value(match: re.Match[str]) -> str:
        unit = match[2].replace("·", "*")
        quantity = get_unit_registry().Quantity(_number(match[1]), unit).to_base_units()
        return f"= {float(quantity.magnitude):.17g} {quantity.units:~}"

    normalised = re.sub(rf"=\s*({NUMBER})\s*({unit_pattern})(?![\w/])", si_value, q)
    spec = parse_problem(normalised)
    stated = stated_ode_system(spec.expression, spec.func or "", spec.ics) if spec.kind == "ode" else None
    if stated is None:
        sentences = [s.strip() for s in re.split(r"\.\s+|[;\n]", normalised) if s.strip()]
        for s in sentences:
            if re.search(r"[A-Za-z]''|d\^?2[A-Za-z]/dt\^?2|d[A-Za-z]/dt", s):
                spec_cand = parse_problem(s)
                if spec_cand.kind == "ode":
                    stated_cand = stated_ode_system(spec_cand.expression, spec_cand.func or "", spec_cand.ics)
                    if stated_cand:
                        spec = spec_cand
                        stated = stated_cand
                        break
    if spec.kind != "ode" or stated is None:
        return None
    fname = (spec.func or "").split("(")[0]
    initial_names = set(re.findall(r"\b([A-Za-z_]\w*)'*\(\s*0\s*\)\s*=", q))
    if initial_names - {fname}:
        return None  # another state/ODE is present: this scalar adapter does not cover the whole request
    step = re.search(
        rf"\b(?:fixed\s+)?(?:time\s+)?step(?:\s+size)?\s*(?:of|=|:)?\s*({NUMBER})\s*({TIME_UNIT})(?!\w)",
        q,
        re.I,
    )
    h = _quantity(step[1], step[2], "s") if step else None
    count = _steps(q)
    ends = [t for t in _time_at(q) if t > 0]
    if not ends:
        m_to = re.search(rf"\bto\s+({NUMBER})\s*({TIME_UNIT})", q, re.I)
        if m_to:
            ends = [_quantity(m_to[1], m_to[2], "s")]
    end = ends[-1] if len(ends) == 1 else None
    errors = []
    if len(ends) > 1:
        return None  # multiple requested reporting times belong on the general path
    if end is None and count is not None and h is not None:
        end = count * h
    if end is None or (h is None and count is None):
        return None
    if (
        end is not None
        and h is not None
        and count is not None
        and not math.isclose(end, h * count, rel_tol=1e-10)
    ):
        errors.append(
            "The requested RK4 step, step count and final time disagree; none was substituted."
        )
    args = (
        {}
        if errors
        else {
            "rhs": stated["rhs"],
            "initial_state": stated["initial_state"],
            "t_span": [0.0, end],
            "method": "RK4",
            "step_size": h,
            "num_steps": count,
            "analytic_reference": bool(
                re.search(r"\b(?:analyt\w*|exact|closed[ -]form)\b", q, re.I)
            ),
        }
    )
    from tribos.dynamis.stated_ode import stated_units

    units = stated_units(normalised, spec.func or "", stated["state_names"])
    units["t"] = "s"
    if len(stated["state_names"]) == 2 and fname in units:
        units[stated["state_names"][1]] = units[fname] + "/s"
    if args:
        args["units"] = units
    return ScientificRequest(
        "ode_rk4",
        "dynamis_simulate_ode",
        args,
        3,
        errors,
        {"equation": spec.expression, "func": spec.func, "ics": spec.ics},
    )


def _rc_charge(q: str) -> ScientificRequest | None:
    if (re.search(r"capacitor|\bC\s*=|RC\s+circuit", q, re.I) and
            re.search(r"resistor|resistance|\bR\s*=|RC\s+circuit", q, re.I)):
        r = _assigned(q, r"R|resistance", r"[kM]?Ω|[kM]?ohms?", "ohm")
        c = _assigned(q, r"C|capacitance", r"[munμµ]?F", "F")
        source = re.search(rf"({NUMBER})\s*V\s+(?:ideal\s+)?(?:voltage\s+)?source", q, re.I)
        v = _number(source[1]) if source else _assigned(q, r"V_s|Vs|source\s+voltage", "V", "V")
        m_t = re.search(rf"\bt\s*=\s*({NUMBER})\s*({TIME_UNIT})", q, re.I)
        times = [_quantity(m_t[1], m_t[2], "s")] if m_t else [t for t in _time_at(q) if t > 0]
        if len(times) != 1 or not re.search(r"initially\s+uncharged|V_?c\(0\)\s*=\s*0", q, re.I):
            return None
        if any(x is None for x in (r, c, v)):
            return None
        return ScientificRequest(
            "rc_charge",
            "physis_engineering_calc",
            {
                "calculator": "rc_charge",
                "inputs": {
                    "resistance": r,
                    "capacitance": c,
                    "source_voltage": v,
                    "initial_voltage": 0.0,
                    "time": times[0],
                },
            },
            4,
        )
    return None


def _beam(q: str) -> ScientificRequest | None:
    if re.search(r"cantilever\s+beam", q, re.I) and re.search(r"rectangular|rectangle", q, re.I):
        if not re.search(r"free\s+end", q, re.I) or re.search(r"distributed\s+load|UDL", q, re.I):
            return None
        vals = {
            "length": _assigned(q, "L", "mm|cm|m", "m"),
            "point_load": _assigned(q, "P", "kN|N", "N"),
            "width": _assigned(q, "b", "mm|cm|m", "m"),
            "height": _assigned(q, "h", "mm|cm|m", "m"),
            "elastic_modulus": _assigned(q, "E", "GPa|MPa|Pa", "Pa"),
        }
        if any(v is None for v in vals.values()):
            return None
        return ScientificRequest(
            "beam",
            "physis_engineering_calc",
            {
                "calculator": "beam",
                "inputs": {
                    **vals,
                    "support": "cantilever",
                    "load": "point",
                    "section": "rectangle",
                },
            },
            4,
        )
    return None


def _engineering(q: str) -> ScientificRequest | None:
    if re.search(
        r"frequency|impedance|fatigue|buckling|nonlinear|sensitivity|optimis|optimiz|uncertainty",
        q,
        re.I,
    ):
        return None
    return _rc_charge(q) or _beam(q)


def parse_composite_scientific_request(query: str) -> CompositeScientificRequest | None:
    """Parse composite multi-task scientific evaluation queries."""
    q = (
        query.replace("−", "-")
        .replace("–", "-")
        .replace("’", "'")
        .replace("²", "^2")
        .replace("³", "^3")
    )
    q = re.sub(r"(?<=\d),(?=\d{3}(?:\D|$))", "", q)

    chunks = [s.strip() for s in re.split(r"(?m)^\s*(?:\d+[\.\)]|### Section \d+|Section \d+:?)", q) if s.strip()]
    if len(chunks) < 2:
        return None

    tasks: list[ScientificRequest] = []
    seen_kinds: set[str] = set()

    for chunk in chunks:
        for parser in (_rc_charge, _beam, _ode, _heat, _monte_carlo):
            try:
                req = parser(chunk)
                if req and req.kind not in seen_kinds:
                    tasks.append(req)
                    seen_kinds.add(req.kind)
                    break
            except Exception:
                continue

    if len(tasks) >= 2:
        return CompositeScientificRequest(
            kind="composite_scientific",
            tool="composite_scientific_suite",
            tasks=tasks,
            items=8,
            errors=[],
            context={"chunk_count": len(chunks)},
        )
    return None


def parse_scientific_request(query: str) -> ScientificRequest | CompositeScientificRequest | None:
    """Recognise a fully stated supported class; return None for broader or differently formatted work."""
    comp = parse_composite_scientific_request(query)
    if comp is not None:
        return comp

    from tribos.utils.output_contract import extract

    if re.search(
        r"\b(?:write|generate|provide)\b[^.\n]{0,50}\b(?:code|script|program)\b|\bcite\b|bibliograph|literature\s+review",
        query,
        re.I,
    ):
        return None  # code-writing/research deliverables require the general agent, not a computed-values renderer

    q = (
        query.replace("−", "-")
        .replace("–", "-")
        .replace("’", "'")
        .replace("²", "^2")
        .replace("³", "^3")
    )
    q = re.sub(r"(?<=\d),(?=\d{3}(?:\D|$))", "", q)
    for parser in (_monte_carlo, _heat, _ode, _engineering):
        try:
            request = parser(q)
        except (ValueError, TypeError, OverflowError):
            return None  # no speculative numeric coercion; the general path can clarify the original text
        if request is not None:
            contract = extract(query)
            if (
                contract.exact_words
                or contract.exact_lines
                or contract.literal
                or contract.exact_items not in (None, 0, request.items)
            ):
                return None
            return request
    return None
