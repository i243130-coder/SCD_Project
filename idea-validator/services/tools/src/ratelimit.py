"""Per-domain token bucket stored in Redis (works with redis.asyncio or fakeredis)."""

from __future__ import annotations

import time
from typing import Any


class TokenBucket:
    def __init__(self, redis: Any, rate_per_s: float, burst: int, prefix: str = "ratelimit:domain") -> None:
        self.r = redis
        self.rate = rate_per_s
        self.burst = burst
        self.prefix = prefix

    async def acquire(self, key: str, now: float | None = None) -> bool:
        now = time.time() if now is None else now
        k = f"{self.prefix}:{key}"
        data = await self.r.hgetall(k)
        tokens = float(data.get(b"tokens", data.get("tokens", self.burst)))
        ts = float(data.get(b"ts", data.get("ts", now)))
        tokens = min(self.burst, tokens + (now - ts) * self.rate)
        ok = tokens >= 1
        if ok:
            tokens -= 1
        await self.r.hset(k, mapping={"tokens": tokens, "ts": now})
        await self.r.expire(k, 3600)
        return ok
