"""The orchestrator's view of the other modules. `HttpAgents` talks to the real services over HTTP;
tests pass a fake object with the same methods (duck-typed `Agents` protocol)."""

from __future__ import annotations

import json
from typing import Any, Protocol

import httpx

from ivcommon.config import get_settings
from ivcommon.http import internal_headers
from ivcommon.schemas.core import DimensionScore, EvidenceItem, Objection, StudentProfile, Verdict

SCORER_DIMS: dict[str, tuple[str, ...]] = {
    "demand": ("demand_pain",),
    "competition": ("competition", "differentiation"),
    "feasibility": ("feasibility", "learning"),
    "risk": ("risk",),
}
RUBRIC_VERSIONS = {d: f"{d}@v1" for dims in SCORER_DIMS.values() for d in dims}
RUBRIC_SET_VERSION = "r1"


class Agents(Protocol):
    async def input_rail(self, text: str) -> dict[str, Any]: ...
    async def get_profile(self, user_id: str) -> StudentProfile: ...
    async def create_idea(self, user_id: str, text: str, source: str = "own") -> dict[str, Any]: ...
    async def add_version(self, idea_id: str, text: str, change: str | None) -> int: ...
    async def cache_get(self, key: str) -> dict[str, Any] | None: ...
    async def cache_put(self, key: str, value: dict[str, Any]) -> None: ...
    async def extract_fields(self, idea_text: str) -> dict[str, Any]: ...
    async def search(self, query: str, k: int = 10, filters: dict[str, Any] | None = None) -> list[EvidenceItem]: ...
    async def scout(self, query: str, run_id: str) -> dict[str, Any]: ...
    async def score(self, scorer: str, payload: dict[str, Any], run_id: str) -> list[DimensionScore]: ...
    async def verdict(self, payload: dict[str, Any]) -> Verdict: ...
    async def whatif(self, payload: dict[str, Any]) -> Verdict: ...
    async def skeptic(self, payload: dict[str, Any]) -> list[Objection]: ...
    async def check_claims(self, claims: list[dict[str, Any]]) -> list[dict[str, Any]]: ...
    async def suggest_change(self, payload: dict[str, Any]) -> str: ...
    async def save_verdict(self, v: Verdict) -> None: ...
    async def persist_run(self, run_id: str, state: str, context: dict[str, Any]) -> None: ...
    async def publish(self, run_id: str, event: dict[str, Any]) -> None: ...
    # discover
    async def niches(self, profile: StudentProfile, niche: str | None) -> list[dict[str, Any]]: ...
    async def gaps(self, niche_id: str) -> list[dict[str, Any]]: ...
    async def ideate(self, payload: dict[str, Any]) -> list[dict[str, Any]]: ...
    async def gap_analyse(self, idea: dict[str, Any]) -> dict[str, Any]: ...


