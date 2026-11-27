"""Base vs fine-tuned vs hosted on the HAND-CHECKED test examples -> eval/results/finetune_comparison.json + markdown.
Metrics: MAE vs human, share within 1 point, valid-JSON rate, share of real evidence ids, latency p50/p95, cost/score.
    python compare_models.py --scorer-base http://localhost:9001 --scorer-ft http://localhost:9002 --hosted   (human runs)"""

from __future__ import annotations

import argparse
import json
import statistics
import time
from pathlib import Path
from typing import Any

from common import ROOT, read_jsonl


def metrics(preds: list[dict[str, Any]]) -> dict[str, Any]:
    scored = [p for p in preds if p["valid"] and p["pred"] is not None and p["human"] is not None]
    lat = sorted(p["latency_ms"] for p in preds) or [0]
    return {
        "n": len(preds),
        "mae": round(statistics.mean(abs(p["pred"] - p["human"]) for p in scored), 3) if scored else None,
        "within_1": round(sum(abs(p["pred"] - p["human"]) <= 1 for p in scored) / len(scored), 3) if scored else None,
        "valid_json": round(sum(p["valid"] for p in preds) / len(preds), 3) if preds else None,
        "real_evidence_ids": round(sum(p["ids_real"] for p in preds) / len(preds), 3) if preds else None,
        "latency_p50_ms": lat[len(lat) // 2],
        "latency_p95_ms": lat[int(0.95 * (len(lat) - 1))],
        "cost_per_score_usd": round(statistics.mean(p.get("cost", 0.0) for p in preds), 6) if preds else None,
    }


def run(url: str, examples: list[dict[str, Any]]) -> list[dict[str, Any]]:
    import httpx

    out = []
    for ex in examples:
        user = ex["messages"][1]["content"]
        gold = json.loads(ex["messages"][2]["content"])
        ev_ids = [t.split("]")[0] for t in user.split("[")[1:]]
        req = {
            "rubric": f"{ex['dimension']}@v1",
            "dimension": ex["dimension"],
            "idea": {"text": user.split(" EVIDENCE:")[0][6:]},
            "evidence": [
                {
                    "evidence_id": i,
                    "card_id": i.split("#")[0],
                    "quote": "",
                    "source": "hackernews",
                    "url": "https://x",
                    "retrieved_at": "2026-01-01T00:00:00Z",
                }
                for i in ev_ids
            ],
        }
        t0 = time.perf_counter()
        try:
            r = httpx.post(f"{url}/score", json=req, timeout=120).json()
            valid = True
        except Exception:
            r, valid = {}, False
        out.append(
            {
                "pred": r.get("score"),
                "human": gold["score"],
                "valid": valid,
                "ids_real": set(r.get("evidence_ids", [])) <= set(ev_ids),
                "latency_ms": int((time.perf_counter() - t0) * 1000),
                "fallback": bool(r.get("extra", {}).get("fallback")),
                "example": ex["idea_id"],
            }
        )
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--scorer-base", required=True)
    ap.add_argument("--scorer-ft", required=True)
    ap.add_argument("--scorer-hosted", required=True)
    a = ap.parse_args()
    test = [e for e in read_jsonl(Path(__file__).parent / "data/test.jsonl") if e.get("checked")]
    res = {
        name: metrics(run(url, test))
        for name, url in (("base", a.scorer_base), ("fine_tuned", a.scorer_ft), ("hosted", a.scorer_hosted))
    }
    res["did_not_help_example"] = "TODO(human): pick one example where fine-tuning did not help and explain why"
    out = ROOT / "eval/results/finetune_comparison.json"
    out.write_text(json.dumps(res, indent=2))
    print("| Model | MAE | Within 1 | Valid JSON | Real ids | p50/p95 ms | $/score |\n|---|---|---|---|---|---|---|")
    for k in ("base", "fine_tuned", "hosted"):
        m = res[k]
        print(
            f"| {k} | {m['mae']} | {m['within_1']} | {m['valid_json']} | {m['real_evidence_ids']} | "
            f"{m['latency_p50_ms']}/{m['latency_p95_ms']} | {m['cost_per_score_usd']} |"
        )


if __name__ == "__main__":
    main()
