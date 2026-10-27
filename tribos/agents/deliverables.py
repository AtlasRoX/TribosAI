"""The deliverables a question asks for, and whether the final answer provides them.

Completeness is a property of the request, not of the tool log: a run whose tools all succeeded can still leave a
requested quantity out, and a run with a failed (and recovered) attempt can still answer everything. Items are read
from the imperative clauses of the question ("Calculate the natural frequency, damping ratio, ...; report the maximum
absolute error, ..."). Each item is

- missing:       most of its words appear nowhere in the answer (conservative: wording differences are tolerated),
- failed_check:  a quantity the question asks for is addressed, but a mathematical statement in the passage or table
                 row that addresses it was contradicted by the checks (tribos.verify.math_claims),
- verified:      a requested quantity is addressed and a statement there passed the checks or tool computation,
- addressed:     present, not checked (prose requests such as "explain" or "consult" or hand derivations are never machine checked).
"""

from __future__ import annotations

import re
from typing import Any

_COMPOUND_VERBS = (
    "prove or disprove", "show or disprove", "prove/disprove",
)
_COMPOUND_VERB_RE = re.compile(r"(?<![\w-])(?:" + "|".join(re.escape(v) for v in _COMPOUND_VERBS) + r")(?![\w-])", re.I)

_VERBS = (
    "calculate", "compute", "determine", "find", "derive", "report", "give", "state", "estimate", "evaluate", "plot",
    "simulate", "verify", "check", "compare", "investigate", "explain", "discuss", "consult", "provide", "include",
    "list", "show", "prove", "disprove", "refute", "solve", "analy[sz]e", "quantify", "predict", "assess", "distinguish",
    "describe", "decide", "test", "identify",
)
_VERB_RE = re.compile(r"(?<![\w-])(?:" + "|".join(_VERBS) + r")(?![\w-])", re.I)
_AUX_BEFORE_RE = re.compile(r"\b(?:do|does|did|not|to|cannot|will|would|should|could|might|may)\s*$", re.I)

_PROSE_VERBS = {"explain", "discuss", "consult", "describe"}
_QUANTITY_VERBS = {
    "calculate", "compute", "determine", "find", "derive", "report", "estimate", "evaluate", "solve",
    "quantify", "predict", "give", "state", "prove", "disprove", "refute", "verify", "check", "test", "decide",
    "prove or disprove",
}
_LEAD_RE = re.compile(r"^(?:\s*(?:the|a(?=\s+[a-z]{2,})|an|its|their|all|any|both|each|independently|clearly|also|that|whether|if)\b)+", re.I)

_TAIL_RE = re.compile(
    r"\b(?:using|with|via|in order|so that|by|under|within|governed|defined|whose)\b.*$",
    re.I,
)
_GENERIC_OVER_FOR = re.compile(
    r"\b(?:over|for)\s+(?!(?:every|all|nonnegative|positive|negative|integer|integers|real|reals|complex|rational|rationals|[a-z]\b|\d))\w+.*$",
    re.I,
)

_STOP = {
    "the", "and", "for", "with", "that", "this", "from", "into", "its", "their", "any", "all", "results", "result",
    "values", "value", "including", "both", "each",
}
_SUBJECT_WORDS = {"system", "problem", "model", "question", "setup", "configuration", "claim"}
_ACTIVITY = {"simulate": "numerical simulation", "compare": "comparison", "plot": "plot"}
_SPLIT_RE = re.compile(r"(?<!\d),(?!\d)\s*(?:and\s+|or\s+)?|\s+and\s+(?=(?:the\s+)?[a-z\-]+(?:\s+[a-z\-]+){0,3}\s*(?:,|$))", re.I)
# Given parameter assignment like m = 2 kg, F0 = 10 N, x(0) = 0.1 m, \omega = 4 rad/s
_GIVEN_PARAM_RE = re.compile(
    r"^\s*(?:[A-Za-z\u0370-\u03ff]\w*(?:\([^)]*\)|'*)*)\s*=\s*[-+]?\d+(?:\.\d+)?(?:\s*[\w/·°\\]+)?$"
)

_STATUS_RE = re.compile(
    r"\b(?:true|false|holds?|fails?|proved|proven|unproven|disproved|disproof|counterexamples?|open\s+(?:problem|question|conjecture)|"
    r"(?:remains?|is)\s+open|unknown|unresolved|not\s+(?:been\s+)?(?:proved|proven|known|established)|undefined|no\s+solution|yes|no)\b",
    re.I,
)

