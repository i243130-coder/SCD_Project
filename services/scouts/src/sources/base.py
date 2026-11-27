"""Source base: every request goes through M5 /fetch (scouts have no internet egress). Per-source rate limit,
back-off on 429/5xx, circuit breaker after N consecutive failures (source marked `degraded`)."""

from __future__ import annotations

import asyncio
import json
import time
from dataclasses import dataclass, field
from typing import Any

import httpx

from ivcommon.config import get_settings


@dataclass
class RawItem:
    source: str
    external_id: str
    url: str
    title: str
    text: str
    published_at: str | None = None
    extra: dict[str, Any] = field(default_factory=dict)


class SourceDown(Exception):
    pass


class Source:
    name = "base"
    connector = "generic"
    rate_per_s = 1.0
    max_failures = 3

    def __init__(
        self,
        client: httpx.AsyncClient | None = None,
        tools_url: str | None = None,
        run_id: str | None = None,
        sleep: Any = asyncio.sleep,
    ) -> None:
        self.c = client or httpx.AsyncClient(timeout=20)
        self.tools = tools_url or get_settings().tools_url
        self.run_id = run_id
        self.failures = 0
        self.degraded = False
        self._last = 0.0
        self._sleep = sleep

    async def fetch(
        self,
        url: str,
        params: dict[str, Any] | None = None,
        method: str = "GET",
        json_body: dict[str, Any] | None = None,
    ) -> Any:
        if self.degraded:
            raise SourceDown(self.name)
        wait = 1 / self.rate_per_s - (time.monotonic() - self._last)
        if wait > 0:
            await self._sleep(wait)
        for attempt in range(4):
            self._last = time.monotonic()
            headers = {"X-Run-Id": self.run_id} if self.run_id else {}
            try:
                r = await self.c.post(
                    f"{self.tools}/fetch",
                    headers=headers,
                    json={
                        "url": url,
                        "connector": self.connector,
                        "params": params or {},
                        "method": method,
                        "json_body": json_body,
                    },
                )
            except httpx.HTTPError:
                r = None
            if r is not None and r.status_code == 200:
                body = r.json()
                if body["status"] == 200:
                    self.failures = 0
                    return json.loads(body["content"]) if body["content"].strip()[:1] in "[{" else body["content"]
                status = body["status"]
            else:
                status = r.status_code if r is not None else 599
            if status in (429, 500, 502, 503, 504, 599):
                retry_after = float(r.headers.get("Retry-After", 0)) if r is not None else 0
                await self._sleep(max(retry_after, 0.5 * 2**attempt))
                continue
            break
        self.failures += 1
        if self.failures >= self.max_failures:
            self.degraded = True
        raise SourceDown(f"{self.name}: status {status}")

    async def fetch_since(
        self, cursor: str | None, query: str | None = None, max_pages: int = 5
    ) -> tuple[list[RawItem], str | None]:
        raise NotImplementedError
