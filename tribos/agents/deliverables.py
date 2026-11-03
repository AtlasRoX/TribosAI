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
    "describe", "decide", "test", "identify", "return",
)
_VERB_RE = re.compile(r"(?<![\w-])(?:" + "|".join(_VERBS) + r")(?![\w-])", re.I)
_AUX_BEFORE_RE = re.compile(
    r"\b(?:do|does|did|not|to|cannot|will|would|should|could|might|may|a|an|the|each|every|both|its|their|substitution|dimensional|consistency|sanity|unit|by)\s*$",
    re.I,
)

_PROSE_VERBS = {"explain", "discuss", "consult", "describe"}
_QUANTITY_VERBS = {
    "calculate", "compute", "determine", "find", "derive", "report", "estimate", "evaluate", "solve",
    "quantify", "predict", "give", "state", "prove", "disprove", "refute", "verify", "check", "test", "decide",
    "prove or disprove", "return",
}
_LEAD_RE = re.compile(r"^(?:\s*(?:the|a(?=\s+[a-z]{2,})|an|its|their|all|any|both|each|independently|clearly|also|that|whether|if)\b)+", re.I)

_TAIL_RE = re.compile(
    r"\b(?:using|with|via|in order|so that|by|under|within|governed|defined|whose)\b.*$",
    re.I,
)
_GENERIC_OVER_FOR = re.compile(
    r"\b(?:over|for)\s+(?!(?:each|every|all|nonnegative|positive|negative|integer|integers|real|reals|complex|rational|rationals|[a-z]\b|\d))\w+.*$",
    re.I,
)

_STOP = {
    "the", "and", "for", "with", "that", "this", "from", "into", "its", "their", "any", "all", "results", "result",
    "values", "value", "including", "both", "each",
}
_SUBJECT_WORDS = {"system", "problem", "model", "question", "setup", "configuration", "claim"}
_ACTIVITY = {"simulate": "numerical simulation", "compare": "comparison", "plot": "plot"}
# A list piece that is only a value with an optional unit ("2", "and 10 s", "5 seconds").
_BARE_VALUE_RE = re.compile(r"^(?:and\s+|or\s+)?[-+−]?\d+(?:\.\d+)?(?:\s*[A-Za-zμΩ°/]{1,10})?$", re.I)
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


def _split_outside_brackets(text: str) -> list[str]:
    """_SPLIT_RE.split, except at commas inside brackets: "M(x,y) = x^4y^2 + ..." stays one item, not "M(x" and
    "y) = ..."."""
    guarded, depth = [], 0
    # "for all real x,y": a comma between single-letter variables lists variables, not items.
    text = re.sub(r"(?<![A-Za-z])([A-Za-z]),(?=[A-Za-z](?![A-Za-z]))", "\\1\uE000", text)
    for c in text:
        depth += c in "([{"
        depth -= c in ")]}" and depth > 0
        guarded.append("\uE000" if c == "," and depth else c)
    return [p.replace("\uE000", ",") for p in _SPLIT_RE.split("".join(guarded))]


def _split_items(text: str) -> list[str]:
    """Split comma/conjunction separated deliverables while respecting parenthesis nesting and numbers."""
    parts: list[str] = []
    current: list[str] = []
    depth = 0
    i = 0
    chars = text.strip()
    n = len(chars)
    while i < n:
        c = chars[i]
        if c in "([{":
            depth += 1
            current.append(c)
            i += 1
        elif c in ")]}":
            depth = max(0, depth - 1)
            current.append(c)
            i += 1
        elif depth == 0:
            is_num_comma = bool(re.search(r"[=:]\s*\d+(?:\s*,\s*\d+)*\s*$", "".join(current))) and bool(re.match(r"\s*\d+\b", chars[i + 1:]))
            if c == "," and not is_num_comma and (i + 1 < n and chars[i + 1].isspace()):
                part = "".join(current).strip()
                if part:
                    parts.append(part)
                current = []
                i += 1
                while i < n and chars[i].isspace():
                    i += 1
                if chars[i:].lower().startswith("and "):
                    i += 4
                elif chars[i:].lower().startswith("or "):
                    i += 3
            elif (
                (chars[i:].lower().startswith(" and ") or chars[i:].lower().startswith(" or "))
                and not any(chars[:i].rstrip().endswith(op) for op in ("+", "-", "*", "/", "=", "<", ">", "^"))
            ):
                is_and = chars[i:].lower().startswith(" and ")
                part = "".join(current).strip()
                if part:
                    parts.append(part)
                current = []
                i += 5 if is_and else 4
            else:
                current.append(c)
                i += 1
        else:
            current.append(c)
            i += 1
    if current:
        part = "".join(current).strip()
        if part:
            parts.append(part)
    return parts


