"""M3 Orchestrator API: starts Validate/Discover machines, resumes them on answers/approvals, runs what-if and
challenge. Machines live in memory while active; their state + context are persisted to M2 after every transition."""

from __future__ import annotations

import asyncio
import os
import uuid
from typing import Any

import httpx
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from ivcommon.config import get_settings
from ivcommon.health import health_router
from ivcommon.http import internal_headers
from ivcommon.metrics import APPROVALS, metrics_router
from ivcommon.schemas.core import EvidenceItem

from .machines.discover import DiscoverContext, DiscoverMachine, DState
from .machines.validate import ValidateContext, ValidateMachine, VState
from .steps.agents import SCORER_DIMS, HttpAgents
from .steps.budget_guard import load_budget_config

app = FastAPI(title="orchestrator (M3)")
app.include_router(health_router("orchestrator"))
app.include_router(metrics_router())

MACHINES: dict[str, ValidateMachine | DiscoverMachine] = {}
LAST_VALIDATE: dict[tuple[str, int], ValidateContext] = {}
TASKS: set[asyncio.Task[Any]] = set()
DIM_TO_SCORER = {d: s for s, dims in SCORER_DIMS.items() for d in dims}


def agents() -> HttpAgents:
    if getattr(app.state, "agents", None) is None:
        import redis.asyncio as aioredis

        app.state.agents = HttpAgents(redis=aioredis.from_url(os.environ.get("REDIS_URL", "redis://redis:6379/0")))
    return app.state.agents  # type: ignore[no-any-return]


class StartRun(BaseModel):
    kind: str = Field(pattern="^(validate|discover)$")
    user_id: str
    idea_text: str | None = Field(default=None, max_length=2000)
    idea_id: str | None = None
    niche: str | None = Field(default=None, max_length=200)
    count: int = Field(default=8, ge=1, le=10)
    run_id: str | None = None


class Answer(BaseModel):
    question_id: str
    answer: str = Field(max_length=500)
    skip: bool = False


class Approve(BaseModel):
    approval_id: str | None = None
    approve: bool


class WhatIfApply(BaseModel):
    user_id: str
    from_version: int
    option_index: int | None = None
    change_text: str | None = Field(default=None, max_length=500)


class Challenge(BaseModel):
    user_id: str
    version: int
    dimension: str
    claim_text: str = Field(max_length=1000)
    evidence_ids: list[str]


async def _create_run_row(
    run_id: str, user_id: str, kind: str, budget: float, idea_id: str | None = None, version: int | None = None
) -> None:
    s = get_settings()
    async with httpx.AsyncClient(timeout=10) as c:
        r = await c.post(
            f"{s.profile_url}/runs",
            headers=internal_headers(run_id),
            json={
                "run_id": run_id,
                "user_id": user_id,
                "kind": kind,
                "budget_usd": budget,
                "idea_id": idea_id,
                "version": version,
            },
        )
        r.raise_for_status()


def _spawn(m: ValidateMachine | DiscoverMachine) -> None:
    async def go() -> None:
        await m.run()
        if isinstance(m, ValidateMachine) and m.done and m.context.verdict is not None and m.context.idea_id:
            LAST_VALIDATE[(m.context.idea_id, m.context.version)] = m.context

    t = asyncio.create_task(go())
    TASKS.add(t)
    t.add_done_callback(TASKS.discard)


def _budget(kind: str) -> float:
    return float(load_budget_config()["runs"][kind]["max_cost_usd"])


@app.post("/runs", status_code=202)
async def start_run(b: StartRun) -> dict[str, str]:
    run_id = b.run_id or f"run_{uuid.uuid4().hex[:10]}"
    await _create_run_row(run_id, b.user_id, b.kind, _budget(b.kind), b.idea_id)
    m: ValidateMachine | DiscoverMachine
    if b.kind == "validate":
        if not b.idea_text:
            raise HTTPException(422, "idea_text required")
        m = ValidateMachine(
            ValidateContext(run_id=run_id, user_id=b.user_id, idea_text=b.idea_text, idea_id=b.idea_id), agents()
        )
    else:
        m = DiscoverMachine(DiscoverContext(run_id=run_id, user_id=b.user_id, niche=b.niche, count=b.count), agents())
    MACHINES[run_id] = m
    _spawn(m)
    return {"run_id": run_id}


def _machine(run_id: str) -> ValidateMachine | DiscoverMachine:
    m = MACHINES.get(run_id)
    if m is None:
        raise HTTPException(404, "run not active in this orchestrator")
    return m


@app.get("/runs/{run_id}")
async def get_run(run_id: str) -> dict[str, Any]:
    m = _machine(run_id)
    c = m.context
    out: dict[str, Any] = {"run_id": run_id, "state": m.state.name, "history": m.history, "budget": m.guard.snapshot()}
    if isinstance(c, ValidateContext):
        out |= {
            "idea_id": c.idea_id,
            "version": c.version,
            "questions": c.questions,
            "pending_approval": c.pending_approval,
            "error": c.error,
            "cache_hit": c.cache_hit,
            "verdict": c.verdict.model_dump(mode="json") if c.verdict and m.done else None,
            "objections": c.objections,
        }
    else:
        out |= {
            "round": c.round,
            "dropped": c.dropped,
            "pending_approval": c.pending_approval,
            "error": c.error,
            "results": c.results if m.done else [],
        }
    return out


