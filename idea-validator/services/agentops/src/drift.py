"""Drift report after each ingestion: freshness per source, niche coverage change, verdict-distribution shift."""

from __future__ import annotations

from typing import Any

LABELS = ("GO", "PIVOT", "NO-GO", "INSUFFICIENT_EVIDENCE")
TVD_FLAG = 0.15


def distribution(verdicts: list[str]) -> dict[str, float]:
    n = len(verdicts) or 1
    return {lbl: verdicts.count(lbl) / n for lbl in LABELS}


def tvd(p: dict[str, float], q: dict[str, float]) -> float:
    return 0.5 * sum(abs(p.get(k, 0) - q.get(k, 0)) for k in LABELS)


def report(
    prev_stats: dict[str, Any], cur_stats: dict[str, Any], prev_verdicts: list[str], cur_verdicts: list[str]
) -> dict[str, Any]:
    pn, cn = prev_stats.get("niches", {}), cur_stats.get("niches", {})
    coverage = {
        n: {"before": pn.get(n, {}).get("cards", 0), "after": cn.get(n, {}).get("cards", 0)}
        for n in sorted(set(pn) | set(cn))
    }
    d_prev, d_cur = distribution(prev_verdicts), distribution(cur_verdicts)
    shift = tvd(d_prev, d_cur)
    return {
        "freshness": cur_stats.get("sources", {}),
        "niche_coverage": coverage,
        "verdict_distribution": {"before": d_prev, "after": d_cur, "tvd": round(shift, 4)},
        "flagged": shift > TVD_FLAG,
    }
