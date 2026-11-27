"""Computed features (plain code) for the four scorers (§8 M9)."""

from __future__ import annotations

import math
import re
from collections import Counter
from datetime import UTC, date, datetime

from ivcommon.schemas.core import EvidenceItem, StudentProfile

COMPLAINT = re.compile(
    r"\b(is there a tool|i wish|frustrat\w*|annoy\w*|painful|struggl\w*|tired of|hate|"
    r"no good way|feature request|why can't|complain\w*)\b",
    re.I,
)
COMPONENTS = {  # effort heuristic: base 40h + per component
    "auth": (r"\b(login|account|auth|sign ?up)\b", 20),
    "ui": (r"\b(app|dashboard|web|page|ui|interface)\b", 40),
    "ml": (r"\b(ml|ai|model|predict\w*|recommend\w*|classif\w*|llm|fine-tun\w*)\b", 80),
    "scraping": (r"\b(scrap\w*|crawl\w*|aggregat\w*)\b", 30),
    "payments": (r"\b(payment|checkout|billing|subscription)\b", 30),
    "mobile": (r"\b(mobile|android|ios|phone app)\b", 60),
    "realtime": (r"\b(real-?time|chat|live|notification)\b", 25),
    "integrations": (r"\b(api|integrat\w*|whatsapp|slack|calendar|sms)\b", 25),
}
SKILL_HINTS = {
    "ml": ["python", "ml", "pytorch"],
    "ui": ["react", "javascript", "html"],
    "mobile": ["flutter", "kotlin", "swift"],
    "auth": ["backend"],
    "payments": ["backend"],
    "scraping": ["python"],
    "realtime": ["websockets", "backend"],
    "integrations": ["backend", "api"],
}
RISK = {
    "medical_advice": r"\b(diagnos\w*|dosage|medical advice|prescri\w*|treatment plan)\b",
    "finance_trading": r"\b(trading signals?|investment advice|crypto trading|stock tips|forex)\b",
    "minors": r"\b(children|kids|minors|under 13|teenagers)\b",
    "private_data_scraping": r"\b(scrap\w* (private|personal)|private profiles|personal data of others)\b",
    "single_platform_tos": r"\b(instagram|tiktok|whatsapp|twitter|x\.com) (bot|automation|scraper)\b",
    "legal_licensing": r"\b(copyrighted|pirat\w*|torrent|unlicensed)\b",
}
BLOCKERS = {"medical_advice", "private_data_scraping", "legal_licensing"}
LAUNCHED = {"producthunt", "yc", "github"}


def toks(t: str) -> Counter[str]:
    return Counter(w for w in re.findall(r"[a-z0-9]+", t.lower()) if len(w) > 2)


def sim(a: str, b: str) -> float:
    ta, tb = toks(a), toks(b)
    if not ta or not tb:
        return 0.0
    return sum(ta[w] * tb[w] for w in ta) / (
        math.sqrt(sum(v * v for v in ta.values())) * math.sqrt(sum(v * v for v in tb.values()))
    )


def demand(ev: list[EvidenceItem], trend_slope: float = 0.0, today: date | None = None) -> dict[str, float]:
    today = today or datetime.now(UTC).date()
    dates = [e.published_at for e in ev if e.published_at]
    return {
        "n_sources": float(len({e.card_id for e in ev})),
        "n_platforms": float(len({e.source for e in ev})),
        "complaint_count": float(sum(1 for e in ev if COMPLAINT.search(e.quote))),
        "trend_growth": trend_slope,
        "recency_days": float((today - max(dates)).days) if dates else 9999.0,
    }


def competition(idea: str, ev: list[EvidenceItem], saturation: float = 0.0) -> tuple[dict[str, float], str | None]:
    products = [e for e in ev if e.source in LAUNCHED and not COMPLAINT.search(e.quote)]
    sims = [(sim(idea, e.quote), e) for e in products]
    direct = [e for s, e in sims if s > 0.35]
    best = max(sims, key=lambda x: x[0], default=(0.0, None))
    duplicate = best[1].quote[:80] if best[0] > 0.85 and best[1] is not None else None
    return (
        {
            "n_direct_competitors": float(len(direct)),
            "funded_competitors": float(sum(1 for e in direct if e.source == "yc")),
            "niche_saturation": saturation,
            "max_similarity_to_existing": round(best[0], 4),
            "unaddressed_gap_count": float(sum(1 for e in ev if COMPLAINT.search(e.quote))),
        },
        duplicate,
    )


def effort_hours(idea: str) -> tuple[float, list[str]]:
    comps = [c for c, (rx, _) in COMPONENTS.items() if re.search(rx, idea, re.I)]
    return 40.0 + sum(COMPONENTS[c][1] for c in comps), comps


def feasibility(idea: str, p: StudentProfile) -> dict[str, float]:
    hours, comps = effort_hours(idea)
    req = {s for c in comps for s in SKILL_HINTS.get(c, [])}
    have = {s.lower() for s in p.skills}
    overlap = len(req & have) / len(req | have) if req else 1.0
    compute_need = (
        2.0 if "ml" in comps and re.search(r"\b(train|fine-tun\w*)\b", idea, re.I) else 1.0 if "ml" in comps else 0.0
    )
    compute_have = {"laptop": 0.0, "free_gpu": 1.5, "paid": 3.0}[p.compute]
    return {
        "available_hours": p.available_hours,
        "effort_hours": hours,
        "skill_overlap": round(overlap, 4),
        "compute_need": compute_need,
        "compute_gap": max(0.0, compute_need - compute_have),
        "n_components": float(len(comps)),
    }


def risk(idea: str) -> tuple[dict[str, float], list[str]]:
    flags = [k for k, rx in RISK.items() if re.search(rx, idea, re.I)]
    return {"risk_flags": float(len(flags))}, flags


def learning(idea: str, p: StudentProfile) -> dict[str, float]:
    _, comps = effort_hours(idea)
    wanted = {i.lower() for i in p.interests} | ({"ml"} if p.goal == "portfolio" else set())
    words = set(toks(idea)) | set(comps)
    overlap = len(wanted & words) / len(wanted) if wanted else 0.3
    novelty = min(1.0, len({c for c in comps if c in ("ml", "realtime", "mobile")}) / 2)
    return {"interest_overlap": round(overlap, 4), "novelty": novelty}