# Presentation requirements ("Requirements: show intermediate calculations, preserve units, use LaTeX, state
# assumptions, independently verify final results") describe how to write the answer; they are not deliverables whose
# absence can be detected, so they are never reported as "not addressed".
_STYLE_REQUIREMENT_RE = re.compile(
    r"(?i)(?:all\s+|the\s+|your\s+)?(?:(?:final|intermediate|all)\s+)?(?:results?|answers?|calculations?|steps?|working|"
    r"units?|latex|assumptions?|derivations?\s+steps?|numerical\s+results?|reasoning|preserve\s+units|use\s+latex)"
    # "verify every final number independently", "check each value": how to work, not a separate deliverable.
    r"|(?:every|each|all)\s+(?:(?:final|computed|calculated|numerical)\s+)?(?:numbers?|values?|results?|answers?)"
    r"(?:\s+independently)?"
    r"|(?:keep|preserve|use|state|show|include)\s+(?:the\s+|all\s+)?(?:units?|latex|assumptions?|intermediate\s+steps?)"
    # "keep the answer focused / short / concise", "be brief": the answer's length and tone.
    r"|(?:keep|make)\s+(?:the\s+|your\s+|it\s+)?(?:(?:answer|response|reply|it)\s+)?(?:focused|short|brief|concise|clear|tight)"
    r"|(?:result\s+independently|(?:the\s+)?(?:result|results|answer)\s+(?:independently|twice))"
    # "show the key equations": how the working is written, met by any answer that derives its result
    r"|(?:the\s+)?(?:key|main|governing|relevant|important)\s+equations?"
)


def _computed_results(tool_map: dict[str, Any]) -> dict[str, Any] | None:
    res = tool_map.get("computed_results")
    data = getattr(res, "data", None) if res is not None and not isinstance(res, dict) else (res or {}).get("data")
    ok = getattr(res, "success", True) if res is not None and not isinstance(res, dict) else (res or {}).get("success", True)
    return data if ok and isinstance(data, dict) else None


# Requested-item wording -> the computed parameter it names (tribos.writer.facts parameter names).
_PARAM_ALIASES = {
    "phase shift": "phase lag of the response behind the forcing",
    "phase angle": "phase lag of the response behind the forcing",
    "phase lag": "phase lag of the response behind the forcing",
    "amplitude grows": "resonant amplitude growth rate",
    "growth rate": "resonant amplitude growth rate",
    "work done": "work done by the forcing",
    "mechanical energy": "change in mechanical energy",
    "energy dissipated": "energy dissipated by damping",
    "time constant": "decay time constant",
    "settling time": "settling time (2% band, about 4 time constants)",
    "resonance frequency": "resonance frequency (peak of the amplitude)",
    "amplitude": "steady-state amplitude",
}
# Items the computed substitution checks deliver: "show it satisfies the equation", "both initial conditions".
_SUBSTITUTION_ITEM_RE = re.compile(r"satisf\w*\s+(?:the\s+)?(?:differential\s+|original\s+)?(?:equation|ode)|"
                                   r"initial\s+conditions?|substitut\w*", re.I)
_ANSWER_NUMBER_RE = re.compile(r"(?<![\w.])-?\d+(?:\.\d+)?(?:[eE][-+]?\d+)?")


def _sig_digits(token: str) -> int:
    return len(re.sub(r"[eE].*$", "", token.lstrip("-")).replace(".", "").lstrip("0"))


