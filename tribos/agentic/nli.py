"""
Semantic claim verification with natural-language inference (feature 8).

The deterministic verifier (tribos/verify/verifier.py) grounds claims by identifiers, figures and
term overlap. This module adds an optional semantic second pass, installed as the verifier's
`entailment_judge(claim_text, [{"source_key", "passage"}]) -> {"status", "reason"} | None`. The verifier lets a
judge only downgrade a deterministic verdict (supported -> unsupported/contradicted, or confirm an unsupported
mechanistic claim); identifier and numeric checks stay deterministic, and a judge that returns None abstains.

Techniques
- SciFact (Wadden et al., EMNLP 2020, arXiv:2004.14974): the SUPPORTS / REFUTES / NOINFO label scheme used by
  the model judge, mapped to the verifier's supported / contradicted / unsupported.
- MultiVerS (Wadden et al., Findings NAACL 2022, arXiv:2112.01640): judge a claim against the whole abstract
  rather than pre-selected rationale sentences (the model judge sees full passages).
- FActScore (Min et al., EMNLP 2023, arXiv:2305.14251): the answer is split into atomic sentence-level claims
  and the supported fraction is reported.
- SummaC-ZS (Laban et al., TACL 2022, arXiv:2111.09525) and MiniCheck (Tang et al., EMNLP 2024,
  arXiv:2404.10774): long passages are chunked and a claim's score is the maximum entailment over chunks
  (and over the candidate passages). AlignScore (Zha et al., ACL 2023, arXiv:2305.16739) uses the same
  chunk-and-max alignment idea.

Backends, chosen per run by TRIBOS_NLI = off | auto (default) | model | llm:
1. "cross-encoder": a local HF NLI cross-encoder, TRIBOS_NLI_MODEL (default cross-encoder/nli-deberta-v3-base,
   label order 0=contradiction, 1=entailment, 2=neutral, overridden by the model's config.id2label when that
   names the three labels). Loaded lazily with local_files_only=True and never downloaded; CPU, batched.
   It scores synchronously, so the judge can also compute on the fly inside verify_response.
2. "llm": the agent model with a "[phase:nli]" prompt and SciFact labels. verify_response is synchronous and
   cannot await a model call, so the judge serves from a cache that the after_draft phase "nli_precompute"
   fills: it dry-runs the deterministic verifier on each draft with a recording judge, which yields exactly the
   (claim, passages) pairs the real verification will ask about, and has the model label them in batches.
   Results are cached per (claim, passage sha1); at most TRIBOS_NLI_MAX_LLM_CALLS (default and maximum 12)
   model calls per run, and never past the run budget. A final draft that was not precomputed (the last
   rewrite round, the Reflexion correction) gets no LLM judgment: the judge abstains there.
3. "none": no judge is installed; the verifier keeps its deterministic audit.
auto = the cross-encoder when it is in the local HF cache, else the model judge when the agent model is
available, else none; model = cross-encoder only; llm = model judge only.

Shared state written (consumers must work when these are absent):
- state.bag["entailment_judge"]: the verifier judge (read by the orchestrator after the draft loop).
- state.bag["nli_judge_fn"]: the same synchronous judge, for other phases (counter-evidence F7).
- state.bag["nli_judge_async"]: async variant that may also call the model on a cache miss (within the cap).
- state.bag["nli_score_fn"]: (claim, passages) -> {"entailment","contradiction","neutral","backend",...} | None.
- state.bag["nli_scores"][claim_text]: {"entailment","contradiction","neutral","backend","best_source","label",
  "supporting_sources","contradicting_sources"} for confidence (F9); claim_text is the claim's whitespace-
  collapsed text cut at 240 characters (the verifier's ClaimRecord.claim_text).
- state.bag["nli_backend"]: "cross-encoder" | "llm" | "none".
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import math
import os
import re
import threading
from collections.abc import Callable, Iterable, Sequence
from typing import Any

import numpy as np

from ..sources.keys import make_key, normalize_evidence_key, passage_keys
from ..utils.text import sentence_spans
from .budget import BudgetExhausted
from .config import env_float, env_int
from .guardrails import SPOTLIGHT_RULE, neutralise, spotlight
from .llm import AgentLLMUnavailable
from .runtime import AgentPhase, PhaseOutcome, register_phase
from .state import AgentState

logger = logging.getLogger(__name__)

DEFAULT_MODEL_ID = "cross-encoder/nli-deberta-v3-base"
# Label order of cross-encoder/nli-deberta-v3-base (model card); other NLI models order labels differently.
DEFAULT_LABELS: dict[int, str] = {0: "contradiction", 1: "entailment", 2: "neutral"}
NLI_LABELS = ("contradiction", "entailment", "neutral")

BACKEND_CROSS_ENCODER = "cross-encoder"
BACKEND_LLM = "llm"
BACKEND_NONE = "none"

MAX_LLM_CALLS = 12  # hard ceiling per run, whatever the env says
MAX_PASSAGES_PER_CLAIM = 3
MAX_PRECOMPUTE_CLAIMS = 30
CLAIM_KEY_CHARS = 240  # ClaimRecord.claim_text is cut at 240 characters
PASSAGE_KEY_CHARS = 1500  # the verifier passes d.text[:1500] to the judge
LLM_PASSAGE_CHARS = 1200
LLM_BUDGET_RESERVE = 2  # model calls left for a rewrite round and the confidence phase

Judge = Callable[[str, list[dict[str, str]]], dict[str, Any] | None]
Scores = dict[str, Any]


# Settings ---------------------------------------------------------------------------------------------------
def nli_mode() -> str:
    value = (os.getenv("TRIBOS_NLI", "") or "auto").strip().lower()
    if value == "on":
        return "auto"
    return value if value in ("off", "auto", "model", "llm") else "auto"


def model_id() -> str:
    return (os.getenv("TRIBOS_NLI_MODEL", "") or DEFAULT_MODEL_ID).strip()


def thresholds() -> tuple[float, float, float]:
    """(entailment for supported, contradiction for contradicted, entailment below which a claim is unsupported).
    Between the first and the last the judge abstains. MiniCheck gives no recommended threshold, so these are
    conservative defaults to calibrate (TRIBOS_NLI_ENTAIL / _CONTRADICT / _UNSUPPORTED)."""
    return (
        env_float("TRIBOS_NLI_ENTAIL", 0.5, 0.05, 0.99),
        env_float("TRIBOS_NLI_CONTRADICT", 0.8, 0.3, 0.999),
        env_float("TRIBOS_NLI_UNSUPPORTED", 0.15, 0.0, 0.9),
    )


def llm_call_cap() -> int:
    return env_int("TRIBOS_NLI_MAX_LLM_CALLS", MAX_LLM_CALLS, 0, MAX_LLM_CALLS)


# Text helpers -----------------------------------------------------------------------------------------------
def _norm(text: str) -> str:
    return " ".join(str(text or "").split())


def claim_key(text: str) -> str:
    """The nli_scores key: whitespace-collapsed claim text cut at 240 characters. A lookup key, not display
    text: show claims with verifier.truncate_words (word boundary + ellipsis) instead."""
    return _norm(text)[:CLAIM_KEY_CHARS]


def passage_sha1(text: str) -> str:
    return hashlib.sha1(_norm(str(text or "")[:PASSAGE_KEY_CHARS]).lower().encode("utf-8"), usedforsecurity=False).hexdigest()


def find_scores(nli_scores: dict[str, Scores] | None, text: str) -> Scores | None:
    """nli_scores entry for a claim, matched exactly, then case-insensitively, then by prefix."""
    if not nli_scores or not text:
        return None
    key = claim_key(text)
    if key in nli_scores:
        return nli_scores[key]
    low = key.lower()
    for k, v in nli_scores.items():
        kl = k.lower()
        if kl == low or (len(low) >= 40 and (kl.startswith(low[:200]) or low.startswith(kl[:200]))):
            return v
    return None


def split_sentences(text: str) -> list[str]:
    """Sentences and lines of `text` (utils.text.sentence_spans: abbreviations such as "e.g." do not end one)."""
    text = text or ""
    return [text[s:e].strip() for s, e in sentence_spans(text)]


def chunk_passage(text: str, max_words: int | None = None, overlap: int = 1) -> list[str]:
    """
    Sentence windows of at most max_words words (TRIBOS_NLI_CHUNK_WORDS, default 120), each starting with the
    last `overlap` sentence(s) of the previous window (SummaC-ZS / MiniCheck chunking). A sentence longer than
    the window is split by words.
    """
    limit = max_words or env_int("TRIBOS_NLI_CHUNK_WORDS", 120, 20, 400)
    words_total = len(str(text or "").split())
    if words_total == 0:
        return []
    if words_total <= limit:
        return [_norm(text)]
    units: list[str] = []
    for s in split_sentences(text):
        w = s.split()
        if len(w) <= limit:
            units.append(s)
        else:
            units.extend(" ".join(w[i : i + limit]) for i in range(0, len(w), limit))
    chunks: list[str] = []
    cur: list[str] = []
    cur_words = 0
    for u in units:
        n = len(u.split())
        if cur and cur_words + n > limit:
            chunks.append(" ".join(cur))
            keep = cur[-overlap:] if overlap > 0 else []
            if sum(len(k.split()) for k in keep) + n > limit:
                keep = []
            cur, cur_words = list(keep), sum(len(k.split()) for k in keep)
        cur.append(u)
        cur_words += n
    if cur:
        chunks.append(" ".join(cur))
    return chunks


def label_mapping(id2label: dict[Any, Any] | None) -> dict[int, str]:
    """
    Index -> NLI label. Uses the model config's id2label when it names contradiction, entailment and neutral
    unambiguously; otherwise (missing, or generic LABEL_0 names) the hard-coded order of
    cross-encoder/nli-deberta-v3-base.
    """
    if not id2label:
        return dict(DEFAULT_LABELS)
    found: dict[int, str] = {}
    for k, v in id2label.items():
        try:
            idx = int(k)
        except (TypeError, ValueError):
            return dict(DEFAULT_LABELS)
        name = str(v).lower()
        hit = [lab for lab, cue in (("contradiction", "contra"), ("entailment", "entail"), ("neutral", "neutral")) if cue in name]
        if len(hit) == 1:
            found[idx] = hit[0]
    if sorted(found.values()) == sorted(NLI_LABELS) and len(found) == 3:
        return found
    return dict(DEFAULT_LABELS)


def _softmax(logits: np.ndarray) -> np.ndarray:
    z = np.asarray(logits, dtype=float)
    z = z - z.max(axis=-1, keepdims=True)
    e = np.exp(z)
    return e / e.sum(axis=-1, keepdims=True)


def _scores_label(s: Scores) -> str:
    return max(NLI_LABELS, key=lambda lab: float(s.get(lab, 0.0)))


def status_from_scores(entailment: float, contradiction: float, neutral: float = 0.0) -> str | None:
    """The verifier status for aggregated NLI probabilities, or None (abstain) in the uncertain band."""
    t_entail, t_contra, t_unsup = thresholds()
    if entailment >= t_entail:
        return "supported"
    if contradiction >= t_contra and contradiction > entailment:
        return "contradicted"
    if entailment < t_unsup:
        return "unsupported"
    return None


# Cross-encoder backend --------------------------------------------------------------------------------------
Predictor = Callable[[list[tuple[str, str]]], Any]


class CrossEncoderNLI:
    """A batched (premise, hypothesis) NLI scorer: premise = evidence chunk, hypothesis = claim."""

    def __init__(
        self,
        predict: Predictor,
        id2label: dict[Any, Any] | None = None,
        batch_size: int = 16,
        max_words: int | None = None,
        name: str = DEFAULT_MODEL_ID,
    ) -> None:
        self._predict = predict
        self.labels = label_mapping(id2label)
        self._index = {lab: i for i, lab in self.labels.items()}
        self.batch_size = max(1, batch_size)
        self.max_words = max_words
        self.name = name
        self._lock = threading.Lock()

    def probabilities(self, pairs: list[tuple[str, str]]) -> np.ndarray:
        """(n, 3) softmax probabilities in the model's index order."""
        out: list[np.ndarray] = []
        with self._lock:
            for i in range(0, len(pairs), self.batch_size):
                logits = np.asarray(self._predict(pairs[i : i + self.batch_size]), dtype=float)
                if logits.ndim == 1:
                    logits = logits[None, :]
                out.append(_softmax(logits))
        return np.concatenate(out, axis=0) if out else np.zeros((0, 3))

    def score(self, claim: str, passages: Sequence[str]) -> list[Scores]:
        """Per passage: max entailment and max contradiction over its chunks (neutral of the best chunk)."""
        pairs: list[tuple[str, str]] = []
        owner: list[int] = []
        for pi, passage in enumerate(passages):
            for chunk in chunk_passage(passage, self.max_words) or [""]:
                pairs.append((chunk, claim))
                owner.append(pi)
        probs = self.probabilities(pairs) if pairs else np.zeros((0, 3))
        ie, ic, inn = self._index["entailment"], self._index["contradiction"], self._index["neutral"]
        results: list[Scores] = []
        for pi in range(len(passages)):
            rows = [r for r, o in zip(probs, owner, strict=False) if o == pi]
            if not rows:
                results.append({"entailment": 0.0, "contradiction": 0.0, "neutral": 1.0, "chunks": 0})
                continue
            m = np.vstack(rows)
            best = int(np.argmax(m[:, ie]))
            results.append(
                {
                    "entailment": float(m[best, ie]),
                    "contradiction": float(m[:, ic].max()),
                    "neutral": float(m[best, inn]),
                    "chunks": len(rows),
                }
            )
        return results


