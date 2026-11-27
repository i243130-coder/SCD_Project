from __future__ import annotations

import asyncio

from ivcommon.schemas.core import DimensionScore, EvidenceItem, StudentProfile

from .. import features as F
from .base import ScoreFn, score_dim


async def run(
    score_fn: ScoreFn, idea: str, ev: list[EvidenceItem], p: StudentProfile | None, ctx: dict
) -> list[DimensionScore]:
    feats, dup = F.competition(idea, ev, ctx.get("niche_saturation", 0.0))
    comp, diff = await asyncio.gather(
        score_dim(score_fn, "competition", idea, ev, feats, {"duplicate_of": dup}),
        score_dim(score_fn, "differentiation", idea, ev, feats),
    )
    return [comp, diff]
