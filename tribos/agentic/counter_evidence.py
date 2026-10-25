"""
Counter-evidence and contradiction search (feature 7, stage augment).

After the pipeline's evidence exists, the phase looks for literature that argues against its main claims, so the
answer discusses conflicts instead of presenting one side:

- PaperQA2 / ContraCrow (Skarlinski et al. 2024, arXiv:2409.13740): extract claims, search for contradicting
  literature, rate each (claim, passage) pair on an 11-point Likert scale (0 = strongly supports, 5 = lack of
  evidence, 10 = strongly contradicts) and flag a contradiction at 8 or more.
- SciFact (Wadden et al., EMNLP 2020, arXiv:2004.14974) and SciFact-Open (Findings EMNLP 2022, arXiv:2210.13777):
  the SUPPORTS / REFUTES / NOINFO label scheme, here "supports" / "contradicts" / "neutral".
- Chain-of-Verification (Dhuliawala et al., Findings ACL 2024, arXiv:2309.11495): the "find evidence against X"
  verification questions are answered independently of the draft (this phase runs before any draft exists).

Claims come from the evidence (passage sentences that state a result: a prediction, a scaling, a bound, an
agreement with measurement) or, failing that, from the question. Queries are deterministic negations of the
question's main concept, equation, system or material ("<x> limitations", "<x> counterexample", "<x> breakdown
regime", "<x> experimental discrepancy", "<material> failure mode"); at most 3 literature calls run and only passages
not already in the evidence are kept. Each pair is classified by, in order: the NLI judge another phase installed
(state.bag["nli_judge_async"], then state.bag["nli_judge_fn"]), the agent model with the Likert rubric
([phase:counter_evidence]), or a cue-word heuristic that is always labelled "heuristic" and never reported as a
certain contradiction.

After the answer is written and verified, a second, model-free pass (CounterEvidenceRecheckPhase, stage finalize)
re-checks the answer's own top claims (mathematical and numeric ones from the verifier report, recheck_claims) against
the counter-evidence passages already fetched, with the NLI judge or the cue-word heuristic; rows are added to the
same artifact under "answer_rechecks". No new literature calls are made.

Off when agent_options.enable_counter_evidence is false, when TRIBOS_COUNTER_EVIDENCE=off, outside research
scope, or when the turn's source restriction excludes the literature tool.
"""

from __future__ import annotations

import inspect
import logging
import re
from html import escape
from typing import Any

from pydantic import BaseModel, Field

from ..sources.keys import passage_keys, same_document
from ..utils.text import sentence_spans
from ..verify.verifier import truncate_words
from .config import env_flag
from .guardrails import SPOTLIGHT_RULE, neutralise, spotlight
from .runtime import AgentPhase, PhaseOutcome, register_phase
from .specialists import (
    ask_json,
    fetch_new_literature,
    is_pure_derivation,
    iter_passages,
    named_tool_allowed,
    passage_source_key,
    query_entities,
    resolve_literature_tool,
    seen_passages,
    stems,
)

logger = logging.getLogger(__name__)

MAX_QUERIES = 3
MAX_CLAIMS = 3
MAX_PAIRS = 10
FLAG_AT = 8  # ContraCrow: a claim is contradicted at a Likert score of 8 or more