_ENCODER_LOCK = threading.Lock()
_ENCODERS: dict[str, CrossEncoderNLI] = {}
_LOAD_ERRORS: dict[str, str] = {}


def reset_cache() -> None:
    """Forget loaded models and load failures (tests, or after installing a model into the HF cache)."""
    with _ENCODER_LOCK:
        _ENCODERS.clear()
        _LOAD_ERRORS.clear()


def _model_available(mid: str) -> bool:
    """True when the model is a local directory or already in the HF cache (no network, no torch import)."""
    if os.path.isdir(mid):
        return os.path.isfile(os.path.join(mid, "config.json"))
    try:
        from huggingface_hub import try_to_load_from_cache

        return isinstance(try_to_load_from_cache(mid, "config.json"), str)
    except Exception:  # noqa: BLE001
        return False


def _load_predictor(mid: str) -> tuple[Predictor, dict[Any, Any]]:
    """Load tokenizer + sequence-classification model from local files only; never downloads. CPU."""
    import torch
    from transformers import AutoModelForSequenceClassification, AutoTokenizer

    tokenizer = AutoTokenizer.from_pretrained(mid, local_files_only=True)
    model = AutoModelForSequenceClassification.from_pretrained(mid, local_files_only=True)
    model.to("cpu")
    model.eval()

    def predict(pairs: list[tuple[str, str]]) -> np.ndarray:
        with torch.no_grad():
            enc = tokenizer(
                [p[0] for p in pairs],
                [p[1] for p in pairs],
                padding=True,
                truncation="only_first",
                max_length=512,
                return_tensors="pt",
            )
            return model(**enc).logits.float().cpu().numpy()

    return predict, dict(getattr(model.config, "id2label", None) or {})


