from __future__ import annotations

from ivcommon.schemas.core import DimensionScore, EvidenceItem, StudentProfile

from .. import features as F
from .base import ScoreFn, score_dim


async def run(
    score_fn: ScoreFn, idea: str, ev: list[EvidenceItem], p: StudentProfile | None, ctx: dict
) -> list[DimensionScore]:
    feats, flags = F.risk(idea)
    blockers = [f for f in flags if f in F.BLOCKERS]
    ds = await score_dim(
        score_fn, "risk", idea, ev, feats, {"flags": flags, "blocker": blockers[0] if blockers else None}
    )
    return [ds]
