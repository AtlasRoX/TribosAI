"""The deliverables a question asks for, and whether the final answer provides them.

Completeness is a property of the request, not of the tool log: a run whose tools all succeeded can still leave a
requested quantity out, and a run with a failed (and recovered) attempt can still answer everything. Items are read
from the imperative clauses of the question ("Calculate the natural frequency, damping ratio, ...; report the maximum
absolute error, ..."). Each item is

- missing:       most of its words appear nowhere in the answer (conservative: wording differences are tolerated),
- failed_check:  a quantity the question asks for is addressed, but a mathematical statement in the passage or table
                 row that addresses it was contradicted by the checks (tribos.verify.math_claims),
- verified:      a requested quantity is addressed and a statement there passed the checks,
- addressed:     present, not checked (prose requests such as "explain" or "consult" are never checked here).
"""

from __future__ import annotations

import re
from typing import Any

_VERBS = (
    "calculate", "compute", "determine", "find", "derive", "report", "give", "state", "estimate", "evaluate", "plot",
    "simulate", "verify", "check", "compare", "investigate", "explain", "discuss", "consult", "provide", "include",
    "list", "show", "prove", "solve", "analy[sz]e", "quantify", "predict", "assess", "distinguish", "describe",
)
# Not inside a hyphenated word: "steady-state" contains no verb "state".
_VERB_RE = re.compile(r"(?<![\w-])(?:" + "|".join(_VERBS) + r")(?![\w-])", re.I)
# Verbs whose objects are quantities or results a check can confirm; the others ask for prose.
_QUANTITY_VERBS = {"calculate", "compute", "determine", "find", "derive", "report", "estimate", "evaluate", "solve",
                   "quantify", "predict", "give", "state"}
_LEAD_RE = re.compile(r"^(?:\s*(?:the|a|an|its|their|all|any|both|each|independently|clearly|also)\b)+", re.I)
_TAIL_RE = re.compile(
    r"\b(?:using|with|over|for|from|via|in order|so that|by|at|between|under|within|governed|given|defined|where|"
    r"which|that|whose)\b.*$",
    re.I,
)
_STOP = {"the", "and", "for", "with", "that", "this", "from", "into", "its", "their", "any", "all", "results", "result",
         "values", "value", "including", "both", "each"}
# The question's subject ("Investigate a forced damped mass-spring system") is not a deliverable.
_SUBJECT_WORDS = {"system", "problem", "model", "question", "setup", "configuration"}
# Verbs whose object is the activity itself ("simulate the system" asks for a simulation).
_ACTIVITY = {"simulate": "numerical simulation", "compare": "comparison", "plot": "plot"}
_SPLIT_RE = re.compile(r",\s*(?:and\s+|or\s+)?|\s+and\s+(?=(?:the\s+)?[a-z\-]+(?:\s+[a-z\-]+){0,3}\s*(?:,|$))", re.I)


# A verdict on a yes/no or status question.
_STATUS_RE = re.compile(
    r"\b(?:true|false|holds?|fails?|proved|proven|unproven|disproved|disproof|counterexamples?|open\s+(?:problem|question|conjecture)|"
    r"(?:remains?|is)\s+open|unknown|unresolved|not\s+(?:been\s+)?(?:proved|proven|known|established)|yes|no)\b", re.I)


def _words(text: str) -> list[str]:
    return [w for w in re.findall(r"[a-z][a-z\-]{2,}", (text or "").lower()) if w not in _STOP]


def _stem(word: str) -> str:
    return word.replace("-", "")[:6]


def _clauses(question: str) -> list[tuple[str, str]]:
    """(verb, object text) for every imperative verb; an object ends at the next verb or at the sentence end."""
    out: list[tuple[str, str]] = []
    for sentence in re.split(r"[.;:?!](?:\s+|$)", question or ""):
        hits = list(_VERB_RE.finditer(sentence))
        for i, m in enumerate(hits):
            end = hits[i + 1].start() if i + 1 < len(hits) else len(sentence)
            out.append((m.group(0).lower(), sentence[m.end():end]))
    return out