# Sentences that state a checkable result: a prediction, a scaling or bound, a dependence, an agreement with data.
_CLAIM_CUE_RE = re.compile(
    r"\b(predict\w*|scal(?:es|ing)|proportional|bound(?:ed|s)?|converg\w*|diverg\w*|stab(?:le|ility)|unstable|"
    r"increas\w*|decreas\w*|reduc\w*|improv\w*|exceed\w*|depend\w*|correlat\w*|associat\w*|agree\w*|consistent|"
    r"valid|holds?|satisf\w*|implies|yield\w*|exhibit\w*|enhanc\w*|suppress\w*|dominat\w*|governed by|follows?)\b",
    re.I,
)
# Cue words for the heuristic classifier: (pattern, weight). Strong cues state a negative finding outright: a
# counterexample, a result that does not hold, a model that breaks down or disagrees with measurement.
_CONTRA_CUES: tuple[tuple[re.Pattern, int], ...] = (
    (re.compile(r"\bcounter-?examples?\b|\bdisprov\w*|\brefut\w*|\bfalsif\w*", re.I), 3),
    (re.compile(r"\b(?:does|do|did) not (?:hold|apply|agree|match|converge|reproduce|predict|scale|generali[sz]e|"
                r"satisfy|capture|improve|reduce|increase|show)\b", re.I), 3),
    (re.compile(r"\bbreaks? down\b|\bbreakdown of\b|\bfails? (?:to|for|when|at|beyond|in)\b|\bfailure of\b"
                r"|\binvalid(?:ates?|ated)?\b|\bviolat\w*", re.I), 3),
    (re.compile(r"\bcontrary to\b|\bno longer (?:valid|holds?|applies)\b", re.I), 3),
    (re.compile(r"\bno (?:statistically )?significant (?:effect|improvement|change|correlation|dependence)\b", re.I), 2),
    (re.compile(r"\bdiscrepanc(?:y|ies)\b|\bdeviat\w* (?:from|significantly)\b|\bdisagree\w*|\b(?:over|under)estimat\w*",
                re.I), 2),
    (re.compile(r"\b(?:inconsistent|conflicting|controvers\w*|contradict\w*)\b", re.I), 2),
)
# A negated discrepancy ("no significant deviation from the prediction", "without measurable error") reports
# agreement: it is not a negative finding about the claim, so these spans are removed before the contradiction cues
# are counted (AGT-008: a single negation word must not read as a contradiction).
_DISCREPANCY_TERMS = (
    r"(?:deviations?|discrepanc(?:y|ies)|disagreements?|errors?|differences?|violations?|breakdowns?|instabilit(?:y|ies)"
    r"|failures?|anomal(?:y|ies)|inconsistenc(?:y|ies))"
)
_DISCREPANCY_QUALIFIERS = (
    r"(?:(?:statistically )?significant(?:ly)?|appreciable|measurable|noticeable|systematic|large|major|notable"
    r"|observable|detectable|substantial)\s+"
)
_NEGATED_DISCREPANCY_RE = re.compile(
    rf"\b(?:no|without|absence of|free of|nor|not any|negligible)\s+(?:{_DISCREPANCY_QUALIFIERS}){{0,3}}{_DISCREPANCY_TERMS}\b"
    rf"|\b(?:did|does|do)\s+not\s+(?:show|exhibit|reveal|display|produce|find|observe)\s+(?:an?\s+)?"
    rf"(?:{_DISCREPANCY_QUALIFIERS}){{0,3}}{_DISCREPANCY_TERMS}\b",
    re.I,
)
_SUPPORT_CUE_RE = re.compile(
    r"\b((?:good|excellent|close|reasonable) agreement|agrees? (?:well )?with|in agreement with|consistent with|"
    r"confirm\w*|validat\w*|verif(?:y|ies|ied)|reproduc(?:es|ed)|matche[sd]|accurately predict\w*)\b",
    re.I,
)


class _Rating(BaseModel):
    pair: int
    likert: float = 5
    reason: str = ""


class _RatingReply(BaseModel):
    ratings: list[_Rating] = Field(default_factory=list)


COUNTER_SYSTEM = (
    "[phase:counter_evidence] You rate whether a retrieved passage contradicts a scientific or engineering claim, using the "
    "PaperQA2/ContraCrow 11-point scale: 0 = strongly supports, 2 = supports, 5 = lack of evidence or unrelated, "
    "8 = contradicts, 10 = strongly contradicts. A passage contradicts a claim only if it reports a finding that "
    "is incompatible with it in the same regime (a counterexample, a measurement that disagrees with the prediction, "
    "a model that breaks down, an opposite trend); a different regime, geometry, material or parameter range is at "
    "most a partial conflict (6-7). Reply with only JSON: "
    '{"ratings":[{"pair":<number>,"likert":<0-10>,"reason":"<one sentence>"}]}\n' + SPOTLIGHT_RULE
)


def _sentences(text: str) -> list[str]:
    text = text or ""
    return [text[s:e].strip() for s, e in sentence_spans(text) if len(text[s:e].split()) >= 5]


