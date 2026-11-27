"""Shared scorer flow: features -> M10 /score (rubric + idea + evidence + features) -> verify ids -> abstain."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from ivcommon.schemas.core import DimensionScore, EvidenceItem, ScoreRequest

ScoreFn = Callable[[ScoreRequest], Awaitable[DimensionScore]]


def verify(ds: DimensionScore, retrieved: list[EvidenceItem]) -> DimensionScore:
    allowed = {e.evidence_id for e in retrieved}
    ids = [i for i in ds.evidence_ids if i in allowed]
    if not ids or ds.score is None:
        return ds.model_copy(
            update={
                "score": None,
                "confidence": 0.0,
                "evidence_ids": [],
                "abstained": True,
                "reason": ds.reason or "no valid evidence ids -> abstain",
            }
        )
    return ds.model_copy(update={"evidence_ids": ids})


async def score_dim(
    score_fn: ScoreFn,
    dim: str,
    idea: str,
    ev: list[EvidenceItem],
    feats: dict[str, float],
    extra: dict[str, Any] | None = None,
) -> DimensionScore:
    if not ev:
        return DimensionScore(
            dimension=dim,
            score=None,
            confidence=0.0,
            evidence_ids=[],
            features=feats,  # type: ignore[arg-type]
            reason="no evidence retrieved -> abstain",
            rubric_version=f"{dim}@v1",
            model="none",
            abstained=True,
            extra=extra or {},
        )
    req = ScoreRequest(rubric=f"{dim}@v1", dimension=dim, idea={"text": idea}, evidence=ev, features=feats)  # type: ignore[arg-type]
    ds = verify(await score_fn(req), ev)
    return ds.model_copy(update={"features": feats, "extra": {**ds.extra, **(extra or {})}})