def get_cross_encoder(mid: str | None = None, require_cached: bool = True) -> CrossEncoderNLI | None:
    """The process-wide cross-encoder for this model id, loaded once; None when unavailable (remembered)."""
    mid = mid or model_id()
    with _ENCODER_LOCK:
        if mid in _ENCODERS:
            return _ENCODERS[mid]
        if mid in _LOAD_ERRORS:
            return None
        if require_cached and not _model_available(mid):
            return None  # not remembered: a model installed later is picked up by the next run
        try:
            predict, id2label = _load_predictor(mid)
        except Exception as exc:  # noqa: BLE001
            _LOAD_ERRORS[mid] = f"{type(exc).__name__}: {str(exc)[:200]}"
            logger.info("NLI cross-encoder %s unavailable: %s", mid, _LOAD_ERRORS[mid])
            return None
        enc = CrossEncoderNLI(predict, id2label, batch_size=env_int("TRIBOS_NLI_BATCH", 16, 1, 128), name=mid)
        _ENCODERS[mid] = enc
        return enc


# Per-run cache and judge ------------------------------------------------------------------------------------
class NLIStore:
    """Per-run NLI results: (claim, passage sha1) and (claim, source key) caches plus claim-level scores."""

    def __init__(self, backend: str, encoder: CrossEncoderNLI | None = None) -> None:
        self.backend = backend
        self.encoder = encoder
        self.pairs: dict[tuple[str, str], Scores] = {}
        self.by_source: dict[tuple[str, str], Scores] = {}
        self.claims: dict[str, Scores] = {}  # == state.bag["nli_scores"]
        self.llm_calls = 0
        self.judge_calls = 0
        self._lock = threading.Lock()

    def lookup(self, claim: str, source_key: str, passage: str) -> Scores | None:
        ck = claim_key(claim).lower()
        hit = self.pairs.get((ck, passage_sha1(passage)))
        if hit is None and source_key:
            hit = self.by_source.get((ck, normalize_evidence_key(source_key)))
        return hit

    def record(self, claim: str, source_key: str, passage: str, scores: Scores) -> None:
        t_entail, t_contra, _ = thresholds()
        # One spelling per document ("doi: 10.1/ABC" and "DOI:10.1/abc" are one source), as tribos.sources.keys.
        source_key = normalize_evidence_key(source_key) if source_key else source_key
        key = claim_key(claim)
        ck = key.lower()
        s = {k: float(scores.get(k, 0.0)) for k in NLI_LABELS}
        s["backend"] = self.backend
        s["source_key"] = source_key
        with self._lock:
            self.pairs[(ck, passage_sha1(passage))] = s
            if source_key:
                prev = self.by_source.get((ck, source_key))
                if prev is None or s["entailment"] >= prev["entailment"]:
                    self.by_source[(ck, source_key)] = s
            entry = self.claims.get(key)
            if entry is None:
                entry = {
                    "entailment": 0.0,
                    "contradiction": 0.0,
                    "neutral": 1.0,
                    "backend": self.backend,
                    "best_source": None,
                    "label": "neutral",
                    "supporting_sources": [],
                    "contradicting_sources": [],
                }
                self.claims[key] = entry
            if entry["best_source"] is None or s["entailment"] > entry["entailment"]:
                entry["entailment"], entry["neutral"], entry["best_source"] = s["entailment"], s["neutral"], source_key or None
            entry["contradiction"] = max(entry["contradiction"], s["contradiction"])
            if source_key and s["entailment"] >= t_entail and source_key not in entry["supporting_sources"]:
                entry["supporting_sources"].append(source_key)
            if source_key and s["contradiction"] >= t_contra and source_key not in entry["contradicting_sources"]:
                entry["contradicting_sources"].append(source_key)
            entry["label"] = _scores_label(entry)

    def compute(self, claim: str, passages: Sequence[tuple[str, str]]) -> None:
        """Cross-encoder scores for (source_key, passage) pairs not cached yet (synchronous)."""
        if self.encoder is None:
            return
        todo = [(sk, p) for sk, p in passages if p and self.pairs.get((claim_key(claim).lower(), passage_sha1(p))) is None]
        if not todo:
            return
        try:
            results = self.encoder.score(claim, [p for _, p in todo])
        except Exception as exc:  # noqa: BLE001
            logger.warning("NLI cross-encoder scoring failed: %s", exc)
            return
        for (sk, p), s in zip(todo, results, strict=False):
            self.record(claim, sk, p, s)

    def aggregate(self, claim: str, passages: Sequence[dict[str, str]], compute: bool = True) -> Scores | None:
        """Max entailment / max contradiction over the given passages (scored on the fly by the cross-encoder)."""
        items = [(str(p.get("source_key") or ""), str(p.get("passage") or "")) for p in passages[:MAX_PASSAGES_PER_CLAIM] if p]
        items = [(sk, t) for sk, t in items if t.strip()]
        if not claim or not items:
            return None
        if compute and self.encoder is not None:
            self.compute(claim, items)
        found = [(sk, s) for sk, t in items if (s := self.lookup(claim, sk, t)) is not None]
        if not found:
            return None
        best_sk, best = max(found, key=lambda r: r[1]["entailment"])
        return {
            "entailment": best["entailment"],
            "contradiction": max(s["contradiction"] for _, s in found),
            "neutral": best["neutral"],
            "backend": self.backend,
            "source_key": best_sk,
            "label": _scores_label(best),
        }

    def judge(self, claim: str, passages: list[dict[str, str]]) -> dict[str, Any] | None:
        """The verifier's entailment_judge contract; None to abstain."""
        self.judge_calls += 1
        agg = self.aggregate(claim, passages or [], compute=True)
        if agg is None:
            return None
        status = status_from_scores(agg["entailment"], agg["contradiction"], agg["neutral"])
        if status is None:
            return None
        return {
            "status": status,
            "reason": (
                f"NLI {self.backend} entailment {agg['entailment']:.2f}, contradiction {agg['contradiction']:.2f}"
                f" against {agg['source_key'] or 'the passage'}"
            ),
            "entailment": agg["entailment"],
            "contradiction": agg["contradiction"],
            "neutral": agg["neutral"],
            "backend": self.backend,
        }