def subject_names(entities: dict[str, list[str]]) -> list[str]:
    """The question's subjects a claim or a negation query is about: concepts, equations, systems, then materials."""
    names: list[str] = []
    for kind in ("concepts", "equations", "systems", "materials"):
        names.extend(n for n in entities.get(kind) or [] if n and n not in names)
    return names


def extract_claims(state: Any, entities: dict[str, list[str]]) -> list[dict[str, Any]]:
    """Up to 3 checkable claims from the gathered evidence, else one from the question."""
    names = subject_names(entities)
    name_stems = stems(" ".join(names))
    claims: list[dict[str, Any]] = []
    scored: list[tuple[float, str, str]] = []
    for rkey, p in iter_passages(state.tool_results):
        for s in _sentences(str(p.get("passage_text") or "")):
            cues = len(_CLAIM_CUE_RE.findall(s))
            if not cues:
                continue
            mention = 2.0 if name_stems & stems(s) else 0.0
            if names and not mention:
                continue
            scored.append((mention + min(cues, 3), truncate_words(s, 300), passage_source_key(p, rkey)))
    for _score, text, skey in sorted(scored, key=lambda t: -t[0]):
        if len(claims) >= MAX_CLAIMS:
            break
        if all(c["text"] != text for c in claims):
            claims.append({"text": text, "source_key": skey, "entity": names[0] if names else ""})
    if not claims:
        claims.append({"text": state.clean_query or state.query, "source_key": "question", "entity": names[0] if names else ""})
    for i, c in enumerate(claims, 1):
        c["id"] = f"c{i}"
    return claims


# A bare number, a unit or a generic mechanical component is not a subject a contradicting paper is written about.
_NOT_A_SUBJECT_RE = re.compile(
    r"^\d|^(?:kg|g|mg|mm|cm|m|s|ms|N|kN|Pa|kPa|MPa|GPa|Hz|kHz|MHz|rad/s|J|kJ|W|kW|ball|oscillator|spring|damper)$", re.I
)
# Negation templates per subject kind. A theory, method or equation is challenged by counterexamples, limits of
# validity and disagreement with measurement; a material or engineered system by its failure modes.
_THEORY_NEGATIONS = ("{} limitations", "{} counterexample", "{} breakdown regime", "{} experimental discrepancy")
_MATERIAL_NEGATIONS = ("{} failure mode", "{} limitations", "{} experimental discrepancy")


def negation_queries(entities: dict[str, list[str]]) -> list[str]:
    """Deterministic contradiction queries for the question's main subject (a concept, equation or system), plus a
    failure-mode query for the first material when the question names one. No subject, no queries."""
    def first(kinds: tuple[str, ...]) -> str:
        for kind in kinds:
            for name in entities.get(kind) or []:
                if name and not _NOT_A_SUBJECT_RE.search(name.strip()):
                    return name.strip()
        return ""

    subject = first(("concepts", "equations", "systems"))
    material = first(("materials",))
    queries: list[str] = []
    if subject:
        queries.append(_THEORY_NEGATIONS[0].format(subject))
        if material and material != subject:
            queries.append(_MATERIAL_NEGATIONS[0].format(material))
        queries += [t.format(subject) for t in _THEORY_NEGATIONS[1:]]
    elif material:
        queries += [t.format(material) for t in _MATERIAL_NEGATIONS]
    return list(dict.fromkeys(queries))[:MAX_QUERIES]


def label_for(likert: float) -> str:
    return "contradicts" if likert >= FLAG_AT else ("supports" if likert <= 2 else "neutral")


def heuristic_rating(claim: str, passage: str) -> tuple[int, str]:
    """Cue-word estimate of the Likert score: at most FLAG_AT - 1, so cue words alone never reach "contradicts"
    (they can still be flagged as a possible conflict to check at 7). A negated discrepancy ("no significant
    deviation") is not counted as a negative finding."""
    claim_stems = stems(claim)
    overlap = len(claim_stems & stems(passage))
    if not claim_stems or overlap == 0:
        return 5, "passage does not mention the claim's terms"
    negated = bool(_NEGATED_DISCREPANCY_RE.search(passage))
    scan = _NEGATED_DISCREPANCY_RE.sub(" ", passage)
    hits = [(pat.pattern, w) for pat, w in _CONTRA_CUES if pat.search(scan)]
    contra = sum(w for _p, w in hits)
    if contra:
        return min(FLAG_AT - 1, 5 + contra), "negative-finding cue words in the passage (heuristic, unverified)"
    if _SUPPORT_CUE_RE.search(scan):
        return 3, "supporting cue words in the passage (heuristic, unverified)"
    if negated:
        return 5, "the passage reports an absence of discrepancy (e.g. no significant deviation), not a negative finding (heuristic)"
    return 5, "no cue words either way (heuristic)"


