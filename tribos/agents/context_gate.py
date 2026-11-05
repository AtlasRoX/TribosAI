"""
Context gate: what retrieved evidence reaches the answer model, and how much of it.

Two deterministic steps on the retrieved passages (no model call, standard library only):

1. Query-focused extractive compression. Each passage is split into sentences and only the sentences relevant to
   the question are kept, ranked by BM25 (Robertson & Zaragoza, Found. Trends Inf. Retr. 2009) over all retrieved
   sentences, within a character budget. Extractive compression of retrieved documents keeps question-answering
   accuracy at a fraction of the tokens: RECOMP (Xu, Shi & Choi, ICLR 2024) selects sentences with a trained
   scorer; here the scorer is lexical, so it needs no model and no network. Long contexts also hurt models directly:
   facts in the middle of a long context are used less (Liu et al., "Lost in the Middle", TACL 2024), so a shorter,
   relevant context is not only cheaper.

2. The Lumo Admission Gate (standalone package: https://github.com/AtlasRoX/Lumo-GATE). Every kept sentence gets
   an integer admission score K: the weight of its source class (official +3, internal +2, external +1, unverified 0,
   outdated -2, false -3), plus the weight of every other independent source that states the same fact, minus the
   weight of every reliable source that states a conflicting number. Only K >= 1 is admitted to the model; K = 0 is
   quarantined and K <= -1 blocked, and both are only counted. The decision is deterministic, never made by a model.
   What it encodes is source-weighted corroboration with abstention, which grounding research supports (answers
   restricted to attributable evidence, Gao et al., ALCE, EMNLP 2023; abstaining when evidence is weak, selective
   prediction); K is only as good as the source classes behind it.

Source classes in Tribos: a technical report or standard, and a standards or regulatory host, are official; a
peer-reviewed journal or conference paper, a textbook or reference work, and a repository, publisher or university
host are internal (curated); a preprint and other web pages are external; forums and social media are unverified;
a retracted paper is false.

Settings: TRIBOS_CONTEXT_GATE (on), TRIBOS_CONTEXT_GATE_CHARS (literature budget after compression).
"""

from __future__ import annotations

import math
import re
from collections import Counter
from dataclasses import dataclass, field
from typing import Any

SOURCE_WEIGHTS = {"official": 3, "internal": 2, "external": 1, "unverified": 0, "outdated": -2, "false": -3}

# Sentence boundary: ., ! or ? followed by space and an upper-case letter, digit or opening bracket. Abbreviations
# ("et al.", "Fig.", "e.g.") and decimals are not boundaries.
_ABBREV = r"(?<!\bet al\.)(?<!\bFig\.)(?<!\bEq\.)(?<!\be\.g\.)(?<!\bi\.e\.)(?<!\bvs\.)(?<!\bapprox\.)(?<!\bRef\.)(?<!\bNo\.)"
_SENT_SPLIT = re.compile(_ABBREV + r"(?<=[.!?])\s+(?=[A-Z0-9(\[$\\])")
_WORD = re.compile(r"[a-z][a-z0-9]+|\d+(?:\.\d+)?")
_STOP = frozenset(
    "the a an and or of to in on for with by from at as is are was were be been being this that these those it its "
    "their there which who whom what when where why how than then also into over under between about such can may "
    "might will would should could does do did has have had not no but if so we our you your they them he she his "
    "her one two using used use based study paper results show shows shown".split()
)
_FORUM_HOSTS = ("reddit.com", "quora.com", "stackexchange.com", "stackoverflow.com", "twitter.com", "x.com",
                "facebook.com", "medium.com", "tiktok.com", "youtube.com", "answers.com")
MIN_SENTENCE_CHARS = 25
CONFLICT_OVERLAP = 0.8
PER_PASSAGE_MAX_SENTENCES = 6


def tokens(text: str) -> list[str]:
    return [w for w in _WORD.findall((text or "").lower()) if w not in _STOP]


def split_sentences(text: str) -> list[str]:
    text = re.sub(r"\s+", " ", text or "").strip()
    if not text:
        return []
    return [s.strip() for s in _SENT_SPLIT.split(text) if s.strip()]