_LINK_ITEM_RE = re.compile(r"(?i)\b(?:url|urls|link|links|web\s*page|website|hyperlink)\b")
_URL_RE = re.compile(r"https?://[^\s)\]>\"']+")


def _words(text: str) -> list[str]:
    return [w for w in re.findall(r"[a-z][a-z\-]{1,}", (text or "").lower()) if w not in _STOP]


def _math_tokens(text: str) -> list[str]:
    return [tok.lower() for tok in re.findall(r"[A-Za-z]\w*|\d+(?:\.\d+)?", text or "") if tok.lower() not in _STOP]


def _norm_math(s: str) -> str:
    s = re.sub(r"\s+", "", (s or "").lower())
    s = re.sub(r"([0-9])\*([a-z])", r"\1\2", s)
    s = re.sub(r"([a-z])\*([a-z])", r"\1\2", s)
    return s


def _stem(word: str) -> str:
    return word.replace("-", "")[:6]


def _clean_question(q: str) -> str:
    return re.sub(r"\b(prove|find|check|show)\s*/\s*(disprove|refute|check)\b", r"\1 or \2", q or "", flags=re.I)


def _clauses(question: str) -> list[tuple[str, str]]:
    """(verb, object text) for every imperative verb; an object ends at the next verb or at the sentence end."""
    out: list[tuple[str, str]] = []
    question = _clean_question(question)
    for sentence in re.split(r"[.;:?!](?:\s+|$)", question or ""):
        compound_hits = list(_COMPOUND_VERB_RE.finditer(sentence))
        simple_hits = list(_VERB_RE.finditer(sentence))
        filtered_simple = [m for m in simple_hits if not any(c.start() <= m.start() < c.end() for c in compound_hits)]
        all_hits = sorted(compound_hits + filtered_simple, key=lambda m: m.start())
        hits = [m for m in all_hits if not _AUX_BEFORE_RE.search(sentence[:m.start()])]
        for i, m in enumerate(hits):
            end = hits[i + 1].start() if i + 1 < len(hits) else len(sentence)
            verb = m.group(0).lower()
            rest = sentence[m.end():end]
            rest = re.sub(r"^\s*(?:or|and)\s+(?:" + "|".join(_VERBS) + r")\b\s*", "", rest, flags=re.I)
            out.append((verb, rest))
    return out


def requested_items(question: str, limit: int = 24) -> list[dict[str, str]]:
    """Noun phrases the question asks the answer to provide, in order: [{id, item, verb}]."""
    from ..axiom.problem import (
        strip_question_framing,  # local: sympy is heavy and the framing rules live there
    )

    items: list[tuple[str, str]] = []
    cleaned_q = strip_question_framing(question)

    for verb, rest in _clauses(cleaned_q):
        found = False
        for part in _SPLIT_RE.split(rest):
            p = _LEAD_RE.sub("", part or "").strip()
            p = _TAIL_RE.sub("", p).strip(" ,")
            p = _GENERIC_OVER_FOR.sub("", p).strip(" ,")
            p = re.sub(r"^(?:including|such as|e\.g\.?)\s+", "", p, flags=re.I)
            p = re.sub(r"\s+(?:and|or)$", "", p).strip(" ,")
            p = re.sub(r"^/(?:disprove|refute|check)\s+", "", p, flags=re.I)

            if re.match(r"(?i)^(?:requiring|assuming|showing|providing|given|with|where)\b", p):
                continue
            if _GIVEN_PARAM_RE.match(p):
                continue

            words = _words(p)
            has_math = bool(re.search(r"[0-9+\-*/=<>^()_]", p))
            if not words and not has_math:
                continue
            if len(words) > 12:
                continue
            if _SUBJECT_WORDS & set(words):
                continue
            if re.match(r"(?i)^(?:or|and|nor|then)\b", p):
                continue

            cleaned_item = " ".join(p.split())
            if cleaned_item:
                items.append((cleaned_item, verb))
                found = True
        if not found and verb in _ACTIVITY:
            items.append((_ACTIVITY[verb], verb))

    out: list[dict[str, str]] = []
    seen: set[str] = set()
    for it, verb in items:
        key = " ".join(_stem(w) for w in _words(it)) or it.lower()
        if key and key not in seen:
            seen.add(key)
            out.append({"id": f"req-{len(out)+1}", "item": it, "verb": verb})
    return out[:limit]