async def _judge(fn: Any, claim: str, source_key: str, passage: str) -> dict[str, Any] | None:
    try:
        out = fn(claim, [{"source_key": source_key, "passage": passage}])
        if inspect.isawaitable(out):
            out = await out
    except Exception as exc:  # noqa: BLE001
        logger.info("NLI judge failed on a counter-evidence pair: %s", exc)
        return None
    return out if isinstance(out, dict) and out.get("status") else None


_NLI_LIKERT = {"contradicted": 9, "supported": 1, "unsupported": 5}


class CounterEvidencePhase(AgentPhase):
    key = "counter_evidence"
    stage = "augment"
    order = 60
    frameworks = None  # every agentic framework

    def applies(self, state: Any) -> bool:
        if state.options.get("enable_counter_evidence") is False or env_flag("TRIBOS_COUNTER_EVIDENCE") == "off":
            return False
        if getattr(state.ctx, "scope", "research") != "research":
            return False
        # A pure mathematics or physics derivation, proof or calculation (by sub-question focus or planner intent) is
        # checked by computation, not argued against with papers.
        if is_pure_derivation(state):
            return False
        lit_tool = resolve_literature_tool(state.registry, state)
        return named_tool_allowed(state, lit_tool)

    async def run(self, state: Any) -> PhaseOutcome | None:
        entities = query_entities(state.ctx)
        queries = negation_queries(entities)
        if not queries:
            return None
        await state.step("agent_counter_evidence", "Searching for contradicting evidence", "; ".join(queries),
                         status="running", agent="Counter-evidence searcher")
        claims = extract_claims(state, entities)
        seen = seen_passages(state.tool_results)
        new: list[tuple[str, dict[str, Any]]] = []
        for q in queries:
            if state.budget.exhausted():
                break
            keywords = [w for w in q.split() if w.lower() not in ("evidence", "regime", "mode")] + entities["systems"][:1]
            key, passages = await fetch_new_literature(
                state, phase=self.key, query=q, purpose=f"counter-evidence search: {q}", seen=seen,
                keywords=keywords, max_articles=4, render=False,
            )
            new.extend((key, p) for p in passages if key)

        pairs: list[dict[str, Any]] = []
        for rkey, p in new[:MAX_PAIRS]:
            text = re.sub(r"\s+", " ", str(p.get("passage_text") or "")).strip()
            p_stems = stems(text)
            claim = max(claims, key=lambda c: len(stems(c["text"]) & p_stems))
            pairs.append({
                "claim_id": claim["id"], "claim": claim["text"], "passage": text[:1200],
                "source_key": passage_source_key(p, rkey), "result_key": rkey,
                "pmid": str(p.get("pmid") or ""), "doi": str(p.get("doi") or ""), "keys": passage_keys(p),
                "citation": str(p.get("citation") or p.get("citation_label") or ""),
                "setting": str(p.get("grade_label") or p.get("experimental_setting") or ""),
            })
        await self._classify(state, pairs)

        flagged = [r for r in pairs if r["likert"] >= FLAG_AT or (r["classifier"] == "heuristic" and r["likert"] >= 7)]
        classifiers = [r["classifier"] for r in pairs]
        top = max(set(classifiers), key=classifiers.count) if classifiers else "heuristic"
        artifact = {
            "queries": queries,
            "claims_checked": len(claims),
            "classifier": top,
            "claims": [{"id": c["id"], "text": c["text"], "source_key": c["source_key"]} for c in claims],
            "conflicts": [
                {
                    "claim": r["claim"], "passage": r["passage"][:600], "source_key": r["source_key"], "pmid": r["pmid"],
                    "doi": r["doi"], "keys": r["keys"], "label": r["label"], "likert": r["likert"], "score": r["score"],
                    "classifier": r["classifier"], "reason": r["reason"][:240],
                }
                for r in pairs
            ][:50],
        }
        state.artifacts["evidence_conflicts"] = artifact
        if flagged:
            state.evidence_sections.append(self._section(claims, flagged, top))
            heuristic = any(r["classifier"] == "heuristic" for r in flagged)
            state.brief_notes.append(
                f"A counter-evidence search found {len(flagged)} passage(s) that may conflict with the main claims "
                "(<evidence_conflicts>). Discuss these conflicts explicitly: name the claim each bears on, compare the "
                "strength and setting of the sources, and say whether the conflict changes the conclusion."
                + (" Some were flagged by cue words only (classifier=heuristic): present them as possible conflicts "
                   "to check, not as established contradictions." if heuristic else "")
            )
        text = (
            f"Checked {len(claims)} claim(s) against {len(pairs)} new passage(s): "
            f"{len(flagged)} possible conflict(s) (classifier: {top})." if pairs else
            "No new passages beyond the evidence already gathered."
        )
        await state.step("agent_counter_evidence", "Searched for contradicting evidence", text, agent="Counter-evidence searcher")
        return None

    async def _classify(self, state: Any, pairs: list[dict[str, Any]]) -> None:
        # The async judge may call the NLI model on a cache miss; the sync one answers from its cache or local model.
        judges = [j for j in (state.bag.get("nli_judge_async"), state.bag.get("nli_judge_fn")) if callable(j)]
        pending: list[dict[str, Any]] = []
        for r in pairs:
            out = None
            for judge in judges:
                out = await _judge(judge, r["claim"], r["source_key"], r["passage"])
                if out is not None:
                    break
            status = str((out or {}).get("status") or "").lower()
            if status in _NLI_LIKERT:
                likert = _NLI_LIKERT[status]
                score = (out or {}).get("score", (out or {}).get("probability"))
                r.update(likert=likert, label=label_for(likert), classifier="nli", reason=str((out or {}).get("reason") or ""),
                         score=round(float(score), 3) if isinstance(score, (int, float)) else round(likert / 10, 2))
            else:
                pending.append(r)
        if pending:
            ratings = await self._model_ratings(state, pending)
            for i, r in enumerate(pending, 1):
                if i in ratings:
                    likert, reason = ratings[i]
                    r.update(likert=likert, label=label_for(likert), classifier="llm", reason=reason, score=round(likert / 10, 2))
                else:
                    likert, reason = heuristic_rating(r["claim"], r["passage"])
                    # A heuristic score is a weak signal: its score is scaled down so it never reads as certain.
                    r.update(likert=likert, label=label_for(likert), classifier="heuristic", reason=reason,
                             score=round(likert / 10 * 0.6, 2))

    async def _model_ratings(self, state: Any, pairs: list[dict[str, Any]]) -> dict[int, tuple[int, str]]:
        blocks = [
            f"Pair {i}:\nClaim: {spotlight(r['claim'], 'claim', 400)}\nPassage ({r['source_key']}): "
            f"{spotlight(r['passage'], r['source_key'] or 'passage', 1000)}"
            for i, r in enumerate(pairs, 1)
        ]
        reply = await ask_json(state, COUNTER_SYSTEM, "\n\n".join(blocks), phase=self.key, schema=_RatingReply)
        if not isinstance(reply, _RatingReply):
            return {}
        out: dict[int, tuple[int, str]] = {}
        for row in reply.ratings:
            if 1 <= row.pair <= len(pairs):
                out[row.pair] = (int(round(max(0.0, min(10.0, float(row.likert))))), row.reason[:300])
        return out

    @staticmethod
    def _section(claims: list[dict[str, Any]], rows: list[dict[str, Any]], classifier: str) -> str:
        heuristic = any(r["classifier"] == "heuristic" for r in rows)
        note = (
            "Passages from a targeted search for contradicting evidence (PaperQA2/ContraCrow scale: 0 strongly supports, "
            "5 no evidence, 10 strongly contradicts; flagged at 8 or more). Discuss each conflict explicitly."
            + (" Rows with classifier=heuristic were flagged by cue words only and are unverified possible conflicts."
               if heuristic else "")
        )
        used = {r["claim_id"] for r in rows}
        parts = [f'<evidence_conflicts classifier="{escape(classifier, quote=True)}" note="{escape(note, quote=True)}">']
        for c in claims:
            if c["id"] in used:
                parts.append(f'<claim id="{escape(c["id"], quote=True)}">{escape(neutralise(c["text"]), quote=False)}</claim>')
        for r in rows:
            attrs = {
                "claim": r["claim_id"], "label": r["label"], "likert": str(r["likert"]), "classifier": r["classifier"],
                "flag": "flagged" if r["likert"] >= FLAG_AT else "possible",
                "certainty": "low" if r["classifier"] == "heuristic" else ("model" if r["classifier"] == "llm" else "nli"),
                "source_key": r["source_key"], "pmid": r["pmid"], "doi": r["doi"], "citation": r["citation"],
                "setting": r["setting"] or "unspecified",
            }
            attr_text = " ".join(f'{k}="{escape(v, quote=True)}"' for k, v in attrs.items())
            parts.append(f"<conflict {attr_text}>{spotlight(r['passage'], r['source_key'] or 'passage', 700)}</conflict>")
        parts.append("</evidence_conflicts>")
        return "\n".join(parts)