# ------------------------------------------------------------------------------------------------- source classes
def passage_class(p: dict[str, Any]) -> str:
    """Lumo source class of one literature passage."""
    if p.get("retracted") or str(p.get("integrity_status") or "").lower() in ("retracted", "withdrawn"):
        return "false"
    from .prompts import (
        LEVEL_JOURNAL,
        LEVEL_PREPRINT,
        LEVEL_REFERENCE,
        LEVEL_REPORT,
        evidence_level,
    )

    level = evidence_level(p)
    if level == LEVEL_REPORT:
        return "official"
    if level in (LEVEL_JOURNAL, LEVEL_REFERENCE):
        return "internal"
    if level == LEVEL_PREPRINT:
        return "external"
    return url_class(p.get("url") or p.get("link") or "")


def url_class(url: str) -> str:
    """Lumo source class of a web page, from its host."""
    from ..utils.source_authority import host_of, source_authority

    host = host_of(url) or ""
    if any(host == h or host.endswith("." + h) for h in _FORUM_HOSTS):
        return "unverified"
    authority = source_authority(url)
    if authority in ("standards", "regulatory"):
        return "official"
    if authority in ("repository", "literature", "academic"):
        return "internal"
    return "external"


# -------------------------------------------------------------------------------------------------- Lumo relation
def _stems(text: str) -> set[str]:
    """Fact signature: 5-letter stems of the words of 4+ letters, numbers removed."""
    text = re.sub(r"\d+(?:[.,]\d+)?", " ", text.lower())
    return {w[:5] for w in re.findall(r"[a-z]+", text) if len(w) >= 4}


def _numbers(text: str) -> list[str]:
    return sorted(x.replace(",", ".") for x in re.findall(r"\d+(?:[.,]\d+)?", text))


def relate(a: str, b: str) -> str:
    """The relation of two sentences: "same" (same words and numbers), "conflict" (same words, different numbers) or "new"."""
    sa, sb = _stems(a), _stems(b)
    if not sa or not sb:
        return "new"
    j = len(sa & sb) / len(sa | sb)
    na, nb = _numbers(a), _numbers(b)
    if j >= 0.7 and na == nb:
        return "same"
    # Scientific text often states different values under different conditions ("100 C at 1 atm", "120 C at 2 atm"),
    # so a conflict needs 80% shared words: the same statement with another number.
    if j >= CONFLICT_OVERLAP and na and nb and na != nb and _same_conditions(na, nb):
        return "conflict"
    return "new"


def _same_conditions(na: list[str], nb: list[str]) -> bool:
    """Whether two statements with different numbers state one quantity differently (a conflict) rather than the
    same relation under different conditions. One number each: a conflict ("450 MPa" vs "520 MPa"). More: a conflict
    only when some numbers are shared (the conditions) and others differ ("100 C at 1 atm" vs "105 C at 1 atm");
    when every number differs ("100 C at 1 atm" vs "120 C at 2 atm") the conditions differ, which is no conflict."""
    if len(na) == 1 and len(nb) == 1:
        return True
    return bool(set(na) & set(nb))


# ------------------------------------------------------------------------------------------------- the gate
@dataclass
class Fact:
    doc: int  # index of the passage in the input list
    source: str  # an independent-source key (identifier or host)
    text: str
    position: int  # sentence position in its passage
    score: float  # BM25 relevance to the question
    cls: str
    K: int = 0


@dataclass
class GateResult:
    texts: dict[int, str]  # passage index -> admitted text (in original sentence order); absent: nothing admitted
    facts: list[Fact] = field(default_factory=list)
    sentences_in: int = 0
    chars_in: int = 0
    chars_out: int = 0
    quarantined: int = 0  # K == 0
    blocked: int = 0  # K <= -1
    irrelevant: int = 0  # not selected by relevance

    @property
    def admitted(self) -> int:
        return sum(1 for f in self.facts if f.K >= 1)

    def summary(self) -> dict[str, Any]:
        return {"sentences_in": self.sentences_in, "admitted": self.admitted, "quarantined": self.quarantined,
                "blocked": self.blocked, "irrelevant": self.irrelevant, "chars_in": self.chars_in,
                "chars_out": self.chars_out,
                "saved_pct": round(100 * (1 - self.chars_out / self.chars_in), 1) if self.chars_in else 0.0}


