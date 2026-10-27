"""The typed, versioned record of what a run computed: the problem as stated, its parameters and units, the computed
expressions and quantities with their provenance, solver settings, and (after verification) the claim outcomes.

The answer text, the result cards and the exports are views of a run; this record is the shared source they are
checked against. `revision` is a content hash of everything computed, so a check or an export can say which results it
describes, and a change in any computed value changes the revision (invalidating checks made against the old one).

Builders read the tools' structured outputs only (never model prose):
- the problem statement (tribos.axiom.problem.parse_problem): kind, equation, function, initial conditions, given values
- the verified mathematics agent (agent.math_agent.result): the answer expression and its verification status
- the ODE verification (ode_verification): characteristic quantities with their formulas and symbols, convergence,
  energy terms
- simulations (dynamis_*): solver settings, output sampling, sampled and dense extrema
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass, field
from typing import Any

RECORD_VERSION = "result-record/1"

# Units written after a given value in a question ("m = 2 kg", "c = 3 N·s/m").
_GIVEN_RE = re.compile(
    r"(?<![\w'(])(?P<name>[A-Za-z](?:_?[A-Za-z0-9]{1,3})?|[α-ωΑ-Ω](?:_?[A-Za-z0-9]{1,2})?)\s*=\s*"
    r"(?P<value>[-−+]?\d+(?:\.\d+)?(?:[eE][-+]?\d+)?)\s*(?P<unit>(?:[A-Za-zΩμ°]+(?:\s*[·*/^]\s*[A-Za-z0-9Ωμ]+)*)?)"
)
_GREEK_NAMES = {"ω": "omega", "ζ": "zeta", "φ": "phi", "θ": "theta", "λ": "lamda", "μ": "mu", "σ": "sigma",
                "τ": "tau", "α": "alpha", "β": "beta", "γ": "gamma", "δ": "delta", "ρ": "rho", "ν": "nu"}
_NOT_UNITS = {"and", "with", "the", "for", "over", "from", "to", "in", "at", "is", "or", "if", "then", "find"}


def canonical_name(name: str) -> str:
    """'F_0' and 'F0', 'ω' and 'omega', 'omega_n' and 'omegan' are one name."""
    out = str(name or "").strip()
    for g, word in _GREEK_NAMES.items():
        out = out.replace(g, word)
    return re.sub(r"[_{}\\\s]", "", out)


@dataclass
class Quantity:
    key: str
    value: float | str
    unit: str = ""
    formula: str = ""
    symbol: str = ""  # the symbol the tool's formula defines ("X" in "X = F0 / sqrt(...)")
    name_words: list[str] = field(default_factory=list)  # words a reader would use for it ("steady", "amplitude")
    convention: str = ""  # sign/phase convention when the value depends on one
    source: str = ""  # result key of the tool output
    status: str = "computed"  # computed | verified


@dataclass
class Expression:
    name: str  # "x(t)"
    function: str  # "x"
    variable: str  # "t"
    text: str  # SymPy syntax
    source: str = ""
    status: str = "computed"


@dataclass
class SolverRun:
    source: str
    method: str = ""
    rtol: float | None = None
    atol: float | None = None
    t_span: list[float] = field(default_factory=list)
    output_samples: int | None = None
    output_spacing: float | None = None
    internal_steps: int | None = None
    function_evaluations: int | None = None
    extrema: dict[str, Any] = field(default_factory=dict)


@dataclass
class ResultRecord:
    version: str = RECORD_VERSION
    revision: str = ""
    problem: dict[str, Any] = field(default_factory=dict)
    parameters: dict[str, dict[str, Any]] = field(default_factory=dict)  # canonical name -> {name, value, unit}
    assumptions: list[str] = field(default_factory=list)
    expressions: list[Expression] = field(default_factory=list)
    quantities: list[Quantity] = field(default_factory=list)
    solvers: list[SolverRun] = field(default_factory=list)
    provenance: list[dict[str, Any]] = field(default_factory=list)
    verification: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return json.loads(json.dumps(asdict(self), default=str))

    def stamp(self) -> None:
        body = {k: v for k, v in self.to_dict().items() if k not in ("revision", "verification")}
        self.revision = hashlib.sha256(json.dumps(body, sort_keys=True).encode()).hexdigest()[:16]


def given_values(text: str, scoped: set[str] | frozenset[str] = frozenset()) -> dict[str, dict[str, Any]]:
    """Values a question states as "name = number unit"; function values such as x(0) = 0.1 are excluded. A name the
    question assigns different values ("Case A: n = 40. Case B: n = 41.") or names case-local (`scoped`) is not a
    parameter of the whole problem: each value belongs to its own case, so none is kept here."""
    out: dict[str, dict[str, Any]] = {}
    seen: dict[str, set[float]] = {}
    for m in _GIVEN_RE.finditer(text or ""):
        raw = m.group("name")
        tail = (text or "")[m.end():]
        if re.match(r"\s*,\s*\d+", tail):
            continue
        unit = (m.group("unit") or "").strip()
        if unit.split(" ")[0].lower() in _NOT_UNITS:
            unit = ""
        try:
            value = float(m.group("value").replace("−", "-"))
        except ValueError:
            continue
        c = canonical_name(raw)
        seen.setdefault(c, set()).add(value)
        out.setdefault(c, {"name": raw, "value": value, "unit": unit})
    scoped_c = {canonical_name(s) for s in scoped}
    return {c: v for c, v in out.items() if len(seen[c]) == 1 and c not in scoped_c}


def _formula_symbol(formula: str) -> str:
    m = re.match(r"\s*([A-Za-z][A-Za-z0-9_]*)\s*=", formula or "")
    return m.group(1) if m else ""


def _num(v: Any) -> float | None:
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _answer_expression(data: dict[str, Any], func: str, var: str, source: str) -> Expression | None:
    answer = (data.get("answer") or {}) if isinstance(data, dict) else {}
    text = str(answer.get("text") or "")
    m = re.match(r"\s*([A-Za-z]\w*)\s*\(\s*([A-Za-z])\s*\)\s*=\s*(.+)$", text, re.S)
    if m:
        return Expression(name=f"{m.group(1)}({m.group(2)})", function=m.group(1), variable=m.group(2),
                          text=m.group(3).strip(), source=source,
                          status="verified" if data.get("status") == "verified" else "computed")
    if func and text and "=" not in text:
        return Expression(name=f"{func}({var})", function=func, variable=var, text=text.strip(), source=source)
    return None


_UNKNOWN_KINDS = frozenset({"solve", "inequality", "optimize"})


def build_result_record(query: str, tool_results: dict[str, Any]) -> ResultRecord:
    """The record of a run from its structured tool outputs (successful ones only)."""
    rec = ResultRecord()
    try:
        from ..axiom.problem import parse_problem

        spec = parse_problem(query or "")
        rec.problem = {
            "text": (query or "")[:4000],
            "kind": getattr(spec, "kind", ""),
            "equation": getattr(spec, "expression", "") or "",
            "function": getattr(spec, "func", "") or "",
            "variable": str(getattr(spec, "variable", "") or ""),
            "initial_conditions": dict(getattr(spec, "ics", None) or {}),
        }
        if getattr(spec, "kind", "") in _UNKNOWN_KINDS:
            # The unknowns of a solve / inequality / extremum task take many values in one answer (roots, endpoints,
            # critical points): "x = 0" there is a case being examined, never a definition of x.
            rec.problem["unknowns"] = [str(v) for v in (getattr(spec, "variables", None) or [getattr(spec, "variable", None)]) if v]
        if getattr(spec, "kind", "") == "structured":
            # Definitions and case-local bindings (structured questions, axiom/definitions.py): the answer checker
            # evaluates defined functions through their branches and gives each case its own bindings.
            tasks = spec.params.get("tasks") or []
            rec.problem["definitions"] = spec.params.get("definitions") or []
            rec.problem["cases"] = [{"id": t["id"], "bindings": t["bindings"]} for t in tasks if t.get("bindings")]
            # Names bound in two or more cases are case-local; a single substitution ("evaluate n^2 + 1 for n = 3")
            # stays a parameter of the problem. A claim's variable is case-local too: "n = 40 gives 1681" and
            # "n = 41 gives 1763" are two tested values.
            bound = [k for t in tasks for k in (t.get("bindings") or {})]
            cases = rec.problem["cases"]
            case_vars = {k for c in cases for k in c.get("bindings", {})} if len(cases) > 1 else {k for k in bound if bound.count(k) > 1}
            rec.problem["case_scoped"] = sorted(case_vars | {t["variable"] for t in tasks if t.get("op") == "claim" and t.get("variable")})
        m_local = re.search(r"\b([a-z])\s+local\s+to\s+each\b", str(query or "").lower())
        if m_local:
            existing = set(rec.problem.get("case_scoped") or ())
            existing.add(m_local.group(1))
            rec.problem["case_scoped"] = sorted(existing)
    except Exception:  # noqa: BLE001 - an unparsed question still gets a record of its tool outputs
        rec.problem = {"text": (query or "")[:4000], "kind": "unknown"}
    def_params = {d["parameter"] for d in rec.problem.get("definitions") or [] if isinstance(d, dict) and d.get("parameter")}
    prob_vars = {rec.problem.get("variable")} if rec.problem.get("variable") else set()
    prob_unknowns = set(rec.problem.get("unknowns") or ())
    prob_assumptions = set(rec.problem.get("assumptions") or ())
    scoped_symbols = (
        set(rec.problem.get("case_scoped") or ())
        | def_params
        | prob_vars
        | prob_unknowns
        | prob_assumptions
    )
    rec.parameters = given_values(query or "", scoped_symbols)
    func_name = re.sub(r"\(.*$", "", str(rec.problem.get("function") or ""))
    var = str(rec.problem.get("variable") or "t")

    for key, res in (tool_results or {}).items():
        if res is None or not getattr(res, "success", False):
            continue
        data = getattr(res, "data", None)
        if not isinstance(data, dict):
            continue
        tool = str(getattr(res, "tool_name", "") or "")
        rec.provenance.append({"key": str(key), "tool": tool, "success": True})
        if tool == "axiom_solve_problem" or str(key).endswith("math_agent.result"):
            expr = _answer_expression(data, func_name, var, str(key))
            if expr is not None:
                rec.expressions.append(expr)
        if tool == "ode_verification" or key == "ode_verification":
            for qkey, p in (data.get("parameters") or {}).items():
                if not isinstance(p, dict):
                    continue
                value = p.get("value")
                if _num(value) is None:
                    continue
                rec.quantities.append(Quantity(
                    key=str(qkey), value=float(value), unit=str(p.get("unit") or ""), formula=str(p.get("formula") or ""),
                    symbol=_formula_symbol(str(p.get("formula") or "")),
                    name_words=[w for w in str(qkey).split("_") if len(w) > 2],
                    convention=str(p.get("convention") or ""), source=str(key), status="computed",
                ))
        sim = data.get("solver") if isinstance(data.get("solver"), dict) else None
        if sim is not None or tool.startswith("dynamis_simulate"):
            s = sim or {}
            rec.solvers.append(SolverRun(
                source=str(key), method=str(s.get("method") or data.get("method") or ""),
                rtol=_num(s.get("rtol")), atol=_num(s.get("atol")),
                t_span=[float(x) for x in (s.get("t_span") or data.get("t_span") or []) if _num(x) is not None],
                output_samples=s.get("output_samples"), output_spacing=_num(s.get("output_spacing")),
                internal_steps=s.get("internal_steps"), function_evaluations=s.get("function_evaluations"),
                extrema=dict(data.get("extrema") or {}),
            ))
    rec.stamp()
    return rec


__all__ = [
    "Expression",
    "Quantity",
    "RECORD_VERSION",
    "ResultRecord",
    "SolverRun",
    "build_result_record",
    "canonical_name",
    "given_values",
]
