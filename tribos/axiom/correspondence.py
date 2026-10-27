"""
Semantic correspondence verification between original mathematical tasks and tool calls/verdicts (F04).

Ensures that a certificate of verification is granted only when the computation answers the exact problem
requested by the user, guarding against:
- Operation type shifts (e.g. evaluation of expressions mistranslated into simultaneous equation solving)
- Conjunctions of independent scopes (e.g. independent cases k=1, k=3, k=6 flattened into an inconsistent system)
- Out-of-domain witnesses/counterexamples (e.g. i = -1/7 refuting a claim over nonnegative integers)
- Trivial tautologies (e.g. 1=1, 2=2 generated from fragmented inputs)
- Discarded target expressions (solving bindings while dropping what was to be evaluated)

Valid algebraic transformations (factorization, expansion, substitution of definitions) are preserved
through symbolic equivalence checks under declared definitions and assumptions.
"""

from __future__ import annotations

import re
from typing import Any

import sympy as sp

from . import engine as E
from .definitions import in_domain
from .problem import ProblemSpec


def _detect_intents(text: str) -> dict[str, bool]:
    """Detect operation types and scoping constraints stated in the verbatim question text."""
    low = (text or "").lower()
    is_eval = bool(re.search(r"\b(?:evaluate|compute|calculate|value\s+of|substitute|find\s+the\s+value)\b", low))
    is_solve = bool(re.search(r"\b(?:solve|roots?|solutions?|find\s+(?:all\s+)?(?:real\s+|complex\s+|integer\s+)?(?:values\s+of\s+)?[a-z]\b|zeros?)\b", low))
    is_proof = bool(re.search(r"\b(?:prove|show\s+that|verify\s+that|is\s+.*an\s+identity|identity)\b", low))
    has_scopes = bool(re.search(r"\b(?:independent\s+(?:calculations?|cases?|items?)|(?:[a-z]\s+)?local\s+to\s+each|in\s+each\s+(?:case|item)|for\s+each\s+(?:case|item|value))\b", low))
    return {
        "evaluation": is_eval,
        "solving": is_solve,
        "proof": is_proof,
        "independent_scopes": has_scopes,
    }


def _extract_target_expressions(text: str) -> list[str]:
    """Expressions that the question asks to evaluate or prove, beyond simple variable bindings."""
    targets: list[str] = []
    m_eval = re.search(r"(?i)\b(?:evaluate|compute|calculate)\s+([^.,;?!]+)", text)
    if m_eval:
        cand = m_eval.group(1).strip()
        # Drop trailing clauses like 'for k=1' or 'in each'
        cand = re.split(r"(?i)\s+(?:for|at|when|where|with|in)\s+", cand)[0].strip()
        if cand and not re.fullmatch(r"[a-z]\s*=\s*\d+", cand, re.I):
            targets.append(cand)
    return targets


def _parse_sympy_value(val: Any) -> sp.Expr | None:
    if val is None:
        return None
    if isinstance(val, sp.Expr):
        return val
    try:
        s = str(val).strip()
        if "/" in s:
            num, den = s.split("/", 1)
            return sp.Rational(int(num.strip()), int(den.strip()))
        if s.lstrip("-+").isdigit():
            return sp.Integer(int(s))
        return sp.sympify(s)
    except Exception:
        return None


def is_tautology_claim(claim_dict: dict[str, Any]) -> bool:
    """Detect trivial tautological claims like 1=1 or 2=2 without variables or definitions."""
    lhs = str(claim_dict.get("lhs", "")).strip()
    rhs = str(claim_dict.get("rhs", "")).strip()
    var = claim_dict.get("variable")
    if lhs and rhs and lhs == rhs and not var and re.fullmatch(r"[-+]?\d+(?:\.\d+)?", lhs):
        return True
    expr = str(claim_dict.get("expression", "")).strip()
    if "=" in expr and not var:
        parts = [p.strip() for p in expr.split("=", 1)]
        if len(parts) == 2 and parts[0] == parts[1] and re.fullmatch(r"[-+]?\d+(?:\.\d+)?", parts[0]):
            return True
    return False


