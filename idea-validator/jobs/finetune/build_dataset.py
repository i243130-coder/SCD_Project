"""Sample (idea, evidence, dimension) triples from the KB: real cards as ideas, evidence from KB /search.
>= 300 examples over all six dimensions; evidence sets are thinned/strengthened to reach rare score levels.
Ideas from eval/labelled/ (the tuning set) are EXCLUDED.
    python jobs/finetune/build_dataset.py --snapshot data/snapshot/cards.jsonl.gz --kb http://localhost:8000 --n 360"""

from __future__ import annotations

import argparse
import gzip
import json
import random
from pathlib import Path
from typing import Any

from common import DIMS, ROOT, labelled_ideas, norm, write_jsonl


def build(
    cards: list[dict[str, Any]], search: Any, n: int, seed: int = 13, exclude: set[str] | None = None
) -> list[dict[str, Any]]:
    rng = random.Random(seed)
    exclude = exclude if exclude is not None else labelled_ideas()
    pool = [
        c
        for c in cards
        if norm(f"{c['name']} {c.get('summary', '')}") not in exclude and norm(c.get("summary", "")) not in exclude
    ]
    rng.shuffle(pool)
    out: list[dict[str, Any]] = []
    i = 0
    while len(out) < n and pool:
        c = pool[i % len(pool)]
        dim = DIMS[len(out) % len(DIMS)]
        ev = search(f"{c['name']} {c.get('summary', '')}", 8)
        ev = [e for e in ev if e["card_id"] != c["id"]]
        strength = (len(out) // len(DIMS)) % 4  # 0: none, 1: thin, 2: medium, 3: strong -> covers rare levels
        k = [0, 1, 3, 6][strength]
        out.append(
            {
                "idea_id": c["id"],
                "idea": f"{c['name']}: {c.get('summary', '')}",
                "dimension": dim,
                "evidence": ev[:k],
                "evidence_strength": strength,
            }
        )
        i += 1
    return out


def main() -> None:
    import httpx

    ap = argparse.ArgumentParser()
    ap.add_argument("--snapshot", default=str(ROOT / "data/snapshot/cards.jsonl.gz"))
    ap.add_argument("--kb", default="http://localhost:8000")
    ap.add_argument("--n", type=int, default=360)
    a = ap.parse_args()
    with gzip.open(a.snapshot, "rt") as f:
        cards = [json.loads(line) for line in f if line.strip()]

    def search(q: str, k: int) -> list[dict[str, Any]]:
        return httpx.post(f"{a.kb}/search", json={"query": q, "k": k}, timeout=30).json()["results"]

    rows = build(cards, search, a.n)
    write_jsonl(Path(__file__).parent / "data/raw/candidates.jsonl", rows)
    print(f"{len(rows)} candidates written (unlabelled)")


if __name__ == "__main__":
    main()
