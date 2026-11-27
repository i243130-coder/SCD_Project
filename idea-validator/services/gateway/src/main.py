"""M1 API Gateway: the only public entrance. JWT auth, rate limits, input validation, input rail, proxy to M2/M3,
SSE live events from Redis `run:{id}` (with a 15 s heartbeat)."""

from __future__ import annotations

import asyncio
import json
import os
import time
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import jwt
from fastapi import Depends, FastAPI, HTTPException, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, EmailStr, Field

from ivcommon.config import get_settings
from ivcommon.health import health_router
from ivcommon.http import internal_headers
from ivcommon.metrics import REQUESTS, metrics_router
from ivcommon.schemas.core import DIMENSIONS, StudentProfile

S = get_settings()
JWT_ALG = "HS256"
JWT_TTL_H = 12
USER_RPM = int(os.environ.get("RATE_USER_PER_MIN", "60"))
AUTH_IP_RPM = int(os.environ.get("RATE_AUTH_IP_PER_MIN", "20"))
MAX_CONCURRENT_RUNS = int(os.environ.get("MAX_CONCURRENT_RUNS", "5"))
HEARTBEAT_S = float(os.environ.get("SSE_HEARTBEAT_S", "15"))
PUBLIC = ("/auth/", "/health", "/ready", "/metrics", "/docs", "/openapi.json")

app = FastAPI(title="gateway (M1)")
if S.ui_origin:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[o.strip() for o in S.ui_origin.split(",")],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )


def redis() -> Any:
    if getattr(app.state, "redis", None) is None:
        import redis.asyncio as aioredis

        app.state.redis = aioredis.from_url(S.redis_url)
    return app.state.redis


def http() -> httpx.AsyncClient:
    if getattr(app.state, "http", None) is None:
        app.state.http = httpx.AsyncClient(timeout=30)
    return app.state.http  # type: ignore[no-any-return]


async def _redis_ok() -> bool:
    return bool(await redis().ping())


async def _ready_extra() -> bool:
    return not S.bad_release  # rollout/rollback demo: a "bad release" never becomes ready


app.include_router(health_router("gateway", {"redis": _redis_ok, "release": _ready_extra}))
app.include_router(metrics_router())


# ------------------------------------------------------------------ rate limiting (Redis token bucket)
async def take_token(key: str, per_minute: int) -> tuple[bool, int]:
    r = redis()
    now = time.time()
    k = f"ratelimit:{key}"
    data = await r.hgetall(k)
    tokens = float(data.get(b"t", data.get("t", per_minute)))
    ts = float(data.get(b"ts", data.get("ts", now)))
    tokens = min(per_minute, tokens + (now - ts) * per_minute / 60)
    ok = tokens >= 1
    if ok:
        tokens -= 1
    await r.hset(k, mapping={"t": tokens, "ts": now})
    await r.expire(k, 120)
    retry = 0 if ok else int((1 - tokens) * 60 / per_minute) + 1
    return ok, retry


def _secret() -> str:
    if not S.jwt_secret:
        raise HTTPException(500, "JWT_SECRET not configured")
    return S.jwt_secret


def make_token(uid: str, email: str) -> str:
    exp = datetime.now(UTC) + timedelta(hours=JWT_TTL_H)
    return jwt.encode({"sub": uid, "email": email, "exp": exp}, _secret(), algorithm=JWT_ALG)


@app.middleware("http")
async def auth_and_limits(request: Request, call_next: Any) -> Response:
    path = request.url.path
    ip = request.client.host if request.client else "unknown"
    if request.method == "OPTIONS":
        return await call_next(request)  # type: ignore[no-any-return]
    if path.startswith("/auth/"):
        ok, retry = await take_token(f"ip:{ip}", AUTH_IP_RPM)
        if not ok:
            return JSONResponse({"detail": "rate limited"}, 429, headers={"Retry-After": str(retry)})
    elif not path.startswith(PUBLIC):
        header = request.headers.get("authorization", "")
        token = header.removeprefix("Bearer ").strip() or request.query_params.get("token", "")
        try:
            claims = jwt.decode(token, _secret(), algorithms=[JWT_ALG])
        except jwt.PyJWTError:
            return JSONResponse({"detail": "not authenticated"}, 401)
        request.state.user_id = claims["sub"]
        ok, retry = await take_token(f"user:{claims['sub']}", USER_RPM)
        if not ok:
            return JSONResponse({"detail": "rate limited"}, 429, headers={"Retry-After": str(retry)})
    resp: Response = await call_next(request)
    route = request.scope.get("route")
    REQUESTS.labels("gateway", getattr(route, "path", "other"), str(resp.status_code)).inc()
    return resp


def uid(request: Request) -> str:
    return str(request.state.user_id)


# ------------------------------------------------------------------ upstream helpers
async def upstream(method: str, url: str, **kw: Any) -> Any:
    try:
        r = await http().request(method, url, headers=internal_headers(), **kw)
    except httpx.HTTPError as e:
        raise HTTPException(502, f"upstream unavailable: {e.__class__.__name__}") from e
    if r.status_code >= 400:
        try:
            detail = r.json().get("detail", r.text)
        except ValueError:
            detail = r.text
        raise HTTPException(r.status_code, detail)
    return r.json()