COUNTER_EVIDENCE_PHASE = CounterEvidencePhase()
register_phase(COUNTER_EVIDENCE_PHASE)


# After-draft re-check ----------------------------------------------------------------------------------------
MAX_RECHECK_CLAIMS = 5
_FIGURE_RE = re.compile(r"\d")


def _attr(obj: Any, name: str, default: Any = None) -> Any:
    return obj.get(name, default) if isinstance(obj, dict) else getattr(obj, name, default)


# Verifier claim types re-checked even without a figure: results stated about the subject ("clinical" is the
# verifier's label for an outcome claim about a study, kept while the verifier still emits it).
_RESULT_CLAIM_TYPES = frozenset({"mathematical", "quantitative", "empirical", "clinical"})
_ID_TOKEN_RE = re.compile(r"\b(?:PMID|arXiv|DOI|Zbl|MR):?\s*[\w./-]+|\b10\.\d{4,9}/\S+", re.IGNORECASE)


def recheck_claims(report: Any, limit: int = MAX_RECHECK_CLAIMS) -> list[dict[str, Any]]:
    """The answer's top claims for a counter-evidence re-check: result claims (mathematical, quantitative) and
    claims with a figure from the verifier report (contradicted ones are already flagged and skipped), result
    claims first."""
    picked: list[tuple[int, dict[str, Any]]] = []
    for c in list(_attr(report, "claims", None) or []):
        text = str(_attr(c, "claim_text", "") or "").strip()
        kind = str(_attr(c, "claim_type", "") or "")
        status = str(_attr(c, "status", "") or "")
        if not text or status == "contradicted" or kind == "absence":
            continue
        numeric = bool(_FIGURE_RE.search(_ID_TOKEN_RE.sub(" ", text)))  # an identifier's digits are not a figure
        result = kind in _RESULT_CLAIM_TYPES
        if not result and not numeric:
            continue
        evidence = list(_attr(c, "evidence", None) or [])
        source = str(_attr(evidence[0], "source_key", "") or "") if evidence else ""
        rank = (0 if result else 1) * 2 + (0 if numeric else 1)
        picked.append((rank, {"id": f"a{len(picked) + 1}", "text": text, "source_key": source or "answer"}))
    picked.sort(key=lambda t: t[0])
    return [c for _r, c in picked[:limit]]