def _bm25(query: list[str], docs: list[list[str]], k1: float = 1.2, b: float = 0.75) -> list[float]:
    n = len(docs)
    if not n or not query:
        return [0.0] * n
    avg = sum(len(d) for d in docs) / n or 1.0
    df = Counter(t for d in docs for t in set(d))
    q = Counter(query)
    out = []
    for d in docs:
        tf = Counter(d)
        s = 0.0
        for t, qn in q.items():
            if t not in tf:
                continue
            idf = math.log(1 + (n - df[t] + 0.5) / (df[t] + 0.5))
            s += qn * idf * tf[t] * (k1 + 1) / (tf[t] + k1 * (1 - b + b * len(d) / avg))
        out.append(s)
    return out


def _source_key(p: dict[str, Any], i: int) -> str:
    for k in ("doi", "pmid", "arxiv_id", "url", "title"):
        v = p.get(k)
        if v:
            return f"{k}:{str(v).strip().lower()}"
    return f"doc:{i}"


def gate(query: str, passages: list[dict[str, Any]], budget_chars: int, text_key: str = "passage_text",
         classify: Any = None) -> GateResult:
    """Compress `passages` to the sentences relevant to `query` (within budget_chars) and admit only K >= 1."""
    classify = classify or passage_class
    q = tokens(query)
    facts: list[Fact] = []
    sentences_in = chars_in = 0
    raw: list[tuple[int, int, str, str, str]] = []
    for i, p in enumerate(passages):
        text = str(p.get(text_key) or "")
        chars_in += len(text)
        cls = classify(p)
        src = _source_key(p, i)
        for pos, s in enumerate(split_sentences(text)):
            sentences_in += 1
            if len(s) >= MIN_SENTENCE_CHARS:
                raw.append((i, pos, s, cls, src))
    scores = _bm25(q, [tokens(s) for _, _, s, _, _ in raw])
    for (i, pos, s, cls, src), sc in zip(raw, scores, strict=True):
        facts.append(Fact(doc=i, source=src, text=s, position=pos, score=sc, cls=cls))

    # Relevance: the best sentences overall, at most PER_PASSAGE_MAX_SENTENCES per passage, until the budget is spent.
    ranked = sorted((f for f in facts if f.score > 0), key=lambda f: -f.score)
    chosen: list[Fact] = []
    used = 0
    per_doc: Counter[int] = Counter()
    for f in ranked:
        if per_doc[f.doc] >= PER_PASSAGE_MAX_SENTENCES or used + len(f.text) > budget_chars:
            continue
        chosen.append(f)
        per_doc[f.doc] += 1
        used += len(f.text) + 1
    irrelevant = sentences_in - len(chosen)

    # Lumo K: own weight, plus corroboration from other independent sources, minus reliable conflicts.
    for f in chosen:
        f.K = SOURCE_WEIGHTS[f.cls]
    for a_i, a in enumerate(chosen):
        for b in chosen[a_i + 1:]:
            if a.source == b.source:
                continue  # two pages of one source are one source
            rel = relate(a.text, b.text)
            wa, wb = SOURCE_WEIGHTS[a.cls], SOURCE_WEIGHTS[b.cls]
            if rel == "same":
                a.K += wb
                b.K += wa
            elif rel == "conflict":
                if wb > 0:
                    a.K -= wb
                if wa > 0:
                    b.K -= wa

    texts: dict[int, str] = {}
    by_doc: dict[int, list[Fact]] = {}
    for f in chosen:
        if f.K >= 1:
            by_doc.setdefault(f.doc, []).append(f)
    for doc, fs in by_doc.items():
        texts[doc] = " ".join(f.text for f in sorted(fs, key=lambda f: f.position))
    return GateResult(texts=texts, facts=chosen, sentences_in=sentences_in, chars_in=chars_in,
                      chars_out=sum(len(t) for t in texts.values()),
                      quarantined=sum(1 for f in chosen if f.K == 0),
                      blocked=sum(1 for f in chosen if f.K <= -1), irrelevant=irrelevant)


# ------------------------------------------------------------------------------------------------- query guard
# Liar-paradox guard: a self-referential query has no grounding
# context (K = 0), so it is answered without retrieval or a model call.
_LIAR = re.compile(r"\b(?:this (?:statement|sentence) is (?:false|a lie|not true)|will you answer [\"']?no[\"']? to this "
                   r"question|i am lying right now|the next statement is true\W+the previous statement is false)\b",
                   re.I)


def is_self_referential(query: str) -> bool:
    return bool(_LIAR.search(query or ""))


__all__ = ["SOURCE_WEIGHTS", "Fact", "GateResult", "gate", "is_self_referential", "passage_class", "relate",
           "split_sentences", "url_class"]