async def input_rail(text: str) -> str:
    res = await upstream("POST", f"{S.critic_url}/input_rail", json={"text": text})
    if res["decision"] == "block":
        raise HTTPException(422, f"input rejected: {res['reason']}")
    return str(res["text"])


# ------------------------------------------------------------------ auth
class Credentials(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=200)


@app.post("/auth/register", status_code=201)
async def register(c: Credentials) -> dict[str, str]:
    u = await upstream("POST", f"{S.profile_url}/users", json=c.model_dump())
    return {"token": make_token(u["id"], u["email"]), "user_id": u["id"]}


@app.post("/auth/login")
async def login(c: Credentials) -> dict[str, str]:
    u = await upstream("POST", f"{S.profile_url}/users/verify", json=c.model_dump())
    return {"token": make_token(u["id"], u["email"]), "user_id": u["id"]}


# ------------------------------------------------------------------ profile
class ProfileIn(BaseModel):
    skills: list[str] = Field(max_length=40)
    hours_per_week: float = Field(ge=0, le=80)
    weeks_available: int = Field(ge=1, le=52)
    team_size: int = Field(ge=1, le=6)
    compute: str = Field(pattern="^(laptop|free_gpu|paid)$")
    goal: str = Field(pattern="^(startup|portfolio|course_project)$")
    interests: list[str] = Field(default=[], max_length=40)


@app.get("/profile")
async def get_profile(user_id: str = Depends(uid)) -> Any:
    return await upstream("GET", f"{S.profile_url}/profiles/{user_id}")


@app.put("/profile")
async def put_profile(p: ProfileIn, user_id: str = Depends(uid)) -> Any:
    body = StudentProfile(user_id=user_id, **p.model_dump()).model_dump()  # type: ignore[arg-type]
    return await upstream("PUT", f"{S.profile_url}/profiles/{user_id}", json=body)


# ------------------------------------------------------------------ runs
class DiscoverIn(BaseModel):
    niche: str | None = Field(default=None, max_length=200)
    count: int = Field(default=8, ge=1, le=10)


class ValidateIn(BaseModel):
    idea_text: str | None = Field(default=None, min_length=1, max_length=2000)
    idea_id: str | None = None


async def _check_concurrency(user_id: str) -> None:
    n = await redis().incr(f"active_runs:{user_id}")
    await redis().expire(f"active_runs:{user_id}", 600)
    if n > MAX_CONCURRENT_RUNS:
        await redis().decr(f"active_runs:{user_id}")
        raise HTTPException(429, "too many concurrent runs", headers={"Retry-After": "30"})


@app.post("/discover", status_code=202)
async def discover(b: DiscoverIn, user_id: str = Depends(uid)) -> Any:
    niche = await input_rail(b.niche) if b.niche else None
    await _check_concurrency(user_id)
    return await upstream(
        "POST",
        f"{S.orchestrator_url}/runs",
        json={"kind": "discover", "user_id": user_id, "niche": niche, "count": b.count},
    )


@app.post("/validate", status_code=202)
async def validate(b: ValidateIn, user_id: str = Depends(uid)) -> Any:
    text = b.idea_text
    if text is None and b.idea_id:
        versions = await upstream("GET", f"{S.profile_url}/ideas/{b.idea_id}/versions")
        if not versions:
            raise HTTPException(404, "idea not found")
        text = versions[-1]["text"]
    if not text:
        raise HTTPException(422, "idea_text or idea_id required")
    text = await input_rail(text)
    await _check_concurrency(user_id)
    return await upstream(
        "POST",
        f"{S.orchestrator_url}/runs",
        json={"kind": "validate", "user_id": user_id, "idea_text": text, "idea_id": b.idea_id},
    )


@app.get("/runs/{run_id}")
async def get_run(run_id: str, user_id: str = Depends(uid)) -> Any:
    row = await upstream("GET", f"{S.profile_url}/runs/{run_id}")
    if row["user_id"] != user_id:
        raise HTTPException(404, "run not found")
    try:
        live = await upstream("GET", f"{S.orchestrator_url}/runs/{run_id}")
    except HTTPException:
        live = {}
    return {**row, **live}


class AnswerIn(BaseModel):
    question_id: str = Field(max_length=60)
    answer: str = Field(default="", max_length=500)
    skip: bool = False


@app.post("/runs/{run_id}/answer")
async def answer(run_id: str, b: AnswerIn, user_id: str = Depends(uid)) -> Any:
    if b.answer:
        b.answer = await input_rail(b.answer)
    return await upstream("POST", f"{S.orchestrator_url}/runs/{run_id}/answer", json=b.model_dump())


class ApproveIn(BaseModel):
    approval_id: str | None = None
    approve: bool


