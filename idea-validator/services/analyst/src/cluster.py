"""Clustering cards into niches. KMeans (k chosen by silhouette in [k_min, k_max], fixed seed) when scikit-learn
is available; otherwise group by the card's existing niche tag. Names come from c-TF-IDF keywords
(the LLM prompt niche_namer@v1 can rename them; names are cached)."""

from __future__ import annotations

import math
import re
from collections import Counter, defaultdict
from typing import Any

SEED = 42


def ctfidf_keywords(groups: dict[str, list[str]], top: int = 5) -> dict[str, list[str]]:
    tf = {g: Counter(w for t in texts for w in re.findall(r"[a-z]{4,}", t.lower())) for g, texts in groups.items()}
    df: Counter[str] = Counter()
    for c in tf.values():
        df.update(set(c))
    n = len(groups)
    out = {}
    for g, c in tf.items():
        total = sum(c.values()) or 1
        scored = {w: (v / total) * math.log(1 + n / df[w]) for w, v in c.items()}
        out[g] = [w for w, _ in sorted(scored.items(), key=lambda x: (-x[1], x[0]))[:top]]
    return out


def cluster(
    cards: list[dict[str, Any]], vectors: list[list[float]] | None = None, k_min: int = 15, k_max: int = 40
) -> dict[str, str]:
    """Returns card_id -> cluster id."""
    if vectors is not None and len(cards) > k_min * 3:
        try:
            from sklearn.cluster import KMeans
            from sklearn.metrics import silhouette_score

            best, best_s = None, -1.0
            for k in range(k_min, min(k_max, len(cards) - 1) + 1, 5):
                km = KMeans(n_clusters=k, random_state=SEED, n_init=5).fit(vectors)
                s = float(silhouette_score(vectors, km.labels_))
                if s > best_s:
                    best, best_s = km, s
            assert best is not None
            return {c["id"]: f"n{int(lbl)}" for c, lbl in zip(cards, best.labels_, strict=False)}
        except ImportError:
            pass
    return {c["id"]: (c.get("niche") or (c.get("niche_tags") or ["misc"])[0]) for c in cards}


def name_niches(cards: list[dict[str, Any]], assign: dict[str, str]) -> dict[str, dict[str, Any]]:
    groups: dict[str, list[str]] = defaultdict(list)
    for c in cards:
        groups[assign[c["id"]]].append(f"{c['name']} {c.get('summary', '')}")
    kw = ctfidf_keywords(groups)
    return {
        g: {
            "id": g,
            "name": g.replace("-", " ").title() if not g.startswith("n") or "-" in g else " / ".join(kw[g][:2]),
            "keywords": kw[g],
            "size": len(texts),
        }
        for g, texts in groups.items()
    }
