"""Hybrid search: keyword (BM25) top 50 + vector top 50 -> Reciprocal Rank Fusion (k=60) -> rerank top 30 -> k."""

from __future__ import annotations

import re
from datetime import UTC, datetime
from typing import Any, Literal

from ivcommon.schemas.core import EvidenceItem

from .index import Chunk, MemoryIndex, tokens
from .rerank import LexicalReranker, Reranker

Mode = Literal["keyword", "vector", "hybrid", "hybrid_rerank"]
RRF_K = 60


def rrf(*rankings: list[int], k: int = RRF_K) -> list[tuple[int, float]]:
    scores: dict[int, float] = {}
    for ranking in rankings:
        for rank, idx in enumerate(ranking):
            scores[idx] = scores.get(idx, 0.0) + 1.0 / (k + rank + 1)
    return sorted(scores.items(), key=lambda x: (-x[1], x[0]))


def best_quote(text: str, query: str, limit: int = 300) -> str:
    sents = [s.strip() for s in re.split(r"(?<=[.!?])\s+|\n", text) if s.strip()]
    if not sents:
        return text[:limit]
    q = set(tokens(query))
    best = max(sents, key=lambda s: (len(q & set(tokens(s))), -len(s)))
    return best[:limit]


def search_chunks(
    idx: MemoryIndex,
    query: str,
    k: int = 10,
    filters: dict[str, Any] | None = None,
    mode: Mode = "hybrid_rerank",
    reranker: Reranker | None = None,
) -> list[Chunk]:
    kw = [i for i, _ in idx.keyword(query, 50, filters)]
    vec = [i for i, _ in idx.vector(query, 50, filters)]
    if mode == "keyword":
        order = kw
    elif mode == "vector":
        order = vec
    else:
        order = [i for i, _ in rrf(kw, vec)]
        if mode == "hybrid_rerank":
            top = order[:30]
            scores = (reranker or LexicalReranker()).score(query, [idx.chunks[i] for i in top])
            rrf_pos = {i: p for p, i in enumerate(top)}
            order = [i for i, _ in sorted(zip(top, scores, strict=False), key=lambda x: (-x[1], rrf_pos[x[0]]))]
    return [idx.chunks[i] for i in order[:k]]


def dedupe_cards(chunks: list[Chunk], k: int) -> list[Chunk]:
    seen, out = set(), []
    for c in chunks:
        if c.card_id in seen:
            continue
        seen.add(c.card_id)
        out.append(c)
        if len(out) >= k:
            break
    return out


def to_evidence(chunks: list[Chunk], query: str) -> list[EvidenceItem]:
    now = datetime.now(UTC)
    return [
        EvidenceItem(
            evidence_id=c.chunk_id,
            card_id=c.card_id,
            quote=best_quote(c.text, query),
            source=c.source,
            url=c.url,
            retrieved_at=now,
            published_at=c.published_at,
        )  # type: ignore[arg-type]
        for c in chunks
    ]
