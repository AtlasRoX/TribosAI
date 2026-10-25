"""
Questions that define their own functions, evaluate independent cases, or state a universal claim.

The generic parsers in problem.py read "T(n) = n/2" as an equation in two unknowns T and n, and "f(x) - x^2 = 1" as
the product f*x minus x^2. This module keeps what such questions actually say, as plain JSON-friendly data:

- function definitions: name, parameter, declared domain and branches, each branch with its own condition
  ("n/2 for even positive integers", "2t - 3 if t < 0", "t^2 otherwise");
- tasks, each with an id taken from the question: evaluate an expression that applies the defined functions
  ("T(4)", "f(2) + f(3)"), iterate a function from a start value ("the cycle starting at 1"), evaluate one expression
  under case-local bindings ("Case A: n = 40"), or decide a universal claim ("... is prime for every nonnegative
  integer n");
- checks that are kept apart: interpretation (a defined function is applied, never multiplied), domain (every argument
  and witness lies in the stated domain and exactly one branch applies), computation (values recomputed by a second
  route), coverage (every requested item has a result).

All mathematics goes through the allowlist parser (engine.safe_parse_expr); nothing here evaluates user text, and
every search is bounded.
"""

from __future__ import annotations

import math
import re
from fractions import Fraction
from typing import Any

import sympy as sp
from sympy.core.function import AppliedUndef

from .engine import safe_parse_expr

DOMAINS = ("unspecified", "complex", "real", "rational", "integer", "nonnegative_integer", "positive_integer")
_INTEGER_DOMAINS = ("integer", "nonnegative_integer", "positive_integer")
CLAIM_SEARCH_LIMIT = 1000  # domain values tried when looking for a counterexample
ORBIT_LIMIT = 1000  # applications when iterating a function from a start value
_MAX_TASKS = 24

# Names that are mathematical functions, not user definitions ("sin(x) = 0" is an equation).
_RESERVED = frozenset({
    "sin", "cos", "tan", "cot", "sec", "csc", "sinh", "cosh", "tanh", "asin", "acos", "atan", "arcsin", "arccos",
    "arctan", "exp", "log", "ln", "sqrt", "abs", "floor", "ceil", "gcd", "lcm", "max", "min", "det", "lim", "sum",
    "Eq", "Abs", "re", "im", "arg", "sign", "mod", "deg", "rad", "P", "Pr", "E", "Var",
})

_REL_OPS = {"<=": sp.Le, ">=": sp.Ge, "!=": sp.Ne, "<": sp.Lt, ">": sp.Gt, "=": sp.Eq}
_UNICODE_REL = {"≤": "<=", "≥": ">=", "≠": "!=", "⩽": "<=", "⩾": ">="}
_NUMBER = r"[-+]?\d+(?:\.\d+)?(?:/\d+)?"


class DefinitionError(ValueError):
    """A definition cannot be applied at a value (outside its domain, no branch, ambiguous branches)."""


def _ascii_rel(text: str) -> str:
    for u, a in _UNICODE_REL.items():
        text = text.replace(u, a)
    return text


# Domains -------------------------------------------------------------------------------------------------------------

def domain_from_words(text: str) -> str | None:
    """The number set named in a phrase ("positive integers", "every real x", "ℤ", "R -> R")."""
    low = text.lower()
    if re.search(r"\bnon-?negative\s+(?:integers?|whole\s+numbers?)\b|\bwhole\s+numbers?\b|ℕ\s*[_∪]?\s*\{?0|\bn\s*0\b", low):
        return "nonnegative_integer"
    if re.search(r"\bpositive\s+integers?\b|\bnatural\s+numbers?\b|ℕ|ℤ\s*\+|ℤ_\{?>\s*0|\bz\s*\+", low):
        return "positive_integer"
    if re.search(r"\bintegers?\b|ℤ", low):
        return "integer"
    if re.search(r"\brationals?\b|\brational\s+numbers?\b|ℚ", low):
        return "rational"
    if re.search(r"\breals?\b|\breal\s+numbers?\b|ℝ", low):
        return "real"
    if re.search(r"\bcomplex\b|ℂ", low):
        return "complex"
    return None


def _domain_from_symbol(sym: str) -> str | None:
    return {"r": "real", "ℝ": "real", "z": "integer", "ℤ": "integer", "n": "positive_integer", "ℕ": "positive_integer",
            "q": "rational", "ℚ": "rational", "c": "complex", "ℂ": "complex"}.get(sym.strip().lower())


def in_domain(value: sp.Expr, domain: str) -> bool | None:
    """Membership of an exact value; None when it cannot be decided."""
    if domain in ("unspecified", "complex"):
        return bool(value.is_finite) if value.is_finite is not None else None
    if domain == "real":
        return value.is_extended_real and value.is_finite
    if domain == "rational":
        return value.is_rational
    if not value.is_integer:
        return False if value.is_integer is False or value.is_number else None
    v = int(value)
    return {"integer": True, "nonnegative_integer": v >= 0, "positive_integer": v >= 1}[domain]


def domain_label(domain: str) -> str:
    return {"positive_integer": "positive integers", "nonnegative_integer": "nonnegative integers", "integer": "integers",
            "rational": "rational numbers", "real": "real numbers", "complex": "complex numbers"}.get(domain, "its domain")


# Conditions ------------------------------------------------------------------------------------------------------------

def parse_condition(text: str, param: str) -> tuple[str, str | None] | None:
    """A branch condition phrase -> (condition, domain named in it). condition is "", "otherwise", "even", "odd" or a
    relation such as "t < 0"; None when the phrase is not understood."""
    low = _ascii_rel(text.strip().lower())
    dom = domain_from_words(low)
    if re.fullmatch(r"(?:for\s+|in\s+)?(?:all\s+)?(?:other(?:wise)?|else|elsewhere|all other\s+\w+(?:\s+\w+)?)", low) or low in ("otherwise", "else"):
        return "otherwise", dom
    if re.search(r"\beven\b", low):
        return "even", dom
    if re.search(r"\bodd\b", low):
        return "odd", dom
    m = re.search(rf"\b([a-z])\s*(<=|>=|!=|<|>|=)\s*({_NUMBER})\b", low)
    if m and m.group(1) == param:
        return f"{param} {m.group(2)} {m.group(3)}", dom
    m = re.search(r"\b([a-z])\s+(?:is\s+)?(positive|negative|nonzero|non-zero|zero|nonnegative|non-negative)\b", low)
    if m and m.group(1) == param:
        rel = {"positive": ">", "negative": "<", "nonzero": "!=", "non-zero": "!=", "zero": "=", "nonnegative": ">=", "non-negative": ">="}[m.group(2)]
        return f"{param} {rel} 0", dom
    if dom is not None and re.fullmatch(r"(?:for\s+|on\s+|over\s+)?(?:all\s+|every\s+|each\s+)?(?:the\s+)?[\w\s-]*?(?:\s+[a-z])?", low):
        return "", dom  # "for positive integers n": a domain, no branch condition
    return None


def condition_holds(condition: str, param: str, value: sp.Expr) -> bool | None:
    if condition in ("", "otherwise"):
        return True
    if condition in ("even", "odd"):
        if value.is_integer is not True:
            return False
        return (int(value) % 2 == 0) == (condition == "even")
    m = re.fullmatch(rf"{re.escape(param)}\s*(<=|>=|!=|<|>|=)\s*({_NUMBER})", condition)
    if not m:
        return None
    rhs = safe_parse_expr(m.group(2))
    if m.group(1) in ("=", "!="):
        same = sp.simplify(value - rhs) == 0
        return same if m.group(1) == "=" else not same
    if value.is_extended_real is not True:
        return None
    rel = _REL_OPS[m.group(1)](value, rhs)
    return bool(rel) if rel in (sp.true, sp.false) else None


# Definitions ---------------------------------------------------------------------------------------------------------

