from __future__ import annotations

import asyncio

from ivcommon.schemas.core import DimensionScore, EvidenceItem, StudentProfile

from .. import features as F
from .base import ScoreFn, score_dim


async def run(
    score_fn: ScoreFn, idea: str, ev: list[EvidenceItem], p: StudentProfile | None, ctx: dict
) -> list[DimensionScore]:
    assert p is not None, "feasibility needs the student profile"
    feats = F.feasibility(idea, p)
    heur = feats["effort_hours"]
    feas, learn = await asyncio.gather(
        score_dim(score_fn, "feasibility", idea, ev, feats),
        score_dim(score_fn, "learning", idea, ev, F.learning(idea, p)),
    )
    model_est = feas.extra.get("effort_hours")
    # model estimate bounded by the component heuristic (0.5x .. 2x)
    effort = heur if model_est is None else min(2 * heur, max(0.5 * heur, float(model_est)))
    feas = feas.model_copy(update={"extra": {**feas.extra, "effort_hours": effort, "effort_heuristic": heur}})
    return [feas, learn]
