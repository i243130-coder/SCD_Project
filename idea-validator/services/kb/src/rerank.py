"""Rerankers. Default: a dependency-free lexical cross-scorer (query-term coverage + phrase/bigram + name match).
Set RERANKER=crossencoder to use fastembed's `Xenova/ms-marco-MiniLM-L-6-v2` cross-encoder."""

from __future__ import annotations

import math
from typing import Protocol

from .index import Chunk, tokens


class Reranker(Protocol):
    def score(self, query: str, chunks: list[Chunk]) -> list[float]: ...


class LexicalReranker:
    def score(self, query: str, chunks: list[Chunk]) -> list[float]:
        q = tokens(query)
        qs, qb = set(q), {f"{a} {b}" for a, b in zip(q, q[1:], strict=False)}
        out = []
        for ch in chunks:
            ct = set(ch.toks)
            cb = {f"{a} {b}" for a, b in zip(ch.toks, ch.toks[1:], strict=False)}
            name = set(tokens(ch.name))
            coverage = len(qs & ct) / max(1, len(qs))
            bigram = len(qb & cb) / max(1, len(qb)) if qb else 0.0
            name_hit = len(qs & name) / max(1, len(name)) if name else 0.0
            out.append(coverage + 0.5 * bigram + 0.7 * name_hit - 0.02 * math.log(1 + len(ch.toks)))
        return out


class CrossEncoderReranker:
    def __init__(self, model: str = "Xenova/ms-marco-MiniLM-L-6-v2") -> None:
        from fastembed.rerank.cross_encoder import TextCrossEncoder  # optional dependency

        self.m = TextCrossEncoder(model_name=model)

    def score(self, query: str, chunks: list[Chunk]) -> list[float]:
        return [float(s) for s in self.m.rerank(query, [c.text for c in chunks])]