def _own_source(claim: dict[str, Any], row: dict[str, Any]) -> bool:
    """Whether a counter-evidence row is the claim's own supporting source, under any of the row's identifiers."""
    own = str(claim.get("source_key") or "")
    if not own:
        return False
    keys = [str(row.get("source_key") or ""), *(str(k) for k in row.get("keys") or [])]
    keys += [f"DOI:{row['doi']}"] if row.get("doi") else []
    keys += [f"PMID:{row['pmid']}"] if row.get("pmid") else []
    return any(k and (k == own or same_document(k, own)) for k in keys)


def recheck_pairs(claims: list[dict[str, Any]], passages: list[dict[str, Any]], max_pairs: int = MAX_PAIRS) -> list[dict[str, Any]]:
    """(answer claim, counter-evidence passage) pairs: each claim with the passages sharing at least two stems,
    never the claim's own supporting source (compared as documents, so "arXiv:2312.04511v2" and "ARXIV:2312.04511",
    or a passage's DOI and its arXiv id, are the same source)."""
    pairs: list[dict[str, Any]] = []
    for c in claims:
        c_stems = stems(c["text"])
        for p in passages:
            text = str(p.get("passage") or "")
            if not text or len(c_stems & stems(text)) < 2 or _own_source(c, p):
                continue
            pairs.append({
                "claim_id": c["id"], "claim": c["text"], "passage": text, "source_key": str(p.get("source_key") or ""),
                "pmid": str(p.get("pmid") or ""), "doi": str(p.get("doi") or ""),
            })
            if len(pairs) >= max_pairs:
                return pairs
    return pairs