_DEF_HEAD_RE = re.compile(r"(?<![\w.'])([A-Za-z][A-Za-z0-9_]{0,15})\s*\(\s*([A-Za-z])\s*\)\s*=(?!=)\s*")
_DECL_RE = re.compile(r"(?<![\w.])([A-Za-z][A-Za-z0-9_]{0,15})\s*:\s*([A-Za-zℝℤℕℚℂ+_{}>0\s]{1,12}?)\s*(?:->|→)\s*([A-Za-zℝℤℕℚℂ+_{}>0]{1,12})")
_DEF_CUE_RE = re.compile(r"\b(?:define|defined|definition|let|where|with|given|suppose|consider|be|by|denote|denotes|set)\b|[:\-*•]\s*$", re.I)
_ACTION_RE = re.compile(
    r"\b(?:prove|show|verify|check|disprove|whether|true\s+that|solve|find|compute|evaluate|calculate|determine|what|"
    r"plot|graph|differentiate|integrate|simplify)\b", re.I)
_EXPR_END_RE = re.compile(
    r"\s+(?:for|if|when|whenever|provided|otherwise|else|on)\b|\s*[,;]|\.(?=\s|$)|\s+and\s+(?=[A-Za-z]\w*\s*\()|\n|$")
_COND_END_RE = re.compile(r"\s*[,;]|\.(?=\s|$)|\s+and\s+(?=[A-Za-z]\w*\s*\()|\n|$")


def _sentence_start(text: str, pos: int) -> int:
    cut = max(text.rfind(". ", 0, pos), text.rfind("? ", 0, pos), text.rfind("! ", 0, pos), text.rfind("\n", 0, pos))
    return cut + 1


def _is_definition_site(text: str, start: int) -> bool:
    prefix = text[_sentence_start(text, start):start]
    cue = list(_DEF_CUE_RE.finditer(prefix))
    act = list(_ACTION_RE.finditer(prefix))
    if act and (not cue or act[-1].start() > cue[-1].start()):
        return False
    if cue:
        return True
    return not prefix.strip(" \t-*•0123456789.)(") or bool(re.fullmatch(r"\s*(?:and|also|then)?\s*", prefix))


def parse_definitions(text: str) -> tuple[list[dict[str, Any]], list[tuple[int, int]], list[str]]:
    """Function definitions stated in the question -> (definitions, their text spans, problems). A definition the parser
    cannot represent faithfully is reported in problems instead of being guessed."""
    defs: dict[str, dict[str, Any]] = {}
    spans: list[tuple[int, int]] = []
    problems: list[str] = []
    declared: dict[str, str] = {}
    for m in _DECL_RE.finditer(text):
        dom = _domain_from_symbol(m.group(2)) or domain_from_words(m.group(2))
        if dom:
            declared[m.group(1)] = dom
            spans.append(m.span())
    for m in _DEF_HEAD_RE.finditer(text):
        name, param = m.group(1), m.group(2)
        if name in _RESERVED or name == param or not _is_definition_site(text, m.start()):
            continue
        rest = text[m.end():]
        end = _EXPR_END_RE.search(rest)
        expr_text = rest[: end.start() if end else len(rest)].strip()
        cond_text, stop = "", m.end() + (end.start() if end else len(rest))
        if end and re.match(r"\s+(?:for|if|when|whenever|provided|otherwise|else|on)\b", end.group(0)):
            tail = rest[end.start():]
            c_end = _COND_END_RE.search(tail, 1)
            cond_text = tail[: c_end.start() if c_end else len(tail)].strip()
            stop = m.end() + end.start() + (c_end.start() if c_end else len(tail))
        if not expr_text:
            continue
        if re.search(rf"(?<![\w.]){re.escape(name)}\s*\(", expr_text):
            problems.append(f"{name} is defined recursively; only explicit definitions are evaluated")
            continue
        try:
            body = safe_parse_expr(_ascii_rel(expr_text), local_dict={param: sp.Symbol(param)})
        except Exception:  # noqa: BLE001 - not a formula: not a definition this module can represent
            continue
        cond = parse_condition(cond_text, param) if cond_text else ("", None)
        if cond is None:
            problems.append(f"the condition {cond_text!r} of {name} is not understood")
            continue
        condition, cond_domain = cond
        entry = defs.setdefault(name, {"name": name, "parameter": param, "domain": None, "branches": []})
        if entry["parameter"] != param:
            body = body.subs(sp.Symbol(param), sp.Symbol(entry["parameter"]))
            condition = condition.replace(param, entry["parameter"]) if condition not in ("even", "odd", "otherwise") else condition
        entry["branches"].append({"expression": sp.sstr(body), "condition": condition})
        if cond_domain:
            entry.setdefault("_domains", []).append(cond_domain)
        spans.append((m.start(), stop))
    out = []
    for name, entry in defs.items():
        branch_domains = set(entry.pop("_domains", []))
        if name in declared:
            entry["domain"] = declared[name]
        elif len(branch_domains) == 1:
            entry["domain"] = branch_domains.pop()
        elif any(b["condition"] in ("even", "odd") for b in entry["branches"]):
            entry["domain"] = "integer"
        else:
            m = re.search(rf"\b{re.escape(name)}\b[^.]*?\b(?:on|over)\s+(?:the\s+)?([\w\s-]+?)(?:\s+by\b|[.,]|$)", text)
            entry["domain"] = (domain_from_words(m.group(1)) if m else None) or "unspecified"
        conds = [b["condition"] for b in entry["branches"]]
        if len(conds) > 1 and "" in conds:
            problems.append(f"{name} has several formulas without branch conditions")
            continue
        out.append(entry)
    return out, spans, problems


def function_symbols(defs: list[dict[str, Any]]) -> dict[str, Any]:
    return {d["name"]: sp.Function(d["name"]) for d in defs}


def parse_with_definitions(text: str, defs: list[dict[str, Any]], extra: dict[str, Any] | None = None) -> sp.Expr:
    """Parse an expression in which the defined names are function applications, never products."""
    local = dict(function_symbols(defs))
    local.update(extra or {})
    return safe_parse_expr(_ascii_rel(text), local_dict=local)


def apply_definition(defn: dict[str, Any], value: sp.Expr) -> tuple[sp.Expr, int]:
    """Exact value of a defined function at an exact argument -> (value, index of the branch used)."""
    name, param, domain = defn["name"], defn["parameter"], defn.get("domain") or "unspecified"
    member = in_domain(value, domain)
    if member is False:
        raise DefinitionError(f"{name}({value}) is undefined: {value} is not in the domain of {name} ({domain_label(domain)})")
    x = sp.Symbol(param)
    chosen = [i for i, b in enumerate(defn["branches"]) if b["condition"] != "otherwise" and condition_holds(b["condition"], param, value) is True]
    undecided = [i for i, b in enumerate(defn["branches"]) if condition_holds(b["condition"], param, value) is None]
    if undecided:
        raise DefinitionError(f"cannot decide which branch of {name} applies at {param} = {value}")
    if not chosen:
        chosen = [i for i, b in enumerate(defn["branches"]) if b["condition"] == "otherwise"]
    if not chosen:
        raise DefinitionError(f"no branch of {name} applies at {param} = {value}")
    results = {sp.simplify(safe_parse_expr(defn["branches"][i]["expression"], local_dict={param: x}).subs(x, value)) for i in chosen}
    if len(results) > 1:
        raise DefinitionError(f"branches of {name} disagree at {param} = {value}")
    out = results.pop()
    if out.has(sp.zoo, sp.nan) or out.is_finite is False:
        raise DefinitionError(f"{name}({value}) is undefined (division by zero)")
    return out, chosen[0]


def evaluate(expr: sp.Expr, defs: list[dict[str, Any]], trace: list[dict[str, Any]] | None = None) -> sp.Expr:
    """Replace every application of a defined function by its value, innermost first; record each application."""
    by_name = {d["name"]: d for d in defs}
    for _ in range(200):
        apps = [a for a in expr.atoms(AppliedUndef) if a.func.__name__ in by_name and not a.args[0].atoms(AppliedUndef)]
        if not apps:
            break
        repl = {}
        for app in apps:
            defn = by_name[app.func.__name__]
            arg = app.args[0]
            if arg.free_symbols:
                if len(defn["branches"]) != 1 or defn["branches"][0]["condition"] not in ("", "otherwise"):
                    raise DefinitionError(f"{app} has a symbolic argument and {defn['name']} has several branches")
                x = sp.Symbol(defn["parameter"])
                repl[app] = safe_parse_expr(defn["branches"][0]["expression"], local_dict={x.name: x}).subs(x, arg)
                if trace is not None:
                    trace.append({"function": defn["name"], "argument": sp.sstr(arg), "branch": 0, "value": sp.sstr(repl[app]), "symbolic": True})
                continue
            val, branch = apply_definition(defn, arg)
            repl[app] = val
            if trace is not None:
                trace.append({"function": defn["name"], "argument": sp.sstr(arg), "branch": branch, "value": sp.sstr(val)})
        expr = expr.xreplace(repl)
    return expr


