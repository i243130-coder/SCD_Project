"""Freshness and coverage stats (GET /stats)."""

from __future__ import annotations

from collections import defaultdict
from datetime import UTC, datetime, timedelta
from typing import Any

from .index import MemoryIndex


def stats(idx: MemoryIndex, now: datetime | None = None) -> dict[str, Any]:
    now = now or datetime.now(UTC)
    by_src: dict[str, list[dict[str, Any]]] = defaultdict(list)
    by_niche: dict[str, dict[str, Any]] = defaultdict(lambda: {"cards": 0, "platforms": set()})
    for c in idx.cards.values():
        by_src[c["source"]].append(c)
        n = c.get("niche") or (c.get("niche_tags") or ["unassigned"])[0]
        by_niche[n]["cards"] += 1
        by_niche[n]["platforms"].add(c["source"])
    sources = {}
    for s, cards in by_src.items():
        fetched = [
            datetime.fromisoformat(str(c["fetched_at"]).replace("Z", "+00:00")) for c in cards if c.get("fetched_at")
        ]
        recent = sum(1 for f in fetched if now - f <= timedelta(days=30))
        sources[s] = {
            "cards": len(cards),
            "newest_fetched_at": max(fetched).isoformat() if fetched else None,
            "pct_last_30d": round(100 * recent / len(cards), 1) if cards else 0.0,
        }
    return {
        "total_cards": len(idx.cards),
        "total_chunks": len(idx.chunks),
        "sources": sources,
        "niches": {n: {"cards": v["cards"], "platforms": sorted(v["platforms"])} for n, v in by_niche.items()},
    }