def build_judge(backend: str, *, encoder: CrossEncoderNLI | None = None, store: NLIStore | None = None) -> Judge | None:
    """
    A judge with the verifier's exact contract: judge(claim_text, [{"source_key", "passage"}]) ->
    {"status": "supported"|"contradicted"|"unsupported", "reason", ...} or None (abstain). Returns None (no
    judge) for backend "none" or a cross-encoder backend without a model. The "llm" backend judge answers only
    from the store's cache (filled by precompute).
    """
    if backend == BACKEND_NONE or (backend == BACKEND_CROSS_ENCODER and encoder is None and (store is None or store.encoder is None)):
        return None
    st = store or NLIStore(backend, encoder)
    if encoder is not None and st.encoder is None:
        st.encoder = encoder

    def judge(claim_text: str, passages: list[dict[str, str]]) -> dict[str, Any] | None:
        try:
            return st.judge(claim_text, passages)
        except Exception as exc:  # noqa: BLE001 - never break verification
            logger.warning("NLI judge failed: %s", exc)
            return None

    judge.store = st  # type: ignore[attr-defined]
    return judge


# Model judge (SciFact labels) -------------------------------------------------------------------------------
NLI_SYSTEM_PROMPT = (
    "[phase:nli] You verify scientific claims against evidence passages, following the SciFact task "
    "(Wadden et al. 2020). For every item, label each numbered passage: SUPPORTS if the passage entails the "
    "claim, REFUTES if it contradicts the claim, NOINFO if it does neither. Judge only from the passage text, "
    "not from background knowledge; a passage on a related topic that does not state the claim is NOINFO. "
    f"{SPOTLIGHT_RULE} "
    'Reply with JSON only: {"labels": [{"item": 1, "passage": 1, "label": "SUPPORTS|REFUTES|NOINFO", '
    '"confidence": 0.0-1.0}]}'
)