async def recheck_answer_claims(state: Any, claims: list[dict[str, Any]] | None = None) -> list[dict[str, Any]]:
    """Re-check the answer's claims against the counter-evidence passages already in the evidence_conflicts
    artifact, with the NLI judge (if installed) or the cue-word heuristic. No model or literature calls. A heuristic
    row is capped below the contradiction flag so cue words alone never count as a contradiction."""
    art = state.artifacts.get("evidence_conflicts") if isinstance(state.artifacts, dict) else None
    passages = [r for r in ((art or {}).get("conflicts") or []) if isinstance(r, dict)]
    claims = recheck_claims(state.verification) if claims is None else claims
    pairs = recheck_pairs(claims, passages)
    judges = [j for j in (state.bag.get("nli_judge_async"), state.bag.get("nli_judge_fn")) if callable(j)]
    for r in pairs:
        out = None
        for judge in judges:
            out = await _judge(judge, r["claim"], r["source_key"], r["passage"])
            if out is not None:
                break
        status = str((out or {}).get("status") or "").lower()
        if status in _NLI_LIKERT:
            likert, classifier, reason = _NLI_LIKERT[status], "nli", str((out or {}).get("reason") or "")
        else:
            likert, reason = heuristic_rating(r["claim"], r["passage"])  # already capped below FLAG_AT
            likert, classifier = min(likert, FLAG_AT - 1), "heuristic"
        r.update(likert=likert, label=label_for(likert), classifier=classifier, reason=truncate_words(reason, 240),
                 score=round(likert / 10 * (0.6 if classifier == "heuristic" else 1.0), 2), phase="after_draft")
    return pairs


class CounterEvidenceRecheckPhase(AgentPhase):
    """After the answer is verified: re-check its top numeric/clinical claims against the counter-evidence
    passages fetched before the draft. Runs before confidence (order 10), which reads contradicting rows."""

    key = "counter_evidence_recheck"
    stage = "finalize"
    order = 5
    frameworks = None

    def applies(self, state: Any) -> bool:
        art = state.artifacts.get("evidence_conflicts") if isinstance(state.artifacts, dict) else None
        return bool(isinstance(art, dict) and art.get("conflicts") and state.verification is not None)

    async def run(self, state: Any) -> PhaseOutcome | None:
        claims = recheck_claims(state.verification)
        if not claims:
            return None
        rows = await recheck_answer_claims(state, claims)
        art = state.artifacts["evidence_conflicts"]
        art["answer_rechecks"] = rows[:MAX_PAIRS]
        flagged = [r for r in rows if r["likert"] >= FLAG_AT]
        if flagged:
            art["conflicts"] = list(art.get("conflicts") or []) + [
                {k: r[k] for k in ("claim", "passage", "source_key", "pmid", "doi", "label", "likert", "score", "classifier", "reason", "phase")}
                for r in flagged
            ]
        if rows:
            await state.step(
                "agent_counter_recheck",
                "Re-checked the answer's claims against contradicting evidence",
                f"{len(claims)} answer claim(s) against {len(rows)} passage pair(s): {len(flagged)} contradiction(s)",
                agent="Counter-evidence searcher",
            )
        return None


COUNTER_EVIDENCE_RECHECK_PHASE = CounterEvidenceRecheckPhase()
register_phase(COUNTER_EVIDENCE_RECHECK_PHASE)
