"""M6 Knowledge Base: POST /search, GET /cards/{id}, POST /evidence/lookup, GET /stats."""

from __future__ import annotations

import hashlib
import json
import os
import time
from typing import Any

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from ivcommon.cachekeys import cache_key
from ivcommon.health import health_router
from ivcommon.metrics import CACHE_HITS, CACHE_MISSES, LATENCY, metrics_router

from .freshness import stats
from .index import FastEmbedder, MemoryIndex, load_snapshot
from .search import dedupe_cards, search_chunks, to_evidence

app = FastAPI(title="kb (M6)")
SNAPSHOT = os.environ.get("KB_SNAPSHOT", "/data/snapshot/cards.jsonl.gz")


def get_index() -> MemoryIndex:
    idx = getattr(app.state, "index", None)
    if idx is None:
        emb = FastEmbedder() if os.environ.get("EMBEDDER") == "fastembed" else None
        idx = MemoryIndex(emb)
        if os.path.exists(SNAPSHOT):
            idx.add_cards(load_snapshot(SNAPSHOT))
        app.state.index = idx
        app.state.snapshot_id = _snapshot_id()
    return idx  # type: ignore[no-any-return]


def _snapshot_id() -> str:
    if not os.path.exists(SNAPSHOT):
        return "empty"
    st = os.stat(SNAPSHOT)
    return hashlib.sha1(f"{st.st_size}-{st.st_mtime}".encode()).hexdigest()[:10]


async def _ready() -> bool:
    return len(get_index().cards) > 0


app.include_router(health_router("kb", {"index_loaded": _ready}))
app.include_router(metrics_router())


class Filters(BaseModel):
    date_from: str | None = None
    date_to: str | None = None
    source: list[str] = []
    niche: list[str] = []


class SearchRequest(BaseModel):
    query: str = Field(min_length=1, max_length=1000)
    k: int = Field(default=10, ge=1, le=50)
    filters: Filters = Filters()
    mode: str = "hybrid_rerank"
    per_card: bool = True


@app.post("/search")
async def search(req: SearchRequest) -> dict[str, Any]:
    t0 = time.perf_counter()
    idx = get_index()
    redis = getattr(app.state, "redis", None)
    f = req.filters.model_dump(exclude_none=True)
    f = {k: v for k, v in f.items() if v}
    key = cache_key(
        "retrieval",
        query=[req.query, req.k, req.mode],
        filters=f,
        kb_snapshot_id=getattr(app.state, "snapshot_id", "x"),
    )
    if redis is not None:
        hit = await redis.get(key)
        if hit:
            CACHE_HITS.labels("retrieval").inc()
            return {"results": json.loads(hit), "cache_hit": True}
        CACHE_MISSES.labels("retrieval").inc()
    chunks = search_chunks(idx, req.query, k=req.k * 3 if req.per_card else req.k, filters=f, mode=req.mode)  # type: ignore[arg-type]
    if req.per_card:
        chunks = dedupe_cards(chunks, req.k)
    results = [e.model_dump(mode="json") for e in to_evidence(chunks, req.query)]
    if redis is not None:
        await redis.set(key, json.dumps(results), ex=86400)
    LATENCY.labels("kb_search").observe(time.perf_counter() - t0)
    return {"results": results, "cache_hit": False}


@app.get("/cards/{card_id}")
async def card(card_id: str) -> dict[str, Any]:
    c = get_index().cards.get(card_id)
    if c is None:
        raise HTTPException(404, "unknown card")
    return c


class Lookup(BaseModel):
    ids: list[str]


@app.post("/evidence/lookup")
async def lookup(b: Lookup) -> dict[str, Any]:
    by_id = {c.chunk_id: c for c in get_index().chunks}
    found = {i: by_id[i].text[:600] for i in b.ids if i in by_id}
    return {"found": found, "missing": [i for i in b.ids if i not in by_id]}


@app.get("/stats")
async def get_stats() -> dict[str, Any]:
    return stats(get_index())


@app.post("/reload")
async def reload() -> dict[str, Any]:
    app.state.index = None
    return {"cards": len(get_index().cards)}