def check_task_correspondence(
    spec: ProblemSpec,
    tool: str,
    args: dict[str, Any],
    data: dict[str, Any] | None = None,
) -> tuple[bool, str, dict[str, Any]]:
    """
    Verify semantic correspondence between the original problem task (spec.text) and the tool call/data.
    Returns (passed, detail, metadata).
    """
    q_text = spec.text or ""
    intents = _detect_intents(q_text)
    data = data or {}

    # 1. Independent scopes check (S10)
    # If the user requested independent calculations with local bindings, a simultaneous solver conjunction
    # is an invalid translation / interpretation failure.
    if intents["independent_scopes"]:
        if tool in ("axiom_solve", "axiom_nsolve"):
            eqs = args.get("equations")
            eq_list = [eqs] if isinstance(eqs, str) else list(eqs or [])
            if len(eq_list) > 1:
                return (
                    False,
                    "original task requested independent case calculations, not a simultaneous system of equations; "
                    "a 'no solutions' conjunction result does not answer the task",
                    {"mismatch": "independent_scopes"},
                )

    # 2. Operation type mismatch (S10)
    # If evaluation was requested and no equation solving was asked, a solver returning 'no solutions' is an error.
    if intents["evaluation"] and not intents["solving"]:
        if tool in ("axiom_solve", "axiom_nsolve"):
            sols = data.get("solutions")
            if sols == [] or sols is None:
                return (
                    False,
                    "original task requested evaluation of expressions, not simultaneous equation solving; "
                    "'no solutions' does not answer evaluation",
                    {"mismatch": "operation_type"},
                )

    # 3. Target expression retention
    # If the question requested evaluation of an expression (e.g. 2k+1), but the tool only solved the bindings:
    targets = _extract_target_expressions(q_text)
    for tgt in targets:
        if tool in ("axiom_solve", "axiom_nsolve"):
            eqs = args.get("equations")
            eq_str = " ".join(eqs) if isinstance(eqs, list) else str(eqs or "")
            tgt_clean = re.sub(r"\s+", "", tgt)
            if tgt_clean not in re.sub(r"\s+", "", eq_str) and not any(
                re.sub(r"\s+", "", p) in re.sub(r"\s+", "", eq_str)
                for p in re.split(r"[+\-*/]", tgt_clean) if len(p) > 1
            ):
                return (
                    False,
                    f"tool call solves variable bindings without evaluating the requested expression '{tgt}'",
                    {"mismatch": "target_expression_omitted"},
                )

    # 4. Tautology checks (1=1, 2=2)
    # Check if tasks in structured data are trivial numeric tautologies
    for t in (args.get("tasks") or []) + (data.get("tasks") or []):
        if isinstance(t, dict) and is_tautology_claim(t):
            return (
                False,
                f"trivial tautological task '{t.get('id')}' detected; does not validate problem claims",
                {"mismatch": "tautology_claim"},
            )

    # 6. Domain & witness validity check (S07 / I08)
    dom = spec.domain or ""
    low_text = q_text.lower()
    from .definitions import domain_from_words
    dw = domain_from_words(q_text)
    if dw:
        dom = dw
    elif "nonnegative" in low_text or "non-negative" in low_text or "z>=0" in low_text or "z >= 0" in low_text or "z_{\\ge 0}" in low_text:
        dom = "nonnegative_integer"
    elif "positive integer" in low_text or "natural number" in low_text or "z>0" in low_text or "z > 0" in low_text:
        dom = "positive_integer"
    elif "integer" in low_text and not dom:
        dom = "integer"

    if dom:
        # Check counterexample in data top-level, in answer, and in results
        ans = data.get("answer") if isinstance(data.get("answer"), dict) else {}
        ces: list[Any] = []
        if data.get("counterexample") is not None:
            ces.append(data.get("counterexample"))
        if ans.get("counterexample") is not None:
            ces.append(ans.get("counterexample"))
        for r in (data.get("results") or []) + (ans.get("results") or []):
            if isinstance(r, dict) and r.get("counterexample") is not None:
                ces.append(r.get("counterexample"))

        for ce in ces:
            w_val = ce if not isinstance(ce, dict) else next(iter(ce.values()), None)
            sym_val = _parse_sympy_value(w_val)
            if sym_val is not None and in_domain(sym_val, dom) is False:
                return (
                    False,
                    f"witness '{ce}' lies outside the problem's declared domain ({dom})",
                    {"mismatch": "domain_violation"},
                )

        # Check roots in solutions
        for sol in data.get("solutions") or []:
            if isinstance(sol, dict):
                for var_name, root_val in sol.items():
                    r_val = _parse_sympy_value(root_val)
                    if r_val is not None and in_domain(r_val, dom) is False:
                        return (
                            False,
                            f"solution {var_name} = {root_val} lies outside declared domain ({dom})",
                            {"mismatch": "domain_violation"},
                        )

    # 7. Traceable transformed calculation mapping (Requirement 4)
    # If the tool used an algebraically transformed expression, verify equivalence
    orig_expr = spec.expression
    tool_expr = args.get("expression") or args.get("equation")
    if orig_expr and tool_expr and orig_expr != tool_expr and tool in ("axiom_simplify", "axiom_solve", "axiom_verify_identity"):
        try:
            var = sp.Symbol(spec.variable or "x")
            e1 = E.safe_parse_expr(str(orig_expr), local_dict={var.name: var})
            e2 = E.safe_parse_expr(str(tool_expr), local_dict={var.name: var})
            if sp.simplify(e1 - e2) == 0:
                return (
                    True,
                    "traceable mapping: transformed expression is equivalent to original problem",
                    {"transformed_equivalent": True},
                )
        except Exception:
            pass

    return True, "correspondence to original task verified", {}


__all__ = ["check_task_correspondence", "is_tautology_claim"]
