from __future__ import annotations

from ivcommon.schemas.core import DimensionScore, EvidenceItem, StudentProfile

from .. import features as F
from .base import ScoreFn, score_dim


async def run(
    score_fn: ScoreFn, idea: str, ev: list[EvidenceItem], p: StudentProfile | None, ctx: dict
) -> list[DimensionScore]:
    return [await score_dim(score_fn, "demand_pain", idea, ev, F.demand(ev, ctx.get("trend_slope", 0.0)))]
