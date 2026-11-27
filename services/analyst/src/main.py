"""M7 Niche & Trend Analyst: GET /niches, GET /niches/{id}/series, GET /gaps?niche=, POST /recompute."""

from __future__ import annotations

import os
from datetime import UTC, datetime
from typing import Any

from fastapi import FastAPI, HTTPException

from ivcommon.health import health_router
from ivcommon.metrics import metrics_router

from .cluster import cluster, name_niches
from .gaps import find_gaps
from .trends import classify, monthly_series, slope

app = FastAPI(title="analyst (M7)")
app.include_router(health_router("analyst"))
app.include_router(metrics_router())
SNAPSHOT = os.environ.get("KB_SNAPSHOT", "/data/snapshot/cards.jsonl.gz")


def compute(cards: list[dict[str, Any]], end: datetime | None = None) -> dict[str, Any]:
    end_d = (end or datetime.now(UTC)).date()
    assign = cluster(cards)
    meta = name_niches(cards, assign)
    by: dict[str, list[dict[str, Any]]] = {g: [] for g in meta}
    for c in cards:
        by[assign[c["id"]]].append(c)
    sizes = sorted(m["size"] for m in meta.values())
    q75 = sizes[int(0.75 * (len(sizes) - 1))] if sizes else 0
    niches, series, gaps = [], {}, {}
    for g, m in meta.items():
        s = monthly_series(by[g], end_d)
        sl = slope([x["launches"] + x["mentions"] for x in s])
        niches.append({**m, "trend_slope": round(sl, 4), "status": classify(sl, m["size"], q75)})
        series[g] = s
        gaps[g] = find_gaps(by[g], g)
    return {
        "niches": sorted(niches, key=lambda n: -n["size"]),
        "series": series,
        "gaps": gaps,
        "computed_at": datetime.now(UTC).isoformat(),
    }


def state() -> dict[str, Any]:
    st = getattr(app.state, "data", None)
    if st is None:
        cards: list[dict[str, Any]] = []
        if os.path.exists(SNAPSHOT):
            import gzip
            import json

            with gzip.open(SNAPSHOT, "rt") as f:
                cards = [json.loads(line) for line in f if line.strip()]
        st = app.state.data = compute(cards)
    return st  # type: ignore[no-any-return]


@app.get("/niches")
async def niches() -> list[dict[str, Any]]:
    return state()["niches"]  # type: ignore[no-any-return]


@app.get("/niches/{niche_id}/series")
async def niche_series(niche_id: str) -> list[dict[str, Any]]:
    s = state()["series"].get(niche_id)
    if s is None:
        raise HTTPException(404, "unknown niche")
    return s  # type: ignore[no-any-return]


@app.get("/gaps")
async def get_gaps(niche: str | None = None) -> list[dict[str, Any]]:
    g = state()["gaps"]
    return g.get(niche, []) if niche else [x for v in g.values() for x in v]  # type: ignore[no-any-return]


@app.post("/recompute")
async def recompute() -> dict[str, Any]:
    app.state.data = None
    return {"niches": len(state()["niches"])}