_LABEL_ALIASES = {
    "SUPPORTS": "SUPPORTS", "SUPPORT": "SUPPORTS", "SUPPORTED": "SUPPORTS", "ENTAILMENT": "SUPPORTS",
    "REFUTES": "REFUTES", "REFUTE": "REFUTES", "CONTRADICTS": "REFUTES", "CONTRADICTION": "REFUTES",
    "NOINFO": "NOINFO", "NOT_ENOUGH_INFO": "NOINFO", "NEI": "NOINFO", "NEUTRAL": "NOINFO", "NO_INFO": "NOINFO",
}


def scifact_to_scores(label: str, confidence: float | None = None) -> Scores | None:
    lab = _LABEL_ALIASES.get(str(label or "").strip().upper().replace(" ", "_"))
    if lab is None:
        return None
    try:
        c = float(confidence) if confidence is not None else 0.85
    except (TypeError, ValueError):
        c = 0.85
    c = min(1.0, max(0.0, c)) if math.isfinite(c) else 0.85
    if lab == "SUPPORTS":
        return {"entailment": c, "contradiction": 0.0, "neutral": 1.0 - c}
    if lab == "REFUTES":
        return {"entailment": 0.0, "contradiction": c, "neutral": 1.0 - c}
    return {"entailment": (1.0 - c) / 2, "contradiction": (1.0 - c) / 2, "neutral": c}


def _llm_allowance(state: AgentState, store: NLIStore) -> int:
    b = state.budget
    left_budget = b.max_llm_calls - b.llm_calls - LLM_BUDGET_RESERVE
    return max(0, min(llm_call_cap() - store.llm_calls, left_budget))


async def llm_label(state: AgentState, store: NLIStore, items: list[tuple[str, list[tuple[str, str]]]]) -> int:
    """
    Label (claim, [(source_key, passage)]) items with the model judge, in batches of TRIBOS_NLI_LLM_BATCH
    (default 4) claims per call, and record the results. Returns the number of model calls made.
    """
    batch = env_int("TRIBOS_NLI_LLM_BATCH", 4, 1, 8)
    calls = 0
    for i in range(0, len(items), batch):
        if _llm_allowance(state, store) <= 0 or state.budget.exhausted():
            break
        group = items[i : i + batch]
        blocks: list[str] = []
        for n, (claim, passages) in enumerate(group, 1):
            lines = [f'<item id="{n}">', f"<claim>{neutralise(claim)[:600]}</claim>"]
            for m, (sk, text) in enumerate(passages[:MAX_PASSAGES_PER_CLAIM], 1):
                lines.append(f'<passage n="{m}">{spotlight(text, sk or "evidence", LLM_PASSAGE_CHARS)}</passage>')
            lines.append("</item>")
            blocks.append("\n".join(lines))
        user = "Label every passage of every item.\n\n" + "\n\n".join(blocks)
        store.llm_calls += 1
        calls += 1
        try:
            data = await state.llm.json(NLI_SYSTEM_PROMPT, user, phase="nli", retries=0)
        except (BudgetExhausted, AgentLLMUnavailable) as exc:
            logger.info("NLI model judge stopped: %s", exc)
            break
        except ValueError as exc:
            logger.info("NLI model judge reply unusable: %s", exc)
            continue
        rows = data.get("labels") if isinstance(data, dict) else data if isinstance(data, list) else None
        for row in rows or []:
            if not isinstance(row, dict):
                continue
            try:
                n, m = int(row.get("item", 1)), int(row.get("passage", 1))
            except (TypeError, ValueError):
                continue
            if not (1 <= n <= len(group)):
                continue
            claim, passages = group[n - 1]
            if not (1 <= m <= len(passages[:MAX_PASSAGES_PER_CLAIM])):
                continue
            scores = scifact_to_scores(str(row.get("label") or ""), row.get("confidence"))
            if scores is not None:
                sk, text = passages[m - 1]
                store.record(claim, sk, text, scores)
    return calls


