"""Retrieval metrics + the 4-configuration comparison (vector / keyword / hybrid / hybrid+rerank)."""

from __future__ import annotations

import json
import math
import sys
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[2]
KB = ROOT / "services" / "kb"
MODES = ("vector", "keyword", "hybrid", "hybrid_rerank")


def _kb() -> tuple[Any, Any, Any]:
    sys.path.insert(0, str(KB))
    from src.index import MemoryIndex  # type: ignore[import-not-found]
    from src.search import dedupe_cards, search_chunks  # type: ignore[import-not-found]

    return MemoryIndex, search_chunks, dedupe_cards


def recall_at(ranked: list[str], relevant: set[str], k: int) -> float:
    return len(set(ranked[:k]) & relevant) / len(relevant)


def mrr(ranked: list[str], relevant: set[str]) -> float:
    for i, c in enumerate(ranked, 1):
        if c in relevant:
            return 1 / i
    return 0.0


def ndcg_at(ranked: list[str], relevant: set[str], k: int = 10) -> float:
    dcg = sum(1 / math.log2(i + 1) for i, c in enumerate(ranked[:k], 1) if c in relevant)
    idcg = sum(1 / math.log2(i + 1) for i in range(1, min(k, len(relevant)) + 1))
    return dcg / idcg if idcg else 0.0


def evaluate(cards_path: Path, queries_path: Path) -> dict[str, dict[str, float]]:
    MemoryIndex, search_chunks, dedupe_cards = _kb()
    idx = MemoryIndex()
    idx.add_cards([json.loads(line) for line in cards_path.read_text().splitlines() if line.strip()])
    queries = yaml.safe_load(queries_path.read_text())["queries"]
    out = {}
    for mode in MODES:
        agg = {"recall@5": 0.0, "recall@10": 0.0, "mrr": 0.0, "ndcg@10": 0.0}
        for q in queries:
            rel = set(q["relevant"])
            ranked = [
                c.card_id
                for c in dedupe_cards(search_chunks(idx, q["q"], k=30, filters=q.get("filters") or {}, mode=mode), 10)
            ]
            agg["recall@5"] += recall_at(ranked, rel, 5)
            agg["recall@10"] += recall_at(ranked, rel, 10)
            agg["mrr"] += mrr(ranked, rel)
            agg["ndcg@10"] += ndcg_at(ranked, rel, 10)
        out[mode] = {k: round(v / len(queries), 4) for k, v in agg.items()} | {"n_queries": len(queries)}
    return out


def markdown(results: dict[str, dict[str, float]]) -> str:
    rows = ["| Configuration | Recall@5 | Recall@10 | MRR | nDCG@10 |", "|---|---|---|---|---|"]
    for m, r in results.items():
        rows.append(f"| {m} | {r['recall@5']:.3f} | {r['recall@10']:.3f} | {r['mrr']:.3f} | {r['ndcg@10']:.3f} |")
    return "\n".join(rows)


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    cards = Path(args[0]) if args else ROOT / "eval/retrieval/fixtures/cards.jsonl"
    queries = Path(args[1]) if len(args) > 1 else ROOT / "eval/retrieval/queries.yaml"
    res = evaluate(cards, queries)
    print(markdown(res))
    if "--write-baseline" in sys.argv:
        (ROOT / "eval/retrieval/baseline.json").write_text(
            json.dumps(
                {
                    "config": "hybrid_rerank",
                    "fixture": str(cards.relative_to(ROOT)),
                    **res["hybrid_rerank"],
                    "all": res,
                },
                indent=2,
            )
            + "\n"
        )
        print("baseline written")