def singular_points(expr_text: str, variable: str) -> list[sp.Expr]:
    """Real points where a written expression is undefined because a written denominator vanishes. SymPy cancels x/x
    to 1 while parsing, so the denominators are read from the text itself."""
    x = sp.Symbol(variable)
    points: set[sp.Expr] = set()
    for m in re.finditer(r"/\s*(\((?:[^()]|\([^()]*\))*\)|[A-Za-z0-9_.^]+)", expr_text):
        try:
            den = safe_parse_expr(m.group(1), local_dict={variable: x})
        except Exception:  # noqa: BLE001
            continue
        if x in den.free_symbols:
            try:
                points.update(r for r in sp.solve(sp.Eq(den, 0), x) if r.is_real)
            except Exception:  # noqa: BLE001
                continue
    return sorted(points, key=lambda v: float(v))


# Task parsing ----------------------------------------------------------------------------------------------------------

# "Case A: n = 40." / "(b) x = 3, y = 4;" -- inline, because normalisation joins the question into one line.
_BINDINGS = rf"(?:[A-Za-z]\w*\s*=\s*{_NUMBER}\s*(?:,|and)?\s*)+?"
_CASE_RE = re.compile(
    rf"(?:\b(?P<word>[Cc]ase)\s+\(?(?P<label>[A-Za-z0-9]{{1,3}})\)?\s*[:.)]|(?:^|(?<=[\s:;]))\((?P<plabel>[A-Za-z0-9]{{1,3}})\))"
    rf"\s*(?P<bindings>{_BINDINGS})(?=\.\s|\.$|;|$|\s*\b[Cc]ase\b|\s*\([A-Za-z0-9]{{1,3}}\))")
_CASES_EXPR_RE = re.compile(
    r"(?i)\b(?:evaluate|compute|calculate|find|determine|work\s+out)\s+(?:the\s+value\s+of\s+)?(?P<expr>.+?)\s+"
    r"(?:in|for|under|across|on)\s+(?:each\s+of\s+)?(?:the\s+)?(?:following\s+)?(?:\w+\s+)?(?:independent\s+|separate\s+|following\s+)?cases?\b")
_ORBIT_RE = re.compile(r"(?i)\b(cycle|orbit|trajectory|sequence|iterates?|iteration)\b")
_ORBIT_START_RE = re.compile(rf"(?i)\b(?:start(?:ing)?|beginning|begin|from)\s+(?:at|from|with)?\s*(?:[a-z]\s*=\s*)?({_NUMBER})\b")
_CLAIM_RE = re.compile(
    r"(?is)\b(?:prove\s+or\s+disprove|prove|show|verify|disprove|demonstrate|determine\s+whether|check\s+whether|"
    r"decide\s+whether|is\s+it\s+true)\s+(?:that\s+)?(?P<stmt>(?:[^.?!;\n]|!=)+?)\s+"
    r"(?P<q>for\s+(?:every|all|each|any)\s+(?:[^.?!;\n]|!=|\.\d)+?)\s*(?:[.?;\n]|!(?!=)|$)")
_PREDICATE_RE = re.compile(
    r"(?i)^(?P<expr>.+?)\s+is\s+(?:always\s+)?(?:a\s+|an\s+)?(?P<pred>prime|composite|even|odd|positive|negative|"
    r"non-?negative|nonzero|non-zero|integer|perfect\s+square)(?:\s+(?:number|integer))?$")
_DIVISIBLE_RE = re.compile(r"(?i)^(?P<expr>.+?)\s+is\s+(?:always\s+)?divisible\s+by\s+(?P<d>\S+)$")
_EVAL_VERB_RE = re.compile(r"(?i)\b(?:compute|evaluate|calculate|find|determine|give|state|what\s+(?:is|are))\b")
_NOT_A_VALUE_RE = re.compile(
    r"(?i)\b(?:derivative|integral|limit|roots?|zeros?|solutions?|maximum|minimum|inverse|graph|plot|domain|range|"
    r"period|series|slope|tangent|cycle|orbit|sequence|iterat\w*|whether|prove|show)\b")
_FACTOR_RE = re.compile(r"(?i)\bfactori[sz]ations?\b|\bfactor(?:ed|s|ise|ize)?\b|\bprime\s+factors\b")


def _split_top(text: str) -> list[str]:
    parts, depth, cur = [], 0, ""
    i = 0
    while i < len(text):
        ch = text[i]
        depth += ch in "([{"
        depth -= ch in ")]}"
        if depth == 0 and (ch in ",;" or text.startswith(" and ", i)):
            parts.append(cur)
            cur = ""
            i += 5 if text.startswith(" and ", i) else 1
            continue
        cur += ch
        i += 1
    parts.append(cur)
    return [p.strip(" .?!:") for p in parts if p.strip(" .?!:")]


def _mask(text: str, spans: list[tuple[int, int]]) -> str:
    out = list(text)
    for a, b in spans:
        for i in range(a, min(b, len(out))):
            if out[i] != "\n":
                out[i] = " "
    return "".join(out)