# Evidence documents and candidate passages ------------------------------------------------------------------
_TOKEN_RE = re.compile(r"[a-z0-9][a-z0-9\-]{2,}")
_BM25_STOP = {
    "the", "and", "for", "with", "that", "this", "were", "was", "from", "have", "has", "had", "been", "into", "their",
    "which", "these", "those", "than", "then", "also", "such", "are", "not", "but", "can", "may", "its", "our", "who",
}
# Identifiers a claim cites: arXiv ids (new and old style), DOIs, zbMATH and MR numbers, PMIDs.
_CITED_RE = re.compile(
    r"\barXiv:?\s*((?:\d{4}\.\d{4,5}|[a-z\-]+(?:\.[A-Z]{2})?/\d{7})(?:v\d+)?)"
    r"|\b(10\.\d{4,9}/[-._;()/:A-Za-z0-9]+)"
    r"|\bZbl:?\s*(\d{4}\.\d{5}|\d{7})\b"
    r"|\bMR:?\s*(\d{5,8})\b"
    r"|\bPMID:?\s*(\d{1,9})\b",
    re.IGNORECASE,
)


def cited_keys(text: str) -> set[str]:
    """Canonical keys (tribos.sources.keys) of the identifiers a claim cites."""
    out: set[str] = set()
    for arxiv, doi, zbl, mr, pmid in _CITED_RE.findall(text or ""):
        for prefix, value in (("ARXIV", arxiv), ("DOI", doi.rstrip(".,;)")), ("ZBL", zbl), ("MR", mr), ("PMID", pmid)):
            if value:
                out.add(make_key(prefix, value))
    return out


def _bm25_tokens(text: str) -> list[str]:
    return [w for w in _TOKEN_RE.findall(str(text or "").lower()) if w not in _BM25_STOP]


def collect_documents(tool_results: dict[str, Any]) -> list[dict[str, Any]]:
    """
    Literature passages (and web results) from every successful tool result, keyed by tribos.sources.keys (the
    passage's most specific identifier: 'ARXIV:<id>', 'DOI:<doi>', 'ZBL:<id>', ..., else 'passage:<id>' or
    'tool:<name>'; `keys` lists all of them) with the verifier's document text (lowercased 'title. passage'), plus
    the passage's evidence grade.
    """
    try:
        from ..extensions.hooks import apply_serialization_filters
    except Exception:  # noqa: BLE001
        apply_serialization_filters = None  # type: ignore[assignment]
    docs: list[dict[str, Any]] = []
    for name, res in (tool_results or {}).items():
        if not res or not getattr(res, "success", False):
            continue
        data = getattr(res, "data", None)
        if apply_serialization_filters is not None:
            try:
                data = apply_serialization_filters(name, data)
            except Exception:  # noqa: BLE001
                logger.debug("Serialization filter failed for %s; using the raw data", name, exc_info=True)
        if not isinstance(data, dict):
            continue
        for p in data.get("ranked_passages") or []:
            if not isinstance(p, dict) or not p.get("passage_text"):
                continue
            text = str(p["passage_text"]).lower()
            local = make_key("passage", p["passage_id"]) if p.get("passage_id") else make_key("tool", name)
            keys = passage_keys(p)
            title = str(p.get("title") or "").lower()
            grade = p.get("evidence_grade") if isinstance(p.get("evidence_grade"), dict) else {}
            docs.append(
                {
                    "source_key": keys[0] if keys else local,
                    "keys": keys or [local],  # every identifier of the document, for citation and own-source matches
                    "text": f"{title}. {text}" if title else text,
                    "grade_label": p.get("grade_label") or grade.get("label"),
                    "grade_weight": grade.get("weight"),
                    "tool": name,
                }
            )
        tool_name = str(getattr(res, "tool_name", "") or name)
        if tool_name.startswith("websurfer") and isinstance(data.get("results"), list):
            for r in data["results"][:8]:
                if isinstance(r, dict) and (r.get("snippet") or r.get("content")):
                    docs.append(
                        {
                            "source_key": f"web:{r.get('url') or name}",
                            "keys": [f"web:{r.get('url') or name}"],
                            "text": str(r.get("snippet") or r.get("content") or "")[:2000].lower(),
                            "grade_label": "web",
                            "grade_weight": None,
                            "tool": name,
                        }
                    )
    return docs


def bm25_rank(query: str, docs: Sequence[dict[str, Any]], k: int = MAX_PASSAGES_PER_CLAIM, k1: float = 1.5, b: float = 0.75) -> list[tuple[float, int]]:
    """(score, index) of the top-k documents by Okapi BM25 over their text; only positive scores."""
    q = set(_bm25_tokens(query))
    if not q or not docs:
        return []
    toks = [_bm25_tokens(d.get("text", "")) for d in docs]
    n = len(toks)
    avg = (sum(len(t) for t in toks) / n) or 1.0
    df: dict[str, int] = {}
    for t in toks:
        for w in set(t):
            if w in q:
                df[w] = df.get(w, 0) + 1
    scored: list[tuple[float, int]] = []
    for i, t in enumerate(toks):
        if not t:
            continue
        tf: dict[str, int] = {}
        for w in t:
            if w in q:
                tf[w] = tf.get(w, 0) + 1
        s = 0.0
        for w, f in tf.items():
            idf = math.log(1 + (n - df[w] + 0.5) / (df[w] + 0.5))
            s += idf * f * (k1 + 1) / (f + k1 * (1 - b + b * len(t) / avg))
        if s > 0:
            scored.append((s, i))
    scored.sort(key=lambda r: -r[0])
    return scored[:k]


