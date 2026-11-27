"""Value-of-information for clarifying questions (U5): ask only questions that change the verdict."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from ivcommon.schemas.core import DIMENSIONS, StudentProfile

QUESTIONS = {
    "scope": "How big is the first version? (e.g. 'one core feature, web only' vs 'full platform')",
    "customer": "Who exactly is the first customer? (a narrow segment, or everyone?)",
    "platform": "Web, mobile, or both?",
    "core_features": "What are the 2-3 core features of the first version?",
}

# optimistic vs pessimistic assumptions for each missing field
ASSUMPTIONS: dict[str, tuple[dict[str, Any], dict[str, Any]]] = {
    "scope": ({"effort_hours": 80}, {"effort_hours": 400}),
    "core_features": ({"effort_hours": 100}, {"effort_hours": 300}),
    "platform": ({"effort_hours": 120}, {"effort_hours": 260}),
    "customer": ({"competition": 3.5, "differentiation": 3.5}, {"competition": 2.0, "differentiation": 2.0}),
}

PRIOR_SCORE = 3.4
PRIOR_CONF = 0.7


def prior_request(profile: StudentProfile, assumption: dict[str, Any]) -> dict[str, Any]:
    scores = []
    for d in DIMENSIONS:
        extra: dict[str, Any] = {}
        if d == "feasibility":
            extra["effort_hours"] = assumption.get("effort_hours", 120)
        scores.append(
            {
                "dimension": d,
                "score": assumption.get(d, PRIOR_SCORE),
                "confidence": PRIOR_CONF,
                "evidence_ids": ["prior#c0"],
                "reason": "prior for value-of-information",
                "rubric_version": f"{d}@v1",
                "model": "rule",
                "extra": extra,
            }
        )
    return {
        "scores": scores,
        "profile": profile.model_dump(),
        "n_sources": 5,
        "n_platforms": 2,
        "include_what_if": False,
    }


async def questions_that_matter(
    fields: dict[str, Any], profile: StudentProfile, whatif: Callable[[dict[str, Any]], Awaitable[Any]], max_q: int = 3
) -> list[dict[str, str]]:
    out: list[dict[str, str]] = []
    for field_name in ("scope", "customer", "platform", "core_features"):
        if fields.get(field_name):
            continue
        opt, pes = ASSUMPTIONS[field_name]
        v_opt = await whatif(prior_request(profile, opt))
        v_pes = await whatif(prior_request(profile, pes))
        if v_opt.verdict != v_pes.verdict:
            out.append(
                {
                    "id": f"q_{field_name}",
                    "field": field_name,
                    "question": QUESTIONS[field_name],
                    "why": f"answer changes the verdict ({v_opt.verdict} vs {v_pes.verdict})",
                }
            )
        if len(out) >= max_q:
            break
    return out
