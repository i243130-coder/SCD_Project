"""Monthly series + trend slope + rising / flat / saturated (thresholds from config)."""

from __future__ import annotations

from collections import Counter
from datetime import date
from typing import Any

RISING_SLOPE = 0.05
FLAT_BAND = 0.05


def month(d: date) -> str:
    return f"{d.year:04d}-{d.month:02d}"


def last_months(end: date, n: int = 12) -> list[str]:
    out, y, m = [], end.year, end.month
    for _ in range(n):
        out.append(f"{y:04d}-{m:02d}")
        m -= 1
        if m == 0:
            y, m = y - 1, 12
    return out[::-1]


def monthly_series(cards: list[dict[str, Any]], end: date, n: int = 12) -> list[dict[str, Any]]:
    launches: Counter[str] = Counter()
    mentions: Counter[str] = Counter()
    for c in cards:
        if not c.get("published_at"):
            continue
        k = str(c["published_at"])[:7]
        (mentions if c["source"] in ("hackernews", "reddit") else launches)[k] += 1
    return [{"month": m, "launches": launches[m], "mentions": mentions[m]} for m in last_months(end, n)]


def slope(values: list[float]) -> float:
    """Least-squares slope per month, normalised by the mean (0 if the mean is 0)."""
    n = len(values)
    if n < 2:
        return 0.0
    mean_y = sum(values) / n
    if mean_y == 0:
        return 0.0
    mean_x = (n - 1) / 2
    num = sum((i - mean_x) * (v - mean_y) for i, v in enumerate(values))
    den = sum((i - mean_x) ** 2 for i in range(n))
    return (num / den) / mean_y


def classify(s: float, size: int, size_q75: float) -> str:
    if size >= size_q75 and s <= FLAT_BAND:
        return "saturated"
    if s > RISING_SLOPE:
        return "rising"
    return "flat"
