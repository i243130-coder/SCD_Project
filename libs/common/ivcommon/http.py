"""httpx client with timeouts, retries and the internal headers."""

from __future__ import annotations

from typing import Any

import httpx
from tenacity import AsyncRetrying, retry_if_exception_type, stop_after_attempt, wait_exponential

from ivcommon.config import get_settings

RETRYABLE = (httpx.TimeoutException, httpx.TransportError)


def internal_headers(run_id: str | None = None) -> dict[str, str]:
    h = {"X-Internal-Token": get_settings().internal_token}
    if run_id:
        h["X-Run-Id"] = run_id
    return h


async def post_json(
    url: str,
    body: Any,
    *,
    run_id: str | None = None,
    timeout_s: float = 10.0,
    retries: int = 2,
    client: httpx.AsyncClient | None = None,
) -> Any:
    async def _do(c: httpx.AsyncClient) -> Any:
        async for attempt in AsyncRetrying(
            stop=stop_after_attempt(retries + 1),
            wait=wait_exponential(multiplier=0.2, max=2),
            retry=retry_if_exception_type(RETRYABLE),
            reraise=True,
        ):
            with attempt:
                r = await c.post(url, json=body, headers=internal_headers(run_id), timeout=timeout_s)
                r.raise_for_status()
                return r.json()

    if client is not None:
        return await _do(client)
    async with httpx.AsyncClient() as c:
        return await _do(c)


async def get_json(url: str, *, run_id: str | None = None, timeout_s: float = 10.0) -> Any:
    async with httpx.AsyncClient() as c:
        r = await c.get(url, headers=internal_headers(run_id), timeout=timeout_s)
        r.raise_for_status()
        return r.json()