class HttpAgents:
    def __init__(self, redis: Any = None, client: httpx.AsyncClient | None = None) -> None:
        self.s = get_settings()
        self.redis = redis
        self.c = client or httpx.AsyncClient(timeout=30)

    async def _post(self, url: str, body: Any, run_id: str | None = None) -> Any:
        r = await self.c.post(url, json=body, headers=internal_headers(run_id))
        r.raise_for_status()
        return r.json()

    async def _get(self, url: str, **params: Any) -> Any:
        r = await self.c.get(url, params=params or None, headers=internal_headers())
        if r.status_code == 404:
            return None
        r.raise_for_status()
        return r.json()

    async def input_rail(self, text: str) -> dict[str, Any]:
        return await self._post(f"{self.s.critic_url}/input_rail", {"text": text})  # type: ignore[no-any-return]

    async def get_profile(self, user_id: str) -> StudentProfile:
        data = await self._get(f"{self.s.profile_url}/profiles/{user_id}")
        if data is None:
            raise ValueError("profile missing: save your profile first")
        return StudentProfile.model_validate(data)

    async def create_idea(self, user_id: str, text: str, source: str = "own") -> dict[str, Any]:
        return await self._post(
            f"{self.s.profile_url}/ideas",  # type: ignore[no-any-return]
            {"user_id": user_id, "text": text, "source": source},
        )

    async def add_version(self, idea_id: str, text: str, change: str | None) -> int:
        d = await self._post(f"{self.s.profile_url}/ideas/{idea_id}/versions", {"text": text, "change_applied": change})
        return int(d["version"])

    async def cache_get(self, key: str) -> dict[str, Any] | None:
        return await self._get(f"{self.s.profile_url}/cache/{key}")  # type: ignore[no-any-return]

    async def cache_put(self, key: str, value: dict[str, Any]) -> None:
        r = await self.c.put(f"{self.s.profile_url}/cache/{key}", json=value, headers=internal_headers())
        r.raise_for_status()

    async def extract_fields(self, idea_text: str) -> dict[str, Any]:
        return await self._post(f"{self.s.ideation_url}/extract", {"text": idea_text})  # type: ignore[no-any-return]

    async def search(self, query: str, k: int = 10, filters: dict[str, Any] | None = None) -> list[EvidenceItem]:
        d = await self._post(f"{self.s.kb_url}/search", {"query": query, "k": k, "filters": filters or {}})
        return [EvidenceItem.model_validate(e) for e in d["results"]]

    async def scout(self, query: str, run_id: str) -> dict[str, Any]:
        return await self._post(
            f"{self.s.orchestrator_url.replace('orchestrator', 'scouts')}/scout",  # type: ignore[no-any-return]
            {"source": "all", "query": query, "max_pages": 5},
            run_id,
        )

    async def score(self, scorer: str, payload: dict[str, Any], run_id: str) -> list[DimensionScore]:
        d = await self._post(f"{self.s.validators_url}/score/{scorer}", payload, run_id)
        return [DimensionScore.model_validate(x) for x in d]

    async def verdict(self, payload: dict[str, Any]) -> Verdict:
        return Verdict.model_validate(await self._post(f"{self.s.verdict_url}/verdict", payload))

    async def whatif(self, payload: dict[str, Any]) -> Verdict:
        return Verdict.model_validate(await self._post(f"{self.s.verdict_url}/whatif", payload))

    async def skeptic(self, payload: dict[str, Any]) -> list[Objection]:
        return [Objection.model_validate(o) for o in await self._post(f"{self.s.ideation_url}/skeptic", payload)]

    async def check_claims(self, claims: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return await self._post(f"{self.s.critic_url}/check", {"claims": claims})  # type: ignore[no-any-return]

    async def suggest_change(self, payload: dict[str, Any]) -> str:
        return str((await self._post(f"{self.s.ideation_url}/suggest_change", payload))["change"])

    async def save_verdict(self, v: Verdict) -> None:
        await self._post(f"{self.s.profile_url}/verdicts", v.model_dump(mode="json"))

    async def persist_run(self, run_id: str, state: str, context: dict[str, Any]) -> None:
        r = await self.c.patch(
            f"{self.s.profile_url}/runs/{run_id}",
            headers=internal_headers(run_id),
            json={"state": state, "context": context, "spent_usd": context.get("budget", {}).get("cost_usd", 0.0)},
        )
        r.raise_for_status()

    async def publish(self, run_id: str, event: dict[str, Any]) -> None:
        if self.redis is not None:
            payload = json.dumps(event, default=str)
            await self.redis.publish(f"run:{run_id}", payload)
            await self.redis.rpush(f"runlog:{run_id}", payload)  # replayable history for late SSE subscribers
            await self.redis.expire(f"runlog:{run_id}", 86400)

    async def niches(self, profile: StudentProfile, niche: str | None) -> list[dict[str, Any]]:
        return await self._get(f"{self.s.analyst_url}/niches") or []  # type: ignore[no-any-return]

    async def gaps(self, niche_id: str) -> list[dict[str, Any]]:
        return await self._get(f"{self.s.analyst_url}/gaps", niche=niche_id) or []  # type: ignore[no-any-return]

    async def ideate(self, payload: dict[str, Any]) -> list[dict[str, Any]]:
        return await self._post(f"{self.s.ideation_url}/generate", payload)  # type: ignore[no-any-return]

    async def gap_analyse(self, idea: dict[str, Any]) -> dict[str, Any]:
        return await self._post(f"{self.s.ideation_url}/gap_analyse", idea)  # type: ignore[no-any-return]