def candidate_passages(claim: str, docs: Sequence[dict[str, Any]], k: int = MAX_PASSAGES_PER_CLAIM) -> list[tuple[str, str]]:
    """Passages the claim cites first (by any identifier of the document), then the best BM25 matches;
    (source_key, text), at most k."""
    cited = cited_keys(claim)
    out: list[tuple[str, str]] = []
    seen: set = set()
    for d in docs:
        if cited & set(d.get("keys") or [d["source_key"]]) and d["source_key"] not in seen:
            out.append((d["source_key"], d["text"]))
            seen.add(d["source_key"])
    for _, i in bm25_rank(claim, docs, k=k + len(out)):
        sk = docs[i]["source_key"]
        if sk not in seen:
            out.append((sk, docs[i]["text"]))
            seen.add(sk)
    return out[:k]


# Claim extraction (FActScore-style atomic sentences) --------------------------------------------------------
_HEADING_RE = re.compile(r"^\s*(?:#{1,6}\s|\|)")
_BULLET_RE = re.compile(r"^\s*(?:[-*•]|\d+[.)])\s+")


def _verifier():
    from ..verify.verifier import TribosVerifier

    return TribosVerifier


def answer_sentences(text: str, limit: int = MAX_PRECOMPUTE_CLAIMS) -> list[str]:
    """Checkable answer sentences: the verifier's sentence split, minus headings, table rows and short or
    uncertainty-only fragments (FActScore-style sentence-level atomic claims)."""
    try:
        V = _verifier()
        from ..verify.verifier import markdown_claim_units

        text = V._normalize_typography(text or "")
        # Markdown-aware units: no headings or table header rows; a table row with a figure becomes one sentence.
        sentences = [claim for _raw, claim, _from_table in markdown_claim_units(text)]
        assertive = V._assertive_text
    except Exception:  # noqa: BLE001
        sentences, assertive = split_sentences(text or ""), (lambda s: s)
    out: list[str] = []
    for s in sentences:
        if _HEADING_RE.match(s):
            continue
        s = _BULLET_RE.sub("", s).strip().strip("*_ ")
        if len(s.split()) < 6:
            continue
        a = assertive(s)
        if not a or len(a.split()) < 4:
            continue
        if claim_key(a) not in out:
            out.append(claim_key(a))
        if len(out) >= limit:
            break
    return out


def judge_requests(state: AgentState, text: str) -> tuple[list[tuple[str, list[tuple[str, str]]]], Any]:
    """
    Dry-run the deterministic verifier on a draft with a recording judge: the exact (claim, passages) pairs the
    real verification will ask the judge about, plus the deterministic report.
    """
    requests: list[tuple[str, list[tuple[str, str]]]] = []

    def recorder(claim: str, passages: list[dict[str, str]]) -> None:
        requests.append((claim, [(str(p.get("source_key") or ""), str(p.get("passage") or "")) for p in passages]))
        return None

    report = _verifier()().verify_response(
        query=state.query,
        response_markdown=text,
        tool_results=state.tool_results,
        query_context=state.ctx,
        entailment_judge=recorder,
    )
    return requests, report


async def precompute(state: AgentState, text: str | None = None, extra: bool = True) -> dict[str, int]:
    """
    Score a draft's claims into the run's NLI store: first the verifier's own judge requests (dry run), then,
    for confidence, other answer sentences against cited + BM25 candidate passages (cross-encoder only; the
    model judge spends its capped calls on the verifier's requests).
    """
    store: NLIStore | None = state.bag.get("_nli_store")
    text = text if text is not None else state.draft
    stats = {"requests": 0, "scored": 0, "llm_calls": 0}
    if store is None or store.backend == BACKEND_NONE or not (text or "").strip():
        return stats
    requests, _report = await asyncio.to_thread(judge_requests, state, text)
    stats["requests"] = len(requests)
    items: list[tuple[str, list[tuple[str, str]]]] = []
    seen: set = set()
    for claim, passages in requests:
        todo = [(sk, p) for sk, p in passages[:MAX_PASSAGES_PER_CLAIM] if p and store.pairs.get((claim_key(claim).lower(), passage_sha1(p))) is None]
        seen.add(claim_key(claim).lower())
        if todo:
            items.append((claim, todo))
    if extra and store.backend == BACKEND_CROSS_ENCODER:
        docs = collect_documents(state.tool_results)
        if docs:
            for sentence in answer_sentences(text):
                if sentence.lower() in seen or len(items) >= MAX_PRECOMPUTE_CLAIMS:
                    continue
                seen.add(sentence.lower())
                cands = [(sk, p) for sk, p in candidate_passages(sentence, docs) if store.pairs.get((sentence.lower(), passage_sha1(p))) is None]
                if cands:
                    items.append((sentence, cands))
    if not items:
        return stats
    if store.backend == BACKEND_CROSS_ENCODER:

        def run_all() -> None:
            for claim, passages in items:
                store.compute(claim, passages)

        await asyncio.to_thread(run_all)
    else:
        stats["llm_calls"] = await llm_label(state, store, items)
    stats["scored"] = sum(1 for claim, _ in items if claim_key(claim) in store.claims)
    return stats


async def score_texts(state: AgentState, texts: Iterable[str]) -> dict[str, Scores]:
    """nli_scores for these claim texts, computing missing ones with the cross-encoder (the model judge is not
    called here). Returns only the texts that have scores."""
    store: NLIStore | None = state.bag.get("_nli_store")
    out: dict[str, Scores] = {}
    if store is None or store.backend == BACKEND_NONE:
        return out
    texts = [t for t in texts if t and t.strip()]
    missing = [t for t in texts if find_scores(store.claims, t) is None]
    if missing and store.encoder is not None:
        docs = collect_documents(state.tool_results)

        def run_all() -> None:
            for t in missing[:MAX_PRECOMPUTE_CLAIMS]:
                cands = candidate_passages(t, docs)
                if cands:
                    store.compute(t, cands)

        if docs:
            await asyncio.to_thread(run_all)
    for t in texts:
        s = find_scores(store.claims, t)
        if s is not None:
            out[t] = s
    return out