@app.post("/runs/{run_id}/approve")
async def approve(run_id: str, b: ApproveIn, user_id: str = Depends(uid)) -> Any:
    return await upstream("POST", f"{S.orchestrator_url}/runs/{run_id}/approve", json=b.model_dump())


async def event_stream(
    run_id: str, request: Request | None = None, max_events: int | None = None
) -> AsyncIterator[str]:
    """History first (runlog list), then live pub/sub; heartbeat comments every HEARTBEAT_S seconds."""
    r = redis()
    pubsub = r.pubsub()
    await pubsub.subscribe(f"run:{run_id}")
    sent = 0
    try:
        for raw in await r.lrange(f"runlog:{run_id}", 0, -1):
            yield f"data: {raw.decode() if isinstance(raw, bytes) else raw}\n\n"
            sent += 1
            if max_events and sent >= max_events:
                return
        last_beat = time.monotonic()
        while True:
            if request is not None and await request.is_disconnected():
                return
            msg = await pubsub.get_message(ignore_subscribe_messages=True, timeout=1.0)
            if msg and msg.get("type") == "message":
                data = msg["data"].decode() if isinstance(msg["data"], bytes) else msg["data"]
                yield f"data: {data}\n\n"
                sent += 1
                if json.loads(data).get("type") == "result" and "child" not in json.loads(data).get("payload", {}):
                    return
                if max_events and sent >= max_events:
                    return
            if time.monotonic() - last_beat >= HEARTBEAT_S:
                yield ": heartbeat\n\n"
                last_beat = time.monotonic()
            await asyncio.sleep(0)
    finally:
        await pubsub.unsubscribe(f"run:{run_id}")
        await redis().decr(f"active_runs:{getattr(request.state, 'user_id', '') if request else ''}")


@app.get("/runs/{run_id}/events")
async def events(run_id: str, request: Request, user_id: str = Depends(uid)) -> StreamingResponse:
    return StreamingResponse(
        event_stream(run_id, request),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# ------------------------------------------------------------------ ideas, what-if, challenge, compare
class ChallengeIn(BaseModel):
    version: int = Field(ge=1)
    dimension: str = Field(pattern="^(" + "|".join(DIMENSIONS) + ")$")
    claim_text: str = Field(min_length=1, max_length=1000)
    evidence_ids: list[str] = Field(max_length=20)


class WhatIfIn(BaseModel):
    from_version: int = Field(ge=1)
    option_index: int | None = Field(default=None, ge=0, le=10)
    change_text: str | None = Field(default=None, max_length=500)


@app.post("/ideas/{idea_id}/challenge")
async def challenge(idea_id: str, b: ChallengeIn, user_id: str = Depends(uid)) -> Any:
    return await upstream(
        "POST", f"{S.orchestrator_url}/ideas/{idea_id}/challenge", json={**b.model_dump(), "user_id": user_id}
    )


@app.post("/ideas/{idea_id}/whatif", status_code=202)
async def whatif(idea_id: str, b: WhatIfIn, user_id: str = Depends(uid)) -> Any:
    if b.change_text:
        b.change_text = await input_rail(b.change_text)
    return await upstream(
        "POST", f"{S.orchestrator_url}/ideas/{idea_id}/whatif", json={**b.model_dump(), "user_id": user_id}
    )


@app.get("/ideas")
async def ideas(user_id: str = Depends(uid)) -> Any:
    return await upstream("GET", f"{S.profile_url}/ideas", params={"user_id": user_id})


@app.get("/ideas/{idea_id}/versions")
async def versions(idea_id: str, user_id: str = Depends(uid)) -> Any:
    return await upstream("GET", f"{S.profile_url}/ideas/{idea_id}/versions")


def _parse_ref(ref: str) -> tuple[str, int]:
    if "@" not in ref:
        raise HTTPException(422, "use idea_id@version")
    i, v = ref.rsplit("@", 1)
    try:
        return i, int(v.removeprefix("v"))
    except ValueError as e:
        raise HTTPException(422, "bad version") from e


@app.get("/compare")
async def compare(a: str, b: str, user_id: str = Depends(uid)) -> dict[str, Any]:
    va = await upstream("GET", f"{S.profile_url}/verdicts/{_parse_ref(a)[0]}/{_parse_ref(a)[1]}")
    vb = await upstream("GET", f"{S.profile_url}/verdicts/{_parse_ref(b)[0]}/{_parse_ref(b)[1]}")
    rows = []
    for d in DIMENSIONS:
        sa = next((s for s in va["scores"] if s["dimension"] == d), None)
        sb = next((s for s in vb["scores"] if s["dimension"] == d), None)
        rows.append(
            {
                "dimension": d,
                "a": sa and sa["score"],
                "a_conf": sa and sa["confidence"],
                "b": sb and sb["score"],
                "b_conf": sb and sb["confidence"],
            }
        )
    return {
        "a": {"ref": a, "verdict": va["verdict"], "score": va["score"], "stability": va["stability"]},
        "b": {"ref": b, "verdict": vb["verdict"], "score": vb["score"], "stability": vb["stability"]},
        "dimensions": rows,
    }
