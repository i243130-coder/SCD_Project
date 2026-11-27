"""HTTP routes. Never touch the DB directly: they only call services."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy.ext.asyncio import AsyncSession

from ivcommon.metrics import CACHE_HITS, CACHE_MISSES
from ivcommon.schemas.core import StudentProfile, Verdict

from ..db import get_session
from ..services.cache import Cache
from ..services.core import AccountService, Conflict, IdeaService, NotFound, ProfileService, RunService

router = APIRouter()


class Credentials(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=200)


class IdeaCreate(BaseModel):
    user_id: str
    title: str = ""
    text: str = Field(min_length=1, max_length=2000)
    source: str = "own"


class VersionCreate(BaseModel):
    text: str = Field(min_length=1, max_length=2000)
    change_applied: str | None = None


class RunCreate(BaseModel):
    user_id: str
    kind: str
    budget_usd: float = 0.05
    idea_id: str | None = None
    version: int | None = None
    run_id: str | None = None


class ApprovalCreate(BaseModel):
    run_id: str
    action: str
    estimated_cost: float


class ApprovalDecision(BaseModel):
    approve: bool


def _run_dict(r: Any) -> dict[str, Any]:
    return {
        k: getattr(r, k)
        for k in (
            "id",
            "user_id",
            "kind",
            "state",
            "idea_id",
            "version",
            "budget_usd",
            "spent_usd",
            "context",
            "created_at",
            "finished_at",
        )
    }


@router.post("/users", status_code=201)
async def create_user(c: Credentials, s: AsyncSession = Depends(get_session)) -> dict[str, str]:
    try:
        u = await AccountService(s).register(c.email, c.password)
    except Conflict as e:
        raise HTTPException(409, str(e)) from e
    return {"id": u.id, "email": u.email}


@router.post("/users/verify")
async def verify_user(c: Credentials, s: AsyncSession = Depends(get_session)) -> dict[str, str]:
    u = await AccountService(s).verify(c.email, c.password)
    if u is None:
        raise HTTPException(401, "invalid credentials")
    return {"id": u.id, "email": u.email}


@router.get("/profiles/{uid}", response_model=StudentProfile)
async def get_profile(uid: str, s: AsyncSession = Depends(get_session)) -> StudentProfile:
    p = await ProfileService(s).get(uid)
    if p is None:
        raise HTTPException(404, "no profile yet")
    return p


@router.put("/profiles/{uid}", response_model=StudentProfile)
async def put_profile(uid: str, p: StudentProfile, s: AsyncSession = Depends(get_session)) -> StudentProfile:
    return await ProfileService(s).upsert(uid, p.model_copy(update={"user_id": uid}))


@router.post("/ideas", status_code=201)
async def create_idea(b: IdeaCreate, s: AsyncSession = Depends(get_session)) -> dict[str, Any]:
    idea, v = await IdeaService(s).create(b.user_id, b.title, b.text, b.source)
    return {"id": idea.id, "version": v.version, "title": idea.title}


@router.get("/ideas")
async def list_ideas(user_id: str, s: AsyncSession = Depends(get_session)) -> list[dict[str, Any]]:
    return await IdeaService(s).list_for_user(user_id)


@router.get("/ideas/{idea_id}/versions")
async def versions(idea_id: str, s: AsyncSession = Depends(get_session)) -> list[dict[str, Any]]:
    return await IdeaService(s).versions(idea_id)


@router.post("/ideas/{idea_id}/versions", status_code=201)
async def add_version(idea_id: str, b: VersionCreate, s: AsyncSession = Depends(get_session)) -> dict[str, Any]:
    try:
        v = await IdeaService(s).add_version(idea_id, b.text, b.change_applied)
    except NotFound as e:
        raise HTTPException(404, "idea not found") from e
    return {"idea_id": idea_id, "version": v.version}


@router.post("/ideas/{idea_id}/conversation")
async def add_turn(idea_id: str, turn: dict[str, Any], s: AsyncSession = Depends(get_session)) -> dict[str, str]:
    await IdeaService(s).add_turn(idea_id, turn)
    return {"status": "ok"}


@router.post("/verdicts", status_code=201)
async def save_verdict(v: Verdict, s: AsyncSession = Depends(get_session)) -> dict[str, int]:
    return {"id": await IdeaService(s).save_verdict(v)}


@router.get("/verdicts/{idea_id}/{version}")
async def get_verdict(idea_id: str, version: int, s: AsyncSession = Depends(get_session)) -> dict[str, Any]:
    v = await IdeaService(s).verdict(idea_id, version)
    if v is None:
        raise HTTPException(404, "no verdict")
    return v


@router.post("/runs", status_code=201)
async def create_run(b: RunCreate, s: AsyncSession = Depends(get_session)) -> dict[str, Any]:
    r = await RunService(s).create(b.user_id, b.kind, b.budget_usd, b.idea_id, b.version, b.run_id)
    return _run_dict(r)


@router.get("/runs/{rid}")
async def get_run(rid: str, s: AsyncSession = Depends(get_session)) -> dict[str, Any]:
    r = await RunService(s).get(rid)
    if r is None:
        raise HTTPException(404, "run not found")
    return _run_dict(r)


@router.patch("/runs/{rid}")
async def patch_run(rid: str, fields: dict[str, Any], s: AsyncSession = Depends(get_session)) -> dict[str, Any]:
    allowed = {k: v for k, v in fields.items() if k in ("state", "spent_usd", "context", "idea_id", "version")}
    try:
        return _run_dict(await RunService(s).update(rid, allowed))
    except NotFound as e:
        raise HTTPException(404, "run not found") from e


@router.post("/approvals", status_code=201)
async def create_approval(b: ApprovalCreate, s: AsyncSession = Depends(get_session)) -> dict[str, Any]:
    a = await RunService(s).request_approval(b.run_id, b.action, b.estimated_cost)
    return {"id": a.id, "decision": a.decision}


@router.post("/approvals/{aid}")
async def decide_approval(aid: str, b: ApprovalDecision, s: AsyncSession = Depends(get_session)) -> dict[str, Any]:
    try:
        a = await RunService(s).decide_approval(aid, b.approve)
    except NotFound as e:
        raise HTTPException(404, "approval not found") from e
    return {"id": a.id, "decision": a.decision}


@router.get("/cache/{key:path}")
async def cache_get(key: str, request: Request) -> dict[str, Any]:
    v = await Cache(request.app.state.redis).get(key)
    kind = key.split(":", 1)[0]
    if v is None:
        CACHE_MISSES.labels(kind).inc()
        raise HTTPException(404, "miss")
    CACHE_HITS.labels(kind).inc()
    return v


@router.put("/cache/{key:path}")
async def cache_put(key: str, value: dict[str, Any], request: Request) -> dict[str, str]:
    await Cache(request.app.state.redis).put(key, value)
    return {"status": "stored"}
