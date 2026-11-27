"""Cache key builder (one place) + Redis cache access. Keys include profile and rubric versions (R-M2)."""

from __future__ import annotations

import json
from typing import Any

from ivcommon.cachekeys import KINDS, cache_key, normalise_text  # noqa: F401  (re-exported)

TTL = {"verdict": 7 * 86400, "retrieval": 86400, "score": 7 * 86400}


class Cache:
    def __init__(self, redis: Any) -> None:
        self.r = redis

    async def get(self, key: str) -> dict[str, Any] | None:
        raw = await self.r.get(key)
        if raw is None:
            return None
        data = json.loads(raw)
        if isinstance(data, dict):
            data["cache_hit"] = True  # cache hits are visible (R-M2)
        return data

    async def put(self, key: str, value: Any, ttl: int | None = None) -> None:
        kind = key.split(":", 1)[0]
        await self.r.set(key, json.dumps(value, default=str), ex=ttl or TTL.get(kind, 86400))
