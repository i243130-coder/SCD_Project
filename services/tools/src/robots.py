"""robots.txt check with a 24 h cache per domain (urllib.robotparser)."""

from __future__ import annotations

import time
from collections.abc import Awaitable, Callable
from urllib import robotparser
from urllib.parse import urlparse

TTL_S = 24 * 3600
Fetcher = Callable[[str], Awaitable[tuple[int, str]]]


class RobotsCache:
    def __init__(self, fetcher: Fetcher, user_agent: str, ttl_s: int = TTL_S) -> None:
        self.fetcher = fetcher
        self.ua = user_agent
        self.ttl = ttl_s
        self._cache: dict[str, tuple[float, robotparser.RobotFileParser]] = {}

    async def allowed(self, url: str) -> bool:
        p = urlparse(url)
        base = f"{p.scheme}://{p.netloc}"
        hit = self._cache.get(base)
        if hit is None or time.monotonic() - hit[0] > self.ttl:
            rp = robotparser.RobotFileParser()
            try:
                status, text = await self.fetcher(base + "/robots.txt")
            except Exception:
                status, text = 599, ""
            if status in (401, 403):
                rp.disallow_all = True  # type: ignore[attr-defined]
            elif status >= 400:
                rp.allow_all = True  # type: ignore[attr-defined]  # no robots.txt -> allowed (standard behaviour)
            else:
                rp.parse(text.splitlines())
            self._cache[base] = (time.monotonic(), rp)
            hit = self._cache[base]
        return hit[1].can_fetch(self.ua, url)