def requested_items(question: str, limit: int = 24) -> list[dict[str, str]]:
    """Noun phrases the question asks the answer to provide, in order: [{item, verb}]."""
    from ..axiom.problem import (
        strip_question_framing,  # local: sympy is heavy and the framing rules live there
    )

    items: list[tuple[str, str]] = []
    # "solve <image>" arrives as "solve\n\nAttached image 1 (q.png), transcribed: ...": the header is not a request
    # ("transcribed" is no deliverable), nor is a source label ("IMO 1960 Problem 2").
    for verb, rest in _clauses(strip_question_framing(question)):
        found = False
        for part in _SPLIT_RE.split(rest):
            p = _LEAD_RE.sub("", part or "").strip()
            p = _TAIL_RE.sub("", p).strip(" ,")
            p = re.sub(r"^(?:including|such as|e\.g\.?)\s+", "", p, flags=re.I)
            p = re.sub(r"\s+(?:and|or)$", "", p).strip(" ,")
            words = _words(p)
            if not words or len(words) > 7 or "=" in p or re.search(r"\d", p) or _SUBJECT_WORDS & set(words):
                continue
            if re.match(r"(?i)(?:or|and|nor)\b", p):
                continue  # "prove or disprove that ...": the second verb of one request, not a deliverable
            items.append((" ".join(p.split()), verb))
            found = True
        if not found and verb in _ACTIVITY:
            items.append((_ACTIVITY[verb], verb))
    out: list[dict[str, str]] = []
    seen: set[str] = set()
    for it, verb in items:
        key = " ".join(_stem(w) for w in _words(it))
        if key and key not in seen:
            seen.add(key)
            out.append({"item": it, "verb": verb})
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


def assess(question: str, answer: str, math_audit: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    """[{item, status, where}] for each requested deliverable."""
    stems_all = {_stem(w) for w in _words(answer)}
    passages = [(p, {_stem(w) for w in _words(p)}) for p in _passages(answer)]
    claims = list((math_audit or {}).get("claims") or [])
    results: list[dict[str, Any]] = []
    from ..utils.output_contract import mask_instructions

    for req in requested_items(mask_instructions(question)):
        item, verb = req["item"], req["verb"]
        item_stems = [_stem(w) for w in _words(item)]
        if not item_stems:
            continue
        proof_item = re.search(r"(?i)\b(?:proof|justification|argument|demonstration)\b", item)
        if (re.match(r"(?i)whether\b|if\b", item) or proof_item) and _STATUS_RE.search(answer or ""):
            # A requested proof of a statement the answer shows false is delivered by the disproof (audit I14/T05).
            # "Determine whether the claim is proved": a verdict (proved, false, open, a counterexample) answers it,
            # whatever words the item itself uses (audit I14: a valid disproof was reported "not addressed").
            results.append({"item": item, "status": "addressed", "where": _STATUS_RE.search(answer).group(0),
                            "quantity": verb in _QUANTITY_VERBS})
            continue
        present = sum(1 for s in item_stems if _has(stems_all, s)) / len(item_stems)
        if present < 0.5:
            results.append({"item": item, "status": "missing", "where": "", "quantity": verb in _QUANTITY_VERBS})
            continue
        best, best_score = "", 0.0
        for text, stems in passages:
            score = sum(1 for s in item_stems if _has(stems, s)) / len(item_stems)
            if score > best_score:
                best, best_score = text, score
        status = "addressed"
        if best and claims and verb in _QUANTITY_VERBS:
            norm = re.sub(r"\s+", " ", best)
            hits = [c for c in claims if c.get("source_text") and re.sub(r"\s+", " ", str(c["source_text"])) in norm]
            if any(c.get("status") == "failed" for c in hits):
                status = "failed_check"
            elif any(c.get("status") == "passed" for c in hits):
                status = "verified"
        results.append({"item": item, "status": status, "where": re.sub(r"\s+", " ", best)[:160],
                        "quantity": verb in _QUANTITY_VERBS})
    return results


__all__ = ["assess", "requested_items"]
