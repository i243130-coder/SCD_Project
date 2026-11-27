"""Gaps = complaint / request items per niche that few launched products address."""

from __future__ import annotations

import hashlib
import re
from typing import Any

REQUEST = re.compile(
    r"\b(is there a (tool|app|way)|i wish|frustrat\w*|tired of|no good way|feature request|"
    r"why (isn't|can't)|struggl\w* (with|to)|annoy\w*)\b",
    re.I,
)


def _toks(t: str) -> set[str]:
    return {w for w in re.findall(r"[a-z0-9]+", t.lower()) if len(w) > 3}


def find_gaps(cards: list[dict[str, Any]], niche_id: str, max_cover: float = 0.35) -> list[dict[str, Any]]:
    complaints = [c for c in cards if REQUEST.search(c.get("text", "") + " " + c.get("name", ""))]
    launched = [c for c in cards if c["source"] in ("producthunt", "yc", "github") and c not in complaints]
    gaps = []
    for c in complaints:
        t = _toks(c.get("text", ""))
        cover = max((len(t & _toks(p.get("text", ""))) / max(1, len(t)) for p in launched), default=0.0)
        if cover <= max_cover:
            gid = "gap_" + hashlib.sha1(c["id"].encode()).hexdigest()[:8]
            gaps.append(
                {
                    "id": gid,
                    "niche_id": niche_id,
                    "description": c.get("summary") or c["name"],
                    "evidence_ids": [f"{c['id']}#c0"],
                    "coverage": round(cover, 3),
                }
            )
    return gaps
