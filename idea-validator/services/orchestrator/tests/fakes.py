"""Fake agents for orchestrator tests. The verdict engine is the REAL M11 code, loaded by file path."""

from __future__ import annotations

import asyncio
import importlib.util
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from ivcommon.schemas.core import (
    DimensionScore,
    EvidenceItem,
    Objection,
    StudentProfile,
    Verdict,
    VerdictRequest,
    WhatIfRequest,
)

VERDICT_SRC = Path(__file__).resolve().parents[2] / "verdict" / "src"


def _load_engine() -> Any:
    name = "m11_engine_pkg"
    if name not in sys.modules:
        spec = importlib.util.spec_from_file_location(
            name, VERDICT_SRC / "__init__.py", submodule_search_locations=[str(VERDICT_SRC)]
        )
        assert spec and spec.loader
        mod = importlib.util.module_from_spec(spec)
        sys.modules[name] = mod
        spec.loader.exec_module(mod)
    eng = importlib.import_module(f"{name}.engine")
    cfg = importlib.import_module(f"{name}.config").load_config()
    return eng, cfg


ENGINE, CFG = _load_engine()
SOURCES = ["hackernews", "github", "producthunt"]


def ev(i: int, source: str | None = None) -> EvidenceItem:
    return EvidenceItem(
        evidence_id=f"card_{i:04d}#c0",
        card_id=f"card_{i:04d}",
        quote=f"evidence {i}",
        source=source or SOURCES[i % 3],
        url=f"https://example.org/{i}",  # type: ignore[arg-type]
        retrieved_at=datetime.now(UTC),
    )


DEFAULT_SCORES = {
    "demand_pain": 4.0,
    "competition": 3.5,
    "differentiation": 3.5,
    "feasibility": 4.0,
    "risk": 4.0,
    "learning": 4.0,
}
DIMS = {
    "demand": ["demand_pain"],
    "competition": ["competition", "differentiation"],
    "feasibility": ["feasibility", "learning"],
    "risk": ["risk"],
}


