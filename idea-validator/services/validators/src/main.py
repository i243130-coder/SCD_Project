"""M9 Validation agents: POST /score/{scorer} for demand | competition | feasibility | risk."""

from __future__ import annotations

from typing import Any

import httpx
from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel

from ivcommon.config import get_settings
from ivcommon.health import health_router
from ivcommon.http import internal_headers
from ivcommon.metrics import metrics_router
from ivcommon.schemas.core import DimensionScore, EvidenceItem, IdeaInput, ScoreRequest, StudentProfile

from .scorers import competition, demand, feasibility, risk

SCORERS = {"demand": demand.run, "competition": competition.run, "feasibility": feasibility.run, "risk": risk.run}
app = FastAPI(title="validators (M9)")
app.include_router(health_router("validators"))
app.include_router(metrics_router())


class ScorerInput(BaseModel):
    idea: IdeaInput
    evidence: list[EvidenceItem]
    profile: StudentProfile | None = None
    context: dict[str, Any] = {}


async def m10_score(req: ScoreRequest, run_id: str | None = None) -> DimensionScore:
    s = get_settings()
    async with httpx.AsyncClient(timeout=60) as c:
        r = await c.post(f"{s.scorer_url}/score", json=req.model_dump(mode="json"), headers=internal_headers(run_id))
        r.raise_for_status()
        return DimensionScore.model_validate(r.json())


@app.post("/score/{scorer}", response_model=list[DimensionScore])
async def score(scorer: str, b: ScorerInput, x_run_id: str | None = Header(default=None)) -> list[DimensionScore]:
    fn = SCORERS.get(scorer)
    if fn is None:
        raise HTTPException(404, f"unknown scorer {scorer}")
    score_fn = getattr(app.state, "score_fn", None) or (lambda r: m10_score(r, x_run_id))
    return await fn(score_fn, b.idea.text, b.evidence, b.profile, b.context)
