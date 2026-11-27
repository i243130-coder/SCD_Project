"""In-process hybrid index: BM25 keyword index + dense vectors. Chunks always keep their card id (`card_x#cN`).

Backends: this in-memory index is used for tests, the CI retrieval gate and small deployments (loaded from the
card snapshot). The Postgres FTS + Qdrant backends implement the same `Index` methods (see README / PROGRESS).
"""

from __future__ import annotations

import gzip
import hashlib
import json
import math
import re
from collections import Counter
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Any, Protocol

STOP = set(
    "a an the and or of to in on for with is are was were be it this that by as at from not no your you "
    "we our i my can do does how what".split()
)
TOKEN = re.compile(r"[a-z0-9]+")


def tokens(text: str) -> list[str]:
    return [t for t in TOKEN.findall(text.lower()) if t not in STOP and len(t) > 1]


@dataclass
class Chunk:
    chunk_id: str
    card_id: str
    text: str
    source: str
    url: str
    name: str
    niche: str | None = None
    published_at: date | None = None
    fetched_at: datetime | None = None
    toks: list[str] = field(default_factory=list)


class Embedder(Protocol):
    dim: int

    def embed(self, texts: list[str]) -> list[list[float]]: ...


class HashingEmbedder:
    """Dependency-free embedder: hashed unigrams + bigrams, sublinear tf, L2-normalised (dim 384).
    Swap for fastembed `BAAI/bge-small-en-v1.5` with EMBEDDER=fastembed."""

    dim = 384

    def embed(self, texts: list[str]) -> list[list[float]]:
        out = []
        for t in texts:
            v = [0.0] * self.dim
            tk = tokens(t)
            feats = tk + [f"{a}_{b}" for a, b in zip(tk, tk[1:], strict=False)]
            for f, n in Counter(feats).items():
                h = int(hashlib.md5(f.encode()).hexdigest(), 16)
                v[h % self.dim] += (1 if (h >> 9) & 1 else -1) * (1 + math.log(n))
            norm = math.sqrt(sum(x * x for x in v)) or 1.0
            out.append([x / norm for x in v])
        return out


class FastEmbedder:
    dim = 384

    def __init__(self, model: str = "BAAI/bge-small-en-v1.5") -> None:
        from fastembed import TextEmbedding  # optional dependency

        self.m = TextEmbedding(model)

    def embed(self, texts: list[str]) -> list[list[float]]:
        return [list(map(float, v)) for v in self.m.embed(texts)]


def cosine(a: list[float], b: list[float]) -> float:
    return sum(x * y for x, y in zip(a, b, strict=False))


class MemoryIndex:
    def __init__(self, embedder: Embedder | None = None, k1: float = 1.5, b: float = 0.75) -> None:
        self.emb = embedder or HashingEmbedder()
        self.chunks: list[Chunk] = []
        self.vecs: list[list[float]] = []
        self.df: Counter[str] = Counter()
        self.avgdl = 0.0
        self.k1, self.b = k1, b
        self.cards: dict[str, dict[str, Any]] = {}

    def add_cards(self, cards: list[dict[str, Any]]) -> None:
        new: list[Chunk] = []
        for c in cards:
            self.cards[c["id"]] = c
            for i, piece in enumerate(chunk_text(c.get("text") or c.get("summary", ""))):
                header = f"{c['name']}. {c.get('summary', '')}" if i == 0 else c["name"]
                text = f"{header}\n{piece}" if piece not in header else header
                new.append(
                    Chunk(
                        chunk_id=f"{c['id']}#c{i}",
                        card_id=c["id"],
                        text=text,
                        source=c["source"],
                        url=c["url"],
                        name=c["name"],
                        niche=c.get("niche") or (c.get("niche_tags") or [None])[0],
                        published_at=_d(c.get("published_at")),
                        fetched_at=_dt(c.get("fetched_at")),
                        toks=tokens(text),
                    )
                )
        self.vecs += self.emb.embed([ch.text for ch in new])
        self.chunks += new
        for ch in new:
            self.df.update(set(ch.toks))
        self.avgdl = sum(len(ch.toks) for ch in self.chunks) / max(1, len(self.chunks))

    def _ok(self, ch: Chunk, f: dict[str, Any]) -> bool:
        if f.get("source") and ch.source not in f["source"]:
            return False
        if f.get("niche") and ch.niche not in f["niche"]:
            return False
        if f.get("date_from") and (ch.published_at is None or ch.published_at < _d(f["date_from"])):  # type: ignore[operator]
            return False
        if f.get("date_to") and (ch.published_at is None or ch.published_at > _d(f["date_to"])):  # type: ignore[operator]
            return False
        return True

    def keyword(self, query: str, n: int = 50, filters: dict[str, Any] | None = None) -> list[tuple[int, float]]:
        q = tokens(query)
        N = len(self.chunks)
        scores = []
        for idx, ch in enumerate(self.chunks):
            if filters and not self._ok(ch, filters):
                continue
            tf = Counter(ch.toks)
            s = 0.0
            for t in q:
                if t not in tf:
                    continue
                idf = math.log(1 + (N - self.df[t] + 0.5) / (self.df[t] + 0.5))
                s += idf * tf[t] * (self.k1 + 1) / (tf[t] + self.k1 * (1 - self.b + self.b * len(ch.toks) / self.avgdl))
            if s > 0:
                scores.append((idx, s))
        return sorted(scores, key=lambda x: (-x[1], x[0]))[:n]

    def vector(self, query: str, n: int = 50, filters: dict[str, Any] | None = None) -> list[tuple[int, float]]:
        qv = self.emb.embed([query])[0]
        scores = [
            (i, cosine(qv, v)) for i, v in enumerate(self.vecs) if not filters or self._ok(self.chunks[i], filters)
        ]
        return sorted(scores, key=lambda x: (-x[1], x[0]))[:n]


def chunk_text(text: str, size: int = 350, overlap: int = 50) -> list[str]:
    """~300-500 token chunks with 50-token overlap (words used as a token proxy)."""
    words = text.split()
    if len(words) <= size:
        return [text.strip()] if text.strip() else [""]
    out, start = [], 0
    while start < len(words):
        out.append(" ".join(words[start : start + size]))
        if start + size >= len(words):
            break
        start += size - overlap
    return out


def _d(v: Any) -> date | None:
    if v is None or isinstance(v, date):
        return v
    return date.fromisoformat(str(v)[:10])


def _dt(v: Any) -> datetime | None:
    if v is None or isinstance(v, datetime):
        return v
    return datetime.fromisoformat(str(v).replace("Z", "+00:00"))


def load_snapshot(path: str | Path) -> list[dict[str, Any]]:
    p = Path(path)
    opener = gzip.open if p.suffix == ".gz" else open
    with opener(p, "rt", encoding="utf-8") as f:  # type: ignore[operator]
        return [json.loads(line) for line in f if line.strip()]