class FakeAgents:
    def __init__(
        self,
        *,
        profile: StudentProfile | None = None,
        n_evidence: int = 6,
        rail: str = "allow",
        cached: dict[str, Any] | None = None,
        fields: dict[str, Any] | None = None,
        scores: dict[str, float] | None = None,
        effort_hours: float = 100,
        scorer_delay: dict[str, float] | None = None,
        scorer_fail_times: dict[str, int] | None = None,
        objections: list[Objection] | None = None,
        supported: bool = True,
        scout_adds: int = 0,
    ) -> None:
        self.profile = profile or StudentProfile(
            user_id="u1",
            skills=["python"],
            hours_per_week=10,
            weeks_available=12,
            team_size=2,
            compute="laptop",
            goal="portfolio",
        )
        self.n_evidence, self.rail, self.cached = n_evidence, rail, cached
        self.fields = (
            fields
            if fields is not None
            else {"customer": "club organisers", "scope": "small", "platform": "web", "core_features": "rsvp"}
        )
        self.scores = scores or DEFAULT_SCORES
        self.effort = effort_hours
        self.delay = scorer_delay or {}
        self.fail_times = dict(scorer_fail_times or {})
        self.objections = objections or []
        self.supported = supported
        self.scout_adds = scout_adds
        self.events: list[dict[str, Any]] = []
        self.persisted: list[str] = []
        self.score_calls: list[str] = []
        self.saved: list[Verdict] = []
        self.cache: dict[str, Any] = {}
        self.versions = 1

    async def input_rail(self, text: str) -> dict[str, Any]:
        return {"decision": self.rail, "text": text, "reason": "test"}

    async def get_profile(self, user_id: str) -> StudentProfile:
        return self.profile

    async def create_idea(self, user_id: str, text: str, source: str = "own") -> dict[str, Any]:
        return {"id": "idea_1", "version": 1}

    async def add_version(self, idea_id: str, text: str, change: str | None) -> int:
        self.versions += 1
        return self.versions

    async def cache_get(self, key: str) -> dict[str, Any] | None:
        return self.cached

    async def cache_put(self, key: str, value: dict[str, Any]) -> None:
        self.cache[key] = value

    async def extract_fields(self, idea_text: str) -> dict[str, Any]:
        return dict(self.fields)

    async def search(self, query: str, k: int = 10, filters: dict[str, Any] | None = None) -> list[EvidenceItem]:
        return [ev(i) for i in range(self.n_evidence)]

    async def scout(self, query: str, run_id: str) -> dict[str, Any]:
        self.n_evidence += self.scout_adds
        return {"added": self.scout_adds}

    async def score(self, scorer: str, payload: dict[str, Any], run_id: str) -> list[DimensionScore]:
        self.score_calls.append(scorer)
        if self.fail_times.get(scorer, 0) > 0:
            self.fail_times[scorer] -= 1
            await asyncio.sleep(10)  # forces a timeout
        await asyncio.sleep(self.delay.get(scorer, 0))
        ids = [e["evidence_id"] for e in payload["evidence"]][:2]
        out = []
        for d in DIMS[scorer]:
            extra: dict[str, Any] = {}
            if d == "feasibility":
                extra["effort_hours"] = self.effort
            out.append(
                DimensionScore(
                    dimension=d,
                    score=self.scores[d],
                    confidence=0.8,
                    evidence_ids=ids,  # type: ignore[arg-type]
                    reason=f"{d} reason",
                    rubric_version=f"{d}@v1",
                    model="fake",
                    extra=extra,
                )
            )
        return out

    async def verdict(self, payload: dict[str, Any]) -> Verdict:
        return ENGINE.decide(VerdictRequest.model_validate(payload), CFG)

    async def whatif(self, payload: dict[str, Any]) -> Verdict:
        return ENGINE.whatif(WhatIfRequest.model_validate(payload), CFG)

    async def skeptic(self, payload: dict[str, Any]) -> list[Objection]:
        return list(self.objections)

    async def check_claims(self, claims: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return [{"text": c["text"], "supported": self.supported, "reason": "fake"} for c in claims]

    async def suggest_change(self, payload: dict[str, Any]) -> str:
        return f"Concrete: {payload['change']}"

    async def save_verdict(self, v: Verdict) -> None:
        self.saved.append(v)

    async def persist_run(self, run_id: str, state: str, context: dict[str, Any]) -> None:
        self.persisted.append(state)

    async def publish(self, run_id: str, event: dict[str, Any]) -> None:
        self.events.append(event)

    # discover
    async def niches(self, profile: StudentProfile, niche: str | None) -> list[dict[str, Any]]:
        return [
            {
                "id": "n1",
                "name": "Campus events",
                "status": "rising",
                "size": 40,
                "trend_slope": 0.1,
                "keywords": ["events"],
            },
            {
                "id": "n2",
                "name": "Crypto trading bots",
                "status": "saturated",
                "size": 300,
                "trend_slope": 0.0,
                "keywords": ["crypto"],
            },
        ]

    async def gaps(self, niche_id: str) -> list[dict[str, Any]]:
        return [
            {
                "id": f"gap_{niche_id}",
                "niche_id": niche_id,
                "description": "RSVP tracking is painful",
                "evidence_ids": ["card_0001#c0"],
            }
        ]

    async def ideate(self, payload: dict[str, Any]) -> list[dict[str, Any]]:
        return payload.get("_ideas") or [
            {
                "title": f"Idea {i}",
                "one_liner": f"one liner {i}",
                "problem": "p",
                "customer": "c",
                "niche_id": "n1",
                "gap_evidence_ids": ["card_0001#c0"],
                "source": "generated",
            }
            for i in range(payload.get("count", 3))
        ]

    async def gap_analyse(self, idea: dict[str, Any]) -> dict[str, Any]:
        return {**idea, "complaints": ["slow"], "extra_evidence_ids": ["card_0002#c0"]}