def _has(stems: set[str], stem: str) -> bool:
    """A word is present when it or a form of it occurs ("max" for "maximum", "converged" for "convergence")."""
    if stem in stems:
        return True
    return len(stem) >= 3 and any(len(s) >= 3 and (s.startswith(stem) or stem.startswith(s)) for s in stems)


def _passages(answer: str) -> list[str]:
    """Paragraphs, table rows and headings: the units in which an item is addressed."""
    out: list[str] = []
    for block in re.split(r"\n\s*\n", answer or ""):
        lines = block.split("\n")
        if any(line.strip().startswith("|") for line in lines):
            out.extend(line for line in lines if line.strip())
        else:
            out.append(block)
    return out


def assess(
    question: str,
    answer: str,
    math_audit: dict[str, Any] | None = None,
    tool_results: dict[str, Any] | list[Any] | None = None,
) -> list[dict[str, Any]]:
    """[{id, item, verb, status, answer_state, check_state, where, quantity, evidence}] for each requested deliverable."""
    from ..utils.output_contract import mask_instructions

    stems_all = {_stem(w) for w in _words(answer)}
    passages = [(p, {_stem(w) for w in _words(p)}) for p in _passages(answer)]
    claims = list((math_audit or {}).get("claims") or [])
    results: list[dict[str, Any]] = []

    tool_map: dict[str, Any] = {}
    if isinstance(tool_results, dict):
        tool_map = tool_results
    elif isinstance(tool_results, list):
        for t in tool_results:
            if isinstance(t, dict) and t.get("tool"):
                tool_map[str(t["tool"])] = t

    req_list = requested_items(mask_instructions(question))

    for req in req_list:
        item_id = req.get("id") or f"req-{len(results)+1}"
        item, verb = req["item"], req["verb"]
        item_stems = [_stem(w) for w in _words(item)]
        has_math = bool(re.search(r"[0-9+\-*/=<>^()_]", item))

        evidence: list[str] = []

        link = _URL_RE.search(answer or "")
        if _LINK_ITEM_RE.search(item) and link:
            results.append({
                "id": item_id,
                "item": item,
                "verb": verb,
                "status": "addressed",
                "answer_state": "answered",
                "check_state": "unverified",
                "where": link.group(0)[:160],
                "quantity": False,
                "evidence": evidence,
            })
            continue

        proof_item = re.search(r"(?i)\b(?:proof|justification|argument|demonstration|refutation)\b", item)
        is_verdict_query = bool(
            re.match(r"(?i)^(?:whether|if)\b", item) or proof_item or verb in ("decide", "prove", "disprove", "refute", "test", "prove or disprove")
        )

        is_algebra_item = bool(re.search(r"(?i)\balgebra\b|\balgebraic\b", item))
        has_algebra_work = bool(re.search(r"[-+*/]\s*[^=<>]+[=<>]\s*[-+*/]|\b[a-z]\s*[-+*]\s*\d+|[=<>]\s*[-+*/0-9a-z]+\s*[=<>]\s*[-+*/0-9a-z]+|\b[a-z]\([a-z0-9]+\)\s*[-+*]", answer or ""))

        is_num_checks_item = bool(re.search(r"(?i)\b(?:numerical\s+checks?|checks?|comparisons?)\b", item))
        has_num_checks = len(re.findall(r"\d+\s*(?:>|<|>=|<=|=)\s*\d+", answer or "")) >= 2

        # Check if item is evaluating functions at specific values (e.g. "a(i) and b(i) separately for i = 0, 1, 2")
        m_fn_vals = re.findall(r"([A-Za-z]\w*)\s*\(", item)
        nums = re.findall(r"\d+", item)
        is_point_eval = bool(m_fn_vals and nums and re.search(r"(?i)\b(?:for|at|when|with)\b", item))

        if is_point_eval:
            apps = [rf"(?<![\w.]){fn}\s*\(\s*{n}\s*\)" for fn in m_fn_vals for n in nums]
            hits = sum(1 for rx in apps if re.search(rx, answer or ""))
            present = hits / len(apps) if apps else 0.0
        elif is_algebra_item:
            present = 1.0 if has_algebra_work else 0.0
        elif is_num_checks_item:
            present = 1.0 if has_num_checks else 0.0
        elif item_stems:
            present = sum(1 for s in item_stems if _has(stems_all, s)) / len(item_stems)
        else:
            present = 1.0 if has_math and re.sub(r"\s+", "", item) in re.sub(r"\s+", "", answer or "") else 0.0

        status_match = _STATUS_RE.search(answer or "")
        if is_verdict_query and status_match:
            present = 1.0

        is_missing = False
        if is_point_eval:
            is_missing = (present < 0.5)
        elif present < 0.4 and not (has_math and any(sym in answer for sym in re.findall(r"[A-Za-z0-9]+", item))):
            is_missing = True

        if is_missing:
            results.append({
                "id": item_id,
                "item": item,
                "verb": verb,
                "status": "missing",
                "answer_state": "missing",
                "check_state": "unverified",
                "where": "",
                "quantity": verb in _QUANTITY_VERBS,
                "evidence": evidence,
            })
            continue

        best, best_score = "", 0.0
        norm_item = _norm_math(item)
        lhs = item.split("=")[0].strip() if "=" in item else ""
        norm_lhs = _norm_math(lhs)

        for text, stems in passages:
            score = sum(1 for s in item_stems if _has(stems, s)) / len(item_stems) if item_stems else 0.0
            norm_text = _norm_math(text)
            if has_math:
                if norm_item and norm_item in norm_text:
                    score += 2.0
                elif norm_lhs and norm_lhs in norm_text:
                    score += 1.5
                elif re.sub(r"\s+", "", item) in re.sub(r"\s+", "", text):
                    score += 1.0
                else:
                    m_toks = _math_tokens(item)
                    t_toks = set(_math_tokens(text))
                    if m_toks:
                        score += sum(1 for t in m_toks if t in t_toks) / len(m_toks)
            if score > best_score:
                best, best_score = text, score

        if not best and is_algebra_item and has_algebra_work:
            for text, _ in passages:
                if re.search(r"[-+*/]\s*[^=<>]+[=<>]\s*[-+*/]|\b[a-z]\([a-z0-9]+\)\s*[-+*]", text):
                    best = text
                    break
        if not best and is_num_checks_item and has_num_checks:
            for text, _ in passages:
                if re.search(r"\d+\s*(?:>|<|>=|<=|=)\s*\d+", text):
                    best = text
                    break

        if not best and status_match:
            best = status_match.group(0)

        if not best and len(req_list) == 1 and passages:
            best = passages[0][0]

        status = "addressed"
        check_state = "unverified"
        answer_state = "answered"

        # Determine relevant claims for this item
        if len(req_list) == 1:
            item_claims = claims
        elif best:
            norm = re.sub(r"\s+", " ", best)
            item_claims = [c for c in claims if c.get("source_text") and re.sub(r"\s+", " ", str(c["source_text"])) in norm]
            if not item_claims and has_math:
                m_toks = set(_math_tokens(item))
                item_claims = [c for c in claims if any(t in m_toks for t in _math_tokens(str(c.get("text", ""))))]
        else:
            item_claims = []

        failed_claims = [c for c in item_claims if c.get("status") in ("failed", "contradicted")]
        passed_claims = [c for c in item_claims if c.get("status") in ("passed", "supported")]

        if failed_claims:
            status = "failed_check"
            check_state = "failed"
        elif item_claims and verb not in _PROSE_VERBS:
            q_lower = (question or "").lower()
            asks_factorization = bool(re.search(r"\b(?:factori[sz]ation|factored(?:\s+form)?|factors?)\b", q_lower))
            asks_roots = bool(re.search(r"\b(?:roots?|zeros?|solutions?)\b", q_lower) or verb in ("solve", "find", "determine"))
            asks_complete_roots = bool(re.search(r"\b(?:complete\s+set|all\s+(?:integer\s+)?roots|all\s+zeros|all\s+solutions)\b", q_lower))
            asks_subst_check = bool(re.search(r"\b(?:substitution\s+checks?|substitution|substitut(?:e|ing)|check\s+(?:for\s+)?each\s+root|verify\s+(?:by\s+)?substitution)\b", q_lower))
            asks_each_root = bool(re.search(r"\b(?:each\s+root|both\s+roots|all\s+roots)\b", q_lower))

            expected_roots: list[str] = []
            if (asks_complete_roots or asks_roots or asks_subst_check) and "=" in item:
                try:
                    import sympy as sp
                    eq_parts = item.split("=")
                    s_lhs = re.sub(r"([0-9])([a-z])", r"\1*\2", eq_parts[0].strip()).replace("^", "**")
                    s_rhs = re.sub(r"([0-9])([a-z])", r"\1*\2", eq_parts[1].strip()).replace("^", "**") if len(eq_parts) > 1 and eq_parts[1].strip() else "0"
                    syms = list(sp.sympify(s_lhs).free_symbols)
                    if syms:
                        var_sym = syms[0]
                        roots = sp.solve(sp.sympify(s_lhs) - sp.sympify(s_rhs), var_sym)
                        if "integer" in q_lower:
                            roots = [r for r in roots if getattr(r, "is_integer", False)]
                        expected_roots = [str(r) for r in roots]
                except Exception:
                    pass

            def has_root_statement(ans: str, r: str, var: str = "x") -> bool:
                patterns = [
                    rf"\b{var}\s*=\s*{r}\b",
                    rf"\b(?:roots?|zeros?|solutions?)\b[^\n]*\b{r}\b",
                    rf"\b(?:for|at|when)\s+{var}\s*=\s*{r}\b",
                ]
                return any(re.search(p, ans, re.I) for p in patterns)

            subst_validated_roots = set()
            for c in passed_claims:
                c_text = str(c.get("text", "")) + " " + str(c.get("source_text", ""))
                for r in expected_roots:
                    if re.search(rf"\b{re.escape(r)}\^|\*\s*{re.escape(r)}\b|\(\s*{re.escape(r)}\s*\)", c_text):
                        if re.search(r"\b0\b", c_text):
                            subst_validated_roots.add(r)

            subst_passed = False
            if asks_subst_check:
                if asks_each_root and expected_roots:
                    subst_passed = all(r in subst_validated_roots for r in expected_roots)
                else:
                    subst_passed = bool(subst_validated_roots) or any(
                        (re.search(r"\b0\b", str(c.get("text", ""))) and re.search(r"\d+", str(c.get("text", ""))))
                        for c in passed_claims
                    )

            factor_passed = False
            if asks_factorization:
                factor_passed = any(
                    re.search(r"\([a-z]\s*[-+]\s*\d+\)", str(c.get("text", "") or c.get("source_text", "")))
                    for c in passed_claims
                )
                if not factor_passed and re.search(r"\([a-z]\s*[-+]\s*\d+\)\s*(?:\*?\s*\([a-z]\s*[-+]\s*\d+\))+", answer, re.I):
                    factor_passed = True

            roots_complete = True
            if (asks_complete_roots or asks_roots) and expected_roots:
                for r in expected_roots:
                    if not has_root_statement(answer, r):
                        roots_complete = False
                        break

            validation_incomplete = False
            if asks_subst_check and not subst_passed:
                validation_incomplete = True
            if asks_factorization and not factor_passed:
                validation_incomplete = True
            if asks_complete_roots and not roots_complete:
                validation_incomplete = True

            if not validation_incomplete and passed_claims:
                status = "verified"
                check_state = "checked"
            else:
                status = "addressed"
                check_state = "unverified"

        if tool_map:
            if "axiom_inequality" in tool_map:
                ax_ineq = tool_map["axiom_inequality"]
                is_success = getattr(ax_ineq, "success", True) if not isinstance(ax_ineq, dict) else ax_ineq.get("success", True)
                if ("real" in item.lower() or "inequality" in item.lower() or ">" in item or "<" in item) and ("integer" not in item.lower() or "real" in item.lower()):
                    if is_success:
                        status = "verified"
                        check_state = "checked"
                        evidence.append("axiom_inequality")

            if "axiom_structured" in tool_map and status != "failed_check":
                ax_struct = tool_map["axiom_structured"]
                is_success = getattr(ax_struct, "success", True) if not isinstance(ax_struct, dict) else ax_struct.get("success", True)
                if ("zero" in item.lower() or "root" in item.lower() or "polynomial" in item.lower() or "=" in item) and "whether" not in item.lower() and "force" not in item.lower() and is_success:
                    status = "verified"
                    check_state = "checked"
                    evidence.append("axiom_structured")

        results.append({
            "id": item_id,
            "item": item,
            "verb": verb,
            "status": status,
            "answer_state": answer_state,
            "check_state": check_state,
            "where": re.sub(r"\s+", " ", best)[:160],
            "quantity": verb in _QUANTITY_VERBS,
            "evidence": evidence,
        })
    return results


__all__ = ["assess", "requested_items"]
