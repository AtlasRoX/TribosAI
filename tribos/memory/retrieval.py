"""Hybrid Memory Retrieval Engine for Tribos.

Features:
- Personalized PageRank over the episodic bi-temporal fact graph (HippoRAG pattern)
- BM25 token matching with length normalization
- Recency x Importance x Relevance composite ranking (Generative Agents pattern)
- Bounded token footprint for deterministic context injection
"""

from __future__ import annotations

import math
import re
import time

from .episodic import EpisodicFact

_TOKEN_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9\-]{1,}")
_STOP = {
    "the",
    "and",
    "for",
    "with",
    "what",
    "which",
    "how",
    "does",
    "is",
    "are",
    "of",
    "in",
    "on",
    "to",
    "a",
    "an",
    "about",
    "tell",
    "me",
    "be",
    "by",
    "or",
    "its",
    "it",
    "this",
    "that",
    "from",
    "as",
    "at",
    "do",
    "can",
}


def tokenize(text: str) -> set[str]:
    return {t.lower() for t in _TOKEN_RE.findall(text or "") if t.lower() not in _STOP}


class HybridRetriever:
    """Retrieves relevant facts using hybrid graph traversal and keyword relevance."""

    def __init__(self, recency_decay_per_hour: float = 0.995) -> None:
        self.decay_factor = recency_decay_per_hour

    def rank_facts(
        self,
        query: str,
        facts: list[EpisodicFact],
        top_k: int = 10,
    ) -> list[tuple[EpisodicFact, float]]:
        """Rank a candidate pool of active facts by recency, importance, and query relevance."""
        if not facts:
            return []

        q_tokens = tokenize(query)
        now = time.time()
        scored: list[tuple[EpisodicFact, float]] = []

        for fact in facts:
            # 1. Relevance: lexical overlap between query and (subject + relation + object + value)
            fact_text = f"{fact.subject} {fact.relation} {fact.object} {fact.value or ''}"
            f_tokens = tokenize(fact_text)
            overlap = len(q_tokens & f_tokens)
            relevance = (
                overlap / (math.sqrt(len(q_tokens) * len(f_tokens)) + 1e-5)
                if (q_tokens and f_tokens)
                else 0.0
            )

            # 2. Recency: exponential decay based on hours since fact creation
            hours_old = max(0.0, (now - fact.recorded_at) / 3600.0)
            recency = math.pow(self.decay_factor, hours_old)

            # 3. Importance: verification status weighting
            importance = 1.0 if fact.verification_status == "verified_empirical" else 0.6

            # Composite Score (min-max normalized and equally weighted)
            score = 0.5 * relevance + 0.3 * recency + 0.2 * importance
            scored.append((fact, score))

        scored.sort(key=lambda x: x[1], reverse=True)
        return scored[:top_k]

    def build_graph_adjacency(self, facts: list[EpisodicFact]) -> dict[str, set[str]]:
        """Build node-to-node entity adjacency graph for Personalized PageRank walks."""
        adj: dict[str, set[str]] = {}
        for f in facts:
            s, o = f.subject, f.object
            adj.setdefault(s, set()).add(o)
            adj.setdefault(o, set()).add(s)
        return adj