# Installation and phases ------------------------------------------------------------------------------------
def resolve_backend(state: AgentState) -> tuple[str, CrossEncoderNLI | None]:
    mode = nli_mode()
    if mode == "off":
        return BACKEND_NONE, None
    if mode in ("auto", "model"):
        enc = get_cross_encoder(model_id(), require_cached=(mode == "auto"))
        if enc is not None:
            return BACKEND_CROSS_ENCODER, enc
        if mode == "model":
            return BACKEND_NONE, None
    if mode in ("auto", "llm") and llm_call_cap() > 0:
        try:
            if state.llm.available:
                return BACKEND_LLM, None
        except Exception:  # noqa: BLE001
            logger.debug("Could not check LLM availability for the NLI judge", exc_info=True)
    return BACKEND_NONE, None


def install(state: AgentState) -> NLIStore:
    """Create the run's NLI store and publish the judge in state.bag (idempotent)."""
    store: NLIStore | None = state.bag.get("_nli_store")
    if store is not None:
        return store
    backend, encoder = resolve_backend(state)
    store = NLIStore(backend, encoder)
    state.bag["_nli_store"] = store
    state.bag["nli_backend"] = backend
    judge = build_judge(backend, encoder=encoder, store=store)
    if judge is None:
        return store

    def score_fn(claim: str, passages: list[dict[str, str]]) -> Scores | None:
        try:
            return store.aggregate(claim, passages or [], compute=True)
        except Exception as exc:  # noqa: BLE001
            logger.warning("NLI scoring failed: %s", exc)
            return None

    async def judge_async(claim: str, passages: list[dict[str, str]]) -> dict[str, Any] | None:
        items = [(str(p.get("source_key") or ""), str(p.get("passage") or "")) for p in (passages or [])[:MAX_PASSAGES_PER_CLAIM]]
        if store.backend == BACKEND_CROSS_ENCODER:
            await asyncio.to_thread(store.compute, claim, items)
        elif store.backend == BACKEND_LLM:
            todo = [(sk, t) for sk, t in items if t and store.lookup(claim, sk, t) is None]
            if todo:
                await llm_label(state, store, [(claim, todo)])
        return judge(claim, passages)

    state.bag["nli_scores"] = store.claims
    state.bag["nli_judge_fn"] = judge
    state.bag["nli_judge_async"] = judge_async
    state.bag["nli_score_fn"] = score_fn
    state.bag["entailment_judge"] = judge
    return store


class NLISetupPhase(AgentPhase):
    """Installs the judge early in augment so counter-evidence (order 60) can use bag["nli_judge_fn"]."""

    key = "nli_setup"
    stage = "augment"
    order = 5

    def applies(self, state: AgentState) -> bool:
        return nli_mode() != "off"

    async def run(self, state: AgentState) -> PhaseOutcome | None:
        install(state)
        return None


class NLIPhase(AgentPhase):
    """Feature 8: install the semantic entailment judge for the verifier (state.bag["entailment_judge"])."""

    key = "nli"
    stage = "augment"
    order = 90

    def applies(self, state: AgentState) -> bool:
        return nli_mode() != "off"

    async def run(self, state: AgentState) -> PhaseOutcome | None:
        store = install(state)
        if store.backend == BACKEND_NONE:
            await state.step(
                "agent_nli", "Semantic claim check unavailable", "no local NLI model and no agent model; the deterministic audit applies",
                status="done", agent="Verifier",
            )
        else:
            detail = store.encoder.name if store.encoder is not None else f"agent model, at most {llm_call_cap()} calls"
            await state.step("agent_nli", "Semantic claim check ready", f"backend {store.backend} ({detail})", agent="Verifier")
        return None


class NLIPrecomputePhase(AgentPhase):
    """After each draft: score the claims the verifier will ask about (fills the model judge's cache)."""

    key = "nli_precompute"
    stage = "after_draft"
    order = 90

    def applies(self, state: AgentState) -> bool:
        store = state.bag.get("_nli_store")
        return store is not None and store.backend != BACKEND_NONE and bool((state.draft or "").strip())

    async def run(self, state: AgentState) -> PhaseOutcome | None:
        # Only the verifier's own requests: the confidence phase scores the final answer's other sentences once.
        stats = await precompute(state, extra=False)
        store: NLIStore = state.bag["_nli_store"]
        if stats["requests"] or stats["scored"]:
            supported = sum(1 for s in store.claims.values() if s.get("supporting_sources"))
            await state.step(
                "agent_nli_precompute",
                f"Semantic check of {len(store.claims)} claim(s)",
                f"backend {store.backend}; {supported} entailed by a passage; {store.llm_calls} model call(s)",
                agent="Verifier",
            )
        return None  # never asks for a rewrite


register_phase(NLISetupPhase())
register_phase(NLIPhase())
register_phase(NLIPrecomputePhase())


__all__ = [
    "BACKEND_CROSS_ENCODER",
    "BACKEND_LLM",
    "BACKEND_NONE",
    "CrossEncoderNLI",
    "DEFAULT_LABELS",
    "DEFAULT_MODEL_ID",
    "NLIStore",
    "build_judge",
    "candidate_passages",
    "chunk_passage",
    "claim_key",
    "collect_documents",
    "find_scores",
    "get_cross_encoder",
    "install",
    "judge_requests",
    "label_mapping",
    "precompute",
    "reset_cache",
    "scifact_to_scores",
    "score_texts",
    "status_from_scores",
]