@app.post("/runs/{run_id}/answer")
async def answer(run_id: str, b: Answer) -> dict[str, Any]:
    m = _machine(run_id)
    if not isinstance(m, ValidateMachine) or m.state != VState.WAITING_ANSWER:
        raise HTTPException(409, "run is not waiting for an answer")
    complete = True if b.skip else m.answer(b.question_id, b.answer)
    if b.skip:
        m.proceed_with_assumptions()
        _spawn(m)
    elif complete:
        m.resume_to(VState.EVIDENCE)
        _spawn(m)
    return {"accepted": True, "resumed": complete}


@app.post("/runs/{run_id}/approve")
async def approve(run_id: str, b: Approve) -> dict[str, Any]:
    m = _machine(run_id)
    if m.state not in (VState.WAITING_APPROVAL, DState.WAITING_APPROVAL):
        raise HTTPException(409, "run is not waiting for approval")
    APPROVALS.labels("approved" if b.approve else "declined").inc()
    await m.approve(b.approve)
    _spawn(m)
    return {"accepted": True}


def _previous(idea_id: str, version: int) -> ValidateContext:
    prev = LAST_VALIDATE.get((idea_id, version))
    if prev is None:
        raise HTTPException(409, "no finished validate run for this idea version in this orchestrator; re-validate")
    return prev


@app.post("/ideas/{idea_id}/whatif", status_code=202)
async def whatif_apply(idea_id: str, b: WhatIfApply) -> dict[str, Any]:
    prev = _previous(idea_id, b.from_version)
    assert prev.verdict is not None
    dim: str | None = None
    if b.option_index is not None:
        opts = prev.verdict.what_would_make_go
        if not 0 <= b.option_index < len(opts):
            raise HTTPException(422, "option_index out of range")
        change, dim = opts[b.option_index].change, opts[b.option_index].dimension
    elif b.change_text:
        change = b.change_text
    else:
        raise HTTPException(422, "option_index or change_text required")
    new_text = f"{prev.idea_text}\nChange applied: {change}"
    a = agents()
    version = await a.add_version(idea_id, new_text, change)
    run_id = f"run_{uuid.uuid4().hex[:10]}"
    await _create_run_row(run_id, b.user_id, "whatif", _budget("whatif"), idea_id, version)
    affected = DIM_TO_SCORER.get(dim) if dim else None
    texts = {s: prev.idea_text for s in SCORER_DIMS if affected and s != affected}
    ctx = ValidateContext(
        run_id=run_id,
        user_id=b.user_id,
        kind="whatif",
        idea_text=new_text,
        idea_id=idea_id,
        version=version,
        change_applied=change,
        evidence=prev.evidence,
        n_sources=prev.n_sources,
        n_platforms=prev.n_platforms,
        prev_scores=prev.scores,
        prev_score_hashes=prev.score_hashes,
        scorer_texts=texts,
    )
    m = ValidateMachine(ctx, a)
    MACHINES[run_id] = m
    _spawn(m)
    return {"run_id": run_id, "version": version, "change": change}


@app.post("/ideas/{idea_id}/challenge")
async def challenge(idea_id: str, b: Challenge) -> dict[str, Any]:
    """U8: the critic re-checks the claim; unsupported -> removed and that one scorer re-runs without it."""
    prev = _previous(idea_id, b.version)
    a = agents()
    check = (await a.check_claims([{"text": b.claim_text, "evidence_ids": b.evidence_ids}]))[0]
    turn: dict[str, Any] = {
        "type": "challenge",
        "dimension": b.dimension,
        "claim": b.claim_text,
        "evidence_ids": b.evidence_ids,
        "check": check,
    }
    if check["supported"]:
        turn["result"] = "defended"
        await _conversation(idea_id, turn)
        ev = [e.model_dump(mode="json") for e in prev.evidence if e.evidence_id in set(b.evidence_ids)]
        return {"result": "defended", "check": check, "evidence": ev}
    scorer = DIM_TO_SCORER.get(b.dimension)
    if scorer is None:
        raise HTTPException(422, "unknown dimension")
    removed = set(b.evidence_ids)
    evidence: list[EvidenceItem] = [e for e in prev.evidence if e.evidence_id not in removed]
    payload = {
        "idea": {"text": prev.idea_text},
        "evidence": [e.model_dump(mode="json") for e in evidence],
        "profile": prev.profile.model_dump() if prev.profile else None,
    }
    new_scores = await a.score(scorer, payload, f"challenge-{idea_id}")
    by_dim = {s.dimension: s for s in new_scores}
    scores = [by_dim.get(s.dimension, s) for s in prev.scores]
    vreq = {
        "idea_id": idea_id,
        "version": b.version,
        "run_id": f"challenge-{idea_id}-{b.version}",
        "scores": [s.model_dump(mode="json") for s in scores],
        "profile": prev.profile.model_dump() if prev.profile else None,
        "n_sources": len({e.card_id for e in evidence}),
        "n_platforms": len({e.source for e in evidence}),
    }
    verdict = await a.verdict(vreq)
    await a.save_verdict(verdict)
    prev.scores, prev.verdict = scores, verdict
    turn |= {"result": "removed", "new_verdict": verdict.verdict, "new_score": verdict.score}
    await _conversation(idea_id, turn)
    return {"result": "removed", "check": check, "verdict": verdict.model_dump(mode="json")}


async def _conversation(idea_id: str, turn: dict[str, Any]) -> None:
    s = get_settings()
    try:
        async with httpx.AsyncClient(timeout=5) as c:
            await c.post(f"{s.profile_url}/ideas/{idea_id}/conversation", json=turn, headers=internal_headers())
    except httpx.HTTPError:
        pass