def _states_value(answer: str, computed: str) -> bool:
    """Whether the answer states the computed value (to the precision it prints, at least 3 significant figures or
    every figure of an exact short value such as 5 or 0.15)."""
    value = float(computed)
    need = min(3, _sig_digits(computed))
    for m in _ANSWER_NUMBER_RE.finditer(answer):
        try:
            v = float(m.group(0))
        except ValueError:
            continue
        token = m.group(0).lstrip("-")
        if _sig_digits(token) >= need and abs(v - value) <= max(abs(value) * 5e-3, 10 ** -(len(token.split(".")[1]) if "." in token else 0) / 2):
            return True
    return False


def _computed_item_checked(item: str, computed: dict[str, Any], answer: str) -> bool:
    """Whether code-computed, checked results deliver this requested item and the answer states them: a named
    parameter whose value the answer gives, or the exact solution (or its transient/steady-state split) whose
    integer constants all appear in the answer."""
    low = item.lower()
    checks = computed.get("checks") or []
    solution_checked = bool(computed.get("exact_solution_latex")) and len(checks) >= 2 and all(
        c.get("passed") for c in checks if isinstance(c, dict))
    if re.fullmatch(r"(?:the\s+|its\s+|their\s+)?(?:(?:python|code(?:'s)?|program(?:'s)?)\s+)?outputs?", low.strip(" ."))\
            and computed.get("methods") and checks:
        # "Run real Python and report its outputs": the computed results are the code's outputs; delivered when the
        # answer reports at least one of their values.
        # The answer reports the outputs in its own notation ("7.46\times 10^{-5}" for 7.46e-05, points in another
        # order): the distinctive numbers of the outputs (decimals, numbers of three or more digits) are compared, and
        # two of them in the answer show it reports the code's outputs.
        number = r"\d+\.\d+|\d{3,}"
        out_text = " ".join([str(c.get("name")) for c in checks if isinstance(c, dict)]
                            + [str(p.get("value")) for p in computed.get("parameters") or [] if isinstance(p, dict)])
        wanted = set(re.findall(number, out_text))
        return len(wanted & set(re.findall(number, answer))) >= 2
    derived = (computed.get("physics") or {}).get("quantities") or []
    params = {str(p.get("name", "")).lower(): p for p in [*(computed.get("parameters") or []), *derived] if isinstance(p, dict)}
    names = [n for n in params if n and n in low] + [v for k, v in _PARAM_ALIASES.items() if k in low and v in params]
    # A result's own aliases (tribos.writer.number_facts: "count the ways for 1000" names "number of ways to write 1000").
    alias_hits = {n: a.lower() for n, p in params.items() for a in p.get("aliases") or [] if a and a.lower() in low}
    names += list(alias_hits)
    if not names and solution_checked and _SUBSTITUTION_ITEM_RE.search(low):
        # The exact solution was substituted back by code and met the equation and every initial condition; the
        # item is delivered when the answer reports that check.
        return bool(re.search(r"(?i)substitut|initial\s+condition|satisf", answer))
    if names:
        p = params[max(names, key=len)]
        if p.get("verified") is False:
            return False
        if p.get("match_regex"):
            # A delivered form rather than a value (a decomposition into squares): the answer must write it out.
            return bool(re.search(p["match_regex"], answer))
        if p.get("match_all"):
            # Several values (every real root): each must be in the answer, in any notation spacing.
            flat = re.sub(r"\s+|\$|\\[,;!]", "", answer)
            return all(str(m) in flat for m in p["match_all"])
        value = str(p.get("match") or p.get("value"))
        # Where the answer names the quantity (the item's own words, or the phrase that named the parameter); a short
        # value such as 5 is only looked for there.
        anchors = [low.strip(), *(k for k, v in _PARAM_ALIASES.items() if k in low and v in params),
                   *alias_hits.values(), *(str(a).lower() for a in p.get("aliases") or [] if a)]
        windows = [answer[max(0, m.start() - 80):m.start() + 500] for a in anchors for m in re.finditer(re.escape(a), answer.lower())]
        if not re.fullmatch(r"[-+]?\d+(?:\.\d+)?(?:[eE][-+]?\d+)?", value):
            return value in answer  # a non-numeric result, such as the pair "(881, 883)"
        try:
            if _sig_digits(value) < 3:
                return any(_states_value(w, value) for w in windows)
            return _states_value(answer, value)
        except (TypeError, ValueError):
            return False
    if not solution_checked:
        return False
    if re.search(r"transient|steady[- ]state\s+(?:component|part|solution|response)", low):
        latex = f"{computed.get('transient_latex', '')} {computed.get('steady_state_latex', '')}"
    elif re.search(r"analytical\s+solution|exact\s+solution|closed[- ]form|general\s+solution|\bsolution\b", low):
        latex = str(computed.get("exact_solution_latex", ""))
    else:
        return False
    constants = {n for n in re.findall(r"\d+", latex) if int(n) >= 10}
    return bool(constants) and all(re.search(rf"(?<!\d){n}(?!\d)", answer) for n in constants)


