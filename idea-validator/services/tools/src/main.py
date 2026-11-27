"""M5 Tool Layer: the single exit to the internet. POST /fetch.

allow-list -> page budget (per X-Run-Id) -> robots.txt -> cache -> rate limit -> fetch -> sanitise.
"""

from __future__ import annotations

import json
import os
from typing import Any

import httpx
from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel

from ivcommon.health import health_router
from ivcommon.metrics import FETCH_BLOCKED, INJECTIONS, metrics_router

from .allowlist import is_allowed
from .connectors import headers_for
from .ratelimit import TokenBucket
from .robots import RobotsCache
from .sanitiser import sanitise

USER_AGENT = os.environ.get("USER_AGENT", "IdeaValidatorStudentProject/1.0")
CACHE_TTL_S = int(os.environ.get("FETCH_CACHE_TTL_S", "21600"))
MAX_PAGES = int(os.environ.get("BUDGET_MAX_PAGES", "30"))
RATE = float(os.environ.get("DOMAIN_RATE_PER_S", "1.0"))
BURST = int(os.environ.get("DOMAIN_BURST", "5"))


class FetchRequest(BaseModel):
    url: str
    connector: str = "generic"
    params: dict[str, Any] = {}
    method: str = "GET"
    json_body: dict[str, Any] | None = None


class FetchResponse(BaseModel):
    status: int
    content: str
    injection_flags: list[str] = []
    from_cache: bool = False
    content_type: str = ""


app = FastAPI(title="tools (M5)")


def _redis() -> Any:
    if getattr(app.state, "redis", None) is None:
        import redis.asyncio as aioredis

        app.state.redis = aioredis.from_url(os.environ.get("REDIS_URL", "redis://redis:6379/0"))
    return app.state.redis


def _http() -> httpx.AsyncClient:
    if getattr(app.state, "http", None) is None:
        app.state.http = httpx.AsyncClient(timeout=10, follow_redirects=False)
    return app.state.http


async def _raw_get(url: str) -> tuple[int, str]:
    r = await _http().get(url, headers={"User-Agent": USER_AGENT})
    return r.status_code, r.text


def _robots() -> RobotsCache:
    if getattr(app.state, "robots", None) is None:
        app.state.robots = RobotsCache(_raw_get, USER_AGENT)
    return app.state.robots


async def _redis_ok() -> bool:
    return bool(await _redis().ping())


app.include_router(health_router("tools", {"redis": _redis_ok}))
app.include_router(metrics_router())


def _block(reason: str, detail: str) -> HTTPException:
    FETCH_BLOCKED.labels(reason).inc()
    return HTTPException(403, detail={"blocked": reason, "detail": detail})


@app.post("/fetch", response_model=FetchResponse)
async def fetch(req: FetchRequest, x_run_id: str | None = Header(default=None)) -> FetchResponse:
    if not is_allowed(req.url):
        raise _block("allowlist", f"domain not allow-listed: {req.url}")
    r = _redis()
    if x_run_id:
        pages = await r.incr(f"pages:{x_run_id}")
        await r.expire(f"pages:{x_run_id}", 86400)
        if pages > MAX_PAGES:
            raise _block("budget", f"page budget {MAX_PAGES} exceeded for run {x_run_id}")
    if not await _robots().allowed(req.url):
        raise _block("robots", f"robots.txt disallows {req.url}")

    cache_key = "fetchcache:" + json.dumps([req.method, req.url, req.params, req.json_body], sort_keys=True)
    cached = await r.get(cache_key)
    if cached:
        data = json.loads(cached)
        return FetchResponse(**data, from_cache=True)

    host = httpx.URL(req.url).host
    if not await TokenBucket(r, RATE, BURST).acquire(host):
        raise HTTPException(429, detail={"rate_limited": host}, headers={"Retry-After": "1"})

    try:
        resp = await _http().request(
            req.method,
            req.url,
            params=req.params or None,
            json=req.json_body,
            headers=headers_for(req.connector, USER_AGENT),
        )
    except httpx.TimeoutException as e:
        raise HTTPException(504, "upstream timeout") from e
    except httpx.TransportError as e:
        raise HTTPException(502, f"upstream error: {e.__class__.__name__}") from e

    ctype = resp.headers.get("content-type", "")
    clean = sanitise(resp.text, is_html="html" in ctype)
    if clean.flagged:
        INJECTIONS.labels("tools").inc(len(clean.injection_flags))
    out = FetchResponse(
        status=resp.status_code, content=clean.text, injection_flags=clean.injection_flags, content_type=ctype
    )
    if resp.status_code == 200:
        await r.set(cache_key, out.model_dump_json(exclude={"from_cache"}), ex=CACHE_TTL_S)
    return out


@app.post("/sanitise")
async def sanitise_endpoint(body: dict[str, str]) -> dict[str, Any]:
    res = sanitise(body.get("text", ""))
    return {"text": res.text, "injection_flags": res.injection_flags}