def _application_tasks(text: str, defs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    names = "|".join(re.escape(d["name"]) for d in defs)
    tasks: list[dict[str, Any]] = []
    for sentence in re.split(r"(?<=[.?!])\s+|\n+", text):
        verb = _EVAL_VERB_RE.search(sentence)
        if not verb or not re.search(rf"(?<![\w.])(?:{names})\s*\(", sentence):
            continue
        body = sentence[verb.end():]
        if _CLAIM_RE.search(sentence):
            continue
        for piece in _split_top(body):
            piece = re.sub(r"(?i)^(?:also|then|the\s+values?\s+of|the\s+value|values?\s+of|of)\s+", "", piece).strip()
            if _NOT_A_VALUE_RE.search(piece):
                continue
            if not re.search(rf"(?<![\w.])(?:{names})\s*\(", piece):
                try:  # a closed numeric expression in the same request ("h(4) and 3*4 + 2")
                    closed = not parse_with_definitions(piece, defs).free_symbols and re.search(r"\d", piece)
                except Exception:  # noqa: BLE001
                    closed = False
                if closed and not re.search(r"[A-Za-z]{2,}", piece):
                    tasks.append({"id": re.sub(r"\s+", "", piece), "op": "evaluate", "expression": piece})
                continue
            if re.search(r"[A-Za-z]{3,}", re.sub(rf"(?<![\w.])(?:{names})\s*\(", "(", piece)):
                continue  # words around the application: not a bare expression to evaluate
            try:
                parse_with_definitions(piece, defs)
            except Exception:  # noqa: BLE001
                continue
            tasks.append({"id": re.sub(r"\s+", "", piece), "op": "evaluate", "expression": piece})
    return tasks


def _orbit_tasks(text: str, defs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    tasks = []
    for sentence in re.split(r"(?<=[.?!])\s+|\n+", text):
        kind = _ORBIT_RE.search(sentence)
        start = _ORBIT_START_RE.search(sentence)
        if not kind or not start:
            continue
        named = [d["name"] for d in defs if re.search(rf"(?<![\w.]){re.escape(d['name'])}(?![\w(])|(?<![\w.]){re.escape(d['name'])}\s*\(", sentence)]
        fn = named[0] if len(named) == 1 else defs[0]["name"] if len(defs) == 1 else None
        if fn is None:
            continue
        steps = re.search(r"(?i)\b(\d+)\s+(?:times|iterations|steps|applications)\b", sentence)
        mode = "cycle" if re.search(r"(?i)\bcycle\b", sentence) else "steps" if steps else "until_repeat"
        task = {"id": f"{kind.group(1).lower()} from {start.group(1)}", "op": "orbit", "function": fn, "start": start.group(1), "mode": mode}
        if steps:
            task["steps"] = int(steps.group(1))
        tasks.append(task)
    return tasks


def _case_tasks(text: str, defs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    cases = list(_CASE_RE.finditer(text))
    if not cases or not (any(m.group("word") for m in cases) or (len(cases) >= 2 and re.search(r"(?i)\bcases?\b", text))):
        return []
    head = _CASES_EXPR_RE.search(text[: cases[0].start()])
    if not head:
        return []
    expr = head.group("expr").strip(" :,")
    try:
        parsed = parse_with_definitions(expr, defs)
    except Exception:  # noqa: BLE001
        return []
    factor = bool(_FACTOR_RE.search(text))
    tasks = []
    for m in cases:
        bindings = dict(re.findall(rf"([A-Za-z]\w*)\s*=\s*({_NUMBER})", m.group("bindings")))
        if not set(bindings) & {s.name for s in parsed.free_symbols}:
            return []
        label = f"Case {m.group('label')}" if m.group("word") else f"({m.group('plabel')})"
        tasks.append({"id": label, "op": "evaluate", "expression": expr, "bindings": bindings, "factor": factor})
    return tasks


_SUBSTITUTION_RE = re.compile(
    rf"(?i)\b(?:evaluate|compute|calculate|find|determine|work\s+out)\s+(?:the\s+value\s+of\s+)?(?P<expr>[^.?;]+?)\s+"
    rf"(?:for|at|when|with|if|where|given)\s+(?P<bindings>(?:[A-Za-z]\w*\s*=\s*{_NUMBER}\s*(?:,\s*(?:and\s+)?|\s+and\s+)?)+)"
    rf"\s*(?:[.?;]|$)")


def _substitution_tasks(text: str, defs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """"Evaluate n^2 + 1 for n = 3", "compute 2x + y at x = 1, y = 4": one evaluation with its own bindings (read by
    the generic parsers as the equation n = 3 to solve)."""
    tasks = []
    for m in _SUBSTITUTION_RE.finditer(text):
        expr = m.group("expr").strip(" :,")
        bindings = dict(re.findall(rf"([A-Za-z]\w*)\s*=\s*({_NUMBER})", m.group("bindings")))
        try:
            parsed = parse_with_definitions(expr, defs)
        except Exception:  # noqa: BLE001
            continue
        if not bindings or not set(bindings) <= {s.name for s in parsed.free_symbols} or not re.search(r"[-+*/^(]", expr):
            continue
        label = ", ".join(f"{k} = {v}" for k, v in bindings.items())
        tasks.append({"id": f"{expr} at {label}", "op": "evaluate", "expression": expr, "bindings": bindings,
                      "factor": bool(_FACTOR_RE.search(text))})
    return tasks


def parse_quantifier(text: str, stmt_symbols: set[str]) -> tuple[str | None, str, list[str]] | None:
    """'for every nonnegative integer n' -> ("n", "nonnegative_integer", []); 'for all real x != 0' -> ("x", "real",
    ["x != 0"])."""
    q = _ascii_rel(text)
    dom = domain_from_words(q)
    conds = [f"{v} {op} {num}" for v, op, num in re.findall(rf"\b([a-z])\s*(<=|>=|!=|<|>)\s*({_NUMBER})", q)]
    names = [n for n in re.findall(r"\b([a-z])\b", q) if n in stmt_symbols]
    var = names[-1] if names else (next(iter(stmt_symbols)) if len(stmt_symbols) == 1 else None)
    if var is None:
        return None
    m = re.search(rf"\b{var}\s+in\s+(\S+)", q)
    if m and dom is None:
        dom = _domain_from_symbol(m.group(1)) or domain_from_words(m.group(1))
    if dom is None:
        if not re.search(r"\b(?:every|all|each|any)\s+[a-z]\b", q):
            return None
        dom = "unspecified"
    return var, dom, conds


def _claim_tasks(text: str, defs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    tasks = []
    for m in _CLAIM_RE.finditer(text):
        stmt = _ascii_rel(m.group("stmt").strip())
        claim: dict[str, Any] = {"id": "claim" if not tasks else f"claim {len(tasks) + 1}", "op": "claim"}
        pm, dm = _PREDICATE_RE.match(stmt), _DIVISIBLE_RE.match(stmt)
        if pm:
            claim.update(expression=pm.group("expr").strip(), predicate=re.sub(r"[\s-]+", "_", pm.group("pred").lower()).replace("non_negative", "nonnegative").replace("non_zero", "nonzero"))
            sides = [claim["expression"]]
        elif dm:
            claim.update(expression=dm.group("expr").strip(), predicate="divisible", divisor=dm.group("d").strip(" ."))
            sides = [claim["expression"], claim["divisor"]]
        else:
            rel = re.search(r"(<=|>=|!=|<|>|=)", stmt)
            if not rel:
                continue
            claim.update(lhs=stmt[: rel.start()].strip(), relation=rel.group(1), rhs=stmt[rel.end():].strip())
            sides = [claim["lhs"], claim["rhs"]]
        try:
            symbols = {s.name for side in sides for s in parse_with_definitions(side, defs).free_symbols}
        except Exception:  # noqa: BLE001
            continue
        fnames = {d["name"] for d in defs}
        symbols |= {v for side in sides for v in re.findall(r"(?<![\w.])([a-z])(?![\w(])", side) if v not in fnames}
        quant = parse_quantifier(m.group("q"), symbols)
        if quant is None:
            continue
        claim["variable"], claim["domain"], claim["conditions"] = quant
        claim["statement"] = f"{stmt} {m.group('q').strip()}"
        tasks.append(claim)
    return tasks


def parse_structured(text: str) -> tuple[dict[str, Any] | None, list[str]]:
    """The structured reading of a question -> (params {"definitions", "tasks"} or None, problems)."""
    defs, spans, problems = parse_definitions(text)
    rest = _mask(text, spans)
    tasks: list[dict[str, Any]] = []
    tasks += _case_tasks(rest, defs)
    if not tasks:
        tasks += _substitution_tasks(rest, defs)
    tasks += _claim_tasks(rest, defs)
    if defs:
        tasks += _orbit_tasks(rest, defs)
        tasks += _application_tasks(rest, defs)
    seen, unique = set(), []
    for t in tasks:
        key = (t["op"], t["id"])
        if key not in seen:
            seen.add(key)
            unique.append(t)
    if not unique:
        return None, problems
    return {"definitions": defs, "tasks": unique[:_MAX_TASKS]}, problems


# Execution -------------------------------------------------------------------------------------------------------------

def _value_text(v: sp.Expr) -> str:
    return sp.sstr(v)


def factor_text(value: sp.Expr) -> tuple[str, list[int]] | None:
    """'41^2' / '41 * 43' and the prime factors with multiplicity, for a nonzero integer value."""
    if value.is_integer is not True:
        return None
    n = int(value)
    if n == 0:
        return None
    sign = -1 if n < 0 else 1
    fs = sp.factorint(abs(n))
    flat = [p for p, k in sorted(fs.items()) for _ in range(k)]
    if not flat:
        return ("-1" if sign < 0 else "1"), []
    text = " * ".join(f"{p}^{k}" if k > 1 else str(p) for p, k in sorted(fs.items()))
    return ("-" + text if sign < 0 else text), flat


def _predicate(pred: str, value: sp.Expr, divisor: sp.Expr | None = None) -> bool | None:
    if pred in ("prime", "composite", "even", "odd", "perfect_square", "divisible"):
        if value.is_integer is not True:
            return False if value.is_number else None
        n = int(value)
        if pred == "prime":
            return bool(sp.isprime(n))
        if pred == "composite":
            return n > 1 and not sp.isprime(n)
        if pred == "even":
            return n % 2 == 0
        if pred == "odd":
            return n % 2 == 1
        if pred == "perfect_square":
            return n >= 0 and math.isqrt(n) ** 2 == n
        if divisor is None or divisor.is_integer is not True or int(divisor) == 0:
            return None
        return n % int(divisor) == 0
    if pred == "integer":
        return bool(value.is_integer) if value.is_integer is not None else None
    if value.is_extended_real is not True:
        return None
    return {"positive": value > 0, "negative": value < 0, "nonnegative": value >= 0, "nonzero": value != 0}[pred] in (True, sp.true)


def domain_values(domain: str, limit: int = CLAIM_SEARCH_LIMIT) -> list[sp.Expr]:
    if domain == "positive_integer":
        return [sp.Integer(k) for k in range(1, limit + 1)]
    if domain == "nonnegative_integer":
        return [sp.Integer(k) for k in range(limit)]
    if domain == "integer":
        out = [sp.Integer(0)]
        for k in range(1, limit // 2 + 1):
            out += [sp.Integer(k), sp.Integer(-k)]
        return out[:limit]
    # real / rational / unspecified: a fixed grid of exact rationals, symmetric about 0
    grid = {sp.Rational(p, q) for q in (1, 2, 3, 7) for p in range(-12 * q, 12 * q + 1)}
    return sorted(grid, key=lambda v: (abs(v), v))[:limit]


def _pretty(text: str) -> str:
    return str(text).replace("**", "^")


def _residue_proof(task: dict[str, Any], defs: list[dict[str, Any]], var: sp.Symbol, domain: str) -> dict[str, Any] | None:
    """Divisibility and parity of a polynomial over the integers: with D the common denominator of its coefficients,
    D*P(n) has integer coefficients, so D*P(n) mod D*d depends only on n mod D*d. Checking every residue proves (or
    refutes) the claim for all integers, and for the nonnegative or positive integers, which contain every residue."""
    pred = task.get("predicate")
    if pred not in ("divisible", "even", "odd") or domain not in _INTEGER_DOMAINS or task.get("conditions"):
        return None
    try:
        expr = evaluate(parse_with_definitions(task["expression"], defs, {var.name: var}), defs)
        d = 2 if pred != "divisible" else int(safe_parse_expr(str(task["divisor"])))
        poly = sp.Poly(sp.expand(expr), var)
    except Exception:  # noqa: BLE001 - not a polynomial in the variable: no residue argument
        return None
    if d == 0 or poly.free_symbols - {var} or not all(c.is_rational for c in poly.all_coeffs()):
        return None
    den = int(sp.ilcm(*[sp.Rational(c).q for c in poly.all_coeffs()], 1))
    mod = abs(d) * den
    if mod > 100_000:
        return None
    q = sp.Poly(poly.as_expr() * den, var)
    target = den % mod if pred == "odd" else 0
    for r in range(mod):
        if int(q.eval(r)) % mod != target:
            return None  # fails for some residue: the counterexample search below finds the witness
    what = {"divisible": f"divisible by {d}", "even": "even", "odd": "odd"}[pred]
    step = (f"{task['expression']} has {'integer' if den == 1 else 'rational'} coefficients, so "
            f"{'' if den == 1 else f'{den}*('}{task['expression']}{'' if den == 1 else ')'} mod {mod} depends only on {var} mod {mod}; "
            f"all {mod} residues give a value that is {what}")
    return {"status": "proved", "steps": [step], "method": f"exhaustive check of the residues modulo {mod}",
            "text": f"True: {task['statement']}. {step}."}


def _run_claim(task: dict[str, Any], defs: list[dict[str, Any]]) -> dict[str, Any]:
    var = sp.Symbol(task["variable"])
    extra = {var.name: var}
    conds = task.get("conditions") or []
    domain = task.get("domain") or "unspecified"
    steps: list[str] = []
    trace: list[dict[str, Any]] = []

    def holds_at(v: sp.Expr) -> tuple[bool | None, str]:
        if task.get("predicate"):
            e = evaluate(parse_with_definitions(task["expression"], defs, extra).subs(var, v), defs)
            d = parse_with_definitions(task["divisor"], defs, extra).subs(var, v) if task.get("divisor") else None
            ok = _predicate(task["predicate"], sp.simplify(e), d)
            detail = f"{task['expression']} = {_value_text(sp.simplify(e))}"
            ft = factor_text(sp.simplify(e)) if task["predicate"] in ("prime", "composite") else None
            if ft and len(ft[1]) > 1:
                detail += f" = {ft[0]}"
            return ok, detail
        lhs = evaluate(parse_with_definitions(task["lhs"], defs, extra).subs(var, v), defs)
        rhs = evaluate(parse_with_definitions(task["rhs"], defs, extra).subs(var, v), defs)
        rel = _REL_OPS[task["relation"]](sp.simplify(lhs), sp.simplify(rhs))
        ok = bool(rel) if rel in (sp.true, sp.false) else None
        return ok, f"{task['lhs']} = {_value_text(sp.simplify(lhs))}, {task['rhs']} = {_value_text(sp.simplify(rhs))}"

    def admissible(v: sp.Expr) -> bool:
        return in_domain(v, domain) is not False and all(condition_holds(c, var.name, v) is True for c in conds)

    # Symbolic proof of an equation: substitute the definitions, simplify, then look at points where the written
    # expression is undefined but the quantifier still includes them.
    if task.get("relation") == "=":
        try:
            lhs = evaluate(parse_with_definitions(task["lhs"], defs, extra), defs, trace)
            rhs = evaluate(parse_with_definitions(task["rhs"], defs, extra), defs, trace)
            for t in trace:
                defn = next(d for d in defs if d["name"] == t["function"])
                steps.append(f"{t['function']}({t['argument']}) = {_pretty(t['value'])} by the definition of {defn['name']}")
            diff = sp.simplify(lhs - rhs)
            if diff == 0:
                written = task["lhs"] + " - (" + task["rhs"] + ")"
                bad = [p for p in singular_points(written, var.name) + [p for t in trace for p in singular_points(
                    next(b["expression"] for b in next(d for d in defs if d["name"] == t["function"])["branches"]), t["argument"])
                    if t.get("symbolic")] if admissible(p)]
                if bad:
                    return {"status": "disproved", "counterexample": _value_text(bad[0]), "detail": f"undefined at {var} = {bad[0]} (division by zero)",
                            "steps": steps, "text": f"False as stated: the expression is undefined at {var} = {bad[0]}, which the statement includes."}
                written_lhs = task["lhs"]
                for t in trace:
                    if t.get("symbolic"):
                        written_lhs = re.sub(rf"(?<![\w.]){re.escape(t['function'])}\s*\(\s*{re.escape(t['argument'])}\s*\)",
                                             f"({_pretty(t['value'])})", written_lhs)
                chain = f"{task['lhs']} = {written_lhs} = {_pretty(sp.sstr(sp.simplify(lhs)))}" if written_lhs != task["lhs"] else \
                    f"{task['lhs']} - ({task['rhs']}) simplifies to 0"
                steps.append(chain)
                return {"status": "proved", "steps": steps, "method": "substitution of the definitions and exact simplification",
                        "text": f"True: {task['statement']}. " + "; ".join(_pretty(x) for x in steps) + "."}
        except DefinitionError as exc:
            steps.append(str(exc))
    proof = _residue_proof(task, defs, var, domain)
    if proof is not None:
        return proof
    for v in domain_values(domain if domain in _INTEGER_DOMAINS else "real"):
        if not admissible(v):
            continue
        try:
            ok, detail = holds_at(v)
        except DefinitionError:
            continue
        if ok is False:
            witness = {var.name: _value_text(v)}
            sides = [task["expression"]] if task.get("predicate") else [task["lhs"], task["rhs"]]
            for side in sides:
                try:
                    side_value = sp.simplify(evaluate(parse_with_definitions(side, defs, extra).subs(var, v), defs))
                    steps += evaluation_steps({"expression": side, "bindings": witness,
                                               "factor": task.get("predicate") in ("prime", "composite")}, defs, side_value, [])
                except (DefinitionError, ValueError):
                    continue
            what = {"prime": "is not prime", "composite": "is not composite", "even": "is not even", "odd": "is not odd",
                    "divisible": f"is not divisible by {task.get('divisor')}"}.get(str(task.get("predicate")), "violates the relation")
            steps.append(f"So {var} = {_value_text(v)}, which lies in the stated domain, gives a value that {what}: "
                         "one counterexample refutes the universal statement.")
            return {"status": "disproved", "counterexample": _value_text(v), "detail": detail, "steps": steps,
                    "text": f"False: at {var} = {v}, {detail}" + (", which is not prime." if task.get("predicate") == "prime" else ".")}
    searched = f"{domain_label(domain)}" + (f" up to {CLAIM_SEARCH_LIMIT} values" if domain in _INTEGER_DOMAINS else " on a grid of rational points")
    return {"status": "unresolved", "steps": steps, "searched": searched,
            "text": f"No counterexample among the {searched}; this is evidence, not a proof."}


# Derivation steps ------------------------------------------------------------------------------------------------------
# Every step is generated from the exact computation, never written by a model: which branch applies and why, the
# formula with the value substituted, the terms evaluated, the result. The writer is told to use them verbatim.

def _plug(expr_text: str, values: dict[str, str]) -> str:
    """The written expression with each variable replaced by its value ("n^2 + n + 41" -> "40^2 + 40 + 41")."""
    out = _pretty(expr_text)
    for name, value in values.items():
        shown = f"({value})" if str(value).startswith("-") or "/" in str(value) else str(value)
        # "3n" with n = 1 is 3*1, never "31".
        out = re.sub(rf"(?<=\d){re.escape(name)}(?![\w(])", f"*{shown}", out)
        out = re.sub(rf"(?<![\w.]){re.escape(name)}(?![\w(])", shown, out)
    return out


def _top_level_terms(text: str) -> list[tuple[str, str]]:
    """[(sign, term)] of a written sum at parenthesis depth 0: "n^2 + n + 41" -> [("+","n^2"), ("+","n"), ("+","41")]."""
    terms, depth, cur, sign = [], 0, "", "+"
    for i, ch in enumerate(text):
        depth += ch == "("
        depth -= ch == ")"
        if depth == 0 and ch in "+-" and cur.strip() and not re.search(r"[*/^(]\s*$", cur):
            terms.append((sign, cur.strip()))
            cur, sign = "", ch
            continue
        if depth == 0 and ch in "+-" and not cur.strip() and i == 0:
            sign = ch
            continue
        cur += ch
    if cur.strip():
        terms.append((sign, cur.strip()))
    return terms


def _term_values(expr_text: str, defs: list[dict[str, Any]], values: dict[str, sp.Expr]) -> str | None:
    """'1600 + 40 + 41' for a written sum: each term evaluated, in the question's order; None for a single term."""
    terms = _top_level_terms(expr_text)
    if len(terms) < 2:
        return None
    parts = []
    for sign, term in terms:
        v = parse_with_definitions(term, defs, {k: sp.Symbol(k) for k in values}).xreplace(
            {sp.Symbol(k): val for k, val in values.items()})
        parts.append((sign, _pretty(sp.sstr(sp.simplify(evaluate(v, defs))))))
    out = parts[0][1] if parts[0][0] == "+" else f"-{parts[0][1]}"
    for sign, val in parts[1:]:
        out += f" {sign} {val}"
    return out.replace("+ -", "- ").replace("- -", "+ ")


def _condition_reason(condition: str, param: str, value: sp.Expr) -> str:
    if condition == "even":
        return f"{_pretty(sp.sstr(value))} is even"
    if condition == "odd":
        return f"{_pretty(sp.sstr(value))} is odd"
    if condition == "otherwise":
        return "no other branch applies"
    if condition:
        return condition.replace(param, _pretty(sp.sstr(value)), 1)
    return ""


def application_step(defn: dict[str, Any], value: sp.Expr, branch: int, result: sp.Expr) -> str:
    """"T(1): 1 is odd, so T(1) = 3*1 + 1 = 4" from the branch actually used."""
    b = defn["branches"][branch]
    arg = _pretty(sp.sstr(value))
    plugged = _plug(b["expression"], {defn["parameter"]: sp.sstr(value)})
    reason = _condition_reason(b["condition"], defn["parameter"], value)
    if b["condition"] == "otherwise":
        # Say why the other branches do not apply ("0 < 0 is false"), not only that this one is left.
        failed = []
        for other in defn["branches"]:
            c = other["condition"]
            if c in ("even", "odd"):
                failed.append(f"{arg} is not {c}")
            elif c not in ("", "otherwise"):
                failed.append(f"{c.replace(defn['parameter'], arg, 1)} is false")
        reason = (", ".join(failed) + ", so the remaining branch applies") if failed else reason
    lhs = f"{defn['name']}({arg})"
    body = f"{lhs} = {plugged} = {_pretty(sp.sstr(result))}" if plugged != _pretty(sp.sstr(result)) else f"{lhs} = {plugged}"
    return f"{reason}, so {body}" if reason else body


def evaluation_steps(task: dict[str, Any], defs: list[dict[str, Any]], value: sp.Expr, trace: list[dict[str, Any]]) -> list[str]:
    steps: list[str] = []
    by_name = {d["name"]: d for d in defs}
    for app in trace:
        defn = by_name.get(app["function"])
        if defn is not None and not app.get("symbolic"):
            steps.append(application_step(defn, _exact_value(app["argument"]), app["branch"], _exact_value(app["value"])))
    bindings = {k: str(v) for k, v in (task.get("bindings") or {}).items()}
    if bindings:
        plugged = _plug(task["expression"], bindings)
        terms = _term_values(task["expression"], defs, {k: _exact_value(v) for k, v in bindings.items()})
        chain = [_pretty(task["expression"]), plugged] + ([terms] if terms and terms != plugged else []) + [_pretty(sp.sstr(value))]
        steps.append(f"With {', '.join(f'{k} = {v}' for k, v in bindings.items())}: " + " = ".join(dict.fromkeys(chain)))
    if task.get("factor"):
        ft = factor_text(value)
        if ft is not None:
            primes = sorted(set(ft[1]))
            steps.append(f"{_pretty(sp.sstr(value))} = {ft[0]}" + (
                f", where {', '.join(map(str, primes))} {'is' if len(primes) == 1 else 'are'} prime" if primes else ""))
    return steps


def _run_orbit(task: dict[str, Any], defs: list[dict[str, Any]]) -> dict[str, Any]:
    defn = next(d for d in defs if d["name"] == task["function"])
    value = safe_parse_expr(str(task["start"]))
    seq, branches = [value], []
    limit = min(int(task.get("steps") or ORBIT_LIMIT), ORBIT_LIMIT)
    steps: list[str] = []
    for _ in range(limit):
        prev = value
        value, branch = apply_definition(defn, value)
        seq.append(value)
        branches.append(branch)
        if len(steps) < 40:
            steps.append(application_step(defn, prev, branch, value))
        if task.get("mode") in ("cycle", "until_repeat") and value in seq[:-1]:
            break
    closed = seq[-1] in seq[:-1]
    if closed:
        steps.append(f"{_pretty(sp.sstr(seq[-1]))} appeared before, so the orbit repeats from here: "
                     + " -> ".join(_pretty(sp.sstr(v)) for v in seq[seq.index(seq[-1]):]))
    if task.get("mode") == "cycle" and closed and seq[-1] != seq[0]:
        # The cycle the orbit enters does not pass through the start value: report the cycle itself, separately.
        first = seq.index(seq[-1])
        cycle = seq[first:]
    else:
        cycle = seq if closed else []
    arrow = " -> ".join(map(_value_text, seq))
    text = arrow if not (task.get("mode") == "cycle" and not closed) else f"{arrow} (no repeat within {limit} applications)"
    return {"sequence": [_value_text(v) for v in seq], "branches": branches, "closed": closed, "steps": steps,
            "cycle": [_value_text(v) for v in cycle], "text": text}


def _clean(value: Any) -> Any:
    """Drop unset (None) fields, as a validated tool call carries every optional field."""
    if isinstance(value, dict):
        return {k: _clean(v) for k, v in value.items() if v is not None}
    if isinstance(value, list):
        return [_clean(v) for v in value]
    return value


def axiom_structured(definitions: list[dict[str, Any]] | None = None, tasks: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """Tool entry point (schema: AxiomStructuredInput)."""
    defs = _clean(list(definitions or []))
    for d in defs:
        d.setdefault("domain", "unspecified")
        for b in d["branches"]:
            b.setdefault("condition", "")
            safe_parse_expr(b["expression"], local_dict={d["parameter"]: sp.Symbol(d["parameter"])})  # validates the formula
    return run_structured(defs, _clean(list(tasks or [])))


def run_structured(definitions: list[dict[str, Any]], tasks: list[dict[str, Any]]) -> dict[str, Any]:
    """Execute every task against the definitions. A task that cannot be carried out reports its reason; it never
    falls back to a different problem."""
    results = []
    for task in tasks[:_MAX_TASKS]:
        res: dict[str, Any] = {"id": task["id"], "op": task["op"]}
        try:
            if task["op"] == "evaluate":
                bindings = {k: safe_parse_expr(str(v)) for k, v in (task.get("bindings") or {}).items()}
                trace: list[dict[str, Any]] = []
                expr = parse_with_definitions(task["expression"], definitions, {k: sp.Symbol(k) for k in bindings})
                value = sp.simplify(evaluate(expr.xreplace({sp.Symbol(k): v for k, v in bindings.items()}), definitions, trace))
                res.update(value=_value_text(value), bindings={k: _value_text(v) for k, v in bindings.items()}, applications=trace)
                label = ", ".join(f"{k} = {v}" for k, v in res["bindings"].items())
                res["text"] = f"{task['id']}" + (f" ({label})" if label and task["id"].lower().startswith("case") else "") + f": {res['value']}" \
                    if bindings else f"{task['expression']} = {res['value']}"
                if task.get("factor"):
                    ft = factor_text(value)
                    if ft is not None:
                        res["factorization"], res["factors"] = ft[0], [str(p) for p in ft[1]]
                        res["text"] += f" = {ft[0]}"
                res["steps"] = evaluation_steps(task, definitions, value, trace)
            elif task["op"] == "orbit":
                res.update(_run_orbit(task, definitions))
            elif task["op"] == "claim":
                res.update(_run_claim(task, definitions))
            else:
                raise ValueError(f"unknown task operation {task['op']!r}")
            res["status"] = res.get("status", "computed")
        except DefinitionError as exc:
            # "g(0) is undefined: 0 is not in the domain of g" answers the question that was asked.
            status = "undefined" if task["op"] == "evaluate" else "error"
            res.update(status=status, error=str(exc), text=f"{task['id']}: {exc}")
        results.append(res)
    return {"results": results, "text": "\n".join(r["text"] for r in results)}


def substitute_definitions(text: str) -> tuple[str, list[str]] | None:
    """The question with every application of a single-formula definition replaced by the formula ("the derivative
    of f(x)" with f(x) = x^2 + 1 -> "the derivative of (x**2 + 1)") and the definition statements blanked, so the other
    parsers can read the task. None when a definition has branches or the question defines nothing."""
    defs, spans, problems = parse_definitions(text)
    if not defs or problems or any(len(d["branches"]) != 1 or d["branches"][0]["condition"] not in ("", "otherwise") for d in defs):
        return None
    by_name = {d["name"]: d for d in defs}
    out = _mask(text, spans)
    out = re.sub(r"(?i)\b(?:let|define|suppose|consider|where|given)\b\s*(?:that\s+)?[,.;:]?", " ", out) if spans else out
    notes = []
    for _ in range(20):
        m = re.search(rf"(?<![\w.])({'|'.join(map(re.escape, by_name))})\s*\(", out)
        if not m:
            break
        depth, i = 1, m.end()
        while i < len(out) and depth:
            depth += {"(": 1, ")": -1}.get(out[i], 0)
            i += 1
        if depth:
            return None
        defn = by_name[m.group(1)]
        x = sp.Symbol(defn["parameter"])
        try:
            arg = safe_parse_expr(out[m.end(): i - 1])
            body = safe_parse_expr(defn["branches"][0]["expression"], local_dict={x.name: x}).subs(x, arg)
        except Exception:  # noqa: BLE001
            return None
        out = out[: m.start()] + f"({sp.sstr(body)})" + out[i:]
        notes.append(f"substituted the definition {defn['name']}({defn['parameter']}) = {_pretty(defn['branches'][0]['expression'])}")
    return re.sub(r"[ \t]{2,}", " ", out).strip(), list(dict.fromkeys(notes))


# Independent checks -----------------------------------------------------------------------------------------------------

def misread_functions(text: str, expressions: list[str]) -> list[str]:
    """Names the question defines as functions that a parse does not evaluate through their definition: used as plain
    symbols (T(n) read as T*n) or left as an unknown function application handed to a generic solver."""
    defs, _, _ = parse_definitions(text)
    names = {d["name"] for d in defs}
    if not names:
        return []
    bad = set()
    for e in expressions:
        if not e:
            continue
        for name in names:
            if re.search(rf"(?<![\w.]){re.escape(name)}(?!\w)", e):
                bad.add(name)
    return sorted(bad)


def _exact_value(text: str) -> sp.Expr:
    return safe_parse_expr(str(text))


def _second_route(expr_text: str, defs: list[dict[str, Any]], bindings: dict[str, str]) -> Fraction | None:
    """Recompute a value with rational arithmetic on the branch formulas, application by application, without SymPy's
    simplification of the whole expression. None when the expression is not rational-valued."""
    by_name = {d["name"]: d for d in defs}
    local = {k: sp.Symbol(k) for k in bindings}
    expr = parse_with_definitions(expr_text, defs, local).xreplace({sp.Symbol(k): sp.Rational(v) if re.fullmatch(_NUMBER, str(v)) else safe_parse_expr(str(v)) for k, v in bindings.items()})

    def walk(e: sp.Expr) -> Fraction:
        if isinstance(e, AppliedUndef) and e.func.__name__ in by_name:
            arg = walk(e.args[0])
            defn = by_name[e.func.__name__]
            val = sp.Rational(arg.numerator, arg.denominator)
            branch = None
            for b in defn["branches"]:
                if b["condition"] != "otherwise" and condition_holds(b["condition"], defn["parameter"], val):
                    branch = b
                    break
            branch = branch or next((b for b in defn["branches"] if b["condition"] == "otherwise"), None)
            if branch is None:
                raise DefinitionError("no branch")
            inner = safe_parse_expr(branch["expression"], local_dict={defn["parameter"]: sp.Symbol(defn["parameter"])})
            return walk(inner.xreplace({sp.Symbol(defn["parameter"]): val}))
        if e.is_Rational:
            return Fraction(int(e.p), int(e.q))
        if isinstance(e, sp.Add):
            return sum((walk(a) for a in e.args), Fraction(0))
        if isinstance(e, sp.Mul):
            out = Fraction(1)
            for a in e.args:
                out *= walk(a)
            return out
        if isinstance(e, sp.Pow) and e.exp.is_Integer:
            base = walk(e.base)
            k = int(e.exp)
            if abs(k) > 4096:
                raise ValueError("power too large")
            return base ** k
        raise ValueError(f"not rational arithmetic: {e}")

    try:
        return walk(expr)
    except (ValueError, ZeroDivisionError, DefinitionError):
        return None


def _denominator_vanishes(text: str, variable: str, witness: str) -> bool:
    """Does a denominator written in the text evaluate to zero at the witness? (Direct substitution, a different route
    from singular_points, which solves for the zeros.)"""
    value = _exact_value(witness)
    for m in re.finditer(r"/\s*(\((?:[^()]|\([^()]*\))*\)|[A-Za-z0-9_.^]+)", text):
        try:
            den = safe_parse_expr(m.group(1), local_dict={variable: sp.Symbol(variable)})
        except Exception:  # noqa: BLE001
            continue
        if sp.simplify(den.subs(sp.Symbol(variable), value)) == 0:
            return True
    return False


def check_structured(params: dict[str, Any], data: dict[str, Any]) -> list[tuple[str, bool | None, int, str]]:
    """Four separate checks of a structured result: (name, passed, level, detail)."""
    defs, tasks = params.get("definitions") or [], params.get("tasks") or []
    results = {r["id"]: r for r in data.get("results") or []}
    out: list[tuple[str, bool | None, int, str]] = []

    names = {d["name"] for d in defs}
    misread = sorted({n for t in tasks for key in ("expression", "lhs", "rhs") if t.get(key)
                      for n in names if re.search(rf"(?<![\w.]){re.escape(n)}(?!\w)(?!\s*\()", t[key])})
    out.append(("interpretation: defined functions are applied, never multiplied", not misread, 1,
                f"{', '.join(misread)} used as a number" if misread else f"{len(names)} definition(s) kept as functions"))

    domain_bad: list[str] = []
    for t in tasks:
        r = results.get(t["id"]) or {}
        for app in r.get("applications") or []:
            if app.get("symbolic"):
                continue
            defn = next((d for d in defs if d["name"] == app["function"]), None)
            if defn is None:
                domain_bad.append(f"{app['function']} is not defined")
                continue
            arg = _exact_value(app["argument"])
            if in_domain(arg, defn.get("domain") or "unspecified") is False:
                domain_bad.append(f"{app['function']}({arg}) outside {domain_label(defn['domain'])}")
            holds = [i for i, b in enumerate(defn["branches"]) if b["condition"] not in ("otherwise",) and condition_holds(b["condition"], defn["parameter"], arg)]
            expected = holds[0] if holds else next((i for i, b in enumerate(defn["branches"]) if b["condition"] == "otherwise"), None)
            if len(holds) > 1 or expected != app["branch"]:
                domain_bad.append(f"{app['function']}({arg}) used branch {app['branch']}, expected {expected}")
        if t["op"] == "evaluate" and r.get("status") == "undefined":
            try:
                again = evaluate(parse_with_definitions(t["expression"], defs, {k: sp.Symbol(k) for k in t.get("bindings") or {}})
                                 .xreplace({sp.Symbol(k): _exact_value(v) for k, v in (t.get("bindings") or {}).items()}), defs)
                domain_bad.append(f"{t['id']} was reported undefined but evaluates to {again}")
            except DefinitionError:
                pass  # confirmed: an argument lies outside the domain or no branch applies
        if t["op"] == "claim" and r.get("counterexample") is not None:
            w = _exact_value(r["counterexample"])
            if in_domain(w, t.get("domain") or "unspecified") is False or not all(
                    condition_holds(c, t["variable"], w) is True for c in t.get("conditions") or []):
                domain_bad.append(f"witness {t['variable']} = {w} is outside {domain_label(t.get('domain', ''))}")
        if t["op"] == "orbit":
            defn = next((d for d in defs if d["name"] == t["function"]), None)
            if defn is not None:
                for v in r.get("sequence") or []:
                    if in_domain(_exact_value(v), defn.get("domain") or "unspecified") is False:
                        domain_bad.append(f"orbit value {v} outside {domain_label(defn['domain'])}")
    out.append(("domain: arguments and witnesses lie in the stated domain; one branch applies each time", not domain_bad, 1,
                "; ".join(domain_bad)[:400]))

    comp_bad: list[str] = []
    checked = 0
    for t in tasks:
        r = results.get(t["id"]) or {}
        if r.get("status") in ("error", "undefined"):
            continue
        if t["op"] == "evaluate":
            again = _second_route(t["expression"], defs, {k: str(v) for k, v in (t.get("bindings") or {}).items()})
            if again is not None:
                checked += 1
                if Fraction(str(r.get("value"))) != again if re.fullmatch(_NUMBER, str(r.get("value"))) else True:
                    comp_bad.append(f"{t['id']}: recomputed {again}, reported {r.get('value')}")
            if r.get("factors"):
                prod = math.prod(int(p) for p in r["factors"])
                if abs(prod) != abs(int(_exact_value(r["value"]))) or not all(sp.isprime(int(p)) for p in r["factors"]):
                    comp_bad.append(f"{t['id']}: factors {r['factors']} do not multiply to {r['value']} as primes")
        elif t["op"] == "orbit":
            seq = r.get("sequence") or []
            for a, b in zip(seq, seq[1:]):
                again = _second_route(f"{t['function']}({a})", defs, {})
                checked += 1
                if again is None or Fraction(b) != again:
                    comp_bad.append(f"{t['function']}({a}) = {again}, orbit shows {b}")
            if t.get("mode") == "cycle" and r.get("closed") and seq and seq[-1] not in seq[:-1]:
                comp_bad.append("the reported cycle does not close")
        elif t["op"] == "claim":
            if r.get("status") == "disproved" and "undefined" in str(r.get("detail")):
                checked += 1
                if not any(_denominator_vanishes(t[k], t["variable"], r["counterexample"]) for k in ("lhs", "rhs", "expression") if t.get(k)):
                    comp_bad.append(f"{t['id']}: no written denominator vanishes at {t['variable']} = {r['counterexample']}")
            elif r.get("status") == "disproved" and r.get("counterexample") is not None:
                checked += 1
                w = r["counterexample"]
                if t.get("predicate"):
                    val = _second_route(t["expression"], defs, {t["variable"]: w})
                    div = _second_route(t["divisor"], defs, {t["variable"]: w}) if t.get("divisor") else None
                    still = None if val is None else _predicate(t["predicate"], sp.Rational(val.numerator, val.denominator),
                                                                None if div is None else sp.Rational(div.numerator, div.denominator))
                else:
                    lv = _second_route(t["lhs"], defs, {t["variable"]: w})
                    rv = _second_route(t["rhs"], defs, {t["variable"]: w})
                    still = None if lv is None or rv is None else bool(_REL_OPS[t["relation"]](sp.Rational(lv.numerator, lv.denominator), sp.Rational(rv.numerator, rv.denominator)))
                if still is not False:
                    comp_bad.append(f"{t['id']}: the counterexample {t['variable']} = {w} does not refute the claim on recomputation")
            elif r.get("status") == "proved" and t.get("predicate"):
                for v in [v for v in domain_values(t.get("domain") or "integer", 60) if all(
                        condition_holds(c, t["variable"], v) is True for c in t.get("conditions") or [])][:30]:
                    val = _second_route(t["expression"], defs, {t["variable"]: str(v)})
                    div = _second_route(t["divisor"], defs, {t["variable"]: str(v)}) if t.get("divisor") else None
                    if val is None:
                        continue
                    checked += 1
                    if _predicate(t["predicate"], sp.Rational(val.numerator, val.denominator),
                                  None if div is None else sp.Rational(div.numerator, div.denominator)) is not True:
                        comp_bad.append(f"{t['id']}: fails at {t['variable']} = {v}")
                        break
            elif r.get("status") == "proved" and t.get("relation") == "=":
                pts = [v for v in domain_values(t.get("domain") if t.get("domain") in _INTEGER_DOMAINS else "real", 40)
                       if in_domain(v, t.get("domain") or "unspecified") is not False and all(condition_holds(c, t["variable"], v) is True for c in t.get("conditions") or [])]
                for v in pts[:12]:
                    lv = _second_route(t["lhs"], defs, {t["variable"]: str(v)})
                    rv = _second_route(t["rhs"], defs, {t["variable"]: str(v)})
                    if lv is None or rv is None:
                        continue
                    checked += 1
                    if lv != rv:
                        comp_bad.append(f"{t['id']}: differs at {t['variable']} = {v}")
                        break
    out.append(("computation: every value recomputed by exact rational arithmetic", (not comp_bad) if checked else None, 2,
                "; ".join(comp_bad)[:400] if comp_bad else f"{checked} recomputation(s) agree"))

    missing = [t["id"] for t in tasks if t["id"] not in results or results[t["id"]].get("status") == "error"]  # "undefined" is an answer
    out.append(("coverage: every requested item has a result", not missing, 1,
                ("no result for " + ", ".join(missing)) if missing else f"{len(tasks)} item(s) answered"))
    return out


__all__ = [
    "CLAIM_SEARCH_LIMIT",
    "DOMAINS",
    "DefinitionError",
    "apply_definition",
    "axiom_structured",
    "check_structured",
    "domain_from_words",
    "evaluate",
    "factor_text",
    "in_domain",
    "misread_functions",
    "parse_definitions",
    "parse_structured",
    "parse_with_definitions",
    "run_structured",
    "singular_points",
]
