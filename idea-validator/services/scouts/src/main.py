"""M4 Scouts: scheduled (CronJob: `python -m src.main --source hn`) and on demand (POST /scout).
Raw items are written as JSONL to RAW_DIR (a PVC) and handed to ingestion (M6i). Cursors are saved per source."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import time
from dataclasses import asdict
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Header
from pydantic import BaseModel, Field

from ivcommon.health import health_router
from ivcommon.metrics import metrics_router

from .sources.base import Source, SourceDown
from .sources.github import GitHub
from .sources.hn import HackerNews
from .sources.producthunt import ProductHunt
from .sources.reddit import Reddit
from .sources.yc import YC

SOURCES: dict[str, type[Source]] = {
    "hn": HackerNews,
    "github": GitHub,
    "producthunt": ProductHunt,
    "yc": YC,
    "reddit": Reddit,
}
RAW_DIR = Path(os.environ.get("RAW_DIR", "/data/raw"))
CURSORS = RAW_DIR / "cursors.json"

app = FastAPI(title="scouts (M4)")
app.include_router(health_router("scouts"))
app.include_router(metrics_router())


def _cursors() -> dict[str, str]:
    return json.loads(CURSORS.read_text()) if CURSORS.exists() else {}


async def run_sources(
    names: list[str], query: str | None = None, max_pages: int = 5, run_id: str | None = None, factory: Any = None
) -> dict[str, Any]:
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    cursors = _cursors()
    report: dict[str, Any] = {}

    async def one(name: str) -> None:
        src: Source = (factory or (lambda n: SOURCES[n](run_id=run_id)))(name)
        try:
            items, cur = await src.fetch_since(None if query else cursors.get(name), query, max_pages)
        except SourceDown as e:  # one source down -> the others still succeed
            report[name] = {"status": "degraded", "items": 0, "error": str(e)}
            return
        path = RAW_DIR / f"{name}-{int(time.time())}.jsonl"
        with path.open("w") as f:
            for it in items:
                f.write(json.dumps(asdict(it)) + "\n")
        if cur and not query:
            cursors[name] = cur
        report[name] = {"status": "ok", "items": len(items), "file": str(path)}

    await asyncio.gather(*(one(n) for n in names))
    CURSORS.write_text(json.dumps(cursors))
    return report


class ScoutRequest(BaseModel):
    source: str = "all"
    query: str | None = Field(default=None, max_length=200)
    max_pages: int = Field(default=3, ge=1, le=10)


@app.post("/scout")
async def scout(b: ScoutRequest, x_run_id: str | None = Header(default=None)) -> dict[str, Any]:
    names = ["hn", "github", "producthunt", "yc"] if b.source == "all" else [b.source]
    return await run_sources(names, b.query, b.max_pages, x_run_id)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--source", required=True, choices=[*SOURCES, "all"])
    ap.add_argument("--max-pages", type=int, default=5)
    a = ap.parse_args()
    print(json.dumps(asyncio.run(run_sources(list(SOURCES) if a.source == "all" else [a.source], None, a.max_pages))))