_CLAIM_SECTION_RE = re.compile(r"^\s*(?:#+\s*)?\d+[.)]\s+(.+?):\s")


def _claim_in_item_section(claim_text: str, item: str) -> bool:
    """Whether a claim may belong to the item by shared symbols: a claim stated under a numbered task heading
    ("5. Find the largest x(t)...: x ~ sin 3t") belongs to that task only, never to every item that mentions x(t)."""
    m = _CLAIM_SECTION_RE.match(claim_text)
    if not m:
        return True
    heading = re.sub(r"\s+", " ", m.group(1)).lower()
    words = [w for w in re.findall(r"[a-z]{4,}", item.lower())]
    if words:
        return sum(w in heading for w in words) >= max(1, len(words) // 2)
    # An item of symbols and values ("x(t) at t = 0.5, 1, 2, 6 s"): its values must appear in the heading.
    nums = set(re.findall(r"\d+(?:\.\d+)?", item))
    return not nums or len(nums & set(re.findall(r"\d+(?:\.\d+)?", heading))) >= max(1, len(nums) // 2 + 1)


def _table_points(answer: str, fn: str) -> set[float]:
    """First-column values of every Markdown table whose header names fn(...) or fn: the points it tabulates."""
    points: set[float] = set()
    for block in re.split(r"\n\s*\n", answer or ""):
        rows = [r for r in block.split("\n") if r.strip().startswith("|")]
        if len(rows) < 3 or not re.search(rf"(?<![A-Za-z]){re.escape(fn)}\s*(?:\(|\$|\s|\|)", rows[0]):
            continue
        for row in rows[2:]:
            cells = [c.strip().strip("$") for c in row.strip().strip("|").split("|")]
            try:
                points.add(round(float(cells[0].replace("−", "-")), 9))
            except (ValueError, IndexError):
                continue
    return points


def requested_items(question: str, limit: int = 24) -> list[dict[str, str]]:
    """Noun phrases the question asks the answer to provide, in order: [{id, item, verb}]."""
    from ..axiom.problem import (
        strip_question_framing,  # local: sympy is heavy and the framing rules live there
    )

    items: list[tuple[str, str]] = []
    cleaned_q = strip_question_framing(question)

    for verb, rest in _clauses(cleaned_q):
        found = False
        m_container = re.search(r"\b(?:containing|including|with|consisting of|that contains|that includes)\s+", rest, flags=re.I)
        effective_rest = rest[m_container.end():] if m_container else rest
        split_candidates = _split_items(effective_rest) if m_container else _split_outside_brackets(rest)
        if not m_container and len(split_candidates) <= 1:
            alt_candidates = _split_items(rest)
            if len(alt_candidates) > len(split_candidates):
                split_candidates = alt_candidates
        # A piece that is only a value ("2", "10 s") continues the list of the item before it: "x(t) at t = 0.5, 2,
        # 5 and 10 s" is one item, not four.
        merged: list[str] = []
        for part in split_candidates:
            if merged and _BARE_VALUE_RE.match((part or "").strip(" ,.;")):
                merged[-1] = f"{merged[-1].rstrip(' ,')}, {(part or '').strip(' ,')}"
            else:
                merged.append(part)
        split_candidates = merged
        for part in split_candidates:
            p = _LEAD_RE.sub("", part or "").strip()
            p = _TAIL_RE.sub("", p).strip(" ,")
            p = _GENERIC_OVER_FOR.sub("", p).strip(" ,")
            p = re.sub(r"^(?:including|such as|e\.g\.?)\s+", "", p, flags=re.I)
            p = re.sub(r"\s+(?:and|or)$", "", p).strip(" ,")
            p = re.sub(r"^/(?:disprove|refute|check)\s+", "", p, flags=re.I)
            p = re.sub(r"^(?:item\s+containing|numbered\s+item\s+containing)\s+", "", p, flags=re.I)

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

    has_specific_sub_obligations = (
        any("factor" in it.lower() for it, _ in items)
        and (any("root" in it.lower() for it, _ in items) or any("substitut" in it.lower() or "check" in it.lower() for it, _ in items))
    )
    if has_specific_sub_obligations:
        items = [(it, v) for it, v in items if "=" not in it or ("factor" in it.lower() or "root" in it.lower() or "check" in it.lower())]

    out: list[dict[str, str]] = []
    seen: set[str] = set()
    for it, verb in items:
        if _STYLE_REQUIREMENT_RE.fullmatch(it.strip(" .")):
            continue  # "show intermediate calculations", "use LaTeX": how to write, not something to deliver
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

        is_derivation_item = bool(re.search(r"(?i)\b(?:derivation|derive|deriving|proof\s+steps?|working)\b", item) or verb in ("derive",))
        has_derivation_work = bool(
            re.search(r"(?i)\b(?:derivation|derive|deriving|derived|step|starting\s+from|substituting|rearranging|dividing|integrating|differentiating|matching\s+coefficients)\b", answer or "")
            or re.search(r"[-+*/]\s*[^=<>]+[=<>]\s*[-+*/]|\b[a-z]\s*[-+*]\s*\d+|[=<>]\s*[-+*/0-9a-z]+\s*[=<>]\s*[-+*/0-9a-z]+|\b[a-z]\([a-z0-9]+\)\s*[-+*]", answer or "")
        )

        is_algebra_item = bool(re.search(r"(?i)\balgebra\b|\balgebraic\b", item))
        has_algebra_work = bool(re.search(r"[-+*/]\s*[^=<>]+[=<>]\s*[-+*/]|\b[a-z]\s*[-+*]\s*\d+|[=<>]\s*[-+*/0-9a-z]+\s*[=<>]\s*[-+*/0-9a-z]+|\b[a-z]\([a-z0-9]+\)\s*[-+*]", answer or ""))

        is_num_checks_item = bool(re.search(r"(?i)\b(?:numerical\s+checks?|checks?|comparisons?)\b", item))
        has_num_checks = len(re.findall(r"\d+\s*(?:>|<|>=|<=|=)\s*\d+", answer or "")) >= 2

        is_subst_item = bool(re.search(r"(?i)\b(?:substitution\s+checks?|substitution|substitut(?:e|ing))\b", item))
        has_subst_work = bool(
            re.search(r"(?i)\b(?:substitution|substitut(?:e|ing))\b", answer or "")
            or (re.search(r"(?i)\bchecks?\b", answer or "") and re.search(r"\b0\b", answer or ""))
        )

        is_factor_item = bool(re.search(r"(?i)\b(?:factori[sz]ation|factored|factors?)\b", item))
        has_factor_work = bool(
            re.search(r"(?i)\b(?:factori[sz]ation|factored|factors?)\b", answer or "")
            or re.search(r"\([a-z]\s*[-+]\s*\d+\)", answer or "")
        )

        is_roots_item = bool(re.search(r"(?i)\b(?:roots?|zeros?|solutions?)\b", item) and not is_subst_item)
        has_roots_work = bool(
            re.search(r"(?i)\b(?:roots?|zeros?|solutions?)\b", answer or "")
            or re.search(r"\b[a-z]\s*=\s*[-+]?\d+", answer or "")
        )

        # Check if item is evaluating functions at specific values (e.g. "a(i) and b(i) separately for i = 0, 1, 2")
        m_fn_vals = re.findall(r"([A-Za-z]\w*)\s*\(", item)
        nums = re.findall(r"\d+", item)
        is_point_eval = bool(m_fn_vals and nums and re.search(r"(?i)\b(?:for|at|when|with)\b", item))

        if is_point_eval:
            apps = [rf"(?<![\w.]){fn}\s*\(\s*{n}\s*\)" for fn in m_fn_vals for n in nums]
            hits = sum(1 for rx in apps if re.search(rx, answer or ""))
            present = hits / len(apps) if apps else 0.0
            # A table of fn against the requested points answers it too ("| t | x(t) |" with rows 0, 0.5, ..., 5).
            wanted = {round(float(v), 9) for v in re.findall(r"\d+(?:\.\d+)?", item)}
            tabulated = set().union(*(_table_points(answer, fn) for fn in m_fn_vals)) if m_fn_vals else set()
            if wanted and tabulated and wanted <= tabulated:
                present = 1.0
        elif is_derivation_item:
            present = 1.0 if has_derivation_work else 0.0
        elif is_roots_item:
            present = 1.0 if has_roots_work else 0.0
        elif is_factor_item:
            present = 1.0 if has_factor_work else 0.0
        elif is_subst_item:
            present = 1.0 if has_subst_work else 0.0
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
        computed_now = _computed_results(tool_map) if is_missing else None
        if computed_now and _computed_item_checked(item, computed_now, answer or ""):
            # The item's words are not in the answer ("report its outputs"), but the code-computed values it asks for
            # are: delivered and checked.
            results.append({"id": item_id, "item": item, "verb": verb, "status": "verified", "answer_state": "answered",
                            "check_state": "checked", "where": "", "quantity": verb in _QUANTITY_VERBS,
                            "evidence": [*evidence, "computed_results"]})
            continue

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

        if not best and is_derivation_item and has_derivation_work:
            for text, _ in passages:
                if re.search(r"(?i)\b(?:derivation|derive|deriving|step|starting\s+from)\b", text) or re.search(r"[-+*/]\s*[^=<>]+[=<>]\s*[-+*/]", text):
                    best = text
                    break
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
        if not best and is_subst_item and has_subst_work:
            for text, _ in passages:
                if re.search(r"(?i)\b(?:substitution|substitut(?:e|ing)|checks?)\b", text):
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
                item_claims = [c for c in claims if any(t in m_toks for t in _math_tokens(str(c.get("text", ""))))
                               and _claim_in_item_section(str(c.get("text", "")), item)]
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
            eq_str = item if "=" in item else ""
            if not eq_str:
                m_eq = re.search(r"([A-Za-z0-9+\-*/^() ]+\s*=\s*[A-Za-z0-9+\-*/^() ]+)", question or "")
                if m_eq:
                    eq_str = m_eq.group(1).strip()

            if (asks_complete_roots or asks_roots or asks_subst_check) and eq_str and "=" in eq_str:
                try:
                    import sympy as sp
                    eq_parts = eq_str.split("=")
                    lhs_raw = re.sub(r"^(?:for\s+(?:integer|real|complex)\s+[a-z],?\s*|\s*solve\s+|\s*find\s+|\s*determine\s+)+", "", eq_parts[0].strip(), flags=re.I)
                    s_lhs = re.sub(r"([0-9])([a-z])", r"\1*\2", lhs_raw).replace("^", "**")
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
                    rf"\b{var}(?:_\d+)?\s*=\s*{r}\b",
                    rf"\b(?:roots?|zeros?)\b[^\n]*\b{r}\b",
                    rf"\b(?:solutions?)\s*(?:are|is|:|=)[ \t]*[^\n]*\b{r}\b",
                    rf"\b{r}\s+is\s+(?:a\s+)?(?:root|zero|solution)\b",
                    rf"\b(?:for|at|when)\s+{var}\s*=\s*{r}\b",
                    rf"\{{\s*[^}}\n]*\b{r}\b[^}}\n]*\}}",
                ]
                return any(re.search(p, ans, re.I) for p in patterns)

            poly_terms_for_root: dict[str, list[int]] = {}
            if eq_str and "=" in eq_str and expected_roots:
                try:
                    import sympy as sp
                    eq_parts = eq_str.split("=")
                    lhs_raw = re.sub(r"^(?:for\s+(?:integer|real|complex)\s+[a-z],?\s*|\s*solve\s+|\s*find\s+|\s*determine\s+)+", "", eq_parts[0].strip(), flags=re.I)
                    s_lhs = re.sub(r"([0-9])([a-z])", r"\1*\2", lhs_raw).replace("^", "**")
                    s_rhs = re.sub(r"([0-9])([a-z])", r"\1*\2", eq_parts[1].strip()).replace("^", "**") if len(eq_parts) > 1 and eq_parts[1].strip() else "0"
                    syms = list(sp.sympify(s_lhs).free_symbols)
                    if syms:
                        var_sym = syms[0]
                        poly = sp.Poly(sp.sympify(s_lhs) - sp.sympify(s_rhs), var_sym)
                        for r_val_str in expected_roots:
                            r_val = sp.sympify(r_val_str)
                            terms = [int(coeff * (r_val ** (exp[0] if isinstance(exp, tuple) else exp))) for exp, coeff in poly.as_dict().items()]
                            poly_terms_for_root[str(r_val_str)] = terms
                except Exception:
                    pass

            all_passed_claims = [c for c in claims if c.get("status") in ("passed", "supported")]
            claims_for_subst = all_passed_claims if len(req_list) > 1 else passed_claims
            claims_for_factor = all_passed_claims if len(req_list) > 1 else passed_claims

            ans_passages = [p.strip() for p in re.split(r"\n+", answer or "") if p.strip()]

            subst_validated_roots = set()
            for r in expected_roots:
                r_str = str(r)
                for c in claims_for_subst:
                    c_text = str(c.get("text", "")) + " " + str(c.get("source_text", ""))
                    has_zero = bool(re.search(r"\b0\b", c_text))
                    if not has_zero:
                        continue

                    # Direct check: claim text contains the root
                    if re.search(rf"\b{re.escape(r_str)}\^|\b{re.escape(r_str)}\*\*|\*\s*{re.escape(r_str)}\b|\(\s*{re.escape(r_str)}\s*\)|[-+]\s*{re.escape(r_str)}\s*\(", c_text):
                        subst_validated_roots.add(r_str)
                        break

                    # Passage check: line in answer containing this claim mentions root r
                    c_src = str(c.get("source_text") or c.get("text") or "").strip()
                    matched_line = False
                    for line in ans_passages:
                        if c_src and (c_src in line or re.sub(r"\s+", "", c_src) in re.sub(r"\s+", "", line)):
                            if re.search(rf"(?:\b(?:x\s*=\s*|for\s+(?:x\s*=\s*)?|at\s+(?:x\s*=\s*)?|when\s+(?:x\s*=\s*)?|root\s*(?:is\s*|=?\s*)|root\s*){re.escape(r_str)}\b|(?<![\d.]){re.escape(r_str)}(?![\d.]))", line, re.I):
                                subst_validated_roots.add(r_str)
                                matched_line = True
                                break
                    if matched_line:
                        break

                    # Term evaluation check: arithmetic terms in claim match evaluated polynomial terms
                    terms = poly_terms_for_root.get(r_str)
                    if terms:
                        claim_nums = [int(n) for n in re.findall(r"-?\d+", c_text)]
                        abs_claim_nums = {abs(n) for n in claim_nums}
                        if all(abs(t) in abs_claim_nums for t in terms if t != 0):
                            subst_validated_roots.add(r_str)
                            break

            subst_passed = False
            if asks_subst_check:
                if asks_each_root and expected_roots:
                    subst_passed = all(r in subst_validated_roots for r in expected_roots)
                else:
                    subst_passed = bool(subst_validated_roots) or any(
                        (re.search(r"\b0\b", str(c.get("text", ""))) and re.search(r"\d+", str(c.get("text", ""))))
                        for c in claims_for_subst
                    )

            factor_passed = False
            if asks_factorization:
                factor_passed = any(
                    re.search(r"\([a-z]\s*[-+]\s*\d+\)", str(c.get("text", "") or c.get("source_text", "")))
                    for c in claims_for_factor
                )
                if not factor_passed:
                    factored_match = re.findall(r"\([a-z]\s*[-+]\s*\d+\)\s*(?:\*?\s*\([a-z]\s*[-+]\s*\d+\))+", answer or "", re.I)
                    if factored_match and eq_str and "=" in eq_str:
                        try:
                            import sympy as sp
                            lhs_raw = re.sub(r"^(?:for\s+(?:integer|real|complex)\s+[a-z],?\s*|\s*solve\s+|\s*find\s+|\s*determine\s+)+", "", eq_str.split("=")[0].strip(), flags=re.I)
                            poly_expr = sp.sympify(re.sub(r"([0-9])([a-z])", r"\1*\2", lhs_raw).replace("^", "**"))
                            for fm in factored_match:
                                fm_expr = sp.sympify(re.sub(r"([0-9])([a-z])", r"\1*\2", fm).replace("^", "**"))
                                if sp.simplify(poly_expr - fm_expr) == 0:
                                    factor_passed = True
                                    break
                        except Exception:
                            pass
                    if not factor_passed and factored_match and (passed_claims or all_passed_claims):
                        factor_passed = True

            roots_complete = True
            if (asks_complete_roots or asks_roots) and expected_roots:
                for r in expected_roots:
                    if not has_root_statement(answer, r):
                        roots_complete = False
                        break

            is_item_subst = bool(re.search(r"\b(?:substitution\s+checks?|substitution|substitut(?:e|ing))\b", item.lower()))
            is_item_roots = bool(re.search(r"\b(?:roots?|zeros?|solutions?)\b", item.lower()) and not is_item_subst)
            is_item_factorization = bool(re.search(r"\b(?:factori[sz]ation|factored(?:\s+form)?|factors?)\b", item.lower()))

            validation_incomplete = False
            item_verified = False

            if is_item_factorization:
                validation_incomplete = not factor_passed
                item_verified = factor_passed
            elif is_item_roots:
                validation_incomplete = not roots_complete
                item_verified = roots_complete and (bool(expected_roots) or bool(passed_claims or all_passed_claims))
            elif is_item_subst:
                validation_incomplete = not subst_passed
                item_verified = subst_passed
            else:
                if asks_subst_check and not subst_passed:
                    validation_incomplete = True
                if asks_factorization and not factor_passed:
                    validation_incomplete = True
                if asks_complete_roots and not roots_complete:
                    validation_incomplete = True
                item_verified = not validation_incomplete and bool(passed_claims or all_passed_claims)

            if item_verified and not validation_incomplete:
                status = "verified"
                check_state = "checked"
            elif is_item_subst and not subst_passed and not any(re.search(rf"\b{re.escape(str(r))}\b", answer or "") for r in expected_roots if "substitut" in (answer or "").lower()):
                status = "missing"
                answer_state = "missing"
                check_state = "unverified"
            else:
                status = "addressed"
                check_state = "unverified"

        computed = _computed_results(tool_map)
        if computed and status != "failed_check" and status != "missing":
            # Values computed by code for the question (tribos.writer.facts): an item they deliver is checked when the
            # answer states the computed value (the RK4 error, the tabulated points).
            rk = computed.get("rk4") or {}
            if rk and re.search(r"(?i)runge|\brk4\b|numerical\s+solution|absolute\s+error|max(?:imum)?\s+error", item):
                mantissa = str(rk.get("max_abs_error") or "").split("e")[0]
                if mantissa and mantissa in (answer or ""):
                    status, check_state = "verified", "checked"
                    evidence.append("computed_results")
            if is_point_eval and computed.get("table") and status == "addressed":
                status, check_state = "verified", "checked"
                evidence.append("computed_results")
            if status == "addressed" and _computed_item_checked(item, computed, answer or ""):
                status, check_state = "verified", "checked"
                evidence.append("computed_results")

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
